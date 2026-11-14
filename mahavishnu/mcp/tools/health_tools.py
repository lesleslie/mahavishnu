"""MCP tools for the health check surface.

The six shared health tools are owned by :mod:`mcp_common.health`, so every
Bodai server exposes exactly one implementation behind each name. This
module mounts that shared surface with Mahavishnu's dependency map and
deprecation map, and keeps the three Mahavishnu-specific MCP tools that
have no fleet-wide equivalent:

- ``mahavishnu_mcp_list_tools`` -- tool introspection
- ``mahavishnu_mcp_test_connection`` -- MCP-level connectivity probe
- ``mahavishnu_mcp_get_metrics`` -- metrics snapshot

.. _deprecation-plan:

Deprecation Plan (Control Plane Phase 2)
-----------------------------------------
The following tools are flagged for deprecation and eventual replacement by a
unified ``mahavishnu_ecosystem_status`` MCP tool (to be created in Control Plane Phase 2).

- **health_check_service** -- redundant with ``health_check_all``, which already
  iterates over all configured dependencies.  Prefer ``health_check_all`` for
  bulk checks; single-service pings should use ``mahavishnu_mcp_test_connection``.
- **get_liveness** -- liveness semantics will be subsumed by ``mahavishnu_ecosystem_status``
  (which will report liveness for *all* ecosystem services, not just this one).
- **get_readiness** -- readiness semantics will be subsumed by ``mahavishnu_ecosystem_status``
  (same rationale as liveness).

The map below is handed to mcp-common, which warns only for the names it
lists -- so the other three Bodai servers stay warning-free.

Tools that remain **canonical** and will *not* be removed:

- ``health_check_all`` -- canonical bulk health check.
- ``mahavishnu_mcp_test_connection`` -- MCP-level connectivity probe (distinct from HTTP health).
- ``mahavishnu_mcp_list_tools`` -- tool introspection.
- ``mahavishnu_mcp_get_metrics`` -- metrics snapshot.
- ``wait_for_dependency`` -- blocking dependency gate.
- ``wait_for_all_dependencies`` -- blocking multi-dependency gate.

Reference: docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from weakref import WeakSet

from mcp_common.health import DependencyConfig as SharedDependencyConfig
from mcp_common.health import register_health_tools as register_shared_health_tools

from mahavishnu.core.health import HealthChecker, HealthStatus
from monitoring.metrics import expose_metrics, get_metrics_registry

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP


logger = logging.getLogger(__name__)


#: Tool name -> replacement name for the tools this server still deprecates.
#: Only names present in this map warn; mcp-common owns the mechanism.
DEPRECATED_TOOLS: dict[str, str] = {
    "health_check_service": "health_check_all",
    "get_liveness": "mahavishnu_ecosystem_status",
    "get_readiness": "mahavishnu_ecosystem_status",
}


# Servers that already carry the three Mahavishnu-specific tools. FastMCP
# replaces a duplicate registration (logging "Component already exists"),
# which leaves the first copy shadowed. Mahavishnu mounts health tools from
# BOTH the legacy path (``server_core._register_tools``) and the profile
# path (``apply_tool_profile`` -> ``_register_health_tools``), so this guard
# is what keeps one registration per name. The shared six are guarded by
# mcp-common's own equivalent, so the two guards stay independent: whichever
# path runs first owns the tools.
_WIRED_SERVERS: WeakSet[Any] = WeakSet()


def _server_name(app: Any = None) -> str:
    """Return the service name this server reports."""
    config = getattr(app, "config", None) if app is not None else None
    if config is not None:
        name = getattr(config, "server_name", None)
        if isinstance(name, str) and name.strip():
            return name
    return "mahavishnu"


def _version() -> str:
    """Return the installed Mahavishnu version."""
    try:
        from mahavishnu import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - metadata lookup fallback
        logger.debug("Mahavishnu version metadata unavailable", exc_info=True)
        return "0.0.0"


def _dependency_map(app: Any = None) -> dict[str, SharedDependencyConfig]:
    """Convert Mahavishnu's health dependencies to the shared shape.

    The shared implementation takes its dependency map at registration
    time, which is the same contract the other three Bodai servers use.
    """
    config = getattr(app, "config", None) if app is not None else None
    health = getattr(config, "health", None) if config is not None else None
    if health is None:
        from mahavishnu.core.config import MahavishnuSettings

        health = MahavishnuSettings().health
    return {
        name: SharedDependencyConfig(
            host=dep.host,
            port=dep.port,
            required=dep.required,
            timeout_seconds=dep.timeout_seconds,
            use_tls=dep.use_tls,
        )
        for name, dep in health.dependencies.items()
    }


def _tool_timeout_seconds(tool: Any) -> float | None:
    timeout = getattr(tool, "timeout", None)
    if timeout is None:
        return None
    if hasattr(timeout, "total_seconds"):
        return float(timeout.total_seconds())
    try:
        return float(timeout)
    except TypeError, ValueError:
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


async def _readiness_extra() -> dict[str, Any]:
    """Contribute Mahavishnu's worker-capability state to ``get_readiness``.

    The MCP tool and the ``/ready`` HTTP route are documented to carry the
    same payload, and worker capability state is Mahavishnu's own concept
    -- it has no fleet-wide meaning, so it cannot live in the shared
    module. The shared module merges whatever this returns without
    knowing what the extra fields mean; the hook is invoked at probe
    time, so the payload reflects live state rather than what was
    configured at registration.
    """
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.health import aggregate_readiness

    try:
        settings = MahavishnuSettings()
        return {"workers": await aggregate_readiness(settings=settings)}
    except Exception:
        logger.exception("readiness worker aggregation failed")
        return {"workers": {"status": "unhealthy"}}


def register_health_tools(mcp: FastMCP, app: Any = None) -> None:
    """Register the health surface and Mahavishnu's three MCP tools.

    Args:
        mcp: FastMCP server instance
        app: Optional MahavishnuApp instance for dependency injection
    """
    register_shared_health_tools(
        mcp,
        server_name=_server_name(app),
        version=_version(),
        dependencies=_dependency_map(app),
        deprecated_tools=DEPRECATED_TOOLS,
        readiness_extra=_readiness_extra,
    )

    if mcp in _WIRED_SERVERS:
        logger.debug(
            "Mahavishnu MCP tools are already registered on this server; "
            "skipping re-registration so each tool name is registered "
            "exactly once."
        )
        return
    _WIRED_SERVERS.add(mcp)

    @mcp.tool()
    async def mahavishnu_mcp_list_tools() -> dict[str, Any]:
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
            "server_name": _server_name(app),
            "total_tools": len(tool_summaries),
            "versioned_tools": sum(1 for tool in tool_summaries if tool["version"]),
            "version_registry_size": len(versions),
            "tools": tool_summaries,
        }

    @mcp.tool()
    async def mahavishnu_mcp_test_connection(
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
    async def mahavishnu_mcp_get_metrics() -> dict[str, Any]:
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
            "server_name": _server_name(app),
            "registered_tools": len(tools),
            "metric_family_count": len(metric_families),
            "metric_families": metric_families,
            "metrics_text": metrics_text,
            "metrics_preview": metrics_text.splitlines()[:25],
        }


__all__ = ["DEPRECATED_TOOLS", "register_health_tools"]
