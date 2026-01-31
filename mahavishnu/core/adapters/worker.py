"""Worker orchestrator adapter for task execution."""

from typing import Any

from ..adapters.base import OrchestratorAdapter
from ...workers.manager import WorkerManager


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

    def __init__(self, worker_manager: WorkerManager) -> None:
        """Initialize worker orchestrator adapter.

        Args:
            worker_manager: WorkerManager instance
        """
        self.worker_manager = worker_manager

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
        import time
        import logging

        logger = logging.getLogger(__name__)
        start_time = time.time()

        # Extract task parameters
        worker_type = task.get("worker_type", "terminal-qwen")
        count = task.get("count", len(repos))
        prompt = task.get("prompt", "")
        timeout = task.get("timeout", 300)
        task_type = task.get("task_type", "general")

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
            worker_ids = await self.worker_manager.spawn_workers(
                worker_type=worker_type,
                count=count,
            )
            logger.info(f"Spawned {len(worker_ids)} workers: {', '.join(worker_ids)}")
        except Exception as e:
            logger.error(f"Failed to spawn workers: {e}")
            raise

        # Distribute repos across workers (round-robin)
        tasks = []
        for i, worker_id in enumerate(worker_ids):
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
            results = await self.worker_manager.execute_batch(
                worker_ids,
                tasks,
            )
        except Exception as e:
            logger.error(f"Failed to execute tasks: {e}")
            # Partial results may exist
            results = await self.worker_manager.collect_results(worker_ids)

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
            "successful": successful,
            "failed": failed,
            "total_duration": total_duration,
            "results": {
                wid: {
                    "status": result.status.value,
                    "output": result.output[:200] + "..." if result.output and len(result.output) > 200 else result.output,
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
        health = await self.worker_manager.health_check()

        # Map to orchestrator adapter format
        workers_active = health.get("workers_active", 0)
        max_concurrent = health.get("max_concurrent", 10)

        if workers_active == 0:
            status = "healthy"
        elif workers_active < max_concurrent:
            status = "healthy"
        else:
            status = "degraded"

        return {
            "status": status,
            "adapter_type": "worker",
            "workers_active": workers_active,
            "max_concurrent": max_concurrent,
            "debug_mode": health.get("debug_mode", False),
            "details": health,
        }
