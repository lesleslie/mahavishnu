"""Unit tests for Agno Adapter Phase 2 - Multi-Agent Teams.

These tests verify the team management functionality:
- Team configuration validation
- Team creation from config
- Different team modes
- Result aggregation
- AgentTeamManager lifecycle
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.config import (
    AgnoAdapterConfig,
    AgnoLLMConfig,
    LLMProvider,
)
from mahavishnu.core.errors import AgnoError, ErrorCode
from mahavishnu.engines.agno_teams.config import (
    MemberConfig,
    TeamConfig,
    TeamMode,
    TeamConfigFile,
    get_builtin_team_templates,
)
from mahavishnu.engines.agno_teams.manager import (
    AgentTeamManager,
    AgentRunResult,
    TeamRunResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def member_config() -> MemberConfig:
    """Create a basic member config for testing."""
    return MemberConfig(
        name="test_member",
        role="Test role",
        model="qwen2.5:7b",
        instructions="Test instructions for the member",
        tools=["search_code", "read_file"],
        temperature=0.7,
    )


@pytest.fixture
def leader_config() -> MemberConfig:
    """Create a leader member config for testing."""
    return MemberConfig(
        name="test_leader",
        role="Team leader",
        model="claude-sonnet-4-6",
        instructions="Coordinate the team and aggregate results",
    )


@pytest.fixture
def team_config(leader_config: MemberConfig, member_config: MemberConfig) -> TeamConfig:
    """Create a complete team config for testing."""
    return TeamConfig(
        name="test_team",
        description="Test team for unit tests",
        mode=TeamMode.COORDINATE,
        leader=leader_config,
        members=[member_config],
        memory_enabled=True,
        max_concurrent_runs=3,
        timeout_seconds=300,
    )


@pytest.fixture
def route_team_config(member_config: MemberConfig) -> TeamConfig:
    """Create a route mode team config."""
    return TeamConfig(
        name="route_team",
        mode=TeamMode.ROUTE,
        members=[member_config],
    )


@pytest.fixture
def mock_llm_factory() -> MagicMock:
    """Create a mock LLM provider factory."""
    factory = MagicMock()
    factory.config = AgnoLLMConfig(provider=LLMProvider.OLLAMA, model_id="qwen2.5:7b")
    factory._model_instance = None

    def create_model():
        mock_model = MagicMock()
        mock_model.name = "mock_model"
        return mock_model

    factory.create_model = create_model
    return factory


@pytest.fixture
def team_manager(mock_llm_factory: MagicMock) -> AgentTeamManager:
    """Create an AgentTeamManager for testing."""
    return AgentTeamManager(
        llm_factory=mock_llm_factory,
        mcp_tools=[],
        max_concurrent_agents=5,
    )


# ============================================================================
# MemberConfig Tests
# ============================================================================


class TestMemberConfig:
    """Tests for MemberConfig validation."""

    def test_valid_member_config(self, member_config: MemberConfig) -> None:
        """Test that a valid member config is created correctly."""
        assert member_config.name == "test_member"
        assert member_config.role == "Test role"
        assert member_config.model == "qwen2.5:7b"
        assert member_config.instructions == "Test instructions for the member"
        assert member_config.tools == ["search_code", "read_file"]
        assert member_config.temperature == 0.7
        assert member_config.max_tokens == 4096

    def test_default_values(self) -> None:
        """Test default values for member config."""
        config = MemberConfig(
            name="test",
            role="role",
            instructions="instructions",
        )
        assert config.model == "qwen2.5:7b"
        assert config.tools == []
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_name_validation(self) -> None:
        """Test name length validation."""
        # Too short
        with pytest.raises(ValueError):
            MemberConfig(name="", role="role", instructions="instructions")

        # Too long
        with pytest.raises(ValueError):
            MemberConfig(name="x" * 101, role="role", instructions="instructions")

    def test_temperature_bounds(self) -> None:
        """Test temperature validation."""
        # Valid
        MemberConfig(
            name="test",
            role="role",
            instructions="instructions",
            temperature=0.0,
        )
        MemberConfig(
            name="test",
            role="role",
            instructions="instructions",
            temperature=2.0,
        )

        # Invalid
        with pytest.raises(ValueError):
            MemberConfig(
                name="test",
                role="role",
                instructions="instructions",
                temperature=-0.1,
            )
        with pytest.raises(ValueError):
            MemberConfig(
                name="test",
                role="role",
                instructions="instructions",
                temperature=2.1,
            )

    def test_max_tokens_bounds(self) -> None:
        """Test max_tokens validation."""
        # Invalid
        with pytest.raises(ValueError):
            MemberConfig(
                name="test",
                role="role",
                instructions="instructions",
                max_tokens=0,
            )
        with pytest.raises(ValueError):
            MemberConfig(
                name="test",
                role="role",
                instructions="instructions",
                max_tokens=128001,
            )


# ============================================================================
# TeamConfig Tests
# ============================================================================


class TestTeamConfig:
    """Tests for TeamConfig validation."""

    def test_valid_team_config(self, team_config: TeamConfig) -> None:
        """Test that a valid team config is created correctly."""
        assert team_config.name == "test_team"
        assert team_config.mode == TeamMode.COORDINATE
        assert team_config.leader is not None
        assert len(team_config.members) == 1
        assert team_config.memory_enabled is True

    def test_coordinate_mode_requires_leader(self, member_config: MemberConfig) -> None:
        """Test that coordinate mode requires a leader."""
        with pytest.raises(ValueError, match="leader is required"):
            TeamConfig(
                name="no_leader_team",
                mode=TeamMode.COORDINATE,
                members=[member_config],
                leader=None,
            )

    def test_route_mode_no_leader_required(
        self, member_config: MemberConfig
    ) -> None:
        """Test that route mode doesn't require a leader."""
        config = TeamConfig(
            name="route_team",
            mode=TeamMode.ROUTE,
            members=[member_config],
            leader=None,
        )
        assert config.leader is None

    def test_unique_member_names(self, member_config: MemberConfig) -> None:
        """Test that member names must be unique."""
        duplicate_member = MemberConfig(
            name="test_member",  # Same name as fixture
            role="Another role",
            model="gpt-4o",
            instructions="Different instructions",
        )
        with pytest.raises(ValueError, match="Member names must be unique"):
            TeamConfig(
                name="duplicate_team",
                mode=TeamMode.ROUTE,
                members=[member_config, duplicate_member],
            )

    def test_get_all_members(self, team_config: TeamConfig) -> None:
        """Test get_all_members includes leader."""
        all_members = team_config.get_all_members()
        assert len(all_members) == 2  # leader + 1 member
        assert all_members[0].name == "test_leader"

    def test_get_member_by_name(self, team_config: TeamConfig) -> None:
        """Test get_member_by_name lookup."""
        member = team_config.get_member_by_name("test_member")
        assert member is not None
        assert member.name == "test_member"

        # Not found
        not_found = team_config.get_member_by_name("nonexistent")
        assert not_found is None


