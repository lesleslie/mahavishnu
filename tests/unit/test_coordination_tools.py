"""Comprehensive unit tests for coordination_tools MCP tool functions.

Tests all 13 async FastMCP tool functions that wrap CoordinationManager.
Each test patches _get_manager to return a mock manager, verifying correct
delegation, validation, error handling, and JSON serialization behavior.

Mocking strategy:
    Patch ``mahavishnu.mcp.tools.coordination_tools._get_manager`` so that
    every tool function receives a controllable MagicMock instead of a real
    CoordinationManager (which would require ecosystem.yaml on disk).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyType,
    IssueStatus,
    PlanStatus,
    Priority,
    TodoStatus,
)
from mahavishnu.core.status import DependencyStatus
from mahavishnu.mcp.tools.coordination_tools import (
    coord_check_dependencies,
    coord_close_issue,
    coord_complete_todo,
    coord_create_issue,
    coord_create_todo,
    coord_get_blocking_issues,
    coord_get_issue,
    coord_get_repo_status,
    coord_get_todo,
    coord_list_dependencies,
    coord_list_issues,
    coord_list_plans,
    coord_list_todos,
    coord_update_issue,
)

# ---------------------------------------------------------------------------
# Helpers / shared mock data factories
# ---------------------------------------------------------------------------


def _make_issue(
    issue_id: str = "ISSUE-001",
    title: str = "Test issue",
    description: str = "Test description",
    status: IssueStatus = IssueStatus.PENDING,
    priority: Priority = Priority.MEDIUM,
    severity: str = "normal",
    repos: list[str] | None = None,
    assignee: str | None = None,
    target: str | None = None,
    labels: list[str] | None = None,
) -> CrossRepoIssue:
    """Create a CrossRepoIssue instance with sensible defaults."""
    now = "2026-01-01T00:00:00"
    return CrossRepoIssue(
        id=issue_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        severity=severity,
        repos=repos or ["repo1"],
        created=now,
        updated=now,
        target=target,
        dependencies=[],
        blocking=[],
        assignee=assignee,
        labels=labels or [],
        metadata={},
    )


def _make_todo(
    todo_id: str = "TODO-001",
    task: str = "Test task",
    description: str = "Test todo description",
    repo: str = "repo1",
    status: TodoStatus = TodoStatus.PENDING,
    priority: Priority = Priority.MEDIUM,
    estimated_hours: float = 4.0,
    assignee: str | None = None,
) -> CrossRepoTodo:
    """Create a CrossRepoTodo instance with sensible defaults."""
    now = "2026-01-01T00:00:00"
    return CrossRepoTodo(
        id=todo_id,
        task=task,
        description=description,
        repo=repo,
        status=status,
        priority=priority,
        created=now,
        updated=now,
        estimated_hours=estimated_hours,
        actual_hours=None,
        blocked_by=[],
        blocking=[],
        assignee=assignee,
        labels=[],
        acceptance_criteria=[],
    )


def _make_dependency(
    dep_id: str = "DEP-001",
    consumer: str = "fastblocks",
    provider: str = "oneiric",
    dep_type: DependencyType = DependencyType.RUNTIME,
    version_constraint: str = ">=0.2.0",
    status: DependencyStatus = DependencyStatus.SATISFIED,
) -> Dependency:
    """Create a Dependency instance with sensible defaults."""
    return Dependency(
        id=dep_id,
        consumer=consumer,
        provider=provider,
        type=dep_type,
        version_constraint=version_constraint,
        status=status,
        created="2026-01-15T00:00:00",
        updated="2026-01-30T00:00:00",
        notes="Test dependency",
        validation=None,
    )


def _make_plan(
    plan_id: str = "PLAN-001",
    title: str = "Test plan",
    status: PlanStatus = PlanStatus.DRAFT,
    repos: list[str] | None = None,
) -> CrossRepoPlan:
    """Create a CrossRepoPlan instance with sensible defaults."""
    now = "2026-01-01T00:00:00"
    return CrossRepoPlan(
        id=plan_id,
        title=title,
        description="Test plan description",
        status=status,
        repos=repos or ["repo1"],
        created=now,
        updated=now,
        target="2026-06-01T00:00:00",
        milestones=[],
    )


def _mock_manager() -> MagicMock:
    """Create a mock CoordinationManager with _coordination dict."""
    mgr = MagicMock()
    mgr._coordination = {
        "issues": [],
        "todos": [],
        "dependencies": [],
        "plans": [],
    }
    return mgr


_PATCH_TARGET = "mahavishnu.mcp.tools.coordination_tools._get_manager"


# ===========================================================================
# 1. coord_list_issues
# ===========================================================================


class TestCoordListIssues:
    """Tests for coord_list_issues tool function."""

    @pytest.mark.asyncio
    async def test_no_filters_returns_all_issues(self) -> None:
        """When no filters are given, list_issues is called with all None."""
        issue = _make_issue()
        mgr = _mock_manager()
        mgr.list_issues.return_value = [issue]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_issues()

        mgr.list_issues.assert_called_once_with(
            status=None, priority=None, repo=None, assignee=None
        )
        assert len(result) == 1
        assert result[0]["id"] == "ISSUE-001"
        assert result[0]["title"] == "Test issue"

    @pytest.mark.asyncio
    async def test_status_filter_converts_to_enum(self) -> None:
        """A valid status string is converted to IssueStatus before passing to manager."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_issues(status="pending")

        call_kwargs = mgr.list_issues.call_args
        assert call_kwargs.kwargs["status"] == IssueStatus.PENDING

    @pytest.mark.asyncio
    async def test_invalid_status_raises_value_error(self) -> None:
        """An invalid status string raises ValueError with valid values listed."""
        mgr = _mock_manager()

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid status: nonexistent"):
                await coord_list_issues(status="nonexistent")

    @pytest.mark.asyncio
    async def test_priority_filter_passed_through(self) -> None:
        """Priority filter string is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_issues(priority="high")

        call_kwargs = mgr.list_issues.call_args
        assert call_kwargs.kwargs["priority"] == "high"

    @pytest.mark.asyncio
    async def test_repo_filter_passed_through(self) -> None:
        """Repo filter string is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_issues(repo="mahavishnu")

        call_kwargs = mgr.list_issues.call_args
        assert call_kwargs.kwargs["repo"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_assignee_filter_passed_through(self) -> None:
        """Assignee filter string is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_issues(assignee="les")

        call_kwargs = mgr.list_issues.call_args
        assert call_kwargs.kwargs["assignee"] == "les"

    @pytest.mark.asyncio
    async def test_multiple_filters_combined(self) -> None:
        """All provided filters are forwarded together."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_issues(
                status="in_progress", priority="critical", repo="akosha", assignee="les"
            )

        call_kwargs = mgr.list_issues.call_args
        assert call_kwargs.kwargs["status"] == IssueStatus.IN_PROGRESS
        assert call_kwargs.kwargs["priority"] == "critical"
        assert call_kwargs.kwargs["repo"] == "akosha"
        assert call_kwargs.kwargs["assignee"] == "les"

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """When manager returns no issues, result is an empty list."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_issues()

        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self) -> None:
        """Each issue in the result is a plain dict (model_dump mode='json')."""
        issue = _make_issue()
        mgr = _mock_manager()
        mgr.list_issues.return_value = [issue]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_issues()

        assert isinstance(result[0], dict)
        # Enum values should be serialized to strings
        assert result[0]["status"] == "pending"
        assert result[0]["priority"] == "medium"


# ===========================================================================
# 2. coord_get_issue
# ===========================================================================


class TestCoordGetIssue:
    """Tests for coord_get_issue tool function."""

    @pytest.mark.asyncio
    async def test_found_returns_issue_dict(self) -> None:
        """When manager returns an issue, it is serialized to a dict."""
        issue = _make_issue()
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_issue("ISSUE-001")

        mgr.get_issue.assert_called_once_with("ISSUE-001")
        assert result["id"] == "ISSUE-001"
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_not_found_raises_value_error(self) -> None:
        """When manager returns None, ValueError is raised."""
        mgr = _mock_manager()
        mgr.get_issue.return_value = None

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Issue ISSUE-999 not found"):
                await coord_get_issue("ISSUE-999")


# ===========================================================================
# 3. coord_create_issue
# ===========================================================================


class TestCoordCreateIssue:
    """Tests for coord_create_issue tool function."""

    @pytest.mark.asyncio
    async def test_success_with_all_params(self) -> None:
        """Creating an issue with all parameters succeeds."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_issue(
                title="New issue",
                description="Issue description",
                repos=["repo1", "repo2"],
                priority="high",
                severity="bug",
                assignee="les",
                target="2026-06-01T00:00:00",
                labels=["bug", "urgent"],
            )

        mgr.create_issue.assert_called_once()
        mgr.save.assert_called_once()
        assert result["title"] == "New issue"
        assert result["priority"] == "high"
        assert result["repos"] == ["repo1", "repo2"]
        assert result["assignee"] == "les"
        assert result["labels"] == ["bug", "urgent"]

    @pytest.mark.asyncio
    async def test_default_values(self) -> None:
        """Creating an issue with only required params uses sensible defaults."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_issue(
                title="Minimal issue",
                description="desc",
                repos=["repo1"],
            )

        assert result["priority"] == "medium"
        assert result["severity"] == "normal"
        assert result["assignee"] is None
        assert result["target"] is None
        assert result["labels"] == []
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_id_generation_with_empty_list(self) -> None:
        """When no existing issues, ID is ISSUE-001."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_issue(title="First", description="desc", repos=["repo1"])

        assert result["id"] == "ISSUE-001"

    @pytest.mark.asyncio
    async def test_id_generation_with_existing_issues(self) -> None:
        """When existing issues exist, ID is incremented."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = [_make_issue(), _make_issue("ISSUE-002")]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_issue(title="Third", description="desc", repos=["repo1"])

        assert result["id"] == "ISSUE-003"

    @pytest.mark.asyncio
    async def test_invalid_priority_raises_value_error(self) -> None:
        """An invalid priority string raises ValueError."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid priority: nonexistent"):
                await coord_create_issue(
                    title="Bad", description="desc", repos=["repo1"], priority="nonexistent"
                )

    @pytest.mark.asyncio
    async def test_manager_save_called(self) -> None:
        """create_issue and save are both called on the manager."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_create_issue(title="T", description="D", repos=["r"])

        mgr.create_issue.assert_called_once()
        mgr.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_created_and_updated_timestamps_set(self) -> None:
        """Created and updated timestamps are set to current time."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_issue(title="T", description="D", repos=["r"])

        # Timestamps should be ISO format strings
        datetime.fromisoformat(result["created"])
        datetime.fromisoformat(result["updated"])


