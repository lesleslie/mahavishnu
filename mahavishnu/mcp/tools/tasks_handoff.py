"""The single dispatch edge from the Bodai task system to pool dispatch.

This module exposes the ``mahavishnu_tasks_handoff_to_workflow`` MCP tool. It is the
only dispatch edge in the task system: every other task tool (create /
update / complete / list / get) talks to session-buddy directly; this one
talks to session-buddy *and* to mahavishnu's pool router in sequence.

The flow is three sequential steps wrapped in try/finally so that a
disconnect between steps 2 and 3 emits ``task.handoff_orphan`` before
re-raising:

    1. session-buddy.tasks_get(task_id)         # load the task
    2. mahavishnu_pool_route_execute(prompt=task.content)  # dispatch
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


#: Errors that mean "the event publisher is not available".
#:
#: Held in a constant rather than written inline. ruff-format on Python
#: 3.14 rewrites ``except (A, B):`` into the unparenthesised PEP 758
#: form, which splits the clause over three lines and leaves the
#: ``noqa`` on the closing parenthesis -- a line ruff does not report
#: the diagnostic on, so the suppression stops applying and BLE001
#: fires anyway. The same pattern is used in
#: ``mahavishnu/bifrost/cache_headers.py``.
_PUBLISHER_ERRORS = (Exception,)


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
    MCP schema advertises valid values to clients.

    ``repo`` scopes the dispatch to ONE repository. It is required
    (directly or via the task's ``metadata["repo"]``): a durable
    workflow with no repo scope fans out over the whole repository
    catalog, which for a single task dispatch is a fleet-wide run.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    timeout_seconds: int | None = None
    repo: str | None = None
    idempotency_key: str | None = None
    extra_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class HandoffResult(BaseModel):
    """Result envelope returned by ``mahavishnu_tasks_handoff_to_workflow`` after
    step 2 (dispatch) succeeds.

    ``workflow_id`` is the identifier of the durable mahavishnu workflow
    the task was dispatched to; step 3 stores it on the task through
    session-buddy's ``tasks_link_workflow`` tool (the dedicated typed
    channel — NOT ``UpdateTaskRequest.metadata``).

    ``pool_name`` was dropped when the dispatch edge moved from the pool
    router to the durable-workflow path: a durable workflow has no pool.
    ``status`` and ``repos_processed`` are the fields that path returns.
    See ``docs/specs/2026-10-30-task-workflow-backlink-design.md``.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)]
    workflow_id: str
    adapter: _ADAPTER
    started_at: datetime
    status: str = "running"
    repos_processed: int = 0


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
    """Raised when the dispatch succeeded but did not return a
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
            f"[MHV-102] the dispatch did not return a workflow_id "
            f"for task {self.task_id}: {self.dispatch_result!r}"
        )


class NoRepoScopeError(Exception):
    """Raised when the handoff cannot scope the dispatch to a repository.

    A durable workflow with no repository scope runs over EVERY
    repository in the catalog. For a single task dispatch that is a
    fleet-wide run, so the handoff refuses rather than fanning out.

    The scope comes from ``params.repo`` or the task's
    ``metadata["repo"]``.
    """

    code: str = "MHV-103"

    def __init__(self, task_id: str, details: dict[str, Any] | None = None) -> None:
        self.task_id = str(task_id)
        self.details = {"task_id": self.task_id, **(details or {})}
        super().__init__(
            f"[MHV-103] Task {self.task_id} has no repository scope. Pass "
            f"params.repo, or set metadata['repo'] on the task -- an unscoped "
            f"dispatch would run over every repository in the catalog."
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
        raise ValueError(
            f"task content exceeds {_MAX_CONTENT_BYTES} bytes after sanitization"
        )
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

    def __init__(
        self, limit: int = _RATE_LIMIT_PER_MINUTE, window_seconds: int = 60
    ) -> None:
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
# Publisher — mahavishnu publishes its own task.* events
# ---------------------------------------------------------------------------
#
# These events used to be published through session-buddy's
# ``publish_task_event_raw``, which writes through a module-level
# publisher singleton that is assigned in EXACTLY one place in the fleet:
# inside the session-buddy server process. From mahavishnu it was
# therefore a silent no-op — every ``task.handoff_orphan`` event was
# never written, so the sweeper had nothing to consume and the v1.1
# error-handling matrix never ran.
#
# Mahavishnu now publishes onto the same ``bodai:events`` Redis stream
# itself, in the flat-fields XADD shape the stream adapter expects and
# the sweeper filters on (``payload["channel"]``).


#: The Redis Stream the task system's events live on. The same stream
#: the orphan sweeper consumes.
_BODAI_EVENTS_STREAM = "bodai:events"

_PUBLISHER_ADAPTER: Any | None = None


def _get_publisher_adapter() -> Any:
    """Return the process-wide Redis Streams publisher adapter."""
    global _PUBLISHER_ADAPTER
    if _PUBLISHER_ADAPTER is None:
        from oneiric.adapters.queue.redis_streams import (
            RedisStreamsQueueAdapter,
            RedisStreamsQueueSettings,
        )

        _PUBLISHER_ADAPTER = RedisStreamsQueueAdapter(
            settings=RedisStreamsQueueSettings(stream=_BODAI_EVENTS_STREAM),
        )
    return _PUBLISHER_ADAPTER


async def _publish_task_event(event_type: str, payload: dict[str, Any]) -> None:
    """Publish a ``task.*`` event onto the ``bodai:events`` stream.

    Best-effort: a failed audit publish must never block the caller.
    The event carries a ``channel`` field — the stream adapter writes
    flat fields, and consumers filter on ``payload["channel"]``.
    """
    try:
        adapter = _get_publisher_adapter()
    except _PUBLISHER_ERRORS as exc:  # publisher unavailable — best-effort audit event
        logger.warning("tasks_handoff: no event publisher available: %s", exc)
        return
    try:
        await adapter.enqueue({"channel": event_type, **payload})
    except Exception as exc:  # best-effort event publish — broad catch so a fire-and-forget audit event never blocks the caller  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
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


def _publish_task_handoff_orphan(
    task_id: str, reason: str, workflow_id: str = ""
) -> None:
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
# Session-buddy + mahavishnu_pool_route_execute call sites — module-level so tests
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


async def _session_buddy_link_workflow(
    task_id: str,
    workflow_id: str,
) -> dict[str, Any]:
    """Call session-buddy's ``tasks_link_workflow`` MCP tool.

    This is the ONLY channel that writes ``Task.workflow_id``. The
    generic ``tasks_update`` metadata bag cannot reach the field — a
    metadata dict is caller-supplied content whatever key it carries.
    """
    raise NotImplementedError(
        "tasks_handoff: no session_buddy_client bound — pass one via "
        "register_tasks_handoff_tools(..., session_buddy_client=...)"
    )


async def _dispatch_workflow(
    prompt: str,
    *,
    adapter: str = "prefect",
    repo: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Start a durable workflow for ``prompt`` and return immediately.

    Module-level so tests can monkeypatch it. Returns the dispatch
    envelope (``workflow_id``, ``status``, ``repos_processed``, ...).

    The workflow is FIRE-AND-FORGET: the call returns while the workflow
    is still running. That is what makes the orphan case meaningful — a
    failure to record the binding leaves a workflow that is alive but
    unlinked, which the sweeper can recover.
    """
    raise NotImplementedError(
        "tasks_handoff: no workflow_dispatch_fn bound — pass one via "
        "register_tasks_handoff_tools(..., workflow_dispatch_fn=...)"
    )


