"""Unit tests for mahavishnu.mcp.tools.worker_contract_tools."""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.settle.state_machine import (
    Binding,
    SettleAction,
    SettleRunRecord,
    SettleState,
)
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _tmux_dict() -> dict:
    """Return a plain dict mimicking TmuxTarget.model_dump() output."""
    return {
        "socket": "/tmp/wct.sock",
        "session": "s1",
        "window": "w1",
        "pane": "p1",
        "attach_command": "tmux attach -t s1:1.0",
    }


def _tmux_obj() -> TmuxTarget:
    """Return a real TmuxTarget for tests that need a model instance."""
    return TmuxTarget(
        socket="/tmp/wct.sock",
        session="s1",
        window="w1",
        pane="p1",
        attach_command="tmux attach -t s1:1.0",
    )


def _make_record(
    *,
    worker_id: str = "w-1",
    state: WorkerLifecycleState = WorkerLifecycleState.READY,
    tmux: TmuxTarget | None = None,
    last_seen_at: dt.datetime | None = None,
    created_at: dt.datetime | None = None,
    last_exit_code: int | None = None,
    claude_session: str | None = None,
) -> DurableWorkerRecord:
    """Build a real DurableWorkerRecord for tests."""
    now = dt.datetime.now(dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=tmux,
        state=state,
        created_at=created_at or now,
        last_seen_at=last_seen_at or now,
        last_exit_code=last_exit_code,
        claude_session=claude_session,
    )


def _make_manager_mock() -> MagicMock:
    """Build a MagicMock that mimics DurableWorkerManager."""
    manager = MagicMock()
    manager.spawn = MagicMock()
    manager.send_input = MagicMock(return_value=True)
    manager.capture_output = MagicMock()
    manager.status = MagicMock(return_value=None)
    manager.cancel = MagicMock(return_value=True)
    manager.reap = MagicMock()
    manager.pane_command = MagicMock(return_value="tmux attach -t s1:1.0")
    return manager


def _make_spawn_result(
    *,
    worker_id: str = "w-1",
    state: WorkerLifecycleState = WorkerLifecycleState.READY,
) -> SimpleNamespace:
    """Build a SpawnResult-like SimpleNamespace."""
    record = _make_record(worker_id=worker_id, state=state, tmux=_tmux_obj())
    return SimpleNamespace(worker_id=worker_id, record=record, pane="p1")


