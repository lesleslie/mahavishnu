"""Tests for pool_route_execute / dispatch_to_pool durable routing.

The durable-worker contract (F1, F12) routes shell-based worker types
through ``DurableWorkerManager.spawn`` for both ``pool_route_execute``
and ``dispatch_to_pool``. The ``worker_type`` parameter is added to
both nested tool functions; non-shell types continue on the legacy path.

Calls the registered tools through ``stub.tools[...]`` (mirror
``test_worker_list_filter.py`` and ``test_worker_tools.py`` conventions)
because ``pool_route_execute`` / ``dispatch_to_pool`` are nested inside
``register_pool_tools`` for FastMCP's decorator contract.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from unittest.mock import MagicMock

import pytest

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


def _stub_pool_manager() -> MagicMock:
    """A legacy pool manager that should NOT be called on the durable path."""
    return MagicMock()


def test_pool_route_execute_routes_shell_type_through_durable() -> None:
    """``pool_route_execute`` with a shell ``worker_type`` spawns via ``_durable_manager.spawn``."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    record = _make_record("w-1")
    spawn_result = SpawnResult(worker_id="w-1", record=record, pane="%0")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=durable_manager,
        dhara=None,
    )

    fn = stub.tools["pool_route_execute"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
        )
    )
    assert out == {"worker_id": "w-1", "pane": "%0"}
    durable_manager.spawn.assert_called_once_with(
        worker_type="terminal-claude",
        backend="claude_tui",
        command=["terminal-claude"],
    )


def test_dispatch_to_pool_records_worker_id_in_dhara() -> None:
    """``dispatch_to_pool`` persists worker_id at ``workflow-results/{wf_id}/``."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    record = _make_record("w-42")
    spawn_result = SpawnResult(worker_id="w-42", record=record, pane="%3")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    fake_dhara = MagicMock()
    fake_dhara.put = MagicMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=durable_manager,
        dhara=fake_dhara,
    )

    fn = stub.tools["dispatch_to_pool"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
            workflow_id="wf-42",
        )
    )
    assert out == {"worker_id": "w-42", "workflow_id": "wf-42"}
    fake_dhara.put.assert_called_once()
    call_args = fake_dhara.put.call_args
    assert call_args.args[0] == "workflow-results/wf-42/"
    assert call_args.args[1]["worker_id"] == "w-42"