# ---------------------------------------------------------------------------
# Handoff step helpers
# ---------------------------------------------------------------------------
#
# The tool body below owns the rate-limit gate and delegates the
# three-step flow to :func:`_execute_handoff`. Each helper here owns ONE
# decision (dependency binding, repo scope, timeout, one orphan reason),
# so the flow stays readable and every function stays under the pyscn
# complexity ceiling.


def _resolve_handoff_dependencies(
    session_buddy_client: Any | None,
    workflow_dispatch_fn: Any | None,
) -> tuple[Any, Any, Any]:
    """Bind the injected dependencies (if any) at call time.

    A registration-time miss must not blow up test discovery, so the
    unbound case falls back to the module-level stubs that raise a clear
    ``NotImplementedError``.
    """
    get_task = (
        session_buddy_client.tasks_get
        if session_buddy_client is not None
        else _session_buddy_get_task
    )
    link_workflow = (
        session_buddy_client.tasks_link_workflow
        if session_buddy_client is not None
        else _session_buddy_link_workflow
    )
    dispatch = (
        workflow_dispatch_fn if workflow_dispatch_fn is not None else _dispatch_workflow
    )
    return get_task, link_workflow, dispatch


def _normalize_repo_scope(value: Any) -> str | None:
    """Return a usable repo scope, or ``None`` when there is none.

    An empty or whitespace-only value is no scope at all.
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _task_repo_scope(task: dict[str, Any]) -> str | None:
    """Return the repo scope named by the task's metadata, if any."""
    task_metadata = task.get("metadata")
    candidate = task_metadata.get("repo") if isinstance(task_metadata, dict) else None
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _resolve_repo_scope(
    params: HandoffParams | None,
    task: dict[str, Any],
    task_id: str,
) -> str:
    """Resolve the repository scope, or refuse the dispatch.

    The scope is normalised here, once, because the call site turns a
    falsy repo into ``repos=None`` -- the *unrestricted* dispatch this
    check exists to refuse. An empty or whitespace-only value is no
    scope at all, so it falls back to the task's metadata and is refused
    if the metadata does not name one either.
    """
    repo = _normalize_repo_scope(params.repo if params else None)
    if not repo:
        repo = _task_repo_scope(task)
    if not repo:
        raise NoRepoScopeError(task_id)
    return repo


