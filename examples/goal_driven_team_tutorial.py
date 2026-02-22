#!/usr/bin/env python3
"""Goal-Driven Teams Tutorial.

This tutorial demonstrates how to use the GoalDrivenTeamFactory to create
intelligent multi-agent teams from natural language goals.

Run this example:
    python examples/goal_driven_team_tutorial.py

Requirements:
    - Mahavishnu installed: pip install -e ".[dev]"
    - Agno SDK installed: pip install agno>=2.5.0
    - Optional: Ollama running for local LLM (http://localhost:11434)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Mock Classes for Demo (Replace with real imports in production)
# ============================================================================


@dataclass
class MockParsedGoal:
    """Mock parsed goal for demonstration."""

    intent: str
    domain: str
    skills: list[str]
    confidence: float
    raw_goal: str
    metadata: dict[str, Any]


@dataclass
class MockMemberConfig:
    """Mock member configuration."""

    name: str
    role: str
    model: str
    instructions: str
    tools: list[str]
    temperature: float


@dataclass
class MockTeamConfig:
    """Mock team configuration."""

    name: str
    description: str
    mode: str
    leader: MockMemberConfig | None
    members: list[MockMemberConfig]


# ============================================================================
# Tutorial Step 1: Understanding Goal Parsing
# ============================================================================


async def tutorial_step_1_basic_parsing():
    """Step 1: Basic goal parsing without LLM fallback.

    This demonstrates pattern matching for common goals.
    Pattern matching is fast and free - no API calls required.
    """
    print("\n" + "=" * 70)
    print("STEP 1: Basic Goal Parsing (Pattern Matching)")
    print("=" * 70)

    # In production, import from:
    # from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

    # For demo, we'll simulate the parsing logic
    goals = [
        "Review this code for security vulnerabilities",
        "Build a REST API with authentication",
        "Test the payment processing module",
        "Fix the database connection bug",
        "Refactor the user service for better maintainability",
        "Document the authentication workflow",
        "Analyze performance bottlenecks",
    ]

    print("\nParsing various goal types:\n")

    for goal in goals:
        parsed = simulate_parse_goal(goal)
        print(f"Goal: {goal}")
        print(f"  Intent:    {parsed.intent}")
        print(f"  Domain:    {parsed.domain}")
        print(f"  Skills:    {parsed.skills}")
        print(f"  Confidence: {parsed.confidence:.2f}")
        print()


def simulate_parse_goal(goal: str) -> MockParsedGoal:
    """Simulate goal parsing for demonstration.

    In production, use:
        factory = GoalDrivenTeamFactory()
        parsed = await factory.parse_goal(goal)
    """
    goal_lower = goal.lower()

    # Detect intent
    intent = "analyze"  # default
    if any(w in goal_lower for w in ["review", "check", "audit"]):
        intent = "review"
    elif any(w in goal_lower for w in ["build", "create", "implement"]):
        intent = "build"
    elif any(w in goal_lower for w in ["test", "testing"]):
        intent = "test"
    elif any(w in goal_lower for w in ["fix", "bug", "error", "debug"]):
        intent = "fix"
    elif any(w in goal_lower for w in ["refactor", "clean", "improve"]):
        intent = "refactor"
    elif any(w in goal_lower for w in ["document", "docs", "readme"]):
        intent = "document"

    # Detect skills
    skills = []
    if "security" in goal_lower or "auth" in goal_lower:
        skills.append("security")
    if "performance" in goal_lower or "bottleneck" in goal_lower:
        skills.append("performance")
    if "test" in goal_lower:
        skills.append("testing")
    if "document" in goal_lower:
        skills.append("documentation")
    if "refactor" in goal_lower:
        skills.append("refactoring")
    if "bug" in goal_lower or "fix" in goal_lower:
        skills.append("debugging")

    # Default skill based on intent
    if not skills:
        intent_skill_map = {
            "review": ["quality"],
            "build": ["quality", "testing"],
            "test": ["testing"],
            "fix": ["debugging"],
            "refactor": ["refactoring"],
            "document": ["documentation"],
            "analyze": ["quality"],
        }
        skills = intent_skill_map.get(intent, ["quality"])

    # Detect domain
    domain = "general"
    if "security" in goal_lower:
        domain = "security"
    elif "performance" in goal_lower:
        domain = "performance"
    elif "test" in goal_lower:
        domain = "testing"
    elif "api" in goal_lower:
        domain = "api"

    # Calculate confidence
    confidence = 0.3
    if intent != "analyze":
        confidence += 0.2
    confidence += min(len(skills) * 0.15, 0.3)
    if domain != "general":
        confidence += 0.2

    return MockParsedGoal(
        intent=intent,
        domain=domain,
        skills=skills,
        confidence=min(confidence, 1.0),
        raw_goal=goal,
        metadata={"method": "pattern"},
    )


# ============================================================================
# Tutorial Step 2: Creating Teams from Goals
# ============================================================================


async def tutorial_step_2_create_team():
    """Step 2: Create a team configuration from a goal.

    The factory generates a complete TeamConfig with:
    - Team name based on goal
    - Appropriate collaboration mode
    - Leader agent (for coordinate mode)
    - Member agents with skill-specific instructions
    """
    print("\n" + "=" * 70)
    print("STEP 2: Create Team from Goal")
    print("=" * 70)

    goal = "Review this code for security vulnerabilities and performance issues"

    print(f"\nGoal: {goal}\n")

    # In production:
    # factory = GoalDrivenTeamFactory()
    # team_config = await factory.create_team_from_goal(goal)

    # Simulate team creation
    parsed = simulate_parse_goal(goal)
    team_config = simulate_create_team(parsed)

    print("Generated Team Configuration:")
    print(f"  Name:        {team_config.name}")
    print(f"  Description: {team_config.description[:60]}...")
    print(f"  Mode:        {team_config.mode}")

    if team_config.leader:
        print(f"\n  Leader Agent:")
        print(f"    Name:         {team_config.leader.name}")
        print(f"    Role:         {team_config.leader.role}")
        print(f"    Model:        {team_config.leader.model}")
        print(f"    Temperature:  {team_config.leader.temperature}")

    print(f"\n  Member Agents ({len(team_config.members)}):")
    for member in team_config.members:
        print(f"    - {member.name}")
        print(f"      Role: {member.role}")
        print(f"      Tools: {', '.join(member.tools)}")


def simulate_create_team(parsed: MockParsedGoal) -> MockTeamConfig:
    """Simulate team creation from parsed goal.

    In production, use:
        team_config = await factory.create_team_from_goal(parsed.raw_goal)
    """
    # Map intent to mode
    mode_map = {
        "review": "coordinate",
        "build": "coordinate",
        "test": "coordinate",
        "fix": "route",
        "refactor": "coordinate",
        "document": "route",
        "analyze": "broadcast",
    }
    mode = mode_map.get(parsed.intent, "coordinate")

    # Generate team name
    domain = parsed.domain if parsed.domain != "general" else "task"
    team_name = f"{domain}_{parsed.intent}_team"

    # Create skill-based members
    skill_configs = {
        "security": MockMemberConfig(
            name="security_specialist",
            role="Security vulnerability specialist",
            model="sonnet",
            instructions="Analyze for security vulnerabilities...",
            tools=["search_code", "read_file", "grep"],
            temperature=0.3,
        ),
        "performance": MockMemberConfig(
            name="performance_specialist",
            role="Performance optimization specialist",
            model="sonnet",
            instructions="Analyze performance including...",
            tools=["search_code", "read_file", "profile"],
            temperature=0.4,
        ),
        "quality": MockMemberConfig(
            name="quality_specialist",
            role="Code quality engineer",
            model="sonnet",
            instructions="Evaluate code quality including...",
            tools=["search_code", "read_file", "run_linter"],
            temperature=0.5,
        ),
        "testing": MockMemberConfig(
            name="testing_specialist",
            role="Test engineer",
            model="sonnet",
            instructions="Design and implement tests...",
            tools=["search_code", "read_file", "run_tests"],
            temperature=0.6,
        ),
        "debugging": MockMemberConfig(
            name="debugging_specialist",
            role="Debugging specialist",
            model="sonnet",
            instructions="Investigate and resolve issues...",
            tools=["search_code", "read_file", "run_tests", "debugger"],
            temperature=0.3,
        ),
        "documentation": MockMemberConfig(
            name="documentation_specialist",
            role="Technical writer",
            model="haiku",
            instructions="Create documentation including...",
            tools=["search_code", "read_file", "write_file"],
            temperature=0.7,
        ),
        "refactoring": MockMemberConfig(
            name="refactoring_specialist",
            role="Refactoring specialist",
            model="sonnet",
            instructions="Plan and execute refactoring...",
            tools=["search_code", "read_file", "write_file"],
            temperature=0.5,
        ),
    }

    members = []
    for skill in parsed.skills:
        if skill in skill_configs:
            members.append(skill_configs[skill])

    # Ensure at least one member
    if not members:
        members.append(
            MockMemberConfig(
                name="generalist",
                role="General purpose assistant",
                model="sonnet",
                instructions=f"Help with: {parsed.raw_goal}",
                tools=["search_code", "read_file"],
                temperature=0.7,
            )
        )

    # Create leader for coordinate mode
    leader = None
    if mode == "coordinate":
        leader = MockMemberConfig(
            name="coordinator",
            role=f"Coordinates {parsed.intent} tasks across specialists",
            model="sonnet",
            instructions=f"Team coordinator for {parsed.intent} tasks...",
            tools=[],
            temperature=0.5,
        )

    return MockTeamConfig(
        name=team_name,
        description=f"Team created from goal: {parsed.raw_goal[:100]}",
        mode=mode,
        leader=leader,
        members=members,
    )


# ============================================================================
# Tutorial Step 3: Different Goal Types
# ============================================================================


async def tutorial_step_3_goal_types():
    """Step 3: Compare team generation for different goal types.

    Different goals produce different team structures:
    - Review goals -> Coordinate mode with multiple specialists
    - Fix goals -> Route mode with single debugging specialist
    - Document goals -> Route mode with documentation specialist
    """
    print("\n" + "=" * 70)
    print("STEP 3: Different Goal Types Produce Different Teams")
    print("=" * 70)

    goals = [
        ("Security Review", "Review this code for security vulnerabilities"),
        ("Bug Fix", "Fix the authentication timeout bug"),
        ("Documentation", "Document the REST API endpoints"),
        ("Performance", "Optimize database query performance"),
        ("Complex Review", "Review for security, performance, and code quality"),
    ]

    for name, goal in goals:
        parsed = simulate_parse_goal(goal)
        team = simulate_create_team(parsed)

        print(f"\n{name}:")
        print(f"  Goal:    {goal}")
        print(f"  Mode:    {team.mode}")
        print(f"  Members: {[m.name for m in team.members]}")
        if team.leader:
            print(f"  Leader:  {team.leader.name}")


# ============================================================================
# Tutorial Step 4: Using with AgnoAdapter (Production Example)
# ============================================================================


async def tutorial_step_4_production_usage():
    """Step 4: Production usage with AgnoAdapter.

    This shows the complete production workflow:
    1. Initialize AgnoAdapter with configuration
    2. Create team from goal
    3. Run team with a specific task
    4. Process results
    """
    print("\n" + "=" * 70)
    print("STEP 4: Production Usage with AgnoAdapter")
    print("=" * 70)

    print("""
