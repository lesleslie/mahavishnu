"""Verify workflow_get_outcome returns a validated WorkflowOutcome struct."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from dhara.schema import WorkflowOutcome
from fastmcp import FastMCP
import pytest

from mahavishnu.mcp.tools import workflow_tools
from mahavishnu.mcp.tools.workflow_tools import (
    register_workflow_tools,
    workflow_get_outcome,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_workflow_get_outcome_returns_validated_struct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "workflow_id": "wf-abc",
        "status": "failed",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {},
    }

    async def fake_get(key: str):
        return payload

    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.dhara.get",
        fake_get,
    )
    result = await workflow_get_outcome("wf-abc")
    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-abc"
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_workflow_get_outcome_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substrate returns None → consumer returns None (no validation attempted)."""

    async def fake_get(key: str):
        return None

    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.dhara.get",
        fake_get,
    )
    result = await workflow_get_outcome("wf-missing")
    assert result is None


@pytest.mark.asyncio
async def test_register_workflow_tools_registers_tool() -> None:
    """register_workflow_tools registers workflow_get_outcome as an MCP tool."""
    mcp = FastMCP(name="test-workflow-tools")
    register_workflow_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    # FastMCP derives tool name from the inline function's __name__
    assert "workflow_get_outcome_tool" in tool_names

    # And: the registered coroutine is async, matching the FastMCP contract.
    tool = next(t for t in tools if t.name == "workflow_get_outcome_tool")
    assert asyncio.iscoroutinefunction(tool.fn)


@pytest.mark.asyncio
async def test_registered_tool_delegates_to_module_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: calling the registered MCP tool returns a validated struct."""
    payload = {
        "workflow_id": "wf-e2e",
        "status": "succeeded",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {},
    }

    async def fake_get(key: str):
        return payload

    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.dhara.get",
        fake_get,
    )
    mcp = FastMCP(name="test-workflow-tools")
    register_workflow_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")
    result = await tool.fn(workflow_id="wf-e2e", user_id="viewer-1")
    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-e2e"
    assert result.status == "succeeded"


@pytest.mark.asyncio
async def test_workflow_get_outcome_is_coroutine_function() -> None:
    """workflow_get_outcome is async — FastMCP requires coroutines for tools."""
    assert asyncio.iscoroutinefunction(workflow_get_outcome)


@pytest.mark.asyncio
async def test_workflow_get_outcome_rejects_path_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module-level guard: caller-supplied path-traversal workflow_id is refused.

    Mirrors the sibling parity gate in ``pool_tools.workflow_result``: when
    ``workflow_id`` is anything other than ``^[A-Za-z0-9._-]{1,128}$``, the
    function returns the sentinel ``{"status": "invalid_workflow_id"}`` and
    Dhara is never queried. Without this gate, a caller could read arbitrary
    Dhara keys via ``workflow_id="../../etc/passwd"``.
    """
    dhara_get = AsyncMock()
    monkeypatch.setattr(workflow_tools.dhara, "get", dhara_get)

    result = await workflow_get_outcome("../../etc/passwd")

    assert result == {
        "workflow_id": "../../etc/passwd",
        "status": "invalid_workflow_id",
    }
    dhara_get.assert_not_called()


@pytest.mark.asyncio
async def test_registered_tool_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: registered MCP tool returns sentinel and never touches Dhara.

    Walks the FastMCP-registered ``workflow_get_outcome_tool`` so we know the
    guard is wired in the production registration path, not only on the
    module-level coroutine.
    """
    dhara_get = AsyncMock()
    monkeypatch.setattr(workflow_tools.dhara, "get", dhara_get)

    mcp = FastMCP(name="test-workflow-tools-traversal")
    register_workflow_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="../../etc/passwd", user_id="viewer-1")

    assert result == {
        "workflow_id": "../../etc/passwd",
        "status": "invalid_workflow_id",
    }
    dhara_get.assert_not_called()


async def test_workflow_get_outcome_tool_rejects_without_user_id(monkeypatch):
    """@require_mcp_auth wrapper rejects calls missing user_id.

    Without user_id the wrapper returns the AUTH_REQUIRED error envelope
    before the underlying workflow_get_outcome runs. Mirrors the brief's
    "rejection without permission" contract: the read never reaches the
    Dhara substrate.
    """
    from mcp_common.fastmcp import FastMCP

    from mahavishnu.mcp.tools import workflow_tools
    from mahavishnu.mcp.tools.workflow_tools import register_workflow_tools

    dhara_get = AsyncMock()
    monkeypatch.setattr(workflow_tools.dhara, "get", dhara_get)

    mcp = FastMCP(name="test-workflow-tools-auth")
    register_workflow_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="wf-1")

    assert isinstance(result, dict)
    assert result.get("status") == "error"
    assert result.get("error_code") == "AUTH_REQUIRED"
    dhara_get.assert_not_called()


async def test_workflow_get_outcome_tool_passes_with_user_id(monkeypatch):
    """@require_mcp_auth wrapper passes when user_id is supplied.

    With user_id the wrapper falls through to workflow_get_outcome. The
    substrate-compat gate still returns None when dhara.get returns None
    — we assert the wrapper did NOT short-circuit on auth.
    """
    from mcp_common.fastmcp import FastMCP

    from mahavishnu.mcp.tools import workflow_tools
    from mahavishnu.mcp.tools.workflow_tools import register_workflow_tools

    dhara_get = AsyncMock(return_value=None)
    monkeypatch.setattr(workflow_tools.dhara, "get", dhara_get)

    mcp = FastMCP(name="test-workflow-tools-auth-ok")
    register_workflow_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "workflow_get_outcome_tool")

    result = await tool.fn(workflow_id="wf-ok", user_id="viewer-1")

    # No AUTH_REQUIRED envelope → wrapper fell through.
    if isinstance(result, dict):
        assert result.get("error_code") != "AUTH_REQUIRED"
    dhara_get.assert_awaited_once_with("workflow-results/wf-ok/")
