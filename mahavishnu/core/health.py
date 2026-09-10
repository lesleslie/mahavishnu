"""Health check system for MCP services.

This module provides health checking and dependency waiting functionality
using Oneiric's HTTP infrastructure for observability and proper lifecycle management.

Includes Pydantic schemas for health check API endpoints (merged from health_schemas.py).

Design: docs/plans/2026-02-27-health-check-system-design.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Any

import httpx2 as httpx
from oneiric.actions.http import HttpActionSettings, HttpFetchAction
from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.core.logging import get_logger
from opentelemetry import trace as _otel_trace
from pydantic import BaseModel, Field

from mahavishnu.core.config import DependencyConfig, HealthConfig, MahavishnuSettings
from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_all_capabilities,
)
from monitoring.metrics import (
    mahavishnu_dependency_health_status,
    mahavishnu_dependency_request_duration_seconds,
    mahavishnu_dependency_requests_total,
)

if TYPE_CHECKING:
    from mahavishnu.core.app import MahavishnuApp

logger = get_logger("mahavishnu.health")

# Per-module Tracer for ``merge.driver.probe`` observability (M10 fix).
# Lazy via ``trace.get_tracer(__name__)``; returns a no-op Tracer until
# TracerProvider is initialized. Separate from the tracer inside
# ``mahavishnu.settle.merge`` (which wraps the merge invocation itself)
# so the probe path is observable independently of the actual merge call.
_probe_tracer = _otel_trace.get_tracer(__name__)


# ---------------------------------------------------------------------------
# Health check schemas (merged from health_schemas.py)
# ---------------------------------------------------------------------------


class HealthStatus(StrEnum):
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
    last_check: datetime | None = Field(default=None, description="Timestamp of last health check")


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
    checks: dict[str, str] = Field(default_factory=dict, description="Status of internal checks")
    # Phase 4 / Round-4 review M1 fix: surface the mergiraf merge
    # driver probe on the HTTP /ready endpoint, not just on the MCP
    # ``get_readiness`` tool. Load balancers and Kubernetes probes need
    # the same payload the MCP layer sees. ``None`` when the merge
    # driver probe is disabled or fails in a way that can't recover
    # the payload (defensive — see ``merge_driver_health`` C3 wrap).
    merge_driver: dict[str, Any] | None = Field(
        default=None,
        description="Mergiraf merge driver probe (REQ-SM-009 payload shape)",
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
                        "dhara": {"status": "ok", "latency_ms": 2},
                    },
                    "checks": {"database": "ok", "cache": "ok"},
                    "merge_driver": {
                        "available": True,
                        "binary": "/usr/local/bin/mergiraf",
                        "version": "0.19.1",
                        "grammars": ["Python", "Rust"],
                        "degraded_since": None,
                    },
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


# ---------------------------------------------------------------------------
# Health check system
# ---------------------------------------------------------------------------


class HealthCheckError(MahavishnuError):
    """Base error for health check failures."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    ):
        super().__init__(message, error_code=error_code, details=details or {})


class DependencyTimeoutError(HealthCheckError):
    """Dependency did not respond within timeout."""

    def __init__(self, service_name: str, timeout_seconds: float):
        super().__init__(
            f"Dependency '{service_name}' did not respond within {timeout_seconds}s",
            details={"service": service_name, "timeout_seconds": timeout_seconds},
            error_code=ErrorCode.TIMEOUT_ERROR,
        )


class DependencyUnavailableError(HealthCheckError):
    """Dependency returned unhealthy status."""

    def __init__(self, service_name: str, error: str):
        super().__init__(
            f"Dependency '{service_name}' is unhealthy: {error}",
            details={"service": service_name, "error": error},
            error_code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
        )


@dataclass
class ServiceInfo:
    """Information about the current service."""

    name: str
    version: str
    start_time: float = field(default_factory=time.time)

    @property
    def uptime_seconds(self) -> float:
        """Calculate uptime in seconds."""
        return time.time() - self.start_time


