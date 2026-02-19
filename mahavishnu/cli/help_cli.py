"""Comprehensive Help System for Mahavishnu CLI.

Provides detailed help for all commands with examples, use cases,
and troubleshooting guidance.

Usage:
    mahavishnu help              # Show general help overview
    mahavishnu help <command>    # Show help for specific command
    mahavishnu help --all        # Show complete reference
"""

from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()

# Command Categories
COMMAND_CATEGORIES: dict[str, dict[str, Any]] = {
    "Task Management": {
        "description": "Create, update, and manage tasks across repositories",
        "commands": {
            "task create": {
                "usage": "mahavishnu task create <title> -r <repo> [options]",
                "shorthand": "mhv tc",
                "description": "Create a new task with title, repository, and optional metadata",
                "options": {
                    "-r, --repository": "Repository name (required)",
                    "-d, --description": "Task description",
                    "-p, --priority": "Priority: low, medium, high, critical",
                    "-s, --status": "Initial status: pending, in_progress, blocked",
                    "-a, --assignee": "Assignee email or username",
                    "-t, --tag": "Tags (can specify multiple)",
                    "--due": "Due date (e.g., 'tomorrow', 'next week', '2024-12-31')",
                },
                "examples": [
                    "mahavishnu task create 'Fix login bug' -r session-buddy -p high -t bug",
                    "mahavishnu task create 'Add API endpoint' -r mahavishnu --due tomorrow",
                    "mhv tc 'Write tests' -r crackerjack -p medium",
                ],
            },
            "task list": {
                "usage": "mahavishnu task list [options]",
                "shorthand": "mhv tl",
                "description": "List tasks with optional filters",
                "options": {
                    "-r, --repository": "Filter by repository",
                    "-s, --status": "Filter by status",
                    "-p, --priority": "Filter by priority",
                    "-a, --assignee": "Filter by assignee",
                    "--search": "Search in title and description",
                    "-l, --limit": "Maximum results (default: 20)",
                    "-t, --tag": "Filter by tag",
                },
                "examples": [
                    "mahavishnu task list -r mahavishnu -s in_progress",
                    "mahavishnu task list -p high --search 'bug'",
                    "mhv tl -r session-buddy -t urgent",
                ],
            },
            "task update": {
                "usage": "mahavishnu task update <task_id> [options]",
                "shorthand": "mhv tu",
                "description": "Update task properties",
                "options": {
                    "--title": "New title",
                    "-d, --description": "New description",
                    "-s, --status": "New status",
                    "-p, --priority": "New priority",
                    "-a, --assignee": "New assignee",
                },
                "examples": [
                    "mahavishnu task update task-123 -s completed",
                    "mahavishnu task update task-456 -p critical --title 'URGENT: Fix outage'",
                    "mhv tu task-123 -s in_progress",
                ],
            },
            "task status": {
                "usage": "mahavishnu task status <task_id> <status>",
                "shorthand": "mhv ts",
                "description": "Quick status update (shorthand for update --status)",
                "examples": [
                    "mahavishnu task status task-123 completed",
                    "mhv ts task-456 in_progress",
                ],
            },
            "task delete": {
                "usage": "mahavishnu task delete <task_id> [options]",
                "shorthand": "mhv td",
                "description": "Delete a task (requires confirmation)",
                "options": {
                    "-f, --force": "Skip confirmation prompt",
                },
                "examples": [
                    "mahavishnu task delete task-123",
                    "mahavishnu task delete task-456 -f",
                    "mhv td task-789 -f",
                ],
            },
        },
    },
    "Repository Management": {
        "description": "View and manage repository configuration",
        "commands": {
            "list-repos": {
                "usage": "mahavishnu list-repos [options]",
                "description": "List configured repositories",
                "options": {
                    "-t, --tag": "Filter by tag",
                    "-r, --role": "Filter by role",
                },
                "examples": [
                    "mahavishnu list-repos",
                    "mahavishnu list-repos --tag backend",
                    "mahavishnu list-repos --role tool",
                ],
            },
            "list-roles": {
                "usage": "mahavishnu list-roles",
                "description": "List all available roles with descriptions",
                "examples": ["mahavishnu list-roles"],
            },
            "show-role": {
                "usage": "mahavishnu show-role <role_name>",
                "description": "Show detailed information about a specific role",
                "examples": [
                    "mahavishnu show-role orchestrator",
                    "mahavishnu show-role tool",
                ],
            },
            "list-nicknames": {
                "usage": "mahavishnu list-nicknames",
                "description": "List all repository nicknames",
                "examples": ["mahavishnu list-nicknames"],
            },
        },
    },
    "Search & Discovery": {
        "description": "Semantic search and knowledge discovery",
        "commands": {
            "search tasks": {
                "usage": "mahavishnu search tasks <query>",
                "description": "Semantic search across tasks using natural language",
                "examples": [
                    "mahavishnu search tasks 'bug fix authentication'",
                    "mahavishnu search tasks 'API endpoint implementation'",
                ],
            },
            "search similar": {
                "usage": "mahavishnu search similar <task_id>",
                "description": "Find tasks similar to a given task",
                "examples": ["mahavishnu search similar task-123"],
            },
        },
    },
    "Content Ingestion": {
        "description": "Ingest web content, blogs, and books",
        "commands": {
            "ingest web": {
                "usage": "mahavishnu ingest web --url <url>",
                "description": "Ingest webpage content",
                "examples": ["mahavishnu ingest web --url 'https://example.com'"],
            },
            "ingest blog": {
                "usage": "mahavishnu ingest blog --url <url>",
                "description": "Ingest blog post content",
                "examples": [
                    "mahavishnu ingest blog --url 'https://blog.example.com/post'"
                ],
            },
            "ingest book": {
                "usage": "mahavishnu ingest book --path <path>",
                "description": "Ingest book (PDF/EPUB)",
                "examples": ["mahavishnu ingest book --path ~/Documents/book.pdf"],
            },
        },
    },
    "MCP Server": {
        "description": "MCP server lifecycle management",
        "commands": {
            "mcp start": {
                "usage": "mahavishnu mcp start [options]",
                "description": "Start the MCP server",
                "options": {
                    "-h, --host": "Host address (default: 127.0.0.1)",
                    "-p, --port": "Port number (default: 3000)",
                },
                "examples": [
                    "mahavishnu mcp start",
                    "mahavishnu mcp start --port 8680",
                ],
            },
            "mcp status": {
                "usage": "mahavishnu mcp status",
                "description": "Check MCP server configuration status",
                "examples": ["mahavishnu mcp status"],
            },
            "mcp health": {
                "usage": "mahavishnu mcp health",
                "description": "Check if MCP server is running",
                "examples": ["mahavishnu mcp health"],
            },
        },
    },
    "Worker & Pool Management": {
        "description": "Worker orchestration and multi-pool management",
        "commands": {
            "workers spawn": {
                "usage": "mahavishnu workers spawn [options]",
                "description": "Spawn worker instances",
                "options": {
                    "-t, --type": "Worker type (terminal-qwen, terminal-claude)",
                    "-n, --count": "Number of workers (default: 1)",
                },
                "examples": [
                    "mahavishnu workers spawn --type terminal-qwen --count 3",
                ],
            },
            "workers execute": {
                "usage": "mahavishnu workers execute --prompt <prompt> [options]",
                "description": "Execute task on workers",
                "options": {
                    "-p, --prompt": "Task prompt (required)",
                    "-n, --count": "Number of workers",
                    "-t, --type": "Worker type",
                    "-T, --timeout": "Timeout in seconds",
                },
                "examples": [
                    "mahavishnu workers execute --prompt 'Write tests' --count 3",
                ],
            },
            "pool spawn": {
                "usage": "mahavishnu pool spawn [options]",
                "description": "Spawn a worker pool",
                "options": {
                    "-t, --type": "Pool type (mahavishnu, session-buddy, kubernetes)",
                    "-n, --name": "Pool name",
                    "-m, --min": "Minimum workers",
                    "-M, --max": "Maximum workers",
                },
                "examples": [
                    "mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5",
                ],
            },
            "pool list": {
                "usage": "mahavishnu pool list",
                "description": "List active pools",
                "examples": ["mahavishnu pool list"],
            },
            "pool health": {
                "usage": "mahavishnu pool health",
                "description": "Get health status of all pools",
                "examples": ["mahavishnu pool health"],
            },
        },
    },
    "Terminal Management": {
        "description": "Terminal session management",
        "commands": {
            "terminal launch": {
                "usage": "mahavishnu terminal launch <command> [options]",
                "description": "Launch terminal sessions",
                "options": {
                    "-c, --count": "Number of sessions",
                    "--columns": "Terminal width",
                    "--rows": "Terminal height",
                },
                "examples": ["mahavishnu terminal launch 'python script.py' --count 2"],
            },
            "terminal list": {
                "usage": "mahavishnu terminal list",
                "description": "List active terminal sessions",
                "examples": ["mahavishnu terminal list"],
            },
            "terminal send": {
                "usage": "mahavishnu terminal send <session_id> <command>",
                "description": "Send command to terminal",
                "examples": ["mahavishnu terminal send session-123 'ls -la'"],
            },
            "terminal capture": {
                "usage": "mahavishnu terminal capture <session_id> [options]",
                "description": "Capture terminal output",
                "options": {"-l, --lines": "Number of lines (default: 100)"},
                "examples": ["mahavishnu terminal capture session-123 --lines 50"],
            },
            "terminal close": {
                "usage": "mahavishnu terminal close <session_id>",
                "description": "Close terminal session (use 'all' to close all)",
                "examples": [
                    "mahavishnu terminal close session-123",
                    "mahavishnu terminal close all",
                ],
            },
        },
    },
    "Configuration": {
        "description": "Configuration validation and setup",
        "commands": {
            "init": {
                "usage": "mahavishnu init",
                "description": "Initialize default configuration",
                "examples": ["mahavishnu init"],
            },
            "config validate": {
                "usage": "mahavishnu config validate",
                "description": "Validate configuration files",
                "examples": ["mahavishnu config validate"],
            },
        },
    },
    "Onboarding": {
        "description": "Interactive tutorial and getting started",
        "commands": {
            "tutorial": {
                "usage": "mahavishnu tutorial",
                "description": "Start interactive tutorial (can skip with Ctrl+C)",
                "examples": ["mahavishnu tutorial"],
            },
        },
    },
}


