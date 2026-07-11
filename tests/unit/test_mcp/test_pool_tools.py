"""Unit tests for mahavishnu.mcp.tools.pool_tools.

The module exposes ``register_pool_tools`` which attaches 11 FastMCP tools
(``pool_spawn``, ``pool_execute``, ``pool_route_execute``,
``dispatch_to_pool``, ``pool_list``, ``pool_monitor``, ``pool_scale``,
``pool_close``, ``pool_close_all``, ``pool_health``,
``pool_search_memory``) plus the module-level
``_resolve_peer_affinity_allowlist_from_env`` helper.

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

from mahavishnu.mcp.tools.pool_tools import (
    _resolve_peer_affinity_allowlist_from_env,
    register_pool_tools,
)

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
    manager.route_task = AsyncMock(
        return_value={"pool_id": "pool_test_id", "status": "completed"}
    )
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
        return_value={"status": "healthy", "pools_active": 2}
    )
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
    "pool_spawn",
    "pool_execute",
    "pool_route_execute",
    "dispatch_to_pool",
    "pool_list",
    "pool_monitor",
    "pool_scale",
    "pool_close",
    "pool_close_all",
    "pool_health",
    "pool_search_memory",
}


# =============================================================================
# TestRegistration
# =============================================================================


class TestRegistration:
    """register_pool_tools attaches every documented tool to the FastMCP."""

    def test_all_eleven_tools_registered(self, registered_mcp: _StubMCP) -> None:
        assert EXPECTED_TOOL_NAMES.issubset(set(registered_mcp.tools))

    def test_registers_exactly_expected_tools(self, registered_mcp: _StubMCP) -> None:
        assert set(registered_mcp.tools) == EXPECTED_TOOL_NAMES


# =============================================================================
# TestResolveAllowlist
# =============================================================================


class TestResolvePeerAffinityAllowlistFromEnv:
    """``_resolve_peer_affinity_allowlist_from_env`` reads the env var."""

    def test_unset_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", raising=False)
        assert _resolve_peer_affinity_allowlist_from_env() is None

    def test_empty_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "")
        assert _resolve_peer_affinity_allowlist_from_env() is None

    def test_whitespace_only_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "   ")
        assert _resolve_peer_affinity_allowlist_from_env() is None

    def test_wildcard_returns_singleton_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "*")
        assert _resolve_peer_affinity_allowlist_from_env() == {"*"}

    def test_comma_separated_returns_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "pool_abc, pool_xyz , pool_q"
        )
        assert _resolve_peer_affinity_allowlist_from_env() == {
            "pool_abc",
            "pool_xyz",
            "pool_q",
        }

    def test_skips_empty_segments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "pool_abc,, pool_xyz,"
        )
        assert _resolve_peer_affinity_allowlist_from_env() == {
            "pool_abc",
            "pool_xyz",
        }


# =============================================================================
# TestPoolSpawn
# =============================================================================


class TestPoolSpawn:
    """``pool_spawn`` creates a new pool via PoolManager.spawn_pool."""

    async def test_returns_pool_id_and_status(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_spawn"]
        result = await fn(
            pool_type="mahavishnu",
            name="test-pool",
            min_workers=2,
            max_workers=5,
            worker_type="terminal-claude",
        )
        assert result["status"] == "created"
        assert result["pool_id"] == "pool_test_id"
        assert result["pool_type"] == "mahavishnu"
        assert result["name"] == "test-pool"
        assert result["min_workers"] == 2
        assert result["max_workers"] == 5

    async def test_passes_pool_config_to_manager(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_spawn"]
        await fn(
            pool_type="session-buddy",
            name="buddy-pool",
            min_workers=3,
            max_workers=3,
            worker_type="terminal-claude",
        )
        mock_pool_manager.spawn_pool.assert_awaited_once()
        # Second positional arg is the PoolConfig; ensure it carries
        # the kwargs the caller passed through.
        _pool_type, config = mock_pool_manager.spawn_pool.call_args.args
        assert config.name == "buddy-pool"
        assert config.pool_type == "session-buddy"
        assert config.min_workers == 3
        assert config.max_workers == 3

    async def test_default_arguments_used_when_omitted(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_spawn"]
        result = await fn()
        assert result["status"] == "created"
        assert result["pool_type"] == "mahavishnu"
        assert result["name"] == "default"
        assert result["min_workers"] == 1
        assert result["max_workers"] == 10

    async def test_returns_failure_dict_on_exception(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.spawn_pool = AsyncMock(
            side_effect=RuntimeError("Spawn failed")
        )
        fn = registered_mcp.tools["pool_spawn"]
        result = await fn(pool_type="mahavishnu", name="test")
        assert result == {"status": "failed", "error": "Spawn failed"}


# =============================================================================
# TestPoolExecute
# =============================================================================


class TestPoolExecute:
    """``pool_execute`` runs a task on a specific pool."""

    async def test_returns_manager_result(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        from mahavishnu.pools.manager import CallerKind

        fn = registered_mcp.tools["pool_execute"]
        result = await fn(pool_id="pool_1", prompt="Write tests", timeout=300)
        assert result == {"status": "completed", "output": "test output"}
        mock_pool_manager.execute_on_pool.assert_awaited_once()
        _pool_id, task = mock_pool_manager.execute_on_pool.call_args.args
        assert _pool_id == "pool_1"
        # pool_execute enriches the task with caller_kind + parent_session_id
        # so downstream code reading the task can see who dispatched it. The
        # baseline prompt/timeout must still be present.
        assert task["prompt"] == "Write tests"
        assert task["timeout"] == 300
        assert task["caller_kind"] == "unknown"  # default coerced to UNKNOWN
        assert task["parent_session_id"] is None
        # The kwarg path also forwarded caller_kind so the manager can
        # enforce quota (Phase 3 security fix: pool_execute gates the same
        # as pool_route_execute).
        assert (
            mock_pool_manager.execute_on_pool.call_args.kwargs["caller_kind"]
            == CallerKind.UNKNOWN
        )

    async def test_uses_default_timeout(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_execute"]
        await fn(pool_id="pool_1", prompt="hi")
        _, task = mock_pool_manager.execute_on_pool.call_args.args
        assert task["timeout"] == 300

    async def test_returns_failure_dict_on_exception(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.execute_on_pool = AsyncMock(
            side_effect=RuntimeError("Task failed")
        )
        fn = registered_mcp.tools["pool_execute"]
        result = await fn(pool_id="pool_1", prompt="x")
        assert result["status"] == "failed"
        assert "Task failed" in result["error"]
        assert result["pool_id"] == "pool_1"


# =============================================================================
# TestPoolRouteExecute
# =============================================================================


class TestPoolRouteExecute:
    """``pool_route_execute`` routes a task via a PoolSelector."""

    async def test_least_loaded_default(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_route_execute"]
        result = await fn(prompt="Write tests")
        assert result["status"] == "completed"
        _task, selector = mock_pool_manager.route_task.call_args.args
        assert selector.value == "least_loaded"

    async def test_round_robin_selector(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["pool_route_execute"]
        result = await fn(prompt="Write tests", pool_selector="round_robin")
        assert result["status"] == "completed"
        _task, selector = mock_pool_manager.route_task.call_args.args
        assert selector.value == "round_robin"

    async def test_returns_failure_dict_on_exception(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.route_task = AsyncMock(
            side_effect=RuntimeError("Routing failed")
        )
        fn = registered_mcp.tools["pool_route_execute"]
        result = await fn(prompt="x")
        assert result == {"status": "failed", "error": "Routing failed"}

    async def test_explicit_caller_pool_allowlist_forwarded(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        """When the caller supplies an allowlist, it's forwarded to the
        manager as-is so the manager can apply ADR-014 authorization."""
        fn = registered_mcp.tools["pool_route_execute"]
        await fn(
            prompt="x",
            pool_selector="peer_affinity",
            caller_pool_allowlist=["pool_abc", "pool_xyz"],
        )
        _, kwargs = mock_pool_manager.route_task.call_args
        assert set(kwargs["caller_pool_allowlist"]) == {"pool_abc", "pool_xyz"}

    async def test_env_allowlist_used_when_arg_omitted(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "pool_env_a,pool_env_b"
        )
        fn = registered_mcp.tools["pool_route_execute"]
        await fn(prompt="x", pool_selector="peer_affinity")
        _, kwargs = mock_pool_manager.route_task.call_args
        assert set(kwargs["caller_pool_allowlist"]) == {
            "pool_env_a",
            "pool_env_b",
        }

    async def test_explicit_allowlist_overrides_env(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(
            "MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", "pool_env_only"
        )
        fn = registered_mcp.tools["pool_route_execute"]
        await fn(
            prompt="x",
            pool_selector="peer_affinity",
            caller_pool_allowlist=["pool_arg_a"],
        )
        _, kwargs = mock_pool_manager.route_task.call_args
        assert set(kwargs["caller_pool_allowlist"]) == {"pool_arg_a"}

    async def test_no_allowlist_passes_none_when_env_unset(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MAHAVISHNU_PEER_AFFINITY_ALLOWLIST", raising=False)
        fn = registered_mcp.tools["pool_route_execute"]
        await fn(prompt="x")
        _, kwargs = mock_pool_manager.route_task.call_args
        assert kwargs["caller_pool_allowlist"] is None


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

    async def test_empty_list(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.list_pools = AsyncMock(return_value=[])
        fn = registered_mcp.tools["pool_list"]
        assert await fn() == []

    async def test_exception_returns_empty_list(
        self, registered_mcp: _StubMCP, mock_pool_manager: AsyncMock
    ) -> None:
        mock_pool_manager.list_pools = AsyncMock(
            side_effect=RuntimeError("list failed")
        )
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
        mock_pool_manager.aggregate_results = AsyncMock(
            side_effect=RuntimeError("monitor failed")
        )
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
        mock_pool_manager.close_pool = AsyncMock(
            side_effect=RuntimeError("close failed")
        )
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
        mock_pool_manager.close_all = AsyncMock(
            side_effect=RuntimeError("close all failed")
        )
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
        mock_pool_manager.health_check = AsyncMock(
            side_effect=RuntimeError("health failed")
        )
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
        mock_aggregator.cross_pool_search = AsyncMock(
            side_effect=RuntimeError("search failed")
        )
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
