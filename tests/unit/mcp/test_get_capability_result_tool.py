"""Tests for the ``get_capability_result`` MCP tool.

Mocks the Dhara client so no live storage is required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP
import pytest

from mahavishnu.core.capabilities import EnvelopeId, TraceId
from mahavishnu.mcp.tools.get_capability_result_tool import register_get_capability_result

pytestmark = pytest.mark.unit


def _envelope_key(envelope_id: str) -> str:
    """Build a canonical ``envelopes/<trace_id>/<envelope_id>`` key for fixtures."""
    return f"envelopes/{'a' * 32}/{envelope_id}"


def test_get_capability_result_reads_envelopes_from_mcp() -> None:
    """Registration smoke check: tool appears in ``list_tools()``."""
    mcp = MagicMock()
    server = FastMCP("test")
    register_get_capability_result(server, mcp=mcp)

    tools = asyncio.run(server.list_tools())
    assert any(t.name == "get_capability_result" for t in tools)


async def test_get_capability_result_returns_dict_with_envelopes() -> None:
    """End-to-end: invoking the tool awaits ``list_envelopes`` and returns a dict.

    Before the missing-await fix, this returned a coroutine object instead of
    a dict. With the fix, ``await tool.fn(...)`` resolves to the inner
    ``{"trace_id": ..., "status": ..., "envelopes": ..., "error": ...}`` dict.
    """
    envelope_id = EnvelopeId("12345678-1234-4234-8234-123456789012")
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(return_value=[_envelope_key(envelope_id)])

    server = FastMCP("test-invoke")
    register_get_capability_result(server, mcp=mcp)

    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "get_capability_result")

    trace_id = TraceId("a" * 32)
    result = await tool.fn(trace_id=trace_id)

    assert not asyncio.iscoroutine(result), (
        "tool.fn must return a dict, not a coroutine — missing await on list_envelopes"
    )
    assert isinstance(result, dict)
    assert result["trace_id"] == trace_id
    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["envelopes"] == [_envelope_key(envelope_id)]
    mcp.call_tool.assert_awaited_once_with("list_keys", {"prefix": f"envelopes/{trace_id}/"})


async def test_get_capability_result_returns_pending_when_no_envelopes() -> None:
    """Empty Dhara result surfaces ``status='pending'`` and empty envelope list."""
    mcp = MagicMock()
    mcp.call_tool = AsyncMock(return_value=[])

    server = FastMCP("test-empty")
    register_get_capability_result(server, mcp=mcp)

    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "get_capability_result")

    trace_id = TraceId("a" * 32)
    result = await tool.fn(trace_id=trace_id)

    assert isinstance(result, dict)
    assert result["status"] == "pending"
    assert result["envelopes"] == []
    assert result["error"] is None


async def test_get_capability_result_fails_loudly_when_mcp_call_raises() -> None:
    """Dhara-unavailable must surface as an exception, NOT silently return pending.

    Regression guard for the v0.19.0 contract: the deprecated
    ``dispatch_to_pool``/``workflow_result`` pair had a silent-no-op
    fallback that returned ``not_found`` whenever Dhara was unavailable,
    breaking the read-back contract (see
    ``docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md``).
    The new ``get_capability_result`` must NOT regress to a silent ``pending``
    on Dhara failure — operators must see the failure.
    """
    from mahavishnu.core.errors import ErrorCode, MahavishnuError

    mcp = MagicMock()
    mcp.call_tool = AsyncMock(
        side_effect=MahavishnuError(
            "mcp unavailable", error_code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE
        )
    )

    server = FastMCP("test-mcp-down")
    register_get_capability_result(server, mcp=mcp)

    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "get_capability_result")

    trace_id = TraceId("a" * 32)
    with pytest.raises(MahavishnuError, match="mcp unavailable"):
        await tool.fn(trace_id=trace_id)


async def test_get_capability_result_fails_loudly_when_mcp_is_none() -> None:
    """Invoking the tool with ``mcp=None`` must raise, NOT silently return pending.

    The bug-path of v0.18.x's ``workflow_result`` was: registration accepted
    ``mcp=None`` and silently returned ``not_found`` for every lookup. The
    new tool requires ``mcp`` as a keyword argument; passing ``None`` is
    type-unsafe but Python does not enforce the annotation at runtime, so
    registration succeeds. The crucial regression check is that invocation
    raises clearly — operators must see the misconfiguration, not a silent
    ``status='pending'`` that hides a broken backend.
    """
    server = FastMCP("test-none-mcp")
    register_get_capability_result(server, mcp=None)  # type: ignore[arg-type]

    tools = await server.list_tools()
    tool = next(t for t in tools if t.name == "get_capability_result")

    trace_id = TraceId("a" * 32)
    with pytest.raises((AttributeError, TypeError)):
        await tool.fn(trace_id=trace_id)
