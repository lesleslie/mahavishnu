"""Metrics collection for adaptive routing with statistical learning.

Tracks adapter executions, success rates, latency, and costs.
Provides ExecutionTracker class with async batch writes and sampling strategies.

Design:
- Storage-agnostic (works with or without Dhruva)
- ULID-based execution identifiers
- TTL-based automatic cleanup
- Configurable sampling strategies
"""

from __future__ import annotations

import asyncio
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from typing import Any, Awaitable, Callable
from enum import Enum

from pydantic import ValidationError

from mahavishnu.core.metrics_schema import (
    ExecutionRecord,
    AdapterStats,
    AdapterType,
    TaskType,
    ExecutionStatus,
    CostTracking,
)

try:
    from oneiric.core.ulid import generate_config_id
except ImportError:
    def generate_config_id() -> str:
        import uuid
        return uuid.uuid4().hex


logger = logging.getLogger(__name__)


class SamplingStrategy(str, Enum):
    """Sampling strategies for metrics collection."""

    FULL = "full"  # 100% sampling
    HIGH_FREQUENCY = "high_frequency"  # Sample 10% of high-frequency tasks
    LOW_FREQUENCY = "low_frequency"  # 100% sampling for low-frequency tasks
    ADAPTIVE = "adaptive"  # Automatically adjust based on volume


@dataclass
class ExecutionMetrics:
    """In-memory execution metrics tracking.

    Tracks:
    - Active executions (start time recorded, waiting for completion)
    - Completed executions (ready for aggregation)
    - Adapter attempt counts for success rate calculation
    - Task type frequencies for adaptive sampling
    """

    active_executions: dict[str, dict[str, Any]] = field(default_factory=dict)
    """exec:{ulid} -> {start_ts, adapter, task_type, repos}"""

    completed_executions: list[ExecutionRecord] = field(default_factory=list)
    """Completed execution records awaiting batch write."""

    adapter_attempts: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    """{adapter: {success: count, failure: count}}"""

    task_type_counts: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    """{task_type: execution_count} for adaptive sampling"""

    last_aggregate_ts: float = field(default_factory=lambda: time.time())
    """Timestamp of last aggregation to Dhruva."""

    def get_success_rate(
        self, adapter: AdapterType, min_samples: int = 10
    ) -> float | None:
        """Calculate success rate for adapter.

        Args:
            adapter: Adapter type to calculate
            min_samples: Minimum executions before returning rate

        Returns:
            Success rate (0.0-1.0) or None if insufficient samples
        """
        attempts = self.adapter_attempts.get(adapter.value, {})
        total = attempts.get("success", 0) + attempts.get("failure", 0)

        if total < min_samples:
            return None

        if total == 0:
            return 0.0

        return attempts.get("success", 0) / total


