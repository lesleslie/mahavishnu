"""Pool management MCP tools."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from mcp_common.fastmcp import FastMCP  # noqa: TC002

from mahavishnu.core.budget import BudgetRecord, BudgetSpec, BudgetStateMachine

try:
    from mahavishnu.pools.memory_aggregator import MemoryAggregator
except Exception:  # pragma: no cover - optional import for test patching  # noqa: BLE001 - MCP boundary must preserve all operation failures  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
    MemoryAggregator = None

logger = logging.getLogger(__name__)


def register_pool_tools(
    mcp: FastMCP,
    pool_manager,
    *,
    budget_store: Any | None = None,
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
        budget_store: Optional :class:`mahavishnu.core.budget_watchdog.BudgetStore`
            used by ``budget_enforce``. When ``None`` (the default, used
            in tests that don't exercise budgets) ``budget_enforce``
            returns ``{"status": "unconfigured"}`` rather than raising.

    This registers 8 pool management tools:
    - pool_list: List all active pools
    - pool_monitor: Monitor pool metrics
    - pool_scale: Scale pool worker count
    - pool_close: Close a specific pool
    - pool_close_all: Close all pools
    - pool_health: Get health status
    - pool_search_memory: Search memory across pools
    - budget_enforce: Declare a per-workflow budget (Phase 3 v2 plan)
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

    @mcp.tool()
    async def budget_enforce(
        workflow_id: str,
        budget_tokens: int | None = None,
        budget_turns: int | None = None,
        budget_wallclock_seconds: float | None = None,
        declared_by: str | None = None,
    ) -> dict[str, Any]:
        """Declare a per-workflow budget; the watchdog enforces it.

        ``workflow_id`` must be unique per call. Re-calling with the
        same ``workflow_id`` re-bases the cap (intentional "pause at
        N" semantics on a running run). The MCP boundary swallows
        Dhara failures as ``status: "failed"`` rather than raising —
        the watchdog polls against whatever state was last persisted,
        so a partial write here is acceptable.
        """
        if budget_store is None:
            return {
                "workflow_id": workflow_id,
                "status": "unconfigured",
                "error": "budget_store is not configured on this server",
            }
        spec = BudgetSpec(
            budget_tokens=budget_tokens,
            budget_turns=budget_turns,
            budget_wallclock_seconds=budget_wallclock_seconds,
            declared_by=declared_by,
        )
        try:
            existing_raw = await budget_store.get(f"mahavishni://budgets/{workflow_id}.json")
        except Exception as exc:  # noqa: BLE001 - MCP boundary must persist all failures
            logger.warning("budget_enforce: read failed for %s: %s", workflow_id, exc)
            existing_raw = None
        sm = BudgetStateMachine(
            BudgetRecord.from_dict(existing_raw)
            if isinstance(existing_raw, dict) and existing_raw.get("workflow_id")
            else BudgetRecord(workflow_id=workflow_id)
        )
        sm.declare(spec)
        try:
            sm.start(when=datetime.now(UTC))
        except ValueError as exc:
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": str(exc),
            }
        try:
            await budget_store.put(
                f"mahavishni://budgets/{workflow_id}.json",
                sm.record.to_dict(),
            )
        except Exception as exc:  # noqa: BLE001 - MCP boundary must persist all failures
            logger.warning("budget_enforce: persist failed for %s: %s", workflow_id, exc)
            return {
                "workflow_id": workflow_id,
                "status": "failed",
                "error": f"failed to persist budget: {exc}",
            }
        return {
            "workflow_id": workflow_id,
            "status": "active",
            "spec": spec.to_dict(),
            "state": sm.record.state.value,
            "started_at": (
                sm.record.started_at.isoformat() if sm.record.started_at is not None else None
            ),
        }

    logger.info("Registered 8 pool management tools")