class HealthChecker(HTTPXClientMixin):
    """Check health of a single service using Oneiric HTTP infrastructure."""

    def __init__(
        self,
        config: HealthConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize health checker.

        Args:
            config: Health configuration
            client: Optional httpx async client for dependency injection
        """
        super().__init__(client=client)
        self._config = config
        self._logger = get_logger("mahavishnu.health.checker")

        # Create Oneiric HTTP action for observability
        settings = HttpActionSettings(
            timeout_seconds=config.check_timeout_seconds if config else 5.0,
            verify_ssl=True,
            raise_for_status=False,
        )
        self._http_action = HttpFetchAction(settings=settings, client=client)

    async def check(self, url: str, timeout: float = 5.0) -> HealthCheckResult:
        """Perform health check against a single service.

        Uses Oneiric's HttpFetchAction for observability and trace context injection.

        Args:
            url: Health endpoint URL (e.g., "http://localhost:8678/health")
            timeout: Request timeout in seconds

        Returns:
            HealthCheckResult with status and latency
        """
        start_time = time.time()
        service_name = self._extract_service_name(url)

        try:
            result = await self._http_action.execute(
                {
                    "url": url,
                    "method": "GET",
                    "timeout": timeout,
                    "raise_for_status": False,
                }
            )

            latency_ms = (time.time() - start_time) * 1000

            if not result.get("ok", False):
                health_result = HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency_ms,
                    error=f"HTTP {result.get('status_code', 'unknown')}",
                    response_data=result,
                )
                self._record_metrics(health_result)
                return health_result

            # Parse response body
            json_data = result.get("json") or {}  # type: ignore[var-annotated]
            status_str = json_data.get("status", "ok").lower()

            # Map status string to enum
            if status_str == "ok":
                status = HealthStatus.OK
            elif status_str == "degraded":
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

            health_result = HealthCheckResult(
                service_name=service_name,
                status=status,
                latency_ms=latency_ms,
                response_data=json_data,
            )
            self._record_metrics(health_result)
            return health_result

        except TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.warning(
                "health-check-timeout",
                url=url,
                timeout=timeout,
            )
            health_result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=f"Timeout after {timeout}s",
            )
            self._record_metrics(health_result)
            return health_result

        except httpx.ConnectError as e:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.warning(
                "health-check-connection-refused",
                url=url,
                error=str(e),
            )
            health_result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error="Connection refused",
            )
            self._record_metrics(health_result)
            return health_result

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.exception(
                "health-check-error",
                extra={
                    "url": url,
                    "error": str(e),
                },
            )
            health_result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=str(e),
            )
            self._record_metrics(health_result)
            return health_result

    def _record_metrics(self, result: HealthCheckResult) -> None:
        """Record Prometheus metrics for dependency health checks."""
        status = result.status.value
        latency_seconds = (result.latency_ms or 0.0) / 1000.0
        if result.status == HealthStatus.OK:
            health_value = 1.0
        elif result.status == HealthStatus.DEGRADED:
            health_value = 0.5
        else:
            health_value = 0.0

        mahavishnu_dependency_requests_total.labels(
            dependency=result.service_name,
            status=status,
        ).inc()
        mahavishnu_dependency_request_duration_seconds.labels(
            dependency=result.service_name,
            status=status,
        ).observe(latency_seconds)
        mahavishnu_dependency_health_status.labels(
            dependency=result.service_name,
        ).set(health_value)

    def _extract_service_name(self, url: str) -> str:
        """Extract service name from URL for logging."""
        try:
            # Extract host:port from URL
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return f"{parsed.hostname}:{parsed.port}" if parsed.port else str(parsed.hostname)
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return url


class DependencyWaiter:
    """Wait for all dependencies to become healthy with exponential backoff."""

    def __init__(
        self,
        config: HealthConfig | None = None,
        *,
        checker: HealthChecker | None = None,
    ) -> None:
        """Initialize dependency waiter.

        Args:
            config: Health configuration
            checker: Optional health checker for dependency injection
        """
        self._config = config
        self._checker = checker or HealthChecker(config=config)
        self._logger = get_logger("mahavishnu.health.waiter")

    async def wait_for_all(
        self,
        dependencies: dict[str, DependencyConfig],
    ) -> WaitResult:
        """Wait for all dependencies to become healthy.

        Uses exponential backoff for retries:
        - Base delay: 1s
        - Max delay: 16s
        - Sequence: 1s, 2s, 4s, 8s, 16s, 16s, ...

        Args:
            dependencies: Map of service name to configuration

        Returns:
            WaitResult with success/failure status per dependency
        """
        start_time = time.time()
        results: dict[str, HealthCheckResult] = {}
        failed_required: list[str] = []
        skipped_optional: list[str] = []

        # Check all dependencies concurrently
        tasks = {name: self._wait_for_single(name, config) for name, config in dependencies.items()}

        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for (name, _), result in zip(tasks.items(), gathered, strict=False):
                if isinstance(result, Exception):
                    results[name] = HealthCheckResult(
                        service_name=name,
                        status=HealthStatus.UNHEALTHY,
                        error=str(result),
                    )
                    dep_config = dependencies[name]
                    if dep_config.required:
                        failed_required.append(name)
                elif isinstance(result, HealthCheckResult):
                    results[name] = result
                    if result.status != HealthStatus.OK:
                        dep_config = dependencies[name]
                        if dep_config.required:
                            failed_required.append(result.service_name)
                        else:
                            skipped_optional.append(result.service_name)
                    elif result.status == HealthStatus.OK and not dependencies[name].required:
                        # Optional dependency that succeeded
                        pass
                else:
                    # Handle case where dependency was skipped (optional and failed quickly)
                    if isinstance(result, tuple):
                        results[name] = result[0]
                        if result[1] == "skipped":
                            skipped_optional.append(name)

        total_wait = time.time() - start_time
        success = len(failed_required) == 0

        self._logger.info(
            "dependency-wait-complete",
            success=success,
            total_wait_seconds=total_wait,
            failed_required=failed_required,
            skipped_optional=skipped_optional,
        )

        return WaitResult(
            success=success,
            dependencies=results,
            total_wait_seconds=total_wait,
            failed_required=failed_required,
            skipped_optional=skipped_optional,
        )

    async def _wait_for_single(
        self,
        name: str,
        config: DependencyConfig,
    ) -> HealthCheckResult | tuple[HealthCheckResult, str]:
        """Wait for a single dependency with exponential backoff.

        Args:
            name: Service name
            config: Dependency configuration

        Returns:
            HealthCheckResult or tuple of (result, status)
        """
        base_delay = self._config.retry_base_delay_seconds if self._config else 1.0
        max_delay = self._config.retry_max_delay_seconds if self._config else 16.0
        check_timeout = self._config.check_timeout_seconds if self._config else 5.0

        url = self._build_health_url(config)
        deadline = time.time() + config.timeout_seconds
        attempt = 0
        delay = base_delay

        while time.time() < deadline:
            attempt += 1
            result = await self._checker.check(url, timeout=check_timeout)

            if result.status == HealthStatus.OK:
                self._logger.info(
                    "dependency-healthy",
                    service=name,
                    attempt=attempt,
                    latency_ms=result.latency_ms,
                )
                return result

            if result.status == HealthStatus.DEGRADED:
                # Degraded is acceptable - service is up
                self._logger.warning(
                    "dependency-degraded",
                    service=name,
                    attempt=attempt,
                )
                return result

            # Service is unhealthy, retry with backoff
            self._logger.debug(
                "dependency-retry",
                service=name,
                attempt=attempt,
                delay=delay,
                error=result.error,
            )

            # For optional dependencies, fail fast after a few attempts
            if not config.required and attempt >= 3:
                self._logger.warning(
                    "optional-dependency-skipped",
                    service=name,
                    attempts=attempt,
                )
                return (result, "skipped")

            # Wait before next attempt
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

        # Timeout exceeded
        self._logger.error(
            "dependency-timeout",
            service=name,
            timeout_seconds=config.timeout_seconds,
            attempts=attempt,
        )
        return HealthCheckResult(
            service_name=name,
            status=HealthStatus.UNHEALTHY,
            error=f"Timeout after {config.timeout_seconds}s",
        )

    def _build_health_url(self, config: DependencyConfig) -> str:
        """Build health check URL from configuration."""
        scheme = "https" if config.use_tls else "http"
        return f"{scheme}://{config.host}:{config.port}/health"


class HealthEndpoint(HTTPXClientMixin):
    """Provide /health and /ready endpoints for this service."""

    def __init__(
        self,
        service_info: ServiceInfo,
        config: HealthConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize health endpoint provider.

        Args:
            service_info: Information about this service
            config: Health configuration
            client: Optional httpx client for checking dependencies
        """
        super().__init__(client=client)
        self._service_info = service_info
        self._config = config
        self._checker = HealthChecker(config=config, client=client)
        self._logger = get_logger("mahavishnu.health.endpoint")

    async def liveness(self) -> HealthResponse:
        """Return liveness status for this service.

        This is a simple "is the process running" check.
        """
        return HealthResponse(
            status=HealthStatus.OK,
            service=self._service_info.name,
            version=self._service_info.version,
            uptime_seconds=self._service_info.uptime_seconds,
        )

    async def readiness(
        self,
        dependencies: dict[str, DependencyConfig] | None = None,
    ) -> ReadyResponse:
        """Return readiness status, checking all dependencies.

        Args:
            dependencies: Optional override of dependencies to check

        Returns:
            ReadyResponse with dependency status
        """
        checks: dict[str, str] = {}
        dep_status: dict[str, DependencyStatus] = {}

        # Check internal health
        checks["process"] = "ok"
        checks["uptime"] = "ok"

        # Check dependencies if configured
        deps_to_check = dependencies or (self._config.dependencies if self._config else {})

        if deps_to_check:
            check_tasks = {
                name: self._checker.check(
                    f"{'https' if dep.use_tls else 'http'}://{dep.host}:{dep.port}/health",
                    timeout=self._config.check_timeout_seconds if self._config else 5.0,
                )
                for name, dep in deps_to_check.items()
            }

            if check_tasks:
                results = await asyncio.gather(*check_tasks.values(), return_exceptions=True)
                for (name, _), result in zip(check_tasks.items(), results, strict=False):
                    if isinstance(result, Exception):
                        dep_status[name] = DependencyStatus(
                            status=HealthStatus.UNHEALTHY,
                            error=str(result),
                        )
                    elif isinstance(result, HealthCheckResult):
                        dep_status[name] = DependencyStatus(
                            status=result.status,
                            latency_ms=result.latency_ms,
                            error=result.error,
                        )

        # Determine overall readiness
        all_healthy = all(
            ds.status in (HealthStatus.OK, HealthStatus.DEGRADED) for ds in dep_status.values()
        )

        # Consider required dependencies specifically
        if deps_to_check:
            required_unhealthy = [
                name
                for name, dep in deps_to_check.items()
                if dep.required
                and name in dep_status
                and dep_status[name].status == HealthStatus.UNHEALTHY
            ]
            all_healthy = len(required_unhealthy) == 0

        return ReadyResponse(
            ready=all_healthy,
            service=self._service_info.name,
            dependencies=dep_status,
            checks=checks,
        )


# ---------------------------------------------------------------------------
# Capability-aware readiness aggregator (Task 10)
# ---------------------------------------------------------------------------


async def aggregate_readiness(
    *,
    settings: MahavishnuSettings | None = None,
) -> dict[str, Any]:
    """Aggregate worker capability reports into a readiness payload (Phase 4 m4).

    Module-level async function renamed from :func:`readiness` to resolve
    the naming collision with :meth:`HealthEndpoint.readiness`. The two
    names previously coexisted; this aggregate function returns the
    AGGREGATE payload (worker capability state + mergiraf merge_driver
    probe) used by the MCP ``get_readiness`` tool and the ``/ready``
    HTTP endpoint, while :meth:`HealthEndpoint.readiness` is a
    per-instance method that runs dependency HTTP probes.

    Round-4 review fix m4: the two ``readiness`` names collided and
    confused readers who grep'd for ``readiness`` and found both. The
    aggregate function lives in module scope (no ``self``) and was the
    least-coupled of the two to rename. The method name is unchanged
    because ``HealthEndpoint.readiness(...)`` is part of the public HTTP
    surface that downstream callers and tests already exercise.

    Args:
        settings: Optional pre-built :class:`MahavishnuSettings`
            instance. When ``None`` the settings are resolved lazily so
            test fixtures can pass partial mocks.

    Returns:
        Dict with ``status`` (str), ``worker_reports`` (mapping of
        worker type to capability state value), and the resolved
        ``default_worker`` type.
    """
    if settings is None:
        settings = MahavishnuSettings()

    reports = evaluate_all_capabilities(settings=settings, force_live=False)
    default_type = getattr(
        getattr(settings, "workers", None),
        "default_type",
        "terminal-claude",
    )
    default_report = reports.get(default_type)
    state = default_report.state if default_report is not None else WorkerCapabilityState.REGISTERED

    if state is WorkerCapabilityState.REGISTERED:
        status = HealthStatus.UNHEALTHY
    elif state in {
        WorkerCapabilityState.CONFIGURED,
        WorkerCapabilityState.READY,
    }:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.OK

    return {
        "status": status.value,
        "default_worker": default_type,
        "worker_reports": {k: v.state.value for k, v in reports.items()},
        "merge_driver": merge_driver_health(),
    }


# ---------------------------------------------------------------------------
# Phase 4 (settle-semantic-merge plan REQ-SM-009): merge_driver health probe.
# Wired into the ``readiness`` aggregate above. Operators run
# ``mahavishnu health --section merge_driver`` (or hit ``/health``) to
# see the same payload.
# ---------------------------------------------------------------------------

# Module-level fallback timestamp. The PRIMARY state lives on each
# ``MahavishnuApp`` instance as ``app._degraded_since`` (m3 round-5
# review fix; module-global stomp-collision when two apps share a
# process — CLI tests + a server daemon, etc.). The module-level
# slot is the FALLBACK for callers that haven't registered an app
# (CLI tools, scripts, one-off tests). Existing tests that target
# the module-global path continue to work; new tests that want
# per-app isolation must pass the app through.
_DEGRADED_SINCE: datetime | None = None


def _resolve_degraded_since(
    app: MahavishnuApp | None,
) -> datetime | None:
    """Return the active ``_DEGRADED_SINCE`` slot for ``app``.

    Per-app when ``app`` is provided AND has the ``_degraded_since``
    attribute (always true for ``MahavishnuApp`` instances built via
    ``__init__``); module-global otherwise. Centralized so callers
    don't drift between per-instance and module-global reads.

    The ``hasattr`` branch is the gate — ``getattr(..., None)`` alone
    cannot distinguish "attribute exists but is None" from "attribute
    doesn't exist on a duck-typed ``app``". Module-global is the safe
    fallback when the attribute is missing.
    """
    if app is not None and hasattr(app, "_degraded_since"):
        return app._degraded_since
    return _DEGRADED_SINCE


def _assign_degraded_since(
    app: MahavishnuApp | None,
    value: datetime | None,
) -> None:
    """Write ``value`` to the active ``_DEGRADED_SINCE`` slot for ``app``.

    Mirrors :func:`_resolve_degraded_since`. Per-app when ``app`` is
    provided; module-global otherwise.
    """
    if app is not None and hasattr(app, "_degraded_since"):
        app._degraded_since = value
        return
    global _DEGRADED_SINCE
    _DEGRADED_SINCE = value


def mark_merge_driver_fallback(app: MahavishnuApp | None = None) -> None:
    """Stamp the active degraded-since slot when the merge driver falls back.

    Called from :func:`mahavishnu.settle.merge._resolve_default_strategy`
    when ``merge_driver_default == "mergiraf"`` but the binary is missing.
    The OTel counter increment happens at the call site; this function
    exists for the timestamp side-effect.

    Round-5 review fix (M9): ALWAYS stamp, even when a previous stamp
    already exists. Operators want to see the most recent fallback, not
    the first one — the prior "first-stamp-wins" logic could leave a
    days-old stamp visible while the current degradation was hidden.

    Round-5 review fix (m3): when ``app`` is provided, stamp on the
    per-instance attribute instead of the module-global, so two
    ``MahavishnuApp`` instances in the same process don't stomp each
    other's fallback history. The module-global path remains the
    fallback for callers without an app context (CLI tools, tests).
    """
    _assign_degraded_since(app, datetime.now(UTC))


def merge_driver_health(app: MahavishnuApp | None = None) -> dict[str, Any]:
    """Probe the mergiraf merge driver and return the ``merge_driver`` payload.

    Shape (per REQ-SM-009 + wire-up contract + Phase 4 deferred review M8):
        ``available`` (bool): binary present AND version parses
        ``binary`` (path or null)
        ``version`` (string or null)
        ``grammars`` (list of available tree-sitter languages)
        ``probe_ok`` (bool): the grammar probe subprocess ran cleanly
            (timed-out, errored, or exited non-zero → False). Distinguishes
            "no grammars installed" from "probe broken" — operators can
            tell at a glance whether the empty grammars list means a real
            configuration gap or a transient subprocess failure. M8 also
            stamps ``degraded_since`` when ``probe_ok=False`` so the
            operator's ``/health`` view reflects the probe-broke state.
        ``degraded_since`` (ISO timestamp or null) — most-recent
        fallback timestamp since the last healthy probe; cleared
        here on every healthy probe only — NOT when the binary
        disappears (Round-4 review M2 fix; clearing on
        binary-missing defeated operator-trust because a healthy past
        degraded stamp was wiped before the operator could see it).
        M8 also sets the stamp when ``probe_ok=False``.

    Cheap to compute — runs once per ``/health`` call (not per request).
    Catches all subprocess errors so a transient ``mergiraf`` crash
    never brings down the health endpoint (Round-4 review C3 fix —
    the docstring used to claim this but the body didn't actually
    wrap the probe helpers).

    Round-5 review fix (M10): wraps the binary PATH probe in a
    ``merge.driver.probe`` OTel span. The original R5 task wanted this
    span around ``_resolve_mergiraf_binary()`` in
    ``mahavishnu.settle.merge`` (the cold-cache PATH probe on first
    merge call), but that function lives outside this round's strict
    scope. The ``merge_driver_health`` probe is the operator-facing
    counterpart — also a ``shutil.which("mergiraf")`` call observed by
    every ``/health`` request — so the span is emitted there instead.
    Both probe paths now contribute telemetry; the cold-cache one
    should land in a follow-up round that owns ``settle/merge.py``.

    Args:
        app: Optional ``MahavishnuApp`` instance. When provided the
            per-app ``_degraded_since`` slot is read/written instead
            of the module-global fallback (m3 fix; see
            :func:`mark_merge_driver_fallback`).
    """
    try:
        # M10: emit a ``merge.driver.probe`` span around the PATH probe so
        # operators can see probe latency + binary-path resolution in
        # traces. Attributes: driver name, probe.cached (False on first
        # call, True on cached re-probes from the same process), and
        # merge.binary_path (the resolved path or None). Spans are
        # best-effort — TracerProvider may be unconfigured; the no-op
        # tracer swallows the emit.
        with _probe_tracer.start_as_current_span(
            "merge.driver.probe",
            attributes={
                "merge.driver": "mergiraf",
                "probe.cached": False,
            },
        ) as probe_span:
            binary = shutil.which("mergiraf")
            probe_span.set_attribute("merge.binary_path", binary)
            if binary is None:
                # M2: do NOT clear the degraded stamp here. The
                # degraded stamp records "we fell back at some point
                # in this process"; clearing it when the binary
                # disappears would wipe evidence the operator may
                # still want to see (the binary could be back in a
                # moment, the fallback history should still be
                # visible). Only a successful probe clears the stamp
                # (see below).
                return _build_payload(
                    available=False,
                    binary=None,
                    version=None,
                    grammars=[],
                    probe_ok=False,
                    stamp=_resolve_degraded_since(app),
                )
            version = _probe_mergiraf_version(binary)
            # Phase 4 deferred review (M8): the grammar probe returns
            # a structured :class:`GrammarProbeResult` so the payload
            # can distinguish "no grammars" (empty list, probe_ok=True)
            # from "probe broken" (probe_ok=False). On probe-broke we
            # stamp degraded_since so operators see the degradation
            # even when mergiraf is the failure mode.
            grammar_result = _probe_mergiraf_grammars(binary)
            grammars = list(grammar_result.grammars)
            probe_ok = grammar_result.probe_ok
            if not probe_ok and _resolve_degraded_since(app) is None:
                _assign_degraded_since(app, datetime.now(UTC))
            available = version is not None
            if available and probe_ok and _resolve_degraded_since(app) is not None:
                # Healthy probe — clear stale degradation stamp.
                # This is the ONLY branch that clears the stamp;
                # binary-missing preserves the stamp per M2 and M8
                # sets the stamp on a broken probe.
                _assign_degraded_since(app, None)
            return _build_payload(
                available=available,
                binary=binary,
                version=version,
                grammars=grammars,
                probe_ok=probe_ok,
                stamp=_resolve_degraded_since(app),
            )
    except Exception as exc:  # noqa: BLE001 — /health must never propagate
        # C3: the function used to claim "catches all subprocess errors"
        # but the body didn't actually wrap the probe helpers, so any
        # ``TypeError``/``AttributeError`` (e.g. on a malformed binary
        # path that survived ``shutil.which``) would propagate and break
        # the entire ``/health`` endpoint. Wrap the whole body and
        # return the canonical empty payload so the health endpoint
        # always serves a well-formed response.
        logger.warning(
            "merge_driver_health.unhandled_error: "
            "type=%s message=%s — returning empty payload",
            type(exc).__name__,
            exc,
        )
        return _build_payload(
            available=False,
            binary=None,
            version=None,
            grammars=[],
            probe_ok=False,
            stamp=_resolve_degraded_since(app),
        )


def _build_payload(
    *,
    available: bool,
    binary: str | None,
    version: str | None,
    grammars: list[str],
    probe_ok: bool,
    stamp: datetime | None,
) -> dict[str, Any]:
    """Render the canonical ``merge_driver`` payload shape (REQ-SM-009).

    Centralizes the dict-shape construction so the four return paths
    in :func:`merge_driver_health` (binary-missing, healthy probe,
    probe-broken, unhandled-error) all serialize ``degraded_since``
    consistently. The stamp is the most-recent fallback timestamp set
    by :func:`mark_merge_driver_fallback`; ``None`` indicates either
    no fallback since process start or a successful probe cleared the
    stamp.

    Phase 4 deferred review (M8): the ``probe_ok`` field passes through
    directly — callers see ``False`` when the grammar probe subprocess
    timed out, errored, or exited non-zero. Distinct from
    ``grammars=[]`` with ``probe_ok=True`` (operators installed no
    grammars; that's a configuration choice, not a failure).
    """
    return {
        "available": available,
        "binary": binary,
        "version": version,
        "grammars": grammars,
        "probe_ok": probe_ok,
        "degraded_since": stamp.isoformat() if stamp is not None else None,
    }


def _probe_mergiraf_version(binary: str) -> str | None:
    """Parse ``mergiraf --version`` output. Returns ``None`` on failure."""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    import re

    match = re.search(r"mergiraf\s+(\d+\.\d+\.\d+)", result.stdout or result.stderr)
    return match.group(1) if match else None


# Phase 4 deferred review (M8): structured probe result so operators can
# distinguish "no grammars installed" from "probe broken". ``probe_ok``
# propagates to ``merge_driver_health`` payload as the ``probe_ok`` field.
@dataclass(frozen=True)
class GrammarProbeResult:
    """Structured outcome of ``mergiraf languages`` subprocess.

    ``grammars`` is a tuple of language names (matches the Phase 2 list
    shape but immutable for ``frozen=True``); ``probe_ok`` is ``True``
    only when the subprocess completed cleanly AND exited 0; ``error``
    carries a short human-readable reason when ``probe_ok=False``.
    """

    grammars: tuple[str, ...]
    probe_ok: bool
    error: str | None = None


def _probe_mergiraf_grammars(binary: str) -> GrammarProbeResult:
    """Probe ``mergiraf languages`` and return a structured result.

    Phase 4 deferred review (M8): the probe distinguishes "no grammars
    installed" (empty tuple, ``probe_ok=True``) from "probe broken"
    (timeout, non-zero exit, OSError — ``probe_ok=False``). Operators
    can tell at a glance whether an empty grammars list means a real
    configuration gap or a transient subprocess failure; ``merge_driver_health``
    stamps ``degraded_since`` on ``probe_ok=False`` so the operator's
    ``/health`` view stays accurate.
    """
    try:
        result = subprocess.run(
            [binary, "languages"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        return GrammarProbeResult(grammars=(), probe_ok=False, error=f"timeout: {exc!s}")
    except OSError as exc:
        return GrammarProbeResult(grammars=(), probe_ok=False, error=f"subprocess error: {exc!s}")
    if result.returncode != 0:
        return GrammarProbeResult(
            grammars=(),
            probe_ok=False,
            error=f"non-zero exit: {result.returncode}",
        )
    lines = (result.stdout or "").splitlines()
    # Output shape: ``Language Name (*.ext)`` per line; strip the
    # extension glob for a clean payload.
    languages: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        name = line.split(" ", 1)[0]
        if name and name not in languages:
            languages.append(name)
    return GrammarProbeResult(
        grammars=tuple(languages),
        probe_ok=True,
        error=None,
    )