def show_general_help() -> None:
    """Show general help overview with command categories."""
    console.print(
        Panel.fit(
            "[bold cyan]Mahavishnu[/] - Multi-Engine Orchestration Platform\n\n"
            "Manage tasks, workflows, and coordination across multiple repositories.",
            title="Help",
            border_style="cyan",
        )
    )

    console.print("\n[bold]Quick Start[/]")
    console.print("  mahavishnu tutorial           # Interactive tutorial")
    console.print("  mahavishnu --help             # Basic command list")
    console.print("  mahavishnu help <command>     # Detailed command help")

    console.print("\n[bold]Command Categories[/]")

    for category, info in COMMAND_CATEGORIES.items():
        console.print(f"\n[cyan]{category}[/]")
        console.print(f"  {info['description']}")
        console.print(f"  Commands: {', '.join(info['commands'].keys())}")

    console.print("\n[bold]Common Workflows[/]")
    console.print("  1. Create a task:      mahavishnu task create 'Fix bug' -r my-repo")
    console.print("  2. List tasks:         mahavishnu task list -s in_progress")
    console.print("  3. Update status:      mahavishnu task status task-123 completed")
    console.print("  4. Search tasks:       mahavishnu search tasks 'API endpoint'")

    console.print("\n[bold]Shorthand Commands[/]")
    console.print("  tc = task create, tl = task list, tu = task update")
    console.print("  ts = task status, td = task delete")

    console.print("\n[bold]Getting Help[/]")
    console.print("  mahavishnu help --all          # Complete reference")
    console.print("  mahavishnu <command> --help    # Command-specific help")
    console.print("  docs/QUICK_START.md            # Quick start guide")


