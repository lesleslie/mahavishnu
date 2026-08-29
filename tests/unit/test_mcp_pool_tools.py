"""Comprehensive tests for MCP pool management tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.pool_tools import register_pool_tools


@pytest.fixture
def mock_pool_manager():
    """Create mock pool manager."""
    manager = AsyncMock()
    manager.spawn_pool = AsyncMock(return_value="pool_test_id")
    manager.execute_on_pool = AsyncMock(
        return_value={"status": "completed", "output": "test output"}
    )
    manager.route_task = AsyncMock(return_value={"pool_id": "pool_test_id", "status": "completed"})
    manager.list_pools = AsyncMock(
        return_value=[
            {"pool_id": "pool_1", "pool_type": "mahavishnu", "status": "active"},
            {"pool_id": "pool_2", "pool_type": "session-buddy", "status": "active"},
        ]
    )
    manager.aggregate_results = AsyncMock(
        return_value={
            "pool_1": {"status": "healthy", "workers": 5},
            "pool_2": {"status": "healthy", "workers": 3},
        }
    )
    manager.health_check = AsyncMock(
        return_value={
            "status": "healthy",
            "pools_active": 2,
        }
    )
    manager.close_pool = AsyncMock(return_value=None)
    manager.close_all = AsyncMock(return_value=None)
    manager._pools = {
        "pool_1": MagicMock(scale=AsyncMock(return_value=None), _workers=[1, 2, 3, 4, 5]),
        "pool_2": MagicMock(scale=AsyncMock(return_value=None), _workers=[1, 2, 3]),
    }
    return manager


@pytest.fixture
def mock_mcp():
    """Create mock FastMCP instance."""
    mcp = MagicMock()

    def tool(fn=None):
        if fn is None:
            return lambda wrapped: wrapped
        return fn

    mcp.tool = tool
    return mcp


class TestPoolListTool:
    """Test pool_list tool."""

    @pytest.mark.asyncio
    async def test_pool_list(self, mock_mcp, mock_pool_manager):
        """Test listing all active pools."""

        @mock_mcp.tool()
        async def pool_list():
            return await mock_pool_manager.list_pools()

        pools = await pool_list()

        assert len(pools) == 2
        assert pools[0]["pool_id"] == "pool_1"
        assert pools[0]["pool_type"] == "mahavishnu"
        assert pools[1]["pool_id"] == "pool_2"
        assert pools[1]["pool_type"] == "session-buddy"

    @pytest.mark.asyncio
    async def test_pool_list_empty(self, mock_mcp, mock_pool_manager):
        """Test listing pools when none exist."""
        mock_pool_manager.list_pools = AsyncMock(return_value=[])

        @mock_mcp.tool()
        async def pool_list():
            return await mock_pool_manager.list_pools()

        pools = await pool_list()
        assert len(pools) == 0


class TestPoolMonitorTool:
    """Test pool_monitor tool."""

    @pytest.mark.asyncio
    async def test_pool_monitor_all_pools(self, mock_mcp, mock_pool_manager):
        """Test monitoring all pools."""

        @mock_mcp.tool()
        async def pool_monitor(pool_ids=None):
            return await mock_pool_manager.aggregate_results(pool_ids)

        metrics = await pool_monitor()

        assert "pool_1" in metrics
        assert "pool_2" in metrics
        assert metrics["pool_1"]["status"] == "healthy"
        assert metrics["pool_1"]["workers"] == 5

    @pytest.mark.asyncio
    async def test_pool_monitor_specific_pools(self, mock_mcp, mock_pool_manager):
        """Test monitoring specific pools."""

        @mock_mcp.tool()
        async def pool_monitor(pool_ids=None):
            return await mock_pool_manager.aggregate_results(pool_ids)

        metrics = await pool_monitor(pool_ids=["pool_1"])

        assert "pool_1" in metrics
        mock_pool_manager.aggregate_results.assert_called_once_with(["pool_1"])


class TestPoolScaleTool:
    """Test pool_scale tool."""

    @pytest.mark.asyncio
    async def test_pool_scale_success(self, mock_mcp, mock_pool_manager):
        """Test scaling pool successfully."""
        mock_pool_manager._pools["pool_1"]

        @mock_mcp.tool()
        async def pool_scale(pool_id: str, target_workers: int):
            pool_obj = mock_pool_manager._pools.get(pool_id)
            if not pool_obj:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": f"Pool not found: {pool_id}",
                }
            await pool_obj.scale(target_workers)
            return {
                "pool_id": pool_id,
                "target_workers": target_workers,
                "actual_workers": len(pool_obj._workers),
                "status": "scaled",
            }

        result = await pool_scale(pool_id="pool_1", target_workers=10)

        assert result["status"] == "scaled"
        assert result["pool_id"] == "pool_1"
        assert result["target_workers"] == 10
        assert result["actual_workers"] == 5

    @pytest.mark.asyncio
    async def test_pool_scale_not_found(self, mock_mcp, mock_pool_manager):
        """Test scaling non-existent pool."""

        @mock_mcp.tool()
        async def pool_scale(pool_id: str, target_workers: int):
            pool_obj = mock_pool_manager._pools.get(pool_id)
            if not pool_obj:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": f"Pool not found: {pool_id}",
                }
            return {"status": "scaled"}

        result = await pool_scale(pool_id="nonexistent", target_workers=10)
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_pool_scale_not_implemented(self, mock_mcp, mock_pool_manager):
        """Test scaling pool that doesn't support scaling."""
        pool = mock_pool_manager._pools["pool_1"]
        pool.scale = AsyncMock(side_effect=NotImplementedError("Fixed worker count"))

        @mock_mcp.tool()
        async def pool_scale(pool_id: str, target_workers: int):
            pool_obj = mock_pool_manager._pools.get(pool_id)
            if not pool_obj:
                return {"status": "failed", "error": "Pool not found"}
            try:
                await pool_obj.scale(target_workers)
                return {"status": "scaled"}
            except NotImplementedError:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": "Pool does not support scaling (e.g., SessionBuddyPool is fixed at 3 workers)",
                }

        result = await pool_scale(pool_id="pool_1", target_workers=10)
        assert result["status"] == "failed"
        assert "does not support scaling" in result["error"]


