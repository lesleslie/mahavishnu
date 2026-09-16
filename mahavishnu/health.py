"""Health check endpoints for Mahavishnu MCP server.

This module provides HTTP health check endpoints for monitoring
and orchestration systems (Kubernetes, systemd, supervisord, etc.).

Endpoints:
- GET /health - Aggregated health check (Plan §4 + §11.4). Returns
  200 for ``healthy``/``warming_up`` worst-case status, 503 for
  ``degraded``/``failed``. Delegates per-feed evaluation to
  ``mcp_common.health.aggregator.aggregate_feed_states`` via
  ``mahavishnu.core.health_aggregator.aggregate_mahavishnu_health``.
- GET /ready - Readiness check (checks if server is ready to accept connections)
- GET /metrics - Prometheus text-format metrics endpoint. Exposes
  the four PromQL metrics emitted by the health aggregator
  (``health_feed_status`` / ``health_feed_errors_within_window`` /
  ``mcp_common_health_halflife_seconds`` /
  ``mcp_common_health_aggregate_duration_ms``) so the alerts in
  ``config/prometheus/health_aggregator_alerts.yml`` fire live.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Response
import prometheus_client

from .core.health import HealthResponse, HealthStatus
from .core.health import ReadyResponse as ReadinessResponse
from .core.health_aggregator import (
    aggregate_mahavishnu_health,
    get_health_metrics_registry,
)

if TYPE_CHECKING:
    from .core.config import HealthConfig

logger = __import__("logging").getLogger(__name__)


# =============================================================================
# HEALTH CHECK APPLICATION
# =============================================================================


# StatusValue → HealthStatus mapping for the legacy ``status`` field on
# ``HealthResponse``. ``healthy`` and ``warming_up`` map to ``ok`` (the
# orchestrator is operational); ``degraded`` and ``failed`` map to
# ``degraded`` and ``unhealthy`` respectively. ``warming_up`` does NOT
# map to ``degraded`` even though ``is_healthy`` returns ``healthy=False``
# for it — the legacy contract is "is the orchestrator alive?", and
# ``warming_up`` means producers are mid-stride, not that the
# orchestrator is broken.
_WORST_STATUS_TO_LEGACY: dict[str, HealthStatus] = {
    "healthy": HealthStatus.OK,
    "warming_up": HealthStatus.OK,
    "degraded": HealthStatus.DEGRADED,
    "failed": HealthStatus.UNHEALTHY,
}


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
    async def health_check() -> Response:
        """Aggregated health check endpoint (Plan §4 + §11.4).

        Delegates to
        :func:`mahavishnu.core.health_aggregator.aggregate_mahavishnu_health`
        which builds the ``dict[str, HealthFeedState]`` from the 3
        v1 feeds (storage, message_bus, adapters), calls
        ``aggregate_feed_states``, emits the four PromQL metrics,
        and returns a :class:`MahavishnuHealthVerdict` carrying the
        worst-case ``StatusValue`` + mapped HTTP code.

        HTTP code: 200 for ``healthy``/``warming_up`` (operational),
        503 for ``degraded``/``failed`` (load balancers should pull
        this pod out of rotation). Per spec §4.8 threshold contract.

        Response body shape (Phase 4):
        - legacy fields unchanged: ``status``, ``service``,
          ``version``, ``uptime_seconds``, ``timestamp``.
        - new aggregator fields: ``worst_status``, ``feed_states``
          (per-feed ``status``/``healthy``/``reason_codes``),
          ``reason_codes`` (worst-feed's deduped union),
          ``aggregate_duration_ms``.
        """
        verdict = aggregate_mahavishnu_health(repo=server_name)
        uptime = (datetime.now(UTC) - startup_time).total_seconds()

        # Per-feed FeedSnapshot dicts: cast StatusValue → str,
        # ReasonCode → str so the response stays JSON-native.
        feed_states_json: dict[str, dict[str, object]] = {
            feed_name: {
                "status": feed_snapshot["status"].value,
                "healthy": feed_snapshot["healthy"],
                "reason_codes": [
                    rc.value for rc in feed_snapshot["reason_codes"]
                ],
            }
            for feed_name, feed_snapshot in verdict.snapshot["checks"].items()
        }

        # Worst-feed's reason codes (deduped union across tied
        # worst-status feeds; ``aggregate_feed_states`` already
        # dedupes).
        reason_codes_json: list[str] = [
            rc.value for rc in verdict.snapshot["reason_codes"]
        ]

        body = HealthResponse(
            status=_WORST_STATUS_TO_LEGACY.get(
                verdict.worst_status.value, HealthStatus.UNHEALTHY
            ),
            service=server_name,
            version=version,
            uptime_seconds=uptime,
            worst_status=verdict.worst_status.value,
            feed_states=feed_states_json,
            reason_codes=reason_codes_json,
            aggregate_duration_ms=verdict.duration_ms,
        )

        # FastAPI's response_model validates the body but discards
        # the HTTP code; we return a raw ``JSONResponse`` to honour
        # the 503 mapping for degraded/failed verdicts.
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=verdict.http_status,
            content=body.model_dump(mode="json"),
        )

    @app.get("/ready", response_model=ReadinessResponse, tags=["health"])
    async def readiness_check() -> ReadinessResponse:
        """Readiness check endpoint.

        This endpoint checks if the server is ready to accept connections.
        Use this for readiness probes (can the server handle requests?).

        Returns:
            ReadinessResponse with readiness status and component checks.
            The ``checks`` mapping now also carries the aggregated worker
            capability component from
            :func:`mahavishnu.core.health.aggregate_readiness`.
        """
        # Perform readiness checks
        checks: dict[str, str] = {
            "server": "ok",  # Server is running
            "database": "ok" if _check_database() else "unhealthy",
            "message_bus": "ok" if _check_message_bus() else "unhealthy",
            "adapters": "ok" if _check_adapters() else "unhealthy",
        }

        # Aggregate worker capability reports so observability sees the
        # worker component alongside the other readiness probes. The
        # worker capability state is surfaced as informational rather
        # than gating readiness: a worker in ``READY`` (declared, not
        # yet probed) or ``DEGRADED`` state is not the same as the
        # orchestrator being unable to accept work, so the readiness
        # endpoint treats both as ``ok``. The MCP-level
        # ``get_readiness`` tool surfaces the granular status for
        # operators who need the detailed view. Any settings-resolution
        # error here still degrades to ``ok`` so a transient
        # misconfiguration cannot turn a healthy orchestrator red.
        try:
            worker_summary = await get_readiness()
            worker_status = worker_summary.get("status", "unhealthy")
            checks["workers"] = (
                "ok"
                if worker_status in (HealthStatus.OK.value, HealthStatus.DEGRADED.value)
                else "unhealthy"
            )
            checks["workers_default"] = (
                "ok"
                if worker_status in (HealthStatus.OK.value, HealthStatus.DEGRADED.value)
                else "unhealthy"
            )
        except Exception:
            logger.exception("readiness worker aggregation failed")
            checks["workers"] = "ok"
            checks["workers_default"] = "ok"

        # Round-4 review fix (M1): surface the mergiraf merge driver
        # probe on the HTTP /ready endpoint. The MCP ``get_readiness``
        # tool already exposes the payload via the module-level
        # ``aggregate_readiness()`` aggregator; load balancers and
        # Kubernetes probes now see the same shape. The probe is sync
        # (subprocess call) — cheap enough to run on every readiness
        # check.
        merge_driver_payload: dict[str, Any] | None = None
        try:
            from .core.health import merge_driver_health

            merge_driver_payload = merge_driver_health()
            checks["merge_driver"] = "ok" if merge_driver_payload.get("available") else "degraded"
        except Exception:
            logger.exception("readiness merge_driver probe failed")
            checks["merge_driver"] = "unknown"

        all_ready = all(status == "ok" for status in checks.values())

        return ReadinessResponse(
            ready=all_ready,
            service=server_name,
            dependencies={},
            checks=checks,
            merge_driver=merge_driver_payload,
        )

    @app.get("/metrics", tags=["health"])
    async def metrics() -> Response:
        """Prometheus text-format metrics endpoint.

        Exposes the four PromQL metrics emitted by
        :func:`mcp_common.health.metrics.update_health_metrics`
        from :func:`aggregate_mahavishnu_health`. The alerts at
        ``config/prometheus/health_aggregator_alerts.yml`` reference
        these metric names; the endpoint serves them so Prometheus
        can scrape and the alerts fire live.

        Pre-Phase-4 this endpoint imported ``from monitoring.metrics
        import metrics_endpoint`` which didn't exist (the module
        path was never wired). The import raised ``ImportError``
        at request time. Phase 4 replaces the broken import with a
        direct ``prometheus_client`` text exposition from the
        private CollectorRegistry used by the aggregator. OTel
        metrics (worktree/streaming/etc.) remain on the OTel meter
        and require a separate OTel collector — out of scope here.
        """
        try:
            text = prometheus_client.generate_latest(
                get_health_metrics_registry()
            )
        except Exception:
            logger.exception("metrics endpoint: registry render failed")
            return Response(
                content=b"# metrics endpoint unavailable\n",
                media_type="text/plain; version=0.0.4",
                status_code=503,
            )
        return Response(
            content=text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

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

    Wraps :func:`mahavishnu.core.health.aggregate_readiness` so the MCP
    ``get_readiness`` tool and the ``/ready`` HTTP endpoint can share a
    single source of truth for the worker component. Settings are
    resolved up-front because the readiness aggregator expects a
    fully-built :class:`MahavishnuSettings`.

    Returns:
        Dict from :func:`mahavishnu.core.health.aggregate_readiness`
        describing status, default worker type, and per-worker
        capability states.
    """
    from .core.config import MahavishnuSettings
    from .core.health import aggregate_readiness

    settings = MahavishnuSettings()
    return await aggregate_readiness(settings=settings)


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
