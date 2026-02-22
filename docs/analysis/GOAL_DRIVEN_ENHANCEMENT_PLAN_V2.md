# Goal-Driven Team Enhancement Plan v2.0

**Date:** 2026-02-21
**Status:** Revised After 5-Person Committee Review
**Previous Version:** v1.0 (superseded)

---

## Executive Summary

This revised plan incorporates feedback from a 5-person committee review (Backend Developer, Product Manager, AI Engineer, Code Reviewer, Architect). Key changes from v1.0:

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| Phase 1 effort | 1-2 days | **1 week** (includes tests, DI, error handling) |
| Learning system | New TeamLearningEngine | **Extend StatisticalRouter** |
| GraphExecutor | Optional (Phase 4) | **Deferred indefinitely** |
| New skills | 7 proposed | **2 only** (devops, api_design) |
| SkillRegistry | Class with dynamic loading | **Keep as dict** |

**Effort Reduction:** 25-40 days → **10-14 days** (60% reduction)

---

## Phase 1: User-Facing Core (1 week)

### 1.1 Prerequisites (Day 1-2)

Before implementing MCP/CLI tools, fix foundation issues identified by committee:

#### A. Add Error Codes for Team/Learning

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

#### B. Dependency Injection Pattern

**Problem (from Backend Developer):**
```python
# BAD: Undefined 'app' reference
factory = GoalDrivenTeamFactory(llm_factory=app.llm_factory)
```

**Solution:** Context-based dependency injection

**File:** `mahavishnu/core/context.py`

```python
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_common.llm import LLMProviderFactory
    from mahavishnu.engines.agno_adapter import AgnoAdapter

# Context variables for dependency injection
_current_llm_factory: ContextVar[Any] = ContextVar("llm_factory")
_current_agno_adapter: ContextVar[Any] = ContextVar("agno_adapter")


def get_llm_factory() -> Any:
    """Get the current LLM factory from context."""
    try:
        return _current_llm_factory.get()
    except LookupError:
        raise RuntimeError(
            "LLM factory not available in current context. "
            "Ensure MahavishnuApp is initialized."
        )


def get_agno_adapter() -> Any:
    """Get the current Agno adapter from context."""
    try:
        return _current_agno_adapter.get()
    except LookupError:
        raise RuntimeError(
            "Agno adapter not available in current context. "
            "Ensure MahavishnuApp is initialized."
        )


def set_app_context(llm_factory: Any, agno_adapter: Any) -> None:
    """Set the application context for dependency injection."""
    _current_llm_factory.set(llm_factory)
    _current_agno_adapter.set(agno_adapter)
```

**Integration in MahavishnuApp:**

```python
# In mahavishnu/core/app.py
from .context import set_app_context

class MahavishnuApp:
    async def _initialize_adapters(self) -> None:
        # ... existing initialization ...

        # Set context for dependency injection
        set_app_context(
            llm_factory=self.llm_factory,
            agno_adapter=self.agno_adapter,
        )
```

### 1.2 MCP Tool Implementation (Day 3-4)

**File:** `mahavishnu/mcp/tools/goal_team_tools.py`

