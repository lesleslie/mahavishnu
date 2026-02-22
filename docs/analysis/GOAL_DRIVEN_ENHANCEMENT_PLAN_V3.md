# Goal-Driven Team Enhancement Plan v3.0

**Date:** 2026-02-21
**Status:** Final After 8-Person Review (5 Committee + 3 Specialists)
**Previous Versions:** v1.0 (superseded), v2.0 (superseded)

---

## Executive Summary

This final plan incorporates feedback from 8 reviewers across two review cycles:

| Review Cycle | Reviewers | Key Changes |
|--------------|-----------|-------------|
| **5-Person Committee** | Backend, PM, AI Engineer, Code Reviewer, Architect | Effort reduction 60%, extend StatisticalRouter vs new learning |
| **3-Person Specialists** | Test Automation, Documentation, DevOps | Add tests, docs, feature flags, metrics |

**Total Effort:** 14-15 days (vs 25-40 days in v1.0, 10 days in v2.0)

---

## Changes from v2.0

| Aspect | v2.0 | v3.0 |
|--------|------|------|
| Test coverage | Basic MCP tests | **80%+ coverage with factory, CLI, integration tests** |
| Documentation | Mentioned | **Required deliverables with examples** |
| Feature flags | None | **goal_teams.enabled flag** |
| Metrics | None | **Prometheus metrics for parsing/creation** |
| LLM fallback | Basic | **Circuit breaker with pattern fallback** |
| Phase 1 effort | 1 week | **1.5 weeks** (includes expanded tests) |

---

## Phase 1: Foundation + Core (1.5 weeks)

### Day 1-2: Infrastructure

#### A. Error Codes

**File:** `mahavishnu/core/errors.py`

```python
class ErrorCode(StrEnum):
    # ... existing codes ...

    # Team creation errors (MHV-460 to MHV-479)
    TEAM_CREATION_FAILED = "MHV-460"
    TEAM_GOAL_PARSING_FAILED = "MHV-461"
    TEAM_SKILL_NOT_FOUND = "MHV-462"
    TEAM_MODE_INVALID = "MHV-463"
    TEAM_LLM_UNAVAILABLE = "MHV-464"
    TEAM_ADAPTER_UNAVAILABLE = "MHV-465"
    TEAM_EXECUTION_FAILED = "MHV-466"
    TEAM_TIMEOUT = "MHV-467"

    # Learning system errors (MHV-480 to MHV-499)
    LEARNING_STORAGE_FAILED = "MHV-480"
    LEARNING_EMBEDDING_FAILED = "MHV-481"
    LEARNING_INSUFFICIENT_DATA = "MHV-482"
```

#### B. Dependency Injection Context

**File:** `mahavishnu/core/context.py`

```python
"""Dependency injection context for Mahavishnu components.

Provides context variables for accessing shared components without
global state or tight coupling.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # Avoid circular imports

# Context variables for dependency injection
_current_llm_factory: ContextVar[Any] = ContextVar("llm_factory")
_current_agno_adapter: ContextVar[Any] = ContextVar("agno_adapter")


class ContextNotInitializedError(RuntimeError):
    """Raised when context is accessed before initialization."""

    def __init__(self, component: str) -> None:
        super().__init__(
            f"{component} not available in current context. "
            f"Ensure MahavishnuApp is initialized."
        )


def get_llm_factory() -> Any:
    """Get the current LLM factory from context.

    Returns:
        LLMProviderFactory instance.

    Raises:
        ContextNotInitializedError: If context not set.
    """
    try:
        return _current_llm_factory.get()
    except LookupError as e:
        raise ContextNotInitializedError("LLM factory") from e


def get_agno_adapter() -> Any:
    """Get the current Agno adapter from context.

    Returns:
        AgnoAdapter instance.

    Raises:
        ContextNotInitializedError: If context not set.
    """
    try:
        return _current_agno_adapter.get()
    except LookupError as e:
        raise ContextNotInitializedError("Agno adapter") from e


def set_app_context(
    llm_factory: Any,
    agno_adapter: Any,
) -> None:
    """Set the application context for dependency injection.

    Called once during MahavishnuApp initialization.

    Args:
        llm_factory: LLMProviderFactory instance.
        agno_adapter: AgnoAdapter instance.
    """
    _current_llm_factory.set(llm_factory)
    _current_agno_adapter.set(agno_adapter)


def is_context_initialized() -> bool:
    """Check if the app context has been initialized."""
    try:
        _current_llm_factory.get()
        _current_agno_adapter.get()
        return True
    except LookupError:
        return False
```

