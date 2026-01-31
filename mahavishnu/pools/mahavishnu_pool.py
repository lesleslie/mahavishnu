"""Direct worker management by Mahavishnu.

Wraps existing WorkerManager to provide pool abstraction.
"""

import logging
import time
from typing import Any

from ..terminal.manager import TerminalManager
from ..workers.manager import WorkerManager
from .base import BasePool, PoolConfig, PoolStatus

logger = logging.getLogger(__name__)


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
    │  │  • TerminalAIWorker (Qwen)    │  │
    │  │  • TerminalAIWorker (Claude)  │  │
    │  │  • ContainerWorker (Docker)   │  │
    │  └───────────────────────────────┘  │
    └─────────────────────────────────────┘
    """

    def __init__(
        self,
        config: PoolConfig,
        terminal_manager: TerminalManager,
        session_buddy_client: Any = None,
    ):
        """Initialize MahavishnuPool.

        Args:
            config: Pool configuration
            terminal_manager: TerminalManager for terminal control
            session_buddy_client: Optional Session-Buddy MCP client
        """
        super().__init__(config)
        self.terminal_manager = terminal_manager
        self.session_buddy_client = session_buddy_client

        # Wrap existing WorkerManager
        self.worker_manager = WorkerManager(
            terminal_manager=terminal_manager,
            max_concurrent=config.max_workers,
            session_buddy_client=session_buddy_client,
        )

        # Track task statistics for metrics
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

    async def start(self) -> str:
        """Initialize pool and spawn initial workers.

        Returns:
            pool_id: Unique pool identifier
        """
        self._status = PoolStatus.INITIALIZING

        # Spawn minimum workers
        worker_ids = await self.worker_manager.spawn_workers(
            worker_type=self.config.worker_type,
            count=self.config.min_workers,
        )

        self._workers = {wid: f"worker_{wid}" for wid in worker_ids}
        self._status = PoolStatus.RUNNING

        logger.info(
            f"MahavishnuPool {self.pool_id} started with {len(worker_ids)} workers"
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

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
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
        worker_tasks = [
            (worker_ids[i % len(worker_ids)], task)
            for i, task in enumerate(tasks)
        ]

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
        task_results = {}
        for task_id, (_, result) in enumerate(zip(tasks, results.values())):
            task_results[task_id] = {
                "pool_id": self.pool_id,
                "worker_id": result.worker_id,
                "status": result.status.value,
                "output": result.output,
            }

        logger.info(
            f"MahavishnuPool {self.pool_id} executed {len(tasks)} tasks "
            f"in {total_duration:.2f}s"
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
                f"Scaling up MahavishnuPool {self.pool_id}: "
                f"{current_count} → {target_worker_count}"
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

    async def get_metrics(self) -> dict[str, Any]:
        """Get real-time pool metrics.

        Returns:
            PoolMetrics with current stats
        """
        from .base import PoolMetrics

        health = await self.health_check()

        # Calculate average task duration
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations)
            if self._task_durations
            else 0.0
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
        for worker_id, result in results.items():
            memory_items.append({
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
            })

        logger.info(
            f"Collected {len(memory_items)} memory items from pool {self.pool_id}"
        )

        return memory_items

    async def stop(self) -> None:
        """Shutdown pool and all workers."""
        logger.info(f"Stopping MahavishnuPool {self.pool_id}...")
        await self.worker_manager.close_all()
        self._status = PoolStatus.STOPPED
        logger.info(f"MahavishnuPool {self.pool_id} stopped")
