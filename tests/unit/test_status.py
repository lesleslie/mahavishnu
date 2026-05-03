"""Tests for consolidated status enums.

Tests cover:
- All 18 StrEnum classes have expected members
- String values are lowercase/underscore format (API compatible)
- Membership testing works correctly
- Enum comparison behavior
- __all__ exports completeness
"""

from mahavishnu.core.status import (
    BlockingStatus,
    CoordinationStatus,
    DatabaseStatus,
    DeadLetterStatus,
    DependencyStatus,
    DeploymentStatus,
    ExecutionStatus,
    HealthStatus,
    IssueStatus,
    MigrationStatus,
    OnboardingStatus,
    PlanStatus,
    PoolStatus,
    ReadinessStatus,
    SyncStatus,
    TaskStatus,
    TodoStatus,
    WorkerStatus,
    WorkflowStatus,
    __all__,
)

# ============================================================================
# Task Status Family
# ============================================================================


class TestTaskStatus:
    def test_has_pending(self):
        assert TaskStatus.PENDING == "pending"

    def test_has_in_progress(self):
        assert TaskStatus.IN_PROGRESS == "in_progress"

    def test_has_completed(self):
        assert TaskStatus.COMPLETED == "completed"

    def test_has_failed(self):
        assert TaskStatus.FAILED == "failed"

    def test_has_cancelled(self):
        assert TaskStatus.CANCELLED == "cancelled"

    def test_has_blocked(self):
        assert TaskStatus.BLOCKED == "blocked"

    def test_member_count(self):
        assert len(TaskStatus) == 6

    def test_membership(self):
        assert "pending" in list(TaskStatus)
        assert "unknown" not in list(TaskStatus)


class TestIssueStatus:
    def test_has_resolved(self):
        assert IssueStatus.RESOLVED == "resolved"

    def test_has_closed(self):
        assert IssueStatus.CLOSED == "closed"

    def test_member_count(self):
        assert len(IssueStatus) == 5


class TestTodoStatus:
    def test_values(self):
        expected = {"pending", "in_progress", "blocked", "completed", "cancelled"}
        assert set(TodoStatus) == expected

    def test_member_count(self):
        assert len(TodoStatus) == 5


class TestCoordinationStatus:
    def test_has_rolled_back(self):
        assert CoordinationStatus.ROLLED_BACK == "rolled_back"

    def test_member_count(self):
        assert len(CoordinationStatus) == 5


class TestMigrationStatus:
    def test_has_running(self):
        assert MigrationStatus.RUNNING == "running"

    def test_has_rolled_back(self):
        assert MigrationStatus.ROLLED_BACK == "rolled_back"

    def test_member_count(self):
        assert len(MigrationStatus) == 5


class TestWorkerStatus:
    def test_has_starting(self):
        assert WorkerStatus.STARTING == "starting"

    def test_has_timeout(self):
        assert WorkerStatus.TIMEOUT == "timeout"

    def test_member_count(self):
        assert len(WorkerStatus) == 7


# ============================================================================
# Workflow Status Family
# ============================================================================


class TestWorkflowStatus:
    def test_has_timeout(self):
        assert WorkflowStatus.TIMEOUT == "timeout"

    def test_member_count(self):
        assert len(WorkflowStatus) == 6


class TestExecutionStatus:
    def test_values(self):
        expected = {"success", "failure", "timeout", "cancelled"}
        assert set(ExecutionStatus) == expected

    def test_member_count(self):
        assert len(ExecutionStatus) == 4


class TestPlanStatus:
    def test_has_draft(self):
        assert PlanStatus.DRAFT == "draft"

    def test_has_on_hold(self):
        assert PlanStatus.ON_HOLD == "on_hold"

    def test_member_count(self):
        assert len(PlanStatus) == 5


# ============================================================================
# Resource Status Family
# ============================================================================


class TestPoolStatus:
    def test_has_initializing(self):
        assert PoolStatus.INITIALIZING == "initializing"

    def test_has_scaling(self):
        assert PoolStatus.SCALING == "scaling"

    def test_has_degraded(self):
        assert PoolStatus.DEGRADED == "degraded"

    def test_member_count(self):
        assert len(PoolStatus) == 7


class TestDeploymentStatus:
    def test_has_deploying(self):
        assert DeploymentStatus.DEPLOYING == "deploying"

    def test_has_rolling_back(self):
        assert DeploymentStatus.ROLLING_BACK == "rolling_back"

    def test_member_count(self):
        assert len(DeploymentStatus) == 6


class TestDatabaseStatus:
    def test_values(self):
        expected = {"disconnected", "connecting", "connected", "error"}
        assert set(DatabaseStatus) == expected

    def test_member_count(self):
        assert len(DatabaseStatus) == 4


# ============================================================================
# Health Status Family
# ============================================================================


