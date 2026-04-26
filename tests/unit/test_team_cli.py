"""Comprehensive unit tests for the team CLI module.

Tests cover all CLI commands registered on the team sub-app,
mocking GoalDrivenTeamFactory, feature flags, and learning engine
to avoid filesystem access and external dependencies.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.core.errors import GoalParsingError, GoalTeamError
from mahavishnu.engines.agno_teams.config import MemberConfig, TeamConfig, TeamMode
from mahavishnu.engines.goal_team_factory import ParsedGoal, SkillConfig

runner = CliRunner()

# Rich renders table-cell overflow as the Unicode ellipsis character.
# Source code uses ASCII "..." for string truncation, but Rich tables
# clip cells and show their own ellipsis (U+2026).
ELLIPSIS = "…"

# ASCII three dots -- used by source code string concatenation (e.g. "..." )
ASCII_ELLIPSIS = "..."

# Sentinel to distinguish "caller explicitly passed None" from "caller used default"
_UNSET = object()


# ---------------------------------------------------------------------------
# Fixtures: mock data helpers
# ---------------------------------------------------------------------------


def _make_parsed_goal(
    intent: str = "review",
    domain: str = "security",
    skills: list[str] | None = None,
    confidence: float = 0.85,
    raw_goal: str = "Review code for security vulnerabilities",
    metadata: dict | None = None,
) -> ParsedGoal:
    """Create a ParsedGoal instance for testing."""
    return ParsedGoal(
        intent=intent,
        domain=domain,
        skills=skills if skills is not None else ["security"],
        confidence=confidence,
        raw_goal=raw_goal,
        metadata=metadata if metadata is not None else {"method": "pattern"},
    )


def _make_member(
    name: str = "analyst",
    role: str = "Security analyst",
    model: str = "sonnet",
    tools: list[str] | None = None,
) -> MemberConfig:
    """Create a MemberConfig instance for testing."""
    return MemberConfig(
        name=name,
        role=role,
        model=model,
        instructions=f"Instructions for {name}",
        tools=tools if tools is not None else [],
    )


def _make_team_config(
    name: str = "review_team",
    description: str = "A team for reviewing code",
    mode: TeamMode = TeamMode.COORDINATE,
    leader: MemberConfig | None = _UNSET,
    members: list[MemberConfig] | None = None,
) -> TeamConfig:
    """Create a TeamConfig instance for testing.

    Uses a sentinel so that ``leader=None`` means "no leader" rather than
    "use the default leader".
    """
    if leader is _UNSET:
        leader = _make_member(name="coordinator", role="Coordinator")
    if members is None:
        members = [_make_member(name="analyst")]
    return TeamConfig(
        name=name,
        description=description,
        mode=mode,
        leader=leader,
        members=members,
    )


def _make_async_factory(
    parsed: ParsedGoal | None = None,
    config: TeamConfig | None = None,
    parse_error: Exception | None = None,
    create_error: Exception | None = None,
) -> MagicMock:
    """Create a mock factory with async methods pre-configured."""
    factory = MagicMock()
    if parse_error:
        factory.parse_goal = AsyncMock(side_effect=parse_error)
    else:
        factory.parse_goal = AsyncMock(
            return_value=parsed if parsed is not None else _make_parsed_goal(),
        )
    if create_error:
        factory.create_team_from_goal = AsyncMock(side_effect=create_error)
    else:
        factory.create_team_from_goal = AsyncMock(
            return_value=config if config is not None else _make_team_config(),
        )
    return factory


# ---------------------------------------------------------------------------
# Helper: build a parent Typer app with team sub-app attached
# ---------------------------------------------------------------------------


def _make_app() -> typer.Typer:
    """Create a parent Typer app with team commands registered."""
    app = typer.Typer()
    from mahavishnu.cli.team_cli import add_team_commands

    add_team_commands(app)
    return app


# ---------------------------------------------------------------------------
# Feature flag patches
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_feature_flags():
    """Enable all feature flags by default for every test."""
    with (
        patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True),
        patch("mahavishnu.core.feature_flags.is_feature_enabled", return_value=True),
    ):
        yield


# ===========================================================================
# add_team_commands
# ===========================================================================


class TestAddTeamCommands:
    """Tests for add_team_commands()."""

    def test_registers_team_sub_app(self):
        """add_team_commands should attach a 'team' sub-app."""
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "team" in registered_names

    def test_team_app_is_typer_instance(self):
        """The registered team app should be a Typer instance."""
        from mahavishnu.cli.team_cli import app as team_app

        assert isinstance(team_app, typer.Typer)


# ===========================================================================
# _check_feature_flags
# ===========================================================================


class TestCheckFeatureFlags:
    """Tests for _check_feature_flags() gate."""

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", side_effect=lambda f: f != "enabled")
    def test_master_switch_disabled(self, mock_flags):
        """When master switch is disabled, commands should exit with code 1."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 1
        assert "disabled" in result.output.lower()

    @patch(
        "mahavishnu.cli.team_cli.is_feature_enabled",
        side_effect=lambda f: f != "cli_commands_enabled",
    )
    def test_cli_commands_disabled(self, mock_flags):
        """When cli_commands_enabled is off, commands should exit with code 1."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 1
        assert "CLI commands are disabled" in result.output


# ===========================================================================
# create-team command
# ===========================================================================


class TestCreateTeam:
    """Tests for the 'create' command."""

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_basic(self, mock_get_factory):
        """Basic team creation should succeed."""
        parsed = _make_parsed_goal()
        config = _make_team_config()
        mock_get_factory.return_value = _make_async_factory(parsed, config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code for security vulnerabilities"],
        )
        assert result.exit_code == 0
        assert "Team created successfully" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_with_name_and_mode(self, mock_get_factory):
        """Create team with custom name and mode."""
        config = _make_team_config(name="perf_team", mode=TeamMode.ROUTE)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            [
                "team",
                "create",
                "--goal", "Analyze performance",
                "--name", "perf_team",
                "--mode", "route",
            ],
        )
        assert result.exit_code == 0
        assert "Team created successfully" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_with_short_flags(self, mock_get_factory):
        """Create team using short flags (-g, -n, -m, -v)."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "-g", "Review code", "-n", "my_team", "-m", "coordinate", "-v"],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_invalid_mode(self, mock_get_factory):
        """Invalid mode should produce an error."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code", "--mode", "invalid_mode"],
        )
        assert result.exit_code == 1
        assert "Invalid mode" in result.output
        assert "invalid_mode" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_dry_run(self, mock_get_factory):
        """Dry run should show config but not store team."""
        config = _make_team_config(description="A" * 150)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert "To create this team" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_dry_run_verbose(self, mock_get_factory):
        """Dry run with verbose should show member details."""
        member = _make_member(name="analyst", tools=["search_code", "read_file"])
        leader = _make_member(name="coordinator", role="Lead coordinator")
        config = _make_team_config(leader=leader, members=[member])
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code", "--dry-run", "--verbose"],
        )
        assert result.exit_code == 0
        assert "coordinator" in result.output
        assert "analyst" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_run_without_task(self, mock_get_factory):
        """--run without --task should warn."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code", "--run"],
        )
        assert result.exit_code == 0
        assert "requires --task" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_run_with_task(self, mock_get_factory):
        """--run with --task should initiate execution."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            [
                "team",
                "create",
                "--goal", "Review code",
                "--run",
                "--task", "Fix the login bug",
            ],
        )
        assert result.exit_code == 0
        assert "Executing task" in result.output
        assert "Fix the login bug" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_goal_parsing_error(self, mock_get_factory):
        """GoalParsingError should be handled gracefully."""
        error = GoalParsingError(goal="x", reason="Goal too short")
        mock_get_factory.return_value = _make_async_factory(parse_error=error)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "x"],
        )
        assert result.exit_code == 1
        assert "Goal parsing error" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_goal_team_error(self, mock_get_factory):
        """GoalTeamError should be handled gracefully."""
        error = GoalTeamError("Team creation failed")
        mock_get_factory.return_value = _make_async_factory(create_error=error)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code"],
        )
        assert result.exit_code == 1
        assert "Team creation error" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_unexpected_error(self, mock_get_factory):
        """Unexpected errors should be caught and displayed."""
        mock_get_factory.return_value = _make_async_factory(
            parse_error=RuntimeError("something broke"),
        )

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code"],
        )
        assert result.exit_code == 1
        assert "Unexpected error" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_verbose_shows_members(self, mock_get_factory):
        """Verbose output should show member details."""
        member = _make_member(name="tester", tools=["run_tests"])
        config = _make_team_config(members=[member])
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Write tests", "--verbose"],
        )
        assert result.exit_code == 0
        assert "tester" in result.output
        assert "run_tests" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_description_truncation(self, mock_get_factory):
        """Long descriptions should be truncated in the display table."""
        config = _make_team_config(description="A" * 200)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code"],
        )
        assert result.exit_code == 0
        # Rich table cell overflow renders truncation as Unicode ellipsis
        assert ELLIPSIS in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_no_leader(self, mock_get_factory):
        """Team config without leader should still display correctly."""
        config = _make_team_config(mode=TeamMode.ROUTE, leader=None)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Route task", "--mode", "route"],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_dry_run_yaml_output(self, mock_get_factory):
        """Dry run should produce YAML-like config output."""
        member = _make_member(name="dev", tools=["write_file", "search_code"])
        leader = _make_member(name="lead", role="Team lead")
        config = _make_team_config(
            name="yaml_test",
            description="Testing YAML output",
            leader=leader,
            members=[member],
        )
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Build feature", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "team:" in result.output
        assert "name: yaml_test" in result.output
        assert "description: Testing YAML output" in result.output
        assert "mode: coordinate" in result.output
        assert "leader:" in result.output
        assert "name: lead" in result.output
        assert "members:" in result.output
        assert "name: dev" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_dry_run_yaml_no_tools(self, mock_get_factory):
        """Dry run YAML should not show tools line when member has no tools."""
        member = _make_member(name="dev", tools=[])
        leader = _make_member(name="lead")
        config = _make_team_config(leader=leader, members=[member])
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Simple task", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "tools:" not in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_stores_in_active_teams(self, mock_get_factory):
        """Created teams should be stored in _active_teams."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code"],
        )
        assert result.exit_code == 0
        assert "team_1" in result.output
        assert len(team_cli_mod._active_teams) == 1

        team_cli_mod._active_teams.clear()

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_valid_modes_listed_on_error(self, mock_get_factory):
        """Invalid mode error should list all valid modes."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Test", "--mode", "bogus"],
        )
        assert result.exit_code == 1
        for mode in TeamMode:
            assert mode.value in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_verbose_shows_leader(self, mock_get_factory):
        """Verbose output should show leader details when present."""
        leader = _make_member(name="lead", role="Team lead", model="opus")
        member = _make_member(name="worker")
        config = _make_team_config(leader=leader, members=[member])
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code", "--verbose"],
        )
        assert result.exit_code == 0
        assert "Leader:" in result.output
        assert "lead" in result.output
        assert "Team lead" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_verbose_no_tools_member(self, mock_get_factory):
        """Verbose output should not crash for members without tools."""
        member = _make_member(name="simple_worker", tools=[])
        config = _make_team_config(members=[member])
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Simple task", "--verbose"],
        )
        assert result.exit_code == 0
        assert "simple_worker" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_missing_goal_option(self, mock_get_factory):
        """Missing required --goal option should show help/error."""
        app = _make_app()
        result = runner.invoke(app, ["team", "create"])
        assert result.exit_code != 0

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_create_team_shows_team_id(self, mock_get_factory):
        """Created team should display its team ID."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Review code"],
        )
        assert result.exit_code == 0
        assert "Team ID:" in result.output
        assert "team_1" in result.output

        team_cli_mod._active_teams.clear()


