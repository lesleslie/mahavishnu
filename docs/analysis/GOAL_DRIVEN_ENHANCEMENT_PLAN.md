# Goal-Driven Team Enhancement Plan

**Date:** 2026-02-21
**Status:** Draft for Committee Review
**Prerequisite:** GoalDrivenTeamFactory (✅ Implemented)

---

## Executive Summary

This plan outlines enhancements to the newly implemented `GoalDrivenTeamFactory` and related infrastructure. Building on the native implementation (which replaced Hive integration), these enhancements would provide:

1. **MCP/CLI Integration** - Expose goal-driven team creation to users
2. **Enhanced Skill Mapping** - Expand domain coverage
3. **Learning from Outcomes** - Feed execution results back into team optimization
4. **GraphExecutor Pattern** - Complex workflow orchestration
5. **Prompt Template Manager** - Reusable prompt patterns

---

## 1. MCP Tool: `team_from_goal`

### 1.1 Purpose

Expose the `GoalDrivenTeamFactory` via MCP for programmatic team creation.

### 1.2 Implementation

**File:** `mahavishnu/mcp/tools/goal_team_tools.py`

```python
from mcp_common.fastmcp import FastMCP

@mcp.tool()
async def team_from_goal(
    goal: str,
    name: str | None = None,
    mode: str | None = None,
    auto_run: bool = False,
    task: str | None = None,
) -> dict:
    """Create an agent team from a natural language goal.

    Args:
        goal: Natural language description of what the team should do.
              Examples:
              - "Review this code for security vulnerabilities"
              - "Build a REST API for user management"
              - "Analyze performance bottlenecks in the database layer"
        name: Optional team name (auto-generated if not provided).
        mode: Optional collaboration mode (coordinate, route, broadcast).
        auto_run: If True, immediately run the team with the provided task.
        task: Task to run if auto_run is True.

    Returns:
        Dictionary with team_id, config, and optionally run results.
    """
    factory = GoalDrivenTeamFactory(llm_factory=app.llm_factory)

    # Parse and create team config
    team_config = await factory.create_team_from_goal(goal, name, mode)

    # Create the team
    team_id = await app.agno_adapter.create_team(team_config)

    result = {
        "team_id": team_id,
        "team_name": team_config.name,
        "mode": team_config.mode.value,
        "members": [m.name for m in team_config.members],
        "goal": goal,
    }

    # Optionally run immediately
    if auto_run and task:
        run_result = await app.agno_adapter.run_team(team_id, task)
        result["run_result"] = run_result.model_dump()

    return result


@mcp.tool()
async def parse_goal(goal: str) -> dict:
    """Parse a goal to see what team would be created.

    Useful for debugging and understanding goal parsing logic.

    Args:
        goal: Natural language goal to parse.

    Returns:
        Parsed goal with intent, domain, skills, and confidence.
    """
    factory = GoalDrivenTeamFactory(llm_factory=app.llm_factory)
    parsed = await factory.parse_goal(goal)

    return {
        "intent": parsed.intent,
        "domain": parsed.domain,
        "skills": parsed.skills,
        "confidence": parsed.confidence,
        "raw_goal": parsed.raw_goal,
    }
```

### 1.3 Effort

- **Time:** 2-4 hours
- **Risk:** Low (wraps existing functionality)
- **Dependencies:** None

---

## 2. CLI Command: `mahavishnu team create --goal`

### 2.1 Purpose

Command-line interface for goal-driven team creation.

### 2.2 Implementation

**File:** `mahavishnu/cli/team_cli.py`

