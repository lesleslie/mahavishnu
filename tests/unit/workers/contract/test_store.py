from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore

if TYPE_CHECKING:
    import pathlib


def _record(
    worker_id: str,
    state: WorkerLifecycleState = WorkerLifecycleState.READY,
) -> DurableWorkerRecord:
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket="/tmp/m.sock",
            session="s",
            window="w",
            pane="%0",
        ),
        state=state,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC),
    )


def test_put_and_get(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    rec = _record("worker-1")
    store.put(rec)
    fetched = store.get("worker-1")
    assert fetched == rec


def test_get_missing_returns_none(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    assert store.get("nope") is None


def test_delete(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    store.delete("worker-1")
    assert store.get("worker-1") is None


def test_list_all(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    store.put(_record("worker-2"))
    ids = sorted(r.worker_id for r in store.list_all())
    assert ids == ["worker-1", "worker-2"]


def test_list_active_excludes_terminal_states(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-ready"))
    store.put(_record("worker-completed", WorkerLifecycleState.COMPLETED))
    store.put(_record("worker-reaped", WorkerLifecycleState.REAPED))
    ids = sorted(r.worker_id for r in store.list_active())
    assert ids == ["worker-ready"]


def test_atomic_write_does_not_leave_temp_files(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("worker-1"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".worker-")]
    assert leftovers == []


def test_directory_created_on_init(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "nested" / "store"
    WorkerRecordStore(target)
    assert target.is_dir()
    assert (target / "index.json").exists() or target.is_dir()


def test_store_permissions(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path / "store")
    store.put(_record("worker-1"))
    assert store.root.stat().st_mode & 0o777 == 0o700
    assert (store.root / "worker-1.json").stat().st_mode & 0o777 == 0o600
