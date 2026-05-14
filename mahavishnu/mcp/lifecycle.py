"""Lifecycle helpers for the MCP server."""

from __future__ import annotations

import logging
from typing import Any

from .bootstrap import register_profile_tools as _register_profile_tools_helper
from .tools.profiles import PROFILE_REGISTRATIONS, get_active_profile

logger = logging.getLogger(__name__)


async def start_server(server: Any, host: str = "127.0.0.1", port: int = 3000) -> None:
    """Start the MCP server with the active tool profile."""
    server._active_profile = get_active_profile()
    methods_to_call = PROFILE_REGISTRATIONS[server._active_profile]
    methods_set = set(methods_to_call)

    logger.info(
        "Starting Mahavishnu MCP server with tool profile: %s (%d registration groups scheduled)",
        server._active_profile.value,
        len(methods_to_call),
    )

    await _register_profile_tools_helper(server, methods_set)
    server._update_registered_tool_metrics()
    await server.server.run_http_async(host=host, port=port)


async def stop_server(server: Any) -> None:
    """Stop the MCP server and cleanup resources."""
    if hasattr(server, "mcp_client") and hasattr(server.mcp_client, "_client"):
        try:
            await server.mcp_client._client.stop()
            logger.info("Stopped mcpretentious MCP server")
        except Exception as exc:
            logger.warning("Error stopping mcpretentious server: %s", exc)


async def register_worktree_tools(server: Any) -> None:
    """Register worktree management tools."""
    if not server.app.worktree_coordinator:
        logger.info("WorktreeCoordinator not initialized, skipping tool registration")
        return

    from ..mcp.tools.worktree_tools import register_worktree_tools

    register_worktree_tools(server.server, server.app)
    logger.info("Registered 1 worktree management tool with MCP server")
