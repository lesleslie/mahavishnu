"""Coverage-push tests for the 5 missed lines in mahavishnu/engines/goal_team_factory.py"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.engines.goal_team_factory import (
    GoalDrivenTeamFactory,
    ParsedGoal,
)


def _factory_with_unknown_goal() -> GoalDrivenTeamFactory:
    """Factory wired so its parsed goal carries a skill absent from the default mapping."""
    factory = GoalDrivenTeamFactory()
    fake_goal = ParsedGoal(
        intent="build",
        domain="general",
        skills=["nonexistent_skill_xyz"],
        confidence=0.4,
        raw_goal="do something unknown",
    )

    async def fake_parse_goal(_goal: str) -> ParsedGoal:
        return fake_goal

    factory.parse_goal = fake_parse_goal  # type: ignore[method-assign]
    return factory


@pytest.fixture
def factory_no_llm() -> GoalDrivenTeamFactory:
    return _factory_with_unknown_goal()


@pytest.fixture
def factory_with_failing_llm() -> GoalDrivenTeamFactory:
    mock_llm_factory = MagicMock()
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    mock_llm_factory.create_model = MagicMock(return_value=mock_model)
    return GoalDrivenTeamFactory(llm_factory=mock_llm_factory)


@pytest.mark.asyncio
async def test_create_default_member_used_when_no_skills_match(
    factory_no_llm: GoalDrivenTeamFactory,
) -> None:
    """Line 386: fallback to _create_default_member when skills produce no members."""
    config = await factory_no_llm.create_team_from_goal("do something unknown")

    assert len(config.members) == 1
    assert config.members[0].name == "generalist"


@pytest.mark.asyncio
async def test_llm_parse_without_factory_returns_default(
    factory_no_llm: GoalDrivenTeamFactory,
) -> None:
    """Line 629: _llm_parse returns analyze/general fallback when llm_factory is None."""
    result = await factory_no_llm._llm_parse("anything")

    assert result.intent == "analyze"
    assert result.domain == "general"
    assert result.skills == ["quality"]
    assert result.confidence == 0.3


@pytest.mark.asyncio
async def test_llm_parse_swallows_exception(
    factory_with_failing_llm: GoalDrivenTeamFactory,
) -> None:
    """Lines 658-660: _llm_parse catches exceptions and returns the analyze fallback."""
    result = await factory_with_failing_llm._llm_parse("any goal")

    assert result.intent == "analyze"
    assert result.domain == "general"
    assert result.skills == ["quality"]
    assert result.confidence == 0.3
    assert result.metadata.get("error") == "boom"
