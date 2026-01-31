"""MCP tools for worker orchestration."""

from typing import Any

from fastmcp import FastMCP

from ...workers.manager import WorkerManager
from ...workers.base import WorkerStatus


def register_worker_tools(
    mcp: FastMCP,
    worker_manager: WorkerManager,
) -> None:
    """Register worker orchestration tools with MCP server.

    Args:
        mcp: FastMCP server instance
        worker_manager: WorkerManager instance for backend operations
    """

    @mcp.tool()
    async def worker_spawn(
        worker_type: str = "terminal-qwen",
        count: int = 1,
    ) -> list[str]:
        """Spawn worker instances for task execution.

        Args:
            worker_type: Type of worker to spawn
                - "terminal-qwen": Headless Qwen CLI execution
                - "terminal-claude": Headless Claude Code CLI execution
                - "container-executor": Containerized task execution (Phase 3)
            count: Number of workers to spawn (1-50)

        Returns:
            List of worker IDs for spawned workers

        Example:
            >>> worker_ids = await worker_spawn("terminal-qwen", 3)
            >>> print(f"Spawned {len(worker_ids)} workers")

        Raises:
            ValueError: If worker_type is unknown or count is invalid
        """
        if count < 1 or count > 50:
            raise ValueError("count must be between 1 and 50")

        worker_ids = await worker_manager.spawn_workers(
            worker_type=worker_type,
            count=count,
        )

        return worker_ids

    @mcp.tool()
    async def worker_execute(
        worker_id: str,
        prompt: str,
        timeout: int = 300,
    ) -> dict:
        """Execute task on specific worker.

        Args:
            worker_id: Worker ID (from worker_spawn)
            prompt: Task prompt to send to AI worker
            timeout: Timeout in seconds (30-3600)

        Returns:
            Execution result with:
                - worker_id: Worker identifier
                - status: Execution status (completed, failed, timeout)
                - output: Worker output (truncated if large)
                - error: Error message if failed
                - duration: Execution time in seconds

        Example:
            >>> result = await worker_execute(
            ...     "term_abc123",
            ...     "Implement a REST API with FastAPI",
            ...     timeout=600
            ... )
            >>> print(f"Status: {result['status']}")

        Raises:
            ValueError: If worker_id not found
            TimeoutError: If task execution times out
        """
        if timeout < 30 or timeout > 3600:
            raise ValueError("timeout must be between 30 and 3600")

        task = {
            "prompt": prompt,
            "timeout": timeout,
        }

        result = await worker_manager.execute_task(worker_id, task)

        return {
            "worker_id": result.worker_id,
            "status": result.status.value,
            "output": result.output[:500] + "..." if result.output and len(result.output) > 500 else result.output,
            "error": result.error,
            "duration": result.duration_seconds,
            "has_output": result.has_output(),
        }

    @mcp.tool()
    async def worker_execute_batch(
        worker_ids: list[str],
        prompts: list[str],
        timeout: int = 300,
    ) -> dict:
        """Execute tasks on multiple workers concurrently.

        Args:
            worker_ids: List of worker IDs
            prompts: List of prompts (same length as worker_ids)
            timeout: Timeout in seconds for all tasks

        Returns:
            Dictionary mapping worker_id -> execution result

        Example:
            >>> results = await worker_execute_batch(
            ...     ["term_abc", "term_def"],
            ...     ["Task 1", "Task 2"],
            ...     timeout=600
            ... )
            >>> for wid, result in results.items():
            ...     print(f"{wid}: {result['status']}")

        Raises:
            ValueError: If worker_ids and prompts length mismatch
        """
        if len(worker_ids) != len(prompts):
            raise ValueError("worker_ids and prompts must have same length")

        tasks = [
            {"prompt": prompt, "timeout": timeout}
            for prompt in prompts
        ]

        results = await worker_manager.execute_batch(worker_ids, tasks)

        return {
            wid: {
                "status": result.status.value,
                "output": result.output[:200] + "..." if result.output and len(result.output) > 200 else result.output,
                "duration": result.duration_seconds,
            }
            for wid, result in results.items()
        }

    @mcp.tool()
    async def worker_list() -> list[dict]:
        """List all active workers.

        Returns:
            List of worker information dictionaries with:
                - worker_id: Worker identifier
                - worker_type: Type of worker
                - status: Current status (running, pending, completed, etc.)

        Example:
            >>> workers = await worker_list()
            >>> print(f"Active workers: {len(workers)}")
        """
        return await worker_manager.list_workers()

    @mcp.tool()
    async def worker_monitor(
        worker_ids: list[str] | None = None,
        interval: float = 1.0,
    ) -> dict:
        """Monitor worker status in real-time.

        Args:
            worker_ids: List of worker IDs (None = all workers)
            interval: Polling interval in seconds (0.1-10.0)

        Returns:
            Dictionary mapping worker_id -> status

        Example:
            >>> statuses = await worker_monitor(interval=0.5)
            >>> for wid, status in statuses.items():
            ...     print(f"{wid}: {status}")
        """
        if interval < 0.1 or interval > 10.0:
            raise ValueError("interval must be between 0.1 and 10.0")

        statuses = await worker_manager.monitor_workers(worker_ids, interval)

        return {wid: status.value for wid, status in statuses.items()}

    @mcp.tool()
    async def worker_collect_results(
        worker_ids: list[str] | None = None,
    ) -> dict:
        """Collect results from completed workers.

        Args:
            worker_ids: List of worker IDs (None = all workers)

        Returns:
            Dictionary mapping worker_id -> result with output and status

        Example:
            >>> results = await worker_collect_results(["term_abc", "term_def"])
            >>> for wid, result in results.items():
            ...     if result["status"] == "completed":
            ...         print(f"{wid}: {result['output'][:100]}...")
        """
        results = await worker_manager.collect_results(worker_ids)

        return {
            wid: {
                "status": result.status.value,
                "output": result.output,
                "error": result.error,
                "duration": result.duration_seconds,
                "has_output": result.has_output(),
            }
            for wid, result in results.items()
        }

    @mcp.tool()
    async def worker_close(worker_id: str) -> dict:
        """Close a specific worker.

        Args:
            worker_id: Worker ID to close

        Returns:
            Closure result with success status

        Example:
            >>> result = await worker_close("term_abc123")
            >>> print(f"Closed: {result['success']}")
        """
        try:
            await worker_manager.close_worker(worker_id)
            return {"success": True, "worker_id": worker_id}
        except Exception as e:
            return {
                "success": False,
                "worker_id": worker_id,
                "error": str(e),
            }

    @mcp.tool()
    async def worker_close_all() -> dict:
        """Close all active workers.

        Returns:
            Closure result with count of closed workers

        Example:
            >>> result = await worker_close_all()
            >>> print(f"Closed {result['closed_count']} workers")
        """
        workers_list = await worker_manager.list_workers()
        worker_ids = [w["worker_id"] for w in workers_list]

        for wid in worker_ids:
            await worker_manager.close_worker(wid)

        return {"closed_count": len(worker_ids)}

    @mcp.tool()
    async def worker_health() -> dict:
        """Get worker system health.

        Returns:
            Health status with:
                - status: Overall health (healthy, degraded, unhealthy)
                - workers_active: Number of active workers
                - max_concurrent: Maximum concurrent workers
                - details: Additional health details

        Example:
            >>> health = await worker_health()
            >>> print(f"Status: {health['status']}, Active: {health['workers_active']}")
        """
        return await worker_manager.health_check()
