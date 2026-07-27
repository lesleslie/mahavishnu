"""Tests for §14 pool_share instrumentation on pool_route_execute / terminal_launch.

The spec §14 pool_share success criterion is the ratio of
``pool_route_execute`` (durable-branch) calls vs ``terminal_launch`` calls.
Both tools feed the same shared ``WorkerMetrics`` singleton; this file
exercises the wiring and the combined ratio using the ``_StubMCP`` pattern.

Calls the registered tools through ``stub.tools[...]`` because both
``pool_route_execute`` and ``terminal_launch`` are nested inside their
respective ``register_*_tools`` functions for FastMCP's decorator contract.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.observability.worker_metrics import WorkerMetrics
from mahavishnu.workers.contract.manager import SpawnResult
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState

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


def _make_record(worker_id: str) -> DurableWorkerRecord:
    now = dt.datetime(2026, 7, 27, 10, 0, 0, tzinfo=dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session=worker_id, window="@0", pane="%0"),
        state=WorkerLifecycleState.STARTING,
        created_at=now,
        last_seen_at=now,
    )


@pytest.fixture
def fresh_metrics(monkeypatch: pytest.MonkeyPatch) -> WorkerMetrics:
    """Reset the module-level _metrics singleton in both pool_tools and terminal_tools.

    The singletons live at import time and persist across tests; without a
    reset, prior tests in the suite leak counter values into ours.
    """
    fresh = WorkerMetrics()
    from mahavishnu.mcp.tools import pool_tools, terminal_tools

    monkeypatch.setattr(pool_tools, "_metrics", fresh)
    monkeypatch.setattr(terminal_tools, "_metrics", fresh)
    return fresh


def test_pool_route_execute_durable_branch_increments_pool_share(
    fresh_metrics: WorkerMetrics,
) -> None:
    """A successful durable-branch ``pool_route_execute`` increments pool_share numerator."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    spawn_result = SpawnResult(worker_id="w-1", record=_make_record("w-1"), pane="%0")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=MagicMock(),
        durable_manager=durable_manager,
        dhara=None,
    )

    fn = stub.tools["pool_route_execute"]
    out = asyncio.run(fn(prompt="do it", worker_type="terminal-claude"))

    assert out == {"worker_id": "w-1", "pane": "%0"}
    snap = fresh_metrics.snapshot()
    assert snap["pool_share_numerator"] == 1
    assert snap["pool_share_denominator"] == 1
    assert snap["pool_route_execute"] == 1
    assert snap["pool_share_ratio"] == 1.0


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


def test_combined_pool_and_terminal_calls_yield_half_ratio(
    fresh_metrics: WorkerMetrics,
) -> None:
    """1 pool + 1 terminal call produces ratio = 1/2 = 0.5 (≥0.45 target)."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools
    from mahavishnu.mcp.tools.terminal_tools import register_terminal_tools

    # Pool call first.
    spawn_result = SpawnResult(worker_id="w-1", record=_make_record("w-1"), pane="%0")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)
    pool_stub = _StubMCP()
    register_pool_tools(
        pool_stub,
        pool_manager=MagicMock(),
        durable_manager=durable_manager,
        dhara=None,
    )
    asyncio.run(
        pool_stub.tools["pool_route_execute"](prompt="do it", worker_type="terminal-claude")
    )

    # Terminal call second.
    terminal_manager = MagicMock()
    terminal_manager.launch_sessions = AsyncMock(return_value=["sess-1"])
    terminal_stub = _StubMCP()
    register_terminal_tools(terminal_stub, terminal_manager=terminal_manager, mcp_client=None)
    asyncio.run(terminal_stub.tools["terminal_launch"](command="ls"))

    snap = fresh_metrics.snapshot()
    assert snap["pool_share_numerator"] == 1
    assert snap["pool_share_denominator"] == 2
    assert snap["pool_share_ratio"] == 0.5
    assert snap["pool_route_execute"] == 1
    assert snap["terminal_launch"] == 1
