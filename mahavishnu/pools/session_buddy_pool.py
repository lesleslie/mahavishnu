"""Session-Buddy delegated pool management.

Each Session-Buddy instance manages 3 workers directly.
"""

import logging
import time
from typing import Any

import httpx

from .base import BasePool, PoolConfig, PoolStatus

logger = logging.getLogger(__name__)


class SessionBuddyPool(BasePool):
    """Delegates worker management to Session-Buddy instance.

    Session-Buddy manages 3 workers directly.
    Mahavishnu communicates via MCP protocol.

    Use Cases:
    - Distributed worker management
    - Remote worker execution
    - Session-Buddy memory integration
    - Multi-server deployments

    Architecture:
    ┌─────────────────────────────────────┐
    │      SessionBuddyPool              │
    │  • HTTP MCP client                 │
    │  • worker_spawn (3 workers)        │
    │  • worker_execute                  │
    │  • worker_monitor                  │
    └─────────────────────────────────────┘
            │ HTTP (MCP)
            ↓
    ┌───────────────────────┐
    │  Session-Buddy MCP    │
    │  (Port 8678)          │
    ├───────────────────────┤
    │  WorkerManager        │
    │  • 3 workers          │
    │  • Memory storage     │
    └───────────────────────┘
    """

    def __init__(
        self,
        config: PoolConfig,
        session_buddy_url: str = "http://localhost:8678/mcp",
        max_workers: int = 3,  # Session-Buddy manages 3 workers
    ):
        """Initialize SessionBuddyPool.

        Args:
            config: Pool configuration
            session_buddy_url: Session-Buddy MCP server URL
            max_workers: Fixed worker count (Session-Buddy manages 3)
        """
        super().__init__(config)
        self.session_buddy_url = session_buddy_url
        self.max_workers = max_workers
        self._mcp_client = httpx.AsyncClient(timeout=300.0)

        # Track task statistics
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

    async def _call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call Session-Buddy MCP tool.

        Args:
            tool_name: Name of the MCP tool
            arguments: Tool arguments

        Returns:
            Tool result dictionary

        Raises:
            httpx.HTTPError: If MCP call fails
        """
        response = await self._mcp_client.post(
            f"{self.session_buddy_url}/tools/call",
            json={
                "name": tool_name,
                "arguments": arguments,
            },
        )
        response.raise_for_status()
        return response.json()

    async def start(self) -> str:
        """Initialize Session-Buddy pool via MCP.

        Returns:
            pool_id: Unique pool identifier
        """
        self._status = PoolStatus.INITIALIZING

        try:
            # Call Session-Buddy worker_spawn tool
            result = await self._call_mcp_tool(
                "worker_spawn",
                {
                    "worker_type": self.config.worker_type,
                    "count": self.max_workers,
                },
            )

            worker_ids = result.get("result", [])
            if not isinstance(worker_ids, list):
                worker_ids = []

            self._workers = {wid: f"worker_{wid}" for wid in worker_ids}
            self._status = PoolStatus.RUNNING

            logger.info(
                f"SessionBuddyPool {self.pool_id} started with {len(worker_ids)} workers "
                f"(via {self.session_buddy_url})"
            )

        except httpx.HTTPError as e:
            logger.error(f"Failed to start SessionBuddyPool: {e}")
            self._status = PoolStatus.FAILED
            raise

        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task via Session-Buddy worker_execute.

        Args:
            task: Task specification with pool-specific parameters

        Returns:
            Execution result
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_id = next(iter(self._workers.keys()))

        start_time = time.time()
        try:
            result = await self._call_mcp_tool(
                "worker_execute",
                {
                    "worker_id": worker_id,
                    "prompt": task.get("prompt", ""),
                    "timeout": task.get("timeout", 300),
                },
            )

            duration = time.time() - start_time
            tool_result = result.get("result", {})

            # Track statistics
            status_value = tool_result.get("status", "unknown")
            if status_value == "completed":
                self._tasks_completed += 1
            else:
                self._tasks_failed += 1
            self._task_durations.append(duration)

            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": status_value,
                "output": tool_result.get("output"),
                "error": tool_result.get("error"),
                "duration": duration,
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed to execute task on SessionBuddyPool: {e}")
            self._tasks_failed += 1
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": str(e),
                "duration": time.time() - start_time,
            }

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute tasks via Session-Buddy worker_execute_batch.

        Args:
            tasks: List of task specifications

        Returns:
            Dictionary mapping task_id -> result
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        start_time = time.time()
        try:
            result = await self._call_mcp_tool(
                "worker_execute_batch",
                {
                    "worker_ids": list(self._workers.keys()),
                    "tasks": tasks,
                },
            )

            duration = time.time() - start_time
            batch_results = result.get("result", {})

            # Track statistics
            for task_result in batch_results.values():
                status_value = task_result.get("status", "unknown")
                if status_value == "completed":
                    self._tasks_completed += 1
                else:
                    self._tasks_failed += 1
                self._task_durations.append(duration / len(tasks))

            # Add pool_id to each result
            task_results = {}
            for task_id, task_result in batch_results.items():
                task_results[task_id] = {
                    "pool_id": self.pool_id,
                    **task_result,
                }

            logger.info(
                f"SessionBuddyPool {self.pool_id} executed {len(tasks)} tasks in {duration:.2f}s"
            )

            return task_results

        except httpx.HTTPError as e:
            logger.error(f"Failed to execute batch on SessionBuddyPool: {e}")
            self._tasks_failed += len(tasks)
            return {
                str(i): {
                    "pool_id": self.pool_id,
                    "status": "failed",
                    "error": str(e),
                }
                for i in range(len(tasks))
            }

    async def scale(self, target_worker_count: int) -> None:
        """Scale not supported (fixed at 3 workers).

        Args:
            target_worker_count: Desired worker count

        Raises:
            NotImplementedError: Always - SessionBuddyPool has fixed worker count
        """
        raise NotImplementedError(
            "SessionBuddyPool has fixed worker count (3). Spawn additional pools for more capacity."
        )

    async def health_check(self) -> dict[str, Any]:
        """Check pool health via Session-Buddy.

        Returns:
            Health status dictionary
        """
        try:
            result = await self._call_mcp_tool("worker_health", {})
            health_result = result.get("result", {})

            pool_status = "healthy"
            if len(self._workers) < self.config.min_workers:
                pool_status = "degraded"
            elif len(self._workers) == 0:
                pool_status = "unhealthy"

            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": pool_status,
                "workers_active": len(self._workers),
                "max_workers": self.max_workers,
                "worker_health": health_result,
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
                "session_buddy_url": self.session_buddy_url,
            }

        except httpx.HTTPError as e:
            logger.error(f"Failed health check for SessionBuddyPool: {e}")
            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": "unhealthy",
                "workers_active": len(self._workers),
                "error": str(e),
            }

    async def get_metrics(self) -> dict[str, Any]:
        """Get metrics from Session-Buddy.

        Returns:
            PoolMetrics with current stats
        """
        from .base import PoolMetrics

        health = await self.health_check()

        # Calculate average task duration
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )

        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=len(self._workers),
            total_workers=self.max_workers,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Collect memory from Session-Buddy.

        Returns:
            List of memory dictionaries
        """
        try:
            # Query Session-Buddy for recent worker executions
            result = await self._call_mcp_tool(
                "search_conversations",
                {
                    "query": f"pool_id:{self.pool_id}",
                    "limit": 100,
                },
            )

            conversations = result.get("result", {}).get("conversations", [])

            logger.info(
                f"Collected {len(conversations)} memory items from SessionBuddyPool {self.pool_id}"
            )

            return conversations

        except httpx.HTTPError as e:
            logger.error(f"Failed to collect memory from SessionBuddyPool: {e}")
            return []

    async def stop(self) -> None:
        """Shutdown Session-Buddy workers."""
        logger.info(f"Stopping SessionBuddyPool {self.pool_id}...")

        try:
            await self._call_mcp_tool("worker_close_all", {})

        except httpx.HTTPError as e:
            logger.warning(f"Failed to properly close SessionBuddyPool workers: {e}")

        finally:
            await self._mcp_client.aclose()
            self._status = PoolStatus.STOPPED
            logger.info(f"SessionBuddyPool {self.pool_id} stopped")
