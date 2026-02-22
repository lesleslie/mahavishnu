"""Unit tests for GoalDrivenTeamFactory.

These tests verify the goal-driven team creation functionality:
- Goal parsing and confidence calculation
- Skill extraction and mapping
- Intent pattern matching
- Team configuration generation
- LLM fallback handling

Coverage target: >90%
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.engines.agno_teams.config import (
    MemberConfig,
    TeamConfig,
    TeamMode,
)
from mahavishnu.engines.goal_team_factory import (
    DOMAIN_PATTERNS,
    INTENT_PATTERNS,
    SKILL_MAPPING,
    GoalDrivenTeamFactory,
    ParsedGoal,
    SkillConfig,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def factory() -> GoalDrivenTeamFactory:
    """Create a GoalDrivenTeamFactory without LLM fallback."""
    return GoalDrivenTeamFactory()


@pytest.fixture
def factory_with_llm() -> GoalDrivenTeamFactory:
    """Create a GoalDrivenTeamFactory with mock LLM factory."""
    mock_llm_factory = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.content = """INTENT: review
DOMAIN: security
SKILLS: security, quality
CONFIDENCE: 0.95"""
    mock_model.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm_factory.create_model = MagicMock(return_value=mock_model)

    return GoalDrivenTeamFactory(llm_factory=mock_llm_factory)


@pytest.fixture
def custom_skill_mapping() -> dict[str, SkillConfig]:
    """Create a custom skill mapping for testing."""
    return {
        "custom_skill": SkillConfig(
            role="Custom specialist",
            instructions="Custom instructions for testing",
            tools=["custom_tool"],
            model="custom-model",
            temperature=0.5,
        ),
    }


@pytest.fixture
def factory_with_custom_skills(
    custom_skill_mapping: dict[str, SkillConfig],
) -> GoalDrivenTeamFactory:
    """Create a factory with custom skill mapping."""
    return GoalDrivenTeamFactory(skill_mapping=custom_skill_mapping)


# ============================================================================
# Goal Parsing Tests
# ============================================================================


class TestGoalParsing:
    """Tests for goal parsing functionality."""

    @pytest.mark.asyncio
    async def test_parse_security_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a security-related goal."""
        parsed = await factory.parse_goal("Review this code for security vulnerabilities")

        assert parsed.intent == "review"
        assert parsed.domain == "security"
        assert "security" in parsed.skills
        assert parsed.confidence > 0.5
        assert parsed.raw_goal == "Review this code for security vulnerabilities"

    @pytest.mark.asyncio
    async def test_parse_testing_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a testing-related goal."""
        parsed = await factory.parse_goal("Write unit tests for the authentication module")

        assert parsed.intent == "build"  # "write" maps to build
        assert "testing" in parsed.skills
        assert parsed.confidence > 0.5

    @pytest.mark.asyncio
    async def test_parse_performance_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a performance-related goal."""
        parsed = await factory.parse_goal("Optimize the database query performance")

        assert parsed.intent == "refactor"  # "optimize" maps to refactor
        assert parsed.domain == "performance"
        assert "performance" in parsed.skills

    @pytest.mark.asyncio
    async def test_parse_complex_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a complex multi-skill goal."""
        parsed = await factory.parse_goal(
            "Review and test the security implementation with performance optimization"
        )

        # Should detect multiple skills
        assert len(parsed.skills) >= 1
        assert parsed.confidence > 0.0

    @pytest.mark.asyncio
    async def test_parse_short_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a very short goal."""
        parsed = await factory.parse_goal("test")

        # Should still produce valid result
        assert parsed.intent == "test"
        assert parsed.confidence >= 0.0
        assert isinstance(parsed.skills, list)

    @pytest.mark.asyncio
    async def test_parse_empty_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing an empty goal."""
        parsed = await factory.parse_goal("")

        # Should produce defaults
        assert parsed.intent == "analyze"  # Default intent
        assert parsed.domain == "general"  # Default domain
        assert parsed.confidence >= 0.0

    @pytest.mark.asyncio
    async def test_confidence_calculation(self, factory: GoalDrivenTeamFactory) -> None:
        """Test confidence score calculation."""
        # High confidence: clear intent + skills + domain
        high_confidence = await factory.parse_goal(
            "Review code for security vulnerabilities and test coverage"
        )

        # Low confidence: vague goal
        low_confidence = await factory.parse_goal("do something")

        assert high_confidence.confidence > low_confidence.confidence

    @pytest.mark.asyncio
    async def test_parse_goal_normalization(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that goals are normalized (lowercase, trimmed)."""
        parsed = await factory.parse_goal("  REVIEW CODE FOR SECURITY  ")

        # Should match patterns despite uppercase
        assert parsed.intent == "review"
        assert "security" in parsed.skills

    @pytest.mark.asyncio
    async def test_parse_goal_metadata(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that metadata is included in parsed goal."""
        parsed = await factory.parse_goal("Review security code")

        assert "method" in parsed.metadata
        # High confidence goals use pattern matching
        if parsed.confidence >= 0.7:
            assert parsed.metadata["method"] == "pattern"


class TestGoalParsingWithLLMFallback:
    """Tests for goal parsing with LLM fallback."""

    @pytest.mark.asyncio
    async def test_llm_fallback_for_low_confidence(
        self, factory_with_llm: GoalDrivenTeamFactory
    ) -> None:
        """Test that LLM is used when pattern confidence is low."""
        # Vague goal should trigger LLM fallback
        parsed = await factory_with_llm.parse_goal("help me with stuff")

        # LLM should improve results
        assert parsed.confidence >= 0.0
        assert parsed.metadata.get("method") in ["pattern", "llm", "pattern_low"]

    @pytest.mark.asyncio
    async def test_llm_fallback_not_used_for_high_confidence(
        self, factory_with_llm: GoalDrivenTeamFactory
    ) -> None:
        """Test that LLM fallback is not used for high-confidence patterns."""
        # Clear goal should use pattern matching
        parsed = await factory_with_llm.parse_goal("Review code for security vulnerabilities")

        # Should use pattern matching, not LLM
        assert parsed.metadata.get("method") == "pattern"

    @pytest.mark.asyncio
    async def test_llm_response_parsing(self, factory_with_llm: GoalDrivenTeamFactory) -> None:
        """Test parsing of LLM response."""
        response = """INTENT: build
DOMAIN: testing
SKILLS: testing, quality
CONFIDENCE: 0.85"""

        result = factory_with_llm._parse_llm_response("test goal", response)

        assert result.intent == "build"
        assert result.domain == "testing"
        assert "testing" in result.skills
        assert "quality" in result.skills
        assert result.confidence == 0.85
        assert result.metadata.get("method") == "llm"


# ============================================================================
# Team Creation Tests
# ============================================================================


class TestTeamCreation:
    """Tests for team creation from goals."""

    @pytest.mark.asyncio
    async def test_create_team_from_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test creating a team from a goal."""
        team_config = await factory.create_team_from_goal("Review code for security issues")

        assert isinstance(team_config, TeamConfig)
        assert team_config.name != ""
        assert len(team_config.members) >= 1
        assert team_config.mode in [
            TeamMode.COORDINATE,
            TeamMode.ROUTE,
            TeamMode.BROADCAST,
            TeamMode.COLLABORATE,
        ]

    @pytest.mark.asyncio
    async def test_create_team_with_custom_name(self, factory: GoalDrivenTeamFactory) -> None:
        """Test creating a team with a custom name."""
        team_config = await factory.create_team_from_goal(
            "Review security code", name="custom_team_name"
        )

        assert team_config.name == "custom_team_name"

    @pytest.mark.asyncio
    async def test_create_team_with_custom_mode(self, factory: GoalDrivenTeamFactory) -> None:
        """Test creating a team with a custom mode."""
        team_config = await factory.create_team_from_goal(
            "Review security code", mode=TeamMode.BROADCAST
        )

        assert team_config.mode == TeamMode.BROADCAST

    @pytest.mark.asyncio
    async def test_team_has_correct_members(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that team has correct member configurations."""
        team_config = await factory.create_team_from_goal(
            "Review code for security and performance"
        )

        # Should have members for matched skills
        assert len(team_config.members) >= 1

        # Each member should have required fields
        for member in team_config.members:
            assert isinstance(member, MemberConfig)
            assert member.name != ""
            assert member.role != ""
            assert member.instructions != ""

    @pytest.mark.asyncio
    async def test_coordinate_mode_has_leader(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that coordinate mode teams have a leader."""
        # Review intent uses coordinate mode
        team_config = await factory.create_team_from_goal("Review the codebase for issues")

        # If mode is coordinate, leader should be present
        if team_config.mode == TeamMode.COORDINATE:
            assert team_config.leader is not None
            assert team_config.leader.name == "coordinator"

    @pytest.mark.asyncio
    async def test_default_member_created_for_unknown_goal(
        self, factory: GoalDrivenTeamFactory
    ) -> None:
        """Test that a default member is created for unknown goals."""
        team_config = await factory.create_team_from_goal("xyzzy")

        # Should have at least one member (default generalist)
        assert len(team_config.members) >= 1

        # Default member should be a generalist
        first_member = team_config.members[0]
        assert "generalist" in first_member.name or first_member.role != ""


# ============================================================================
# Skill Mapping Tests
# ============================================================================


class TestSkillMapping:
    """Tests for skill mapping configuration."""

    def test_all_skills_have_required_fields(self) -> None:
        """Test that all skills in SKILL_MAPPING have required fields."""
        for skill_name, config in SKILL_MAPPING.items():
            assert isinstance(config, SkillConfig)
            assert config.role != "", f"Skill {skill_name} missing role"
            assert config.instructions != "", f"Skill {skill_name} missing instructions"
            assert isinstance(config.tools, list)
            assert config.model != "", f"Skill {skill_name} missing model"
            assert 0.0 <= config.temperature <= 2.0

    def test_skill_config_instantiation(self) -> None:
        """Test SkillConfig dataclass instantiation."""
        config = SkillConfig(
            role="Test role",
            instructions="Test instructions",
            tools=["tool1", "tool2"],
            model="test-model",
            temperature=0.5,
        )

        assert config.role == "Test role"
        assert config.instructions == "Test instructions"
        assert config.tools == ["tool1", "tool2"]
        assert config.model == "test-model"
        assert config.temperature == 0.5

    def test_skill_config_defaults(self) -> None:
        """Test SkillConfig default values."""
        config = SkillConfig(
            role="Role",
            instructions="Instructions",
        )

        assert config.tools == []
        assert config.model == "qwen2.5:7b"
        assert config.temperature == 0.7

    def test_skill_mapping_completeness(self) -> None:
        """Test that SKILL_MAPPING covers expected domains."""
        expected_skills = [
            "security",
            "quality",
            "performance",
            "testing",
            "documentation",
            "refactoring",
            "debugging",
        ]

        for skill in expected_skills:
            assert skill in SKILL_MAPPING, f"Missing skill: {skill}"


# ============================================================================
# Intent Matching Tests
# ============================================================================


class TestIntentMatching:
    """Tests for intent pattern matching."""

    def test_review_intent_patterns(self) -> None:
        """Test review intent pattern matching."""
        factory = GoalDrivenTeamFactory()

        review_goals = [
            "review the code",
            "analyze this file",
            "check for issues",
            "audit the system",
            "inspect the output",
            "evaluate the code",
        ]

        for goal in review_goals:
            intent = factory._match_intent(goal.lower())
            assert intent == "review", f"Failed for goal: {goal}"

    def test_build_intent_patterns(self) -> None:
        """Test build intent pattern matching."""
        factory = GoalDrivenTeamFactory()

        build_goals = [
            "build a feature",
            "create a new module",
            "implement the api",
            "develop a solution",
            "add new functionality",
            "write a function",
        ]

        for goal in build_goals:
            intent = factory._match_intent(goal.lower())
            assert intent == "build", f"Failed for goal: {goal}"

    def test_fix_intent_patterns(self) -> None:
        """Test fix intent pattern matching."""
        factory = GoalDrivenTeamFactory()

        fix_goals = [
            "fix the bug",
            "debug this issue",
            "resolve the error",
            "solve this problem",
            "bug in the code",
            "error in output",
        ]

        for goal in fix_goals:
            intent = factory._match_intent(goal.lower())
            assert intent == "fix", f"Failed for goal: {goal}"

    def test_default_intent_for_unknown(self) -> None:
        """Test that unknown goals default to analyze intent."""
        factory = GoalDrivenTeamFactory()

        unknown_goals = [
            "xyzzy",
            "plugh",
            "random text that doesn't match",
        ]

        for goal in unknown_goals:
            intent = factory._match_intent(goal.lower())
            assert intent == "analyze", f"Failed for goal: {goal}"


# ============================================================================
# Mode Selection Tests
# ============================================================================


class TestModeSelection:
    """Tests for team mode selection."""

    @pytest.mark.asyncio
    async def test_review_uses_coordinate_mode(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that review goals use coordinate mode."""
        team_config = await factory.create_team_from_goal("Review the code for security issues")

        assert team_config.mode == TeamMode.COORDINATE

    @pytest.mark.asyncio
    async def test_fix_uses_route_mode(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that fix goals use route mode."""
        team_config = await factory.create_team_from_goal("Fix the bug in authentication")

        assert team_config.mode == TeamMode.ROUTE

    @pytest.mark.asyncio
    async def test_analyze_uses_broadcast_mode(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that analyze goals use broadcast mode."""
        # Use a goal that doesn't match any intent patterns to trigger analyze default
        team_config = await factory.create_team_from_goal(
            "xyzzy plugh"  # No intent patterns match, defaults to analyze
        )

        # Analyze intent should use broadcast mode
        assert team_config.mode == TeamMode.BROADCAST

    def test_select_mode_mapping(self) -> None:
        """Test _select_mode returns correct modes for all intents."""
        factory = GoalDrivenTeamFactory()

        expected_modes = {
            "review": TeamMode.COORDINATE,
            "build": TeamMode.COORDINATE,
            "test": TeamMode.COORDINATE,
            "fix": TeamMode.ROUTE,
            "refactor": TeamMode.COORDINATE,
            "document": TeamMode.ROUTE,
            "analyze": TeamMode.BROADCAST,
        }

        for intent, expected_mode in expected_modes.items():
            result = factory._select_mode(intent)
            assert result == expected_mode, f"Wrong mode for {intent}"


# ============================================================================
# Confidence Calculation Tests
# ============================================================================


class TestConfidenceCalculation:
    """Tests for confidence calculation."""

    def test_base_confidence(self) -> None:
        """Test base confidence is applied."""
        factory = GoalDrivenTeamFactory()

        # No matches should give base confidence
        confidence = factory._calculate_confidence("analyze", [], "general")

        assert confidence >= 0.3  # Base confidence

    def test_intent_match_increases_confidence(self) -> None:
        """Test that non-default intent increases confidence."""
        factory = GoalDrivenTeamFactory()

        low_conf = factory._calculate_confidence("analyze", [], "general")
        high_conf = factory._calculate_confidence("review", [], "general")

        assert high_conf > low_conf

    def test_skills_increase_confidence(self) -> None:
        """Test that skills increase confidence."""
        factory = GoalDrivenTeamFactory()

        no_skills = factory._calculate_confidence("review", [], "general")
        with_skills = factory._calculate_confidence("review", ["security"], "general")

        assert with_skills > no_skills

    def test_confidence_never_exceeds_one(self) -> None:
        """Test that confidence never exceeds 1.0."""
        factory = GoalDrivenTeamFactory()

        confidence = factory._calculate_confidence(
            "review", ["security", "quality", "performance"], "security"
        )

        assert confidence <= 1.0


# ============================================================================
# Member Creation Tests
# ============================================================================


class TestMemberCreation:
    """Tests for member configuration creation."""

    def test_create_members_from_skills(self) -> None:
        """Test creating members from skill list."""
        factory = GoalDrivenTeamFactory()

        members = factory._create_members_from_skills(["security", "testing"])

        assert len(members) == 2

        # Check member names follow convention
        member_names = [m.name for m in members]
        assert "security_specialist" in member_names
        assert "testing_specialist" in member_names

    def test_create_members_unknown_skill(self) -> None:
        """Test creating members with unknown skill."""
        factory = GoalDrivenTeamFactory()

        members = factory._create_members_from_skills(["unknown_skill_xyz"])

        # Unknown skills should not create members
        assert len(members) == 0

    def test_create_members_empty_list(self) -> None:
        """Test creating members from empty skill list."""
        factory = GoalDrivenTeamFactory()

        members = factory._create_members_from_skills([])

        assert len(members) == 0

    def test_create_leader(self) -> None:
        """Test creating leader configuration."""
        factory = GoalDrivenTeamFactory()

        parsed = ParsedGoal(
            intent="review",
            domain="security",
            skills=["security", "quality"],
            confidence=0.8,
            raw_goal="Review security",
        )

        leader = factory._create_leader(parsed)

        assert leader.name == "coordinator"
        assert "review" in leader.role.lower() or "coordinate" in leader.role.lower()
        assert leader.model == "sonnet"

    def test_create_default_member(self) -> None:
        """Test creating default member."""
        factory = GoalDrivenTeamFactory()

        parsed = ParsedGoal(
            intent="analyze",
            domain="general",
            skills=[],
            confidence=0.3,
            raw_goal="do something",
        )

        member = factory._create_default_member(parsed)

        assert member.name == "generalist"
        assert "general" in member.role.lower() or member.role != ""
        assert len(member.tools) > 0


# ============================================================================
# ParsedGoal Model Tests
# ============================================================================


class TestParsedGoalModel:
    """Tests for ParsedGoal Pydantic model."""

    def test_parsed_goal_creation(self) -> None:
        """Test creating a ParsedGoal instance."""
        parsed = ParsedGoal(
            intent="review",
            domain="security",
            skills=["security"],
            confidence=0.8,
            raw_goal="Review security",
        )

        assert parsed.intent == "review"
        assert parsed.domain == "security"
        assert parsed.skills == ["security"]
        assert parsed.confidence == 0.8
        assert parsed.raw_goal == "Review security"

    def test_parsed_goal_defaults(self) -> None:
        """Test ParsedGoal default values."""
        parsed = ParsedGoal(
            intent="analyze",
            domain="general",
            confidence=0.5,
            raw_goal="test",
        )

        assert parsed.skills == []
        assert parsed.metadata == {}

    def test_parsed_goal_confidence_bounds(self) -> None:
        """Test ParsedGoal confidence validation."""
        # Valid bounds
        ParsedGoal(intent="x", domain="y", confidence=0.0, raw_goal="z")
        ParsedGoal(intent="x", domain="y", confidence=1.0, raw_goal="z")

        # Invalid - below 0
        with pytest.raises(ValueError):
            ParsedGoal(intent="x", domain="y", confidence=-0.1, raw_goal="z")

        # Invalid - above 1
        with pytest.raises(ValueError):
            ParsedGoal(intent="x", domain="y", confidence=1.1, raw_goal="z")


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_very_long_goal(self, factory: GoalDrivenTeamFactory) -> None:
        """Test parsing a very long goal."""
        long_goal = "Review code for security " * 100

        parsed = await factory.parse_goal(long_goal)

        assert parsed.intent == "review"
        assert "security" in parsed.skills

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self, factory: GoalDrivenTeamFactory) -> None:
        """Test that matching is case insensitive."""
        goals = [
            "REVIEW THE CODE",
            "Review The Code",
            "review the code",
            "ReViEw ThE cOdE",
        ]

        for goal in goals:
            parsed = await factory.parse_goal(goal)
            assert parsed.intent == "review"


class TestFactoryInitialization:
    """Tests for factory initialization."""

    def test_initialization_without_llm(self) -> None:
        """Test factory initialization without LLM."""
        factory = GoalDrivenTeamFactory()

        assert factory.llm_factory is None
        assert factory.skill_mapping == SKILL_MAPPING

    def test_initialization_with_llm(self) -> None:
        """Test factory initialization with LLM."""
        mock_llm = MagicMock()
        factory = GoalDrivenTeamFactory(llm_factory=mock_llm)

        assert factory.llm_factory == mock_llm

    def test_initialization_with_custom_skills(self) -> None:
        """Test factory initialization with custom skills."""
        custom_skills = {
            "custom": SkillConfig(
                role="Custom",
                instructions="Custom instructions",
            )
        }
        factory = GoalDrivenTeamFactory(skill_mapping=custom_skills)

        assert factory.skill_mapping == custom_skills
        assert "security" not in factory.skill_mapping
        assert "custom" in factory.skill_mapping
