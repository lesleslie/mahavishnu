"""Workflow execution tracking with UUID7 identifiers.

Provides models for tracking workflow executions and pool operations
with globally unique UUID7 identifiers for cross-system correlation.
"""

from datetime import UTC, datetime

from oneiric.core.ids import generate_id, is_valid_id
from pydantic import BaseModel, Field, field_validator


def _now_utc() -> datetime:
    """Timezone-aware UTC now — replacement for deprecated datetime.utcnow()."""
    return datetime.now(UTC)


def generate_config_id() -> str:
    """Generate a new UUID7 for a config / workflow / pool execution record.

    Delegates to :func:`oneiric.core.ids.generate_id` (Python 3.14 stdlib
    ``uuid.uuid7`` wrapped for ecosystem use, per the cross-repo UUID7
    plan Phase 2).
    """
    return generate_id()


def is_uuid7_id(value: str) -> bool:
    """Return True iff ``value`` is a syntactically valid UUID7 hex string.

    This replaces the pre-2026-10-11 ``is_config_ulid`` alias. The
    contract is :func:`oneiric.core.ids.is_valid_id` (UUID7 only; the
    ULID read-time acceptance was removed in
    ``docs/plans/2026-10-12-ulid-surface-elimination.md`` T1).
    """
    return is_valid_id(value)


class WorkflowExecution(BaseModel):
    """Workflow execution tracked with UUID7.

    Provides globally unique identifier for workflow runs across
    the Mahavishnu orchestration system.
    """

    execution_id: str = Field(
        default_factory=generate_config_id, description="UUID7 workflow execution identifier"
    )
    workflow_name: str = Field(..., min_length=1, max_length=100, description="Workflow name")
    status: str = Field(..., description="Execution status (running, completed, failed, cancelled)")
    start_time: datetime = Field(default_factory=_now_utc, description="Execution start timestamp")
    end_time: datetime | None = Field(None, description="Execution end timestamp")
    iterations: int = Field(default=1, ge=1, description="Number of iterations performed")
    metadata: dict = Field(default_factory=dict, description="Additional execution metadata")

    @field_validator("execution_id")
    @classmethod
    def execution_id_must_be_uuid7(cls, v: str) -> str:
        """Validate that execution_id is a valid UUID7 hex string."""
        if not is_uuid7_id(v):
            raise ValueError(f"Invalid ID format for execution_id: {v}")
        return v

    def is_complete(self) -> bool:
        """Check if workflow execution is complete."""
        return self.status in ("completed", "failed", "cancelled")

    def duration_seconds(self) -> float | None:
        """Calculate execution duration in seconds."""
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds()
        return None


class PoolExecution(BaseModel):
    """Pool execution tracked with UUID7.

    Provides globally unique identifier for pool operations across
    the Mahavishnu multi-pool orchestration system.
    """

    execution_id: str = Field(
        default_factory=generate_config_id, description="UUID7 pool execution identifier"
    )
    pool_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Pool identifier (e.g., 'local', 'session_buddy_pool_1')",
    )
    worker_id: str | None = Field(None, description="Worker identifier (if applicable)")
    operation: str = Field(..., description="Operation type (spawn, execute, scale, close)")
    status: str = Field(..., description="Execution status (running, completed, failed)")
    start_time: datetime = Field(default_factory=_now_utc, description="Execution start timestamp")
    end_time: datetime | None = Field(None, description="Execution end timestamp")
    metadata: dict = Field(default_factory=dict, description="Additional execution metadata")

    @field_validator("execution_id")
    @classmethod
    def execution_id_must_be_uuid7(cls, v: str) -> str:
        """Validate that execution_id is a valid UUID7 hex string."""
        if not is_uuid7_id(v):
            raise ValueError(f"Invalid ID format for execution_id: {v}")
        return v

    def duration_seconds(self) -> float | None:
        """Calculate execution duration in seconds."""
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds()
        return None


class WorkflowCheckpoint(BaseModel):
    """Checkpoint data for workflow execution tracking.

    Stores intermediate results and state during workflow execution
    for resume capability and debugging.
    """

    checkpoint_id: str = Field(
        default_factory=generate_config_id, description="UUID7 checkpoint identifier"
    )
    workflow_execution_id: str = Field(..., description="Parent workflow execution ID")
    stage_name: str = Field(..., min_length=1, max_length=100, description="Workflow stage name")
    status: str = Field(
        ..., description="Checkpoint status (pending, in_progress, completed, failed)"
    )
    result_data: dict = Field(default_factory=dict, description="Stage result data")
    timestamp: datetime = Field(default_factory=_now_utc, description="Checkpoint timestamp")
    error_message: str | None = Field(None, description="Error message if stage failed")

    @field_validator("checkpoint_id")
    @classmethod
    def checkpoint_id_must_be_uuid7(cls, v: str) -> str:
        """Validate that checkpoint_id is a valid UUID7 hex string."""
        if not is_uuid7_id(v):
            raise ValueError(f"Invalid ID format for checkpoint_id: {v}")
        return v


# Export public API
__all__ = [
    "PoolExecution",
    "WorkflowCheckpoint",
    "WorkflowExecution",
]