class TestTeamMode:
    """Tests for TeamMode enum."""

    def test_mode_values(self) -> None:
        """Test team mode values."""
        assert TeamMode.COORDINATE.value == "coordinate"
        assert TeamMode.ROUTE.value == "route"
        assert TeamMode.BROADCAST.value == "broadcast"
        assert TeamMode.COLLABORATE.value == "collaborate"


class TestTeamConfigFile:
    """Tests for TeamConfigFile YAML model."""

    def test_team_config_file(self, team_config: TeamConfig) -> None:
        """Test TeamConfigFile wrapper."""
        config_file = TeamConfigFile(team=team_config)
        assert config_file.team.name == "test_team"


class TestBuiltinTemplates:
    """Tests for built-in team templates."""

    def test_get_builtin_templates(self) -> None:
        """Test getting built-in templates."""
        templates = get_builtin_team_templates()
        assert "code_review" in templates
        assert "research" in templates

    def test_code_review_template_structure(self) -> None:
        """Test code review template has expected structure."""
        templates = get_builtin_team_templates()
        code_review = templates["code_review"]

        assert code_review["name"] == "code_review_team"
        assert code_review["mode"] == TeamMode.COORDINATE
        assert "leader" in code_review
        assert "members" in code_review
        # Built-in template has 2 members: security_analyst, quality_engineer
        assert len(code_review["members"]) >= 2


# ============================================================================
# AgentTeamManager Tests
# ============================================================================


