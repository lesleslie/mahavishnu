"""Tests for ULID-based workflow execution tracking."""

import pytest
from mahavishnu.core.workflow_models import (
    WorkflowExecution,
    PoolExecution,
    WorkflowCheckpoint,
)


def test_workflow_execution_ulid_validation():
    """Should validate ULID format for workflow executions."""
    # Valid Crockford Base32 ULID (from Dhruva)
    valid_ulid = "01kh85b0x6000a9vb7cgn42ed8"

    execution = WorkflowExecution(
        execution_id=valid_ulid,
        workflow_name="test_workflow",
        status="running",
    )

    assert execution.execution_id == valid_ulid
    assert execution.workflow_name == "test_workflow"
    assert execution.status == "running"
    assert execution.start_time is not None
    assert execution.metadata == {}


def test_workflow_execution_invalid_ulid_raises():
    """Should raise ValueError for invalid ULID."""
    # Invalid ULID (wrong format)
    invalid_ulid = "not-a-valid-ulid"

    with pytest.raises(ValueError, match="Invalid ULID format"):
        WorkflowExecution(
            execution_id=invalid_ulid,
            workflow_name="test_workflow",
            status="running",
        )


def test_pool_execution_ulid_validation():
    """Should validate ULID format for pool executions."""
    # Valid Crockford Base32 ULID
    valid_ulid = "01kh85b0x70004j6njsda15ffh"

    execution = PoolExecution(
        execution_id=valid_ulid,
        pool_id="local_pool",
        operation="spawn",
        status="completed",
    )

    assert execution.execution_id == valid_ulid
    assert execution.pool_id == "local_pool"
    assert execution.operation == "spawn"
    assert execution.status == "completed"


def test_pool_execution_invalid_ulid_raises():
    """Should raise ValueError for invalid ULID."""
    invalid_ulid = "invalid-format"

    with pytest.raises(ValueError, match="Invalid ULID format"):
        PoolExecution(
            execution_id=invalid_ulid,
            pool_id="local_pool",
            operation="spawn",
            status="completed",
        )


def test_workflow_checkpoint_ulid_validation():
    """Should validate ULID format for workflow checkpoints."""
    # Valid Crockford Base32 ULID
    valid_ulid = "01kh85b0x6000a9vb7cgn42ed8"
    workflow_execution_id = "01ARZ3NDEKTS6PQRYF"

    checkpoint = WorkflowCheckpoint(
        checkpoint_id=valid_ulid,
        workflow_execution_id=workflow_execution_id,
        stage_name="quality_check",
        status="completed",
        result_data={"test": "data"},
    )

    assert checkpoint.checkpoint_id == valid_ulid
    assert checkpoint.workflow_execution_id == workflow_execution_id
    assert checkpoint.stage_name == "quality_check"
    assert checkpoint.status == "completed"
    assert checkpoint.result_data == {"test": "data"}


def test_workflow_checkpoint_invalid_ulid_raises():
    """Should raise ValueError for invalid ULID."""
    invalid_ulid = "not-valid-ulid"

    with pytest.raises(ValueError, match="Invalid ULID format"):
        WorkflowCheckpoint(
            checkpoint_id=invalid_ulid,
            workflow_execution_id="some_workflow_id",
            stage_name="test_stage",
            status="pending",
        )


def test_workflow_execution_is_complete():
    """Should correctly identify completed workflows."""
    # Generate valid ULID from Dhruva to ensure format compliance
    from dhruva import ULID
    valid_ulid = str(ULID())

    execution = WorkflowExecution(
        execution_id=valid_ulid,
        workflow_name="test_workflow",
        status="completed",
        end_time="2026-02-11T12:00:00",
    )

    assert execution.is_complete() is True


def test_workflow_execution_is_not_complete():
    """Should correctly identify incomplete workflows."""
    # Generate valid ULID from Dhruva to ensure format compliance
    from dhruva import ULID
    valid_ulid = str(ULID())

    execution = WorkflowExecution(
        execution_id=valid_ulid,
        workflow_name="test_workflow",
        status="running",
    )

    assert execution.is_complete() is False


def test_workflow_execution_duration():
    """Should calculate execution duration correctly."""
    from datetime import datetime
    from dhruva import ULID

    start = datetime(2026, 2, 11, 12, 0, 0)
    end = datetime(2026, 2, 11, 12, 5, 30, 0)
    valid_ulid = str(ULID())

    execution = WorkflowExecution(
        execution_id=valid_ulid,
        workflow_name="test_workflow",
        status="completed",
        start_time=start,
        end_time=end,
    )

    duration = execution.duration_seconds()
    assert duration == pytest.approx(330.0, 0.1)  # 5 minutes 30 seconds


def test_workflow_execution_no_end_time():
    """Should return None when end_time is missing."""
    from dhruva import ULID
    valid_ulid = str(ULID())

    execution = WorkflowExecution(
        execution_id=valid_ulid,
        workflow_name="test_workflow",
        status="running",
    )

    assert execution.duration_seconds() is None


def test_pool_execution_duration():
    """Should calculate pool execution duration correctly."""
    from datetime import datetime
    from dhruva import ULID

    start = datetime(2026, 2, 11, 12, 0, 0)
    end = datetime(2026, 2, 11, 12, 0, 30)
    valid_ulid = str(ULID())

    execution = PoolExecution(
        execution_id=valid_ulid,
        pool_id="local_pool",
        operation="spawn",
        status="completed",
        start_time=start,
        end_time=end,
    )

    duration = execution.duration_seconds()
    assert duration == pytest.approx(30.0, 0.1)  # 30 seconds


def test_pool_execution_no_duration():
    """Should return None when end_time is missing."""
    from dhruva import ULID
    valid_ulid = str(ULID())

    execution = PoolExecution(
        execution_id=valid_ulid,
        pool_id="local_pool",
        operation="spawn",
        status="running",
    )

    assert execution.duration_seconds() is None
