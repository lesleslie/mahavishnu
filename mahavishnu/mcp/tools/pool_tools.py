"""Pool management MCP tools."""

import logging
from typing import Any

from fastmcp import FastMCP


logger = logging.getLogger(__name__)


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
) -> None:
    """Register pool management tools.

    Args:
        mcp: FastMCP instance
        pool_manager: PoolManager instance

    This registers 9 pool management tools:
    - pool_spawn: Create a new pool
    - pool_execute: Execute task on specific pool
    - pool_route_execute: Execute task with automatic routing
    - pool_list: List all active pools
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    """

    @mcp.tool()
    async def pool_spawn(
        pool_type: str = "mahavishnu",
        name: str = "default",
        min_workers: int = 1,
        max_workers: int = 10,
        worker_type: str = "terminal-qwen",
    ) -> dict[str, Any]:
        """Spawn a new worker pool.

        Args:
            pool_type: Type of pool ("mahavishnu", "session-buddy", "kubernetes")
            name: Pool name
            min_workers: Minimum worker count
            max_workers: Maximum worker count
            worker_type: Worker type ("terminal-qwen", "terminal-claude", "container")

        Returns:
            Pool creation result with pool_id

        Example:
            ```python
            result = await pool_spawn(
                pool_type="mahavishnu",
                name="local-pool",
                min_workers=2,
                max_workers=5
            )
            print(f"Pool ID: {result['pool_id']}")
            ```
        """
        from ..pools.base import PoolConfig

        config = PoolConfig(
            name=name,
            pool_type=pool_type,
            min_workers=min_workers,
            max_workers=max_workers,
            worker_type=worker_type,
        )

        try:
            pool_id = await pool_manager.spawn_pool(pool_type, config)

            return {
                "pool_id": pool_id,
                "pool_type": pool_type,
                "name": name,
                "status": "created",
                "min_workers": min_workers,
                "max_workers": max_workers,
            }
        except Exception as e:
            logger.error(f"Failed to spawn pool: {e}")
            return {
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_execute(
        pool_id: str,
        prompt: str,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Execute task on specific pool.

        Args:
            pool_id: Target pool ID
            prompt: Task prompt
            timeout: Execution timeout in seconds

        Returns:
            Execution result

        Example:
            ```python
            result = await pool_execute(
                pool_id="pool_abc",
                prompt="Write a Python function",
                timeout=300
            )
            print(f"Output: {result['output']}")
            ```
        """
        task = {
            "prompt": prompt,
            "timeout": timeout,
        }

        try:
            result = await pool_manager.execute_on_pool(pool_id, task)
            return result
        except Exception as e:
            logger.error(f"Failed to execute task: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_route_execute(
        prompt: str,
        pool_selector: str = "least_loaded",
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Execute task with automatic pool routing.

        Args:
            prompt: Task prompt
            pool_selector: Selection strategy ("round_robin", "least_loaded", "random")
            timeout: Execution timeout in seconds

        Returns:
            Execution result with pool_id

        Example:
            ```python
            result = await pool_route_execute(
                prompt="Write a Python function",
                pool_selector="least_loaded",
                timeout=300
            )
            print(f"Executed on pool: {result['pool_id']}")
            ```
        """
        from ..pools.manager import PoolSelector

        task = {
            "prompt": prompt,
            "timeout": timeout,
        }

        try:
            selector = PoolSelector(pool_selector)
            result = await pool_manager.route_task(task, selector)
            return result
        except Exception as e:
            logger.error(f"Failed to route task: {e}")
            return {
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_list() -> list[dict[str, Any]]:
        """List all active pools.

        Returns:
            List of pool information dictionaries

        Example:
            ```python
            pools = await pool_list()
            for pool in pools:
                print(f"{pool['pool_id']}: {pool['pool_type']} - {pool['status']}")
            ```
        """
        try:
            return await pool_manager.list_pools()
        except Exception as e:
            logger.error(f"Failed to list pools: {e}")
            return []

    @mcp.tool()
    async def pool_monitor(
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Monitor pool status and metrics.

        Args:
            pool_ids: List of pool IDs (None = all pools)

        Returns:
            Dictionary mapping pool_id -> metrics

        Example:
            ```python
            # Monitor all pools
            metrics = await pool_monitor()

            # Monitor specific pools
            metrics = await pool_monitor(pool_ids=["pool_abc", "pool_def"])

            for pool_id, pool_metrics in metrics.items():
                print(f"{pool_id}: {pool_metrics['status']}")
            ```
        """
        try:
            return await pool_manager.aggregate_results(pool_ids)
        except Exception as e:
            logger.error(f"Failed to monitor pools: {e}")
            return {}

    @mcp.tool()
    async def pool_scale(
        pool_id: str,
        target_workers: int,
    ) -> dict[str, Any]:
        """Scale pool to target worker count.

        Args:
            pool_id: Pool ID to scale
            target_workers: Target worker count

        Returns:
            Scale result

        Example:
            ```python
            result = await pool_scale(
                pool_id="pool_abc",
                target_workers=10
            )
            print(f"Scaled to {result['target_workers']} workers")
            ```
        """
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
        except Exception as e:
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
        """Close a specific pool.

        Args:
            pool_id: Pool ID to close

        Returns:
            Close result

        Example:
            ```python
            result = await pool_close(pool_id="pool_abc")
            print(f"Pool {result['pool_id']} closed")
            ```
        """
        try:
            await pool_manager.close_pool(pool_id)

            return {
                "pool_id": pool_id,
                "status": "closed",
            }
        except Exception as e:
            logger.error(f"Failed to close pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_close_all() -> dict[str, Any]:
        """Close all active pools.

        Returns:
            Close result with count

        Example:
            ```python
            result = await pool_close_all()
            print(f"Closed {result['pools_closed']} pools")
            ```
        """
        try:
            pools = await pool_manager.list_pools()
            count = len(pools)

            await pool_manager.close_all()

            return {
                "pools_closed": count,
                "status": "all_closed",
            }
        except Exception as e:
            logger.error(f"Failed to close pools: {e}")
            return {
                "pools_closed": 0,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_health() -> dict[str, Any]:
        """Get health status of all pools.

        Returns:
            Health status dictionary

        Example:
            ```python
            health = await pool_health()
            print(f"Overall status: {health['status']}")
            print(f"Active pools: {health['pools_active']}")
            ```
        """
        try:
            return await pool_manager.health_check()
        except Exception as e:
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
        """Search memory across all pools.

        Args:
            query: Search query
            limit: Result limit

        Returns:
            Unified search results

        Example:
            ```python
            results = await pool_search_memory(
                query="API implementation",
                limit=50
            )

            for result in results:
                print(f"{result['content'][:100]}...")
            ```
        """
        try:
            from ..pools.memory_aggregator import MemoryAggregator

            aggregator = MemoryAggregator()
            results = await aggregator.cross_pool_search(
                query=query,
                pool_manager=pool_manager,
                limit=limit,
            )

            return results
        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []

    logger.info("Registered 10 pool management tools")
