"""Smoke tests for the 6 drain CLI handlers (Task 12, spec §3.2).

Each handler must:
  - Import cleanly (sentinel that the signature matches the brief).
  - Exit SystemExit(1) on a bad handle so the CLI surfaces errors cleanly.

Happy-path behaviour is exercised by the unit tests for the underlying
``mahavishnu.jot.drain`` primitives — the CLI handlers are thin wrappers
that resolve the handle and delegate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.jot import hlc as hlc_module
from mahavishnu.jot.cli import (
    cmd_defer,
    cmd_delete,
    cmd_dispatch,
    cmd_drain,
    cmd_resurface,
    cmd_retry,
)
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.paths import log_path as default_log_path


def _redirect_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Path:
    """Redirect Path.home() to tmp_path, seed a fixed node ID, return jot_dir."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hlc_module._node = None
    jot = tmp_path / ".mahavishnu" / "jot"
    jot.mkdir(parents=True, exist_ok=True)
    (jot / "node").write_text("a" * 8)
    return jot


def _capture(event_id: str, text: str, wall_ms: int) -> JotEvent:
    return JotEvent(
        id=event_id.ljust(32, "0"), op="capture",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text, ctx={"cwd": "/x", "session_id": "s"},
        created_ms=wall_ms,
    )


def test_cmd_drain_imports_cleanly() -> None:
    """Sentinel: module-level import must succeed with the brief's signature."""
    assert callable(cmd_drain)


def test_cmd_dispatch_imports_cleanly() -> None:
    assert callable(cmd_dispatch)


def test_cmd_defer_imports_cleanly() -> None:
    assert callable(cmd_defer)


def test_cmd_delete_imports_cleanly() -> None:
    assert callable(cmd_delete)


def test_cmd_retry_imports_cleanly() -> None:
    assert callable(cmd_retry)


def test_cmd_resurface_imports_cleanly() -> None:
    assert callable(cmd_resurface)


# ---------------------------------------------------------------------------
# Bad-args behaviour — each handler must exit SystemExit(1) so the CLI
# surface (Task 13's Typer registration) gets a clean exit code.
# ---------------------------------------------------------------------------


def test_cmd_dispatch_bad_handle_exits_1(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cmd_dispatch(handle="deadbeef")
    assert exc_info.value.code == 1
    assert "error:" in capsys.readouterr().err


def test_cmd_defer_bad_handle_exits_1(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cmd_defer(handle="deadbeef", until_ms=99999999999)
    assert exc_info.value.code == 1


def test_cmd_delete_bad_handle_exits_1(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cmd_delete(handle="deadbeef")
    assert exc_info.value.code == 1


def test_cmd_retry_bad_handle_exits_1(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cmd_retry(handle="deadbeef")
    assert exc_info.value.code == 1


def test_cmd_resurface_invalid_trigger_exits_1(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        cmd_resurface(trigger="not_a_real_trigger", context_text="hello")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Happy-path sanity — exercise cmd_defer / cmd_delete against a captured jot.
# These avoid touching the workflow runtime (cmd_dispatch / cmd_retry would)
# so they don't need Prefect mocking.
# ---------------------------------------------------------------------------


def test_cmd_defer_happy_path_writes_event(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_defer resolves the handle and writes a defer event to the log."""
    from mahavishnu.jot.fold import parse_events

    jot_dir = _redirect_to_tmp(monkeypatch, tmp_path)
    (jot_dir / "log.jsonl").write_text(
        serialize(_capture("a" * 32, "hello", wall_ms=1)) + "\n",
    )
    cmd_defer(handle="a" * 6, until_ms=99999999999999)
    out = capsys.readouterr().out
    assert "deferred:" in out
    events = parse_events(default_log_path())
    assert any(e.op == "defer" for e in events)


def test_cmd_delete_happy_path_writes_event(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_delete resolves the handle and writes a delete event to the log."""
    from mahavishnu.jot.fold import parse_events

    jot_dir = _redirect_to_tmp(monkeypatch, tmp_path)
    (jot_dir / "log.jsonl").write_text(
        serialize(_capture("a" * 32, "hello", wall_ms=1)) + "\n",
    )
    cmd_delete(handle="a" * 6, reason="stale")
    out = capsys.readouterr().out
    assert "deleted:" in out
    events = parse_events(default_log_path())
    assert any(e.op == "delete" for e in events)


def test_cmd_resurface_happy_path_prints_header(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_resurface prints a header even with zero hits (default session_start)."""
    _redirect_to_tmp(monkeypatch, tmp_path)
    cmd_resurface(trigger="session_start", context_text="anything")
    out = capsys.readouterr().out
    assert "# resurface" in out


def test_cmd_drain_happy_path_prints_header(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cmd_drain prints the candidate header (0 hits on empty log)."""
    _redirect_to_tmp(monkeypatch, tmp_path)
    cmd_drain(limit=10)
    out = capsys.readouterr().out
    assert "# drain candidates" in out
