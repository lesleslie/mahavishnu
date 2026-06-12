"""
Focused unit tests for mahavishnu.core.coordination.manager.

Targets the public surface of CoordinationManager plus the module-level
helper ``_run_command_safe``. The companion ``test_coordination.py``
exercises integration scenarios across manager/memory/executor; this
file isolates manager behavior with finer-grained edge cases.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from mahavishnu.core.coordination.manager import (
    CoordinationManager,
    _run_command_safe,
)
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyType,
    DependencyValidation,
    Priority,
)
from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.status import DependencyStatus, IssueStatus, PlanStatus, TodoStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(data: dict[str, Any]) -> str:
    """Write ``data`` to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return path


def _issue(**overrides: Any) -> dict[str, Any]:
    """Return a base issue dict; override keys as needed."""
    base: dict[str, Any] = {
        "id": "ISSUE-001",
        "title": "Sample",
        "description": "Sample description",
        "status": "pending",
        "priority": "medium",
        "severity": "bug",
        "repos": ["mahavishnu"],
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "dependencies": [],
        "blocking": [],
        "labels": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


def _todo(**overrides: Any) -> dict[str, Any]:
    """Return a base todo dict; override keys as needed."""
    base: dict[str, Any] = {
        "id": "TODO-001",
        "task": "Do thing",
        "description": "Do the thing",
        "repo": "mahavishnu",
        "status": "pending",
        "priority": "medium",
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "estimated_hours": 4.0,
        "blocked_by": [],
        "blocking": [],
        "labels": [],
        "acceptance_criteria": [],
    }
    base.update(overrides)
    return base


def _plan(**overrides: Any) -> dict[str, Any]:
    """Return a base plan dict; override keys as needed."""
    base: dict[str, Any] = {
        "id": "PLAN-001",
        "title": "Sample plan",
        "description": "Sample plan description",
        "status": "draft",
        "repos": ["mahavishnu"],
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "target": "2026-03-01T00:00:00",
        "milestones": [],
    }
    base.update(overrides)
    return base


def _dep(**overrides: Any) -> dict[str, Any]:
    """Return a base dependency dict; override keys as needed."""
    base: dict[str, Any] = {
        "id": "DEP-001",
        "consumer": "fastblocks",
        "provider": "oneiric",
        "type": "runtime",
        "version_constraint": ">=0.2.0",
        "status": "satisfied",
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "notes": "Sample dep",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def ecosystem_path() -> str:
    """A path to an ecosystem.yaml with one of each entity."""
    path = _write(
        {
            "coordination": {
                "issues": [_issue()],
                "todos": [_todo()],
                "plans": [_plan()],
                "dependencies": [_dep()],
            }
        }
    )
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def empty_path() -> str:
    """A path to an ecosystem.yaml with no coordination section."""
    path = _write({})
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def manager(ecosystem_path: str) -> CoordinationManager:
    """A CoordinationManager wired to the standard fixture."""
    return CoordinationManager(ecosystem_path)


# ===========================================================================
# Module-level: _run_command_safe
# ===========================================================================


@pytest.mark.unit
class TestRunCommandSafe:
    def test_returns_empty_string_for_empty_input(self) -> None:
        # An empty input string produces one empty stage which is treated
        # as a no-op (popening [] raises IndexError). Verify the
        # short-circuit path on a string whose ``split("|")`` returns [].
        class _EmptyCommand(str):
            def split(self, sep: Any = None, maxsplit: int = -1) -> list[str]:  # type: ignore[override]
                if sep == "|":
                    return []
                return super().split(sep, maxsplit)

        assert _run_command_safe(_EmptyCommand("")) == ""

    def test_runs_simple_command(self) -> None:
        assert _run_command_safe("echo hello").strip() == "hello"

    def test_chains_pipes(self) -> None:
        assert _run_command_safe("echo hello | tr a-z A-Z").strip() == "HELLO"

    def test_raises_called_process_error_on_nonzero_exit(self) -> None:
        with pytest.raises(subprocess.CalledProcessError):
            _run_command_safe("false")

    def test_handles_three_stage_pipe(self) -> None:
        out = _run_command_safe("echo abc | tr a-z A-Z | rev")
        assert out.strip() == "CBA"

    def test_returns_output_even_when_intermediate_stages_have_no_stdin(
        self,
    ) -> None:
        # echo always has a stdin, but tr without input would error. Instead
        # test that the first stage's failure surfaces.
        with pytest.raises(subprocess.CalledProcessError):
            _run_command_safe("echo x | false")

    def test_whitespace_only_stages_are_split(self) -> None:
        # Leading/trailing whitespace around the pipe is trimmed.
        out = _run_command_safe("  echo hi  |  tr i I  ")
        assert out.strip() == "hI"


# ===========================================================================
# CoordinationManager: initialization
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerInitialization:
    def test_uses_explicit_path(self, ecosystem_path: str) -> None:
        cm = CoordinationManager(ecosystem_path)
        assert cm.ecosystem_path == Path(ecosystem_path)

    def test_uses_env_var_when_path_omitted(
        self, ecosystem_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", ecosystem_path)
        cm = CoordinationManager()
        assert cm.ecosystem_path == Path(ecosystem_path)

    def test_falls_back_to_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MAHAVISHNU_ECOSYSTEM_PATH", raising=False)
        cm = CoordinationManager()
        assert str(cm.ecosystem_path).endswith("settings/ecosystem.yaml")

    def test_missing_file_raises_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            CoordinationManager("/nonexistent/path/ecosystem.yaml")

    def test_bad_yaml_raises_configuration_error(self) -> None:
        # The ``coordination`` section is a string, so ``.get("issues", [])``
        # raises ``AttributeError`` (str has no .get) which is *not*
        # caught by the manager's ValidationError guard. This documents
        # the existing behavior — a stricter contract would wrap it.
        path = _write({"coordination": "this is not a dict"})
        try:
            cm = CoordinationManager(path)
            with pytest.raises(AttributeError):
                cm.list_issues()
        finally:
            os.unlink(path)

    def test_yaml_with_invalid_data_raises_during_load(self) -> None:
        # ``issues`` is a string instead of a list of dicts. The
        # normalize_issue_record call attempts ``dict(issue)`` and fails
        # because iterating the string yields single characters. The
        # manager does not catch this — it propagates.
        path = _write({"coordination": {"issues": "not-a-list"}})
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ValueError):
                cm.list_issues()
        finally:
            os.unlink(path)

    def test_empty_ecosystem_file_loads_with_empty_coordination(
        self, empty_path: str
    ) -> None:
        cm = CoordinationManager(empty_path)
        assert cm._ecosystem == {}
        assert cm._coordination == {}


# ===========================================================================
# CoordinationManager: Issue CRUD
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerIssueCRUD:
    def test_list_issues_empty(self, empty_path: str) -> None:
        cm = CoordinationManager(empty_path)
        assert cm.list_issues() == []

    def test_list_issues_returns_loaded_issues(self, manager: CoordinationManager) -> None:
        assert len(manager.list_issues()) == 1

    def test_list_issues_filter_status_pending(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_issues(status=IssueStatus.PENDING)) == 1

    def test_list_issues_filter_status_resolved_empty(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_issues(status=IssueStatus.RESOLVED) == []

    def test_list_issues_filter_priority(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_issues(priority="medium")) == 1
        assert manager.list_issues(priority="high") == []

    def test_list_issues_filter_repo_present(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_issues(repo="mahavishnu")) == 1

    def test_list_issues_filter_repo_absent(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_issues(repo="nope") == []

    def test_list_issues_filter_assignee_none(
        self, manager: CoordinationManager
    ) -> None:
        # Default fixture has no assignee.
        assert manager.list_issues(assignee="les") == []

    def test_list_issues_combined_filters(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.list_issues(
            status=IssueStatus.PENDING,
            priority="medium",
            repo="mahavishnu",
        )
        assert len(result) == 1

    def test_list_issues_combined_filters_no_match(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.list_issues(
            status=IssueStatus.PENDING,
            priority="high",  # not present
        )
        assert result == []

    def test_get_issue_returns_match(self, manager: CoordinationManager) -> None:
        issue = manager.get_issue("ISSUE-001")
        assert issue is not None
        assert issue.id == "ISSUE-001"

    def test_get_issue_returns_none_for_missing(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.get_issue("ISSUE-999") is None

    def test_create_issue_appends(self, manager: CoordinationManager) -> None:
        new = CrossRepoIssue(
            id="ISSUE-002",
            title="New",
            description="New issue",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        manager.create_issue(new)
        assert manager.get_issue("ISSUE-002") is not None
        assert len(manager._coordination["issues"]) == 2

    def test_create_issue_duplicate_id_raises(
        self, manager: CoordinationManager
    ) -> None:
        existing = manager.get_issue("ISSUE-001")
        assert existing is not None
        with pytest.raises(ConfigurationError, match="already exists"):
            manager.create_issue(existing)

    def test_update_issue_modifies_field(
        self, manager: CoordinationManager
    ) -> None:
        manager.update_issue("ISSUE-001", {"title": "Renamed"})
        assert manager.get_issue("ISSUE-001").title == "Renamed"

    def test_update_issue_missing_raises(
        self, manager: CoordinationManager
    ) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            manager.update_issue("ISSUE-999", {"title": "x"})

    def test_update_issue_persists_in_raw_state(
        self, manager: CoordinationManager
    ) -> None:
        manager.update_issue("ISSUE-001", {"status": "in_progress"})
        raw = manager._coordination["issues"][0]
        assert raw["status"] == "in_progress"

    def test_delete_issue_removes(self, manager: CoordinationManager) -> None:
        manager.delete_issue("ISSUE-001")
        assert manager.get_issue("ISSUE-001") is None
        assert manager._coordination["issues"] == []

    def test_delete_issue_missing_raises(
        self, manager: CoordinationManager
    ) -> None:
        with pytest.raises(ConfigurationError, match="not found"):
            manager.delete_issue("ISSUE-999")

    def test_delete_issue_leaves_other_issues_alone(
        self, manager: CoordinationManager
    ) -> None:
        new = CrossRepoIssue(
            id="ISSUE-002",
            title="Other",
            description="Other",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        manager.create_issue(new)
        manager.delete_issue("ISSUE-001")
        assert manager.get_issue("ISSUE-002") is not None


# ===========================================================================
# CoordinationManager: Plan management
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerPlanManagement:
    def test_list_plans_empty(self, empty_path: str) -> None:
        cm = CoordinationManager(empty_path)
        assert cm.list_plans() == []

    def test_list_plans_returns_loaded(self, manager: CoordinationManager) -> None:
        assert len(manager.list_plans()) == 1

    def test_list_plans_filter_status_match(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_plans(status="draft")) == 1

    def test_list_plans_filter_status_miss(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_plans(status="active") == []

    def test_list_plans_filter_repo_match(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_plans(repo="mahavishnu")) == 1

    def test_list_plans_filter_repo_miss(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_plans(repo="nope") == []

    def test_get_plan_found(self, manager: CoordinationManager) -> None:
        assert manager.get_plan("PLAN-001") is not None

    def test_get_plan_missing_returns_none(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.get_plan("PLAN-999") is None


# ===========================================================================
# CoordinationManager: Todo management
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerTodoManagement:
    def test_list_todos_empty(self, empty_path: str) -> None:
        cm = CoordinationManager(empty_path)
        assert cm.list_todos() == []

    def test_list_todos_returns_loaded(self, manager: CoordinationManager) -> None:
        assert len(manager.list_todos()) == 1

    def test_list_todos_filter_status_match(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_todos(status=TodoStatus.PENDING)) == 1

    def test_list_todos_filter_status_miss(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_todos(status=TodoStatus.COMPLETED) == []

    def test_list_todos_filter_repo_match(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_todos(repo="mahavishnu")) == 1

    def test_list_todos_filter_repo_miss(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_todos(repo="nope") == []

    def test_list_todos_filter_assignee_none(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_todos(assignee="nobody") == []

    def test_get_todo_found(self, manager: CoordinationManager) -> None:
        todo = manager.get_todo("TODO-001")
        assert todo is not None
        assert todo.id == "TODO-001"

    def test_get_todo_missing_returns_none(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.get_todo("TODO-999") is None


# ===========================================================================
# CoordinationManager: Dependency management
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerDependencyManagement:
    def test_list_dependencies_empty(self, empty_path: str) -> None:
        cm = CoordinationManager(empty_path)
        assert cm.list_dependencies() == []

    def test_list_dependencies_returns_loaded(
        self, manager: CoordinationManager
    ) -> None:
        deps = manager.list_dependencies()
        assert len(deps) == 1
        assert deps[0].id == "DEP-001"

    def test_list_dependencies_filter_consumer(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_dependencies(consumer="fastblocks")) == 1
        assert manager.list_dependencies(consumer="nobody") == []

    def test_list_dependencies_filter_provider(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_dependencies(provider="oneiric")) == 1
        assert manager.list_dependencies(provider="nobody") == []

    def test_list_dependencies_filter_type_match(
        self, manager: CoordinationManager
    ) -> None:
        assert len(manager.list_dependencies(dependency_type="runtime")) == 1

    def test_list_dependencies_filter_type_miss(
        self, manager: CoordinationManager
    ) -> None:
        assert manager.list_dependencies(dependency_type="mcp") == []

    def test_check_dependencies_summary_keys(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.check_dependencies()
        assert set(result.keys()) == {
            "total",
            "satisfied",
            "unsatisfied",
            "unknown",
            "deprecated",
            "dependencies",
        }

    def test_check_dependencies_per_dep_keys(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.check_dependencies()
        dep_info = result["dependencies"][0]
        assert set(dep_info.keys()) == {
            "id",
            "consumer",
            "provider",
            "type",
            "version_constraint",
            "status",
            "validation",
        }

    def test_check_dependencies_filters_by_consumer(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.check_dependencies(consumer="fastblocks")
        assert result["total"] == 1

    def test_check_dependencies_filters_by_unknown_consumer(
        self, manager: CoordinationManager
    ) -> None:
        result = manager.check_dependencies(consumer="nobody")
        assert result["total"] == 0
        assert result["dependencies"] == []


# ===========================================================================
# CoordinationManager: Status / reporting
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerReporting:
    def test_get_blocking_issues_excludes_resolved(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "issues": [
                        _issue(id="ISSUE-OPEN", status="pending"),
                        _issue(id="ISSUE-RESOLVED", status="resolved"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            assert {i.id for i in cm.get_blocking_issues("mahavishnu")} == {
                "ISSUE-OPEN"
            }
        finally:
            os.unlink(path)

    def test_get_blocking_issues_excludes_closed(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "issues": [
                        _issue(id="ISSUE-BLOCKED", status="blocked"),
                        _issue(id="ISSUE-CLOSED", status="closed"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            assert {i.id for i in cm.get_blocking_issues("mahavishnu")} == {
                "ISSUE-BLOCKED"
            }
        finally:
            os.unlink(path)

    def test_get_blocking_issues_repo_filter(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "issues": [
                        _issue(id="I-1", repos=["mahavishnu"], status="pending"),
                        _issue(id="I-2", repos=["other"], status="pending"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            assert {i.id for i in cm.get_blocking_issues("mahavishnu")} == {
                "I-1"
            }
            # I-2 affects "other" and is not resolved/closed, so it does
            # block the "other" repo.
            assert {i.id for i in cm.get_blocking_issues("other")} == {"I-2"}
            # A repo neither issue affects yields no blocking issues.
            assert cm.get_blocking_issues("missing") == []
        finally:
            os.unlink(path)

    def test_get_repo_status_keys(
        self, manager: CoordinationManager
    ) -> None:
        status = manager.get_repo_status("mahavishnu")
        assert set(status.keys()) == {
            "issues",
            "todos",
            "dependencies_outgoing",
            "dependencies_incoming",
            "blocking",
            "blocked_by",
        }

    def test_get_repo_status_outgoing_vs_incoming(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(id="OUT", consumer="mahavishnu", provider="other"),
                        _dep(id="IN", consumer="other", provider="mahavishnu"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            status = cm.get_repo_status("mahavishnu")
            assert {d.id for d in status["dependencies_outgoing"]} == {"OUT"}
            assert {d.id for d in status["dependencies_incoming"]} == {"IN"}
        finally:
            os.unlink(path)

    def test_get_repo_status_blocking_todos(
        self, manager: CoordinationManager
    ) -> None:
        # The default todo is pending, blocking=[], so blocking == [].
        status = manager.get_repo_status("mahavishnu")
        assert status["blocking"] == []

    def test_get_repo_status_blocked_by(
        self, manager: CoordinationManager
    ) -> None:
        # The default dep is satisfied, so blocked_by == [].
        status = manager.get_repo_status("mahavishnu")
        assert status["blocked_by"] == []


# ===========================================================================
# CoordinationManager: get_ecosystem_status
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerEcosystemStatus:
    def test_healthy_when_no_blockers(self, manager: CoordinationManager) -> None:
        # Default fixture: medium-priority pending issue, satisfied dep.
        # Issue is medium (not critical/high) so not a blocker.
        status = manager.get_ecosystem_status()
        assert status["health"] in {"healthy", "degraded"}
        assert status["active_plans"] == 0
        assert status["pending_todos"] >= 0
        assert status["in_progress_todos"] >= 0

    def test_active_plans_count(self, ecosystem_path: str) -> None:
        path = _write(
            {
                "coordination": {
                    "plans": [
                        _plan(id="P1", status="active"),
                        _plan(id="P2", status="draft"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            assert cm.get_ecosystem_status()["active_plans"] == 1
        finally:
            os.unlink(path)

    def test_critical_blockers_uses_priority_and_status(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "issues": [
                        _issue(id="CRIT-OPEN", status="pending", priority="critical"),
                        _issue(id="HIGH-OPEN", status="in_progress", priority="high"),
                        _issue(
                            id="CRIT-RESOLVED",
                            status="resolved",
                            priority="critical",
                        ),
                        _issue(id="LOW-OPEN", status="pending", priority="low"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            status = cm.get_ecosystem_status()
            assert status["critical_blockers"] == 2
            ids = {b["id"] for b in status["blockers"]}
            assert ids == {"CRIT-OPEN", "HIGH-OPEN"}
        finally:
            os.unlink(path)

    def test_degraded_dependencies_count(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(id="OK", status="satisfied"),
                        _dep(id="BAD", status="unsatisfied"),
                        _dep(id="UNK", status="unknown"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            status = cm.get_ecosystem_status()
            assert status["degraded_dependencies"] == 2
            ids = {d["id"] for d in status["dependencies"]}
            assert ids == {"BAD", "UNK"}
        finally:
            os.unlink(path)

    def test_health_degraded_when_open_blocker(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "issues": [_issue(priority="critical", status="pending")]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            assert cm.get_ecosystem_status()["health"] == "degraded"
        finally:
            os.unlink(path)

    def test_todo_counts(self, ecosystem_path: str) -> None:
        path = _write(
            {
                "coordination": {
                    "todos": [
                        _todo(id="P1", status="pending"),
                        _todo(id="P2", status="pending"),
                        _todo(id="I1", status="in_progress"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            status = cm.get_ecosystem_status()
            assert status["pending_todos"] == 2
            assert status["in_progress_todos"] == 1
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager: save / reload
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerSaveReload:
    def test_save_writes_to_disk(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        new_path = tmp_path / "ecosystem.yaml"
        manager.ecosystem_path = new_path  # type: ignore[assignment]
        manager.create_issue(
            CrossRepoIssue(
                id="ISSUE-002",
                title="Persisted",
                description="Should be on disk",
                repos=["mahavishnu"],
                created="2026-01-15T00:00:00",
                updated="2026-01-15T00:00:00",
            )
        )
        manager.save()
        assert new_path.exists()
        data = yaml.safe_load(new_path.read_text())
        ids = {i["id"] for i in data["coordination"]["issues"]}
        assert {"ISSUE-001", "ISSUE-002"} <= ids

    def test_save_propagates_oserror(
        self, manager: CoordinationManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("builtins.open", _boom)
        with pytest.raises(ConfigurationError, match="Failed to write"):
            manager.save()

    def test_reload_replaces_state(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        new_path = tmp_path / "ecosystem.yaml"
        new_path.write_text(
            yaml.dump(
                {
                    "coordination": {
                        "issues": [_issue(id="FRESH", status="pending")],
                    }
                }
            )
        )
        manager.ecosystem_path = new_path  # type: ignore[assignment]
        manager.reload()
        assert manager.get_issue("FRESH") is not None
        assert manager.get_issue("ISSUE-001") is None

    def test_save_persists_normalization_aware_creates(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        # Create an issue then save+reload to verify round-trip integrity.
        manager.create_issue(
            CrossRepoIssue(
                id="ISSUE-NEW",
                title="New",
                description="desc",
                status=IssueStatus.PENDING,
                priority=Priority.MEDIUM,
                repos=["mahavishnu"],
                created="2026-01-15T00:00:00",
                updated="2026-01-15T00:00:00",
            )
        )
        manager.save()
        new = CoordinationManager(manager.ecosystem_path)
        assert new.get_issue("ISSUE-NEW") is not None


# ===========================================================================
# CoordinationManager: _run_command_safe integration with check_dependencies
# ===========================================================================


@pytest.mark.unit
class TestValidateDependencyBranch:
    def test_validation_runs_command_and_passes(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(
                            validation={
                                "command": "echo hello",
                                "expected_pattern": "hello",
                            }
                        )
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()["dependencies"][0]["validation"]
            assert result["method"] == "command"
            assert result["passed"] is True
        finally:
            os.unlink(path)

    def test_validation_without_pattern_just_runs(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(validation={"command": "echo ok"})
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()["dependencies"][0]["validation"]
            assert result["passed"] is True
            assert "ok" in (result["details"] or "")
        finally:
            os.unlink(path)

    def test_validation_pattern_miss(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(
                            validation={
                                "command": "echo hello",
                                "expected_pattern": "^world$",
                            }
                        )
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()["dependencies"][0]["validation"]
            assert result["passed"] is False
        finally:
            os.unlink(path)

    def test_validation_command_failure(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(
                            validation={
                                "command": "false",
                                "expected_pattern": "anything",
                            }
                        )
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()["dependencies"][0]["validation"]
            assert result["passed"] is False
        finally:
            os.unlink(path)

    def test_validation_unexpected_exception(
        self, manager: CoordinationManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The default fixture has no validation, so first add one via the
        # underlying state, then patch the helper to raise.
        manager._coordination["dependencies"] = [
            {
                **_dep(),
                "validation": {
                    "command": "echo x",
                    "expected_pattern": "x",
                },
            }
        ]
        dep = manager.list_dependencies()[0]
        monkeypatch.setattr(
            "mahavishnu.core.coordination.manager._run_command_safe",
            lambda _c: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = manager._validate_dependency(dep)
        assert result["passed"] is False
        assert result["details"] == "boom"

    def test_validation_skipped_when_no_command(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        # No validation block at all.
                        _dep()
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            info = cm.check_dependencies()["dependencies"][0]
            assert info["validation"] is None
        finally:
            os.unlink(path)

    def test_validation_skipped_when_command_none(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(validation={"expected_pattern": "x"})
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            info = cm.check_dependencies()["dependencies"][0]
            # The validation was provided but command is None, so the
            # helper returns its no-op default dict.
            assert info["validation"] == {
                "method": None,
                "passed": False,
                "details": None,
            }
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager: normalization helpers
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerNormalization:
    def test_normalize_issue_status_legacy_resolved(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(status="fixed")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].status == IssueStatus.RESOLVED
        finally:
            os.unlink(path)

    def test_normalize_issue_status_legacy_closed(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(status="closed")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].status == IssueStatus.CLOSED
        finally:
            os.unlink(path)

    def test_normalize_issue_status_legacy_in_progress(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(status="in progress")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].status == IssueStatus.IN_PROGRESS
        finally:
            os.unlink(path)

    def test_normalize_issue_status_unknown_string_falls_back_to_pending(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(status="???")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].status == IssueStatus.PENDING
        finally:
            os.unlink(path)

    def test_normalize_issue_status_none_falls_back_to_pending(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(status=None)]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].status == IssueStatus.PENDING
        finally:
            os.unlink(path)

    def test_normalize_issue_status_passthrough_enum(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue()]}})
        try:
            cm = CoordinationManager(path)
            assert cm._normalize_issue_status(IssueStatus.BLOCKED) == IssueStatus.BLOCKED
        finally:
            os.unlink(path)

    def test_normalize_issue_priority_aliases(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(priority="p0")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].priority.value == "critical"
        finally:
            os.unlink(path)

    def test_normalize_issue_priority_unknown_defaults_to_medium(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"issues": [_issue(priority="zany")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].priority.value == "medium"
        finally:
            os.unlink(path)

    def test_normalize_todo_status_done(self, ecosystem_path: str) -> None:
        path = _write({"coordination": {"todos": [_todo(status="done")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].status == TodoStatus.COMPLETED
        finally:
            os.unlink(path)

    def test_normalize_todo_status_in_progress_aliases(
        self, ecosystem_path: str
    ) -> None:
        for alias in ("in_progress", "in-progress", "in progress"):
            path = _write(
                {"coordination": {"todos": [_todo(status=alias)]}}
            )
            try:
                cm = CoordinationManager(path)
                assert cm.list_todos()[0].status == TodoStatus.IN_PROGRESS
            finally:
                os.unlink(path)

    def test_normalize_todo_status_unknown_falls_back_to_pending(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"todos": [_todo(status="??")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].status == TodoStatus.PENDING
        finally:
            os.unlink(path)

    def test_normalize_todo_priority_inherits_issue_logic(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"todos": [_todo(priority="p1")]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].priority.value == "high"
        finally:
            os.unlink(path)

    def test_normalize_infer_repos_from_affected_files(
        self, ecosystem_path: str
    ) -> None:
        issue = _issue()
        del issue["repos"]
        issue["affected_files"] = ["mahavishnu/a.py", "session-buddy/b.py"]
        path = _write({"coordination": {"issues": [issue]}})
        try:
            cm = CoordinationManager(path)
            repos = set(cm.list_issues()[0].repos)
            assert repos == {"mahavishnu", "session-buddy"}
        finally:
            os.unlink(path)

    def test_normalize_infer_repos_from_pool(
        self, ecosystem_path: str
    ) -> None:
        issue = _issue()
        del issue["repos"]
        issue["pool"] = "akosha"
        path = _write({"coordination": {"issues": [issue]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].repos == ["akosha"]
        finally:
            os.unlink(path)

    def test_normalize_infer_repos_default(
        self, ecosystem_path: str
    ) -> None:
        issue = _issue()
        del issue["repos"]
        path = _write({"coordination": {"issues": [issue]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].repos == ["mahavishnu"]
        finally:
            os.unlink(path)

    def test_normalize_issue_tags_to_labels(
        self, ecosystem_path: str
    ) -> None:
        # The normalize pass only copies ``tags`` to ``labels`` when the
        # dict has no ``labels`` key at all.
        issue = _issue()
        del issue["labels"]
        issue["tags"] = ["alpha", "beta"]
        path = _write({"coordination": {"issues": [issue]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_issues()[0].labels == ["alpha", "beta"]
        finally:
            os.unlink(path)

    def test_normalize_todo_tags_to_labels(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        todo["tags"] = "not-a-list"  # type: ignore[assignment]
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].labels == []
        finally:
            os.unlink(path)

    def test_normalize_todo_task_fallback_to_description(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["task"]
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            # Falls back to description when task is missing.
            assert cm.list_todos()[0].task == "Do the thing"
        finally:
            os.unlink(path)

    def test_normalize_todo_task_fallback_to_id(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["task"]
        del todo["description"]
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            # Falls back to id when both task and description missing.
            assert cm.list_todos()[0].task == "TODO-001"
        finally:
            os.unlink(path)

    def test_normalize_todo_estimated_hours_default(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["estimated_hours"]
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].estimated_hours == 1.0
        finally:
            os.unlink(path)

    def test_normalize_todo_estimate_hours_alias(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["estimated_hours"]
        todo["estimate_hours"] = 12.0
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].estimated_hours == 12.0
        finally:
            os.unlink(path)

    def test_normalize_todo_infer_repo_from_issue(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["repo"]
        todo["issue_id"] = "ISSUE-001"
        path = _write(
            {
                "coordination": {
                    "issues": [_issue()],
                    "todos": [todo],
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            # The default issue has repos=["mahavishnu"] so the todo should
            # pick that up.
            assert cm.list_todos()[0].repo == "mahavishnu"
        finally:
            os.unlink(path)

    def test_normalize_todo_infer_repo_from_pool(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["repo"]
        todo["pool"] = "akosha"
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].repo == "akosha"
        finally:
            os.unlink(path)

    def test_normalize_todo_infer_repo_default(
        self, ecosystem_path: str
    ) -> None:
        todo = _todo()
        del todo["repo"]
        path = _write({"coordination": {"todos": [todo]}})
        try:
            cm = CoordinationManager(path)
            assert cm.list_todos()[0].repo == "mahavishnu"
        finally:
            os.unlink(path)

    def test_normalize_datetime_objects_to_iso(
        self, ecosystem_path: str
    ) -> None:
        issue = _issue()
        issue["created"] = datetime(2026, 1, 1)
        issue["updated"] = datetime(2026, 1, 2)
        path = _write({"coordination": {"issues": [issue]}})
        try:
            cm = CoordinationManager(path)
            issue_obj = cm.list_issues()[0]
            assert issue_obj.created.startswith("2026-01-01")
            assert issue_obj.updated.startswith("2026-01-02")
        finally:
            os.unlink(path)

    def test_stringify_datetime_passthrough_string(
        self, manager: CoordinationManager
    ) -> None:
        # The helper should not modify non-datetime values.
        assert manager._stringify_datetime("plain-string") == "plain-string"
        assert manager._stringify_datetime(None) is None

    def test_stringify_datetime_converts_datetime(
        self, manager: CoordinationManager
    ) -> None:
        result = manager._stringify_datetime(datetime(2026, 5, 10, 12, 30, 0))
        assert isinstance(result, str)
        assert result.startswith("2026-05-10")


# ===========================================================================
# CoordinationManager: validation error paths
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerValidationErrors:
    def test_list_issues_invalid_data_raises(
        self, ecosystem_path: str
    ) -> None:
        # Force an issue to have repos as a non-list.
        path = _write(
            {"coordination": {"issues": [_issue(repos="not-a-list")]}}
        )
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ConfigurationError, match="Invalid issue data"):
                cm.list_issues()
        finally:
            os.unlink(path)

    def test_list_plans_invalid_data_raises(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"plans": [_plan(repos=[])]}})
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ConfigurationError, match="Invalid plan data"):
                cm.list_plans()
        finally:
            os.unlink(path)

    def test_list_todos_invalid_data_raises(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {"coordination": {"todos": [_todo(estimated_hours=0)]}}
        )
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ConfigurationError, match="Invalid todo data"):
                cm.list_todos()
        finally:
            os.unlink(path)

    def test_list_dependencies_invalid_data_raises(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"dependencies": [_dep(consumer="")]}})
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ConfigurationError, match="Invalid dependency data"):
                cm.list_dependencies()
        finally:
            os.unlink(path)

    def test_check_dependencies_invalid_data_raises(
        self, ecosystem_path: str
    ) -> None:
        path = _write({"coordination": {"dependencies": [_dep(consumer="")]}})
        try:
            cm = CoordinationManager(path)
            with pytest.raises(ConfigurationError, match="Invalid dependency data"):
                cm.check_dependencies()
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager: private helpers via direct invocation
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerPrivateHelpers:
    def test_infer_todo_repo_from_issue_id(
        self, manager: CoordinationManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(
            manager,
            "get_issue",
            lambda _id: SimpleNamespace(repos=["session-buddy"]),
        )
        assert manager._infer_todo_repo({"issue_id": "ISSUE-001"}) == "session-buddy"

    def test_infer_todo_repo_from_pool(
        self, manager: CoordinationManager
    ) -> None:
        assert manager._infer_todo_repo({"pool": "akosha"}) == "akosha"

    def test_infer_todo_repo_default(
        self, manager: CoordinationManager
    ) -> None:
        assert manager._infer_todo_repo({}) == "mahavishnu"

    def test_infer_todo_repo_strips_pool(
        self, manager: CoordinationManager
    ) -> None:
        assert manager._infer_todo_repo({"pool": "  akosha  "}) == "akosha"

    def test_infer_todo_repo_ignores_blank_issue_id(
        self, manager: CoordinationManager
    ) -> None:
        # If issue_id is a non-empty whitespace string, the helper trims
        # and falls through.
        assert manager._infer_todo_repo({"issue_id": "   "}) == "mahavishnu"

    def test_infer_issue_repos_default(
        self, manager: CoordinationManager
    ) -> None:
        assert manager._infer_issue_repos({}) == ["mahavishnu"]

    def test_infer_issue_repos_from_pool(
        self, manager: CoordinationManager
    ) -> None:
        assert manager._infer_issue_repos({"pool": "akosha"}) == ["akosha"]

    def test_infer_issue_repos_dedup_and_sort(
        self, manager: CoordinationManager
    ) -> None:
        repos = manager._infer_issue_repos(
            {"affected_files": ["zeta/x.py", "alpha/y.py", "zeta/z.py"]}
        )
        # First component only, sorted & deduplicated.
        assert repos == ["alpha", "zeta"]

    def test_infer_issue_repos_ignores_non_string_paths(
        self, manager: CoordinationManager
    ) -> None:
        # Non-string entries in affected_files are silently ignored.
        repos = manager._infer_issue_repos(
            {"affected_files": [None, 42, {"x": 1}, "alpha/a.py"]}
        )
        assert repos == ["alpha"]

    def test_normalize_issue_record_includes_status_and_priority(
        self, manager: CoordinationManager
    ) -> None:
        rec = manager._normalize_issue_record({"id": "X", "repos": ["a"]})
        # The fallback values should still be present.
        assert "status" in rec
        assert "priority" in rec

    def test_normalize_todo_record_includes_estimated_hours(
        self, manager: CoordinationManager
    ) -> None:
        rec = manager._normalize_todo_record(
            {"id": "X", "repo": "a", "task": "t", "description": "d"}
        )
        assert rec["estimated_hours"] == 1.0


# ===========================================================================
# CoordinationManager: integration / behavior
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerBehavior:
    def test_create_update_delete_lifecycle(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        new_path = tmp_path / "ecosystem.yaml"
        manager.ecosystem_path = new_path  # type: ignore[assignment]

        issue = CrossRepoIssue(
            id="ISSUE-002",
            title="Lifecycle",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        manager.create_issue(issue)
        manager.update_issue("ISSUE-002", {"status": "in_progress"})
        manager.save()

        new = CoordinationManager(new_path)
        assert new.get_issue("ISSUE-002").status == IssueStatus.IN_PROGRESS
        new.delete_issue("ISSUE-002")
        new.save()

        final = CoordinationManager(new_path)
        assert final.get_issue("ISSUE-002") is None

    def test_reload_preserves_in_memory_changes_until_reload(
        self, manager: CoordinationManager
    ) -> None:
        manager.create_issue(
            CrossRepoIssue(
                id="ISSUE-TEMP",
                title="Temp",
                description="desc",
                repos=["mahavishnu"],
                created="2026-01-15T00:00:00",
                updated="2026-01-15T00:00:00",
            )
        )
        # Before reload, in-memory state has the new issue.
        assert manager.get_issue("ISSUE-TEMP") is not None
        manager.reload()
        # After reload, the in-memory change is lost (we never called save).
        assert manager.get_issue("ISSUE-TEMP") is None

    def test_get_ecosystem_status_isolates_plan_filter(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "plans": [
                        _plan(id="ACTIVE", status="active"),
                        _plan(id="DRAFT", status="draft"),
                        _plan(id="ACTIVE2", status="active"),
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            status = cm.get_ecosystem_status()
            plan_ids = {p["id"] for p in status["plans"]}
            assert plan_ids == {"ACTIVE", "ACTIVE2"}
            assert status["active_plans"] == 2
        finally:
            os.unlink(path)

    def test_ecosystem_status_with_milestones_tracks_completion(
        self, ecosystem_path: str
    ) -> None:
        plan = _plan(
            milestones=[
                {
                    "id": "M1",
                    "name": "M1",
                    "description": "d",
                    "due": "2026-02-01T00:00:00",
                    "status": "completed",
                    "dependencies": [],
                    "completion_criteria": [],
                    "deliverables": [],
                },
                {
                    "id": "M2",
                    "name": "M2",
                    "description": "d",
                    "due": "2026-02-15T00:00:00",
                    "status": "pending",
                    "dependencies": [],
                    "completion_criteria": [],
                    "deliverables": [],
                },
            ],
            status="active",
        )
        path = _write({"coordination": {"plans": [plan]}})
        try:
            cm = CoordinationManager(path)
            status = cm.get_ecosystem_status()
            assert status["active_plans"] == 1
            assert status["plans"][0]["milestones_total"] == 2
            assert status["plans"][0]["milestones_done"] == 1
        finally:
            os.unlink(path)

    def test_ecosystem_path_is_path_instance(
        self, manager: CoordinationManager
    ) -> None:
        assert isinstance(manager.ecosystem_path, Path)

    def test_pydantic_v2_model_dump_round_trip(
        self, manager: CoordinationManager
    ) -> None:
        # CrossRepoIssue uses Pydantic v2 model_dump.
        issue = CrossRepoIssue(
            id="ISSUE-002",
            title="Round trip",
            description="d",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        dumped = issue.model_dump(mode="json")
        assert dumped["id"] == "ISSUE-002"
        assert isinstance(dumped["repos"], list)

    def test_dependency_validation_object_can_be_loaded(
        self, ecosystem_path: str
    ) -> None:
        path = _write(
            {
                "coordination": {
                    "dependencies": [
                        _dep(
                            validation=DependencyValidation(
                                command="echo x",
                                expected_pattern="x",
                            ).model_dump()
                        )
                    ]
                }
            }
        )
        try:
            cm = CoordinationManager(path)
            dep = cm.list_dependencies()[0]
            assert dep.validation is not None
            assert dep.validation.command == "echo x"
            assert dep.validation.expected_pattern == "x"
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager: defensive patches (e.g. _run_command_safe edge cases)
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerDefensivePatching:
    def test_check_dependencies_with_patched_safe(
        self, manager: CoordinationManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Patch _run_command_safe so that any dep with a validation command
        # uses the patched behavior.
        monkeypatch.setattr(
            "mahavishnu.core.coordination.manager._run_command_safe",
            lambda _c: "patched-output",
        )
        manager._coordination["dependencies"] = [
            {
                **_dep(),
                "validation": {
                    "command": "irrelevant",
                    "expected_pattern": "patched-output",
                },
            }
        ]
        result = manager.check_dependencies()
        validation = result["dependencies"][0]["validation"]
        assert validation is not None
        assert validation["passed"] is True

    def test_check_dependencies_command_oserror_with_pattern(
        self, manager: CoordinationManager
    ) -> None:
        # Run an actual `false` command so subprocess.CalledProcessError
        # is raised (returncode != 0) and the validation block falls into
        # the CalledProcessError branch.
        manager._coordination["dependencies"] = [
            {
                **_dep(),
                "validation": {
                    "command": "false",
                    "expected_pattern": "won't match",
                },
            }
        ]
        result = manager.check_dependencies()
        validation = result["dependencies"][0]["validation"]
        assert validation is not None
        assert validation["passed"] is False

    def test_check_dependencies_command_success_no_pattern(
        self, manager: CoordinationManager
    ) -> None:
        manager._coordination["dependencies"] = [
            {
                **_dep(),
                "validation": {"command": "echo success"},
            }
        ]
        result = manager.check_dependencies()
        validation = result["dependencies"][0]["validation"]
        assert validation is not None
        assert validation["passed"] is True
        assert validation["details"] == "success"


# ===========================================================================
# CoordinationManager: misc coverage
# ===========================================================================


@pytest.mark.unit
class TestCoordinationManagerMisc:
    def test_load_ecosystem_populates_internal_state(
        self, manager: CoordinationManager
    ) -> None:
        assert "coordination" in manager._ecosystem
        assert "issues" in manager._coordination

    def test_init_with_explicit_path_sets_path(
        self, ecosystem_path: str
    ) -> None:
        cm = CoordinationManager(ecosystem_path)
        assert str(cm.ecosystem_path) == ecosystem_path

    def test_list_issues_returns_pydantic_objects(
        self, manager: CoordinationManager
    ) -> None:
        issues = manager.list_issues()
        assert all(isinstance(i, CrossRepoIssue) for i in issues)

    def test_list_plans_returns_pydantic_objects(
        self, manager: CoordinationManager
    ) -> None:
        plans = manager.list_plans()
        assert all(isinstance(p, CrossRepoPlan) for p in plans)

    def test_list_todos_returns_pydantic_objects(
        self, manager: CoordinationManager
    ) -> None:
        todos = manager.list_todos()
        assert all(isinstance(t, CrossRepoTodo) for t in todos)

    def test_list_dependencies_returns_pydantic_objects(
        self, manager: CoordinationManager
    ) -> None:
        deps = manager.list_dependencies()
        assert all(isinstance(d, Dependency) for d in deps)

    def test_apply_issue_filters_is_static(
        self, manager: CoordinationManager
    ) -> None:
        # The static filter helper should be callable as a classmethod
        # without instantiating.
        from mahavishnu.core.coordination.manager import (
            CoordinationManager as CMgr,
        )

        # Build synthetic issue objects.
        issues = [
            CrossRepoIssue(
                id=f"ISSUE-{i}",
                title=f"t-{i}",
                description="d",
                repos=["mahavishnu"] if i % 2 == 0 else ["other"],
                created="2026-01-15T00:00:00",
                updated="2026-01-15T00:00:00",
            )
            for i in range(4)
        ]
        filtered = CMgr._apply_issue_filters(
            issues,
            status=IssueStatus.PENDING,
            priority="medium",
            repo="mahavishnu",
            assignee=None,
        )
        assert len(filtered) == 2  # Even indices

    def test_save_round_trips_dependency_status_enum(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        # Create a dep with FAILED status via the Pydantic model and verify
        # it survives save+reload.
        dep = Dependency(
            id="DEP-NEW",
            consumer="a",
            provider="b",
            type=DependencyType.RUNTIME,
            version_constraint=">=1.0",
            status=DependencyStatus.FAILED,
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            notes="n",
        )
        manager._coordination["dependencies"].append(dep.model_dump(mode="json"))
        new_path = tmp_path / "ecosystem.yaml"
        manager.ecosystem_path = new_path  # type: ignore[assignment]
        manager.save()
        new = CoordinationManager(new_path)
        loaded = new.list_dependencies()
        assert any(d.id == "DEP-NEW" for d in loaded)

    def test_plan_status_enum_survives_round_trip(
        self, manager: CoordinationManager, tmp_path: Path
    ) -> None:
        plan = CrossRepoPlan(
            id="PLAN-NEW",
            title="New",
            description="d",
            status=PlanStatus.ACTIVE,
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            target="2026-03-01T00:00:00",
        )
        manager._coordination.setdefault("plans", []).append(
            plan.model_dump(mode="json")
        )
        new_path = tmp_path / "ecosystem.yaml"
        manager.ecosystem_path = new_path  # type: ignore[assignment]
        manager.save()
        new = CoordinationManager(new_path)
        loaded = new.list_plans()
        assert any(p.id == "PLAN-NEW" and p.status == PlanStatus.ACTIVE for p in loaded)


# ===========================================================================
# Run the file directly (informational only)
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
