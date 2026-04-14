"""MCP tools for worker orchestration."""

from fastmcp import FastMCP

from ...workers.manager import WorkerManager


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
        """Spawn worker instances for task execution."""
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
        """Execute task on specific worker."""
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
            "output": result.output[:500] + "..."
            if result.output and len(result.output) > 500
            else result.output,
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
        """Execute tasks on multiple workers concurrently."""
        if len(worker_ids) != len(prompts):
            raise ValueError("worker_ids and prompts must have same length")

        tasks = [{"prompt": prompt, "timeout": timeout} for prompt in prompts]

        results = await worker_manager.execute_batch(worker_ids, tasks)

        return {
            wid: {
                "status": result.status.value,
                "output": result.output[:200] + "..."
                if result.output and len(result.output) > 200
                else result.output,
                "duration": result.duration_seconds,
            }
            for wid, result in results.items()
        }

    @mcp.tool()
    async def worker_list() -> list[dict]:
        """List all active workers."""
        return await worker_manager.list_workers()

    @mcp.tool()
    async def worker_monitor(
        worker_ids: list[str] | None = None,
        interval: float = 1.0,
    ) -> dict:
        """Monitor worker status in real-time."""
        if interval < 0.1 or interval > 10.0:
            raise ValueError("interval must be between 0.1 and 10.0")

        statuses = await worker_manager.monitor_workers(worker_ids, interval)

        return {wid: status.value for wid, status in statuses.items()}

    @mcp.tool()
    async def worker_collect_results(
        worker_ids: list[str] | None = None,
    ) -> dict:
        """Collect results from completed workers."""
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
        """Close a specific worker."""
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
        """Close all active workers."""
        workers_list = await worker_manager.list_workers()
        worker_ids = [w["worker_id"] for w in workers_list]

        for wid in worker_ids:
            await worker_manager.close_worker(wid)

        return {"closed_count": len(worker_ids)}

    @mcp.tool()
    async def worker_health() -> dict:
        """Get worker system health."""
        return await worker_manager.health_check()