```python
"""MCP tools for goal-driven team creation.

These tools expose the GoalDrivenTeamFactory functionality via MCP protocol.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_common.fastmcp import FastMCP

from mahavishnu.core.context import get_agno_adapter, get_llm_factory
from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory
from mahavishnu.engines.agno_teams.config import TeamMode

logger = logging.getLogger(__name__)


def _validate_mode(mode: str | None) -> TeamMode | None:
    """Validate and convert mode string to TeamMode enum.

    Args:
        mode: Mode string or None.

    Returns:
        TeamMode enum or None.

    Raises:
        MahavishnuError: If mode is invalid.
    """
    if mode is None:
        return None

    valid_modes = {m.value for m in TeamMode}
    if mode not in valid_modes:
        raise MahavishnuError(
            f"Invalid team mode: {mode}. Valid modes: {', '.join(valid_modes)}",
            error_code=ErrorCode.TEAM_MODE_INVALID,
            details={"provided": mode, "valid_modes": list(valid_modes)},
        )

    return TeamMode(mode)


@mcp.tool()
async def team_from_goal(
    goal: str,
    name: str | None = None,
    mode: str | None = None,
    auto_run: bool = False,
    task: str | None = None,
) -> dict[str, Any]:
    """Create an agent team from a natural language goal.

    This tool parses a natural language goal, generates an appropriate team
    configuration, and optionally runs the team immediately.

    Args:
        goal: Natural language description of what the team should accomplish.
              Examples:
              - "Review this code for security vulnerabilities"
              - "Build a REST API for user management"
              - "Analyze performance bottlenecks in the database layer"
              Minimum length: 10 characters. Maximum length: 2000 characters.
        name: Optional team name. Auto-generated from goal if not provided.
        mode: Optional collaboration mode. Valid values:
              - "coordinate": Leader distributes tasks (default for complex goals)
              - "route": Single specialist handles task (default for simple goals)
              - "broadcast": All members work simultaneously (default for analysis)
              - "collaborate": Sequential work with shared context
        auto_run: If True, immediately run the team with the provided task.
        task: Task to run if auto_run is True. Required if auto_run is True.

    Returns:
        Dictionary containing:
        - team_id: Unique identifier for the created team
        - team_name: Name of the team
        - mode: Collaboration mode used
        - members: List of team member names
        - goal: Original goal string
        - parsing_confidence: Confidence score of goal parsing (0.0-1.0)
        - run_result: (if auto_run) Execution results

    Raises:
        MahavishnuError: With error codes:
            - MHV-460: Team creation failed
            - MHV-461: Goal parsing failed
            - MHV-463: Invalid mode
            - MHV-464: LLM unavailable
            - MHV-465: Agno adapter unavailable
            - MHV-466: Team execution failed (if auto_run)

    Example:
        >>> result = await team_from_goal(
        ...     goal="Review code for security issues",
        ...     mode="coordinate",
        ...     auto_run=True,
        ...     task="Review src/auth/*.py"
        ... )
        >>> print(result["team_id"])
        "team_security_review_abc123"
    """
    # Validate inputs
    if len(goal) < 10:
        raise MahavishnuError(
            "Goal too short. Provide at least 10 characters.",
            error_code=ErrorCode.TEAM_GOAL_PARSING_FAILED,
            details={"goal_length": len(goal), "minimum": 10},
        )

    if len(goal) > 2000:
        raise MahavishnuError(
            "Goal too long. Maximum 2000 characters.",
            error_code=ErrorCode.TEAM_GOAL_PARSING_FAILED,
            details={"goal_length": len(goal), "maximum": 2000},
        )

    if auto_run and not task:
        raise MahavishnuError(
            "task is required when auto_run is True",
            error_code=ErrorCode.TEAM_EXECUTION_FAILED,
        )

    # Get dependencies via DI
    try:
        llm_factory = get_llm_factory()
        agno_adapter = get_agno_adapter()
    except RuntimeError as e:
        raise MahavishnuError(
            str(e),
            error_code=ErrorCode.TEAM_ADAPTER_UNAVAILABLE,
        ) from e

    # Validate mode
    team_mode = _validate_mode(mode)

    # Create factory and parse goal
    try:
        factory = GoalDrivenTeamFactory(llm_factory=llm_factory)
        parsed = await factory.parse_goal(goal)
        team_config = await factory.create_team_from_goal(
            goal=goal,
            name=name,
            mode=team_mode,
        )
    except Exception as e:
        logger.error(f"Failed to create team from goal: {e}")
        raise MahavishnuError(
            f"Failed to create team: {e}",
            error_code=ErrorCode.TEAM_CREATION_FAILED,
            details={"goal": goal[:100], "error": str(e)},
        ) from e

    # Create the team
    try:
        team_id = await agno_adapter.create_team(team_config)
    except Exception as e:
        logger.error(f"Failed to create team in adapter: {e}")
        raise MahavishnuError(
            f"Failed to create team in adapter: {e}",
            error_code=ErrorCode.TEAM_ADAPTER_UNAVAILABLE,
            details={"team_name": team_config.name, "error": str(e)},
        ) from e

    result: dict[str, Any] = {
        "team_id": team_id,
        "team_name": team_config.name,
        "mode": team_config.mode.value,
        "members": [m.name for m in team_config.members],
        "goal": goal,
        "parsing_confidence": parsed.confidence,
    }

    # Optionally run immediately
    if auto_run and task:
        try:
            run_result = await agno_adapter.run_team(team_id, task)
            result["run_result"] = {
                "success": run_result.success,
                "responses": [
                    {"agent": r.agent_name, "content": r.content[:500]}
                    for r in run_result.responses
                ],
                "latency_ms": run_result.latency_ms,
            }
        except Exception as e:
            logger.error(f"Team execution failed: {e}")
            raise MahavishnuError(
                f"Team execution failed: {e}",
                error_code=ErrorCode.TEAM_EXECUTION_FAILED,
                details={"team_id": team_id, "task": task[:100], "error": str(e)},
            ) from e

    logger.info(
        f"Created team from goal: team_id={team_id}, "
        f"mode={team_config.mode.value}, members={len(team_config.members)}"
    )

    return result


@mcp.tool()
async def parse_goal(goal: str) -> dict[str, Any]:
    """Parse a goal to preview team configuration without creating it.

    Useful for debugging goal parsing and understanding how the system
    interprets natural language goals.

    Args:
        goal: Natural language goal to parse.

    Returns:
        Dictionary containing:
        - intent: Detected intent (review, build, test, fix, refactor, document, analyze)
        - domain: Detected domain (security, performance, quality, testing, etc.)
        - skills: List of skills that would be assigned
        - confidence: Parsing confidence score (0.0-1.0)
        - method: Parsing method used ("pattern" or "llm")
        - raw_goal: Original goal string

    Example:
        >>> result = await parse_goal("Review code for security issues")
        >>> print(result["skills"])
        ["security", "quality"]
    """
    try:
        llm_factory = get_llm_factory()
    except RuntimeError:
        # Fall back to pattern-only parsing if LLM unavailable
        factory = GoalDrivenTeamFactory(llm_factory=None)
    else:
        factory = GoalDrivenTeamFactory(llm_factory=llm_factory)

    try:
        parsed = await factory.parse_goal(goal)
    except Exception as e:
        raise MahavishnuError(
            f"Failed to parse goal: {e}",
            error_code=ErrorCode.TEAM_GOAL_PARSING_FAILED,
            details={"goal": goal[:100], "error": str(e)},
        ) from e

    return {
        "intent": parsed.intent,
        "domain": parsed.domain,
        "skills": parsed.skills,
        "confidence": parsed.confidence,
        "method": parsed.metadata.get("method", "unknown"),
        "raw_goal": parsed.raw_goal,
    }


@mcp.tool()
async def list_team_skills() -> dict[str, Any]:
    """List all available team skills and their configurations.

    Returns:
        Dictionary containing:
        - skills: List of skill names
        - count: Total number of skills
        - details: Configuration for each skill

    Example:
        >>> result = await list_team_skills()
        >>> print(result["skills"])
        ["security", "quality", "performance", "testing", ...]
    """
    from mahavishnu.engines.goal_team_factory import SKILL_MAPPING

    skills = []
    for name, config in SKILL_MAPPING.items():
        skills.append({
            "name": name,
            "role": config.role,
            "model": config.model,
            "tools": config.tools,
        })

    return {
        "skills": skills,
        "count": len(skills),
    }
```

