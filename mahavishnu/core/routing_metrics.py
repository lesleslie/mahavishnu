"""Prometheus metrics for adaptive routing system.

Tracks adapter performance, routing decisions, cost optimization,
and A/B testing metrics for observability.

Design:
- Prometheus Counter for cumulative tracking
- Prometheus Gauge for current values
- Prometheus Histogram for distributions
- Lazy metric initialization to avoid duplicate registration
"""

from __future__ import annotations

import logging
import time
from typing import Any

from mahavishnu.core.metrics_schema import AdapterType, TaskType

# Lazy import - only import if actually used
try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server, REGISTRY
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Create dummy classes for graceful degradation
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def inc(self, amount=1): pass
        def count(self): return 0

    class Gauge:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def set(self, value): pass
        def set_to_current_value(self): pass
        def inc(self, amount=1): pass
        def dec(self, amount=1): pass

    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def observe(self, amount): pass
        def time(self): return self

    class Summary:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def observe(self, amount): pass
        def time(self): return self

    def start_http_server(port: int):
        logging.warning(f"prometheus_client not available, metrics server not started on port {port}")
        return None

logger = logging.getLogger(__name__)


class RoutingMetrics:
    """Prometheus metrics collector for adaptive routing.

    Tracks:
    - Routing decisions by adapter and task type
    - Adapter success rates and latency
    - Cost tracking and budget alerts
    - Fallback chain metrics
    - A/B testing metrics

    Uses lazy metric initialization to avoid duplicate registration errors.
    """

    def __init__(self, server_name: str = "mahavishnu"):
        """Initialize routing metrics collector.

        Args:
            server_name: Name of routing server (default: "mahavishnu")
        """
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client not available, routing metrics disabled")
            self._enabled = False
        else:
            self._enabled = True

        self.server_name = server_name

        # Lazy metric instances (cached after creation)
        self._metrics_initialized = False

        # Counter metrics
        self._routing_decision_counter: Counter | None = None
        self._adapter_execution_counter: Counter | None = None
        self._fallback_counter: Counter | None = None
        self._cost_counter: Counter | None = None
        self._budget_alert_counter: Counter | None = None
        self._ab_test_counter: Counter | None = None

        # Gauge metrics
        self._adapter_success_rate_gauge: dict[AdapterType, Gauge] = {}
        self._adapter_latency_gauge: dict[AdapterType, Gauge] = {}
        self._current_cost_gauge: Gauge | None = None
        self._active_experiments_gauge: Gauge | None = None

        # Histogram metrics
        self._routing_latency_histogram: Histogram | None = None
        self._adapter_latency_histogram: Histogram | None = None
        self._fallback_chain_histogram: Histogram | None = None
        self._cost_distribution_histogram: Histogram | None = None

        # Summary metrics
        self._latency_summary: dict[AdapterType, Summary] = {}

    def _initialize_metrics(self) -> None:
        """Initialize all Prometheus metrics (called once).

        This method creates all metric instances at once to avoid
        duplicate registration errors.
        """
        if self._metrics_initialized:
            return

        # Create routing decision counter
        try:
            self._routing_decision_counter = Counter(
                'mahavishnu_routing_decisions_total',
                'Total routing decisions made by StatisticalRouter',
                ['server', 'adapter', 'task_type']
            )
        except ValueError:
            logger.debug(f"Reusing existing routing decision counter: {self.server_name}")

        # Create adapter execution counter
        try:
            self._adapter_execution_counter = Counter(
                'mahavishnu_adapter_executions_total',
                'Total adapter executions',
                ['server', 'adapter', 'status']
            )
        except ValueError:
            logger.debug(f"Reusing existing adapter execution counter: {self.server_name}")

        # Create fallback counter
        try:
            self._fallback_counter = Counter(
                'mahavishnu_routing_fallbacks_total',
                'Total adapter fallbacks triggered',
                ['server', 'original_adapter', 'fallback_adapter']
            )
        except ValueError:
            logger.debug(f"Reusing existing fallback counter: {self.server_name}")

        # Create cost counter
        try:
            self._cost_counter = Counter(
                'mahavishnu_routing_cost_usd_total',
                'Total routing cost in USD',
                ['server', 'adapter', 'task_type']
            )
        except ValueError:
            logger.debug(f"Reusing existing cost counter: {self.server_name}")

        # Create budget alert counter
        try:
            self._budget_alert_counter = Counter(
                'mahavishnu_budget_alerts_total',
                'Total budget alerts triggered',
                ['server', 'budget_type', 'severity']
            )
        except ValueError:
            logger.debug(f"Reusing existing budget alert counter: {self.server_name}")

        # Create A/B test counter
        try:
            self._ab_test_counter = Counter(
                'mahavishnu_ab_tests_total',
                'Total A/B test events',
                ['server', 'experiment_id', 'event_type']
            )
        except ValueError:
            logger.debug(f"Reusing existing A/B test counter: {self.server_name}")

        # Create current cost gauge
        try:
            self._current_cost_gauge = Gauge(
                'mahavishnu_routing_cost_usd_current',
                'Current routing cost in USD',
                ['server', 'budget_type']
            )
        except ValueError:
            logger.debug(f"Reusing existing current cost gauge: {self.server_name}")

        # Create active experiments gauge
        try:
            self._active_experiments_gauge = Gauge(
                'mahavishnu_ab_tests_active',
                'Number of active A/B tests',
                ['server']
            )
        except ValueError:
            logger.debug(f"Reusing existing active experiments gauge: {self.server_name}")

        # Create routing latency histogram
        try:
            self._routing_latency_histogram = Histogram(
                'mahavishnu_routing_latency_seconds',
                'Time taken to make routing decisions',
                ['server'],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
            )
        except ValueError:
            logger.debug(f"Reusing existing routing latency histogram: {self.server_name}")

        # Create fallback chain histogram
        try:
            self._fallback_chain_histogram = Histogram(
                'mahavishnu_routing_fallback_chain_length',
                'Length of fallback chains',
                ['server'],
                buckets=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
            )
        except ValueError:
            logger.debug(f"Reusing existing fallback chain histogram: {self.server_name}")

        # Create cost distribution histogram
        try:
            self._cost_distribution_histogram = Histogram(
                'mahavishnu_routing_cost_usd_distribution',
                'Distribution of routing costs in USD',
                ['server', 'adapter'],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
            )
        except ValueError:
            logger.debug(f"Reusing existing cost distribution histogram: {self.server_name}")

        # Create adapter latency histogram (SINGLE histogram for all adapters with 'adapter' label)
        try:
            self._adapter_latency_histogram = Histogram(
                'mahavishnu_adapter_latency_seconds',
                'Adapter execution latency',
                ['server', 'adapter'],
                buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
            )
        except ValueError:
            logger.debug(f"Reusing existing adapter latency histogram: {self.server_name}")

        self._metrics_initialized = True
        logger.info(f"Initialized Prometheus routing metrics for server: {self.server_name}")

    def _ensure_enabled(self) -> None:
        """Check if metrics are enabled and initialize if needed."""
        if not self._enabled:
            logger.debug(f"Routing metrics disabled, skipping operation for server: {self.server_name}")
            return

        # Initialize metrics on first use
        self._initialize_metrics()

    def _get_adapter_latency_histogram(self) -> Histogram:
        """Get the shared adapter latency histogram.

        Single histogram with 'adapter' label distinguishes between adapters
        without needing per-adapter histogram instances.
        """
        self._ensure_enabled()

        histogram = self._adapter_latency_histogram
        if histogram is None:
            raise RuntimeError(
                f"Adapter latency histogram not initialized. "
                f"_ensure_enabled() should have been called first. "
                f"Server: {self.server_name}"
            )

        return histogram

    def record_routing_decision(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        preference_order: int,
    ) -> None:
        """Record a routing decision.

        Args:
            adapter: Selected adapter
            task_type: Type of task
            preference_order: Position in preference order (1=first choice)
        """
        self._ensure_enabled()
        self._routing_decision_counter.labels(
            server=self.server_name,
            adapter=adapter.value,
            task_type=task_type.value
        ).inc()
        logger.debug(
            f"Recorded routing decision: {adapter} for {task_type.value} "
            f"(choice #{preference_order})"
        )

    def record_adapter_execution(
        self,
        adapter: AdapterType,
        success: bool,
        latency_ms: int,
    ) -> None:
        """Record adapter execution.

        Args:
            adapter: Adapter executed
            success: Whether execution succeeded
            latency_ms: Execution duration in milliseconds
        """
        self._ensure_enabled()
        status = "success" if success else "failure"
        self._adapter_execution_counter.labels(
            server=self.server_name,
            adapter=adapter.value,
            status=status
        ).inc()

        # Record latency
        histogram = self._get_adapter_latency_histogram()
        histogram.labels(server=self.server_name, adapter=adapter.value).observe(latency_ms / 1000.0)

        logger.debug(
            f"Recorded adapter execution: {adapter.value} - {status} ({latency_ms}ms)"
        )

    def record_fallback(
        self,
        original_adapter: AdapterType,
        fallback_adapter: AdapterType,
    ) -> None:
        """Record adapter fallback event.

        Args:
            original_adapter: Adapter that failed
            fallback_adapter: Adapter chosen as fallback
        """
        self._ensure_enabled()
        self._fallback_counter.labels(
            server=self.server_name,
            original_adapter=original_adapter,
            fallback_adapter=fallback_adapter.value
        ).inc()
        logger.info(
            f"Recorded fallback: {original_adapter.value} -> {fallback_adapter.value}"
        )

    def record_fallback_chain_length(self, chain_length: int) -> None:
        """Record fallback chain length.

        Args:
            chain_length: Number of adapters attempted
        """
        self._ensure_enabled()
        if self._fallback_chain_histogram:
            self._fallback_chain_histogram.labels(server=self.server_name).observe(chain_length)
            logger.debug(f"Recorded fallback chain length: {chain_length}")

    def record_cost(
        self,
        adapter: AdapterType,
        task_type: TaskType,
        cost_usd: float,
    ) -> None:
        """Record routing cost.

        Args:
            adapter: Adapter used
            task_type: Type of task
            cost_usd: Cost in USD
        """
        self._ensure_enabled()
        self._cost_counter.labels(
            server=self.server_name,
            adapter=adapter.value,
            task_type=task_type.value
        ).inc(cost_usd)

        if self._cost_distribution_histogram:
            self._cost_distribution_histogram.labels(
                server=self.server_name,
                adapter=adapter.value
            ).observe(cost_usd)

        logger.debug(f"Recorded cost: ${cost_usd:.4f} for {adapter.value}")

    def set_current_cost(
        self,
        budget_type: str,
        cost_usd: float,
    ) -> None:
        """Set current cost gauge.

        Args:
            budget_type: Type of budget (daily, weekly, monthly, per_task_type)
            cost_usd: Current accumulated cost
        """
        self._ensure_enabled()
        if self._current_cost_gauge:
            self._current_cost_gauge.labels(
                server=self.server_name,
                budget_type=budget_type
            ).set(cost_usd)
            logger.debug(f"Set current cost for {budget_type}: ${cost_usd:.2f}")

    def trigger_budget_alert(
        self,
        budget_type: str,
        severity: str,
    ) -> None:
        """Trigger budget alert.

        Args:
            budget_type: Type of budget that exceeded threshold
            severity: Alert severity (warning, critical)
        """
        self._ensure_enabled()
        if self._budget_alert_counter:
            self._budget_alert_counter.labels(
                server=self.server_name,
                budget_type=budget_type,
                severity=severity
            ).inc()
            logger.warning(
                f"Budget alert triggered: {budget_type} - {severity}"
            )

    def record_ab_test_event(
        self,
        experiment_id: str,
        event_type: str,
    ) -> None:
        """Record A/B test event.

        Args:
            experiment_id: Unique experiment identifier
            event_type: Event type (start, complete, evaluate, variant_assigned)
        """
        self._ensure_enabled()
        if self._ab_test_counter:
            self._ab_test_counter.labels(
                server=self.server_name,
                experiment_id=experiment_id,
                event_type=event_type
            ).inc()
            logger.debug(f"Recorded A/B test event: {event_type} for {experiment_id}")

    def set_active_experiments(self, count: int) -> None:
        """Set active experiments gauge.

        Args:
            count: Number of active A/B tests
        """
        self._ensure_enabled()
        if self._active_experiments_gauge:
            self._active_experiments_gauge.labels(server=self.server_name).set(count)
            logger.debug(f"Set active experiments: {count}")

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get summary of current metrics.

        Returns:
            Dictionary with metric summaries
        """
        return {
            "server": self.server_name,
            "enabled": self._enabled,
            "initialized": self._metrics_initialized,
            "routing_tracking": self._routing_decision_counter is not None,
            "adapter_execution_tracking": self._adapter_execution_counter is not None,
            "fallback_tracking": self._fallback_counter is not None,
            "cost_tracking": self._cost_counter is not None,
            "alert_tracking": self._budget_alert_counter is not None,
            "ab_test_tracking": self._ab_test_counter is not None,
        }


def start_routing_metrics_server(port: int = 9091) -> Any:
    """Start Prometheus metrics HTTP server for routing metrics.

    Args:
        port: Metrics server port (default: 9091)

    Returns:
        Prometheus HTTP server thread (or None if unavailable)

    Example:
        >>> from mahavishnu.core.routing_metrics import start_routing_metrics_server
        >>> metrics_server = start_routing_metrics_server(port=9091)
        >>> print("Routing metrics available on http://localhost:9091")
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Cannot start Prometheus routing metrics server: prometheus_client not installed")
        logger.warning("Install with: pip install prometheus-client")
        return None

    try:
        return start_http_server(port)
    except OSError as e:
        logger.error(f"Failed to start Prometheus metrics server on port {port}: {e}")
        logger.error(f"Port {port} may already be in use")
        return None


