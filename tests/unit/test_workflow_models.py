"""Unit tests for workflow models (WorkflowExecution, PoolExecution, WorkflowCheckpoint).

These tests are self-contained and do not rely on external projects like oneiric or dhara.
Uses only the fallback generate_config_id and is_config_ulid from the module itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import ValidationError
import pytest

from mahavishnu.core.workflow_models import (
    PoolExecution,
    WorkflowCheckpoint,
    WorkflowExecution,
    generate_config_id,
    is_config_ulid,
)

# ============================================================================
# WorkflowExecution Tests
# ============================================================================


class TestWorkflowExecutionDefaults:
    """Test WorkflowExecution model defaults."""

    def test_generates_ulid_by_default(self):
        """execution_id is auto-generated as a valid ULID."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.execution_id is not None
        assert len(wf.execution_id) == 26
        assert is_config_ulid(wf.execution_id)

    def test_status_field_required(self):
        """status field is required (no default)."""
        with pytest.raises(ValidationError):
            WorkflowExecution(workflow_name="test")

    def test_workflow_name_required(self):
        """workflow_name is required."""
        with pytest.raises(ValidationError):
            WorkflowExecution(status="running")

    def test_iterations_defaults_to_one(self):
        """iterations field defaults to 1."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.iterations == 1

    def test_iterations_minimum_is_one(self):
        """iterations must be >= 1."""
        with pytest.raises(ValidationError):
            WorkflowExecution(workflow_name="test", status="running", iterations=0)

    def test_metadata_defaults_to_empty_dict(self):
        """metadata field defaults to empty dict."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.metadata == {}

    def test_end_time_defaults_to_none(self):
        """end_time is None until workflow completes."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.end_time is None


class TestWorkflowExecutionULIDValidation:
    """Test ULID validation on execution_id."""

    def test_rejects_invalid_ulid_format(self):
        """execution_id must be a valid ULID."""
        with pytest.raises(ValidationError, match="Invalid ULID format"):
            WorkflowExecution(
                execution_id="not-a-valid-ulid",
                workflow_name="test",
                status="running",
            )

    def test_rejects_short_execution_id(self):
        """execution_id rejects too-short values."""
        with pytest.raises(ValidationError):
            WorkflowExecution(execution_id="abc123", workflow_name="test", status="running")

    def test_accepts_valid_ulid(self):
        """Valid 26-char lowercase ULID is accepted."""
        valid_ulid = generate_config_id()
        wf = WorkflowExecution(
            execution_id=valid_ulid,
            workflow_name="test",
            status="running",
        )
        assert wf.execution_id == valid_ulid


class TestWorkflowExecutionMethods:
    """Test WorkflowExecution instance methods."""

    def test_is_complete_true_for_completed(self):
        """is_complete returns True when status is 'completed'."""
        wf = WorkflowExecution(workflow_name="test", status="completed")
        assert wf.is_complete() is True

    def test_is_complete_true_for_failed(self):
        """is_complete returns True when status is 'failed'."""
        wf = WorkflowExecution(workflow_name="test", status="failed")
        assert wf.is_complete() is True

    def test_is_complete_true_for_cancelled(self):
        """is_complete returns True when status is 'cancelled'."""
        wf = WorkflowExecution(workflow_name="test", status="cancelled")
        assert wf.is_complete() is True

    def test_is_complete_false_for_running(self):
        """is_complete returns False when status is 'running'."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.is_complete() is False

    def test_is_complete_false_for_pending(self):
        """is_complete returns False for intermediate statuses."""
        wf = WorkflowExecution(workflow_name="test", status="pending")
        assert wf.is_complete() is False

    def test_duration_seconds_returns_none_when_no_end_time(self):
        """duration_seconds returns None if end_time is not set."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        assert wf.duration_seconds() is None

    def test_duration_seconds_calculates_correctly(self):
        """duration_seconds returns correct delta between end and start."""
        start = datetime(2026, 5, 1, 12, 0, 0)
        end = datetime(2026, 5, 1, 12, 1, 30)
        wf = WorkflowExecution(
            workflow_name="test",
            status="completed",
            start_time=start,
            end_time=end,
        )
        assert wf.duration_seconds() == 90.0

    def test_duration_seconds_with_timedelta(self):
        """duration_seconds works with timedelta for end_time."""
        start = datetime.utcnow()
        end = start + timedelta(seconds=45)
        wf = WorkflowExecution(
            workflow_name="test",
            status="completed",
            start_time=start,
            end_time=end,
        )
        assert wf.duration_seconds() == 45.0


class TestWorkflowExecutionMetadata:
    """Test WorkflowExecution metadata handling."""

    def test_metadata_can_store_arbitrary_data(self):
        """metadata dict can hold custom fields."""
        wf = WorkflowExecution(
            workflow_name="test",
            status="running",
            metadata={"key": "value", "count": 42},
        )
        assert wf.metadata["key"] == "value"
        assert wf.metadata["count"] == 42

    def test_metadata_mutable_after_creation(self):
        """metadata dict is mutable (not frozen)."""
        wf = WorkflowExecution(workflow_name="test", status="running")
        wf.metadata["new_key"] = "new_value"
        assert wf.metadata["new_key"] == "new_value"


# ============================================================================
# PoolExecution Tests
# ============================================================================


class TestPoolExecutionDefaults:
    """Test PoolExecution model defaults."""

    def test_generates_ulid_by_default(self):
        """execution_id is auto-generated."""
        pe = PoolExecution(pool_id="local", operation="spawn", status="running")
        assert pe.execution_id is not None
        assert len(pe.execution_id) == 26

    def test_worker_id_defaults_to_none(self):
        """worker_id is None when not assigned."""
        pe = PoolExecution(pool_id="local", operation="spawn", status="running")
        assert pe.worker_id is None

    def test_metadata_defaults_to_empty_dict(self):
        """metadata field defaults to empty dict."""
        pe = PoolExecution(pool_id="local", operation="spawn", status="running")
        assert pe.metadata == {}


class TestPoolExecutionValidation:
    """Test PoolExecution field validation."""

    def test_pool_id_required(self):
        """pool_id is required."""
        with pytest.raises(ValidationError):
            PoolExecution(operation="spawn", status="running")

    def test_pool_id_min_length(self):
        """pool_id must be at least 1 character."""
        with pytest.raises(ValidationError):
            PoolExecution(pool_id="", operation="spawn", status="running")

    def test_operation_required(self):
        """operation is required."""
        with pytest.raises(ValidationError):
            PoolExecution(pool_id="local", status="running")

    def test_rejects_invalid_ulid_on_execution_id(self):
        """execution_id must be valid ULID."""
        with pytest.raises(ValidationError, match="Invalid ULID format"):
            PoolExecution(
                execution_id="bad-ulid",
                pool_id="local",
                operation="spawn",
                status="running",
            )


class TestPoolExecutionMethods:
    """Test PoolExecution instance methods."""

    def test_duration_seconds_returns_none_when_no_end_time(self):
        """duration_seconds returns None if end_time not set."""
        pe = PoolExecution(pool_id="local", operation="spawn", status="running")
        assert pe.duration_seconds() is None

    def test_duration_seconds_calculates_correctly(self):
        """duration_seconds calculates correct delta."""
        start = datetime(2026, 5, 1, 10, 0, 0)
        end = datetime(2026, 5, 1, 10, 2, 15)
        pe = PoolExecution(
            pool_id="local",
            operation="spawn",
            status="completed",
            start_time=start,
            end_time=end,
        )
        assert pe.duration_seconds() == 135.0


# ============================================================================
# WorkflowCheckpoint Tests
# ============================================================================


class TestWorkflowCheckpointDefaults:
    """Test WorkflowCheckpoint model defaults."""

    def test_generates_ulid_by_default(self):
        """checkpoint_id is auto-generated."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="pending",
        )
        assert cp.checkpoint_id is not None
        assert len(cp.checkpoint_id) == 26

    def test_result_data_defaults_to_empty_dict(self):
        """result_data field defaults to empty dict."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="pending",
        )
        assert cp.result_data == {}

    def test_error_message_defaults_to_none(self):
        """error_message is None when no error."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="pending",
        )
        assert cp.error_message is None


