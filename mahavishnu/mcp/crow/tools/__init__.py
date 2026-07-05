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

from typing import TYPE_CHECKING

from . import file_tools, rg_search, web_extract, web_tools

if TYPE_CHECKING:
    from mcp_common.profiles.standard import StandardServer

    from mahavishnu.mcp.crow.settings import CrowSettings


def _tool_decorator(server: StandardServer):
    """Return the tool decorator appropriate for this server."""
    return server.fastmcp.tool if hasattr(server, "fastmcp") else server.tool


def register_all(server: StandardServer, settings: CrowSettings) -> None:
    """Register all crow tools onto ``server``."""
    file_tools.register(server, settings)
    rg_search.register(server, settings)
    web_tools.register(server, settings)
    web_extract.register(server, settings)


__all__ = ["register_all", "_tool_decorator"]