```python
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="team", help="Agent team management")
console = Console()


@app.command("create")
def create_team(
    goal: str = typer.Option(..., "--goal", "-g", help="Natural language goal"),
    name: str | None = typer.Option(None, "--name", "-n", help="Team name"),
    mode: str | None = typer.Option(None, "--mode", "-m", help="Team mode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show config without creating"),
    run: bool = typer.Option(False, "--run", help="Run team immediately"),
    task: str | None = typer.Option(None, "--task", "-t", help="Task to run"),
) -> None:
    """Create an agent team from a natural language goal.

    Examples:
        mahavishnu team create --goal "Review code for security issues"
        mahavishnu team create --goal "Build REST API" --name api_team
        mahavishnu team create --goal "Test the auth module" --run --task "Test login flow"
    """
    import asyncio
    from mahavishnu.engines import GoalDrivenTeamFactory

    async def _create():
        factory = GoalDrivenTeamFactory()

        # Parse goal
        parsed = await factory.parse_goal(goal)

        console.print(f"\n[bold]Parsed Goal:[/bold]")
        console.print(f"  Intent: {parsed.intent}")
        console.print(f"  Domain: {parsed.domain}")
        console.print(f"  Skills: {', '.join(parsed.skills)}")
        console.print(f"  Confidence: {parsed.confidence:.0%}")

        if dry_run:
            console.print("\n[yellow]Dry run - not creating team[/yellow]")
            return

        # Create team config
        team_mode = TeamMode(mode) if mode else None
        config = await factory.create_team_from_goal(goal, name, team_mode)

        console.print(f"\n[bold green]Team Created:[/bold green]")
        console.print(f"  Name: {config.name}")
        console.print(f"  Mode: {config.mode.value}")
        console.print(f"  Members: {len(config.members)}")

        # Show member table
        table = Table(title="Team Members")
        table.add_column("Name", style="cyan")
        table.add_column("Role", style="green")
        table.add_column("Model", style="yellow")

        for member in config.members:
            table.add_row(member.name, member.role, member.model)

        console.print(table)

        if run and task:
            console.print(f"\n[bold]Running team with task...[/bold]")
            # ... run logic

    asyncio.run(_create())


@app.command("list")
def list_teams() -> None:
    """List all active teams."""
    # ... implementation


@app.command("run")
def run_team(
    team_id: str = typer.Argument(..., help="Team ID"),
    task: str = typer.Option(..., "--task", "-t", help="Task to run"),
) -> None:
    """Run a team with a task."""
    # ... implementation
```

### 2.3 Effort

- **Time:** 4-6 hours
- **Risk:** Low
- **Dependencies:** MCP tool implementation

---

## 3. Enhanced Skill Mapping

### 3.1 Purpose

Expand the skill mapping beyond the current 7 domains to cover more use cases.

### 3.2 Current Coverage

| Skill | Domain | Tools |
|-------|--------|-------|
| security | Security analysis | search_code, read_file, grep |
| quality | Code quality | search_code, read_file, run_linter |
| performance | Performance optimization | search_code, read_file, profile |
| testing | Test engineering | search_code, read_file, run_tests |
| documentation | Technical writing | search_code, read_file, write_file |
| refactoring | Code restructuring | search_code, read_file, write_file |
| debugging | Issue resolution | search_code, read_file, run_tests, debugger |

### 3.3 Proposed Additions

| Skill | Domain | Tools | Instructions |
|-------|--------|-------|--------------|
| **api_design** | REST/GraphQL APIs | search_code, read_file, openapi_spec | Design consistent, versioned APIs |
| **database** | Schema/queries | search_code, read_file, sql_analyzer | Optimize queries, design schemas |
| **devops** | CI/CD, infrastructure | read_file, docker, kubectl | Build reproducible deployments |
| **frontend** | UI/UX | search_code, read_file, browser_tools | Accessible, responsive interfaces |
| **ml_ops** | ML pipelines | read_file, model_registry, experiment_tracker | Reproducible ML workflows |
| **compliance** | Regulatory | search_code, read_file, compliance_checker | GDPR, SOC2, HIPAA compliance |
| **accessibility** | A11y | search_code, read_file, axe_tools | WCAG compliance |

### 3.4 Implementation

**File:** `mahavishnu/engines/skill_registry.py`

```python
class SkillRegistry:
    """Registry for skill configurations with dynamic loading."""

    def __init__(self):
        self._skills: dict[str, SkillConfig] = {}
        self._load_builtin_skills()
        self._load_custom_skills()

    def register_skill(self, name: str, config: SkillConfig) -> None:
        """Register a new skill configuration."""
        self._skills[name] = config

    def get_skill(self, name: str) -> SkillConfig | None:
        """Get a skill configuration by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """List all registered skills."""
        return list(self._skills.keys())

    def find_skills_by_domain(self, domain: str) -> list[SkillConfig]:
        """Find all skills related to a domain."""
        # Fuzzy matching on domain keywords
        ...

    def _load_custom_skills(self) -> None:
        """Load custom skills from settings/skills.yaml."""
        ...
```

### 3.5 Effort

- **Time:** 1-2 days
- **Risk:** Low (additive, no breaking changes)
- **Dependencies:** None

---

## 4. Learning from Team Execution Outcomes

### 4.1 Purpose

Feed execution results back into team optimization so the system learns which configurations work best.