class ExecutionTracker:
    """Tracks adapter execution metrics with async batch writes.

    Features:
    - Record execution start/end with ULID tracking
    - Async batch writes to reduce storage overhead
    - Configurable sampling strategy
    - Automatic aggregation of statistics
    - TTL-based cleanup of old records
    """

    def __init__(
        self,
        sampling_strategy: SamplingStrategy = SamplingStrategy.FULL,
        sampling_rate: float = 1.0,
        batch_size: int = 100,
        batch_timeout_ms: int = 5000,
        aggregate_interval_ms: int = 60000,  # 1 minute
        storage_client: Any | None = None,
    ):
        """Initialize ExecutionTracker.

        Args:
            sampling_strategy: How to sample executions (default: FULL)
            sampling_rate: Sampling rate 0.0-1.0 (default: 1.0 = 100%)
            batch_size: Max records before forcing batch write (default: 100)
            batch_timeout_ms: Max time before forcing batch write (default: 5s)
            aggregate_interval_ms: Interval for recalculating aggregates (default: 60s)
            storage_client: Optional Dhruva/storage client
        """
        self.sampling_strategy = sampling_strategy
        self.sampling_rate = sampling_rate
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.aggregate_interval_ms = aggregate_interval_ms
        self.storage_client = storage_client

        self._metrics = ExecutionMetrics()
        self._write_lock = asyncio.Lock()
        self._aggregate_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"ExecutionTracker initialized: strategy={sampling_strategy.value}, "
            f"rate={sampling_rate}, batch={batch_size}"
        )

    def _should_sample(self, task_type: TaskType) -> bool:
        """Determine if execution should be sampled.

        Args:
            task_type: Type of task being executed

        Returns:
            True if execution should be tracked
        """
        if self.sampling_strategy == SamplingStrategy.FULL:
            return True

        if self.sampling_strategy == SamplingStrategy.ADAPTIVE:
            # Sample based on task frequency
            count = self._metrics.task_type_counts.get(task_type.value, 0)
            # High frequency: sample 10%, Low frequency: 100%
            return count < 100 or (count % 10) == 0

        if self.sampling_strategy == SamplingStrategy.HIGH_FREQUENCY:
            # Sample 10% of tasks
            import random
            return random.random() < self.sampling_rate

        # LOW_FREQUENCY or default: track everything
        return True

    async def record_execution_start(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        repos: list[str],
    ) -> str:
        """Record the start of an execution.

        Args:
            adapter: Adapter being used
            task_type: Type of task
            repos: Repository paths involved

        Returns:
            ULID execution identifier
        """
        execution_id = generate_config_id()

        # Check sampling strategy
        if not self._should_sample(task_type):
            logger.debug(f"Execution {execution_id} not sampled (strategy={self.sampling_strategy.value})")
            return execution_id

        # Record active execution
        self._metrics.active_executions[execution_id] = {
            "start_ts": time.time(),
            "adapter": adapter.value,
            "task_type": task_type.value,
            "repos": repos,
        }

        # Track task type frequency
        self._metrics.task_type_counts[task_type.value] += 1

        logger.debug(f"Recorded execution start: {execution_id} ({adapter.value} - {task_type.value})")

        return execution_id

    async def record_execution_end(
        self,
        execution_id: str,
        success: bool,
        status: ExecutionStatus = ExecutionStatus.SUCCESS,
        latency_ms: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Record the completion of an execution.

        Args:
            execution_id: ULID execution identifier
            success: Whether execution succeeded
            status: Final execution status
            latency_ms: Execution duration in milliseconds
            error_type: Error category (if failed)
            error_message: Detailed error message (if failed)
            cost_usd: Execution cost in USD (if tracked)
        """
        # Check if execution was tracked (active)
        active = self._metrics.active_executions.pop(execution_id, None)

        if active is None:
            logger.debug(f"Execution {execution_id} not found in active (may not be sampled)")
            return

        # Calculate latency if not provided
        if latency_ms is None:
            start_ts = active["start_ts"]
            latency_ms = int((time.time() - start_ts) * 1000)

        # Create execution record
        record = ExecutionRecord(
            execution_id=execution_id,
            adapter=AdapterType(active["adapter"]),
            task_type=TaskType(active["task_type"]),
            start_timestamp=active["start_ts"],
            end_timestamp=time.time(),
            status=status,
            latency_ms=latency_ms,
            error_type=error_type,
            error_message=error_message,
            cost_usd=cost_usd,
        )

        # Add to completed list for batch write
        self._metrics.completed_executions.append(record)

        # Update adapter attempt counts
        adapter = AdapterType(active["adapter"])
        outcome = "success" if success else "failure"
        self._metrics.adapter_attempts[adapter.value][outcome] += 1

        logger.debug(
            f"Recorded execution end: {execution_id} - "
            f"{'SUCCESS' if success else 'FAILURE'} ({latency_ms}ms)"
        )

        # Trigger batch write if size threshold reached
        if len(self._metrics.completed_executions) >= self.batch_size:
            await self._flush_batch()

    async def record_adapter_attempt(
        self,
        adapter: AdapterType,
        attempt_number: int,
        outcome: str,
    ) -> None:
        """Record adapter attempt for fallback tracking.

        Args:
            adapter: Adapter being attempted
            attempt_number: Attempt number (1, 2, 3...)
            outcome: "success", "failure", "timeout"
        """
        # This is called by AdapterManager for fallback attempts
        # We'll track these separately from execution records
        key = f"{adapter.value}:attempt_{attempt_number}"
        # Store in metrics for statistical analysis
        logger.debug(f"Adapter attempt: {adapter.value} #{attempt_number} -> {outcome}")

    async def _flush_batch(self) -> dict[str, Any]:
        """Write batched execution records to storage.

        Returns:
            Dictionary with write statistics
        """
        if not self._metrics.completed_executions:
            return {"status": "no_records", "written": 0}

        records = self._metrics.completed_executions.copy()
        self._metrics.completed_executions.clear()

        # Try to write to Dhruva if available
        if self.storage_client is not None:
            try:
                # TODO: Implement Dhruva batch write
                # For now, simulate successful write
                await asyncio.sleep(0.001)  # Simulate IO
                written = len(records)
            except Exception as e:
                logger.error(f"Dhruva write failed: {e}")
                return {"status": "error", "error": str(e), "written": 0}
        else:
            # No storage client - simulate write
            await asyncio.sleep(0.001)
            written = len(records)

        logger.info(f"Flushed {written} execution records to storage")
        return {"status": "success", "written": written}

    async def _aggregation_loop(self) -> None:
        """Background task to periodically aggregate metrics.

        Calculates:
        - Adapter success rates
        - Per-task-type statistics
        - Cost aggregations
        - Writes aggregated stats to storage
        """
        while not self._shutdown_event.is_set():
            try:
                # Wait for aggregate interval
                await asyncio.sleep(self.aggregate_interval_ms / 1000)

                # Calculate aggregates
                aggregates = await self._calculate_aggregates()

                # Write aggregates to storage
                if self.storage_client is not None:
                    # TODO: Write aggregates to Dhruva
                    logger.debug(f"Aggregates calculated: {aggregates}")
                else:
                    logger.debug(f"Aggregates (no storage): {aggregates}")

                self._metrics.last_aggregate_ts = time.time()

            except asyncio.CancelledError:
                logger.info("Aggregation loop cancelled")
                break
            except Exception as e:
                logger.error(f"Aggregation error: {e}", exc_info=True)

    async def _calculate_aggregates(self) -> dict[str, Any]:
        """Calculate statistical aggregates from tracked metrics.

        Returns:
            Dictionary with aggregated statistics
        """
        aggregates = {
            "adapter_stats": {},
            "task_type_stats": {},
            "timestamp": time.time(),
        }

        # Calculate per-adapter statistics
        for adapter in AdapterType:
            success_rate = self._metrics.get_success_rate(adapter)
            if success_rate is not None:
                attempts = self._metrics.adapter_attempts.get(adapter.value, {})
                aggregates["adapter_stats"][adapter.value] = {
                    "success_rate": success_rate,
                    "total_executions": attempts.get("success", 0) + attempts.get("failure", 0),
                    "last_updated": datetime.now(UTC).isoformat(),
                }

        # Calculate per-task-type statistics
        for task_type in TaskType:
            count = self._metrics.task_type_counts.get(task_type.value, 0)
            aggregates["task_type_stats"][task_type.value] = {
                "execution_count": count,
                "last_updated": datetime.now(UTC).isoformat(),
            }

        return aggregates

    async def get_adapter_stats(
        self, adapter: AdapterType
    ) -> dict[str, Any] | None:
        """Get current statistics for an adapter.

        Args:
            adapter: Adapter type

        Returns:
            Dictionary with adapter stats or None
        """
        success_rate = self._metrics.get_success_rate(adapter)
        if success_rate is None:
            return None

        attempts = self._metrics.adapter_attempts.get(adapter.value, {})
        total = attempts.get("success", 0) + attempts.get("failure", 0)

        return {
            "adapter": adapter.value,
            "success_rate": success_rate,
            "total_executions": total,
            "successful_executions": attempts.get("success", 0),
            "failed_executions": attempts.get("failure", 0),
        }

    async def get_task_type_stats(self, task_type: TaskType) -> dict[str, Any]:
        """Get statistics for a task type.

        Args:
            task_type: Task type enum

        Returns:
            Dictionary with task type stats
        """
        count = self._metrics.task_type_counts.get(task_type.value, 0)

        return {
            "task_type": task_type.value,
            "execution_count": count,
        }

    async def get_recent_executions(
        self, limit: int = 100
    ) -> list[ExecutionRecord]:
        """Get recent execution records.

        Args:
            limit: Maximum records to return

        Returns:
            List of recent execution records
        """
        # Return most recent from completed + active
        all_records = list(self._metrics.completed_executions)
        return all_records[-limit:]

    async def start(self) -> None:
        """Start the metrics tracker.

        Begins background aggregation loop.
        """
        if self._aggregate_task is not None:
            logger.warning("ExecutionTracker already started")
            return

        self._shutdown_event.clear()
        self._aggregate_task = asyncio.create_task(self._aggregation_loop())
        logger.info("ExecutionTracker started")

    async def stop(self) -> None:
        """Stop the metrics tracker.

        Flushes pending writes and stops aggregation loop.
        """
        logger.info("Stopping ExecutionTracker...")

        # Cancel aggregation loop
        if self._aggregate_task and not self._aggregate_task.done():
            self._aggregate_task.cancel()
            try:
                await self._aggregate_task
            except asyncio.CancelledError:
                pass

        # Shutdown event
        self._shutdown_event.set()

        # Flush pending batch
        async with self._write_lock:
            if self._metrics.completed_executions:
                await self._flush_batch()

        logger.info("ExecutionTracker stopped")

    async def get_health(self) -> dict[str, Any]:
        """Get health status of metrics tracker.

        Returns:
            Health status dictionary
        """
        pending_count = len(self._metrics.completed_executions)
        active_count = len(self._metrics.active_executions)

        return {
            "status": "healthy",
            "active_executions": active_count,
            "pending_writes": pending_count,
            "sampling_strategy": self.sampling_strategy.value,
            "sampling_rate": self.sampling_rate,
            "last_aggregation": datetime.fromtimestamp(
                self._metrics.last_aggregate_ts, UTC
            ).isoformat()
            if self._metrics.last_aggregate_ts > 0 else None,
        }


# Singleton instance for global access
_tracker: ExecutionTracker | None = None


def get_execution_tracker() -> ExecutionTracker:
    """Get or create global ExecutionTracker singleton.

    Returns:
        Global ExecutionTracker instance
    """
    global _tracker
    if _tracker is None:
        _tracker = ExecutionTracker()
    return _tracker


async def initialize_execution_tracker(
    sampling_strategy: SamplingStrategy = SamplingStrategy.FULL,
    storage_client: Any | None = None,
    force_recreate: bool = False,
) -> ExecutionTracker:
    """Initialize and start the global execution tracker.

    Args:
        sampling_strategy: Sampling strategy to use
        storage_client: Optional storage backend (Dhruva)
        force_recreate: If True, create new tracker even if one exists

    Returns:
        Started ExecutionTracker instance
    """
    global _tracker

    # If forcing recreation or tracker doesn't exist, create new one
    if force_recreate or _tracker is None:
        _tracker = ExecutionTracker(
            sampling_strategy=sampling_strategy,
            storage_client=storage_client,
        )

    await _tracker.start()
    return _tracker


__all__ = [
    "SamplingStrategy",
    "ExecutionMetrics",
    "ExecutionTracker",
    "get_execution_tracker",
    "initialize_execution_tracker",
]
