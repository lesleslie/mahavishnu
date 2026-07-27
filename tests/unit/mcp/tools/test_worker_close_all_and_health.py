"""Tests for worker_tools.worker_close_all and worker_health durable paths.

The durable-worker contract (F1) routes ``worker_close_all`` through
``DurableWorkerManager.cancel`` for each in-flight record and
``worker_health`` through an aggregate ``store.list_all()`` count.

Uses real ``DurableWorkerRecord`` instances (Task 19's reviewer caught
the ``r.state.value`` anti-pattern that MagicMock had hidden).
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


def test_worker_close_all_cancels_each_in_flight_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """``worker_close_all`` cancels every in-flight record and returns their ids."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    records = [
        _make_record("w-1", WorkerLifecycleState.RUNNING),
        _make_record("w-2", WorkerLifecycleState.READY),
    ]
    manager.store.list_all = MagicMock(return_value=records)
    manager.cancel = MagicMock(return_value=True)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_close_all())
    assert out == {"closed": ["w-1", "w-2"]}
    assert manager.cancel.call_count == 2
    manager.cancel.assert_any_call("w-1", signal="soft", grace_ms=5_000)
    manager.cancel.assert_any_call("w-2", signal="soft", grace_ms=5_000)


def test_worker_health_aggregates_state_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """``worker_health`` returns ``{"total": int, "counts": {state: int}}`` for every state."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    records = [
        _make_record("w-1", WorkerLifecycleState.READY),
        _make_record("w-2", WorkerLifecycleState.READY),
        _make_record("w-3", WorkerLifecycleState.RUNNING),
    ]
    manager.store.list_all = MagicMock(return_value=records)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_health())
    assert out["total"] == 3
    assert out["counts"]["ready"] == 2
    assert out["counts"]["running"] == 1
    # Every WorkerLifecycleState value must appear in counts (zero default).
    for state in WorkerLifecycleState:
        assert state.value in out["counts"]
