"""Tests for metrics collector and ExecutionTracker."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from mahavishnu.core.metrics_collector import (
    ExecutionTracker,
    ExecutionMetrics,
    SamplingStrategy,
    get_execution_tracker,
    initialize_execution_tracker,
)
from mahavishnu.core.metrics_schema import (
    AdapterType,
    TaskType,
    ExecutionStatus,
)


@pytest.fixture
async def tracker():
    """Provide a fresh ExecutionTracker for each test."""
    tracker = ExecutionTracker(
        sampling_strategy=SamplingStrategy.FULL,
        batch_size=10,  # Small batch size for testing
        aggregate_interval_ms=1000,  # Fast aggregation for tests
    )
    await tracker.start()
    yield tracker
    await tracker.stop()


class TestExecutionMetrics:
    """Test ExecutionMetrics dataclass."""

    def test_initialization(self):
        """ExecutionMetrics should initialize with empty collections."""
        metrics = ExecutionMetrics()

        assert len(metrics.active_executions) == 0
        assert len(metrics.completed_executions) == 0
        assert len(metrics.adapter_attempts) == 0
        assert len(metrics.task_type_counts) == 0

    def test_track_task_type_counts(self):
        """Should track task type execution counts."""
        metrics = ExecutionMetrics()

        metrics.task_type_counts["workflow"] += 5
        metrics.task_type_counts["ai_task"] += 3

        assert metrics.task_type_counts["workflow"] == 5
        assert metrics.task_type_counts["ai_task"] == 3

    def test_adapter_attempts_tracking(self):
        """Should track adapter success/failure attempts."""
        metrics = ExecutionMetrics()

        metrics.adapter_attempts["prefect"]["success"] += 10
        metrics.adapter_attempts["prefect"]["failure"] += 2
        metrics.adapter_attempts["agno"]["success"] += 8

        assert metrics.adapter_attempts["prefect"]["success"] == 10
        assert metrics.adapter_attempts["prefect"]["failure"] == 2
        assert metrics.adapter_attempts["agno"]["success"] == 8

    def test_get_success_rate_sufficient_samples(self):
        """Should calculate success rate with sufficient samples."""
        metrics = ExecutionMetrics()
        metrics.adapter_attempts["prefect"]["success"] = 8
        metrics.adapter_attempts["prefect"]["failure"] = 2

        rate = metrics.get_success_rate(AdapterType.PREFECT, min_samples=5)

        assert rate == 0.8  # 8/10 = 0.8

    def test_get_success_rate_insufficient_samples(self):
        """Should return None with insufficient samples."""
        metrics = ExecutionMetrics()
        metrics.adapter_attempts["prefect"]["success"] = 2
        metrics.adapter_attempts["prefect"]["failure"] = 1

        rate = metrics.get_success_rate(AdapterType.PREFECT, min_samples=10)

        assert rate is None  # Only 3 samples, need 10

    def test_get_success_rate_zero_attempts(self):
        """Should return 0.0 when no attempts."""
        metrics = ExecutionMetrics()

        rate = metrics.get_success_rate(AdapterType.AGNO, min_samples=0)

        assert rate == 0.0


class TestExecutionTrackerInitialization:
    """Test ExecutionTracker initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_initialization_default_params(self):
        """Should initialize with default parameters."""
        tracker = ExecutionTracker()

        assert tracker.sampling_strategy == SamplingStrategy.FULL
        assert tracker.sampling_rate == 1.0
        assert tracker.batch_size == 100
        assert tracker.storage_client is None

    @pytest.mark.asyncio
    async def test_initialization_custom_params(self):
        """Should initialize with custom parameters."""
        tracker = ExecutionTracker(
            sampling_strategy=SamplingStrategy.HIGH_FREQUENCY,
            sampling_rate=0.1,
            batch_size=50,
            batch_timeout_ms=3000,
        )

        assert tracker.sampling_strategy == SamplingStrategy.HIGH_FREQUENCY
        assert tracker.sampling_rate == 0.1
        assert tracker.batch_size == 50
        assert tracker.batch_timeout_ms == 3000

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, tracker):
        """Should start and stop cleanly."""
        assert tracker._aggregate_task is not None
        assert not tracker._shutdown_event.is_set()

        await tracker.stop()

        assert tracker._aggregate_task.cancelled() or tracker._aggregate_task.done()
        assert tracker._shutdown_event.is_set()