#### C. Configuration

**File:** `settings/mahavishnu.yaml` (additions)

```yaml
# Goal-driven teams configuration
goal_teams:
  enabled: true  # Feature flag for rollout

  goal_parsing:
    min_goal_length: 10
    max_goal_length: 2000
    llm_fallback_enabled: true
    pattern_confidence_threshold: 0.7
    circuit_breaker:
      failure_threshold: 5
      recovery_timeout_seconds: 60

  limits:
    max_teams_per_user: 50
    max_members_per_team: 10
    team_ttl_hours: 168  # 1 week

  # Learning system (Phase 3)
  learning:
    enabled: false
    min_executions_for_learning: 100
```

### Day 3-5: MCP Tools

**File:** `mahavishnu/mcp/tools/goal_team_tools.py`

(See v2.0 for full implementation - unchanged)

### Day 5-7: CLI Commands

**File:** `mahavishnu/cli/team_cli.py`

(See v2.0 for full implementation - unchanged)

### Day 5-10: Test Suite (Parallel with CLI)

#### Test File Structure

```
tests/
├── unit/
│   ├── test_goal_team_factory.py     # NEW - Core logic
│   ├── test_goal_team_tools.py       # EXPAND - MCP tools
│   ├── test_team_cli.py              # NEW - CLI commands
│   ├── test_prompt_templates.py      # NEW - Templates
│   └── test_context.py               # NEW - DI context
├── integration/
│   └── test_goal_team_integration.py # NEW - E2E tests
├── property/
│   └── test_goal_parsing_properties.py # NEW - Hypothesis
└── fixtures/
    └── team_fixtures.py              # NEW - Shared fixtures
```

#### Core Factory Tests

**File:** `tests/unit/test_goal_team_factory.py`

