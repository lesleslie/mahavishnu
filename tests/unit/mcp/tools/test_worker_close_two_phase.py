"""Tests for worker_tools.worker_close two-phase graceful shutdown.

The durable-worker contract (F1) routes ``worker_close`` through
``DurableWorkerManager.cancel(worker_id, signal=..., grace_ms=...)``.
The two-phase escalation (soft → SIGTERM → SIGKILL) is implemented
in ``manager.py:216-253``. Uses real ``DurableWorkerRecord`` instances
so ``exit_code`` round-trips correctly (Task 19's reviewer caught
the ``r.state.value`` anti-pattern on the same record type).
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.contract.manager import DurableWorkerManager
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore

if TYPE_CHECKING:
    import pathlib

pytestmark = pytest.mark.unit


def _make_record(
    worker_id: str, state: WorkerLifecycleState, exit_code: int = 0
) -> DurableWorkerRecord:
    now = dt.datetime(2026, 7, 27, 10, 0, 0, tzinfo=dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session=worker_id, window="@0", pane="%0"),
        state=state,
        last_exit_code=exit_code,
        created_at=now,
        last_seen_at=now,
    )


def test_worker_close_durable_returns_closed_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable path returns ``{"closed": True, "exit_code": <int>}``."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.cancel = MagicMock(return_value=True)
    manager.status = MagicMock(
        return_value=_make_record("w-1", WorkerLifecycleState.REAPED, exit_code=0)
    )
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_close("w-1"))
    assert out == {"closed": True, "exit_code": 0}
    manager.cancel.assert_called_once_with("w-1", signal="soft", grace_ms=5_000)


def test_worker_close_force_escalates_to_sigkill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """force=True drives the durable manager's SIGKILL branch end-to-end.

    Constructs a real ``DurableWorkerManager`` so the casing bug
    (``"sigkill"`` vs ``"SIGKILL"``) and the grace-window loop are
    exercised through the actual code path. ``pane_alive`` is stubbed
    to stay alive past the grace window so the post-loop SIGKILL branch
    fires; ``tmux._run`` is intercepted to record the kill-pane
    invocation that is the SIGKILL branch's signature.
    """
    from mahavishnu.mcp.tools import worker_tools

    store = WorkerRecordStore(tmp_path)
    publisher = MagicMock()
    manager = DurableWorkerManager(
        store=store, publisher=publisher, socket_dir=tmp_path / "tmux"
    )
    record = _make_record("w-1", WorkerLifecycleState.READY, exit_code=137)
    store.put(record)

    run_calls: list[tuple[str, ...]] = []

    def fake_run(socket: str, *args: str, **kwargs: object) -> MagicMock:
        run_calls.append(args)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    # Stay alive past the grace window so the post-loop SIGKILL branch
    # is the one that fires.
    monkeypatch.setattr(
        "mahavishnu.workers.contract.manager.pane_alive", lambda *a, **k: True
    )
    # Intercept tmux._run so we never shell out and can record calls.
    monkeypatch.setattr("mahavishnu.workers.contract.tmux_adapter._run", fake_run)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_close("w-1", force=True))

    assert out["closed"] is True
    assert out["exit_code"] == 137
    # kill-pane is the differentiating call of the SIGKILL branch.
    assert any("kill-pane" in args for args in run_calls), (
        f"expected kill-pane in tmux._run calls, got {run_calls}"
    )
