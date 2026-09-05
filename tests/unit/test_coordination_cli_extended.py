"""
Extended CLI tests for ``mahavishnu.coordination_cli``.

Targets command callbacks that were not exercised by the original
``test_coordination_cli.py`` suite — specifically:

* ``add_repo_commands`` registration
* ``show-issue`` target field branch
* ``update-issue`` invalid-priority error path
* ``ecosystem-status`` and ``roadmap`` rendering
* ``repo`` Typer sub-app commands (``list-tasks``, ``show-task``,
  ``list-runs``, ``list-events``, ``create-event``) — these exercise the
  async ``TaskRepository``/``TaskRunRepository``/``TaskEventRepository``
  code paths via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.core.coordination.models import (
    DependencyType,
    IssueStatus,
    PlanStatus,
    Priority,
    TodoStatus,
)
from mahavishnu.core.status import TaskStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Rich / Typer terminal colour suppression
# ---------------------------------------------------------------------------
#
# CLI modules bind ``console = Console()`` at import time. Without
# ``no_color=True`` Rich inserts ANSI codes mid-string (e.g.
# ``ISSUE-\x1b[0m\x1b[1;36m001``) which breaks plain text assertions.
# We patch ``Console.__init__`` here for this file only (the project
# conftest disables it globally; the autouse fixture here guards against
# accidental removal of that conftest hook in the future).


@pytest.fixture(autouse=True)
def _disable_rich_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable Rich ANSI escape codes within this test file."""
    from rich.console import Console as _RichConsole

    _orig_init = _RichConsole.__init__

    def _patched_init(self: _RichConsole, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("no_color", True)
        kwargs.setdefault("color_system", None)
        kwargs.setdefault("force_terminal", False)
        kwargs.setdefault("force_interactive", False)
        kwargs.setdefault("width", 200)
        _orig_init(self, *args, **kwargs)

    monkeypatch.setattr(_RichConsole, "__init__", _patched_init)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(
    plan_id: str = "PLAN-001",
    title: str = "Q3 Roadmap",
    status: PlanStatus = PlanStatus.ACTIVE,
    repos: list[str] | None = None,
    target: str = "2026-09-30T00:00:00",
    milestones: list | None = None,
) -> MagicMock:
    plan = MagicMock()
    plan.id = plan_id
    plan.title = title
    plan.status = status
    plan.repos = repos or ["mahavishnu", "akosha"]
    plan.target = target
    plan.milestones = milestones if milestones is not None else []
    return plan


def _make_milestone(
    name: str = "Milestone",
    status: str = "completed",
    due: str = "2026-08-01T00:00:00",
) -> MagicMock:
    m = MagicMock()
    m.name = name
    m.status = MagicMock(value=status)
    m.due = due
    return m


def _make_issue(
    issue_id: str = "ISSUE-001",
    title: str = "Test issue",
    status: IssueStatus = IssueStatus.PENDING,
    priority: Priority = Priority.MEDIUM,
    repos: list[str] | None = None,
    assignee: str | None = "alice",
    severity: str = "normal",
    description: str = "A test issue",
    dependencies: list[str] | None = None,
    blocking: list[str] | None = None,
    labels: list[str] | None = None,
    metadata: dict | None = None,
    target: str | None = None,
    created: str = "2026-01-01T00:00:00",
    updated: str = "2026-01-01T00:00:00",
) -> MagicMock:
    issue = MagicMock()
    issue.id = issue_id
    issue.title = title
    issue.status = status
    issue.priority = priority
    issue.repos = repos or ["repo-a"]
    issue.assignee = assignee
    issue.severity = severity
    issue.description = description
    issue.dependencies = dependencies or []
    issue.blocking = blocking or []
    issue.labels = labels or []
    issue.metadata = metadata or {}
    issue.target = target
    issue.created = created
    issue.updated = updated
    return issue


def _make_task(
    task_id: UUID | None = None,
    title: str = "Sample task",
    repository: str | None = "mahavishnu",
    status: str = "pending",
    priority: str = "medium",
    created_at: str = "2026-01-01T00:00:00",
    description: str | None = "Long task description",
) -> MagicMock:
    """Construct a MagicMock matching the ``TaskRead`` shape.

    Uses string-backed ``status`` / ``priority`` mocks so Rich-style
    ``.value`` reads work and the production code can do
    ``t.status.value`` without touching a real Enum member.
    """
    from datetime import datetime

    t = MagicMock()
    t.id = task_id or uuid4()
    t.title = title
    t.repository = repository
    t.status = MagicMock()
    t.status.value = status
    t.priority = MagicMock()
    t.priority.value = priority
    t.created_at = (
        datetime.fromisoformat(created_at)
        if isinstance(created_at, str)
        else created_at
    )
    t.description = description
    return t


def _make_run(
    run_id: UUID | None = None,
    task_id: UUID | None = None,
    run_number: int = 1,
    status: str = "succeeded",
    engine: str | None = "prefect",
    worker_id: str | None = "worker-1",
) -> MagicMock:
    r = MagicMock()
    r.id = run_id or uuid4()
    r.task_id = task_id or uuid4()
    r.run_number = run_number
    r.status = status
    r.engine = engine
    r.worker_id = worker_id
    return r


def _make_event(
    event_id: UUID | None = None,
    task_id: UUID | None = None,
    run_id: UUID | None = None,
    event_type: str = "started",
    actor: str | None = "alice",
    event_time: str = "2026-08-15T10:30:00",
) -> MagicMock:
    e = MagicMock()
    e.id = event_id or uuid4()
    e.task_id = task_id or uuid4()
    e.run_id = run_id
    e.event_type = event_type
    e.actor = actor
    e.event_time = _parse_iso(event_time)
    return e


def _parse_iso(value: str) -> object:
    from datetime import datetime

    return datetime.fromisoformat(value)


def _make_app() -> typer.Typer:
    """Build a parent Typer with both coord and repo sub-apps attached."""
    app = typer.Typer()
    from mahavishnu.coordination_cli import (
        add_coordination_commands,
        add_repo_commands,
    )

    add_coordination_commands(app)
    add_repo_commands(app)
    return app


# ===========================================================================
# add_repo_commands
# ===========================================================================


class TestAddRepoCommands:
    """``add_repo_commands`` registers the ``repo`` Typer sub-app."""

    def test_registers_repo_sub_app(self) -> None:
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "repo" in registered_names

    def test_repo_app_is_typer_instance(self) -> None:
        import typer

        from mahavishnu.coordination_cli import repo_app

        assert isinstance(repo_app, typer.Typer)


# ===========================================================================
# show_issue target branch
# ===========================================================================


class TestShowIssueTargetBranch:
    """``show-issue`` renders the ``Target`` line when ``issue.target`` is set."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_issue_renders_target(self, MockMgr: MagicMock) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.get_issue.return_value = _make_issue(
            issue_id="ISSUE-007",
            title="With target",
            target="2026-12-31T00:00:00",
        )
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-issue", "ISSUE-007"])
        assert result.exit_code == 0
        assert "ISSUE-007" in result.output
        assert "Target:" in result.output
        assert "2026-12-31" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_show_issue_omits_target_when_none(self, MockMgr: MagicMock) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.get_issue.return_value = _make_issue(
            issue_id="ISSUE-008",
            title="No target",
            target=None,
        )
        app = _make_app()
        result = runner.invoke(app, ["coord", "show-issue", "ISSUE-008"])
        assert result.exit_code == 0
        assert "Target:" not in result.output


# ===========================================================================
# update_issue invalid priority branch
# ===========================================================================


class TestUpdateIssueInvalidPriority:
    """``update-issue`` exits 1 when given an invalid priority."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_invalid_priority(self, MockMgr: MagicMock) -> None:
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "update-issue",
                "ISSUE-001",
                "--priority",
                "ultra",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid priority" in result.output
        mock_mgr.update_issue.assert_not_called()
        mock_mgr.save.assert_not_called()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_update_issue_valid_priority_path(self, MockMgr: MagicMock) -> None:
        """Sanity check: valid priority should call update_issue + save."""
        mock_mgr = MockMgr.return_value
        app = _make_app()
        result = runner.invoke(
            app,
            [
                "coord",
                "update-issue",
                "ISSUE-001",
                "--priority",
                "high",
            ],
        )
        assert result.exit_code == 0
        mock_mgr.update_issue.assert_called_once_with("ISSUE-001", {"priority": "high"})
        mock_mgr.save.assert_called_once()


# ===========================================================================
# ecosystem_status
# ===========================================================================


class TestEcosystemStatus:
    """``ecosystem-status`` renders health, plans, blockers, deps, todos."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_ecosystem_status_healthy_with_data(
        self,
        MockMgr: MagicMock,
    ) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.get_ecosystem_status.return_value = {
            "health": "healthy",
            "active_plans": 2,
            "critical_blockers": 0,
            "degraded_dependencies": 0,
            "pending_todos": 3,
            "in_progress_todos": 1,
            "plans": [
                {
                    "id": "PLAN-001",
                    "title": "Q3 Roadmap",
                    "milestones_done": 2,
                    "milestones_total": 5,
                    "target": "2026-09-30T00:00:00",
                },
            ],
            "blockers": [],
            "dependencies": [],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "ecosystem-status"])
        assert result.exit_code == 0
        assert "Ecosystem Status:" in result.output
        assert "HEALTHY" in result.output
        assert "Active Plans: 2" in result.output
        assert "PLAN-001" in result.output
        assert "2/5 milestones" in result.output
        mock_mgr.get_ecosystem_status.assert_called_once_with()

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_ecosystem_status_degraded_with_blockers(
        self,
        MockMgr: MagicMock,
    ) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.get_ecosystem_status.return_value = {
            "health": "degraded",
            "active_plans": 0,
            "critical_blockers": 1,
            "degraded_dependencies": 1,
            "pending_todos": 0,
            "in_progress_todos": 0,
            "plans": [],
            "blockers": [
                {
                    "id": "ISSUE-9",
                    "title": "Auth broken",
                    "priority": "critical",
                    "repos": ["mahavishnu", "akosha"],
                },
            ],
            "dependencies": [
                {
                    "consumer": "mahavishnu",
                    "provider": "dhara",
                    "status": "unsatisfied",
                },
            ],
        }
        app = _make_app()
        result = runner.invoke(app, ["coord", "ecosystem-status"])
        assert result.exit_code == 0
        assert "DEGRADED" in result.output
        assert "Critical Blockers: 1" in result.output
        assert "ISSUE-9" in result.output
        assert "Degraded Dependencies: 1" in result.output
        assert "mahavishnu → dhara" in result.output
        assert "0 pending, 0 in progress" in result.output


# ===========================================================================
# roadmap
# ===========================================================================


class TestRoadmap:
    """``roadmap`` renders active plans with milestone progress bars."""

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_roadmap_with_plans_and_milestones(
        self,
        MockMgr: MagicMock,
    ) -> None:
        mock_mgr = MockMgr.return_value
        milestones = [
            _make_milestone("Phase 1", "completed", "2026-07-01T00:00:00"),
            _make_milestone("Phase 2", "completed", "2026-08-01T00:00:00"),
            _make_milestone("Phase 3", "in_progress", "2026-09-01T00:00:00"),
        ]
        mock_mgr.list_plans.return_value = [
            _make_plan(
                plan_id="PLAN-001",
                title="Q3 Roadmap",
                status=PlanStatus.ACTIVE,
                repos=["mahavishnu", "akosha", "crackerjack"],
                milestones=milestones,
            ),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "roadmap"])
        assert result.exit_code == 0
        assert "PLAN-001" in result.output
        assert "Q3 Roadmap" in result.output
        # Progress bar uses filled/empty blocks for done/total
        assert "Progress:" in result.output
        assert "2/3" in result.output
        # Truncates repos after 3 entries; the plan only has 3 so no truncation
        assert "mahavishnu, akosha, crackerjack" in result.output
        # Status filter call: defaults to "active"
        mock_mgr.list_plans.assert_called_once_with(status="active")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_roadmap_with_status_filter(self, MockMgr: MagicMock) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "roadmap", "--status", "draft"])
        assert result.exit_code == 0
        assert "No active plans found" in result.output
        mock_mgr.list_plans.assert_called_once_with(status="draft")

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_roadmap_empty_results(self, MockMgr: MagicMock) -> None:
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = []
        app = _make_app()
        result = runner.invoke(app, ["coord", "roadmap"])
        assert result.exit_code == 0
        assert "No active plans found" in result.output

    @patch("mahavishnu.coordination_cli.CoordinationManager")
    def test_roadmap_plan_without_milestones(self, MockMgr: MagicMock) -> None:
        """Plans without milestones render the dash placeholder for bar.

        Rich renders the em-dash via ``console.print`` and strips it from
        ``CliRunner.output``. We instead assert the empty-milestone branch
        was taken by verifying the ``Progress:`` line is absent (production
        code only emits it when ``plan.milestones`` is truthy).
        """
        mock_mgr = MockMgr.return_value
        mock_mgr.list_plans.return_value = [
            _make_plan(plan_id="PLAN-EMPTY", milestones=[]),
        ]
        app = _make_app()
        result = runner.invoke(app, ["coord", "roadmap"])
        assert result.exit_code == 0
        assert "PLAN-EMPTY" in result.output
        # No progress line when milestones are empty
        assert "Progress:" not in result.output


# ===========================================================================
# repo_app commands
# ===========================================================================
#
# These functions live inside async closures and call
# ``asyncio.run(_list())``. We mock the repository classes in
# ``mahavishnu.coordination_cli`` so the AsyncMock methods are returned to
# the closure's ``await`` expressions.


def _patch_async_repo(
    target_name: str,
    return_value: object,
) -> tuple[MagicMock, AsyncMock]:
    """Build a MagicMock with an async method returning ``return_value``."""
    repo_instance = MagicMock(name=target_name)
    method = AsyncMock(return_value=return_value)
    setattr(repo_instance, target_name.split(".")[-1], method)
    return repo_instance, method


class TestRepoListTasks:
    """``repo list-tasks`` drives ``TaskRepository.list_tasks``."""

    def test_list_tasks_with_results(self) -> None:
        tasks = [_make_task(title="task-a"), _make_task(title="task-b")]
        from datetime import datetime

        for t in tasks:
            t.created_at = datetime(2026, 1, 1, 0, 0, 0)

        mock_repo = MagicMock()
        mock_repo.list_tasks = AsyncMock(return_value=tasks)

        with patch(
            "mahavishnu.coordination_cli.TaskRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(app, ["repo", "list-tasks"])

        assert result.exit_code == 0
        assert "task-a" in result.output
        assert "task-b" in result.output
        assert "mahavishnu" in result.output
        mock_repo.list_tasks.assert_awaited_once()

    def test_list_tasks_empty(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks = AsyncMock(return_value=[])

        with patch(
            "mahavishnu.coordination_cli.TaskRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(app, ["repo", "list-tasks"])

        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_list_tasks_with_filters(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_tasks = AsyncMock(return_value=[_make_task()])

        with patch(
            "mahavishnu.coordination_cli.TaskRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                [
                    "repo",
                    "list-tasks",
                    "--status",
                    "pending",
                    "--repo",
                    "mahavishnu",
                    "--limit",
                    "5",
                ],
            )

        assert result.exit_code == 0
        mock_repo.list_tasks.assert_awaited_once()
        # Inspect the filter passed to the repository
        call_args = mock_repo.list_tasks.await_args
        filter_obj = call_args.args[0]
        assert filter_obj.repository == "mahavishnu"
        assert filter_obj.limit == 5
        assert filter_obj.status == TaskStatus.PENDING


class TestRepoShowTask:
    """``repo show-task`` drives ``TaskRepository.get_task``."""

    def test_show_task_found(self) -> None:
        from datetime import datetime

        task_id = uuid4()
        mock_task = MagicMock()
        mock_task.id = task_id
        mock_task.title = "Detailed task"
        mock_task.status = MagicMock()
        mock_task.status.value = "pending"
        mock_task.priority = MagicMock()
        mock_task.priority.value = "medium"
        mock_task.repository = "mahavishnu"
        mock_task.created_at = datetime(2026, 5, 1, 12, 30, 0)
        mock_task.description = "A task description"

        mock_repo = MagicMock()
        mock_repo.get_task = AsyncMock(return_value=mock_task)

        with patch(
            "mahavishnu.coordination_cli.TaskRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                ["repo", "show-task", str(task_id)],
            )

        assert result.exit_code == 0
        assert "Detailed task" in result.output
        assert "mahavishnu" in result.output
        assert "A task description" in result.output
        mock_repo.get_task.assert_awaited_once_with(task_id)

    def test_show_task_not_found(self) -> None:
        missing_id = uuid4()
        mock_repo = MagicMock()
        mock_repo.get_task = AsyncMock(return_value=None)

        with patch(
            "mahavishnu.coordination_cli.TaskRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                ["repo", "show-task", str(missing_id)],
            )

        assert result.exit_code == 1
        assert "not found" in result.output


class TestRepoListRuns:
    """``repo list-runs`` drives ``TaskRunRepository.list_runs_for_task``."""

    def test_list_runs_with_results(self) -> None:
        task_id = uuid4()
        runs = [
            _make_run(task_id=task_id, run_number=1, status="succeeded"),
            _make_run(task_id=task_id, run_number=2, status="failed"),
        ]

        mock_repo = MagicMock()
        mock_repo.list_runs_for_task = AsyncMock(return_value=runs)

        with patch(
            "mahavishnu.coordination_cli.TaskRunRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                ["repo", "list-runs", str(task_id)],
            )

        assert result.exit_code == 0
        assert "prefect" in result.output
        assert "worker-1" in result.output
        mock_repo.list_runs_for_task.assert_awaited_once_with(task_id)

    def test_list_runs_empty(self) -> None:
        task_id = uuid4()
        mock_repo = MagicMock()
        mock_repo.list_runs_for_task = AsyncMock(return_value=[])

        with patch(
            "mahavishnu.coordination_cli.TaskRunRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                ["repo", "list-runs", str(task_id)],
            )

        assert result.exit_code == 0
        assert "No runs found" in result.output


class TestRepoListEvents:
    """``repo list-events`` drives ``TaskEventRepository.list_events``."""

    def test_list_events_with_results(self) -> None:
        events = [
            _make_event(event_type="started", actor="alice"),
            _make_event(event_type="completed", actor="bob"),
        ]

        mock_repo = MagicMock()
        mock_repo.list_events = AsyncMock(return_value=events)

        with patch(
            "mahavishnu.coordination_cli.TaskEventRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(app, ["repo", "list-events"])

        assert result.exit_code == 0
        assert "started" in result.output
        assert "completed" in result.output
        assert "alice" in result.output
        mock_repo.list_events.assert_awaited_once()

    def test_list_events_with_filters(self) -> None:
        task_id = uuid4()
        mock_repo = MagicMock()
        mock_repo.list_events = AsyncMock(return_value=[])

        with patch(
            "mahavishnu.coordination_cli.TaskEventRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                [
                    "repo",
                    "list-events",
                    "--task",
                    str(task_id),
                    "--actor",
                    "alice",
                    "--limit",
                    "10",
                ],
            )

        assert result.exit_code == 0
        # The filter should have parsed task_id and limit
        call_args = mock_repo.list_events.await_args
        filter_obj = call_args.args[0]
        assert filter_obj.task_id == task_id
        assert filter_obj.actor == "alice"
        assert filter_obj.limit == 10

    def test_list_events_empty(self) -> None:
        mock_repo = MagicMock()
        mock_repo.list_events = AsyncMock(return_value=[])

        with patch(
            "mahavishnu.coordination_cli.TaskEventRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(app, ["repo", "list-events"])

        assert result.exit_code == 0
        assert "No events found" in result.output


class TestRepoCreateEvent:
    """``repo create-event`` drives ``TaskEventRepository.record_event``."""

    def test_create_event_success(self) -> None:
        task_id = uuid4()
        recorded_event = MagicMock()
        recorded_event.id = uuid4()
        recorded_event.task_id = task_id
        recorded_event.event_type = "started"
        recorded_event.actor = "alice"

        mock_repo = MagicMock()
        mock_repo.record_event = AsyncMock(return_value=recorded_event)

        with patch(
            "mahavishnu.coordination_cli.TaskEventRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                [
                    "repo",
                    "create-event",
                    "--task",
                    str(task_id),
                    "--type",
                    "started",
                    "--actor",
                    "alice",
                ],
            )

        assert result.exit_code == 0
        assert "Recorded event" in result.output
        assert "started" in result.output
        assert "alice" in result.output
        mock_repo.record_event.assert_awaited_once()
        # Confirm the TaskEventCreate payload was built correctly
        payload = mock_repo.record_event.await_args.args[0]
        assert payload.task_id == task_id
        assert payload.event_type == "started"
        assert payload.actor == "alice"
        assert payload.run_id is None

    def test_create_event_with_run_id(self) -> None:
        task_id = uuid4()
        run_id = uuid4()
        recorded_event = MagicMock()
        recorded_event.id = uuid4()
        recorded_event.task_id = task_id
        recorded_event.event_type = "completed"
        recorded_event.actor = None

        mock_repo = MagicMock()
        mock_repo.record_event = AsyncMock(return_value=recorded_event)

        with patch(
            "mahavishnu.coordination_cli.TaskEventRepository",
            return_value=mock_repo,
        ):
            app = _make_app()
            result = runner.invoke(
                app,
                [
                    "repo",
                    "create-event",
                    "--task",
                    str(task_id),
                    "--type",
                    "completed",
                    "--run",
                    str(run_id),
                ],
            )

        assert result.exit_code == 0
        assert "Recorded event" in result.output
        payload = mock_repo.record_event.await_args.args[0]
        assert payload.run_id == run_id
        assert payload.actor is None
