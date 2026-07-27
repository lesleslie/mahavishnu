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
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force=True escalates to SIGKILL regardless of pane state."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.cancel = MagicMock(return_value=True)
    manager.status = MagicMock(
        return_value=_make_record("w-1", WorkerLifecycleState.REAPED, exit_code=137)
    )
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)

    out = asyncio.run(worker_tools.worker_close("w-1", force=True))
    manager.cancel.assert_called_once_with("w-1", signal="sigkill", grace_ms=0)
    assert out["closed"] is True
    assert out["exit_code"] == 137
