"""Regression test for Plan 7 Phase 2: the discover_tools handler must use
the public ``await server.get_tools()`` API instead of poking at the
private ``_tool_manager`` / ``_tools`` attributes on the FastMCP server.

Under FastMCP 3.x the private-attribute fallback in ``server_core.py``
returns stale data because the public tool registry moved. This test
asserts that the new public-API path actually retrieves the registered
tools, so a regression to the private poke fails fast.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_server_core_does_not_poke_private_tool_manager() -> None:
    """The production source must not reference the private
    ``_tool_manager`` / ``_tools`` attribute anymore.

    Plan 7 Phase 2 replaces these with the public
    ``await server.get_tools()`` API; a regression to the private poke
    breaks against FastMCP 3.x and must fail loudly.
    """
    server_core_path = (
        Path(__file__).resolve().parents[2]
        / "mahavishnu"
        / "mcp"
        / "server_core.py"
    )
    text = server_core_path.read_text(encoding="utf-8")
    # Strip comments and string literals before scanning — we want to
    # catch actual code references, not comments referencing the old API.
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Drop inline trailing comments so a `# was: _tool_manager` line
        # does not false-positive.
        code_only = line.split("#", 1)[0]
        cleaned_lines.append(code_only)
    cleaned = "\n".join(cleaned_lines)
    assert "_tool_manager" not in cleaned, (
        "Found private _tool_manager reference in server_core.py; "
        "Plan 7 Phase 2 requires the public await server.get_tools() API"
    )
    assert "server._tools" not in cleaned, (
        "Found private server._tools attribute access in server_core.py; "
        "Plan 7 Phase 2 requires the public await server.get_tools() API"
    )


@pytest.mark.asyncio
async def test_discover_tools_returns_registered_tools() -> None:
    """discover_tools must return at least one tool name from the FastMCP
    server's public registry.

    Under FastMCP 3.x the only supported introspection path is
    ``await server.list_tools()``. If the private ``_tool_manager`` poke
    regresses, this test catches the silent-empty-set failure.
    """
    from mcp_common.fastmcp import FastMCP

    server = FastMCP(name="test-discover-tools")

    @server.tool()
    async def sample_tool_one() -> str:
        """A trivial tool for testing discover_tools."""
        return "ok"

    @server.tool()
    async def sample_tool_two() -> str:
        """Another trivial tool for testing discover_tools."""
        return "ok"

    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert {"sample_tool_one", "sample_tool_two"} <= tool_names