def show_command_help(command: str) -> None:
    """Show detailed help for a specific command."""
    # Search for command in categories
    for category, info in COMMAND_CATEGORIES.items():
        if command in info["commands"]:
            cmd_info = info["commands"][command]

            console.print(
                Panel.fit(
                    f"[bold cyan]{command}[/]\n{cmd_info['description']}",
                    title=f"{category} Command",
                    border_style="cyan",
                )
            )

            if "shorthand" in cmd_info:
                console.print(f"\n[bold]Shorthand:[/] {cmd_info['shorthand']}")

            console.print(f"\n[bold]Usage:[/]")
            console.print(f"  {cmd_info['usage']}")

            if "options" in cmd_info:
                console.print(f"\n[bold]Options:[/]")
                for opt, desc in cmd_info["options"].items():
                    console.print(f"  [yellow]{opt}[/]  {desc}")

            if "examples" in cmd_info:
                console.print(f"\n[bold]Examples:[/]")
                for example in cmd_info["examples"]:
                    console.print(f"  [green]{example}[/]")

            return

    # Command not found
    console.print(f"[red]Unknown command: {command}[/]")
    console.print("\nUse 'mahavishnu help' to see available commands.")


def show_all_help() -> None:
    """Show complete command reference."""
    console.print(
        Panel.fit(
            "[bold cyan]Mahavishnu Complete Command Reference[/]",
            border_style="cyan",
        )
    )

    for category, info in COMMAND_CATEGORIES.items():
        console.print(f"\n[bold cyan]{'=' * 60}[/]")
        console.print(f"[bold cyan]{category}[/]")
        console.print(f"[dim]{info['description']}[/]")
        console.print(f"[bold cyan]{'=' * 60}[/]")

        for cmd_name, cmd_info in info["commands"].items():
            console.print(f"\n[bold]{cmd_name}[/]")
            console.print(f"  {cmd_info['description']}")

            if "shorthand" in cmd_info:
                console.print(f"  [dim]Shorthand: {cmd_info['shorthand']}[/]")

            console.print(f"  [yellow]Usage:[/] {cmd_info['usage']}")

            if "examples" in cmd_info and cmd_info["examples"]:
                console.print(f"  [green]Example:[/] {cmd_info['examples'][0]}")


