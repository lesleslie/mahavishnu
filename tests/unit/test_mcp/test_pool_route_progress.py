"""Unit tests for the pool-dispatch progress heartbeat.

A pool dispatch can legitimately outlast the MCP client's idle window. The
client aborts a tool call that produces neither a response nor a progress
notification for that window, so a healthy long-running dispatch dies at the
idle timeout. ``_dispatch_with_progress`` closes that gap by reporting
liveness while the dispatch is in flight.

These tests pin the four properties that matter:

1. the heartbeat actually emits progress notifications,
2. a dispatch with no context (direct call, or a client that supplied no
   progress token) runs exactly as it did before,
3. the heartbeat never outlives the dispatch -- on success or on failure,
4. a broken progress channel cannot fail a successful dispatch.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mahavishnu.mcp.tools.pool_tools import (
    _dispatch_with_progress,
    register_pool_tools,
)

pytestmark = pytest.mark.unit


class _FakeContext:
    """Minimal stand-in for FastMCP's ``Context``.

    Only ``report_progress`` matters here; that is the single method the
    heartbeat uses.
    """

    def __init__(self) -> None:
        self.progress: list[tuple[float, float | None, str | None]] = []

    async def report_progress(
        self, progress: float, total: float | None = None, message: str | None = None
    ) -> None:
        self.progress.append((progress, total, message))


# =============================================================================
# Heartbeat behaviour
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.req(["REQ-DSPROG-001"])
async def test_heartbeat_reports_progress_while_the_dispatch_runs() -> None:
    """The heartbeat emits at least one progress notification before the end."""
    ctx = _FakeContext()
    started = asyncio.Event()

    async def dispatch() -> dict[str, Any]:
        started.set()
        await asyncio.sleep(0.12)
        return {"status": "ok"}

    result = await _dispatch_with_progress(ctx, dispatch, interval=0.02)

    assert result == {"status": "ok"}
    assert ctx.progress, "expected at least one progress notification"
    first = ctx.progress[0]
    assert first[1] is None, "total is unknown for an unbounded dispatch"
    assert first[2] is not None and "elapsed" in first[2]
    # Elapsed seconds are reported as a monotonically increasing counter.
    elapsed = [int(p[0]) for p in ctx.progress]
    assert elapsed == sorted(elapsed)


@pytest.mark.asyncio
@pytest.mark.req(["REQ-DSPROG-003"])
async def test_dispatch_without_context_runs_unattended() -> None:
    """``ctx=None`` (direct call / no progress token) runs the dispatch as-is."""
    ctx = _FakeContext()
    calls: list[str] = []

    async def dispatch() -> dict[str, Any]:
        calls.append("ran")
        return {"status": "ok", "value": 42}

    result = await _dispatch_with_progress(None, dispatch)

    assert result == {"status": "ok", "value": 42}
    assert calls == ["ran"]
    assert ctx.progress == [], "no context means no progress to report"


@pytest.mark.asyncio
async def test_heartbeat_is_cancelled_when_the_dispatch_completes() -> None:
    """The heartbeat task does not outlive the dispatch."""
    ctx = _FakeContext()

    async def dispatch() -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    before = len(asyncio.all_tasks())
    await _dispatch_with_progress(ctx, dispatch, interval=0.01)
    await asyncio.sleep(0.05)

    # Allow the event loop a tick to process the cancellation.
    assert len(asyncio.all_tasks()) <= before


@pytest.mark.asyncio
async def test_dispatch_failure_propagates_and_still_cancels_the_heartbeat() -> None:
    """A failed dispatch raises its own error, not a heartbeat error."""
    ctx = _FakeContext()

    async def dispatch() -> dict[str, Any]:
        await asyncio.sleep(0.05)
        raise RuntimeError("dispatch failed")

    before = len(asyncio.all_tasks())
    with pytest.raises(RuntimeError, match="dispatch failed"):
        await _dispatch_with_progress(ctx, dispatch, interval=0.01)
    await asyncio.sleep(0.05)

    assert len(asyncio.all_tasks()) <= before


@pytest.mark.asyncio
async def test_a_broken_progress_channel_does_not_fail_the_dispatch() -> None:
    """Progress is advisory: a failing report must not fail the dispatch."""
    ctx = _FakeContext()
    ctx.report_progress = AsyncMock(side_effect=RuntimeError("client gone"))

    async def dispatch() -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    result = await _dispatch_with_progress(ctx, dispatch, interval=0.01)

    assert result == {"status": "ok"}
    assert ctx.report_progress.await_count >= 1


@pytest.mark.asyncio
async def test_heartbeat_does_not_delay_a_fast_dispatch() -> None:
    """A dispatch that finishes before the first tick emits no progress."""
    ctx = _FakeContext()

    async def dispatch() -> dict[str, Any]:
        return {"status": "ok"}

    result = await _dispatch_with_progress(ctx, dispatch, interval=10.0)

    assert result == {"status": "ok"}
    assert ctx.progress == []


# =============================================================================
# Schema: the injected context must stay out of the tool contract
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.req(["REQ-DSPROG-002"])
async def test_context_parameter_is_excluded_from_the_tool_schema() -> None:
    """``ctx`` is injected by FastMCP, never part of the wire contract.

    The MCP tool schema is the public contract with every client. Adding an
    injected-context parameter must not change it, or every checked-in
    surface snapshot drifts.
    """
    from mcp_common.fastmcp import FastMCP

    mcp = FastMCP("schema-probe")
    register_pool_tools(mcp, pool_manager=AsyncMock())

    tools = await mcp._list_tools()
    route = next(t for t in tools if t.name == "mahavishnu_pool_route_execute")

    properties = route.parameters.get("properties", {})
    assert "ctx" not in properties, (
        "the injected context must not appear in the tool schema"
    )
    assert "ctx" not in route.parameters.get("required", [])
    assert "prompt" in properties