```python
"""Unit tests for GoalDrivenTeamFactory."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from mahavishnu.engines.goal_team_factory import (
    GoalDrivenTeamFactory,
    ParsedGoal,
    SkillConfig,
    SKILL_MAPPING,
)
from mahavishnu.engines.agno_teams.config import TeamMode


class TestGoalDrivenTeamFactoryInit:
    """Tests for factory initialization."""

    def test_init_with_defaults(self):
        """Test default initialization."""
        factory = GoalDrivenTeamFactory()
        assert factory.llm_factory is None
        assert factory.skill_mapping == SKILL_MAPPING

    def test_init_with_custom_skills(self):
        """Test initialization with custom skill mapping."""
        custom_skills = {
            "custom": SkillConfig(
                role="Custom role",
                instructions="Custom instructions",
                tools=["tool1"],
            )
        }
        factory = GoalDrivenTeamFactory(skill_mapping=custom_skills)
        assert factory.skill_mapping == custom_skills


class TestIntentMatching:
    """Tests for intent pattern matching."""

    @pytest.mark.parametrize("goal,expected_intent", [
        ("Review this code for issues", "review"),
        ("Analyze the codebase", "review"),
        ("Check for bugs", "review"),
        ("Audit the security", "review"),
        ("Build a REST API", "build"),
        ("Create a new feature", "build"),
        ("Implement user auth", "build"),
        ("Write unit tests", "test"),
        ("Test the auth module", "test"),
        ("Add test coverage", "test"),
        ("Fix the login bug", "fix"),
        ("Debug the error", "fix"),
        ("Resolve the issue", "fix"),
        ("Refactor the database layer", "refactor"),
        ("Clean up the code", "refactor"),
        ("Improve performance", "refactor"),
        ("Document this function", "document"),
        ("Add docstrings", "document"),
        ("Write README", "document"),
    ])
    def test_intent_matching_various_goals(self, goal, expected_intent):
        """Test intent matching for various goal types."""
        factory = GoalDrivenTeamFactory()
        result = factory._match_intent(goal.lower())
        assert result == expected_intent

    def test_unknown_intent_defaults_to_analyze(self):
        """Test unknown goals default to analyze."""
        factory = GoalDrivenTeamFactory()
        result = factory._match_intent("xyzabc unknown words")
        assert result == "analyze"


class TestSkillExtraction:
    """Tests for skill extraction from goals."""

    def test_security_skill_extraction(self):
        """Test security skills extracted from goal."""
        factory = GoalDrivenTeamFactory()
        skills = factory._extract_skills("review this code for security vulnerabilities")
        assert "security" in skills

    def test_performance_skill_extraction(self):
        """Test performance skills extracted from goal."""
        factory = GoalDrivenTeamFactory()
        skills = factory._extract_skills("optimize performance and speed")
        assert "performance" in skills

    def test_multiple_skills_extraction(self):
        """Test multiple skills extracted from complex goal."""
        factory = GoalDrivenTeamFactory()
        skills = factory._extract_skills(
            "review code for security issues and performance bottlenecks"
        )
        assert "security" in skills
        assert "performance" in skills

    def test_default_skill_when_none_matched(self):
        """Test default skill when no keywords match."""
        factory = GoalDrivenTeamFactory()
        skills = factory._extract_skills("do something generic")
        # Should have some default
        assert len(skills) >= 1


class TestDomainExtraction:
    """Tests for domain extraction."""

    def test_security_domain(self):
        """Test security domain detection."""
        factory = GoalDrivenTeamFactory()
        domain = factory._extract_domain("check for xss and sql injection")
        assert domain == "security"

    def test_general_domain_default(self):
        """Test general domain as default."""
        factory = GoalDrivenTeamFactory()
        domain = factory._extract_domain("do something unrelated")
        assert domain == "general"


class TestConfidenceCalculation:
    """Tests for confidence calculation."""

    def test_high_confidence_with_clear_match(self):
        """Test high confidence when patterns clearly match."""
        factory = GoalDrivenTeamFactory()
        confidence = factory._calculate_confidence(
            intent="review",
            skills=["security"],
            domain="security",
        )
        assert confidence >= 0.7

    def test_low_confidence_with_no_matches(self):
        """Test low confidence when nothing matches."""
        factory = GoalDrivenTeamFactory()
        confidence = factory._calculate_confidence(
            intent="analyze",
            skills=[],
            domain="general",
        )
        assert confidence < 0.5


class TestParseGoal:
    """Tests for parse_goal method."""

    @pytest.mark.asyncio
    async def test_parse_goal_returns_parsed_goal(self):
        """Test parse_goal returns ParsedGoal instance."""
        factory = GoalDrivenTeamFactory()
        result = await factory.parse_goal("Review code for security issues")

        assert isinstance(result, ParsedGoal)
        assert result.intent == "review"
        assert "security" in result.skills
        assert result.confidence > 0
        assert result.raw_goal == "Review code for security issues"

    @pytest.mark.asyncio
    async def test_parse_goal_pattern_matching_used(self):
        """Test pattern matching is used for common goals."""
        factory = GoalDrivenTeamFactory()
        result = await factory.parse_goal("Review code for security issues")

        # Pattern matching should have high confidence
        assert result.confidence >= 0.7
        assert result.metadata.get("method") == "pattern"

    @pytest.mark.asyncio
    async def test_parse_goal_llm_fallback(self):
        """Test LLM fallback for ambiguous goals."""
        mock_llm = MagicMock()
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=MagicMock(
                content="INTENT: analyze\nDOMAIN: custom\nSKILLS: quality\nCONFIDENCE: 0.8"
            )
        )
        mock_llm.create_model = MagicMock(return_value=mock_model)

        factory = GoalDrivenTeamFactory(llm_factory=mock_llm)

        # Use a very ambiguous goal that won't match patterns
        result = await factory.parse_goal("xyzabc lorem ipsum dolor")

        # Should still return a valid result
        assert isinstance(result, ParsedGoal)
        assert result.intent is not None


class TestCreateTeamFromGoal:
    """Tests for create_team_from_goal method."""

    @pytest.mark.asyncio
    async def test_create_team_basic(self):
        """Test basic team creation."""
        factory = GoalDrivenTeamFactory()
        config = await factory.create_team_from_goal(
            "Review code for security issues"
        )

        assert config.name is not None
        assert config.mode in TeamMode
        assert len(config.members) >= 1

    @pytest.mark.asyncio
    async def test_create_team_coordinate_mode_has_leader(self):
        """Test coordinate mode creates leader."""
        factory = GoalDrivenTeamFactory()
        config = await factory.create_team_from_goal(
            "Review code for security issues"
        )

        # Review intent defaults to coordinate mode
        if config.mode == TeamMode.COORDINATE:
            assert config.leader is not None

    @pytest.mark.asyncio
    async def test_create_team_custom_name(self):
        """Test custom team name."""
        factory = GoalDrivenTeamFactory()
        config = await factory.create_team_from_goal(
            goal="Review code",
            name="my_custom_team",
        )

        assert config.name == "my_custom_team"

    @pytest.mark.asyncio
    async def test_create_team_custom_mode(self):
        """Test custom team mode."""
        factory = GoalDrivenTeamFactory()
        config = await factory.create_team_from_goal(
            goal="Review code",
            mode=TeamMode.BROADCAST,
        )

        assert config.mode == TeamMode.BROADCAST

    @pytest.mark.asyncio
    async def test_create_team_security_goal_has_security_member(self):
        """Test security goal creates security member."""
        factory = GoalDrivenTeamFactory()
        config = await factory.create_team_from_goal(
            "Review code for security vulnerabilities"
        )

        member_names = [m.name for m in config.members]
        assert any("security" in name.lower() for name in member_names)


class TestModeSelection:
    """Tests for automatic mode selection."""

    def test_review_intent_selects_coordinate(self):
        """Test review intent selects coordinate mode."""
        factory = GoalDrivenTeamFactory()
        mode = factory._select_mode("review")
        assert mode == TeamMode.COORDINATE

    def test_fix_intent_selects_route(self):
        """Test fix intent selects route mode."""
        factory = GoalDrivenTeamFactory()
        mode = factory._select_mode("fix")
        assert mode == TeamMode.ROUTE

    def test_analyze_intent_selects_broadcast(self):
        """Test analyze intent selects broadcast mode."""
        factory = GoalDrivenTeamFactory()
        mode = factory._select_mode("analyze")
        assert mode == TeamMode.BROADCAST


class TestLLMFallback:
    """Tests for LLM fallback parsing."""

    @pytest.mark.asyncio
    async def test_llm_parse_success(self):
        """Test successful LLM parsing."""
        mock_llm = MagicMock()
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=MagicMock(
                content="INTENT: review\nDOMAIN: security\nSKILLS: security\nCONFIDENCE: 0.9"
            )
        )
        mock_llm.create_model = MagicMock(return_value=mock_model)

        factory = GoalDrivenTeamFactory(llm_factory=mock_llm)
        result = await factory._llm_parse("Custom goal")

        assert result.intent == "review"
        assert result.domain == "security"
        assert result.skills == ["security"]
        assert result.confidence == 0.9

    def test_parse_llm_response(self):
        """Test parsing LLM response format."""
        factory = GoalDrivenTeamFactory()
        response = """INTENT: build
DOMAIN: api
SKILLS: quality, testing
CONFIDENCE: 0.85"""

        result = factory._parse_llm_response("Build an API", response)

        assert result.intent == "build"
        assert result.domain == "api"
        assert "quality" in result.skills
        assert "testing" in result.skills
        assert result.confidence == 0.85

    def test_parse_llm_response_malformed(self):
        """Test handling malformed LLM response."""
        factory = GoalDrivenTeamFactory()
        response = "This is not the expected format"

        result = factory._parse_llm_response("Some goal", response)

        # Should return defaults
        assert result.intent == "analyze"
        assert result.domain == "general"
```