# ===========================================================================
# 4. coord_update_issue
# ===========================================================================


class TestCoordUpdateIssue:
    """Tests for coord_update_issue tool function."""

    @pytest.mark.asyncio
    async def test_update_status(self) -> None:
        """Updating an issue status delegates to manager.update_issue."""
        issue = _make_issue(status=IssueStatus.IN_PROGRESS)
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_update_issue("ISSUE-001", status="in_progress")

        mgr.update_issue.assert_called_once_with("ISSUE-001", {"status": "in_progress"})
        mgr.save.assert_called_once()
        assert result["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_priority(self) -> None:
        """Updating an issue priority delegates to manager.update_issue."""
        issue = _make_issue(priority=Priority.HIGH)
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_update_issue("ISSUE-001", priority="high")

        mgr.update_issue.assert_called_once_with("ISSUE-001", {"priority": "high"})
        assert result["priority"] == "high"

    @pytest.mark.asyncio
    async def test_update_both_status_and_priority(self) -> None:
        """Both status and priority can be updated in one call."""
        issue = _make_issue(status=IssueStatus.IN_PROGRESS, priority=Priority.HIGH)
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_update_issue("ISSUE-001", status="in_progress", priority="high")

        mgr.update_issue.assert_called_once_with(
            "ISSUE-001", {"status": "in_progress", "priority": "high"}
        )

    @pytest.mark.asyncio
    async def test_invalid_status_raises_value_error(self) -> None:
        """An invalid status string raises ValueError."""
        mgr = _mock_manager()

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid status: bad_status"):
                await coord_update_issue("ISSUE-001", status="bad_status")

    @pytest.mark.asyncio
    async def test_invalid_priority_raises_value_error(self) -> None:
        """An invalid priority string raises ValueError."""
        mgr = _mock_manager()

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid priority: bad_priority"):
                await coord_update_issue("ISSUE-001", priority="bad_priority")

    @pytest.mark.asyncio
    async def test_no_updates_raises_value_error(self) -> None:
        """Calling without status or priority raises ValueError."""
        mgr = _mock_manager()

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="No updates specified"):
                await coord_update_issue("ISSUE-001")

    @pytest.mark.asyncio
    async def test_returns_updated_issue(self) -> None:
        """After update, the updated issue is fetched and returned."""
        updated_issue = _make_issue(status=IssueStatus.RESOLVED)
        mgr = _mock_manager()
        mgr.get_issue.return_value = updated_issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_update_issue("ISSUE-001", status="resolved")

        # get_issue is called after update_issue to fetch the updated state
        assert mgr.get_issue.call_count == 1
        assert result["id"] == "ISSUE-001"
        assert result["status"] == "resolved"