# CLI Group
@click.group(name="help", invoke_without_command=True)
@click.argument("command", required=False)
@click.option("--all", "show_all", is_flag=True, help="Show complete reference")
@click.pass_context
def help_group(ctx: click.Context, command: str | None, show_all: bool) -> None:
    """Comprehensive help system for Mahavishnu."""
    if show_all:
        show_all_help()
    elif command:
        show_command_help(command)
    else:
        show_general_help()


# Add help commands for each category
@help_group.command("tasks")
def help_tasks() -> None:
    """Help for task management commands."""
    _show_category_help("Task Management")


@help_group.command("repos")
def help_repos() -> None:
    """Help for repository management commands."""
    _show_category_help("Repository Management")


@help_group.command("search")
def help_search() -> None:
    """Help for search and discovery commands."""
    _show_category_help("Search & Discovery")


@help_group.command("ingest")
def help_ingest() -> None:
    """Help for content ingestion commands."""
    _show_category_help("Content Ingestion")


@help_group.command("mcp")
def help_mcp() -> None:
    """Help for MCP server commands."""
    _show_category_help("MCP Server")


@help_group.command("pools")
def help_pools() -> None:
    """Help for worker and pool management commands."""
    _show_category_help("Worker & Pool Management")


@help_group.command("terminal")
def help_terminal() -> None:
    """Help for terminal management commands."""
    _show_category_help("Terminal Management")


def _show_category_help(category: str) -> None:
    """Show help for a specific category."""
    if category not in COMMAND_CATEGORIES:
        console.print(f"[red]Unknown category: {category}[/]")
        return

    info = COMMAND_CATEGORIES[category]
    console.print(
        Panel.fit(
            f"[bold cyan]{category}[/]\n{info['description']}",
            border_style="cyan",
        )
    )

    for cmd_name, cmd_info in info["commands"].items():
        console.print(f"\n[bold]{cmd_name}[/]")
        console.print(f"  {cmd_info['description']}")

        if "shorthand" in cmd_info:
            console.print(f"  [dim]Shorthand: {cmd_info['shorthand']}[/]")

        console.print(f"  [yellow]Usage:[/] {cmd_info['usage']}")

        if "options" in cmd_info:
            console.print(f"  [bold]Options:[/]")
            for opt, desc in cmd_info["options"].items():
                console.print(f"    [yellow]{opt}[/]  {desc}")

        if "examples" in cmd_info:
            console.print(f"  [bold]Examples:[/]")
            for example in cmd_info["examples"]:
                console.print(f"    [green]{example}[/]")
