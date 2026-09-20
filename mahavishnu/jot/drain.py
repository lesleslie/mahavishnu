"""Drain sub-plan (3): state machine, dispatch orchestration, retry, surfacing.

Single write path for all drain events. See spec §3.2, §4.2, §4.6, §6.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import time
from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

from oneiric.core.logging import get_logger

from mahavishnu.jot.errors import (
    JotDeferError,
    JotDispatchError,
    JotLogUnwritableError,
    JotRetryError,
    JotValidationError,
)
from mahavishnu.jot.events import JotEvent, Op, serialize
from mahavishnu.jot.fold import DispatchState, JotSummary  # re-export target
from mahavishnu.jot.hlc import get_node, hlc_now, read_tail_hlc
from mahavishnu.jot.paths import log_path, node_path

if TYPE_CHECKING:
    from collections.abc import Callable

log = get_logger(__name__)

# Re-export DispatchState (canonical location is fold.py to avoid cycle)
__all__ = [
    "DispatchResult",
    "DispatchState",
    "DrainPlan",
    "_append_event",
    "defer_jot",
    "delete_jot",
    "dispatch_jot",
    "drain_plan",
    "retry_dispatch",
]


# =============================================================================
# Per-op TypedDict schemas (spec §4.2 — exact values)
# =============================================================================


class DispatchCtx(TypedDict, total=False):
    workflow_id: str
    attempt: int
    pool_selector: str
    triggered_by: Literal["first", "auto", "manual"]
    dispatched_from: Literal["cli", "mcp", "slash"]
    started_at_ms: int


class DispatchDoneCtx(TypedDict, total=False):
    workflow_id: str
    summary: str
    commit_sha: str


class DispatchFailedCtx(TypedDict, total=False):
    workflow_id: str
    attempt: int
    error: str
    error_id: str
    retry_budget_exhausted: bool
    retry_after_seconds: int | None


class DeferCtx(TypedDict, total=False):
    until: int


class DeferExpiredCtx(TypedDict, total=False):
    defer_event_id: str | None


class DeleteCtx(TypedDict, total=False):
    reason: str | None


# Required keys per op. TypedDict total=False doesn't enforce required;
# we validate manually with a hard-fail list (spec §4.2 + R10 contract).
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "dispatch": ("workflow_id", "attempt", "pool_selector", "dispatched_from"),
    "dispatch_done": ("workflow_id", "summary"),
    "dispatch_failed": (
        "workflow_id",
        "attempt",
        "error",
        "error_id",
        "retry_budget_exhausted",
    ),
    "defer": ("until",),
    "defer_expired": (),
    "delete": (),
}

_INT_KEYS = ("attempt",)
_BOOL_KEYS = ("retry_budget_exhausted",)
_STR_KEYS = (
    "workflow_id",
    "summary",
    "commit_sha",
    "error",
    "error_id",
    "pool_selector",
    "dispatched_from",
    "triggered_by",
    "reason",
)
_LITERAL_KEYS = {
    "triggered_by": ("first", "auto", "manual"),
    "dispatched_from": ("cli", "mcp", "slash"),
}

# Keys that _append_event auto-fills before _validate_ctx runs.
# MUST be in the per-op whitelist or the unknown-key check (below)
# rejects auto-filled values at runtime, breaking dispatch.
_AUTO_FILLED_KEYS: tuple[str, ...] = ("started_at_ms",)

# Per-op whitelist of known keys (required ∪ typed ∪ auto-filled).
# Computed once at module import; _validate_ctx looks up the op's
# whitelist and rejects any ctx key not in it.
_KNOWN_KEYS_PER_OP: dict[str, frozenset[str]] = {
    op: frozenset(_REQUIRED_KEYS[op]).union(
        _INT_KEYS,
        _BOOL_KEYS,
        _STR_KEYS,
        _AUTO_FILLED_KEYS,
        _LITERAL_KEYS.keys(),
    )
    for op in _REQUIRED_KEYS
}


# =============================================================================
# Helpers
# =============================================================================


def _now_ms() -> int:
    """Wall-clock in epoch ms. Project-utility; replaceable via clock fixture."""
    return int(time.time() * 1000)


# =============================================================================
# Filter helpers + retry budget (spec §5.2, §6.3.1)
# =============================================================================


def _is_surface_eligible(jot: JotSummary, now_ms: int) -> bool:
    """Used by ambient surfacing. See spec §5.2.

    Surfaced candidates: open + not-deleted + not-deferred-or-expired
    + (not-dispatched OR failed-dispatch).

    IN_FLIGHT is excluded because the user already sees these in /jot vitals.
    FAILED is included because it requires user action (manual retry).
    """
    return (
        jot.status == "open"
        and not jot.deleted
        and (jot.deferred_until is None or jot.deferred_until <= now_ms)
        and (jot.dispatch_state is None or jot.dispatch_state == DispatchState.FAILED)
    )


def _is_drain_eligible(jot: JotSummary, now_ms: int) -> bool:
    """Used by drain_plan to build the bulk-action candidates list.

    Differs from _is_surface_eligible by INCLUDING IN_FLIGHT and SUCCEEDED
    jots. drain_plan applies a SECOND filter to drop IN_FLIGHT (since the
    action "dispatch" is a no-op on an IN_FLIGHT jot). The CLI flag
    --include-in-flight overrides the second filter.
    """
    return (
        jot.status == "open"
        and not jot.deleted
        and (jot.deferred_until is None or jot.deferred_until <= now_ms)
    )


MAX_AUTO_ATTEMPTS: int = 2  # total (1 initial + 1 auto-retry)


def _should_exhaust_retry_budget(jot: JotSummary) -> bool:
    """Return True iff this dispatch failure should NOT auto-retry.

    Policy: a failed dispatch on the LAST configured attempt exhausts the
    budget. With MAX_AUTO_ATTEMPTS=2, attempt 2 failure → exhausted (True);
    attempt 1 failure → budget remaining (False, auto-retry fires).

    Edge case: malformed ctx where current_attempt is 0 is treated as
    attempt=1 (fail-safe — retry-once is safer than terminal FAILED).
    """
    return max(jot.current_attempt, 1) >= MAX_AUTO_ATTEMPTS


def _is_pure_int(v: object) -> bool:
    """``True`` for ``int`` but NOT ``bool`` (Python bools subclass int)."""
    return isinstance(v, int) and not isinstance(v, bool)


def _is_bool(v: object) -> bool:
    """``True`` for ``bool``."""
    return isinstance(v, bool)


def _is_str(v: object) -> bool:
    """``True`` for ``str``."""
    return isinstance(v, str)


def _check_required_keys(op: str, ctx: dict[str, object]) -> None:
    """Raise JotValidationError if any required key is missing for ``op``."""
    missing = [k for k in _REQUIRED_KEYS[op] if k not in ctx]
    if missing:
        raise JotValidationError(
            f"missing required keys for op={op!r}: {missing}",
            field=f"ctx.{missing[0]}",
            error_id="ERROR_JOT_VALIDATION",
        )


def _check_typed_keys(
    op: str,
    ctx: dict[str, object],
    keys: tuple[str, ...],
    type_name: str,
    predicate: Callable[[object], bool],
) -> None:
    """Raise JotValidationError if any key in ``keys`` has the wrong type."""
    for k in keys:
        if k in ctx and not predicate(ctx[k]):
            raise JotValidationError(
                f"{op}.{k} must be {type_name}, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )


def _check_literal_keys(op: str, ctx: dict[str, object]) -> None:
    """Raise JotValidationError if any literal key has a value outside its allowed set."""
    for k, allowed in _LITERAL_KEYS.items():
        if k in ctx and ctx[k] not in allowed:
            raise JotValidationError(
                f"{op}.{k} must be one of {allowed}, got {ctx[k]!r}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )


def _validate_ctx(op: str, ctx: dict[str, object]) -> None:
    """Hard-fail validation against per-op TypedDict + required keys.

    Raises JotValidationError on missing required keys, wrong types,
    or unknown Literal values. Does NOT write to the log.
    """
    if op not in _REQUIRED_KEYS:
        raise JotValidationError(
            f"unknown op: {op!r}",
            field="op",
            error_id="ERROR_JOT_VALIDATION",
        )
    _check_required_keys(op, ctx)
    unknown = set(ctx) - _KNOWN_KEYS_PER_OP[op]
    if unknown:
        first_unknown = min(unknown)
        raise JotValidationError(
            f"unknown keys for op={op!r}: {sorted(unknown)}",
            field=f"ctx.{first_unknown}",
            error_id="ERROR_JOT_VALIDATION",
        )
    _check_typed_keys(op, ctx, _INT_KEYS, "int", _is_pure_int)
    _check_typed_keys(op, ctx, _BOOL_KEYS, "bool", _is_bool)
    _check_typed_keys(op, ctx, _STR_KEYS, "str", _is_str)
    _check_literal_keys(op, ctx)


# Shared in-process asyncio lock. Both capture (sub-plan 1) and drain
# acquire this lock before writing to log.jsonl. Single-process assumption
# per spec §4.6 (cross-process atomicity is out of scope).
_append_lock = asyncio.Lock()

# Per-jot waiter events for adversarial test observability of
# _auto_retry_after. The reconciler schedules retries as fire-and-forget
# background tasks via asyncio.create_task; tests observe completion by
# awaiting _retry_waiters[handle]. _auto_retry_after sets the event after
# its post-sleep fold/validate path completes (success or failure —
# set unconditionally so tests aren't sensitive to the failure path).
_retry_waiters: dict[str, asyncio.Event] = {}


# =============================================================================
# Surfaces + Result types for MCP return shapes (TypedDicts, no Any)
# =============================================================================


class DrainPlanDict(TypedDict):
    query: str | None
    candidates: list[dict[str, Any]]  # JotSummaryDict-shaped items
    action_proposals: list[ActionProposalDict]


class ActionProposalDict(TypedDict):
    """Suggested action for one drain candidate (spec §3.3.4 — locked).

    The mapping from `JotSummary.dispatch_state` to `suggested_action` and
    `reason` is policy; see parent spec §3.3.4 for the canonical table.
    Behavior change requires brainstorming re-open.

    Field shape:
      - handle: str  (6-hex short_id; resolves via JotSummary)
      - suggested_action: "dispatch" | "defer" | "done" | "delete" | "skip"
      - reason: str  (short human-readable rationale)
    """

    handle: str
    suggested_action: Literal["dispatch", "defer", "done", "delete", "skip"]
    reason: str


class DispatchResultDict(TypedDict):
    handle: str
    workflow_id: str
    attempt: int
    status: Literal["in_flight", "queued"]
    dispatched_from: Literal["cli", "mcp", "slash"]


# =============================================================================
# Single write path
# =============================================================================


async def _append_event(
    op: str,
    ctx: dict[str, object],
    *,
    jot_id: str,
) -> None:
    """Validate ctx, auto-fill started_at_ms on dispatch, append to log.

    Single write path for all drain events. Validation happens BEFORE
    the lock is acquired, so malformed ctx cannot tie up the lock.
    Raises JotValidationError for malformed ctx (NOT written); raises
    JotLogUnwritableError on disk failure (also NOT written).

    `jot_id` is required (kw-only): every drain event must carry the
    parent jot's id so the fold groups it under the originating jot's
    bucket, updating `dispatch_state` / `deleted` / `deferred_until`
    rather than spawning a phantom empty-id jot.

    On `op == "dispatch"`, if the caller did not pass `started_at_ms`,
    the wrapper stamps the current wall-clock so Tier-2 reconcilers can
    compute elapsed time without re-scanning events. The field is also
    validated against `DispatchCtx` after the fill, so a caller-provided
    invalid value still raises JotValidationError.
    """
    if op == "dispatch" and "started_at_ms" not in ctx:
        ctx = {**ctx, "started_at_ms": _now_ms()}

    _validate_ctx(op, ctx)

    node = get_node(node_path())
    last_hlc = read_tail_hlc(log_path())
    hlc = hlc_now(node, last_hlc)
    event = JotEvent(
        id=jot_id,
        op=cast("Op", op),
        text="",  # drain events have no user-text payload
        ctx=ctx,
        hlc=hlc,
        created_ms=hlc.wall_ms,
    )

    path = log_path()
    line = serialize(event)

    async with _append_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(line)
        except OSError as exc:
            raise JotLogUnwritableError(
                f"cannot append to {path}: {exc}",
                path=str(path),
            ) from exc


# Re-export TypedDicts so callers can import from drain.py
__all__ = [
    "ActionProposalDict",
    "DeferCtx",
    "DeferExpiredCtx",
    "DeleteCtx",
    "DispatchCtx",
    "DispatchDoneCtx",
    "DispatchFailedCtx",
    "DispatchResultDict",
    "DispatchState",
    "DrainPlanDict",
    "_append_event",
]


@dataclass(frozen=True, slots=True)
class _Placeholder:
    """Marker for future modules to import. Will be removed in later tasks."""


# =============================================================================
# Two-tier reconciliation (Tasks 6, 7, 10 — spec §6.3, §6.4)
# =============================================================================


TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"})
STATUS_CALL_TIMEOUT_SECONDS: int = 30
RECONCILER_TIMEOUT_MS: int = 10 * 60 * 1000  # 10 min
RECONCILER_INTERVAL_SECONDS: int = 30
RETRY_BACKOFF_SECONDS: int = 30


async def _mcp_trigger_workflow(
    adapter: str, task_type: str, params: dict[str, object]
) -> dict[str, object]:
    """Thin wrapper over mahavishnu.mcp.server_core.trigger_workflow.

    Raises JotDispatchError on failure so callers can decide retry vs fail-fast.
    """
    try:
        # Imported lazily to avoid module-load cost when drain is unused.
        from mahavishnu.mcp.server_core import trigger_workflow  # ty: ignore[unresolved-import]

        result: dict[str, object] = await trigger_workflow(
            adapter=adapter,
            task_type=task_type,
            params=params,
        )
        return result
    except Exception as exc:
        raise JotDispatchError(
            f"{type(exc).__name__}: {exc}",
            error_id="ERROR_JOT_TRIGGER_WORKFLOW_FAILED",
        ) from exc


async def _mcp_get_workflow_status(workflow_id: str) -> dict[str, object]:
    """Thin wrapper over mahavishnu.mcp.server_core.get_workflow_status."""
    try:
        from mahavishnu.mcp.server_core import get_workflow_status  # ty: ignore[unresolved-import]

        result: dict[str, object] = await get_workflow_status(workflow_id=workflow_id)
        return result
    except Exception as exc:
        raise JotDispatchError(
            f"{type(exc).__name__}: {exc}",
            error_id="ERROR_JOT_RECONCILE_STATUS",
        ) from exc


async def _auto_retry_after(handle: str, backoff_s: int) -> None:
    """Auto-retry a FAILED-dispatched jot after backoff. Spec §6.4.

    Records an event in `_retry_waiters` before sleeping so adversarial
    tests can await the retry completing without blocking the reconciler.

    Pre-conditions checked after the sleep:
      - jot still FAILED-eligible (manual retry may have won the race)
      - current_attempt < MAX_AUTO_ATTEMPTS (budget remaining)
    """
    event = asyncio.Event()
    _retry_waiters[handle] = event
    try:
        await asyncio.sleep(backoff_s)

        try:
            from mahavishnu.jot.fold import build_states, parse_events
            from mahavishnu.jot.handle import resolve_handle

            events = parse_events(log_path())
            states = build_states(events, enrich=False).states
            current = resolve_handle(states, handle)
        except Exception as exc:  # noqa: BLE001 - log path may be unreadable
            log.error(
                "JOT_AUTO_RETRY_FOLD_FAILED",
                handle=handle,
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        if current.dispatch_state is not DispatchState.FAILED:
            return  # user retried manually; auto-retry exits

        if current.current_attempt >= MAX_AUTO_ATTEMPTS:
            return  # budget exhausted before this sleep completed

        try:
            result = await _mcp_trigger_workflow(
                adapter="prefect",
                task_type="jot_dispatch",
                params={"prompt": current.text},
            )
            wf_id_raw = result.get("workflow_id")
            workflow_id = str(wf_id_raw) if wf_id_raw is not None else ""
        except JotDispatchError as exc:
            try:
                await _append_event(
                    "dispatch_failed",
                    {
                        "workflow_id": f"failed_to_create:{exc.error_id}",
                        "attempt": current.current_attempt + 1,
                        "error": f"{type(exc).__name__}: {exc}",
                        "error_id": exc.error_id,
                        "retry_budget_exhausted": True,
                    },
                    jot_id=current.id,
                )
            except (JotLogUnwritableError, JotValidationError) as log_exc:
                log.error(
                    "JOT_AUTO_RETRY_LOG_FAILED",
                    handle=handle,
                    error=str(log_exc),
                )
            return

        try:
            await _append_event(
                "dispatch",
                {
                    "workflow_id": workflow_id,
                    "attempt": current.current_attempt + 1,
                    "pool_selector": "least_loaded",
                    "dispatched_from": "mcp",
                    "triggered_by": "auto",
                },
                jot_id=current.id,
            )
        except (JotLogUnwritableError, JotValidationError) as exc:
            log.error(
                "JOT_AUTO_RETRY_EVENT_APPEND_FAILED",
                handle=handle,
                workflow_id=workflow_id,
                error_id="ERROR_JOT_DISPATCH_EVENT_APPEND",
                error=f"{type(exc).__name__}: {exc}",
            )
    finally:
        event.set()


async def _reconcile_if_in_flight(jot: JotSummary) -> None:
    """Tier-1 lazy reconciler — runs on every fold. Spec §6.3.

    Order of operations:
      1. Tier-2 timeout gate: if IN_FLIGHT > RECONCILER_TIMEOUT_MS, write
         dispatch_failed with `_should_exhaust_retry_budget(jot)` flag (per
         locked decision "max 2 attempts total" — attempt 1 timeout still
         allows attempt 2).
      2. Substrate status check (with asyncio.wait_for timeout).
      3. Emit dispatch_done / dispatch_failed based on terminal status.
      4. Schedule auto-retry when budget remains.

    All exceptions caught; fold must not crash because reconciliation
    can't persist.
    """
    if jot.dispatch_state is not DispatchState.IN_FLIGHT:
        return
    workflow_id = jot.dispatch_workflow_id
    if workflow_id is None:
        log.warning("JOT_DISPATCH_NO_WORKFLOW_ID", handle=jot.short_id)
        return

    # Tier-2 timeout gate
    now_ms_ = _now_ms()
    started_at = jot.dispatch_started_at_ms
    if started_at is not None and (now_ms_ - started_at) >= RECONCILER_TIMEOUT_MS:
        budget_exhausted = _should_exhaust_retry_budget(jot)
        try:
            await _append_event(
                "dispatch_failed",
                {
                    "workflow_id": workflow_id,
                    "attempt": jot.current_attempt,
                    "error": "workflow_timeout:tier2",
                    "error_id": "ERROR_JOT_WORKFLOW_TIMEOUT",
                    "retry_budget_exhausted": budget_exhausted,
                },
                jot_id=jot.id,
            )
            log.error(
                "JOT_WORKFLOW_TIMEOUT",
                handle=jot.short_id,
                workflow_id=workflow_id,
                elapsed_ms=now_ms_ - started_at,
                attempt=jot.current_attempt,
                error_id="ERROR_JOT_WORKFLOW_TIMEOUT",
            )
            if not budget_exhausted:
                # Fire-and-forget: don't block the reconciler on the
                # 30s backoff. Tests observe via _retry_waiters[handle].
                asyncio.create_task(
                    _auto_retry_after(
                        jot.short_id,
                        backoff_s=RETRY_BACKOFF_SECONDS,
                    ),
                )
        except (JotLogUnwritableError, JotValidationError) as exc:
            log.error(
                "JOT_RECONCILE_TIMEOUT_WRITE_FAILED",
                handle=jot.short_id,
                error=str(exc),
            )
        return

    # Substrate status check
    try:
        status_dict = await asyncio.wait_for(
            _mcp_get_workflow_status(workflow_id),
            timeout=STATUS_CALL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        log.warning(
            "JOT_RECONCILE_STATUS_TIMEOUT",
            handle=jot.short_id,
            workflow_id=workflow_id,
        )
        return
    except Exception as exc:  # noqa: BLE001 - status fetch may raise; logged
        log.error(
            "JOT_RECONCILE_STATUS_FAILED",
            handle=jot.short_id,
            workflow_id=workflow_id,
            error_id="ERROR_JOT_RECONCILE_STATUS",
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    status_str = str(status_dict.get("status", "UNKNOWN"))
    if status_str not in TERMINAL_STATUSES:
        return  # still RUNNING/PENDING

    succeeded = status_str == "COMPLETED"
    try:
        if succeeded:
            await _append_event(
                "dispatch_done",
                {
                    "workflow_id": workflow_id,
                    "summary": ("ok" if status_dict.get("results_count") else "completed"),
                    **(
                        {"commit_sha": status_dict["commit_sha"]}
                        if status_dict.get("commit_sha")
                        else {}
                    ),
                },
                jot_id=jot.id,
            )
        else:
            budget_exhausted = _should_exhaust_retry_budget(jot)
            await _append_event(
                "dispatch_failed",
                {
                    "workflow_id": workflow_id,
                    "attempt": jot.current_attempt,
                    "error": f"workflow_status:{status_str}",
                    "error_id": "ERROR_JOT_WORKFLOW_FAILED",
                    "retry_budget_exhausted": budget_exhausted,
                },
                jot_id=jot.id,
            )
            if not budget_exhausted:
                # Fire-and-forget: don't block the reconciler on the
                # 30s backoff. Tests observe via _retry_waiters[handle].
                asyncio.create_task(
                    _auto_retry_after(
                        jot.short_id,
                        backoff_s=RETRY_BACKOFF_SECONDS,
                    ),
                )
    except (JotLogUnwritableError, JotValidationError) as exc:
        log.error(
            "JOT_RECONCILE_WRITE_FAILED",
            handle=jot.short_id,
            error=str(exc),
        )


async def _background_reconciler_loop() -> None:
    """Tier-2 background reconciler. Spec §6.3.

    Runs forever (started at Mahavishnu server boot). Idempotent with Tier 1.
    Per-jot and per-tick exception handling — a single bad jot or fold
    must not crash the loop.
    """
    while True:
        await asyncio.sleep(RECONCILER_INTERVAL_SECONDS)
        try:
            from mahavishnu.jot.fold import build_states, parse_events

            events = parse_events(log_path())
            jots = build_states(events, enrich=False).states
        except Exception as exc:  # noqa: BLE001 - log path may be unreadable
            log.error(
                "JOT_RECONCILER_FOLD_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        for jot in jots:
            if jot.dispatch_state is not DispatchState.IN_FLIGHT:
                continue
            try:
                await _reconcile_if_in_flight(jot)
            except Exception as exc:  # noqa: BLE001 - per-jot reconcile; logged
                log.error(
                    "JOT_RECONCLE_PER_JOT_FAILED",
                    handle=jot.short_id,
                    error=f"{type(exc).__name__}: {exc}",
                )


# =============================================================================
# Public drain primitives (Task 9 — spec §3.3)
# =============================================================================
#
# These functions form the CLI handler / MCP-tool surface in
# `mahavishnu/jot/cli.py` and `mahavishnu/mcp/tools/jot_tools.py`. The
# 4 action primitives (`dispatch_jot`, `retry_dispatch`, `defer_jot`,
# `delete_jot`) are async — sync callers wrap them via ``asyncio.run``.
# ``drain_plan`` stays sync so the CLI handler can render results
# without an event-loop round trip.
#
# Return shapes:
#   - ``drain_plan`` → ``DrainPlan`` (frozen dataclass)
#   - ``dispatch_jot`` / ``retry_dispatch`` → ``DispatchResult`` (frozen)
#   - ``defer_jot`` / ``delete_jot`` → ``JotSummary`` (frozen, with new
#     `deferred_until` / `deleted` reflected via re-fold)


# =============================================================================
# High-level drain result dataclasses (Task 9 — spec §3.3)
# =============================================================================


@dataclass(frozen=True, slots=True)
class DrainPlan:
    """Bulk-action candidate list returned by ``drain_plan``.

    `query` is the search string passed in (None when no query filter).
    `candidates` is the JotSummary list (already filtered + limited).
    `action_proposals` mirrors `candidates` with a heuristic suggested
    action per jot (spec §3.3) — derived from each candidate's
    `dispatch_state`. The mapping is intentionally narrow (no semantic
    ranking); callers may override or re-pick before invoking
    `execute_action`.
    `error` carries a fold failure as a structured value (None on success)
    so callers don't have to catch exceptions just to know the log was
    unreadable.
    """

    query: str | None
    candidates: list[JotSummary] = field(default_factory=list)
    action_proposals: list[ActionProposalDict] = field(default_factory=list)
    """Suggested action per drain candidate, 1:1 with `candidates` (same
    length, same order). Each element is an `ActionProposalDict` with:

      {
        "handle": str,           # 6-hex short_id; resolves via JotSummary
        "suggested_action": "dispatch" | "defer" | "done" | "delete" | "skip",
        "reason": str,           # short human-readable rationale
      }

    Policy is locked in spec §3.3.4 (see `_propose_action`).
    """
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of ``dispatch_jot`` / ``retry_dispatch``.

    `status` is the literal workflow-substrate state — "in_flight" when the
    runtime has accepted the workflow, "queued" when the substrate accepted
    but hasn't promoted to in_flight yet.
    """

    handle: str
    workflow_id: str
    attempt: int
    status: Literal["in_flight", "queued"]