# ===========================================================================
# 5. coord_close_issue
# ===========================================================================


class TestCoordCloseIssue:
    """Tests for coord_close_issue tool function."""

    @pytest.mark.asyncio
    async def test_close_calls_update_with_closed(self) -> None:
        """Closing an issue calls update_issue with status=closed."""
        issue = _make_issue(status=IssueStatus.CLOSED)
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_close_issue("ISSUE-001")

        mgr.update_issue.assert_called_once_with("ISSUE-001", {"status": "closed"})
        mgr.save.assert_called_once()
        assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_close_returns_serialized_issue(self) -> None:
        """The returned value is a JSON-serializable dict."""
        issue = _make_issue()
        mgr = _mock_manager()
        mgr.get_issue.return_value = issue

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_close_issue("ISSUE-001")

        assert isinstance(result, dict)
        assert "id" in result


# ===========================================================================
# 6. coord_list_todos
# ===========================================================================


class TestCoordListTodos:
    """Tests for coord_list_todos tool function."""

    @pytest.mark.asyncio
    async def test_no_filters_returns_all_todos(self) -> None:
        """When no filters are given, list_todos is called with all None."""
        todo = _make_todo()
        mgr = _mock_manager()
        mgr.list_todos.return_value = [todo]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_todos()

        mgr.list_todos.assert_called_once_with(status=None, repo=None, assignee=None)
        assert len(result) == 1
        assert result[0]["id"] == "TODO-001"

    @pytest.mark.asyncio
    async def test_status_filter_converts_to_enum(self) -> None:
        """A valid status string is converted to TodoStatus before passing to manager."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_todos(status="completed")

        call_kwargs = mgr.list_todos.call_args
        assert call_kwargs.kwargs["status"] == TodoStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_invalid_status_raises_value_error(self) -> None:
        """An invalid status string raises ValueError with valid values listed."""
        mgr = _mock_manager()

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid status: nonexistent"):
                await coord_list_todos(status="nonexistent")

    @pytest.mark.asyncio
    async def test_repo_filter_passed_through(self) -> None:
        """Repo filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_todos(repo="mahavishnu")

        call_kwargs = mgr.list_todos.call_args
        assert call_kwargs.kwargs["repo"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_assignee_filter_passed_through(self) -> None:
        """Assignee filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_todos(assignee="les")

        call_kwargs = mgr.list_todos.call_args
        assert call_kwargs.kwargs["assignee"] == "les"

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """When manager returns no todos, result is an empty list."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_todos()

        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self) -> None:
        """Each todo in the result is a plain dict with string enum values."""
        todo = _make_todo()
        mgr = _mock_manager()
        mgr.list_todos.return_value = [todo]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_todos()

        assert isinstance(result[0], dict)
        assert result[0]["status"] == "pending"
        assert result[0]["priority"] == "medium"


