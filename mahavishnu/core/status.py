"""Consolidated status enums for Mahavishnu.

This module provides a unified set of status enums to eliminate
duplication and ensure consistent state management across the codebase.

Design Principles:
- Single source of truth for common states
- Consistent naming conventions across domains
- String-based enums for database/API compatibility
- Clear state transition semantics

Migration Guide:
- Replace local status enums with imports from this module
- Use domain-specific enums (TaskStatus, WorkflowStatus, etc.)
- Values are unchanged for backward compatibility

Issue: MHV-008 - Status Enum Consolidation
"""

from enum import StrEnum


# =============================================================================
# TASK STATUS FAMILY
# =============================================================================


class TaskStatus(StrEnum):
    """Task lifecycle status.

    Standard lifecycle for discrete work items that can be
    created, worked on, and brought to completion.

    Used by: task_store, dependency_manager
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class IssueStatus(StrEnum):
    """Issue tracking status.

    Status for tracking issues across repositories.
    Extends task status with resolution states.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TodoStatus(StrEnum):
    """Todo item status.

    Status for tracking todo items within tasks or issues.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CoordinationStatus(StrEnum):
    """Multi-repo coordination status.

    Status for cross-repository coordination operations.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class MigrationStatus(StrEnum):
    """Migration status.

    Status for database and schema migrations.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class WorkerStatus(StrEnum):
    """Worker execution status.

    Status for worker instances in pools.
    """

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# =============================================================================
# WORKFLOW STATUS FAMILY
# =============================================================================


class WorkflowStatus(StrEnum):
    """Multi-step workflow status.

    Status for coordinating multiple tasks across repositories.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ExecutionStatus(StrEnum):
    """Execution outcome status.

    Lightweight status for recording execution results.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class PlanStatus(StrEnum):
    """Plan/roadmap status.

    Status for planning and roadmap management.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# =============================================================================
# RESOURCE STATUS FAMILY
# =============================================================================


class PoolStatus(StrEnum):
    """Pool resource status.

    Status for worker pool lifecycle management.
    """

    PENDING = "pending"
    INITIALIZING = "initializing"
    RUNNING = "running"
    SCALING = "scaling"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    FAILED = "failed"


class DeploymentStatus(StrEnum):
    """Deployment status.

    Status for deployment lifecycle management.
    """

    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"


class DatabaseStatus(StrEnum):
    """Database connection status.

    Status for database connection lifecycle.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# =============================================================================
# HEALTH STATUS FAMILY
# =============================================================================


class HealthStatus(StrEnum):
    """Health check status.

    Status for health assessments.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ReadinessStatus(StrEnum):
    """Production readiness status.

    Status for production readiness gate evaluations.
    """

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class DependencyStatus(StrEnum):
    """Dependency satisfaction status.

    Status for tracking whether dependencies are met.
    """

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"
    DEPRECATED = "deprecated"
    PENDING = "pending"
    FAILED = "failed"


# =============================================================================
# SPECIALIZED STATUS
# =============================================================================


class DeadLetterStatus(StrEnum):
    """Dead letter queue item status.

    Status for items in the dead letter queue.
    """

    PENDING = "pending"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class BlockingStatus(StrEnum):
    """Cross-repo blocker status.

    Status for blockers affecting multiple repositories.
    """

    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class SyncStatus(StrEnum):
    """Configuration sync status.

    Status for tracking configuration synchronization.
    """

    PENDING = "pending"
    APPROVED = "approved"
    SYNCED = "synced"
    FAILED = "failed"


class OnboardingStatus(StrEnum):
    """Repository onboarding status.

    Status for tracking repository setup progress.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    # Task status family
    "TaskStatus",
    "IssueStatus",
    "TodoStatus",
    "CoordinationStatus",
    "MigrationStatus",
    "WorkerStatus",
    # Workflow status family
    "WorkflowStatus",
    "ExecutionStatus",
    "PlanStatus",
    # Resource status family
    "PoolStatus",
    "DeploymentStatus",
    "DatabaseStatus",
    # Health status family
    "HealthStatus",
    "ReadinessStatus",
    "DependencyStatus",
    # Specialized status
    "DeadLetterStatus",
    "BlockingStatus",
    "SyncStatus",
    "OnboardingStatus",
]