In production, you would use:

```python
import asyncio
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings

async def main():
    # 1. Initialize adapter
    settings = MahavishnuSettings()
    adapter = AgnoAdapter(config=settings)
    await adapter.initialize()

    # 2. Create team from goal
    team_id = await adapter.create_team_from_goal(
        "Review this code for security vulnerabilities"
    )

    # 3. Run the team
    result = await adapter.run_team(
        team_id,
        "Analyze the authentication module in src/auth/"
    )

    # 4. Process results
    print(f"Team: {result.team_name}")
    print(f"Success: {result.success}")
    print(f"Latency: {result.latency_ms:.0f}ms")

    for response in result.responses:
        print(f"\\n{response.agent_name}:")
        print(response.content[:500])

    # 5. Cleanup
    await adapter.shutdown()

asyncio.run(main())
```
""")

    print("\nKey points:")
    print("  1. Always initialize adapter before use")
    print("  2. Team ID is returned from create_team_from_goal()")
    print("  3. Use run_team() with team_id and task description")
    print("  4. Results contain responses from all agents")
    print("  5. Always shutdown adapter to cleanup resources")


# ============================================================================
# Tutorial Step 5: MCP Tool Usage
# ============================================================================


async def tutorial_step_5_mcp_tools():
    """Step 5: Using goal-driven teams via MCP tools.

    Mahavishnu exposes goal-driven team functionality as MCP tools
    for integration with other applications and AI systems.
    """
    print("\n" + "=" * 70)
    print("STEP 5: MCP Tool Usage")
    print("=" * 70)

    print("""