#### CLI Tests

**File:** `tests/unit/test_team_cli.py`

```python
"""Tests for team CLI commands."""

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock

from mahavishnu.cli.team_cli import app

runner = CliRunner()


class TestTeamCreateCommand:
    """Tests for team create command."""

    @patch("mahavishnu.cli.team_cli.get_llm_factory")
    def test_create_team_success(self, mock_get_llm):
        """Test successful team creation."""
        mock_get_llm.return_value = MagicMock()

        result = runner.invoke(app, [
            "create",
            "--goal", "Review code for security issues",
            "--name", "test_team",
        ])

        assert result.exit_code == 0
        assert "Parsed Goal" in result.output

    @patch("mahavishnu.cli.team_cli.get_llm_factory")
    def test_create_team_dry_run(self, mock_get_llm):
        """Test dry run shows config without creating."""
        mock_get_llm.return_value = MagicMock()

        result = runner.invoke(app, [
            "create",
            "--goal", "Review code for security issues",
            "--dry-run",
        ])

        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_create_team_invalid_mode(self):
        """Test error for invalid mode."""
        result = runner.invoke(app, [
            "create",
            "--goal", "Review code",
            "--mode", "invalid_mode",
        ])

        assert result.exit_code == 1
        assert "Invalid mode" in result.output

    @patch("mahavishnu.cli.team_cli.get_llm_factory")
    def test_create_team_run_without_task(self, mock_get_llm):
        """Test error when --run without --task."""
        mock_get_llm.return_value = MagicMock()

        result = runner.invoke(app, [
            "create",
            "--goal", "Review code",
            "--run",
        ])

        assert result.exit_code == 1

    @patch("mahavishnu.cli.team_cli.get_llm_factory")
    def test_create_team_verbose_output(self, mock_get_llm):
        """Test verbose output shows more details."""
        mock_get_llm.return_value = MagicMock()

        result = runner.invoke(app, [
            "create",
            "--goal", "Review code for security issues",
            "--verbose",
        ])

        assert result.exit_code == 0
        assert "Member Details" in result.output


class TestTeamListCommand:
    """Tests for team list command."""

    @patch("mahavishnu.cli.team_cli.get_agno_adapter")
    def test_list_teams_empty(self, mock_get_adapter):
        """Test list with no teams."""
        mock_adapter = MagicMock()
        mock_adapter.list_teams = AsyncMock(return_value=[])
        mock_get_adapter.return_value = mock_adapter

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "No active teams" in result.output

    @patch("mahavishnu.cli.team_cli.get_agno_adapter")
    def test_list_teams_with_teams(self, mock_get_adapter):
        """Test list with existing teams."""
        mock_adapter = MagicMock()
        mock_adapter.list_teams = AsyncMock(return_value=["team_1", "team_2"])
        mock_adapter.get_team_config = AsyncMock(
            return_value=MagicMock(name="Test Team", mode=MagicMock(value="coordinate"), members=[])
        )
        mock_get_adapter.return_value = mock_adapter

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "team_1" in result.output


class TestTeamParseCommand:
    """Tests for team parse command."""

    @patch("mahavishnu.cli.team_cli.get_llm_factory")
    def test_parse_goal_success(self, mock_get_llm):
        """Test successful goal parsing."""
        mock_get_llm.return_value = MagicMock()

        result = runner.invoke(app, [
            "parse",
            "Review code for security issues",
        ])

        assert result.exit_code == 0
        assert "Intent" in result.output
        assert "Skills" in result.output
```

