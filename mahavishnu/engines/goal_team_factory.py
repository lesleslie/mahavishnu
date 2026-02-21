"""Goal-driven team factory for natural language team generation.

This module provides the GoalDrivenTeamFactory class that converts natural
language goals into agent team configurations. This is a NATIVE implementation
that fills the only gap between Hive's capabilities and Bodai's existing
infrastructure.

Key Features:
- Pattern matching for common goals (fast, free)
- LLM fallback for complex goals (slower, costs money)
- Skill-based agent configuration mapping
- Team mode selection based on goal intent

Design Decision:
This implementation was chosen over Hive integration after extensive review
by three independent power trios. Hive was found to be "conceptware with stubs"
while Bodai already has production implementations for:
- StatisticalRouter: Learning, confidence intervals, A/B testing
- AgentTeamManager: Multi-agent orchestration with 4 modes
- DependencyGraph: DAG validation and execution
- PoolManager: Concurrent execution

The only missing piece was: natural language goal -> team configuration.
This module provides that capability in ~150 lines.

See: docs/analysis/HIVE_INTEGRATION_TRIO_SYNTHESIS.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mahavishnu.engines.agno_teams.config import (
    MemberConfig,
    TeamConfig,
    TeamMode,
)

if TYPE_CHECKING:
    pass  # LLM factory type is Any to avoid circular imports

logger = logging.getLogger(__name__)


# ============================================================================
# Goal Parsing Models
# ============================================================================


class ParsedGoal(BaseModel):
    """Result of parsing a natural language goal.

    Attributes:
        intent: Primary intent (review, build, test, analyze, etc.)
        domain: Domain area (code, security, performance, docs, etc.)
        skills: Required skills for the task
        confidence: Confidence score of the parsing (0.0-1.0)
        raw_goal: Original goal string
    """

    intent: str = Field(description="Primary intent of the goal")
    domain: str = Field(description="Domain area (code, security, etc.)")
    skills: list[str] = Field(default_factory=list, description="Required skills")
    confidence: float = Field(ge=0.0, le=1.0, description="Parsing confidence")
    raw_goal: str = Field(description="Original goal string")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


@dataclass
class SkillConfig:
    """Configuration for a skill-based agent.

    Attributes:
        role: Role description for the agent
        instructions: Detailed instructions
        tools: List of tool names
        model: Default model to use
        temperature: Sampling temperature
    """

    role: str
    instructions: str
    tools: list[str] = field(default_factory=list)
    model: str = "qwen2.5:7b"
    temperature: float = 0.7


# ============================================================================
# Skill Mappings
# ============================================================================

# Pre-configured skill mappings for common domains
SKILL_MAPPING: dict[str, SkillConfig] = {
    "security": SkillConfig(
        role="Security vulnerability specialist",
        instructions="""Analyze for security vulnerabilities including:
- SQL injection, XSS, CSRF risks
- Authentication and authorization flaws
- Sensitive data exposure
- Insecure configurations
- OWASP Top 10 issues

Provide severity ratings and remediation recommendations.""",
        tools=["search_code", "read_file", "grep"],
        model="sonnet",
        temperature=0.3,
    ),
    "quality": SkillConfig(
        role="Code quality engineer",
        instructions="""Evaluate code quality including:
- Adherence to style guides and conventions
- Complexity metrics and code smell detection
- Test coverage gaps
- Documentation completeness
- Maintainability concerns

Provide actionable improvement suggestions.""",
        tools=["search_code", "read_file", "run_linter"],
        model="sonnet",
        temperature=0.5,
    ),
    "performance": SkillConfig(
        role="Performance optimization specialist",
        instructions="""Analyze performance including:
- Algorithm complexity and efficiency
- Memory usage patterns
- Database query optimization
- Caching opportunities
- Resource bottlenecks

Provide specific optimization recommendations with expected impact.""",
        tools=["search_code", "read_file", "profile"],
        model="sonnet",
        temperature=0.4,
    ),
    "testing": SkillConfig(
        role="Test engineer",
        instructions="""Design and implement tests including:
- Unit test coverage
- Integration test scenarios
- Edge case identification
- Test data generation
- Assertion strategies

Ensure tests are maintainable and comprehensive.""",
        tools=["search_code", "read_file", "run_tests"],
        model="sonnet",
        temperature=0.6,
    ),
    "documentation": SkillConfig(
        role="Technical writer",
        instructions="""Create documentation including:
- API documentation
- Usage examples and tutorials
- Architecture explanations
- Code comments and docstrings
- README and getting started guides

Ensure clarity and completeness for the target audience.""",
        tools=["search_code", "read_file", "write_file"],
        model="haiku",
        temperature=0.7,
    ),
    "refactoring": SkillConfig(
        role="Refactoring specialist",
        instructions="""Plan and execute refactoring including:
- Code smell identification
- Design pattern application
- Dependency optimization
- Interface improvements
- Backward compatibility considerations

Preserve behavior while improving structure.""",
        tools=["search_code", "read_file", "write_file"],
        model="sonnet",
        temperature=0.5,
    ),
    "debugging": SkillConfig(
        role="Debugging specialist",
        instructions="""Investigate and resolve issues including:
- Root cause analysis
- Error trace interpretation
- State inspection
- Reproduction strategies
- Fix verification

Provide clear explanations of findings and solutions.""",
        tools=["search_code", "read_file", "run_tests", "debugger"],
        model="sonnet",
        temperature=0.3,
    ),
}

# Intent patterns for fast matching
INTENT_PATTERNS = {
    "review": [
        r"\breviews?\b",
        r"\banalyze\b",
        r"\bcheck\b",
        r"\baudit\b",
        r"\binspect\b",
        r"\bevaluate\b",
    ],
    "build": [
        r"\bbuild\b",
        r"\bcreate\b",
        r"\bimplement\b",
        r"\bdevelop\b",
        r"\badd\b",
        r"\bwrite\b",
    ],
    "test": [
        r"\btests?\b",
        r"\btesting\b",
        r"\bcoverage\b",
        r"\bunit\b",
        r"\bintegration\b",
    ],
    "fix": [
        r"\bfix\b",
        r"\bdebug\b",
        r"\bresolve\b",
        r"\bsolve\b",
        r"\bbug\b",
        r"\berror\b",
        r"\bissue\b",
    ],
    "refactor": [
        r"\brefactor\b",
        r"\bclean\b",
        r"\bimprove\b",
        r"\boptimize\b",
        r"\brestructure\b",
    ],
    "document": [
        r"\bdocument\b",
        r"\bdocs?\b",
        r"\breadme\b",
        r"\bcomment\b",
        r"\bexplain\b",
    ],
}

# Domain patterns for skill extraction
DOMAIN_PATTERNS = {
    "security": [r"\bsecurity\b", r"\bauth\b", r"\bxss\b", r"\binjection\b", r"\bvulnerab"],
    "performance": [r"\bperformance\b", r"\bspeed\b", r"\boptimiz\b", r"\bmemory\b", r"\blatency\b"],
    "quality": [r"\bquality\b", r"\bstyle\b", r"\blint\b", r"\bcomplexity\b", r"\bmaintain"],
    "testing": [r"\btest\b", r"\bcoverage\b", r"\bunit\b", r"\bintegration\b"],
    "documentation": [r"\bdoc\b", r"\breadme\b", r"\bcomment\b", r"\bapi\b"],
}


# ============================================================================
# GoalDrivenTeamFactory
# ============================================================================


class GoalDrivenTeamFactory:
    """Converts natural language goals to team configurations.

    This is a NATIVE implementation - no Hive dependency.

    The factory uses a two-phase approach:
    1. Pattern matching (fast, free) - regex patterns for common goals
    2. LLM fallback (slower, costs money) - for complex or ambiguous goals

    Example:
        ```python
        factory = GoalDrivenTeamFactory(llm_factory=llm_factory)

        # Parse a goal
        parsed = await factory.parse_goal("Review this code for security issues")
        # parsed.intent = "review"
        # parsed.skills = ["security", "quality"]

        # Create a team from the goal
        team_config = await factory.create_team_from_goal(
            "Review this code for security issues"
        )

        # Use with AgentTeamManager
        team_id = await team_manager.create_team(team_config)
        result = await team_manager.run_team(team_id, "...")
        ```

    Attributes:
        llm_factory: LLM factory for LLM fallback parsing (type varies by provider)
        skill_mapping: Dictionary mapping skill names to agent configurations
    """

    def __init__(
        self,
        llm_factory: Any = None,
        skill_mapping: dict[str, SkillConfig] | None = None,
    ) -> None:
        """Initialize the goal-driven team factory.

        Args:
            llm_factory: Optional LLM factory for fallback parsing.
                        If None, only pattern matching is used.
            skill_mapping: Optional custom skill mapping. If None, uses defaults.
        """
        self.llm_factory = llm_factory
        self.skill_mapping = skill_mapping or SKILL_MAPPING
        logger.info(
            f"GoalDrivenTeamFactory initialized with {len(self.skill_mapping)} skills"
        )

    async def parse_goal(self, goal: str) -> ParsedGoal:
        """Parse a natural language goal into structured components.

        Uses pattern matching first, falls back to LLM if needed.

        Args:
            goal: Natural language goal string.

        Returns:
            ParsedGoal with intent, domain, skills, and confidence.
        """
        # Normalize goal
        normalized = goal.lower().strip()

        # Phase 1: Pattern matching
        intent = self._match_intent(normalized)
        skills = self._extract_skills(normalized)
        domain = self._extract_domain(normalized)

        # Calculate confidence based on pattern matches
        confidence = self._calculate_confidence(intent, skills, domain)

        # Phase 2: LLM fallback if confidence is low
        if confidence < 0.7 and self.llm_factory:
            logger.debug(f"Low confidence ({confidence:.2f}), using LLM fallback")
            llm_result = await self._llm_parse(goal)
            if llm_result.confidence > confidence:
                return llm_result

        return ParsedGoal(
            intent=intent,
            domain=domain,
            skills=skills,
            confidence=confidence,
            raw_goal=goal,
            metadata={"method": "pattern" if confidence >= 0.7 else "pattern_low"},
        )

    async def create_team_from_goal(
        self,
        goal: str,
        name: str | None = None,
        mode: TeamMode | None = None,
    ) -> TeamConfig:
        """Create a team configuration from a natural language goal.

        This is the main entry point for goal-driven team creation.

        Args:
            goal: Natural language goal string.
            name: Optional team name. If None, generated from goal.
            mode: Optional team mode. If None, selected based on intent.

        Returns:
            TeamConfig ready for use with AgentTeamManager.
        """
        parsed = await self.parse_goal(goal)

        # Generate team name
        team_name = name or self._generate_team_name(parsed)

        # Select team mode based on intent
        team_mode = mode or self._select_mode(parsed.intent)

        # Create member configurations from skills
        members = self._create_members_from_skills(parsed.skills)

        # Ensure at least one member
        if not members:
            members = [self._create_default_member(parsed)]

        # Create leader for coordinate mode
        leader = None
        if team_mode == TeamMode.COORDINATE:
            leader = self._create_leader(parsed)

        config = TeamConfig(
            name=team_name,
            description=f"Team created from goal: {goal[:100]}",
            mode=team_mode,
            leader=leader,
            members=members,
        )

        logger.info(
            f"Created team config: name={team_name}, mode={team_mode.value}, "
            f"members={len(members)}, confidence={parsed.confidence:.2f}"
        )

        return config

    # ========================================================================
    # Pattern Matching Methods
    # ========================================================================

    def _match_intent(self, normalized_goal: str) -> str:
        """Match intent from normalized goal string.

        Args:
            normalized_goal: Lowercase, trimmed goal string.

        Returns:
            Intent string (review, build, test, fix, refactor, document, or analyze).
        """
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized_goal):
                    return intent
        return "analyze"  # Default intent

    def _extract_skills(self, normalized_goal: str) -> list[str]:
        """Extract required skills from normalized goal string.

        Args:
            normalized_goal: Lowercase, trimmed goal string.

        Returns:
            List of skill names found in the goal.
        """
        skills = set()

        for skill in self.skill_mapping:
            if skill in normalized_goal:
                skills.add(skill)

        # Check domain patterns for implied skills
        for domain, patterns in DOMAIN_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized_goal):
                    skills.add(domain)
                    break

        # Default skills based on intent
        if not skills:
            default_for_intent = {
                "review": {"quality"},
                "build": {"quality", "testing"},
                "test": {"testing"},
                "fix": {"debugging"},
                "refactor": {"refactoring"},
                "document": {"documentation"},
            }
            skills = default_for_intent.get("analyze", {"quality"})

        return sorted(skills)

    def _extract_domain(self, normalized_goal: str) -> str:
        """Extract domain from normalized goal string.

        Args:
            normalized_goal: Lowercase, trimmed goal string.

        Returns:
            Domain string.
        """
        for domain, patterns in DOMAIN_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized_goal):
                    return domain
        return "general"

    def _calculate_confidence(
        self, intent: str, skills: list[str], domain: str
    ) -> float:
        """Calculate confidence score for pattern matching results.

        Args:
            intent: Matched intent.
            skills: Extracted skills.
            domain: Extracted domain.

        Returns:
            Confidence score between 0.0 and 1.0.
        """
        score = 0.3  # Base confidence

        # Intent match adds confidence
        if intent != "analyze":
            score += 0.2

        # Each skill adds confidence
        score += min(len(skills) * 0.15, 0.3)

        # Domain match adds confidence
        if domain != "general":
            score += 0.2

        return min(score, 1.0)

    # ========================================================================
    # Team Creation Methods
    # ========================================================================

    def _create_members_from_skills(self, skills: list[str]) -> list[MemberConfig]:
        """Create member configurations from skill list.

        Args:
            skills: List of skill names.

        Returns:
            List of MemberConfig instances.
        """
        members = []

        for skill in skills:
            if skill in self.skill_mapping:
                config = self.skill_mapping[skill]
                members.append(
                    MemberConfig(
                        name=f"{skill}_specialist",
                        role=config.role,
                        model=config.model,
                        instructions=config.instructions,
                        tools=config.tools,
                        temperature=config.temperature,
                    )
                )

        return members

    def _create_leader(self, parsed: ParsedGoal) -> MemberConfig:
        """Create leader agent configuration.

        Args:
            parsed: Parsed goal with intent and skills.

        Returns:
            MemberConfig for the team leader.
        """
        return MemberConfig(
            name="coordinator",
            role=f"Coordinates {parsed.intent} tasks across specialists",
            model="sonnet",
            instructions=f"""You are a team coordinator for {parsed.intent} tasks.

