"""Tool registration for the Bodai crow HTTP MCP server.

Each tool module exposes a ``register(server, settings)`` function that
binds the public tool name to the internal ``_``-prefixed implementation
via the appropriate decorator. The decorator is dispatched at runtime:

- If the server exposes a ``fastmcp`` attribute (our ``CrowServer``),
  ``server.fastmcp.tool()`` is used so FastMCP owns the lifespan and
  the tool registry.
- Otherwise, ``server.tool()`` (StandardServer's decorator) is used.

This dual-target pattern lets the same ``register`` functions work
against a plain ``StandardServer`` (e.g. in a test fixture) and the
production ``CrowServer`` (with FastMCP-owned lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import file_tools, rg_search, terminal_proxy_tool, web_extract, web_tools

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp_common.profiles.standard import StandardServer

    from mahavishnu.mcp.crow.settings import CrowSettings


def _tool_decorator(server: "FastMCP | StandardServer") -> Any:
    """Return the tool decorator appropriate for this server."""
    fastmcp = getattr(server, "fastmcp", None)
    if fastmcp is not None:
        return fastmcp.tool
    return server.tool


def register_all(server: "FastMCP | StandardServer", settings: CrowSettings) -> None:
    """Register all crow tools onto ``server``."""
    file_tools.register(server, settings)
    rg_search.register(server, settings)
    web_tools.register(server, settings)
    web_extract.register(server, settings)
    terminal_proxy_tool.register(server, settings)


__all__ = ["register_all", "_tool_decorator"]
