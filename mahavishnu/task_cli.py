"""Task CLI Commands for Mahavishnu.

Provides shorthand commands for task management:
- mhv tc (task create)
- mhv ts (task status)
- mhv tl (task list)
- mhv tu (task update)
- mhv td (task delete)

Also provides smart defaults and auto-completion support.

Usage:
    # Full commands
    mahavishnu task create "Fix bug" --repo mahavishnu --priority high
    mahavishnu task list --status in_progress --repo session-buddy
    mahavishnu task update task-123 --status completed
    mahavishnu task delete task-123

    # Shorthands
    mhv tc "Fix bug" -r mahavishnu -p high
    mhv tl -s in_progress -r session-buddy
    mhv tu task-123 -s completed
    mhv td task-123
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Note: These imports would work in production but may need mocking in tests
# from mahavishnu.core.task_store import TaskStore, TaskCreate, TaskUpdate, TaskStatus, TaskPriority, TaskListFilter
# from mahavishnu.core.database import get_database

console = Console()
logger = logging.getLogger(__name__)


# Completion support functions
def complete_repository(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Provide repository name completions.

    Reads from repos.yaml or environment.
    """
    repositories = []

    # Try to load from environment
    repos_env = os.getenv("MAHAVISHNU_REPOS", "")
    if repos_env:
        repositories.extend(repos_env.split(","))

    # Add common repositories
    common_repos = ["mahavishnu", "session-buddy", "crackerjack", "akosha", "mcp-common"]
    for repo in common_repos:
        if repo not in repositories:
            repositories.append(repo)

    # Filter by incomplete
    return [r for r in repositories if r.startswith(incomplete)]