class TestWorkflowCheckpointValidation:
    """Test WorkflowCheckpoint field validation."""

    def test_workflow_execution_id_required(self):
        """workflow_execution_id is required."""
        with pytest.raises(ValidationError):
            WorkflowCheckpoint(stage_name="init", status="pending")

    def test_stage_name_required(self):
        """stage_name is required."""
        valid_workflow_id = generate_config_id()
        with pytest.raises(ValidationError):
            WorkflowCheckpoint(
                workflow_execution_id=valid_workflow_id,
                status="pending",
            )

    def test_stage_name_min_length(self):
        """stage_name must be at least 1 character."""
        valid_workflow_id = generate_config_id()
        with pytest.raises(ValidationError):
            WorkflowCheckpoint(
                workflow_execution_id=valid_workflow_id,
                stage_name="",
                status="pending",
            )

    def test_status_required(self):
        """status is required."""
        valid_workflow_id = generate_config_id()
        with pytest.raises(ValidationError):
            WorkflowCheckpoint(
                workflow_execution_id=valid_workflow_id,
                stage_name="init",
            )

    def test_rejects_invalid_ulid_on_checkpoint_id(self):
        """checkpoint_id must be valid ULID."""
        valid_workflow_id = generate_config_id()
        with pytest.raises(ValidationError, match="Invalid ULID format"):
            WorkflowCheckpoint(
                checkpoint_id="not-valid",
                workflow_execution_id=valid_workflow_id,
                stage_name="init",
                status="pending",
            )