### 1.3 CLI Command Implementation (Day 5-7)

**File:** `mahavishnu/cli/team_cli.py`

```python
"""CLI commands for team management.

Commands:
    mahavishnu team create --goal "..."
    mahavishnu team list
    mahavishnu team run <team_id> --task "..."
"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="team", help="Agent team management")
console = Console()


def _run_async(coro):
    """Run async coroutine in sync context.

    Uses nest_asyncio to allow nested event loops.
    """
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in async context, create task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


@app.command("create")
def create_team(
    goal: str = typer.Option(
        ...,
        "--goal", "-g",
        help="Natural language goal describing what the team should do",
        prompt="Enter your goal",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name", "-n",
        help="Team name (auto-generated if not provided)",
    ),
    mode: Optional[str] = typer.Option(
        None,
        "--mode", "-m",
        help="Collaboration mode: coordinate, route, broadcast, collaborate",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview configuration without creating team",
    ),
    run: bool = typer.Option(
        False,
        "--run",
        help="Run team immediately after creation",
    ),
    task: Optional[str] = typer.Option(
        None,
        "--task", "-t",
        help="Task to run (required if --run is specified)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed output",
    ),
) -> None:
    """Create an agent team from a natural language goal.

    Examples:
        mahavishnu team create --goal "Review code for security issues"
        mahavishnu team create --goal "Build REST API" --name api_team
        mahavishnu team create --goal "Test auth module" --run --task "Test login"
        mahavishnu team create --goal "..." --dry-run
    """
    async def _create():
        from mahavishnu.core.context import get_llm_factory
        from mahavishnu.core.errors import MahavishnuError
        from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory
        from mahavishnu.engines.agno_teams.config import TeamMode

        # Validate mode early
        if mode:
            valid_modes = {m.value for m in TeamMode}
            if mode not in valid_modes:
                console.print(f"[red]Error: Invalid mode '{mode}'[/red]")
                console.print(f"Valid modes: {', '.join(valid_modes)}")
                raise typer.Exit(1)

        # Get factory
        try:
            llm_factory = get_llm_factory()
        except RuntimeError as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print("Ensure Mahavishnu is running: mahavishnu mcp start")
            raise typer.Exit(1) from e

        factory = GoalDrivenTeamFactory(llm_factory=llm_factory)

        # Parse goal
        console.print(f"\n[bold]Parsing goal:[/bold] {goal[:100]}...")
        try:
            parsed = await factory.parse_goal(goal)
        except Exception as e:
            console.print(f"[red]Error parsing goal: {e}[/red]")
            raise typer.Exit(1) from e

        # Show parsed result
        console.print(f"\n[bold]Parsed Goal:[/bold]")
        console.print(f"  Intent: [cyan]{parsed.intent}[/cyan]")
        console.print(f"  Domain: [green]{parsed.domain}[/green]")
        console.print(f"  Skills: [yellow]{', '.join(parsed.skills)}[/yellow]")
        console.print(f"  Confidence: [blue]{parsed.confidence:.0%}[/blue]")
        console.print(f"  Method: {parsed.metadata.get('method', 'unknown')}")

        if dry_run:
            console.print("\n[yellow]Dry run - not creating team[/yellow]")

            # Show what members would be created
            team_mode = TeamMode(mode) if mode else None
            config = await factory.create_team_from_goal(goal, name, team_mode)

            console.print(f"\n[bold]Would create team:[/bold]")
            console.print(f"  Name: {config.name}")
            console.print(f"  Mode: {config.mode.value}")

            table = Table(title="Team Members")
            table.add_column("Name", style="cyan")
            table.add_column("Role", style="green")
            table.add_column("Model", style="yellow")

            for member in config.members:
                table.add_row(member.name, member.role[:50], member.model)

            console.print(table)
            return

        # Create team
        team_mode = TeamMode(mode) if mode else None
        try:
            config = await factory.create_team_from_goal(goal, name, team_mode)
        except Exception as e:
            console.print(f"[red]Error creating team config: {e}[/red]")
            raise typer.Exit(1) from e

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
            table.add_row(member.name, member.role[:50], member.model)

        console.print(table)

        if verbose:
            console.print(f"\n[bold]Member Details:[/bold]")
            for member in config.members:
                console.print(f"\n  [cyan]{member.name}[/cyan]:")
                console.print(f"    Role: {member.role}")
                console.print(f"    Model: {member.model}")
                console.print(f"    Tools: {', '.join(member.tools) or 'None'}")
                console.print(f"    Temperature: {member.temperature}")

        if run:
            if not task:
                console.print("[red]Error: --task is required when --run is specified[/red]")
                raise typer.Exit(1)

            console.print(f"\n[bold]Running team with task:[/bold] {task[:100]}...")
            # ... run implementation

    _run_async(_create())


@app.command("list")
def list_teams(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed info"),
) -> None:
    """List all active teams."""
    async def _list():
        from mahavishnu.core.context import get_agno_adapter

        try:
            adapter = get_agno_adapter()
        except RuntimeError as e:
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(1) from e

        teams = adapter.list_teams()

        if not teams:
            console.print("[yellow]No active teams[/yellow]")
            return

        table = Table(title="Active Teams")
        table.add_column("Team ID", style="cyan")
        table.add_column("Name", style="green")

        if verbose:
            table.add_column("Mode", style="yellow")
            table.add_column("Members", style="blue")

        for team_id in teams:
            config = await adapter.get_team_config(team_id)
            if config:
                row = [team_id, config.name]
                if verbose:
                    row.extend([config.mode.value, str(len(config.members))])
                table.add_row(*row)

        console.print(table)

    _run_async(_list())


@app.command("parse")
def parse_goal_cmd(
    goal: str = typer.Argument(..., help="Goal to parse"),
) -> None:
    """Parse a goal without creating a team (for debugging)."""
    async def _parse():
        from mahavishnu.core.context import get_llm_factory
        from mahavishnu.engines.goal_team_factory import GoalDrivenTeamFactory

        try:
            llm_factory = get_llm_factory()
        except RuntimeError:
            factory = GoalDrivenTeamFactory(llm_factory=None)
        else:
            factory = GoalDrivenTeamFactory(llm_factory=llm_factory)

        parsed = await factory.parse_goal(goal)

        console.print(f"\n[bold]Parsed Goal:[/bold]")
        console.print(f"  Intent: [cyan]{parsed.intent}[/cyan]")
        console.print(f"  Domain: [green]{parsed.domain}[/green]")
        console.print(f"  Skills: [yellow]{', '.join(parsed.skills)}[/yellow]")
        console.print(f"  Confidence: [blue]{parsed.confidence:.0%}[/blue]")
        console.print(f"  Method: {parsed.metadata.get('method', 'unknown')}")

    _run_async(_parse())


if __name__ == "__main__":
    app()
```

