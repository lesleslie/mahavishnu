# Goal-Driven Teams

Create intelligent multi-agent teams from natural language goals.

## Overview

Goal-Driven Teams is a feature that converts natural language goals into fully-configured multi-agent teams. Instead of manually defining agents, roles, and collaboration modes, you describe what you want to accomplish, and Mahavishnu automatically generates the optimal team configuration.

**Key Benefits:**

- **Natural Language Input**: Describe your goal in plain English
- **Automatic Skill Detection**: Identifies required skills from your goal
- **Intelligent Mode Selection**: Chooses the best collaboration mode
- **Zero Configuration**: No YAML files or manual setup required

## Quick Start

### Parse a Goal

```python
from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

# Create factory
factory = GoalDrivenTeamFactory()

# Parse a natural language goal
parsed = await factory.parse_goal("Review this code for security vulnerabilities")

print(f"Intent: {parsed.intent}")      # "review"
print(f"Skills: {parsed.skills}")      # ["security", "quality"]
print(f"Domain: {parsed.domain}")      # "security"
print(f"Confidence: {parsed.confidence}")  # 0.85
```

### Create a Team from Goal

```python
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings

# Initialize adapter
settings = MahavishnuSettings()
adapter = AgnoAdapter(config=settings)
await adapter.initialize()

# Create team from natural language goal
team_id = await adapter.create_team_from_goal(
    "Review this code for security issues and performance bottlenecks"
)

# Run the team
result = await adapter.run_team(team_id, "Analyze the authentication module")
print(result.responses)
```

### CLI Usage

```bash
# Parse a goal
mahavishnu goal parse "Build a REST API with authentication"

# Create and run a team
mahavishnu goal run "Review code for security vulnerabilities" --repo ./myproject
```

## How Goal Parsing Works

The `GoalDrivenTeamFactory` uses a two-phase approach:

### Phase 1: Pattern Matching (Fast, Free)

1. **Intent Detection**: Matches goal against regex patterns to identify intent (review, build, test, fix, refactor, document)
2. **Skill Extraction**: Identifies required skills from domain keywords
3. **Domain Classification**: Categorizes the goal area (security, performance, quality, etc.)
4. **Confidence Calculation**: Scores how well patterns matched

### Phase 2: LLM Fallback (Slower, More Accurate)

If pattern matching confidence is below 70% and an LLM factory is configured:

1. Sends goal to LLM for semantic analysis
2. Extracts structured intent, domain, and skills
3. Uses LLM result if confidence is higher

## Writing Effective Goals

### Good Goals

```python
# Specific and actionable
"Review this code for security vulnerabilities"
"Build a REST API with JWT authentication"
"Test the payment processing module"
"Analyze performance bottlenecks in database queries"
"Document the authentication workflow"

# Include domain keywords
"Check for SQL injection and XSS vulnerabilities"  # -> security skill
"Optimize memory usage and latency"  # -> performance skill
"Ensure code follows style guide and has tests"  # -> quality skill
```

### Less Effective Goals

```python
# Too vague
"Make this code better"  # -> generic "quality" skill only

# No clear intent
"The application has issues"  # -> defaults to "analyze" intent

# Multiple conflicting intents
"Build and test and document everything"  # -> picks first matched intent
```

### Goal Intent Patterns

| Intent | Trigger Words | Default Mode |
|--------|---------------|--------------|
| `review` | review, analyze, check, audit, inspect, evaluate | coordinate |
| `build` | build, create, implement, develop, add, write | coordinate |
| `test` | test, testing, coverage, unit, integration | coordinate |
| `fix` | fix, debug, resolve, solve, bug, error, issue | route |
| `refactor` | refactor, clean, improve, optimize, restructure | coordinate |
| `document` | document, docs, readme, comment, explain | route |
| `analyze` | (default fallback) | broadcast |

## Available Skills

Each skill maps to a pre-configured agent role with specific instructions and tools:

| Skill | Role | Tools | Temperature |
|-------|------|-------|-------------|
| `security` | Security vulnerability specialist | search_code, read_file, grep | 0.3 |
| `quality` | Code quality engineer | search_code, read_file, run_linter | 0.5 |
| `performance` | Performance optimization specialist | search_code, read_file, profile | 0.4 |
| `testing` | Test engineer | search_code, read_file, run_tests | 0.6 |
| `documentation` | Technical writer | search_code, read_file, write_file | 0.7 |
| `refactoring` | Refactoring specialist | search_code, read_file, write_file | 0.5 |
| `debugging` | Debugging specialist | search_code, read_file, run_tests, debugger | 0.3 |

## Collaboration Modes

The factory automatically selects the best collaboration mode based on goal intent:

### Coordinate Mode (Most Common)

A leader agent distributes tasks to specialists and aggregates results.

```
Goal: "Review this code for security vulnerabilities"

Team Structure:
  - coordinator (leader): Distributes tasks, aggregates findings
  - security_specialist: Analyzes for vulnerabilities
  - quality_specialist: Checks code quality
```

**Best for:** Complex tasks requiring multiple perspectives (review, build, test)

### Route Mode

Single agent selected based on task type or expertise.

```
Goal: "Fix the authentication bug"

Team Structure:
  - debugging_specialist: Root cause analysis and fix
```

**Best for:** Single-focus tasks (fix, document)

### Broadcast Mode

All agents work on the same task simultaneously.

```
Goal: "Analyze this codebase"

Team Structure:
  - security_specialist: Security perspective
  - performance_specialist: Performance perspective
  - quality_specialist: Quality perspective
```

**Best for:** Open-ended analysis requiring diverse perspectives

## MCP Tool Documentation

### parse_goal

Parse a natural language goal into structured components.

**Parameters:**
- `goal` (string, required): Natural language goal to parse

**Returns:**
```json
{
  "intent": "review",
  "domain": "security",
  "skills": ["security", "quality"],
  "confidence": 0.85,
  "raw_goal": "Review this code for security vulnerabilities",
  "metadata": {"method": "pattern"}
}
```

### create_team_from_goal

Create a team configuration from a natural language goal.

**Parameters:**
- `goal` (string, required): Natural language goal
- `name` (string, optional): Team name (auto-generated if not provided)
- `mode` (string, optional): Override collaboration mode

**Returns:**
```json
{
  "name": "security_review_team",
  "description": "Team created from goal: Review this code...",
  "mode": "coordinate",
  "leader": {...},
  "members": [...]
}
```

### run_goal_team

Create and execute a team from a goal in one step.

**Parameters:**
- `goal` (string, required): Natural language goal
- `task` (string, required): Specific task for the team
- `repo` (string, optional): Repository path for context

**Returns:**
```json
{
  "team_id": "team_security_review_abc123",
  "run_id": "run_xyz789",
  "success": true,
  "responses": [...],
  "total_tokens": 1234,
  "latency_ms": 5678.9
}
```

## Error Code Reference

| Code | Description | Resolution |
|------|-------------|------------|
| `GOAL_PARSE_ERROR` | Goal could not be parsed | Use more specific language |
| `GOAL_TOO_VAGUE` | Confidence below 0.3 threshold | Add domain keywords |
| `TEAM_CREATION_FAILED` | Team configuration invalid | Check skill names |
| `NO_LLM_FACTORY` | LLM fallback requested but not configured | Configure LLM provider |
| `AGENT_NOT_FOUND` | Referenced agent does not exist | Verify agent names |

## Complete Examples

### Example 1: Security Code Review

```python
import asyncio
from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

async def security_review():
    factory = GoalDrivenTeamFactory()

    # Parse goal
    parsed = await factory.parse_goal(
        "Review the authentication module for security vulnerabilities "
        "including SQL injection and XSS"
    )

    print(f"Detected skills: {parsed.skills}")
    # Output: ['security', 'quality']

    # Create team config
    team_config = await factory.create_team_from_goal(parsed.raw_goal)

    print(f"Team name: {team_config.name}")
    # Output: security_review_team

    print(f"Members: {[m.name for m in team_config.members]}")
    # Output: ['security_specialist', 'quality_specialist']

asyncio.run(security_review())
```

### Example 2: Performance Optimization