# ===========================================================================
# parse command
# ===========================================================================


class TestParseGoal:
    """Tests for the 'parse' command."""

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_basic(self, mock_get_factory):
        """Basic goal parsing should display parsed info."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Review code for security issues"],
        )
        assert result.exit_code == 0
        assert "Parsed Goal" in result.output
        assert "review" in result.output
        assert "security" in result.output
        assert "85%" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_verbose(self, mock_get_factory):
        """Verbose parse should show team preview and analysis details."""
        parsed = _make_parsed_goal(
            raw_goal="Analyze performance bottlenecks",
            metadata={"method": "pattern", "patterns_matched": ["analyze"]},
        )
        config = _make_team_config()
        mock_get_factory.return_value = _make_async_factory(parsed, config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Analyze performance bottlenecks", "--verbose"],
        )
        assert result.exit_code == 0
        assert "Preview team configuration" in result.output
        assert "Analysis Details" in result.output
        assert "Raw goal:" in result.output
        assert "Metadata:" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_empty_skills(self, mock_get_factory):
        """Parse should handle empty skills list."""
        parsed = _make_parsed_goal(skills=[])
        mock_get_factory.return_value = _make_async_factory(parsed=parsed)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Do something vague"],
        )
        assert result.exit_code == 0
        assert "none" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_error(self, mock_get_factory):
        """Parse errors should be caught and displayed."""
        mock_get_factory.return_value = _make_async_factory(
            parse_error=Exception("parse failed"),
        )

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Do something"],
        )
        assert result.exit_code == 1
        assert "Error parsing goal" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_with_short_verbose_flag(self, mock_get_factory):
        """Short -v flag should work for verbose."""
        mock_get_factory.return_value = _make_async_factory()

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Review code", "-v"],
        )
        assert result.exit_code == 0
        assert "Preview team configuration" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_shows_method(self, mock_get_factory):
        """Parse should display the method from metadata."""
        parsed = _make_parsed_goal(metadata={"method": "llm_fallback"})
        mock_get_factory.return_value = _make_async_factory(parsed=parsed)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "parse", "Complex goal"],
        )
        assert result.exit_code == 0
        assert "llm_fallback" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_parse_goal_missing_argument(self, mock_get_factory):
        """Missing required goal argument should show help/error."""
        app = _make_app()
        result = runner.invoke(app, ["team", "parse"])
        assert result.exit_code != 0


# ===========================================================================
# skills command
# ===========================================================================


class TestListSkills:
    """Tests for the 'skills' command."""

    def test_list_skills_basic(self):
        """Skills command should list available skills."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 0
        assert "Available Skills" in result.output
        assert "security" in result.output
        assert "Total skills:" in result.output

    def test_list_skills_verbose(self):
        """Verbose skills should show detailed configurations."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills", "--verbose"])
        assert result.exit_code == 0
        assert "Detailed Skill Configurations" in result.output
        assert "Temperature:" in result.output
        assert "Instructions:" in result.output

    def test_list_skills_shows_tools_truncation(self):
        """Skills with more than 3 tools should show '+N more'."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 0
        assert "+1 more" in result.output

    def test_list_skills_role_truncation(self):
        """Roles exceeding 40 chars should be truncated with ASCII '...'."""
        # Default SKILL_MAPPING roles are all under 40 chars, so we patch
        # in a custom mapping with a long role to exercise the truncation.
        custom_mapping = {
            "testing": SkillConfig(
                role="A" * 60,
                instructions="Short instructions.",
                tools=["run_tests"],
                model="sonnet",
                temperature=0.6,
            ),
        }
        with patch("mahavishnu.cli.team_cli.SKILL_MAPPING", custom_mapping):
            app = _make_app()
            result = runner.invoke(app, ["team", "skills"])
            assert result.exit_code == 0
            # Source truncates role at 40 chars and appends ASCII "..."
            assert ASCII_ELLIPSIS in result.output

    def test_list_skills_verbose_instructions_truncation(self):
        """Verbose mode should truncate instructions to first 5 lines."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills", "--verbose"])
        assert result.exit_code == 0
        # Source uses ASCII "..." for instructions truncation (line 415)
        assert ASCII_ELLIPSIS in result.output

    def test_list_skills_with_short_flag(self):
        """Short -v flag should work."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills", "-v"])
        assert result.exit_code == 0
        assert "Detailed Skill Configurations" in result.output

    def test_list_skills_shows_all_skill_names(self):
        """All skills from SKILL_MAPPING should appear in output."""
        from mahavishnu.engines.goal_team_factory import SKILL_MAPPING

        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 0
        for skill_name in SKILL_MAPPING:
            assert skill_name in result.output

    def test_list_skills_shows_models(self):
        """Each skill should display its model."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills"])
        assert result.exit_code == 0
        assert "sonnet" in result.output
        assert "haiku" in result.output

    def test_list_skills_verbose_shows_temperature(self):
        """Verbose mode should show temperature for each skill."""
        app = _make_app()
        result = runner.invoke(app, ["team", "skills", "-v"])
        assert result.exit_code == 0
        assert "Temperature: 0.3" in result.output
        assert "Temperature: 0.7" in result.output


# ===========================================================================
# list command
# ===========================================================================


class TestListTeams:
    """Tests for the 'list' command."""

    def test_list_teams_empty(self):
        """Empty teams list should show informational message."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()

        app = _make_app()
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        assert "No active teams found" in result.output
        assert "mahavishnu team create" in result.output

    def test_list_teams_with_teams(self):
        """Should display active teams in a table."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        config = _make_team_config(name="review_team", description="Review code")
        team_cli_mod._active_teams["team_1"] = config

        app = _make_app()
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        assert "team_1" in result.output
        assert "review_team" in result.output

        team_cli_mod._active_teams.clear()

    def test_list_teams_verbose(self):
        """Verbose should show detailed team information."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        member = _make_member(name="analyst", tools=["search_code"])
        leader = _make_member(name="coordinator")
        config = _make_team_config(leader=leader, members=[member])
        team_cli_mod._active_teams["team_1"] = config

        app = _make_app()
        result = runner.invoke(app, ["team", "list", "--verbose"])
        assert result.exit_code == 0
        assert "Detailed Team Information" in result.output
        assert "coordinator" in result.output
        assert "analyst" in result.output

        team_cli_mod._active_teams.clear()

    def test_list_teams_description_truncation(self):
        """Long descriptions should be truncated in the table."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        config = _make_team_config(description="A" * 100)
        team_cli_mod._active_teams["team_1"] = config

        app = _make_app()
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        # Rich table cell overflow renders truncation as Unicode ellipsis
        assert ELLIPSIS in result.output

        team_cli_mod._active_teams.clear()

    def test_list_teams_with_short_flag(self):
        """Short -v flag should work."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()

        app = _make_app()
        result = runner.invoke(app, ["team", "list", "-v"])
        assert result.exit_code == 0
        assert "No active teams found" in result.output

    def test_list_teams_shows_count(self):
        """Should show the count of active teams."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        team_cli_mod._active_teams["team_1"] = _make_team_config()
        team_cli_mod._active_teams["team_2"] = _make_team_config(name="team2")

        app = _make_app()
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        assert "(2)" in result.output

        team_cli_mod._active_teams.clear()

    def test_list_teams_shows_mode_and_members(self):
        """Table should show mode and member count columns."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        config = _make_team_config(
            mode=TeamMode.BROADCAST,
            members=[_make_member(), _make_member(name="m2")],
        )
        team_cli_mod._active_teams["team_1"] = config

        app = _make_app()
        result = runner.invoke(app, ["team", "list"])
        assert result.exit_code == 0
        assert "broadcast" in result.output

        team_cli_mod._active_teams.clear()

    def test_list_teams_verbose_shows_team_id(self):
        """Verbose should show team ID for each team."""
        import mahavishnu.cli.team_cli as team_cli_mod

        team_cli_mod._active_teams.clear()
        team_cli_mod._active_teams["team_42"] = _make_team_config()

        app = _make_app()
        result = runner.invoke(app, ["team", "list", "-v"])
        assert result.exit_code == 0
        assert "team_42" in result.output

        team_cli_mod._active_teams.clear()


