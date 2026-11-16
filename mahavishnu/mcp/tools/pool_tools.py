"""Pool management MCP tools."""

from __future__ import annotations

import asyncio
import contextlib
from functools import partial
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

# Runtime import, NOT a type-checking-only import. FastMCP resolves the
# injected-context parameter via ``get_type_hints(fn)``; under
# ``from __future__ import annotations`` that call evaluates the annotation
# string against the module globals. A TYPE_CHECKING-only import would
# leave ``Context`` absent from the globals, ``get_type_hints`` would
# raise NameError, FastMCP would fall back to the raw string annotation,
# and the context would never be injected -- the progress heartbeat
# would silently never run.
from mcp_common.fastmcp import Context  # noqa: TC002

from mahavishnu.core._producer_metrics import (
    WORKTREE_ACTIVE_COUNT,
    WORKTREE_CREATION_TOTAL,
    WORKTREE_ISOLATION_REFUSALS_TOTAL,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from mcp_common.fastmcp import FastMCP

    # The runtime ``TaskCategory`` name below is a possibly-None sentinel
    # (defensive import), so annotations must reference the real class.
    from mahavishnu.core.model_routing import TaskCategory as TaskCategoryType

try:
    from mahavishnu.pools.memory_aggregator import MemoryAggregator
except Exception:  # pragma: no cover - optional import for test patching  # module-level import fallback for test patching  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
    MemoryAggregator = None

try:
    # Phase 2m (Plan v3): mahavishnu_pool_route_execute needs the selector enum, the
    # caller_kind quota attribution enum, the coerce_caller_kind funnel,
    # and the quota error type. Each is defensive-imported so test patching
    # can inject sentinel versions without instantiating the full pools
    # package on import.
    from mahavishnu.core.errors import RateLimitError
    from mahavishnu.pools.base import PoolConfig as RuntimePoolConfig
    from mahavishnu.pools.manager import CallerKind, PoolSelector, coerce_caller_kind
except Exception:  # pragma: no cover - optional import for test patching  # module-level defensive import fallback  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
    PoolSelector = None
    CallerKind = None
    RateLimitError = None
    RuntimePoolConfig = None
    coerce_caller_kind = None

try:
    # C-9: per-TaskCategory concurrency gate (REQ-012, REQ-013).
    # Defensive import so test patching can inject a sentinel gate.
    from mahavishnu.core.concurrency_gate import ConcurrencyGate
    from mahavishnu.core.config import get_settings
    from mahavishnu.core.model_routing import (
        TaskCategory,
        classify_task,
        resolve_model_id,
    )
    from mahavishnu.core.rate_limit import _estimate_retry
except Exception:  # pragma: no cover - optional import for test patching  # module-level defensive import fallback  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
    ConcurrencyGate = None
    TaskCategory = None
    classify_task = None
    resolve_model_id = None
    _estimate_retry = None
    get_settings = None

try:
    # C-6: idempotency layer (REQ-006/007/008). Defensive import so tests can
    # inject sentinels via ``set_idempotency_store(None)`` without forcing the
    # full event_store stack to import on every test.
    from mahavishnu.core.errors import (
        IdempotencyCircuitOpen,
        IdempotencyStoreUnavailable,
    )
    from mahavishnu.core.event_store import TaskEventType
    from mahavishnu.core.idempotency import (
        IdempotencyCircuitBreaker,
        IdempotencyOptions,
        IdempotencyStore,
        get_idempotency_breaker,
        get_idempotency_store,
        set_idempotency_breaker,
        set_idempotency_store,
    )
except Exception:  # pragma: no cover - optional import for test patching  # module-level defensive import fallback  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
    IdempotencyCircuitOpen = None
    IdempotencyStoreUnavailable = None
    TaskEventType = None
    IdempotencyCircuitBreaker = None
    IdempotencyOptions = None
    IdempotencyStore = None
    get_idempotency_store = lambda: None
    set_idempotency_store = lambda _store: None
    get_idempotency_breaker = lambda: None
    set_idempotency_breaker = lambda _breaker: None

try:
    # C-8: worktree isolation (REQ-010/011). Defensive import so tests can
    # patch ``WorktreeManager`` without forcing the full event_store stack
    # to import on every test.
    from mahavishnu.core.errors import WorktreeError, WorktreeLockedError
    from mahavishnu.core.worktree_manager import WorktreeInfo, WorktreeManager
    from mahavishnu.core.worktree_options import WorktreeOptions
except Exception:  # pragma: no cover - optional import for test patching  # module-level defensive import fallback  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
    WorktreeError = None
    WorktreeLockedError = None
    WorktreeInfo = None
    WorktreeManager = None
    WorktreeOptions = None

logger = logging.getLogger(__name__)


# Module-level singleton gate (per-process scope documented in
# ``docs/runbooks/CONCURRENCY_LIMIT_STORM.md``). Test suites that want
# isolation call ``set_concurrency_gate()`` to swap this out.
_concurrency_gate: ConcurrencyGate | None = (
    ConcurrencyGate(get_settings().concurrency_limits)
    if ConcurrencyGate is not None and get_settings is not None
    else None
)


def get_concurrency_gate() -> ConcurrencyGate | None:
    """Return the module-level ``ConcurrencyGate`` (None when not configured)."""
    return _concurrency_gate


def set_concurrency_gate(gate: ConcurrencyGate | None) -> None:
    """Override the module-level gate (test seam; resets between cases)."""
    global _concurrency_gate
    _concurrency_gate = gate


# ---------------------------------------------------------------------------
# C-8 worktree helpers (REQ-010).
# Module-level so tests can monkeypatch them via
# ``patch("mahavishnu.mcp.tools.pool_tools._repo_has_git", ...)``.
# ---------------------------------------------------------------------------


#: The marker a dispatch prompt uses to name the repository a
#: worktree-isolated run should fork from. The token is read only from
#: a line that starts with this marker, so a prompt that merely
#: *mentions* a repository does not silently become the isolation
#: target.
REPOSITORY_MARKER = "Repository:"


async def _resolve_repo_nickname(prompt: str) -> str:
    """Read the repository a dispatch asks to isolate, if it names one.

    Returns an empty string when the prompt names no repository — the
    caller then isolates in the server's own working directory, which
    is what a dispatch without a named repository has always done.

    The token is read from a line introduced by ``Repository:`` and
    ending in ``.git``. It may be relative — resolved against the
    server's working directory — or absolute, which is what a dispatch
    about another repository has to use: the server's working directory
    is its *own* checkout, so a relative token can only ever name a
    repository beside it. The absolute form is checked against the
    operator's allowed repository roots before anything is created (see
    :func:`_validate_repo_path`).

    Scanning the whole prompt for a ``.git`` token was the first
    implementation, and it was wrong in a way that broke ordinary
    dispatches: a prompt that merely mentions a repository — a URL in a
    bug report, an SSH remote in a clone instruction — turned the
    dispatch into a refusal, because the mentioned path is not the
    repository the caller wanted isolated and is usually not a local
    path at all. Only a line that names the repository counts now.

    The original text is scanned, not a lowercased copy of it: a path
    carries case, and a lowercased path is a different path.
    """
    if not prompt:
        return ""
    marker = REPOSITORY_MARKER.lower()
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith(marker):
            continue
        value = stripped[len(REPOSITORY_MARKER) :].strip()
        token = value.split()[0] if value else ""
        if token.lower().endswith(".git"):
            return token[: -len(".git")]
    return ""


def _resolve_repo_path(repo_nickname: str) -> Path:
    """Resolve ``repo_nickname`` to a filesystem path.

    An absolute nickname is taken as it stands; a relative one is
    resolved against the current working directory. An empty nickname
    means the server's own working directory — pool_tools tests
    exercise this branch to keep the worktree path deterministic.
    """
    from pathlib import Path as _Path

    if not repo_nickname:
        return _Path.cwd()
    candidate = _Path(repo_nickname)
    if candidate.is_absolute():
        return candidate
    return _Path.cwd() / repo_nickname


async def _path_is_git_repo(path: Path) -> bool:
    """Return True when ``path`` is a git working tree.

    Returns ``False`` when the path does not exist or is not a git
    working tree.
    """
    if not path.exists():
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(path),
            "rev-parse",
            "--is-inside-work-tree",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except Exception:  # subprocess probing helper — broad catch to return False on any failure  # MCP tool error handler — broad catch is the documented contract  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return False
    return proc.returncode == 0 and stdout.decode().strip() == "true"


async def _repo_has_git(repo_nickname: str) -> bool:
    """Return True when the resolved repo path is a git working tree.

    Returns ``False`` when the path does not exist or is not a git
    working tree — gates the worktree-isolation path in
    ``mahavishnu_pool_route_execute``.
    """

    return await _path_is_git_repo(_resolve_repo_path(repo_nickname))


async def _resolve_worktree_repo(prompt: str) -> tuple[Path | None, str]:
    """Resolve the repository the isolated worktree is forked from.

    The dispatch prompt names the repository, by a ``.git``-suffixed
    token on a ``Repository:`` line: relative for the server's own
    repository, absolute for any other one. The absolute form is
    checked against the operator's allowed repository roots before
    anything is created — creating a worktree of a repository is a
    security boundary, and an unchecked path would let a dispatch name
    anything readable on the host.

    Returns ``(path, REPO_ALLOWED)`` when the repository resolved and
    is authorized, and ``(None, reason)`` otherwise. The caller turns
    the refusal into a message that names the reason, because the
    operator's remedy is different for each.
    """
    repo_nickname = await _resolve_repo_nickname(prompt)
    candidate = _resolve_repo_path(repo_nickname)
    validated, reason = _validate_repo_path(candidate)
    if validated is None:
        return None, reason
    if not await _path_is_git_repo(validated):
        logger.warning(
            "repository %s is not a git working tree",
            validated,
            extra={"error_id": "WORKTREE_REPO_NOT_A_GIT_REPO"},
        )
        return None, REPO_NOT_A_GIT_REPO
    return validated, REPO_ALLOWED


#: Why a repository was refused. The reasons are separate because the
#: operator's remedy differs for each: a repository that does not
#: resolve is a wrong prompt, a repository that is not authorized is a
#: policy decision, and settings that cannot be read is a broken
#: server. Reporting all three as "could not be resolved" sends the
#: operator to fix the wrong thing.
REPO_ALLOWED = "allowed"
REPO_NOT_AUTHORIZED = "not_authorized"
REPO_UNRESOLVED = "unresolved"
REPO_NOT_A_GIT_REPO = "not_a_git_repo"
REPO_SETTINGS_UNAVAILABLE = "settings_unavailable"


def _isolation_refusal_message(reason: str) -> str:
    """The refusal text for a repository that cannot be isolated.

    The refusal is the operator's only signal — the dispatch did not
    happen, so nothing else will tell them why — so it has to name the
    thing to fix. A wrong prompt, a policy decision and a broken
    server are three different problems, and one message covering all
    three sends the operator to fix the wrong one.
    """
    if reason == REPO_NOT_AUTHORIZED:
        return (
            "worktree isolation was requested but the repository named in "
            "the dispatch prompt is not inside an allowed repository root; "
            "the task was not dispatched rather than run in the shared "
            "checkout. Add the repository to 'allowed_repo_paths' in the "
            "Mahavishnu settings, or name an allowed repository in the "
            "dispatch prompt as '<repo path>/.git'."
        )
    if reason == REPO_UNRESOLVED:
        return (
            "worktree isolation was requested but the repository named in "
            "the dispatch prompt does not resolve to a local path; the task "
            "was not dispatched rather than run in the shared checkout. "
            "Name the repository in the dispatch prompt as '<repo path>/.git'."
        )
    if reason == REPO_NOT_A_GIT_REPO:
        return (
            "worktree isolation was requested but the repository named in "
            "the dispatch prompt is not a git working tree; the task was not "
            "dispatched rather than run in the shared checkout. Name a git "
            "repository in the dispatch prompt as '<repo path>/.git'."
        )
    if reason == REPO_SETTINGS_UNAVAILABLE:
        return (
            "worktree isolation was requested but the allowed repository "
            "roots could not be read, so no repository could be trusted to "
            "isolate; the task was not dispatched rather than run in the "
            "shared checkout. Check the Mahavishnu settings, then retry."
        )
    return (
        "worktree isolation was requested but the repository to isolate "
        "could not be resolved; the task was not dispatched rather than run "
        "in the shared checkout. Name the repository in the dispatch prompt "
        "as '<repo path>/.git'."
    )


def _validate_repo_path(path: Path) -> tuple[Path | None, str]:
    """Return the canonical repository path and the reason it was refused.

    The pool may create a worktree of a repository, so the repository
    it is allowed to name is a security boundary. The operator's
    authorized roots come from the settings (``allowed_repo_paths``),
    and the same ``PathValidator`` the rest of the codebase uses does
    the checking: it resolves the path, rejects traversal, and refuses
    a path outside the allowed roots.

    Returns ``(path, REPO_ALLOWED)`` when the path is authorized, and
    ``(None, reason)`` otherwise. A repository the operator has not
    authorized is refused the same way an unresolvable one is: the
    dispatch does not happen.
    """
    if get_settings is None:
        return None, REPO_SETTINGS_UNAVAILABLE
    try:
        settings = get_settings()
    except Exception:  # settings are a boundary, not a dependency
        logger.exception(
            "cannot read the allowed repository roots; refusing to isolate",
            extra={"error_id": "WORKTREE_REPO_VALIDATION_UNAVAILABLE"},
        )
        return None, REPO_SETTINGS_UNAVAILABLE
    allowed = list(getattr(settings, "allowed_repo_paths", []) or [])
    if not allowed:
        logger.warning(
            "no allowed repository roots are configured; refusing to isolate",
            extra={"error_id": "WORKTREE_REPO_NOT_ALLOWED"},
        )
        return None, REPO_NOT_AUTHORIZED

    # A path that does not exist is a different failure from a path
    # outside the allowed roots, and the validator reports both the
    # same way. The existence check comes first so the refusal can
    # name the real reason.
    if not path.exists():
        logger.warning(
            "repository %s does not exist",
            path,
            extra={"error_id": "WORKTREE_REPO_UNRESOLVED"},
        )
        return None, REPO_UNRESOLVED

    from mahavishnu.core.validators import PathValidator

    validator = PathValidator(allowed_base_dirs=allowed)
    try:
        return validator.validate_path(path, must_exist=True), REPO_ALLOWED
    except Exception:  # an unauthorized path is refused, not raised  # noqa: BLE001
        logger.warning(
            "repository %s is not inside an allowed repository root",
            path,
            extra={"error_id": "WORKTREE_REPO_NOT_ALLOWED"},
        )
        return None, REPO_NOT_AUTHORIZED


def _get_worktree_manager() -> WorktreeManager | None:
    """Return a per-process ``WorktreeManager`` singleton.

    Returns ``None`` when the class failed to import (defensive-import
    branch) so callers fall back to host isolation rather than crash.
    """
    global _worktree_manager_singleton
    if WorktreeManager is None:
        return None
    if _worktree_manager_singleton is None:
        _worktree_manager_singleton = WorktreeManager()
    return _worktree_manager_singleton


_worktree_manager_singleton: WorktreeManager | None = None


def _set_worktree_manager(mgr: WorktreeManager | None) -> None:
    """Test seam: override the module-level worktree manager singleton."""
    global _worktree_manager_singleton
    _worktree_manager_singleton = mgr


async def _dispatch_internal(
    prompt: str,
    pool_selector: Any,
    execution_id: str,
    pool_affinity: str | None,
    coerced_kind: Any,
    parent_session_id: str | None,
    auto_spawn: bool | None,
    pool_manager: Any,
    timeout: float | None = None,
    cwd: str | None = None,
):
    """Internal dispatch helper used when a worktree path is active.

    Mirrors the inline dispatch in ``mahavishnu_pool_route_execute`` so the worktree
    finally-block can wrap it cleanly. Returns the same ``dict`` shape as
    ``pool_manager.route_task``.

    ``timeout`` is forwarded into the task dict because the worker's
    own execute timeout is read from ``task["timeout"]``. Without it the
    worker's default (300s) applies regardless of what the caller asked
    for, so a long-running task is killed mid-flight while the caller
    believes it was given a larger budget.

    ``cwd`` rides the task dict the same way, and names the directory the
    worker session starts in. It is how worktree isolation reaches the
    worker: the pool reads ``task["cwd"]`` and launches the session there.
    """
    task = {"prompt": prompt}
    if timeout is not None:
        task["timeout"] = timeout
    if cwd is not None:
        task["cwd"] = cwd
    return await pool_manager.route_task(
        task=task,
        pool_selector=pool_selector,
        pool_affinity=pool_affinity,
        caller_kind=coerced_kind if coerced_kind is not None else "claude_code",
        parent_session_id=parent_session_id,
        auto_spawn=auto_spawn,
    )


# How often the dispatch heartbeat reports liveness. The MCP client's
# idle timer is reset by every progress notification, so the interval
# only has to be comfortably below that timer -- it does not need to be
# short. 20s keeps a 600s idle window refreshed with a wide margin.
_PROGRESS_HEARTBEAT_SECONDS = 20.0


class _ProgressReporter(Protocol):
    """The one method of FastMCP's ``Context`` the heartbeat needs.

    Declaring the dependency structurally keeps the heartbeat testable
    without constructing a live request context, and keeps the helper
    independent of which FastMCP version supplies ``Context``.
    """

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None: ...


async def _dispatch_with_progress(
    ctx: _ProgressReporter | None,
    dispatch: Callable[[], Awaitable[dict[str, Any]]],
    *,
    interval: float | None = None,
) -> dict[str, Any]:
    """Await a dispatch, reporting liveness while it runs.

    A pool dispatch can legitimately take longer than the MCP client's
    idle window: a multi-file refactor runs for minutes with nothing to
    say. The client's idle timer aborts a tool call that produces
    neither a response nor a progress notification for that window, so a
    long dispatch dies at the idle timeout even though the server is
    working perfectly.

    The heartbeat closes that gap. While the dispatch is in flight it
    emits a periodic progress notification, which resets the client's
    idle clock. It does NOT extend the client's wall-clock cap -- a
    wedged dispatch still dies at the cap rather than hanging forever.

    ``ctx`` is ``None`` when the tool is called directly (the test
    suite) or when the client did not supply a progress token. In both
    cases the dispatch runs exactly as it did before, with no heartbeat
    and no behaviour change.

    Progress reporting is best-effort: a disconnected client must not
    turn a successful dispatch into a failed one.
    """
    if ctx is None:
        # req: REQ-DSPROG-003 -- no client progress token: run untouched.
        return await dispatch()
    # Resolved at call time, not bound as a default, so the module
    # constant stays the single source of truth for the interval.
    tick = _PROGRESS_HEARTBEAT_SECONDS if interval is None else interval

    async def _heartbeat() -> None:
        # req: REQ-DSPROG-001 -- report liveness for the whole dispatch.
        started = time.monotonic()
        while True:
            await asyncio.sleep(tick)
            elapsed = int(time.monotonic() - started)
            try:
                await ctx.report_progress(
                    elapsed, None, f"pool dispatch in progress ({elapsed}s elapsed)"
                )
            except Exception:  # progress is advisory; never fail the dispatch
                logger.debug("dispatch progress report failed", exc_info=True)

    heartbeat = asyncio.create_task(_heartbeat())
    try:
        return await dispatch()
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat


async def _hash_prompt(prompt: str) -> str:
    """SHA-256 hex digest of the dispatch prompt text.

    Used as the ``payload_hash`` for the idempotency fingerprint so a
    duplicate dispatch with the same prompt produces the same key.
    Async because Oneiric ``HashAction.execute`` is async.
    """
    from oneiric.actions.compression import HashAction

    result = await HashAction().execute({"algorithm": "sha256", "data": prompt})
    return result["digest"]


async def _enforce_concurrency_limit(
    task_category: TaskCategory, pool_id: str | None
) -> None:
    """Acquire a TaskCategory slot or raise RateLimitError (fail-closed).

    No-op when the gate is unconfigured (defensive-import failure in tests)
    or when no spec is registered for the category. Otherwise the gate
    returns False on saturation and we raise — callers MUST NOT silently
    proceed past a denial (REQ-013 fail-closed default).
    """
    gate = get_concurrency_gate()
    if gate is None or task_category is None:
        return
    if not await gate.try_acquire(task_category, pool_id):
        spec = gate.spec_for(task_category)
        if RateLimitError is None:
            # Sentinel: defensive import failed. ``enforce_concurrency_limit``
            # is fire-and-forget — returning None is the documented contract.
            return
        raise RateLimitError(
            limit=spec.concurrency_limit if spec else None,
            retry_after_seconds=_estimate_retry(spec) if _estimate_retry else None,
            domain=f"task_category={task_category.value}",
        )


# ---------------------------------------------------------------------------
# mahavishnu_pool_route_execute decomposition.
# req: REQ-CX-001
#
# The dispatch tool is a linear pipeline with many early-exit branches.
# Each helper below owns exactly one concern. Helpers that can abort the
# dispatch return an explicit "early response" payload that the tool
# returns verbatim, so no response shape is lost in the extraction.
# ---------------------------------------------------------------------------


def _resolve_pool_selector(pool_selector: str) -> tuple[Any, dict[str, Any] | None]:
    """Resolve the wire selector string into a ``PoolSelector`` enum.

    Returns ``(selector, None)`` on success. On failure returns
    ``(None, response)`` where ``response`` is the structured payload
    the tool must return verbatim.
    """
    if PoolSelector is None:
        return None, {
            "status": "failed",
            "error": "Pool selector subsystem unavailable; pools package not loaded",
        }
    try:
        return PoolSelector(pool_selector), None
    except ValueError:
        valid = [s.value for s in PoolSelector]
        return None, {
            "status": "invalid_selector",
            "error": f"Unknown pool_selector: {pool_selector!r}. Valid: {valid}",
        }


def _coerce_caller_kind(caller_kind: str) -> Any:
    """Map the wire caller-kind string onto a ``CallerKind`` enum.

    ``coerce_caller_kind`` maps unknown wire strings to
    ``CallerKind.UNKNOWN`` (one shared bucket per the indirection
    rule). A failure inside that funnel degrades to ``None`` (no
    bucket) rather than failing the dispatch.
    """
    if coerce_caller_kind is None:
        return None
    try:
        return coerce_caller_kind(caller_kind)
    except Exception:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return None


def _classify_prompt(prompt: str) -> TaskCategoryType | None:
    """Classify the prompt into a ``TaskCategory``.

    Returns ``None`` when the classifier is unavailable or fails — the
    dispatch then proceeds without a per-category concurrency limit.
    """
    if classify_task is None:
        return None
    try:
        return classify_task(prompt)
    except Exception:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return None


def _resolve_auto_spawn(auto_spawn: bool | None) -> bool:
    """Resolve ``auto_spawn`` from config when the caller did not specify.

    ``None`` means "read settings"; ``False``/``True`` are explicit
    caller overrides. A settings failure falls back to ``False`` so a
    dispatch never auto-spawns a pool it could not confirm.
    """
    if auto_spawn is not None:
        return auto_spawn
    if get_settings is None:
        return False
    try:
        return get_settings().pools.auto_spawn
    except Exception:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return False


def _log_routed_model(task_category: TaskCategoryType | None) -> None:
    """Log the model the dispatch was routed to, when routing is known.

    The routing table is resolved per task category, so the log line is
    how the audit trail records which model actually ran the work. Both
    the resolver and the category are absent when the routing layer is
    not configured, and then there is nothing to log.
    """
    if resolve_model_id is None or task_category is None:
        return
    logger.info(
        "mahavishnu_pool_route_execute: dispatch routed to model %s (category=%s)",
        resolve_model_id(task_category),
        task_category.value,
    )


async def _lookup_idempotency(
    idempotency: IdempotencyOptions | None,
    prompt: str,
) -> tuple[Any, Any, Any, dict[str, Any] | None]:
    """Look up (or create) the idempotency record for this dispatch.

    Returns ``(existing_event, idem_store, breaker, early_response)``.
    ``early_response`` is set when the tool must return without
    dispatching: a cached duplicate, or a fail-closed store error.
    """
    if idempotency is None:
        return None, None, None, None

    idem_store = get_idempotency_store() if get_idempotency_store is not None else None
    breaker = get_idempotency_breaker() if get_idempotency_breaker is not None else None
    if idem_store is None or breaker is None:
        logger.exception(
            "idempotency requested but layer not configured",
            extra={"error_id": "IDEMPOTENCY_NOT_CONFIGURED"},
        )
        return (
            None,
            None,
            None,
            {
                "status": "error",
                "error": "idempotency store unavailable",
            },
        )

    try:
        # Pre-compute the payload hash so the lambda stays sync;
        # _hash_prompt is async and would otherwise force an
        # ``await`` inside the lambda (syntax error in sync code).
        payload_hash = await _hash_prompt(prompt)
        existing_event = await breaker.call(
            lambda: idem_store.get_or_create(
                idempotency,
                payload_hash=payload_hash,
                actor="mahavishnu_pool_route_execute",
            )
        )
    except IdempotencyStoreUnavailable as exc:  # ty: ignore[invalid-exception-caught]
        logger.exception(
            "idempotency store unreachable; failing closed",
            extra={"error_id": "IDEMPOTENCY_STORE_UNAVAILABLE"},
        )
        return (
            None,
            idem_store,
            breaker,
            {
                "status": "error",
                "error": f"idempotency store unavailable: {exc}",
            },
        )
    except IdempotencyCircuitOpen as exc:  # ty: ignore[invalid-exception-caught]
        logger.warning(
            "idempotency circuit open; failing closed",
            extra={"error_id": "IDEMPOTENCY_CIRCUIT_OPEN"},
        )
        return (
            None,
            idem_store,
            breaker,
            {
                "status": "error",
                "error": f"idempotency circuit open: {exc}",
            },
        )

    if (
        existing_event is not None
        and TaskEventType is not None
        and existing_event.event_type == TaskEventType.COMPLETED
    ):
        cached = (existing_event.data or {}).get("result", {})
        logger.info(
            "idempotency hit; returning cached result",
            extra={"idempotency_key": existing_event.idempotency_key},
        )
        return (
            existing_event,
            idem_store,
            breaker,
            {
                "status": "duplicate",
                "result": cached,
            },
        )
    return existing_event, idem_store, breaker, None


async def _acquire_concurrency_slot(
    gate: Any,
    task_category: TaskCategoryType | None,
) -> tuple[bool, dict[str, Any] | None]:
    """Acquire a per-category concurrency slot.

    Returns ``(acquired, early_response)``. ``early_response`` is set
    only when the defensive import of ``RateLimitError`` failed; the
    normal saturation path raises ``RateLimitError`` so the caller's
    error mapper can build the canonical rate-limit response.
    """
    if gate is None or task_category is None:
        return False, None
    if await gate.try_acquire(task_category, None):
        return True, None
    spec = gate.spec_for(task_category)
    if RateLimitError is None:
        # Sentinel: defensive import failed; surface as a
        # generic rate-limit response so the caller still
        # gets a structured status (matches the dispatched
        # path's RateLimitError contract).
        return False, {
            "status": "rate_limited",
            "retry_after_seconds": 0,
            "limit": f"task_category={task_category.value}",
        }
    raise RateLimitError(
        limit=spec.concurrency_limit if spec else None,
        retry_after_seconds=(_estimate_retry(spec) if _estimate_retry else None),
        domain=f"task_category={task_category.value}",
    )


async def _release_concurrency_slot(
    acquired: bool,
    gate: Any,
    task_category: TaskCategoryType | None,
) -> None:
    """Release the per-category concurrency slot, whatever the outcome.

    Called from the dispatch tool's ``finally`` block, so it must cover
    the success path and every failure path. Without it the per-process
    counter would never decrement and the gate would saturate permanently
    after one burst.
    """
    if acquired and gate is not None and task_category is not None:
        await gate.release(task_category, None)


async def _prepare_worktree(
    worktree: WorktreeOptions | None,
    prompt: str,
    execution_id: str,
    effective_isolation: str,
    wt_manager: Any,
) -> tuple[Any, Path | None, dict[str, Any] | None]:
    """Create an isolated worktree for the dispatch.

    Returns ``(worktree_info, repo_path, early_response)``. The early
    response is set on a lock conflict; every other creation failure
    propagates so the caller can convert it like any dispatch error.
    """
    if effective_isolation != "worktree":
        return None, None, None
    if wt_manager is None or WorktreeOptions is None:
        return None, None, None

    repo_path, reason = await _resolve_worktree_repo(prompt)
    if repo_path is None:
        # Isolation was asked for and could not be set up. Dispatching
        # anyway would run the worker in the shared checkout — the
        # exact harm the isolation exists to prevent — and the caller
        # would only find out afterwards, once the damage was done.
        # Fail before the dispatch instead, and say which thing to fix.
        WORKTREE_ISOLATION_REFUSALS_TOTAL.labels(reason=reason).inc()
        return (
            None,
            None,
            {
                "status": "failed",
                "error": _isolation_refusal_message(reason),
            },
        )

    branch = f"feature/{execution_id}-{uuid4().hex[:8]}"
    try:
        worktree_info = await wt_manager.create_worktree(
            task_id=execution_id,
            repo_path=repo_path,
            branch_name=branch,
            base_branch=(worktree.base_branch if worktree is not None else "main"),
            ttl_seconds=(worktree.ttl_seconds if worktree is not None else 86_400),
        )
    except (
        Exception
    ) as exc:  # MCP tool error handler — broad catch is the documented contract
        if WorktreeLockedError is not None and isinstance(exc, WorktreeLockedError):
            logger.exception(
                "worktree lock conflict",
                extra={"error_id": "WORKTREE_LOCK_CONFLICT"},
            )
            WORKTREE_CREATION_TOTAL.labels(result="lock_conflict").inc()
            return (
                None,
                None,
                {
                    "status": "worktree_conflict",
                    "error": str(exc),
                },
            )
        logger.exception(
            "worktree creation failed",
            extra={"error_id": "WORKTREE_CREATION_FAILED"},
        )
        WORKTREE_CREATION_TOTAL.labels(result="error").inc()
        raise
    WORKTREE_CREATION_TOTAL.labels(result="success").inc()
    WORKTREE_ACTIVE_COUNT.set(len(wt_manager.list_worktrees()))
    return worktree_info, repo_path, None


def _worktree_cwd(worktree_info: Any) -> str | None:
    """Resolve the directory the dispatched worker must run in.

    Worktree isolation only isolates if the worker actually runs inside
    the worktree. The path rides the task dict; the pool reads
    ``task["cwd"]`` and launches the session there. Without this the
    worker edits the source repo and the captured diff is empty — the
    isolation protected nothing.

    Returns ``None`` when no worktree is active, so a dispatch without
    isolation keeps the default session start.
    """
    if worktree_info is None:
        return None
    wt_path = getattr(worktree_info, "worktree_path", None)
    if wt_path is None:
        return None
    return str(wt_path)


async def _finalize_worktree(
    wt_manager: Any,
    worktree_info: Any,
    worktree: WorktreeOptions | None,
    repo_path: Path | None,
    result: dict[str, Any],
) -> None:
    """Attach the worktree diff/merge summary to the dispatch result."""
    on_completion = worktree.on_completion if worktree is not None else "return_diff"
    try:
        completion = await wt_manager.complete_worktree(
            worktree_id=worktree_info.worktree_id,
            merge=(on_completion == "auto_merge"),
            repo_path=repo_path,
        )
        worktree_info = completion.info
        result["worktree"] = {
            # Where the worker actually ran. Without it the caller
            # cannot tell an isolated run from a shared-checkout run,
            # and a dispatch that silently fell back to the shared
            # checkout is indistinguishable from one that isolated.
            "path": getattr(worktree_info, "worktree_path", None),
            "branch": getattr(worktree_info, "branch_name", None),
            "base_branch": getattr(worktree_info, "base_branch", None),
            "diff": worktree_info.diff,
            "merge": worktree_info.merge,
            "files_touched": list(worktree_info.files_touched),
        }
    except (
        Exception
    ) as exc:  # MCP tool error handler — broad catch is the documented contract
        logger.exception(
            "worktree completion failed",
            extra={"error_id": "WORKTREE_COMPLETION_FAILED"},
        )
        result["worktree"] = {"error": str(exc)}


async def _discard_worktree_branch(
    worktree_info: Any,
    repo_path: Path | None,
) -> None:
    """Delete the ephemeral branch a discarded worktree left behind.

    ``git worktree add -b`` creates a branch as a side effect of
    creating the worktree. Removing the worktree does not remove that
    branch, so every worktree-isolated dispatch leaked one branch.
    Three concurrent reviewers leaked three per merge, and they
    accumulate in the repository's branch list forever.

    Only ``on_completion="discard"`` deletes the branch: that mode
    means the work is thrown away, and the diff has already been
    captured into the dispatch result before cleanup runs. The other
    modes keep the branch, because there the branch is where the work
    still lives.

    A deletion failure is non-fatal: a leftover branch is untidy, not
    dangerous, and the worktree itself is already gone.
    """
    branch_name = getattr(worktree_info, "branch_name", None)
    if not branch_name or repo_path is None:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "branch",
            "-D",
            str(branch_name),
            cwd=str(repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "worktree branch discard failed for %s: %s",
                branch_name,
                stderr.decode(errors="replace").strip(),
                extra={"error_id": "WORKTREE_BRANCH_DISCARD_FAILED"},
            )
        else:
            logger.info("Discarded worktree branch %s", branch_name)
    except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.warning(
            "worktree branch discard failed for %s: %s",
            branch_name,
            exc,
            extra={"error_id": "WORKTREE_BRANCH_DISCARD_FAILED"},
        )


async def _cleanup_worktree(
    wt_manager: Any,
    worktree_info: Any,
    repo_path: Path | None,
) -> None:
    """Remove the isolated worktree; a cleanup failure is non-fatal."""
    try:
        await wt_manager.cleanup_worktree(
            worktree_id=worktree_info.worktree_id,
            repo_path=repo_path,
        )
        # The gauge counts what is still on disk, so it has to come
        # down with the worktree. A gauge that only ever climbs is a
        # lie the on-call engineer acts on.
        WORKTREE_ACTIVE_COUNT.set(len(wt_manager.list_worktrees()))
    except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.warning(
            "worktree cleanup failed: %s",
            exc,
            extra={"error_id": "WORKTREE_CLEANUP_FAILED"},
        )


async def _cleanup_dispatched_worktree(
    wt_manager: Any,
    worktree_info: Any,
    worktree: WorktreeOptions | None,
    repo_path: Path | None,
) -> None:
    """Remove the dispatch's worktree and, on discard, its branch.

    Runs from the dispatch tool's ``finally`` block, so it covers the
    failure path too. ``"discard"`` means the work is thrown away, and
    the branch the worktree creation created goes with it -- without
    this, every isolated dispatch leaked a branch into the repository.
    """
    if worktree_info is None:
        return
    await _cleanup_worktree(wt_manager, worktree_info, repo_path)
    on_completion = worktree.on_completion if worktree is not None else "return_diff"
    if on_completion == "discard":
        await _discard_worktree_branch(worktree_info, repo_path)


def _idempotency_wired(
    existing_event: Any,
    idem_store: Any,
    breaker: Any,
) -> bool:
    """Whether the C-6 idempotency layer is available for this dispatch.

    All three must be present: the lookup yields the event, the store it
    came from, and the circuit breaker that fronts it.
    """
    return existing_event is not None and idem_store is not None and breaker is not None


async def _mark_idempotency_completed(
    idem_store: Any,
    breaker: Any,
    existing_event: Any,
    result: dict[str, Any],
) -> None:
    """Record the dispatch result on the idempotency record."""
    # Wrap mark_completed through the same breaker so a DB
    # hiccup at dispatch-completion time does not lose the
    # result (FIX round-7 Tier 2).
    try:
        await breaker.call(lambda: idem_store.mark_completed(existing_event, result))
    except IdempotencyStoreUnavailable, IdempotencyCircuitOpen:  # ty: ignore[invalid-exception-caught]
        logger.exception(
            "failed to mark idempotency record completed",
            extra={"error_id": "IDEMPOTENCY_MARK_COMPLETED_FAILED"},
        )


async def _mark_idempotency_failed(
    idem_store: Any,
    breaker: Any,
    existing_event: Any,
    exc: Exception,
) -> None:
    """Mark the idempotency record FAILED after a dispatch error."""
    try:
        # Default-arg capture binds ``exc`` at lambda-definition
        # time so ruff's static analysis can resolve it through the
        # nested try/except scope.
        await breaker.call(
            lambda _exc=str(exc): idem_store.mark_failed(
                existing_event,
                error=_exc,
            )
        )
    except IdempotencyStoreUnavailable, IdempotencyCircuitOpen:  # ty: ignore[invalid-exception-caught]
        logger.exception(
            "failed to mark idempotency record failed",
            extra={"error_id": "IDEMPOTENCY_MARK_FAILED_FAILED"},
        )


def _map_dispatch_error(
    exc: Exception,
    worktree_info: Any,
) -> dict[str, Any] | None:
    """Map a dispatch exception to its structured response payload.

    Returns ``None`` when the exception has no specific mapping — the
    caller then falls back to the generic failure shape. A
    ``RuntimeError`` raised while a worktree is active is re-raised so
    the cleanup path stays observable to the test suite.
    """
    if RateLimitError is not None and isinstance(exc, RateLimitError):
        details = getattr(exc, "details", {}) or {}
        return {
            "status": "rate_limited",
            "retry_after_seconds": details.get("retry_after_seconds", 0),
            "limit": details.get("limit", "caller_kind=unknown"),
        }
    if isinstance(exc, TimeoutError):
        return {"status": "timeout"}
    if isinstance(exc, ValueError):
        return {
            "status": "invalid_selector",
            "error": str(exc),
        }
    if isinstance(exc, RuntimeError):
        # C-8 round-8: when the worktree path is active, let
        # RuntimeError propagate so the finally-block's cleanup
        # can be verified by the test suite. Other paths
        # continue to convert to ``{"status": "failed"}``.
        if worktree_info is not None:
            raise exc
        return {
            "status": "failed",
            "error": str(exc),
        }
    return None


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
) -> None:
    """Register pool management tools.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    The ``budget_enforce`` MCP surface previously lived here; it was
    extracted to :mod:`mahavishnu.mcp.tools.budget_tools` as part of
    the Stage 3b unblocker — see
    ``docs/plans/2026-10-12-pool-tools-debt-and-shepherd-registry.md``.

    Args:
        mcp: FastMCP instance
        pool_manager: PoolManager instance

    This registers 10 pool management tools:
    - mahavishnu_pool_list: List all active pools
    - mahavishnu_pool_spawn: Spawn a new pool (idempotent on name)
    - mahavishnu_pool_bootstrap: SessionStart bootstrap (spawn default pool if registry empty)
    - mahavishnu_pool_monitor: Monitor pool metrics
    - mahavishnu_pool_scale: Scale pool worker count
    - mahavishnu_pool_close: Close a specific pool
    - mahavishnu_pool_close_all: Close all pools
    - mahavishnu_pool_health: Get health status
    - mahavishnu_pool_search_memory: Search memory across pools
    - mahavishnu_pool_route_execute: Ad-hoc single-task dispatch across registered pools (Plan v3 Phase 2m)
    """

    @mcp.tool()
    async def mahavishnu_pool_list() -> list[dict[str, Any]]:
        """List all active pools."""
        try:
            return await pool_manager.list_pools()
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to list pools: {e}")
            return []

    @mcp.tool()
    async def mahavishnu_pool_spawn(
        name: str,
        pool_type: str = "mahavishnu",
        min_workers: int | None = None,
        max_workers: int | None = None,
        worker_type: str = "shepherd",
    ) -> dict[str, Any]:
        """Spawn a new worker pool. Mirrors the CLI at ``_main_cli.py:1632-1756``.

        Args:
            name: Human-readable pool name (used as the idempotency key in
                  ``PoolManager._pools_by_name``).
            pool_type: One of the registry-registered types
                  (mahavishnu, session-buddy, runpod).
            min_workers: Minimum workers (mahavishnu only; ignored for
                  session-buddy/runpod).
            max_workers: Maximum workers (mahavishnu only; ignored for
                  session-buddy/runpod).
            worker_type: Worker backend — see the canonical list in
                  ``mahavishnu.workers.registry.WORKER_REGISTRY``.

        Returns:
            ``{"status": "spawned" | "exists" | "warning" | "failed", ...}``
            - ``spawned``: new pool created
            - ``exists``: a pool with this name already exists (idempotent)
            - ``warning``: spawn succeeded but sizing was ignored for
              non-mahavishnu types

        All failures return ``{"status": "failed", "error": "..."}`` —
        this tool never raises.
        """
        logger.info(
            "mahavishnu_pool_spawn tool called",
            extra={
                "pool_name": name,
                "pool_type": pool_type,
                "min_workers": min_workers,
                "max_workers": max_workers,
            },
        )

        # Validate pool_type via the registry whitelist. canonicalize
        # only does string normalization (it does NOT raise on unknowns);
        # the membership check is the actual gate.
        from mahavishnu.pools._registry import canonicalize_pool_type, list_pool_types

        canonical = canonicalize_pool_type(pool_type)
        if canonical not in list_pool_types():
            return {
                "status": "failed",
                "error": (
                    f"Unknown pool type: {pool_type!r}. "
                    f"Supported: {', '.join(sorted(list_pool_types()))}"
                ),
            }

        # Validate worker_type against the canonical registry.
        # (Mirrors _main_cli.py:1682-1690; the CLI's enum is the
        # authoritative source — keep the set in sync if you add a worker.)
        from mahavishnu.workers.registry import WORKER_REGISTRY

        valid_worker_types = set(WORKER_REGISTRY.keys()) | {
            "gateway-openclaw",  # CLI-registered, may not be in WORKER_REGISTRY
            "container-executor",
        }
        if worker_type not in valid_worker_types:
            return {
                "status": "failed",
                "error": (
                    f"Unknown worker type: {worker_type!r}. "
                    f"Supported: {', '.join(sorted(valid_worker_types))}"
                ),
            }

        # Idempotency: if a pool with this name already exists, return it.
        # Uses the new _pools_by_name index from Task 3.5, NOT _pools
        # (which is keyed by generated pool_id, not user-provided name).
        existing_id = pool_manager._pools_by_name.get(name)
        if existing_id is not None:
            logger.info(
                "mahavishnu_pool_spawn: pool with name already exists, returning existing",
                extra={"pool_name": name, "pool_id": existing_id},
            )
            return {
                "status": "exists",
                "pool_id": existing_id,
                "name": name,
                "type": canonical,
            }

        # Build the config with type-specific sizing semantics.
        sizing_warning: str | None = None
        if canonical == "mahavishnu":
            effective_min = min_workers if min_workers is not None else 1
            effective_max = max_workers if max_workers is not None else 10
            if effective_min < 1 or effective_max > 100:
                return {
                    "status": "failed",
                    "error": (
                        f"Worker count must be 1 <= min <= max <= 100; "
                        f"got min={effective_min}, max={effective_max}"
                    ),
                }
            if effective_min > effective_max:
                return {
                    "status": "failed",
                    "error": (
                        f"min_workers ({effective_min}) exceeds max_workers ({effective_max})"
                    ),
                }
        else:
            # session-buddy and runpod have substrate-fixed sizing;
            # accept the params for API consistency but warn the caller.
            if min_workers is not None or max_workers is not None:
                sizing_warning = (
                    f"min_workers/max_workers ignored for pool_type={canonical!r}; "
                    f"sizing is fixed by the underlying pool substrate"
                )
            effective_min = 1
            effective_max = 3 if canonical == "session-buddy" else 10

        try:
            # NOTE: the import alias `RuntimePoolConfig` is required because
            # the settings class is also called `PoolConfig` (see task header).
            # The alias is bound at module top by Task 4 step 3; the
            # not-callable suppression below is because the except
            # branch in the defensive import at module top can rebind the
            # alias to None.
            pool_config = RuntimePoolConfig(  # ty: ignore[not-callable]
                name=name,
                pool_type=canonical,
                min_workers=effective_min,
                max_workers=effective_max,
                worker_type=worker_type,
            )
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            return {"status": "failed", "error": f"invalid pool config: {exc}"}

        try:
            pool_id = await pool_manager.spawn_pool(canonical, pool_config)
        except (
            Exception
        ) as exc:  # MCP tool error handler — broad catch is the documented contract
            logger.exception(
                "mahavishnu_pool_spawn: spawn failed",
                extra={"error_id": "POOL_SPAWN_FAILED"},
            )
            return {"status": "failed", "error": f"spawn failed: {exc}"}

        result: dict[str, Any] = {
            "status": "warning" if sizing_warning else "spawned",
            "pool_id": pool_id,
            "name": name,
            "type": canonical,
            "min_workers": effective_min,
            "max_workers": effective_max,
            "worker_type": worker_type,
        }
        if sizing_warning:
            result["warning"] = sizing_warning
        return result

    @mcp.tool()
    async def mahavishnu_pool_bootstrap() -> dict[str, Any]:
        """SessionStart bootstrap: ensure a default pool exists.

        Reads ``mahavishnu_pool_health`` (via ``health_check()``); if
        ``pools_active == 0``, spawns a default pool via the
        config-driven settings (``pools.auto_spawn_*``). Returns
        structured status so the calling hook script can log/observe
        without parsing.

        The bridge handler ``handle_pool_bootstrap`` (separate from
        this tool) emits audit telemetry for the same event but
        cannot do the work itself — bridge handlers run in
        subprocess context without PoolManager access.

        CRITICAL: This tool never raises. All failures return
        ``{"status": "failed", "error": "..."}`` so SessionStart
        hooks that wrap this call cannot be blocked by MCP errors.
        """
        logger.info("mahavishnu_pool_bootstrap: tool called")

        try:
            health = await pool_manager.health_check()
            pools_active_before = (health or {}).get("pools_active", 0)
            if pools_active_before > 0:
                logger.info(
                    "mahavishnu_pool_bootstrap: registry already populated",
                    extra={"pools_active": pools_active_before},
                )
                return {
                    "status": "skipped",
                    "pools_active_before": pools_active_before,
                    "pools_active_after": pools_active_before,
                }
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(
                "mahavishnu_pool_bootstrap: health check failed; attempting spawn anyway",
                extra={"error": str(exc)},
            )
            pools_active_before = 0

        # Read config via PoolManager's shared helper. Single source of
        # truth for the auto-spawn defaults (the same helper is used
        # by route_task's defensive auto-spawn path).
        from mahavishnu.pools.manager import PoolManager

        defaults = PoolManager._resolve_auto_spawn_defaults()
        spawn_type = defaults["spawn_type"]
        min_workers = defaults["min_workers"]
        max_workers = defaults["max_workers"]
        # Wave 7 (2026-10-09): worker_type is now surfaced in the
        # auto-spawn defaults (see manager.py). Pass it through
        # explicitly so the bootstrap doesn't depend on PoolConfig's
        # default.
        worker_type = defaults.get("worker_type", "shepherd")

        # Wave 7 (2026-10-09) skip gate: a ``mahavishnu`` pool needs
        # a terminal_manager (shepherd uses it for output streaming
        # via the configured terminal adapter — typically tmux).
        # If the manager is uninitialized (lite-mode / tmux-unavailable
        # / dev environments), skip the spawn with a structured
        # reason instead of letting ``spawn_pool`` raise a cryptic
        # ``RuntimeError("terminal_manager is not available")`` and
        # crash the SessionStart hook. session-buddy / runpod are
        # substrate-fixed and do NOT need a terminal manager, so
        # the gate is pool-type-aware.
        if spawn_type == "mahavishnu":
            terminal_manager = getattr(pool_manager, "terminal_manager", None)
            if terminal_manager is None:
                logger.info(
                    "mahavishnu_pool_bootstrap: terminal_manager unavailable, skipping spawn",
                    extra={"spawn_type": spawn_type},
                )
                return {
                    "status": "skipped",
                    "reason": "terminal_manager_unavailable",
                    "pools_active_before": pools_active_before,
                    "pools_active_after": pools_active_before,
                }

        # Same type-specific sizing as mahavishnu_pool_spawn (Task 4)
        sizing_warning: str | None = None
        if spawn_type != "mahavishnu":
            sizing_warning = (
                f"min_workers/max_workers ignored for pool_type={spawn_type!r}; "
                f"sizing is fixed by the underlying pool substrate"
            )
            effective_min = 1
            effective_max = 3 if spawn_type == "session-buddy" else 10
        else:
            effective_min = min_workers
            effective_max = max_workers

        try:
            # Use RuntimePoolConfig (the runtime dataclass, not the
            # settings class). The alias is bound at module top by
            # Task 4 step 3; the not-callable suppression below
            # is because the except branch in the defensive import at
            # module top can rebind the alias to None.
            pool_config = RuntimePoolConfig(  # ty: ignore[not-callable]
                name="session-start-bootstrap",
                pool_type=spawn_type,
                min_workers=effective_min,
                max_workers=effective_max,
                worker_type=worker_type,
            )
            pool_id = await pool_manager.spawn_pool(spawn_type, pool_config)
        except (
            Exception
        ) as exc:  # MCP tool error handler — broad catch is the documented contract
            logger.exception(
                "mahavishnu_pool_bootstrap: spawn failed",
                extra={"error_id": "POOL_BOOTSTRAP_SPAWN_FAILED"},
            )
            return {
                "status": "failed",
                "pools_active_before": pools_active_before,
                "error": f"spawn failed: {exc}",
            }

        logger.info(
            "mahavishnu_pool_bootstrap: spawned default pool",
            extra={"pool_id": pool_id, "pool_type": spawn_type},
        )
        result: dict[str, Any] = {
            "status": "warning" if sizing_warning else "spawned",
            "pools_active_before": pools_active_before,
            "pools_active_after": pools_active_before + 1,
            "pool_id": pool_id,
            "pool_type": spawn_type,
        }
        if sizing_warning:
            result["warning"] = sizing_warning
        return result

    @mcp.tool()
    async def mahavishnu_pool_monitor(
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Monitor pool status and metrics."""
        try:
            return await pool_manager.aggregate_results(pool_ids)
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to monitor pools: {e}")
            return {}

    @mcp.tool()
    async def mahavishnu_pool_scale(
        pool_id: str,
        target_workers: int,
    ) -> dict[str, Any]:
        """Scale pool to target worker count."""
        try:
            pool = pool_manager._pools.get(pool_id)
            if not pool:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": f"Pool not found: {pool_id}",
                }

            await pool.scale(target_workers)

            return {
                "pool_id": pool_id,
                "target_workers": target_workers,
                "actual_workers": len(pool._workers),
                "status": "scaled",
            }
        except NotImplementedError:
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": "Pool does not support scaling (e.g., SessionBuddyPool is fixed at 3 workers)",
            }
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to scale pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def mahavishnu_pool_close(
        pool_id: str,
    ) -> dict[str, Any]:
        """Close a specific pool."""
        try:
            await pool_manager.close_pool(pool_id)

            return {
                "pool_id": pool_id,
                "status": "closed",
            }
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to close pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def mahavishnu_pool_close_all() -> dict[str, Any]:
        """Close all active pools."""
        try:
            pools = await pool_manager.list_pools()
            count = len(pools)

            await pool_manager.close_all()

            return {
                "pools_closed": count,
                "status": "all_closed",
            }
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to close pools: {e}")
            return {
                "pools_closed": 0,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def mahavishnu_pool_health() -> dict[str, Any]:
        """Get health status of all pools."""
        try:
            return await pool_manager.health_check()
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to get health: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    @mcp.tool()
    async def mahavishnu_pool_search_memory(
        query: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search memory across all pools."""
        try:
            aggregator_cls = MemoryAggregator
            if aggregator_cls is None:
                raise RuntimeError("MemoryAggregator is not available")

            aggregator = aggregator_cls()
            results = await aggregator.cross_pool_search(
                query=query,
                pool_manager=pool_manager,
                limit=limit,
            )

            return results
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to search memory: {e}")
            return []

    @mcp.tool()
    async def mahavishnu_pool_route_execute(  # ty: ignore[invalid-argument-type]
        prompt: str,
        pool_selector: str = "least_loaded",
        timeout: float | None = None,
        pool_affinity: str | None = None,
        caller_kind: str = "claude_code",
        parent_session_id: str | None = None,
        auto_spawn: bool | None = None,
        idempotency: IdempotencyOptions | None = None,
        worktree: WorktreeOptions | None = None,
        # req: REQ-DSPROG-002 -- injected by FastMCP, excluded from the schema.
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Load-balanced single-task dispatch across registered worker pools.

        Plan v3 Phase 2m — Demo Track. Routes one ad-hoc task to the
        best-fit pool via the configured selector. Mirrors the documented
        primary entry point in ``.claude/agents/mahavishnu-specialist.md``
        and ``skills_catalog/pool-route.md``.

        Anti-bug guard (memory rule ``mahavishnu-dispatch-prompt-mangling``):
        Implementation MUST call ``await pool_manager.route_task(...)``
        directly. Do NOT wrap the prompt in a shell (``sh -lc``) — that
        re-introduces the prompt-mangling bug.

        ADR 014 (Honcho/ACL composition contract): ``caller_pool_allowlist``
        is set server-side via ``PoolManager``, not exposed to wire callers.
        The ``caller_kind`` parameter is for QUOTA ATTRIBUTION only (which
        ClientKind bucket the dispatch counts against).

        Liveness: a dispatch can outlast the MCP client's idle window. The
        injected ``ctx`` carries the client's progress token, and a
        heartbeat reports liveness while the dispatch runs, so the client's
        idle timer is reset instead of aborting a healthy call. The
        parameter is excluded from the tool schema and is ``None`` for
        direct (non-MCP) calls, which run unchanged.

        Returns:
            - On success: the dispatch result dict (carries ``pool_id``,
              ``status``, ``result``, etc.).
            - On quota saturation (RateLimitError):
              ``{"status": "rate_limited", "retry_after_seconds": N, "limit": "caller_kind=..."}``.
            - On timeout (asyncio.TimeoutError):
              ``{"status": "timeout"}``.
            - On invalid selector (ValueError):
              ``{"status": "invalid_selector", "error": "..."}``.
            - On pool registry error (RuntimeError):
              ``{"status": "failed", "error": "..."}``.
        """
        # Selector resolution — bad input is a user error, not a system crash.
        selector_enum, selector_error = _resolve_pool_selector(pool_selector)
        if selector_error is not None:
            return selector_error

        # Caller-kind funnel — unknown wire-strings map to CallerKind.UNKNOWN
        # (one shared bucket per memory rule indirection).
        coerced_kind = _coerce_caller_kind(caller_kind)

        # C-9: per-TaskCategory concurrency gate. Pool_id is unknown at the
        # dispatch entry point (the selector picks it inside route_task), so
        # we use pool_id=None — the gate falls back to the category-only key.
        # Specs without an explicit limit are pass-through; failure here
        # surfaces as RateLimitError and is caught by the envelope handler
        # below (fail-closed per REQ-013).
        task_category = _classify_prompt(prompt)

        gate = get_concurrency_gate()
        acquired = False
        idem_store: Any = None
        breaker: Any = None
        existing_event: Any = None
        worktree_info: Any = None
        worktree_repo_path: Path | None = None
        try:
            # C-6 idempotency: lookup-or-create BEFORE dispatch so a duplicate
            # call returns the cached result without ever entering the gate.
            # When idempotency is configured, the store is the fail-CLOSED
            # guard — if it's unreachable, we DO NOT dispatch (REQ-007).
            existing_event, idem_store, breaker, early = await _lookup_idempotency(
                idempotency, prompt
            )
            if early is not None:
                return early

            acquired, gate_error = await _acquire_concurrency_slot(gate, task_category)
            if gate_error is not None:
                return gate_error

            # C-8: worktree isolation. When ``worktree.isolation == "worktree"``
            # and the resolved repo is a git working tree, create an isolated
            # worktree, dispatch inside it, and capture diff/merge/files_touched
            # on completion. WorktreeLockedError => ``status="worktree_conflict"``.
            # ``worktree_storage.default_isolation`` was removed in the
            # 2026-09-27 config audit (no Bodai consumer); the worktree
            # subsystem manages its own constants/defaults. When the
            # caller passes no per-call ``worktree`` parameter, isolation
            # stays off ("host").
            effective_isolation = worktree.isolation if worktree is not None else "host"
            wt_manager = _get_worktree_manager()
            execution_id = str(uuid4())
            worktree_info, worktree_repo_path, wt_error = await _prepare_worktree(
                worktree,
                prompt,
                execution_id,
                effective_isolation,
                wt_manager,
            )
            if wt_error is not None:
                return wt_error

            # Resolve auto_spawn from config when caller didn't specify.
            # None means "read settings"; False / True are explicit overrides.
            resolved_auto_spawn = _resolve_auto_spawn(auto_spawn)
            # Log the resolved value so the audit trail captures whether
            # config drove the decision (or an explicit caller override).
            logger.info(
                "mahavishnu_pool_route_execute: auto_spawn resolved",
                extra={"auto_spawn_resolved": resolved_auto_spawn},
            )

            try:
                _log_routed_model(task_category)
                result = await _dispatch_with_progress(
                    ctx,
                    partial(
                        _dispatch_internal,
                        prompt=prompt,
                        pool_selector=selector_enum,
                        execution_id=execution_id,
                        pool_affinity=pool_affinity,
                        coerced_kind=coerced_kind,
                        parent_session_id=parent_session_id,
                        auto_spawn=resolved_auto_spawn,
                        pool_manager=pool_manager,
                        timeout=timeout,
                        cwd=_worktree_cwd(worktree_info),
                    ),
                )

                if worktree_info is not None:
                    await _finalize_worktree(
                        wt_manager,
                        worktree_info,
                        worktree,
                        worktree_repo_path,
                        result,
                    )
            finally:
                await _cleanup_dispatched_worktree(
                    wt_manager,
                    worktree_info,
                    worktree,
                    worktree_repo_path,
                )

            if _idempotency_wired(existing_event, idem_store, breaker):
                await _mark_idempotency_completed(
                    idem_store, breaker, existing_event, result
                )

            return result
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            # If idempotency is wired, mark the record FAILED so a future
            # retry does not return stale PENDING. Best-effort — a DB
            # hiccup here must not mask the original dispatch error.
            if _idempotency_wired(existing_event, idem_store, breaker):
                await _mark_idempotency_failed(idem_store, breaker, existing_event, exc)

            response = _map_dispatch_error(exc, worktree_info)
            if response is None:
                logger.exception(
                    "Failed to route task via mahavishnu_pool_route_execute — see traceback"
                )
                response = {
                    "status": "failed",
                    "error": str(exc),
                }
            return response
        finally:
            # Release the concurrency slot regardless of outcome (success,
            # rate-limit denial, timeout, dispatch failure).
            await _release_concurrency_slot(acquired, gate, task_category)

    logger.info("Registered 11 pool management tools")
