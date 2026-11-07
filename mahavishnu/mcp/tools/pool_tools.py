"""Pool management MCP tools."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
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
    # Phase 2m (Plan v3): pool_route_execute needs the selector enum, the
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
    RuntimePoolConfig = None  # type: ignore[assignment]
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
    get_idempotency_store = lambda: None  # type: ignore[assignment]
    set_idempotency_store = lambda _store: None  # type: ignore[assignment]
    get_idempotency_breaker = lambda: None  # type: ignore[assignment]
    set_idempotency_breaker = lambda _breaker: None  # type: ignore[assignment]

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


async def _resolve_repo_nickname(prompt: str) -> str:
    """Best-effort extraction of a repo nickname from a dispatch prompt.

    Returns an empty string when no nickname is detectable — callers
    MUST treat the empty string as "unknown repo, skip worktree path".
    The implementation is intentionally lightweight (string contains);
    the actual repo resolution lives in the pool routing layer.
    """
    if not prompt:
        return ""
    lowered = prompt.lower()
    for token in lowered.replace("\n", " ").split():
        if token.startswith(("@", "/")):
            continue
        if token.endswith(".git"):
            return token[: -len(".git")]
    return ""


def _resolve_repo_path(repo_nickname: str) -> Path:
    """Resolve ``repo_nickname`` to a filesystem path.

    Falls back to the current working directory joined with the nickname
    when the nickname is empty — pool_tools tests exercise this branch
    to keep the worktree path deterministic.
    """
    from pathlib import Path as _Path

    if not repo_nickname:
        return _Path.cwd()
    return _Path.cwd() / repo_nickname


async def _repo_has_git(repo_nickname: str) -> bool:
    """Return True when the resolved repo path is a git working tree.

    Returns ``False`` when the path does not exist or is not a git
    working tree — gates the worktree-isolation path in
    ``pool_route_execute``.
    """

    repo_path = _resolve_repo_path(repo_nickname)
    if not repo_path.exists():
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo_path),
            "rev-parse",
            "--is-inside-work-tree",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except Exception:  # subprocess probing helper — broad catch to return False on any failure  # MCP tool error handler — broad catch is the documented contract  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        return False
    return proc.returncode == 0 and stdout.decode().strip() == "true"


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
):
    """Internal dispatch helper used when a worktree path is active.

    Mirrors the inline dispatch in ``pool_route_execute`` so the worktree
    finally-block can wrap it cleanly. Returns the same ``dict`` shape as
    ``pool_manager.route_task``.

    ``timeout`` is forwarded into the task dict because the worker's
    own execute timeout is read from ``task["timeout"]``. Without it the
    worker's default (300s) applies regardless of what the caller asked
    for, so a long-running task is killed mid-flight while the caller
    believes it was given a larger budget.
    """
    task = {"prompt": prompt}
    if timeout is not None:
        task["timeout"] = timeout
    return await pool_manager.route_task(
        task=task,
        pool_selector=pool_selector,
        pool_affinity=pool_affinity,
        caller_kind=coerced_kind if coerced_kind is not None else "claude_code",
        parent_session_id=parent_session_id,
        auto_spawn=auto_spawn,
    )


async def _hash_prompt(prompt: str) -> str:
    """SHA-256 hex digest of the dispatch prompt text.

    Used as the ``payload_hash`` for the idempotency fingerprint so a
    duplicate dispatch with the same prompt produces the same key.
    Async because Oneiric ``HashAction.execute`` is async.
    """
    from oneiric.actions.compression import HashAction

    result = await HashAction().execute({"algorithm": "sha256", "data": prompt})
    return result["digest"]  # type: ignore[no-any-return]


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
# pool_route_execute decomposition.
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
                actor="pool_route_execute",
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

    repo_nickname = await _resolve_repo_nickname(prompt)
    if not await _repo_has_git(repo_nickname):
        return None, None, None

    repo_path = _resolve_repo_path(repo_nickname)
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
        raise
    return worktree_info, repo_path, None


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
    except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.warning(
            "worktree cleanup failed: %s",
            exc,
            extra={"error_id": "WORKTREE_CLEANUP_FAILED"},
        )


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
    - pool_list: List all active pools
    - pool_spawn: Spawn a new pool (idempotent on name)
    - pool_bootstrap: SessionStart bootstrap (spawn default pool if registry empty)
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    - pool_route_execute: Ad-hoc single-task dispatch across registered pools (Plan v3 Phase 2m)
    """

    @mcp.tool()
    async def pool_list() -> list[dict[str, Any]]:
        """List all active pools."""
        try:
            return await pool_manager.list_pools()  # type: ignore[no-any-return]
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to list pools: {e}")
            return []

    @mcp.tool()
    async def pool_spawn(
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
            "pool_spawn tool called",
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
        existing_id = pool_manager._pools_by_name.get(name)  # type: ignore[union-attr]
        if existing_id is not None:
            logger.info(
                "pool_spawn: pool with name already exists, returning existing",
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
            # call-non-callable suppression below is because the except
            # branch in the defensive import at module top can rebind the
            # alias to None.
            pool_config = RuntimePoolConfig(  # ty: ignore[call-non-callable]
                name=name,
                pool_type=canonical,
                min_workers=effective_min,
                max_workers=effective_max,
                worker_type=worker_type,
            )
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            return {"status": "failed", "error": f"invalid pool config: {exc}"}

        try:
            pool_id = await pool_manager.spawn_pool(canonical, pool_config)  # type: ignore[union-attr]
        except (
            Exception
        ) as exc:  # MCP tool error handler — broad catch is the documented contract
            logger.exception(
                "pool_spawn: spawn failed", extra={"error_id": "POOL_SPAWN_FAILED"}
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
    async def pool_bootstrap() -> dict[str, Any]:
        """SessionStart bootstrap: ensure a default pool exists.

        Reads ``pool_health`` (via ``health_check()``); if
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
        logger.info("pool_bootstrap: tool called")

        try:
            health = await pool_manager.health_check()  # type: ignore[union-attr]
            pools_active_before = (health or {}).get("pools_active", 0)
            if pools_active_before > 0:
                logger.info(
                    "pool_bootstrap: registry already populated",
                    extra={"pools_active": pools_active_before},
                )
                return {
                    "status": "skipped",
                    "pools_active_before": pools_active_before,
                    "pools_active_after": pools_active_before,
                }
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(
                "pool_bootstrap: health check failed; attempting spawn anyway",
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
                    "pool_bootstrap: terminal_manager unavailable, skipping spawn",
                    extra={"spawn_type": spawn_type},
                )
                return {
                    "status": "skipped",
                    "reason": "terminal_manager_unavailable",
                    "pools_active_before": pools_active_before,
                    "pools_active_after": pools_active_before,
                }

        # Same type-specific sizing as pool_spawn (Task 4)
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
            # Task 4 step 3; the call-non-callable suppression below
            # is because the except branch in the defensive import at
            # module top can rebind the alias to None.
            pool_config = RuntimePoolConfig(  # ty: ignore[call-non-callable]
                name="session-start-bootstrap",
                pool_type=spawn_type,
                min_workers=effective_min,
                max_workers=effective_max,
                worker_type=worker_type,
            )
            pool_id = await pool_manager.spawn_pool(spawn_type, pool_config)  # type: ignore[union-attr]
        except (
            Exception
        ) as exc:  # MCP tool error handler — broad catch is the documented contract
            logger.exception(
                "pool_bootstrap: spawn failed",
                extra={"error_id": "POOL_BOOTSTRAP_SPAWN_FAILED"},
            )
            return {
                "status": "failed",
                "pools_active_before": pools_active_before,
                "error": f"spawn failed: {exc}",
            }

        logger.info(
            "pool_bootstrap: spawned default pool",
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
    async def pool_monitor(
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Monitor pool status and metrics."""
        try:
            return await pool_manager.aggregate_results(pool_ids)  # type: ignore[no-any-return]
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to monitor pools: {e}")
            return {}

    @mcp.tool()
    async def pool_scale(
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
    async def pool_close(
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
    async def pool_close_all() -> dict[str, Any]:
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
    async def pool_health() -> dict[str, Any]:
        """Get health status of all pools."""
        try:
            return await pool_manager.health_check()  # type: ignore[no-any-return]
        except Exception as e:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.error(f"Failed to get health: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_search_memory(
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
    async def pool_route_execute(  # ty: ignore[invalid-argument-type]
        prompt: str,
        pool_selector: str = "least_loaded",
        timeout: float | None = None,
        pool_affinity: str | None = None,
        caller_kind: str = "claude_code",
        parent_session_id: str | None = None,
        auto_spawn: bool | None = None,
        idempotency: IdempotencyOptions | None = None,
        worktree: WorktreeOptions | None = None,
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
                "pool_route_execute: auto_spawn resolved",
                extra={"auto_spawn_resolved": resolved_auto_spawn},
            )

            try:
                if resolve_model_id is not None and task_category is not None:
                    logger.info(
                        "pool_route_execute: dispatch routed to model %s (category=%s)",
                        resolve_model_id(task_category),
                        task_category.value,
                    )
                result = await _dispatch_internal(
                    prompt=prompt,
                    pool_selector=selector_enum,
                    execution_id=execution_id,
                    pool_affinity=pool_affinity,
                    coerced_kind=coerced_kind,
                    parent_session_id=parent_session_id,
                    auto_spawn=resolved_auto_spawn,
                    pool_manager=pool_manager,
                    timeout=timeout,
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
                if worktree_info is not None:
                    await _cleanup_worktree(
                        wt_manager,
                        worktree_info,
                        worktree_repo_path,
                    )

            if (
                existing_event is not None
                and idem_store is not None
                and breaker is not None
            ):
                await _mark_idempotency_completed(
                    idem_store, breaker, existing_event, result
                )

            return result
        except Exception as exc:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
            # If idempotency is wired, mark the record FAILED so a future
            # retry does not return stale PENDING. Best-effort — a DB
            # hiccup here must not mask the original dispatch error.
            if (
                existing_event is not None
                and idem_store is not None
                and breaker is not None
            ):
                await _mark_idempotency_failed(idem_store, breaker, existing_event, exc)

            response = _map_dispatch_error(exc, worktree_info)
            if response is None:
                logger.exception(
                    "Failed to route task via pool_route_execute — see traceback"
                )
                response = {
                    "status": "failed",
                    "error": str(exc),
                }
            return response
        finally:
            # Release the concurrency slot regardless of outcome (success,
            # rate-limit denial, timeout, dispatch failure). Without this,
            # the per-process counter would never decrement and the gate
            # would saturate permanently after one burst.
            if acquired and gate is not None and task_category is not None:
                await gate.release(task_category, None)

    logger.info("Registered 11 pool management tools")
