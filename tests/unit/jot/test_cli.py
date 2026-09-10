"""CLI subcommand handlers (Tasks 8-11).

Tests use the autouse `_reset_module_caches` fixture from
tests/unit/jot/conftest.py plus inline `monkeypatch.setattr(Path, "home")`
to redirect default_log_path() to tmp_path WITHOUT polluting the real
~/.mahavishnu/jot/ directory. Each test additionally creates a fixed
node ID at the redirected node_path so get_node() returns "a" * 8
deterministically (the seed step the brief's "tmp_jot_dir" autouse
fixture was supposed to provide).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.jot import hlc as hlc_module
from mahavishnu.jot.cli import (
    cmd_list,
    cmd_show,
    cmd_vitals,
)
from mahavishnu.jot.events import HLC, JotEvent, serialize


def _redirect_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Path:
    """Redirect Path.home() to tmp_path, seed a fixed node ID, return jot_dir.

    Returns the redirected jot directory so callers can use it if needed.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hlc_module._node = None  # ensure get_node() re-reads after redirect
    jot = tmp_path / ".mahavishnu" / "jot"
    jot.mkdir(parents=True, exist_ok=True)
    # Seed a fixed node ID so get_node() returns "a" * 8 deterministically.
    (jot / "node").write_text("a" * 8)
    return jot


def _seed_log(jot_dir: Path, events: list[JotEvent]) -> None:
    """Seed the redirected tmp_path log with the given events."""
    log = jot_dir / "log.jsonl"
    log.write_text("".join(serialize(e) + "\n" for e in events))


def _capture(event_id: str, text: str, wall_ms: int) -> JotEvent:
    return JotEvent(
        id=event_id.ljust(32, "0"), op="capture",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text, ctx={"cwd": "/x", "session_id": "s"},
        created_ms=wall_ms,
    )


def test_cmd_list_prints_states(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "hello", wall_ms=1)])
    cmd_list(status=None, limit=50)
    captured = capsys.readouterr()
    assert "hello" in captured.out


def test_cmd_list_status_filter_open_only(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("a" * 32, "open one", wall_ms=1),
        JotEvent(
            id="b" * 32, op="done",
            hlc=HLC(wall_ms=2, ctr=0, node="a" * 8),
            text="", ctx={}, created_ms=2,
        ),
    ])
    cmd_list(status="open", limit=50)
    out = capsys.readouterr().out
    assert "open one" in out


def test_cmd_show_resolves_handle(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "hello", wall_ms=1)])
    cmd_show(handle="a" * 6)  # short_id
    out = capsys.readouterr().out
    assert "hello" in out
    assert "OPEN" in out


def test_cmd_show_not_found_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "hello", wall_ms=1)])
    with pytest.raises(SystemExit) as exc_info:
        cmd_show(handle="z9z9z9")
    assert exc_info.value.code == 1


def test_cmd_vitals_prints_counts(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "x", wall_ms=1)])
    cmd_vitals()
    out = capsys.readouterr().out
    assert "Total:   1" in out