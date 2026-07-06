"""MCP tools for adapter registry management.

Provides MCP tools for:
- Listing registered adapters with filters
- Resolving adapters by task requirements
- Checking adapter health
- Enabling/disabling adapters
- Invalidating caches

Related: Hybrid Adapter Integration Plan Phase 5
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_adapter_registry_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register adapter registry MCP tools.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def adapter_list(
        domain: str | None = None,
        capabilities: list[str] | None = None,
        healthy_only: bool = False,
    ) -> dict[str, Any]:
        """List all registered adapters with optional filters."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()
            adapters = registry.list_adapters(
                domain=domain,
                capabilities=capabilities,
                healthy_only=healthy_only,
            )

            return {
                "success": True,
                "adapters": adapters,
                "count": len(adapters),
                "filters": {
                    "domain": domain,
                    "capabilities": capabilities,
                    "healthy_only": healthy_only,
                },
            }

        except RuntimeError:
            # Registry not initialized
            return {
                "success": False,
                "error": "Adapter registry not initialized",
                "adapters": [],
                "count": 0,
            }
        except Exception as e:
            logger.error(f"Failed to list adapters: {e}")
            return {
                "success": False,
                "error": str(e),
                "adapters": [],
                "count": 0,
            }

    @mcp.tool()
    async def adapter_resolve(
        task_type: str,
        required_capabilities: list[str],
        domain: str = "orchestration",
    ) -> dict[str, Any]:
        """Resolve the best adapter for task requirements."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()
            decision = await registry.resolve(
                domain=domain,
                key=task_type,
                capabilities=required_capabilities,
            )

            if decision is None:
                return {
                    "success": False,
                    "error": "No adapter found matching requirements",
                    "task_type": task_type,
                    "required_capabilities": required_capabilities,
                }

            return {
                "success": True,
                "adapter_name": decision.adapter_name,
                "matched_capabilities": decision.matched_capabilities,
                "resolution_time_ms": decision.resolution_time_ms,
                "fallback_used": decision.fallback_used,
                "explanation": decision.explanation,
            }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to resolve adapter: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def adapter_health(
        adapter_name: str | None = None,
    ) -> dict[str, Any]:
        """Check health of adapters."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()

            if adapter_name:
                # Check single adapter
                health = await registry.check_adapter_health(adapter_name)  # type: ignore[attr-defined]
                if health is None:
                    return {
                        "success": False,
                        "error": f"Adapter '{adapter_name}' not found",
                    }
                return {
                    "success": True,
                    "adapter_name": adapter_name,
                    "health": health,
                }
            else:
                # Check all adapters
                all_health = await registry.check_all_health()
                healthy_count = sum(1 for h in all_health.values() if h.get("status") == "healthy")
                return {
                    "success": True,
                    "health": all_health,
                    "summary": {
                        "total": len(all_health),
                        "healthy": healthy_count,
                        "unhealthy": len(all_health) - healthy_count,
                    },
                }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to check adapter health: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def adapter_enable(
        adapter_name: str,
        enabled: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Enable or disable an adapter."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()
            success = await registry.set_adapter_enabled(
                name=adapter_name,
                enabled=enabled,
                reason=reason,
            )

            if success:
                return {
                    "success": True,
                    "adapter_name": adapter_name,
                    "enabled": enabled,
                    "message": f"Adapter '{adapter_name}' {'enabled' if enabled else 'disabled'}",
                }
            else:
                return {
                    "success": False,
                    "error": f"Adapter '{adapter_name}' not found",
                }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to set adapter enabled: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def adapter_metadata(
        adapter_name: str,
    ) -> dict[str, Any]:
        """Get metadata for a specific adapter."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()
            metadata = registry.get_metadata(adapter_name)

            if metadata is None:
                return {
                    "success": False,
                    "error": f"Adapter '{adapter_name}' not found",
                }

            return {
                "success": True,
                "adapter_name": adapter_name,
                "metadata": metadata.to_dict(),
            }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to get adapter metadata: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def adapter_cache_invalidate(
        source: str | None = None,
    ) -> dict[str, Any]:
        """Invalidate adapter registry caches."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()

            if source:
                # Invalidate specific source
                if source == "discovery":
                    registry.discovery.invalidate_cache()
                elif source == "resolution":
                    registry.resolution_cache.invalidate()
                else:
                    registry.invalidate_cache()
            else:
                # Invalidate all caches
                registry.invalidate_cache()

            return {
                "success": True,
                "message": f"Cache invalidated: {source or 'all'}",
            }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def adapter_discover(
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Discover adapters from all sources."""
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()

            if force_refresh:
                registry.invalidate_cache()

            report = await registry.discover_and_register()

            return {
                "success": True,
                "report": report.to_dict(),
            }

        except RuntimeError:
            return {
                "success": False,
                "error": "Adapter registry not initialized",
            }
        except Exception as e:
            logger.error(f"Failed to discover adapters: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    logger.info("Registered adapter registry MCP tools")


__all__ = ["register_adapter_registry_tools"]
