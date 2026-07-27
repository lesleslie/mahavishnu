"""Tests for worker_tools.worker_collect_results incremental-output path.

The durable-worker contract (F1, F20) extends ``worker_collect_results``
with optional ``since_offset`` pagination. The current flat-dict return
shape (``{wid: {...}}``) is replaced with an envelope
(``{"workers": {wid: {...}}}``) so the wire format stays explicit about
its contents. Uses real ``CapturedOutput`` dataclass instances so type
mismatches surface (Task 19's reviewer caught exactly that pattern).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.contract.tmux_adapter import CapturedOutput

pytestmark = pytest.mark.unit


def test_worker_collect_results_returns_envelope_with_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Durable path returns ``{"workers": {wid: {text, next_offset}}}`` envelope."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    captured = CapturedOutput(text="hello", next_offset=5, truncated=False, pane_alive=True)
    manager.capture_output = MagicMock(return_value=captured)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_collect_results(["w-1"], since_offset=0))
    assert out == {
        "workers": {
            "w-1": {
                "text": "hello",
                "next_offset": 5,
                "truncated": False,
                "pane_alive": True,
            }
        }
    }
    manager.capture_output.assert_called_once_with("w-1", since_offset=0)


def test_worker_collect_results_empty_workers_returns_empty_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty worker_ids list returns ``{"workers": {}}`` (no exception)."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    manager.capture_output = MagicMock()  # never called
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)

    out = asyncio.run(worker_tools.worker_collect_results([], since_offset=0))
    assert out == {"workers": {}}
    manager.capture_output.assert_not_called()


def test_worker_collect_results_passes_since_offset_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """since_offset is forwarded to capture_output verbatim (pagination)."""
    from mahavishnu.mcp.tools import worker_tools

    manager = MagicMock()
    captured = CapturedOutput(text="more", next_offset=2048, truncated=True, pane_alive=True)
    manager.capture_output = MagicMock(return_value=captured)
    monkeypatch.setattr(worker_tools, "_durable_manager", manager)
    monkeypatch.setattr(worker_tools, "_worker_manager", None)

    out = asyncio.run(worker_tools.worker_collect_results(["w-1", "w-2"], since_offset=1024))
    assert set(out["workers"]) == {"w-1", "w-2"}
    assert manager.capture_output.call_count == 2
    for call in manager.capture_output.call_args_list:
        assert call.kwargs["since_offset"] == 1024
