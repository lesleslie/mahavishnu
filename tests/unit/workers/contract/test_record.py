from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from mahavishnu.workers.contract.record import (
    DurableWorkerRecord,
    TmuxTarget,
)
from mahavishnu.workers.contract.state import WorkerLifecycleState


def _sample_kwargs() -> dict:
    return dict(
        worker_id="worker-abc",
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(
            socket="/tmp/mahavishnu.sock",
            session="mahavishnu-abc",
            window="worker",
            pane="%7",
        ),
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 5, 0, tzinfo=dt.timezone.utc),
    )


def test_record_roundtrip() -> None:
    rec = DurableWorkerRecord(**_sample_kwargs())
    payload = rec.to_dict()
    rebuilt = DurableWorkerRecord.from_dict(payload)
    assert rebuilt == rec
    assert rebuilt.worker_id == "worker-abc"


def test_record_pane_default_empty_when_no_tmux() -> None:
    rec = DurableWorkerRecord(
        worker_id="worker-xyz",
        worker_type="cloud-runpod",
        backend="runpod_flash",
        tmux=None,
        state=WorkerLifecycleState.READY,
        created_at=dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.timezone.utc),
        last_seen_at=dt.datetime(2026, 7, 26, 10, 5, 0, tzinfo=dt.timezone.utc),
    )
    assert rec.tmux is None
    payload = rec.to_dict()
    assert payload["tmux"] is None


def test_record_rejects_unknown_state() -> None:
    with pytest.raises(ValidationError):
        DurableWorkerRecord(
            **{
                **_sample_kwargs(),
                "state": "not-a-state",
            }
        )
