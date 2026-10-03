"""The single dispatch edge from the Bodai task system to pool dispatch.

This module exposes the ``tasks_handoff_to_workflow`` MCP tool. It is the
only dispatch edge in the task system: every other task tool (create /
update / complete / list / get) talks to session-buddy directly; this one
talks to session-buddy *and* to mahavishnu's pool router in sequence.

The flow is three sequential steps wrapped in try/finally so that a
disconnect between steps 2 and 3 emits ``task.handoff_orphan`` before
re-raising:

    1. session-buddy.tasks_get(task_id)         # load the task
    2. pool_route_execute(prompt=task.content)  # dispatch
    3. session-buddy.tasks_update(workflow_id)  # back-link

Mahavishnu owns its own copies of :class:`HandoffParams` and
:class:`HandoffResult` (per spec — to avoid runtime cross-repo imports).
T1's ``session_buddy.mcp.tools.tasks_models`` is the source-of-truth;
the :func:`tasks_handoff_to_workflow_available` gate (T16) verifies the
shapes still match at registration time.

Registration is T18's responsibility. This module is consumed by
``mahavishnu/mcp/tools/profiles.py`` via
``register_tasks_handoff_tools(mcp, ...)``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import re
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from mahavishnu.mcp.tools.tasks_handoff_gate import (
    tasks_handoff_to_workflow_available,
)

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline copies of T1 contract types (source-of-truth: session-buddy PR #1)
# ---------------------------------------------------------------------------
#
# We DO NOT import from ``session_buddy.mcp.tools.tasks_models`` at module
# load time. Mahavishnu owns its own copies so a session-buddy upgrade
# cannot break the tool signature mid-flight. The T16 gate validates at
# registration that the upstream source-of-truth still ships the matching
# shapes.

TASK_ID_PATTERN = r"^t-[0-9a-f]{32}$"

_ADAPTER = Literal["prefect", "llamaindex", "agno"]


class HandoffParams(BaseModel):
    """Typed parameters for dispatch. Replaces free-form ``dict`` so the
    MCP schema advertises valid values to clients."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    timeout_seconds: int | None = None
    pool_selector: Literal["least_loaded", "round_robin", "affinity"] = "least_loaded"
    pool_name: str | None = None
    idempotency_key: str | None = None
    extra_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HandoffResult(BaseModel):
    """Result envelope returned by ``tasks_handoff_to_workflow`` after
    step 2 (dispatch) succeeds. ``workflow_id`` is the upstream
    ``dispatch_to_pool`` identifier; step 3 (session-buddy update) stores
    it on the task via ``UpdateTaskRequest(metadata__workflow_id=...)``."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    adapter: _ADAPTER
    started_at: datetime
    pool_name: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TaskNotFoundError(Exception):
    """Raised when session-buddy has no record of ``task_id`` (or the caller
    cannot see it). Carries code ``MHV-101`` per the task-system spec.

    Deliberately does NOT inherit from :class:`mahavishnu.core.errors.MahavishnuError`
    because the upstream enum maps ``MHV-101`` to ``TASK_CREATION_FAILED``;
    this tool reuses the code for a ``not-found`` surface per the brief.
    The code is exposed as a plain string attribute so test assertions and
    FastMCP error envelopes can branch on it without coupling to the
    mahavishnu error taxonomy.
    """

    code: str = "MHV-101"

    def __init__(self, task_id: str, details: dict[str, Any] | None = None) -> None:
        self.task_id = str(task_id)
        self.details = {"task_id": self.task_id, **(details or {})}
        super().__init__(f"[MHV-101] Task not found: {self.task_id}")


class WorkflowNotReturnedError(Exception):
    """Raised when ``pool_route_execute`` succeeded but did not return a
    ``workflow_id``. The v1.1 sweeper would chase a phantom orphan if we
    emitted one here, so this surfaces as a typed caller-visible failure
    instead. Carries the raw dispatch envelope for diagnostics.
    """

    code: str = "MHV-102"

    def __init__(
        self,
        task_id: str,
        dispatch_result: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = str(task_id)
        self.dispatch_result = dict(dispatch_result)
        self.details = {
            "task_id": self.task_id,
            "dispatch_keys": sorted(dispatch_result.keys()),
            **(details or {}),
        }
        super().__init__(
            f"[MHV-102] pool_route_execute did not return a workflow_id "
            f"for task {self.task_id}: {self.dispatch_result!r}"
        )


# Canonical orphan reasons (per Fix Round 1). Keep these as module-level
# constants rather than an Enum so the upstream task_events literal type
# stays string-typed and avoids a cross-package import.
_ORPHAN_REASON_STEP_3_UPDATE_FAILED = "step_3_update_failed"
_ORPHAN_REASON_STEP_2_DISPATCH_FAILED = "step_2_dispatch_failed"
_ORPHAN_REASON_UNEXPECTED = "unexpected_error"


# ---------------------------------------------------------------------------
# Content validation (mirrors session-buddy's sanitizer so dispatch-time
# validation rejects the same set of malformed payloads without depending
# on session-buddy's stub publisher).
# ---------------------------------------------------------------------------

# Strip every ASCII control char except tab (\x09) and newline (\x0a).
# \x7f (DEL) is also in the strip set.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# 4 KiB cap mirrors session-buddy's _MAX_FIELD_BYTES.
_MAX_CONTENT_BYTES = 4096


def _validate_task_content_for_dispatch(content: str) -> str:
    """Reject malformed task content BEFORE we hit the pool router.

    Returns the sanitized content (control chars stripped, length-capped).
    Raises :class:`ValueError` (caught at the MCP boundary and surfaced as
    a validation envelope) when the input cannot be made dispatch-safe.
    """
    if not content:
        raise ValueError("task content is empty")
    sanitized = _CONTROL_CHARS.sub("", content)
    encoded = sanitized.encode("utf-8")[:_MAX_CONTENT_BYTES]
    truncated = encoded.decode("utf-8", errors="replace")
    if encoded != sanitized.encode("utf-8"):
        # Lost bytes during cap — refuse rather than silently truncate.
        raise ValueError(f"task content exceeds {_MAX_CONTENT_BYTES} bytes after sanitization")
    return truncated


# ---------------------------------------------------------------------------
# Rate limiter (10/min per caller — spec §Input Limits)
# ---------------------------------------------------------------------------
#
# Simple in-process sliding-window limiter. The MCP server is single-process
# in current deployments; if it becomes multi-process this needs a backing
# store (Redis INCR with EXPIRE) but that is out of scope for T17.

_RATE_LIMIT_PER_MINUTE = 10


class _HandoffRateLimiter:
    """Per-caller sliding-window limiter, ``limit`` requests per 60 s."""

    def __init__(self, limit: int = _RATE_LIMIT_PER_MINUTE, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def _evict(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._requests[key] = [t for t in self._requests.get(key, []) if t > cutoff]

    def check(self, key: str) -> None:
        """Raise :class:`RateLimitError` if ``key`` is over the limit.

        Otherwise record this call and return. Tests can monkeypatch
        :func:`_derive_caller_key` to drive the limiter deterministically.
        """
        now = time.monotonic()
        self._evict(key, now)
        history = self._requests.setdefault(key, [])
        if len(history) >= self.limit:
            retry_after = int(self.window_seconds - (now - history[0])) + 1
            raise RateLimitError(
                f"tasks_handoff_to_workflow rate limit exceeded for caller {key!r}",
                retry_after_seconds=retry_after,
            )
        history.append(now)


class RateLimitError(Exception):
    """Raised by :class:`_HandoffRateLimiter` when a caller exceeds the
    per-minute cap. Carries ``retry_after_seconds`` for caller backoff."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


