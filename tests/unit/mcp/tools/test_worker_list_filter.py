"""Unit tests for ``mahavishnu.mcp.tools.worker_tools.worker_list`` filtering.

The durable-worker contract (F1) extends ``worker_list`` with optional
``state`` and ``worker_id`` filters. When the durable manager is
configured the tool reads from ``_durable_manager.store.list_all()`` and
projects each record to ``{"worker_id": ..., "state": ...}``. When the
durable manager is not configured the tool falls back to the legacy
``worker_manager.list_workers()`` path so existing callers stay green.

The test follows the ``_StubMCP`` convention used in
``tests/unit/mcp/tools/test_worker_tools.py``: a stub FastMCP captures
each registered tool by name, and tests invoke the registered callable
directly with mocked dependencies. ``worker_list`` is kept inline
inside ``register_worker_tools`` per the FastMCP decorator contract.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState
from mahavishnu.workers.contract.store import WorkerRecordStore

if TYPE_CHECKING:
    import pathlib

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


def _make_record(worker_id: str, state: WorkerLifecycleState) -> DurableWorkerRecord:
    """Build a real DurableWorkerRecord for filter tests.

    Uses real Pydantic records (not MagicMock) so the test catches
    real type mismatches like ``r.state.value`` (DurableWorkerRecord
    uses ``use_enum_values=True``, so ``r.state`` is already a string).
    """
    now = dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session=worker_id, window="@0", pane="%0"),
        state=state,
        created_at=now,
        last_seen_at=now,
    )


def test_worker_list_filters_by_state(tmp_path: pathlib.Path) -> None:
    """``state='ready'`` keeps only records whose state matches."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    manager = MagicMock()
    manager.store = WorkerRecordStore(tmp_path)
    manager.store.put(_make_record("w-1", WorkerLifecycleState.READY))
    manager.store.put(_make_record("w-2", WorkerLifecycleState.RUNNING))

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=MagicMock(), durable_manager=manager)

    fn = stub.tools["worker_list"]
    out = asyncio.run(fn(state="ready"))
    assert out == [{"worker_id": "w-1", "state": "ready"}]


def test_worker_list_filters_by_worker_id(tmp_path: pathlib.Path) -> None:
    """``worker_id='w-2'`` keeps only the record with the matching id."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    manager = MagicMock()
    manager.store = WorkerRecordStore(tmp_path)
    manager.store.put(_make_record("w-1", WorkerLifecycleState.READY))
    manager.store.put(_make_record("w-2", WorkerLifecycleState.RUNNING))

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=MagicMock(), durable_manager=manager)

    fn = stub.tools["worker_list"]
    out = asyncio.run(fn(worker_id="w-2"))
    assert out == [{"worker_id": "w-2", "state": "running"}]


def test_worker_list_combined_state_and_worker_id_filters(
    tmp_path: pathlib.Path,
) -> None:
    """``state`` AND ``worker_id`` filters compose; both must match."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    manager = MagicMock()
    manager.store = WorkerRecordStore(tmp_path)
    # WorkerRecordStore.put keys by worker_id, so use distinct ids.
    manager.store.put(_make_record("w-1", WorkerLifecycleState.READY))
    manager.store.put(_make_record("w-2", WorkerLifecycleState.READY))
    manager.store.put(_make_record("w-3", WorkerLifecycleState.RUNNING))

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=MagicMock(), durable_manager=manager)

    fn = stub.tools["worker_list"]
    out = asyncio.run(fn(state="ready", worker_id="w-2"))
    assert out == [{"worker_id": "w-2", "state": "ready"}]


def test_worker_list_no_filter_returns_all_records() -> None:
    """No filters returns every record from the durable store."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    manager = MagicMock()
    ready = _make_record("w-1", "ready")
    running = _make_record("w-2", "running")
    manager.store.list_all = MagicMock(return_value=[ready, running])

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=MagicMock(), durable_manager=manager)

    fn = stub.tools["worker_list"]
    out = asyncio.run(fn())
    assert out == [
        {"worker_id": "w-1", "state": "ready"},
        {"worker_id": "w-2", "state": "running"},
    ]


def test_worker_list_no_durable_falls_back_to_legacy_manager() -> None:
    """Without a durable manager, ``worker_list`` delegates to the legacy manager."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    legacy = MagicMock()
    legacy.list_workers = AsyncMock(
        return_value=[
            {"worker_id": "w_1", "worker_type": "terminal-claude"},
            {"worker_id": "w_2", "worker_type": "terminal-claude"},
        ]
    )

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=legacy, durable_manager=None)

    fn = stub.tools["worker_list"]
    out = asyncio.run(fn())
    assert out == [
        {"worker_id": "w_1", "worker_type": "terminal-claude"},
        {"worker_id": "w_2", "worker_type": "terminal-claude"},
    ]
    legacy.list_workers.assert_awaited_once()
    # The durable path must not be touched when the durable manager is absent.
    assert not hasattr(stub, "_durable_manager") or stub._durable_manager is None


def test_worker_list_filter_mismatch_returns_empty() -> None:
    """A filter that matches no records returns an empty list."""
    from mahavishnu.mcp.tools.worker_tools import register_worker_tools

    manager = MagicMock()
    manager.store.list_all = MagicMock(return_value=[_make_record("w-1", "ready")])

    stub = _StubMCP()
    register_worker_tools(stub, worker_manager=MagicMock(), durable_manager=manager)

    fn = stub.tools["worker_list"]
    assert asyncio.run(fn(state="failed")) == []
    assert asyncio.run(fn(worker_id="w-missing")) == []