### 1.4 Test Suite (Day 5-7, parallel with CLI)

**File:** `tests/unit/test_goal_team_tools.py`

```python
"""Tests for goal team MCP tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.mcp.tools.goal_team_tools import (
    team_from_goal,
    parse_goal,
    list_team_skills,
    _validate_mode,
)
from mahavishnu.engines.agno_teams.config import TeamMode


class TestValidateMode:
    """Tests for _validate_mode function."""

    def test_valid_mode(self):
        """Test valid mode conversion."""
        assert _validate_mode("coordinate") == TeamMode.COORDINATE
        assert _validate_mode("route") == TeamMode.ROUTE
        assert _validate_mode("broadcast") == TeamMode.BROADCAST

    def test_none_returns_none(self):
        """Test None input returns None."""
        assert _validate_mode(None) is None

    def test_invalid_mode_raises_error(self):
        """Test invalid mode raises MahavishnuError."""
        with pytest.raises(MahavishnuError) as exc_info:
            _validate_mode("invalid_mode")

        assert exc_info.value.error_code == ErrorCode.TEAM_MODE_INVALID


class TestTeamFromGoal:
    """Tests for team_from_goal MCP tool."""

    @pytest.fixture
    def mock_context(self):
        """Set up mock DI context."""
        with patch("mahavishnu.mcp.tools.goal_team_tools.get_llm_factory") as mock_llm, \
             patch("mahavishnu.mcp.tools.goal_team_tools.get_agno_adapter") as mock_adapter:

            mock_llm.return_value = MagicMock()
            mock_adapter.return_value = MagicMock()
            mock_adapter.return_value.create_team = AsyncMock(return_value="team_123")

            yield {"llm": mock_llm, "adapter": mock_adapter}

    @pytest.mark.asyncio
    async def test_team_from_goal_success(self, mock_context):
        """Test successful team creation."""
        result = await team_from_goal(
            goal="Review this code for security vulnerabilities",
            name="test_team",
            mode="coordinate",
        )

        assert result["team_id"] == "team_123"
        assert result["team_name"] == "test_team"
        assert result["mode"] == "coordinate"
        assert "members" in result
        assert "parsing_confidence" in result

    @pytest.mark.asyncio
    async def test_team_from_goal_too_short(self, mock_context):
        """Test error when goal is too short."""
        with pytest.raises(MahavishnuError) as exc_info:
            await team_from_goal(goal="short")

        assert exc_info.value.error_code == ErrorCode.TEAM_GOAL_PARSING_FAILED

    @pytest.mark.asyncio
    async def test_team_from_goal_too_long(self, mock_context):
        """Test error when goal is too long."""
        long_goal = "x" * 2001

        with pytest.raises(MahavishnuError) as exc_info:
            await team_from_goal(goal=long_goal)

        assert exc_info.value.error_code == ErrorCode.TEAM_GOAL_PARSING_FAILED

    @pytest.mark.asyncio
    async def test_team_from_goal_invalid_mode(self, mock_context):
        """Test error when mode is invalid."""
        with pytest.raises(MahavishnuError) as exc_info:
            await team_from_goal(
                goal="Review this code for security",
                mode="invalid_mode",
            )

        assert exc_info.value.error_code == ErrorCode.TEAM_MODE_INVALID

    @pytest.mark.asyncio
    async def test_team_from_goal_auto_run_without_task(self, mock_context):
        """Test error when auto_run is True but no task provided."""
        with pytest.raises(MahavishnuError) as exc_info:
            await team_from_goal(
                goal="Review this code for security",
                auto_run=True,
                task=None,
            )

        assert exc_info.value.error_code == ErrorCode.TEAM_EXECUTION_FAILED


class TestParseGoal:
    """Tests for parse_goal MCP tool."""

    @pytest.fixture
    def mock_context(self):
        """Set up mock DI context."""
        with patch("mahavishnu.mcp.tools.goal_team_tools.get_llm_factory") as mock_llm:
            mock_llm.return_value = MagicMock()
            yield mock_llm

    @pytest.mark.asyncio
    async def test_parse_goal_success(self, mock_context):
        """Test successful goal parsing."""
        result = await parse_goal("Review this code for security vulnerabilities")

        assert result["intent"] == "review"
        assert "security" in result["skills"]
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_parse_goal_patterns(self, mock_context):
        """Test parsing of various goal patterns."""
        test_cases = [
            ("Review code for security", "review", ["security"]),
            ("Build a REST API", "build", ["quality"]),
            ("Test the auth module", "test", ["testing"]),
            ("Fix this bug", "fix", ["debugging"]),
            ("Refactor the code", "refactor", ["refactoring"]),
            ("Document this function", "document", ["documentation"]),
        ]

        for goal, expected_intent, expected_skills in test_cases:
            result = await parse_goal(goal)
            assert result["intent"] == expected_intent, f"Failed for: {goal}"


class TestListTeamSkills:
    """Tests for list_team_skills MCP tool."""

    @pytest.mark.asyncio
    async def test_list_skills(self):
        """Test listing all skills."""
        result = await list_team_skills()

        assert "skills" in result
        assert "count" in result
        assert result["count"] > 0

        skill_names = [s["name"] for s in result["skills"]]
        assert "security" in skill_names
        assert "quality" in skill_names
        assert "testing" in skill_names
```

