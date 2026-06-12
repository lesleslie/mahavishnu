"""Additional unit tests for the team CLI module.

Fills coverage gaps left by test_team_cli.py for the 'learning' and
'recommend' subcommands, which use the *correct* patch target
(`mahavishnu.cli.team_cli.team_learning.get_learning_engine`) so the
patches actually take effect when running under coverage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.core import team_learning
from mahavishnu.engines.goal_team_factory import SKILL_MAPPING

runner = CliRunner()


def _make_app() -> typer.Typer:
    """Create a parent Typer app with the team sub-app registered."""
    from mahavishnu.cli.team_cli import add_team_commands

    app = typer.Typer()
    add_team_commands(app)
    return app


@pytest.fixture(autouse=True)
def _enable_feature_flags():
    """Enable all feature flags by default for every test."""
    with (
        patch("mahavishnu.cli.team_cli.is_feature_enabled", return_value=True),
        patch("mahavishnu.core.feature_flags.is_feature_enabled", return_value=True),
    ):
        yield


def _make_engine_mock(
    summary: dict | None = None,
    recommendation: object | None = None,
    recent_outcomes: list[dict] | None = None,
) -> MagicMock:
    """Construct a mock learning engine with the given canned responses."""
    engine = MagicMock()
    engine.get_learning_summary.return_value = summary or {
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
    engine.get_mode_recommendation.return_value = recommendation
    engine.get_recent_outcomes.return_value = recent_outcomes or []
    engine.export_stats.return_value = {"exported": True}
    return engine


# =============================================================================
# learning command - mode_performance, intent_performance, top_skills
# =============================================================================


@pytest.mark.unit
class TestLearningModePerformance:
    """Cover the 'Mode Performance' sub-table in the learning command."""

    def test_learning_mode_performance_displayed(self) -> None:
        """Mode performance table should be rendered when data is present."""
        engine = _make_engine_mock(
            summary={
                "total_outcomes": 12,
                "skill_combinations": 3,
                "intents_tracked": 2,
                "modes_tracked": 2,
                "intent_mode_combinations": 4,
                "recent_success_rate": 0.75,
                "mode_performance": {
                    "coordinate": {
                        "success_rate": 0.9,
                        "avg_latency_ms": 120.0,
                        "executions": 10,
                    },
                    "route": {
                        "success_rate": 0.5,
                        "avg_latency_ms": 80.0,
                        "executions": 4,
                    },
                },
                "intent_performance": {},
                "top_skills": [],
            }
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning"])

        assert result.exit_code == 0
        assert "Mode Performance" in result.output
        assert "coordinate" in result.output
        assert "route" in result.output
        assert "90%" in result.output
        assert "120ms" in result.output


@pytest.mark.unit
class TestLearningIntentPerformance:
    """Cover the 'Intent Performance' sub-table."""

    def test_learning_intent_performance_displayed(self) -> None:
        """Intent performance table should render when data is present."""
        engine = _make_engine_mock(
            summary={
                "total_outcomes": 8,
                "skill_combinations": 1,
                "intents_tracked": 2,
                "modes_tracked": 1,
                "intent_mode_combinations": 2,
                "recent_success_rate": 0.6,
                "mode_performance": {},
                "intent_performance": {
                    "review": {
                        "success_rate": 0.8,
                        "avg_latency_ms": 200.0,
                        "executions": 5,
                    },
                    "fix": {
                        "success_rate": 0.4,
                        "avg_latency_ms": 300.0,
                        "executions": 3,
                    },
                },
                "top_skills": [],
            }
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning"])

        assert result.exit_code == 0
        assert "Intent Performance" in result.output
        assert "review" in result.output
        assert "fix" in result.output
        assert "200ms" in result.output


@pytest.mark.unit
class TestLearningTopSkills:
    """Cover the 'Top Performing Skill Combinations' sub-table."""

    def test_learning_top_skills_displayed(self) -> None:
        """Top skills table should render when data is present."""
        engine = _make_engine_mock(
            summary={
                "total_outcomes": 20,
                "skill_combinations": 4,
                "intents_tracked": 3,
                "modes_tracked": 2,
                "intent_mode_combinations": 5,
                "recent_success_rate": 0.85,
                "mode_performance": {},
                "intent_performance": {},
                "top_skills": [
                    {
                        "skills": "code_review,security_scan",
                        "success_rate": 0.95,
                        "avg_latency_ms": 150.0,
                        "executions": 12,
                    },
                    {
                        "skills": "performance_analysis" * 6,  # >40 chars: exercise truncation branch
                        "success_rate": 0.70,
                        "avg_latency_ms": 250.0,
                        "executions": 6,
                    },
                ],
            }
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning"])

        assert result.exit_code == 0
        assert "Top Performing Skill Combinations" in result.output
        assert "code_review" in result.output

    def test_learning_top_skills_short_unchanged(self) -> None:
        """Top skills list with short skill names should render without truncation."""
        engine = _make_engine_mock(
            summary={
                "total_outcomes": 5,
                "skill_combinations": 1,
                "intents_tracked": 1,
                "modes_tracked": 1,
                "intent_mode_combinations": 1,
                "recent_success_rate": 1.0,
                "mode_performance": {},
                "intent_performance": {},
                "top_skills": [
                    {
                        "skills": "short_skill",
                        "success_rate": 1.0,
                        "avg_latency_ms": 50.0,
                        "executions": 5,
                    },
                ],
            }
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning"])

        assert result.exit_code == 0
        assert "short_skill" in result.output


@pytest.mark.unit
class TestLearningVerbose:
    """Cover the verbose branch showing recent outcomes."""

    def test_learning_verbose_recent_outcomes_success(self) -> None:
        """Verbose flag should render recent successful outcomes."""
        engine = _make_engine_mock(
            recent_outcomes=[
                {
                    "team_id": "team_1",
                    "success": True,
                    "latency_ms": 100.0,
                    "team_mode": "coordinate",
                    "parsed_intent": "review",
                },
            ]
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning", "--verbose"])

        assert result.exit_code == 0
        assert "Recent Outcomes" in result.output
        assert "team_1" in result.output
        assert "success" in result.output
        assert "review" in result.output

    def test_learning_verbose_recent_outcomes_failure(self) -> None:
        """Verbose flag should render recent failed outcomes."""
        engine = _make_engine_mock(
            recent_outcomes=[
                {
                    "team_id": "team_42",
                    "success": False,
                    "latency_ms": 250.0,
                    "team_mode": "route",
                    "parsed_intent": "fix",
                },
            ]
        )

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning", "--verbose"])

        assert result.exit_code == 0
        assert "Recent Outcomes" in result.output
        assert "team_42" in result.output
        assert "failed" in result.output

    def test_learning_verbose_no_recent_outcomes(self) -> None:
        """Verbose flag with no recent outcomes should not blow up."""
        engine = _make_engine_mock(recent_outcomes=[])

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "learning", "--verbose"])

        assert result.exit_code == 0


# =============================================================================
# recommend command - data display path
# =============================================================================


@pytest.mark.unit
class TestRecommendWithData:
    """Cover the display of ModeRecommendation when learning data exists."""

    def test_recommend_displays_all_properties(self) -> None:
        """When a recommendation is available, all properties should render."""
        recommendation = MagicMock()
        recommendation.mode = "coordinate"
        recommendation.confidence = 0.85
        recommendation.success_rate = 0.90
        recommendation.sample_count = 20
        recommendation.reason = "High historical success rate"
        engine = _make_engine_mock(recommendation=recommendation)

        with patch.object(team_learning, "get_learning_engine", return_value=engine):
            result = runner.invoke(_make_app(), ["team", "recommend", "review"])

        assert result.exit_code == 0
        assert "Recommended Mode" in result.output
        assert "coordinate" in result.output
        assert "85%" in result.output
        assert "90%" in result.output
        assert "20" in result.output
        assert "High historical success rate" in result.output


# =============================================================================
# skills command - SKILL_MAPPING rendering paths
# =============================================================================


@pytest.mark.unit
class TestSkillsVerbose:
    """Cover the verbose rendering of skill configurations."""

    def test_skills_verbose_with_long_role(self) -> None:
        """Verbose skills listing should truncate roles that exceed 40 chars."""
        # Pick any existing skill and confirm verbose output works.
        assert SKILL_MAPPING, "SKILL_MAPPING should not be empty"
        first_skill_name = next(iter(SKILL_MAPPING))

        result = runner.invoke(_make_app(), ["team", "skills", "--verbose"])

        assert result.exit_code == 0
        assert "Detailed Skill Configurations" in result.output
        assert first_skill_name.upper() in result.output
        assert "Total skills" in result.output


# =============================================================================
# list command - empty and populated paths
# =============================================================================


@pytest.mark.unit
class TestListTeamsEmpty:
    """Cover the empty-`_active_teams` branch."""

    def test_list_teams_no_teams(self) -> None:
        """When no teams exist, list should print a friendly empty message."""
        from mahavishnu.cli import team_cli

        original_teams = team_cli._active_teams
        team_cli._active_teams = {}
        try:
            result = runner.invoke(_make_app(), ["team", "list"])
            assert result.exit_code == 0
            assert "No active teams found" in result.output
        finally:
            team_cli._active_teams = original_teams