### 4.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LEARNING FEEDBACK LOOP                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │
│  │   GOAL +    │────▶│    TEAM     │────▶│  EXECUTION  │          │
│  │   TEAM      │     │   CONFIG    │     │   RESULT    │          │
│  └─────────────┘     └─────────────┘     └──────┬──────┘          │
│                                                 │                  │
│                                                 ▼                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │
│  │   UPDATED   │◀────│   LEARNING  │◀────│   OUTCOME   │          │
│  │   WEIGHTS   │     │   ENGINE    │     │   ANALYSIS  │          │
│  └─────────────┘     └─────────────┘     └─────────────┘          │
│                                                                     │
│  Storage: Session-Buddy (sessions) + Akosha (embeddings)           │
│  Metrics: StatisticalRouter (confidence intervals)                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.3 Implementation

**File:** `mahavishnu/engines/team_learning.py`

```python
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class TeamExecutionOutcome:
    """Record of a team execution for learning."""

    goal: str
    team_config: TeamConfig
    parsed_goal: ParsedGoal
    task: str
    success: bool
    latency_ms: float
    tokens_used: int
    quality_score: float | None  # From Crackerjack if available
    timestamp: datetime
    error: str | None = None
    user_feedback: str | None = None


class TeamLearningEngine:
    """Learn from team execution outcomes to improve configurations."""

    def __init__(
        self,
        session_buddy_client,
        akosha_client,
        statistical_router,
    ):
        self.session_buddy = session_buddy_client
        self.akosha = akosha_client
        self.router = statistical_router

    async def record_outcome(self, outcome: TeamExecutionOutcome) -> None:
        """Record an execution outcome for learning.

        Stores in:
        - Session-Buddy: Full execution context
        - Akosha: Embedding of goal + outcome for similarity search
        """
        # Store in Session-Buddy
        await self.session_buddy.store_session({
            "type": "team_execution",
            "goal": outcome.goal,
            "team_config": outcome.team_config.model_dump(),
            "success": outcome.success,
            "quality_score": outcome.quality_score,
            "timestamp": outcome.timestamp.isoformat(),
        })

        # Store embedding in Akosha
        embedding_text = f"Goal: {outcome.goal}\nOutcome: {'success' if outcome.success else 'failure'}"
        await self.akosha.store_embedding(
            text=embedding_text,
            metadata={
                "team_name": outcome.team_config.name,
                "skills": outcome.parsed_goal.skills,
                "success": outcome.success,
            },
        )

    async def get_recommended_config(
        self,
        goal: str,
        parsed: ParsedGoal,
    ) -> dict | None:
        """Get a recommended team configuration based on similar past goals.

        Uses embedding similarity to find successful configurations.
        """
        # Search Akosha for similar goals
        similar = await self.akosha.search_similar(
            query=goal,
            filter={"success": True},
            limit=5,
        )

        if not similar:
            return None

        # Weight by similarity and quality score
        # Return best matching config
        ...

    async def update_skill_weights(self) -> None:
        """Update skill weights in StatisticalRouter based on outcomes.

        Called periodically to adjust preferences.
        """
        # Analyze recent outcomes
        # Update confidence intervals
        ...
```

### 4.4 Integration Points

- **AgentTeamManager** → Call `record_outcome()` after each team run
- **GoalDrivenTeamFactory** → Call `get_recommended_config()` before creating new teams
- **Crackerjack** → Provide quality scores for team outputs

### 4.5 Effort

- **Time:** 2-3 days
- **Risk:** Medium (integrates multiple systems)
- **Dependencies:** Session-Buddy, Akosha, StatisticalRouter

---

## 5. GraphExecutor Pattern

### 5.1 Purpose

Execute complex multi-stage workflows where agents are organized as a DAG with dependencies.

### 5.2 When Needed

The trios noted that `DependencyGraph + PoolManager already handle this`. GraphExecutor would be useful when:

1. **Complex multi-stage workflows** with branching logic
2. **State persistence** between stages
3. **Parallel execution** of independent branches
4. **Checkpoint/resume** for long-running workflows

### 5.3 Implementation

**File:** `mahavishnu/engines/graph_executor.py`