def drain_plan(
    query: str | None = None,
    limit: int = 20,
    include_in_flight: bool = False,
) -> DrainPlan:
    """Build candidate list for bulk drain (spec §6.6 / Task 9).

    Filters open jots through ``_is_drain_eligible`` then optionally drops
    IN_FLIGHT (since "dispatch" is a no-op on an IN_FLIGHT jot — the CLI
    flag ``--include-in-flight`` overrides the second filter). Applies a
    lexical-score threshold (>=0.20) when ``query`` is provided. Newest
    first, capped to ``limit``.

    Returns a structured ``DrainPlan`` dataclass; fold failures are
    captured in ``error`` rather than raised so callers can render
    partial results.
    """
    from mahavishnu.jot.fold import build_states, parse_events

    try:
        events = parse_events(log_path())
        states = build_states(events, enrich=False).states
    except Exception as exc:  # noqa: BLE001 - log path may be unreadable
        log.error("JOT_DRAIN_PLAN_FOLD_FAILED", error=f"{type(exc).__name__}: {exc}")
        return DrainPlan(query=query, candidates=[], error=str(exc))

    now_ms_ = _now_ms()
    eligible = [s for s in states if _is_drain_eligible(s, now_ms=now_ms_)]
    if not include_in_flight:
        eligible = [c for c in eligible if c.dispatch_state is not DispatchState.IN_FLIGHT]
    if query:
        q_tokens = _tokenize(query)
        eligible = [c for c in eligible if _lexical_score(_tokenize(c.text), q_tokens) >= 0.20]
    # Newest first, then truncate.
    eligible_sorted = sorted(
        eligible,
        key=lambda s: (-s.last_modified_ms, s.id),
    )
    truncated = eligible_sorted[:limit]
    return DrainPlan(
        query=query,
        candidates=truncated,
        action_proposals=[_propose_action(s) for s in truncated],
    )