def _resolve_dispatch_timeout(
    params: HandoffParams | None,
    timeout: int | None,
) -> float | None:
    """Resolve the dispatch timeout: ``params`` first, then the argument."""
    dispatch_timeout = (
        params.timeout_seconds
        if (params and params.timeout_seconds is not None)
        else timeout
    )
    return float(dispatch_timeout) if dispatch_timeout is not None else None


def _raise_if_workflow_id_missing(
    task_id: str,
    workflow_id: str,
    dispatch_result: dict[str, Any],
) -> None:
    """Refuse a dispatch that came back without a usable workflow id.

    The dispatch succeeded but didn't give us a usable ``workflow_id``.
    Don't emit an orphan -- the sweeper would chase a phantom (Fix
    Round 1 #5). Surface as a typed caller-visible error instead.

    ``"unknown"`` is the literal the durable path returns when the
    adapter produced no id, so it has to be rejected here or every task
    would end up bound to a workflow called "unknown".
    """
    if not workflow_id or workflow_id == "unknown":
        raise WorkflowNotReturnedError(
            task_id=task_id,
            dispatch_result=dispatch_result,
        )


def _emit_step2_dispatch_orphan(task_id: str) -> None:
    """Emit the step-2 orphan marker (no workflow exists yet).

    Step 2 dispatch failure -- no workflow exists, so emit an orphan
    with ``workflow_id=""`` so the v1.1 sweeper can tell step-2 from
    step-3 failures (Fix Round 1 #4).
    """
    _publish_task_handoff_orphan(
        task_id=task_id,
        reason=_ORPHAN_REASON_STEP_2_DISPATCH_FAILED,
        workflow_id="",
    )


def _emit_step3_update_orphan(task_id: str, workflow_id: str) -> None:
    """Emit the step-3 orphan marker (the workflow is alive, unlinked).

    Workflow is running, task not linked -> orphan with the canonical
    step-3 reason (Fix Round 1 #4).
    """
    _publish_task_handoff_orphan(
        task_id=task_id,
        reason=_ORPHAN_REASON_STEP_3_UPDATE_FAILED,
        workflow_id=workflow_id,
    )