# ===========================================================================
# learning command
# ===========================================================================


class TestLearningStats:
    """Tests for the 'learning' command."""

    def test_learning_system_disabled(self):
        """When learning_system_enabled is off, should exit with code 1."""
        with patch(
            "mahavishnu.cli.team_cli.is_feature_enabled",
            side_effect=lambda f: f != "learning_system_enabled",
        ):
            app = _make_app()
            result = runner.invoke(app, ["team", "learning"])
            assert result.exit_code == 1
            assert "Learning system is disabled" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_basic_stats(self, mock_get_engine, mock_flags):
        """Basic learning stats should display."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 10,
            "skill_combinations": 5,
            "intents_tracked": 3,
            "modes_tracked": 2,
            "intent_mode_combinations": 6,
            "recent_success_rate": 0.75,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "Team Learning Statistics" in result.output
        assert "10" in result.output
        assert "75%" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_mode_performance(self, mock_get_engine, mock_flags):
        """Mode performance table should be shown when data exists."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 20,
            "skill_combinations": 5,
            "intents_tracked": 3,
            "modes_tracked": 2,
            "intent_mode_combinations": 6,
            "recent_success_rate": 0.80,
            "mode_performance": {
                "coordinate": {
                    "success_rate": 0.90,
                    "avg_latency_ms": 1500.0,
                    "executions": 10,
                },
                "route": {
                    "success_rate": 0.70,
                    "avg_latency_ms": 800.0,
                    "executions": 10,
                },
            },
            "intent_performance": {},
            "top_skills": [],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "Mode Performance" in result.output
        assert "coordinate" in result.output
        assert "route" in result.output
        assert "90%" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_intent_performance(self, mock_get_engine, mock_flags):
        """Intent performance table should be shown when data exists."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 15,
            "skill_combinations": 4,
            "intents_tracked": 2,
            "modes_tracked": 2,
            "intent_mode_combinations": 4,
            "recent_success_rate": 0.67,
            "mode_performance": {},
            "intent_performance": {
                "review": {
                    "success_rate": 0.80,
                    "avg_latency_ms": 1200.0,
                    "executions": 10,
                },
                "build": {
                    "success_rate": 0.50,
                    "avg_latency_ms": 2000.0,
                    "executions": 5,
                },
            },
            "top_skills": [],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "Intent Performance" in result.output
        assert "review" in result.output
        assert "build" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_top_skills(self, mock_get_engine, mock_flags):
        """Top skills table should be shown when data exists."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 10,
            "skill_combinations": 3,
            "intents_tracked": 2,
            "modes_tracked": 2,
            "intent_mode_combinations": 4,
            "recent_success_rate": 0.85,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [
                {
                    "skills": "security, quality",
                    "success_rate": 0.95,
                    "avg_latency_ms": 1500.0,
                    "executions": 20,
                },
            ],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "Top Performing Skill Combinations" in result.output
        assert "security, quality" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_top_skills_truncation(self, mock_get_engine, mock_flags):
        """Long skill names should be truncated in top skills table."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 1,
            "skill_combinations": 1,
            "intents_tracked": 1,
            "modes_tracked": 1,
            "intent_mode_combinations": 1,
            "recent_success_rate": 1.0,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [
                {
                    "skills": "a" * 60,
                    "success_rate": 0.90,
                    "avg_latency_ms": 1000.0,
                    "executions": 5,
                },
            ],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        # Rich table cell overflow renders truncation as Unicode ellipsis
        assert ELLIPSIS in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_verbose_recent_outcomes(self, mock_get_engine, mock_flags):
        """Verbose should show recent outcomes."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 5,
            "skill_combinations": 2,
            "intents_tracked": 2,
            "modes_tracked": 2,
            "intent_mode_combinations": 4,
            "recent_success_rate": 0.60,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [],
        }
        mock_engine.get_recent_outcomes.return_value = [
            {
                "team_id": "team_1",
                "success": True,
                "latency_ms": 1200.0,
                "team_mode": "coordinate",
                "parsed_intent": "review",
            },
            {
                "team_id": "team_2",
                "success": False,
                "latency_ms": 3000.0,
                "team_mode": "route",
                "parsed_intent": "build",
            },
        ]

        app = _make_app()
        result = runner.invoke(app, ["team", "learning", "--verbose"])
        assert result.exit_code == 0
        assert "Recent Outcomes" in result.output
        assert "team_1" in result.output
        assert "team_2" in result.output
        assert "coordinate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_export(self, mock_get_engine, mock_flags):
        """Export flag should display JSON data."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.export_stats.return_value = {
            "total_outcomes": 5,
            "summary": "test data",
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning", "--export"])
        assert result.exit_code == 0
        assert "Learning Data Export" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    @patch("mahavishnu.core.team_learning.reset_learning_engine")
    def test_learning_clear_confirmed(self, mock_reset, mock_get_engine, mock_flags):
        """Clear with confirmation should reset learning data."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "learning", "--clear"],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "Learning data cleared successfully" in result.output
        mock_reset.assert_called_once()

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    @patch("mahavishnu.core.team_learning.reset_learning_engine")
    def test_learning_clear_declined(self, mock_reset, mock_get_engine, mock_flags):
        """Clear with declined confirmation should not reset."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "learning", "--clear"],
            input="n\n",
        )
        assert result.exit_code == 0
        mock_reset.assert_not_called()

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_verbose_no_recent(self, mock_get_engine, mock_flags):
        """Verbose with no recent outcomes should not crash."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 0,
            "skill_combinations": 0,
            "intents_tracked": 0,
            "modes_tracked": 0,
            "intent_mode_combinations": 0,
            "recent_success_rate": 0.0,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [],
        }
        mock_engine.get_recent_outcomes.return_value = []

        app = _make_app()
        result = runner.invoke(app, ["team", "learning", "--verbose"])
        assert result.exit_code == 0
        assert "Recent Outcomes" not in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_usage_hint(self, mock_get_engine, mock_flags):
        """Learning command should show usage hint."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 0,
            "skill_combinations": 0,
            "intents_tracked": 0,
            "modes_tracked": 0,
            "intent_mode_combinations": 0,
            "recent_success_rate": 0.0,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "--verbose" in result.output
        assert "--export" in result.output
        assert "--clear" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_learning_shows_summary_properties(self, mock_get_engine, mock_flags):
        """Learning summary should show all expected properties."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_learning_summary.return_value = {
            "total_outcomes": 42,
            "skill_combinations": 7,
            "intents_tracked": 4,
            "modes_tracked": 3,
            "intent_mode_combinations": 12,
            "recent_success_rate": 0.91,
            "mode_performance": {},
            "intent_performance": {},
            "top_skills": [],
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "learning"])
        assert result.exit_code == 0
        assert "Total Outcomes" in result.output
        assert "Skill Combinations" in result.output
        assert "Intents Tracked" in result.output
        assert "Modes Tracked" in result.output
        assert "Intent-Mode Combos" in result.output
        assert "Recent Success Rate" in result.output


