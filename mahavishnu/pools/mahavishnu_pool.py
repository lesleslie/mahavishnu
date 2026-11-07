"""Direct worker management by Mahavishnu.

Wraps existing WorkerManager to provide pool abstraction.

Substrate-wrapper rationale (Plan v3 §10 #5 analysis, 2026-09-25):
This pool is a leaf substrate wrapper, not a child of PoolManager.
It wraps WorkerManager the same way SessionBuddyPool wraps
CommonMCPClient and RunPodPool wraps ``runpod.Endpoint``. Do NOT
rewrite execute_task to call pool_manager.route_task — that would
create a circular dependency and double-enforce the per-CallerKind
quota. See docs/POOL_ARCHITECTURE.md "Why pool types wrap substrates,
not delegate to PoolManager.route_task" for the full rationale.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from ..workers.manager import WorkerManager
from ..workers.registry import RuntimeKind, get_worker_config
from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager

logger = logging.getLogger(__name__)


def _initialize_shepherd_workspace(path: Path) -> bool:
    """Create the Shepherd workspace inside ``path``.

    A pool workspace is a Shepherd workspace, and a Shepherd workspace is a
    git-backed store (``.vcscore``) that lives INSIDE the workspace
    directory -- not the directory itself. Creating the directory alone
    left every Shepherd worker failing closed with MHV-312 ("not a
    Shepherd workspace. Run `sp init` first"), which put an invisible
    operator step between "spawn a pool" and "it works": the failure
    surfaced only as a worker that never started, with the real cause
    buried in the pool's logs.

    ``initialize_workspace`` is Shepherd's own bootstrap -- the same call
    ``sp init`` makes -- so there is one implementation rather than two,
    and no dependency on the ``sp`` executable being on the server's PATH
    (it is not: it lives in the venv's ``bin/``, which launchd does not
    put on PATH).

    Args:
        path: The workspace directory to initialize.

    Returns:
        True when the workspace is ready to be discovered.
    """
    try:
        from shepherd_dialect import initialize_workspace
    except ImportError:
        logger.exception(
            "Cannot auto-initialize the Shepherd workspace at %s. "
            "Install the 'shepherd-ai' extra, or run `sp init %s` by hand.",
            path,
            path,
        )
        return False
    try:
        initialize_workspace(path, adopt="none")
    except Exception:  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
        logger.exception(
            "Failed to auto-initialize the Shepherd workspace at %s. "
            "Run `sp init %s` by hand.",
            path,
            path,
        )
        return False
    logger.info(
        "Auto-initialized the Shepherd workspace at %s. The pool owns "
        "initializing it — a Shepherd worker there would otherwise fail "
        "closed with MHV-312.",
        path,
    )
    return True


def _resolve_settings() -> Any:
    """Return the project settings, or ``None`` when they cannot be loaded.

    The settings carry ``workers.enabled``, which the worker capability
    check reads before it will spawn anything. Loading them is best
    effort: a pool that cannot read the settings still runs, and the
    capability check then reports what it can.
    """
    from ..core.config import get_settings

    try:
        return get_settings()
    except Exception as exc:  # MCP tool error handler — settings load is best-effort, never fatal  # noqa: BLE001, RUF100
        logger.warning(f"Could not load settings for the pool: {exc}")
        return None


class MahavishnuPool(BasePool):
    """Direct worker management by Mahavishnu.

    Wraps existing WorkerManager to provide pool abstraction.
    Workers run locally in Mahavishnu's process context.

    Use Cases:
    - Local development and testing
    - Low-latency task execution
    - Debugging and monitoring
    - CI/CD pipeline automation

    Architecture:
    ┌─────────────────────────────────────┐
    │         MahavishnuPool              │
    │  ┌───────────────────────────────┐  │
    │  │    WorkerManager (EXISTING)   │  │
    │  │  • spawn_workers()            │  │
    │  │  • execute_task()             │  │
    │  │  • execute_batch()            │  │
    │  │  • monitor_workers()          │  │
    │  └───────────────────────────────┘  │
    │           │                          │
    │           ↓                          │
    │  ┌───────────────────────────────┐  │
    │  │      Local Workers            │  │
    │  │  • GenericShellWorker (Qwen)   │  │
    │  │  • GenericShellWorker (Claude) │  │
    │  │  • shepherd (OS syscall-jail) │  │
    │  └───────────────────────────────┘  │
    └─────────────────────────────────────┘

    Note: After Plan v3 Phase 4.5b (legacy-worker-deprecation), only
    `shepherd_backend` remains as the isolated-worker backend. The
    prior AppleContainer / E2B microVM tiers were removed 2026-09-25 —
    see `docs/decisions/2026-09-24-legacy-worker-deprecation.md`.
    """

    def __init__(
        self,
        config: PoolConfig,
        terminal_manager: TerminalManager,
        session_buddy_client: Any = None,
        settings: Any = None,
    ):
        """Initialize MahavishnuPool.

        Args:
            config: Pool configuration
            terminal_manager: TerminalManager for terminal control
            session_buddy_client: Optional Session-Buddy MCP client
            settings: Settings used for the worker capability check.
                Resolved from the project when not supplied.
        """
        super().__init__(config)
        self.terminal_manager = terminal_manager
        self.session_buddy_client = session_buddy_client

        # The WorkerManager evaluates a worker's capability against the
        # settings before it will spawn one, and the first thing it reads
        # is ``workers.enabled``. With no settings object at all that
        # lookup resolves to None, which reads as False -- so every
        # dispatch was refused with "workers disabled by config" and
        # "missing_requirements: workers.enabled", whatever the YAML
        # actually said.
        if settings is None:
            settings = _resolve_settings()
        self.settings = settings
        # A one-shot CLI harness takes its prompt with the launch command
        # and the CLI exits when it is done, so the pool launches one
        # session per task instead of holding a pool of idle sessions.
        #
        # Only the SHELL-runtime one-shot workers qualify. The other
        # one-shot types (shepherd, container, openhands, ...) are
        # isolated workers with their own lifecycle, and they do not
        # consume a prompt at all -- they take a command or a task ref.
        worker_config = get_worker_config(config.worker_type)
        self._is_one_shot = bool(
            worker_config
            and worker_config.one_shot
            and worker_config.runtime_kind is RuntimeKind.SHELL
        )

        # Resolve writable_root for ShepherdBackendWorker (the post-2026-09-24
        # default worker substrate; see docs/decisions/2026-09-24-
        # legacy-worker-deprecation.md). Falls back to a per-pool subdir
        # of $XDG_DATA_HOME/mahavishnu/pools/ when the config doesn't
        # specify one, so the spawn no longer raises MHV-312.
        # Resolution order (first existing/writable wins):
        #   1. config.writable_root (if set on PoolConfig)
        #   2. ~/.local/state/mahavishnu/worktrees/<pool_name>/workspace
        #      (matches the worktree preference in CLAUDE.md; persistent
        #      across reboots)
        #   3. user_data_dir/mahavishnu/pools/<pool_name>/workspace
        #      (XDG-style; per-OS default)
        #   4. /tmp/mahavishnu-ephemeral/<pool_name>/workspace
        #      (last-resort for serverless / ephemeral workers; lost on
        #      reboot but always writable in containerized contexts)
        config_writable_root = getattr(config, "writable_root", None)
        if config_writable_root:
            self.writable_root = Path(config_writable_root).resolve()
            self.writable_root.mkdir(parents=True, exist_ok=True)
        else:
            candidates = [
                Path.home()
                / ".local"
                / "state"
                / "mahavishnu"
                / "worktrees"
                / config.name
                / "workspace",
            ]
            try:
                from platformdirs import user_data_dir

                base = Path(user_data_dir("mahavishnu", "BodaiEcosystem", roaming=False))
                candidates.append(base / "pools" / config.name / "workspace")
            except ImportError, OSError:
                logger.exception(
                    "platformdirs unavailable or user_data_dir failed; skipping platform candidate"
                )
            candidates.append(Path("/tmp") / "mahavishnu-ephemeral" / config.name / "workspace")

            chosen: Path | None = None
            for candidate in candidates:
                try:
                    candidate.mkdir(parents=True, exist_ok=True)
                    if candidate.resolve().exists():
                        chosen = candidate.resolve()
                        break
                except OSError, PermissionError:
                    continue
            if chosen is None:
                # Last-resort: use the first candidate and let the worker's
                # own mkdir surface the error downstream if creation still
                # fails. Better than refusing to spawn at the pool level.
                chosen = candidates[0].resolve()
            self.writable_root = chosen

        # Whether the workspace directory is empty decides whether the pool
        # initializes the Shepherd workspace inside it.
        #
        # An EMPTY directory is the pool's to fill: it is either one the
        # pool just created or an empty leftover from an earlier run, and
        # a Shepherd pool needs a Shepherd workspace in it. That is what
        # makes the fix reach pools that were created before it existed --
        # their workspace directory is there but uninitialized.
        #
        # A directory with CONTENT in it belongs to the operator, and a
        # missing Shepherd workspace there is a misconfiguration to report
        # rather than to paper over: initializing it would drop a
        # ``.vcscore`` store into somebody's directory without asking.
        if self._workspace_is_empty():
            _initialize_shepherd_workspace(self.writable_root)

        # Wrap existing WorkerManager
        self.worker_manager = WorkerManager(
            terminal_manager=terminal_manager,
            max_concurrent=config.max_workers,
            session_buddy_client=session_buddy_client,
            writable_root=self.writable_root,
            settings=self.settings,
        )

        # Track task statistics for metrics
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

    def _workspace_is_empty(self) -> bool:
        """Whether the workspace directory holds nothing.

        True for a directory that does not exist yet, and for one with no
        entries. An unreadable directory counts as NOT empty: the safe
        answer is the one that does not mutate somebody's files.
        """
        try:
            if not self.writable_root.exists():
                return True
            return not any(self.writable_root.iterdir())
        except OSError:
            return False

    async def start(self) -> str:
        """Initialize pool and spawn initial workers.

        Returns:
            pool_id: Unique pool identifier

        Raises:
            RuntimeError: If terminal_manager is not available, or if the
                worker_type's ``requires_tool`` is missing from ``PATH``.
                The tool check runs first so callers see a clear, named
                ``requires_tool`` error before the generic terminal_manager
                unavailability error.
        """
        self._status = PoolStatus.INITIALIZING

        # Reject early with a clear message when the worker_type's declared
        # ``requires_tool`` is missing from PATH. Without this check, the
        # underlying shell machinery raises an opaque error (e.g.
        # ``Command failed`` / ``AttributeError: 'NoneType' object has no
        # attribute 'X'``) far away from the actual misconfiguration.
        worker_type = getattr(self.config, "worker_type", None)
        if worker_type:
            import shutil

            from ..core.errors import ErrorCode, MahavishnuError
            from ..workers.registry import get_worker_entry

            try:
                entry = get_worker_entry(worker_type)
            except MahavishnuError as exc:
                if exc.error_code is not ErrorCode.RESOURCE_NOT_FOUND:
                    raise
            else:
                required_tool = entry.requires_tool
                if required_tool and shutil.which(required_tool) is None:
                    self._status = PoolStatus.FAILED
                    raise RuntimeError(
                        f"Worker {worker_type!r} requires tool "
                        f"{required_tool!r} which is not on PATH"
                    )

        # Verify terminal_manager is available before spawning workers
        if self.terminal_manager is None:
            self._status = PoolStatus.FAILED
            raise RuntimeError(
                "Cannot spawn pool: terminal_manager is not available. "
                "Ensure terminal management is enabled and the adapter is properly initialized. "
                "Check logs for terminal manager initialization errors."
            )

        # Spawn minimum workers (writable_root is the ShepherdBackendWorker's
        # required kwarg; we set it on WorkerManager.__init__ above, but pass
        # per-call here so future per-spawn overrides are easy to add).
        #
        # A one-shot CLI is the exception: it reads its prompt from the
        # launch command, so a session spawned now would have no prompt
        # and the CLI would exit immediately. Those sessions are launched
        # per task instead -- see ``_execute_one_shot_task``.
        if self._is_one_shot:
            self._workers = {}
        else:
            worker_ids = await self.worker_manager.spawn_workers(
                worker_type=self.config.worker_type,
                count=self.config.min_workers,
                writable_root=self.writable_root,
            )
            self._workers = {wid: f"worker_{wid}" for wid in worker_ids}
        self._status = PoolStatus.RUNNING

        logger.info(
            f"MahavishnuPool {self.pool_id} started with {len(self._workers)} "
            f"pre-spawned workers (one_shot={self._is_one_shot})"
        )

        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task on available worker (auto-select).

        Args:
            task: Task specification with pool-specific parameters
                Common fields: prompt, timeout, command, etc.

        Returns:
            Execution result with worker_id, output, status
        """
        if self._is_one_shot:
            return await self._execute_one_shot_task(task)

        # Get first available worker
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_id = next(iter(self._workers.keys()))

        start_time = time.time()
        result = await self.worker_manager.execute_task(worker_id, task)
        duration = time.time() - start_time

        # Track statistics
        if result.status.value == "completed":
            self._tasks_completed += 1
        else:
            self._tasks_failed += 1
        self._task_durations.append(duration)

        return {
            "pool_id": self.pool_id,
            "worker_id": result.worker_id,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "duration": duration,
        }

    async def _execute_one_shot_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run one task on a freshly launched one-shot worker.

        A one-shot CLI takes its prompt with the launch command -- it
        rides the command line as ``MAHAVISHNU_PROMPT`` -- so the session
        has to be started *after* the prompt is known. A pool that
        pre-spawned workers could only deliver the prompt by typing it
        into the CLI's TUI over tmux keystrokes, which depends on the
        CLI being ready to read it and on its Enter semantics: both are
        outside this codebase's control, and both have gone wrong. The
        prompt sat unsubmitted in the input buffer and the dispatch ran
        out its timeout with the CLI idle.

        Launching per task costs one session per dispatch, which is the
        price of the contract: the session exists to run one prompt, and
        the CLI exits when it is done.
        """
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(
                f"Pool {self.pool_id!r} runs the one-shot worker "
                f"{self.config.worker_type!r}, which needs a non-empty 'prompt'."
            )

        start_time = time.time()
        worker_ids = await self.worker_manager.submit_workers(
            self.config.worker_type,
            [prompt],
        )
        worker_id = worker_ids[0]
        try:
            results = await self.worker_manager.execute_batch(worker_ids, [task])
        finally:
            await self.worker_manager.close_worker(worker_id)

        result = results.get(worker_id)
        if result is None:
            raise RuntimeError(f"Pool {self.pool_id!r}: worker {worker_id} produced no result")

        duration = time.time() - start_time
        if result.status.value == "completed":
            self._tasks_completed += 1
        else:
            self._tasks_failed += 1
        self._task_durations.append(duration)

        return {
            "pool_id": self.pool_id,
            "worker_id": result.worker_id,
            "status": result.status.value,
            "output": result.output,
            "error": result.error,
            "duration": duration,
        }

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Execute tasks across all workers.

        Args:
            tasks: List of task specifications

        Returns:
            Dictionary mapping task_id -> result
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_ids = list(self._workers.keys())

        # Round-robin task assignment
        worker_tasks = [(worker_ids[i % len(worker_ids)], task) for i, task in enumerate(tasks)]

        start_time = time.time()
        results = await self.worker_manager.execute_batch(
            worker_ids=[wt[0] for wt in worker_tasks],
            tasks=[wt[1] for wt in worker_tasks],
        )
        total_duration = time.time() - start_time

        # Track statistics
        for result in results.values():
            if result.status.value == "completed":
                self._tasks_completed += 1
            else:
                self._tasks_failed += 1
            self._task_durations.append(result.duration_seconds)

        # Map task IDs to results
        task_results: dict[str, dict[str, Any]] = {}
        for task_id, (_, result) in enumerate(zip(tasks, results.values(), strict=False)):
            task_results[str(task_id)] = {
                "pool_id": self.pool_id,
                "worker_id": result.worker_id,
                "status": result.status.value,
                "output": result.output,
            }

        logger.info(
            f"MahavishnuPool {self.pool_id} executed {len(tasks)} tasks in {total_duration:.2f}s"
        )

        return task_results

    async def scale(self, target_worker_count: int) -> None:
        """Scale pool to target worker count.

        Args:
            target_worker_count: Desired number of workers

        Raises:
            ValueError: If target outside [min_workers, max_workers]
        """
        if not (self.config.min_workers <= target_worker_count <= self.config.max_workers):
            raise ValueError(
                f"Target {target_worker_count} outside range "
                f"[{self.config.min_workers}, {self.config.max_workers}]"
            )

        self._status = PoolStatus.SCALING

        current_count = len(self._workers)

        if target_worker_count > current_count:
            # Scale up
            logger.info(
                f"Scaling up MahavishnuPool {self.pool_id}: {current_count} → {target_worker_count}"
            )
            new_workers = await self.worker_manager.spawn_workers(
                worker_type=self.config.worker_type,
                count=target_worker_count - current_count,
            )
            for wid in new_workers:
                self._workers[wid] = f"worker_{wid}"

        elif target_worker_count < current_count:
            # Scale down
            logger.info(
                f"Scaling down MahavishnuPool {self.pool_id}: "
                f"{current_count} → {target_worker_count}"
            )
            workers_to_remove = list(self._workers.keys())[target_worker_count:]
            for wid in workers_to_remove:
                await self.worker_manager.close_worker(wid)
                del self._workers[wid]

        self._status = PoolStatus.RUNNING

    async def health_check(self) -> dict[str, Any]:
        """Check pool health via WorkerManager.

        Returns:
            Health status with degraded/unhealthy indicators
        """
        health = await self.worker_manager.health_check()

        # Determine overall health
        if health.get("status") == "healthy" and len(self._workers) >= self.config.min_workers:
            pool_status = "healthy"
        elif len(self._workers) > 0:
            pool_status = "degraded"
        else:
            pool_status = "unhealthy"

        return {
            "pool_id": self.pool_id,
            "pool_type": "mahavishnu",
            "status": pool_status,
            "workers_active": len(self._workers),
            "worker_health": health,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
        }

    async def get_metrics(self) -> PoolMetrics:
        """Get real-time pool metrics.

        Returns:
            PoolMetrics with current stats
        """
        await self.health_check()

        # Calculate average task duration
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )

        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=len(self._workers),
            total_workers=len(self._workers),
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,  # Track via psutil if needed
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Collect worker results for Session-Buddy.

        Returns:
            List of memory dictionaries for Session-Buddy storage
        """
        results = await self.worker_manager.collect_results()

        # Transform WorkerResults to memory format
        memory_items = []
        for result in results.values():
            memory_items.append(
                {
                    "content": result.output or "",
                    "metadata": {
                        "type": "pool_worker_execution",
                        "pool_id": self.pool_id,
                        "pool_type": "mahavishnu",
                        "worker_id": result.worker_id,
                        "status": result.status.value,
                        "duration_seconds": result.duration_seconds,
                        "exit_code": result.exit_code,
                        "error": result.error,
                        "timestamp": time.time(),
                    },
                }
            )

        logger.info(f"Collected {len(memory_items)} memory items from pool {self.pool_id}")

        return memory_items

    async def stop(self) -> None:
        """Shutdown pool and all workers."""
        logger.info(f"Stopping MahavishnuPool {self.pool_id}...")
        await self.worker_manager.close_all()
        self._status = PoolStatus.STOPPED
        logger.info(f"MahavishnuPool {self.pool_id} stopped")


# Registry integration: factory consumes kwargs forwarded by PoolManager.spawn_pool.
# The MahavishnuPool constructor needs terminal_manager and session_buddy_client from
# the enclosing PoolManager instance.
def _build_mahavishnu_pool(
    config: PoolConfig,
    *,
    terminal_manager: TerminalManager,
    session_buddy_client: Any = None,
) -> MahavishnuPool:
    return MahavishnuPool(
        config=config,
        terminal_manager=terminal_manager,
        session_buddy_client=session_buddy_client,
    )


from ._registry import register_pool_type

register_pool_type("mahavishnu", _build_mahavishnu_pool)