# Metrics instance factory
_instances: dict[str, RoutingMetrics] = {}


def get_routing_metrics(server_name: str = "mahavishnu") -> RoutingMetrics:
    """Get or create routing metrics instance.

    Args:
        server_name: Name of routing server (default: "mahavishnu")

    Returns:
        RoutingMetrics instance for server

    Example:
        >>> from mahavishnu.core.routing_metrics import get_routing_metrics
        >>> metrics = get_routing_metrics()
        >>> metrics.record_routing_decision(AdapterType.PREFECT, TaskType.WORKFLOW, 1)
    """
    if server_name not in _instances:
        _instances[server_name] = RoutingMetrics(server_name)
        logger.info(f"Created routing metrics instance for server: {server_name}")

    return _instances[server_name]


def reset_routing_metrics() -> None:
    """Reset all routing metrics instances (useful for testing).

    Also clears Prometheus registry to avoid duplicate errors.

    Example:
        >>> from mahavishnu.core.routing_metrics import reset_routing_metrics
        >>> reset_routing_metrics()
        >>> print("All routing metrics instances and registry cleared")
    """
    global _instances
    _instances.clear()

    # Clear Prometheus registry if available
    if PROMETHEUS_AVAILABLE:
        # Clear all collectors from default registry
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        logger.info("Cleared Prometheus registry")

    logger.info("Reset all routing metrics instances")


__all__ = [
    "RoutingMetrics",
    "get_routing_metrics",
    "reset_routing_metrics",
    "start_routing_metrics_server",
]
