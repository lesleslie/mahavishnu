"""Worker lifecycle management and orchestration."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from monitoring.metrics import (
    agent_task_duration_seconds,
    agent_tasks_in_progress,
    agent_tasks_total,
)

from .base import BaseWorker, WorkerResult, WorkerStatus
from .capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
    invalidate_capability,
)
from .registry import RuntimeKind, WorkerConfig, get_worker_config, get_worker_entry
from .shell_backend import ShellWorker, resolve_permission_mode

if TYPE_CHECKING:
    from pathlib import Path

    from ..core.config import MahavishnuSettings
    from ..terminal.manager import TerminalManager

logger = logging.getLogger(__name__)


def _substitute_argv(
    argv: list[str],
    env: dict[str, str],
    extra: dict[str, str],
) -> list[str]:
    """Replace {key} placeholders with env values, then $1..$9 with extra values.

    Args:
        argv: raw command_argv from settings, e.g. ["psql", "-U", "{user}", "$1"]
        env: process environment (for placeholders matching {X})
        extra: caller-supplied values for $1..$9 (positional args)

    Returns:
        New argv with placeholders substituted. $1..$9 are replaced in order
        from `extra`; missing extras become empty strings.
    """
    import re

    out: list[str] = []
    positional = [extra.get(f"{i}", "") for i in range(1, 10)]
    for arg in argv:
        # {key} → os.environ[key] (case-sensitive)
        def repl_brace(m: re.Match[str]) -> str:
            return env.get(m.group(1), m.group(0))  # leave placeholder if missing

        new = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl_brace, arg)
        # $1..$9 → positional args (only outside double quotes; simple left-to-right)
        for i in range(9, 0, -1):
            new = new.replace(f"${i}", positional[i - 1])
        out.append(new)
    return out


def _create_isolated_worker(
    worker_type: str,
    session_buddy_client: Any,
    kwargs: dict[str, Any],
) -> BaseWorker:
    """Create an isolated-execution worker.

    Plan v3 Phase 4: the legacy isolated-worker surface (Apple container,
    E2B sandbox) has been retired. ``worker_type == "shepherd"`` is the
    ONLY supported isolated-worker type. Every other worker_type raises
    ``ValueError`` with a helpful message pointing to the new ADR.

    This MUST land before Phase 4.5b's ``git rm`` of ``apple_container.py``
    and ``e2b_sandbox.py`` so the function body never imports a deleted
    module.
    """
    from ..core.errors import ErrorCode, MahavishnuError
    from .shepherd_backend import ShepherdBackendWorker

    if worker_type == "shepherd":
        writable_root = kwargs.get("writable_root")
        if writable_root is None:
            raise MahavishnuError(
                "ShepherdBackendWorker requires 'writable_root' kwarg; "
                "refusing to start without an explicit write grant.",
                ErrorCode.WORKER_UNAVAILABLE,
                details={"worker_type": worker_type},
            )
        return ShepherdBackendWorker(
            writable_root=writable_root,
            workspace_cwd=kwargs.get("workspace_cwd"),
            placement=kwargs.get("placement", "auto"),
            default_timeout=kwargs.get("timeout", 300),
            session_buddy_client=session_buddy_client,
        )

    # Every other worker_type is unsupported by the isolated-worker
    # factory. The dispatch in ``WorkerManager._create_worker``
    # routes RuntimeKind.SHELL workers to ``ShellWorker`` (see
    # ``shell_backend.py``) and RuntimeKind.NONE workers to their
    # dedicated constructors; reaching this branch means the
    # dispatch didn't recognize ``worker_type``'s runtime_kind.
    # Per docs/decisions/2026-09-24-legacy-worker-deprecation.md,
    # the isolated-worker surface only supports ``shepherd`` (the
    # OS-level syscall-jail). The legacy Apple-container and
    # E2B-sandbox backends were retired; the AI assistant CLI
    # workers (terminal-claude / terminal-qwen / terminal-codex)
    # were never isolated workers in the first place.
    supported = sorted(WORKER_SUPPORTED_TYPES)
    raise ValueError(
        f"worker_type={worker_type!r} is not an isolated worker type. "
        f"WorkerManager._create_worker routes by WorkerConfig.runtime_kind: "
        f"RuntimeKind.SHELL -> ShellWorker (mahavishnu/workers/shell_backend.py); "
        f"RuntimeKind.APPLE_CONTAINER / E2B -> retired (per ADR "
        f"docs/decisions/2026-09-24-legacy-worker-deprecation.md); "
        f"the only surviving isolated worker is 'shepherd' "
        f"({type(supported).__name__}({supported})). "
        f"If you reached this branch, the dispatch's runtime_kind check "
        f"missed this worker — add the appropriate branch to "
        f"WorkerManager._create_worker or check the Worker's "
        f"WorkerConfig.runtime_kind in the registry."
    )


# Worker types supported by the isolated-worker factory above. The legacy
# Apple-container and E2B-sandbox types are intentionally absent — see the
# ADR.
WORKER_SUPPORTED_TYPES: frozenset[str] = frozenset({"shepherd"})


class WorkerManager:
    """Manages isolated-execution workers (``worker_type == "shepherd"`` only).

    Non-isolated workloads route through ``mahavishnu/pools/``. The legacy
    isolated-worker surface (Apple container, E2B sandbox, generic_shell,
    application workers, gateways, A2A) was retired per
    ``docs/decisions/2026-09-24-legacy-worker-deprecation.md``; callers
    passing any other ``worker_type`` now receive a clear ``ValueError``
    from :func:`_create_isolated_worker` instead of an opaque
    ``ModuleNotFoundError`` or silent fallback.

    Args:
        terminal_manager: TerminalManager for terminal session control
        max_concurrent: Maximum number of concurrent workers
        session_buddy_client: Optional Session-Buddy MCP client
        mcp_client: Optional MCP client for application workers
        writable_root: Path | None = None
            Default filesystem path the ShepherdBackendWorker
            (the only supported worker_type since 2026-09-24) may write
            into. Per-spawn overrides accepted by ``spawn_workers``.
            Pool-level pools (PoolConfig.writable_root) flow through
            to here via MahavishnuPool.__init__; if both are None the
            shepherd constructor raises MHV-312 with a clear remediation.
        settings: Optional MahavishnuSettings used for capability evaluation
    """

    def __init__(
        self,
        terminal_manager: TerminalManager,
        max_concurrent: int = 10,
        session_buddy_client: Any = None,
        mcp_client: Any = None,
        writable_root: Path | None = None,
        *,
        settings: MahavishnuSettings | None = None,
    ) -> None:
        """Initialize worker manager.

        Args:
            terminal_manager: TerminalManager instance
            max_concurrent: Maximum concurrent workers (1-100)
            session_buddy_client: Session-Buddy MCP client
            mcp_client: MCP client for application workers
            writable_root: Default filesystem path the ShepherdBackendWorker
                (the only supported worker_type since 2026-09-24) may write
                into. Per-spawn overrides accepted by ``spawn_workers``.
                Pool-level pools (PoolConfig.writable_root) flow through
                to here via MahavishnuPool.__init__; if both are None the
                shepherd constructor raises MHV-312 with a clear remediation.
            settings: Optional MahavishnuSettings for capability evaluation
        """
        self.terminal_manager = terminal_manager
        self.max_concurrent = max(1, min(max_concurrent, 100))
        self.session_buddy_client = session_buddy_client
        self.mcp_client = mcp_client
        self.writable_root = writable_root
        self.settings = settings
        self._workers: dict[str, BaseWorker] = {}
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        logger.info(f"Initialized WorkerManager (max_concurrent={self.max_concurrent})")

    def list_worker_ids(self) -> list[str]:
        """Return IDs of all currently registered workers."""
        return list(self._workers.keys())

    def _require_ready(self, worker_type: str) -> None:
        """Evaluate capabilities and raise if the worker is not READY.

        Imports lazily to avoid a circular import through core.errors.
        """
        report = evaluate_worker_capabilities(worker_type, settings=self.settings)
        if report.state is not WorkerCapabilityState.READY:
            from ..core.errors import WorkerUnavailableError

            raise WorkerUnavailableError(
                worker_type=worker_type,
                state=report.state.value,
                missing_requirements=report.missing_requirements,
                message=report.safe_reason or "static prerequisites missing",
            )

    def _validate_required_env(self, worker_type: str) -> None:
        """Ensure all ``entry.required_env`` vars are set for this worker_type.

        Looks up the worker via the new capability-driven registry (Task 2.5).
        Raises :class:`MahavishnuError` with ``VALIDATION_ERROR`` when any
        required environment variable is missing. Silently returns when the
        worker is not in the new registry — those legacy-only workers have
        their own env checks in their dedicated constructors.

        Args:
            worker_type: Worker-type identifier.
        """
        from ..core.config import MahavishnuSettings
        from ..core.errors import ErrorCode, MahavishnuError

        # Only use self.settings when it is a real MahavishnuSettings instance.
        # Tests sometimes inject ``settings=object()`` as a sentinel; we ignore
        # those and let ``get_worker_entry`` construct a default.
        registry_settings = self.settings if isinstance(self.settings, MahavishnuSettings) else None

        try:
            entry = get_worker_entry(worker_type, settings=registry_settings)
        except MahavishnuError:
            # Legacy-only worker (container, application, gateway, etc.).
            # Its constructor will perform any required-env checks.
            return

        missing = [var for var in entry.required_env if var not in os.environ]
        if missing:
            raise MahavishnuError(
                f"Worker {worker_type!r} missing required env: {missing}",
                ErrorCode.VALIDATION_ERROR,
                details={"worker_type": worker_type, "missing_env": missing},
            )

    def _validate_required_tool(self, worker_type: str) -> None:
        """Ensure ``entry.requires_tool`` is on PATH for this worker_type.

        Mirrors :meth:`_validate_required_env`. Looks up the worker via the
        capability-driven registry and raises :class:`MahavishnuError` with
        ``VALIDATION_ERROR`` when the declared tool is not on ``PATH``. This
        gives callers (and the spawn flow) a clear, named error instead of
        letting the underlying ``Command failed`` / ``AttributeError`` bubble
        up at runtime.

        Silently returns when:
        * the worker is not in the new registry (legacy-only workers have
          their own checks), or
        * the entry does not declare a ``requires_tool``.

        Args:
            worker_type: Worker-type identifier.
        """
        import shutil

        from ..core.config import MahavishnuSettings
        from ..core.errors import ErrorCode, MahavishnuError

        registry_settings = self.settings if isinstance(self.settings, MahavishnuSettings) else None

        try:
            entry = get_worker_entry(worker_type, settings=registry_settings)
        except MahavishnuError:
            # Legacy-only worker (container, application, gateway, etc.).
            # Its constructor will perform any required-tool checks.
            return

        required_tool = entry.requires_tool
        if not required_tool:
            return

        if shutil.which(required_tool) is None:
            current_path = os.environ.get("PATH", "")
            if len(current_path) > 512:
                current_path_truncated = current_path[:512] + "..."
            else:
                current_path_truncated = current_path
            fix_hint = (
                "Set MAHAVISHNU_NO_EXTRA_PATH=1 to skip PATH augmentation, "
                "or rely on the PATH bootstrap in scripts/launch_mcp.py to "
                "prepend ~/.local/bin before launching the subprocess."
            )
            raise MahavishnuError(
                f"Worker {worker_type!r} requires tool {required_tool!r} "
                f"which is not on PATH.\n"
                f"Current PATH: {current_path_truncated}\n"
                f"Fix: {fix_hint}",
                ErrorCode.VALIDATION_ERROR,
                details={
                    "worker_type": worker_type,
                    "missing_tool": required_tool,
                    "current_path_truncated": current_path_truncated,
                    "fix_hint": fix_hint,
                },
            )

    # wired: WorkerManager public API. One-shot dispatch surface for codex /
    # deepagents / clai / openhands / gateway-openclaw. Tests at
    # tests/unit/test_worker_manager.py::test_submit_workers_runs_one_shot_lifecycle
    # exercise the contract; pool-routing (planned per docs/plans/
    # 2026-07-21-worker-readiness.md) calls mgr.submit_workers(...) at runtime.
    async def submit_workers(
        self,
        worker_type: str,
        prompts: list[str],
        *,
        runtime_kwargs: dict[str, Any] | None = None,
    ) -> list[str]:
        """Submit prompts to a one-shot worker, launching one session per prompt.

        Args:
            worker_type: Worker type to use (must be registered and one_shot).
            prompts: One prompt per session to launch.
            runtime_kwargs: Optional kwargs forwarded to the worker factory.

        Returns:
            List of newly-created worker session IDs in the same order as ``prompts``.

        Raises:
            ValueError: If ``worker_type`` is not registered as one_shot.
            WorkerUnavailableError: If capability evaluation rejects the worker.
        """
        cfg = get_worker_config(worker_type)
        if cfg is None or not cfg.one_shot:
            raise ValueError(f"Worker {worker_type!r} is not a one-shot worker")
        self._require_ready(worker_type)

        worker_ids: list[str] = []
        try:
            for prompt in prompts:
                worker = self._create_worker(worker_type, **(runtime_kwargs or {}))
                worker_id = await worker.start(prompt=prompt)
                self._workers[worker_id] = worker
                worker_ids.append(worker_id)
        except Exception:  # Background task — worker dispatch rollback must catch every failure to drain partially-spawned workers
            for wid in worker_ids:
                await self.close_worker(wid)
            invalidate_capability(worker_type)
            # Capability transition broadcast for the failure is handled by the
            # next _require_ready call, which re-evaluates and emits a
            # transition event if the state changes. We deliberately avoid
            # importing emit_transition here to keep this rollback free of
            # new top-level dependencies.
            raise
        return worker_ids

    async def spawn_workers(
        self,
        worker_type: str,
        count: int,
        task_spec: dict[str, Any] | None = None,
        writable_root: Path | None = None,
    ) -> list[str]:
        """Spawn multiple workers of specified type.

        Args:
            worker_type: Type of worker ("terminal-qwen" [legacy], "terminal-claude", "terminal-codex", "container")
            count: Number of workers to spawn
            task_spec: Optional task specification for immediate execution
            writable_root: Per-spawn override for the ShepherdBackendWorker's
                ``writable_root`` kwarg. ``None`` falls back to
                ``self.writable_root`` (set in __init__ from the pool
                config). If both are ``None`` the shepherd constructor
                raises MHV-312.
        """
        """Spawn multiple workers of specified type.

        Args:
            worker_type: Type of worker ("terminal-qwen" [legacy], "terminal-claude", "terminal-codex", "container")
            count: Number of workers to spawn
            task_spec: Optional task specification for immediate execution

        Returns:
            List of worker IDs

        Raises:
            ValueError: If worker_type is unknown
        """
        worker_ids = []

        for _ in range(count):
            worker = self._create_worker(
                worker_type,
                writable_root=writable_root or self.writable_root,
            )
            worker_id = await worker.start()
            self._workers[worker_id] = worker
            worker_ids.append(worker_id)

        logger.info(f"Spawned {len(worker_ids)} {worker_type} workers")

        return worker_ids

    def _resolve_permission_mode(self, config: WorkerConfig) -> str | None:
        """Resolve the agent's approval/sandbox mode from settings.

        ``workers.permission_modes`` overrides the registry default per
        worker type, e.g. ``{'terminal-claude': 'plan'}``. The value is
        validated against the allowlist for that CLI -- it is substituted
        into a command line, so an unchecked value could smuggle a flag
        into the agent's argv.

        A bad value raises at spawn time rather than silently falling back:
        a deployment that asked for ``plan`` must not silently get
        ``acceptEdits``.
        """
        override = None
        settings = self.settings
        workers_settings = getattr(settings, "workers", None)
        modes = getattr(workers_settings, "permission_modes", None)
        if isinstance(modes, dict):
            candidate = modes.get(config.worker_type)
            if isinstance(candidate, str):
                override = candidate
        return resolve_permission_mode(config, override)

    def _create_worker(self, worker_type: str, **kwargs: Any) -> BaseWorker:
        """Factory method for worker creation.

        Dispatches by :class:`WorkerConfig.runtime_kind` (per
        ``mahavishnu/workers/registry.py``):

        - ``RuntimeKind.SHELL`` (terminal-claude / terminal-qwen /
          terminal-codex) → :class:`ShellWorker` — runs the registered
          shell command in a terminal session via the shared
          :class:`TerminalManager`. The Bifrost Phase D env-injection
          (OPENAI_BASE_URL / ANTHROPIC_BASE_URL based on the
          configured ``bifrost.routing`` flags) happens inside the
          terminal manager's ``launch_sessions``.
        - Anything else (isolated workers) →
          :func:`_create_isolated_worker_from_config` →
          :func:`_create_isolated_worker`, which only accepts
          ``shepherd`` per the 2026-09-24 deprecation decision.

        The previous implementation routed *every* worker_type
        through the isolated-worker factory; that broke the
        Bifrost Phase D SHELL path (the AI assistant CLI workers
        were never isolated workers in the first place — they're
        shell-out to a CLI binary the operator already controls).
        This dispatch restores the missing path.

        Args:
            worker_type: Type of worker to create (must be in
                ``mahavishnu.workers.registry.WORKER_REGISTRY``).
            **kwargs: Additional parameters for worker. For
                ``RuntimeKind.SHELL``, ``writable_root`` is
                ignored (SHELL workers use a terminal session, not a
                filesystem sandbox). For ``RuntimeKind.SHEPHERD``
                (the surviving isolated worker), ``writable_root``
                is required and the constructor raises if absent.

        Returns:
            Configured worker instance.

        Raises:
            ValueError: If ``worker_type`` is unknown or its
                ``runtime_kind`` doesn't match a supported dispatch
                branch.
            MahavishnuError: If ``required_env`` from the new registry is
                missing from the process environment.
        """
        config = get_worker_config(worker_type)

        if config is None:
            raise ValueError(f"Unknown worker type: {worker_type}")

        # Validate required_env against the new capability-driven registry.
        # Skip silently for worker_types that live only in the legacy
        # WORKER_REGISTRY (containers, applications, gateways); their env
        # checks belong to their dedicated constructors below.
        self._validate_required_env(worker_type)

        # Validate required_tool against the new capability-driven registry.
        # Mirrors _validate_required_env: surfaces a clear "missing tool"
        # error before any terminal/shell machinery runs.
        self._validate_required_tool(worker_type)

        # Dispatch by runtime_kind. SHELL workers go to ShellWorker;
        # everything else falls through to the isolated-worker factory
        # (which only accepts "shepherd" per the 2026-09-24 deprecation
        # decision and raises a clear ValueError for everything else).
        if config.runtime_kind == RuntimeKind.SHELL:
            return ShellWorker(
                config=config,
                terminal_manager=self.terminal_manager,
                session_buddy_client=self.session_buddy_client,
                permission_mode=self._resolve_permission_mode(config),
            )
        return self._create_isolated_worker_from_config(config, kwargs)

    def _create_isolated_worker_from_config(
        self,
        config: WorkerConfig,
        kwargs: dict[str, Any],
    ) -> BaseWorker:
        """Adapter from :class:`WorkerConfig` to ``_create_isolated_worker``'s kwargs.

        Lets :meth:`_create_worker` route every request through the
        single dispatch that already knows how to fail loud on retired
        worker_types. Replaces the previous category-keyed ``if``/``elif``
        chain that hard-coded constructors for every category (all of
        which have since been retired).

        Args:
            config: Resolved :class:`WorkerConfig` from the registry.
            kwargs: Forwarded to :func:`_create_isolated_worker`.

        Returns:
            The constructed :class:`BaseWorker`.
        """
        return _create_isolated_worker(
            worker_type=config.worker_type,
            session_buddy_client=self.session_buddy_client,
            kwargs=kwargs,
        )

    async def execute_task(
        self,
        worker_id: str,
        task: dict[str, Any],
    ) -> WorkerResult:
        """Execute task on specific worker.

        Args:
            worker_id: Worker ID
            task: Task specification

        Returns:
            WorkerResult with execution results

        Raises:
            ValueError: If worker not found
        """
        worker = self._workers.get(worker_id)
        if not worker:
            raise ValueError(f"Worker not found: {worker_id}")

        worker_type = getattr(worker, "worker_type", "unknown")
        adapter = "worker_manager"

        async with self._semaphore:
            agent_tasks_in_progress.labels(agent_type=worker_type, adapter=adapter).inc()
            try:
                logger.info(f"Executing task on worker {worker_id}")
                # Bounded execution: a hung worker would otherwise hold this
                # semaphore slot indefinitely and starve every subsequent
                # pool_execute. ``asyncio.wait_for`` cancels the inner awaitable
                # on timeout; workers that spawn their own background tasks
                # are responsible for their own cancellation propagation.
                default_timeout = getattr(worker, "config", None)
                default_timeout_s = (
                    getattr(default_timeout, "default_timeout", None)
                    if default_timeout is not None
                    else None
                )
                timeout_s = task.get("timeout", default_timeout_s)
                try:
                    if timeout_s is not None and float(timeout_s) > 0:
                        result = await asyncio.wait_for(
                            worker.execute(task), timeout=float(timeout_s)
                        )
                    else:
                        result = await worker.execute(task)
                except TimeoutError:
                    logger.warning(
                        "Worker %s timed out after %ss; releasing semaphore slot",
                        worker_id,
                        timeout_s,
                    )
                    return WorkerResult(
                        worker_id=worker_id,
                        status=WorkerStatus.TIMEOUT,
                        output=None,
                        error=f"worker execute() exceeded timeout of {timeout_s}s",
                        exit_code=None,
                        duration_seconds=float(timeout_s) if timeout_s else 0.0,
                        metadata={"timeout": True, "timeout_seconds": timeout_s},
                    )
                agent_tasks_total.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                    status=result.status.value,
                ).inc()
                agent_task_duration_seconds.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                ).observe(result.duration_seconds)
                logger.info(
                    f"Worker {worker_id} completed: {result.status.value} "
                    f"({result.duration_seconds:.2f}s)"
                )
                return result
            except Exception as e:  # Background task — worker execution converts every failure into a FAILED WorkerResult with metrics update  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.error(f"Worker {worker_id} failed: {e}")
                failure_result = WorkerResult(
                    worker_id=worker_id,
                    status=WorkerStatus.FAILED,
                    output=None,
                    error=str(e),
                    exit_code=None,
                    duration_seconds=0,
                    metadata={"exception": type(e).__name__},
                )
                agent_tasks_total.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                    status=failure_result.status.value,
                ).inc()
                agent_task_duration_seconds.labels(
                    agent_type=worker_type,
                    adapter=adapter,
                ).observe(failure_result.duration_seconds)
                return failure_result
            finally:
                agent_tasks_in_progress.labels(agent_type=worker_type, adapter=adapter).dec()

    async def execute_batch(
        self,
        worker_ids: list[str],
        tasks: list[dict[str, Any]],
    ) -> dict[str, WorkerResult]:
        """Execute tasks on multiple workers concurrently.

        Args:
            worker_ids: List of worker IDs
            tasks: List of task specs (same length as worker_ids)

        Returns:
            Dictionary mapping worker_id -> WorkerResult

        Raises:
            ValueError: If worker_ids and tasks length mismatch
        """
        if len(worker_ids) != len(tasks):
            raise ValueError("worker_ids and tasks must have same length")

        async def execute_one(worker_id: str, task: dict[str, Any]) -> tuple[str, WorkerResult]:
            result = await self.execute_task(worker_id, task)
            return worker_id, result

        # Execute all tasks concurrently
        coros = [execute_one(wid, task) for wid, task in zip(worker_ids, tasks, strict=False)]
        results = await asyncio.gather(*coros)

        logger.info(f"Completed {len(results)} worker tasks")

        return dict(results)

    async def monitor_workers(
        self,
        worker_ids: list[str] | None = None,
        interval: float = 1.0,
    ) -> dict[str, WorkerStatus]:
        """Monitor status of multiple workers.

        Args:
            worker_ids: List of worker IDs (None = all workers)
            interval: Polling interval in seconds

        Returns:
            Dictionary mapping worker_id -> status
        """
        if worker_ids is None:
            worker_ids = list(self._workers.keys())

        statuses = {}

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker:
                try:
                    status = await worker.status()
                    statuses[wid] = status
                except Exception as e:  # Background task — monitor loop must keep going when a single worker probe fails  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                    logger.warning(f"Failed to get status for {wid}: {e}")
                    statuses[wid] = WorkerStatus.FAILED

        await asyncio.sleep(interval)
        return statuses

    async def collect_results(
        self,
        worker_ids: list[str] | None = None,
    ) -> dict[str, WorkerResult]:
        """Collect results from completed workers.

        Args:
            worker_ids: List of worker IDs (None = all workers)

        Returns:
            Dictionary mapping worker_id -> WorkerResult
        """
        if worker_ids is None:
            worker_ids = list(self._workers.keys())

        results = {}

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker:
                try:
                    # Get final output/status
                    progress = await worker.get_progress()

                    # Build result from progress
                    status = WorkerStatus(progress.get("status", "unknown"))
                    results[wid] = WorkerResult(
                        worker_id=wid,
                        status=status,
                        output=progress.get("output_preview"),
                        error=None,
                        exit_code=0 if status == WorkerStatus.COMPLETED else 1,
                        duration_seconds=progress.get("duration_seconds", 0),
                        metadata=progress,
                    )
                except Exception as e:  # Background task — result collector keeps going when a single worker fetch fails  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                    logger.error(f"Failed to collect result from {wid}: {e}")
                    results[wid] = WorkerResult(
                        worker_id=wid,
                        status=WorkerStatus.FAILED,
                        output=None,
                        error=str(e),
                        exit_code=None,
                        duration_seconds=0,
                        metadata={"error": str(e)},
                    )

        return results

    async def close_worker(self, worker_id: str) -> None:
        """Close a specific worker.

        Args:
            worker_id: Worker ID to close
        """
        worker = self._workers.get(worker_id)
        if worker:
            try:
                await worker.stop()
                logger.info(f"Closed worker {worker_id}")
            except Exception as e:  # Background task — close failures must not break the calling cleanup path  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                logger.error(f"Failed to close worker {worker_id}: {e}")
            finally:
                self._workers.pop(worker_id, None)

    async def close_all(self) -> None:
        """Close all active workers."""
        worker_ids = list(self._workers.keys())
        if worker_ids:
            logger.info(f"Closing {len(worker_ids)} workers...")
            tasks = [self.close_worker(wid) for wid in worker_ids]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def list_workers(self) -> list[dict[str, Any]]:
        """List all active workers.

        Returns:
            List of worker information dictionaries
        """
        workers_info = []

        for wid, worker in self._workers.items():
            try:
                status = await worker.status()
                workers_info.append(
                    {
                        "worker_id": wid,
                        "worker_type": worker.worker_type,
                        "status": status.value,
                    }
                )
            except Exception:  # Background task — list snapshot keeps going when a single worker status probe fails  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                workers_info.append(
                    {
                        "worker_id": wid,
                        "worker_type": worker.worker_type,
                        "status": "unknown",
                    }
                )

        return workers_info

    async def health_check(self) -> dict[str, Any]:
        """Get worker system health.

        Returns:
            Dictionary with health status
        """
        workers_list = await self.list_workers()

        return {
            "status": "healthy",
            "workers_active": len(workers_list),
            "max_concurrent": self.max_concurrent,
            "workers": workers_list,
        }
