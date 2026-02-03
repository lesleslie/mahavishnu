"""Unit tests for Dead Letter Queue.

Tests DLQ functionality including:
- Task enqueue and retrieval
- Retry policy calculations
- Automatic retry processing
- Statistics and metrics
- Persistence and recovery
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.dead_letter_queue import (
    DeadLetterQueue,
    DeadLetterStatus,
    FailedTask,
    RetryPolicy,
)


class TestFailedTask:
    """Test FailedTask dataclass."""

    def test_create_failed_task(self):
        """Test creating a FailedTask."""
        task = FailedTask(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            failed_at=datetime.now(UTC),
        )

        assert task.task_id == "wf_123"
        assert task.error == "Test error"
        assert task.retry_count == 0
        assert task.status == DeadLetterStatus.PENDING

    def test_failed_task_to_dict(self):
        """Test converting FailedTask to dictionary."""
        now = datetime.now(UTC)
        task = FailedTask(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            failed_at=now,
            retry_policy=RetryPolicy.EXPONENTIAL,
        )

        task_dict = task.to_dict()

        assert task_dict["task_id"] == "wf_123"
        assert task_dict["retry_policy"] == "exponential"
        assert task_dict["status"] == "pending"
        assert "failed_at" in task_dict
        assert "updated_at" in task_dict

    def test_failed_task_from_dict(self):
        """Test creating FailedTask from dictionary."""
        task_dict = {
            "task_id": "wf_123",
            "task": {"type": "test"},
            "repos": ["/path/to/repo"],
            "error": "Test error",
            "failed_at": datetime.now(UTC).isoformat(),
            "retry_count": 1,
            "max_retries": 3,
            "retry_policy": "exponential",
            "next_retry_at": None,
            "status": "pending",
            "metadata": {},
            "error_category": None,
            "last_error": None,
            "total_attempts": 1,
        }

        task = FailedTask.from_dict(task_dict)

        assert task.task_id == "wf_123"
        assert task.retry_count == 1
        assert task.retry_policy == RetryPolicy.EXPONENTIAL


class TestRetryPolicyCalculations:
    """Test retry policy calculations."""

    def test_never_policy(self):
        """Test NEVER retry policy."""
        dlq = DeadLetterQueue(max_size=100)
        next_retry = dlq._calculate_next_retry(RetryPolicy.NEVER, 0)

        assert next_retry is None

    def test_immediate_policy(self):
        """Test IMMEDIATE retry policy."""
        dlq = DeadLetterQueue(max_size=100)
        now = datetime.now(UTC)
        next_retry = dlq._calculate_next_retry(RetryPolicy.IMMEDIATE, 0)

        assert next_retry is not None
        # Should be within 1 second of now
        assert abs((next_retry - now).total_seconds()) < 1

    def test_linear_policy(self):
        """Test LINEAR retry policy."""
        dlq = DeadLetterQueue(max_size=100)
        now = datetime.now(UTC)

        # First retry: 5 minutes
        next_retry_1 = dlq._calculate_next_retry(RetryPolicy.LINEAR, 0)
        assert abs((next_retry_1 - now).total_seconds() - 300) < 1  # 5 minutes

        # Second retry: 10 minutes
        next_retry_2 = dlq._calculate_next_retry(RetryPolicy.LINEAR, 1)
        assert abs((next_retry_2 - now).total_seconds() - 600) < 1  # 10 minutes

        # Third retry: 15 minutes
        next_retry_3 = dlq._calculate_next_retry(RetryPolicy.LINEAR, 2)
        assert abs((next_retry_3 - now).total_seconds() - 900) < 1  # 15 minutes

    def test_exponential_policy(self):
        """Test EXPONENTIAL retry policy."""
        dlq = DeadLetterQueue(max_size=100)
        now = datetime.now(UTC)

        # First retry: 1 minute (2^0)
        next_retry_1 = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 0)
        assert abs((next_retry_1 - now).total_seconds() - 60) < 1  # 1 minute

        # Second retry: 2 minutes (2^1)
        next_retry_2 = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 1)
        assert abs((next_retry_2 - now).total_seconds() - 120) < 1  # 2 minutes

        # Third retry: 4 minutes (2^2)
        next_retry_3 = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 2)
        assert abs((next_retry_3 - now).total_seconds() - 240) < 1  # 4 minutes

        # Capped at 60 minutes
        next_retry_capped = dlq._calculate_next_retry(RetryPolicy.EXPONENTIAL, 10)
        assert abs((next_retry_capped - now).total_seconds() - 3600) < 1  # 60 minutes


class TestDeadLetterQueue:
    """Test DeadLetterQueue functionality."""

    @pytest.fixture
    def dlq(self):
        """Create a DLQ instance for testing."""
        return DeadLetterQueue(max_size=100)

    @pytest.mark.asyncio
    async def test_enqueue_task(self, dlq):
        """Test enqueuing a failed task."""
        task = await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            retry_policy=RetryPolicy.EXPONENTIAL,
            max_retries=3,
        )

        assert task.task_id == "wf_123"
        assert task.status == DeadLetterStatus.PENDING
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert dlq._stats["enqueued_total"] == 1

    @pytest.mark.asyncio
    async def test_queue_full(self, dlq):
        """Test queue full error."""
        # Fill the queue
        for i in range(100):
            await dlq.enqueue(
                task_id=f"wf_{i}",
                task={"type": "test"},
                repos=["/path/to/repo"],
                error=f"Error {i}",
            )

        # Try to enqueue one more
        with pytest.raises(ValueError, match="Dead letter queue is full"):
            await dlq.enqueue(
                task_id="wf_overflow",
                task={"type": "test"},
                repos=["/path/to/repo"],
                error="Overflow",
            )

    @pytest.mark.asyncio
    async def test_get_task(self, dlq):
        """Test retrieving a specific task."""
        # Enqueue a task
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
        )

        # Get the task
        task = await dlq.get_task("wf_123")
        assert task is not None
        assert task.task_id == "wf_123"

        # Get non-existent task
        task = await dlq.get_task("wf_nonexistent")
        assert task is None

    @pytest.mark.asyncio
    async def test_list_tasks(self, dlq):
        """Test listing tasks."""
        # Enqueue tasks with different statuses
        await dlq.enqueue(
            task_id="wf_1",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Error 1",
        )

        # Modify one task's status
        dlq._queue[0].status = DeadLetterStatus.EXHAUSTED

        await dlq.enqueue(
            task_id="wf_2",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Error 2",
        )

        # List all tasks
        all_tasks = await dlq.list_tasks()
        assert len(all_tasks) == 2

        # Filter by status
        pending_tasks = await dlq.list_tasks(status=DeadLetterStatus.PENDING)
        assert len(pending_tasks) == 1

        exhausted_tasks = await dlq.list_tasks(status=DeadLetterStatus.EXHAUSTED)
        assert len(exhausted_tasks) == 1

    @pytest.mark.asyncio
    async def test_archive_task(self, dlq):
        """Test archiving a task."""
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
        )

        # Archive the task
        result = await dlq.archive_task("wf_123")
        assert result is True

        # Task should be removed from queue
        task = await dlq.get_task("wf_123")
        assert task is None

        # Stats should be updated
        assert dlq._stats["archived"] == 1

        # Archive non-existent task
        result = await dlq.archive_task("wf_nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_statistics(self, dlq):
        """Test getting queue statistics."""
        # Enqueue some tasks
        for i in range(5):
            await dlq.enqueue(
                task_id=f"wf_{i}",
                task={"type": "test"},
                repos=["/path/to/repo"],
                error=f"Error {i}",
                error_category="transient" if i % 2 == 0 else "permanent",
            )

        stats = await dlq.get_statistics()

        assert stats["queue_size"] == 5
        assert stats["max_size"] == 100
        assert stats["utilization_percent"] == 5.0
        assert stats["status_breakdown"]["pending"] == 5
        assert stats["error_categories"]["transient"] == 3  # 0, 2, 4
        assert stats["error_categories"]["permanent"] == 2  # 1, 3
        assert stats["lifetime_stats"]["enqueued_total"] == 5

    @pytest.mark.asyncio
    async def test_clear_all(self, dlq):
        """Test clearing all tasks."""
        # Enqueue some tasks
        for i in range(10):
            await dlq.enqueue(
                task_id=f"wf_{i}",
                task={"type": "test"},
                repos=["/path/to/repo"],
                error=f"Error {i}",
            )

        # Clear all
        count = await dlq.clear_all()
        assert count == 10

        # Queue should be empty
        stats = await dlq.get_statistics()
        assert stats["queue_size"] == 0


class TestRetryProcessor:
    """Test automatic retry processor."""

    @pytest.fixture
    def dlq(self):
        """Create a DLQ instance for testing."""
        return DeadLetterQueue(max_size=100)

    @pytest.mark.asyncio
    async def test_retry_processor_success(self, dlq):
        """Test retry processor with successful retry."""
        # Create a mock callback that succeeds
        callback = AsyncMock(return_value={"status": "success"})

        # Enqueue a task ready for immediate retry
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            retry_policy=RetryPolicy.IMMEDIATE,
            max_retries=3,
        )

        # Start processor
        await dlq.start_retry_processor(callback, check_interval_seconds=1)

        # Wait for processing
        await asyncio.sleep(2)

        # Stop processor
        await dlq.stop_retry_processor()

        # Task should be removed (successful retry)
        task = await dlq.get_task("wf_123")
        assert task is None

        # Stats should show success
        assert dlq._stats["retry_success"] == 1

    @pytest.mark.asyncio
    async def test_retry_processor_failure(self, dlq):
        """Test retry processor with failed retry."""
        # Create a mock callback that fails
        callback = AsyncMock(side_effect=Exception("Retry failed"))

        # Enqueue a task ready for immediate retry
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            retry_policy=RetryPolicy.IMMEDIATE,
            max_retries=3,
        )

        # Start processor
        await dlq.start_retry_processor(callback, check_interval_seconds=1)

        # Wait for processing
        await asyncio.sleep(2)

        # Stop processor
        await dlq.stop_retry_processor()

        # Task should still be in queue with incremented retry count
        task = await dlq.get_task("wf_123")
        assert task is not None
        assert task.retry_count == 1

        # Stats should show failure
        assert dlq._stats["retry_failed"] == 1

    @pytest.mark.asyncio
    async def test_retry_processor_exhausted(self, dlq):
        """Test retry processor when retries are exhausted."""
        # Create a mock callback that always fails
        callback = AsyncMock(side_effect=Exception("Always fails"))

        # Enqueue a task with only 1 retry allowed
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            retry_policy=RetryPolicy.IMMEDIATE,
            max_retries=1,
        )

        # Start processor
        await dlq.start_retry_processor(callback, check_interval_seconds=1)

        # Wait for processing (initial attempt + 1 retry)
        await asyncio.sleep(3)

        # Stop processor
        await dlq.stop_retry_processor()

        # Task should be marked as exhausted
        task = await dlq.get_task("wf_123")
        assert task is not None
        assert task.status == DeadLetterStatus.EXHAUSTED
        assert task.retry_count == 1

        # Stats should show exhausted
        assert dlq._stats["exhausted"] == 1

    @pytest.mark.asyncio
    async def test_manual_retry(self, dlq):
        """Test manual retry of a specific task."""
        # Create a mock callback
        callback = AsyncMock(return_value={"status": "success"})

        # Enqueue a task
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
        )

        # Start processor (required for callback)
        await dlq.start_retry_processor(callback, check_interval_seconds=1)

        # Manually retry
        result = await dlq.retry_task("wf_123")

        assert result["success"] is True
        assert result["task_id"] == "wf_123"

        # Task should be removed
        task = await dlq.get_task("wf_123")
        assert task is None

        # Stats should show manual retry
        assert dlq._stats["manually_retried"] == 1

        # Stop processor
        await dlq.stop_retry_processor()

    @pytest.mark.asyncio
    async def test_manual_retry_not_found(self, dlq):
        """Test manual retry of non-existent task."""
        # Create a mock callback
        callback = AsyncMock()

        # Start processor
        await dlq.start_retry_processor(callback, check_interval_seconds=1)

        # Try to retry non-existent task
        with pytest.raises(ValueError, match="not found in dead letter queue"):
            await dlq.retry_task("wf_nonexistent")

        # Stop processor
        await dlq.stop_retry_processor()

    @pytest.mark.asyncio
    async def test_manual_retry_no_callback(self, dlq):
        """Test manual retry without callback configured."""
        # Enqueue a task
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
        )

        # Try to retry without starting processor
        with pytest.raises(RuntimeError, match="No retry callback configured"):
            await dlq.retry_task("wf_123")


class TestPersistence:
    """Test OpenSearch persistence."""

    @pytest.mark.asyncio
    async def test_persist_task(self):
        """Test persisting task to OpenSearch."""
        # Mock OpenSearch client
        mock_client = AsyncMock()

        dlq = DeadLetterQueue(max_size=100, opensearch_client=mock_client)

        # Enqueue a task
        await dlq.enqueue(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
        )

        # Should have called index
        mock_client.index.assert_called_once()
        call_args = mock_client.index.call_args
        assert call_args[1]["id"] == "wf_123"
        assert call_args[1]["index"] == "mahavishnu_dlq"

    @pytest.mark.asyncio
    async def test_update_persistence(self):
        """Test updating persisted task."""
        # Mock OpenSearch client
        mock_client = AsyncMock()

        dlq = DeadLetterQueue(max_size=100, opensearch_client=mock_client)

        # Create a task
        task = FailedTask(
            task_id="wf_123",
            task={"type": "test"},
            repos=["/path/to/repo"],
            error="Test error",
            failed_at=datetime.now(UTC),
        )

        # Update persistence
        await dlq._update_task_persistence(task)

        # Should have called update
        mock_client.update.assert_called_once()
        call_args = mock_client.update.call_args
        assert call_args[1]["id"] == "wf_123"
        assert call_args[1]["index"] == "mahavishnu_dlq"

    @pytest.mark.asyncio
    async def test_remove_from_persistence(self):
        """Test removing task from persistence."""
        # Mock OpenSearch client
        mock_client = AsyncMock()

        dlq = DeadLetterQueue(max_size=100, opensearch_client=mock_client)

        # Remove from persistence
        await dlq._remove_from_persistence("wf_123")

        # Should have called delete
        mock_client.delete.assert_called_once()
        call_args = mock_client.delete.call_args
        assert call_args[1]["id"] == "wf_123"
        assert call_args[1]["index"] == "mahavishnu_dlq"