class TestSamplingStrategy:
    """Test sampling strategy decision making."""

    @pytest.mark.asyncio
    async def test_full_sampling_always_true(self, tracker):
        """FULL sampling should always return True."""
        assert tracker._should_sample(TaskType.WORKFLOW)
        assert tracker._should_sample(TaskType.AI_TASK)
        assert tracker._should_sample(TaskType.RAG_QUERY)

    @pytest.mark.asyncio
    async def test_low_frequency_sampling_always_true(self, tracker):
        """LOW_FREQUENCY sampling should always return True."""
        tracker.sampling_strategy = SamplingStrategy.LOW_FREQUENCY

        assert tracker._should_sample(TaskType.WORKFLOW)
        assert tracker._should_sample(TaskType.AI_TASK)

    @pytest.mark.asyncio
    async def test_high_frequency_sampling(self, tracker):
        """HIGH_FREQUENCY sampling should use sampling rate."""
        tracker.sampling_strategy = SamplingStrategy.HIGH_FREQUENCY
        tracker.sampling_rate = 0.5  # 50% sampling

        # Mock random to be predictable
        with patch("random.random", return_value=0.3):
            # 0.3 < 0.5, should sample
            assert tracker._should_sample(TaskType.WORKFLOW) is True

        with patch("random.random", return_value=0.7):
            # 0.7 > 0.5, should not sample
            assert tracker._should_sample(TaskType.WORKFLOW) is False

    @pytest.mark.asyncio
    async def test_adaptive_sampling_low_frequency(self, tracker):
        """ADAPTIVE sampling should track low-frequency tasks."""
        tracker.sampling_strategy = SamplingStrategy.ADAPTIVE

        # Task type has < 100 executions
        tracker._metrics.task_type_counts["workflow"] = 50

        assert tracker._should_sample(TaskType.WORKFLOW) is True

    @pytest.mark.asyncio
    async def test_adaptive_sampling_high_frequency(self, tracker):
        """ADAPTIVE sampling should sample high-frequency tasks."""
        tracker.sampling_strategy = SamplingStrategy.ADAPTIVE

        # Task type has > 100 executions
        tracker._metrics.task_type_counts["ai_task"] = 150

        # Should sample every 10th (150 % 10 == 0)
        assert tracker._should_sample(TaskType.AI_TASK) is True

        # 151 % 10 != 0, should not sample
        tracker._metrics.task_type_counts["ai_task"] = 151
        assert tracker._should_sample(TaskType.AI_TASK) is False


class TestExecutionRecording:
    """Test execution start/end recording."""

    @pytest.mark.asyncio
    async def test_record_execution_start(self, tracker):
        """Should record execution start and return ULID or UUID."""
        execution_id = await tracker.record_execution_start(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            repos=["/path/to/repo"],
        )

        assert execution_id is not None
        # ULID is 26 chars, UUID fallback is 32 chars
        assert len(execution_id) in (26, 32)
        assert execution_id in tracker._metrics.active_executions

        active = tracker._metrics.active_executions[execution_id]
        assert active["adapter"] == "prefect"
        assert active["task_type"] == "workflow"
        assert active["repos"] == ["/path/to/repo"]
        assert "start_ts" in active

    @pytest.mark.asyncio
    async def test_record_execution_end_success(self, tracker):
        """Should record successful execution end."""
        # First, start an execution
        execution_id = await tracker.record_execution_start(
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            repos=["/path/to/repo"],
        )

        # Then record successful completion
        await tracker.record_execution_end(
            execution_id=execution_id,
            success=True,
            status=ExecutionStatus.SUCCESS,
            latency_ms=1500,
            cost_usd=0.002,
        )

        # Execution should be moved from active to completed
        assert execution_id not in tracker._metrics.active_executions
        assert len(tracker._metrics.completed_executions) == 1

        record = tracker._metrics.completed_executions[0]
        assert record.execution_id == execution_id
        assert record.status == ExecutionStatus.SUCCESS
        assert record.latency_ms == 1500
        assert record.cost_usd == 0.002

        # Adapter attempts should be updated
        assert tracker._metrics.adapter_attempts["agno"]["success"] == 1

    @pytest.mark.asyncio
    async def test_record_execution_end_failure(self, tracker):
        """Should record failed execution end."""
        execution_id = await tracker.record_execution_start(
            adapter=AdapterType.LLAMAINDEX,
            task_type=TaskType.RAG_QUERY,
            repos=["/path/to/repo"],
        )

        await tracker.record_execution_end(
            execution_id=execution_id,
            success=False,
            status=ExecutionStatus.FAILURE,
            latency_ms=5000,
            error_type="timeout",
            error_message="Query timed out after 5 seconds",
        )

        record = tracker._metrics.completed_executions[0]
        assert record.status == ExecutionStatus.FAILURE
        assert record.error_type == "timeout"
        assert record.error_message == "Query timed out after 5 seconds"

        # Adapter attempts should track failure
        assert tracker._metrics.adapter_attempts["llamaindex"]["failure"] == 1

    @pytest.mark.asyncio
    async def test_record_execution_calculates_latency(self, tracker):
        """Should calculate latency if not provided."""
        execution_id = await tracker.record_execution_start(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            repos=["/path/to/repo"],
        )

        # Wait a bit to simulate execution
        await asyncio.sleep(0.01)

        # Record end without latency (should be calculated)
        await tracker.record_execution_end(
            execution_id=execution_id,
            success=True,
        )

        record = tracker._metrics.completed_executions[0]
        assert record.latency_ms is not None
        assert record.latency_ms >= 10  # At least 10ms passed

    @pytest.mark.asyncio
    async def test_record_execution_end_not_found(self, tracker):
        """Should handle execution_id not found gracefully."""
        # Don't start execution, just try to end
        await tracker.record_execution_end(
            execution_id="nonexistent_ulid",
            success=True,
        )

        # Should not crash, just log debug message
        assert len(tracker._metrics.completed_executions) == 0