### Day 8-10: Documentation (Parallel)

#### User Guide

**File:** `docs/GOAL_DRIVEN_TEAMS.md`

```markdown
# Goal-Driven Teams

Create agent teams from natural language descriptions.

## Quick Start

```bash
# Preview what team would be created
mahavishnu team create --goal "Review code for security issues" --dry-run

# Create a team
mahavishnu team create --goal "Review code for security issues"

# Create and run immediately
mahavishnu team create --goal "Test the auth module" --run --task "Test login flow"
```

## How It Works

1. **Parse Goal**: Analyze natural language to extract intent and required skills
2. **Select Mode**: Choose collaboration mode based on intent
3. **Create Members**: Assign specialists based on detected skills
4. **Execute**: Run the team on your task

## Writing Effective Goals

### Goal Structure

```
[Intent] + [Subject] + [Domain/Focus]
```

### Examples by Intent

| Intent | Example Goal | Skills Assigned |
|--------|--------------|-----------------|
| **Review** | "Review authentication code for security vulnerabilities" | security, quality |
| **Build** | "Build a REST API for user management" | quality |
| **Test** | "Generate unit tests for the payment module" | testing |
| **Fix** | "Fix the null pointer exception in login" | debugging |
| **Refactor** | "Refactor the database layer for better performance" | refactoring, performance |
| **Document** | "Document the REST API endpoints" | documentation |

### Tips

- **Be specific**: "Review Python code for SQL injection" > "Review code"
- **Include domain keywords**: security, performance, testing, etc.
- **Keep it concise**: 10-2000 characters

## Collaboration Modes

| Mode | When Used | Behavior |
|------|-----------|----------|
| **coordinate** | Review, Build, Test | Leader distributes tasks to specialists |
| **route** | Fix, Document | Single specialist handles the task |
| **broadcast** | Analyze | All members work simultaneously |

## Available Skills

| Skill | Role | Tools |
|-------|------|-------|
| **security** | Security vulnerability specialist | search_code, read_file, grep |
| **quality** | Code quality engineer | search_code, read_file, run_linter |
| **performance** | Performance optimization specialist | search_code, read_file, profile |
| **testing** | Test engineer | search_code, read_file, run_tests |
| **documentation** | Technical writer | search_code, read_file, write_file |
| **refactoring** | Refactoring specialist | search_code, read_file, write_file |
| **debugging** | Debugging specialist | search_code, read_file, run_tests, debugger |
| **devops** | DevOps and CI/CD specialist | search_code, read_file, run_command |
| **api_design** | API design specialist | search_code, read_file, openapi_spec |

## MCP Tools

### team_from_goal

Create a team from a natural language goal.

```python
result = await team_from_goal(
    goal="Review code for security issues",
    name="security_review",
    mode="coordinate",
    auto_run=True,
    task="Review src/auth/*.py",
)
```

### parse_goal

Parse a goal without creating a team (for debugging).

```python
parsed = await parse_goal("Review code for security issues")
# Returns: intent, domain, skills, confidence
```

### list_team_skills

List all available skills.

```python
skills = await list_team_skills()
```

## Error Handling

| Error Code | Description | Resolution |
|------------|-------------|------------|
| MHV-460 | Team creation failed | Check adapter availability |
| MHV-461 | Goal parsing failed | Rephrase goal with more context |
| MHV-463 | Invalid mode | Use: coordinate, route, broadcast, collaborate |
| MHV-464 | LLM unavailable | Pattern-only fallback used automatically |

## Examples

### Security Review

```bash
mahavishnu team create \
  --goal "Review authentication code for security vulnerabilities including SQL injection and XSS" \
  --run \
  --task "Review src/auth/"
