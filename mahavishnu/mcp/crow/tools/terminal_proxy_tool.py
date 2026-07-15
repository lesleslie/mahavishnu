"""FastMCP tool wrapper for the crow-mcp subprocess (terminal tool).

Currently the bodai-crow-server lifespan spawns a single crow-mcp subprocess
(see ``mahavishnu.mcp.crow.terminal_proxy``) but exposes no MCP tool that
calls into it. This module fills that gap with a single ``terminal`` tool
that delegates every call to the singleton subprocess. Task 2 will
add per-session subprocess support; this Task wires up the missing tool.

Until Task 2 lands, the tool multiplexes all callers onto one PTY. The
existing CrowTerminalAdapter keeps working unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastmcp import FastMCP

from ..terminal_proxy import get_crow_session

if TYPE_CHECKING:
    from ..settings import CrowSettings


def _tool_decorator(server: Any) -> Any:
    """Pick the tool decorator that routes through FastMCP when available.

    Mirrors the dual-target pattern used by ``file_tools``, ``rg_search``
    and the other tools in this package: a ``CrowServer`` exposes ``.fastmcp``
    whose ``tool`` decorator registers into FastMCP's tool manager; a plain
    ``StandardServer`` (used in tests) lacks that attribute, so we fall back
    to its own ``tool`` decorator.
    """
    fastmcp = getattr(server, "fastmcp", None)
    if fastmcp is not None:
        return cast("Any", fastmcp).tool
    return server.tool


def register(server: Any, settings: CrowSettings) -> None:
    """Register the ``terminal`` tool on the given FastMCP server."""
    deco = _tool_decorator(server)

    @deco()
    async def terminal(command: str) -> dict[str, Any]:
        """Run a command in the persistent crow-mcp PTY session.

        Args:
            command: The shell command to execute.

        Returns:
            MCP tool result (typically ``{"output": ...}`` or similar).
        """
        session = get_crow_session()
        # crow-mcp returns an mcp.types.CallToolResult; the FastMCP tool
        # contract here treats that as an opaque dict-shaped payload so
        # downstream MCP clients can serialize it themselves.
        return await session.call_tool("terminal", {"command": command})  # ty: ignore[invalid-return-type]


__all__ = ["register"]