class TestWorkflowCheckpointStatusValues:
    """Test WorkflowCheckpoint status field accepted values."""

    def test_accepts_pending_status(self):
        """pending is a valid status."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="pending",
        )
        assert cp.status == "pending"

    def test_accepts_in_progress_status(self):
        """in_progress is a valid status."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="in_progress",
        )
        assert cp.status == "in_progress"

    def test_accepts_completed_status(self):
        """completed is a valid status."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="completed",
        )
        assert cp.status == "completed"

    def test_accepts_failed_status(self):
        """failed is a valid status."""
        valid_workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            workflow_execution_id=valid_workflow_id,
            stage_name="init",
            status="failed",
            error_message="Something went wrong",
        )
        assert cp.status == "failed"
        assert cp.error_message == "Something went wrong"


# ============================================================================
# Edge Cases and Integration
# ============================================================================


class TestWorkflowExecutionEdgeCases:
    """Test edge cases for WorkflowExecution."""

    def test_workflow_name_max_length(self):
        """workflow_name has a 100 character max."""
        long_name = "a" * 100
        wf = WorkflowExecution(workflow_name=long_name, status="running")
        assert wf.workflow_name == long_name

        too_long_name = "a" * 101
        with pytest.raises(ValidationError):
            WorkflowExecution(workflow_name=too_long_name, status="running")

    def test_multiple_iterations(self):
        """iterations can be set to any value >= 1."""
        wf = WorkflowExecution(
            workflow_name="test",
            status="running",
            iterations=10,
        )
        assert wf.iterations == 10

    def test_empty_metadata_allowed(self):
        """Empty metadata dict is acceptable."""
        wf = WorkflowExecution(workflow_name="test", status="running", metadata={})
        assert wf.metadata == {}


class TestAllModelsWithCustomExecutionID:
    """Test all models accept custom valid ULIDs."""

    def test_workflow_execution_custom_ulid(self):
        """WorkflowExecution accepts custom ULID."""
        ulid = generate_config_id()
        wf = WorkflowExecution(
            execution_id=ulid,
            workflow_name="test",
            status="running",
        )
        assert wf.execution_id == ulid

    def test_pool_execution_custom_ulid(self):
        """PoolExecution accepts custom ULID."""
        ulid = generate_config_id()
        pe = PoolExecution(
            execution_id=ulid,
            pool_id="local",
            operation="execute",
            status="completed",
        )
        assert pe.execution_id == ulid

    def test_workflow_checkpoint_custom_ulid(self):
        """WorkflowCheckpoint accepts custom ULID."""
        ulid = generate_config_id()
        workflow_id = generate_config_id()
        cp = WorkflowCheckpoint(
            checkpoint_id=ulid,
            workflow_execution_id=workflow_id,
            stage_name="final",
            status="completed",
        )
        assert cp.checkpoint_id == ulid


class TestIsConfigULID:
    """Test the is_config_ulid validation function.

    Note: The fallback implementation uses isalnum() which is case-insensitive,
    so mixed-case strings may return True depending on the implementation.
    """

    def test_valid_ulid_returns_true(self):
        """Valid 26-char lowercase alnum returns True."""
        assert is_config_ulid("01kh85b0x6000a9vb7cgn42ed8") is True

    def test_rejects_short_strings(self):
        """Strings shorter than 26 return False."""
        assert is_config_ulid("01kh85b0x6") is False

    def test_rejects_long_strings(self):
        """Strings longer than 26 return False."""
        assert is_config_ulid("01kh85b0x6000a9vb7cgn42ed8xxxx") is False

    def test_rejects_strings_with_special_chars(self):
        """Non-alphanumeric characters return False."""
        assert is_config_ulid("01kh85b0x6000a9vb7cgn42ed!") is False

    def test_rejects_empty_string(self):
        """Empty string returns False."""
        assert is_config_ulid("") is False
