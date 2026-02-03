"""
Unit tests for the cross-repository coordination system.

Tests the CoordinationManager and data models.
"""

from pathlib import Path
import tempfile

import pytest
import yaml

from mahavishnu.core.coordination.manager import CoordinationManager
from mahavishnu.core.coordination.models import (
    CrossRepoIssue,
    CrossRepoTodo,
    Dependency,
    DependencyStatus,
    DependencyType,
    IssueStatus,
    Priority,
    TodoStatus,
)


@pytest.fixture
def temp_ecosystem_file():
    """Create a temporary ecosystem.yaml file for testing."""
    ecosystem_data = {
        "version": "1.0",
        "coordination": {
            "issues": [
                {
                    "id": "ISSUE-001",
                    "title": "Test Issue",
                    "description": "A test issue",
                    "status": "pending",
                    "priority": "high",
                    "severity": "bug",
                    "repos": ["mahavishnu", "session-buddy"],
                    "created": "2026-01-31T00:00:00",
                    "updated": "2026-01-31T00:00:00",
                    "target": "2026-02-15T00:00:00",
                    "dependencies": [],
                    "blocking": [],
                    "assignee": "les",
                    "labels": ["test"],
                    "metadata": {},
                }
            ],
            "plans": [],
            "todos": [
                {
                    "id": "TODO-001",
                    "task": "Test task",
                    "description": "A test todo",
                    "repo": "mahavishnu",
                    "status": "pending",
                    "priority": "medium",
                    "created": "2026-01-31T00:00:00",
                    "updated": "2026-01-31T00:00:00",
                    "estimated_hours": 8.0,
                    "actual_hours": None,
                    "blocked_by": [],
                    "blocking": [],
                    "assignee": "les",
                    "labels": [],
                    "acceptance_criteria": [],
                }
            ],
            "dependencies": [
                {
                    "id": "DEP-001",
                    "consumer": "fastblocks",
                    "provider": "oneiric",
                    "type": "runtime",
                    "version_constraint": ">=0.2.0",
                    "status": "satisfied",
                    "created": "2026-01-15T00:00:00",
                    "updated": "2026-01-30T00:00:00",
                    "notes": "Test dependency",
                    "validation": None,
                }
            ],
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(ecosystem_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink()


class TestCoordinationManager:
    """Test suite for CoordinationManager."""

    def test_load_ecosystem(self, temp_ecosystem_file):
        """Test loading ecosystem.yaml."""
        mgr = CoordinationManager(temp_ecosystem_file)
        assert mgr._ecosystem is not None
        assert "coordination" in mgr._ecosystem

    def test_list_issues(self, temp_ecosystem_file):
        """Test listing issues."""
        mgr = CoordinationManager(temp_ecosystem_file)
        issues = mgr.list_issues()

        assert len(issues) == 1
        assert issues[0].id == "ISSUE-001"
        assert issues[0].title == "Test Issue"

    def test_list_issues_with_filters(self, temp_ecosystem_file):
        """Test listing issues with filters."""
        mgr = CoordinationManager(temp_ecosystem_file)

        # Filter by status
        pending_issues = mgr.list_issues(status=IssueStatus.PENDING)
        assert len(pending_issues) == 1

        resolved_issues = mgr.list_issues(status=IssueStatus.RESOLVED)
        assert len(resolved_issues) == 0

        # Filter by repo
        mahavishnu_issues = mgr.list_issues(repo="mahavishnu")
        assert len(mahavishnu_issues) == 1

        other_issues = mgr.list_issues(repo="crackerjack")
        assert len(other_issues) == 0

    def test_get_issue(self, temp_ecosystem_file):
        """Test getting a specific issue."""
        mgr = CoordinationManager(temp_ecosystem_file)
        issue = mgr.get_issue("ISSUE-001")

        assert issue is not None
        assert issue.id == "ISSUE-001"
        assert issue.title == "Test Issue"

    def test_create_issue(self, temp_ecosystem_file):
        """Test creating a new issue."""
        mgr = CoordinationManager(temp_ecosystem_file)

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

        # Reload and verify
        mgr.reload()
        issues = mgr.list_issues()
        assert len(issues) == 2

        new_issue = mgr.get_issue("ISSUE-002")
        assert new_issue is not None
        assert new_issue.title == "New Issue"

    def test_create_duplicate_issue(self, temp_ecosystem_file):
        """Test that creating a duplicate issue raises an error."""
        mgr = CoordinationManager(temp_ecosystem_file)

        duplicate_issue = CrossRepoIssue(
            id="ISSUE-001",  # Duplicate ID
            title="Duplicate",
            description="Duplicate issue",
            status=IssueStatus.PENDING,
            priority=Priority.MEDIUM,
            severity="bug",
            repos=["mahavishnu"],
            created="2026-01-31T00:00:00",
            updated="2026-01-31T00:00:00",
            dependencies=[],
            blocking=[],
            labels=[],
            metadata={},
        )

        with pytest.raises(Exception):  # ConfigurationError
            mgr.create_issue(duplicate_issue)

    def test_update_issue(self, temp_ecosystem_file):
        """Test updating an issue."""
        mgr = CoordinationManager(temp_ecosystem_file)

        mgr.update_issue("ISSUE-001", {"status": "in_progress"})
        mgr.save()

        # Reload and verify
        mgr.reload()
        issue = mgr.get_issue("ISSUE-001")
        assert issue.status == IssueStatus.IN_PROGRESS

    def test_delete_issue(self, temp_ecosystem_file):
        """Test deleting an issue."""
        mgr = CoordinationManager(temp_ecosystem_file)

        mgr.delete_issue("ISSUE-001")
        mgr.save()

        # Reload and verify
        mgr.reload()
        issues = mgr.list_issues()
        assert len(issues) == 0

    def test_list_todos(self, temp_ecosystem_file):
        """Test listing todos."""
        mgr = CoordinationManager(temp_ecosystem_file)
        todos = mgr.list_todos()

        assert len(todos) == 1
        assert todos[0].id == "TODO-001"
        assert todos[0].task == "Test task"

    def test_get_todo(self, temp_ecosystem_file):
        """Test getting a specific todo."""
        mgr = CoordinationManager(temp_ecosystem_file)
        todo = mgr.get_todo("TODO-001")

        assert todo is not None
        assert todo.id == "TODO-001"
        assert todo.task == "Test task"

    def test_list_dependencies(self, temp_ecosystem_file):
        """Test listing dependencies."""
        mgr = CoordinationManager(temp_ecosystem_file)
        deps = mgr.list_dependencies()

        assert len(deps) == 1
        assert deps[0].id == "DEP-001"
        assert deps[0].consumer == "fastblocks"
        assert deps[0].provider == "oneiric"

    def test_check_dependencies(self, temp_ecosystem_file):
        """Test checking dependencies."""
        mgr = CoordinationManager(temp_ecosystem_file)
        results = mgr.check_dependencies()

        assert results["total"] == 1
        assert results["satisfied"] == 1
        assert results["unsatisfied"] == 0
        assert len(results["dependencies"]) == 1

    def test_get_blocking_issues(self, temp_ecosystem_file):
        """Test getting blocking issues for a repository."""
        mgr = CoordinationManager(temp_ecosystem_file)
        blocking_issues = mgr.get_blocking_issues("mahavishnu")

        assert len(blocking_issues) == 1
        assert blocking_issues[0].id == "ISSUE-001"

    def test_get_repo_status(self, temp_ecosystem_file):
        """Test getting comprehensive status for a repository."""
        mgr = CoordinationManager(temp_ecosystem_file)
        status = mgr.get_repo_status("mahavishnu")

        assert "issues" in status
        assert "todos" in status
        assert "dependencies_outgoing" in status
        assert "dependencies_incoming" in status
        assert "blocking" in status
        assert "blocked_by" in status

        assert len(status["issues"]) == 1
        assert len(status["todos"]) == 1


class TestCoordinationModels:
    """Test suite for coordination data models."""

    def test_cross_repo_issue_validation(self):
        """Test CrossRepoIssue model validation."""
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
                repos=[],  # Empty repos list
                created="2026-01-31T00:00:00",
                updated="2026-01-31T00:00:00",
                dependencies=[],
                blocking=[],
                labels=[],
                metadata={},
            )

    def test_cross_repo_todo_validation(self):
        """Test CrossRepoTodo model validation."""
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
                estimated_hours=-1.0,  # Negative
                blocked_by=[],
                blocking=[],
                labels=[],
                acceptance_criteria=[],
            )

    def test_dependency_model(self):
        """Test Dependency model."""
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
