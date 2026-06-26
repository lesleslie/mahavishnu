"""
MCP tools for cross-repository coordination.

Exposes coordination functionality via FastMCP for AI agent access.
"""

from datetime import datetime
from typing import Any

from mcp_common.fastmcp import FastMCP

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoTodo,
    IssueStatus,
    Priority,
    TodoStatus,
)

mcp = FastMCP("Mahavishnu Coordination")


def _get_manager() -> CoordinationManager:
    """Get a coordination manager instance."""
    return CoordinationManager()


@mcp.tool()
async def coord_list_issues(
    status: str | None = None,
    priority: str | None = None,
    repo: str | None = None,
    assignee: str | None = None,
) -> list[dict[str, Any]]:
    """List cross-repository issues with optional filtering."""
    mgr = _get_manager()

    # Convert status string to enum if provided
    status_enum = None
    if status:
        try:
            status_enum = IssueStatus(status)
        except ValueError:
            raise ValueError(
                f"Invalid status: {status}. Valid values: {[s.value for s in IssueStatus]}"
            )

    issues = mgr.list_issues(status=status_enum, priority=priority, repo=repo, assignee=assignee)
    return [issue.model_dump(mode="json") for issue in issues]


@mcp.tool()
async def coord_get_issue(issue_id: str) -> dict[str, Any]:
    """Get detailed information about a specific issue."""
    mgr = _get_manager()
    issue = mgr.get_issue(issue_id)

    if not issue:
        raise ValueError(f"Issue {issue_id} not found")

    return issue.model_dump(mode="json")


@mcp.tool()
async def coord_create_issue(
    title: str,
    description: str,
    repos: list[str],
    priority: str = "medium",
    severity: str = "normal",
    assignee: str | None = None,
    target: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new cross-repository issue."""
    mgr = _get_manager()

    # Generate issue ID
    existing_issues = mgr.list_issues()
    next_num = len(existing_issues) + 1
    issue_id = f"ISSUE-{next_num:03d}"

    # Validate priority
    try:
        priority_enum = Priority(priority)
    except ValueError:
        raise ValueError(
            f"Invalid priority: {priority}. Valid values: {[p.value for p in Priority]}"
        )

    # Create issue
    now = datetime.now().isoformat()
    issue = CrossRepoIssue(
        id=issue_id,
        title=title,
        description=description,
        status=IssueStatus.PENDING,
        priority=priority_enum,
        severity=severity,
        repos=repos,
        created=now,
        updated=now,
        target=target,
        dependencies=[],
        blocking=[],
        assignee=assignee,
        labels=labels or [],
        metadata={},
    )

    mgr.create_issue(issue)
    mgr.save()

    return issue.model_dump(mode="json")


@mcp.tool()
async def coord_update_issue(
    issue_id: str,
    status: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    """Update an existing issue."""
    mgr = _get_manager()

    updates = {}
    if status:
        try:
            IssueStatus(status)  # Validate
            updates["status"] = status
        except ValueError:
            raise ValueError(f"Invalid status: {status}")

    if priority:
        try:
            Priority(priority)  # Validate
            updates["priority"] = priority
        except ValueError:
            raise ValueError(f"Invalid priority: {priority}")

    if not updates:
        raise ValueError("No updates specified")

    mgr.update_issue(issue_id, updates)
    mgr.save()

    issue = mgr.get_issue(issue_id)
    return issue.model_dump(mode="json")  # type: ignore[union-attr]


@mcp.tool()
async def coord_close_issue(issue_id: str) -> dict[str, Any]:
    """Close an issue."""
    mgr = _get_manager()
    mgr.update_issue(issue_id, {"status": "closed"})
    mgr.save()

    issue = mgr.get_issue(issue_id)
    return issue.model_dump(mode="json")  # type: ignore[union-attr]


@mcp.tool()
async def coord_list_todos(
    status: str | None = None,
    repo: str | None = None,
    assignee: str | None = None,
) -> list[dict[str, Any]]:
    """List todo items with optional filtering."""
    mgr = _get_manager()

    # Convert status string to enum if provided
    status_enum = None
    if status:
        try:
            status_enum = TodoStatus(status)
        except ValueError:
            raise ValueError(
                f"Invalid status: {status}. Valid values: {[s.value for s in TodoStatus]}"
            )

    todos = mgr.list_todos(status=status_enum, repo=repo, assignee=assignee)
    return [todo.model_dump(mode="json") for todo in todos]


@mcp.tool()
async def coord_get_todo(todo_id: str) -> dict[str, Any]:
    """Get detailed information about a specific todo."""
    mgr = _get_manager()
    todo = mgr.get_todo(todo_id)

    if not todo:
        raise ValueError(f"Todo {todo_id} not found")

    return todo.model_dump(mode="json")


@mcp.tool()
async def coord_create_todo(
    task: str,
    description: str,
    repo: str,
    estimate_hours: float,
    priority: str = "medium",
    assignee: str | None = None,
    blocked_by: list[str] | None = None,
    labels: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new todo item."""
    mgr = _get_manager()

    # Generate todo ID
    existing_todos = mgr.list_todos()
    next_num = len(existing_todos) + 1
    todo_id = f"TODO-{next_num:03d}"

    # Validate priority
    try:
        priority_enum = Priority(priority)
    except ValueError:
        raise ValueError(f"Invalid priority: {priority}")

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
        estimated_hours=estimate_hours,
        actual_hours=None,
        blocked_by=blocked_by or [],
        blocking=[],
        assignee=assignee,
        labels=labels or [],
        acceptance_criteria=acceptance_criteria or [],
    )

    # Add to coordination data
    todos_data = mgr._coordination.get("todos", [])
    todos_data.append(todo.model_dump(mode="json"))
    mgr._coordination["todos"] = todos_data
    mgr.save()

    return todo.model_dump(mode="json")


