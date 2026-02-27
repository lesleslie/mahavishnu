"""Health check schemas for MCP services.

This module defines Pydantic models for health check endpoints following
the design in docs/plans/2026-02-27-health-check-system-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """Health status values for liveness probes."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DependencyStatus(BaseModel):
    """Status of a single dependency."""

    status: HealthStatus = Field(description="Health status of the dependency")
    latency_ms: float | None = Field(
        default=None, description="Latency of health check in milliseconds"
    )
    error: str | None = Field(default=None, description="Error message if unhealthy")
    last_check: datetime | None = Field(
        default=None, description="Timestamp of last health check"
    )


class HealthResponse(BaseModel):
    """Response schema for /health endpoint (liveness probe).

    Purpose: "Is this service running?"
    Called by: Platform health checks (Cloud Run, Kubernetes, etc.)
    Frequency: Every 10-30 seconds by platform
    """

    status: HealthStatus = Field(description="Overall health status")
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")
    uptime_seconds: float = Field(description="Service uptime in seconds")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Response timestamp"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ok",
                    "service": "mahavishnu",
                    "version": "0.3.2",
                    "uptime_seconds": 3600,
                    "timestamp": "2026-02-27T14:00:00Z",
                }
            ]
        }
    }


class ReadyResponse(BaseModel):
    """Response schema for /ready endpoint (readiness probe).

    Purpose: "Is this service ready to accept work?"
    Called by: Load balancers, orchestrators, other services
    Frequency: On-demand (startup, before routing traffic)
    """

    ready: bool = Field(description="Whether service is ready to accept work")
    service: str = Field(description="Service name")
    dependencies: dict[str, DependencyStatus] = Field(
        default_factory=dict, description="Status of each dependency"
    )
    checks: dict[str, str] = Field(
        default_factory=dict, description="Status of internal checks"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ready": True,
                    "service": "mahavishnu",
                    "dependencies": {
                        "session_buddy": {"status": "ok", "latency_ms": 5},
                        "akosha": {"status": "ok", "latency_ms": 3},
                        "dhruva": {"status": "ok", "latency_ms": 2},
                    },
                    "checks": {"database": "ok", "cache": "ok"},
                }
            ]
        }
    }


class HealthCheckResult(BaseModel):
    """Result of a single health check operation."""

    service_name: str = Field(description="Name of the checked service")
    status: HealthStatus = Field(description="Health status")
    latency_ms: float | None = Field(default=None, description="Latency in milliseconds")
    error: str | None = Field(default=None, description="Error message if failed")
    response_data: dict[str, Any] | None = Field(
        default=None, description="Raw response data from health endpoint"
    )


class WaitResult(BaseModel):
    """Result of waiting for all dependencies."""

    success: bool = Field(description="Whether all required dependencies are healthy")
    dependencies: dict[str, HealthCheckResult] = Field(
        default_factory=dict, description="Results for each dependency"
    )
    total_wait_seconds: float = Field(description="Total time spent waiting")
    failed_required: list[str] = Field(
        default_factory=list, description="Names of failed required dependencies"
    )
    skipped_optional: list[str] = Field(
        default_factory=list, description="Names of skipped optional dependencies"
    )
