"""Tests for §14 pool_share instrumentation on terminal_launch.

The spec §14 pool_share success criterion is the ratio of pool-routed
calls vs ``terminal_launch`` calls, both feeding the same shared
``WorkerMetrics`` singleton.

Task 3b.3 removed the deprecated ``pool_route_execute`` tool (and with it
the ``pool_tools._metrics`` singleton), so the numerator side of the ratio
is no longer produced by ``pool_tools``. What remains here is the
denominator wiring on ``terminal_launch``; the numerator is re-established
by ``execute_capability`` and covered by its own tests.

Calls the registered tool through ``stub.tools[...]`` because
``terminal_launch`` is nested inside ``register_terminal_tools`` for
FastMCP's decorator contract.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.observability.worker_metrics import WorkerMetrics

pytestmark = pytest.mark.unit


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def fresh_metrics(monkeypatch: pytest.MonkeyPatch) -> WorkerMetrics:
    """Reset the module-level ``_metrics`` singleton in terminal_tools.

    The singleton lives at import time and persists across tests; without a
    reset, prior tests in the suite leak counter values into ours.
    """
    fresh = WorkerMetrics()
    from mahavishnu.mcp.tools import terminal_tools

    monkeypatch.setattr(terminal_tools, "_metrics", fresh)
    return fresh


def test_terminal_launch_increments_pool_share_denominator(
    fresh_metrics: WorkerMetrics,
) -> None:
    """``terminal_launch`` increments terminal_calls on the shared metrics singleton."""
    from mahavishnu.mcp.tools.terminal_tools import register_terminal_tools

    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["sess-1"])

    stub = _StubMCP()
    register_terminal_tools(stub, terminal_manager=manager, mcp_client=None)

    fn = stub.tools["terminal_launch"]
    out = asyncio.run(fn(command="ls -la"))

    assert out == ["sess-1"]
    snap = fresh_metrics.snapshot()
    assert snap["pool_share_numerator"] == 0
    assert snap["pool_share_denominator"] == 1
    assert snap["terminal_launch"] == 1
    assert snap["pool_share_ratio"] == 0.0