_HANDOFF_RATE_LIMITER = _HandoffRateLimiter()


def _derive_caller_key() -> str:
    """Derive the per-caller identity used by the rate limiter.

    In production this is wired up by T18 from the FastMCP request
    context (auth subject + caller_kind). For now we expose a single
    module-level hook so tests can monkeypatch the key deterministically
    without forcing a FastMCP context fixture.
    """
    return "default"


# ---------------------------------------------------------------------------
# Publisher shims — typed no-ops that call session-buddy's stub publisher
# if it is importable. We deliberately do NOT make module-level imports
# from session_buddy so this module can be imported in test environments
# where session_buddy is not installed (the gate handles that case at
# registration time).
# ---------------------------------------------------------------------------


async def _publish_task_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish a task.* event. No-op when session-buddy is not importable.

    The publisher itself is a stub upstream (T2 deferred Redis wiring),
    so this is typed-but-side-effect-free in the current environment.
    """
    try:
        from session_buddy.mcp.tools.tasks_events import (
            publish_task_event_raw,
        )
    except ImportError:
        return
    try:
        await publish_task_event_raw(event_type, payload)
    except Exception as exc:  # noqa: BLE001 - publisher is best-effort
        logger.warning("tasks_handoff: publish %s failed: %s", event_type, exc)


def _publish_task_handoff_started(task_id: str, actor: str) -> None:
    payload = {
        "task_id": task_id,
        "actor": actor,
        "started_at": datetime.now(UTC).isoformat(),
    }
    # Awaitable shim — we deliberately do not block on this in the hot path.
    asyncio.create_task(_publish_task_event("task.handoff_started", payload))


def _publish_task_handoff_completed(
    task_id: str,
    workflow_id: str,
    adapter: str,
    actor: str,
) -> None:
    payload = {
        "task_id": task_id,
        "workflow_id": workflow_id,
        "actor": actor,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    asyncio.create_task(_publish_task_event("task.handoff_completed", payload))


def _publish_task_handoff_orphan(task_id: str, reason: str, workflow_id: str = "") -> None:
    payload: dict[str, Any] = {
        "task_id": task_id,
        "actor": _derive_caller_key(),
        "reason": reason,
        "orphaned_at": datetime.now(UTC).isoformat(),
    }
    if workflow_id:
        payload["workflow_id"] = workflow_id
    asyncio.create_task(_publish_task_event("task.handoff_orphan", payload))


# ---------------------------------------------------------------------------
# Session-buddy + pool_route_execute call sites — module-level so tests
# can monkeypatch them at the boundary.
# ---------------------------------------------------------------------------


async def _session_buddy_get_task(task_id: str) -> dict[str, Any]:
    """Call session-buddy's ``tasks_get`` MCP tool. Module-level so tests
    can monkeypatch it. The return shape mirrors the canonical Task
    envelope (``id``, ``content``, ``owner``, ``metadata``, ...)."""
    raise NotImplementedError(
        "tasks_handoff: no session_buddy_client bound — pass one via "
        "register_tasks_handoff_tools(..., session_buddy_client=...)"
    )


async def _session_buddy_update_task(
    task_id: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call session-buddy's ``tasks_update`` MCP tool with the supplied
    ``metadata`` patch (the only field step 3 needs to write)."""
    raise NotImplementedError(
        "tasks_handoff: no session_buddy_client bound — pass one via "
        "register_tasks_handoff_tools(..., session_buddy_client=...)"
    )


