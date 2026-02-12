"""Prometheus metrics for WebSocket server.

This module provides Prometheus metrics collection for Mahavishnu WebSocket server,
tracking connections, messages, broadcasts, and performance metrics.

Example:
    >>> from mahavishnu.websocket.metrics import WebSocketMetrics, start_metrics_server
    >>> # Create metrics instance
    >>> metrics = WebSocketMetrics("mahavishnu")
    >>> # Track events
    >>> metrics.inc_message("request")
    >>> metrics.set_connections(5)
    >>> metrics.observe_broadcast("pool:abc", 0.123)
    >>> # Start metrics server
    >>> start_metrics_server(port=9090)
"""

from __future__ import annotations

import logging
from typing import Any

# Lazy import - only import if actually used
try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server, REGISTRY
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

    class Histogram:
        def __init__(self, *args, **kwargs): pass
        def labels(self, **kwargs): return self
        def observe(self, amount): pass

    def start_http_server(port: int):
        logging.warning(f"prometheus_client not available, metrics server not started on port {port}")
        return None

logger = logging.getLogger(__name__)


class WebSocketMetrics:
    """Metrics collector for WebSocket server.

    Tracks:
    - Message counts by type (request, response, event)
    - Connection counts
    - Broadcast durations
    - Active subscriptions
    - Errors by type

    Uses lazy metric initialization to avoid duplicate registration errors.

    Example:
        >>> metrics = WebSocketMetrics("mahavishnu")
        >>> metrics.inc_message("request")
        >>> metrics.set_connections(10)
        >>> metrics.observe_broadcast("pool:local", 0.045)
    """

    def __init__(self, server_name: str):
        """Initialize metrics collector.

        Args:
            server_name: Name of WebSocket server (e.g., "mahavishnu")
        """
        if not PROMETHEUS_AVAILABLE:
            logger.warning("Prometheus client not available, metrics disabled")
            self._enabled = False
        else:
            self._enabled = True

        self.server_name = server_name

        # Lazy metric instances (cached after creation)
        self._metrics_initialized = False
        self._message_counter: Counter | None = None
        self._connection_gauge: Gauge | None = None
        self._broadcast_histograms: dict[str, Histogram] = {}
        self._subscription_gauge: Gauge | None = None
        self._error_counters: dict[str, Counter] = {}

    def _initialize_metrics(self) -> None:
        """Initialize all Prometheus metrics (called once).

        This method creates all metric instances at once to avoid
        duplicate registration errors.
        """
        if self._metrics_initialized:
            return

        # Create message counter (handle duplicate gracefully)
        try:
            self._message_counter = Counter(
                'websocket_messages_total',
                'Total messages processed by WebSocket server',
                ['server', 'message_type']
            )
        except ValueError as e:
            # Metric already registered, get existing one
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names.values():
                if 'websocket_messages_total' in collector:
                    self._message_counter = collector
                    break
            logger.debug(f"Reusing existing message counter: {self.server_name}")

        # Create connection gauge
        try:
            self._connection_gauge = Gauge(
                'websocket_connections',
                'Current number of active WebSocket connections',
                ['server']
            )
        except ValueError:
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names.values():
                if 'websocket_connections' in collector:
                    self._connection_gauge = collector
                    break
            logger.debug(f"Reusing existing connection gauge: {self.server_name}")

        # Create subscription gauge
        try:
            self._subscription_gauge = Gauge(
                'websocket_subscriptions',
                'Current number of active room subscriptions',
                ['server']
            )
        except ValueError:
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names.values():
                if 'websocket_subscriptions' in collector:
                    self._subscription_gauge = collector
                    break
            logger.debug(f"Reusing existing subscription gauge: {self.server_name}")

        self._metrics_initialized = True
        logger.info(f"Initialized Prometheus metrics for server: {self.server_name}")

    def _ensure_enabled(self) -> None:
        """Check if metrics are enabled and initialize if needed."""
        if not self._enabled:
            logger.debug(f"Metrics disabled, skipping operation for server: {self.server_name}")
            return

        # Initialize metrics on first use
        self._initialize_metrics()

    def _get_message_counter(self) -> Counter:
        """Get message counter (initializes if needed)."""
        self._ensure_enabled()
        return self._message_counter

    def _get_connection_gauge(self) -> Gauge:
        """Get connection gauge (initializes if needed)."""
        self._ensure_enabled()
        return self._connection_gauge

    def _get_broadcast_histogram(self, channel: str) -> Histogram:
        """Get or create broadcast histogram for channel."""
        self._ensure_enabled()
        if channel not in self._broadcast_histograms:
            self._broadcast_histograms[channel] = Histogram(
                'websocket_broadcast_duration_seconds',
                'Time taken to broadcast messages to subscribers',
                ['server', 'channel'],
                buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
            )
            logger.info(f"Created broadcast histogram for channel: {channel} in {self.server_name}")

        return self._broadcast_histograms[channel]

    def _get_subscription_gauge(self) -> Gauge:
        """Get subscription gauge (initializes if needed)."""
        self._ensure_enabled()
        return self._subscription_gauge

    def _get_error_counter(self, error_type: str) -> Counter:
        """Get or create error counter for specific error type."""
        self._ensure_enabled()
        if error_type not in self._error_counters:
            self._error_counters[error_type] = Counter(
                'websocket_errors_total',
                'Total errors encountered by WebSocket server',
                ['server', 'error_type']
            )
            logger.info(f"Created error counter '{error_type}' for server: {self.server_name}")

        return self._error_counters[error_type]

    def inc_message(self, message_type: str, amount: int = 1) -> None:
        """Increment message counter.

        Args:
            message_type: Type of message (request, response, event)
            amount: Amount to increment (default: 1)
        """
        self._ensure_enabled()
        counter = self._get_message_counter()
        counter.labels(server=self.server_name, message_type=message_type).inc(amount)
        logger.debug(f"Incremented {message_type} messages by {amount} for {self.server_name}")

    def set_connections(self, count: int) -> None:
        """Set connection count gauge.

        Args:
            count: Number of active connections
        """
        self._ensure_enabled()
        gauge = self._get_connection_gauge()
        gauge.labels(server=self.server_name).set(count)
        logger.debug(f"Set connections to {count} for {self.server_name}")

    def adjust_connections(self, delta: int) -> None:
        """Adjust connection count by delta.

        Args:
            delta: Amount to adjust (positive or negative)
        """
        self._ensure_enabled()
        gauge = self._get_connection_gauge()
        gauge.labels(server=self.server_name).inc(delta)
        logger.debug(f"Adjusted connections by {delta} for {self.server_name}")

    def observe_broadcast(self, channel: str, duration: float) -> None:
        """Record broadcast duration.

        Args:
            channel: Channel name broadcasted to
            duration: Duration in seconds
        """
        self._ensure_enabled()
        histogram = self._get_broadcast_histogram(channel)
        histogram.labels(server=self.server_name, channel=channel).observe(duration)
        logger.debug(f"Recorded broadcast to {channel}: {duration:.4f}s for {self.server_name}")

    def set_subscriptions(self, count: int) -> None:
        """Set subscription count gauge.

        Args:
            count: Number of active subscriptions
        """
        self._ensure_enabled()
        gauge = self._get_subscription_gauge()
        gauge.labels(server=self.server_name).set(count)
        logger.debug(f"Set subscriptions to {count} for {self.server_name}")

    def inc_error(self, error_type: str, amount: int = 1) -> None:
        """Increment error counter.

        Args:
            error_type: Type of error (connection, parse, broadcast, auth)
            amount: Amount to increment (default: 1)
        """
        self._ensure_enabled()
        counter = self._get_error_counter(error_type)
        counter.labels(server=self.server_name, error_type=error_type).inc(amount)
        logger.warning(f"Incremented {error_type} errors by {amount} for {self.server_name}")

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get summary of current metrics.

        Returns:
            Dictionary with metric summaries
        """
        return {
            "server": self.server_name,
            "enabled": self._enabled,
            "initialized": self._metrics_initialized,
            "connection_tracking": self._connection_gauge is not None,
            "broadcast_tracking": len(self._broadcast_histograms) > 0,
            "subscription_tracking": self._subscription_gauge is not None,
            "error_types_tracked": list(self._error_counters.keys()) if self._enabled else [],
        }


def start_metrics_server(port: int = 9090) -> Any:
    """Start Prometheus metrics HTTP server.

    Args:
        port: Metrics server port (default: 9090)

    Returns:
        Prometheus HTTP server thread (or None if unavailable)

    Example:
        >>> from mahavishnu.websocket.metrics import start_metrics_server
        >>> metrics_server = start_metrics_server(port=9090)
        >>> print("Prometheus metrics available on http://localhost:9090")
    """
    if not PROMETHEUS_AVAILABLE:
        logger.warning("Cannot start Prometheus metrics server: prometheus_client not installed")
        logger.warning("Install with: pip install prometheus-client")
        return None

    try:
        return start_http_server(port)
    except OSError as e:
        logger.error(f"Failed to start Prometheus metrics server on port {port}: {e}")
        logger.error(f"Port {port} may already be in use")
        return None


# Metrics instance factory
_instances: dict[str, WebSocketMetrics] = {}


def get_metrics(server_name: str) -> WebSocketMetrics:
    """Get or create metrics instance for a server.

    Args:
        server_name: Name of WebSocket server

    Returns:
        WebSocketMetrics instance for server

    Example:
        >>> from mahavishnu.websocket.metrics import get_metrics
        >>> metrics = get_metrics("mahavishnu")
        >>> metrics.inc_message("request")
    """
    if server_name not in _instances:
        _instances[server_name] = WebSocketMetrics(server_name)
        logger.info(f"Created metrics instance for server: {server_name}")

    return _instances[server_name]


def reset_metrics() -> None:
    """Reset all metrics instances (useful for testing).

    Also clears the Prometheus registry to avoid duplicate errors.

    Example:
        >>> from mahavishnu.websocket.metrics import reset_metrics
        >>> reset_metrics()
        >>> print("All metrics instances and registry cleared")
    """
    global _instances
    _instances.clear()

    # Clear Prometheus registry if available
    if PROMETHEUS_AVAILABLE:
        # Clear all collectors from the default registry
        for collector in list(REGISTRY._collector_to_names.keys()):
            REGISTRY.unregister(collector)
        logger.info("Cleared Prometheus registry")

    logger.info("Reset all metrics instances")
