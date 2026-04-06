"""Tests for core/dlq_integration.py — DLQ integration with workflow execution."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from mahavishnu.core.dead_letter_queue import DeadLetterQueue, FailedTask, RetryPolicy
from mahavishnu.core.dlq_integration import (
    DLQIntegration,
    DLQIntegrationStrategy,
    create_dlq_integration,
)
from mahavishnu.core.errors import AdapterError
from mahavishnu.core.resilience import ErrorCategory


# ---------------------------------------------------------------------------
# DLQIntegrationStrategy
# ---------------------------------------------------------------------------


class TestDLQIntegrationStrategy:
    def test_all_members(self):
        assert DLQIntegrationStrategy.AUTOMATIC == "automatic"
        assert DLQIntegrationStrategy.SELECTIVE == "selective"
        assert DLQIntegrationStrategy.MANUAL == "manual"
        assert DLQIntegrationStrategy.DISABLED == "disabled"

    def test_from_string(self):
        assert DLQIntegrationStrategy("automatic") is DLQIntegrationStrategy.AUTOMATIC

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            DLQIntegrationStrategy("invalid")


# ---------------------------------------------------------------------------
# DLQIntegration.__init__
# ---------------------------------------------------------------------------


def _make_integration(strategy=DLQIntegrationStrategy.AUTOMATIC):
    """Create a DLQIntegration with mocked app/dlq."""
    mock_app = MagicMock()
    mock_app.error_recovery_manager = AsyncMock()
    mock_app.error_recovery_manager.classify_error = AsyncMock(
        return_value=ErrorCategory.TRANSIENT
    )
    mock_app.config = MagicMock()
    mock_app.config.dlq_default_max_retries = 3
    mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "ok"})

    mock_dlq = AsyncMock(spec=DeadLetterQueue)
    mock_dlq.enqueue = AsyncMock()

    integration = DLQIntegration(mock_app, mock_dlq)
    integration.set_strategy(strategy)
    return integration, mock_app, mock_dlq


class TestDLQIntegrationInit:
    def test_default_strategy(self):
        integration, _, _ = _make_integration()
        assert integration.get_strategy() == DLQIntegrationStrategy.AUTOMATIC

    def test_initial_stats(self):
        integration, _, _ = _make_integration()
        stats = integration._stats
        assert stats["workflows_executed"] == 0
        assert stats["workflows_failed"] == 0
        assert stats["auto_enqueued"] == 0


class TestSetStrategy:
    def test_set_strategy(self):
        integration, _, _ = _make_integration()
        integration.set_strategy(DLQIntegrationStrategy.DISABLED)
        assert integration.get_strategy() == DLQIntegrationStrategy.DISABLED

    def test_set_selective(self):
        integration, _, _ = _make_integration()
        integration.set_strategy(DLQIntegrationStrategy.SELECTIVE)
        assert integration.get_strategy() == DLQIntegrationStrategy.SELECTIVE


# ---------------------------------------------------------------------------
# should_enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestShouldEnqueue:
    async def test_disabled_never(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.DISABLED)
        assert await integration.should_enqueue(RuntimeError("err")) is False

    async def test_manual_never(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.MANUAL)
        assert await integration.should_enqueue(RuntimeError("err")) is False

    async def test_automatic_always(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.AUTOMATIC)
        assert await integration.should_enqueue(RuntimeError("err")) is True

    async def test_selective_transient(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.TRANSIENT
        )
        assert result is True

    async def test_selective_network(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.NETWORK
        )
        assert result is True

    async def test_selective_resource(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.RESOURCE
        )
        assert result is True

    async def test_selective_permanent(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.PERMANENT
        )
        assert result is False

    async def test_selective_permission(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.PERMISSION
        )
        assert result is False

    async def test_selective_validation(self):
        integration, _, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        result = await integration.should_enqueue(
            RuntimeError("err"), ErrorCategory.VALIDATION
        )
        assert result is False

    async def test_selective_classifies_when_no_category(self):
        integration, mock_app, _ = _make_integration(DLQIntegrationStrategy.SELECTIVE)
        mock_app.error_recovery_manager.classify_error = AsyncMock(
            return_value=ErrorCategory.TRANSIENT
        )
        result = await integration.should_enqueue(RuntimeError("err"))
        mock_app.error_recovery_manager.classify_error.assert_called_once()
        assert result is True


# ---------------------------------------------------------------------------
# determine_retry_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDetermineRetryPolicy:
    async def test_transient_exponential(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.TRANSIENT
        )
        assert policy == RetryPolicy.EXPONENTIAL

    async def test_network_exponential(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.NETWORK
        )
        assert policy == RetryPolicy.EXPONENTIAL

    async def test_resource_linear(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.RESOURCE
        )
        assert policy == RetryPolicy.LINEAR

    async def test_permission_never(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.PERMISSION
        )
        assert policy == RetryPolicy.NEVER

    async def test_validation_never(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.VALIDATION
        )
        assert policy == RetryPolicy.NEVER

    async def test_permanent_never(self):
        integration, _, _ = _make_integration()
        policy = await integration.determine_retry_policy(
            RuntimeError("err"), ErrorCategory.PERMANENT
        )
        assert policy == RetryPolicy.NEVER

    async def test_classifies_when_no_category(self):
        integration, mock_app, _ = _make_integration()
        mock_app.error_recovery_manager.classify_error = AsyncMock(
            return_value=ErrorCategory.NETWORK
        )
        policy = await integration.determine_retry_policy(RuntimeError("err"))
        mock_app.error_recovery_manager.classify_error.assert_called_once()


# ---------------------------------------------------------------------------
# enqueue_failed_workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnqueueFailedWorkflow:
    async def test_enqueue_success(self):
        integration, mock_app, mock_dlq = _make_integration()

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "task-1"
        mock_task.retry_policy = RetryPolicy.EXPONENTIAL
        mock_task.max_retries = 3
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        result = await integration.enqueue_failed_workflow(
            task_id="task-1",
            task={"type": "sweep"},
            repos=["/repo"],
            error=RuntimeError("boom"),
        )

        assert result is mock_task
        mock_dlq.enqueue.assert_called_once()
        assert integration._stats["auto_enqueued"] == 1

    async def test_enqueue_skipped_by_policy(self):
        integration, _, mock_dlq = _make_integration(DLQIntegrationStrategy.DISABLED)

        result = await integration.enqueue_failed_workflow(
            task_id="task-1",
            task={"type": "sweep"},
            repos=["/repo"],
            error=RuntimeError("boom"),
        )

        assert result is None
        assert integration._stats["skipped_permanent"] == 1

    async def test_enqueue_dlq_full(self):
        integration, _, mock_dlq = _make_integration()
        mock_dlq.enqueue = AsyncMock(side_effect=ValueError("DLQ full"))

        result = await integration.enqueue_failed_workflow(
            task_id="task-1",
            task={"type": "sweep"},
            repos=["/repo"],
            error=RuntimeError("boom"),
        )

        assert result is None

    async def test_enqueue_with_custom_retry_policy(self):
        integration, _, mock_dlq = _make_integration()

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "task-1"
        mock_task.retry_policy = RetryPolicy.LINEAR
        mock_task.max_retries = 5
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        result = await integration.enqueue_failed_workflow(
            task_id="task-1",
            task={"type": "sweep"},
            repos=["/repo"],
            error=RuntimeError("boom"),
            retry_policy=RetryPolicy.LINEAR,
            max_retries=5,
        )

        assert result is not None
        # Verify the custom policy was passed
        call_kwargs = mock_dlq.enqueue.call_args[1]
        assert call_kwargs["retry_policy"] == RetryPolicy.LINEAR
        assert call_kwargs["max_retries"] == 5

    async def test_enqueue_with_metadata(self):
        integration, _, mock_dlq = _make_integration()

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "task-1"
        mock_task.retry_policy = RetryPolicy.EXPONENTIAL
        mock_task.max_retries = 3
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        await integration.enqueue_failed_workflow(
            task_id="task-1",
            task={"type": "sweep"},
            repos=["/repo"],
            error=RuntimeError("boom"),
            metadata={"custom_key": "custom_val"},
        )

        call_kwargs = mock_dlq.enqueue.call_args[1]
        assert call_kwargs["metadata"]["custom_key"] == "custom_val"
        assert "enqueued_at" in call_kwargs["metadata"]


# ---------------------------------------------------------------------------
# execute_with_dlq
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteWithDlq:
    async def test_success(self):
        integration, mock_app, _ = _make_integration()
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})

        result = await integration.execute_with_dlq(
            task={"type": "sweep"}, adapter_name="prefect"
        )

        assert result["status"] == "done"
        assert integration._stats["workflows_executed"] == 1

    async def test_failure_enqueued(self):
        integration, mock_app, mock_dlq = _make_integration()
        mock_app.execute_workflow_parallel = AsyncMock(side_effect=RuntimeError("boom"))

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "task-1"
        mock_task.retry_policy = RetryPolicy.EXPONENTIAL
        mock_task.max_retries = 3
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        result = await integration.execute_with_dlq(
            task={"type": "sweep"}, adapter_name="prefect"
        )

        assert result["status"] == "failed"
        assert result["dlq_enqueued"] is True
        assert integration._stats["workflows_failed"] == 1

    async def test_failure_not_enqueued_raises(self):
        integration, mock_app, _ = _make_integration(DLQIntegrationStrategy.DISABLED)
        mock_app.execute_workflow_parallel = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(AdapterError, match="not enqueued"):
            await integration.execute_with_dlq(
                task={"type": "sweep"}, adapter_name="prefect"
            )

    async def test_uses_task_id_from_task(self):
        integration, mock_app, mock_dlq = _make_integration()
        mock_app.execute_workflow_parallel = AsyncMock(side_effect=RuntimeError("boom"))

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "my-custom-id"
        mock_task.retry_policy = RetryPolicy.EXPONENTIAL
        mock_task.max_retries = 3
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        result = await integration.execute_with_dlq(
            task={"type": "sweep", "id": "my-custom-id"}, adapter_name="prefect"
        )

        assert result["workflow_id"] == "my-custom-id"

    async def test_generates_workflow_id_if_missing(self):
        integration, mock_app, mock_dlq = _make_integration()
        mock_app.execute_workflow_parallel = AsyncMock(side_effect=RuntimeError("boom"))

        mock_task = MagicMock(spec=FailedTask)
        mock_task.task_id = "generated-id"
        mock_task.retry_policy = RetryPolicy.EXPONENTIAL
        mock_task.max_retries = 3
        mock_dlq.enqueue = AsyncMock(return_value=mock_task)

        result = await integration.execute_with_dlq(
            task={"type": "sweep"}, adapter_name="prefect"
        )

        # Should have generated a workflow ID with prefix "wf_"
        assert result["workflow_id"].startswith("wf_")


# ---------------------------------------------------------------------------
# get_statistics / reset_statistics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStatistics:
    async def test_initial_statistics(self):
        integration, _, _ = _make_integration()
        stats = await integration.get_statistics()
        assert stats["strategy"] == "automatic"
        assert stats["workflows_executed"] == 0
        assert stats["enqueue_rate"] == 0.0

    async def test_reset_statistics(self):
        integration, _, _ = _make_integration()
        integration._stats["workflows_executed"] = 42
        integration._stats["auto_enqueued"] = 10

        integration.reset_statistics()

        assert integration._stats["workflows_executed"] == 0
        assert integration._stats["auto_enqueued"] == 0


# ---------------------------------------------------------------------------
# create_dlq_integration factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateDlqIntegration:
    async def test_creates_with_existing_dlq(self):
        mock_app = MagicMock()
        mock_app.dlq = AsyncMock(spec=DeadLetterQueue)
        mock_app.config = MagicMock()
        mock_app.config.dlq_integration_strategy = "automatic"

        integration = await create_dlq_integration(mock_app)
        assert isinstance(integration, DLQIntegration)
        assert integration.get_strategy() == DLQIntegrationStrategy.AUTOMATIC

    async def test_invalid_strategy_uses_automatic(self):
        mock_app = MagicMock()
        mock_app.dlq = AsyncMock(spec=DeadLetterQueue)
        mock_app.config = MagicMock()
        mock_app.config.dlq_integration_strategy = "invalid_value"

        integration = await create_dlq_integration(mock_app)
        assert integration.get_strategy() == DLQIntegrationStrategy.AUTOMATIC
