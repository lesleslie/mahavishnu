"""MCP tools for health check system.

These tools provide health checking capabilities for the Mahavishnu ecosystem
following the design in docs/plans/2026-02-27-health-check-system-design.md.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from mahavishnu.core.health import (
    DependencyWaiter,
    HealthChecker,
    HealthEndpoint,
    ServiceInfo,
)
from mahavishnu.core.health_schemas import HealthStatus

if TYPE_CHECKING:
    from mahavishnu.core.config import DependencyConfig, HealthConfig, MahavishnuSettings


def register_health_tools(mcp: FastMCP, app: Any = None) -> None:
    """Register health check tools with MCP server.

    Args:
        mcp: FastMCP server instance
        app: Optional MahavishnuApp instance for dependency injection
    """

    @mcp.tool()
    async def health_check_service(
        service_name: str,
        host: str = "localhost",
        port: int = 8080,
        timeout: int = 5,
        use_tls: bool = False,
    ) -> dict[str, Any]:
        """Check health of a specific service.

        Performs an HTTP GET request to the service's /health endpoint
        and returns the health status.

        Args:
            service_name: Name of the service to check
            host: Hostname or IP address (default: localhost)
            port: Port number (default: 8080)
            timeout: Request timeout in seconds (default: 5)
            use_tls: Use HTTPS instead of HTTP (default: false)

        Returns:
            Health status dictionary with status, latency, and any errors

        Example:
            >>> result = await health_check_service("session_buddy", port=8678)
            >>> print(result["status"])
            "ok"
        """
        from mahavishnu.core.config import HealthConfig

        config = HealthConfig(check_timeout_seconds=timeout)
        checker = HealthChecker(config=config)

        scheme = "https" if use_tls else "http"
        url = f"{scheme}://{host}:{port}/health"

        result = await checker.check(url, timeout=timeout)

        response = {
            "service_name": service_name,
            "status": result.status.value,
            "latency_ms": result.latency_ms,
            "url": url,
        }

        if result.error:
            response["error"] = result.error

        if result.response_data:
            response["response"] = result.response_data

        return response

    @mcp.tool()
    async def health_check_all() -> dict[str, Any]:
        """Check health of all configured services.

        Queries the /health endpoint of each service configured in the
        health.dependencies section of settings.

        Returns:
            Dictionary with health status of all services

        Example:
            >>> result = await health_check_all()
            >>> for name, status in result["services"].items():
            ...     print(f"{name}: {status['status']}")
        """
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        config = settings.health
        checker = HealthChecker(config=config)

        if not config.dependencies:
            return {
                "status": "ok",
                "services": {},
                "message": "No dependencies configured",
            }

        # Check all dependencies concurrently
        results = {}
        tasks = {}

        for name, dep in config.dependencies.items():
            scheme = "https" if dep.use_tls else "http"
            url = f"{scheme}://{dep.host}:{dep.port}/health"
            tasks[name] = checker.check(url, timeout=config.check_timeout_seconds)

        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for (name, _), result in zip(tasks.items(), gathered):
                if isinstance(result, Exception):
                    results[name] = {
                        "status": HealthStatus.UNHEALTHY.value,
                        "error": str(result),
                    }
                else:
                    results[name] = {
                        "status": result.status.value,
                        "latency_ms": result.latency_ms,
                    }
                    if result.error:
                        results[name]["error"] = result.error

        # Determine overall status
        all_ok = all(
            r.get("status") in (HealthStatus.OK.value, HealthStatus.DEGRADED.value)
            for r in results.values()
        )

        return {
            "status": HealthStatus.OK.value if all_ok else HealthStatus.UNHEALTHY.value,
            "services": results,
            "total_services": len(results),
            "healthy_services": sum(
                1 for r in results.values() if r.get("status") == HealthStatus.OK.value
            ),
        }

    @mcp.tool()
    async def wait_for_dependency(
        service_name: str,
        host: str = "localhost",
        port: int = 8080,
        timeout: int = 30,
        required: bool = True,
        use_tls: bool = False,
    ) -> dict[str, Any]:
        """Wait for a specific dependency to become healthy.

        Uses exponential backoff for retries:
        - Base delay: 1s
        - Max delay: 16s
        - Sequence: 1s, 2s, 4s, 8s, 16s, 16s, ...

        Args:
            service_name: Name of the service to wait for
            host: Hostname or IP address (default: localhost)
            port: Port number (default: 8080)
            timeout: Maximum wait time in seconds (default: 30)
            required: Whether this is a required dependency (default: true)
            use_tls: Use HTTPS instead of HTTP (default: false)

        Returns:
            Result indicating success or timeout

        Example:
            >>> result = await wait_for_dependency(
            ...     "session_buddy",
            ...     port=8678,
            ...     timeout=60
            ... )
            >>> print(result["success"])
            True
        """
        from mahavishnu.core.config import DependencyConfig, HealthConfig

        dep_config = DependencyConfig(
            host=host,
            port=port,
            required=required,
            timeout_seconds=timeout,
            use_tls=use_tls,
        )

        health_config = HealthConfig()
        waiter = DependencyWaiter(config=health_config)

        start_time = time.time()
        result = await waiter.wait_for_all({service_name: dep_config})
        elapsed = time.time() - start_time

        dep_result = result.dependencies.get(service_name)

        response = {
            "service_name": service_name,
            "success": result.success or (not required and dep_result is not None),
            "elapsed_seconds": elapsed,
            "timeout_seconds": timeout,
        }

        if dep_result:
            response["status"] = dep_result.status.value
            response["latency_ms"] = dep_result.latency_ms
            if dep_result.error:
                response["error"] = dep_result.error

        if not result.success and required:
            response["message"] = (
                f"Required dependency '{service_name}' did not become healthy"
                f" within {timeout}s"
            )

        return response

    @mcp.tool()
    async def wait_for_all_dependencies() -> dict[str, Any]:
        """Wait for all configured dependencies to become healthy.

        Checks all dependencies configured in health.dependencies and waits
        for them to become healthy using exponential backoff.

        Required dependencies will block startup if unhealthy.
        Optional dependencies will be skipped after a few failed attempts.

        Returns:
            Result indicating overall success and per-dependency status

        Example:
            >>> result = await wait_for_all_dependencies()
            >>> if result["success"]:
            ...     print("All dependencies healthy")
            ... else:
            ...     print(f"Failed: {result['failed_required']}")
        """
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        config = settings.health

        if not config.dependencies:
            return {
                "success": True,
                "message": "No dependencies configured",
                "dependencies": {},
                "total_wait_seconds": 0,
            }

        waiter = DependencyWaiter(config=config)
        result = await waiter.wait_for_all(config.dependencies)

        response: dict[str, Any] = {
            "success": result.success,
            "total_wait_seconds": result.total_wait_seconds,
            "failed_required": result.failed_required,
            "skipped_optional": result.skipped_optional,
        }

        # Convert dependency results to serializable format
        deps_status = {}
        for name, dep_result in result.dependencies.items():
            deps_status[name] = {
                "status": dep_result.status.value,
                "latency_ms": dep_result.latency_ms,
            }
            if dep_result.error:
                deps_status[name]["error"] = dep_result.error

        response["dependencies"] = deps_status

        if not result.success:
            response["message"] = (
                f"Failed to connect to required dependencies: "
                f"{', '.join(result.failed_required)}"
            )

        return response

    @mcp.tool()
    async def get_liveness() -> dict[str, Any]:
        """Get liveness status for this service.

        Returns basic "is this process running" information.
        Called by platform health checks (Cloud Run, Kubernetes, etc.).

        Returns:
            Health response with status, service name, version, and uptime

        Example:
            >>> result = await get_liveness()
            >>> print(result["status"])
            "ok"
        """
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        config = settings.health

        service_info = ServiceInfo(
            name="mahavishnu",
            version="0.3.2",
        )
        endpoint = HealthEndpoint(service_info=service_info, config=config)

        response = await endpoint.liveness()
        return response.model_dump()

    @mcp.tool()
    async def get_readiness() -> dict[str, Any]:
        """Get readiness status for this service.

        Checks if this service is ready to accept work by verifying
        all dependencies are healthy.

        Called by load balancers, orchestrators, and other services
        before routing traffic.

        Returns:
            Readiness response with dependency status

        Example:
            >>> result = await get_readiness()
            >>> if result["ready"]:
            ...     print("Service is ready")
        """
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        config = settings.health

        service_info = ServiceInfo(
            name="mahavishnu",
            version="0.3.2",
        )
        endpoint = HealthEndpoint(service_info=service_info, config=config)

        response = await endpoint.readiness(config.dependencies)
        return response.model_dump()


__all__ = ["register_health_tools"]
