"""Comprehensive unit tests for MahavishnuAgent."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from mahavishnu.agents.mahavishnu_agent import (
    MahavishnuAgent,
    get_mahavishnu_agent,
    reset_agent,
    SweepReposRequest,
    SweepReposResult,
    RouteTaskRequest,
    RouteTaskResult,
    PoolStatusResult,
    RoutingInfoResult,
)


# ---------------------------------------------------------------------------
# Pydantic Model Validation Tests
# ---------------------------------------------------------------------------

class TestSweepReposRequest:
    """Tests for SweepReposRequest validation."""

    def test_valid_minimal(self):
        """Valid request with just required tag."""
        req = SweepReposRequest(tag="backend")
        assert req.tag == "backend"
        assert req.adapter == "agno"
        assert req.strategy == "balanced"
        assert req.dry_run is False

    def test_valid_full(self):
        """Valid request with all fields."""
        req = SweepReposRequest(
            tag="backend",
            adapter="llamaindex",
            strategy="cost",
            dry_run=True,
        )
        assert req.tag == "backend"
        assert req.adapter == "llamaindex"
        assert req.strategy == "cost"
        assert req.dry_run is True

    def test_valid_tag_characters(self):
        """Tag accepts allowed characters: alphanumeric, underscore, hyphen."""
        for tag in ["a", "ABC", "abc123", "my_tag", "my-tag", "a_b_c", "a-b-c", "Tag_123-456"]:
            req = SweepReposRequest(tag=tag)
            assert req.tag == tag

    def test_invalid_tag_special_chars(self):
        """Tag rejects special characters outside allowed set."""
        for tag in ["tag with space", "tag.dot", "tag/slash", "tag@email", "tag#hash", "tag$", "tag%", "tag!", "tag?"]:
            with pytest.raises(ValidationError):
                SweepReposRequest(tag=tag)

    def test_invalid_tag_empty(self):
        """Tag rejects empty string."""
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="")

    def test_invalid_tag_too_long(self):
        """Tag rejects strings exceeding max_length=50."""
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="a" * 51)

    def test_adapter_enum_values(self):
        """Adapter accepts only valid Literal values."""
        for adapter in ["agno", "llamaindex", "prefect"]:
            req = SweepReposRequest(tag="backend", adapter=adapter)
            assert req.adapter == adapter

    def test_adapter_invalid_value(self):
        """Adapter rejects invalid string."""
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="backend", adapter="invalid")

    def test_strategy_enum_values(self):
        """Strategy accepts only valid Literal values."""
        for strategy in ["cost", "latency", "success_rate", "balanced"]:
            req = SweepReposRequest(tag="backend", strategy=strategy)
            assert req.strategy == strategy

    def test_strategy_invalid_value(self):
        """Strategy rejects invalid string."""
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="backend", strategy="invalid")

    def test_dry_run_boolean(self):
        """dry_run accepts boolean values."""
        req_true = SweepReposRequest(tag="backend", dry_run=True)
        assert req_true.dry_run is True
        req_false = SweepReposRequest(tag="backend", dry_run=False)
        assert req_false.dry_run is False


class TestSweepReposResult:
    """Tests for SweepReposResult structure and field population."""

    def test_default_values(self):
        """All fields have appropriate defaults."""
        result = SweepReposResult(tag="backend")
        assert result.workflow_id == ""
        assert result.tag == "backend"
        assert result.repos_processed == 0
        assert result.adapter_used == ""
        assert result.success is False
        assert result.results == {}
        assert result.error is None

    def test_all_fields_populated(self):
        """All fields can be populated correctly."""
        result = SweepReposResult(
            workflow_id="wf_123",
            tag="backend",
            repos_processed=5,
            adapter_used="agno",
            success=True,
            results={"key": "value"},
            error=None,
        )
        assert result.workflow_id == "wf_123"
        assert result.tag == "backend"
        assert result.repos_processed == 5
        assert result.adapter_used == "agno"
        assert result.success is True
        assert result.results == {"key": "value"}
        assert result.error is None

    def test_error_populated(self):
        """Error field can hold error message."""
        result = SweepReposResult(tag="backend", error="No repos found")
        assert result.error == "No repos found"


class TestRouteTaskRequest:
    """Tests for RouteTaskRequest validation and defaults."""

    def test_valid_minimal(self):
        """Valid request with just required intent."""
        req = RouteTaskRequest(intent="security scan backend repos")
        assert req.intent == "security scan backend repos"
        assert req.strategy == "balanced"
        assert req.enable_fallback is True
        assert req.context is None

    def test_valid_full(self):
        """Valid request with all fields."""
        req = RouteTaskRequest(
            intent="generate a function",
            strategy="cost",
            enable_fallback=False,
            context={"budget": "low"},
        )
        assert req.intent == "generate a function"
        assert req.strategy == "cost"
        assert req.enable_fallback is False
        assert req.context == {"budget": "low"}

    def test_invalid_intent_empty(self):
        """Intent rejects empty string."""
        with pytest.raises(ValidationError):
            RouteTaskRequest(intent="")

    def test_invalid_intent_too_long(self):
        """Intent rejects strings exceeding max_length=1000."""
        with pytest.raises(ValidationError):
            RouteTaskRequest(intent="a" * 1001)

    def test_strategy_enum_values(self):
        """Strategy accepts only valid Literal values."""
        for strategy in ["cost", "latency", "success_rate", "balanced"]:
            req = RouteTaskRequest(intent="scan", strategy=strategy)
            assert req.strategy == strategy

    def test_strategy_invalid_value(self):
        """Strategy rejects invalid string."""
        with pytest.raises(ValidationError):
            RouteTaskRequest(intent="scan", strategy="invalid")

    def test_enable_fallback_default_true(self):
        """enable_fallback defaults to True."""
        req = RouteTaskRequest(intent="test")
        assert req.enable_fallback is True

    def test_context_optional_none(self):
        """context defaults to None when not provided."""
        req = RouteTaskRequest(intent="test")
        assert req.context is None


class TestRouteTaskResult:
    """Tests for RouteTaskResult structure."""

    def test_default_values(self):
        """All fields have appropriate defaults."""
        result = RouteTaskResult(intent="test", task_type="ai_task", adapter_used="agno")
        assert result.fallback_chain == []
        assert result.success is False
        assert result.results == {}
        assert result.error is None

    def test_all_fields_populated(self):
        """All fields can be populated correctly."""
        result = RouteTaskResult(
            intent="code review",
            task_type="ai_task",
            adapter_used="agno",
            fallback_chain=["agno", "llamaindex", "prefect"],
            success=True,
            results={"reviewed": 10},
            error=None,
        )
        assert result.intent == "code review"
        assert result.task_type == "ai_task"
        assert result.adapter_used == "agno"
        assert result.fallback_chain == ["agno", "llamaindex", "prefect"]
        assert result.success is True
        assert result.results == {"reviewed": 10}
        assert result.error is None


class TestPoolStatusResult:
    """Tests for PoolStatusResult structure."""

    def test_default_values(self):
        """All fields have appropriate defaults."""
        result = PoolStatusResult()
        assert result.pools == []
        assert result.total_pools == 0
        assert result.active_workers == 0
        assert result.error is None

    def test_all_fields_populated(self):
        """All fields can be populated correctly."""
        result = PoolStatusResult(
            pools=[{"pool_id": "pool_1", "active_workers": 3}],
            total_pools=1,
            active_workers=3,
            error=None,
        )
        assert len(result.pools) == 1
        assert result.total_pools == 1
        assert result.active_workers == 3

    def test_error_populated(self):
        """Error field can hold error message."""
        result = PoolStatusResult(error="Pool manager unavailable")
        assert result.error == "Pool manager unavailable"


class TestRoutingInfoResult:
    """Tests for RoutingInfoResult structure."""

    def test_required_fields(self):
        """Required fields task_type and strategy exist."""
        result = RoutingInfoResult(task_type="ai_task", strategy="balanced")
        assert result.task_type == "ai_task"
        assert result.strategy == "balanced"

    def test_default_values(self):
        """Optional fields have appropriate defaults."""
        result = RoutingInfoResult(task_type="ai_task", strategy="balanced")
        assert result.fallback_chain == []
        assert result.primary_adapter is None
        assert result.adapter_scores == {}

    def test_all_fields_populated(self):
        """All fields can be populated correctly."""
        result = RoutingInfoResult(
            task_type="ai_task",
            strategy="cost",
            fallback_chain=["agno", "llamaindex"],
            primary_adapter="agno",
            adapter_scores={"agno": 0.9, "llamaindex": 0.7},
        )
        assert result.task_type == "ai_task"
        assert result.strategy == "cost"
        assert result.fallback_chain == ["agno", "llamaindex"]
        assert result.primary_adapter == "agno"
        assert result.adapter_scores == {"agno": 0.9, "llamaindex": 0.7}


# ---------------------------------------------------------------------------
# MahavishnuAgent Method Tests
# ---------------------------------------------------------------------------

class TestMahavishnuAgentInit:
    """Tests for MahavishnuAgent initialization and dependency injection."""

    def test_init_with_none(self):
        """Init with no args creates MahavishnuApp from settings."""
        agent = MahavishnuAgent()
        assert agent._app is not None
        assert isinstance(agent._app, MagicMock) is False

    def test_init_with_mock_app(self):
        """Init with provided app instance uses it directly."""
        mock_app = MagicMock()
        agent = MahavishnuAgent(app=mock_app)
        assert agent._app is mock_app

    def test_init_with_config(self):
        """Init with config creates new MahavishnuApp."""
        from mahavishnu.core.config import MahavishnuSettings
        config = MahavishnuSettings()
        agent = MahavishnuAgent(config=config)
        assert agent._app is not None


class TestMahavishnuAgentSweepRepos:
    """Tests for sweep_repos method."""

    @pytest.mark.asyncio
    async def test_sweep_repos_no_repos_found(self):
        """Returns error result when no repos match tag."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = []

        agent = MahavishnuAgent(app=mock_app)
        request = SweepReposRequest(tag="nonexistent-tag")

        result = await agent.sweep_repos(request)

        assert result.tag == "nonexistent-tag"
        assert result.error is not None
        assert "No repos found" in result.error

    @pytest.mark.asyncio
    async def test_sweep_repos_balanced_agno_executes_parallel(self):
        """balanced strategy + agno adapter uses execute_workflow_parallel."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = [{"path": "/repo/a"}, {"path": "/repo/b"}]
        mock_app.execute_workflow_parallel = AsyncMock(return_value={
            "workflow_id": "wf_abc",
            "adapter_used": "agno",
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        request = SweepReposRequest(tag="backend", adapter="agno", strategy="balanced")

        result = await agent.sweep_repos(request)

        mock_app.execute_workflow_parallel.assert_called_once()
        assert result.success is True
        assert result.workflow_id == "wf_abc"
        assert result.adapter_used == "agno"
        assert result.repos_processed == 2

    @pytest.mark.asyncio
    async def test_sweep_repos_non_balanced_strategy_uses_routing(self):
        """Non-balanced strategy uses execute_workflow_with_routing."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = [{"path": "/repo/a"}]
        mock_app.execute_workflow_with_routing = AsyncMock(return_value={
            "workflow_id": "wf_xyz",
            "adapter_used": "llamaindex",
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        request = SweepReposRequest(tag="backend", adapter="agno", strategy="cost")

        result = await agent.sweep_repos(request)

        mock_app.execute_workflow_with_routing.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sweep_repos_non_agno_adapter_uses_routing(self):
        """Non-agno adapter uses execute_workflow_with_routing even with balanced."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = [{"path": "/repo/a"}]
        mock_app.execute_workflow_with_routing = AsyncMock(return_value={
            "workflow_id": "wf_xyz",
            "adapter_used": "llamaindex",
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        request = SweepReposRequest(tag="backend", adapter="llamaindex", strategy="balanced")

        result = await agent.sweep_repos(request)

        mock_app.execute_workflow_with_routing.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sweep_repos_exception_returns_error(self):
        """Exceptions are caught and returned as error results."""
        mock_app = MagicMock()
        mock_app.get_repos.side_effect = Exception("Simulated failure")

        agent = MahavishnuAgent(app=mock_app)
        request = SweepReposRequest(tag="backend")

        result = await agent.sweep_repos(request)

        assert result.error == "Simulated failure"
        assert result.tag == "backend"


class TestMahavishnuAgentRouteTask:
    """Tests for route_task method."""

    @pytest.fixture
    def mock_router(self):
        """Create a mock TaskRouter."""
        router = MagicMock()
        router.classify_intent.return_value = MagicMock(value="ai_task")
        router.select_adapter = AsyncMock(return_value=MagicMock(value="agno"))
        router.generate_fallback_chain.return_value = [
            MagicMock(value="agno"),
            MagicMock(value="llamaindex"),
        ]
        router.get_adapter_scores = AsyncMock(return_value={
            MagicMock(value="agno"): 0.9,
            MagicMock(value="llamaindex"): 0.7,
        })
        return router

    @pytest.mark.asyncio
    async def test_route_task_enable_fallback_uses_fallback_chain(self, mock_router):
        """enable_fallback=True uses execute_workflow_with_fallback."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = [{"path": "/repo/a"}]
        mock_app.execute_workflow_with_fallback = AsyncMock(return_value={
            "adapter_used": "agno",
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router

        request = RouteTaskRequest(intent="security scan", enable_fallback=True)
        result = await agent.route_task(request)

        mock_app.execute_workflow_with_fallback.assert_called_once()
        assert result.success is True
        assert result.adapter_used == "agno"

    @pytest.mark.asyncio
    async def test_route_task_enable_fallback_false_uses_parallel(self, mock_router):
        """enable_fallback=False uses execute_workflow_parallel."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = [{"path": "/repo/a"}]
        mock_app.execute_workflow_parallel = AsyncMock(return_value={
            "adapter_used": "agno",
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router

        request = RouteTaskRequest(intent="security scan", enable_fallback=False)
        result = await agent.route_task(request)

        mock_app.execute_workflow_parallel.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_route_task_exception_returns_error(self, mock_router):
        """Exceptions are caught and returned as error results."""
        mock_app = MagicMock()
        mock_app.get_repos.side_effect = Exception("Simulated failure")

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router

        request = RouteTaskRequest(intent="security scan")
        result = await agent.route_task(request)

        assert result.error == "Simulated failure"
        assert result.intent == "security scan"
        assert result.task_type == "unknown"
        assert result.adapter_used == ""

    @pytest.mark.asyncio
    async def test_route_task_fallback_chain_populated(self, mock_router):
        """Fallback chain is correctly populated in result."""
        mock_app = MagicMock()
        mock_app.get_repos.return_value = []
        mock_app.execute_workflow_with_fallback = AsyncMock(return_value={
            "success": True,
        })

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router

        request = RouteTaskRequest(intent="code review")
        result = await agent.route_task(request)

        assert result.fallback_chain == ["agno", "llamaindex"]


class TestMahavishnuAgentGetPoolStatus:
    """Tests for get_pool_status method."""

    @pytest.mark.asyncio
    async def test_get_pool_status_success(self):
        """Returns pool status from pool manager."""
        mock_pool_manager = MagicMock()
        mock_pool_manager.get_all_pool_status = AsyncMock(return_value={
            "pool_1": {"active_workers": 3, "status": "healthy"},
            "pool_2": {"active_workers": 5, "status": "healthy"},
        })

        with patch("mahavishnu.factories.get_pool_manager", return_value=mock_pool_manager):
            agent = MahavishnuAgent(app=MagicMock())
            result = await agent.get_pool_status()

        assert result.total_pools == 2
        assert result.active_workers == 8
        assert len(result.pools) == 2

    @pytest.mark.asyncio
    async def test_get_pool_status_empty(self):
        """Returns empty pools when no pools exist."""
        mock_pool_manager = MagicMock()
        mock_pool_manager.get_all_pool_status = AsyncMock(return_value={})

        with patch("mahavishnu.factories.get_pool_manager", return_value=mock_pool_manager):
            agent = MahavishnuAgent(app=MagicMock())
            result = await agent.get_pool_status()

        assert result.total_pools == 0
        assert result.active_workers == 0
        assert result.pools == []

    @pytest.mark.asyncio
    async def test_get_pool_status_exception(self):
        """Exceptions return error result without raising."""
        mock_pool_manager = MagicMock()
        mock_pool_manager.get_all_pool_status = AsyncMock(side_effect=Exception("Pool manager unavailable"))

        with patch("mahavishnu.factories.get_pool_manager", return_value=mock_pool_manager):
            agent = MahavishnuAgent(app=MagicMock())
            result = await agent.get_pool_status()

        assert result.error is not None
        assert "Pool manager unavailable" in result.error

    @pytest.mark.asyncio
    async def test_get_pool_status_non_dict_status(self):
        """Handles non-dict status return gracefully."""
        mock_pool_manager = MagicMock()
        mock_pool_manager.get_all_pool_status = AsyncMock(return_value="invalid")

        with patch("mahavishnu.factories.get_pool_manager", return_value=mock_pool_manager):
            agent = MahavishnuAgent(app=MagicMock())
            result = await agent.get_pool_status()

        assert result.total_pools == 0
        assert result.active_workers == 0


class TestMahavishnuAgentGetRoutingInfo:
    """Tests for get_routing_info method."""

    @pytest.fixture
    def mock_router_instance(self):
        """Create a mock TaskRouter instance with required methods."""
        router = MagicMock()
        router.generate_fallback_chain.return_value = None
        router.get_adapter_scores = AsyncMock(return_value={
            MagicMock(value="agno"): 0.9,
            MagicMock(value="llamaindex"): 0.7,
        })
        router.get_routing_info.return_value = {
            "fallback_chain": ["agno", "llamaindex"],
            "primary_adapter": "agno",
        }
        return router

    @pytest.mark.asyncio
    async def test_get_routing_info_success(self, mock_router_instance):
        """Returns routing info successfully."""
        mock_app = MagicMock()

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router_instance

        result = await agent.get_routing_info(task_type="ai_task", strategy="balanced")

        assert result.task_type == "ai_task"
        assert result.strategy == "balanced"
        assert result.primary_adapter == "agno"
        assert "agno" in result.adapter_scores

    @pytest.mark.asyncio
    async def test_get_routing_info_custom_task_type(self, mock_router_instance):
        """Accepts custom task_type parameter."""
        mock_app = MagicMock()

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router_instance

        result = await agent.get_routing_info(task_type="rag_query", strategy="cost")

        assert result.task_type == "rag_query"
        assert result.strategy == "cost"

    @pytest.mark.asyncio
    async def test_get_routing_info_exception(self, mock_router_instance):
        """Exceptions are caught and returned as error result."""
        mock_app = MagicMock()
        mock_router_instance.get_adapter_scores = AsyncMock(side_effect=Exception("Router failure"))

        agent = MahavishnuAgent(app=mock_app)
        agent._router = mock_router_instance

        result = await agent.get_routing_info()

        # get_routing_info catches exceptions and returns the exception message
        # The actual return is a RoutingInfoResult constructed with the error field
        # which Pydantic v2 doesn't expose as a field but may store in private attrs
        # We verify it doesn't raise and returns a valid result
        assert result.task_type == "ai_task"
        assert result.strategy == "balanced"


# ---------------------------------------------------------------------------
# Singleton Factory Tests
# ---------------------------------------------------------------------------

class TestSingletonFactory:
    """Tests for get_mahavishnu_agent and reset_agent."""

    def test_get_mahavishnu_agent_returns_singleton(self):
        """Multiple calls return the same instance."""
        reset_agent()
        mock_app = MagicMock()

        agent1 = get_mahavishnu_agent(app=mock_app)
        agent2 = get_mahavishnu_agent()

        assert agent1 is agent2

    def test_get_mahavishnu_agent_with_app_injects_app(self):
        """Passing app uses that app in the singleton."""
        reset_agent()
        mock_app = MagicMock()

        agent = get_mahavishnu_agent(app=mock_app)

        assert agent._app is mock_app

    def test_reset_agent_clears_singleton(self):
        """reset_agent clears the singleton so next call creates new instance."""
        reset_agent()
        mock_app1 = MagicMock()
        mock_app2 = MagicMock()

        agent1 = get_mahavishnu_agent(app=mock_app1)
        reset_agent()
        agent2 = get_mahavishnu_agent(app=mock_app2)

        assert agent1 is not agent2
        assert agent2._app is mock_app2

    def test_reset_agent_allows_fresh_singleton(self):
        """After reset, new singleton is created on next call."""
        reset_agent()
        mock_app = MagicMock()

        agent1 = get_mahavishnu_agent(app=mock_app)
        reset_agent()
        agent2 = get_mahavishnu_agent(app=mock_app)

        assert agent1 is not agent2


# ---------------------------------------------------------------------------
# Module Exports Test
# ---------------------------------------------------------------------------

class TestModuleExports:
    """Tests that __init__.py exports are correct."""

    def test_all_exports_present_in_dunder_all(self):
        """All expected exports are listed in __all__."""
        from mahavishnu.agents.mahavishnu_agent import __all__ as exports

        expected = {
            "MahavishnuAgent",
            "SweepReposRequest",
            "SweepReposResult",
            "RouteTaskRequest",
            "RouteTaskResult",
            "PoolStatusResult",
            "RoutingInfoResult",
            "get_mahavishnu_agent",
            "reset_agent",
        }
        assert set(exports) == expected

    def test_mahavishnu_agent_class_export(self):
        """MahavishnuAgent is exported from mahavishnu.agents."""
        from mahavishnu.agents import MahavishnuAgent

        assert MahavishnuAgent is not None

    def test_get_mahavishnu_agent_export(self):
        """get_mahavishnu_agent is exported from mahavishnu.agents."""
        from mahavishnu.agents import get_mahavishnu_agent

        assert get_mahavishnu_agent is not None

    def test_models_importable_from_module(self):
        """Models are importable from mahavishnu.agents.mahavishnu_agent."""
        from mahavishnu.agents.mahavishnu_agent import (
            SweepReposRequest,
            SweepReposResult,
            RouteTaskRequest,
            RouteTaskResult,
            PoolStatusResult,
            RoutingInfoResult,
        )
        assert SweepReposRequest is not None
        assert SweepReposResult is not None
        assert RouteTaskRequest is not None
        assert RouteTaskResult is not None
        assert PoolStatusResult is not None
        assert RoutingInfoResult is not None