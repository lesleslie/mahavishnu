"""OpenTelemetry tracing configuration for all MCP servers.

This module provides distributed tracing setup using OpenTelemetry,
with automatic instrumentation for FastAPI, asyncio, and HTTP clients.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Global tracer
_tracer: trace.Tracer | None = None
_instrumented: set[str] = set()


def setup_telemetry(
    service_name: str,
    otlp_endpoint: str | None = None,
    enable_console_export: bool = False,
    environment: str = "production",
) -> trace.Tracer:
    """Configure OpenTelemetry tracing for an MCP server.

    Args:
        service_name: Name of the MCP service (e.g., "mahavishnu", "akosha")
        otlp_endpoint: OTLP collector endpoint (default: localhost:4317)
        enable_console_export: Enable console span export for debugging
        environment: Environment name (production, staging, development)

    Returns:
        Configured tracer instance

    Example:
        >>> tracer = setup_telemetry(
        ...     service_name="mahavishnu",
        ...     otlp_endpoint="http://localhost:4317",
        ...     environment="production"
        ... )
        >>> with tracer.start_as_current_span("operation"):
        ...     # Do work
        ...     pass
    """
    global _tracer

    # Create resource with service attributes
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            "service.environment": environment,
            "service.namespace": "mcp-ecosystem",
        }
    )

    # Configure tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter if endpoint provided
    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint,
            insecure=True,  # TODO: Use TLS in production
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info(f"Configured OTLP exporter: {otlp_endpoint}")

    # Add console exporter for debugging (optional)
    if enable_console_export or os.getenv("OTEL_CONSOLE_DEBUG"):
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))
        logger.info("Configured console span exporter")

    # Set global tracer provider
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(__name__)

    logger.info(f"OpenTelemetry configured for service: {service_name}")
    return _tracer


@asynccontextmanager
async def start_span(
    name: str,
    attributes: dict[str, str] | None = None,
):
    """Start a new span for tracing async operations.

    Args:
        name: Span name
        attributes: Span attributes (tags)

    Example:
        >>> async with start_span("process_request", {"request_id": "123"}):
        ...     await process()
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


def instrument_fastapi(app: "FastAPI", service_name: str) -> None:
    """Instrument FastAPI application with OpenTelemetry.

    Args:
        app: FastAPI application instance
        service_name: Name for the service in traces

    Example:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> instrument_fastapi(app, "mahavishnu")
    """
    if service_name in _instrumented:
        logger.warning(f"FastAPI already instrumented for {service_name}")
        return

    FastAPIInstrumentor.instrument_app(app)
    _instrumented.add(service_name)
    logger.info(f"Instrumented FastAPI for {service_name}")


def instrument_httpx() -> None:
    """Instrument HTTPX client for outbound tracing.

    Automatically traces all HTTP requests made through HTTPX.

    Example:
        >>> instrument_httpx()
        >>> async with httpx.AsyncClient() as client:
        ...     # This request will be traced
        ...     response = await client.get("https://api.example.com")
    """
    if "httpx" in _instrumented:
        logger.warning("HTTPX already instrumented")
        return

    HTTPXClientInstrumentor().instrument()
    _instrumented.add("httpx")
    logger.info("Instrumented HTTPX client")


def instrument_asyncio() -> None:
    """Instrument asyncio for task tracing.

    Automatically traces all asyncio tasks and coroutines.

    Example:
        >>> instrument_asyncio()
        >>> async def my_task():
        ...     # This task will be traced
        ...     await asyncio.sleep(1)
    """
    if "asyncio" in _instrumented:
        logger.warning("Asyncio already instrumented")
        return

    AsyncioInstrumentor().instrument()
    _instrumented.add("asyncio")
    logger.info("Instrumented asyncio")


def get_tracer() -> trace.Tracer:
    """Get the global tracer instance.

    Returns:
        Tracer instance

    Raises:
        RuntimeError: If telemetry hasn't been configured
    """
    if _tracer is None:
        raise RuntimeError(
            "Telemetry not configured. Call setup_telemetry() first."
        )
    return _tracer


def add_span_attributes(**attributes: str) -> None:
    """Add attributes to the current span.

    Args:
        **attributes: Key-value pairs to add to span

    Example:
        >>> add_span_attributes(user_id="123", action="login")
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_attributes(attributes)


def record_exception(exception: Exception) -> None:
    """Record an exception on the current span.

    Args:
        exception: Exception to record

    Example:
        >>> try:
        ...     risky_operation()
        >>> except ValueError as e:
        ...     record_exception(e)
        ...     raise
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.record_exception(exception)


def set_span_status(status: str, description: str | None = None) -> None:
    """Set the status of the current span.

    Args:
        status: Status string (OK, ERROR, UNSET)
        description: Optional description

    Example:
        >>> set_span_status("OK", "Operation completed successfully")
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        current_span.set_status(status=status, description=description)


# Convenience context manager for tracing
class trace_operation:
    """Context manager for tracing operations.

    Example:
        >>> with trace_operation("database_query", {"table": "users"}):
        ...     results = await db.fetch_users()
    """

    def __init__(self, name: str, attributes: dict[str, str] | None = None):
        self.name = name
        self.attributes = attributes
        self.span = None

    async def __aenter__(self):
        tracer = get_tracer()
        self.span = tracer.start_as_current_span(
            self.name, attributes=self.attributes or {}
        )
        return self.span

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type is not None:
                self.span.record_exception(exc_val)
                self.span.set_status("ERROR", str(exc_val))
            else:
                self.span.set_status("OK")
            self.span.end()


# Auto-instrumentation setup
def auto_instrument(
    fastapi_app: "FastAPI | None" = None,
    service_name: str = "mcp-server",
) -> None:
    """Automatically instrument all available components.

    This is a convenience function that instruments:
    - FastAPI (if app provided)
    - HTTPX (for outbound requests)
    - Asyncio (for task tracking)

    Args:
        fastapi_app: Optional FastAPI app to instrument
        service_name: Service name for traces

    Example:
        >>> from fastapi import FastAPI
        >>> app = FastAPI()
        >>> setup_telemetry("my-service")
        >>> auto_instrument(app, "my-service")
    """
    instrument_asyncio()
    instrument_httpx()

    if fastapi_app:
        instrument_fastapi(fastapi_app, service_name)

    logger.info("Auto-instrumentation complete")