def _make_capture_output(
    *,
    text: str = "",
    next_offset: int = 0,
    truncated: bool = False,
    pane_alive: bool = True,
) -> SimpleNamespace:
    """Build a CaptureOutput-like SimpleNamespace."""
    return SimpleNamespace(
        text=text,
        next_offset=next_offset,
        truncated=truncated,
        pane_alive=pane_alive,
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestStripAnsi:
    def test_strips_csi_color_codes(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        text = "\x1B[31mred\x1B[0m text"
        assert tools._strip_ansi(text) == "red text"

    def test_strips_cursor_moves(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        text = "\x1B[2J\x1B[Hhello"
        assert tools._strip_ansi(text) == "hello"

    def test_preserves_plain_text(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        assert tools._strip_ansi("no escapes here") == "no escapes here"

    def test_strips_complex_sequence(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        text = "\x1B[1;36m--type\x1B[0m"
        assert tools._strip_ansi(text) == "--type"


class TestStateValue:
    def test_returns_string_for_enum_value(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        assert tools._state_value(WorkerLifecycleState.READY) == "ready"

    def test_returns_missing_for_none(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        assert tools._state_value(None) == "missing"

    def test_returns_str_for_plain_string(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        assert tools._state_value("custom") == "custom"

    def test_handles_enum_without_string_value(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        # An object without a .value attribute returns str(obj)
        obj = 42
        assert tools._state_value(obj) == "42"


class TestTmuxPayload:
    def test_returns_none_when_no_tmux(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        record = SimpleNamespace(tmux=None)
        assert tools._tmux_payload(record) is None

    def test_returns_dict_via_model_dump(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        record = SimpleNamespace(tmux=_tmux_obj())
        out = tools._tmux_payload(record)
        assert isinstance(out, dict)
        assert out["session"] == "s1"

    def test_returns_dict_directly(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        record = SimpleNamespace(tmux=_tmux_dict())
        out = tools._tmux_payload(record)
        assert isinstance(out, dict)
        assert out["session"] == "s1"

    def test_returns_none_for_non_dict_model_dump(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        # model_dump returns something that isn't a dict (list, etc.)
        class _Odd:
            def model_dump(self) -> list:
                return [1, 2, 3]

        record = SimpleNamespace(tmux=_Odd())
        assert tools._tmux_payload(record) is None


class TestBindingsFromPayload:
    def test_valid_bindings(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        bindings = tools._bindings_from_payload([
            {"path": "a.py", "base": "old"},
            {"path": "b.py"},
        ])
        assert bindings[0].path == "a.py"
        assert bindings[0].base == "old"
        assert bindings[1].path == "b.py"
        assert bindings[1].base == ""

    def test_non_dict_binding_raises(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        with pytest.raises(TypeError, match="must be a dict"):
            tools._bindings_from_payload(["not-a-dict"])  # type: ignore[list-item]

    def test_missing_path_raises(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        with pytest.raises(TypeError, match="path must be a non-empty string"):
            tools._bindings_from_payload([{"base": "x"}])

    def test_empty_path_raises(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        with pytest.raises(TypeError, match="path must be a non-empty string"):
            tools._bindings_from_payload([{"path": "", "base": "x"}])

    def test_non_string_base_raises(self) -> None:
        from mahavishnu.mcp.tools import worker_contract_tools as tools

        with pytest.raises(TypeError, match="base must be a string"):
            tools._bindings_from_payload([{"path": "a.py", "base": 42}])


# ---------------------------------------------------------------------------
# launch_worker
# ---------------------------------------------------------------------------


def test_launch_worker_returns_manager_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.launch_worker(prompt="hi"))
    assert out == {"worker_id": None, "state": "manager_unconfigured"}


def test_launch_worker_returns_no_tmux_when_session_mode_no_tmux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", _make_manager_mock())
    out = asyncio.run(tools.launch_worker(prompt="hi", session_mode="no_tmux"))
    assert out == {"worker_id": None, "state": "no_tmux"}


def test_launch_worker_calls_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.launch_worker(
            prompt="do it",
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )
    )
    assert out["worker_id"] == "w-1"
    assert out["state"] == "ready"
    assert out["pty"] is True
    assert out["session_mode"] == "managed_tmux"
    manager.spawn.assert_called_once()


def test_launch_worker_defaults_command_to_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result())
    monkeypatch.setattr(tools, "_durable_manager", manager)
    asyncio.run(tools.launch_worker(prompt="x"))
    call_kwargs = manager.spawn.call_args.kwargs
    assert call_kwargs["command"] == ["claude"]
    assert call_kwargs["worker_type"] == "terminal-claude"


def test_launch_worker_with_metadata_window_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result())
    monkeypatch.setattr(tools, "_durable_manager", manager)
    asyncio.run(
        tools.launch_worker(prompt="x", metadata={"window_name": "editor"})
    )
    assert manager.spawn.call_args.kwargs["window_name"] == "editor"


def test_launch_worker_with_non_dict_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result())
    monkeypatch.setattr(tools, "_durable_manager", manager)
    # metadata is not a dict → falls back to "main"
    out = asyncio.run(tools.launch_worker(prompt="x", metadata="not-a-dict"))  # type: ignore[arg-type]
    assert out["metadata"] == "not-a-dict"
    assert manager.spawn.call_args.kwargs["window_name"] == "main"


def test_launch_worker_returns_metadata_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result())
    monkeypatch.setattr(tools, "_durable_manager", manager)
    meta = {"k": "v"}
    out = asyncio.run(tools.launch_worker(prompt="x", metadata=meta))
    assert out["metadata"] == meta


def test_launch_worker_returns_empty_metadata_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result())
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.launch_worker(prompt="x"))
    assert out["metadata"] == {}


# ---------------------------------------------------------------------------
# send_input
# ---------------------------------------------------------------------------


def test_send_input_returns_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.send_input("w-1", "hello"))
    assert out == {"accepted": False, "byte_offset": 0}


def test_send_input_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.send_input = MagicMock(return_value=True)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.send_input("w-1", "hello", submit=False))
    assert out["accepted"] is True
    manager.send_input.assert_called_once_with("w-1", "hello", submit=False)


def test_send_input_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.send_input = MagicMock(return_value=False)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.send_input("w-1", "hello"))
    assert out["accepted"] is False


# ---------------------------------------------------------------------------
# capture_output
# ---------------------------------------------------------------------------


def test_capture_output_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.capture_output("w-1"))
    assert out == {
        "worker_id": "w-1",
        "text": "",
        "next_offset": 0,
        "truncated": False,
        "pane_alive": False,
    }


def test_capture_output_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.capture_output = MagicMock(
        return_value=_make_capture_output(text="hello", next_offset=42, truncated=True)
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.capture_output("w-1", since_offset=10, max_bytes=2048, strip_ansi=False)
    )
    assert out["text"] == "hello"
    assert out["next_offset"] == 42
    assert out["truncated"] is True
    assert out["pane_alive"] is True
    manager.capture_output.assert_called_once_with(
        "w-1", since_offset=10, max_bytes=2048
    )


def test_capture_output_strips_ansi_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.capture_output = MagicMock(
        return_value=_make_capture_output(text="\x1B[31mred\x1B[0m text")
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.capture_output("w-1"))
    assert out["text"] == "red text"


def test_capture_output_handles_none_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.capture_output = MagicMock(
        return_value=SimpleNamespace(
            text=None, next_offset=99, truncated=False, pane_alive=True
        )
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.capture_output("w-1"))
    assert out["text"] == ""
    assert out["next_offset"] == 99


def test_capture_output_no_strip_when_text_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.capture_output = MagicMock(return_value=_make_capture_output(text=""))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.capture_output("w-1", strip_ansi=True))
    assert out["text"] == ""


# ---------------------------------------------------------------------------
# worker_status
# ---------------------------------------------------------------------------


def test_workflow_status_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out == {"worker_id": "w-1", "state": "manager_unconfigured"}


def test_workflow_status_returns_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=_make_record(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))

    assert out["worker_id"] == "w-1"
    assert out["state"] == "ready"
    manager.status.assert_called_once_with("w-1")


def test_workflow_status_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=None)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out == {"worker_id": "w-1", "state": "not_found"}


def test_workflow_status_returns_record_with_tmux_and_uptime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    created = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    later = dt.datetime(2026, 1, 1, 0, 5, tzinfo=dt.UTC)
    record = _make_record(
        worker_id="w-1",
        tmux=_tmux_obj(),
        created_at=created,
        last_seen_at=later,
        last_exit_code=0,
        claude_session="sess-1",
    )
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))

    assert out["worker_id"] == "w-1"
    assert out["state"] == "ready"
    assert out["uptime_seconds"] == 300
    assert out["last_activity_iso"] == "2026-01-01T00:05:00+00:00"
    assert out["pane_command"] == "tmux attach -t s1:1.0"
    assert out["exit_code"] == 0
    assert out["claude_session"] == "sess-1"
    assert out["error"] is None
    assert isinstance(out["tmux"], dict)


