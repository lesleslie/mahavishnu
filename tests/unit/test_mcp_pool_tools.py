"""Comprehensive tests for MCP pool management tools."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.pool_tools import register_pool_tools
from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.manager import PoolSelector


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


class TestPoolSpawnTool:
    """Test pool_spawn tool."""

    @pytest.mark.asyncio
    async def test_pool_spawn_mahavishnu_pool(self, mock_mcp, mock_pool_manager):
        """Test spawning a mahavishnu pool."""
        register_pool_tools(mock_mcp, mock_pool_manager)

        # Import and call the tool function

        # Re-register to get the tool function
        @mock_mcp.tool()
        async def pool_spawn(
            pool_type: str = "mahavishnu",
            name: str = "default",
            min_workers: int = 1,
            max_workers: int = 10,
            worker_type: str = "terminal-claude",
        ):

            config = PoolConfig(
                name=name,
                pool_type=pool_type,
                min_workers=min_workers,
                max_workers=max_workers,
                worker_type=worker_type,
            )
            pool_id = await mock_pool_manager.spawn_pool(pool_type, config)
            return {
                "pool_id": pool_id,
                "pool_type": pool_type,
                "name": name,
                "status": "created",
                "min_workers": min_workers,
                "max_workers": max_workers,
            }

        result = await pool_spawn(
            pool_type="mahavishnu", name="test-pool", min_workers=2, max_workers=5
        )

        assert result["status"] == "created"
        assert result["pool_id"] == "pool_test_id"
        assert result["pool_type"] == "mahavishnu"
        assert result["name"] == "test-pool"
        assert result["min_workers"] == 2
        assert result["max_workers"] == 5

    @pytest.mark.asyncio
    async def test_pool_spawn_session_buddy_pool(self, mock_mcp, mock_pool_manager):
        """Test spawning a session-buddy pool."""

        @mock_mcp.tool()
        async def pool_spawn(
            pool_type: str = "session-buddy",
            name: str = "buddy-pool",
            min_workers: int = 3,
            max_workers: int = 3,
            worker_type: str = "terminal-claude",
        ):

            config = PoolConfig(
                name=name,
                pool_type=pool_type,
                min_workers=min_workers,
                max_workers=max_workers,
                worker_type=worker_type,
            )
            pool_id = await mock_pool_manager.spawn_pool(pool_type, config)
            return {
                "pool_id": pool_id,
                "pool_type": pool_type,
                "name": name,
                "status": "created",
                "min_workers": min_workers,
                "max_workers": max_workers,
            }

        result = await pool_spawn()

        assert result["status"] == "created"
        assert result["pool_type"] == "session-buddy"

    @pytest.mark.asyncio
    async def test_pool_spawn_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_spawn handles errors gracefully."""
        mock_pool_manager.spawn_pool = AsyncMock(side_effect=Exception("Spawn failed"))

        @mock_mcp.tool()
        async def pool_spawn(pool_type: str = "mahavishnu", name: str = "test"):

            config = PoolConfig(name=name, pool_type=pool_type, min_workers=1, max_workers=10)
            try:
                pool_id = await mock_pool_manager.spawn_pool(pool_type, config)
                return {
                    "pool_id": pool_id,
                    "pool_type": pool_type,
                    "name": name,
                    "status": "created",
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "error": str(e),
                }

        result = await pool_spawn()
        assert result["status"] == "failed"
        assert "Spawn failed" in result["error"]


