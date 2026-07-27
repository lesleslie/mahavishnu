# tests/integration/workers/contract/test_reconciliation.py
from __future__ import annotations

import datetime as dt
import pathlib
from unittest.mock import MagicMock, patch

from mahavishnu.workers.contract.manager import DurableWorkerManager
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


def test_reconcile_marks_dead_pane_as_reaped(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    manager = DurableWorkerManager(
        store=store,
        publisher=publisher,
        socket_dir=tmp_path / "tmux",
    )
    now = dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc)
    record = DurableWorkerRecord(
        worker_id="w-1",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket=str(tmp_path / "tmux" / "x.sock"),
            session="mvs",
            window="@0",
            pane="%3",
        ),
        state=WorkerLifecycleState.READY,
        created_at=now,
        last_seen_at=now,
    )
    store.put(record)

    with patch(
        "mahavishnu.workers.contract.manager.pane_alive",
        return_value=False,
    ):
        reconciled = manager.reconcile_all()

    assert len(reconciled) == 1
    assert reconciled[0].state == WorkerLifecycleState.REAPED
    topics = [c.args[1] for c in publisher.emit.call_args_list]
    assert "worker.reaped" in topics


def test_reconcile_revives_detached_pane(tmp_path: pathlib.Path):
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    manager = DurableWorkerManager(
        store=store,
        publisher=publisher,
        socket_dir=tmp_path / "tmux",
    )
    now = dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc)
    record = DurableWorkerRecord(
        worker_id="w-1",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket=str(tmp_path / "tmux" / "x.sock"),
            session="mvs",
            window="@0",
            pane="%3",
        ),
        state=WorkerLifecycleState.DETACHED,
        created_at=now,
        last_seen_at=now,
    )
    store.put(record)

    with patch(
        "mahavishnu.workers.contract.manager.pane_alive",
        return_value=True,
    ):
        reconciled = manager.reconcile_all()

    assert len(reconciled) == 1
    assert reconciled[0].state == WorkerLifecycleState.READY
    topics = [c.args[1] for c in publisher.emit.call_args_list]
    assert "worker.attached" in topics
    assert "worker.status_changed" in topics
