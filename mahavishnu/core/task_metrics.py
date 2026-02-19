"""Prometheus metrics for Task Orchestration System.

This module provides comprehensive metrics for monitoring task operations:
- Task lifecycle events (created, completed, failed, etc.)
- Quality gate results
- Performance metrics (latency, throughput)
- Error rates and categories

Usage:
    from mahavishnu.core.task_metrics import TaskMetrics, get_task_metrics

    metrics = get_task_metrics()
    metrics.record_task_created("session-buddy", "high")
    metrics.record_task_completed("session-buddy", duration_seconds=120.5)
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Lazy initialization flag
_metrics_initialized = False
_metrics_lock = threading.Lock()

# Global metrics instance (lazy singleton)
_task_metrics: "TaskMetrics | None" = None


def _ensure_prometheus_available() -> bool:
    """Check if prometheus_client is available."""
    try:
        import prometheus_client  # noqa: F401
        return True
    except ImportError:
        return False


class TaskMetrics:
    """Prometheus metrics for task orchestration operations.

    This class provides metrics for monitoring the health and performance
    of the task orchestration system. Metrics are exposed via Prometheus
    for aggregation in Grafana dashboards.

    Metrics Categories:
        - task_operations_total: Counter of task lifecycle events
        - task_duration_seconds: Histogram of task completion times
        - quality_gate_results_total: Counter of quality gate outcomes
        - active_tasks_gauge: Current number of tasks by status
        - task_errors_total: Counter of task-related errors

    Example:
        >>> metrics = TaskMetrics()
        >>> metrics.record_task_created("session-buddy", "high")
        >>> metrics.record_task_completed("session-buddy", 120.5)
        >>> metrics.start_server(9091)
    """

    def __init__(self) -> None:
        """Initialize task metrics.

        This will attempt to import prometheus_client and create metrics.
        If prometheus_client is not available, metrics will be no-ops.
        """
        self._prometheus_available = _ensure_prometheus_available()

        if self._prometheus_available:
            self._init_prometheus_metrics()
        else:
            logger.warning(
                "prometheus_client not available. Metrics will be no-ops. "
                "Install with: pip install prometheus-client"
            )
            self._init_noop_metrics()

        logger.debug("TaskMetrics initialized")

    def _init_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        from prometheus_client import Counter, Gauge, Histogram

        # Task lifecycle events counter
        self.task_operations_total = Counter(
            "mahavishnu_task_operations_total",
            "Total count of task operations",
            ["operation", "repository", "priority"],
        )

        # Task duration histogram (for completed tasks)
        self.task_duration_seconds = Histogram(
            "mahavishnu_task_duration_seconds",
            "Duration of task execution in seconds",
            ["repository"],
            buckets=[30, 60, 120, 300, 600, 1200, 1800, 3600, 7200],  # 30s to 2h
        )

        # Quality gate results counter
        self.quality_gate_results_total = Counter(
            "mahavishnu_quality_gate_results_total",
            "Total count of quality gate results",
            ["result", "repository"],
        )

        # Active tasks gauge by status
        self.active_tasks_gauge = Gauge(
            "mahavishnu_active_tasks",
            "Current number of active tasks",
            ["status", "repository"],
        )

        # Task errors counter
        self.task_errors_total = Counter(
            "mahavishnu_task_errors_total",
            "Total count of task errors",
            ["error_type", "repository"],
        )

        # Webhook metrics
        self.webhook_operations_total = Counter(
            "mahavishnu_webhook_operations_total",
            "Total count of webhook operations",
            ["operation", "result"],
        )

        # Validation failures counter
        self.validation_failures_total = Counter(
            "mahavishnu_validation_failures_total",
            "Total count of validation failures",
            ["field", "error_type"],
        )

        # Audit log events counter
        self.audit_events_total = Counter(
            "mahavishnu_audit_events_total",
            "Total count of audit events",
            ["event_type", "result"],
        )

    def _init_noop_metrics(self) -> None:
        """Initialize no-op metrics for when Prometheus is not available."""

        class NoOpMetric:
            """No-op metric that does nothing."""

            def labels(self, *args: Any, **kwargs: Any) -> "NoOpMetric":
                return self

            def inc(self, *args: Any, **kwargs: Any) -> None:
                pass

            def dec(self, *args: Any, **kwargs: Any) -> None:
                pass

            def observe(self, *args: Any, **kwargs: Any) -> None:
                pass

            def set(self, *args: Any, **kwargs: Any) -> None:
                pass

        noop = NoOpMetric()
        self.task_operations_total = noop
        self.task_duration_seconds = noop
        self.quality_gate_results_total = noop
        self.active_tasks_gauge = noop
        self.task_errors_total = noop
        self.webhook_operations_total = noop
        self.validation_failures_total = noop
        self.audit_events_total = noop

    # Task lifecycle metrics

    def record_task_created(
        self, repository: str, priority: str = "medium"
    ) -> None:
        """Record a task creation event.

        Args:
            repository: Repository name
            priority: Task priority (low, medium, high, critical)
        """
        self.task_operations_total.labels(
            operation="created", repository=repository, priority=priority
        ).inc()
        self.active_tasks_gauge.labels(status="pending", repository=repository).inc()

    def record_task_started(self, repository: str) -> None:
        """Record a task start event.

        Args:
            repository: Repository name
        """
        self.task_operations_total.labels(
            operation="started", repository=repository, priority="unknown"
        ).inc()
        self.active_tasks_gauge.labels(status="pending", repository=repository).dec()
        self.active_tasks_gauge.labels(
            status="in_progress", repository=repository
        ).inc()

    def record_task_completed(
        self, repository: str, duration_seconds: float
    ) -> None:
        """Record a task completion event.

        Args:
            repository: Repository name
            duration_seconds: Time from start to completion
        """
        self.task_operations_total.labels(
            operation="completed", repository=repository, priority="unknown"
        ).inc()
        self.task_duration_seconds.labels(repository=repository).observe(
            duration_seconds
        )
        self.active_tasks_gauge.labels(
            status="in_progress", repository=repository
        ).dec()

    def record_task_cancelled(self, repository: str) -> None:
        """Record a task cancellation event.

        Args:
            repository: Repository name
        """
        self.task_operations_total.labels(
            operation="cancelled", repository=repository, priority="unknown"
        ).inc()
        self.active_tasks_gauge.labels(
            status="in_progress", repository=repository
        ).dec()

    def record_task_blocked(self, repository: str) -> None:
        """Record a task blocked event.

        Args:
            repository: Repository name
        """
        self.task_operations_total.labels(
            operation="blocked", repository=repository, priority="unknown"
        ).inc()
        self.active_tasks_gauge.labels(
            status="in_progress", repository=repository
        ).dec()
        self.active_tasks_gauge.labels(status="blocked", repository=repository).inc()

    def record_task_unblocked(self, repository: str) -> None:
        """Record a task unblocked event.

        Args:
            repository: Repository name
        """
        self.task_operations_total.labels(
            operation="unblocked", repository=repository, priority="unknown"
        ).inc()
        self.active_tasks_gauge.labels(status="blocked", repository=repository).dec()
        self.active_tasks_gauge.labels(
            status="in_progress", repository=repository
        ).inc()

    # Quality gate metrics

    def record_quality_gate_passed(self, repository: str) -> None:
        """Record a quality gate pass event.

        Args:
            repository: Repository name
        """
        self.quality_gate_results_total.labels(result="passed", repository=repository).inc()

    def record_quality_gate_failed(self, repository: str) -> None:
        """Record a quality gate failure event.

        Args:
            repository: Repository name
        """
        self.quality_gate_results_total.labels(result="failed", repository=repository).inc()

    # Error metrics

    def record_task_error(self, repository: str, error_type: str) -> None:
        """Record a task error event.

        Args:
            repository: Repository name
            error_type: Error category (validation, timeout, database, etc.)
        """
        self.task_errors_total.labels(error_type=error_type, repository=repository).inc()

    def record_validation_failure(self, field: str, error_type: str) -> None:
        """Record a validation failure event.

        Args:
            field: Field that failed validation
            error_type: Type of validation error
        """
        self.validation_failures_total.labels(field=field, error_type=error_type).inc()

    # Webhook metrics

    def record_webhook_verified(self) -> None:
        """Record a successful webhook verification."""
        self.webhook_operations_total.labels(
            operation="verify", result="success"
        ).inc()

    def record_webhook_rejected(self, reason: str) -> None:
        """Record a rejected webhook.

        Args:
            reason: Rejection reason (signature_mismatch, expired, replay_attack, etc.)
        """
        self.webhook_operations_total.labels(operation="verify", result=reason).inc()

    # Audit metrics

    def record_audit_event(self, event_type: str, result: str = "success") -> None:
        """Record an audit event.

        Args:
            event_type: Type of audit event
            result: Result (success, failure, denied)
        """
        self.audit_events_total.labels(event_type=event_type, result=result).inc()

    # Server management

    def start_server(self, port: int = 9091) -> None:
        """Start the Prometheus metrics server.

        Args:
            port: Port to expose metrics on (default: 9091)
        """
        if not self._prometheus_available:
            logger.warning("Cannot start metrics server: prometheus_client not available")
            return

        from prometheus_client import start_http_server

        global _metrics_initialized

        with _metrics_lock:
            if _metrics_initialized:
                logger.warning(f"Metrics server already running on port {port}")
                return

            try:
                start_http_server(port)
                _metrics_initialized = True
                logger.info(f"Prometheus metrics server started on port {port}")
            except OSError as e:
                if "Address already in use" in str(e):
                    logger.warning(f"Port {port} already in use, metrics server may be running")
                else:
                    raise


def get_task_metrics() -> TaskMetrics:
    """Get the singleton TaskMetrics instance.

    Returns:
        TaskMetrics singleton instance
    """
    global _task_metrics

    if _task_metrics is None:
        _task_metrics = TaskMetrics()

    return _task_metrics


__all__ = [
    "TaskMetrics",
    "get_task_metrics",
]