Available MCP Tools for Goal-Driven Teams:

1. parse_goal
   Parse a natural language goal into structured components.

   Parameters:
     - goal (string, required): Natural language goal

   Example MCP call:
   {
     "tool": "parse_goal",
     "arguments": {
       "goal": "Review code for security vulnerabilities"
     }
   }

2. create_team_from_goal
   Create a team configuration from a goal.

   Parameters:
     - goal (string, required): Natural language goal
     - name (string, optional): Team name
     - mode (string, optional): Override mode

   Example MCP call:
   {
     "tool": "create_team_from_goal",
     "arguments": {
       "goal": "Build a REST API with authentication",
       "name": "api_build_team"
     }
   }

3. run_goal_team
   Create and execute a team from a goal in one step.

   Parameters:
     - goal (string, required): Natural language goal
     - task (string, required): Specific task
     - repo (string, optional): Repository path

   Example MCP call:
   {
     "tool": "run_goal_team",
     "arguments": {
       "goal": "Review code for security issues",
       "task": "Analyze the authentication module",
       "repo": "/path/to/repo"
     }
   }
""")


# ============================================================================
# Tutorial Step 6: Best Practices
# ============================================================================


async def tutorial_step_6_best_practices():
    """Step 6: Best practices for effective goal-driven teams."""
    print("\n" + "=" * 70)
    print("STEP 6: Best Practices")
    print("=" * 70)

    print("""
