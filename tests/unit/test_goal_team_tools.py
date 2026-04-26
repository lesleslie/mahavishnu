"""Unit tests for mahavishnu.mcp.tools.goal_team_tools.

Tests the three MCP tool functions registered by register_goal_team_tools:
- team_from_goal: Create and optionally run a team from a natural language goal
- parse_goal: Parse a goal to preview what team would be created
- list_team_skills: List all available skills for team creation

Strategy: Each test registers the tools on a fresh FastMCP instance with
appropriate mocks, then calls mcp.call_tool(name, args) and extracts
structured_content from the ToolResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from mahavishnu.core.errors import ErrorCode, GoalParsingError, GoalTeamError
from mahavishnu.core.goal_team_metrics import reset_goal_team_metrics
from mahavishnu.engines.agno_teams.config import TeamMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_fake_skill_config() -> dict[str, MagicMock]:
    """Return a fake SKILL_MAPPING dict for list_team_skills."""
    return {
        "security": MagicMock(
            role="Security specialist",
            tools=["search_code", "grep"],
            model="sonnet",
            temperature=0.3,
        ),
        "quality": MagicMock(
            role="Quality engineer",
            tools=["search_code", "read_file"],
            model="sonnet",
            temperature=0.5,
        ),
    }


class _FakeMode:
    """Minimal stand-in for TeamMode with a .value attribute."""

    def __init__(self, value: str = "coordinate") -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


@dataclass
class FakeMember:
    """Mimics MemberConfig used in tool output."""

    name: str = "agent_1"
    role: str = "Code reviewer"
    model: str = "sonnet"
    instructions: str = "Review the code thoroughly."
    tools: list[str] = field(default_factory=lambda: ["search_code", "read_file"])
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class FakeLeader:
    """Mimics leader MemberConfig."""

    name: str = "leader_1"
    role: str = "Coordinator"
    model: str = "sonnet"
    instructions: str = "Coordinate the review."
    tools: list[str] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.7


@dataclass
class FakeTeamConfig:
    """Mimics TeamConfig returned by GoalDrivenTeamFactory."""

    name: str = "test_team"
    description: str = "A test team"
    mode: Any = field(default_factory=lambda: TeamMode.COORDINATE)
    members: list[FakeMember] = field(default_factory=list)
    leader: FakeLeader | None = None
    memory_enabled: bool = True
    max_concurrent_runs: int = 5
    timeout_seconds: int = 300


@dataclass
class FakeParsedGoal:
    """Mimics ParsedGoal returned by GoalDrivenTeamFactory.parse_goal."""

    intent: str = "review"
    domain: str = "code"
    skills: list[str] = field(default_factory=lambda: ["security", "quality"])
    confidence: float = 0.85
    raw_goal: str = "Review the authentication module for security vulnerabilities"
    metadata: dict[str, Any] = field(default_factory=lambda: {"method": "pattern"})


@dataclass
class FakeRunResponse:
    """Mimics a single agent response inside a team run result."""

    agent_name: str = "agent_1"
    content: str | None = "I reviewed the code and found 3 issues."


@dataclass
class FakeRunResult:
    """Mimics the result from AgnoAdapter.run_team."""

    success: bool = True
    responses: list[FakeRunResponse] = field(default_factory=list)
    total_tokens: int = 150
    latency_ms: float = 500.0


def _register_tools_with_mocks(
    *,
    feature_enabled_side_effect: Any = True,
    ws_server: Any = None,
    metrics: Any = None,
    agno_adapter: Any = None,
    llm_factory: Any = None,
    context_initialized: bool = False,
) -> FastMCP:
    """Create a FastMCP, register goal_team_tools with all deps mocked, return mcp."""
    reset_goal_team_metrics()
    mcp = FastMCP("test-goal-team")

    patches = {
        "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled": feature_enabled_side_effect,
        "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server": ws_server,
        "mahavishnu.mcp.tools.goal_team_tools.get_goal_team_metrics": metrics or MagicMock(),
        "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized": context_initialized,
        "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory": llm_factory,
        "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter": agno_adapter,
    }

    context_managers = []
    for target, return_val in patches.items():
        if callable(return_val) and not isinstance(return_val, (bool, MagicMock, AsyncMock)):
            cm = patch(target, side_effect=return_val)
        else:
            cm = patch(target, return_value=return_val)
        cm.__enter__()
        context_managers.append(cm)

    try:
        from mahavishnu.mcp.tools.goal_team_tools import register_goal_team_tools

        register_goal_team_tools(mcp)
    finally:
        for cm in context_managers:
            cm.__exit__(None, None, None)

    return mcp


async def _call_tool(
    mcp: FastMCP,
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> Any:
    """Call a tool via mcp.call_tool and return the structured_content dict."""
    result = await mcp.call_tool(tool_name, args or {})
    # ToolResult has .structured_content which is the parsed return value
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    # Fallback: parse from text content
    if hasattr(result, "content") and result.content:
        import json

        return json.loads(result.content[0].text)
    return result


# ===========================================================================
# list_team_skills
# ===========================================================================


class TestListTeamSkills:
    """Tests for the list_team_skills MCP tool."""

    @pytest.mark.asyncio
    async def test_feature_disabled_master_switch(self):
        """When master switch off, returns success=False with FEATURE_DISABLED code."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name != "enabled",
        ):
            result = await _call_tool(mcp, "list_team_skills")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value
        assert result["count"] == 0
        assert result["skills"] == {}

    @pytest.mark.asyncio
    async def test_mcp_tools_disabled(self):
        """When mcp_tools_enabled is off, returns success=False."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name == "enabled",
        ):
            result = await _call_tool(mcp, "list_team_skills")
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    @pytest.mark.asyncio
    async def test_success(self):
        """Happy path: returns skills dict with correct structure."""
        fake_skills = _build_fake_skill_config()
        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch("mahavishnu.engines.goal_team_factory.SKILL_MAPPING", fake_skills),
        ):
            result = await _call_tool(mcp, "list_team_skills")

        assert result["success"] is True
        assert result["count"] == 2
        assert "security" in result["skills"]
        assert result["skills"]["security"]["role"] == "Security specialist"
        assert result["skills"]["security"]["tools"] == ["search_code", "grep"]
        assert result["skills"]["security"]["model"] == "sonnet"
        assert result["skills"]["security"]["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_empty_skill_mapping(self):
        """When SKILL_MAPPING is empty, returns count=0."""
        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch("mahavishnu.engines.goal_team_factory.SKILL_MAPPING", {}),
        ):
            result = await _call_tool(mcp, "list_team_skills")

        assert result["success"] is True
        assert result["count"] == 0
        assert result["skills"] == {}

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self):
        """Unexpected exceptions return internal error with skills stub."""
        # Create a dict-like object whose .items() raises
        class BrokenDict(dict):
            def items(self):
                raise RuntimeError("unexpected")

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch("mahavishnu.engines.goal_team_factory.SKILL_MAPPING", BrokenDict()),
        ):
            result = await _call_tool(mcp, "list_team_skills")

        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
        assert result["skills"] == {}
        assert result["count"] == 0


# ===========================================================================
# parse_goal
# ===========================================================================


class TestParseGoal:
    """Tests for the parse_goal MCP tool."""

    @pytest.mark.asyncio
    async def test_feature_disabled_master_switch(self):
        """Master switch off returns FEATURE_DISABLED."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name != "enabled",
        ):
            result = await _call_tool(mcp, "parse_goal", {"goal": "a valid goal text here"})
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    @pytest.mark.asyncio
    async def test_mcp_tools_disabled(self):
        """MCP tools disabled returns FEATURE_DISABLED."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name == "enabled",
        ):
            result = await _call_tool(mcp, "parse_goal", {"goal": "a valid goal text here"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_goal_too_short(self):
        """Goal shorter than 10 chars raises GoalParsingError caught by handler."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(mcp, "parse_goal", {"goal": "too short"})
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_SHORT.value

    @pytest.mark.asyncio
    async def test_goal_too_short_whitespace_only(self):
        """Goal that is whitespace under 10 chars is rejected."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(mcp, "parse_goal", {"goal": "   hi   "})
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_SHORT.value

    @pytest.mark.asyncio
    async def test_goal_exactly_10_chars(self):
        """Goal of exactly 10 chars is accepted."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(mcp, "parse_goal", {"goal": "0123456789"})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_success_basic(self):
        """Happy path returns parsed and suggested_team sections."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(
            members=[FakeMember(name="sec", role="Security", model="sonnet")],
            leader=FakeLeader(name="lead", role="Leader"),
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security vulnerabilities"},
            )

        assert result["success"] is True
        assert result["parsed"]["intent"] == "review"
        assert result["parsed"]["domain"] == "code"
        assert result["parsed"]["skills"] == ["security", "quality"]
        assert result["parsed"]["confidence"] == 0.85
        assert result["parsed"]["method"] == "pattern"
        assert result["suggested_team"]["name"] == "test_team"
        assert result["suggested_team"]["mode"] == "coordinate"
        assert result["suggested_team"]["member_count"] == 1
        assert result["suggested_team"]["has_leader"] is True
        assert result["recommended_mode"] is None

    @pytest.mark.asyncio
    async def test_success_no_leader(self):
        """Team with no leader has has_leader=False."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=None)

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security vulnerabilities"},
            )

        assert result["suggested_team"]["has_leader"] is False

    @pytest.mark.asyncio
    async def test_success_with_learning_recommendation(self):
        """When learning is enabled and returns a recommendation, includes it."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_recommendation = MagicMock()
        mock_recommendation.mode = "coordinate"
        mock_recommendation.confidence = 0.92
        mock_recommendation.model_dump.return_value = {
            "mode": "coordinate",
            "confidence": 0.92,
        }

        mock_engine = MagicMock()
        mock_engine.get_mode_recommendation.return_value = mock_recommendation

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "learning_system_enabled",
                ),
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
            patch(
                "mahavishnu.core.team_learning.get_learning_engine",
                return_value=mock_engine,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is True
        assert result["recommended_mode"] is not None
        assert result["recommended_mode"]["mode"] == "coordinate"

    @pytest.mark.asyncio
    async def test_learning_recommendation_none(self):
        """If learning returns None recommendation, recommended_mode stays None."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_engine = MagicMock()
        mock_engine.get_mode_recommendation.return_value = None

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "learning_system_enabled",
                ),
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
            patch(
                "mahavishnu.core.team_learning.get_learning_engine",
                return_value=mock_engine,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is True
        assert result["recommended_mode"] is None

    @pytest.mark.asyncio
    async def test_learning_exception_is_caught(self):
        """If learning engine throws, it is silently caught and recommended_mode is None."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "learning_system_enabled",
                ),
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
            patch(
                "mahavishnu.core.team_learning.get_learning_engine",
                side_effect=RuntimeError("db down"),
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is True
        assert result["recommended_mode"] is None

    @pytest.mark.asyncio
    async def test_prometheus_metrics_recorded(self):
        """When prometheus_metrics_enabled, metrics.record_goal_parsed is called."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_metrics = MagicMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "prometheus_metrics_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_goal_team_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is True
        mock_metrics.record_goal_parsed.assert_called_once_with(
            intent="review",
            domain="code",
            method="pattern",
            confidence=0.85,
        )

    @pytest.mark.asyncio
    async def test_websocket_broadcast_on_parse(self):
        """When websocket_broadcasts_enabled, broadcasts parsed event."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()])

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "websocket_broadcasts_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {
                    "goal": "Review the authentication module for security issues",
                    "user_id": "user42",
                },
            )

        assert result["success"] is True
        mock_ws.broadcast_team_parsed.assert_called_once()
        call_kwargs = mock_ws.broadcast_team_parsed.call_args[1]
        assert call_kwargs["goal"] == "Review the authentication module for security issues"
        assert call_kwargs["user_id"] == "user42"

    @pytest.mark.asyncio
    async def test_goal_parsing_error_caught(self):
        """If factory.parse_goal raises GoalParsingError, returns error dict."""
        mock_factory = AsyncMock()
        mock_factory.parse_goal.side_effect = GoalParsingError(
            goal="bad goal",
            reason="cannot parse",
            error_code=ErrorCode.GOAL_PARSING_FAILED,
        )

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_PARSING_FAILED.value

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self):
        """Unexpected exception returns INTERNAL_ERROR."""
        mock_factory = AsyncMock()
        mock_factory.parse_goal.side_effect = RuntimeError("boom")

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "parse_goal",
                {"goal": "Review the authentication module for security issues"},
            )

        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
        assert "boom" in result["error"]["message"]


# ===========================================================================
# team_from_goal
# ===========================================================================


class TestTeamFromGoal:
    """Tests for the team_from_goal MCP tool."""

    @pytest.mark.asyncio
    async def test_feature_disabled_master_switch(self):
        """Master switch off returns FEATURE_DISABLED."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name != "enabled",
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    @pytest.mark.asyncio
    async def test_mcp_tools_disabled(self):
        """MCP tools disabled returns FEATURE_DISABLED."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            side_effect=lambda name: name == "enabled",
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.FEATURE_DISABLED.value

    @pytest.mark.asyncio
    async def test_goal_too_short(self):
        """Goal shorter than 10 chars raises GoalParsingError."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(mcp, "team_from_goal", {"goal": "short"})
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_SHORT.value

    @pytest.mark.asyncio
    async def test_goal_too_long(self):
        """Goal exceeding 1000 chars raises GoalParsingError."""
        long_goal = "a" * 1001
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(mcp, "team_from_goal", {"goal": long_goal})
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TOO_LONG.value

    @pytest.mark.asyncio
    async def test_goal_exactly_1000_chars(self):
        """Goal of exactly 1000 chars is accepted (not too long)."""
        goal = "a" * 1000
        fake_parsed = FakeParsedGoal(raw_goal=goal)
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_123"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(mcp, "team_from_goal", {"goal": goal})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_auto_run_without_task(self):
        """auto_run=True without task returns validation error."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                },
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "task parameter is required" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_auto_run_false_with_no_task(self):
        """auto_run=False without task succeeds (task is optional)."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_456"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": False,
                },
            )
        assert result["success"] is True
        assert result["team_id"] == "team_456"
        assert "run_result" not in result

    @pytest.mark.asyncio
    async def test_success_basic(self):
        """Happy path: creates team, returns config and parsed_goal."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(
            members=[FakeMember(name="sec", role="Security analyst", model="sonnet")],
            leader=FakeLeader(name="coord", role="Coordinator"),
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_abc"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "name": "my_team",
                },
            )

        assert result["success"] is True
        assert result["team_id"] == "team_abc"
        assert result["config"]["name"] == "test_team"
        assert result["config"]["mode"] == "coordinate"
        assert len(result["config"]["members"]) == 1
        assert result["config"]["members"][0]["name"] == "sec"
        assert result["config"]["leader"]["name"] == "coord"
        assert result["parsed_goal"]["intent"] == "review"
        assert result["parsed_goal"]["skills"] == ["security", "quality"]

    @pytest.mark.asyncio
    async def test_success_no_leader(self):
        """Team with no leader has leader=None in result."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=None)

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_nolead"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True
        assert result["config"]["leader"] is None

    @pytest.mark.asyncio
    async def test_invalid_mode(self):
        """Invalid mode string returns validation error."""
        mcp = _register_tools_with_mocks()
        with patch(
            "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
            return_value=True,
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "mode": "invalid_mode",
                },
            )
        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR.value
        assert "Invalid mode" in result["error"]["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["coordinate", "route", "broadcast", "collaborate"])
    async def test_valid_modes(self, mode):
        """All four valid mode strings are accepted."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_mode"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "mode": mode,
                },
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mode_case_insensitive(self):
        """Mode matching is case-insensitive (upper-case accepted)."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_upper"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "mode": "COORDINATE",
                },
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_auto_run_with_task(self):
        """auto_run=True with task runs the team and includes run_result."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        fake_run = FakeRunResult(
            success=True,
            responses=[FakeRunResponse(agent_name="sec", content="All clear")],
            total_tokens=200,
            latency_ms=300.0,
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_run"
        mock_adapter.run_team.return_value = fake_run

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth module",
                },
            )

        assert result["success"] is True
        assert "run_result" in result
        assert result["run_result"]["success"] is True
        assert len(result["run_result"]["responses"]) == 1
        assert result["run_result"]["responses"][0]["agent_name"] == "sec"
        assert result["run_result"]["total_tokens"] == 200
        mock_adapter.run_team.assert_called_once_with("team_run", "Review auth module")

    @pytest.mark.asyncio
    async def test_auto_run_response_content_truncated(self):
        """Long response content is truncated to 500 chars."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        long_content = "x" * 600
        fake_run = FakeRunResult(
            success=True,
            responses=[FakeRunResponse(agent_name="sec", content=long_content)],
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_trunc"
        mock_adapter.run_team.return_value = fake_run

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth module",
                },
            )

        assert len(result["run_result"]["responses"][0]["content"]) == 500

    @pytest.mark.asyncio
    async def test_auto_run_null_content(self):
        """Response with None content is handled."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        fake_run = FakeRunResult(
            success=True,
            responses=[FakeRunResponse(agent_name="sec", content=None)],
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_null"
        mock_adapter.run_team.return_value = fake_run

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth module",
                },
            )

        assert result["run_result"]["responses"][0]["content"] is None

    @pytest.mark.asyncio
    async def test_prometheus_metrics_on_success(self):
        """When prometheus_metrics_enabled, metrics are recorded."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(
            members=[FakeMember(name="a"), FakeMember(name="b")],
            leader=FakeLeader(),
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_prom"

        mock_metrics = MagicMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "prometheus_metrics_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_goal_team_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True
        mock_metrics.record_goal_parsed.assert_called_once()
        mock_metrics.record_skills_usage.assert_called_once_with(["security", "quality"])
        mock_metrics.record_team_created.assert_called_once_with(
            mode="coordinate", skill_count=2,
        )
        mock_metrics.increment_active_teams.assert_called_once()
        mock_metrics.set_team_info.assert_called_once()

    @pytest.mark.asyncio
    async def test_learning_outcome_recorded_on_auto_run(self):
        """When learning_system_enabled and auto_run, outcome is recorded."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        fake_run = FakeRunResult(success=True)

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_learn"
        mock_adapter.run_team.return_value = fake_run

        mock_metrics = MagicMock()
        mock_learning_engine = MagicMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "learning_system_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_goal_team_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
            patch(
                "mahavishnu.core.team_learning.get_learning_engine",
                return_value=mock_learning_engine,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth",
                },
            )

        assert result["success"] is True
        mock_learning_engine.record_outcome.assert_called_once()
        mock_metrics.record_learning_outcome.assert_called_once()

    @pytest.mark.asyncio
    async def test_learning_exception_on_auto_run_does_not_fail(self):
        """If recording learning outcome fails, tool still succeeds."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        fake_run = FakeRunResult(success=True)

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_lexc"
        mock_adapter.run_team.return_value = fake_run

        mock_metrics = MagicMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "learning_system_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_goal_team_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
            patch(
                "mahavishnu.core.team_learning.get_learning_engine",
                side_effect=RuntimeError("learning db down"),
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth",
                },
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_websocket_broadcasts_team_created(self):
        """When websocket_broadcasts_enabled, broadcasts team_created event."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_ws"

        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "websocket_broadcasts_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "user_id": "user1",
                },
            )

        assert result["success"] is True
        mock_ws.broadcast_team_created.assert_called_once()
        call_kwargs = mock_ws.broadcast_team_created.call_args[1]
        assert call_kwargs["team_id"] == "team_ws"
        assert call_kwargs["user_id"] == "user1"

    @pytest.mark.asyncio
    async def test_websocket_broadcasts_execution_lifecycle(self):
        """When websocket_broadcasts_enabled and auto_run, broadcasts start + complete."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())
        fake_run = FakeRunResult(success=True)

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_exec"
        mock_adapter.run_team.return_value = fake_run

        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "websocket_broadcasts_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                    "task": "Review auth",
                    "user_id": "user_ws",
                },
            )

        assert result["success"] is True
        mock_ws.broadcast_team_execution_started.assert_called_once()
        mock_ws.broadcast_team_execution_completed.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_error_broadcast_on_goal_too_short(self):
        """Goal too short broadcasts error via websocket when ws_server present.

        Note: The source code broadcasts the error twice for GoalParsingError:
        once at the raise site (line 98) and once in the except handler (line 383).
        This is a known double-broadcast issue in the source code.
        """
        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "short"},
            )

        assert result["success"] is False
        # Double broadcast: once at raise site, once in except GoalParsingError handler
        assert mock_ws.broadcast_team_error.call_count == 2
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["error_code"] == ErrorCode.GOAL_TOO_SHORT.value

    @pytest.mark.asyncio
    async def test_websocket_error_broadcast_on_goal_too_long(self):
        """Goal too long broadcasts error via websocket.

        Note: The source code broadcasts the error twice for GoalParsingError:
        once at the raise site (line 115) and once in the except handler (line 383).
        This is a known double-broadcast issue in the source code.
        """
        mock_ws = AsyncMock()
        long_goal = "a" * 1001

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": long_goal},
            )

        assert result["success"] is False
        # Double broadcast: once at raise site, once in except GoalParsingError handler
        assert mock_ws.broadcast_team_error.call_count == 2
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["error_code"] == ErrorCode.GOAL_TOO_LONG.value

    @pytest.mark.asyncio
    async def test_websocket_error_broadcast_on_auto_run_no_task(self):
        """auto_run without task broadcasts error via websocket."""
        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "auto_run": True,
                },
            )

        assert result["success"] is False
        mock_ws.broadcast_team_error.assert_called_once()
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["error_code"] == ErrorCode.VALIDATION_ERROR.value

    @pytest.mark.asyncio
    async def test_websocket_error_broadcast_on_invalid_mode(self):
        """Invalid mode broadcasts error via websocket."""
        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "mode": "bad_mode",
                },
            )

        assert result["success"] is False
        mock_ws.broadcast_team_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_goal_team_error_caught(self):
        """GoalTeamError from adapter is caught and returned."""
        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = FakeParsedGoal()
        mock_factory.create_team_from_goal.side_effect = GoalTeamError(
            message="Team creation failed",
            error_code=ErrorCode.GOAL_TEAM_CREATION_FAILED,
        )

        mock_adapter = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.GOAL_TEAM_CREATION_FAILED.value

    @pytest.mark.asyncio
    async def test_generic_exception_caught(self):
        """Unexpected exception returns INTERNAL_ERROR."""
        mock_factory = AsyncMock()
        mock_factory.parse_goal.side_effect = RuntimeError("unexpected crash")

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is False
        assert result["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
        assert "unexpected crash" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_generic_error_broadcasts_via_websocket(self):
        """Generic exceptions broadcast error via websocket."""
        mock_ws = AsyncMock()
        mock_factory = AsyncMock()
        mock_factory.parse_goal.side_effect = RuntimeError("boom")

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is False
        mock_ws.broadcast_team_error.assert_called_once()
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["error_code"] == ErrorCode.INTERNAL_ERROR.value

    @pytest.mark.asyncio
    async def test_llm_factory_fallback_disabled(self):
        """When llm_fallback_enabled=False, factory is created with llm_factory=None."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_llm"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ) as mock_factory_cls,
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True
        mock_factory_cls.assert_called_once_with(llm_factory=None)

    @pytest.mark.asyncio
    async def test_llm_factory_fallback_enabled(self):
        """When llm_fallback_enabled=True, factory gets the LLM factory."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_llm2"

        mock_llm = MagicMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                side_effect=lambda name: name in (
                    "enabled", "mcp_tools_enabled", "llm_fallback_enabled",
                ),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                return_value=mock_llm,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ) as mock_factory_cls,
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True
        mock_factory_cls.assert_called_once_with(llm_factory=mock_llm)

    @pytest.mark.asyncio
    async def test_context_not_initialized_uses_suppressed_llm(self):
        """When context not initialized, LLM factory is fetched with suppress."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_ctx"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_llm_factory",
                side_effect=RuntimeError("not initialized"),
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_context_initialized",
                return_value=False,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            # Should not raise despite LLM factory failure
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_name_parameter_forwarded(self):
        """Name parameter is forwarded to create_team_from_goal."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(members=[FakeMember()], leader=FakeLeader())

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_named"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {
                    "goal": "Build a REST API endpoint for user management",
                    "name": "custom_name",
                },
            )

        assert result["success"] is True
        mock_factory.create_team_from_goal.assert_called_once()
        call_kwargs = mock_factory.create_team_from_goal.call_args[1]
        assert call_kwargs["name"] == "custom_name"

    @pytest.mark.asyncio
    async def test_user_id_forwarded_to_error_broadcasts(self):
        """user_id is forwarded to WebSocket error broadcasts."""
        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "short", "user_id": "alice"},
            )

        assert result["success"] is False
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_multiple_members_in_result(self):
        """Multiple team members are all included in result."""
        fake_parsed = FakeParsedGoal()
        fake_team = FakeTeamConfig(
            members=[
                FakeMember(name="sec", role="Security", model="sonnet"),
                FakeMember(name="qual", role="Quality", model="haiku"),
                FakeMember(name="perf", role="Performance", model="sonnet"),
            ],
            leader=FakeLeader(name="coord", role="Coordinator"),
        )

        mock_factory = AsyncMock()
        mock_factory.parse_goal.return_value = fake_parsed
        mock_factory.create_team_from_goal.return_value = fake_team

        mock_adapter = AsyncMock()
        mock_adapter.create_team.return_value = "team_multi"

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter",
                return_value=mock_adapter,
            ),
            patch(
                "mahavishnu.engines.goal_team_factory.GoalDrivenTeamFactory",
                return_value=mock_factory,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "Build a REST API endpoint for user management"},
            )

        assert result["success"] is True
        assert len(result["config"]["members"]) == 3
        names = [m["name"] for m in result["config"]["members"]]
        assert names == ["sec", "qual", "perf"]

    @pytest.mark.asyncio
    async def test_user_id_none_default(self):
        """user_id defaults to None when not provided."""
        mock_ws = AsyncMock()

        mcp = _register_tools_with_mocks()
        with (
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.is_feature_enabled",
                return_value=True,
            ),
            patch(
                "mahavishnu.mcp.tools.goal_team_tools.get_websocket_server",
                return_value=mock_ws,
            ),
        ):
            result = await _call_tool(
                mcp, "team_from_goal",
                {"goal": "short"},
            )

        assert result["success"] is False
        call_kwargs = mock_ws.broadcast_team_error.call_args[1]
        assert call_kwargs["user_id"] is None


# ===========================================================================
# Registration
# ===========================================================================


class TestRegistration:
    """Tests for the register_goal_team_tools function itself."""

    @pytest.mark.asyncio
    async def test_registers_three_tools(self):
        """register_goal_team_tools registers exactly 3 tools."""
        mcp = _register_tools_with_mocks()
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        assert "team_from_goal" in tool_names
        assert "parse_goal" in tool_names
        assert "list_team_skills" in tool_names
        assert len(tool_names) == 3

    @pytest.mark.asyncio
    async def test_tools_are_async(self):
        """All registered tools are async callables."""
        import asyncio

        mcp = _register_tools_with_mocks()
        tools = await mcp.list_tools()
        for t in tools:
            assert asyncio.iscoroutinefunction(t.fn), f"{t.name} is not async"
