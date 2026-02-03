"""
Cross-repository coordination CLI commands.

This module provides CLI commands for managing cross-repository issues,
plans, todos, and dependencies.
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table
import typer

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoTodo,
    IssueStatus,
    Priority,
    TodoStatus,
)

console = Console()
coord_app = typer.Typer(help="Cross-repository coordination and tracking")


def add_coordination_commands(app: typer.Typer) -> None:
    """Add coordination commands to the main CLI app."""
    app.add_typer(coord_app, name="coord")


# ============================================================================
# Issue Management Commands
# ============================================================================


@coord_app.command("list-issues")
def list_issues(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    priority: str | None = typer.Option(None, "--priority", "-p", help="Filter by priority"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Filter by repository"),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="Filter by assignee"),
):
    """List cross-repository issues with optional filtering."""
    mgr = CoordinationManager()

    # Convert status string to enum if provided
    status_enum = None
    if status:
        try:
            status_enum = IssueStatus(status)
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            console.print(f"Valid values: {[s.value for s in IssueStatus]}")
            raise typer.Exit(code=1)

    issues = mgr.list_issues(status=status_enum, priority=priority, repo=repo, assignee=assignee)

    if not issues:
        console.print("No issues found matching the criteria.")
        return

    table = Table(title="Cross-Repository Issues")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Status", style="green")
    table.add_column("Priority", style="yellow")
    table.add_column("Repos")
    table.add_column("Assignee")

    for issue in issues:
        repos_str = ", ".join(issue.repos[:3])
        if len(issue.repos) > 3:
            repos_str += f" (+{len(issue.repos) - 3})"

        table.add_row(
            issue.id,
            issue.title,
            issue.status.value,
            issue.priority.value,
            repos_str,
            issue.assignee or "Unassigned",
        )

    console.print(table)


@coord_app.command("show-issue")
def show_issue(
    issue_id: str = typer.Argument(..., help="Issue identifier (e.g., ISSUE-001)"),
):
    """Show detailed information about a specific issue."""
    mgr = CoordinationManager()
    issue = mgr.get_issue(issue_id)

    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan bold]Issue:[/cyan bold] {issue.id}")
    console.print(f"[bold]Title:[/bold] {issue.title}")
    console.print(f"[bold]Status:[/bold] {issue.status.value}")
    console.print(f"[bold]Priority:[/bold] {issue.priority.value}")
    console.print(f"[bold]Severity:[/bold] {issue.severity}")
    console.print(f"[bold]Repositories:[/bold] {', '.join(issue.repos)}")
    console.print(f"[bold]Assignee:[/bold] {issue.assignee or 'Unassigned'}")
    console.print(f"[bold]Created:[/bold] {issue.created}")
    console.print(f"[bold]Updated:[/bold] {issue.updated}")
    if issue.target:
        console.print(f"[bold]Target:[/bold] {issue.target}")

    console.print(f"\n[bold]Description:[/bold]\n{issue.description}")

    if issue.dependencies:
        console.print(f"\n[bold]Dependencies:[/bold] {', '.join(issue.dependencies)}")
    if issue.blocking:
        console.print(f"[bold]Blocking:[/bold] {', '.join(issue.blocking)}")
    if issue.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(issue.labels)}")
    if issue.metadata:
        console.print("\n[bold]Metadata:[/bold]")
        for key, value in issue.metadata.items():
            console.print(f"  {key}: {value}")


@coord_app.command("create-issue")
def create_issue(
    title: str = typer.Option(..., "--title", "-t", help="Issue title"),
    description: str = typer.Option(..., "--description", "-d", help="Issue description"),
    repos: str = typer.Option(..., "--repos", "-r", help="Comma-separated list of repositories"),
    priority: str = typer.Option("medium", "--priority", "-p", help="Issue priority"),
    severity: str = typer.Option("normal", "--severity", help="Severity level"),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="Assignee"),
    target: str | None = typer.Option(None, "--target", help="Target completion date (ISO 8601)"),
):
    """Create a new cross-repository issue."""
    mgr = CoordinationManager()

    # Generate issue ID
    existing_issues = mgr.list_issues()
    next_num = len(existing_issues) + 1
    issue_id = f"ISSUE-{next_num:03d}"

    # Parse repos
    repo_list = [r.strip() for r in repos.split(",")]

    # Validate priority
    try:
        priority_enum = Priority(priority)
    except ValueError:
        console.print(f"[red]Invalid priority: {priority}[/red]")
        raise typer.Exit(code=1)

    # Create issue
    now = datetime.now().isoformat()
    issue = CrossRepoIssue(
        id=issue_id,
        title=title,
        description=description,
        status=IssueStatus.PENDING,
        priority=priority_enum,
        severity=severity,
        repos=repo_list,
        created=now,
        updated=now,
        target=target,
        dependencies=[],
        blocking=[],
        assignee=assignee,
        labels=[],
        metadata={},
    )

    mgr.create_issue(issue)
    mgr.save()

    console.print(f"[green]Created issue {issue_id}[/green]")
    console.print(f"Title: {title}")
    console.print(f"Repositories: {', '.join(repo_list)}")


@coord_app.command("update-issue")
def update_issue(
    issue_id: str = typer.Argument(..., help="Issue identifier"),
    status: str | None = typer.Option(None, "--status", "-s", help="New status"),
    priority: str | None = typer.Option(None, "--priority", "-p", help="New priority"),
):
    """Update an existing issue."""
    mgr = CoordinationManager()

    updates = {}
    if status:
        try:
            IssueStatus(status)  # Validate
            updates["status"] = status
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            raise typer.Exit(code=1)

    if priority:
        try:
            Priority(priority)  # Validate
            updates["priority"] = priority
        except ValueError:
            console.print(f"[red]Invalid priority: {priority}[/red]")
            raise typer.Exit(code=1)

    if not updates:
        console.print("[yellow]No updates specified[/yellow]")
        return

    mgr.update_issue(issue_id, updates)
    mgr.save()

    console.print(f"[green]Updated issue {issue_id}[/green]")


@coord_app.command("close-issue")
def close_issue(
    issue_id: str = typer.Argument(..., help="Issue identifier"),
):
    """Close an issue."""
    mgr = CoordinationManager()
    mgr.update_issue(issue_id, {"status": "closed"})
    mgr.save()
    console.print(f"[green]Closed issue {issue_id}[/green]")


# ============================================================================
# Todo Management Commands
# ============================================================================


@coord_app.command("list-todos")
def list_todos(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Filter by repository"),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="Filter by assignee"),
):
    """List todo items with optional filtering."""
    mgr = CoordinationManager()

    # Convert status string to enum if provided
    status_enum = None
    if status:
        try:
            status_enum = TodoStatus(status)
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            raise typer.Exit(code=1)

    todos = mgr.list_todos(status=status_enum, repo=repo, assignee=assignee)

    if not todos:
        console.print("No todos found matching the criteria.")
        return

    table = Table(title="Cross-Repository Todos")
    table.add_column("ID", style="cyan")
    table.add_column("Task")
    table.add_column("Repo", style="blue")
    table.add_column("Status", style="green")
    table.add_column("Priority", style="yellow")
    table.add_column("Est. Hours")
    table.add_column("Assignee")

    for todo in todos:
        table.add_row(
            todo.id,
            todo.task,
            todo.repo,
            todo.status.value,
            todo.priority.value,
            str(todo.estimated_hours),
            todo.assignee or "Unassigned",
        )

    console.print(table)


@coord_app.command("show-todo")
def show_todo(
    todo_id: str = typer.Argument(..., help="Todo identifier (e.g., TODO-001)"),
):
    """Show detailed information about a specific todo."""
    mgr = CoordinationManager()
    todo = mgr.get_todo(todo_id)

    if not todo:
        console.print(f"[red]Todo {todo_id} not found[/red]")
        raise typer.Exit(code=1)

    console.print(f"[cyan bold]Todo:[/cyan bold] {todo.id}")
    console.print(f"[bold]Task:[/bold] {todo.task}")
    console.print(f"[bold]Status:[/bold] {todo.status.value}")
    console.print(f"[bold]Priority:[/bold] {todo.priority.value}")
    console.print(f"[bold]Repository:[/bold] {todo.repo}")
    console.print(f"[bold]Assignee:[/bold] {todo.assignee or 'Unassigned'}")
    console.print(f"[bold]Estimated:[/bold] {todo.estimated_hours}h")
    if todo.actual_hours:
        console.print(f"[bold]Actual:[/bold] {todo.actual_hours}h")
    console.print(f"[bold]Created:[/bold] {todo.created}")
    console.print(f"[bold]Updated:[/bold] {todo.updated}")

    console.print(f"\n[bold]Description:[/bold]\n{todo.description}")

    if todo.blocked_by:
        console.print(f"\n[bold]Blocked by:[/bold] {', '.join(todo.blocked_by)}")
    if todo.blocking:
        console.print(f"[bold]Blocking:[/bold] {', '.join(todo.blocking)}")
    if todo.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(todo.labels)}")
    if todo.acceptance_criteria:
        console.print("\n[bold]Acceptance Criteria:[/bold]")
        for i, criterion in enumerate(todo.acceptance_criteria, 1):
            console.print(f"  {i}. {criterion}")


@coord_app.command("create-todo")
def create_todo(
    task: str = typer.Option(..., "--task", "-t", help="Task description"),
    description: str = typer.Option(..., "--description", "-d", help="Detailed description"),
    repo: str = typer.Option(..., "--repo", "-r", help="Repository nickname"),
    estimate: float = typer.Option(..., "--estimate", "-e", help="Estimated hours"),
    priority: str = typer.Option("medium", "--priority", "-p", help="Task priority"),
    assignee: str | None = typer.Option(None, "--assignee", "-a", help="Assignee"),
):
    """Create a new todo item."""
    mgr = CoordinationManager()

    # Generate todo ID
    existing_todos = mgr.list_todos()
    next_num = len(existing_todos) + 1
    todo_id = f"TODO-{next_num:03d}"

    # Validate priority
    try:
        priority_enum = Priority(priority)
    except ValueError:
        console.print(f"[red]Invalid priority: {priority}[/red]")
        raise typer.Exit(code=1)

    # Create todo
    now = datetime.now().isoformat()
    todo = CrossRepoTodo(
        id=todo_id,
        task=task,
        description=description,
        repo=repo,
        status=TodoStatus.PENDING,
        priority=priority_enum,
        created=now,
        updated=now,
        estimated_hours=estimate,
        actual_hours=None,
        blocked_by=[],
        blocking=[],
        assignee=assignee,
        labels=[],
        acceptance_criteria=[],
    )

    # Add to coordination data
    todos_data = mgr._coordination.get("todos", [])
    todos_data.append(todo.model_dump(mode="json"))
    mgr._coordination["todos"] = todos_data
    mgr.save()

    console.print(f"[green]Created todo {todo_id}[/green]")
    console.print(f"Task: {task}")
    console.print(f"Repository: {repo}")
    console.print(f"Estimated: {estimate}h")


@coord_app.command("complete-todo")
def complete_todo(
    todo_id: str = typer.Argument(..., help="Todo identifier"),
):
    """Mark a todo as completed."""
    mgr = CoordinationManager()

    todos_data = mgr._coordination.get("todos", [])
    for todo in todos_data:
        if todo.get("id") == todo_id:
            todo["status"] = "completed"
            todo["updated"] = datetime.now().isoformat()
            mgr._coordination["todos"] = todos_data
            mgr.save()
            console.print(f"[green]Completed todo {todo_id}[/green]")
            return

    console.print(f"[red]Todo {todo_id} not found[/red]")
    raise typer.Exit(code=1)


# ============================================================================
# Plan Management Commands
# ============================================================================


@coord_app.command("list-plans")
def list_plans(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    repo: str | None = typer.Option(None, "--repo", "-r", help="Filter by repository"),
):
    """List cross-repository plans with optional filtering."""
    mgr = CoordinationManager()
    plans = mgr.list_plans(status=status, repo=repo)

    if not plans:
        console.print("No plans found matching the criteria.")
        return

    table = Table(title="Cross-Repository Plans")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Status", style="green")
    table.add_column("Repos")
    table.add_column("Milestones")
    table.add_column("Target")

    for plan in plans:
        repos_str = ", ".join(plan.repos[:3])
        if len(plan.repos) > 3:
            repos_str += f" (+{len(plan.repos) - 3})"

        table.add_row(
            plan.id,
            plan.title,
            plan.status.value,
            repos_str,
            str(len(plan.milestones)),
            plan.target[:10],  # Show just the date
        )

    console.print(table)


# ============================================================================
# Dependency Management Commands
# ============================================================================


@coord_app.command("list-deps")
def list_deps(
    consumer: str | None = typer.Option(None, "--consumer", "-c", help="Filter by consumer"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="Filter by provider"),
):
    """List inter-repository dependencies."""
    mgr = CoordinationManager()
    deps = mgr.list_dependencies(consumer=consumer, provider=provider)

    if not deps:
        console.print("No dependencies found matching the criteria.")
        return

    table = Table(title="Inter-Repository Dependencies")
    table.add_column("ID", style="cyan")
    table.add_column("Consumer")
    table.add_column("Provider")
    table.add_column("Type")
    table.add_column("Version")
    table.add_column("Status", style="green")

    for dep in deps:
        status_color = "green" if dep.status.value == "satisfied" else "red"
        table.add_row(
            dep.id,
            dep.consumer,
            dep.provider,
            dep.type.value,
            dep.version_constraint,
            f"[{status_color}]{dep.status.value}[/{status_color}]",
        )

    console.print(table)


@coord_app.command("check-deps")
def check_deps(
    consumer: str | None = typer.Option(None, "--consumer", "-c", help="Filter by consumer"),
):
    """Validate inter-repository dependencies."""
    mgr = CoordinationManager()
    results = mgr.check_dependencies(consumer=consumer)

    console.print("\n[bold]Dependency Check Results[/bold]")
    console.print(f"Total: {results['total']}")
    console.print(f"[green]Satisfied: {results['satisfied']}[/green]")
    console.print(f"[red]Unsatisfied: {results['unsatisfied']}[/red]")
    console.print(f"[yellow]Unknown: {results['unknown']}[/yellow]")
    if results.get("deprecated"):
        console.print(f"[dim]Deprecated: {results['deprecated']}[/dim]")

    if results["dependencies"]:
        console.print("\n[bold]Details:[/bold]")
        for dep in results["dependencies"]:
            status_color = "green" if dep["status"] == "satisfied" else "red"
            console.print(
                f"  [{status_color}]● {dep['consumer']} → {dep['provider']}"
                f" ({dep['type']}): {dep['version_constraint']}[/{status_color}]"
            )
            if dep.get("validation"):
                val = dep["validation"]
                val_color = "green" if val["passed"] else "red"
                console.print(f"    Validation: [{val_color}]{val['passed']}[/{val_color}]")
                if val.get("details"):
                    console.print(f"    {val['details']}")


# ============================================================================
# Status and Reporting Commands
# ============================================================================


@coord_app.command("status")
def repo_status(
    repo: str = typer.Argument(..., help="Repository nickname"),
):
    """Show comprehensive coordination status for a repository."""
    mgr = CoordinationManager()
    status = mgr.get_repo_status(repo)

    console.print(f"\n[bold cyan]Coordination Status: {repo}[/bold cyan]\n")

    # Issues
    console.print(f"[bold]Issues Affecting This Repo:[/bold] {len(status['issues'])}")
    for issue in status["issues"]:
        console.print(f"  [{issue.priority.value}] {issue.id}: {issue.title}")

    # Todos
    console.print(f"\n[bold]Todos for This Repo:[/bold] {len(status['todos'])}")
    for todo in status["todos"]:
        console.print(f"  [{todo.status.value}] {todo.id}: {todo.task}")

    # Dependencies
    console.print(f"\n[bold]Outgoing Dependencies:[/bold] {len(status['dependencies_outgoing'])}")
    for dep in status["dependencies_outgoing"]:
        console.print(
            f"  {dep.consumer} → {dep.provider}: {dep.version_constraint} [{dep.status.value}]"
        )

    console.print(f"\n[bold]Incoming Dependencies:[/bold] {len(status['dependencies_incoming'])}")
    for dep in status["dependencies_incoming"]:
        console.print(
            f"  {dep.consumer} → {dep.provider}: {dep.version_constraint} [{dep.status.value}]"
        )

    # Blocking info
    if status["blocking"]:
        console.print("\n[bold yellow]Blocking:[/bold yellow]")
        for todo in status["blocking"]:
            console.print(f"  {todo.id}: {todo.task}")

    if status["blocked_by"]:
        console.print("\n[bold red]Blocked By:[/bold red]")
        for dep in status["blocked_by"]:
            console.print(f"  {dep.id}: {dep.consumer} requires {dep.provider}")


@coord_app.command("blocking")
def blocking(
    repo: str = typer.Argument(..., help="Repository nickname"),
):
    """Show what is blocking a repository."""
    mgr = CoordinationManager()
    status = mgr.get_repo_status(repo)

    console.print(f"\n[bold]What is blocking {repo}:[/bold]\n")

    issues = status["issues"]
    deps = status["blocked_by"]

    if not issues and not deps:
        console.print(f"[green]{repo} is not blocked by anything[/green]")
        return

    if issues:
        console.print("[bold]Open Issues:[/bold]")
        for issue in issues:
            console.print(f"  [{issue.priority.value}] {issue.id}: {issue.title}")

    if deps:
        console.print("\n[bold]Unsatisfied Dependencies:[/bold]")
        for dep in deps:
            console.print(f"  {dep.id}: requires {dep.provider} {dep.version_constraint}")
