"""End-to-end integration test for tasks_handoff_to_workflow registration.

Verifies the T17 ``register_tasks_handoff_tools`` factory wires the
``tasks_handoff_to_workflow`` MCP tool onto a fresh FastMCP server and is
safe to invoke twice (FastMCP 4.x deduplicates via the local provider's
``Component already exists`` log — see ``mcp_common.providers.local_provider``).

Skips when the T16 feature-flag gate is closed (i.e. session-buddy<0.30
or the package is missing). Once PR #1 ships and the operator bumps
the pin, this test runs the full registration path against a real
FastMCP server.
"""

from __future__ import annotations

from mcp_common.fastmcp import FastMCP
import pytest

from mahavishnu.mcp.tools.tasks_handoff import register_tasks_handoff_tools
from mahavishnu.mcp.tools.tasks_handoff_gate import (
    tasks_handoff_to_workflow_available,
)


@pytest.mark.integration
async def test_tasks_handoff_to_workflow_registration_idempotent() -> None:
    """Registering twice does not duplicate the tool.

    The T17 factory's @mcp.tool() decorator must dedupe re-registrations
    so the tool list stays stable across FastMCP server re-uses. Skips
    when the T16 gate is closed (pre-PR #1 session-buddy <0.30).
    """
    if not tasks_handoff_to_workflow_available():
        pytest.skip("session-buddy 0.30+ not installed; pre-PR #1")

    mcp = FastMCP(name="test-handoff-server")
    register_tasks_handoff_tools(mcp)
    register_tasks_handoff_tools(mcp)  # second call should be idempotent

    # FastMCP 4.x exposes the registered tool set via list_tools(); the
    # v1 ``_tool_manager._tools`` private dict was removed in 3.x.
    tool_names = [t.name for t in await mcp.list_tools()]
    assert tool_names.count("tasks_handoff_to_workflow") == 1
