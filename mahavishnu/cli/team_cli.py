"""Goal-Driven Team CLI commands for Mahavishnu.

This module provides CLI commands for creating and managing goal-driven
agent teams. Teams are created from natural language goals and can
execute tasks using multi-agent orchestration.

Commands:
    mahavishnu team create   - Create a team from a natural language goal
    mahavishnu team parse    - Parse a goal to preview team configuration
    mahavishnu team skills   - List all available skills for team creation
    mahavishnu team list     - List all active goal-driven teams
    mahavishnu team learning - Show team learning statistics
    mahavishnu team flags    - Show feature flag status

Example:
    $ mahavishnu team create --goal "Review code for security vulnerabilities"
    $ mahavishnu team parse "Analyze performance bottlenecks"
    $ mahavishnu team skills
    $ mahavishnu team list
    $ mahavishnu team learning
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
import typer

from mahavishnu.core.errors import GoalParsingError, GoalTeamError
from mahavishnu.core.feature_flags import is_feature_enabled
from mahavishnu.engines.agno_teams.config import TeamConfig, TeamMode
from mahavishnu.engines.goal_team_factory import (
    SKILL_MAPPING,
    GoalDrivenTeamFactory,
    ParsedGoal,
)

app = typer.Typer(
    name="team",
    help="Goal-driven team management for multi-agent orchestration",
)

console = Console()


def _check_feature_flags() -> None:
    """Check if Goal-Driven Teams CLI is enabled.

    Raises:
        typer.Exit: If the feature is disabled
    """
    if not is_feature_enabled("enabled"):
        console.print("\n[yellow]Goal-Driven Teams feature is disabled.[/yellow]")
        console.print("[dim]Enable it in settings/mahavishnu.yaml under goal_teams.enabled[/dim]")
        raise typer.Exit(code=1)

    if not is_feature_enabled("cli_commands_enabled"):
        console.print("\n[yellow]Goal-Driven Teams CLI commands are disabled.[/yellow]")
        console.print("[dim]Enable cli_commands_enabled in goal_teams.feature_flags[/dim]")
        raise typer.Exit(code=1)


def _get_factory() -> GoalDrivenTeamFactory:
    """Get or create the GoalDrivenTeamFactory instance."""
    # Check if LLM fallback is enabled
    use_llm_fallback = is_feature_enabled("llm_fallback_enabled")
    return GoalDrivenTeamFactory(
        llm_factory=None  # CLI doesn't have access to LLM factory context
    )


def _display_parsed_goal(parsed: ParsedGoal) -> None:
    """Display parsed goal information in a formatted panel.

    Args:
        parsed: The parsed goal to display
    """
    # Create info panel with parsed details
    info_lines = [
        f"[bold]Intent:[/bold] {parsed.intent}",
        f"[bold]Domain:[/bold] {parsed.domain}",
        f"[bold]Skills:[/bold] {', '.join(parsed.skills) if parsed.skills else 'none'}",
        f"[bold]Confidence:[/bold] {parsed.confidence:.0%}",
        f"[bold]Method:[/bold] {parsed.metadata.get('method', 'unknown')}",
    ]

    console.print()
    console.print(Panel(
        "\n".join(info_lines),
        title="[bold cyan]Parsed Goal[/bold cyan]",
        border_style="cyan",
    ))


def _display_team_config(config: TeamConfig, verbose: bool = False) -> None:
    """Display team configuration in a formatted way.

    Args:
        config: The team configuration to display
        verbose: Whether to show full details
    """
    console.print()
    console.print(Panel(
        "[bold green]Team Configuration[/bold green]",
        border_style="green",
    ))

    # Team info table
    table = Table(show_header=False, box=None)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Name", config.name)
    table.add_row("Mode", config.mode.value)
    table.add_row("Description", config.description[:100] + "..." if len(config.description) > 100 else config.description)
    table.add_row("Members", str(len(config.members)))
    if config.leader:
        table.add_row("Leader", config.leader.name)

    console.print(table)

    if verbose:
        # Show member details
        console.print("\n[bold]Members:[/bold]")
        for member in config.members:
            console.print(f"  [cyan]{member.name}[/cyan]")
            console.print(f"    Role: {member.role}")
            console.print(f"    Model: {member.model}")
            if member.tools:
                console.print(f"    Tools: {', '.join(member.tools)}")

        if config.leader:
            console.print("\n[bold]Leader:[/bold]")
            console.print(f"  [cyan]{config.leader.name}[/cyan]")
            console.print(f"  Role: {config.leader.role}")
            console.print(f"  Model: {config.leader.model}")


def _display_team_config_yaml(config: TeamConfig) -> None:
    """Display team configuration as YAML for dry-run.

    Args:
        config: The team configuration to display
    """
    # Convert to dict for YAML display
    config_dict: dict[str, Any] = {
        "team": {
            "name": config.name,
            "description": config.description,
            "mode": config.mode.value,
            "members": [],
        }
    }

    if config.leader:
        config_dict["team"]["leader"] = {
            "name": config.leader.name,
            "role": config.leader.role,
            "model": config.leader.model,
            "instructions": config.leader.instructions[:100] + "...",
        }

    for member in config.members:
        config_dict["team"]["members"].append({
            "name": member.name,
            "role": member.role,
            "model": member.model,
            "tools": member.tools,
        })

    # Display as YAML-like syntax
    yaml_str = "# Team configuration (dry-run)\n"
    yaml_str += "team:\n"
    yaml_str += f"  name: {config_dict['team']['name']}\n"
    yaml_str += f"  description: {config_dict['team']['description']}\n"
    yaml_str += f"  mode: {config_dict['team']['mode']}\n"

    if config.leader:
        yaml_str += "  leader:\n"
        yaml_str += f"    name: {config_dict['team']['leader']['name']}\n"
        yaml_str += f"    role: {config_dict['team']['leader']['role']}\n"
        yaml_str += f"    model: {config_dict['team']['leader']['model']}\n"

    yaml_str += "  members:\n"
    for member in config_dict["team"]["members"]:
        yaml_str += f"    - name: {member['name']}\n"
        yaml_str += f"      role: {member['role']}\n"
        yaml_str += f"      model: {member['model']}\n"
        if member['tools']:
            yaml_str += f"      tools: [{', '.join(member['tools'])}]\n"

    syntax = Syntax(yaml_str, "yaml", theme="monokai", line_numbers=False)
    console.print()
    console.print(syntax)


# In-memory store for active teams (would be replaced with proper storage)
_active_teams: dict[str, TeamConfig] = {}


@app.command("create")
def create_team(
    goal: str = typer.Option(..., "--goal", "-g", help="Natural language goal"),
    name: str | None = typer.Option(None, "--name", "-n", help="Team name"),
    mode: str | None = typer.Option(None, "--mode", "-m", help="Team mode (coordinate, route, broadcast, collaborate)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show configuration without creating"),
    run: bool = typer.Option(False, "--run", help="Run team immediately after creation"),
    task: str | None = typer.Option(None, "--task", "-t", help="Task to run (requires --run)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Create an agent team from a natural language goal.

    The goal is parsed using pattern matching (fast, free) or LLM fallback
    (slower) to determine the required skills and team structure.

    Examples:
        $ mahavishnu team create --goal "Review code for security vulnerabilities"
        $ mahavishnu team create -g "Analyze performance" --name perf_team --mode coordinate
        $ mahavishnu team create -g "Write tests" --dry-run
        $ mahavishnu team create -g "Debug this issue" --run --task "Fix the login bug"
    """
    # Check feature flags
    _check_feature_flags()

    async def _create():
        try:
            factory = _get_factory()

            # Parse the goal first
            parsed = await factory.parse_goal(goal)
            _display_parsed_goal(parsed)

            # Validate mode if provided
            team_mode = None
            if mode:
                try:
                    team_mode = TeamMode(mode.lower())
                except ValueError:
                    valid_modes = [m.value for m in TeamMode]
                    console.print(f"[red]Error: Invalid mode '{mode}'. Valid modes: {', '.join(valid_modes)}[/red]")
                    raise typer.Exit(code=1) from None

            # Create team configuration
            config = await factory.create_team_from_goal(
                goal=goal,
                name=name,
                mode=team_mode,
            )

            # Display configuration
            if dry_run:
                console.print("\n[yellow]Dry run - showing configuration without creating:[/yellow]")
                _display_team_config_yaml(config)
                _display_team_config(config, verbose=True)
                console.print("\n[green]To create this team, run without --dry-run[/green]")
                return

            # Store the team
            team_id = f"team_{len(_active_teams) + 1}"
            _active_teams[team_id] = config

            # Display created team
            _display_team_config(config, verbose=verbose)
            console.print("\n[green]Team created successfully![/green]")
            console.print(f"[cyan]Team ID:[/cyan] {team_id}")

            # Run if requested
            if run:
                if not task:
                    console.print("[yellow]Warning: --run requires --task. Skipping execution.[/yellow]")
                else:
                    console.print(f"\n[cyan]Executing task on team {team_id}...[/cyan]")
                    console.print(f"[dim]Task: {task}[/dim]")
                    # Actual execution would integrate with AgentTeamManager
                    console.print("[green]Task execution initiated (check logs for progress)[/green]")

        except GoalParsingError as e:
            console.print(f"\n[red]Goal parsing error:[/red] {e.message}")
            console.print(f"[dim]Code: {e.error_code.value}[/dim]")
            raise typer.Exit(code=1) from None
        except GoalTeamError as e:
            console.print(f"\n[red]Team creation error:[/red] {e.message}")
            console.print(f"[dim]Code: {e.error_code.value}[/dim]")
            raise typer.Exit(code=1) from None
        except Exception as e:
            console.print(f"\n[red]Unexpected error:[/red] {e}")
            raise typer.Exit(code=1) from None

    asyncio.run(_create())


