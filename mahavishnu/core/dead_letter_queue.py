"""Dead Letter Queue for failed workflow reprocessing.

This module provides a robust dead letter queue (DLQ) system for handling failed
workflow executions with configurable retry policies, exponential backoff, and
automatic reprocessing. Failed workflows are never lost and can be recovered
manually or automatically.

Key Features:
- Configurable retry policies (never, linear, exponential, immediate)
- Automatic retry with exponential backoff
- Persistent queue storage (OpenSearch + in-memory fallback)
- Circuit breaker integration
- Observability and metrics
- Manual reprocessing capabilities
- Dead letter archival

Example:
    >>> from mahavishnu.core import MahavishnuApp
    >>> app = MahavishnuApp()
    >>> dlq = app.dlq
    >>>
    >>> # Enqueue failed task
    >>> await dlq.enqueue(
    ...     task_id="wf_abc123",
    ...     task={"type": "code_sweep"},
    ...     repos=["/path/to/repo"],
    ...     error="Connection timeout",
    ...     retry_policy=RetryPolicy.EXPONENTIAL,
    ...     max_retries=3
    ... )
    >>>
    >>> # Start automatic retry processor
    >>> await dlq.start_retry_processor()
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any

from mahavishnu.core.status import DeadLetterStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    try:
        from opensearchpy import AsyncOpenSearch
    except ImportError:
        AsyncOpenSearch = Any  # type: ignore

# Try to import OpenSearch at runtime, with fallback if not available
try:
    from opensearchpy import AsyncOpenSearch as _AsyncOpenSearch

    OPENSEARCH_AVAILABLE = True
except ImportError:
    _AsyncOpenSearch = None
    OPENSEARCH_AVAILABLE = False


class RetryPolicy(StrEnum):
    """Retry policy strategies for failed tasks."""

    NEVER = "never"  # Never retry - manual intervention only
    LINEAR = "linear"  # Linear backoff: 5min, 10min, 15min, ...
    EXPONENTIAL = (
        "exponential"  # Exponential backoff: 1min, 2min, 4min, 8min, ... (capped at 60min)
    )
    IMMEDIATE = "immediate"  # Retry immediately on next processor cycle


@dataclass
class FailedTask:
    """A failed workflow task awaiting retry or recovery.

    Attributes:
        task_id: Unique identifier for the task
        task: Original task specification
        repos: List of repository paths the task was processing
        error: Error message from the failure
        failed_at: Timestamp when the task first failed
        retry_count: Number of retry attempts made
        max_retries: Maximum number of retry attempts allowed
        retry_policy: Strategy for calculating retry delays
        next_retry_at: Timestamp when the next retry should be attempted
        status: Current status in the DLQ
        metadata: Additional context about the failure
        error_category: Categorized error type (transient, permanent, etc.)
        last_error: Most recent error message
        total_attempts: Total number of execution attempts
    """

    task_id: str
    task: dict[str, Any]
    repos: list[str]
    error: str
    failed_at: datetime
    retry_count: int = 0
    max_retries: int = 3
    retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    next_retry_at: datetime | None = None
    status: DeadLetterStatus = DeadLetterStatus.PENDING
    metadata: dict[str, Any] = field(default_factory=dict)
    error_category: str | None = None
    last_error: str | None = None
    total_attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "task_id": self.task_id,
            "task": self.task,
            "repos": self.repos,
            "error": self.error,
            "failed_at": self.failed_at.isoformat(),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "retry_policy": self.retry_policy.value,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "status": self.status.value,
            "metadata": self.metadata,
            "error_category": self.error_category,
            "last_error": self.last_error,
            "total_attempts": self.total_attempts,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailedTask:
        """Create FailedTask from dictionary."""
        # Convert ISO format strings back to datetime objects
        failed_at = (
            datetime.fromisoformat(data["failed_at"])
            if data.get("failed_at")
            else datetime.now(UTC)
        )

        next_retry_at = None
        if data.get("next_retry_at"):
            next_retry_at = datetime.fromisoformat(data["next_retry_at"])

        # Convert string enums back to enums
        retry_policy = RetryPolicy(data.get("retry_policy", RetryPolicy.EXPONENTIAL))
        status = DeadLetterStatus(data.get("status", DeadLetterStatus.PENDING))

        return cls(
            task_id=data["task_id"],
            task=data["task"],
            repos=data["repos"],
            error=data["error"],
            failed_at=failed_at,
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            retry_policy=retry_policy,
            next_retry_at=next_retry_at,
            status=status,
            metadata=data.get("metadata", {}),
            error_category=data.get("error_category"),
            last_error=data.get("last_error"),
            total_attempts=data.get("total_attempts", 1),
        )


class DeadLetterQueue:
    """Dead Letter Queue for failed workflow reprocessing.

    The DLQ provides robust handling of failed workflows with:
    - Configurable retry policies with exponential backoff
    - Persistent storage (OpenSearch) with in-memory fallback
    - Automatic background retry processor
    - Manual reprocessing and inspection capabilities
    - Full observability and metrics

    Example:
        >>> dlq = DeadLetterQueue(max_size=10000)
        >>>
        >>> # Enqueue a failed task
        >>> await dlq.enqueue(
        ...     task_id="wf_abc123",
        ...     task={"type": "code_sweep"},
        ...     repos=["/path/to/repo"],
        ...     error="Connection timeout",
        ...     retry_policy=RetryPolicy.EXPONENTIAL,
        ...     max_retries=3
        ... )
        >>>
        >>> # Start automatic retry processor
        >>> await dlq.start_retry_processor(callback=retry_callback)
        >>>
        >>> # Or manually retry a specific task
        >>> await dlq.retry_task("wf_abc123")
        >>>
        >>> # Get queue statistics
        >>> stats = await dlq.get_statistics()
    """

    def __init__(
        self,
        max_size: int = 10000,
        opensearch_client: AsyncOpenSearch | None = None,
        observability_manager: Any = None,
    ):
        """Initialize the Dead Letter Queue.

        Args:
            max_size: Maximum number of tasks to keep in queue
            opensearch_client: Optional OpenSearch client for persistent storage
            observability_manager: Optional observability manager for metrics
        """
        self._max_size = max_size
        self._opensearch: Any = opensearch_client
        self._observability = observability_manager
        """Initialize the Dead Letter Queue.

        Args:
            max_size: Maximum number of tasks to keep in queue
            opensearch_client: Optional OpenSearch client for persistent storage
            observability_manager: Optional observability manager for metrics
        """
        self._max_size = max_size
        self._opensearch = opensearch_client
        self._observability = observability_manager
        self._queue: list[FailedTask] = []
        self._lock = asyncio.Lock()
        self._retry_task: asyncio.Task | None = None
        self._is_running = False
        self._retry_callback: Callable | None = None
        self._retry_interval_seconds = 60  # Check every minute
        self._logger = logging.getLogger(__name__)

        # Statistics
        self._stats = {
            "enqueued_total": 0,
            "retry_success": 0,
            "retry_failed": 0,
            "exhausted": 0,
            "manually_retried": 0,
            "archived": 0,
        }

    def _calculate_next_retry(self, policy: RetryPolicy, retry_count: int) -> datetime | None:
        """Calculate the next retry timestamp based on policy.

        Args:
            policy: Retry policy to use
            retry_count: Number of retries already attempted

        Returns:
            Next retry timestamp or None if never retry
        """
        if policy == RetryPolicy.NEVER:
            return None

        now = datetime.now(UTC)

        if policy == RetryPolicy.IMMEDIATE:
            return now

        elif policy == RetryPolicy.LINEAR:
            # Linear backoff: 5min, 10min, 15min, ...
            delay_minutes = 5 * (retry_count + 1)
            return now + timedelta(minutes=delay_minutes)

        elif policy == RetryPolicy.EXPONENTIAL:
            # Exponential backoff: 1min, 2min, 4min, 8min, ... (capped at 60min)
            delay_minutes = min(2**retry_count, 60)
            return now + timedelta(minutes=delay_minutes)

        return None

    async def enqueue(
        self,
        task_id: str,
        task: dict[str, Any],
        repos: list[str],
        error: str,
        retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL,
        max_retries: int = 3,
        metadata: dict[str, Any] | None = None,
        error_category: str | None = None,
    ) -> FailedTask:
        """Add a failed task to the dead letter queue.

        Args:
            task_id: Unique identifier for the task
            task: Original task specification
            repos: List of repository paths
            error: Error message
            retry_policy: Strategy for retry attempts
            max_retries: Maximum number of retry attempts
            metadata: Additional context
            error_category: Categorized error type

        Returns:
            The created FailedTask object

        Raises:
            ValueError: If queue is at maximum capacity
        """
        async with self._lock:
            # Check queue size
            if len(self._queue) >= self._max_size:
                self._logger.error(f"Dead letter queue is full (max_size={self._max_size})")
                raise ValueError(
                    f"Dead letter queue is full (max_size={self._max_size}). "
                    f"Please manually process or archive tasks before adding more."
                )

            # Create failed task
            failed_task = FailedTask(
                task_id=task_id,
                task=task,
                repos=repos,
                error=error,
                failed_at=datetime.now(UTC),
                retry_count=0,
                max_retries=max_retries,
                retry_policy=retry_policy,
                next_retry_at=self._calculate_next_retry(retry_policy, 0),
                status=DeadLetterStatus.PENDING,
                metadata=metadata or {},
                error_category=error_category,
                last_error=error,
                total_attempts=1,
            )

            # Add to queue
            self._queue.append(failed_task)
            self._stats["enqueued_total"] += 1

            # Persist to OpenSearch if available
            await self._persist_task(failed_task)

            # Log enqueue event
            self._logger.warning(
                f"Task {task_id} enqueued in DLQ: {error} "
                f"(policy={retry_policy.value}, max_retries={max_retries})"
            )

            # Record metrics
            if self._observability:
                self._observability.log_info(
                    "Task enqueued in dead letter queue",
                    attributes={
                        "task_id": task_id,
                        "error": error[:200],  # Truncate long errors
                        "retry_policy": retry_policy.value,
                        "max_retries": max_retries,
                        "error_category": error_category,
                    },
                )

            return failed_task

    async def _persist_task(self, failed_task: FailedTask) -> None:
        """Persist task to OpenSearch if available.

        Args:
            failed_task: Task to persist
        """
        if self._opensearch and OPENSEARCH_AVAILABLE:
            try:
                await self._opensearch.index(
                    index="mahavishnu_dlq",
                    id=failed_task.task_id,
                    body=failed_task.to_dict(),
                )
            except Exception as e:
                self._logger.error(f"Failed to persist task to OpenSearch: {e}")
        # In-memory storage is already handled by _queue list

    async def _update_task_persistence(self, failed_task: FailedTask) -> None:
        """Update persisted task in OpenSearch.

        Args:
            failed_task: Task with updated state
        """
        if self._opensearch and OPENSEARCH_AVAILABLE:
            try:
                await self._opensearch.update(
                    index="mahavishnu_dlq",
                    id=failed_task.task_id,
                    body={"doc": failed_task.to_dict()},
                )
            except Exception as e:
                self._logger.error(f"Failed to update task in OpenSearch: {e}")

    async def start_retry_processor(
        self,
        callback: Callable[[dict[str, Any], list[str]], Any],
        check_interval_seconds: int = 60,
    ) -> None:
        """Start the background retry processor.

        The processor will periodically check for tasks ready for retry
        and attempt to re-execute them using the provided callback.

        Args:
            callback: Async function to call for retry attempts.
                     Should accept (task, repos) and return result.
            check_interval_seconds: How often to check for retries (default 60s)

        Example:
            >>> async def retry_callback(task, repos):
            ...     return await app.execute_workflow(task, "llamaindex", repos)
            >>>
            >>> await dlq.start_retry_processor(retry_callback)
        """
        if self._is_running:
            self._logger.warning("Retry processor is already running")
            return

        self._is_running = True
        self._retry_callback = callback
        self._retry_interval_seconds = check_interval_seconds

        async def retry_loop():
            """Main retry processing loop."""
            while self._is_running:
                try:
                    await self._process_ready_tasks(callback)
                    await asyncio.sleep(self._retry_interval_seconds)
                except Exception as e:
                    self._logger.error(f"Error in retry processor loop: {e}", exc_info=True)
                    # Wait before retrying to avoid tight error loop
                    await asyncio.sleep(10)

        self._retry_task = asyncio.create_task(retry_loop())
        self._logger.info(f"Started DLQ retry processor (check_interval={check_interval_seconds}s)")

    async def stop_retry_processor(self) -> None:
        """Stop the background retry processor.

        Waits for the current retry cycle to complete before stopping.
        """
        if not self._is_running:
            return

        self._is_running = False

        if self._retry_task:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task

        self._retry_task = None
        self._logger.info("Stopped DLQ retry processor")

    async def _process_ready_tasks(
        self, callback: Callable[[dict[str, Any], list[str]], Any]
    ) -> None:
        """Process all tasks ready for retry.

        Args:
            callback: Function to call for retry attempts
        """
        async with self._lock:
            now = datetime.now(UTC)
            tasks_to_retry = [
                task
                for task in self._queue
                if task.next_retry_at
                and task.next_retry_at <= now
                and task.status == DeadLetterStatus.PENDING
                and task.retry_count < task.max_retries
            ]

            if not tasks_to_retry:
                return

            self._logger.info(f"Processing {len(tasks_to_retry)} tasks ready for retry")

        # Process tasks outside the lock to avoid blocking
        for failed_task in tasks_to_retry:
            try:
                # Update status to retrying
                failed_task.status = DeadLetterStatus.RETRYING
                await self._update_task_persistence(failed_task)

                # Attempt retry
                await callback(failed_task.task, failed_task.repos)

                # Success! Remove from queue
                async with self._lock:
                    if failed_task in self._queue:
                        self._queue.remove(failed_task)

                failed_task.status = DeadLetterStatus.COMPLETED
                await self._update_task_persistence(failed_task)

                self._stats["retry_success"] += 1

                self._logger.info(f"Successfully retried task {failed_task.task_id}")

                # Record success metrics
                if self._observability:
                    self._observability.log_info(
                        "Task retry succeeded",
                        attributes={
                            "task_id": failed_task.task_id,
                            "retry_count": failed_task.retry_count + 1,
                            "total_attempts": failed_task.total_attempts + 1,
                        },
                    )

                # Remove from OpenSearch
                await self._remove_from_persistence(failed_task.task_id)

            except Exception as e:
                # Retry failed again - increment retry count
                async with self._lock:
                    if failed_task in self._queue:
                        index = self._queue.index(failed_task)
                        new_retry_count = failed_task.retry_count + 1
                        new_total_attempts = failed_task.total_attempts + 1

                        # Check if retries exhausted
                        if new_retry_count >= failed_task.max_retries:
                            # Mark as exhausted
                            updated_task = failed_task
                            updated_task.retry_count = new_retry_count
                            updated_task.total_attempts = new_total_attempts
                            updated_task.status = DeadLetterStatus.EXHAUSTED
                            updated_task.last_error = str(e)
                            self._queue[index] = updated_task
                            self._stats["exhausted"] += 1

                            self._logger.error(
                                f"Task {failed_task.task_id} exhausted all retries "
                                f"({new_retry_count}/{failed_task.max_retries})"
                            )

                            # Record exhausted metrics
                            if self._observability:
                                self._observability.log_error(
                                    "Task retries exhausted",
                                    attributes={
                                        "task_id": failed_task.task_id,
                                        "retry_count": new_retry_count,
                                        "max_retries": failed_task.max_retries,
                                        "final_error": str(e)[:200],
                                    },
                                )
                        else:
                            # Calculate next retry time
                            updated_task = failed_task
                            updated_task.retry_count = new_retry_count
                            updated_task.total_attempts = new_total_attempts
                            updated_task.next_retry_at = self._calculate_next_retry(
                                failed_task.retry_policy, new_retry_count
                            )
                            updated_task.last_error = str(e)
                            updated_task.status = DeadLetterStatus.PENDING
                            self._queue[index] = updated_task

                        await self._update_task_persistence(updated_task)

                self._stats["retry_failed"] += 1

                self._logger.warning(
                    f"Retry {failed_task.retry_count + 1} failed for task {failed_task.task_id}: {e}"
                )

    async def _remove_from_persistence(self, task_id: str) -> None:
        """Remove task from persistent storage.

        Args:
            task_id: ID of task to remove
        """
        if self._opensearch and OPENSEARCH_AVAILABLE:
            try:
                await self._opensearch.delete(index="mahavishnu_dlq", id=task_id)
            except Exception as e:
                self._logger.error(f"Failed to remove task from OpenSearch: {e}")

    async def retry_task(self, task_id: str) -> dict[str, Any]:
        """Manually retry a specific task.

        Args:
            task_id: ID of task to retry

        Returns:
            Result dictionary with success status

        Raises:
            ValueError: If task not found in queue
        """
        async with self._lock:
            # Find task in queue
            failed_task = None
            for task in self._queue:
                if task.task_id == task_id:
                    failed_task = task
                    break

            if not failed_task:
                raise ValueError(f"Task {task_id} not found in dead letter queue")

            # Increment manual retry count
            self._stats["manually_retried"] += 1

        # Process outside lock using the configured callback
        if not self._retry_callback:
            raise RuntimeError("No retry callback configured. Use start_retry_processor() first.")

        try:
            # Attempt retry
            result = await self._retry_callback(failed_task.task, failed_task.repos)

            # Success - remove from queue
            async with self._lock:
                if failed_task in self._queue:
                    self._queue.remove(failed_task)

            failed_task.status = DeadLetterStatus.COMPLETED
            await self._update_task_persistence(failed_task)
            await self._remove_from_persistence(task_id)

            self._stats["retry_success"] += 1

            return {
                "success": True,
                "task_id": task_id,
                "result": result,
                "message": "Task successfully retried",
            }

        except Exception as e:
            # Failed - update error info
            async with self._lock:
                if failed_task in self._queue:
                    index = self._queue.index(failed_task)
                    updated_task = failed_task
                    updated_task.retry_count += 1
                    updated_task.total_attempts += 1
                    updated_task.last_error = str(e)
                    updated_task.status = DeadLetterStatus.PENDING
                    self._queue[index] = updated_task
                    await self._update_task_persistence(updated_task)

            self._stats["retry_failed"] += 1

            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "message": "Task retry failed",
            }

    async def get_task(self, task_id: str) -> FailedTask | None:
        """Get a specific task from the queue.

        Args:
            task_id: ID of task to retrieve

        Returns:
            FailedTask object or None if not found
        """
        async with self._lock:
            for task in self._queue:
                if task.task_id == task_id:
                    return task
            return None

    async def list_tasks(
        self,
        status: DeadLetterStatus | None = None,
        limit: int = 100,
    ) -> list[FailedTask]:
        """List tasks in the queue, optionally filtered by status.

        Args:
            status: Optional status filter
            limit: Maximum number of tasks to return

        Returns:
            List of FailedTask objects
        """
        async with self._lock:
            tasks = self._queue.copy()

            if status:
                tasks = [t for t in tasks if t.status == status]

            return tasks[:limit]

    async def archive_task(self, task_id: str) -> bool:
        """Archive a task (remove from active queue but keep record).

        Args:
            task_id: ID of task to archive

        Returns:
            True if task was archived, False if not found
        """
        async with self._lock:
            for i, task in enumerate(self._queue):
                if task.task_id == task_id:
                    # Update status to archived
                    task.status = DeadLetterStatus.ARCHIVED
                    self._stats["archived"] += 1

                    # Update persistence
                    await self._update_task_persistence(task)

                    # Remove from active queue
                    self._queue.pop(i)

                    self._logger.info(f"Archived task {task_id}")
                    return True

            return False

    async def get_statistics(self) -> dict[str, Any]:
        """Get queue statistics.

        Returns:
            Dictionary with queue metrics
        """
        async with self._lock:
            pending_count = sum(1 for t in self._queue if t.status == DeadLetterStatus.PENDING)
            retrying_count = sum(1 for t in self._queue if t.status == DeadLetterStatus.RETRYING)
            exhausted_count = sum(1 for t in self._queue if t.status == DeadLetterStatus.EXHAUSTED)

            # Calculate error category distribution
            error_categories: dict[str, int] = {}
            for task in self._queue:
                if task.error_category:
                    error_categories[task.error_category] = (
                        error_categories.get(task.error_category, 0) + 1
                    )

            # Calculate retry policy distribution
            retry_policies: dict[str, int] = {}
            for task in self._queue:
                policy = task.retry_policy.value
                retry_policies[policy] = retry_policies.get(policy, 0) + 1

            return {
                "queue_size": len(self._queue),
                "max_size": self._max_size,
                "utilization_percent": round(len(self._queue) / self._max_size * 100, 2),
                "status breakdown": {
                    "pending": pending_count,
                    "retrying": retrying_count,
                    "exhausted": exhausted_count,
                },
                "error_categories": error_categories,
                "retry_policies": retry_policies,
                "lifetime_stats": self._stats.copy(),
                "is_processor_running": self._is_running,
                "retry_interval_seconds": self._retry_interval_seconds
                if self._is_running
                else None,
            }

    async def clear_all(self) -> int:
        """Clear all tasks from the queue.

        WARNING: This is a destructive operation. Use with caution.

        Returns:
            Number of tasks cleared
        """
        async with self._lock:
            count = len(self._queue)
            self._queue.clear()

            # Clear from OpenSearch if available
            if self._opensearch and OPENSEARCH_AVAILABLE:
                try:
                    # Delete all documents in index
                    await self._opensearch.delete_by_query(
                        index="mahavishnu_dlq",
                        body={"query": {"match_all": {}}},
                    )
                except Exception as e:
                    self._logger.error(f"Failed to clear OpenSearch index: {e}")

            self._logger.warning(f"Cleared {count} tasks from dead letter queue")
            return count

    async def shutdown(self) -> None:
        """Shutdown the DLQ and cleanup resources.

        Stops the retry processor and performs cleanup.
        """
        await self.stop_retry_processor()
        self._logger.info("Dead letter queue shutdown complete")