---

## Phase 2: Polish (3 days)

### 2.1 Prompt Template Manager (Day 8-9)

**File:** `mahavishnu/engines/prompt_templates.py`

```python
"""Prompt template manager for reusable agent instructions.

Simple implementation using Python's string.Template.
Can be extended to Jinja2 if more complex templates are needed.
"""

from __future__ import annotations

from pathlib import Path
import logging
from string import Template
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class PromptTemplateManager:
    """Manage reusable prompt templates for agent instructions.

    Templates are stored in settings/prompts.yaml with support for
    variable substitution. This enables non-developers to customize
    agent behavior without code changes.

    Example:
        >>> manager = PromptTemplateManager()
        >>> instructions = manager.render(
        ...     "security_analyst",
        ...     language="Python",
        ...     focus_areas="SQL injection, XSS",
        ... )
    """

    def __init__(self, config_path: Path | None = None):
        """Initialize template manager.

        Args:
            config_path: Path to prompts.yaml. Defaults to settings/prompts.yaml.
        """
        self._templates: dict[str, Template] = {}
        self._load_builtin_templates()

        if config_path:
            self._load_custom_templates(config_path)

    def register(self, name: str, template: str) -> None:
        """Register a prompt template.

        Args:
            name: Template identifier (e.g., "security_analyst").
            template: Template string with $variable placeholders.
        """
        # Validate template syntax
        try:
            t = Template(template)
            # Test substitution with empty dict to catch missing required vars
            t.safe_substitute({})
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid template '{name}': {e}") from e

        self._templates[name] = Template(template)
        logger.debug(f"Registered prompt template: {name}")

    def render(self, name: str, **kwargs: Any) -> str:
        """Render a template with variables.

        Args:
            name: Template identifier.
            **kwargs: Variables to substitute.

        Returns:
            Rendered template string.

        Raises:
            KeyError: If template not found.
        """
        if name not in self._templates:
            raise KeyError(f"Template not found: {name}")

        return self._templates[name].substitute(**kwargs)

    def safe_render(self, name: str, **kwargs: Any) -> str:
        """Render a template, leaving unmatched variables as-is.

        Args:
            name: Template identifier.
            **kwargs: Variables to substitute.

        Returns:
            Rendered template string with unmatched vars preserved.
        """
        if name not in self._templates:
            raise KeyError(f"Template not found: {name}")

        return self._templates[name].safe_substitute(**kwargs)

    def list_templates(self) -> list[str]:
        """List all registered templates."""
        return list(self._templates.keys())

    def get_template(self, name: str) -> str | None:
        """Get raw template string."""
        if name not in self._templates:
            return None
        return self._templates[name].template

    def _load_builtin_templates(self) -> None:
        """Load built-in prompt templates."""
        builtin_templates = {
            "security_analyst": """You are a security vulnerability specialist analyzing ${language} code.

Focus areas:
${focus_areas}

Output format for each finding:
- Severity: (Critical/High/Medium/Low)
- Issue: <description>
- Location: <file:line>
- Remediation: <suggested fix>

Be thorough but prioritize by severity.""",

            "quality_engineer": """You are a code quality engineer reviewing ${language} code.

Standards enforced:
${standards}

Evaluate:
- Code complexity (max cyclomatic complexity: ${max_complexity:-15})
- Test coverage (minimum: ${min_coverage:-80}%)
- Documentation completeness
- Style guide adherence

Provide actionable improvement suggestions.""",

            "test_engineer": """You are a test engineer designing tests for ${language} code.

Target: ${target:-the provided code}

Create tests covering:
- Happy path scenarios
- Edge cases and boundary conditions
- Error handling paths
- Integration points

Use appropriate testing framework for ${language}.""",

            "performance_specialist": """You are a performance optimization specialist analyzing ${language} code.

Focus on:
- Algorithm complexity and efficiency
- Memory usage patterns
- Database query optimization
- Caching opportunities
- Resource bottlenecks

Provide specific optimization recommendations with expected impact.""",

            "debugging_specialist": """You are a debugging specialist investigating issues in ${language} code.

Error context:
${error_context:-No error context provided}

Investigation approach:
1. Analyze error messages and stack traces
2. Identify root cause
3. Trace execution flow
4. Propose fix with explanation

Be methodical and explain your reasoning.""",
        }

        for name, template in builtin_templates.items():
            self.register(name, template)

    def _load_custom_templates(self, config_path: Path) -> None:
        """Load custom templates from YAML file.

        Args:
            config_path: Path to prompts.yaml file.
        """
        if not config_path.exists():
            logger.debug(f"Custom prompts file not found: {config_path}")
            return

        try:
            with open(config_path) as f:
                data = yaml.safe_load(f)

            if not data or "prompts" not in data:
                return

            for name, template in data["prompts"].items():
                if isinstance(template, str):
                    self.register(name, template)
                    logger.info(f"Loaded custom prompt template: {name}")

        except Exception as e:
            logger.warning(f"Failed to load custom templates: {e}")


# Module-level singleton
_template_manager: PromptTemplateManager | None = None


def get_template_manager() -> PromptTemplateManager:
    """Get or create the shared template manager."""
    global _template_manager
    if _template_manager is None:
        from mahavishnu.core.config import get_settings
        settings = get_settings()
        config_path = settings.settings_dir / "prompts.yaml"
        _template_manager = PromptTemplateManager(config_path)
    return _template_manager
```