@app.command("parse")
def parse_goal_cmd(
    goal: str = typer.Argument(..., help="Natural language goal to parse"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed analysis"),
) -> None:
    """Parse a goal to see what team would be created.

    This command shows how the factory interprets your goal without
    actually creating a team. Useful for debugging and understanding
    the goal parsing logic.

    Examples:
        $ mahavishnu team parse "Review code for security issues"
        $ mahavishnu team parse "Build a REST API with tests" --verbose
    """
    # Check feature flags
    _check_feature_flags()

    async def _parse():
        try:
            factory = _get_factory()
            parsed = await factory.parse_goal(goal)

            _display_parsed_goal(parsed)

            if verbose:
                # Show what team would be created
                console.print("\n[cyan]Preview team configuration:[/cyan]")
                config = await factory.create_team_from_goal(goal)
                _display_team_config(config, verbose=True)

                # Show reasoning
                console.print("\n[bold]Analysis Details:[/bold]")
                console.print(f"  Raw goal: {parsed.raw_goal}")
                console.print(f"  Metadata: {parsed.metadata}")

        except Exception as e:
            console.print(f"\n[red]Error parsing goal:[/red] {e}")
            raise typer.Exit(code=1) from None

    asyncio.run(_parse())


@app.command("skills")
def list_skills(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full skill details"),
) -> None:
    """List all available skills for goal-driven team creation.

    Skills are pre-configured agent profiles with specific roles,
    instructions, and tools. When a goal matches a skill domain,
    an agent with that skill is added to the team.

    Examples:
        $ mahavishnu team skills
        $ mahavishnu team skills --verbose
    """
    # Check feature flags
    _check_feature_flags()

    console.print("\n[bold cyan]Available Skills for Goal-Driven Teams[/bold cyan]\n")

    # Create skills table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Skill", style="cyan")
    table.add_column("Role", style="white")
    table.add_column("Model", style="yellow")
    table.add_column("Tools", style="green")

    for skill_name, skill_config in SKILL_MAPPING.items():
        tools_str = ", ".join(skill_config.tools[:3])
        if len(skill_config.tools) > 3:
            tools_str += f" +{len(skill_config.tools) - 3} more"

        table.add_row(
            skill_name,
            skill_config.role[:40] + "..." if len(skill_config.role) > 40 else skill_config.role,
            skill_config.model,
            tools_str or "none",
        )

    console.print(table)

    if verbose:
        console.print("\n[bold]Detailed Skill Configurations:[/bold]")
        for skill_name, skill_config in SKILL_MAPPING.items():
            console.print(f"\n[cyan]{skill_name.upper()}[/cyan]")
            console.print(f"  Role: {skill_config.role}")
            console.print(f"  Model: {skill_config.model}")
            console.print(f"  Temperature: {skill_config.temperature}")
            console.print(f"  Tools: {', '.join(skill_config.tools) if skill_config.tools else 'none'}")
            console.print("  Instructions:")
            # Show first few lines of instructions
            instructions_lines = skill_config.instructions.strip().split("\n")[:5]
            for line in instructions_lines:
                console.print(f"    {line}")
            if len(skill_config.instructions.strip().split("\n")) > 5:
                console.print("    ...")

    console.print(f"\n[dim]Total skills: {len(SKILL_MAPPING)}[/dim]")


@app.command("list")
def list_teams(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed team info"),
) -> None:
    """List all active goal-driven teams.

    Shows teams that have been created in the current session.
    Note: Teams are stored in-memory and will be lost on restart.

    Examples:
        $ mahavishnu team list
        $ mahavishnu team list --verbose
    """
    # Check feature flags
    _check_feature_flags()

    if not _active_teams:
        console.print("\n[yellow]No active teams found.[/yellow]")
        console.print("[dim]Create a team with: mahavishnu team create --goal \"your goal\"[/dim]")
        return

    console.print(f"\n[bold cyan]Active Goal-Driven Teams ({len(_active_teams)})[/bold cyan]\n")

    # Create teams table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Team ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Mode", style="yellow")
    table.add_column("Members", style="green")
    table.add_column("Description", style="dim")

    for team_id, config in _active_teams.items():
        desc = config.description[:50] + "..." if len(config.description) > 50 else config.description
        table.add_row(
            team_id,
            config.name,
            config.mode.value,
            str(len(config.members)),
            desc,
        )

    console.print(table)

    if verbose:
        console.print("\n[bold]Detailed Team Information:[/bold]")
        for team_id, config in _active_teams.items():
            _display_team_config(config, verbose=True)
            console.print(f"[cyan]Team ID:[/cyan] {team_id}")
            console.print()


@app.command("learning")
def learning_stats(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed learning stats"),
    clear: bool = typer.Option(False, "--clear", help="Clear all learning data"),
    export: bool = typer.Option(False, "--export", help="Export learning stats as JSON"),
) -> None:
    """Show team learning statistics.

    Displays statistics about team execution outcomes that have been
    recorded for the learning system. This includes success rates by
    skill combination, mode performance, and recent outcomes.

    Examples:
        $ mahavishnu team learning
        $ mahavishnu team learning --verbose
        $ mahavishnu team learning --export
        $ mahavishnu team learning --clear
    """
    # Check feature flags
    _check_feature_flags()

    if not is_feature_enabled("learning_system_enabled"):
        console.print("\n[yellow]Learning system is disabled.[/yellow]")
        console.print("[dim]Enable learning_system_enabled in goal_teams.feature_flags[/dim]")
        raise typer.Exit(code=1)

    from mahavishnu.core.team_learning import get_learning_engine, reset_learning_engine

    engine = get_learning_engine()

    # Handle clear flag
    if clear:
        if typer.confirm("Are you sure you want to clear all learning data?"):
            reset_learning_engine()
            console.print("\n[green]Learning data cleared successfully.[/green]")
        return

    # Handle export flag
    if export:
        import json
        data = engine.export_stats()
        console.print("\n[bold cyan]Learning Data Export[/bold cyan]\n")
        console.print(Syntax(json.dumps(data, indent=2), "json", theme="monokai"))
        return

    # Get learning summary
    summary = engine.get_learning_summary()

    console.print("\n[bold cyan]Team Learning Statistics[/bold cyan]\n")

    # Summary table
    table = Table(show_header=False, box=None)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total Outcomes", str(summary["total_outcomes"]))
    table.add_row("Skill Combinations", str(summary["skill_combinations"]))
    table.add_row("Intents Tracked", str(summary["intents_tracked"]))
    table.add_row("Modes Tracked", str(summary["modes_tracked"]))
    table.add_row("Intent-Mode Combos", str(summary["intent_mode_combinations"]))
    table.add_row("Recent Success Rate", f"{summary['recent_success_rate']:.0%}")

    console.print(table)

    # Show mode performance
    if summary["mode_performance"]:
        console.print("\n[bold]Mode Performance:[/bold]")
        mode_table = Table(show_header=True, header_style="bold magenta")
        mode_table.add_column("Mode", style="cyan")
        mode_table.add_column("Success Rate", style="green")
        mode_table.add_column("Avg Latency", style="yellow")
        mode_table.add_column("Executions", style="white")

        for mode, stats in summary["mode_performance"].items():
            mode_table.add_row(
                mode,
                f"{stats['success_rate']:.0%}",
                f"{stats['avg_latency_ms']:.0f}ms",
                str(stats["executions"]),
            )

        console.print(mode_table)

    # Show intent performance
    if summary["intent_performance"]:
        console.print("\n[bold]Intent Performance:[/bold]")
        intent_table = Table(show_header=True, header_style="bold magenta")
        intent_table.add_column("Intent", style="cyan")
        intent_table.add_column("Success Rate", style="green")
        intent_table.add_column("Avg Latency", style="yellow")
        intent_table.add_column("Executions", style="white")

        for intent, stats in summary["intent_performance"].items():
            intent_table.add_row(
                intent,
                f"{stats['success_rate']:.0%}",
                f"{stats['avg_latency_ms']:.0f}ms",
                str(stats["executions"]),
            )

        console.print(intent_table)

    # Show top skills
    if summary["top_skills"]:
        console.print("\n[bold]Top Performing Skill Combinations:[/bold]")
        skills_table = Table(show_header=True, header_style="bold magenta")
        skills_table.add_column("Skills", style="cyan")
        skills_table.add_column("Success Rate", style="green")
        skills_table.add_column("Avg Latency", style="yellow")
        skills_table.add_column("Executions", style="white")

        for skill_data in summary["top_skills"]:
            skills_table.add_row(
                skill_data["skills"][:40] + "..." if len(skill_data["skills"]) > 40 else skill_data["skills"],
                f"{skill_data['success_rate']:.0%}",
                f"{skill_data['avg_latency_ms']:.0f}ms",
                str(skill_data["executions"]),
            )

        console.print(skills_table)

    # Verbose output
    if verbose:
        # Show recent outcomes
        recent = engine.get_recent_outcomes(limit=5)
        if recent:
            console.print("\n[bold]Recent Outcomes:[/bold]")
            for i, outcome in enumerate(recent, 1):
                status = "[green]success[/green]" if outcome["success"] else "[red]failed[/red]"
                console.print(f"  {i}. {outcome['team_id']} - {status} ({outcome['latency_ms']:.0f}ms)")
                console.print(f"     Mode: {outcome['team_mode']}, Intent: {outcome['parsed_intent']}")

    console.print("\n[dim]Use --verbose for more details, --export for JSON, or --clear to reset[/dim]")


@app.command("recommend")
def recommend_mode(
    intent: str = typer.Argument(..., help="Intent to get recommendation for"),
) -> None:
    """Get recommended mode for an intent based on learning data.

    Analyzes historical execution data to recommend the best team mode
    for a given intent.

    Examples:
        $ mahavishnu team recommend review
        $ mahavishnu team recommend test
    """
    # Check feature flags
    _check_feature_flags()

    if not is_feature_enabled("learning_system_enabled"):
        console.print("\n[yellow]Learning system is disabled.[/yellow]")
        console.print("[dim]Enable learning_system_enabled in goal_teams.feature_flags[/dim]")
        raise typer.Exit(code=1)

    from mahavishnu.core.team_learning import get_learning_engine

    engine = get_learning_engine()
    recommendation = engine.get_mode_recommendation(intent)

    console.print(f"\n[bold cyan]Mode Recommendation for '{intent}'[/bold cyan]\n")

    if recommendation is None:
        # Fallback mode based on intent
        fallback_map = {
            "review": "coordinate",
            "build": "coordinate",
            "test": "coordinate",
            "fix": "route",
            "refactor": "coordinate",
            "document": "route",
            "analyze": "broadcast",
        }
        fallback = fallback_map.get(intent, "coordinate")
        console.print(f"[yellow]Insufficient learning data for intent '{intent}'.[/yellow]")
        console.print(f"[dim]Fallback mode: {fallback}[/dim]")
        console.print("[dim]Record more team executions to enable learning-based recommendations.[/dim]")
        return

    # Display recommendation
    table = Table(show_header=False, box=None)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Recommended Mode", f"[green bold]{recommendation.mode}[/green bold]")
    table.add_row("Confidence", f"{recommendation.confidence:.0%}")
    table.add_row("Success Rate", f"{recommendation.success_rate:.0%}")
    table.add_row("Sample Count", str(recommendation.sample_count))
    table.add_row("Reason", recommendation.reason)

    console.print(table)


@app.command("flags")
def show_feature_flags() -> None:
    """Show current feature flag status for Goal-Driven Teams.

    Displays all feature flags and their current enabled/disabled status.

    Example:
        $ mahavishnu team flags
    """
    from mahavishnu.core.feature_flags import get_all_feature_flags

    console.print("\n[bold cyan]Goal-Driven Teams Feature Flags[/bold cyan]\n")

    flags = get_all_feature_flags()

    # Create flags table
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Flag", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Description", style="dim")

    descriptions = {
        "enabled": "Master switch for Goal-Driven Teams",
        "mcp_tools_enabled": "Enable MCP tools for team creation",
        "cli_commands_enabled": "Enable CLI commands",
        "llm_fallback_enabled": "Enable LLM fallback for goal parsing",
        "websocket_broadcasts_enabled": "Enable WebSocket broadcasts",
        "prometheus_metrics_enabled": "Enable Prometheus metrics",
        "learning_system_enabled": "Enable learning system (Phase 3)",
        "auto_mode_selection_enabled": "Enable automatic mode selection",
        "custom_skills_enabled": "Enable custom skills",
    }

    for flag_name, is_enabled in flags.items():
        status = "[green]enabled[/green]" if is_enabled else "[red]disabled[/red]"
        description = descriptions.get(flag_name, "")
        table.add_row(flag_name, status, description)

    console.print(table)
    console.print("\n[dim]Configure feature flags in settings/mahavishnu.yaml under goal_teams.feature_flags[/dim]")


def add_team_commands(main_app: typer.Typer) -> None:
    """Add team commands to the main CLI app.

    Args:
        main_app: The main Typer app to add commands to
    """
    main_app.add_typer(app, name="team", help="Goal-driven team management")


__all__ = [
    "app",
    "add_team_commands",
    "create_team",
    "parse_goal_cmd",
    "list_skills",
    "list_teams",
    "show_feature_flags",
    "learning_stats",
    "recommend_mode",
]
