"""Prometheus metrics collection for all MCP servers.

This module provides Prometheus instrumentation for tracking:
- Request metrics (latency, count, errors)
- Resource metrics (memory, CPU, disk)
- Business metrics (tool executions, agent tasks)
- Custom metrics for domain-specific operations
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import logging
import time
from typing import TYPE_CHECKING, Any

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)

if TYPE_CHECKING:
    from prometheus_client.metrics import MetricWrapperBase

logger = logging.getLogger(__name__)

# ============================================================================
# Request Metrics
# ============================================================================

# HTTP request metrics
http_requests_total = Counter(
    "mcp_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "mcp_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

http_requests_in_progress = Gauge(
    "mcp_http_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "endpoint"],
)

# ============================================================================
# MCP Tool Metrics
# ============================================================================

mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total MCP tool calls",
    ["tool_name", "status"],  # status: success, error, timeout
)

mcp_tool_duration_seconds = Histogram(
    "mcp_tool_duration_seconds",
    "MCP tool execution duration",
    ["tool_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

mcp_tools_registered = Gauge(
    "mcp_tools_registered",
    "Number of registered MCP tools",
    ["server"],
)

# ============================================================================
# Agent/Workflow Metrics (Mahavishnu-specific)
# ============================================================================

agent_tasks_total = Counter(
    "agent_tasks_total",
    "Total agent tasks executed",
    ["agent_type", "adapter", "status"],
)

agent_task_duration_seconds = Histogram(
    "agent_task_duration_seconds",
    "Agent task execution duration",
    ["agent_type", "adapter"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
)

agent_tasks_in_progress = Gauge(
    "agent_tasks_in_progress",
    "Agent tasks currently in progress",
    ["agent_type", "adapter"],
)

pool_workers_active = Gauge(
    "pool_workers_active",
    "Number of active workers in pools",
    ["pool_type"],
)

pool_tasks_queued = Gauge(
    "pool_tasks_queued",
    "Number of tasks waiting in pool queues",
    ["pool_type"],
)

# ============================================================================
# Memory Aggregation Metrics (AkOSHA-specific)
# ============================================================================

memory_syncs_total = Counter(
    "memory_syncs_total",
    "Total memory synchronization operations",
    ["source", "status"],
)

memory_sync_duration_seconds = Histogram(
    "memory_sync_duration_seconds",
    "Memory synchronization duration",
    ["source"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

memories_stored = Gauge(
    "memories_stored_total",
    "Total memories stored in AkOSHA",
    ["source_instance"],
)

embeddings_generated = Counter(
    "embeddings_generated_total",
    "Total embeddings generated",
    ["model"],
)

# ============================================================================
# Session Management Metrics (Session-Buddy-specific)
# ============================================================================

session_operations_total = Counter(
    "session_operations_total",
    "Total session operations",
    ["operation", "status"],  # operation: create, read, update, delete, search
)

session_duration_active = Summary(
    "session_duration_seconds",
    "Session active duration",
)

sessions_active = Gauge(
    "sessions_active_total",
    "Number of active sessions",
)

reflections_stored = Counter(
    "reflections_stored_total",
    "Total reflections stored",
    ["type"],
)

# ============================================================================
# System Resource Metrics
# ============================================================================

system_memory_usage_bytes = Gauge(
    "system_memory_usage_bytes",
    "System memory usage",
    ["type"],  # type: rss, vms, shared
)

system_cpu_usage_percent = Gauge(
    "system_cpu_usage_percent",
    "System CPU usage percentage",
    ["core"],
)

system_disk_usage_percent = Gauge(
    "system_disk_usage_percent",
    "System disk usage percentage",
    ["mount_point"],
)

system_file_descriptors_open = Gauge(
    "system_file_descriptors_open",
    "Number of open file descriptors",
)

# ============================================================================
# Cache Metrics
# ============================================================================

cache_operations_total = Counter(
    "cache_operations_total",
    "Total cache operations",
    ["cache_name", "operation", "result"],  # operation: get, set, delete; result: hit, miss, error
)

cache_size_bytes = Gauge(
    "cache_size_bytes",
    "Cache size in bytes",
    ["cache_name"],
)

cache_evictions_total = Counter(
    "cache_evictions_total",
    "Total cache evictions",
    ["cache_name", "reason"],
)

# ============================================================================
# Custom Metrics Registry
# ============================================================================

_custom_metrics: dict[str, MetricWrapperBase] = {}


def create_counter(
    name: str,
    description: str,
    labels: list[str] | None = None,
) -> Counter:
    """Create and register a custom counter metric.

    Args:
        name: Metric name
        description: Metric description
        labels: Label names

    Returns:
        Counter instance

    Example:
        >>> my_counter = create_counter(
        ...     "my_operations_total",
        ...     "Total my operations",
        ...     ["operation_type"]
        ... )
        >>> my_counter.labels(operation_type="read").inc()
    """
    if name in _custom_metrics:
        logger.warning(f"Metric {name} already exists")
        return _custom_metrics[name]  # type: ignore

    counter = Counter(name, description, labels or [])
    _custom_metrics[name] = counter
    logger.info(f"Created custom counter metric: {name}")
    return counter


def create_gauge(
    name: str,
    description: str,
    labels: list[str] | None = None,
) -> Gauge:
    """Create and register a custom gauge metric.

    Args:
        name: Metric name
        description: Metric description
        labels: Label names

    Returns:
        Gauge instance

    Example:
        >>> queue_size = create_gauge(
        ...     "queue_size",
        ...     "Current queue size",
        ...     ["queue_name"]
        ... )
        >>> queue_size.labels(queue_name="tasks").set(42)
    """
    if name in _custom_metrics:
        logger.warning(f"Metric {name} already exists")
        return _custom_metrics[name]  # type: ignore

    gauge = Gauge(name, description, labels or [])
    _custom_metrics[name] = gauge
    logger.info(f"Created custom gauge metric: {name}")
    return gauge


def create_histogram(
    name: str,
    description: str,
    labels: list[str] | None = None,
    buckets: tuple[float, ...] | None = None,
) -> Histogram:
    """Create and register a custom histogram metric.

    Args:
        name: Metric name
        description: Metric description
        labels: Label names
        buckets: Histogram buckets (defaults to Prometheus defaults)

    Returns:
        Histogram instance

    Example:
        >>> latency = create_histogram(
        ...     "operation_latency_seconds",
        ...     "Operation latency",
        ...     ["operation"],
        ...     buckets=(.1, .5, 1.0, 5.0, 10.0)
        ... )
        >>> latency.labels(operation="process").observe(2.5)
    """
    if name in _custom_metrics:
        logger.warning(f"Metric {name} already exists")
        return _custom_metrics[name]  # type: ignore

    histogram = Histogram(name, description, labels or [], buckets=buckets)
    _custom_metrics[name] = histogram
    logger.info(f"Created custom histogram metric: {name}")
    return histogram


# ============================================================================
# Decorators for Automatic Metrics
# ============================================================================


def track_time(
    histogram: Histogram,
    labels: dict[str, str] | None = None,
):
    """Decorator to track function execution time.

    Args:
        histogram: Histogram metric to use
        labels: Static labels to apply

    Example:
        >>> track_time_histogram = Histogram("function_duration_seconds", ["function_name"])
        >>>
        >>> @track_time(track_time_histogram, {"function_name": "my_func"})
        >>> async def my_func():
        ...     return 42
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            label_values = labels or {}
            if "function_name" not in label_values:
                label_values["function_name"] = func.__name__

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                histogram.labels(**label_values).observe(duration)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            label_values = labels or {}
            if "function_name" not in label_values:
                label_values["function_name"] = func.__name__

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                histogram.labels(**label_values).observe(duration)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def track_calls(
    counter: Counter,
    labels: dict[str, str] | None = None,
):
    """Decorator to track function call counts.

    Args:
        counter: Counter metric to use
        labels: Static labels to apply

    Example:
        >>> calls_counter = Counter("function_calls_total", ["function_name", "status"])
        >>>
        >>> @track_calls(calls_counter, {"function_name": "my_func"})
        >>> async def my_func():
        ...     return 42
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            label_values = labels or {}
            if "function_name" not in label_values:
                label_values["function_name"] = func.__name__

            try:
                result = await func(*args, **kwargs)
                counter.labels(**label_values, status="success").inc()
                return result
            except Exception:
                counter.labels(**label_values, status="error").inc()
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            label_values = labels or {}
            if "function_name" not in label_values:
                label_values["function_name"] = func.__name__

            try:
                result = func(*args, **kwargs)
                counter.labels(**label_values, status="success").inc()
                return result
            except Exception:
                counter.labels(**label_values, status="error").inc()
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# ============================================================================
# Metrics Export
# ============================================================================


def get_metrics_registry() -> CollectorRegistry:
    """Get the Prometheus metrics registry.

    Returns:
        CollectorRegistry with all metrics

    Example:
        >>> registry = get_metrics_registry()
        >>> metrics = generate_latest(registry)
    """
    return REGISTRY


def expose_metrics(registry: CollectorRegistry | None = None) -> bytes:
    """Generate Prometheus metrics exposition format.

    Args:
        registry: Optional registry (defaults to global REGISTRY)

    Returns:
        Metrics in Prometheus text format

    Example:
        >>> from fastapi import Response
        >>> metrics = expose_metrics()
        >>> return Response(content=metrics, media_type="text/plain")
    """
    return generate_latest(registry or REGISTRY)


# ============================================================================
# Metrics Endpoint (for FastAPI)
# ============================================================================


async def metrics_endpoint():
    """FastAPI endpoint handler for /metrics.

    Example:
        >>> from fastapi import FastAPI, Response
        >>> app = FastAPI()
        >>>
        >>> @app.get("/metrics")
        >>> async def metrics():
        ...     return Response(content=expose_metrics(), media_type="text/plain")
    """
    from fastapi import Response

    return Response(content=expose_metrics(), media_type="text/plain")
