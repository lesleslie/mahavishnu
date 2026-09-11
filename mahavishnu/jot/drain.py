"""Drain sub-plan (3): state machine, dispatch orchestration, retry, surfacing.

Single write path for all drain events. See spec §3.2, §4.2, §4.6, §6.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from oneiric.core.logging import get_logger

from mahavishnu.jot.errors import JotLogUnwritableError, JotValidationError
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.fold import DispatchState  # re-export target
from mahavishnu.jot.hlc import get_node, hlc_now, read_tail_hlc
from mahavishnu.jot.paths import log_path, node_path

log = get_logger(__name__)

# Re-export DispatchState (canonical location is fold.py to avoid cycle)
__all__ = ["DispatchState", "_append_event"]


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
        "workflow_id", "attempt", "error", "error_id", "retry_budget_exhausted",
    ),
    "defer": ("until",),
    "defer_expired": (),
    "delete": (),
}

_INT_KEYS = ("attempt",)
_BOOL_KEYS = ("retry_budget_exhausted",)
_STR_KEYS = (
    "workflow_id", "summary", "commit_sha", "error", "error_id",
    "pool_selector", "dispatched_from", "triggered_by", "reason",
)
_LITERAL_KEYS = {
    "triggered_by": ("first", "auto", "manual"),
    "dispatched_from": ("cli", "mcp", "slash"),
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


MAX_AUTO_ATTEMPTS: int = 2    # total (1 initial + 1 auto-retry)


def _should_exhaust_retry_budget(jot: JotSummary) -> bool:
    """Return True iff this dispatch failure should NOT auto-retry.

    Policy: a failed dispatch on the LAST configured attempt exhausts the
    budget. With MAX_AUTO_ATTEMPTS=2, attempt 2 failure → exhausted (True);
    attempt 1 failure → budget remaining (False, auto-retry fires).

    Edge case: malformed ctx where current_attempt is 0 is treated as
    attempt=1 (fail-safe — retry-once is safer than terminal FAILED).
    """
    return max(jot.current_attempt, 1) >= MAX_AUTO_ATTEMPTS


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

    required = _REQUIRED_KEYS[op]
    missing = [k for k in required if k not in ctx]
    if missing:
        raise JotValidationError(
            f"missing required keys for op={op!r}: {missing}",
            field=f"ctx.{missing[0]}",
            error_id="ERROR_JOT_VALIDATION",
        )

    for k in _INT_KEYS:
        if k in ctx and (not isinstance(ctx[k], int) or isinstance(ctx[k], bool)):
            raise JotValidationError(
                f"{op}.{k} must be int, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k in _BOOL_KEYS:
        if k in ctx and not isinstance(ctx[k], bool):
            raise JotValidationError(
                f"{op}.{k} must be bool, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k in _STR_KEYS:
        if k in ctx and not isinstance(ctx[k], str):
            raise JotValidationError(
                f"{op}.{k} must be str, got {type(ctx[k]).__name__}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )
    for k, allowed in _LITERAL_KEYS.items():
        if k in ctx and ctx[k] not in allowed:
            raise JotValidationError(
                f"{op}.{k} must be one of {allowed}, got {ctx[k]!r}",
                field=f"ctx.{k}",
                error_id="ERROR_JOT_VALIDATION",
            )


# Shared in-process asyncio lock. Both capture (sub-plan 1) and drain
# acquire this lock before writing to log.jsonl. Single-process assumption
# per spec §4.6 (cross-process atomicity is out of scope).
_append_lock = asyncio.Lock()


# =============================================================================
# Surfaces + Result types for MCP return shapes (TypedDicts, no Any)
# =============================================================================


class DrainPlanDict(TypedDict):
    query: str | None
    candidates: list[dict[str, Any]]    # JotSummaryDict-shaped items
    action_proposals: list["ActionProposalDict"]


class ActionProposalDict(TypedDict):
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


async def _append_event(op: str, ctx: dict[str, object]) -> None:
    """Validate ctx, auto-fill started_at_ms on dispatch, append to log.

    Single write path for all drain events. Validation happens BEFORE
    the lock is acquired, so malformed ctx cannot tie up the lock.
    Raises JotValidationError for malformed ctx (NOT written); raises
    JotLogUnwritableError on disk failure (also NOT written).

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
        id="",  # filled by serialize from HLC + node
        op=op,  # type: ignore[arg-type]
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
    "DispatchState", "_append_event",
    "DispatchCtx", "DispatchDoneCtx", "DispatchFailedCtx",
    "DeferCtx", "DeferExpiredCtx", "DeleteCtx",
    "DrainPlanDict", "ActionProposalDict", "DispatchResultDict",
]


@dataclass(frozen=True, slots=True)
class _Placeholder:
    """Marker for future modules to import. Will be removed in later tasks."""
    pass


# =============================================================================
# Two-tier reconciliation (Tasks 6, 7, 10 — spec §6.3, §6.4)
# =============================================================================


TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}
)
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
        from mahavishnu.mcp.server_core import trigger_workflow
        result: dict[str, object] = await trigger_workflow(
            adapter=adapter, task_type=task_type, params=params,
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
        from mahavishnu.mcp.server_core import get_workflow_status
        result: dict[str, object] = await get_workflow_status(workflow_id=workflow_id)
        return result
    except Exception as exc:
        raise JotDispatchError(
            f"{type(exc).__name__}: {exc}",
            error_id="ERROR_JOT_RECONCILE_STATUS",
        ) from exc


async def _auto_retry_after(handle: str, backoff_s: int) -> None:
    """Auto-retry a FAILED-dispatched jot after backoff. Spec §6.4.

    Pre-conditions checked after the sleep:
      - jot still FAILED-eligible (manual retry may have won the race)
      - current_attempt < MAX_AUTO_ATTEMPTS (budget remaining)
    """
    try:
        await asyncio.sleep(backoff_s)
    except asyncio.CancelledError:
        raise

    try:
        from mahavishnu.jot.fold import build_states, parse_events
        from mahavishnu.jot.handle import resolve_handle
        events = parse_events(log_path())
        states = build_states(events, enrich=False).states
        current = resolve_handle(states, handle)
    except Exception as exc:
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
            await _append_event("dispatch_failed", {
                "workflow_id": f"failed_to_create:{exc.error_id}",
                "attempt": current.current_attempt + 1,
                "error": f"{type(exc).__name__}: {exc}",
                "error_id": exc.error_id,
                "retry_budget_exhausted": True,
            })
        except (JotLogUnwritableError, JotValidationError) as log_exc:
            log.error(
                "JOT_AUTO_RETRY_LOG_FAILED",
                handle=handle, error=str(log_exc),
            )
        return

    try:
        await _append_event("dispatch", {
            "workflow_id": workflow_id,
            "attempt": current.current_attempt + 1,
            "pool_selector": "least_loaded",
            "triggered_by": "auto",
        })
    except (JotLogUnwritableError, JotValidationError) as exc:
        log.error(
            "JOT_AUTO_RETRY_EVENT_APPEND_FAILED",
            handle=handle, workflow_id=workflow_id,
            error_id="ERROR_JOT_DISPATCH_EVENT_APPEND",
            error=f"{type(exc).__name__}: {exc}",
        )


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
        log.warning("JOT_DISPATCH_NO_WORKFLOW_ID", handle=jot.handle)
        return

    # Tier-2 timeout gate
    now_ms_ = _now_ms()
    started_at = jot.dispatch_started_at_ms
    if started_at is not None and (now_ms_ - started_at) >= RECONCILER_TIMEOUT_MS:
        budget_exhausted = _should_exhaust_retry_budget(jot)
        try:
            await _append_event("dispatch_failed", {
                "workflow_id": workflow_id,
                "attempt": jot.current_attempt,
                "error": "workflow_timeout:tier2",
                "error_id": "ERROR_JOT_WORKFLOW_TIMEOUT",
                "retry_budget_exhausted": budget_exhausted,
            })
            log.error(
                "JOT_WORKFLOW_TIMEOUT",
                handle=jot.handle, workflow_id=workflow_id,
                elapsed_ms=now_ms_ - started_at,
                attempt=jot.current_attempt,
                error_id="ERROR_JOT_WORKFLOW_TIMEOUT",
            )
            if not budget_exhausted:
                asyncio.create_task(
                    _auto_retry_after(jot.handle, backoff_s=RETRY_BACKOFF_SECONDS)
                )
        except (JotLogUnwritableError, JotValidationError) as exc:
            log.error(
                "JOT_RECONCILE_TIMEOUT_WRITE_FAILED",
                handle=jot.handle, error=str(exc),
            )
        return

    # Substrate status check
    try:
        status_dict = await asyncio.wait_for(
            _mcp_get_workflow_status(workflow_id),
            timeout=STATUS_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning(
            "JOT_RECONCILE_STATUS_TIMEOUT",
            handle=jot.handle, workflow_id=workflow_id,
        )
        return
    except Exception as exc:
        log.error(
            "JOT_RECONCILE_STATUS_FAILED",
            handle=jot.handle, workflow_id=workflow_id,
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
            await _append_event("dispatch_done", {
                "workflow_id": workflow_id,
                "summary": (
                    "ok" if status_dict.get("results_count") else "completed"
                ),
                **(
                    {"commit_sha": status_dict["commit_sha"]}
                    if status_dict.get("commit_sha") else {}
                ),
            })
        else:
            budget_exhausted = _should_exhaust_retry_budget(jot)
            await _append_event("dispatch_failed", {
                "workflow_id": workflow_id,
                "attempt": jot.current_attempt,
                "error": f"workflow_status:{status_str}",
                "error_id": "ERROR_JOT_WORKFLOW_FAILED",
                "retry_budget_exhausted": budget_exhausted,
            })
            if not budget_exhausted:
                asyncio.create_task(
                    _auto_retry_after(jot.handle, backoff_s=RETRY_BACKOFF_SECONDS)
                )
    except (JotLogUnwritableError, JotValidationError) as exc:
        log.error(
            "JOT_RECONCILE_WRITE_FAILED",
            handle=jot.handle, error=str(exc),
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
        except Exception as exc:
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
            except Exception as exc:
                log.error(
                    "JOT_RECONCLE_PER_JOT_FAILED",
                    handle=jot.handle,
                    error=f"{type(exc).__name__}: {exc}",
                )


__all__ = [
    "DispatchState", "_append_event",
    "DispatchCtx", "DispatchDoneCtx", "DispatchFailedCtx",
    "DeferCtx", "DeferExpiredCtx", "DeleteCtx",
    "DrainPlanDict", "ActionProposalDict", "DispatchResultDict",
    "_is_surface_eligible", "_is_drain_eligible",
    "MAX_AUTO_ATTEMPTS", "_should_exhaust_retry_budget",
    "_auto_retry_after", "_reconcile_if_in_flight",
    "_background_reconciler_loop",
]
