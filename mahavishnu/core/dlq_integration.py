"""Dead Letter Queue integration with workflow execution.

This module provides integration between the Dead Letter Queue and the
existing workflow execution system. It automatically captures failed
workflows and enqueues them for reprocessing based on configurable policies.

Example:
    >>> from mahavishnu.core import MahavishnuApp
    >>> app = MahavishnuApp()
    >>>
    >>> # DLQ is automatically integrated
    >>> # Failed workflows are automatically enqueued
    >>>
    >>> # Start DLQ retry processor
    >>> await app.start_dlq_processor()
    >>>
    >>> # Check DLQ statistics
    >>> stats = await app.dlq.get_statistics()
    >>> print(f"DLQ size: {stats['queue_size']}")
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any

from .dead_letter_queue import DeadLetterQueue, FailedTask, RetryPolicy, DeadLetterStatus
from .errors import AdapterError, WorkflowError
from .resilience import ErrorCategory


class DLQIntegrationStrategy(str, Enum):
    """Integration strategy for DLQ with workflow execution."""

    AUTOMATIC = "automatic"  # Automatically enqueue all failed workflows
    SELECTIVE = "selective"  # Enqueue based on error classification
    MANUAL = "manual"  # Only enqueue when explicitly requested
    DISABLED = "disabled"  # Never use DLQ


class DLQIntegration:
    """Integration layer for Dead Letter Queue with workflow execution.

    This class provides:
    - Automatic capture of failed workflows
    - Error classification for intelligent retry decisions
    - Configurable integration strategies
    - Metrics and observability
    - Manual intervention capabilities

    Example:
        >>> integration = DLQIntegration(app, dlq)
        >>>
        >>> # Enable automatic integration
        >>> integration.set_strategy(DLQIntegrationStrategy.AUTOMATIC)
        >>>
        >>> # Execute workflow with DLQ protection
        >>> result = await integration.execute_with_dlq(
        ...     task={"type": "code_sweep"},
        ...     adapter_name="llamaindex",
        ...     repos=["/path/to/repo"]
        ... )
    """

    def __init__(self, app, dlq: DeadLetterQueue):
        """Initialize DLQ integration.

        Args:
            app: MahavishnuApp instance
            dlq: DeadLetterQueue instance
        """
        self.app = app
        self.dlq = dlq
        self._strategy = DLQIntegrationStrategy.AUTOMATIC
        self._logger = logging.getLogger(__name__)

        # Statistics
        self._stats = {
            "workflows_executed": 0,
            "workflows_failed": 0,
            "auto_enqueued": 0,
            "manually_enqueued": 0,
            "skipped_permanent": 0,
            "skipped_permission": 0,
        }

    def set_strategy(self, strategy: DLQIntegrationStrategy) -> None:
        """Set the DLQ integration strategy.

        Args:
            strategy: Integration strategy to use
        """
        self._strategy = strategy
        self._logger.info(f"DLQ integration strategy set to: {strategy.value}")

    def get_strategy(self) -> DLQIntegrationStrategy:
        """Get current DLQ integration strategy.

        Returns:
            Current integration strategy
        """
        return self._strategy

    async def should_enqueue(
        self, error: Exception, error_category: ErrorCategory | None = None
    ) -> bool:
        """Determine if a failed workflow should be enqueued in DLQ.

        Args:
            error: The exception that occurred
            error_category: Classified error category

        Returns:
            True if workflow should be enqueued
        """
        # DISABLED strategy - never enqueue
        if self._strategy == DLQIntegrationStrategy.DISABLED:
            return False

        # MANUAL strategy - only enqueue explicitly
        if self._strategy == DLQIntegrationStrategy.MANUAL:
            return False

        # AUTOMATIC strategy - enqueue all failures
        if self._strategy == DLQIntegrationStrategy.AUTOMATIC:
            return True

        # SELECTIVE strategy - enqueue based on error category
        if self._strategy == DLQIntegrationStrategy.SELECTIVE:
            if error_category is None:
                # Classify error if not provided
                error_category = await self.app.error_recovery_manager.classify_error(error)

            # Enqueue transient and network errors (likely to succeed on retry)
            # Skip permanent, permission, and validation errors (won't succeed)
            if error_category in (
                ErrorCategory.TRANSIENT,
                ErrorCategory.NETWORK,
            ):
                return True

            # Resource errors - sometimes worth retrying
            if error_category == ErrorCategory.RESOURCE:
                return True

            # Don't retry permanent, permission, or validation errors
            return False

        return False

    async def determine_retry_policy(
        self, error: Exception, error_category: ErrorCategory | None = None
    ) -> RetryPolicy:
        """Determine appropriate retry policy based on error.

        Args:
            error: The exception that occurred
            error_category: Classified error category

        Returns:
            Recommended retry policy
        """
        if error_category is None:
            error_category = await self.app.error_recovery_manager.classify_error(error)

        # Transient errors - exponential backoff
        if error_category == ErrorCategory.TRANSIENT:
            return RetryPolicy.EXPONENTIAL

        # Network errors - exponential backoff (longer delays)
        if error_category == ErrorCategory.NETWORK:
            return RetryPolicy.EXPONENTIAL

        # Resource errors - linear backoff
        if error_category == ErrorCategory.RESOURCE:
            return RetryPolicy.LINEAR

        # Permission errors - never retry
        if error_category == ErrorCategory.PERMISSION:
            return RetryPolicy.NEVER

        # Validation errors - never retry
        if error_category == ErrorCategory.VALIDATION:
            return RetryPolicy.NEVER

        # Permanent errors - never retry
        if error_category == ErrorCategory.PERMANENT:
            return RetryPolicy.NEVER

        # Default to exponential
        return RetryPolicy.EXPONENTIAL

    async def enqueue_failed_workflow(
        self,
        task_id: str,
        task: dict[str, Any],
        repos: list[str],
        error: Exception,
        retry_policy: RetryPolicy | None = None,
        max_retries: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FailedTask | None:
        """Enqueue a failed workflow in the DLQ.

        Args:
            task_id: Workflow ID
            task: Task specification
            repos: Repository paths
            error: Exception that occurred
            retry_policy: Optional retry policy (auto-detected if not provided)
            max_retries: Optional max retries (uses config default if not provided)
            metadata: Optional additional context

        Returns:
            FailedTask if enqueued, None if skipped
        """
        # Classify error
        error_category = await self.app.error_recovery_manager.classify_error(error)

        # Check if should enqueue
        should_enqueue = await self.should_enqueue(error, error_category)

        if not should_enqueue:
            self._stats["skipped_permanent"] += 1
            self._logger.info(
                f"Skipping DLQ enqueue for {task_id}: {error_category.value} error"
            )
            return None

        # Determine retry policy if not provided
        if retry_policy is None:
            retry_policy = await self.determine_retry_policy(error, error_category)

        # Determine max retries if not provided
        if max_retries is None:
            max_retries = getattr(self.app.config, "dlq_default_max_retries", 3)

        # Prepare metadata
        dlq_metadata = {
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "enqueued_by": "automatic" if self._strategy != DLQIntegrationStrategy.MANUAL else "manual",
            "original_error_type": type(error).__name__,
        }
        if metadata:
            dlq_metadata.update(metadata)

        # Enqueue in DLQ
        try:
            failed_task = await self.dlq.enqueue(
                task_id=task_id,
                task=task,
                repos=repos,
                error=str(error),
                retry_policy=retry_policy,
                max_retries=max_retries,
                metadata=dlq_metadata,
                error_category=error_category.value,
            )

            self._stats["auto_enqueued"] += 1
            self._logger.warning(
                f"Enqueued workflow {task_id} in DLQ: {error} "
                f"(policy={retry_policy.value}, category={error_category.value})"
            )

            return failed_task

        except ValueError as e:
            # DLQ is full
            self._logger.error(f"Failed to enqueue workflow {task_id}: DLQ is full: {e}")
            return None

    async def execute_with_dlq(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow with automatic DLQ protection.

        If the workflow fails, it will automatically be enqueued in the DLQ
        based on the integration strategy and error classification.

        Args:
            task: Task specification
            adapter_name: Adapter to use
            repos: Optional repositories
            user_id: Optional user ID

        Returns:
            Workflow execution result

        Raises:
            AdapterError: If workflow execution fails and is not enqueued
        """
        import uuid

        self._stats["workflows_executed"] += 1

        # Generate workflow ID
        workflow_id = task.get("id", f"wf_{uuid.uuid4().hex[:8]}_{task.get('type', 'default')}")

        try:
            # Execute the workflow
            result = await self.app.execute_workflow_parallel(
                task=task,
                adapter_name=adapter_name,
                repos=repos,
                user_id=user_id,
            )

            return result

        except Exception as e:
            self._stats["workflows_failed"] += 1

            # Try to enqueue in DLQ
            failed_task = await self.enqueue_failed_workflow(
                task_id=workflow_id,
                task=task,
                repos=repos or [],
                error=e,
            )

            if failed_task:
                # Enqueued successfully - return error info
                return {
                    "workflow_id": workflow_id,
                    "status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "dlq_enqueued": True,
                    "dlq_task_id": failed_task.task_id,
                    "retry_policy": failed_task.retry_policy.value,
                    "max_retries": failed_task.max_retries,
                }
            else:
                # Not enqueued - re-raise the exception
                raise AdapterError(
                    message=f"Workflow execution failed and not enqueued in DLQ: {e}",
                    details={
                        "workflow_id": workflow_id,
                        "adapter": adapter_name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "dlq_reason": "skipped_by_policy" or "dlq_full",
                    },
                ) from e

    async def get_statistics(self) -> dict[str, Any]:
        """Get integration statistics.

        Returns:
            Dictionary with integration metrics
        """
        return {
            "strategy": self._strategy.value,
            "workflows_executed": self._stats["workflows_executed"],
            "workflows_failed": self._stats["workflows_failed"],
            "auto_enqueued": self._stats["auto_enqueued"],
            "manually_enqueued": self._stats["manually_enqueued"],
            "skipped_permanent": self._stats["skipped_permanent"],
            "skipped_permission": self._stats["skipped_permission"],
            "enqueue_rate": round(
                self._stats["auto_enqueued"] / max(self._stats["workflows_failed"], 1) * 100,
                2,
            ),
        }

    def reset_statistics(self) -> None:
        """Reset integration statistics."""
        for key in self._stats:
            self._stats[key] = 0
        self._logger.info("DLQ integration statistics reset")


async def create_dlq_integration(app) -> DLQIntegration:
    """Create and configure DLQ integration for an app.

    Args:
        app: MahavishnuApp instance

    Returns:
        Configured DLQIntegration instance
    """
    # Create DLQ if it doesn't exist
    if not hasattr(app, "dlq") or app.dlq is None:
        from .dead_letter_queue import DeadLetterQueue

        app.dlq = DeadLetterQueue(
            max_size=getattr(app.config, "dlq_max_size", 10000),
            opensearch_client=app.opensearch_integration.client if app.opensearch_integration else None,
            observability_manager=app.observability,
        )

    # Create integration
    integration = DLQIntegration(app, app.dlq)

    # Set strategy from config
    strategy_str = getattr(app.config, "dlq_integration_strategy", "automatic")
    try:
        strategy = DLQIntegrationStrategy(strategy_str)
        integration.set_strategy(strategy)
    except ValueError:
        # Invalid strategy, use automatic as default
        integration.set_strategy(DLQIntegrationStrategy.AUTOMATIC)

    return integration
