"""End-to-end proof that the pool dispatch reports progress to a real client.

This is the wiring test for the dispatch heartbeat. It exercises the real
chain, not a mock of it:

    real ``register_pool_tools``  ->  real FastMCP server  ->  real
    ``fastmcp.Client``  ->  real ``ctx.report_progress``  ->  real
    ``notifications/progress``  ->  the client's progress handler

The only fake is the pool manager: ``route_task`` stands in for a worker
that takes a while, which is exactly the situation the heartbeat exists for.

The client here is the same shape as the real one: ``fastmcp.Client`` attaches
``_meta.progressToken`` to the request whenever a progress handler is
supplied, which is what makes the server's context carry a token. Claude
Code's own MCP client does the same thing, and resets its idle timer when a
progress notification arrives.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import mahavishnu.mcp.tools.pool_tools as pool_tools_module
from mahavishnu.mcp.tools.pool_tools import register_pool_tools

pytestmark = pytest.mark.integration


class _SlowPoolManager:
    """Stands in for a pool whose worker takes a while to answer."""

    def __init__(self, delay: float = 0.3) -> None:
        self._delay = delay
        self.calls: list[dict[str, Any]] = []

    async def route_task(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        await asyncio.sleep(self._delay)
        return {"status": "completed", "pool_id": "pool-test", "result": "ok"}

    async def health_check(self) -> dict[str, Any]:
        return {"pools_active": 1}


@pytest.mark.asyncio
@pytest.mark.req(["REQ-DSPROG-001"])
async def test_dispatch_reports_progress_to_a_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real client sees progress notifications for a slow dispatch."""
    from fastmcp.client import Client
    from mcp_common.fastmcp import FastMCP

    # Shorten the heartbeat so the test does not have to wait 20 seconds.
    # The mechanism under test -- injection, notification, delivery -- is
    # identical at any interval.
    monkeypatch.setattr(pool_tools_module, "_PROGRESS_HEARTBEAT_SECONDS", 0.02)

    pool_manager = _SlowPoolManager()
    mcp = FastMCP("progress-e2e")
    register_pool_tools(mcp, pool_manager=pool_manager)

    notifications: list[tuple[float, float | None, str | None]] = []

    async def on_progress(
        progress: float, total: float | None, message: str | None
    ) -> None:
        notifications.append((progress, total, message))

    async with Client(mcp) as client:
        result = await client.call_tool(
            "mahavishnu_pool_route_execute",
            {"prompt": "do the thing"},
            progress_handler=on_progress,
        )

    # The dispatch itself succeeded and returned the worker's result.
    payload = result.content[0].text
    assert "completed" in payload

    # The pool manager really was asked to run the task.
    assert len(pool_manager.calls) == 1
    assert pool_manager.calls[0]["task"]["prompt"] == "do the thing"

    # And the client really was told the server was still working.
    assert notifications, "expected at least one progress notification"
    assert notifications[0][2] is not None
    assert "elapsed" in notifications[0][2]


@pytest.mark.asyncio
async def test_dispatch_without_a_progress_handler_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that asks for no progress gets a normal, uninterrupted result."""
    from fastmcp.client import Client
    from mcp_common.fastmcp import FastMCP

    monkeypatch.setattr(pool_tools_module, "_PROGRESS_HEARTBEAT_SECONDS", 0.02)

    mcp = FastMCP("progress-e2e-noop")
    register_pool_tools(mcp, pool_manager=_SlowPoolManager())

    async with Client(mcp) as client:
        result = await client.call_tool(
            "mahavishnu_pool_route_execute", {"prompt": "do the thing"}
        )

    assert "completed" in result.content[0].text
