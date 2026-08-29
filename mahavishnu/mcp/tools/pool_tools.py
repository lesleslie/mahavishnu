"""Pool management MCP tools."""

from __future__ import annotations

import logging
from typing import Any

from mcp_common.fastmcp import FastMCP  # noqa: TC002

try:
    from mahavishnu.pools.memory_aggregator import MemoryAggregator
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
    MemoryAggregator = None

logger = logging.getLogger(__name__)


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
) -> None:
    """Register pool management tools.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP instance
        pool_manager: PoolManager instance

    This registers 7 pool management tools:
    - pool_list: List all active pools
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    """

    @mcp.tool()
    async def pool_list() -> list[dict[str, Any]]:
        """List all active pools."""
        try:
            return await pool_manager.list_pools()  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to list pools: {e}")
            return []

    @mcp.tool()
    async def pool_monitor(
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Monitor pool status and metrics."""
        try:
            return await pool_manager.aggregate_results(pool_ids)  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to monitor pools: {e}")
            return {}

    @mcp.tool()
    async def pool_scale(
        pool_id: str,
        target_workers: int,
    ) -> dict[str, Any]:
        """Scale pool to target worker count."""
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
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
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
        """Close a specific pool."""
        try:
            await pool_manager.close_pool(pool_id)

            return {
                "pool_id": pool_id,
                "status": "closed",
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to close pool: {e}")
            return {
                "pool_id": pool_id,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_close_all() -> dict[str, Any]:
        """Close all active pools."""
        try:
            pools = await pool_manager.list_pools()
            count = len(pools)

            await pool_manager.close_all()

            return {
                "pools_closed": count,
                "status": "all_closed",
            }
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to close pools: {e}")
            return {
                "pools_closed": 0,
                "status": "failed",
                "error": str(e),
            }

    @mcp.tool()
    async def pool_health() -> dict[str, Any]:
        """Get health status of all pools."""
        try:
            return await pool_manager.health_check()  # type: ignore[no-any-return]
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
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
        """Search memory across all pools."""
        try:
            aggregator_cls = MemoryAggregator
            if aggregator_cls is None:
                raise RuntimeError("MemoryAggregator is not available")

            aggregator = aggregator_cls()
            results = await aggregator.cross_pool_search(
                query=query,
                pool_manager=pool_manager,
                limit=limit,
            )

            return results
        except Exception as e:  # noqa: BLE001 - MCP boundary must preserve all operation failures
            logger.error(f"Failed to search memory: {e}")
            return []

    logger.info("Registered 7 pool management tools")