### 2.2 WebSocket Broadcasting for Team Events (Day 9-10)

**File:** Update `mahavishnu/websocket/server.py`

```python
# Add to MahavishnuWebSocketServer class:

async def broadcast_team_created(
    self,
    team_id: str,
    team_name: str,
    goal: str,
    members: list[str],
) -> None:
    """Broadcast team creation event.

    Args:
        team_id: Unique team identifier.
        team_name: Team name.
        goal: Original goal string.
        members: List of member names.
    """
    event = WebSocketProtocol.create_event(
        "team_created",
        {
            "team_id": team_id,
            "team_name": team_name,
            "goal": goal[:200],  # Truncate for broadcast
            "members": members,
            "timestamp": self._get_timestamp(),
        },
        room="global",
    )
    await self.broadcast_to_room("global", event)


async def broadcast_team_completed(
    self,
    team_id: str,
    success: bool,
    latency_ms: float,
) -> None:
    """Broadcast team execution completion event.

    Args:
        team_id: Unique team identifier.
        success: Whether execution succeeded.
        latency_ms: Execution latency in milliseconds.
    """
    event = WebSocketProtocol.create_event(
        "team_completed",
        {
            "team_id": team_id,
            "success": success,
            "latency_ms": latency_ms,
            "timestamp": self._get_timestamp(),
        },
        room=f"team:{team_id}",
    )
    await self.broadcast_to_room(f"team:{team_id}", event)
```