# ===========================================================================
# 7. coord_get_todo
# ===========================================================================


class TestCoordGetTodo:
    """Tests for coord_get_todo tool function."""

    @pytest.mark.asyncio
    async def test_found_returns_todo_dict(self) -> None:
        """When manager returns a todo, it is serialized to a dict."""
        todo = _make_todo()
        mgr = _mock_manager()
        mgr.get_todo.return_value = todo

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_todo("TODO-001")

        mgr.get_todo.assert_called_once_with("TODO-001")
        assert result["id"] == "TODO-001"
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_not_found_raises_value_error(self) -> None:
        """When manager returns None, ValueError is raised."""
        mgr = _mock_manager()
        mgr.get_todo.return_value = None

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Todo TODO-999 not found"):
                await coord_get_todo("TODO-999")


# ===========================================================================
# 8. coord_create_todo
# ===========================================================================


class TestCoordCreateTodo:
    """Tests for coord_create_todo tool function."""

    @pytest.mark.asyncio
    async def test_success_with_all_params(self) -> None:
        """Creating a todo with all parameters succeeds."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_todo(
                task="Implement feature",
                description="Detailed description",
                repo="mahavishnu",
                estimate_hours=8.0,
                priority="high",
                assignee="les",
                blocked_by=["ISSUE-001"],
                labels=["feature"],
                acceptance_criteria=["Tests pass", "Docs updated"],
            )

        mgr.save.assert_called_once()
        assert result["task"] == "Implement feature"
        assert result["repo"] == "mahavishnu"
        assert result["priority"] == "high"
        assert result["assignee"] == "les"
        assert result["blocked_by"] == ["ISSUE-001"]
        assert result["labels"] == ["feature"]
        assert result["acceptance_criteria"] == ["Tests pass", "Docs updated"]

    @pytest.mark.asyncio
    async def test_default_values(self) -> None:
        """Creating a todo with only required params uses sensible defaults."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_todo(
                task="Minimal task",
                description="desc",
                repo="repo1",
                estimate_hours=2.0,
            )

        assert result["priority"] == "medium"
        assert result["assignee"] is None
        assert result["blocked_by"] == []
        assert result["blocking"] == []
        assert result["labels"] == []
        assert result["acceptance_criteria"] == []
        assert result["actual_hours"] is None
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_id_generation_with_empty_list(self) -> None:
        """When no existing todos, ID is TODO-001."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_todo(
                task="First", description="desc", repo="r", estimate_hours=1.0
            )

        assert result["id"] == "TODO-001"

    @pytest.mark.asyncio
    async def test_id_generation_with_existing_todos(self) -> None:
        """When existing todos exist, ID is incremented."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = [_make_todo(), _make_todo("TODO-002")]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_todo(
                task="Third", description="desc", repo="r", estimate_hours=1.0
            )

        assert result["id"] == "TODO-003"

    @pytest.mark.asyncio
    async def test_invalid_priority_raises_value_error(self) -> None:
        """An invalid priority string raises ValueError."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Invalid priority: nonexistent"):
                await coord_create_todo(
                    task="Bad",
                    description="desc",
                    repo="r",
                    estimate_hours=1.0,
                    priority="nonexistent",
                )

    @pytest.mark.asyncio
    async def test_todo_added_to_coordination_data(self) -> None:
        """The created todo is appended to mgr._coordination['todos']."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_create_todo(task="Task", description="desc", repo="r", estimate_hours=1.0)

        assert len(mgr._coordination["todos"]) == 1
        assert mgr._coordination["todos"][0]["task"] == "Task"

    @pytest.mark.asyncio
    async def test_save_called(self) -> None:
        """Manager.save() is called after creating a todo."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_create_todo(task="T", description="D", repo="r", estimate_hours=1.0)

        mgr.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_created_and_updated_timestamps_set(self) -> None:
        """Created and updated timestamps are set to current time."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_create_todo(
                task="T", description="D", repo="r", estimate_hours=1.0
            )

        datetime.fromisoformat(result["created"])
        datetime.fromisoformat(result["updated"])


