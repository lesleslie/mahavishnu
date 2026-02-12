"""Workflow execution tracking with ULID identifiers.

Provides models for tracking workflow executions and pool operations
with globally unique ULID identifiers for cross-system correlation.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

try:
    from oneiric.core.ulid import generate_config_id, is_config_ulid
except ImportError:
    # Try Dhruva directly (the actual ULID implementation)
    try:
        from dhruva import generate as generate_ulid
        from dhruva import is_ulid

        def generate_config_id() -> str:
            return generate_ulid()

        def is_config_ulid(value: str) -> bool:
            return is_ulid(value)
    except ImportError:
        # Last resort: timestamp-based ULID generation
        import time
        import os

        def generate_config_id() -> str:
            # Generate ULID-compatible timestamp-based ID
            timestamp_ms = int(time.time() * 1000)
            timestamp_bytes = timestamp_ms.to_bytes(6, byteorder='big')

            # Generate 10 bytes of randomness
            randomness = os.urandom(10)

            # Combine: 6 bytes timestamp + 10 bytes randomness = 16 bytes
            ulid_bytes = timestamp_bytes + randomness

            # Encode to Crockford Base32 (Dhruva's alphabet)
            alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
            b32_encode = lambda data: ''.join([
                alphabet[(b >> 35) & 31] for b in data
            ])

            return b32_encode(ulid_bytes)

        def is_config_ulid(value: str) -> bool:
            # Basic validation: 26 chars, alphanumeric
            if len(value) != 26:
                return False
            return value.isalnum() and value.islower()


class WorkflowExecution(BaseModel):
    """Workflow execution tracked with ULID.

    Provides globally unique identifier for workflow runs across
    the Mahavishnu orchestration system.
    """

    execution_id: str = Field(
        default_factory=generate_config_id,
        description="ULID workflow execution identifier"
    )
    workflow_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Workflow name"
    )
    status: str = Field(
        ...,
        description="Execution status (running, completed, failed, cancelled)"
    )
    start_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="Execution start timestamp"
    )
    end_time: Optional[datetime] = Field(
        None,
        description="Execution end timestamp"
    )
    iterations: int = Field(
        default=1,
        ge=1,
        description="Number of iterations performed"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional execution metadata"
    )

    @field_validator("execution_id")
    @classmethod
    def execution_id_must_be_ulid(cls, v: str) -> str:
        """Validate that execution_id is a valid ULID."""
        if not is_config_ulid(v):
            raise ValueError(f"Invalid ULID format for execution_id: {v}")
        return v

    def is_complete(self) -> bool:
        """Check if workflow execution is complete."""
        return self.status in ("completed", "failed", "cancelled")

    def duration_seconds(self) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds()
        return None


class PoolExecution(BaseModel):
    """Pool execution tracked with ULID.

    Provides globally unique identifier for pool operations across
    the Mahavishnu multi-pool orchestration system.
    """

    execution_id: str = Field(
        default_factory=generate_config_id,
        description="ULID pool execution identifier"
    )
    pool_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Pool identifier (e.g., 'local', 'session_buddy_pool_1')"
    )
    worker_id: Optional[str] = Field(
        None,
        description="Worker identifier (if applicable)"
    )
    operation: str = Field(
        ...,
        description="Operation type (spawn, execute, scale, close)"
    )
    status: str = Field(
        ...,
        description="Execution status (running, completed, failed)"
    )
    start_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="Execution start timestamp"
    )
    end_time: Optional[datetime] = Field(
        None,
        description="Execution end timestamp"
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional execution metadata"
    )

    @field_validator("execution_id")
    @classmethod
    def execution_id_must_be_ulid(cls, v: str) -> str:
        """Validate that execution_id is a valid ULID."""
        if not is_config_ulid(v):
            raise ValueError(f"Invalid ULID format for execution_id: {v}")
        return v

    def duration_seconds(self) -> Optional[float]:
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
        default_factory=generate_config_id,
        description="ULID checkpoint identifier"
    )
    workflow_execution_id: str = Field(
        ...,
        description="Parent workflow execution ID"
    )
    stage_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Workflow stage name"
    )
    status: str = Field(
        ...,
        description="Checkpoint status (pending, in_progress, completed, failed)"
    )
    result_data: dict = Field(
        default_factory=dict,
        description="Stage result data"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Checkpoint timestamp"
    )
    error_message: Optional[str] = Field(
        None,
        description="Error message if stage failed"
    )

    @field_validator("checkpoint_id")
    @classmethod
    def checkpoint_id_must_be_ulid(cls, v: str) -> str:
        """Validate that checkpoint_id is a valid ULID."""
        if not is_config_ulid(v):
            raise ValueError(f"Invalid ULID format for checkpoint_id: {v}")
        return v


# Export public API
__all__ = [
    "WorkflowExecution",
    "PoolExecution",
    "WorkflowCheckpoint",
]