# ===========================================================================
# recommend command
# ===========================================================================


class TestRecommendMode:
    """Tests for the 'recommend' command."""

    def test_recommend_learning_disabled(self):
        """When learning_system_enabled is off, should exit with code 1."""
        with patch(
            "mahavishnu.cli.team_cli.is_feature_enabled",
            side_effect=lambda f: f != "learning_system_enabled",
        ):
            app = _make_app()
            result = runner.invoke(app, ["team", "recommend", "review"])
            assert result.exit_code == 1
            assert "Learning system is disabled" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_with_data(self, mock_get_engine, mock_flags):
        """Should display recommendation when learning data is available."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        recommendation = MagicMock()
        recommendation.mode = "coordinate"
        recommendation.confidence = 0.85
        recommendation.success_rate = 0.90
        recommendation.sample_count = 20
        recommendation.reason = "Historical success rate is high"
        mock_engine.get_mode_recommendation.return_value = recommendation

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "review"])
        assert result.exit_code == 0
        assert "coordinate" in result.output
        assert "85%" in result.output
        assert "90%" in result.output
        assert "Historical success rate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_known_intent(self, mock_get_engine, mock_flags):
        """Should show fallback for known intent when no learning data."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "review"])
        assert result.exit_code == 0
        assert "Insufficient learning data" in result.output
        assert "coordinate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_build_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'build' intent should be 'coordinate'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "build"])
        assert result.exit_code == 0
        assert "Fallback mode: coordinate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_fix_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'fix' intent should be 'route'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "fix"])
        assert result.exit_code == 0
        assert "Fallback mode: route" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_analyze_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'analyze' intent should be 'broadcast'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "analyze"])
        assert result.exit_code == 0
        assert "Fallback mode: broadcast" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_unknown_intent(self, mock_get_engine, mock_flags):
        """Fallback for unknown intent should default to 'coordinate'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "something_unknown"])
        assert result.exit_code == 0
        assert "Fallback mode: coordinate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_shows_properties(self, mock_get_engine, mock_flags):
        """Recommendation should show all expected property names."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        recommendation = MagicMock()
        recommendation.mode = "route"
        recommendation.confidence = 0.75
        recommendation.success_rate = 0.80
        recommendation.sample_count = 15
        recommendation.reason = "Good latency"
        mock_engine.get_mode_recommendation.return_value = recommendation

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "test"])
        assert result.exit_code == 0
        assert "Recommended Mode" in result.output
        assert "Confidence" in result.output
        assert "Success Rate" in result.output
        assert "Sample Count" in result.output
        assert "Reason" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_missing_argument(self, mock_get_engine, mock_flags):
        """Missing required intent argument should show help/error."""
        app = _make_app()
        result = runner.invoke(app, ["team", "recommend"])
        assert result.exit_code != 0

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_document_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'document' intent should be 'route'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "document"])
        assert result.exit_code == 0
        assert "Fallback mode: route" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_refactor_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'refactor' intent should be 'coordinate'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "refactor"])
        assert result.exit_code == 0
        assert "Fallback mode: coordinate" in result.output

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    @patch("mahavishnu.core.team_learning.get_learning_engine")
    def test_recommend_no_data_test_intent(self, mock_get_engine, mock_flags):
        """Fallback for 'test' intent should be 'coordinate'."""
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_engine.get_mode_recommendation.return_value = None

        app = _make_app()
        result = runner.invoke(app, ["team", "recommend", "test"])
        assert result.exit_code == 0
        assert "Fallback mode: coordinate" in result.output


