"""
Comprehensive unit tests for the coordination CLI module.

Tests cover all CLI commands registered on the coord_app sub-app,
mocking CoordinationManager to avoid filesystem access to ecosystem.yaml.
"""

from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner

from mahavishnu.core.coordination.models import (
    DependencyType,
    IssueStatus,
    PlanStatus,
    Priority,
    TodoStatus,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures: mock issue / todo / plan / dependency objects
# ---------------------------------------------------------------------------


def _make_issue(
    issue_id: str = "ISSUE-001",
    title: str = "Test issue",
    status: IssueStatus = IssueStatus.PENDING,
    priority: Priority = Priority.MEDIUM,
    repos: list[str] | None = None,
    assignee: str | None = "alice",
    severity: str = "normal",
    created: str = "2026-01-01T00:00:00",
    updated: str = "2026-01-01T00:00:00",
    target: str | None = None,
    description: str = "A test issue",
    dependencies: list[str] | None = None,
    blocking: list[str] | None = None,
    labels: list[str] | None = None,
    metadata: dict | None = None,
) -> MagicMock:
    """Create a mock issue object with the expected attributes."""
    issue = MagicMock()
    issue.id = issue_id
    issue.title = title
    issue.status = status
    issue.priority = priority
    issue.repos = repos or ["repo-a"]
    issue.assignee = assignee
    issue.severity = severity
    issue.created = created
    issue.updated = updated
    issue.target = target
    issue.description = description
    issue.dependencies = dependencies or []
    issue.blocking = blocking or []
    issue.labels = labels or []
    issue.metadata = metadata or {}
    return issue


def _make_todo(
    todo_id: str = "TODO-001",
    task: str = "Test task",
    repo: str = "repo-a",
    status: TodoStatus = TodoStatus.PENDING,
    priority: Priority = Priority.MEDIUM,
    estimated_hours: float = 4.0,
    actual_hours: float | None = None,
    assignee: str | None = "alice",
    created: str = "2026-01-01T00:00:00",
    updated: str = "2026-01-01T00:00:00",
    description: str = "A test todo",
    blocked_by: list[str] | None = None,
    blocking: list[str] | None = None,
    labels: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> MagicMock:
    """Create a mock todo object with the expected attributes."""
    todo = MagicMock()
    todo.id = todo_id
    todo.task = task
    todo.repo = repo
    todo.status = status
    todo.priority = priority
    todo.estimated_hours = estimated_hours
    todo.actual_hours = actual_hours
    todo.assignee = assignee
    todo.created = created
    todo.updated = updated
    todo.description = description
    todo.blocked_by = blocked_by or []
    todo.blocking = blocking or []
    todo.labels = labels or []
    todo.acceptance_criteria = acceptance_criteria or []
    return todo


def _make_plan(
    plan_id: str = "PLAN-001",
    title: str = "Test plan",
    status: PlanStatus = PlanStatus.DRAFT,
    repos: list[str] | None = None,
    milestones: list | None = None,
    target: str = "2026-06-01T00:00:00",
) -> MagicMock:
    """Create a mock plan object with the expected attributes."""
    plan = MagicMock()
    plan.id = plan_id
    plan.title = title
    plan.status = status
    plan.repos = repos or ["repo-a"]
    plan.milestones = milestones or []
    plan.target = target
    return plan


def _make_dep(
    dep_id: str = "DEP-001",
    consumer: str = "fastblocks",
    provider: str = "oneiric",
    dep_type: DependencyType = DependencyType.RUNTIME,
    version_constraint: str = ">=0.2.0",
    status_value: str = "satisfied",
) -> MagicMock:
    """Create a mock dependency object with the expected attributes."""
    dep = MagicMock()
    dep.id = dep_id
    dep.consumer = consumer
    dep.provider = provider
    dep.type = dep_type
    dep.version_constraint = version_constraint
    dep.status = MagicMock(value=status_value)
    return dep


# ---------------------------------------------------------------------------
# Helper: build a parent Typer app with coord sub-app attached
# ---------------------------------------------------------------------------


def _make_app() -> typer.Typer:
    """Create a parent Typer app with coordination commands registered."""
    app = typer.Typer()
    from mahavishnu.coordination_cli import add_coordination_commands

    add_coordination_commands(app)
    return app


# ===========================================================================
# add_coordination_commands
# ===========================================================================


class TestAddCoordinationCommands:
    """Tests for add_coordination_commands()."""

    def test_registers_coord_sub_app(self):
        """add_coordination_commands should attach a 'coord' sub-app."""
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "coord" in registered_names

    def test_coord_app_is_typer_instance(self):
        """The registered coord app should be a Typer instance."""
        import typer

        from mahavishnu.coordination_cli import coord_app

        assert isinstance(coord_app, typer.Typer)


# ===========================================================================
# Issue commands
# ===========================================================================


class TestListIssues:
    """Tests for the 'list-issues' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_no_filters(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(issue_id="ISSUE-001", title="First issue"),
            _make_issue(issue_id="ISSUE-002", title="Second issue"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues"])
        assert result.exit_code == 0
        assert "ISSUE-001" in result.output
        assert "ISSUE-002" in result.output
        mock_mgr.list_issues.assert_called_once_with(
            status=None, priority=None, repo=None, assignee=None
        )

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_with_status_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(issue_id="ISSUE-001", status=IssueStatus.IN_PROGRESS),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues", "--status", "in_progress"])
        assert result.exit_code == 0
        assert "ISSUE-001" in result.output
        assert "in_progress" in result.output
        mock_mgr.list_issues.assert_called_once()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_with_priority_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(priority=Priority.HIGH),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues", "--priority", "high"])
        assert result.exit_code == 0
        mock_mgr.list_issues.assert_called_once_with(
            status=None, priority="high", repo=None, assignee=None
        )

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_with_repo_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(repos=["mahavishnu"]),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues", "--repo", "mahavishnu"])
        assert result.exit_code == 0
        mock_mgr.list_issues.assert_called_once_with(
            status=None, priority=None, repo="mahavishnu", assignee=None
        )

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_with_assignee_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(assignee="bob"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues", "--assignee", "bob"])
        assert result.exit_code == 0
        mock_mgr.list_issues.assert_called_once_with(
            status=None, priority=None, repo=None, assignee="bob"
        )

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_empty_results(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues"])
        assert result.exit_code == 0
        assert "No issues found" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_invalid_status(self, MockMgr):
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues", "--status", "bogus"])
        assert result.exit_code == 1
        assert "Invalid status" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_issues_truncates_repos(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = [
            _make_issue(
                repos=["repo-a", "repo-b", "repo-c", "repo-d", "repo-e"],
            ),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-issues"])
        assert result.exit_code == 0
        # First 3 repos shown, remainder truncated
        assert "repo-a" in result.output
        assert "(+2)" in result.output


class TestShowIssue:
    """Tests for the 'show-issue' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_issue_found(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_issue.return_value = _make_issue(
            issue_id="ISSUE-001",
            title="Detailed issue",
            description="Full description here",
            labels=["bug", "urgent"],
            metadata={"key": "value"},
            blocking=["ISSUE-002"],
            dependencies=["ISSUE-000"],
        )
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-issue", "ISSUE-001"])
        assert result.exit_code == 0
        assert "ISSUE-001" in result.output
        assert "Detailed issue" in result.output
        assert "Full description here" in result.output
        assert "bug" in result.output
        assert "key: value" in result.output
        mock_mgr.get_issue.assert_called_once_with("ISSUE-001")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_issue_not_found(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_issue.return_value = None
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-issue", "ISSUE-999"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCreateIssue:
    """Tests for the 'create-issue' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_create_issue_success(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_issues.return_value = []  # No existing issues -> ISSUE-001
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "create-issue",
                "--title",
                "New issue",
                "--description",
                "Issue description",
                "--repos",
                "repo-a,repo-b",
                "--priority",
                "high",
            ],
        )
        assert result.exit_code == 0
        assert "Created issue ISSUE-001" in result.output
        assert "New issue" in result.output
        assert "repo-a, repo-b" in result.output
        mock_mgr.create_issue.assert_called_once()
        mock_mgr.save.assert_called_once()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_create_issue_invalid_priority(self, MockMgr):
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "create-issue",
                "--title",
                "Bad priority",
                "--description",
                "desc",
                "--repos",
                "repo-a",
                "--priority",
                "ultra",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid priority" in result.output


class TestUpdateIssue:
    """Tests for the 'update-issue' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_status(self, MockMgr):
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(
            app,
            ["coord", "update-issue", "ISSUE-001", "--status", "in_progress"],
        )
        assert result.exit_code == 0
        assert "Updated issue ISSUE-001" in result.output
        mock_mgr.update_issue.assert_called_once_with("ISSUE-001", {"status": "in_progress"})
        mock_mgr.save.assert_called_once()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_priority(self, MockMgr):
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(
            app,
            ["coord", "update-issue", "ISSUE-001", "--priority", "critical"],
        )
        assert result.exit_code == 0
        assert "Updated issue ISSUE-001" in result.output
        mock_mgr.update_issue.assert_called_once_with("ISSUE-001", {"priority": "critical"})
        mock_mgr.save.assert_called_once()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_invalid_status(self, MockMgr):
        app = _make_app()
        result = runner.invoke(
            app,
            ["coord", "update-issue", "ISSUE-001", "--status", "nope"],
        )
        assert result.exit_code == 1
        assert "Invalid status" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_no_updates(self, MockMgr):
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(
            app,
            ["coord", "update-issue", "ISSUE-001"],
        )
        assert result.exit_code == 0
        assert "No updates specified" in result.output
        mock_mgr.update_issue.assert_not_called()
        mock_mgr.save.assert_not_called()


class TestCloseIssue:
    """Tests for the 'close-issue' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_close_issue_success(self, MockMgr):
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(app, ["coord", "close-issue", "ISSUE-001"])
        assert result.exit_code == 0
        assert "Closed issue ISSUE-001" in result.output
        mock_mgr.update_issue.assert_called_once_with("ISSUE-001", {"status": "closed"})
        mock_mgr.save.assert_called_once()


# ===========================================================================
# Todo commands
# ===========================================================================


class TestListTodos:
    """Tests for the 'list-todos' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_no_filters(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = [
            _make_todo(todo_id="TODO-001", task="First task"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos"])
        assert result.exit_code == 0
        assert "TODO-001" in result.output
        assert "First task" in result.output
        mock_mgr.list_todos.assert_called_once_with(status=None, repo=None, assignee=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_with_status_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = [
            _make_todo(status=TodoStatus.IN_PROGRESS),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos", "--status", "in_progress"])
        assert result.exit_code == 0
        assert "in_progre" in result.output
        mock_mgr.list_todos.assert_called_once()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_with_repo_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = [
            _make_todo(repo="mahavishnu"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos", "--repo", "mahavishnu"])
        assert result.exit_code == 0
        mock_mgr.list_todos.assert_called_once_with(status=None, repo="mahavishnu", assignee=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_with_assignee_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = [
            _make_todo(assignee="carol"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos", "--assignee", "carol"])
        assert result.exit_code == 0
        mock_mgr.list_todos.assert_called_once_with(status=None, repo=None, assignee="carol")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_empty_results(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos"])
        assert result.exit_code == 0
        assert "No todos found" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_todos_invalid_status(self, MockMgr):
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-todos", "--status", "invalid"])
        assert result.exit_code == 1
        assert "Invalid status" in result.output


class TestShowTodo:
    """Tests for the 'show-todo' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_todo_found(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_todo.return_value = _make_todo(
            todo_id="TODO-001",
            task="Build the thing",
            description="Detailed description",
            actual_hours=3.5,
            blocked_by=["ISSUE-001"],
            blocking=["TODO-002"],
            labels=["engineering"],
            acceptance_criteria=["Criterion 1", "Criterion 2"],
        )
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-todo", "TODO-001"])
        assert result.exit_code == 0
        assert "TODO-001" in result.output
        assert "Build the thing" in result.output
        assert "Detailed description" in result.output
        assert "Actual:" in result.output
        assert "3.5" in result.output
        assert "engineering" in result.output
        assert "Criterion 1" in result.output
        assert "Criterion 2" in result.output
        mock_mgr.get_todo.assert_called_once_with("TODO-001")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_todo_not_found(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_todo.return_value = None
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-todo", "TODO-999"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCreateTodo:
    """Tests for the 'create-todo' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_create_todo_success(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_todos.return_value = []
        mock_mgr._coordination = {"todos": []}
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "create-todo",
                "--task",
                "Implement feature",
                "--description",
                "Feature details",
                "--repo",
                "mahavishnu",
                "--estimate",
                "8",
                "--priority",
                "high",
            ],
        )
        assert result.exit_code == 0
        assert "Created todo TODO-001" in result.output
        assert "Implement feature" in result.output
        assert "mahavishnu" in result.output
        assert "8.0h" in result.output
        mock_mgr.save.assert_called_once()
        # Verify the todo was appended to _coordination
        assert len(mock_mgr._coordination["todos"]) == 1

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_create_todo_invalid_priority(self, MockMgr):
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "create-todo",
                "--task",
                "Task",
                "--description",
                "Desc",
                "--repo",
                "repo-a",
                "--estimate",
                "2",
                "--priority",
                "superhigh",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid priority" in result.output


class TestCompleteTodo:
    """Tests for the 'complete-todo' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_complete_todo_success(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr._coordination = {
            "todos": [
                {"id": "TODO-001", "status": "pending", "updated": "2026-01-01T00:00:00"},
            ],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "complete-todo", "TODO-001"])
        assert result.exit_code == 0
        assert "Completed todo TODO-001" in result.output
        mock_mgr.save.assert_called_once()
        # Verify status was updated in _coordination
        assert mock_mgr._coordination["todos"][0]["status"] == "completed"

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_complete_todo_not_found(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr._coordination = {"todos": []}
        app = _make_app()
        result = runner.invoke(app, ["coord", "complete-todo", "TODO-999"])
        assert result.exit_code == 1
        assert "not found" in result.output
        mock_mgr.save.assert_not_called()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_complete_todo_no_todos_key(self, MockMgr):
        """complete-todo should work even when _coordination has no 'todos' key."""
        mock_mgr = MockMgr.return_value
        mock_mgr._coordination = {}
        app = _make_app()
        result = runner.invoke(app, ["coord", "complete-todo", "TODO-001"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ===========================================================================
# Plan commands
# ===========================================================================


class TestListPlans:
    """Tests for the 'list-plans' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_plans_no_filters(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = [
            _make_plan(plan_id="PLAN-001", title="Roadmap Q1"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-plans"])
        assert result.exit_code == 0
        assert "PLAN-001" in result.output
        assert "Roadmap Q1" in result.output
        mock_mgr.list_plans.assert_called_once_with(status=None, repo=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_plans_with_status_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = [
            _make_plan(status=PlanStatus.ACTIVE),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-plans", "--status", "active"])
        assert result.exit_code == 0
        mock_mgr.list_plans.assert_called_once_with(status="active", repo=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_plans_with_repo_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = [
            _make_plan(repos=["mahavishnu"]),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-plans", "--repo", "mahavishnu"])
        assert result.exit_code == 0
        mock_mgr.list_plans.assert_called_once_with(status=None, repo="mahavishnu")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_plans_empty_results(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-plans"])
        assert result.exit_code == 0
        assert "No plans found" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_plans_truncates_repos(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = [
            _make_plan(
                repos=["r1", "r2", "r3", "r4"],
                milestones=[MagicMock(), MagicMock()],
            ),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-plans"])
        assert result.exit_code == 0
        assert "(+1)" in result.output


# ===========================================================================
# Dependency commands
# ===========================================================================


class TestListDeps:
    """Tests for the 'list-deps' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_deps_no_filters(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_dependencies.return_value = [
            _make_dep(dep_id="DEP-001"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-deps"])
        assert result.exit_code == 0
        assert "DEP-001" in result.output
        assert "fastblocks" in result.output
        mock_mgr.list_dependencies.assert_called_once_with(consumer=None, provider=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_deps_with_consumer_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_dependencies.return_value = [
            _make_dep(consumer="mahavishnu"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-deps", "--consumer", "mahavishnu"])
        assert result.exit_code == 0
        mock_mgr.list_dependencies.assert_called_once_with(consumer="mahavishnu", provider=None)

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_deps_with_provider_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_dependencies.return_value = [
            _make_dep(provider="oneiric"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-deps", "--provider", "oneiric"])
        assert result.exit_code == 0
        mock_mgr.list_dependencies.assert_called_once_with(consumer=None, provider="oneiric")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_deps_empty_results(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.list_dependencies.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-deps"])
        assert result.exit_code == 0
        assert "No dependencies found" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_list_deps_unsatisfied_status_color(self, MockMgr):
        """Unsatisfied dependencies should appear in red styling."""
        mock_mgr = MockMgr.return_value
        mock_mgr.list_dependencies.return_value = [
            _make_dep(status_value="unsatisfied"),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "list-deps"])
        assert result.exit_code == 0
        assert "unsatisfied" in result.output


class TestCheckDeps:
    """Tests for the 'check-deps' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_check_deps_results_display(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.check_dependencies.return_value = {
            "total": 3,
            "satisfied": 2,
            "unsatisfied": 1,
            "unknown": 0,
            "dependencies": [
                {
                    "consumer": "fastblocks",
                    "provider": "oneiric",
                    "type": "runtime",
                    "version_constraint": ">=0.2.0",
                    "status": "satisfied",
                    "validation": {"passed": True, "details": "OK"},
                },
                {
                    "consumer": "mahavishnu",
                    "provider": "dhara",
                    "type": "mcp",
                    "version_constraint": ">=1.0.0",
                    "status": "unsatisfied",
                    "validation": None,
                },
            ],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "check-deps"])
        assert result.exit_code == 0
        assert "Dependency Check Results" in result.output
        assert "Total: 3" in result.output
        assert "Satisfied: 2" in result.output
        assert "Unsatisfied: 1" in result.output
        assert "fastblocks" in result.output
        assert "dhara" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_check_deps_with_consumer_filter(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.check_dependencies.return_value = {
            "total": 1,
            "satisfied": 1,
            "unsatisfied": 0,
            "unknown": 0,
            "dependencies": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "check-deps", "--consumer", "mahavishnu"])
        assert result.exit_code == 0
        mock_mgr.check_dependencies.assert_called_once_with(consumer="mahavishnu")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_check_deps_with_deprecated(self, MockMgr):
        """Deprecated count should be displayed when present."""
        mock_mgr = MockMgr.return_value
        mock_mgr.check_dependencies.return_value = {
            "total": 2,
            "satisfied": 1,
            "unsatisfied": 0,
            "unknown": 0,
            "deprecated": 1,
            "dependencies": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "check-deps"])
        assert result.exit_code == 0
        assert "Deprecated: 1" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_check_deps_no_deprecated_key(self, MockMgr):
        """Should not crash when 'deprecated' key is absent."""
        mock_mgr = MockMgr.return_value
        mock_mgr.check_dependencies.return_value = {
            "total": 0,
            "satisfied": 0,
            "unsatisfied": 0,
            "unknown": 0,
            "dependencies": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "check-deps"])
        assert result.exit_code == 0


# ===========================================================================
# Status and blocking commands
# ===========================================================================


class TestRepoStatus:
    """Tests for the 'status' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_status_display(self, MockMgr):
        mock_mgr = MockMgr.return_value
        issue = _make_issue(
            issue_id="ISSUE-001",
            title="Open issue",
            status=IssueStatus.IN_PROGRESS,
            priority=Priority.HIGH,
        )
        todo = _make_todo(
            todo_id="TODO-001",
            task="Pending task",
            status=TodoStatus.PENDING,
        )
        dep_out = _make_dep(
            dep_id="DEP-OUT",
            consumer="mahavishnu",
            provider="oneiric",
            status_value="satisfied",
        )
        dep_in = _make_dep(
            dep_id="DEP-IN",
            consumer="crackerjack",
            provider="mahavishnu",
            status_value="satisfied",
        )
        blocking_todo = _make_todo(
            todo_id="TODO-BLOCK",
            task="Blocking task",
            status=TodoStatus.IN_PROGRESS,
            blocking=["TODO-002"],
        )
        mock_mgr.get_repo_status.return_value = {
            "issues": [issue],
            "todos": [todo],
            "dependencies_outgoing": [dep_out],
            "dependencies_incoming": [dep_in],
            "blocking": [blocking_todo],
            "blocked_by": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "status", "mahavishnu"])
        assert result.exit_code == 0
        assert "Coordination Status: mahavishnu" in result.output
        assert "ISSUE-001" in result.output
        assert "TODO-001" in result.output
        assert "mahavishnu" in result.output
        assert "oneiric" in result.output
        assert "Blocking" in result.output
        mock_mgr.get_repo_status.assert_called_once_with("mahavishnu")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_status_blocked_by_display(self, MockMgr):
        mock_mgr = MockMgr.return_value
        dep = _make_dep(
            dep_id="DEP-001",
            consumer="mahavishnu",
            provider="missing-pkg",
            status_value="unsatisfied",
        )
        mock_mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [dep],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "status", "mahavishnu"])
        assert result.exit_code == 0
        assert "Blocked By" in result.output
        assert "missing-pkg" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_status_empty_repo(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "status", "new-repo"])
        assert result.exit_code == 0
        assert "Issues Affecting This Repo: 0" in result.output
        assert "Todos for This Repo: 0" in result.output


class TestBlocking:
    """Tests for the 'blocking' command."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_blocking_with_issues(self, MockMgr):
        mock_mgr = MockMgr.return_value
        issue = _make_issue(
            issue_id="ISSUE-001",
            title="Blocking issue",
            status=IssueStatus.IN_PROGRESS,
            priority=Priority.CRITICAL,
        )
        mock_mgr.get_repo_status.return_value = {
            "issues": [issue],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "blocking", "mahavishnu"])
        assert result.exit_code == 0
        assert "ISSUE-001" in result.output
        assert "Blocking issue" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_blocking_with_deps(self, MockMgr):
        mock_mgr = MockMgr.return_value
        dep = _make_dep(
            dep_id="DEP-001",
            consumer="mahavishnu",
            provider="missing-pkg",
            status_value="unsatisfied",
        )
        mock_mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [dep],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "blocking", "mahavishnu"])
        assert result.exit_code == 0
        assert "Unsatisfied Dependencies" in result.output
        assert "missing-pkg" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_blocking_not_blocked(self, MockMgr):
        mock_mgr = MockMgr.return_value
        mock_mgr.get_repo_status.return_value = {
            "issues": [],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "blocking", "mahavishnu"])
        assert result.exit_code == 0
        assert "not blocked" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_blocking_with_both_issues_and_deps(self, MockMgr):
        mock_mgr = MockMgr.return_value
        issue = _make_issue(
            issue_id="ISSUE-001",
            title="Open issue",
            status=IssueStatus.IN_PROGRESS,
            priority=Priority.HIGH,
        )
        dep = _make_dep(
            dep_id="DEP-001",
            consumer="mahavishnu",
            provider="missing-pkg",
            status_value="unsatisfied",
        )
        mock_mgr.get_repo_status.return_value = {
            "issues": [issue],
            "todos": [],
            "dependencies_outgoing": [],
            "dependencies_incoming": [],
            "blocking": [],
            "blocked_by": [dep],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "blocking", "mahavishnu"])
        assert result.exit_code == 0
        assert "Open Issues" in result.output
        assert "ISSUE-001" in result.output
        assert "Unsatisfied Dependencies" in result.output
        assert "missing-pkg" in result.output