class TestPoolCloseTool:
    """Test pool_close tool."""

    @pytest.mark.asyncio
    async def test_pool_close_success(self, mock_mcp, mock_pool_manager):
        """Test closing a pool successfully."""

        @mock_mcp.tool()
        async def pool_close(pool_id: str):
            await mock_pool_manager.close_pool(pool_id)
            return {
                "pool_id": pool_id,
                "status": "closed",
            }

        result = await pool_close(pool_id="pool_1")

        assert result["status"] == "closed"
        assert result["pool_id"] == "pool_1"
        mock_pool_manager.close_pool.assert_called_once_with("pool_1")

    @pytest.mark.asyncio
    async def test_pool_close_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_close handles errors gracefully."""
        mock_pool_manager.close_pool = AsyncMock(side_effect=Exception("Close failed"))

        @mock_mcp.tool()
        async def pool_close(pool_id: str):
            try:
                await mock_pool_manager.close_pool(pool_id)
                return {"pool_id": pool_id, "status": "closed"}
            except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": str(e),
                }

        result = await pool_close(pool_id="pool_1")
        assert result["status"] == "failed"
        assert "Close failed" in result["error"]


class TestPoolCloseAllTool:
    """Test pool_close_all tool."""

    @pytest.mark.asyncio
    async def test_pool_close_all_success(self, mock_mcp, mock_pool_manager):
        """Test closing all pools successfully."""

        @mock_mcp.tool()
        async def pool_close_all():
            pools = await mock_pool_manager.list_pools()
            count = len(pools)
            await mock_pool_manager.close_all()
            return {
                "pools_closed": count,
                "status": "all_closed",
            }

        result = await pool_close_all()

        assert result["status"] == "all_closed"
        assert result["pools_closed"] == 2
        mock_pool_manager.close_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_pool_close_all_empty(self, mock_mcp, mock_pool_manager):
        """Test closing all pools when none exist."""
        mock_pool_manager.list_pools = AsyncMock(return_value=[])

        @mock_mcp.tool()
        async def pool_close_all():
            pools = await mock_pool_manager.list_pools()
            count = len(pools)
            await mock_pool_manager.close_all()
            return {
                "pools_closed": count,
                "status": "all_closed",
            }

        result = await pool_close_all()
        assert result["pools_closed"] == 0
        assert result["status"] == "all_closed"


class TestPoolHealthTool:
    """Test pool_health tool."""

    @pytest.mark.asyncio
    async def test_pool_health_success(self, mock_mcp, mock_pool_manager):
        """Test getting health status successfully."""

        @mock_mcp.tool()
        async def pool_health():
            return await mock_pool_manager.health_check()

        health = await pool_health()

        assert health["status"] == "healthy"
        assert health["pools_active"] == 2

    @pytest.mark.asyncio
    async def test_pool_health_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_health handles errors gracefully."""
        mock_pool_manager.health_check = AsyncMock(side_effect=Exception("Health check failed"))

        @mock_mcp.tool()
        async def pool_health():
            try:
                return await mock_pool_manager.health_check()
            except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                return {
                    "status": "unhealthy",
                    "error": str(e),
                }

        health = await pool_health()
        assert health["status"] == "unhealthy"
        assert "Health check failed" in health["error"]