def _propose_action(jot: JotSummary) -> ActionProposalDict:
    """Suggested action for a drain candidate (spec §3.3.4 — locked policy).

    Local implementation MUST match the spec table; spec changes require
    brainstorming re-open. See spec for the canonical `(dispatch_state ->
    suggested_action)` mapping and the verbatim `reason` strings.

    Mapping:

      - IN_FLIGHT  → "skip"  (already in flight)
      - FAILED     → "dispatch" (retry failed dispatch)
      - SUCCEEDED  → "done" (workflow succeeded; mark done)
      - None       → "dispatch" (never dispatched)

    `reason` is a short human-readable string the CLI/MCP can render.
    `handle` is the 6-hex short_id so callers can resolve without an
    additional id field on the proposal.
    """
    if jot.dispatch_state is DispatchState.IN_FLIGHT:
        action: Literal["dispatch", "defer", "done", "delete", "skip"] = "skip"
        reason = "already in flight"
    elif jot.dispatch_state is DispatchState.FAILED:
        action = "dispatch"
        reason = "retry failed dispatch"
    elif jot.dispatch_state is DispatchState.SUCCEEDED:
        action = "done"
        reason = "workflow succeeded; mark done"
    else:
        action = "dispatch"
        reason = "never dispatched"
    return ActionProposalDict(
        handle=jot.short_id,
        suggested_action=action,
        reason=reason,
    )


