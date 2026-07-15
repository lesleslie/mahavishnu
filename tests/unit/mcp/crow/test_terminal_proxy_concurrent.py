"""Tests for the missing-wire terminal tool registration.

Task 1 of docs/superpowers/plans/2026-07-14-crow-concurrent-sessions.md:
the bodai-crow-server lifespan spawns a single crow-mcp subprocess
(see ``mahavishnu.mcp.crow.terminal_proxy``) but exposes no MCP tool
that calls into it. This test pins the contract that an MCP tool
named ``terminal`` is registered once a server is brought up with
the standard tool set.

Task 2 extends this file with per-session pool semantics + the four
``crow_terminal_*`` tools.
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
    terminal_proxy_tool.register(server, settings)

    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert "terminal" in tool_names, (
        f"Expected `terminal` tool registered; got {tool_names!r}. "
        "This is the missing wire: terminal_proxy.py owns a subprocess "
        "but no FastMCP tool exposes it."
    )


@pytest.mark.unit
async def test_acquire_session_returns_distinct_subprocesses() -> None:
    """Two acquire_session calls return different _CrowState instances."""
    from mahavishnu.mcp.crow.terminal_proxy import (
        _CrowState,
        acquire_session,
        shutdown_all_sessions,
    )

    settings = CrowSettings(max_concurrent_sessions=4)
    try:
        s1 = await acquire_session("worker-A", settings)
        s2 = await acquire_session("worker-B", settings)
        assert isinstance(s1, _CrowState)
        assert isinstance(s2, _CrowState)
        assert s1 is not s2, "Two acquire_session calls must not return the same state"
        # Different subprocess handles
        assert s1.exit_stack is not s2.exit_stack
    finally:
        await shutdown_all_sessions()


@pytest.mark.unit
async def test_crow_terminal_open_returns_session_handle() -> None:
    """The new open tool must register four ``crow_terminal_*`` tools."""
    server = FastMCP("test")
    terminal_proxy_tool.register(server, CrowSettings())

    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "crow_terminal_open" in names
    assert "crow_terminal_exec" in names
    assert "crow_terminal_read" in names
    assert "crow_terminal_close" in names
