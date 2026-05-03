"""
Comprehensive tests for mahavishnu.core.coordination modules.

Covers executor.py, manager.py, and memory.py with full mocking
of external dependencies.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from mahavishnu.core.coordination.executor import CoordinationExecutor
from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.memory import (
    CoordinationManagerWithMemory,
    CoordinationMemory,
)
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyStatus,
    DependencyType,
    Milestone,
    Priority,
    TodoStatus,
)
from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.status import IssueStatus

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_ecosystem_yaml(
    issues: list[dict] | None = None,
    todos: list[dict] | None = None,
    plans: list[dict] | None = None,
    dependencies: list[dict] | None = None,
) -> dict:
    """Build an ecosystem.yaml dict and return it."""
    coordination: dict[str, Any] = {}
    if issues is not None:
        coordination["issues"] = issues
    if todos is not None:
        coordination["todos"] = todos
    if plans is not None:
        coordination["plans"] = plans
    if dependencies is not None:
        coordination["dependencies"] = dependencies
    return {"coordination": coordination}


def _write_ecosystem(data: dict) -> str:
    """Write ecosystem data to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        yaml.dump(data, f, default_flow_style=False)
    return path


def _sample_issue_dict(**overrides: Any) -> dict:
    base = {
        "id": "ISSUE-001",
        "title": "Test issue",
        "description": "A test issue for coordination",
        "status": "pending",
        "priority": "medium",
        "severity": "bug",
        "repos": ["mahavishnu", "session-buddy"],
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "dependencies": [],
        "blocking": [],
        "labels": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


def _sample_todo_dict(**overrides: Any) -> dict:
    base = {
        "id": "TODO-001",
        "task": "Implement feature",
        "description": "Implement the thing",
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


def _sample_plan_dict(**overrides: Any) -> dict:
    base = {
        "id": "PLAN-001",
        "title": "Test plan",
        "description": "A test plan",
        "status": "draft",
        "repos": ["mahavishnu"],
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "target": "2026-03-01T00:00:00",
        "milestones": [],
    }
    base.update(overrides)
    return base


def _sample_dependency_dict(**overrides: Any) -> dict:
    base = {
        "id": "DEP-001",
        "consumer": "fastblocks",
        "provider": "oneiric",
        "type": "runtime",
        "version_constraint": ">=0.2.0",
        "status": "satisfied",
        "created": "2026-01-15T00:00:00",
        "updated": "2026-01-15T00:00:00",
        "notes": "FastBlocks requires Oneiric",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def ecosystem_path():
    """Create a temp ecosystem.yaml with sample data and return the path."""
    data = _make_ecosystem_yaml(
        issues=[_sample_issue_dict()],
        todos=[_sample_todo_dict()],
        plans=[_sample_plan_dict()],
        dependencies=[_sample_dependency_dict()],
    )
    path = _write_ecosystem(data)
    yield path
    os.unlink(path)


@pytest.fixture
def mgr(ecosystem_path):
    """CoordinationManager wired to a temp ecosystem.yaml."""
    return CoordinationManager(ecosystem_path)


@pytest.fixture
def empty_ecosystem_path():
    """Create a temp ecosystem.yaml with empty coordination data."""
    data = _make_ecosystem_yaml()
    path = _write_ecosystem(data)
    yield path
    os.unlink(path)


# ===========================================================================
# Coordination Models (preserved from original test file)
# ===========================================================================


class TestCoordinationModels:
    """Test suite for coordination data models."""

    def test_cross_repo_issue_validation(self):
        # Valid issue
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test",
            description="Test issue",
            status=IssueStatus.PENDING,
            priority=Priority.HIGH,
            severity="bug",
            repos=["mahavishnu"],
            created="2026-01-31T00:00:00",
            updated="2026-01-31T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )
        assert issue.id == "ISSUE-001"

        # Invalid: no repos
        with pytest.raises(ValueError):
            CrossRepoIssue(
                id="ISSUE-002",
                title="Test",
                description="Test",
                status=IssueStatus.PENDING,
                priority=Priority.MEDIUM,
                severity="feature",
                repos=[],
                created="2026-01-31T00:00:00",
                updated="2026-01-31T00:00:00",
                dependencies=[],
                blocking=[],
                labels=[],
                metadata={},
            )

    def test_cross_repo_todo_validation(self):
        # Valid todo
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Test task",
            description="A test todo",
            repo="mahavishnu",
            status=TodoStatus.PENDING,
            priority=Priority.MEDIUM,
            created="2026-01-31T00:00:00",
            updated="2026-01-31T00:00:00",
            estimated_hours=8.0,
            blocked_by=[],
            blocking=[],
            labels=[],
            acceptance_criteria=[],
        )
        assert todo.estimated_hours == 8.0

        # Invalid: negative hours
        with pytest.raises(ValueError):
            CrossRepoTodo(
                id="TODO-002",
                task="Test",
                description="Test",
                repo="mahavishnu",
                status=TodoStatus.PENDING,
                priority=Priority.MEDIUM,
                created="2026-01-31T00:00:00",
                updated="2026-01-31T00:00:00",
                estimated_hours=-1.0,
                blocked_by=[],
                blocking=[],
                labels=[],
                acceptance_criteria=[],
            )

    def test_dependency_model(self):
        dep = Dependency(
            id="DEP-001",
            consumer="fastblocks",
            provider="oneiric",
            type=DependencyType.RUNTIME,
            version_constraint=">=0.2.0",
            status=DependencyStatus.SATISFIED,
            created="2026-01-15T00:00:00",
            updated="2026-01-30T00:00:00",
            notes="Test dependency",
        )
        assert dep.consumer == "fastblocks"
        assert dep.type == DependencyType.RUNTIME


# ===========================================================================
# CoordinationManager - Initialization
# ===========================================================================


class TestCoordinationManagerInit:
    def test_init_loads_file(self, ecosystem_path):
        cm = CoordinationManager(ecosystem_path)
        assert cm.ecosystem_path == Path(ecosystem_path)
        assert cm._coordination is not None

    def test_init_uses_env_var(self, ecosystem_path, monkeypatch):
        monkeypatch.setenv("MAHAVISHNU_ECOSYSTEM_PATH", ecosystem_path)
        cm = CoordinationManager()
        assert cm.ecosystem_path == Path(ecosystem_path)

    def test_init_missing_file_raises(self):
        with pytest.raises(ConfigurationError, match="not found"):
            CoordinationManager("/nonexistent/path/ecosystem.yaml")

    def test_init_bad_yaml_raises(self):
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(":\n  - bad\n    yaml:\n")
        try:
            with pytest.raises(ConfigurationError, match="Failed to parse"):
                CoordinationManager(path)
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager - Issue CRUD
# ===========================================================================


class TestCoordinationManagerIssues:
    def test_load_ecosystem(self, ecosystem_path):
        mgr = CoordinationManager(ecosystem_path)
        assert mgr._ecosystem is not None
        assert "coordination" in mgr._ecosystem

    def test_list_issues_all(self, mgr):
        issues = mgr.list_issues()
        assert len(issues) == 1
        assert issues[0].id == "ISSUE-001"

    def test_list_issues_with_filters(self, mgr):
        pending_issues = mgr.list_issues(status=IssueStatus.PENDING)
        assert len(pending_issues) == 1
        resolved_issues = mgr.list_issues(status=IssueStatus.RESOLVED)
        assert len(resolved_issues) == 0
        mahavishnu_issues = mgr.list_issues(repo="mahavishnu")
        assert len(mahavishnu_issues) == 1
        other_issues = mgr.list_issues(repo="crackerjack")
        assert len(other_issues) == 0

    def test_list_issues_filter_priority(self, mgr):
        issues = mgr.list_issues(priority="medium")
        assert len(issues) == 1
        issues = mgr.list_issues(priority="high")
        assert len(issues) == 0

    def test_list_issues_filter_assignee(self, mgr):
        issues = mgr.list_issues(assignee="les")
        assert len(issues) == 0

    def test_get_issue_found(self, mgr):
        issue = mgr.get_issue("ISSUE-001")
        assert issue is not None
        assert issue.title == "Test issue"

    def test_get_issue_not_found(self, mgr):
        assert mgr.get_issue("ISSUE-999") is None

    def test_create_issue(self, mgr):
        new_issue = CrossRepoIssue(
            id="ISSUE-002",
            title="New Issue",
            description="A new test issue",
            status=IssueStatus.PENDING,
            priority=Priority.MEDIUM,
            severity="feature",
            repos=["crackerjack"],
            created="2026-01-31T00:00:00",
            updated="2026-01-31T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )
        mgr.create_issue(new_issue)
        mgr.save()
        mgr.reload()
        issues = mgr.list_issues()
        assert len(issues) == 2
        new_issue = mgr.get_issue("ISSUE-002")
        assert new_issue is not None
        assert new_issue.title == "New Issue"

    def test_create_issue_duplicate_raises(self, mgr):
        issue = mgr.get_issue("ISSUE-001")
        with pytest.raises(ConfigurationError, match="already exists"):
            mgr.create_issue(issue)

    def test_update_issue(self, mgr):
        mgr.update_issue("ISSUE-001", {"status": "in_progress"})
        mgr.save()
        mgr.reload()
        issue = mgr.get_issue("ISSUE-001")
        assert issue.status == IssueStatus.IN_PROGRESS

    def test_update_issue_not_found(self, mgr):
        with pytest.raises(ConfigurationError, match="not found"):
            mgr.update_issue("ISSUE-999", {"title": "x"})

    def test_delete_issue(self, mgr):
        mgr.delete_issue("ISSUE-001")
        mgr.save()
        mgr.reload()
        issues = mgr.list_issues()
        assert len(issues) == 0

    def test_delete_issue_not_found(self, mgr):
        with pytest.raises(ConfigurationError, match="not found"):
            mgr.delete_issue("ISSUE-999")


# ===========================================================================
# CoordinationManager - Plan Management
# ===========================================================================


class TestCoordinationManagerPlans:
    def test_list_plans_all(self, mgr):
        plans = mgr.list_plans()
        assert len(plans) == 1
        assert plans[0].id == "PLAN-001"

    def test_list_plans_filter_status(self, mgr):
        plans = mgr.list_plans(status="draft")
        assert len(plans) == 1
        plans = mgr.list_plans(status="active")
        assert len(plans) == 0

    def test_list_plans_filter_repo(self, mgr):
        plans = mgr.list_plans(repo="mahavishnu")
        assert len(plans) == 1
        plans = mgr.list_plans(repo="other")
        assert len(plans) == 0

    def test_get_plan_found(self, mgr):
        plan = mgr.get_plan("PLAN-001")
        assert plan is not None
        assert plan.title == "Test plan"

    def test_get_plan_not_found(self, mgr):
        assert mgr.get_plan("PLAN-999") is None


# ===========================================================================
# CoordinationManager - Todo Management
# ===========================================================================


class TestCoordinationManagerTodos:
    def test_list_todos_all(self, mgr):
        todos = mgr.list_todos()
        assert len(todos) == 1
        assert todos[0].id == "TODO-001"

    def test_list_todos_filter_status(self, mgr):
        todos = mgr.list_todos(status=TodoStatus.PENDING)
        assert len(todos) == 1
        todos = mgr.list_todos(status=TodoStatus.COMPLETED)
        assert len(todos) == 0

    def test_list_todos_filter_repo(self, mgr):
        todos = mgr.list_todos(repo="mahavishnu")
        assert len(todos) == 1
        todos = mgr.list_todos(repo="other")
        assert len(todos) == 0

    def test_list_todos_filter_assignee(self, mgr):
        todos = mgr.list_todos(assignee="les")
        assert len(todos) == 0

    def test_get_todo_found(self, mgr):
        todo = mgr.get_todo("TODO-001")
        assert todo is not None
        assert todo.task == "Implement feature"

    def test_get_todo_not_found(self, mgr):
        assert mgr.get_todo("TODO-999") is None


# ===========================================================================
# CoordinationManager - Dependency Management
# ===========================================================================


class TestCoordinationManagerDependencies:
    def test_list_dependencies_all(self, mgr):
        deps = mgr.list_dependencies()
        assert len(deps) == 1
        assert deps[0].id == "DEP-001"
        assert deps[0].consumer == "fastblocks"
        assert deps[0].provider == "oneiric"

    def test_list_dependencies_filter_consumer(self, mgr):
        deps = mgr.list_dependencies(consumer="fastblocks")
        assert len(deps) == 1
        deps = mgr.list_dependencies(consumer="mahavishnu")
        assert len(deps) == 0

    def test_list_dependencies_filter_provider(self, mgr):
        deps = mgr.list_dependencies(provider="oneiric")
        assert len(deps) == 1

    def test_list_dependencies_filter_type(self, mgr):
        deps = mgr.list_dependencies(dependency_type="runtime")
        assert len(deps) == 1
        deps = mgr.list_dependencies(dependency_type="mcp")
        assert len(deps) == 0

    def test_check_dependencies(self, mgr):
        results = mgr.check_dependencies()
        assert results["total"] == 1
        assert results["satisfied"] == 1
        assert results["unsatisfied"] == 0
        assert len(results["dependencies"]) == 1

    def test_check_dependencies_by_consumer(self, mgr):
        result = mgr.check_dependencies(consumer="fastblocks")
        assert result["total"] == 1

    def test_check_dependencies_empty(self, empty_ecosystem_path):
        cm = CoordinationManager(empty_ecosystem_path)
        result = cm.check_dependencies()
        assert result["total"] == 0

    def test_check_dependencies_counts_all_statuses(self, ecosystem_path):
        deps = [
            _sample_dependency_dict(id="DEP-SAT", status="satisfied"),
            _sample_dependency_dict(id="DEP-UNSAT", status="unsatisfied"),
            _sample_dependency_dict(id="DEP-UNK", status="unknown"),
            _sample_dependency_dict(id="DEP-DEPR", status="deprecated"),
        ]
        data = _make_ecosystem_yaml(dependencies=deps)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()
            assert result["satisfied"] == 1
            assert result["unsatisfied"] == 1
            assert result["unknown"] == 1
            assert result["deprecated"] == 1
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager - Normalization
# ===========================================================================


class TestCoordinationManagerNormalization:
    def test_normalize_issue_status_fixed(self, ecosystem_path):
        issue = _sample_issue_dict(status="fixed")
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert issues[0].status == IssueStatus.RESOLVED
        finally:
            os.unlink(path)

    def test_normalize_issue_status_in_progress(self, ecosystem_path):
        issue = _sample_issue_dict(status="in progress")
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert issues[0].status == IssueStatus.IN_PROGRESS
        finally:
            os.unlink(path)

    def test_normalize_issue_status_none(self, ecosystem_path):
        issue = _sample_issue_dict(status=None)
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert issues[0].status == IssueStatus.PENDING
        finally:
            os.unlink(path)

    def test_normalize_issue_priority_p0(self, ecosystem_path):
        issue = _sample_issue_dict(priority="p0")
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert issues[0].priority.value == "critical"
        finally:
            os.unlink(path)

    def test_normalize_todo_status_done(self, ecosystem_path):
        todo = _sample_todo_dict(status="done")
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            todos = cm.list_todos()
            assert todos[0].status == TodoStatus.COMPLETED
        finally:
            os.unlink(path)

    def test_normalize_todo_status_in_progress_dash(self, ecosystem_path):
        todo = _sample_todo_dict(status="in-progress")
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            todos = cm.list_todos()
            assert todos[0].status == TodoStatus.IN_PROGRESS
        finally:
            os.unlink(path)

    def test_normalize_legacy_tags_to_labels(self, ecosystem_path):
        issue = _sample_issue_dict(tags=["bug", "urgent"])
        del issue["labels"]
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert "bug" in issues[0].labels
        finally:
            os.unlink(path)

    def test_normalize_todo_missing_task_uses_title(self, ecosystem_path):
        todo = _sample_todo_dict(title="Fallback title")
        del todo["task"]
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            todos = cm.list_todos()
            assert todos[0].task == "Fallback title"
        finally:
            os.unlink(path)

    def test_normalize_todo_default_estimated_hours(self, ecosystem_path):
        todo = _sample_todo_dict()
        del todo["estimated_hours"]
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            todos = cm.list_todos()
            assert todos[0].estimated_hours == 1.0
        finally:
            os.unlink(path)

    def test_normalize_infer_issue_repos_from_affected_files(self, ecosystem_path):
        issue = _sample_issue_dict()
        del issue["repos"]
        issue["affected_files"] = ["mahavishnu/foo.py", "session-buddy/bar.py"]
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert "mahavishnu" in issues[0].repos
            assert "session-buddy" in issues[0].repos
        finally:
            os.unlink(path)

    def test_normalize_infer_issue_repos_from_pool(self, ecosystem_path):
        issue = _sample_issue_dict()
        del issue["repos"]
        issue["pool"] = "akosha"
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert issues[0].repos == ["akosha"]
        finally:
            os.unlink(path)

    def test_stringify_datetime(self, ecosystem_path):
        issue = _sample_issue_dict(
            created=datetime(2026, 1, 15),
            updated=datetime(2026, 1, 15),
        )
        data = _make_ecosystem_yaml(issues=[issue])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            issues = cm.list_issues()
            assert isinstance(issues[0].created, str)
            assert "2026-01-15" in issues[0].created
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager - Status & Reporting
# ===========================================================================


class TestCoordinationManagerReporting:
    def test_get_blocking_issues(self, ecosystem_path):
        issues = [
            _sample_issue_dict(id="ISSUE-OPEN", status="pending"),
            _sample_issue_dict(id="ISSUE-RESOLVED", status="resolved"),
        ]
        data = _make_ecosystem_yaml(issues=issues)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            blocking = cm.get_blocking_issues("mahavishnu")
            assert len(blocking) == 1
            assert blocking[0].id == "ISSUE-OPEN"
        finally:
            os.unlink(path)

    def test_get_repo_status(self, ecosystem_path):
        data = _make_ecosystem_yaml(
            issues=[_sample_issue_dict(status="pending")],
            todos=[_sample_todo_dict()],
            dependencies=[_sample_dependency_dict()],
        )
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            status = cm.get_repo_status("mahavishnu")
            assert "issues" in status
            assert "todos" in status
            assert "dependencies_outgoing" in status
            assert "dependencies_incoming" in status
            assert "blocking" in status
            assert "blocked_by" in status
            assert len(status["issues"]) == 1
            assert len(status["todos"]) == 1
        finally:
            os.unlink(path)

    def test_get_blocking_todos(self, ecosystem_path):
        todos = [
            _sample_todo_dict(id="T1", blocking=["T2"], status="pending"),
            _sample_todo_dict(id="T2", blocking=[], status="completed"),
        ]
        data = _make_ecosystem_yaml(todos=todos)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            blocking = cm._get_blocking_todos("mahavishnu")
            assert len(blocking) == 1
            assert blocking[0].id == "T1"
        finally:
            os.unlink(path)

    def test_get_blocking_dependencies(self, ecosystem_path):
        deps = [
            _sample_dependency_dict(id="D1", status="unsatisfied", consumer="mahavishnu"),
            _sample_dependency_dict(id="D2", status="satisfied", consumer="mahavishnu"),
        ]
        data = _make_ecosystem_yaml(dependencies=deps)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            blocking = cm._get_blocking_dependencies("mahavishnu")
            assert len(blocking) == 1
            assert blocking[0].id == "D1"
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationManager - Save & Reload
# ===========================================================================


class TestCoordinationManagerSaveReload:
    def test_save_and_reload(self, ecosystem_path):
        mgr = CoordinationManager(ecosystem_path)
        new_issue = CrossRepoIssue(
            id="ISSUE-003",
            title="Save test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        mgr.create_issue(new_issue)
        mgr.save()
        mgr2 = CoordinationManager(ecosystem_path)
        assert mgr2.get_issue("ISSUE-003") is not None


# ===========================================================================
# CoordinationManager - _validate_dependency
# ===========================================================================


class TestValidateDependency:
    def test_validate_with_command_success(self):
        deps_data = [
            {
                "id": "DEP-VAL",
                "consumer": "a",
                "provider": "b",
                "type": "runtime",
                "version_constraint": ">=1.0",
                "status": "satisfied",
                "created": "2026-01-15T00:00:00",
                "updated": "2026-01-15T00:00:00",
                "notes": "test",
                "validation": {
                    "command": "echo hello",
                    "expected_pattern": "hello",
                },
            }
        ]
        data = _make_ecosystem_yaml(dependencies=deps_data)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()
            assert result["total"] == 1
            dep_info = result["dependencies"][0]
            assert dep_info["validation"]["passed"] is True
        finally:
            os.unlink(path)

    def test_validate_command_failure(self):
        deps_data = [
            {
                "id": "DEP-FAIL",
                "consumer": "a",
                "provider": "b",
                "type": "runtime",
                "version_constraint": ">=1.0",
                "status": "satisfied",
                "created": "2026-01-15T00:00:00",
                "updated": "2026-01-15T00:00:00",
                "notes": "test",
                "validation": {
                    "command": "exit 1",
                    "expected_pattern": "won't match",
                },
            }
        ]
        data = _make_ecosystem_yaml(dependencies=deps_data)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            result = cm.check_dependencies()
            dep_info = result["dependencies"][0]
            assert dep_info["validation"]["passed"] is False
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationMemory - Init
# ===========================================================================


class TestCoordinationMemoryInit:
    def test_init_no_client(self):
        mem = CoordinationMemory()
        assert mem.session_buddy is None
        assert mem.collection == "mahavishnu_coordination"

    def test_init_with_client(self):
        client = MagicMock()
        mem = CoordinationMemory(session_buddy_client=client)
        assert mem.session_buddy is client


# ===========================================================================
# CoordinationMemory - Store Events
# ===========================================================================


class TestCoordinationMemoryStoreIssueEvent:
    @pytest.mark.asyncio
    async def test_store_issue_event_no_client(self):
        mem = CoordinationMemory()
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        # Should return without error
        await mem.store_issue_event("created", issue)

    @pytest.mark.asyncio
    async def test_store_issue_event_with_client(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        await mem.store_issue_event("created", issue)
        mock_sb.store_memory.assert_awaited_once()
        call_kwargs = mock_sb.store_memory.call_args[1]
        assert call_kwargs["collection"] == "mahavishnu_coordination"
        assert "Created issue ISSUE-001" in call_kwargs["content"]
        assert call_kwargs["metadata"]["entity_type"] == "issue"

    @pytest.mark.asyncio
    async def test_store_issue_event_with_changes(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        await mem.store_issue_event("updated", issue, changes={"priority": "high"})
        call_kwargs = mock_sb.store_memory.call_args[1]
        assert call_kwargs["metadata"]["changes"] == {"priority": "high"}


class TestCoordinationMemoryStoreTodoEvent:
    @pytest.mark.asyncio
    async def test_store_todo_event_no_client(self):
        mem = CoordinationMemory()
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Task",
            description="desc",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=4.0,
        )
        await mem.store_todo_event("created", todo)

    @pytest.mark.asyncio
    async def test_store_todo_event_with_client(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Task",
            description="desc",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=4.0,
        )
        await mem.store_todo_event("completed", todo)
        mock_sb.store_memory.assert_awaited_once()
        call_kwargs = mock_sb.store_memory.call_args[1]
        assert call_kwargs["metadata"]["entity_type"] == "todo"
        assert call_kwargs["metadata"]["estimated_hours"] == 4.0


class TestCoordinationMemoryStoreDependencyEvent:
    @pytest.mark.asyncio
    async def test_store_dependency_event_no_client(self):
        mem = CoordinationMemory()
        dep = Dependency(
            id="DEP-001",
            consumer="a",
            provider="b",
            type=DependencyType.RUNTIME,
            version_constraint=">=1.0",
            status=DependencyStatus.SATISFIED,
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            notes="test",
        )
        await mem.store_dependency_event("validated", dep)

    @pytest.mark.asyncio
    async def test_store_dependency_event_with_client(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        dep = Dependency(
            id="DEP-001",
            consumer="fastblocks",
            provider="oneiric",
            type=DependencyType.RUNTIME,
            version_constraint=">=0.2.0",
            status=DependencyStatus.SATISFIED,
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            notes="test",
        )
        await mem.store_dependency_event("validated", dep, validation_result={"passed": True})
        mock_sb.store_memory.assert_awaited_once()
        call_kwargs = mock_sb.store_memory.call_args[1]
        assert call_kwargs["metadata"]["entity_type"] == "dependency"
        assert call_kwargs["metadata"]["validation"]["passed"] is True


class TestCoordinationMemoryStorePlanEvent:
    @pytest.mark.asyncio
    async def test_store_plan_event_no_client(self):
        mem = CoordinationMemory()
        plan = CrossRepoPlan(
            id="PLAN-001",
            title="Plan",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            target="2026-03-01T00:00:00",
        )
        await mem.store_plan_event("created", plan)

    @pytest.mark.asyncio
    async def test_store_plan_event_with_client(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        plan = CrossRepoPlan(
            id="PLAN-001",
            title="Plan",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            target="2026-03-01T00:00:00",
            milestones=[
                Milestone(
                    id="M1",
                    name="Milestone 1",
                    description="desc",
                    due="2026-02-01T00:00:00",
                    completion_criteria=["criterion 1"],
                )
            ],
        )
        await mem.store_plan_event("created", plan, milestone="M1")
        mock_sb.store_memory.assert_awaited_once()
        call_kwargs = mock_sb.store_memory.call_args[1]
        assert call_kwargs["metadata"]["entity_type"] == "plan"
        assert call_kwargs["metadata"]["milestone"] == "M1"
        assert call_kwargs["metadata"]["milestone_count"] == 1


# ===========================================================================
# CoordinationMemory - Search & Trends
# ===========================================================================


class TestCoordinationMemorySearch:
    @pytest.mark.asyncio
    async def test_search_no_client_returns_empty(self):
        mem = CoordinationMemory()
        result = await mem.search_coordination_history("test")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_with_client(self):
        mock_sb = AsyncMock()
        mock_sb.search.return_value = [{"content": "match"}]
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        result = await mem.search_coordination_history("test", entity_type="issue")
        mock_sb.search.assert_awaited_once()
        call_kwargs = mock_sb.search.call_args[1]
        assert call_kwargs["filters"]["entity_type"] == "issue"
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(self):
        mock_sb = AsyncMock()
        mock_sb.search.return_value = []
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        await mem.search_coordination_history("test", repo="mahavishnu")
        call_kwargs = mock_sb.search.call_args[1]
        assert "$or" in call_kwargs["filters"]

    @pytest.mark.asyncio
    async def test_search_exception_returns_empty(self):
        mock_sb = AsyncMock()
        mock_sb.search.side_effect = RuntimeError("search failed")
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        result = await mem.search_coordination_history("test")
        assert result == []


class TestCoordinationMemoryTrends:
    @pytest.mark.asyncio
    async def test_trends_no_client(self):
        mem = CoordinationMemory()
        result = await mem.get_coordination_trends()
        assert result["error"] == "Session-Buddy not available"

    @pytest.mark.asyncio
    async def test_trends_with_client(self):
        mock_sb = AsyncMock()
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        result = await mem.get_coordination_trends(repo="mahavishnu", days=7)
        assert result["message"] == "Trend analysis not yet implemented"
        assert result["repo"] == "mahavishnu"
        assert result["days"] == 7


# ===========================================================================
# CoordinationMemory - Close & Error Handling
# ===========================================================================


class TestCoordinationMemoryClose:
    @pytest.mark.asyncio
    async def test_close(self):
        mem = CoordinationMemory()
        await mem.close()  # Should not raise


class TestCoordinationMemoryStoreError:
    @pytest.mark.asyncio
    async def test_store_memory_error_is_caught(self):
        mock_sb = AsyncMock()
        mock_sb.store_memory.side_effect = RuntimeError("connection error")
        mem = CoordinationMemory(session_buddy_client=mock_sb)
        issue = CrossRepoIssue(
            id="ISSUE-001",
            title="Test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        # Should not raise, just log
        await mem.store_issue_event("created", issue)


# ===========================================================================
# CoordinationManagerWithMemory - Init & Delegation
# ===========================================================================


class TestCoordinationManagerWithMemoryInit:
    def test_init_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=None,
        )
        assert cmwm._coordination_mgr is not None
        assert cmwm.memory is not None
        assert isinstance(cmwm.memory, CoordinationMemory)

    def test_init_with_session_buddy(self, ecosystem_path):
        mock_sb = MagicMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        assert cmwm.memory.session_buddy is mock_sb


class TestCoordinationManagerWithMemoryDelegation:
    def test_list_issues_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        issues = cmwm.list_issues()
        assert len(issues) == 1

    def test_get_issue_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        issue = cmwm.get_issue("ISSUE-001")
        assert issue is not None

    def test_list_plans_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        plans = cmwm.list_plans()
        assert len(plans) == 1

    def test_get_plan_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        plan = cmwm.get_plan("PLAN-001")
        assert plan is not None

    def test_list_todos_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        todos = cmwm.list_todos()
        assert len(todos) == 1

    def test_get_todo_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        todo = cmwm.get_todo("TODO-001")
        assert todo is not None

    def test_list_dependencies_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        deps = cmwm.list_dependencies()
        assert len(deps) == 1

    def test_check_dependencies_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        result = cmwm.check_dependencies()
        assert result["total"] == 1

    def test_get_blocking_issues_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        blocking = cmwm.get_blocking_issues("mahavishnu")
        assert len(blocking) == 1

    def test_get_repo_status_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        status = cmwm.get_repo_status("mahavishnu")
        assert "issues" in status

    def test_reload_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        cmwm.reload()

    def test_save_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        cmwm.save()

    def test_create_issue_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        new_issue = CrossRepoIssue(
            id="ISSUE-NEW",
            title="New",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        cmwm.create_issue(new_issue)
        assert cmwm.get_issue("ISSUE-NEW") is not None

    def test_update_issue_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        cmwm.update_issue("ISSUE-001", {"title": "Updated"})
        assert cmwm.get_issue("ISSUE-001").title == "Updated"

    def test_delete_issue_delegates(self, ecosystem_path):
        cmwm = CoordinationManagerWithMemory(ecosystem_path=ecosystem_path)
        cmwm.delete_issue("ISSUE-001")
        assert cmwm.get_issue("ISSUE-001") is None


# ===========================================================================
# CoordinationManagerWithMemory - Async Operations
# ===========================================================================


class TestCoordinationManagerWithMemoryAsync:
    @pytest.mark.asyncio
    async def test_create_issue_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        new_issue = CrossRepoIssue(
            id="ISSUE-MEM",
            title="Memory test",
            description="desc",
            repos=["mahavishnu"],
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
        )
        await cmwm.create_issue_with_memory(new_issue)
        assert cmwm.get_issue("ISSUE-MEM") is not None
        mock_sb.store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_issue_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        await cmwm.update_issue_with_memory("ISSUE-001", {"title": "Updated"})
        issue = cmwm.get_issue("ISSUE-001")
        assert issue.title == "Updated"
        mock_sb.store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_issue_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        await cmwm.close_issue_with_memory("ISSUE-001")
        raw_status = cmwm._coordination_mgr._coordination["issues"][0]["status"]
        assert raw_status == "closed"
        mock_sb.store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_todo_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        new_todo = CrossRepoTodo(
            id="TODO-MEM",
            task="Memory task",
            description="desc",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=2.0,
        )
        await cmwm.create_todo_with_memory(new_todo)
        assert cmwm.get_todo("TODO-MEM") is not None
        mock_sb.store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_todo_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        await cmwm.complete_todo_with_memory("TODO-001")
        todos = cmwm._coordination_mgr._coordination["todos"]
        assert todos[0]["status"] == "completed"
        mock_sb.store_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_todo_not_found_raises(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        with pytest.raises(ValueError, match="not found"):
            await cmwm.complete_todo_with_memory("TODO-999")

    @pytest.mark.asyncio
    async def test_check_dependencies_with_memory(self, ecosystem_path):
        mock_sb = AsyncMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        result = await cmwm.check_dependencies_with_memory()
        assert result["total"] == 1
        assert mock_sb.store_memory.call_count == 1


# ===========================================================================
# CoordinationExecutor - Initialization
# ===========================================================================


class TestCoordinationExecutorInit:
    def test_init_with_manager(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        assert executor.coordination is mgr
        assert executor.pool_manager is None

    def test_init_with_pool_manager(self, mgr):
        pm = MagicMock()
        executor = CoordinationExecutor(coordination_manager=mgr, pool_manager=pm)
        assert executor.pool_manager is pm


# ===========================================================================
# CoordinationExecutor - execute_todo
# ===========================================================================


class TestCoordinationExecutorExecuteTodo:
    @pytest.mark.asyncio
    async def test_todo_not_found(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        result = await executor.execute_todo("TODO-999")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_todo_blocked(self, ecosystem_path):
        todo = _sample_todo_dict(blocked_by=["ISSUE-001"])
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is False
            assert "blocked" in result["error"]
            assert result["blocked_by"] == ["ISSUE-001"]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_todo_already_completed(self, ecosystem_path):
        todo = _sample_todo_dict(status="completed")
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is True
            assert "already completed" in result["message"]
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_success_no_pool_manager(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is True
            assert result["todo_id"] == "TODO-001"
            assert result["task"] == "Implement feature"
            assert result["repo"] == "mahavishnu"
            assert result["duration_seconds"] > 0
            # Status should be updated to completed
            updated_todo = cm.get_todo("TODO-001")
            assert updated_todo.status.value == "completed"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_with_pool_manager_success(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            pool_mgr = AsyncMock()
            pool_mgr.route_task.return_value = {"success": True, "output": "done"}
            executor = CoordinationExecutor(
                coordination_manager=cm,
                pool_manager=pool_mgr,
            )
            result = await executor.execute_todo("TODO-001", pool_type="mahavishnu")
            assert result["success"] is True
            pool_mgr.route_task.assert_awaited_once()
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_pool_manager_failure(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            pool_mgr = AsyncMock()
            pool_mgr.route_task.return_value = {
                "success": False,
                "error": "task failed",
            }
            executor = CoordinationExecutor(
                coordination_manager=cm,
                pool_manager=pool_mgr,
            )
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is False
            assert result["error"] == "task failed"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_pool_failure_keeps_in_progress(self, ecosystem_path):
        """When pool returns failure (not exception), status stays in_progress."""
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            pool_mgr = AsyncMock()
            pool_mgr.route_task.return_value = {
                "success": False,
                "error": "task failed",
            }
            executor = CoordinationExecutor(
                coordination_manager=cm,
                pool_manager=pool_mgr,
            )
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is False
            assert result["error"] == "task failed"
            # Status stays in_progress because _execute_via_pool catches
            # internally and returns a failure dict (no exception propagates)
            updated = cm.get_todo("TODO-001")
            assert updated.status.value == "in_progress"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_unhandled_exception_sets_blocked(self, ecosystem_path):
        """When an unhandled exception escapes the try block, status becomes blocked."""
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            # Replace _simulate_execution with a function that raises
            # This is inside the try block in execute_todo
            original_sim = executor._simulate_execution

            async def _bad_simulate(t):
                raise RuntimeError("sim error")

            executor._simulate_execution = _bad_simulate
            result = await executor.execute_todo("TODO-001")
            executor._simulate_execution = original_sim
            assert result["success"] is False
            assert "sim error" in result["error"]
            # Status should be blocked after exception
            updated = cm.get_todo("TODO-001")
            assert updated.status.value == "blocked"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_records_actual_hours(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.execute_todo("TODO-001")
            assert result["success"] is True
            # Check actual_hours was recorded (may round to 0.0 for fast execution)
            todos_data = cm._coordination.get("todos", [])
            assert "actual_hours" in todos_data[0]
            assert todos_data[0]["actual_hours"] >= 0.0
            # Verify duration_seconds is also in the result
            assert result["duration_seconds"] >= 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_stores_memory_event(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            # Attach a memory mock to the coordination manager
            mock_memory = AsyncMock()
            executor = CoordinationExecutor(coordination_manager=cm)
            executor.coordination.memory = mock_memory

            result = await executor.execute_todo("TODO-001")
            assert result["success"] is True
            mock_memory.store_todo_event.assert_awaited_once()
            call_kwargs = mock_memory.store_todo_event.call_args
            assert call_kwargs[0][0] == "completed"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_execute_memory_error_does_not_fail(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            mock_memory = AsyncMock()
            mock_memory.store_todo_event.side_effect = RuntimeError("mem error")
            executor = CoordinationExecutor(coordination_manager=cm)
            executor.coordination.memory = mock_memory

            result = await executor.execute_todo("TODO-001")
            assert result["success"] is True  # Should not fail
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationExecutor - sweep_plan
# ===========================================================================


class TestCoordinationExecutorSweepPlan:
    @pytest.mark.asyncio
    async def test_plan_not_found(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        result = await executor.sweep_plan("PLAN-999")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_pending_todos(self, ecosystem_path):
        todo = _sample_todo_dict(status="completed")
        plan = _sample_plan_dict()
        data = _make_ecosystem_yaml(todos=[todo], plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.sweep_plan("PLAN-001")
            assert result["success"] is True
            assert result["total_todos"] == 0
            assert result["executed"] == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_sweep_sequential_success(self, ecosystem_path):
        todo = _sample_todo_dict()
        plan = _sample_plan_dict()
        data = _make_ecosystem_yaml(todos=[todo], plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.sweep_plan("PLAN-001", parallel=False)
            assert result["success"] is True
            assert result["total_todos"] == 1
            assert result["successful"] == 1
            assert result["failed"] == 0
            assert len(result["results"]) == 1
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_sweep_parallel_success(self, ecosystem_path):
        todo = _sample_todo_dict()
        plan = _sample_plan_dict()
        data = _make_ecosystem_yaml(todos=[todo], plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.sweep_plan("PLAN-001", parallel=True)
            assert result["success"] is True
            assert result["total_todos"] == 1
            assert result["successful"] == 1
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_sweep_multiple_todos_across_repos(self, ecosystem_path):
        todos = [
            _sample_todo_dict(id="T1", repo="mahavishnu", status="pending"),
            _sample_todo_dict(id="T2", repo="mahavishnu", status="pending"),
            _sample_todo_dict(id="T3", repo="mahavishnu", status="completed"),
        ]
        plan = _sample_plan_dict(repos=["mahavishnu"])
        data = _make_ecosystem_yaml(todos=todos, plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.sweep_plan("PLAN-001", parallel=True)
            assert result["total_todos"] == 2  # Only pending
            assert result["successful"] == 2
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationExecutor - validate_plan_completion
# ===========================================================================


class TestCoordinationExecutorValidatePlan:
    @pytest.mark.asyncio
    async def test_plan_not_found(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        result = await executor.validate_plan_completion("PLAN-999")
        assert result["valid"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_plan_no_milestones(self, ecosystem_path):
        plan = _sample_plan_dict(milestones=[])
        data = _make_ecosystem_yaml(plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.validate_plan_completion("PLAN-001")
            assert result["valid"] is True
            assert len(result["milestones"]) == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_plan_with_milestones(self, ecosystem_path):
        milestone = {
            "id": "M1",
            "name": "Milestone 1",
            "description": "First milestone",
            "due": "2026-02-01T00:00:00",
            "status": "pending",
            "dependencies": [],
            "completion_criteria": ["Criterion 1", "Criterion 2"],
            "deliverables": [],
        }
        plan = _sample_plan_dict(milestones=[milestone])
        data = _make_ecosystem_yaml(plans=[plan])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            result = await executor.validate_plan_completion("PLAN-001")
            assert result["valid"] is True
            assert len(result["milestones"]) == 1
            ms_result = result["milestones"][0]
            assert ms_result["milestone_id"] == "M1"
            assert ms_result["milestone_name"] == "Milestone 1"
            assert len(ms_result["criteria"]) == 2
            assert all(c["met"] for c in ms_result["criteria"])
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationExecutor - _create_task_prompt
# ===========================================================================


class TestCoordinationExecutorCreateTaskPrompt:
    def test_basic_prompt(self):
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Build API",
            description="Build the REST API",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=4.0,
        )
        executor = CoordinationExecutor()
        prompt = executor._create_task_prompt(todo)
        assert "Build API" in prompt
        assert "Build the REST API" in prompt
        assert "mahavishnu" in prompt

    def test_prompt_with_acceptance_criteria(self):
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Build API",
            description="desc",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=4.0,
            acceptance_criteria=["Must pass tests", "Must have docs"],
        )
        executor = CoordinationExecutor()
        prompt = executor._create_task_prompt(todo)
        assert "Acceptance Criteria" in prompt
        assert "1. Must pass tests" in prompt
        assert "2. Must have docs" in prompt


# ===========================================================================
# CoordinationExecutor - State helpers
# ===========================================================================


class TestCoordinationExecutorStateHelpers:
    def test_get_state_plain_manager(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        state = executor._get_coordination_state()
        assert isinstance(state, dict)
        assert "todos" in state

    def test_get_state_wrapped_manager(self, ecosystem_path):
        mock_sb = MagicMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        executor = CoordinationExecutor(coordination_manager=cmwm)
        state = executor._get_coordination_state()
        assert isinstance(state, dict)
        assert "todos" in state

    def test_save_state_plain_manager(self, mgr):
        executor = CoordinationExecutor(coordination_manager=mgr)
        executor._save_coordination_state()  # Should not raise

    def test_save_state_wrapped_manager(self, ecosystem_path):
        mock_sb = MagicMock()
        cmwm = CoordinationManagerWithMemory(
            ecosystem_path=ecosystem_path,
            session_buddy_client=mock_sb,
        )
        executor = CoordinationExecutor(coordination_manager=cmwm)
        executor._save_coordination_state()  # Should not raise


# ===========================================================================
# CoordinationExecutor - _update_todo_status / _update_todo_actual_hours
# ===========================================================================


class TestCoordinationExecutorTodoUpdates:
    def test_update_todo_status(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            executor._update_todo_status("TODO-001", "in_progress")
            updated = cm.get_todo("TODO-001")
            assert updated.status.value == "in_progress"
        finally:
            os.unlink(path)

    def test_update_todo_status_not_found(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            # Should not raise, just return silently
            executor._update_todo_status("TODO-999", "in_progress")
        finally:
            os.unlink(path)

    def test_update_todo_actual_hours(self, ecosystem_path):
        todo = _sample_todo_dict()
        data = _make_ecosystem_yaml(todos=[todo])
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            executor = CoordinationExecutor(coordination_manager=cm)
            executor._update_todo_actual_hours("TODO-001", 2.5)
            todos_data = cm._coordination.get("todos", [])
            assert todos_data[0]["actual_hours"] == 2.5
        finally:
            os.unlink(path)


# ===========================================================================
# CoordinationExecutor - _execute_via_pool
# ===========================================================================


class TestCoordinationExecutorExecuteViaPool:
    @pytest.mark.asyncio
    async def test_success(self):
        mgr_mock = MagicMock()
        executor = CoordinationExecutor(coordination_manager=mgr_mock)
        pool_mgr = AsyncMock()
        executor.pool_manager = pool_mgr
        pool_mgr.route_task.return_value = {"success": True, "output": "ok"}

        with patch("mahavishnu.pools.PoolSelector") as mock_sel_cls:
            mock_sel_cls.return_value = "least_loaded"
            result = await executor._execute_via_pool(
                {"prompt": "test"}, "mahavishnu", "least_loaded"
            )
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_exception_returns_failure(self):
        mgr_mock = MagicMock()
        executor = CoordinationExecutor(coordination_manager=mgr_mock)
        pool_mgr = AsyncMock()
        executor.pool_manager = pool_mgr
        pool_mgr.route_task.side_effect = RuntimeError("boom")

        with patch("mahavishnu.pools.PoolSelector") as mock_sel_cls:
            mock_sel_cls.return_value = "least_loaded"
            result = await executor._execute_via_pool(
                {"prompt": "test"}, "mahavishnu", "least_loaded"
            )
            assert result["success"] is False
            assert "boom" in result["error"]


# ===========================================================================
# CoordinationExecutor - _simulate_execution
# ===========================================================================


class TestCoordinationExecutorSimulate:
    @pytest.mark.asyncio
    async def test_returns_success(self):
        executor = CoordinationExecutor()
        todo = CrossRepoTodo(
            id="TODO-001",
            task="Sim task",
            description="desc",
            repo="mahavishnu",
            created="2026-01-15T00:00:00",
            updated="2026-01-15T00:00:00",
            estimated_hours=1.0,
        )
        result = await executor._simulate_execution(todo)
        assert result["success"] is True
        assert "Sim task" in result["output"]


# ===========================================================================
# CoordinationExecutor - _execute_sequential
# ===========================================================================


class TestCoordinationExecutorSequential:
    @pytest.mark.asyncio
    async def test_stops_on_failure(self, ecosystem_path):
        todos = [
            _sample_todo_dict(id="T-FAIL", status="pending"),
            _sample_todo_dict(id="T-NEVER", status="pending"),
        ]
        data = _make_ecosystem_yaml(todos=todos)
        path = _write_ecosystem(data)
        try:
            cm = CoordinationManager(path)
            pool_mgr = AsyncMock()
            pool_mgr.route_task.return_value = {"success": False, "error": "fail"}
            executor = CoordinationExecutor(
                coordination_manager=cm,
                pool_manager=pool_mgr,
            )
            # Create todo objects for _execute_sequential
            todo_objs = [
                CrossRepoTodo(**cm._normalize_todo_record(t))
                for t in cm._coordination.get("todos", [])
            ]
            results = await executor._execute_sequential(todo_objs, "mahavishnu", "least_loaded")
            assert len(results) == 1  # Should stop after first failure
            assert results[0]["success"] is False
        finally:
            os.unlink(path)
