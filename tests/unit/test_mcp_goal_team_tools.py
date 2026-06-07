"""Unit tests for mahavishnu.mcp.tools.goal_team_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import (
    ErrorCode,
    FeatureDisabledError,
    GoalParsingError,
    GoalTeamError,
)
from mahavishnu.mcp.tools.goal_team_tools import register_goal_team_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _make_parsed_goal(
    intent: str = "coordinate",
    domain: str = "code",
    skills: list | None = None,
    confidence: float = 0.9,
    method: str = "pattern",
    raw_goal: str = "test goal",
):
    """Build a parsed-goal object with the attributes the tool reads."""
    parsed = MagicMock()
    parsed.intent = intent
    parsed.domain = domain
    parsed.skills = skills or ["code-review"]
    parsed.confidence = confidence
    parsed.metadata = {"method": method}
    parsed.raw_goal = raw_goal
    return parsed


def _make_team_config(name: str = "TestTeam", mode_value: str = "coordinate"):
    """Build a team config object with the attributes the tool reads."""
    member = MagicMock()
    member.name = "Agent1"
    member.role = "reviewer"
    member.model = "test-model"

    leader = MagicMock()
    leader.name = "Lead"
    leader.role = "leader"

    config = MagicMock()
    config.name = name
    config.description = "A test team"
    config.mode.value = mode_value
    config.members = [member]
    config.leader = leader
    return config


def _make_factory(parsed=None, team_config=None):
    """Build a mock GoalDrivenTeamFactory."""
    factory = MagicMock()
    factory.parse_goal = AsyncMock(return_value=parsed or _make_parsed_goal())
    factory.create_team_from_goal = AsyncMock(return_value=team_config or _make_team_config())
    return factory


def _make_agno_adapter(team_id: str = "team-1"):
    """Build a mock Agno adapter."""
    adapter = MagicMock()
    adapter.create_team = AsyncMock(return_value=team_id)

    run_result = MagicMock()
    run_result.success = True
    run_result.responses = []
    run_result.total_tokens = 100
    run_result.latency_ms = 250.0
    adapter.run_team = AsyncMock(return_value=run_result)
    return adapter


def _make_ws_server():
    """Build a mock WebSocket server with broadcast methods as AsyncMocks."""
    ws = MagicMock()
    ws.broadcast_team_error = AsyncMock()
    ws.broadcast_team_parsed = AsyncMock()
    ws.broadcast_team_created = AsyncMock()
    ws.broadcast_team_execution_started = AsyncMock()
    ws.broadcast_team_execution_completed = AsyncMock()
    return ws


@pytest.fixture
def feature_flags_enabled():
    """Patch all feature flags to enabled."""
    return patch(
        "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
        return_value=True,
    )


@pytest.fixture
def mock_mcp():
    """Build a mock FastMCP that captures tool functions."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    return mcp


@pytest.fixture
def default_modules():
    """Patch the dynamic imports that team_from_goal and parse_goal perform."""
    parsed = _make_parsed_goal()
    team_config = _make_team_config()
    factory = _make_factory(parsed, team_config)
    adapter = _make_agno_adapter()

    modules = {
        "factory_cls": MagicMock(return_value=factory),
        "factory": factory,
        "adapter": adapter,
        "parsed": parsed,
        "team_config": team_config,
    }
    return modules


@pytest.fixture
def registered_mcp(mock_mcp):
    """Register goal team tools on the mock MCP."""
    register_goal_team_tools(mock_mcp)
    return mock_mcp


# =============================================================================
# Tool Registration
# =============================================================================


class TestRegistration:
    """Tests for register_goal_team_tools."""

    def test_all_tools_registered(self, registered_mcp):
        """All 3 goal-team tools should be registered."""
        expected = {"team_from_goal", "parse_goal", "list_team_skills"}
        assert expected.issubset(set(registered_mcp._tools.keys()))