Best Practices for Goal-Driven Teams:

1. WRITE SPECIFIC GOALS
   Good: "Review authentication code for SQL injection vulnerabilities"
   Bad:  "Check the code"

2. INCLUDE DOMAIN KEYWORDS
   - Security: security, auth, injection, xss, vulnerability
   - Performance: performance, speed, latency, memory, bottleneck
   - Quality: quality, style, lint, complexity, maintainability
   - Testing: test, coverage, unit, integration

3. UNDERSTAND MODE SELECTION
   - Coordinate: Best for complex tasks needing multiple perspectives
   - Route: Best for single-focus tasks
   - Broadcast: Best for open-ended analysis

4. SET APPROPRIATE EXPECTATIONS FOR CONFIDENCE
   - High confidence (>= 0.8): Pattern matching succeeded
   - Medium confidence (0.5-0.8): Partial match, may need refinement
   - Low confidence (< 0.5): Consider LLM fallback or rephrase goal

5. USE LLM FALLBACK FOR COMPLEX GOALS
   - Domain-specific terminology
   - Multiple overlapping intents
   - Novel goal patterns

6. REVIEW GENERATED TEAMS
   Before running expensive operations, review the team configuration:
   - Check member roles match your intent
   - Verify tools are appropriate
   - Confirm collaboration mode makes sense

7. PROVIDE CONTEXT IN TASKS
   When running teams, provide specific context:
   - File paths or modules to analyze
   - Specific concerns or focus areas
   - Constraints or requirements
""")


# ============================================================================
# Main Tutorial Runner
# ============================================================================


async def main():
    """Run all tutorial steps."""
    print("\n" + "=" * 70)
    print("GOAL-DRIVEN TEAMS TUTORIAL")
    print("Learn to create intelligent multi-agent teams from natural language")
    print("=" * 70)

    steps = [
        ("Basic Goal Parsing", tutorial_step_1_basic_parsing),
        ("Create Team from Goal", tutorial_step_2_create_team),
        ("Different Goal Types", tutorial_step_3_goal_types),
        ("Production Usage", tutorial_step_4_production_usage),
        ("MCP Tool Usage", tutorial_step_5_mcp_tools),
        ("Best Practices", tutorial_step_6_best_practices),
    ]

    for name, step_func in steps:
        try:
            await step_func()
        except Exception as e:
            logger.error(f"Step failed: {name} - {e}")

    print("\n" + "=" * 70)
    print("TUTORIAL COMPLETE")
    print("=" * 70)
    print("""
Next Steps:
1. Try with real AgnoAdapter (requires Agno SDK and LLM provider)
2. Explore team configuration files in settings/agno_teams/
3. Create custom skill mappings for your domain
4. Integrate MCP tools with your AI applications

Documentation:
- docs/GOAL_DRIVEN_TEAMS.md - Full documentation
- docs/AGNO_ADAPTER.md - Adapter configuration
- docs/MCP_TOOLS_REFERENCE.md - MCP tool reference
""")


if __name__ == "__main__":
    asyncio.run(main())