async def dispatch_jot(
    handle: str,
    *,
    dispatched_from: str = "mcp",
) -> DispatchResult:
    """Dispatch a jot to the workflow substrate (spec §6.2 / Task 9).

    Resolves the handle, rejects already-IN_FLIGHT / SUCCEEDED / DONE jots
    before touching the runtime, then triggers a Prefect ``jot_dispatch``
    workflow via the MCP wrapper. Re-folds the log to compute the next
    attempt number, then appends the ``dispatch`` event.

    `dispatched_from` is one of {"cli", "mcp", "slash"} and stamps the
    ``DispatchCtx.dispatched_from`` field for downstream surface tracking.
    """
    from mahavishnu.jot.fold import build_states, parse_events
    from mahavishnu.jot.handle import resolve_handle

    events = parse_events(log_path())
    states = build_states(events, enrich=False).states
    jot = resolve_handle(states, handle)

    if jot.dispatch_state is DispatchState.IN_FLIGHT:
        raise JotDispatchError(
            f"jot {jot.short_id} is already IN_FLIGHT",
            error_id="ERROR_JOT_ALREADY_DISPATCHED",
        )
    if jot.dispatch_state is DispatchState.SUCCEEDED:
        raise JotDispatchError(
            f"jot {jot.short_id} already SUCCEEDED — user must mark done first",
            error_id="ERROR_JOT_ALREADY_SUCCEEDED",
        )
    if jot.status == "done":
        raise JotDispatchError(
            f"jot {jot.short_id} is already done",
            error_id="ERROR_JOT_DONE",
        )

    next_attempt = (jot.current_attempt or 0) + 1
    result = await _mcp_trigger_workflow(
        adapter="prefect",
        task_type="jot_dispatch",
        params={"prompt": jot.text},
    )
    wf_id_raw = result.get("workflow_id")
    workflow_id = str(wf_id_raw) if wf_id_raw is not None else ""

    await _append_event(
        "dispatch",
        {
            "workflow_id": workflow_id,
            "attempt": next_attempt,
            "pool_selector": "least_loaded",
            "dispatched_from": dispatched_from,
            "triggered_by": ("manual" if jot.dispatch_state is DispatchState.FAILED else "first"),
        },
        jot_id=jot.id,
    )
    return DispatchResult(
        handle=jot.short_id,
        workflow_id=workflow_id,
        attempt=next_attempt,
        status="in_flight",
    )