async def _pool_route_execute(
    prompt: str,
    *,
    pool_selector: str = "least_loaded",
    timeout: float | None = None,
) -> dict[str, Any]:
    """Wrap mahavishnu's pool_route_execute MCP tool. Module-level so
    tests can monkeypatch it. Returns the dispatch envelope
    (``workflow_id``, ``pool_id``, ``status``, ...)."""
    raise NotImplementedError(
        "tasks_handoff: no pool_route_execute_fn bound — pass one via "
        "register_tasks_handoff_tools(..., pool_route_execute_fn=...)"
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tasks_handoff_tools(
    mcp: FastMCP,
    *,
    session_buddy_client: Any | None = None,
    pool_route_execute_fn: Any | None = None,
) -> None:
    """Register ``tasks_handoff_to_workflow`` with the FastMCP server.

    Args:
        mcp: FastMCP server instance (T18 wires this via profiles.py).
        session_buddy_client: Optional object exposing ``tasks_get`` and
            ``tasks_update`` awaitables (any duck-type — typically the
            session-buddy MCP client wired through MahavishnuSettings).
            When ``None``, the tool body raises a clear
            ``NotImplementedError`` rather than crashing on import.
        pool_route_execute_fn: Optional callable wrapping mahavishnu's
            ``pool_route_execute`` MCP tool. When ``None``, the tool
            body raises a clear ``NotImplementedError``.

    Both arguments are intentionally optional so this module can be
    imported by test suites that exercise just the validation /
    rate-limit / event-publish branches without binding the upstream
    clients.

    Raises:
        RuntimeError: If the T16 gate reports session-buddy 0.30+ with
            PR #1 tools is not importable. This is a registration-time
            check (per Fix Round 1) so failures surface immediately
            rather than at first dispatch.
    """
    # Registration-time gate (Fix Round 1 #2): surface session-buddy
    # absence once, at registration, not on every call.
    if not tasks_handoff_to_workflow_available():
        raise RuntimeError(
            "tasks_handoff_to_workflow requires session-buddy>=0.30.0 with PR #1 tools"
        )

    @mcp.tool()
    async def tasks_handoff_to_workflow(
        task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)],
        adapter: _ADAPTER = "prefect",
        params: HandoffParams | None = None,
        timeout: int | None = None,
    ) -> HandoffResult:
        """Dispatch a session-buddy task to a Mahavishnu workflow.

        Single dispatch edge: looks up the task, dispatches via the pool
        router, then writes the resulting ``workflow_id`` back onto the
        task as metadata. A failure between steps 2 and 3 emits
        ``task.handoff_orphan`` so the v1.1 sweeper can re-link later.

        Rate limit: 10 calls/minute per caller.
        """
        caller_key = _derive_caller_key()
        try:
            _HANDOFF_RATE_LIMITER.check(caller_key)
        except RateLimitError as exc:
            # Always raises (by contract — see helper). No fallback path.
            _raise_rate_limited(exc)
            # ``_raise_rate_limited`` is contract-bound to raise. The
            # bare ``raise`` below is a defensive ``NoReturn`` hint for
            # ty / mypy: if the helper ever stops raising, re-raise
            # ``RateLimitError`` rather than silently falling through.
            raise

        # Bind the injected dependencies (if any) at call time so a
        # registration-time miss doesn't blow up test discovery.
        get_task = (
            session_buddy_client.tasks_get
            if session_buddy_client is not None
            else _session_buddy_get_task
        )
        update_task = (
            session_buddy_client.tasks_update
            if session_buddy_client is not None
            else _session_buddy_update_task
        )
        pool_dispatch = (
            pool_route_execute_fn if pool_route_execute_fn is not None else _pool_route_execute
        )

        # ---- Step 1: lookup ----
        try:
            task = await get_task(task_id=task_id)
        except Exception as exc:
            raise TaskNotFoundError(task_id, details={"cause": type(exc).__name__}) from exc

        # Content must be dispatch-safe (mirrors session-buddy's sanitizer).
        task_content = _validate_task_content_for_dispatch(str(task.get("content", "")))

        # ---- Event: handoff_started ----
        started_at = datetime.now(UTC)
        _publish_task_handoff_started(task_id=task_id, actor=caller_key)

        # ---- Steps 2 + 3 in try/finally so orphan is emitted on disconnect ----
        workflow_id: str | None = None
        pool_name: str = ""
        # Set to True by any inner ``except`` that has already emitted an
        # orphan event. The outer ``except Exception`` checks this flag
        # to avoid double-emission when step 3's failure bubbles up.
        orphan_handled = False
        try:
            dispatch_selector = params.pool_selector if params else "least_loaded"
            dispatch_timeout = (
                params.timeout_seconds
                if (params and params.timeout_seconds is not None)
                else timeout
            )

            try:
                dispatch_result = await pool_dispatch(
                    prompt=task_content,
                    pool_selector=dispatch_selector,
                    timeout=float(dispatch_timeout) if dispatch_timeout is not None else None,
                )
            except Exception:
                # Step 2 dispatch failure — no workflow exists, so emit
                # an orphan with workflow_id="" so the v1.1 sweeper can
                # tell step-2 from step-3 failures (Fix Round 1 #4).
                _publish_task_handoff_orphan(
                    task_id=task_id,
                    reason=_ORPHAN_REASON_STEP_2_DISPATCH_FAILED,
                    workflow_id="",
                )
                orphan_handled = True
                raise

            workflow_id = str(dispatch_result.get("workflow_id", ""))
            pool_name = str(dispatch_result.get("pool_id", ""))

            if not workflow_id:
                # The router succeeded but didn't give us a usable
                # workflow_id. Don't emit an orphan — the v1.1 sweeper
                # would chase a phantom (Fix Round 1 #5). Surface as a
                # typed caller-visible error instead.
                raise WorkflowNotReturnedError(
                    task_id=task_id,
                    dispatch_result=dispatch_result,
                )

            # ---- Step 3: write workflow_id back onto the task ----
            try:
                await update_task(
                    task_id=task_id,
                    metadata={"workflow_id": workflow_id},
                )
            except Exception:
                # Workflow is running, task not updated → orphan
                # with the canonical step-3 reason (Fix Round 1 #4).
                _publish_task_handoff_orphan(
                    task_id=task_id,
                    reason=_ORPHAN_REASON_STEP_3_UPDATE_FAILED,
                    workflow_id=workflow_id,
                )
                orphan_handled = True
                raise

            # ---- Event: handoff_completed ----
            _publish_task_handoff_completed(
                task_id=task_id,
                workflow_id=workflow_id,
                adapter=adapter,
                actor=caller_key,
            )

            return HandoffResult(
                task_id=task_id,
                workflow_id=workflow_id,
                adapter=adapter,
                started_at=started_at,
                pool_name=pool_name,
            )
        except asyncio.CancelledError:
            # Caller disconnected between step 2 and step 3 — workflow is
            # running, task not updated. Emit orphan so v1.1 sweeper can
            # re-link, then re-raise so callers see the cancellation.
            if not orphan_handled:
                _publish_task_handoff_orphan(
                    task_id=task_id,
                    reason="caller_disconnected",
                    workflow_id=workflow_id or "",
                )
            raise
        except WorkflowNotReturnedError:
            # Already typed — never emitted an orphan. Re-raise as-is.
            raise
        except Exception:
            # Catch-all for anything the inner branches didn't tag. If
            # step 2 returned a workflow_id but the failure happened
            # AFTER (e.g. step 3 fault OR a downstream consumer error),
            # tag the orphan with the unexpected_error reason so the
            # v1.1 sweeper can disambiguate.
            if workflow_id and not orphan_handled:
                _publish_task_handoff_orphan(
                    task_id=task_id,
                    reason=_ORPHAN_REASON_UNEXPECTED,
                    workflow_id=workflow_id,
                )
            raise


def _raise_rate_limited(exc: RateLimitError) -> None:
    """Log + re-raise :class:`RateLimitError`.

    Renamed from ``_rate_limited_envelope`` (Fix Round 1 #3): the helper
    has always raised — it never returned a :class:`HandoffResult`
    placeholder. The name now matches the behavior at the call site.

    Raising (not returning) keeps the :class:`HandoffResult` envelope
    contract honest: a rate-limit denial has no workflow yet, so the
    contract forbids returning one. FastMCP translates the raised
    exception into a structured error envelope upstream.
    """
    logger.warning("tasks_handoff_to_workflow rate-limited: %s", exc)
    raise exc