# ===========================================================================
# 9. coord_complete_todo
# ===========================================================================


class TestCoordCompleteTodo:
    """Tests for coord_complete_todo tool function."""

    @pytest.mark.asyncio
    async def test_complete_sets_status_to_completed(self) -> None:
        """Completing a todo sets its status to 'completed'."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = [
            {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"}
        ]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_complete_todo("TODO-001")

        assert result["status"] == "completed"
        mgr.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_updates_timestamp(self) -> None:
        """Completing a todo updates its 'updated' field to current time."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = [
            {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"}
        ]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_complete_todo("TODO-001")

        # The updated timestamp should be recent
        updated_dt = datetime.fromisoformat(result["updated"])
        assert updated_dt.year >= 2026

    @pytest.mark.asyncio
    async def test_complete_not_found_raises_value_error(self) -> None:
        """Completing a nonexistent todo raises ValueError."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = []

        with patch(_PATCH_TARGET, return_value=mgr):
            with pytest.raises(ValueError, match="Todo TODO-999 not found"):
                await coord_complete_todo("TODO-999")

    @pytest.mark.asyncio
    async def test_complete_correct_todo_among_many(self) -> None:
        """Only the targeted todo is completed, others remain unchanged."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = [
            {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"},
            {"id": "TODO-002", "status": "in_progress", "updated": "2026-01-01T00:00:00"},
            {"id": "TODO-003", "status": "pending", "updated": "2026-01-01T00:00:00"},
        ]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_complete_todo("TODO-002")

        assert result["id"] == "TODO-002"
        assert result["status"] == "completed"
        assert mgr._coordination["todos"][0]["status"] == "pending"
        assert mgr._coordination["todos"][2]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_complete_saves_coordination_data(self) -> None:
        """After completion, _coordination['todos'] is updated on the manager."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = [
            {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"}
        ]

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_complete_todo("TODO-001")

        # The mutation should be reflected in the manager's data
        assert mgr._coordination["todos"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_returns_todo_dict(self) -> None:
        """The returned value is a plain dict (not a Pydantic model)."""
        mgr = _mock_manager()
        mgr._coordination["todos"] = [
            {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"}
        ]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_complete_todo("TODO-001")

        assert isinstance(result, dict)


# ===========================================================================
# 10. coord_get_blocking_issues
# ===========================================================================


class TestCoordGetBlockingIssues:
    """Tests for coord_get_blocking_issues tool function."""

    @pytest.mark.asyncio
    async def test_returns_blocking_issues(self) -> None:
        """Blocking issues are fetched and serialized."""
        issue = _make_issue(status=IssueStatus.IN_PROGRESS)
        mgr = _mock_manager()
        mgr.get_blocking_issues.return_value = [issue]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_blocking_issues("repo1")

        mgr.get_blocking_issues.assert_called_once_with("repo1")
        assert len(result) == 1
        assert result[0]["id"] == "ISSUE-001"

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """When no blocking issues, result is an empty list."""
        mgr = _mock_manager()
        mgr.get_blocking_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_blocking_issues("repo1")

        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self) -> None:
        """Each issue in the result is a plain dict."""
        issue = _make_issue(priority=Priority.CRITICAL)
        mgr = _mock_manager()
        mgr.get_blocking_issues.return_value = [issue]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_blocking_issues("repo1")

        assert isinstance(result[0], dict)
        assert result[0]["priority"] == "critical"


# ===========================================================================
# 11. coord_check_dependencies
# ===========================================================================


class TestCoordCheckDependencies:
    """Tests for coord_check_dependencies tool function."""

    @pytest.mark.asyncio
    async def test_with_consumer_filter(self) -> None:
        """Check dependencies delegates with consumer filter."""
        mgr = _mock_manager()
        mgr.check_dependencies.return_value = {
            "total": 1,
            "satisfied": 1,
            "unsatisfied": 0,
            "unknown": 0,
            "deprecated": 0,
            "dependencies": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_check_dependencies(consumer="fastblocks")

        mgr.check_dependencies.assert_called_once_with(consumer="fastblocks")
        assert result["total"] == 1
        assert result["satisfied"] == 1

    @pytest.mark.asyncio
    async def test_without_consumer_filter(self) -> None:
        """Check dependencies delegates without consumer filter (None)."""
        mgr = _mock_manager()
        mgr.check_dependencies.return_value = {
            "total": 0,
            "satisfied": 0,
            "unsatisfied": 0,
            "unknown": 0,
            "deprecated": 0,
            "dependencies": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_check_dependencies()

        mgr.check_dependencies.assert_called_once_with(consumer=None)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_returns_manager_result_directly(self) -> None:
        """The result from manager.check_dependencies is returned as-is."""
        expected = {
            "total": 3,
            "satisfied": 2,
            "unsatisfied": 1,
            "unknown": 0,
            "deprecated": 0,
            "dependencies": [
                {"id": "DEP-001", "status": "satisfied"},
                {"id": "DEP-002", "status": "satisfied"},
                {"id": "DEP-003", "status": "unsatisfied"},
            ],
        }
        mgr = _mock_manager()
        mgr.check_dependencies.return_value = expected

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_check_dependencies()

        assert result is expected
        assert result["total"] == 3


# ===========================================================================
# 12. coord_get_repo_status
# ===========================================================================


class TestCoordGetRepoStatus:
    """Tests for coord_get_repo_status tool function."""

    @pytest.mark.asyncio
    async def test_returns_all_status_keys(self) -> None:
        """Result dict contains all expected keys."""
        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        expected_keys = {
            "issues",
            "todos",
            "dependencies_outgoing",
            "dependencies_incoming",
            "blocking",
            "blocked_by",
        }
        assert set(result.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_models_converted_to_dicts(self) -> None:
        """Model instances in repo status are converted to plain dicts."""
        issue = _make_issue()
        todo = _make_todo()
        dep_out = _make_dependency(consumer="mahavishnu", provider="oneiric")
        dep_in = _make_dependency(consumer="akosha", provider="mahavishnu")

        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [issue],
            "todos": [todo],
            "dependencies_outgoing": [dep_out],
            "dependencies_incoming": [dep_in],
            "blocking": [todo],
            "blocked_by": [dep_out],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        # All values should be lists of dicts, not model instances
        for key in result:
            assert isinstance(result[key], list)
            for item in result[key]:
                assert isinstance(item, dict), f"{key} item is not a dict"

    @pytest.mark.asyncio
    async def test_issues_serialized_correctly(self) -> None:
        """Issue models are serialized with model_dump(mode='json')."""
        issue = _make_issue(status=IssueStatus.BLOCKED, priority=Priority.CRITICAL)
        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [issue],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        assert result["issues"][0]["status"] == "blocked"
        assert result["issues"][0]["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_todos_serialized_correctly(self) -> None:
        """Todo models are serialized with model_dump(mode='json')."""
        todo = _make_todo(status=TodoStatus.COMPLETED)
        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [todo],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        assert result["todos"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_dependencies_serialized_correctly(self) -> None:
        """Dependency models are serialized with model_dump(mode='json')."""
        dep = _make_dependency(dep_type=DependencyType.MCP, status=DependencyStatus.UNSATISFIED)
        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [dep],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        assert result["dependencies_outgoing"][0]["type"] == "mcp"
        assert result["dependencies_outgoing"][0]["status"] == "unsatisfied"

    @pytest.mark.asyncio
    async def test_empty_status_returns_empty_lists(self) -> None:
        """When no coordination data exists, all lists are empty."""
        mgr = _mock_manager()
        mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_get_repo_status("mahavishnu")

        for key in result:
            assert result[key] == []


# ===========================================================================
# 13. coord_list_plans
# ===========================================================================


class TestCoordListPlans:
    """Tests for coord_list_plans tool function."""

    @pytest.mark.asyncio
    async def test_no_filters_returns_all_plans(self) -> None:
        """When no filters are given, list_plans is called with all None."""
        plan = _make_plan()
        mgr = _mock_manager()
        mgr.list_plans.return_value = [plan]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_plans()

        mgr.list_plans.assert_called_once_with(status=None, repo=None)
        assert len(result) == 1
        assert result[0]["id"] == "PLAN-001"

    @pytest.mark.asyncio
    async def test_with_status_filter(self) -> None:
        """Status filter is passed directly to manager as a string."""
        mgr = _mock_manager()
        mgr.list_plans.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_plans(status="active")

        call_kwargs = mgr.list_plans.call_args
        assert call_kwargs.kwargs["status"] == "active"

    @pytest.mark.asyncio
    async def test_with_repo_filter(self) -> None:
        """Repo filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_plans.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_plans(repo="mahavishnu")

        call_kwargs = mgr.list_plans.call_args
        assert call_kwargs.kwargs["repo"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_with_both_filters(self) -> None:
        """Both filters are forwarded together."""
        mgr = _mock_manager()
        mgr.list_plans.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_plans(status="draft", repo="akosha")

        call_kwargs = mgr.list_plans.call_args
        assert call_kwargs.kwargs["status"] == "draft"
        assert call_kwargs.kwargs["repo"] == "akosha"

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """When no plans exist, result is an empty list."""
        mgr = _mock_manager()
        mgr.list_plans.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_plans()

        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self) -> None:
        """Each plan in the result is a plain dict with string enum values."""
        plan = _make_plan(status=PlanStatus.ACTIVE)
        mgr = _mock_manager()
        mgr.list_plans.return_value = [plan]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_plans()

        assert isinstance(result[0], dict)
        assert result[0]["status"] == "active"