Your responsibilities:
1. Analyze incoming requests and distribute tasks to specialists
2. Aggregate findings from team members
3. Synthesize results into coherent outputs
4. Ensure comprehensive coverage of the goal

Skills available: {', '.join(parsed.skills)}
Domain: {parsed.domain}""",
            tools=[],
            temperature=0.5,
        )

    def _create_default_member(self, parsed: ParsedGoal) -> MemberConfig:
        """Create a default member when no skills are matched.

        Args:
            parsed: Parsed goal.

        Returns:
            Default MemberConfig.
        """
        return MemberConfig(
            name="generalist",
            role="General purpose assistant",
            model="sonnet",
            instructions=f"""You are a general-purpose assistant helping with: {parsed.raw_goal}

Analyze the task and provide helpful, actionable guidance.""",
            tools=["search_code", "read_file"],
            temperature=0.7,
        )

    def _generate_team_name(self, parsed: ParsedGoal) -> str:
        """Generate a team name from parsed goal.

        Args:
            parsed: Parsed goal.

        Returns:
            Team name string.
        """
        domain = parsed.domain if parsed.domain != "general" else "task"
        intent = parsed.intent
        return f"{domain}_{intent}_team"

    def _select_mode(self, intent: str) -> TeamMode:
        """Select team mode based on intent.

        Args:
            intent: Goal intent.

        Returns:
            TeamMode enum value.
        """
        mode_for_intent = {
            "review": TeamMode.COORDINATE,
            "build": TeamMode.COORDINATE,
            "test": TeamMode.COORDINATE,
            "fix": TeamMode.ROUTE,
            "refactor": TeamMode.COORDINATE,
            "document": TeamMode.ROUTE,
            "analyze": TeamMode.BROADCAST,
        }
        return mode_for_intent.get(intent, TeamMode.COORDINATE)

    # ========================================================================
    # LLM Fallback Methods
    # ========================================================================

    async def _llm_parse(self, goal: str) -> ParsedGoal:
        """Use LLM to parse goal when pattern matching has low confidence.

        Args:
            goal: Original goal string.

        Returns:
            ParsedGoal from LLM analysis.
        """
        if not self.llm_factory:
            return ParsedGoal(
                intent="analyze",
                domain="general",
                skills=["quality"],
                confidence=0.3,
                raw_goal=goal,
            )

        try:
            prompt = f"""Analyze this task goal and extract:
1. Intent (review, build, test, fix, refactor, document, analyze)
2. Domain (security, performance, quality, testing, documentation, general)
3. Required skills (from: security, quality, performance, testing, documentation, refactoring, debugging)

Goal: {goal}

Respond in format:
INTENT: <intent>
DOMAIN: <domain>
SKILLS: <comma-separated skills>
CONFIDENCE: <0.0-1.0>"""

            model = self.llm_factory.create_model()
            response = await model.ainvoke(prompt)

            # Parse LLM response
            content = response.content if hasattr(response, "content") else str(response)
            return self._parse_llm_response(goal, content)

        except Exception as e:
            logger.warning(f"LLM parsing failed: {e}")
            return ParsedGoal(
                intent="analyze",
                domain="general",
                skills=["quality"],
                confidence=0.3,
                raw_goal=goal,
                metadata={"error": str(e)},
            )

    def _parse_llm_response(self, goal: str, response: str) -> ParsedGoal:
        """Parse LLM response into ParsedGoal.

        Args:
            goal: Original goal string.
            response: LLM response string.

        Returns:
            ParsedGoal instance.
        """
        intent = "analyze"
        domain = "general"
        skills = ["quality"]
        confidence = 0.5

        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("INTENT:"):
                intent = line.split(":", 1)[1].strip().lower()
            elif line.startswith("DOMAIN:"):
                domain = line.split(":", 1)[1].strip().lower()
            elif line.startswith("SKILLS:"):
                skills_str = line.split(":", 1)[1].strip()
                skills = [s.strip().lower() for s in skills_str.split(",")]
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

        return ParsedGoal(
            intent=intent,
            domain=domain,
            skills=skills,
            confidence=confidence,
            raw_goal=goal,
            metadata={"method": "llm"},
        )


__all__ = [
    "GoalDrivenTeamFactory",
    "ParsedGoal",
    "SkillConfig",
    "SKILL_MAPPING",
]