class TestBatchWrites:
    """Test async batch write functionality."""

    @pytest.mark.asyncio
    async def test_batch_write_on_threshold(self, tracker):
        """Should flush when batch size reached."""
        tracker.batch_size = 3  # Set small threshold

        # Record 3 executions
        for i in range(3):
            execution_id = await tracker.record_execution_start(
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                repos=["/path/to/repo"],
            )
            await tracker.record_execution_end(execution_id, success=True)

        # Batch should be flushed (size >= 3)
        assert len(tracker._metrics.completed_executions) == 0

    @pytest.mark.asyncio
    async def test_flush_batch_writes_records(self, tracker):
        """Flush should write pending records to storage."""
        # Add some records
        for i in range(5):
            execution_id = await tracker.record_execution_start(
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                repos=["/path/to/repo"],
            )
            await tracker.record_execution_end(execution_id, success=True)

        # Flush manually
        result = await tracker._flush_batch()

        assert result["status"] == "success"
        assert result["written"] == 5
        assert len(tracker._metrics.completed_executions) == 0


class TestStatisticsRetrieval:
    """Test statistics retrieval methods."""

    @pytest.mark.asyncio
    async def test_get_adapter_stats(self, tracker):
        """Should return adapter statistics."""
        # Add some data
        tracker._metrics.adapter_attempts["prefect"]["success"] = 8
        tracker._metrics.adapter_attempts["prefect"]["failure"] = 2

        stats = await tracker.get_adapter_stats(AdapterType.PREFECT)

        assert stats is not None
        assert stats["adapter"] == "prefect"
        assert stats["success_rate"] == 0.8
        assert stats["total_executions"] == 10
        assert stats["successful_executions"] == 8
        assert stats["failed_executions"] == 2

    @pytest.mark.asyncio
    async def test_get_adapter_stats_insufficient_data(self, tracker):
        """Should return None with insufficient data."""
        # Only 3 attempts total
        tracker._metrics.adapter_attempts["agno"]["success"] = 2
        tracker._metrics.adapter_attempts["agno"]["failure"] = 1

        stats = await tracker.get_adapter_stats(AdapterType.AGNO)

        assert stats is None

    @pytest.mark.asyncio
    async def test_get_task_type_stats(self, tracker):
        """Should return task type statistics."""
        tracker._metrics.task_type_counts["workflow"] = 25
        tracker._metrics.task_type_counts["ai_task"] = 10

        workflow_stats = await tracker.get_task_type_stats(TaskType.WORKFLOW)
        ai_stats = await tracker.get_task_type_stats(TaskType.AI_TASK)

        assert workflow_stats["execution_count"] == 25
        assert ai_stats["execution_count"] == 10

    @pytest.mark.asyncio
    async def test_get_recent_executions(self, tracker):
        """Should return recent execution records."""
        # Add 5 completed records
        for i in range(5):
            execution_id = await tracker.record_execution_start(
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                repos=["/path/to/repo"],
            )
            await tracker.record_execution_end(
                execution_id=execution_id,
                success=True,
                latency_ms=1000 * (i + 1),
            )

        # Get recent 3
        recent = await tracker.get_recent_executions(limit=3)

        assert len(recent) == 3
        # Should be most recent (last 3 added): 3000, 4000, 5000
        assert recent[0].latency_ms == 3000
        assert recent[1].latency_ms == 4000
        assert recent[2].latency_ms == 5000


class TestHealthStatus:
    """Test health status reporting."""

    @pytest.mark.asyncio
    async def test_get_health_status(self, tracker):
        """Should return health status."""
        # Start one execution
        await tracker.record_execution_start(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            repos=["/path/to/repo"],
        )

        health = await tracker.get_health()

        assert health["status"] == "healthy"
        assert health["active_executions"] == 1
        assert health["sampling_strategy"] == "full"
        assert health["sampling_rate"] == 1.0
        assert "last_aggregation" in health


class TestSingleton:
    """Test global singleton pattern."""

    @pytest.mark.asyncio
    async def test_get_execution_tracker_singleton(self):
        """Should return same instance on multiple calls."""
        # Reset global singleton
        import mahavishnu.core.metrics_collector as mc
        mc._tracker = None

        tracker1 = get_execution_tracker()
        tracker2 = get_execution_tracker()

        assert tracker1 is tracker2

    @pytest.mark.asyncio
    async def test_initialize_execution_tracker(self):
        """Should initialize and start tracker."""
        import mahavishnu.core.metrics_collector as mc
        mc._tracker = None

        tracker = await initialize_execution_tracker(
            sampling_strategy=SamplingStrategy.LOW_FREQUENCY,
            force_recreate=True,  # Force fresh tracker creation
        )

        assert tracker is not None
        assert tracker._aggregate_task is not None
        assert tracker.sampling_strategy == SamplingStrategy.LOW_FREQUENCY

        await tracker.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