# ===========================================================================
# 14. coord_list_dependencies
# ===========================================================================


class TestCoordListDependencies:
    """Tests for coord_list_dependencies tool function."""

    @pytest.mark.asyncio
    async def test_no_filters_returns_all_dependencies(self) -> None:
        """When no filters are given, list_dependencies is called with all None."""
        dep = _make_dependency()
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = [dep]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_dependencies()

        mgr.list_dependencies.assert_called_once_with(
            consumer=None, provider=None, dependency_type=None
        )
        assert len(result) == 1
        assert result[0]["id"] == "DEP-001"

    @pytest.mark.asyncio
    async def test_with_consumer_filter(self) -> None:
        """Consumer filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_dependencies(consumer="fastblocks")

        call_kwargs = mgr.list_dependencies.call_args
        assert call_kwargs.kwargs["consumer"] == "fastblocks"

    @pytest.mark.asyncio
    async def test_with_provider_filter(self) -> None:
        """Provider filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_dependencies(provider="oneiric")

        call_kwargs = mgr.list_dependencies.call_args
        assert call_kwargs.kwargs["provider"] == "oneiric"

    @pytest.mark.asyncio
    async def test_with_dependency_type_filter(self) -> None:
        """Dependency type filter is passed directly to manager."""
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_dependencies(dependency_type="mcp")

        call_kwargs = mgr.list_dependencies.call_args
        assert call_kwargs.kwargs["dependency_type"] == "mcp"

    @pytest.mark.asyncio
    async def test_with_all_filters(self) -> None:
        """All filters are forwarded together."""
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            await coord_list_dependencies(
                consumer="fastblocks",
                provider="oneiric",
                dependency_type="runtime",
            )

        call_kwargs = mgr.list_dependencies.call_args
        assert call_kwargs.kwargs["consumer"] == "fastblocks"
        assert call_kwargs.kwargs["provider"] == "oneiric"
        assert call_kwargs.kwargs["dependency_type"] == "runtime"

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self) -> None:
        """When no dependencies match, result is an empty list."""
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_dependencies()

        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_json_serializable(self) -> None:
        """Each dependency in the result is a plain dict with string enum values."""
        dep = _make_dependency(dep_type=DependencyType.MCP)
        mgr = _mock_manager()
        mgr.list_dependencies.return_value = [dep]

        with patch(_PATCH_TARGET, return_value=mgr):
            result = await coord_list_dependencies()

        assert isinstance(result[0], dict)
        assert result[0]["type"] == "mcp"
        assert result[0]["status"] == "satisfied"