```python
from mahavishnu.engines.agno_adapter import AgnoAdapter
from mahavishnu.core.config import MahavishnuSettings

async def optimize_performance():
    settings = MahavishnuSettings()
    adapter = AgnoAdapter(config=settings)
    await adapter.initialize()

    # Create team from goal
    team_id = await adapter.create_team_from_goal(
        "Analyze and optimize database query performance"
    )

    # Run team against codebase
    result = await adapter.run_team(
        team_id,
        "Analyze the user service module for performance issues"
    )

    for response in result.responses:
        print(f"{response.agent_name}: {response.content[:200]}...")

    await adapter.shutdown()

asyncio.run(optimize_performance())
```

### Example 3: Custom Skill Mapping

```python
from mahavishnu.engines.goal_team_factory import (
    GoalDrivenTeamFactory,
    SkillConfig,
)

# Define custom skills
custom_skills = {
    "api_design": SkillConfig(
        role="API design specialist",
        instructions="Design RESTful APIs following OpenAPI specifications...",
        tools=["search_code", "read_file", "write_file"],
        model="sonnet",
        temperature=0.5,
    ),
    "database_design": SkillConfig(
        role="Database schema designer",
        instructions="Design normalized database schemas...",
        tools=["search_code", "read_file"],
        model="sonnet",
        temperature=0.4,
    ),
}

# Create factory with custom skills
factory = GoalDrivenTeamFactory(skill_mapping=custom_skills)

# Parse goal that uses custom skills
parsed = await factory.parse_goal("Design the API and database for a blog system")
# Skills: ['api_design', 'database_design']
```

### Example 4: LLM Fallback for Complex Goals

```python
from mahavishnu.engines.agno_adapter import AgnoAdapter, LLMProviderFactory
from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

async def complex_goal_with_llm():
    settings = MahavishnuSettings()
    adapter = AgnoAdapter(config=settings)
    await adapter.initialize()

    # Create factory with LLM fallback
    llm_factory = LLMProviderFactory(adapter.agno_config.llm)
    factory = GoalDrivenTeamFactory(llm_factory=llm_factory)

    # Complex goal that pattern matching might miss
    parsed = await factory.parse_goal(
        "Ensure the microservices architecture follows domain-driven design "
        "principles and implements proper bounded contexts"
    )

    print(f"Parsing method: {parsed.metadata.get('method')}")
    # Output: 'llm' (if pattern confidence was low)

    print(f"Detected skills: {parsed.skills}")
    # LLM extracted: ['refactoring', 'quality']

asyncio.run(complex_goal_with_llm())
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GoalDrivenTeamFactory                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌───────────────────────────────┐  │
│  │ Pattern Matcher │───►│ Confidence Calculator         │  │
│  │ (Regex-based)   │    │ (Score: 0.0 - 1.0)            │  │
│  └─────────────────┘    └───────────────┬───────────────┘  │
│                                         │                   │
│                          ┌──────────────▼───────────────┐  │
│                          │ Confidence >= 0.7?           │  │
│                          └──────────────┬───────────────┘  │
│                                   Yes    │    No            │
│                          ┌──────────────┴───────────────┐  │
│                          ▼                              ▼  │
│                   ┌────────────┐              ┌────────────┐│
│                   │ Return     │              │ LLM Fallback││
│                   │ ParsedGoal │              │ (if available)│
│                   └────────────┘              └────────────┘│
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                       TeamConfig                            │
├─────────────────────────────────────────────────────────────┤
│  name: "security_review_team"                               │
│  mode: TeamMode.COORDINATE                                  │
│  leader: MemberConfig(coordinator)                          │
│  members:                                                   │
│    - MemberConfig(security_specialist)                      │
│    - MemberConfig(quality_specialist)                       │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                     AgnoAdapter                             │
├─────────────────────────────────────────────────────────────┤
│  create_team(config) ─► AgentTeamManager                    │
│  run_team(team_id, task) ─► Agno Team Execution             │
│  result ─► TeamRunResult with agent responses               │
└─────────────────────────────────────────────────────────────┘
```

## Related Documentation

- [Agno Adapter Documentation](/docs/AGNO_ADAPTER.md)
- [Team Configuration Reference](/docs/AGNO_TEAMS.md)
- [MCP Tools Reference](/docs/MCP_TOOLS_REFERENCE.md)
- [Architecture Overview](/ARCHITECTURE.md)