def test_workflow_status_handles_bad_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    """When dates are missing/malformed, uptime should default to 0 (not crash)."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = SimpleNamespace(
        worker_id="w-1",
        state=WorkerLifecycleState.READY,
        last_seen_at=None,
        created_at=None,
        last_exit_code=None,
        claude_session=None,
        tmux=None,
    )
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["uptime_seconds"] == 0
    assert out["last_activity_iso"] is None


def test_workflow_status_handles_missing_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When dates are missing, subtraction raises AttributeError → uptime=0."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    # Real DurableWorkerRecord: created_at is required, last_seen_at is required.
    # Use record.model_copy to drop both to test the AttributeError path.
    real_record = _make_record(worker_id="w-1")
    record = real_record.model_copy(update={"created_at": None, "last_seen_at": None})
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["uptime_seconds"] == 0
    assert out["last_activity_iso"] is None


def test_workflow_status_handles_malformed_non_datetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed non-datetime ``last_seen_at`` must not crash isoformat.

    Regression test for `docs/followups/2026-09-05-worker-status-isoformat-crash.md`.
    A corrupted record (e.g. last_seen_at deserialised as a string) must
    fall through the same except clause that guards subtraction.
    """
    from datetime import datetime, timezone

    from mahavishnu.mcp.tools import worker_contract_tools as tools

    real_record = _make_record(worker_id="w-1")
    # Replace last_seen_at with a non-datetime value (corrupt record).
    # Subtraction works (str - datetime is fine for the subtraction
    # call to raise TypeError), but isoformat() on a string raises
    # AttributeError. Both paths must be guarded.
    corrupt = real_record.model_copy(
        update={
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_seen_at": "not-a-datetime",
        }
    )
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=corrupt)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    # Both fallback paths engaged: uptime=0 (subtraction raised TypeError),
    # last_activity_iso=None (isoformat would have raised AttributeError).
    assert out["uptime_seconds"] == 0
    assert out["last_activity_iso"] is None