# ===========================================================================
# flags command
# ===========================================================================


class TestShowFeatureFlags:
    """Tests for the 'flags' command."""

    @patch("mahavishnu.core.feature_flags.get_all_feature_flags")
    def test_flags_display(self, mock_get_flags):
        """Should display all feature flags in a table."""
        mock_get_flags.return_value = {
            "enabled": True,
            "mcp_tools_enabled": True,
            "cli_commands_enabled": True,
            "llm_fallback_enabled": False,
            "websocket_broadcasts_enabled": True,
            "prometheus_metrics_enabled": False,
            "learning_system_enabled": False,
            "auto_mode_selection_enabled": True,
            "custom_skills_enabled": False,
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "flags"])
        assert result.exit_code == 0
        assert "Feature Flags" in result.output
        assert "enabled" in result.output
        assert "mcp_tools_enabled" in result.output
        assert "learning_system_enabled" in result.output
        assert "mahavishnu.yaml" in result.output

    @patch("mahavishnu.core.feature_flags.get_all_feature_flags")
    def test_flags_all_enabled(self, mock_get_flags):
        """All enabled flags should show 'enabled' status."""
        mock_get_flags.return_value = {
            "enabled": True,
            "mcp_tools_enabled": True,
            "cli_commands_enabled": True,
            "llm_fallback_enabled": True,
            "websocket_broadcasts_enabled": True,
            "prometheus_metrics_enabled": True,
            "learning_system_enabled": True,
            "auto_mode_selection_enabled": True,
            "custom_skills_enabled": True,
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "flags"])
        assert result.exit_code == 0
        assert "enabled" in result.output

    @patch("mahavishnu.core.feature_flags.get_all_feature_flags")
    def test_flags_all_disabled(self, mock_get_flags):
        """All disabled flags should show 'disabled' status."""
        mock_get_flags.return_value = {
            "enabled": False,
            "mcp_tools_enabled": False,
            "cli_commands_enabled": False,
            "llm_fallback_enabled": False,
            "websocket_broadcasts_enabled": False,
            "prometheus_metrics_enabled": False,
            "learning_system_enabled": False,
            "auto_mode_selection_enabled": False,
            "custom_skills_enabled": False,
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "flags"])
        assert result.exit_code == 0
        assert "disabled" in result.output

    @patch("mahavishnu.core.feature_flags.get_all_feature_flags")
    def test_flags_shows_descriptions(self, mock_get_flags):
        """Flags table should include description column."""
        mock_get_flags.return_value = {
            "enabled": True,
            "mcp_tools_enabled": True,
            "cli_commands_enabled": True,
            "llm_fallback_enabled": True,
            "websocket_broadcasts_enabled": True,
            "prometheus_metrics_enabled": True,
            "learning_system_enabled": False,
            "auto_mode_selection_enabled": True,
            "custom_skills_enabled": False,
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "flags"])
        assert result.exit_code == 0
        # Description column contains the text from the descriptions dict
        assert "Enable MCP tools" in result.output
        assert "Enable CLI commands" in result.output

    @patch("mahavishnu.core.feature_flags.get_all_feature_flags")
    def test_flags_shows_config_hint(self, mock_get_flags):
        """Flags command should show configuration hint."""
        mock_get_flags.return_value = {
            "enabled": True,
            "mcp_tools_enabled": True,
            "cli_commands_enabled": True,
            "llm_fallback_enabled": True,
            "websocket_broadcasts_enabled": True,
            "prometheus_metrics_enabled": True,
            "learning_system_enabled": False,
            "auto_mode_selection_enabled": True,
            "custom_skills_enabled": False,
        }

        app = _make_app()
        result = runner.invoke(app, ["team", "flags"])
        assert result.exit_code == 0
        assert "Configure feature flags" in result.output
        assert "goal_teams.feature_flags" in result.output


