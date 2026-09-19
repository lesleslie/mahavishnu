"""Session-Buddy delegated pool management.

Each Session-Buddy instance manages 3 workers directly.

Phase 3 (REQ-004): rewired to ``mcp_common.clients.common_mcp_client.CommonMCPClient``.
The ``httpx2.AsyncClient`` POST path is replaced with ``CommonMCPClient.call_tool``
so all Bodai clients share the same streamable-HTTP transport.
"""

import logging
import time
from typing import Any

from mcp_common.clients.common_mcp_client import CommonMCPClient
from mcp_common.exceptions import MCPServerError

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)


async def _await_if_needed(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return as-is.

    Kept for API compatibility with the test suite (see
    ``tests/unit/test_session_buddy_pool.py::TestAwaitIfNeeded`` and
    ``tests/unit/test_pool_manager.py::TestAwaitIfNeededHelper``).
    """
    if hasattr(value, "__await__"):
        return await value
    return value


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
    │  • CommonMCPClient                 │
    │  • worker_spawn (3 workers)        │
    │  • worker_execute                  │
    │  • worker_monitor                  │
    └─────────────────────────────────────┘
            │ HTTP (MCP streamable)
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
        self._mcp = CommonMCPClient(base_url=session_buddy_url, timeout=300.0)

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
            MCPServerError: If MCP call fails
        """
        result = await self._mcp.call_tool(tool_name, arguments)
        if isinstance(result, dict):
            return result
        # Non-dict results are unusual for Session-Buddy tool responses;
        # wrap so callers that read ``.get("result", ...)`` keep working.
        return {"result": result}

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

        except MCPServerError as e:
            logger.error(f"Failed to start SessionBuddyPool: {e}")
            self._status = PoolStatus.FAILED
            raise

        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task via Session-Buddy worker_execute.

        Args:
            task: Task specification with pool-specific parameters. When
                ``task["working_dir"]`` is set, the pool also marks
                ``<working_dir>/.session-buddy/subagent.lock`` before
                dispatch and clears it after — wraps the new
                ``subagent_marker`` MCP tool from session-buddy so the
                checkpoint subsystem's consumer side
                (``SubagentDetector.is_active``) sees the producer
                half of the lockfile contract.

        Returns:
            Execution result
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_id = next(iter(self._workers.keys()))
        working_dir = task.get("working_dir")

        if working_dir:
            await self._call_mcp_tool(
                "subagent_marker",
                {"working_dir": working_dir, "action": "mark"},
            )

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

        except MCPServerError as e:
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
        finally:
            if working_dir:
                try:
                    await self._call_mcp_tool(
                        "subagent_marker",
                        {"working_dir": working_dir, "action": "clear"},
                    )
                except Exception:
                    # Best-effort cleanup: a stale marker would cause
                    # the consumer to fail-open → True indefinitely
                    # and defer every subsequent checkpoint. Log and
                    # move on; the marker will be overwritten by the
                    # next mark.
                    logger.exception(
                        "subagent_marker clear failed for %s; consumer "
                        "may see a stale lockfile until the next mark",
                        working_dir,
                    )

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute tasks via Session-Buddy worker_execute_batch.

        Args:
            tasks: List of task specifications. Each task MAY carry a
                ``working_dir``; tasks with one are wrapped with
                ``subagent_marker`` mark/clear so the checkpoint
                subsystem's consumer side sees the producer half of
                the lockfile contract for that working tree. Tasks
                without ``working_dir`` get no marker (preserves
                existing behavior).

        Returns:
            Dictionary mapping task_id -> result
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        # Collect the working_dirs to mark; preserve order while
        # de-duplicating so a batch with the same working_dir across
        # tasks marks once and clears once.
        working_dirs: list[str] = []
        seen: set[str] = set()
        for task in tasks:
            wd = task.get("working_dir")
            if wd and wd not in seen:
                seen.add(wd)
                working_dirs.append(wd)

        for wd in working_dirs:
            await self._call_mcp_tool(
                "subagent_marker",
                {"working_dir": wd, "action": "mark"},
            )

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

        except MCPServerError as e:
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
        finally:
            for wd in working_dirs:
                try:
                    await self._call_mcp_tool(
                        "subagent_marker",
                        {"working_dir": wd, "action": "clear"},
                    )
                except Exception:
                    logger.exception(
                        "subagent_marker clear failed for %s; consumer "
                        "may see a stale lockfile until the next mark",
                        wd,
                    )

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

        except MCPServerError as e:
            logger.error(f"Failed health check for SessionBuddyPool: {e}")
            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": "unhealthy",
                "workers_active": len(self._workers),
                "error": str(e),
            }

    async def get_metrics(self) -> PoolMetrics:
        """Get metrics from Session-Buddy.

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

            return conversations  # type: ignore[no-any-return]

        except MCPServerError as e:
            logger.error(f"Failed to collect memory from SessionBuddyPool: {e}")
            return []

    async def stop(self) -> None:
        """Shutdown Session-Buddy workers."""
        logger.info(f"Stopping SessionBuddyPool {self.pool_id}...")

        try:
            await self._call_mcp_tool("worker_close_all", {})

        except MCPServerError as e:
            logger.warning(f"Failed to properly close SessionBuddyPool workers: {e}")

        finally:
            await self._mcp.aclose()
            self._status = PoolStatus.STOPPED
            logger.info(f"SessionBuddyPool {self.pool_id} stopped")


# Registry integration: SessionBuddyPool reads session_buddy_url from config.get()
# (matching the original manager dispatch). It does not need terminal_manager or
# session_buddy_client kwargs — they are ignored if forwarded.
def _build_session_buddy_pool(
    config: PoolConfig,
    **_unused_kwargs: Any,
) -> SessionBuddyPool:
    return SessionBuddyPool(
        config=config,
        session_buddy_url=config.get("session_buddy_url", "http://localhost:8678/mcp"),
    )


from ._registry import register_pool_type

register_pool_type("session-buddy", _build_session_buddy_pool)
