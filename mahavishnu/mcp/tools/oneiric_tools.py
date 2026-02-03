"""Oneiric MCP integration tools for Mahavishnu.

This module provides MCP tools for interacting with Oneiric MCP's adapter registry,
enabling dynamic adapter discovery and health monitoring within Mahavishnu workflows.

Tools:
- oneiric_list_adapters: List available adapters with optional filtering
- oneiric_resolve_adapter: Resolve adapter by domain/category/provider
- oneiric_check_health: Check adapter health status
- oneiric_get_adapter: Get adapter details by ID
- oneiric_invalidate_cache: Invalidate adapter cache
"""

import logging
from typing import Any

from mcp_common.models import ToolMetadata, ToolCategory
from mcp_common.ui import ServerPanels

from ...core.oneiric_client import AdapterEntry, OneiricMCPClient, OneiricMCPConfig
from ...core.app import app

logger = logging.getLogger(__name__)

# Global Oneiric MCP client instance
_oneiric_client: OneiricMCPClient | None = None


def get_oneiric_client() -> OneiricMCPClient | None:
    """Get or create Oneiric MCP client instance.

    Returns:
        OneiricMCPClient instance if enabled, None otherwise
    """
    global _oneiric_client

    config = app.config.oneiric_mcp

    if not config.enabled:
        logger.debug("Oneiric MCP integration disabled in configuration")
        return None

    if _oneiric_client is None:
        try:
            _oneiric_client = OneiricMCPClient(config=config)
            logger.info("Oneiric MCP client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Oneiric MCP client: {e}")
            return None

    return _oneiric_client