# =============================================================================
# list_team_skills
# =============================================================================


class TestListTeamSkills:
    """Tests for the list_team_skills tool."""

    async def test_returns_skills(self, registered_mcp):
        """Should return skills with role/tools/model/temperature."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["list_team_skills"]()
        assert result["success"] is True
        assert "skills" in result
        assert "count" in result
        # SKILL_MAPPING should have at least one skill
        assert result["count"] > 0

    async def test_feature_disabled(self, registered_mcp):
        """When feature flag is off, return success=False with empty skills."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=False,
        ):
            result = await registered_mcp._tools["list_team_skills"]()
        assert result["success"] is False
        assert result["skills"] == {}
        assert result["count"] == 0
        assert "disabled" in result["error"]["message"].lower()


# =============================================================================
# team_from_goal
# =============================================================================


class TestTeamFromGoal:
    """Tests for the team_from_goal tool."""

    async def test_feature_flag_disabled(self, registered_mcp):
        """When enabled feature flag is False, return error."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=False,
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="this is a long enough goal to pass validation"
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    async def test_goal_too_short(self, registered_mcp):
        """Goal under 10 chars after strip should raise GoalParsingError."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["team_from_goal"](goal="short")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_SHORT.value

    async def test_goal_too_long(self, registered_mcp):
        """Goal over 1000 chars should raise GoalParsingError."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["team_from_goal"](goal="x" * 1001)
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_LONG.value

    async def test_auto_run_without_task(self, registered_mcp):
        """auto_run=True with no task should return validation error."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation",
                auto_run=True,
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "task" in result["error"]["message"]

    async def test_invalid_mode(self, registered_mcp):
        """An invalid mode value should return a validation error."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation",
                mode="not-a-mode",
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "Invalid mode" in result["error"]["message"]

    async def test_successful_team_creation(self, registered_mcp, default_modules):
        """A valid call should create and return a team."""
        parsed = default_modules["parsed"]
        team_config = default_modules["team_config"]
        factory = default_modules["factory"]
        adapter = default_modules["adapter"]

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=adapter,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation",
            )
        assert result["success"] is True
        assert result["team_id"] == "team-1"
        assert result["config"]["name"] == team_config.name
        assert result["config"]["mode"] == "coordinate"
        assert result["parsed_goal"]["intent"] == parsed.intent

    async def test_successful_team_with_auto_run(self, registered_mcp, default_modules):
        """auto_run=True with a task should add run_result to response."""
        factory = default_modules["factory"]
        adapter = default_modules["adapter"]

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=adapter,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation",
                auto_run=True,
                task="do the work",
            )
        assert result["success"] is True
        assert "run_result" in result
        assert result["run_result"]["success"] is True
        assert result["run_result"]["total_tokens"] == 100
        adapter.run_team.assert_awaited_once()

    async def test_websocket_broadcasting(self, registered_mcp, default_modules):
        """When WebSocket is available, broadcasts should be sent."""
        ws = _make_ws_server()
        factory = default_modules["factory"]
        adapter = default_modules["adapter"]

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=ws,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=adapter,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation"
            )
        # broadcast_team_parsed, broadcast_team_created should have been called
        ws.broadcast_team_parsed.assert_awaited()
        ws.broadcast_team_created.assert_awaited()

    async def test_generic_exception_returns_internal_error(self, registered_mcp, default_modules):
        """An unexpected exception should be caught and returned as INTERNAL_ERROR."""
        factory = default_modules["factory"]
        factory.parse_goal.side_effect = RuntimeError("boom")

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=MagicMock(),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            result = await registered_mcp._tools["team_from_goal"](
                goal="a long enough goal to pass validation"
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
        assert "boom" in result["error"]["message"]


# =============================================================================
# parse_goal
# =============================================================================


class TestParseGoal:
    """Tests for the parse_goal tool."""

    async def test_feature_flag_disabled(self, registered_mcp):
        """When feature flag is off, return error."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=False,
        ):
            result = await registered_mcp._tools["parse_goal"](
                goal="a long enough goal to pass validation"
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    async def test_goal_too_short(self, registered_mcp):
        """Short goal should return GOAL_TOO_SHORT error."""
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await registered_mcp._tools["parse_goal"](goal="hi")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_SHORT.value

    async def test_successful_parse(self, registered_mcp, default_modules):
        """A valid call should return parsed info + suggested team."""
        factory = default_modules["factory"]
        parsed = default_modules["parsed"]
        team_config = default_modules["team_config"]

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            result = await registered_mcp._tools["parse_goal"](
                goal="a long enough goal to pass validation"
            )
        assert result["success"] is True
        assert result["parsed"]["intent"] == parsed.intent
        assert result["parsed"]["domain"] == parsed.domain
        assert result["suggested_team"]["name"] == team_config.name
        assert result["suggested_team"]["mode"] == "coordinate"
        assert result["suggested_team"]["has_leader"] is True

    async def test_parse_with_recommendation(self, registered_mcp, default_modules):
        """When learning system has a recommendation, it should be returned."""
        factory = default_modules["factory"]

        recommendation = MagicMock()
        recommendation.mode = "coordinate"
        recommendation.confidence = 0.95
        recommendation.success_rate = 0.9
        recommendation.sample_count = 10
        recommendation.reason = "most popular"
        # No model_dump -> uses dict branch
        del recommendation.model_dump

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
            patch("mahavishnu.core.team_learning.get_learning_engine") as mock_get_engine,
        ):
            mock_engine = MagicMock()
            mock_engine.get_mode_recommendation = MagicMock(return_value=recommendation)
            mock_get_engine.return_value = mock_engine
            result = await registered_mcp._tools["parse_goal"](
                goal="a long enough goal to pass validation"
            )
        assert result["success"] is True
        assert result["recommended_mode"] is not None
        assert result["recommended_mode"]["mode"] == "coordinate"

    async def test_parse_generic_exception(self, registered_mcp, default_modules):
        """An unexpected exception is caught and returns INTERNAL_ERROR."""
        factory = default_modules["factory"]
        factory.parse_goal.side_effect = RuntimeError("kaboom")

        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=None,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=factory,
            ),
        ):
            result = await registered_mcp._tools["parse_goal"](
                goal="a long enough goal to pass validation"
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value


# =============================================================================
# Error classes
# =============================================================================


class TestErrorClasses:
    """Tests for the exception classes used by these tools."""

    def test_feature_disabled_error_construction(self):
        """FeatureDisabledError can be constructed with a feature name."""
        err = FeatureDisabledError(feature_name="goal_teams")
        assert err.error_code == ErrorCode.FEATURE_DISABLED
        assert err.details["feature_name"] == "goal_teams"
        assert "goal_teams" in err.message

    def test_goal_parsing_error_short(self):
        """GoalParsingError for short goals carries the GOAL_TOO_SHORT code."""
        err = GoalParsingError(
            goal="hi",
            reason="too short",
            error_code=ErrorCode.GOAL_TOO_SHORT,
        )
        assert err.error_code == ErrorCode.GOAL_TOO_SHORT

    def test_goal_parsing_error_long(self):
        """GoalParsingError for long goals carries the GOAL_TOO_LONG code."""
        err = GoalParsingError(
            goal="x" * 1100,
            reason="too long",
            error_code=ErrorCode.GOAL_TOO_LONG,
        )
        assert err.error_code == ErrorCode.GOAL_TOO_LONG

    def test_goal_team_error(self):
        """GoalTeamError is the base for team-creation errors."""
        err = GoalTeamError(
            message="team failed",
            error_code=ErrorCode.INTERNAL_ERROR,
        )
        assert err.message == "team failed"
        assert err.error_code == ErrorCode.INTERNAL_ERROR
