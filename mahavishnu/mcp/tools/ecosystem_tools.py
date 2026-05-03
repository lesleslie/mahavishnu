"""Canonical ecosystem status MCP tools (Control Plane Phase 3).

These tools expose the unified :class:`EcosystemStatusReport` so that
agents can query a single canonical source of truth for ecosystem health,
capabilities, and routing readiness.

See: ``mahavishnu/core/ecosystem_status.py`` for the report models and
     ``EcosystemStatusService`` for the collection logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_ecosystem_tools(mcp: FastMCP) -> None:
    """Register canonical ecosystem status tools.

    Args:
        mcp: FastMCP server instance.
    """

    @mcp.tool()
    async def ecosystem_status(
        sections: list[str] | None = None,
        include_details: bool = False,
        timeout_per_section_ms: int = 5000,
    ) -> dict[str, Any]:
        """Get canonical ecosystem health status across all services and adapters.

        Returns a unified status report with schema_version, overall status,
        per-section data (services, adapters, capabilities, workflows, alerts),
        and optional operational recommendations.

        Args:
            sections: Optional list of sections to include
                      (services, adapters, capabilities, workflows, alerts,
                      recommendations). None = all.
            include_details: Include detailed status information for each
                             component.
            timeout_per_section_ms: Per-section collection timeout in
                                    milliseconds.
        """
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        service = EcosystemStatusService(section_timeout_ms=timeout_per_section_ms)
        report = await service.generate_report()
        data = report.model_dump(mode="json")

        if sections:
            filtered: dict[str, Any] = {
                "schema_version": data["schema_version"],
                "status": data["status"],
                "generated_at": data["generated_at"],
                "duration_ms": data["duration_ms"],
            }
            for s in sections:
                if s in data:
                    filtered[s] = data[s]
            return filtered

        return data

    @mcp.tool()
    async def ecosystem_capabilities(
        capability: str | None = None,
    ) -> dict[str, Any]:
        """Query ecosystem capabilities by name or list all.

        Args:
            capability: Optional capability name filter (partial match,
                        case-insensitive).
        """
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        service = EcosystemStatusService()
        report = await service.generate_report()
        caps = report.capabilities

        if capability:
            caps = {k: v for k, v in caps.items() if capability.lower() in k.lower()}

        return {k: v.model_dump(mode="json") for k, v in caps.items()}

    @mcp.tool()
    async def ecosystem_routing_readiness(
        task_class: str,
    ) -> dict[str, Any]:
        """Check routing readiness for a given task class.

        Returns which adapters are healthy enough to accept work for the
        specified task class, along with degradation trends and preference
        scores.

        Args:
            task_class: The task class to check routing readiness for
                        (e.g. AI_TASK, CODE_GENERATION).
        """
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        service = EcosystemStatusService()
        report = await service.generate_report()

        available_adapters = {}
        for name, adapter in report.adapters.items():
            available_adapters[name] = {
                "status": adapter.status.value,
                "capabilities": adapter.capabilities,
                "degradation_trend": (
                    adapter.degradation_trend.value if adapter.degradation_trend else None
                ),
                "preference_score": adapter.preference_score,
            }

        healthy = [n for n, a in available_adapters.items() if a["status"] == "ok"]
        degraded = [n for n, a in available_adapters.items() if a["status"] == "degraded"]

        return {
            "task_class": task_class,
            "overall_status": report.status.value,
            "available_adapters": available_adapters,
            "healthy_count": len(healthy),
            "degraded_count": len(degraded),
            "recommendation": (
                f"Use {healthy[0]}" if healthy else f"No healthy adapters for {task_class}"
            ),
        }


__all__ = ["register_ecosystem_tools"]
