"""Tests for cross-repository coordination Pydantic models.

Tests cover:
- Priority and DependencyType StrEnum values
- Milestone creation with all fields and defaults
- CrossRepoIssue creation, validation (empty repos, target date format)
- CrossRepoPlan creation, validation (empty repos)
- CrossRepoTodo creation, validation (estimated_hours positive)
- DependencyValidation creation with various field combinations
- Dependency creation, validation (empty consumer/provider)
- Module-level example constants are valid instances
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from mahavishnu.core.coordination.models import (
    EXAMPLE_DEPENDENCY,
    EXAMPLE_ISSUE,
    EXAMPLE_TODO,
    CrossRepoIssue,
    CrossRepoPlan,
    CrossRepoTodo,
    Dependency,
    DependencyType,
    DependencyValidation,
    Milestone,
    Priority,
)
from mahavishnu.core.status import (
    DependencyStatus,
    IssueStatus,
    PlanStatus,
    TodoStatus,
)


# ============================================================================
# Priority Enum
# ============================================================================


class TestPriority:
    def test_values(self):
        assert Priority.CRITICAL == "critical"
        assert Priority.HIGH == "high"
        assert Priority.MEDIUM == "medium"
        assert Priority.LOW == "low"

    def test_member_count(self):
        assert len(Priority) == 4

    def test_string_membership(self):
        assert "critical" in Priority
        assert "invalid" not in Priority

    def test_iteration(self):
        values = {p.value for p in Priority}
        assert values == {"critical", "high", "medium", "low"}


# ============================================================================
# DependencyType Enum
# ============================================================================


class TestDependencyType:
    def test_values(self):
        assert DependencyType.RUNTIME == "runtime"
        assert DependencyType.DEVELOPMENT == "development"
        assert DependencyType.MCP == "mcp"
        assert DependencyType.TEST == "test"
        assert DependencyType.DOCUMENTATION == "documentation"

    def test_member_count(self):
        assert len(DependencyType) == 5

    def test_string_membership(self):
        assert "runtime" in DependencyType
        assert "mcp" in DependencyType
        assert "nonexistent" not in DependencyType

    def test_iteration(self):
        values = {d.value for d in DependencyType}
        assert values == {"runtime", "development", "mcp", "test", "documentation"}


# ============================================================================
# Milestone
# ============================================================================


class TestMilestone:
    def test_creation_with_all_fields(self):
        ms = Milestone(
            id="MILESTONE-001",
            name="Phase 1",
            description="Initial delivery",
            due="2026-03-01T00:00:00",
            status=TodoStatus.IN_PROGRESS,
            dependencies=["MILESTONE-000"],
            completion_criteria=["Tests pass"],
            deliverables=["API module"],
        )
        assert ms.id == "MILESTONE-001"
        assert ms.name == "Phase 1"
        assert ms.description == "Initial delivery"
        assert ms.due == "2026-03-01T00:00:00"
        assert ms.status == TodoStatus.IN_PROGRESS
        assert ms.dependencies == ["MILESTONE-000"]
        assert ms.completion_criteria == ["Tests pass"]
        assert ms.deliverables == ["API module"]

    def test_defaults(self):
        ms = Milestone(
            id="M-1",
            name="M",
            description="D",
            due="2026-01-01",
        )
        assert ms.status == TodoStatus.PENDING
        assert ms.dependencies == []
        assert ms.completion_criteria == []
        assert ms.deliverables == []

    def test_required_fields_missing(self):
        with pytest.raises(ValidationError):
            Milestone(id="M-1", name="M")  # missing description, due


# ============================================================================
# CrossRepoIssue
# ============================================================================


class TestCrossRepoIssue:
    def _minimal_kwargs(self) -> dict:
        return {
            "id": "ISSUE-001",
            "title": "Test issue",
            "description": "A test issue",
            "repos": ["repo-a"],
            "created": "2026-01-01T00:00:00",
            "updated": "2026-01-01T00:00:00",
        }

    def test_creation_with_defaults(self):
        issue = CrossRepoIssue(**self._minimal_kwargs())
        assert issue.id == "ISSUE-001"
        assert issue.title == "Test issue"
        assert issue.status == IssueStatus.PENDING
        assert issue.priority == Priority.MEDIUM
        assert issue.severity == "normal"
        assert issue.repos == ["repo-a"]
        assert issue.target is None
        assert issue.dependencies == []
        assert issue.blocking == []
        assert issue.assignee is None
        assert issue.labels == []
        assert issue.metadata == {}

    def test_creation_with_all_fields(self):
        issue = CrossRepoIssue(
            id="ISSUE-002",
            title="Full issue",
            description="Detailed desc",
            status=IssueStatus.IN_PROGRESS,
            priority=Priority.CRITICAL,
            severity="bug",
            repos=["repo-a", "repo-b"],
            created="2026-01-15T00:00:00",
            updated="2026-01-20T00:00:00",
            target="2026-02-01T00:00:00",
            dependencies=["ISSUE-001"],
            blocking=["ISSUE-003"],
            assignee="alice",
            labels=["bug", "urgent"],
            metadata={"key": "value"},
        )
        assert issue.status == IssueStatus.IN_PROGRESS
        assert issue.priority == Priority.CRITICAL
        assert issue.severity == "bug"
        assert len(issue.repos) == 2
        assert issue.target == "2026-02-01T00:00:00"
        assert issue.assignee == "alice"
        assert issue.metadata == {"key": "value"}

    def test_empty_repos_fails(self):
        with pytest.raises(ValidationError, match="At least one repository"):
            CrossRepoIssue(
                id="ISSUE-003",
                title="Bad issue",
                description="desc",
                repos=[],
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
            )

    def test_valid_target_date_accepted(self):
        issue = CrossRepoIssue(**self._minimal_kwargs(), target="2026-12-31T23:59:59")
        assert issue.target == "2026-12-31T23:59:59"

    def test_invalid_target_date_fails(self):
        with pytest.raises(ValidationError, match="Invalid target date format"):
            CrossRepoIssue(**self._minimal_kwargs(), target="not-a-date")

    def test_none_target_date_accepted(self):
        issue = CrossRepoIssue(**self._minimal_kwargs(), target=None)
        assert issue.target is None

    def test_serialization_roundtrip(self):
        issue = CrossRepoIssue(**self._minimal_kwargs())
        data = issue.model_dump()
        restored = CrossRepoIssue(**data)
        assert restored.id == issue.id
        assert restored.title == issue.title


# ============================================================================
# CrossRepoPlan
# ============================================================================


class TestCrossRepoPlan:
    def _minimal_kwargs(self) -> dict:
        return {
            "id": "PLAN-001",
            "title": "Test plan",
            "description": "A test plan",
            "repos": ["repo-a"],
            "created": "2026-01-01T00:00:00",
            "updated": "2026-01-01T00:00:00",
            "target": "2026-03-01T00:00:00",
        }

    def test_creation_with_defaults(self):
        plan = CrossRepoPlan(**self._minimal_kwargs())
        assert plan.id == "PLAN-001"
        assert plan.status == PlanStatus.DRAFT
        assert plan.repos == ["repo-a"]
        assert plan.milestones == []

    def test_creation_with_all_fields(self):
        milestone = Milestone(
            id="M-1", name="M1", description="D", due="2026-02-01T00:00:00"
        )
        plan = CrossRepoPlan(
            id="PLAN-002",
            title="Full plan",
            description="Detailed desc",
            status=PlanStatus.ACTIVE,
            repos=["repo-a", "repo-b"],
            created="2026-01-15T00:00:00",
            updated="2026-01-20T00:00:00",
            target="2026-06-01T00:00:00",
            milestones=[milestone],
        )
        assert plan.status == PlanStatus.ACTIVE
        assert len(plan.repos) == 2
        assert len(plan.milestones) == 1
        assert plan.milestones[0].id == "M-1"

    def test_empty_repos_fails(self):
        with pytest.raises(ValidationError, match="At least one repository"):
            CrossRepoPlan(
                id="PLAN-003",
                title="Bad plan",
                description="desc",
                repos=[],
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
                target="2026-03-01T00:00:00",
            )

    def test_serialization_roundtrip(self):
        plan = CrossRepoPlan(**self._minimal_kwargs())
        data = plan.model_dump()
        restored = CrossRepoPlan(**data)
        assert restored.id == plan.id
        assert restored.title == plan.title


# ============================================================================
# CrossRepoTodo
# ============================================================================


class TestCrossRepoTodo:
    def _minimal_kwargs(self) -> dict:
        return {
            "id": "TODO-001",
            "task": "Do something",
            "description": "A task",
            "repo": "repo-a",
            "created": "2026-01-01T00:00:00",
            "updated": "2026-01-01T00:00:00",
            "estimated_hours": 4.0,
        }

    def test_creation_with_defaults(self):
        todo = CrossRepoTodo(**self._minimal_kwargs())
        assert todo.id == "TODO-001"
        assert todo.status == TodoStatus.PENDING
        assert todo.priority == Priority.MEDIUM
        assert todo.actual_hours is None
        assert todo.blocked_by == []
        assert todo.blocking == []
        assert todo.assignee is None
        assert todo.labels == []
        assert todo.acceptance_criteria == []

    def test_creation_with_all_fields(self):
        todo = CrossRepoTodo(
            id="TODO-002",
            task="Implement feature",
            description="Detailed task",
            repo="repo-b",
            status=TodoStatus.IN_PROGRESS,
            priority=Priority.HIGH,
            created="2026-01-15T00:00:00",
            updated="2026-01-20T00:00:00",
            estimated_hours=16.5,
            actual_hours=12.0,
            blocked_by=["ISSUE-001"],
            blocking=["TODO-003"],
            assignee="bob",
            labels=["feature"],
            acceptance_criteria=["Tests pass", "Code reviewed"],
        )
        assert todo.status == TodoStatus.IN_PROGRESS
        assert todo.priority == Priority.HIGH
        assert todo.estimated_hours == 16.5
        assert todo.actual_hours == 12.0
        assert todo.blocked_by == ["ISSUE-001"]
        assert todo.blocking == ["TODO-003"]
        assert todo.acceptance_criteria == ["Tests pass", "Code reviewed"]

    def _make_todo(self, **overrides) -> CrossRepoTodo:
        kwargs = self._minimal_kwargs()
        kwargs.update(overrides)
        return CrossRepoTodo(**kwargs)

    def test_positive_estimated_hours_accepted(self):
        todo = self._make_todo(estimated_hours=0.1)
        assert todo.estimated_hours == 0.1

    def test_zero_estimated_hours_fails(self):
        with pytest.raises(ValidationError, match="Estimated hours must be positive"):
            self._make_todo(estimated_hours=0.0)

    def test_negative_estimated_hours_fails(self):
        with pytest.raises(ValidationError, match="Estimated hours must be positive"):
            self._make_todo(estimated_hours=-5.0)

    def test_large_estimated_hours_accepted(self):
        todo = self._make_todo(estimated_hours=1000.0)
        assert todo.estimated_hours == 1000.0

    def test_serialization_roundtrip(self):
        todo = CrossRepoTodo(**self._minimal_kwargs())
        data = todo.model_dump()
        restored = CrossRepoTodo(**data)
        assert restored.id == todo.id
        assert restored.task == todo.task


# ============================================================================
# DependencyValidation
# ============================================================================


class TestDependencyValidation:
    def test_all_defaults(self):
        dv = DependencyValidation()
        assert dv.command is None
        assert dv.expected_pattern is None
        assert dv.health_check is None
        assert dv.expected_status is None

    def test_command_and_pattern(self):
        dv = DependencyValidation(
            command="pip show foo",
            expected_pattern="^Version: 1\\.0",
        )
        assert dv.command == "pip show foo"
        assert dv.expected_pattern == "^Version: 1\\.0"
        assert dv.health_check is None
        assert dv.expected_status is None

    def test_health_check_fields(self):
        dv = DependencyValidation(
            health_check="http://localhost:8080/health",
            expected_status=200,
        )
        assert dv.health_check == "http://localhost:8080/health"
        assert dv.expected_status == 200

    def test_all_fields_populated(self):
        dv = DependencyValidation(
            command="curl -sf health",
            expected_pattern="ok",
            health_check="http://localhost:8080/health",
            expected_status=200,
        )
        assert dv.command == "curl -sf health"
        assert dv.expected_pattern == "ok"
        assert dv.health_check == "http://localhost:8080/health"
        assert dv.expected_status == 200


# ============================================================================
# Dependency
# ============================================================================


class TestDependency:
    def _minimal_kwargs(self) -> dict:
        return {
            "id": "DEP-001",
            "consumer": "app",
            "provider": "lib",
            "type": DependencyType.RUNTIME,
            "version_constraint": ">=1.0.0",
            "created": "2026-01-01T00:00:00",
            "updated": "2026-01-01T00:00:00",
            "notes": "App needs lib",
        }

    def test_creation_with_defaults(self):
        dep = Dependency(**self._minimal_kwargs())
        assert dep.id == "DEP-001"
        assert dep.consumer == "app"
        assert dep.provider == "lib"
        assert dep.type == DependencyType.RUNTIME
        assert dep.version_constraint == ">=1.0.0"
        assert dep.status == DependencyStatus.UNKNOWN
        assert dep.validation is None

    def test_creation_with_all_fields(self):
        validation = DependencyValidation(
            command="pip show lib", expected_pattern="^Version: 1\\."
        )
        dep = Dependency(
            id="DEP-002",
            consumer="fastblocks",
            provider="oneiric",
            type=DependencyType.DEVELOPMENT,
            version_constraint=">=0.2.0",
            status=DependencyStatus.SATISFIED,
            created="2026-01-15T00:00:00",
            updated="2026-01-20T00:00:00",
            notes="Detailed notes here",
            validation=validation,
        )
        assert dep.type == DependencyType.DEVELOPMENT
        assert dep.status == DependencyStatus.SATISFIED
        assert dep.validation.command == "pip show lib"

    def test_empty_consumer_fails(self):
        with pytest.raises(ValidationError, match="Repository nickname cannot be empty"):
            Dependency(
                id="DEP-003",
                consumer="",
                provider="lib",
                type=DependencyType.RUNTIME,
                version_constraint=">=1.0",
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
                notes="n",
            )

    def test_whitespace_consumer_fails(self):
        with pytest.raises(ValidationError, match="Repository nickname cannot be empty"):
            Dependency(
                id="DEP-004",
                consumer="   ",
                provider="lib",
                type=DependencyType.RUNTIME,
                version_constraint=">=1.0",
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
                notes="n",
            )

    def test_empty_provider_fails(self):
        with pytest.raises(ValidationError, match="Repository nickname cannot be empty"):
            Dependency(
                id="DEP-005",
                consumer="app",
                provider="",
                type=DependencyType.RUNTIME,
                version_constraint=">=1.0",
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
                notes="n",
            )

    def test_whitespace_provider_fails(self):
        with pytest.raises(ValidationError, match="Repository nickname cannot be empty"):
            Dependency(
                id="DEP-006",
                consumer="app",
                provider="   ",
                type=DependencyType.RUNTIME,
                version_constraint=">=1.0",
                created="2026-01-01T00:00:00",
                updated="2026-01-01T00:00:00",
                notes="n",
            )

    def _make_dep(self, **overrides) -> Dependency:
        kwargs = self._minimal_kwargs()
        kwargs.update(overrides)
        return Dependency(**kwargs)

    def test_all_dependency_types(self):
        for dep_type in DependencyType:
            dep = self._make_dep(type=dep_type)
            assert dep.type == dep_type

    def test_serialization_roundtrip(self):
        dep = Dependency(**self._minimal_kwargs())
        data = dep.model_dump()
        restored = Dependency(**data)
        assert restored.id == dep.id
        assert restored.consumer == dep.consumer
        assert restored.provider == dep.provider


# ============================================================================
# Example Constants
# ============================================================================


class TestExampleConstants:
    def test_example_issue_is_cross_repo_issue(self):
        assert isinstance(EXAMPLE_ISSUE, CrossRepoIssue)

    def test_example_issue_fields(self):
        assert EXAMPLE_ISSUE.id == "ISSUE-001"
        assert EXAMPLE_ISSUE.title == "Update all repos to Python 3.13"
        assert EXAMPLE_ISSUE.status == IssueStatus.IN_PROGRESS
        assert EXAMPLE_ISSUE.priority == Priority.HIGH
        assert EXAMPLE_ISSUE.severity == "migration"
        assert len(EXAMPLE_ISSUE.repos) == 4
        assert "mahavishnu" in EXAMPLE_ISSUE.repos
        assert EXAMPLE_ISSUE.assignee == "les"
        assert "migration" in EXAMPLE_ISSUE.labels
        assert "migration_guide" in EXAMPLE_ISSUE.metadata

    def test_example_todo_is_cross_repo_todo(self):
        assert isinstance(EXAMPLE_TODO, CrossRepoTodo)

    def test_example_todo_fields(self):
        assert EXAMPLE_TODO.id == "TODO-001"
        assert EXAMPLE_TODO.task == "Implement unified memory service"
        assert EXAMPLE_TODO.repo == "mahavishnu"
        assert EXAMPLE_TODO.status == TodoStatus.PENDING
        assert EXAMPLE_TODO.priority == Priority.HIGH
        assert EXAMPLE_TODO.estimated_hours == 24.0
        assert EXAMPLE_TODO.blocked_by == ["ISSUE-001"]
        assert EXAMPLE_TODO.blocking == ["TODO-002", "TODO-003"]
        assert len(EXAMPLE_TODO.acceptance_criteria) == 3

    def test_example_dependency_is_dependency(self):
        assert isinstance(EXAMPLE_DEPENDENCY, Dependency)

    def test_example_dependency_fields(self):
        assert EXAMPLE_DEPENDENCY.id == "DEP-001"
        assert EXAMPLE_DEPENDENCY.consumer == "fastblocks"
        assert EXAMPLE_DEPENDENCY.provider == "oneiric"
        assert EXAMPLE_DEPENDENCY.type == DependencyType.RUNTIME
        assert EXAMPLE_DEPENDENCY.version_constraint == ">=0.2.0"
        assert EXAMPLE_DEPENDENCY.status == DependencyStatus.SATISFIED
        assert EXAMPLE_DEPENDENCY.validation is not None
        assert EXAMPLE_DEPENDENCY.validation.command is not None
        assert EXAMPLE_DEPENDENCY.validation.expected_pattern is not None

    def test_examples_serialize_without_error(self):
        for example in [EXAMPLE_ISSUE, EXAMPLE_TODO, EXAMPLE_DEPENDENCY]:
            data = example.model_dump()
            assert isinstance(data, dict)
            assert "id" in data
