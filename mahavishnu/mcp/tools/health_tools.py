"""MCP tools for health check system.

These tools provide health checking capabilities for the Mahavishnu ecosystem
following the design in docs/plans/2026-02-27-health-check-system-design.md.

.. _deprecation-plan:

Deprecation Plan (Control Plane Phase 2)
-----------------------------------------
The following tools are flagged for deprecation and eventual replacement by a
unified ``ecosystem_status`` MCP tool (to be created in Control Plane Phase 2).

- **health_check_service** -- redundant with ``health_check_all``, which already
  iterates over all configured dependencies.  Prefer ``health_check_all`` for
  bulk checks; single-service pings should use ``mcp_test_connection``.
- **get_liveness** -- liveness semantics will be subsumed by ``ecosystem_status``
  (which will report liveness for *all* ecosystem services, not just this one).
- **get_readiness** -- readiness semantics will be subsumed by ``ecosystem_status``
  (same rationale as liveness).

Tools that remain **canonical** and will *not* be removed:

- ``health_check_all`` -- canonical bulk health check.
- ``mcp_test_connection`` -- MCP-level connectivity probe (distinct from HTTP health).
- ``mcp_list_tools`` -- tool introspection.
- ``mcp_get_metrics`` -- metrics snapshot.
- ``wait_for_dependency`` -- blocking dependency gate.
- ``wait_for_all_dependencies`` -- blocking multi-dependency gate.

Reference: docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
import warnings

from mahavishnu.core.health import (
    DependencyWaiter,
    HealthChecker,
    HealthEndpoint,
    HealthStatus,
    ServiceInfo,
)
from monitoring.metrics import expose_metrics, get_metrics_registry

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP


def register_health_tools(mcp: FastMCP, app: Any = None) -> None:  # noqa: C901
    """Register health check tools with MCP server.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP server instance
        app: Optional MahavishnuApp instance for dependency injection
    """

    def _server_name() -> str:
        if app is not None and getattr(app, "config", None) is not None:
            server_name = getattr(app.config, "server_name", None)
            if isinstance(server_name, str) and server_name.strip():
                return server_name
        return "mahavishnu"

    def _warn_deprecated_tool(tool_name: str, replacement: str) -> None:
        warnings.warn(
            f"{tool_name} is deprecated; use {replacement} instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def _tool_timeout_seconds(tool: Any) -> float | None:
        timeout = getattr(tool, "timeout", None)
        if timeout is None:
            return None
        if hasattr(timeout, "total_seconds"):
            return float(timeout.total_seconds())
        try:
            return float(timeout)
        except (TypeError, ValueError):
            return None

    def _summarize_tool(tool: Any) -> dict[str, Any]:
        parameters = getattr(tool, "parameters", None)
        summary: dict[str, Any] = {
            "name": getattr(tool, "name", "unknown"),
            "version": getattr(tool, "version", None),
            "title": getattr(tool, "title", None),
            "description": getattr(tool, "description", None),
            "tags": sorted(getattr(tool, "tags", set()) or []),
            "timeout_seconds": _tool_timeout_seconds(tool),
        }
        if parameters is not None:
            summary["parameters"] = parameters
        from mahavishnu.mcp.tool_versions import get_tool_deprecation

        replacement = get_tool_deprecation(summary["name"])
        if replacement is not None:
            summary["deprecated"] = True
            summary["deprecated_replaced_by"] = replacement
        return summary

    # deprecated: redundant with health_check_all; use mcp_test_connection for single-service pings
    # deprecated_replaced_by: ecosystem_status (CP2)
    @mcp.tool()
    async def health_check_service(
        service_name: str,
        host: str = "localhost",
        port: int = 8080,
        timeout: int = 5,
        use_tls: bool = False,
    ) -> dict[str, Any]:
        """Check health of a specific service."""
        _warn_deprecated_tool("health_check_service", "health_check_all")
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
            response["response"] = result.response_data  # type: ignore[assignment]

        return response

    @mcp.tool()
    async def mcp_list_tools() -> dict[str, Any]:
        """List all registered MCP tools with their metadata."""
        from mahavishnu.mcp.tool_versions import get_all_tool_versions

        tools = await mcp.list_tools()
        tool_summaries = sorted(
            (_summarize_tool(tool) for tool in tools),
            key=lambda item: item["name"],
        )
        versions = get_all_tool_versions()

        return {
            "status": "success",
            "server_name": _server_name(),
            "total_tools": len(tool_summaries),
            "versioned_tools": sum(1 for tool in tool_summaries if tool["version"]),
            "version_registry_size": len(versions),
            "tools": tool_summaries,
        }

    @mcp.tool()
    async def mcp_test_connection(
        service_name: str,
        host: str = "localhost",
        port: int = 8080,
        timeout: int = 5,
        use_tls: bool = False,
        health_path: str = "/health",
    ) -> dict[str, Any]:
        """Ping a specific server to verify MCP connectivity."""
        from mahavishnu.core.config import HealthConfig

        config = HealthConfig(check_timeout_seconds=timeout)
        checker = HealthChecker(config=config)

        scheme = "https" if use_tls else "http"
        url = f"{scheme}://{host}:{port}{health_path}"

        result = await checker.check(url, timeout=timeout)

        response = {
            "status": result.status.value,
            "connected": result.status != HealthStatus.UNHEALTHY,
            "service_name": service_name,
            "url": url,
            "latency_ms": result.latency_ms,
        }

        if result.error:
            response["error"] = result.error

        if result.response_data:
            response["response"] = result.response_data

        return response

    @mcp.tool()
    async def mcp_get_metrics() -> dict[str, Any]:
        """Return a metrics snapshot for the running MCP server."""
        tools = await mcp.list_tools()
        registry = get_metrics_registry()
        metric_families = []

        for family in registry.collect():
            metric_families.append(
                {
                    "name": family.name,
                    "type": family.type,
                    "documentation": family.documentation,
                    "sample_count": len(family.samples),
                }
            )

        metrics_text = expose_metrics().decode("utf-8")

        return {
            "status": "success",
            "server_name": _server_name(),
            "registered_tools": len(tools),
            "metric_family_count": len(metric_families),
            "metric_families": metric_families,
            "metrics_text": metrics_text,
            "metrics_preview": metrics_text.splitlines()[:25],
        }

    @mcp.tool()
    async def health_check_all() -> dict[str, Any]:
        """Check health of all configured services."""
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
            for (name, _), result in zip(tasks.items(), gathered, strict=True):
                if isinstance(result, Exception):
                    results[name] = {
                        "status": HealthStatus.UNHEALTHY.value,
                        "error": str(result),
                    }
                else:
                    results[name] = {
                        "status": result.status.value,  # type: ignore[union-attr]
                        "latency_ms": result.latency_ms,  # type: ignore[dict-item, union-attr]
                    }
                    if result.error:  # type: ignore[union-attr]
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
        """Wait for a specific dependency to become healthy."""
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
                f"Required dependency '{service_name}' did not become healthy within {timeout}s"
            )

        return response

    @mcp.tool()
    async def wait_for_all_dependencies() -> dict[str, Any]:
        """Wait for all configured dependencies to become healthy."""
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
                f"Failed to connect to required dependencies: {', '.join(result.failed_required)}"
            )

        return response

    # deprecated: will be subsumed by ecosystem_status (CP2)
    # deprecated_replaced_by: ecosystem_status (CP2)
    @mcp.tool()
    async def get_liveness() -> dict[str, Any]:
        """Get liveness status for this service."""
        _warn_deprecated_tool("get_liveness", "ecosystem_status")
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

    # deprecated: will be subsumed by ecosystem_status (CP2)
    # deprecated_replaced_by: ecosystem_status (CP2)
    @mcp.tool()
    async def get_readiness() -> dict[str, Any]:
        """Get readiness status for this service."""
        _warn_deprecated_tool("get_readiness", "ecosystem_status")
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
