"""Health check system for MCP services.

This module provides health checking and dependency waiting functionality
using Oneiric's HTTP infrastructure for observability and proper lifecycle management.

Design: docs/plans/2026-02-27-health-check-system-design.md
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from oneiric.actions.http import HttpFetchAction, HttpActionSettings
from oneiric.adapters.httpx_base import HTTPXClientMixin
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.core.health_schemas import (
    DependencyStatus,
    HealthCheckResult,
    HealthResponse,
    HealthStatus,
    ReadyResponse,
    WaitResult,
)

if TYPE_CHECKING:
    from mahavishnu.core.config import DependencyConfig, HealthConfig

logger = get_logger("mahavishnu.health")


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
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=latency_ms,
                    error=f"HTTP {result.get('status_code', 'unknown')}",
                    response_data=result,
                )

            # Parse response body
            json_data = result.get("json") or {}
            status_str = json_data.get("status", "ok").lower()

            # Map status string to enum
            if status_str == "ok":
                status = HealthStatus.OK
            elif status_str == "degraded":
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY

            return HealthCheckResult(
                service_name=service_name,
                status=status,
                latency_ms=latency_ms,
                response_data=json_data,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.warning(
                "health-check-timeout",
                url=url,
                timeout=timeout,
            )
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=f"Timeout after {timeout}s",
            )

        except httpx.ConnectError as e:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.warning(
                "health-check-connection-refused",
                url=url,
                error=str(e),
            )
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error="Connection refused",
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.error(
                "health-check-error",
                url=url,
                error=str(e),
                exc_info=True,
            )
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=str(e),
            )

    def _extract_service_name(self, url: str) -> str:
        """Extract service name from URL for logging."""
        try:
            # Extract host:port from URL
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return f"{parsed.hostname}:{parsed.port}" if parsed.port else str(parsed.hostname)
        except Exception:
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
        tasks = {
            name: self._wait_for_single(name, config)
            for name, config in dependencies.items()
        }

        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for (name, _), result in zip(tasks.items(), gathered):
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
        deps_to_check = dependencies or (
            self._config.dependencies if self._config else {}
        )

        if deps_to_check:
            check_tasks = {
                name: self._checker.check(
                    f"{'https' if dep.use_tls else 'http'}://{dep.host}:{dep.port}/health",
                    timeout=self._config.check_timeout_seconds if self._config else 5.0,
                )
                for name, dep in deps_to_check.items()
            }

            if check_tasks:
                results = await asyncio.gather(
                    *check_tasks.values(), return_exceptions=True
                )
                for (name, _), result in zip(check_tasks.items(), results):
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
            ds.status in (HealthStatus.OK, HealthStatus.DEGRADED)
            for ds in dep_status.values()
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
