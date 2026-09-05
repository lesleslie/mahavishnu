"""Coverage-push tests for workers.contract.store; atomic JSON I/O contract verification."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from collections.abc import Iterator

import pytest

from mahavishnu.workers.contract.record import (
    DurableWorkerRecord,
    TmuxTarget,
)
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore


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


def _write_corrupt_json(path: pathlib.Path, name: str) -> None:
    (path / name).write_text("{ this is not valid json")


# ---------- list_all: empty / present / corrupt ----------

def test_list_all_returns_empty_when_directory_has_no_records(
    tmp_path: pathlib.Path,
) -> None:
    store = WorkerRecordStore(tmp_path)
    assert list(store.list_all()) == []


def test_list_all_yields_valid_records(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    rec = _record("w-1")
    store.put(rec)
    found = list(store.list_all())
    assert found == [rec]


def test_list_all_skips_corrupt_json_and_keeps_valid(
    tmp_path: pathlib.Path,
) -> None:
    store = WorkerRecordStore(tmp_path)
    good = _record("w-good")
    store.put(good)
    _write_corrupt_json(tmp_path, "w-bad.json")
    found = list(store.list_all())
    assert len(found) == 1
    assert found[0] == good


def test_list_all_skips_dot_prefixed_files(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-1"))
    (tmp_path / ".worker-leftover.json").write_text("{}")
    found = list(store.list_all())
    assert [r.worker_id for r in found] == ["w-1"]


# ---------- get: missing / present / corrupt ----------

def test_get_missing_record_returns_none(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    assert store.get("does-not-exist") is None


def test_get_present_record_round_trips(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    rec = _record("w-1")
    store.put(rec)
    assert store.get("w-1") == rec


def test_get_corrupt_json_returns_none(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    _write_corrupt_json(tmp_path, "w-corrupt.json")
    assert store.get("w-corrupt") is None


# ---------- put: new / overwrite / atomic semantics ----------

def test_put_creates_json_file_on_disk(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    rec = _record("w-1")
    store.put(rec)
    target = tmp_path / "w-1.json"
    assert target.exists()
    payload = json.loads(target.read_text())
    assert payload["worker_id"] == "w-1"


def test_put_overwrites_existing_record_atomically(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-1", state=WorkerLifecycleState.READY))

    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src: str, dst: str) -> None:
        replaced.append((os.fspath(src), os.fspath(dst)))
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", spy)

    store.put(_record("w-1", state=WorkerLifecycleState.RUNNING))

    matches = [pair for pair in replaced if pair[1].endswith("w-1.json")]
    assert matches, "expected os.replace call targeting w-1.json"
    for src, dst in matches:
        assert pathlib.Path(src).name.startswith(".worker-")
        assert pathlib.Path(dst).name == "w-1.json"


def test_put_no_dotfile_leftovers_after_success(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-1"))
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_put_applies_0o600_mode_to_record_file(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-1"))
    mode = (tmp_path / "w-1.json").stat().st_mode & 0o777
    assert mode == 0o600


# ---------- delete: missing / present ----------

def test_delete_present_record_removes_file(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-1"))
    target = tmp_path / "w-1.json"
    assert target.exists()
    store.delete("w-1")
    assert not target.exists()


def test_delete_missing_record_is_silent_noop(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(tmp_path)
    store.delete("does-not-exist")  # must not raise


# ---------- constructor accepts str and pathlib.Path ----------

def test_init_accepts_string_path(tmp_path: pathlib.Path) -> None:
    store = WorkerRecordStore(str(tmp_path))
    rec = _record("w-1")
    store.put(rec)
    assert store.get("w-1") == rec


# ---------- list_active: terminal-state exclusion ----------

@pytest.mark.parametrize(
    "terminal_state",
    [
        WorkerLifecycleState.COMPLETED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.REAPED,
    ],
)
def test_list_active_excludes_each_terminal_state(
    tmp_path: pathlib.Path,
    terminal_state: WorkerLifecycleState,
) -> None:
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-active", WorkerLifecycleState.RUNNING))
    store.put(_record("w-terminal", terminal_state))
    active = list(store.list_active())
    assert [r.worker_id for r in active] == ["w-active"]


def test_list_active_iterates_list_all_once(tmp_path: pathlib.Path) -> None:
    """list_active must delegate to list_all() (covers the generator composition)."""
    store = WorkerRecordStore(tmp_path)
    store.put(_record("w-running", WorkerLifecycleState.RUNNING))
    store.put(_record("w-ready", WorkerLifecycleState.READY))
    store.put(_record("w-completed", WorkerLifecycleState.COMPLETED))
    active: Iterator[DurableWorkerRecord] = store.list_active()
    assert isinstance(active, Iterator)
    assert sorted(r.worker_id for r in active) == ["w-ready", "w-running"]
