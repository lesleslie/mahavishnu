"""Tests for ``worker_tools.worker_monitor`` durable-manager routing.

When ``_durable_manager`` is configured, ``worker_monitor`` must return
authoritative state from ``DurableWorkerManager.status(worker_id)`` for each
requested worker id. Real ``DurableWorkerRecord`` instances ensure type
mismatches such as ``record.state.value`` are caught.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState

pytestmark = pytest.mark.unit


def _make_record(worker_id: str, state: WorkerLifecycleState) -> DurableWorkerRecord:
    now = dt.datetime(2026, 7, 27, 10, 0, 0, tzinfo=dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session=worker_id, window="@0", pane="%0"),
        state=state,
        created_at=now,
        last_seen_at=now,
    )


def test_worker_monitor_durable_path_returns_state_per_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable path returns flat dict ``{wid: state_string}`` per worker id."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.status = MagicMock(
        side_effect=lambda wid: {
            "w-1": _make_record("w-1", WorkerLifecycleState.RUNNING),
            "w-2": _make_record("w-2", WorkerLifecycleState.READY),
        }[wid]
    )

    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_monitor(["w-1", "w-2"], interval=1.0))
    assert out == {"w-1": "running", "w-2": "ready"}
    assert manager.status.call_count == 2