def test_workflow_status_no_pane_command_when_no_tmux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    record = _make_record(worker_id="w-1", tmux=None)
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["pane_command"] is None


def test_workflow_status_pane_command_exception_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If pane_command raises, status call must still succeed with pane_command=None."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.pane_command = MagicMock(side_effect=RuntimeError("boom"))
    record = _make_record(worker_id="w-1", tmux=_tmux_obj())
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["pane_command"] is None


def test_workflow_status_no_pane_command_attr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older manager revisions may not implement pane_command."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    # Delete delete the pane_command attribute
    del manager.pane_command
    record = _make_record(worker_id="w-1", tmux=_tmux_obj())
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_status("w-1"))
    assert out["pane_command"] is None


# ---------------------------------------------------------------------------
# wait_for_state
# ---------------------------------------------------------------------------


def test_wait_for_state_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.wait_for_state("w-1", until_state="ready"))
    assert out == {
        "worker_id": "w-1",
        "state": "manager_unconfigured",
        "elapsed_ms": 0,
    }


def test_wait_for_state_terminates_on_match(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_record(state=WorkerLifecycleState.READY)
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1", until_state="ready", timeout_ms=200, poll_interval_ms=10
        )
    )
    assert out["state"] == "ready"
    assert "timed_out" not in out


def test_wait_for_state_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_record(state=WorkerLifecycleState.RUNNING)
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1",
            until_state="ready",
            timeout_ms=50,
            poll_interval_ms=10,
        )
    )
    assert out["timed_out"] is True
    assert out["state"] == "running"
    assert out["elapsed_ms"] == 50


def test_wait_for_state_record_missing_during_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=None)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1", until_state="ready", timeout_ms=50, poll_interval_ms=10
        )
    )
    assert out["state"] == "missing"


def test_wait_for_state_record_missing_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record disappears mid-poll → state returns 'missing' with elapsed_ms=0."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    # First call returns running, second returns None → bail with state="missing"
    manager.status = MagicMock(
        side_effect=[
            _make_record(state=WorkerLifecycleState.RUNNING),
            None,
        ]
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1", until_state="ready", timeout_ms=300, poll_interval_ms=10
        )
    )
    assert out["state"] == "missing"
    assert out["elapsed_ms"] == 0


def test_wait_for_state_with_output_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    record = _make_record(state=WorkerLifecycleState.READY)
    manager.status = MagicMock(return_value=record)
    capture = _make_capture_output(text="output chunk", next_offset=50)
    manager.capture_output = MagicMock(return_value=capture)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1",
            until_state="ready",
            timeout_ms=200,
            poll_interval_ms=10,
            include_output=True,
        )
    )
    assert "output_during_wait" in out
    # Single-shot match: capture_output might be called once or zero times
    # depending on timing. Either way, the result must be well-formed.
    assert out["state"] == "ready"


def test_wait_for_state_include_output_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.status = MagicMock(
        return_value=_make_record(state=WorkerLifecycleState.READY)
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.wait_for_state(
            "w-1",
            until_state="ready",
            timeout_ms=200,
            poll_interval_ms=10,
            include_output=False,
        )
    )
    assert out["output_during_wait"] is None
    manager.capture_output.assert_not_called()


# ---------------------------------------------------------------------------
# cancel_worker
# ---------------------------------------------------------------------------


def test_cancel_worker_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.cancel_worker("w-1"))
    assert out == {"killed": False, "exit_code": None}