class TestHealthStatus:
    def test_values(self):
        expected = {"healthy", "degraded", "unhealthy"}
        assert set(HealthStatus) == expected

    def test_member_count(self):
        assert len(HealthStatus) == 3


class TestReadinessStatus:
    def test_values(self):
        expected = {"pass", "fail", "warn"}
        assert set(ReadinessStatus) == expected

    def test_member_count(self):
        assert len(ReadinessStatus) == 3


class TestDependencyStatus:
    def test_has_satisfied(self):
        assert DependencyStatus.SATISFIED == "satisfied"

    def test_has_deprecated(self):
        assert DependencyStatus.DEPRECATED == "deprecated"

    def test_member_count(self):
        assert len(DependencyStatus) == 7


# ============================================================================
# Specialized Status
# ============================================================================


class TestDeadLetterStatus:
    def test_has_retrying(self):
        assert DeadLetterStatus.RETRYING == "retrying"

    def test_has_exhausted(self):
        assert DeadLetterStatus.EXHAUSTED == "exhausted"

    def test_has_archived(self):
        assert DeadLetterStatus.ARCHIVED == "archived"

    def test_member_count(self):
        assert len(DeadLetterStatus) == 5


class TestBlockingStatus:
    def test_values(self):
        expected = {"active", "resolved", "escalated"}
        assert set(BlockingStatus) == expected

    def test_member_count(self):
        assert len(BlockingStatus) == 3


class TestSyncStatus:
    def test_has_approved(self):
        assert SyncStatus.APPROVED == "approved"

    def test_has_synced(self):
        assert SyncStatus.SYNCED == "synced"

    def test_member_count(self):
        assert len(SyncStatus) == 4


class TestOnboardingStatus:
    def test_has_not_started(self):
        assert OnboardingStatus.NOT_STARTED == "not_started"

    def test_has_skipped(self):
        assert OnboardingStatus.SKIPPED == "skipped"

    def test_member_count(self):
        assert len(OnboardingStatus) == 4


# ============================================================================
# Cross-Enum Tests
# ============================================================================


class TestEnumBehavior:
    """Test StrEnum behavior across all enums."""

    def test_all_enums_are_strings(self):
        """Every member value should be a string."""
        enums = [
            TaskStatus,
            IssueStatus,
            TodoStatus,
            CoordinationStatus,
            MigrationStatus,
            WorkerStatus,
            WorkflowStatus,
            ExecutionStatus,
            PlanStatus,
            PoolStatus,
            DeploymentStatus,
            DatabaseStatus,
            HealthStatus,
            ReadinessStatus,
            DependencyStatus,
            DeadLetterStatus,
            BlockingStatus,
            SyncStatus,
            OnboardingStatus,
        ]
        for enum_cls in enums:
            for member in enum_cls:
                assert isinstance(member.value, str), (
                    f"{enum_cls.__name__}.{member.name} value is not str"
                )
                assert isinstance(member, str), (
                    f"{enum_cls.__name__}.{member.name} is not a str instance"
                )

    def test_all_values_lowercase(self):
        """All enum values should be lowercase."""
        enums = __all__
        import mahavishnu.core.status as mod

        for name in enums:
            enum_cls = getattr(mod, name)
            for member in enum_cls:
                assert member.value == member.value.lower(), (
                    f"{name}.{member.name} value '{member.value}' is not lowercase"
                )

    def test_comparison_with_strings(self):
        """StrEnum members should compare equal to their string values."""
        assert TaskStatus.PENDING == "pending"
        assert HealthStatus.HEALTHY == "healthy"
        assert DatabaseStatus.CONNECTED == "connected"

    def test_hashable(self):
        """Enum members should be usable in sets and as dict keys."""
        statuses = {TaskStatus.PENDING, TaskStatus.COMPLETED}
        assert TaskStatus.PENDING in statuses
        assert TaskStatus.FAILED not in statuses

        mapping = {HealthStatus.HEALTHY: "ok", HealthStatus.UNHEALTHY: "bad"}
        assert mapping[HealthStatus.HEALTHY] == "ok"


class TestAllExports:
    """Test __all__ completeness."""

    def test_all_exports_count(self):
        assert len(__all__) == 19

    def test_all_exports_importable(self):
        import mahavishnu.core.status as mod

        for name in __all__:
            assert hasattr(mod, name), f"{name} in __all__ but not importable"
            assert hasattr(getattr(mod, name), "__members__"), f"{name} is not an enum"

    def test_total_enum_count(self):
        """Should have exactly 19 enum classes (18 in __all__)."""
        from enum import StrEnum

        import mahavishnu.core.status as mod

        enum_count = sum(
            1
            for name in dir(mod)
            if isinstance(getattr(mod, name, None), type)
            and issubclass(getattr(mod, name), StrEnum)
            and getattr(mod, name) is not StrEnum
        )
        assert enum_count == 19
