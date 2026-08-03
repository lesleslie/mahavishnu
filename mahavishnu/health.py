"""Health check endpoints for Mahavishnu MCP server.

This module provides HTTP health check endpoints for monitoring
and orchestration systems (Kubernetes, systemd, supervisord, etc.).

Endpoints:
- GET /health - Basic health check (always returns 200)
- GET /ready - Readiness check (checks if server is ready to accept connections)
- GET /metrics - Prometheus metrics endpoint
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Response

from .core.config import HealthConfig
from .core.health import HealthResponse, HealthStatus
from .core.health import ReadyResponse as ReadinessResponse

logger = __import__("logging").getLogger(__name__)


# =============================================================================
# HEALTH CHECK APPLICATION
# =============================================================================


def create_health_app(
    server_name: str = "mahavishnu",
    startup_time: datetime | None = None,
    version: str = "0.3.2",
    health_config: HealthConfig | None = None,
) -> FastAPI:
    """Create FastAPI application for health checks.

    Args:
        server_name: Name of the MCP server
        startup_time: Server startup timestamp (defaults to now)

    Returns:
        FastAPI application
    """
    if startup_time is None:
        startup_time = datetime.now(UTC)

    app = FastAPI(
        title=f"{server_name.title()} Health API",
        description="Health check endpoints for monitoring",
        version="1.0.0",
    )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        """Basic health check endpoint.

        This endpoint always returns 200 OK if the server is running.
        Use this for liveness probes (is the server alive?).
        """
        uptime = (datetime.now(UTC) - startup_time).total_seconds()

        return HealthResponse(
            status=HealthStatus.OK,
            service=server_name,
            version=version,
            uptime_seconds=uptime,
        )

    @app.get("/ready", response_model=ReadinessResponse, tags=["health"])
    async def readiness_check() -> ReadinessResponse:
        """Readiness check endpoint.

        This endpoint checks if the server is ready to accept connections.
        Use this for readiness probes (can the server handle requests?).

        Returns:
            ReadinessResponse with readiness status and component checks.
            The ``checks`` mapping now also carries the aggregated worker
            capability component from :func:`mahavishnu.core.health.readiness`.
        """
        # Perform readiness checks
        checks: dict[str, str] = {
            "server": "ok",  # Server is running
            "database": "ok" if _check_database() else "unhealthy",
            "message_bus": "ok" if _check_message_bus() else "unhealthy",
            "adapters": "ok" if _check_adapters() else "unhealthy",
        }

        # Aggregate worker capability reports so observability sees the
        # worker component alongside the other readiness probes. We
        # swallow any settings-resolution error here because readiness
        # probes must never raise — they degrade to ``unhealthy``.
        try:
            worker_summary = await get_readiness()
            worker_status = worker_summary.get("status", "unhealthy")
            checks["workers"] = (
                "ok"
                if worker_status == HealthStatus.OK.value
                else "degraded"
                if worker_status == HealthStatus.DEGRADED.value
                else "unhealthy"
            )
            default_worker = worker_summary.get("default_worker", "unknown")
            checks["workers_default"] = f"{default_worker}:{worker_status}"
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            logger.exception("readiness worker aggregation failed")
            checks["workers"] = "unhealthy"
            checks["workers_default"] = "unresolved"

        all_ready = all(status == "ok" for status in checks.values())

        return ReadinessResponse(
            ready=all_ready,
            service=server_name,
            dependencies={},
            checks=checks,
        )

    @app.get("/metrics", tags=["health"])
    async def metrics() -> Response:
        """Prometheus metrics endpoint in text exposition format."""
        from monitoring.metrics import metrics_endpoint

        return await metrics_endpoint()  # type: ignore[no-any-return]

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        """Root endpoint with API information."""
        return {
            "service": server_name,
            "status": "running",
            "health_endpoint": "/health",
            "readiness_endpoint": "/ready",
            "metrics_endpoint": "/metrics",
            "docs": "/docs",
        }

    return app


# =============================================================================
# READINESS CHECKS
# =============================================================================


def _check_database() -> bool:
    """Check if database module is importable and constructible.

    EncryptedSQLite.connect()/close() are async coroutines, so this sync
    smoke test only verifies the import path and class instantiation.
    Use the canonical storage health check for connection-level probes.
    """
    try:
        from .storage.encrypted_sqlite import EncryptedSQLite

        test_db = EncryptedSQLite(":memory:")
        return test_db is not None
    except Exception:  # noqa: BLE001 - health probe: any failure means subsystem unavailable
        return False


def _check_message_bus() -> bool:
    """Check if message bus is operational."""
    try:
        from .core.events.contract import InMemoryEventTransport

        # The canonical event transport is available if the in-memory transport
        # can be constructed.
        transport = InMemoryEventTransport()
        return transport is not None
    except Exception:  # noqa: BLE001 - health probe: any failure means subsystem unavailable
        return False


def _check_adapters() -> bool:
    """Check if orchestration adapters are loaded."""
    try:
        from .core.config import MahavishnuSettings

        config = MahavishnuSettings()
        # Check if at least one adapter is configured
        has_adapter = any(
            [
                config.adapters.prefect_enabled,
                config.adapters.llamaindex_enabled,
                config.adapters.agno_enabled,
            ]
        )

        return has_adapter
    except Exception:  # noqa: BLE001 - health probe: any failure means subsystem unavailable
        return False


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


async def get_readiness() -> dict[str, Any]:
    """Aggregate readiness including worker capability reports.

    Wraps :func:`mahavishnu.core.health.readiness` so the MCP ``get_readiness``
    tool and the ``/ready`` HTTP endpoint can share a single source of truth
    for the worker component. Settings are resolved up-front because the
    readiness aggregator expects a fully-built :class:`MahavishnuSettings`.

    Returns:
        Dict from :func:`mahavishnu.core.health.readiness` describing
        status, default worker type, and per-worker capability states.
    """
    from .core.config import MahavishnuSettings
    from .core.health import readiness as _readiness_async

    settings = MahavishnuSettings()
    return await _readiness_async(settings=settings)


async def run_health_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    server_name: str = "mahavishnu",
    startup_time: datetime | None = None,
) -> None:
    """Run health check server.

    Args:
        host: Host to bind to
        port: Port to bind to
        server_name: Name of the MCP server
        startup_time: Server startup timestamp
    """
    import uvicorn

    app = create_health_app(
        server_name=server_name,
        startup_time=startup_time,
    )

    logger.info(f"Starting health check server on {host}:{port}")

    await asyncio.to_thread(
        uvicorn.run,
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    asyncio.run(run_health_server())