```

### API Development

```bash
mahavishnu team create \
  --goal "Design and document a REST API for user management" \
  --mode coordinate \
  --name api_team
```

### Performance Analysis

```bash
mahavishnu team create \
  --goal "Analyze database queries for performance bottlenecks" \
  --run \
  --task "Analyze queries in src/db/"
```
```

#### Tutorial Example

**File:** `examples/goal_driven_team_tutorial.py`

```python
#!/usr/bin/env python
"""Goal-Driven Teams Tutorial

This example demonstrates the complete workflow for creating and
using goal-driven teams in Mahavishnu.

Run with: python examples/goal_driven_team_tutorial.py
"""

import asyncio


async def main():
    """Run the tutorial."""
    print("=" * 60)
    print("Goal-Driven Teams Tutorial")
    print("=" * 60)

    # Step 1: Parse a goal to understand what team would be created
    print("\n[Step 1] Parsing Goal")
    print("-" * 40)

    from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

    factory = GoalDrivenTeamFactory()

    goal = "Review Python code for security vulnerabilities and suggest fixes"
    print(f"Goal: {goal}")

    parsed = await factory.parse_goal(goal)

    print(f"\nParsed result:")
    print(f"  Intent: {parsed.intent}")
    print(f"  Domain: {parsed.domain}")
    print(f"  Skills: {', '.join(parsed.skills)}")
    print(f"  Confidence: {parsed.confidence:.0%}")
    print(f"  Method: {parsed.metadata.get('method')}")

    # Step 2: Create a team configuration
    print("\n[Step 2] Creating Team Configuration")
    print("-" * 40)

    team_config = await factory.create_team_from_goal(goal)

    print(f"Team name: {team_config.name}")
    print(f"Mode: {team_config.mode.value}")
    print(f"Members: {len(team_config.members)}")

    for member in team_config.members:
        print(f"\n  Member: {member.name}")
        print(f"    Role: {member.role}")
        print(f"    Model: {member.model}")
        print(f"    Tools: {', '.join(member.tools)}")

    # Step 3: Show dry-run behavior
    print("\n[Step 3] Dry Run Mode")
    print("-" * 40)

    print("With --dry-run, you can preview the team without creating it:")
    print("  mahavishnu team create --goal \"...\" --dry-run")

    # Step 4: Show different goal types
    print("\n[Step 4] Different Goal Types")
    print("-" * 40)

    goals = [
        ("Review code for security issues", "review"),
        ("Build a REST API for users", "build"),
        ("Test the authentication module", "test"),
        ("Fix the null pointer exception", "fix"),
        ("Refactor the database layer", "refactor"),
        ("Document the API endpoints", "document"),
    ]

    for goal_text, expected_intent in goals:
        parsed = await factory.parse_goal(goal_text)
        match = "✓" if parsed.intent == expected_intent else "✗"
        print(f"  {match} \"{goal_text[:40]}...\" -> {parsed.intent}")

    # Step 5: Show MCP tool usage
    print("\n[Step 5] MCP Tool Usage")
    print("-" * 40)

    print("To use via MCP (after 'mahavishnu mcp start'):")
    print("""
    # Create team
    result = await team_from_goal(
        goal="Review code for security issues",
        auto_run=True,
        task="Review src/auth/",
    )
    print(f"Team ID: {result['team_id']}")
    print(f"Success: {result['run_result']['success']}")
    """)

    print("\n" + "=" * 60)
    print("Tutorial complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Phase 2: Polish (4 days)

### Day 11-12: Metrics & Observability

#### Prometheus Metrics

**File:** `mahavishnu/core/goal_team_metrics.py`

```python
"""Prometheus metrics for goal-driven teams."""