### 2.3 Add devops and api_design Skills (Day 10)

**File:** Update `mahavishnu/engines/goal_team_factory.py`

```python
# Add to SKILL_MAPPING dict:

SKILL_MAPPING: dict[str, SkillConfig] = {
    # ... existing skills ...

    "devops": SkillConfig(
        role="DevOps and CI/CD specialist",
        instructions="""Analyze and improve CI/CD pipelines and infrastructure:

- Pipeline efficiency and parallelization
- Build and deployment automation
- Infrastructure as code quality
- Container optimization
- Security scanning integration

Provide actionable recommendations for:
- Faster build times
- More reliable deployments
- Better observability""",
        tools=["search_code", "read_file", "run_command"],
        model="sonnet",
        temperature=0.4,
    ),

    "api_design": SkillConfig(
        role="API design specialist",
        instructions="""Design and review REST/GraphQL APIs:

- Endpoint naming and resource modeling
- Request/response formats
- Error handling patterns
- Authentication and authorization
- Versioning strategies
- Documentation completeness

Ensure APIs follow:
- RESTful principles (or GraphQL best practices)
- Consistent naming conventions
- Proper HTTP status codes
- Security best practices""",
        tools=["search_code", "read_file", "openapi_spec"],
        model="sonnet",
        temperature=0.5,
    ),
}

# Update DOMAIN_PATTERNS:
DOMAIN_PATTERNS = {
    # ... existing patterns ...
    "devops": [r"\bdevops\b", r"\bci/cd\b", r"\bpipeline\b", r"\bdeploy\b", r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b"],
    "api": [r"\bapi\b", r"\brest\b", r"\bgraphql\b", r"\bendpoint\b", r"\bopenapi\b", r"\bswagger\b"],
}
```