# ===========================================================================
# _display_team_config_yaml (tested indirectly via create --dry-run)
# ===========================================================================


class TestDisplayTeamConfigYaml:
    """Tests for YAML display via the dry-run path."""

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_yaml_no_leader(self, mock_get_factory):
        """YAML display should not include leader section when no leader."""
        config = _make_team_config(mode=TeamMode.ROUTE, leader=None)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Route task", "--dry-run"],
        )
        assert result.exit_code == 0
        # With leader=None the YAML and config display should not mention Leader
        assert "  leader:" not in result.output
        assert "Leader" not in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_yaml_with_multiple_members(self, mock_get_factory):
        """YAML display should list all members."""
        members = [
            _make_member(name="dev1", tools=["write_file"]),
            _make_member(name="dev2", tools=["search_code", "read_file"]),
            _make_member(name="dev3", tools=[]),
        ]
        config = _make_team_config(members=members)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Build feature", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "dev1" in result.output
        assert "dev2" in result.output
        assert "dev3" in result.output
        assert "tools:" in result.output

    @patch("mahavishnu.cli.team_cli._get_factory")
    def test_yaml_leader_section(self, mock_get_factory):
        """YAML display should show leader name, role, and model."""
        leader = _make_member(name="lead", role="Lead", model="opus")
        config = _make_team_config(leader=leader)
        mock_get_factory.return_value = _make_async_factory(config=config)

        app = _make_app()
        result = runner.invoke(
            app,
            ["team", "create", "--goal", "Test", "--dry-run"],
        )
        assert result.exit_code == 0
        # The YAML builder writes leader name, role, and model (lines 193-196)
        assert "  leader:" in result.output
        assert "lead" in result.output
        assert "Lead" in result.output
        assert "opus" in result.output


# ===========================================================================
# _get_factory
# ===========================================================================


class TestGetFactory:
    """Tests for _get_factory()."""

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True)
    def test_get_factory_returns_factory(self, mock_flags):
        """_get_factory should return a GoalDrivenTeamFactory instance."""
        from mahavishnu.cli.team_cli import _get_factory
        from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

        factory = _get_factory()
        assert isinstance(factory, GoalDrivenTeamFactory)

    @patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=False)
    def test_get_factory_llm_fallback_disabled(self, mock_flags):
        """Factory should be created regardless of llm_fallback_enabled."""
        from mahavishnu.cli.team_cli import _get_factory
        from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

        factory = _get_factory()
        assert isinstance(factory, GoalDrivenTeamFactory)


# ===========================================================================
# __all__ exports
# ===========================================================================


class TestModuleExports:
    """Tests for module-level __all__."""

    def test_all_exports_exist(self):
        """All names listed in __all__ should be importable."""
        import mahavishnu.cli.team_cli as team_cli_mod

        for name in team_cli_mod.__all__:
            assert hasattr(team_cli_mod, name), f"Missing export: {name}"