```python
from mahavishnu.core.dependency_graph import DependencyGraph


class GraphExecutor:
    """Execute agent graphs with dependency management.

    Combines:
    - DependencyGraph for DAG management
    - PoolManager for parallel execution
    - State management for inter-node communication
    """

    def __init__(
        self,
        dependency_graph: DependencyGraph,
        pool_manager,
        state_backend,  # Session-Buddy or in-memory
    ):
        self.graph = dependency_graph
        self.pools = pool_manager
        self.state = state_backend

    async def execute(self, initial_input: dict) -> dict:
        """Execute the graph and return final result.

        Uses topological sort to determine execution order.
        Parallelizes independent nodes via PoolManager.
        """
        # Get execution stages
        stages = self._compute_stages()

        for stage in stages:
            # Execute all nodes in this stage in parallel
            tasks = [
                self._execute_node(node_id, self.state.get(node_id))
                for node_id in stage
            ]
            results = await asyncio.gather(*tasks)

            # Store results for dependent nodes
            for node_id, result in zip(stage, results):
                await self._propagate_result(node_id, result)

        return self.state.get_final_result()

    def _compute_stages(self) -> list[list[str]]:
        """Compute parallel execution stages from DAG."""
        # Use DependencyGraph.topological_sort() as base
        # Group nodes by dependency level
        ...

    async def _propagate_result(self, node_id: str, result: dict) -> None:
        """Propagate node result to dependent nodes."""
        dependents = self.graph.get_dependents(node_id)
        for dep_id in dependents:
            await self.state.update(dep_id, result)
```

### 5.4 Effort

- **Time:** 3-5 days
- **Risk:** Medium
- **Dependencies:** Only needed for complex workflows

---

## 6. Prompt Template Manager

### 6.1 Purpose

Centralized management of prompt templates used across agents.

### 6.2 Implementation

**File:** `mahavishnu/engines/prompt_templates.py`

```python
from string import Template
from typing import Any


class PromptTemplateManager:
    """Manage reusable prompt templates for agent instructions."""

    def __init__(self):
        self._templates: dict[str, Template] = {}
        self._load_builtin_templates()

    def register(self, name: str, template: str) -> None:
        """Register a prompt template."""
        self._templates[name] = Template(template)

    def render(self, name: str, **kwargs: Any) -> str:
        """Render a template with variables."""
        if name not in self._templates:
            raise KeyError(f"Template not found: {name}")
        return self._templates[name].substitute(**kwargs)

    def _load_builtin_templates(self) -> None:
        """Load built-in templates."""
        self.register(
            "security_analyst",
            """You are a security specialist analyzing ${language} code.

Focus areas:
${focus_areas}

Recent vulnerabilities to check:
${recent_vulns}

Output format:
- Severity: (Critical/High/Medium/Low)
- Issue: <description>
- Location: <file:line>
- Remediation: <suggested fix>""",
        )

        self.register(
            "quality_engineer",
            """You are a quality engineer reviewing ${language} code.

Standards enforced:
${standards}

Check for:
- Code complexity (max cyclomatic: ${max_complexity})
- Test coverage (minimum: ${min_coverage}%)
- Documentation completeness
- Style guide adherence""",
        )
        # ... more templates
```

### 6.3 Usage in GoalDrivenTeamFactory

```python
# Enhanced skill mapping with templates
SKILL_MAPPING = {
    "security": SkillConfig(
        role="Security vulnerability specialist",
        instructions_template="security_analyst",  # Template name
        # ... rest of config
    ),
}

# When creating member
template_manager.render(
    config.instructions_template,
    language="Python",
    focus_areas="- SQL injection\n- XSS\n- Authentication",
    recent_vulns="CVE-2024-...",
)
```

### 6.4 Effort

- **Time:** 1 day
- **Risk:** Low
- **Dependencies:** None

---

## 7. Implementation Priority

### Phase 1: User-Facing (1-2 days)
1. MCP tool: `team_from_goal` ⭐
2. CLI command: `mahavishnu team create --goal` ⭐

### Phase 2: Enhanced Coverage (2-3 days)
3. Enhanced skill mapping with registry
4. Prompt template manager

### Phase 3: Learning System (2-3 days)
5. TeamLearningEngine for outcome tracking
6. Integration with Session-Buddy + Akosha

### Phase 4: Advanced Workflows (3-5 days) - Optional
7. GraphExecutor pattern (only if needed)

---

## 8. Questions for Committee Review

1. **Priority**: Is Phase 1 (MCP/CLI) the right starting point?
2. **Learning System**: Should we invest in the full learning loop, or start simpler?
3. **GraphExecutor**: Is this needed now, or can it wait for real use cases?
4. **Skill Expansion**: Which of the proposed 7 new skills are highest priority?
5. **Integration Depth**: How tightly should this integrate with Crackerjack quality gates?

---

**Document Version:** 1.0 (Draft for Committee Review)
