"""Unit tests for the Mahavishnu orchestration agent module.

Covers Pydantic request/response models, the MahavishnuAgent public
API (sweep_repos, route_task, get_pool_status, get_routing_info),
and the module-level singleton helpers.

The agent depends on MahavishnuApp and TaskRouter, which are patched
at the import site so that the unit tests stay isolated from real
orchestration or LLM calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from mahavishnu.agents.mahavishnu_agent import (
    MahavishnuAgent,
    PoolStatusResult,
    RouteTaskRequest,
    SweepReposRequest,
    SweepReposResult,
    get_mahavishnu_agent,
    reset_agent,
)
from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.core.routing import RoutingStrategy

# ---------------------------------------------------------------------------
# Pydantic request / response model tests
# ---------------------------------------------------------------------------


class TestSweepReposRequest:
    """Validation of SweepReposRequest inputs."""

    def test_required_tag(self):
        with pytest.raises(ValidationError):
            SweepReposRequest()

    def test_defaults_applied(self):
        req = SweepReposRequest(tag="backend")
        assert req.tag == "backend"
        assert req.adapter == "agno"
        assert req.strategy == "balanced"
        assert req.dry_run is False

    def test_invalid_tag_pattern(self):
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="bad tag with spaces")

    def test_invalid_adapter_literal(self):
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="backend", adapter="not-a-real-adapter")

    def test_invalid_strategy_literal(self):
        with pytest.raises(ValidationError):
            SweepReposRequest(tag="backend", strategy="random-strategy")


class TestSweepReposResult:
    def test_defaults(self):
        result = SweepReposResult(tag="backend")
        assert result.workflow_id == ""
        assert result.repos_processed == 0
        assert result.adapter_used == ""
        assert result.success is False
        assert result.error is None
        assert result.results == {}


class TestRouteTaskRequest:
    def test_required_intent(self):
        with pytest.raises(ValidationError):
            RouteTaskRequest()

    def test_defaults_applied(self):
        req = RouteTaskRequest(intent="scan repos")
        assert req.strategy == "balanced"
        assert req.enable_fallback is True
        assert req.context is None

    def test_intent_max_length(self):
        with pytest.raises(ValidationError):
            RouteTaskRequest(intent="x" * 1001)


class TestPoolStatusResult:
    def test_defaults(self):
        result = PoolStatusResult()
        assert result.pools == []
        assert result.total_pools == 0
        assert result.active_workers == 0
        assert result.error is None


# ---------------------------------------------------------------------------
# Fixtures for the agent
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app() -> MagicMock:
    """Mock MahavishnuApp with sensible defaults for the agent to use."""
    app = MagicMock(name="MahavishnuApp")
    app.get_repos = MagicMock(return_value=["repo1", "repo2"])
    app.execute_workflow_with_routing = AsyncMock(
        return_value={
            "workflow_id": "wf-routing-1",
            "adapter_used": "prefect",
            "success": True,
        }
    )
    app.execute_workflow_parallel = AsyncMock(
        return_value={
            "workflow_id": "wf-parallel-1",
            "adapter_used": "agno",
            "success": True,
        }
    )
    app.execute_workflow_with_fallback = AsyncMock(
        return_value={
            "workflow_id": "wf-fallback-1",
            "adapter_used": "llamaindex",
            "success": True,
        }
    )
    return app


@pytest.fixture
def mock_router() -> MagicMock:
    """Mock TaskRouter with intent classification + adapter selection."""
    router = MagicMock(name="TaskRouter")
    router.classify_intent = MagicMock(return_value=TaskType.AI_TASK)
    router.select_adapter = AsyncMock(return_value=AdapterType.AGNO)
    router.generate_fallback_chain = MagicMock(return_value=[AdapterType.AGNO, AdapterType.PREFECT])
    router.get_adapter_scores = AsyncMock(
        return_value={AdapterType.AGNO: 0.9, AdapterType.PREFECT: 0.7}
    )
    router.get_routing_info = MagicMock(
        return_value={
            "fallback_chain": [AdapterType.AGNO.value],
            "primary_adapter": AdapterType.AGNO.value,
        }
    )
    return router


@pytest.fixture
def agent(mock_app: MagicMock, mock_router: MagicMock) -> MahavishnuAgent:
    """Construct a MahavishnuAgent with both dependencies replaced."""
    with patch("mahavishnu.agents.mahavishnu_agent.TaskRouter", return_value=mock_router):
        return MahavishnuAgent(app=mock_app)


# ---------------------------------------------------------------------------
# sweep_repos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSweepRepos:
    async def test_happy_path_uses_parallel_executor(
        self, agent: MahavishnuAgent, mock_app: MagicMock
    ):
        result = await agent.sweep_repos(SweepReposRequest(tag="backend"))
        assert result.success is True
        assert result.tag == "backend"
        assert result.repos_processed == 2
        # Default strategy=balanced and adapter=agno routes to the parallel
        # path on the wrapped app.
        mock_app.execute_workflow_parallel.assert_awaited_once()
        mock_app.execute_workflow_with_routing.assert_not_awaited()

    async def test_non_default_strategy_uses_routing_path(
        self, agent: MahavishnuAgent, mock_app: MagicMock
    ):
        result = await agent.sweep_repos(
            SweepReposRequest(tag="backend", strategy="cost", adapter="prefect")
        )
        assert result.success is True
        mock_app.execute_workflow_with_routing.assert_awaited_once()
        mock_app.execute_workflow_parallel.assert_not_awaited()

    async def test_no_repos_returns_error(self, agent: MahavishnuAgent, mock_app: MagicMock):
        mock_app.get_repos.return_value = []
        result = await agent.sweep_repos(SweepReposRequest(tag="missing"))
        assert result.success is False
        assert result.error is not None
        assert "missing" in result.error

    async def test_workflow_exception_surfaces_as_error(
        self, agent: MahavishnuAgent, mock_app: MagicMock
    ):
        mock_app.execute_workflow_parallel.side_effect = RuntimeError("kaboom")
        result = await agent.sweep_repos(SweepReposRequest(tag="backend"))
        assert result.success is False
        assert result.error == "kaboom"


# ---------------------------------------------------------------------------
# route_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRouteTask:
    async def test_happy_path_with_fallback(
        self, agent: MahavishnuAgent, mock_app: MagicMock, mock_router: MagicMock
    ):
        result = await agent.route_task(
            RouteTaskRequest(intent="scan backend repos", enable_fallback=True)
        )
        assert result.success is True
        assert result.task_type == TaskType.AI_TASK.value
        assert result.adapter_used
        mock_router.classify_intent.assert_called_once()
        mock_router.select_adapter.assert_awaited_once()
        mock_app.execute_workflow_with_fallback.assert_awaited_once()

    async def test_without_fallback_uses_parallel(
        self, agent: MahavishnuAgent, mock_app: MagicMock, mock_router: MagicMock
    ):
        result = await agent.route_task(
            RouteTaskRequest(intent="quick task", enable_fallback=False)
        )
        assert result.success is True
        mock_app.execute_workflow_parallel.assert_awaited_once()
        mock_app.execute_workflow_with_fallback.assert_not_awaited()

    async def test_router_failure_returns_error_result(
        self, agent: MahavishnuAgent, mock_router: MagicMock
    ):
        mock_router.select_adapter.side_effect = RuntimeError("routing unavailable")
        result = await agent.route_task(RouteTaskRequest(intent="test"))
        assert result.success is False
        assert result.error == "routing unavailable"
        assert result.task_type == "unknown"
        assert result.adapter_used == ""


# ---------------------------------------------------------------------------
# get_pool_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetPoolStatus:
    async def test_aggregates_pool_data(self, agent: MahavishnuAgent):
        pool_mgr = MagicMock()
        pool_mgr.get_all_pool_status = AsyncMock(
            return_value={
                "pool_a": {"active_workers": 3, "status": "healthy"},
                "pool_b": {"active_workers": 2, "status": "degraded"},
            }
        )
        with patch("mahavishnu.factories.get_pool_manager", return_value=pool_mgr):
            result = await agent.get_pool_status()
        assert result.total_pools == 2
        assert result.active_workers == 5
        assert result.error is None
        assert {p["pool_id"] for p in result.pools} == {"pool_a", "pool_b"}

    async def test_pool_manager_error_returns_graceful_result(self, agent: MahavishnuAgent):
        with patch(
            "mahavishnu.factories.get_pool_manager",
            side_effect=RuntimeError("manager offline"),
        ):
            result = await agent.get_pool_status()
        assert result.error == "manager offline"
        assert result.total_pools == 0
        assert result.pools == []


# ---------------------------------------------------------------------------
# get_routing_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetRoutingInfo:
    async def test_happy_path(self, agent: MahavishnuAgent, mock_router: MagicMock):
        result = await agent.get_routing_info(task_type="ai_task", strategy="balanced")
        assert result.task_type == "ai_task"
        assert result.strategy == "balanced"
        assert result.primary_adapter == AdapterType.AGNO.value
        mock_router.get_routing_info.assert_called_once_with(
            TaskType.AI_TASK, RoutingStrategy.BALANCED
        )

    async def test_invalid_strategy_falls_through_to_error(self, agent: MahavishnuAgent):
        # RoutingStrategy is an enum, so an unknown value raises ValueError.
        # The agent catches the exception and returns a RoutingInfoResult
        # with the bad strategy echoed back (Pydantic silently ignores the
        # non-declared `error` kwarg). The result still represents the
        # failure path, just by returning rather than raising.
        result = await agent.get_routing_info(strategy="not-a-real-strategy")
        assert result.task_type == "ai_task"
        assert result.strategy == "not-a-real-strategy"
        assert result.primary_adapter is None
        assert result.fallback_chain == []
        assert result.adapter_scores == {}


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_returns_same_instance(self, mock_app: MagicMock, mock_router: MagicMock):
        reset_agent()
        with patch("mahavishnu.agents.mahavishnu_agent.TaskRouter", return_value=mock_router):
            first = get_mahavishnu_agent(app=mock_app)
            second = get_mahavishnu_agent()
        assert first is second
        reset_agent()

    def test_reset_creates_new_instance(self, mock_app: MagicMock, mock_router: MagicMock):
        reset_agent()
        with patch("mahavishnu.agents.mahavishnu_agent.TaskRouter", return_value=mock_router):
            first = get_mahavishnu_agent(app=mock_app)
            reset_agent()
            second = get_mahavishnu_agent(app=mock_app)
        assert first is not second
        reset_agent()
