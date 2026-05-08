"""Worker orchestrator adapter for task execution."""

from __future__ import annotations

import asyncio
from typing import Any

from ...workers.manager import WorkerManager
from ...workers.registry import resolve_worker_type
from ..adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter


class WorkerOrchestratorAdapter(OrchestratorAdapter):
    """Orchestrator adapter for worker-based task execution.

    Implements the OrchestratorAdapter interface to integrate
    worker execution into Mahavishnu's orchestration layer.

    This adapter enables Mahavishnu to spawn and manage headless AI workers
    (Qwen, Claude Code) for executing tasks across multiple repositories.

    Args:
        worker_manager: WorkerManager instance for lifecycle management

    Example:
        >>> adapter = WorkerOrchestratorAdapter(worker_manager)
        >>> task = {
        ...     "type": "code_generation",
        ...     "worker_type": "terminal-qwen",
        ...     "prompt": "Implement a REST API",
        ...     "count": 3,
        ... }
        >>> result = await adapter.execute(task, ["/path/to/repo"])
    """

    def __init__(self, config: Any = None, worker_manager: WorkerManager | None = None) -> None:
        """Initialize worker orchestrator adapter.

        Args:
            config: Mahavishnu settings (used when worker_manager is not provided)
            worker_manager: Optional pre-built WorkerManager instance
        """
        self._config = config
        self._needs_lazy_init = False

        if worker_manager is None and isinstance(config, WorkerManager):
            worker_manager = config

        if worker_manager is not None:
            self.worker_manager = worker_manager
            self._config = None
            return

        if config is None:
            raise ValueError("Either config or worker_manager must be provided")

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop and running_loop.is_running():
            self.worker_manager = None
            self._needs_lazy_init = True
            return

        self.worker_manager = asyncio.run(self._build_worker_manager(config))

    async def _build_worker_manager(self, config: Any) -> WorkerManager:
        """Build a worker manager from adapter config."""
        from ...terminal.manager import TerminalManager

        terminal_mgr = await TerminalManager.create(
            config,
            mcp_client=None,  # Session-Buddy integration remains optional
        )
        max_concurrent = getattr(getattr(config, "workers", None), "max_concurrent", 10)

        return WorkerManager(
            terminal_manager=terminal_mgr,
            max_concurrent=max_concurrent,
            debug_mode=False,
            session_buddy_client=None,
        )

    async def _ensure_worker_manager(self) -> WorkerManager:
        """Ensure a worker manager exists, building it lazily if needed."""
        if self.worker_manager is not None:
            return self.worker_manager

        if self._config is None:
            raise RuntimeError("Worker manager configuration is unavailable")

        self.worker_manager = await self._build_worker_manager(self._config)
        self._needs_lazy_init = False
        return self.worker_manager

    @property
    def adapter_type(self) -> AdapterType:
        """Return adapter type enum."""
        return AdapterType.WORKER

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "worker"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities."""
        return AdapterCapabilities(
            can_deploy_flows=False,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            has_cloud_ui=False,
            supports_multi_agent=False,
        )

    async def initialize(self) -> None:
        """Initialize the worker adapter."""
        if self.worker_manager is None and self._config is not None:
            await self._ensure_worker_manager()
        return None

    async def cleanup(self) -> None:
        """Cleanup worker resources."""
        return None

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> dict[str, Any]:
        """Execute task using worker pool.

        Spawns workers, distributes tasks across them, and collects results.

        Args:
            task: Task specification with keys:
                - worker_type: Type of worker to spawn ("terminal-qwen", "terminal-claude")
                - prompt: Task prompt for AI workers
                - count: Number of workers to spawn
                - timeout: Task timeout in seconds (default: 300)
                - task_type: Optional task type identifier
            repos: List of repository paths for context

        Returns:
            Execution results with:
                - status: Overall execution status
                - worker_count: Number of workers spawned
                - results: Dictionary mapping worker_id -> result
                - total_duration: Total execution time

        Raises:
            ValueError: If task parameters are invalid
        """
        import logging
        import time

        logger = logging.getLogger(__name__)
        start_time = time.time()
        worker_manager = await self._ensure_worker_manager()

        # Extract task parameters
        requested_worker_type = task.get("worker_type", "terminal-qwen")
        count = task.get("count", len(repos))
        prompt = task.get("prompt", "")
        timeout = task.get("timeout", 300)
        task_type = task.get("task_type", "general")
        worker_type = resolve_worker_type(requested_worker_type, task_type=task_type, prompt=prompt)

        # Validate parameters
        if not prompt:
            raise ValueError("Task must include 'prompt' field")

        if count < 1:
            raise ValueError("Worker count must be at least 1")

        logger.info(
            f"Executing {task_type} task with {count} {worker_type} workers "
            f"across {len(repos)} repos"
        )

        # Spawn workers
        try:
            worker_ids = await worker_manager.spawn_workers(
                worker_type=worker_type,
                count=count,
            )
            logger.info(f"Spawned {len(worker_ids)} workers: {', '.join(worker_ids)}")
        except Exception as e:
            logger.error(f"Failed to spawn workers: {e}")
            raise

        # Distribute repos across workers (round-robin)
        tasks = []
        for i, _worker_id in enumerate(worker_ids):
            repo = repos[i % len(repos)] if repos else None
            task_spec = {
                "prompt": f"Working in {repo}. {prompt}" if repo else prompt,
                "timeout": timeout,
                "repo": repo,
                "task_type": task_type,
            }
            tasks.append(task_spec)

        # Execute tasks across workers
        try:
            results = await worker_manager.execute_batch(
                worker_ids,
                tasks,
            )
        except Exception as e:
            logger.error(f"Failed to execute tasks: {e}")
            # Partial results may exist
            results = await worker_manager.collect_results(worker_ids)

        # Aggregate results
        total_duration = time.time() - start_time
        successful = sum(1 for r in results.values() if r.is_success())
        failed = len(results) - successful

        logger.info(
            f"Task execution complete: {successful} successful, {failed} failed, "
            f"{total_duration:.2f}s total"
        )

        return {
            "status": "completed" if failed == 0 else "partial",
            "worker_count": len(worker_ids),
            "requested_worker_type": requested_worker_type,
            "resolved_worker_type": worker_type,
            "successful": successful,
            "failed": failed,
            "total_duration": total_duration,
            "results": {
                wid: {
                    "status": result.status.value,
                    "output": result.output[:200] + "..."
                    if result.output and len(result.output) > 200
                    else result.output,
                    "duration": result.duration_seconds,
                    "has_output": result.has_output(),
                }
                for wid, result in results.items()
            },
        }

    async def get_health(self) -> dict[str, Any]:
        """Get worker system health.

        Returns:
            Health status with:
                - status: Overall health status ("healthy", "degraded", "unhealthy")
                - workers_active: Number of active workers
                - max_concurrent: Maximum concurrent workers
                - details: Additional health details
        """
        worker_manager = await self._ensure_worker_manager()
        health = await worker_manager.health_check()

        # Map to orchestrator adapter format
        workers_active = health.get("workers_active", 0)
        max_concurrent = health.get("max_concurrent", 10)

        status = "healthy" if workers_active == 0 or workers_active < max_concurrent else "degraded"

        return {
            "status": status,
            "adapter_type": "worker",
            "workers_active": workers_active,
            "max_concurrent": max_concurrent,
            "debug_mode": health.get("debug_mode", False),
            "details": health,
        }

# =============================================================================
# Entry Point for Hybrid Adapter Registry
# =============================================================================


def worker_adapter_entries() -> list[dict[str, Any]]:
    """Entry point for Worker adapter registration.

    This function is called by the HybridAdapterRegistry during
    discovery to register the Worker adapter.

    Returns:
        List of adapter metadata dictionaries
    """
    return [
        {
            "category": "orchestration",
            "provider": "worker",
            "factory_path": "mahavishnu.core.adapters.worker:WorkerOrchestratorAdapter",
            "description": "Worker-based task execution for AI workers",
            "capabilities": [
                "task_execution",
                "worker_pool",
                "parallel_execution",
                "terminal_workers",
            ],
            "priority": 75,
            "domain": "orchestration",
        }
    ]


__all__ = ["WorkerOrchestratorAdapter", "worker_adapter_entries"]