def _emit_caller_disconnected_orphan(
    task_id: str,
    workflow_id: str | None,
) -> None:
    """Emit the cancellation orphan marker (the caller vanished mid-flight).

    Caller disconnected between step 2 and step 3 -- workflow is
    running, task not updated. Emit orphan so v1.1 sweeper can re-link,
    then the caller sees the cancellation.
    """
    _publish_task_handoff_orphan(
        task_id=task_id,
        reason="caller_disconnected",
        workflow_id=workflow_id or "",
    )


def _emit_unexpected_orphan(task_id: str, workflow_id: str) -> None:
    """Emit the unexpected-failure orphan marker.

    Catch-all for anything the inner branches didn't tag. If step 2
    returned a workflow_id but the failure happened AFTER (e.g. step 3
    fault OR a downstream consumer error), tag the orphan with the
    unexpected_error reason so the v1.1 sweeper can disambiguate.
    """
    _publish_task_handoff_orphan(
        task_id=task_id,
        reason=_ORPHAN_REASON_UNEXPECTED,
        workflow_id=workflow_id,
    )


async def _execute_handoff(
    task_id: str,
    adapter: _ADAPTER,
    params: HandoffParams | None,
    timeout: int | None,
    caller_key: str,
    session_buddy_client: Any | None,
    workflow_dispatch_fn: Any | None,
) -> HandoffResult:
    """Run the three-step handoff and return the result envelope.

    Step 1 loads the task, step 2 dispatches the durable workflow, step
    3 binds the resulting ``workflow_id`` back to the task. Steps 2 + 3
    live in one try/except so a disconnect between them emits
    ``task.handoff_orphan`` before re-raising.
    """
    get_task, link_workflow, dispatch = _resolve_handoff_dependencies(
        session_buddy_client,
        workflow_dispatch_fn,
    )

    # ---- Step 1: lookup ----
    try:
        task = await get_task(task_id=task_id)
    except Exception as exc:  # session-buddy lookup — broad catch re-raises typed TaskNotFoundError regardless of underlying session-buddy exception
        raise TaskNotFoundError(task_id, details={"cause": type(exc).__name__}) from exc

    # Content must be dispatch-safe (mirrors session-buddy's sanitizer).
    task_content = _validate_task_content_for_dispatch(str(task.get("content", "")))

    # Repo scope. A durable workflow with no scope runs over every
    # repository in the catalog, so an unscoped dispatch is refused
    # rather than fanned out.
    repo = _resolve_repo_scope(params, task, task_id)

    # ---- Event: handoff_started ----
    started_at = datetime.now(UTC)
    _publish_task_handoff_started(task_id=task_id, actor=caller_key)

    # ---- Steps 2 + 3 in try/finally so orphan is emitted on disconnect ----
    workflow_id: str | None = None
    dispatch_status = "running"
    repos_processed = 0
    # Set to True by any inner ``except`` that has already emitted an
    # orphan event. The outer ``except Exception`` checks this flag
    # to avoid double-emission when step 3's failure bubbles up.
    orphan_handled = False
    try:
        dispatch_timeout = _resolve_dispatch_timeout(params, timeout)

        try:
            dispatch_result = await dispatch(
                prompt=task_content,
                adapter=adapter,
                repo=repo,
                timeout=dispatch_timeout,
            )
        except Exception:  # step-2 dispatch failure — broad catch to emit orphan marker then re-raise as typed HandoffError
            _emit_step2_dispatch_orphan(task_id)
            orphan_handled = True
            raise

        workflow_id = str(dispatch_result.get("workflow_id", "") or "")
        dispatch_status = str(dispatch_result.get("status", "running") or "running")
        repos_processed = int(dispatch_result.get("repos_processed", 0) or 0)

        _raise_if_workflow_id_missing(task_id, workflow_id, dispatch_result)

        # ---- Step 3: bind the workflow to the task ----
        # req: REQ-TASKLINK-006, REQ-TASKLINK-001
        try:
            await link_workflow(
                task_id=task_id,
                workflow_id=workflow_id,
            )
        except Exception:  # step-3 back-link failure — broad catch to emit orphan marker then re-raise (workflow is alive, just task not updated)
            _emit_step3_update_orphan(task_id, workflow_id)
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
            status=dispatch_status,
            repos_processed=repos_processed,
        )
    except asyncio.CancelledError:
        if not orphan_handled:
            _emit_caller_disconnected_orphan(task_id, workflow_id)
        raise
    except WorkflowNotReturnedError:
        # Already typed — never emitted an orphan. Re-raise as-is.
        raise
    except Exception:  # MCP tool error handler — broad catch tags unexpected failure as orphan (workflow_id unknown) then re-raises
        if workflow_id and not orphan_handled:
            _emit_unexpected_orphan(task_id, workflow_id)
        raise


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tasks_handoff_tools(
    mcp: FastMCP,
    *,
    session_buddy_client: Any | None = None,
    workflow_dispatch_fn: Any | None = None,
) -> bool:
    """Register ``mahavishnu_tasks_handoff_to_workflow`` with the FastMCP server.

    Args:
        mcp: FastMCP server instance (T18 wires this via profiles.py).
        session_buddy_client: Optional object exposing ``tasks_get`` and
            ``tasks_link_workflow`` awaitables (any duck-type —
            typically the session-buddy MCP client wired through
            MahavishnuSettings). When ``None``, the tool body raises a
            clear ``NotImplementedError`` rather than crashing on import.
        workflow_dispatch_fn: Optional callable that starts a durable
            workflow and returns its dispatch envelope. When ``None``,
            the tool body raises a clear ``NotImplementedError``.

    Both arguments are intentionally optional so this module can be
    imported by test suites that exercise just the validation /
    rate-limit / event-publish branches without binding the upstream
    clients.

    Returns:
        ``True`` when the tool was registered, ``False`` when the
        installed session-buddy does not provide a usable task-system
        contract (missing, outdated, or failing to import).

        This does NOT raise on a contract mismatch. The registration
        runs inside ``FastMCPServer.__init__``, so raising here would
        take the WHOLE mahavishnu MCP server down over one missing
        tool. A version skew should cost the fleet the handoff edge, not
        the orchestrator.
    """
    # Registration-time gate (Fix Round 1 #2): surface session-buddy
    # absence once, at registration, not on every call.
    if not tasks_handoff_to_workflow_available():
        logger.warning(
            "mahavishnu_tasks_handoff_to_workflow NOT registered — the installed "
            "session-buddy does not provide a usable task-system "
            "contract (missing, outdated, or failing to import)"
        )
        return False

    # req: REQ-CX2-001
    @mcp.tool()
    async def mahavishnu_tasks_handoff_to_workflow(  # req: REQ-TASKLINK-007
        task_id: Annotated[str, Field(pattern=TASK_ID_PATTERN)],
        adapter: _ADAPTER = "prefect",
        params: HandoffParams | None = None,
        timeout: int | None = None,
    ) -> HandoffResult:
        """Dispatch a session-buddy task to a Mahavishnu workflow.

        Single dispatch edge: looks up the task, starts a durable
        workflow, then binds the resulting ``workflow_id`` to the task
        through session-buddy's ``tasks_link_workflow``. The workflow
        runs FIRE-AND-FORGET, so the task is bound to a workflow that is
        still running; a failure between steps 2 and 3 emits
        ``task.handoff_orphan`` so the sweeper can re-link later.

        The dispatch is scoped to ONE repository. Without an explicit
        scope the durable path fans out over the whole repository
        catalog, which for a single task is a fleet-wide run — so the
        scope comes from ``params.repo`` or the task's
        ``metadata["repo"]``, and a task with neither is refused.

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
        # registration-time miss doesn't blow up test discovery, then
        # run the three-step flow.
        return await _execute_handoff(
            task_id=task_id,
            adapter=adapter,
            params=params,
            timeout=timeout,
            caller_key=caller_key,
            session_buddy_client=session_buddy_client,
            workflow_dispatch_fn=workflow_dispatch_fn,
        )

    # The tool is registered. Returning ``True`` is the contract the caller
    # checks; without it the function falls off the end and implicitly
    # returns ``None``, which is not assignable to the declared ``bool``.
    return True


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
    logger.warning("mahavishnu_tasks_handoff_to_workflow rate-limited: %s", exc)
    raise exc