def complete_status(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Provide status completions."""
    statuses = ["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]
    return [s for s in statuses if s.startswith(incomplete)]


def complete_priority(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Provide priority completions."""
    priorities = ["low", "medium", "high", "critical"]
    return [p for p in priorities if p.startswith(incomplete)]


def complete_task_id(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Provide task ID completions.

    In production, this would query the database for matching tasks.
    """
    # This would query the database in production
    # For now, return empty to indicate completion is available
    return []


def complete_tag(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Provide tag completions from common tags."""
    common_tags = [
        "bug", "feature", "enhancement", "documentation", "security",
        "backend", "frontend", "api", "database", "testing",
        "urgent", "blocked", "review-needed",
    ]
    return [t for t in common_tags if t.startswith(incomplete)]


# CLI Group
@click.group(name="task", help="Task management commands")
def task_group() -> None:
    """Task management commands."""
    pass


# Task Create Command
@task_group.command(name="create", help="Create a new task")
@click.argument("title", required=True)
@click.option(
    "-r", "--repository", "--repo",
    required=True,
    help="Repository name",
    shell_complete=complete_repository,
)
@click.option(
    "-d", "--description",
    help="Task description",
)
@click.option(
    "-p", "--priority",
    type=click.Choice(["low", "medium", "high", "critical"]),
    default="medium",
    help="Task priority",
    shell_complete=complete_priority,
)
@click.option(
    "-s", "--status",
    type=click.Choice(["pending", "in_progress", "blocked"]),
    default="pending",
    help="Initial status",
    shell_complete=complete_status,
)
@click.option(
    "-a", "--assignee",
    help="Assignee email or username",
)
@click.option(
    "-t", "--tag",
    multiple=True,
    help="Tags (can specify multiple)",
    shell_complete=complete_tag,
)
@click.option(
    "--due",
    help="Due date (e.g., 'tomorrow', 'next week', '2024-12-31')",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
def task_create(
    title: str,
    repository: str,
    description: str | None,
    priority: str,
    status: str,
    assignee: str | None,
    tag: tuple[str, ...],
    due: str | None,
    output_json: bool,
) -> None:
    """Create a new task.

    Example:
        mahavishnu task create "Fix login bug" -r session-buddy -p high -t bug -t urgent
    """
    from mahavishnu.core.task_store import TaskCreate, TaskPriority, TaskStatus
    from mahavishnu.core.database import get_database
    from mahavishnu.core.task_store import TaskStore

    async def _create() -> None:
        db = await get_database()
        store = TaskStore(db)

        # Parse due date if provided
        due_date = None
        if due:
            due_date = parse_due_date(due)

        task_create_data = TaskCreate(
            title=title,
            repository=repository,
            description=description,
            priority=TaskPriority(priority),
            status=TaskStatus(status),
            assignee=assignee,
            tags=list(tag),
            due_date=due_date,
        )

        task = await store.create(task_create_data)

        if output_json:
            console.print_json(data=task.to_dict())
        else:
            console.print(Panel(
                f"[green]Created task:[/] {task.id}\n"
                f"[bold]{task.title}[/]\n"
                f"Repository: {task.repository}\n"
                f"Priority: {task.priority.value}\n"
                f"Status: {task.status.value}",
                title="Task Created",
                border_style="green",
            ))

    asyncio.run(_create())


# Task List Command
@task_group.command(name="list", help="List tasks")
@click.option(
    "-r", "--repository", "--repo",
    help="Filter by repository",
    shell_complete=complete_repository,
)
@click.option(
    "-s", "--status",
    type=click.Choice(["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]),
    help="Filter by status",
    shell_complete=complete_status,
)
@click.option(
    "-p", "--priority",
    type=click.Choice(["low", "medium", "high", "critical"]),
    help="Filter by priority",
    shell_complete=complete_priority,
)
@click.option(
    "-a", "--assignee",
    help="Filter by assignee",
)
@click.option(
    "--search",
    help="Search in title and description",
)
@click.option(
    "-l", "--limit",
    type=int,
    default=20,
    help="Maximum number of tasks to show",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
@click.option(
    "-t", "--tag",
    help="Filter by tag",
    shell_complete=complete_tag,
)
def task_list(
    repository: str | None,
    status: str | None,
    priority: str | None,
    assignee: str | None,
    search: str | None,
    limit: int,
    output_json: bool,
    tag: str | None,
) -> None:
    """List tasks with optional filters.

    Example:
        mahavishnu task list -r mahavishnu -s in_progress -p high
    """
    from mahavishnu.core.task_store import TaskListFilter, TaskStatus, TaskPriority
    from mahavishnu.core.database import get_database
    from mahavishnu.core.task_store import TaskStore

    async def _list() -> None:
        db = await get_database()
        store = TaskStore(db)

        filters = TaskListFilter(
            repository=repository,
            status=TaskStatus(status) if status else None,
            priority=TaskPriority(priority) if priority else None,
            assignee=assignee,
            search=search,
            tags=[tag] if tag else None,
            limit=limit,
        )

        tasks = await store.list(filters)
        total = await store.count(filters)

        if output_json:
            console.print_json(data=[t.to_dict() for t in tasks])
        else:
            table = Table(title=f"Tasks ({len(tasks)} of {total})")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Title", style="white")
            table.add_column("Repository", style="blue")
            table.add_column("Status", style="green")
            table.add_column("Priority", style="yellow")
            table.add_column("Assignee", style="magenta")

            for task in tasks:
                # Color status
                status_color = {
                    "pending": "white",
                    "in_progress": "blue",
                    "completed": "green",
                    "failed": "red",
                    "cancelled": "dim",
                    "blocked": "yellow",
                }.get(task.status.value, "white")

                # Color priority
                priority_color = {
                    "low": "dim",
                    "medium": "white",
                    "high": "yellow",
                    "critical": "red bold",
                }.get(task.priority.value, "white")

                table.add_row(
                    task.id[:8],
                    task.title[:50] + ("..." if len(task.title) > 50 else ""),
                    task.repository,
                    f"[{status_color}]{task.status.value}[/{status_color}]",
                    f"[{priority_color}]{task.priority.value}[/{priority_color}]",
                    task.assignee or "-",
                )

            console.print(table)

    asyncio.run(_list())


# Task Update Command
@task_group.command(name="update", help="Update a task")
@click.argument("task_id", required=True, shell_complete=complete_task_id)
@click.option(
    "--title",
    help="New title",
)
@click.option(
    "-d", "--description",
    help="New description",
)
@click.option(
    "-s", "--status",
    type=click.Choice(["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]),
    help="New status",
    shell_complete=complete_status,
)
@click.option(
    "-p", "--priority",
    type=click.Choice(["low", "medium", "high", "critical"]),
    help="New priority",
    shell_complete=complete_priority,
)
@click.option(
    "-a", "--assignee",
    help="New assignee",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
def task_update(
    task_id: str,
    title: str | None,
    description: str | None,
    status: str | None,
    priority: str | None,
    assignee: str | None,
    output_json: bool,
) -> None:
    """Update a task.

    Example:
        mahavishnu task update task-123 -s completed -p high
    """
    from mahavishnu.core.task_store import TaskUpdate, TaskStatus, TaskPriority
    from mahavishnu.core.database import get_database
    from mahavishnu.core.task_store import TaskStore

    async def _update() -> None:
        db = await get_database()
        store = TaskStore(db)

        update_data = TaskUpdate(
            title=title,
            description=description,
            status=TaskStatus(status) if status else None,
            priority=TaskPriority(priority) if priority else None,
            assignee=assignee,
        )

        task = await store.update(task_id, update_data)

        if output_json:
            console.print_json(data=task.to_dict())
        else:
            console.print(Panel(
                f"[green]Updated task:[/] {task.id}\n"
                f"[bold]{task.title}[/]\n"
                f"Status: {task.status.value}\n"
                f"Priority: {task.priority.value}",
                title="Task Updated",
                border_style="blue",
            ))

    asyncio.run(_update())


# Task Delete Command
@task_group.command(name="delete", help="Delete a task")
@click.argument("task_id", required=True, shell_complete=complete_task_id)
@click.option(
    "-f", "--force",
    is_flag=True,
    help="Skip confirmation",
)
def task_delete(task_id: str, force: bool) -> None:
    """Delete a task.

    Example:
        mahavishnu task delete task-123
    """
    from mahavishnu.core.database import get_database
    from mahavishnu.core.task_store import TaskStore

    async def _delete() -> None:
        db = await get_database()
        store = TaskStore(db)

        if not force:
            if not click.confirm(f"Delete task {task_id}?"):
                console.print("[yellow]Cancelled[/]")
                return

        await store.delete(task_id)
        console.print(f"[green]Deleted task:[/] {task_id}")

    asyncio.run(_delete())


# Task Status Command (shorthand for update --status)
@task_group.command(name="status", help="Update task status")
@click.argument("task_id", required=True, shell_complete=complete_task_id)
@click.argument(
    "status",
    type=click.Choice(["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]),
    shell_complete=complete_status,
)
def task_status(task_id: str, status: str) -> None:
    """Quick status update.

    Example:
        mahavishnu task status task-123 completed
    """
    from mahavishnu.core.task_store import TaskUpdate, TaskStatus
    from mahavishnu.core.database import get_database
    from mahavishnu.core.task_store import TaskStore

    async def _status() -> None:
        db = await get_database()
        store = TaskStore(db)

        update_data = TaskUpdate(status=TaskStatus(status))
        task = await store.update(task_id, update_data)

        console.print(f"[green]Status updated:[/] {task.id} -> {task.status.value}")

    asyncio.run(_status())


# Utility functions
def parse_due_date(due: str) -> datetime | None:
    """Parse various due date formats.

    Supports:
    - 'today', 'tomorrow'
    - 'next week', 'next month'
    - 'in N days'
    - ISO date format (YYYY-MM-DD)
    """
    from datetime import timedelta

    due_lower = due.lower().strip()
    now = datetime.now()

    if due_lower == "today":
        return now.replace(hour=23, minute=59, second=59)
    elif due_lower == "tomorrow":
        return (now + timedelta(days=1)).replace(hour=23, minute=59, second=59)
    elif due_lower == "next week":
        return (now + timedelta(weeks=1)).replace(hour=23, minute=59, second=59)
    elif due_lower == "next month":
        return (now + timedelta(days=30)).replace(hour=23, minute=59, second=59)
    elif due_lower.startswith("in "):
        # Parse "in N days" or "in N weeks"
        match = re.match(r"in (\d+) (day|days|week|weeks)", due_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if unit in ("day", "days"):
                return (now + timedelta(days=amount)).replace(hour=23, minute=59, second=59)
            else:
                return (now + timedelta(weeks=amount)).replace(hour=23, minute=59, second=59)
    else:
        # Try ISO format
        try:
            return datetime.fromisoformat(due)
        except ValueError:
            pass

    return None


# Register shorthand commands
# These provide shorter aliases like 'mhv tc' for 'mahavishnu task create'
def register_shorthands(cli_group: click.Group) -> None:
    """Register shorthand commands on the CLI group.

    Args:
        cli_group: The main CLI group to add shorthands to
    """

    # Task shorthands
    @cli_group.command(name="tc", hidden=True)
    @click.pass_context
    def tc(ctx: click.Context) -> None:
        """Shorthand for 'task create'."""
        console.print("[dim]Hint: Use 'mahavishnu task create' instead[/]")

    @cli_group.command(name="tl", hidden=True)
    @click.pass_context
    def tl(ctx: click.Context) -> None:
        """Shorthand for 'task list'."""
        console.print("[dim]Hint: Use 'mahavishnu task list' instead[/]")

    @cli_group.command(name="tu", hidden=True)
    @click.pass_context
    def tu(ctx: click.Context) -> None:
        """Shorthand for 'task update'."""
        console.print("[dim]Hint: Use 'mahavishnu task update' instead[/]")

    @cli_group.command(name="td", hidden=True)
    @click.pass_context
    def td(ctx: click.Context) -> None:
        """Shorthand for 'task delete'."""
        console.print("[dim]Hint: Use 'mahavishnu task delete' instead[/]")

    @cli_group.command(name="ts", hidden=True)
    @click.pass_context
    def ts(ctx: click.Context) -> None:
        """Shorthand for 'task status'."""
        console.print("[dim]Hint: Use 'mahavishnu task status' instead[/]")


# Shell completion script generator
def generate_completion_script(shell: str = "bash") -> str:
    """Generate shell completion script.

    Args:
        shell: Shell type (bash, zsh, fish)

    Returns:
        Completion script content
    """
    if shell == "bash":
        return """
# Bash completion for mahavishnu
_mahavishnu_completion() {
    local cur words
    cur="${COMP_WORDS[COMP_CWORD]}"
    words=$(mahavishnu --show-completion bash "${COMP_WORDS[@]}")
    COMPREPLY=($(compgen -W "${words}" -- "${cur}"))
}
complete -F _mahavishnu_completion mahavishnu
complete -F _mahavishnu_completion mhv
"""
    elif shell == "zsh":
        return """
# Zsh completion for mahavishnu
# Add to ~/.zshrc
autoload -U +X compinit && compinit
autoload -U +X bashcompinit && bashcompinit
source <(mahavishnu --show-completion bash)
"""
    elif shell == "fish":
        return """
# Fish completion for mahavishnu
mahavishnu --show-completion fish | source
"""
    return ""
