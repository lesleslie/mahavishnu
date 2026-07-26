from __future__ import annotations

import pathlib  # noqa: TC003  (test fixture parameter type only)
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.workers.contract.manager import DurableWorkerManager
from mahavishnu.workers.contract.record import TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


@pytest.fixture
def manager(tmp_path: pathlib.Path) -> DurableWorkerManager:
    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    return DurableWorkerManager(store=store, publisher=publisher, socket_dir=tmp_path / "tmux")


def test_spawn_persists_record_and_emits_event(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
        attach_command="tmux -S x.sock attach -t mvs",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info):
        info = manager.spawn(
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )
    assert info.pane == "%3"
    rec = manager.store.get(info.worker_id)
    assert rec is not None
    assert rec.state == WorkerLifecycleState.READY
    assert rec.tmux is not None
    assert manager.publisher.emit.call_count >= 1
    emitted_topics = [c.args[1] for c in manager.publisher.emit.call_args_list]
    assert "worker.spawned" in emitted_topics
    assert "worker.status_changed" in emitted_topics


def test_status_returns_record(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
    rec = manager.status(info.worker_id)
    assert rec is not None
    assert rec.worker_id == info.worker_id


def test_capture_output_uses_tmux_adapter(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    fake_capture = MagicMock()
    fake_capture.text = "hello"
    fake_capture.next_offset = 5
    fake_capture.truncated = False
    fake_capture.pane_alive = True
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info), \
         patch("mahavishnu.workers.contract.manager.capture_pane", return_value=fake_capture):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
        out = manager.capture_output(info.worker_id, since_offset=0)
    assert out.text == "hello"
    assert out.next_offset == 5


def test_cancel_reaps_when_pane_dead(manager: DurableWorkerManager, tmp_path):
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info), \
         patch("mahavishnu.workers.contract.manager.pane_alive", return_value=False):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
        manager.cancel(info.worker_id, signal="soft", grace_ms=10)
    rec = manager.store.get(info.worker_id)
    assert rec is not None
    assert rec.state in {WorkerLifecycleState.REAPED, WorkerLifecycleState.FAILED}


def test_cancel_on_reaped_record_is_idempotent(
    manager: DurableWorkerManager, tmp_path
) -> None:
    """Second cancel on a REAPED record must return False without raising.

    Catches regressions where the idempotency check is removed and
    the lifecycle state machine raises ValueError on REAPED -> REAPED.
    """
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
    )
    with patch("mahavishnu.workers.contract.manager.create_session", return_value=fake_info), \
         patch("mahavishnu.workers.contract.manager.pane_alive", return_value=False):
        info = manager.spawn(worker_type="terminal-claude", backend="claude_tui", command=["claude"])
        first = manager.cancel(info.worker_id, signal="soft", grace_ms=10)
        second = manager.cancel(info.worker_id, signal="SIGKILL", grace_ms=10)
    assert first is True
    assert second is False
    rec = manager.store.get(info.worker_id)
    assert rec is not None
    assert rec.state == WorkerLifecycleState.REAPED