def test_cancel_worker_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.cancel = MagicMock(return_value=True)
    manager.status = MagicMock(return_value=_make_record(last_exit_code=42))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.cancel_worker("w-1", signal="soft", grace_ms=1000))
    assert out["killed"] is True
    assert out["exit_code"] == 42
    manager.cancel.assert_called_once_with("w-1", signal="soft", grace_ms=1000)


def test_cancel_worker_record_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.cancel = MagicMock(return_value=True)
    manager.status = MagicMock(return_value=None)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.cancel_worker("w-1"))
    assert out["killed"] is True
    assert out["exit_code"] is None


def test_cancel_worker_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.cancel = MagicMock(return_value=True)
    manager.status = MagicMock(return_value=_make_record(last_exit_code=-9))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.cancel_worker("w-1", signal="SIGKILL"))
    assert out["exit_code"] == -9


# ---------------------------------------------------------------------------
# worker_revoke
# ---------------------------------------------------------------------------


def test_worker_revoke_unconfigured_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(tools.worker_revoke("w-1"))
    assert out == {"revoked": False, "force": False, "attach_command": None}


def test_worker_revoke_no_force(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    record = _make_record(tmux=_tmux_obj())
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_revoke("w-1"))
    assert out["revoked"] is True
    assert out["force"] is False
    assert out["attach_command"] == "tmux attach -t s1:1.0"
    manager.reap.assert_called_once_with("w-1")
    manager.cancel.assert_not_called()


def test_worker_revoke_force(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    record = _make_record(tmux=_tmux_obj())
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_revoke("w-1", force=True))
    assert out["force"] is True
    manager.cancel.assert_called_once_with("w-1", signal="SIGKILL", grace_ms=1_000)
    manager.reap.assert_not_called()


def test_worker_revoke_no_attach_when_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=None)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_revoke("w-1"))
    assert out["attach_command"] is None


def test_worker_revoke_no_attach_when_tmux_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    record = _make_record(tmux=None)
    manager.status = MagicMock(return_value=record)
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_revoke("w-1"))
    assert out["attach_command"] is None