class TestPoolExecuteTool:
    """Test pool_execute tool."""

    @pytest.mark.asyncio
    async def test_pool_execute_success(self, mock_mcp, mock_pool_manager):
        """Test successful task execution on pool."""

        @mock_mcp.tool()
        async def pool_execute(pool_id: str, prompt: str, timeout: int = 300):
            task = {"prompt": prompt, "timeout": timeout}
            result = await mock_pool_manager.execute_on_pool(pool_id, task)
            return result

        result = await pool_execute(pool_id="pool_1", prompt="Write Python code", timeout=300)

        assert result["status"] == "completed"
        assert result["output"] == "test output"
        mock_pool_manager.execute_on_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_pool_execute_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_execute handles errors gracefully."""
        mock_pool_manager.execute_on_pool = AsyncMock(side_effect=Exception("Task failed"))

        @mock_mcp.tool()
        async def pool_execute(pool_id: str, prompt: str, timeout: int = 300):
            task = {"prompt": prompt, "timeout": timeout}
            try:
                result = await mock_pool_manager.execute_on_pool(pool_id, task)
                return result
            except Exception as e:
                return {
                    "pool_id": pool_id,
                    "status": "failed",
                    "error": str(e),
                }

        result = await pool_execute(pool_id="pool_1", prompt="test")
        assert result["status"] == "failed"
        assert "Task failed" in result["error"]


class TestPoolRouteExecuteTool:
    """Test pool_route_execute tool."""

    @pytest.mark.asyncio
    async def test_pool_route_execute_least_loaded(self, mock_mcp, mock_pool_manager):
        """Test routing task to least loaded pool."""

        @mock_mcp.tool()
        async def pool_route_execute(
            prompt: str,
            pool_selector: str = "least_loaded",
            timeout: int = 300,
        ):

            task = {"prompt": prompt, "timeout": timeout}
            selector = PoolSelector(pool_selector)
            result = await mock_pool_manager.route_task(task, selector)
            return result

        result = await pool_route_execute(prompt="Write tests", pool_selector="least_loaded")

        assert result["status"] == "completed"
        assert result["pool_id"] == "pool_test_id"

    @pytest.mark.asyncio
    async def test_pool_route_execute_round_robin(self, mock_mcp, mock_pool_manager):
        """Test routing task with round robin strategy."""

        @mock_mcp.tool()
        async def pool_route_execute(
            prompt: str,
            pool_selector: str = "round_robin",
            timeout: int = 300,
        ):

            task = {"prompt": prompt, "timeout": timeout}
            selector = PoolSelector(pool_selector)
            result = await mock_pool_manager.route_task(task, selector)
            return result

        result = await pool_route_execute(prompt="Write tests", pool_selector="round_robin")

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_pool_route_execute_error_handling(self, mock_mcp, mock_pool_manager):
        """Test pool_route_execute handles errors gracefully."""
        mock_pool_manager.route_task = AsyncMock(side_effect=Exception("Routing failed"))

        @mock_mcp.tool()
        async def pool_route_execute(
            prompt: str,
            pool_selector: str = "least_loaded",
            timeout: int = 300,
        ):

            task = {"prompt": prompt, "timeout": timeout}
            try:
                selector = PoolSelector(pool_selector)
                result = await mock_pool_manager.route_task(task, selector)
                return result
            except Exception as e:
                return {
                    "status": "failed",
                    "error": str(e),
                }

        result = await pool_route_execute(prompt="test")
        assert result["status"] == "failed"
        assert "Routing failed" in result["error"]

    @pytest.mark.asyncio
    async def test_pool_route_execute_refuses_peer_affinity(self, mock_mcp, mock_pool_manager):
        """Security: ``pool_route_execute`` no longer refuses
        ``peer_affinity`` at the surface. The experimental refusal
        was removed in favor of caller-side authorization
        (ADR-014). The tool now forwards the call to the manager
        with the caller's allowlist; the manager is responsible
        for honoring or rejecting the peer hint.

        This test now asserts the NEW contract: the tool does
        NOT short-circuit on ``peer_affinity`` — it delegates to
        ``PoolManager.route_task`` and passes the allowlist
        through. (Authorization is enforced downstream.)
        """
        registered: dict[str, Any] = {}

        def capture_tool(fn=None):
            if fn is None:
                return lambda wrapped: capture_tool(wrapped)
            registered[fn.__name__] = fn
            return fn

        mock_mcp.tool = capture_tool
        register_pool_tools(mock_mcp, mock_pool_manager)

        # Sanity: pool_route_execute was registered.
        assert "pool_route_execute" in registered, (
            "register_pool_tools must register pool_route_execute"
        )
        tool_fn = registered["pool_route_execute"]

        # Configure the mock manager to return a successful
        # route. The MCP tool must no longer refuse
        # ``peer_affinity`` at the surface — it must delegate to
        # the manager.
        captured_kwargs: dict[str, Any] = {}

        async def capture_route(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "pool_id": "pool_abc",
                "status": "completed",
                "routing_reason": "peer_affinity",
            }

        mock_pool_manager.route_task = capture_route

        result = await tool_fn(
            prompt="test",
            pool_selector="peer_affinity",
            caller_pool_allowlist=["pool_abc", "pool_xyz"],
        )

        # The tool must have delegated to the manager (no
        # experimental refusal at the surface).
        assert result["status"] == "completed", (
            f"peer_affinity must reach PoolManager.route_task now "
            f"that caller-side authorization is in place, got {result!r}"
        )
        # And the allowlist must be forwarded.
        assert "caller_pool_allowlist" in captured_kwargs, (
            "pool_route_execute must forward caller_pool_allowlist to PoolManager.route_task"
        )
        assert set(captured_kwargs["caller_pool_allowlist"]) == {
            "pool_abc",
            "pool_xyz",
        }

    @pytest.mark.asyncio
    async def test_pool_route_execute_peer_affinity_with_allowlist(
        self, mock_mcp, mock_pool_manager
    ):
        """Caller-side authorization: ``pool_route_execute`` accepts
        a caller-supplied pool allowlist and forwards it to
        ``PoolManager.route_task`` so PEER_AFFINITY can route to
        pools the caller is authorized to dispatch into.

        ADR-014 codifies that the ACL is authoritative. The MCP
        tool surface is one such caller — once it supplies an
        allowlist (typically from configuration), the experimental
        refusal is no longer required and the call proceeds to the
        manager with the allowlist applied.
        """
        registered: dict[str, Any] = {}

        def capture_tool(fn=None):
            if fn is None:
                return lambda wrapped: capture_tool(wrapped)
            registered[fn.__name__] = fn
            return fn

        mock_mcp.tool = capture_tool
        register_pool_tools(mock_mcp, mock_pool_manager)

        # Sanity: pool_route_execute was registered.
        assert "pool_route_execute" in registered, (
            "register_pool_tools must register pool_route_execute"
        )
        tool_fn = registered["pool_route_execute"]

        # Capture the kwargs the MCP tool passes to route_task so
        # we can assert the allowlist is forwarded. The capture
        # returns a successful result directly (we are not
        # exercising the manager's real PEER_AFFINITY logic here
        # — that lives in tests/unit/pools/test_route_task_peer_affinity_auth.py).
        captured_kwargs: dict[str, Any] = {}

        async def capture_route(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "pool_id": "pool_abc",
                "status": "completed",
                "routing_reason": "peer_affinity",
            }

        mock_pool_manager.route_task = capture_route

        result = await tool_fn(
            prompt="do stuff",
            pool_selector="peer_affinity",
            caller_pool_allowlist=["pool_abc", "pool_xyz"],
        )

        # The tool must have routed successfully (no experimental
        # refusal) AND forwarded the allowlist to the manager.
        assert result["status"] == "completed"
        assert result["pool_id"] == "pool_abc"
        assert "caller_pool_allowlist" in captured_kwargs, (
            "pool_route_execute must forward caller_pool_allowlist to "
            "PoolManager.route_task so the manager can apply the "
            "caller-side authorization check."
        )
        # The MCP tool should normalize the list to a set-like
        # container that the manager can intersect.
        forwarded = captured_kwargs["caller_pool_allowlist"]
        assert set(forwarded) == {"pool_abc", "pool_xyz"}, (
            f"forwarded allowlist must preserve pool ids, got {forwarded!r}"
        )


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
        pool = mock_pool_manager._pools["pool_1"]

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
            except Exception as e:
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
            except Exception as e:
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
            except Exception:
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
        """Test that register_pool_tools registers all 10 tools."""
        # Track tool registrations
        registered_tools = []

        def mock_tool_decorator(func=None):
            if func is None:
                return lambda wrapped: mock_tool_decorator(wrapped)
            registered_tools.append(func.__name__)
            return func

        mock_mcp.tool = mock_tool_decorator

        register_pool_tools(mock_mcp, mock_pool_manager)

        # Verify all 10 tools were registered
        expected_tools = [
            "pool_spawn",
            "pool_execute",
            "pool_route_execute",
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
