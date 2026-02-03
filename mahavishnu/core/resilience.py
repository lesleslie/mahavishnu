"""Resilience and error recovery patterns for Mahavishnu."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
import logging
import random
import time
from typing import Any

from ..core.workflow_state import WorkflowStatus


class RecoveryStrategy(Enum):
    """Different strategies for error recovery."""

    RETRY = "retry"
    FALLBACK = "fallback"
    SKIP = "skip"
    ROLLBACK = "rollback"
    NOTIFY = "notify"


class ErrorCategory(Enum):
    """Categories of errors for appropriate handling."""

    TRANSIENT = "transient"  # Temporary issues that might resolve
    PERMANENT = "permanent"  # Issues that won't resolve automatically
    RESOURCE = "resource"  # Resource exhaustion
    PERMISSION = "permission"  # Access denied
    NETWORK = "network"  # Connectivity issues
    VALIDATION = "validation"  # Input validation errors


class RecoveryAction:
    """Definition of a recovery action."""

    def __init__(
        self,
        strategy: RecoveryStrategy,
        category: ErrorCategory,
        max_attempts: int = 3,
        backoff_factor: float = 2.0,
        notify_on_failure: bool = False,
        fallback_function: Callable | None = None,
    ):
        self.strategy = strategy
        self.category = category
        self.max_attempts = max_attempts
        self.backoff_factor = backoff_factor
        self.notify_on_failure = notify_on_failure
        self.fallback_function = fallback_function


class ErrorRecoveryManager:
    """Manages error recovery and resilience patterns."""

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.recovery_actions: dict[str, RecoveryAction] = {}
        self.failed_workflows: dict[str, dict[str, Any]] = {}
        self.recovery_history: list[dict[str, Any]] = []

        # Initialize default recovery patterns
        self._init_default_recovery_patterns()

    def _init_default_recovery_patterns(self):
        """Initialize default recovery patterns for common error types."""
        # Transient errors - retry with exponential backoff
        self.recovery_actions["TRANSIENT"] = RecoveryAction(
            strategy=RecoveryStrategy.RETRY,
            category=ErrorCategory.TRANSIENT,
            max_attempts=5,
            backoff_factor=2.0,
        )

        # Network errors - retry with longer backoff
        self.recovery_actions["NETWORK"] = RecoveryAction(
            strategy=RecoveryStrategy.RETRY,
            category=ErrorCategory.NETWORK,
            max_attempts=3,
            backoff_factor=3.0,
        )

        # Resource errors - try fallback or skip
        self.recovery_actions["RESOURCE"] = RecoveryAction(
            strategy=RecoveryStrategy.FALLBACK,
            category=ErrorCategory.RESOURCE,
            max_attempts=1,
            fallback_function=self._resource_fallback,
        )

        # Permission errors - skip and continue (no point retrying)
        self.recovery_actions["PERMISSION"] = RecoveryAction(
            strategy=RecoveryStrategy.SKIP, category=ErrorCategory.PERMISSION, max_attempts=1
        )

        # Permanent errors - skip and continue
        self.recovery_actions["PERMANENT"] = RecoveryAction(
            strategy=RecoveryStrategy.SKIP, category=ErrorCategory.PERMANENT, max_attempts=1
        )

    async def classify_error(self, error: Exception) -> ErrorCategory:
        """Classify an error into a category."""
        error_str = str(error).lower()

        # Check for transient issues first (most specific patterns)
        # Must check before resource to catch "rate limit" before "limit"
        if any(
            keyword in error_str
            for keyword in (
                "rate limit",
                "ratelimit",
                "rate-limit",
                "throttle",
                "throttling",
                "temporary",
                "temporaryerror",
                "busy",
                "servicebusy",
                "service busy",
                "unavailable",
                "offline",
                "retryable",
                "retryableerror",
            )
        ):
            return ErrorCategory.TRANSIENT

        # Check for network-related errors
        if any(
            keyword in error_str
            for keyword in (
                "connection",
                "timeout",
                "network",
                "connectivity",
                "socket",
                "ssl",
                "certificate",
                "handshake",
            )
        ):
            return ErrorCategory.NETWORK

        # Check for resource-related errors (but not "rate limit" or "range")
        if any(
            keyword in error_str
            for keyword in (
                "memory",
                "disk",
                "quota",
                "capacity",
                "resource",
                "oom",
                "out of memory",
                "out of",
                "exceeded",
                "space",
                "device",
            )
        ) and not any(
            exclude in error_str
            for exclude in (
                "index",
                "range",  # Exclude index/range errors which are usually permanent
            )
        ):
            return ErrorCategory.RESOURCE

        # Check for permission-related errors
        if any(
            keyword in error_str
            for keyword in (
                "permission",
                "denied",
                "forbidden",
                "unauthorized",
                "access",
                "auth",
                "credential",
            )
        ):
            return ErrorCategory.PERMISSION

        # Check for validation-related errors
        if any(
            keyword in error_str
            for keyword in (
                "invalid",
                "malformed",
                "validation",
                "format",
                "valueerror",
                "typeerror",
                "schema",
                "assertion",
                "assertionerror",
            )
        ):
            return ErrorCategory.VALIDATION

        # Default to permanent for unknown errors
        return ErrorCategory.PERMANENT

    async def execute_with_resilience(
        self,
        operation: Callable[..., Awaitable[Any]],
        *args,
        workflow_id: str | None = None,
        repo_path: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Execute an operation with resilience and error recovery."""
        start_time = time.time()

        try:
            result = await operation(*args, **kwargs)
            execution_time = time.time() - start_time

            # Log successful execution
            await self._log_operation_result(
                workflow_id=workflow_id,
                repo_path=repo_path,
                success=True,
                execution_time=execution_time,
                result=result,
            )

            return {
                "success": True,
                "result": result,
                "attempts": 1,
                "execution_time": execution_time,
            }
        except Exception as error:
            execution_time = time.time() - start_time
            error_category = await self.classify_error(error)

            # Log failed execution
            await self._log_operation_result(
                workflow_id=workflow_id,
                repo_path=repo_path,
                success=False,
                execution_time=execution_time,
                error=str(error),
                error_category=error_category.value,
            )

            # Attempt recovery based on error category
            recovery_result = await self._attempt_recovery(
                error=error,
                error_category=error_category,
                operation=operation,
                args=args,
                kwargs=kwargs,
                workflow_id=workflow_id,
                repo_path=repo_path,
            )

            return {
                "success": recovery_result["success"],
                "result": recovery_result.get("result"),
                "error": recovery_result.get("error"),
                "attempts": recovery_result["attempts"] + 1,  # Add 1 for the initial failed attempt
                "execution_time": execution_time,
                "recovered": recovery_result["recovered"],
                "skipped": recovery_result.get("skipped", False),
            }

    async def _attempt_recovery(
        self,
        error: Exception,
        error_category: ErrorCategory,
        operation: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict,
        workflow_id: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Attempt recovery based on error category and strategy."""
        recovery_action = self.recovery_actions.get(error_category.value.upper())

        if not recovery_action:
            # Use default recovery action
            recovery_action = RecoveryAction(
                strategy=RecoveryStrategy.RETRY, category=error_category, max_attempts=3
            )

        strategy = recovery_action.strategy
        max_attempts = recovery_action.max_attempts
        backoff_factor = recovery_action.backoff_factor

        if strategy == RecoveryStrategy.RETRY:
            return await self._retry_operation(
                operation, args, kwargs, max_attempts, backoff_factor, workflow_id, repo_path
            )
        if strategy == RecoveryStrategy.FALLBACK and recovery_action.fallback_function:
            return await self._execute_fallback(
                recovery_action.fallback_function, args, kwargs, workflow_id, repo_path
            )
        if strategy == RecoveryStrategy.SKIP:
            return await self._skip_and_continue(error, workflow_id, repo_path)
        if strategy == RecoveryStrategy.NOTIFY:
            await self._notify_error(error, workflow_id, repo_path)
            return {"success": False, "error": str(error), "attempts": 1, "recovered": False}
        # Default to retry if no specific strategy
        return await self._retry_operation(
            operation, args, kwargs, max_attempts, backoff_factor, workflow_id, repo_path
        )

    async def _retry_operation(
        self,
        operation: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict,
        max_attempts: int,
        backoff_factor: float,
        workflow_id: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Retry an operation with exponential backoff."""
        last_exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    # Calculate backoff time with jitter
                    backoff_time = min(backoff_factor ** (attempt - 1), 60)  # Cap at 60 seconds
                    jitter = random.uniform(0.1, 0.3) * backoff_time
                    await asyncio.sleep(backoff_time + jitter)

                result = await operation(*args, **kwargs)

                # Log successful retry
                await self._log_recovery_action(
                    workflow_id=workflow_id,
                    repo_path=repo_path,
                    action="retry_success",
                    attempt=attempt,
                    result=result,
                )

                return {"success": True, "result": result, "attempts": attempt, "recovered": True}
            except Exception as e:
                last_exception = e
                self.logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for workflow {workflow_id}: {e}"
                )

                # Log failed retry
                await self._log_recovery_action(
                    workflow_id=workflow_id,
                    repo_path=repo_path,
                    action="retry_failed",
                    attempt=attempt,
                    error=str(e),
                )

        # All retries exhausted
        await self._log_recovery_action(
            workflow_id=workflow_id,
            repo_path=repo_path,
            action="retry_exhausted",
            max_attempts=max_attempts,
            error=str(last_exception),
        )

        return {
            "success": False,
            "error": str(last_exception),
            "attempts": max_attempts,
            "recovered": False,
        }

    async def _execute_fallback(
        self,
        fallback_function: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict,
        workflow_id: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Execute a fallback function."""
        try:
            result = await fallback_function(*args, **kwargs)

            # Log successful fallback
            await self._log_recovery_action(
                workflow_id=workflow_id,
                repo_path=repo_path,
                action="fallback_success",
                result=result,
            )

            return {"success": True, "result": result, "attempts": 1, "recovered": True}
        except Exception as e:
            self.logger.error(f"Fallback function failed for workflow {workflow_id}: {e}")

            # Log failed fallback
            await self._log_recovery_action(
                workflow_id=workflow_id, repo_path=repo_path, action="fallback_failed", error=str(e)
            )

            return {"success": False, "error": str(e), "attempts": 1, "recovered": False}

    async def _skip_and_continue(
        self, error: Exception, workflow_id: str | None = None, repo_path: str | None = None
    ) -> dict[str, Any]:
        """Skip the operation and continue."""
        self.logger.warning(f"Skipping operation for workflow {workflow_id} due to error: {error}")

        # Log skip action
        await self._log_recovery_action(
            workflow_id=workflow_id, repo_path=repo_path, action="skip_operation", error=str(error)
        )

        return {
            "success": False,
            "error": str(error),
            "attempts": 1,
            "recovered": True,  # Considered "recovered" as we continued
            "skipped": True,
        }

    async def _notify_error(
        self, error: Exception, workflow_id: str | None = None, repo_path: str | None = None
    ) -> dict[str, Any]:
        """Notify about the error (placeholder for notification system)."""
        self.logger.error(f"Notifying about error in workflow {workflow_id}: {error}")

        # In a real implementation, this would send notifications
        # via email, Slack, etc.

        return {"success": False, "error": str(error), "attempts": 1, "recovered": False}

    async def _resource_fallback(self, *args, **kwargs) -> Any:
        """Fallback function for resource errors."""
        # This is a placeholder - in a real implementation, this would
        # try to use alternative resources or reduce resource usage
        self.logger.info("Executing resource fallback strategy")
        return {"status": "fallback_executed", "message": "Used alternative resource approach"}

    async def _log_operation_result(
        self,
        workflow_id: str | None = None,
        repo_path: str | None = None,
        success: bool = True,
        execution_time: float = 0.0,
        result: Any = None,
        error: str | None = None,
        error_category: str | None = None,
    ):
        """Log operation results for monitoring and analysis."""
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "workflow_id": workflow_id,
            "repo_path": repo_path,
            "success": success,
            "execution_time": execution_time,
            "error": error,
            "error_category": error_category,
            "result_summary": str(result)[:200] if result else None,  # Truncate long results
        }

        # Log to application observability if available
        if self.app.observability:
            if success:
                self.app.observability.log_info(
                    f"Operation completed for workflow {workflow_id}", attributes=log_entry
                )
            else:
                self.app.observability.log_error(
                    f"Operation failed for workflow {workflow_id}: {error}", attributes=log_entry
                )

        # Also log to OpenSearch if available
        if self.app.opensearch_integration:
            if success:
                await self.app.opensearch_integration.log_workflow_update(
                    workflow_id=workflow_id,
                    status="operation_completed",
                    message=f"Operation succeeded for workflow {workflow_id}",
                    attributes=log_entry,
                )
            else:
                await self.app.opensearch_integration.log_error(
                    workflow_id=workflow_id,
                    error_msg=f"Operation failed for workflow {workflow_id}",
                    attributes=log_entry,
                )

    async def _log_recovery_action(
        self,
        workflow_id: str | None = None,
        repo_path: str | None = None,
        action: str = "",
        attempt: int | None = None,
        max_attempts: int | None = None,
        result: Any = None,
        error: str | None = None,
    ):
        """Log recovery actions for monitoring."""
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "workflow_id": workflow_id,
            "repo_path": repo_path,
            "action": action,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "result": str(result)[:200] if result else None,
            "error": error,
        }

        # Log to application observability if available
        if self.app.observability:
            self.app.observability.log_info(
                f"Recovery action '{action}' for workflow {workflow_id}", attributes=log_entry
            )

        # Also log to OpenSearch if available
        if self.app.opensearch_integration:
            await self.app.opensearch_integration.log_workflow_update(
                workflow_id=workflow_id,
                status="recovery_action",
                message=f"Recovery action '{action}' for workflow {workflow_id}",
                attributes=log_entry,
            )

    async def monitor_and_heal_workflows(self):
        """Monitor workflows and attempt to heal failed ones."""
        try:
            # Get workflows that are in failed state
            failed_workflows = await self.app.workflow_state_manager.list_workflows(
                status=WorkflowStatus.FAILED, limit=50
            )

            healed_count = 0
            for workflow in failed_workflows:
                workflow_id = workflow.get("id") or workflow.get("workflow_id")

                if workflow_id:
                    # Attempt to heal the workflow
                    healed = await self._heal_workflow(workflow_id, workflow)
                    if healed:
                        healed_count += 1

            self.logger.info(
                f"Healed {healed_count} workflows out of {len(failed_workflows)} failed workflows"
            )

            # Also check for workflows that have been stuck for too long
            await self._check_stuck_workflows()

        except Exception as e:
            self.logger.error(f"Error in workflow monitoring: {e}")

    async def _heal_workflow(self, workflow_id: str, workflow_state: dict[str, Any]) -> bool:
        """Attempt to heal a failed workflow."""
        try:
            # Check if this workflow has already been retried too many times
            error_count = len(workflow_state.get("errors", []))
            if error_count > 5:  # Don't endlessly retry
                self.logger.info(f"Skipping healing for workflow {workflow_id} - too many errors")
                return False

            # Get the original task and repos
            original_task = workflow_state.get("task", {})
            repos = workflow_state.get("repos", [])

            if not original_task or not repos:
                self.logger.warning(f"Cannot heal workflow {workflow_id} - missing task or repos")
                return False

            # Update the task ID to indicate this is a retry
            original_task["id"] = f"{original_task.get('id', workflow_id)}_retry_{int(time.time())}"

            # Get the adapter name from the original task or workflow
            adapter_name = original_task.get("adapter") or workflow_state.get(
                "adapter", "llamaindex"
            )

            # Retry the workflow with resilience
            result = await self.execute_with_resilience(
                self.app.execute_workflow,
                original_task,
                adapter_name,
                repos,
                workflow_id=workflow_id,
            )

            if result["success"]:
                self.logger.info(f"Successfully healed workflow {workflow_id}")

                # Update workflow state to running again
                await self.app.workflow_state_manager.update(
                    workflow_id=workflow_id,
                    status="running",
                    healed_from_failure=True,
                    retry_count=workflow_state.get("retry_count", 0) + 1,
                )

                return True
            else:
                self.logger.warning(f"Failed to heal workflow {workflow_id}: {result.get('error')}")
                return False

        except Exception as e:
            self.logger.error(f"Error healing workflow {workflow_id}: {e}")
            return False

    async def _check_stuck_workflows(self):
        """Check for workflows that have been running for too long."""
        try:
            # Get workflows that are running but haven't updated in a while
            running_workflows = await self.app.workflow_state_manager.list_workflows(
                status=WorkflowStatus.RUNNING, limit=100
            )

            current_time = datetime.now(UTC)
            timeout_threshold = timedelta(hours=1)  # Consider workflows stuck after 1 hour

            for workflow in running_workflows:
                updated_at_str = workflow.get("updated_at")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                        if current_time - updated_at > timeout_threshold:
                            # Workflow appears stuck, mark as failed
                            workflow_id = workflow.get("id") or workflow.get("workflow_id")
                            if workflow_id:
                                await self.app.workflow_state_manager.update(
                                    workflow_id=workflow_id,
                                    status="failed",
                                    error="Workflow timed out - appears to be stuck",
                                    timed_out=True,
                                )

                                self.logger.warning(
                                    f"Marked stuck workflow {workflow_id} as failed"
                                )
                    except ValueError:
                        # If we can't parse the date, skip this workflow
                        continue

        except Exception as e:
            self.logger.error(f"Error checking for stuck workflows: {e}")

    async def get_recovery_metrics(self) -> dict[str, Any]:
        """Get metrics about recovery operations."""
        # This would aggregate metrics from logs in a real implementation
        return {
            "total_recovery_attempts": len(self.recovery_history),
            "successful_recoveries": len([r for r in self.recovery_history if r.get("success")]),
            "failed_recoveries": len([r for r in self.recovery_history if not r.get("success")]),
            "most_common_error_categories": {},  # Would be computed from logs
            "average_recovery_time": 0.0,  # Would be computed from logs
            "recovery_effectiveness_rate": 0.0,  # Would be computed from logs
        }


class ResiliencePatterns:
    """Higher-level resilience patterns for common scenarios."""

    def __init__(self, app):
        self.app = app
        self.recovery_manager = ErrorRecoveryManager(app)

    async def resilient_workflow_execution(
        self,
        task: dict[str, Any],
        adapter_name: str,
        repos: list[str],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow with built-in resilience patterns."""
        return await self.recovery_manager.execute_with_resilience(
            self.app.execute_workflow_parallel,
            task,
            adapter_name,
            repos,
            user_id=user_id,
            workflow_id=task.get("id", f"resilient_{int(time.time())}"),
        )

    async def resilient_repo_operation(
        self,
        operation: Callable,
        repo_path: str,
        *args,
        workflow_id: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Execute a repository operation with resilience."""
        return await self.recovery_manager.execute_with_resilience(
            operation, *args, repo_path=repo_path, workflow_id=workflow_id, **kwargs
        )

    async def start_monitoring_service(self):
        """Start the background monitoring and healing service."""

        async def monitoring_loop():
            while True:
                try:
                    await self.recovery_manager.monitor_and_heal_workflows()
                    # Check every 5 minutes
                    await asyncio.sleep(300)
                except Exception as e:
                    self.app.logger.error(f"Error in monitoring loop: {e}")
                    # Wait a bit before retrying
                    await asyncio.sleep(60)

        # Run the monitoring loop in the background
        asyncio.create_task(monitoring_loop())
        self.app.logger.info("Started resilience monitoring service")