from prometheus_client import Counter, Histogram, Gauge, Summary

# Counters
TEAMS_CREATED = Counter(
    "mahavishnu_goal_teams_created_total",
    "Total teams created",
    ["mode", "parsing_method"],
)

GOAL_PARSING_TOTAL = Counter(
    "mahavishnu_goal_parsing_total",
    "Total goal parsing attempts",
    ["method", "success"],
)

LLM_FALLBACK_TOTAL = Counter(
    "mahavishnu_llm_fallback_total",
    "Total LLM fallback events",
    ["reason"],
)

TEAM_EXECUTION_TOTAL = Counter(
    "mahavishnu_team_execution_total",
    "Total team executions",
    ["team_id", "success"],
)

# Histograms
GOAL_PARSING_LATENCY = Histogram(
    "mahavishnu_goal_parsing_latency_seconds",
    "Goal parsing latency",
    ["method"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

TEAM_CREATION_LATENCY = Histogram(
    "mahavishnu_team_creation_latency_seconds",
    "Team creation latency",
    ["mode"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

PARSING_CONFIDENCE = Histogram(
    "mahavishnu_goal_parsing_confidence",
    "Parsing confidence distribution",
    ["method"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# Gauges
ACTIVE_TEAMS = Gauge(
    "mahavishnu_goal_teams_active",
    "Currently active teams",
    ["mode"],
)
```

#### Health Check

**File:** Add to `mahavishnu/mcp/tools/goal_team_tools.py`

```python
@mcp.tool()
async def health_check_goal_teams() -> dict[str, Any]:
    """Health check for goal-driven teams feature.

    Returns:
        Health status and diagnostics.
    """
    from mahavishnu.core.context import is_context_initialized

    checks = {
        "context_initialized": is_context_initialized(),
        "pattern_parser_functional": True,  # Always functional
    }

    # Test pattern parsing
    factory = GoalDrivenTeamFactory(llm_factory=None)
    try:
        parsed = await factory.parse_goal("review code for security")
        checks["pattern_parser_functional"] = parsed.intent == "review"
    except Exception:
        checks["pattern_parser_functional"] = False

    all_healthy = all(checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks,
    }
```

### Day 13-14: DevOps & Templates

#### Prompt Templates

(See v2.0 for PromptTemplateManager implementation)

#### WebSocket Broadcasting

(See v2.0 for WebSocket additions)

---

## Phase 3: Learning System (Future)

After 100+ team executions:

1. Extend StatisticalRouter for team configs
2. Multi-dimensional quality scoring
3. A/B testing for configurations

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Goal parsing accuracy | > 85% | Manual review of 100 samples |
| Team creation latency | < 500ms P95 | Prometheus metrics |
| Test coverage | > 80% | pytest-cov |
| CLI adoption | > 10 uses/week | Command analytics |

---

## Summary

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| **Phase 1** | 1.5 weeks | MCP + CLI + Tests + Docs |
| **Phase 2** | 4 days | Metrics + Templates + WebSocket |
| **Phase 3** | Future | Learning (after 100+ executions) |

**Total: 14-15 days** to production-ready feature

---

## Checklist

### Phase 1

- [ ] Add error codes (MHV-460 to MHV-482)
- [ ] Create context.py DI module
- [ ] Add goal_teams config to settings
- [ ] Implement MCP tools (team_from_goal, parse_goal, list_team_skills)
- [ ] Implement CLI commands (create, list, parse)
- [ ] Write factory unit tests
- [ ] Write CLI tests
- [ ] Write integration tests
- [ ] Create user guide
- [ ] Create tutorial example

### Phase 2

- [ ] Add Prometheus metrics
- [ ] Add health check endpoint
- [ ] Implement PromptTemplateManager
- [ ] Add WebSocket broadcasts
- [ ] Add devops and api_design skills

### Phase 3 (Future)

- [ ] Extend StatisticalRouter for teams
- [ ] Add quality scoring integration
- [ ] Implement A/B testing

---

**Document Version:** 3.0
**Reviewed By:** 8 specialists (5 committee + 3 specialists)
**Status:** Ready for implementation