async def retry_dispatch(
    handle: str,
    *,
    dispatched_from: str = "mcp",
) -> DispatchResult:
    """Manual retry of a FAILED jot (spec §6.2 / Task 9).

    Raises JotRetryError when the jot is not in FAILED state.
    """
    from mahavishnu.jot.fold import build_states, parse_events
    from mahavishnu.jot.handle import resolve_handle

    events = parse_events(log_path())
    states = build_states(events, enrich=False).states
    jot = resolve_handle(states, handle)
    if jot.dispatch_state is not DispatchState.FAILED:
        current_state: Any = jot.dispatch_state.value if jot.dispatch_state else "none"
        raise JotRetryError(f"jot {jot.short_id} is not in FAILED state (current: {current_state})")
    return await dispatch_jot(handle, dispatched_from=dispatched_from)


async def defer_jot(
    handle: str,
    *,
    until_ms: int,
    reason: str | None = None,
) -> JotSummary:
    """Defer a jot until a future timestamp (spec §6.2 / Task 9).

    Raises JotDeferError when ``until_ms <= now_ms``. Re-folds the log
    after appending the defer event so the caller receives the updated
    JotSummary (with the new ``deferred_until`` field).
    """
    if until_ms <= _now_ms():
        raise JotDeferError(
            f"until_ms must be > now_ms; got {until_ms}",
        )
    from mahavishnu.jot.fold import build_states, parse_events
    from mahavishnu.jot.handle import resolve_handle

    events = parse_events(log_path())
    states = build_states(events, enrich=False).states
    jot = resolve_handle(states, handle)

    ctx: dict[str, object] = {"until": until_ms}
    if reason is not None:
        ctx["reason"] = reason
    await _append_event("defer", ctx, jot_id=jot.id)

    # Re-fold to surface the new deferred_until.
    refolded = build_states(parse_events(log_path()), enrich=False).states
    refolded_by_id = {s.id: s for s in refolded}
    return refolded_by_id[jot.id]