def test_worker_revoke_no_attach_when_attach_command_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """record.tmux present but attach_command is None — metrics.record_attach NOT called."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    tmux = TmuxTarget(
        socket="/tmp/x.sock",
        session="s",
        window="w",
        pane="p",
        attach_command=None,
    )
    manager = _make_manager_mock()
    manager.status = MagicMock(return_value=_make_record(tmux=tmux))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(tools.worker_revoke("w-1"))
    assert out["attach_command"] is None


# ---------------------------------------------------------------------------
# register_worker_contract_tools
# ---------------------------------------------------------------------------


def test_register_worker_contract_tools_attaches_all_nine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    app = MagicMock()
    manager = _make_manager_mock()
    tools.register_worker_contract_tools(app, manager, settle_dhara=None)
    # 9 tools registered: launch_worker, send_input, capture_output,
    # worker_status, wait_for_state, cancel_worker, worker_revoke,
    # worker_run_with_settle, worker_settle
    assert app.tool.call_count == 9
    # Module globals set
    assert tools._durable_manager is manager
    assert tools._settle_dhara is None


def test_register_worker_contract_tools_with_settle_dhara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    app = MagicMock()
    manager = _make_manager_mock()
    settle_dhara = MagicMock()
    tools.register_worker_contract_tools(app, manager, settle_dhara=settle_dhara)
    assert tools._settle_dhara is settle_dhara


# ---------------------------------------------------------------------------
# worker_run_with_settle
# ---------------------------------------------------------------------------


def _make_settle_record(
    *,
    run_ref: str = "settle-r1",
    worker_id: str = "w-1",
    state: SettleState = SettleState.PROPOSED,
) -> SettleRunRecord:
    now = dt.datetime.now(dt.UTC)
    return SettleRunRecord(
        run_ref=run_ref,
        worker_id=worker_id,
        task_signature="do the task",
        bindings=(Binding(path="a.py", base=""),),
        state=state,
        created_at=now,
        updated_at=now,
    )


def test_worker_run_with_settle_empty_task_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", _make_manager_mock())
    out = asyncio.run(
        tools.worker_run_with_settle("", bindings=[{"path": "a.py", "base": ""}])
    )
    assert out["state"] == "manager_unconfigured"
    assert "task_signature must be a non-empty string" in out["error"]


def test_worker_run_with_settle_non_string_task_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", _make_manager_mock())
    out = asyncio.run(
        tools.worker_run_with_settle(123, bindings=[{"path": "a.py", "base": ""}])  # type: ignore[arg-type]
    )
    assert out["state"] == "manager_unconfigured"


def test_worker_run_with_settle_empty_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", _make_manager_mock())
    out = asyncio.run(tools.worker_run_with_settle("task", bindings=[]))
    assert out["state"] == "manager_unconfigured"
    assert "bindings must be a non-empty list" in out["error"]


def test_worker_run_with_settle_non_list_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", _make_manager_mock())
    out = asyncio.run(tools.worker_run_with_settle("task", bindings="not-a-list"))  # type: ignore[arg-type]
    assert out["state"] == "manager_unconfigured"


def test_worker_run_with_settle_unconfigured_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", None)
    out = asyncio.run(
        tools.worker_run_with_settle("task", bindings=[{"path": "a.py", "base": ""}])
    )
    assert out["state"] == "manager_unconfigured"
    assert out["run_ref"] is None


def test_worker_run_with_settle_invalid_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.worker_run_with_settle("task", bindings=["not-a-dict"])
    )
    assert out["state"] == "invalid_bindings"
    assert "must be a dict" in out["error"]


def test_worker_run_with_settle_binding_missing_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    out = asyncio.run(
        tools.worker_run_with_settle("task", bindings=[{"base": "x"}])
    )
    assert out["state"] == "invalid_bindings"


def test_worker_run_with_settle_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_run_with_settle(
            "task",
            bindings=[{"path": "a.py", "base": "old"}],
            run_ref="settle-fixed",
            worker_id="w-1",
        )
    )
    assert out["run_ref"] == "settle-fixed"
    assert out["worker_id"] == "w-1"
    assert out["state"] == "proposed"
    assert out["bindings"] == ["a.py"]
    assert out["task_signature"] == "task"
    assert "launch" in out


def test_worker_run_with_settle_generates_run_ref_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_run_with_settle(
            "task", bindings=[{"path": "a.py", "base": "old"}]
        )
    )
    assert out["run_ref"].startswith("settle-")
    assert len(out["run_ref"]) == len("settle-") + 12


def test_worker_run_with_settle_worker_id_change_triggers_restamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When launch_worker returns a new worker_id, the record gets re-stamped."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(
        return_value=_make_spawn_result(worker_id="w-new-id")
    )
    monkeypatch.setattr(tools, "_durable_manager", manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_run_with_settle(
            "task",
            bindings=[{"path": "a.py", "base": "old"}],
            worker_id="<pending>",
        )
    )
    assert out["worker_id"] == "w-new-id"


def test_worker_run_with_settle_no_restamp_when_worker_id_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_run_with_settle(
            "task",
            bindings=[{"path": "a.py", "base": "old"}],
            worker_id="w-1",
        )
    )
    assert out["worker_id"] == "w-1"


def test_worker_run_with_settle_passes_command_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    manager = _make_manager_mock()
    manager.spawn = MagicMock(return_value=_make_spawn_result(worker_id="w-1"))
    monkeypatch.setattr(tools, "_durable_manager", manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)
    asyncio.run(
        tools.worker_run_with_settle(
            "task",
            bindings=[{"path": "a.py", "base": "old"}],
            command=["claude"],
            metadata={"window_name": "editor"},
        )
    )
    call_kwargs = manager.spawn.call_args.kwargs
    assert call_kwargs["command"] == ["claude"]
    assert call_kwargs["window_name"] == "editor"


# ---------------------------------------------------------------------------
# worker_settle
# ---------------------------------------------------------------------------


def test_worker_settle_invalid_run_ref_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    out = asyncio.run(tools.worker_settle("", "select"))
    assert out["state"] == "invalid_run_ref"


def test_worker_settle_invalid_run_ref_non_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    out = asyncio.run(tools.worker_settle(123, "select"))  # type: ignore[arg-type]
    assert out["state"] == "invalid_run_ref"


def test_worker_settle_invalid_action(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    out = asyncio.run(tools.worker_settle("r1", "not-a-real-action"))
    assert out["state"] == "invalid_action"
    assert "action must be one of" in out["error"]


def test_worker_settle_record_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_settle_dhara", None)
    # No dead-letter file → load_record returns None
    out = asyncio.run(tools.worker_settle("r-missing", "select"))
    assert out["state"] == "not_found"


def test_worker_settle_select_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.PROPOSED)
    # Patch load_record to return our pre-canned record
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))

    out = asyncio.run(tools.worker_settle("r1", "select", actor="alice"))
    assert out["state"] == "selected"
    assert out["action"] == "select"
    assert "release" in out["legal_next"]


def test_worker_settle_illegal_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trying to apply from PROPOSED (must select first) → SettleTransitionError."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.PROPOSED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_settle(
            "r1",
            "apply",
            bindings_content={"a.py": "new"},
        )
    )
    assert out["state"] == "illegal_transition"
    assert "current_state" in out


def test_worker_settle_apply_missing_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply from SELECTED but bindings_content missing → missing_bindings_content."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(tools.worker_settle("r1", "apply"))
    assert out["state"] == "missing_bindings_content"


def test_worker_settle_apply_empty_bindings_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(tools.worker_settle("r1", "apply", bindings_content={}))
    assert out["state"] == "missing_bindings_content"


def test_worker_settle_apply_non_dict_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    out = asyncio.run(
        tools.worker_settle("r1", "apply", bindings_content="not-a-dict")  # type: ignore[arg-type]
    )
    assert out["state"] == "missing_bindings_content"


# ---------------------------------------------------------------------------
# _apply_merge
# ---------------------------------------------------------------------------


def test_apply_merge_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeResult

    record = _make_settle_record()
    bindings_content = {"a.py": "new content"}
    # Patch merge_three_way to return clean merge
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(
            return_value=MergeResult(merged="merged-clean", conflict_count=0)
        ),
    )
    out = asyncio.run(
        tools._apply_merge(record, bindings_content)
    )
    assert "merged" in out
    assert out["conflict_count"] == 0
    assert out["merged"]["a.py"] == "merged-clean"


def test_apply_merge_with_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeConflictError

    record = _make_settle_record()
    bindings_content = {"a.py": "ours"}
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(
            side_effect=MergeConflictError(
                path="a.py",
                merged="<<<<<<< OURS\nours\n=======\ntheirs\n>>>>>>> THEIRS",
                base="base",
                ours="ours",
                theirs="theirs",
            )
        ),
    )
    out = asyncio.run(tools._apply_merge(record, bindings_content))
    assert out["error"] == "merge_conflict"
    assert out["conflicts"][0]["path"] == "a.py"


def test_apply_merge_with_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeFailureError

    record = _make_settle_record()
    bindings_content = {"a.py": "ours"}
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(side_effect=MergeFailureError("git boom")),
    )
    out = asyncio.run(tools._apply_merge(record, bindings_content))
    assert out["error"] == "merge_failure"
    assert out["failures"][0]["path"] == "a.py"
    assert out["failures"][0]["detail"] == "git boom"


def test_apply_merge_missing_ours_for_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """When bindings_content lacks a path the record has → fatal."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record()
    # bindings_content has nothing for a.py
    bindings_content: dict[str, str] = {}
    out = asyncio.run(tools._apply_merge(record, bindings_content))
    assert out["error"] == "merge_failure"
    assert out["failures"][0]["error"] == "missing_ours"
    assert out["failures"][0]["path"] == "a.py"


