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
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_adapter_registry_tools(mcp: FastMCP) -> None:
    """Register adapter registry MCP tools.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def adapter_list(
        domain: str | None = None,
        capabilities: list[str] | None = None,
        healthy_only: bool = False,
    ) -> dict[str, Any]:
        """List all registered adapters with optional filters.

        Args:
            domain: Filter by domain (e.g., "orchestration", "ai", "storage")
            capabilities: Filter by required capabilities (ALL must be present)
            healthy_only: Only return healthy adapters

        Returns:
            Dictionary with list of adapters and metadata
        """
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
        """Resolve the best adapter for task requirements.

        Uses capability matching and priority to select the optimal adapter.

        Args:
            task_type: Type of task (e.g., "workflow", "ai_task", "rag_query")
            required_capabilities: Required capabilities (ALL must be present)
            domain: Domain category (default: "orchestration")

        Returns:
            Dictionary with routing decision and selected adapter
        """
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
                    "error": f"No adapter found matching requirements",
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
        """Check health of adapters.

        Args:
            adapter_name: Specific adapter to check, or None for all adapters

        Returns:
            Dictionary with health status for requested adapter(s)
        """
        from mahavishnu.core.adapter_registry import get_registry

        try:
            registry = get_registry()

            if adapter_name:
                # Check single adapter
                health = await registry.check_adapter_health(adapter_name)
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
        """Enable or disable an adapter.

        Args:
            adapter_name: Name of the adapter to enable/disable
            enabled: True to enable, False to disable
            reason: Optional reason for the change

        Returns:
            Dictionary with operation result
        """
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
        """Get metadata for a specific adapter.

        Args:
            adapter_name: Name of the adapter

        Returns:
            Dictionary with adapter metadata
        """
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
        """Invalidate adapter registry caches.

        Args:
            source: Specific cache source to invalidate, or None for all caches

        Returns:
            Dictionary with operation result
        """
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
        """Discover adapters from all sources.

        Args:
            force_refresh: Force refresh even if cache is valid

        Returns:
            Dictionary with discovery report
        """
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