async def delete_jot(
    handle: str,
    *,
    reason: str | None = None,
) -> JotSummary:
    """Soft delete a jot — audit trail preserved in the log.

    Appends the ``delete`` event then re-folds the log so the caller
    receives the updated JotSummary (with ``deleted=True``).
    """
    from mahavishnu.jot.fold import build_states, parse_events
    from mahavishnu.jot.handle import resolve_handle

    events = parse_events(log_path())
    states = build_states(events, enrich=False).states
    jot = resolve_handle(states, handle)

    ctx: dict[str, object] = {}
    if reason is not None:
        ctx["reason"] = reason
    await _append_event("delete", ctx, jot_id=jot.id)

    refolded = build_states(parse_events(log_path()), enrich=False).states
    refolded_by_id = {s.id: s for s in refolded}
    return refolded_by_id[jot.id]


# =============================================================================
# Surfacing scorers + throttle (Task 8 — spec §5.1-§5.6)
# =============================================================================


LEXICAL_THRESHOLD: float = 0.2


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens, len >= 2, Unicode-aware via re.\\w+."""
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) >= 2}


def _lexical_score(jot_tokens: set[str], ctx_tokens: set[str]) -> float:
    """Coverage ratio: how much of the context does the jot cover?"""
    if not jot_tokens or not ctx_tokens:
        return 0.0
    overlap = jot_tokens & ctx_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(ctx_tokens)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# Module-level flag — set by _semantic_score on any error path so
# surface_relevant can surface 'embeddings_down' without a return-value
# channel. Reset at every surface_relevant entry.
_last_surface_degraded: bool = False


def _semantic_score(jot_text: str, ctx_text: str, embeddings: Any) -> float:
    """Batch cosine via EmbeddingsService. Returns 0.0 on any error or
    empty/wrong-shape result; sets _last_surface_degraded=True on errors.
    """
    global _last_surface_degraded
    try:
        emb = embeddings.embed([jot_text, ctx_text])
    except TimeoutError, Exception:  # noqa: BLE001 - degraded embeddings path
        _last_surface_degraded = True
        return 0.0
    # Defensive: OneiricEmbeddingsAdapter.embed is async; a sync caller
    # receives a coroutine here. Treat that (and any non-list result) as
    # a degraded embeddings path rather than crashing the fold.
    try:
        if not emb or len(emb) < 2 or not emb[0] or not emb[1] or len(emb[0]) != len(emb[1]):
            _last_surface_degraded = True
            return 0.0
    except TypeError:
        _last_surface_degraded = True
        return 0.0
    return _cosine_similarity(emb[0], emb[1])


@dataclass(frozen=True, slots=True)
class SurfacingResult:
    """Spec §5.6 — output of surface_relevant."""

    matches: list[JotSummary]
    score_threshold_used: float
    surface_degraded: bool
    surface_reason: str  # "matches" | "no_context" | "no_match" | "throttled" | "embeddings_down"


@dataclass
class _Throttle:
    """Per-process surfacing throttle. Spec §5.5.

    State persists across calls (last_fire_ms). Two skip reasons:
    - 'short_context': context_tokens < 50 (don't fire on tiny contexts).
    - 'throttled': called again within min_interval_ms of last fire.
    """

    last_fire_ms: int = 0
    min_interval_ms: int = 5000
    last_skip_reason: str | None = None

    def should_fire(
        self,
        now_ms: int,
        context_tokens: int,
    ) -> tuple[bool, str | None]:
        if context_tokens < 50:
            self.last_skip_reason = "short_context"
            return False, self.last_skip_reason
        if now_ms - self.last_fire_ms < self.min_interval_ms:
            self.last_skip_reason = "throttled"
            return False, self.last_skip_reason
        self.last_fire_ms = now_ms
        self.last_skip_reason = None
        return True, None


# Module-level throttle singleton — a fresh `_Throttle()` per call would
# never enforce the min_interval_ms gate (last_fire_ms resets to 0).
_THROTTLE: _Throttle = _Throttle()


def surface_relevant(
    trigger: str,
    context_text: str,
    limit: int = 3,
) -> SurfacingResult:
    """Lexical primary, semantic fallback. Spec §5.1-§5.6.

    `trigger` is captured by hook wrappers for downstream routing; not used
    inside this algorithm.
    """
    from mahavishnu.jot.fold import build_states, parse_events

    global _last_surface_degraded
    _last_surface_degraded = False

    # Parse + fold the log. enrich=False keeps this off the git subprocess
    # path — surfacing is a pure text-comparison operation.
    try:
        events = parse_events(log_path())
        states = build_states(events, enrich=False).states
    except Exception as exc:  # noqa: BLE001 - log path may be unreadable
        log.warning(
            "JOT_SURFACE_FOLD_FAILED",
            error=f"{type(exc).__name__}: {exc}",
        )
        return SurfacingResult(
            matches=[],
            score_threshold_used=LEXICAL_THRESHOLD,
            surface_degraded=True,
            surface_reason="embeddings_down",
        )

    now_ms = _now_ms()
    eligible = [j for j in states if _is_surface_eligible(j, now_ms)]

    ctx_tokens = _tokenize(context_text)
    # Raw word count (whitespace split) for the throttle's minimum-context
    # gate. Using tokenized-set length would under-count short prompts;
    # this matches the spec's intent of "non-trivial context only".
    ctx_word_count = len(context_text.split())

    # Throttle — module-level singleton; skip_reason is captured in the
    # SurfacingResult when not firing.
    fire, skip_reason = _THROTTLE.should_fire(now_ms, ctx_word_count)
    if not fire:
        return SurfacingResult(
            matches=[],
            score_threshold_used=LEXICAL_THRESHOLD,
            surface_degraded=False,
            surface_reason=skip_reason if skip_reason else "throttled",
        )

    if not eligible:
        return SurfacingResult(
            matches=[],
            score_threshold_used=LEXICAL_THRESHOLD,
            surface_degraded=False,
            surface_reason="no_match",
        )

    # Lexical scoring pass.
    scored: list[tuple[JotSummary, float]] = []
    for jot in eligible:
        jot_tokens = _tokenize(jot.text)
        score = _lexical_score(jot_tokens, ctx_tokens)
        scored.append((jot, score))

    lexical_hits = [(j, s) for j, s in scored if s >= LEXICAL_THRESHOLD]

    if lexical_hits:
        lexical_hits.sort(key=lambda x: (-x[1], x[0].last_modified_ms))
        return SurfacingResult(
            matches=[j for j, _ in lexical_hits[:limit]],
            score_threshold_used=LEXICAL_THRESHOLD,
            surface_degraded=False,
            surface_reason="matches",
        )

    # Semantic fallback — only when zero lexical hits. Failures inside
    # _semantic_score set _last_surface_degraded so the caller learns the
    # embeddings layer was the cause.
    embeddings = _build_embeddings_adapter()
    sem_scored: list[tuple[JotSummary, float]] = []
    for jot in eligible:
        score = _semantic_score(jot.text, context_text, embeddings)
        sem_scored.append((jot, score))

    sem_scored.sort(key=lambda x: (-x[1], x[0].last_modified_ms))
    sem_matches = [j for j, s in sem_scored if s >= LEXICAL_THRESHOLD][:limit]

    degraded = _last_surface_degraded
    return SurfacingResult(
        matches=sem_matches,
        score_threshold_used=LEXICAL_THRESHOLD,
        surface_degraded=degraded,
        surface_reason="matches"
        if sem_matches
        else ("embeddings_down" if degraded else "no_match"),
    )


def _build_embeddings_adapter() -> Any:
    """Instantiate the embeddings adapter lazily (heavy import).

    Returns the OneiricEmbeddingsAdapter instance. Tests monkeypatch this
    to provide a sync stub matching the embed() contract.
    """
    from mahavishnu.core.embeddings_oneiric import OneiricEmbeddingsAdapter

    return OneiricEmbeddingsAdapter()


__all__ = [
    "LEXICAL_THRESHOLD",
    "MAX_AUTO_ATTEMPTS",
    "ActionProposalDict",
    "DeferCtx",
    "DeferExpiredCtx",
    "DeleteCtx",
    "DispatchCtx",
    "DispatchDoneCtx",
    "DispatchFailedCtx",
    "DispatchResultDict",
    "DispatchState",
    "DrainPlanDict",
    "SurfacingResult",
    "_Throttle",
    "_append_event",
    "_auto_retry_after",
    "_background_reconciler_loop",
    "_build_embeddings_adapter",
    "_cosine_similarity",
    "_is_drain_eligible",
    "_is_surface_eligible",
    "_lexical_score",
    "_reconcile_if_in_flight",
    "_semantic_score",
    "_should_exhaust_retry_budget",
    "_tokenize",
    "defer_jot",
    "delete_jot",
    "dispatch_jot",
    "drain_plan",
    "retry_dispatch",
    "surface_relevant",
]