@mcp.tool()
async def coord_complete_todo(todo_id: str) -> dict[str, Any]:
    """Mark a todo as completed."""
    mgr = _get_manager()

    todos_data = mgr._coordination.get("todos", [])
    for todo in todos_data:
        if todo.get("id") == todo_id:
            todo["status"] = "completed"
            todo["updated"] = datetime.now().isoformat()
            mgr._coordination["todos"] = todos_data
            mgr.save()

            return todo  # type: ignore[no-any-return]

    raise ValueError(f"Todo {todo_id} not found")


@mcp.tool()
async def coord_get_blocking_issues(repo: str) -> list[dict[str, Any]]:
    """Get all issues blocking a specific repository."""
    mgr = _get_manager()
    blocking_issues = mgr.get_blocking_issues(repo)
    return [issue.model_dump(mode="json") for issue in blocking_issues]


@mcp.tool()
async def coord_check_dependencies(
    consumer: str | None = None,
) -> dict[str, Any]:
    """Validate inter-repository dependencies."""
    mgr = _get_manager()
    results = mgr.check_dependencies(consumer=consumer)
    return results


@mcp.tool()
async def coord_get_repo_status(repo: str) -> dict[str, Any]:
    """Get comprehensive coordination status for a repository."""
    mgr = _get_manager()
    status = mgr.get_repo_status(repo)

    # Convert models to dicts for JSON serialization
    return {
        "issues": [issue.model_dump(mode="json") for issue in status["issues"]],
        "todos": [todo.model_dump(mode="json") for todo in status["todos"]],
        "dependencies_outgoing": [
            dep.model_dump(mode="json") for dep in status["dependencies_outgoing"]
        ],
        "dependencies_incoming": [
            dep.model_dump(mode="json") for dep in status["dependencies_incoming"]
        ],
        "blocking": [todo.model_dump(mode="json") for todo in status["blocking"]],
        "blocked_by": [dep.model_dump(mode="json") for dep in status["blocked_by"]],
    }


@mcp.tool()
async def coord_list_plans(
    status: str | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """List cross-repository plans with optional filtering."""
    mgr = _get_manager()
    plans = mgr.list_plans(status=status, repo=repo)
    return [plan.model_dump(mode="json") for plan in plans]


@mcp.tool()
async def coord_list_dependencies(
    consumer: str | None = None,
    provider: str | None = None,
    dependency_type: str | None = None,
) -> list[dict[str, Any]]:
    """List inter-repository dependencies with optional filtering."""
    mgr = _get_manager()
    deps = mgr.list_dependencies(
        consumer=consumer, provider=provider, dependency_type=dependency_type
    )
    return [dep.model_dump(mode="json") for dep in deps]


@mcp.tool()
async def coord_get_ecosystem_status() -> dict[str, Any]:
    """Get unified ecosystem coordination status.

    Single-pane view answering: what is blocked, degraded, and needs operator
    action right now? Aggregates active plans, high/critical blockers,
    unsatisfied dependencies, and todo counts.

    Returns:
        Dictionary with health indicator, plan summaries, blockers,
        degraded dependencies, and pending/in-progress todo counts.
    """
    mgr = _get_manager()
    return mgr.get_ecosystem_status()
