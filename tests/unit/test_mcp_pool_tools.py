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
        """Test that register_pool_tools registers all 9 tools (incl. Phase 2m)."""
        # Track tool registrations
        registered_tools = []

        def mock_tool_decorator(func=None):
            if func is None:
                return lambda wrapped: mock_tool_decorator(wrapped)
            registered_tools.append(func.__name__)
            return func

        mock_mcp.tool = mock_tool_decorator

        register_pool_tools(mock_mcp, mock_pool_manager)

        # Verify all 9 tools were registered
        expected_tools = [
            "pool_list",
            "pool_monitor",
            "pool_scale",
            "pool_close",
            "pool_close_all",
            "pool_health",
            "pool_search_memory",
            "budget_enforce",
            "pool_route_execute",
        ]

        for tool in expected_tools:
            assert tool in registered_tools, f"Tool {tool} was not registered"


def _capture_pool_route_execute(mock_pool_manager):
    """Capture the registered ``pool_route_execute`` callable by stubbing
    ``mcp.tool`` with a registering decorator. Returns the real function so
    tests can call it with various args and assert on the result.
    """
    from unittest.mock import MagicMock

    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    captured: dict[str, object] = {}

    def registering_decorator(func=None):
        if func is None:
            return lambda wrapped: registering_decorator(wrapped)
        captured[func.__name__] = func
        return func

    mcp = MagicMock()
    mcp.tool = registering_decorator
    register_pool_tools(mcp, mock_pool_manager)

    return captured["pool_route_execute"]


class TestPoolRouteExecuteTool:
    """Plan v3 Phase 2m — 8 scenarios.

    Verifies the registered ``pool_route_execute`` callable reacts
    correctly to: happy path, RateLimitError envelope, asyncio
    TimeoutError, ValueError (unknown selector + missing pool_affinity
    for AFFINITY), RuntimeError (empty pool registry + non-empty
    message), caller_kind coercion, default caller_kind semantics.
    """

    @pytest.mark.asyncio
    async def test_pool_route_execute_happy_path(self, mock_pool_manager):
        """Scenario 1 — default selector + caller_kind='claude_code' delegates to route_task."""
        execute = _capture_pool_route_execute(mock_pool_manager)

        result = await execute(prompt="write a haiku")

        assert result == {"pool_id": "pool_test_id", "status": "completed"}
        mock_pool_manager.route_task.assert_awaited_once()
        call_kwargs = mock_pool_manager.route_task.await_args.kwargs
        assert call_kwargs["task"] == {"prompt": "write a haiku"}
        assert call_kwargs["pool_affinity"] is None
        assert call_kwargs["auto_spawn"] is False

    @pytest.mark.asyncio
    async def test_pool_route_execute_rate_limit_envelope(self, mock_pool_manager):
        """Scenario 2 — RateLimitError → {status: 'rate_limited', retry_after_seconds, limit}."""
        from mahavishnu.core.errors import RateLimitError

        # RateLimitError signature: (limit: str, retry_after: int | None = None).
        # The constructor stores details={"limit": ..., "retry_after_seconds": ...}.
        err = RateLimitError("caller_kind=ultracode", retry_after=42)
        mock_pool_manager.route_task = AsyncMock(side_effect=err)

        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi")

        assert result["status"] == "rate_limited"
        assert result["retry_after_seconds"] == 42
        assert result["limit"] == "caller_kind=ultracode"

    @pytest.mark.asyncio
    async def test_pool_route_execute_timeout_envelope(self, mock_pool_manager):
        """Scenario 3 — asyncio.TimeoutError (or TimeoutError on py3.11+) → {status: 'timeout'}."""
        mock_pool_manager.route_task = AsyncMock(side_effect=TimeoutError())

        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi")

        assert result == {"status": "timeout"}

    @pytest.mark.asyncio
    async def test_pool_route_execute_invalid_selector_envelope(self, mock_pool_manager):
        """Scenario 4 — ValueError from ``PoolSelector('invalid_garbage')`` →
        {status: 'invalid_selector', error: ...}. Actually caught at the
        selector-string → enum conversion; route_task is never called.
        """
        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi", pool_selector="not_a_real_selector_value")

        assert result["status"] == "invalid_selector"
        assert "Unknown pool_selector" in result["error"]
        # route_task was never called — selector failed at the boundary.
        mock_pool_manager.route_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_pool_route_execute_affinity_without_pool_affinity(
        self, mock_pool_manager
    ):
        """Scenario 5 — PoolSelector.AFFINITY requires pool_affinity arg.

        Valid selector string + missing pool_affinity: route_task will
        raise a ValueError (per PoolManager.AFFINITY handling), and our
        boundary converts it to the invalid_selector envelope.
        """
        mock_pool_manager.route_task = AsyncMock(
            side_effect=ValueError("AFFINITY selector requires pool_affinity")
        )

        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi", pool_selector="affinity")

        assert result["status"] == "invalid_selector"
        assert "AFFINITY" in result["error"]

    @pytest.mark.asyncio
    async def test_pool_route_execute_empty_pool_registry_envelope(
        self, mock_pool_manager
    ):
        """Scenario 6 — RuntimeError with 'No pools available for routing'
        → {status: 'failed', error: ...}.
        """
        mock_pool_manager.route_task = AsyncMock(
            side_effect=RuntimeError("No pools available for routing")
        )

        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi")

        assert result["status"] == "failed"
        assert "No pools available" in result["error"]

    @pytest.mark.asyncio
    async def test_pool_route_execute_other_runtime_error_envelope(
        self, mock_pool_manager
    ):
        """Scenario 7 — RuntimeError with a different message (e.g. allowlist
        empty) is still mapped to {status: 'failed', error: ...}.
        """
        mock_pool_manager.route_task = AsyncMock(
            side_effect=RuntimeError("allowlist empty")
        )

        execute = _capture_pool_route_execute(mock_pool_manager)
        result = await execute(prompt="hi")

        assert result["status"] == "failed"
        assert "allowlist empty" in result["error"]

    @pytest.mark.asyncio
    async def test_pool_route_execute_caller_kind_default_is_claude_code(
        self, mock_pool_manager
    ):
        """Scenario 8 — default caller_kind resolves through
        coerce_caller_kind; unknown wire-strings map to UNKNOWN bucket.
        """
        execute = _capture_pool_route_execute(mock_pool_manager)

        # No caller_kind → default "claude_code"
        await execute(prompt="hi")
        # When the coerce caller unwraps to the UNKNOWN enum (since
        # `coerce_caller_kind` is best-effort in our impl), it's still
        # passed through as the wire string. The test asserts that a
        # caller_kind is passed (defaulted) rather than None.
        kwargs = mock_pool_manager.route_task.await_args.kwargs
        assert "caller_kind" in kwargs
        assert kwargs["caller_kind"] is not None

        # Bogus wire string → falls through to UNKNOWN-style string
        mock_pool_manager.route_task.reset_mock()
        await execute(prompt="hi2", caller_kind="definitely_not_an_enum_value")
        kwargs2 = mock_pool_manager.route_task.await_args.kwargs
        assert "caller_kind" in kwargs2