def test_apply_merge_uses_base_as_theirs_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When theirs_map lacks the path, theirs defaults to binding.base."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeResult

    now = dt.datetime.now(dt.UTC)
    record = SettleRunRecord(
        run_ref="r1",
        worker_id="w-1",
        task_signature="task",
        bindings=(Binding(path="a.py", base="base-content"),),
        state=SettleState.SELECTED,
        created_at=now,
        updated_at=now,
    )
    bindings_content = {"a.py": "ours"}
    captured: dict = {}

    async def fake_merge(*, base: str, ours: str, theirs: str, label: str):
        captured["base"] = base
        captured["ours"] = ours
        captured["theirs"] = theirs
        captured["label"] = label
        return MergeResult(merged="merged", conflict_count=0)

    monkeypatch.setattr(tools, "merge_three_way", fake_merge)
    out = asyncio.run(tools._apply_merge(record, bindings_content))
    assert captured["theirs"] == "base-content"
    assert captured["base"] == "base-content"
    assert captured["ours"] == "ours"
    assert out["conflict_count"] == 0


def test_apply_merge_passes_theirs_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeResult

    now = dt.datetime.now(dt.UTC)
    record = SettleRunRecord(
        run_ref="r1",
        worker_id="w-1",
        task_signature="task",
        bindings=(Binding(path="a.py", base="base-content"),),
        state=SettleState.SELECTED,
        created_at=now,
        updated_at=now,
    )
    bindings_content = {"a.py": "ours"}
    bindings_theirs = {"a.py": "theirs-content"}
    captured: dict = {}

    async def fake_merge(*, base: str, ours: str, theirs: str, label: str):
        captured["base"] = base
        captured["ours"] = ours
        captured["theirs"] = theirs
        return MergeResult(merged="merged", conflict_count=0)

    monkeypatch.setattr(tools, "merge_three_way", fake_merge)
    asyncio.run(tools._apply_merge(record, bindings_content, theirs=bindings_theirs))
    assert captured["theirs"] == "theirs-content"