---

## Phase 3: Learning System (Future)

### When to Implement

After collecting **100+ team executions**, implement:

1. **Extend StatisticalRouter** for team configs (not separate TeamLearningEngine)
2. **Multi-dimensional quality scoring** from Crackerjack
3. **A/B testing** for team configurations
4. **Cold-start fallback** strategy

### Why Defer

Per AI Engineer review:
- Binary success/failure is too weak for learning
- Need structured configuration space
- No cold-start handling exists
- StatisticalRouter already has Wilson intervals and A/B testing

---

## Deferred Components

| Component | Reason | Revisit When |
|-----------|--------|--------------|
| **GraphExecutor** | DependencyGraph + PoolManager already handle this | Real use case with complex DAG |
| **SkillRegistry class** | Dict is fine for 9 skills | 50+ skills |
| **5 of 7 new skills** | Low value (compliance, ml_ops, etc.) | User requests |
| **Full TeamLearningEngine** | Extend StatisticalRouter instead | 100+ executions collected |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Goal parsing accuracy | > 85% | Manual review of 100 samples |
| Team creation latency | < 500ms P95 | Prometheus metrics |
| CLI adoption | > 10 uses/week | Command analytics |
| User rephrasing rate | < 20% | Goal edit tracking |

---

## Documentation

Create/update:

1. `docs/GOAL_DRIVEN_TEAMS.md` - User guide
2. `docs/MCP_TOOLS_SPECIFICATION.md` - Add team_from_goal docs
3. `README.md` - Add CLI examples

---

## Summary

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| **Phase 1** | 1 week | MCP tool + CLI command + tests |
| **Phase 2** | 3 days | Templates + WebSocket + 2 skills |
| **Phase 3** | Future | Learning (after 100+ executions) |

**Total: 10 days to deliver 90% of user value** (vs 25-40 days in v1.0)

---

**Document Version:** 2.0
**Incorporates:** 5-person committee review feedback
**Next Step:** 3-person specialist review