class TestAgentTeamManager:
    """Tests for AgentTeamManager."""

    def test_manager_initialization(self, mock_llm_factory: MagicMock) -> None:
        """Test manager initialization."""
        manager = AgentTeamManager(
            llm_factory=mock_llm_factory,
            mcp_tools=[],
            max_concurrent_agents=5,
        )

        assert manager.llm_factory == mock_llm_factory
        assert manager.mcp_tools == []
        assert manager.max_concurrent_agents == 5
        assert len(manager._teams) == 0
        assert len(manager._agents) == 0

    @pytest.mark.asyncio
    async def test_create_team(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test creating a team from config."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(team_config)

            assert team_id is not None
            assert team_id.startswith("team_test_team_")
            assert team_id in team_manager._teams
            assert team_id in team_manager._team_configs

    @pytest.mark.asyncio
    async def test_create_team_from_yaml(
        self,
        team_manager: AgentTeamManager,
        tmp_path: Path,
    ) -> None:
        """Test creating a team from YAML file."""
        # Create a temporary YAML file
        yaml_content = """
team:
  name: yaml_test_team
  mode: coordinate
  leader:
    name: yaml_leader
    role: Leader
    model: qwen2.5:7b
    instructions: Lead the team
  members:
    - name: yaml_member
      role: Member
      model: qwen2.5:7b
      instructions: Help the team
"""
        yaml_path = tmp_path / "test_team.yaml"
        yaml_path.write_text(yaml_content)

        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team_from_yaml(str(yaml_path))

            assert team_id is not None
            assert "yaml_test_team" in team_id

    @pytest.mark.asyncio
    async def test_create_team_missing_file(
        self, team_manager: AgentTeamManager
    ) -> None:
        """Test error when YAML file doesn't exist."""
        with pytest.raises(AgnoError, match="Team config file not found"):
            await team_manager.create_team_from_yaml("/nonexistent/path.yaml")

    @pytest.mark.asyncio
    async def test_run_team(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test running a team task."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_agent_cls.return_value = mock_agent

            # Create mock team with arun method
            mock_team = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "Test team response"
            mock_response.run_id = "run_123"
            mock_team.arun = AsyncMock(return_value=mock_response)
            mock_team_cls.return_value = mock_team

            # Create team
            team_id = await team_manager.create_team(team_config)

            # Run team
            result = await team_manager.run_team(team_id, "Test task")

            assert result.success is True
            assert result.team_name == "test_team"
            assert result.run_id is not None
            assert result.mode == "coordinate"

    @pytest.mark.asyncio
    async def test_run_team_not_found(self, team_manager: AgentTeamManager) -> None:
        """Test error when team not found."""
        with pytest.raises(AgnoError, match="Team not found"):
            await team_manager.run_team("nonexistent_team", "Test task")

    @pytest.mark.asyncio
    async def test_get_team(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test getting a team by ID."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(team_config)

            team = await team_manager.get_team(team_id)
            assert team is not None

            # Not found
            not_found = await team_manager.get_team("nonexistent")
            assert not_found is None

    @pytest.mark.asyncio
    async def test_list_teams(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test listing teams."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            # Initially empty
            assert team_manager.list_teams() == []

            # Create team
            team_id = await team_manager.create_team(team_config)
            teams = team_manager.list_teams()
            assert len(teams) == 1
            assert team_id in teams

    @pytest.mark.asyncio
    async def test_delete_team(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test deleting a team."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(team_config)

            # Delete existing team
            deleted = await team_manager.delete_team(team_id)
            assert deleted is True
            assert team_id not in team_manager._teams

            # Delete non-existent team
            deleted = await team_manager.delete_team("nonexistent")
            assert deleted is False

    @pytest.mark.asyncio
    async def test_get_team_stats(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test getting team statistics."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(team_config)

            stats = team_manager.get_team_stats(team_id)
            assert stats["team_name"] == "test_team"
            assert stats["mode"] == "coordinate"
            assert stats["member_count"] == 1
            assert stats["total_runs"] == 0

    @pytest.mark.asyncio
    async def test_shutdown(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test shutting down the manager."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            # Create a team
            await team_manager.create_team(team_config)
            assert len(team_manager._teams) == 1

            # Shutdown
            await team_manager.shutdown()
            assert len(team_manager._teams) == 0
            assert len(team_manager._agents) == 0


# ============================================================================
# Result Dataclass Tests
# ============================================================================


class TestAgentRunResult:
    """Tests for AgentRunResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = AgentRunResult(
            agent_name="test",
            content="content",
            run_id="run_123",
        )
        assert result.success is True
        assert result.error is None
        assert result.tokens_used == 0
        assert result.latency_ms == 0.0
        assert result.metadata == {}

    def test_all_fields(self) -> None:
        """Test all fields."""
        result = AgentRunResult(
            agent_name="test",
            content="content",
            run_id="run_123",
            success=False,
            error="Error message",
            tokens_used=100,
            latency_ms=500.0,
            metadata={"key": "value"},
        )
        assert result.agent_name == "test"
        assert result.success is False
        assert result.error == "Error message"
        assert result.tokens_used == 100
        assert result.latency_ms == 500.0
        assert result.metadata == {"key": "value"}


class TestTeamRunResult:
    """Tests for TeamRunResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        result = TeamRunResult(
            team_name="team",
            mode="coordinate",
            responses=[],
            run_id="run_123",
        )
        assert result.success is True
        assert result.error is None
        assert result.total_tokens == 0
        assert result.latency_ms == 0.0
        assert result.metadata == {}

    def test_with_responses(self) -> None:
        """Test result with agent responses."""
        agent_result = AgentRunResult(
            agent_name="agent1",
            content="response",
            run_id="run_123",
            tokens_used=50,
        )
        result = TeamRunResult(
            team_name="team",
            mode="coordinate",
            responses=[agent_result],
            run_id="run_456",
            total_tokens=50,
        )
        assert len(result.responses) == 1
        assert result.total_tokens == 50


# ============================================================================
# Different Team Mode Tests
# ============================================================================


class TestTeamModes:
    """Tests for different team modes."""

    @pytest.mark.asyncio
    async def test_coordinate_mode(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test coordinate mode team creation."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(team_config)
            config = await team_manager.get_team_config(team_id)

            assert config.mode == TeamMode.COORDINATE
            assert config.leader is not None

    @pytest.mark.asyncio
    async def test_route_mode(
        self,
        team_manager: AgentTeamManager,
        route_team_config: TeamConfig,
    ) -> None:
        """Test route mode team creation."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(route_team_config)
            config = await team_manager.get_team_config(team_id)

            assert config.mode == TeamMode.ROUTE
            assert config.leader is None

    @pytest.mark.asyncio
    async def test_broadcast_mode(
        self,
        team_manager: AgentTeamManager,
        member_config: MemberConfig,
    ) -> None:
        """Test broadcast mode team creation."""
        config = TeamConfig(
            name="broadcast_team",
            mode=TeamMode.BROADCAST,
            members=[member_config],
        )

        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            team_id = await team_manager.create_team(config)
            team_config_result = await team_manager.get_team_config(team_id)

            assert team_config_result.mode == TeamMode.BROADCAST


# ============================================================================
# Integration-Style Tests
# ============================================================================


class TestTeamManagerIntegration:
    """Integration-style tests for team manager lifecycle."""

    @pytest.mark.asyncio
    async def test_full_team_lifecycle(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
    ) -> None:
        """Test full team lifecycle: create -> run -> delete."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent.name = "test_agent"
            mock_agent_cls.return_value = mock_agent

            # Create mock team with arun method
            mock_team = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "Team response"
            mock_response.run_id = "run_123"
            mock_team.arun = AsyncMock(return_value=mock_response)
            mock_team_cls.return_value = mock_team

            # Create team
            team_id = await team_manager.create_team(team_config)
            assert team_id in team_manager.list_teams()

            # Run team
            result = await team_manager.run_team(team_id, "Test task")
            assert result.success is True

            # Get stats
            stats = team_manager.get_team_stats(team_id)
            assert stats["total_runs"] == 1
            assert stats["successful_runs"] == 1

            # Delete team
            deleted = await team_manager.delete_team(team_id)
            assert deleted is True
            assert team_id not in team_manager.list_teams()

    @pytest.mark.asyncio
    async def test_multiple_teams(
        self,
        team_manager: AgentTeamManager,
        team_config: TeamConfig,
        route_team_config: TeamConfig,
    ) -> None:
        """Test managing multiple teams."""
        with patch("agno.agent.Agent") as mock_agent_cls, patch(
            "agno.team.Team"
        ) as mock_team_cls:
            mock_agent = MagicMock()
            mock_agent_cls.return_value = mock_agent

            mock_team = MagicMock()
            mock_team_cls.return_value = mock_team

            # Create multiple teams
            team_id1 = await team_manager.create_team(team_config)
            team_id2 = await team_manager.create_team(route_team_config)

            teams = team_manager.list_teams()
            assert len(teams) == 2
            assert team_id1 in teams
            assert team_id2 in teams

            # Delete all teams
            await team_manager.shutdown()
            assert len(team_manager.list_teams()) == 0