# ---------------------------------------------------------------------------
# worker_settle apply path with merge_three_way integration
# ---------------------------------------------------------------------------


def test_worker_settle_apply_merge_conflict_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When apply-merge fails with conflict, state stays unchanged and error returned."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeConflictError

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(
            side_effect=MergeConflictError(
                path="a.py",
                merged="<<<<<<< OURS\nours\n=======\ntheirs\n>>>>>>> THEIRS",
                base="base",
                ours="ours",
                theirs="theirs",
            )
        ),
    )
    out = asyncio.run(
        tools.worker_settle("r1", "apply", bindings_content={"a.py": "ours"})
    )
    assert out["state"] == "merge_conflict"
    assert "conflicts" in out


def test_worker_settle_apply_merge_failure_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeFailureError

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(side_effect=MergeFailureError("git crashed")),
    )
    out = asyncio.run(
        tools.worker_settle("r1", "apply", bindings_content={"a.py": "ours"})
    )
    assert out["state"] == "merge_failure"


def test_worker_settle_apply_merge_missing_ours_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    # bindings_content does NOT contain a.py
    out = asyncio.run(
        tools.worker_settle("r1", "apply", bindings_content={"other.py": "x"})
    )
    assert out["state"] == "merge_failure"


def test_worker_settle_apply_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools
    from mahavishnu.settle.merge import MergeResult

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(
        tools,
        "merge_three_way",
        AsyncMock(
            return_value=MergeResult(merged="merged-clean", conflict_count=0)
        ),
    )
    out = asyncio.run(
        tools.worker_settle(
            "r1",
            "apply",
            bindings_content={"a.py": "ours"},
            actor="bob",
        )
    )
    assert out["state"] == "applied"
    assert "merge" in out


def test_worker_settle_release_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))
    out = asyncio.run(tools.worker_settle("r1", "release"))
    assert out["state"] == "released"


def test_worker_settle_discard_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))
    out = asyncio.run(tools.worker_settle("r1", "discard"))
    assert out["state"] == "discarded"


def test_worker_settle_action_enum_string_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SettleAction(actor_string) works thanks to StrEnum."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.PROPOSED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))
    out = asyncio.run(tools.worker_settle("r1", SettleAction.SELECT.value))
    assert out["state"] == "selected"


def test_worker_settle_response_legal_next_for_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For terminal states, legal_next should be empty list."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.SELECTED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))
    out = asyncio.run(tools.worker_settle("r1", "release"))
    assert out["legal_next"] == []


def test_worker_settle_response_includes_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    record = _make_settle_record(state=SettleState.PROPOSED)
    monkeypatch.setattr(tools, "load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(tools, "_settle_dhara", None)
    monkeypatch.setattr(tools, "persist_transition", AsyncMock(return_value=record))
    out = asyncio.run(tools.worker_settle("r1", "select"))
    assert "transitions" in out
    assert isinstance(out["transitions"], list)