async def _adapter_to_dict(adapter: AdapterEntry) -> dict[str, Any]:
    """Convert AdapterEntry to dictionary representation.

    Args:
        adapter: Adapter entry object

    Returns:
        Dictionary representation
    """
    return adapter.to_dict()


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_list_adapters",
        description="List available adapters from Oneiric MCP registry with optional filtering",
        category=ToolCategory.DISCOVERY,
    )
)
async def oneiric_list_adapters(
    project: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    healthy_only: bool = False,
    use_cache: bool = True,
) -> dict[str, Any]:
    """List available adapters from Oneiric MCP registry.

    This tool queries the Oneiric MCP adapter registry and returns a list of
    available adapters matching the specified filters. Adapters can be filtered
    by project, domain, category, and health status.

    Args:
        project: Optional project name filter (e.g., "mahavishnu", "session-buddy")
        domain: Optional domain filter (e.g., "adapter", "service")
        category: Optional category filter (e.g., "storage", "orchestration", "cache")
        healthy_only: Only return adapters marked as healthy (default: False)
        use_cache: Use cached results if available (default: True)

    Returns:
        Dictionary with:
            - count: Number of adapters found
            - adapters: List of adapter details
            - cached: Whether results were from cache

    Example:
        >>> # List all healthy storage adapters
        >>> result = await oneiric_list_adapters(
        ...     category="storage",
        ...     healthy_only=True
        ... )
        >>> print(f"Found {result['count']} storage adapters")

        >>> # List all adapters for specific project
        >>> result = await oneiric_list_adapters(project="mahavishnu")
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "count": 0,
            "adapters": [],
            "error": "Oneiric MCP integration disabled or not available",
        }

    try:
        adapters = await client.list_adapters(
            project=project,
            domain=domain,
            category=category,
            healthy_only=healthy_only,
            use_cache=use_cache,
        )

        # Convert to dictionaries
        adapter_dicts = [await _adapter_to_dict(a) for a in adapters]

        logger.info(
            f"Listed {len(adapters)} adapters "
            f"(project={project}, domain={domain}, category={category})"
        )

        return {
            "count": len(adapters),
            "adapters": adapter_dicts,
            "cached": use_cache,
        }

    except Exception as e:
        logger.error(f"Error listing adapters: {e}")
        return {
            "count": 0,
            "adapters": [],
            "error": str(e),
        }


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_resolve_adapter",
        description="Resolve best-matching adapter by domain, category, and provider",
        category=ToolCategory.DISCOVERY,
    )
)
async def oneiric_resolve_adapter(
    domain: str,
    category: str,
    provider: str,
    project: str | None = None,
    healthy_only: bool = True,
) -> dict[str, Any]:
    """Resolve best-matching adapter from Oneiric MCP registry.

    This tool finds the best adapter matching the specified domain, category,
    and provider. It's useful for dynamically resolving adapters at runtime
    based on workflow requirements.

    Args:
        domain: Adapter domain (e.g., "adapter", "service")
        category: Adapter category (e.g., "storage", "orchestration", "cache")
        provider: Adapter provider (e.g., "s3", "prefect", "redis")
        project: Optional project filter
        healthy_only: Only return healthy adapters (default: True)

    Returns:
        Dictionary with:
            - found: Whether adapter was found
            - adapter: Adapter details if found
            - error: Error message if not found

    Example:
        >>> # Resolve S3 storage adapter
        >>> result = await oneiric_resolve_adapter(
        ...     domain="adapter",
        ...     category="storage",
        ...     provider="s3"
        ... )
        >>> if result['found']:
        ...     adapter = result['adapter']
        ...     print(f"Found: {adapter['adapter_id']}")

        >>> # Resolve Prefect orchestration adapter
        >>> result = await oneiric_resolve_adapter(
        ...     domain="adapter",
        ...     category="orchestration",
        ...     provider="prefect"
        ... )
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "found": False,
            "adapter": None,
            "error": "Oneiric MCP integration disabled or not available",
        }

    try:
        adapter = await client.resolve_adapter(
            domain=domain,
            category=category,
            provider=provider,
            project=project,
            healthy_only=healthy_only,
        )

        if adapter:
            logger.info(f"Resolved adapter: {adapter.adapter_id}")
            return {
                "found": True,
                "adapter": await _adapter_to_dict(adapter),
            }
        else:
            logger.warning(
                f"No adapter found for domain={domain}, category={category}, provider={provider}"
            )
            return {
                "found": False,
                "adapter": None,
                "error": f"No adapter found matching the criteria",
            }

    except Exception as e:
        logger.error(f"Error resolving adapter: {e}")
        return {
            "found": False,
            "adapter": None,
            "error": str(e),
        }


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_check_health",
        description="Check health status of a specific adapter",
        category=ToolCategory.MONITORING,
    )
)
async def oneiric_check_health(adapter_id: str) -> dict[str, Any]:
    """Check health status of a specific adapter.

    This tool queries the health status of an adapter from the Oneiric MCP registry.
    It's useful for monitoring adapter health before using it in workflows.

    Args:
        adapter_id: Adapter's unique ID (e.g., "mahavishnu.adapter.storage.s3")

    Returns:
        Dictionary with:
            - healthy: Whether adapter is healthy
            - adapter_id: The adapter ID checked
            - error: Error message if check failed

    Example:
        >>> # Check adapter health before use
        >>> result = await oneiric_check_health("mahavishnu.adapter.storage.s3")
        >>> if result['healthy']:
        ...     print("Adapter is healthy, safe to use")
        ... else:
        ...     print("Adapter is unhealthy, use fallback")

        >>> # Use in workflow with conditional logic
        >>> health = await oneiric_check_health(adapter_id)
        >>> if not health['healthy']:
        ...     # Try alternative adapter
        ...     pass
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "healthy": False,
            "adapter_id": adapter_id,
            "error": "Oneiric MCP integration disabled or not available",
        }

    try:
        is_healthy = await client.check_adapter_health(adapter_id)

        logger.info(f"Health check for {adapter_id}: {'healthy' if is_healthy else 'unhealthy'}")

        return {
            "healthy": is_healthy,
            "adapter_id": adapter_id,
        }

    except Exception as e:
        logger.error(f"Error checking health for {adapter_id}: {e}")
        return {
            "healthy": False,
            "adapter_id": adapter_id,
            "error": str(e),
        }


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_get_adapter",
        description="Get detailed information about a specific adapter by ID",
        category=ToolCategory.DISCOVERY,
    )
)
async def oneiric_get_adapter(adapter_id: str) -> dict[str, Any]:
    """Get detailed information about a specific adapter.

    This tool retrieves full details for an adapter from the Oneiric MCP registry.

    Args:
        adapter_id: Adapter's unique ID (e.g., "mahavishnu.adapter.storage.s3")

    Returns:
        Dictionary with:
            - found: Whether adapter was found
            - adapter: Adapter details if found
            - error: Error message if not found

    Example:
        >>> # Get adapter details
        >>> result = await oneiric_get_adapter("mahavishnu.adapter.storage.s3")
        >>> if result['found']:
        ...     adapter = result['adapter']
        ...     print(f"Provider: {adapter['provider']}")
        ...     print(f"Capabilities: {adapter['capabilities']}")
        ...     print(f"Factory: {adapter['factory_path']}")
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "found": False,
            "adapter": None,
            "error": "Oneiric MCP integration disabled or not available",
        }

    try:
        adapter = await client.get_adapter(adapter_id)

        if adapter:
            logger.debug(f"Retrieved adapter: {adapter_id}")
            return {
                "found": True,
                "adapter": await _adapter_to_dict(adapter),
            }
        else:
            logger.debug(f"Adapter not found: {adapter_id}")
            return {
                "found": False,
                "adapter": None,
                "error": f"Adapter {adapter_id} not found",
            }

    except Exception as e:
        logger.error(f"Error getting adapter {adapter_id}: {e}")
        return {
            "found": False,
            "adapter": None,
            "error": str(e),
        }


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_invalidate_cache",
        description="Invalidate the adapter list cache to force fresh queries",
        category=ToolCategory.MAINTENANCE,
    )
)
async def oneiric_invalidate_cache() -> dict[str, Any]:
    """Invalidate the adapter list cache.

    This tool clears the cached adapter list, forcing the next query to fetch
    fresh results from the Oneiric MCP registry. Useful when adapters are
    registered/unregistered and you need immediate visibility.

    Returns:
        Dictionary with:
            - success: Whether cache was invalidated
            - message: Status message

    Example:
        >>> # Invalidate cache after registering new adapter
        >>> await oneiric_invalidate_cache()
        >>> # Now list_adapters will fetch fresh results
        >>> adapters = await oneiric_list_adapters()
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "success": False,
            "message": "Oneiric MCP integration disabled or not available",
        }

    try:
        await client.invalidate_cache()
        logger.info("Adapter cache invalidated")

        return {
            "success": True,
            "message": "Adapter cache invalidated successfully",
        }

    except Exception as e:
        logger.error(f"Error invalidating cache: {e}")
        return {
            "success": False,
            "message": f"Error invalidating cache: {e}",
        }


@app.mcp.tool(
    ToolMetadata(
        name="oneiric_health_check",
        description="Check overall health of Oneiric MCP integration",
        category=ToolCategory.MONITORING,
    )
)
async def oneiric_health_check() -> dict[str, Any]:
    """Check overall health of Oneiric MCP integration.

    This tool performs a health check on the Oneiric MCP connection and returns
    status information including connection state, adapter count, and cache state.

    Returns:
        Dictionary with:
            - status: Health status ("healthy", "unhealthy", "disabled")
            - connected: Whether connected to Oneiric MCP
            - adapter_count: Number of adapters available (if connected)
            - cache_entries: Number of cached adapter lists
            - error: Error message if unhealthy

    Example:
        >>> # Check integration health before critical workflow
        >>> health = await oneiric_health_check()
        >>> if health['status'] != 'healthy':
        ...     # Log warning or use fallback mechanism
        ...     logger.warning(f"Oneiric MCP unhealthy: {health.get('error')}")
    """
    client = get_oneiric_client()

    if client is None:
        return {
            "status": "disabled",
            "connected": False,
            "adapter_count": 0,
            "cache_entries": 0,
            "message": "Oneiric MCP integration disabled in configuration",
        }

    try:
        health = await client.health_check()
        return health

    except Exception as e:
        logger.error(f"Error performing health check: {e}")
        return {
            "status": "unhealthy",
            "connected": False,
            "adapter_count": 0,
            "cache_entries": 0,
            "error": str(e),
        }
