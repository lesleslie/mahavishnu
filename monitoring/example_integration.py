"""Example monitoring integration for FastAPI MCP servers.

This example shows how to integrate OpenTelemetry tracing and
Prometheus metrics into a FastAPI-based MCP server.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

# Import monitoring components
from monitoring.otel import (
    setup_telemetry,
    auto_instrument,
    start_span,
    add_span_attributes,
    record_exception,
    set_span_status,
)
from monitoring.metrics import (
    expose_metrics,
    http_requests_total,
    http_request_duration_seconds,
    mcp_tool_calls_total,
    mcp_tool_duration_seconds,
    track_time,
    track_calls,
)

# ============================================================================
# Application Setup
# ============================================================================

app = FastAPI(
    title="MCP Server with Monitoring",
    description="Example MCP server with full observability",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Monitoring Configuration
# ============================================================================

# Configure OpenTelemetry
tracer = setup_telemetry(
    service_name="example-mcp-server",
    otlp_endpoint=os.getenv("OTEL_ENDPOINT", "http://localhost:4317"),
    enable_console_export=os.getenv("OTEL_CONSOLE_DEBUG", "false").lower() == "true",
    environment=os.getenv("ENV", "development"),
)

# Auto-instrument all components
auto_instrument(app, "example-mcp-server")

# ============================================================================
# Metrics Endpoint
# ============================================================================

@app.get("/metrics")
async def metrics():
    """Prometheus metrics exposition endpoint.

    Returns all Prometheus metrics in text format.
    """
    return Response(content=expose_metrics(), media_type="text/plain")


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "monitoring": "enabled"}


# ============================================================================
# Example MCP Tool with Monitoring
# ============================================================================

@app.post("/tools/calculate")
async def calculate_tool(operation: str, x: float, y: float):
    """Example MCP tool with automatic monitoring.

    This demonstrates:
    - Automatic span creation with start_span
    - Metrics collection with decorators
    - Error tracking
    """

    # Create span for this tool execution
    async with start_span("tool_execution", {"tool": "calculate", "operation": operation}):
        try:
            # Add custom attributes to span
            add_span_attributes(
                tool_name="calculate",
                operation_type=operation,
                input_values=f"x={x},y={y}"
            )

            # Increment tool call counter (success)
            mcp_tool_calls_total.labels(
                tool_name="calculate",
                status="started"
            ).inc()

            # Execute the operation
            if operation == "add":
                result = x + y
            elif operation == "multiply":
                result = x * y
            elif operation == "divide":
                if y == 0:
                    raise ValueError("Division by zero")
                result = x / y
            else:
                raise ValueError(f"Unknown operation: {operation}")

            # Record success
            mcp_tool_calls_total.labels(
                tool_name="calculate",
                status="success"
            ).inc()

            set_span_status("OK", f"Calculation successful: {result}")

            return {"result": result}

        except ValueError as e:
            # Record exception in span
            record_exception(e)

            # Increment error counter
            mcp_tool_calls_total.labels(
                tool_name="calculate",
                status="error"
            ).inc()

            # Set span status to error
            set_span_status("ERROR", str(e))

            raise


# ============================================================================
# Example Agent Task with Monitoring
# ============================================================================

@app.post("/agent/execute")
async def execute_agent_task(
    agent_type: str,
    prompt: str,
    adapter: str = "agno",
):
    """Example agent task execution with monitoring."""

    # Create span for agent task
    async with start_span("agent_task", {
        "agent_type": agent_type,
        "adapter": adapter,
        "prompt_length": str(len(prompt))
    }):
        from monitoring.metrics import agent_task_duration_seconds, agent_tasks_total

        # Track agent task start
        agent_tasks_total.labels(
            agent_type=agent_type,
            adapter=adapter,
            status="started"
        ).inc()

        start_time = time.time()

        try:
            # Simulate agent execution
            result = await simulate_agent_execution(agent_type, prompt, adapter)

            duration = time.time() - start_time
            agent_task_duration_seconds.labels(
                agent_type=agent_type,
                adapter=adapter
            ).observe(duration)

            agent_tasks_total.labels(
                agent_type=agent_type,
                adapter=adapter,
                status="success"
            ).inc()

            add_span_attributes(task_duration=str(duration))

            return result

        except Exception as e:
            duration = time.time() - start_time
            agent_task_duration_seconds.labels(
                agent_type=agent_type,
                adapter=adapter
            ).observe(duration)

            agent_tasks_total.labels(
                agent_type=agent_type,
                adapter=adapter,
                status="error"
            ).inc()

            record_exception(e)
            raise


async def simulate_agent_execution(agent_type: str, prompt: str, adapter: str) -> dict:
    """Simulate agent execution for demonstration."""
    # Simulate processing time
    await asyncio.sleep(0.5)

    return {
        "agent_type": agent_type,
        "adapter": adapter,
        "response": f"Processed: {prompt[:50]}...",
        "status": "completed"
    }


# ============================================================================
# Example Resource Usage Monitoring
# ============================================================================

import psutil
from monitoring.metrics import system_memory_usage_bytes, system_cpu_usage_percent


async def update_system_metrics():
    """Background task to update system resource metrics."""
    while True:
        # Memory metrics
        memory_info = psutil.virtual_memory()
        system_memory_usage_bytes.labels(type="rss").set(memory_info.rss)
        system_memory_usage_bytes.labels(type="vms").set(memory_info.vms)

        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        for core, percentage in enumerate(cpu_percent):
            system_cpu_usage_percent.labels(core=str(core)).set(percentage)

        # Wait 5 seconds before next update
        await asyncio.sleep(5)


# ============================================================================
# Startup Event
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize monitoring on startup."""
    import asyncio

    # Start background system metrics collection
    asyncio.create_task(update_system_metrics())

    print("✅ Monitoring initialized")
    print("✅ Metrics: http://localhost:8000/metrics")
    print("✅ Tracing: OTLP endpoint (http://localhost:4317)")
    print("✅ Dashboard: http://localhost:3000")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("🚀 MCP Server with Monitoring")
    print("=" * 60)
    print()
    print("📊 Monitoring Features:")
    print("  • OpenTelemetry distributed tracing")
    print("  • Prometheus metrics collection")
    print("  • Grafana dashboard visualization")
    print()
    print("📈 Endpoints:")
    print("  • http://localhost:8000/metrics - Prometheus metrics")
    print("  • http://localhost:8000/health - Health check")
    print()
    print("🔧 Configuration:")
    print("  • OTLP endpoint: http://localhost:4317")
    print("  • Environment: development")
    print()
    print("=" * 60)
    print()

    uvicorn.run(
        "example_monitoring:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
