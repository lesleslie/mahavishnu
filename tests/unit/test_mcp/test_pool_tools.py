"""Unit tests for mahavishnu.mcp.tools.pool_tools.

The module exposes ``register_pool_tools`` which attaches 8 FastMCP tools
(``pool_list``, ``pool_monitor``, ``pool_scale``, ``pool_close``,
``pool_close_all``, ``pool_health``, ``pool_search_memory``, and
``budget_enforce``).

The FastMCP API requires each tool function to be defined inline so the
decorator can introspect the function name and signature. We therefore
register against a stub ``FastMCP`` instance that captures the decorated
callables in a dict, then invoke each registered function directly with
mocked dependencies. This avoids re-implementing the tools in test bodies.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.pool_tools import register_pool_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Stub MCP and fixtures
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def mock_pool_manager() -> AsyncMock:
    """Build an AsyncMock pool manager with realistic defaults."""
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
    manager.health_check = AsyncMock(return_value={"status": "healthy", "pools_active": 2})
    manager.close_pool = AsyncMock(return_value=None)
    manager.close_all = AsyncMock(return_value=None)
    # ``pool_scale`` reaches into ``pool_manager._pools`` to look up the
    # concrete pool object so it can call ``.scale(target_workers)``.
    pool_one = MagicMock()
    pool_one.scale = AsyncMock(return_value=None)
    pool_one._workers = [1, 2, 3, 4, 5]
    pool_two = MagicMock()
    pool_two.scale = AsyncMock(return_value=None)
    pool_two._workers = [1, 2, 3]
    manager._pools = {"pool_1": pool_one, "pool_2": pool_two}
    return manager


@pytest.fixture
def registered_mcp(stub_mcp: _StubMCP, mock_pool_manager: AsyncMock) -> _StubMCP:
    """Register pool tools on a stub MCP for inspection / invocation."""
    register_pool_tools(stub_mcp, mock_pool_manager)
    return stub_mcp


EXPECTED_TOOL_NAMES = {
    "pool_list",
    "pool_monitor",
    "pool_scale",
    "pool_close",
    "pool_close_all",
    "pool_health",
    "pool_search_memory",
    "budget_enforce",
}


# =============================================================================
# TestRegistration
# =============================================================================


class TestRegistration:
    """register_pool_tools attaches every documented tool to the FastMCP."""

    def test_all_seven_tools_registered(self, registered_mcp: _StubMCP) -> None:
        assert EXPECTED_TOOL_NAMES.issubset(set(registered_mcp.tools))

    def test_registers_exactly_expected_tools(self, registered_mcp: _StubMCP) -> None:
        assert set(registered_mcp.tools) == EXPECTED_TOOL_NAMES


# =============================================================================
# TestPoolList
# =============================================================================


class TestPoolList:
    """``pool_list`` returns all active pools from the manager."""

    async def test_returns_pool_list(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_list"]
        pools = await fn()
        assert pools == [
            {"pool_id": "pool_1", "pool_type": "mahavishnu", "status": "active"},
            {"pool_id": "pool_2", "pool_type": "session-buddy", "status": "active"},
        ]

    async def test_empty_list(self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock) -> None:
        mock_pool_manager.list_pools = AsyncMock(return_value=[])
        fn = registered_mcp.tools["pool_list"]
        assert await fn() == []

    async def test_exception_returns_empty_list(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.list_pools = AsyncMock(side_effect=RuntimeError("list failed"))
        fn = registered_mcp.tools["pool_list"]
        assert await fn() == []


# =============================================================================
# TestPoolMonitor
# =============================================================================


class TestPoolMonitor:
    """``pool_monitor`` aggregates pool metrics."""

    async def test_returns_all_pools_when_pool_ids_is_none(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_monitor"]
        metrics = await fn()
        assert "pool_1" in metrics
        assert "pool_2" in metrics
        # None is the documented "all pools" signal.
        mock_pool_manager.aggregate_results.assert_awaited_with(None)

    async def test_passes_specific_pool_ids(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_monitor"]
        await fn(pool_ids=["pool_1"])
        mock_pool_manager.aggregate_results.assert_awaited_with(["pool_1"])

    async def test_exception_returns_empty_dict(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.aggregate_results = AsyncMock(side_effect=RuntimeError("monitor failed"))
        fn = registered_mcp.tools["pool_monitor"]
        assert await fn() == {}


# =============================================================================
# TestPoolScale
# =============================================================================


class TestPoolScale:
    """``pool_scale`` adjusts a pool's worker count."""

    async def test_scale_success(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_scale"]
        result = await fn(pool_id="pool_1", target_workers=10)
        assert result["status"] == "scaled"
        assert result["pool_id"] == "pool_1"
        assert result["target_workers"] == 10
        assert result["actual_workers"] == 5
        mock_pool_manager._pools["pool_1"].scale.assert_awaited_with(10)

    async def test_pool_not_found(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_scale"]
        result = await fn(pool_id="nope", target_workers=5)
        assert result["status"] == "failed"
        assert "not found" in result["error"]
        assert result["pool_id"] == "nope"

    async def test_not_implemented_returns_descriptive_failure(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager._pools["pool_1"].scale = AsyncMock(
            side_effect=NotImplementedError("fixed at 3")
        )
        fn = registered_mcp.tools["pool_scale"]
        result = await fn(pool_id="pool_1", target_workers=10)
        assert result["status"] == "failed"
        assert "does not support scaling" in result["error"]

    async def test_unexpected_exception_returns_failure(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager._pools["pool_1"].scale = AsyncMock(
            side_effect=RuntimeError("scale exploded")
        )
        fn = registered_mcp.tools["pool_scale"]
        result = await fn(pool_id="pool_1", target_workers=10)
        assert result["status"] == "failed"
        assert "scale exploded" in result["error"]


# =============================================================================
# TestPoolClose
# =============================================================================


class TestPoolClose:
    """``pool_close`` shuts down a single pool."""

    async def test_close_success(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_close"]
        result = await fn(pool_id="pool_1")
        assert result == {"pool_id": "pool_1", "status": "closed"}
        mock_pool_manager.close_pool.assert_awaited_with("pool_1")

    async def test_close_failure(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.close_pool = AsyncMock(side_effect=RuntimeError("close failed"))
        fn = registered_mcp.tools["pool_close"]
        result = await fn(pool_id="pool_1")
        assert result["status"] == "failed"
        assert "close failed" in result["error"]
        assert result["pool_id"] == "pool_1"


# =============================================================================
# TestPoolCloseAll
# =============================================================================


class TestPoolCloseAll:
    """``pool_close_all`` shuts down every active pool."""

    async def test_close_all_with_pools(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_close_all"]
        result = await fn()
        assert result == {"pools_closed": 2, "status": "all_closed"}
        mock_pool_manager.close_all.assert_awaited_once()

    async def test_close_all_with_no_pools(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.list_pools = AsyncMock(return_value=[])
        fn = registered_mcp.tools["pool_close_all"]
        result = await fn()
        assert result == {"pools_closed": 0, "status": "all_closed"}

    async def test_close_all_failure(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.close_all = AsyncMock(side_effect=RuntimeError("close all failed"))
        fn = registered_mcp.tools["pool_close_all"]
        result = await fn()
        assert result["status"] == "failed"
        assert result["pools_closed"] == 0
        assert "close all failed" in result["error"]


# =============================================================================
# TestPoolHealth
# =============================================================================


class TestPoolHealth:
    """``pool_health`` reports health of all pools."""

    async def test_health_success(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_health"]
        result = await fn()
        assert result == {"status": "healthy", "pools_active": 2}

    async def test_health_failure(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.health_check = AsyncMock(side_effect=RuntimeError("health failed"))
        fn = registered_mcp.tools["pool_health"]
        result = await fn()
        assert result["status"] == "unhealthy"
        assert "health failed" in result["error"]


# =============================================================================
# TestPoolSearchMemory
# =============================================================================


class TestPoolSearchMemory:
    """``pool_search_memory`` delegates to MemoryAggregator."""

    async def test_returns_aggregator_results(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_aggregator = MagicMock()
        mock_aggregator.cross_pool_search = AsyncMock(
            return_value=[
                {"content": "API implementation code", "score": 0.95},
                {"content": "Test code", "score": 0.85},
            ]
        )
        with patch(
            "mahavishnu.mcp.tools.pool_tools.MemoryAggregator",
            return_value=mock_aggregator,
        ):
            fn = registered_mcp.tools["pool_search_memory"]
            results = await fn(query="API", limit=50)
        assert results == [
            {"content": "API implementation code", "score": 0.95},
            {"content": "Test code", "score": 0.85},
        ]
        mock_aggregator.cross_pool_search.assert_awaited_once_with(
            query="API",
            pool_manager=mock_pool_manager,
            limit=50,
        )

    async def test_exception_returns_empty_list(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_aggregator = MagicMock()
        mock_aggregator.cross_pool_search = AsyncMock(side_effect=RuntimeError("search failed"))
        with patch(
            "mahavishnu.mcp.tools.pool_tools.MemoryAggregator",
            return_value=mock_aggregator,
        ):
            fn = registered_mcp.tools["pool_search_memory"]
            assert await fn(query="x") == []

    async def test_returns_empty_when_aggregator_unavailable(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        """If MemoryAggregator failed to import, the tool guards
        against ``aggregator_cls is None`` and returns ``[]``."""
        with patch("mahavishnu.mcp.tools.pool_tools.MemoryAggregator", None):
            fn = registered_mcp.tools["pool_search_memory"]
            assert await fn(query="x") == []


# =============================================================================
# TestPoolSelectorEnum
# =============================================================================


class TestPoolSelectorEnum:
    """Sanity check the documented PoolSelector enum members."""

    def test_expected_selectors_exist(self) -> None:
        from mahavishnu.pools.manager import PoolSelector

        # The MCP tool accepts a string and forwards a PoolSelector
        # constructed from that string. All strings in this set must
        # therefore be valid ``PoolSelector(<value>)`` arguments.
        expected = {
            "round_robin",
            "least_loaded",
            "random",
            "affinity",
            "peer_affinity",
        }
        actual = {member.value for member in PoolSelector}
        assert expected.issubset(actual)
