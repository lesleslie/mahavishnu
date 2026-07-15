"""Tests for the missing-wire terminal tool registration.

Task 1 of docs/superpowers/plans/2026-07-14-crow-concurrent-sessions.md:
the bodai-crow-server lifespan spawns a single crow-mcp subprocess
(see ``mahavishnu.mcp.crow.terminal_proxy``) but exposes no MCP tool
that calls into it. This test pins the contract that an MCP tool
named ``terminal`` is registered once a server is brought up with
the standard tool set.

Concurrent / per-session support lands in Task 2; this file only
covers the single-PTY wiring (the smallest correct change).
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow.tools import terminal_proxy_tool


@pytest.mark.unit
async def test_terminal_tool_is_registered_on_server() -> None:
    """The ``terminal`` tool must be discoverable via the FastMCP server.

    Currently absent - see architecture report section 4, change #2.
    """
    server = FastMCP("test")
    settings = CrowSettings()
    terminal_proxy_tool.register(server, settings)  # ty: ignore[arg-type]

    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert "terminal" in tool_names, (
        f"Expected `terminal` tool registered; got {tool_names!r}. "
        "This is the missing wire: terminal_proxy.py owns a subprocess "
        "but no FastMCP tool exposes it."
    )