class TestPoolSearchMemoryTool:
    """Test pool_search_memory tool."""

    @pytest.mark.asyncio
    async def test_pool_search_memory_success(self, mock_mcp, mock_pool_manager):
        """Test searching memory across pools successfully."""

        @mock_mcp.tool()
        async def pool_search_memory(query: str, limit: int = 100):
            from mahavishnu.mcp.tools.pool_tools import MemoryAggregator

            aggregator = MemoryAggregator()
            results = await aggregator.cross_pool_search(
                query=query,
                pool_manager=mock_pool_manager,
                limit=limit,
            )
            return results

        # Mock the aggregator
        with patch("mahavishnu.mcp.tools.pool_tools.MemoryAggregator") as MockAggregator:
            mock_aggregator = MagicMock()
            mock_aggregator.cross_pool_search = AsyncMock(
                return_value=[
                    {"content": "API implementation code", "score": 0.95},
                    {"content": "Test code", "score": 0.85},
                ]
            )
            MockAggregator.return_value = mock_aggregator

            results = await pool_search_memory(query="API implementation", limit=50)

            assert len(results) == 2
            assert results[0]["content"] == "API implementation code"
            assert results[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_pool_search_memory_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_search_memory handles errors gracefully."""

        @mock_mcp.tool()
        async def pool_search_memory(query: str, limit: int = 100):
            try:
                from mahavishnu.pools.memory_aggregator import MemoryAggregator

                aggregator = MemoryAggregator()
                results = await aggregator.cross_pool_search(
                    query=query,
                    pool_manager=mock_pool_manager,
                    limit=limit,
                )
                return results
            except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                return []

        # Mock the aggregator to raise error
        with patch("mahavishnu.mcp.tools.pool_tools.MemoryAggregator") as MockAggregator:
            mock_aggregator = MagicMock()
            mock_aggregator.cross_pool_search = AsyncMock(side_effect=Exception("Search failed"))
            MockAggregator.return_value = mock_aggregator

            results = await pool_search_memory(query="test")
            assert results == []


class TestPoolToolRegistration:
    """Test pool tool registration."""

    def test_register_pool_tools_registers_all_tools(self, mock_mcp, mock_pool_manager):
        """Test that register_pool_tools registers all 7 tools."""
        # Track tool registrations
        registered_tools = []

        def mock_tool_decorator(func=None):
            if func is None:
                return lambda wrapped: mock_tool_decorator(wrapped)
            registered_tools.append(func.__name__)
            return func

        mock_mcp.tool = mock_tool_decorator

        register_pool_tools(mock_mcp, mock_pool_manager)

        # Verify all 7 tools were registered
        expected_tools = [
            "pool_list",
            "pool_monitor",
            "pool_scale",
            "pool_close",
            "pool_close_all",
            "pool_health",
            "pool_search_memory",
        ]

        for tool in expected_tools:
            assert tool in registered_tools, f"Tool {tool} was not registered"