# ===========================================================================
# Cross-cutting / edge case tests
# ===========================================================================


class TestCrossCutting:
    """Tests covering cross-cutting concerns and edge cases."""

    @pytest.mark.asyncio
    async def test_all_issue_statuses_are_valid(self) -> None:
        """Every IssueStatus value is accepted by coord_list_issues."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            for status in IssueStatus:
                await coord_list_issues(status=status.value)

    @pytest.mark.asyncio
    async def test_all_todo_statuses_are_valid(self) -> None:
        """Every TodoStatus value is accepted by coord_list_todos."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            for status in TodoStatus:
                await coord_list_todos(status=status.value)

    @pytest.mark.asyncio
    async def test_all_priorities_are_valid_for_issue_creation(self) -> None:
        """Every Priority value is accepted by coord_create_issue."""
        mgr = _mock_manager()
        mgr.list_issues.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            for priority in Priority:
                result = await coord_create_issue(
                    title="T", description="D", repos=["r"], priority=priority.value
                )
                assert result["priority"] == priority.value

    @pytest.mark.asyncio
    async def test_all_priorities_are_valid_for_todo_creation(self) -> None:
        """Every Priority value is accepted by coord_create_todo."""
        mgr = _mock_manager()
        mgr.list_todos.return_value = []

        with patch(_PATCH_TARGET, return_value=mgr):
            for priority in Priority:
                result = await coord_create_todo(
                    task="T",
                    description="D",
                    repo="r",
                    estimate_hours=1.0,
                    priority=priority.value,
                )
                assert result["priority"] == priority.value

    @pytest.mark.asyncio
    async def test_get_manager_called_on_each_invocation(self) -> None:
        """Each tool call invokes _get_manager() to obtain a fresh manager."""
        call_count = 0

        def counting_get_manager() -> MagicMock:
            nonlocal call_count
            call_count += 1
            mgr = _mock_manager()
            mgr.list_issues.return_value = []
            return mgr

        with patch(_PATCH_TARGET, side_effect=counting_get_manager):
            await coord_list_issues()
            await coord_list_issues()
            await coord_list_issues()

        assert call_count == 3
