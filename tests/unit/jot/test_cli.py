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
    cmd_add,
    cmd_done,
    cmd_edit,
    cmd_list,
    cmd_reopen,
    cmd_search,
    cmd_show,
    cmd_vitals,
)
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.fold import parse_events
from mahavishnu.jot.paths import log_path as default_log_path


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


def test_cmd_done_marks_done(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "x", wall_ms=1)])
    cmd_done(handle="a" * 6)
    out = capsys.readouterr().out
    assert "done: a" in out  # short_id of the id
    events = parse_events(default_log_path())
    assert len(events) == 2
    assert events[1].op == "done"


def test_cmd_done_noop_when_already_done(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("a" * 32, "x", wall_ms=1),
        JotEvent(
            id="a" * 32, op="done",
            hlc=HLC(wall_ms=2, ctr=0, node="a" * 8),
            text="", ctx={}, created_ms=2,
        ),
    ])
    cmd_done(handle="a" * 6)
    events = parse_events(default_log_path())
    assert len(events) == 2  # no new event written


def test_cmd_reopen_marks_open(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("a" * 32, "x", wall_ms=1),
        JotEvent(
            id="a" * 32, op="done",
            hlc=HLC(wall_ms=2, ctr=0, node="a" * 8),
            text="", ctx={}, created_ms=2,
        ),
    ])
    cmd_reopen(handle="a" * 6)
    events = parse_events(default_log_path())
    assert events[-1].op == "reopen"


def test_cmd_edit_writes_edit_event(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "v1", wall_ms=1)])
    cmd_edit(handle="a" * 6, new_text="v2")
    events = parse_events(default_log_path())
    assert events[-1].op == "edit"
    assert events[-1].text == "v2"


def test_cmd_add_writes_capture_event(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _redirect_to_tmp(monkeypatch, tmp_path)
    cmd_add(text="new jot")
    events = parse_events(default_log_path())
    assert len(events) == 1
    assert events[0].op == "capture"
    assert events[0].text == "new jot"


def test_cmd_done_ambiguous_handle_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two captures with overlapping handle substrings.
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("f9c2" + "a" * 28, "first", wall_ms=1),
        _capture("0" * 26 + "f9c2", "second", wall_ms=2),
    ])
    with pytest.raises(SystemExit) as exc_info:
        cmd_done(handle="f9c2")
    assert exc_info.value.code == 1


def test_cmd_search_lexical_substring_match(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Session-Buddy in tests — falls back to lexical substring match."""
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("a" * 32, "refactor fold", wall_ms=1),
        _capture("b" * 32, "investigate redaction", wall_ms=2),
    ])
    cmd_search(query="fold", limit=20)
    out = capsys.readouterr().out
    assert "refactor fold" in out
    assert "investigate redaction" not in out


def test_cmd_search_respects_limit(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture(f"{i:032x}", f"match {i}", wall_ms=i) for i in range(5)
    ])
    cmd_search(query="match", limit=2)
    out_lines = capsys.readouterr().out.splitlines()
    assert len(out_lines) == 2


def test_cmd_search_no_results_prints_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "hello", wall_ms=1)])
    cmd_search(query="nonexistent", limit=20)
    assert capsys.readouterr().out == ""


def test_cmd_done_actually_transitions_state(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: cmd_done must transition state, not just emit an event."""
    from mahavishnu.jot.fold import build_states, parse_events
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "hello", wall_ms=1)])
    cmd_done(handle="a" * 6)
    # After cmd_done, the state should actually be "done"
    result = build_states(parse_events(default_log_path()), enrich=False)
    assert len(result.states) == 1
    assert result.states[0].status == "done"
    assert result.errors == []  # No orphans!
    assert result.parked == []  # No parking!


def test_cmd_reopen_actually_transitions_state(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: cmd_reopen must transition state, not just emit an event."""
    from mahavishnu.jot.fold import build_states, parse_events
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [
        _capture("a" * 32, "hello", wall_ms=1),
        JotEvent(
            id="a" * 32, op="done",
            hlc=HLC(wall_ms=2, ctr=0, node="a" * 8),
            text="", ctx={}, created_ms=2,
        ),
    ])
    cmd_reopen(handle="a" * 6)
    result = build_states(parse_events(default_log_path()), enrich=False)
    assert len(result.states) == 1
    assert result.states[0].status == "open"
    assert result.errors == []
    assert result.parked == []


def test_cmd_edit_actually_transitions_text(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: cmd_edit must update the JotSummary text, not just emit."""
    from mahavishnu.jot.fold import build_states, parse_events
    jot = _redirect_to_tmp(monkeypatch, tmp_path)
    _seed_log(jot, [_capture("a" * 32, "v1", wall_ms=1)])
    cmd_edit(handle="a" * 6, new_text="v2")
    result = build_states(parse_events(default_log_path()), enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "v2"
    assert result.errors == []
    assert result.parked == []


from typer.testing import CliRunner

from mahavishnu.cli.jot_cli import app as jot_app


def test_typer_app_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(jot_app, ["--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "show" in result.output
    assert "add" in result.output
    assert "edit" in result.output
    assert "done" in result.output
    assert "reopen" in result.output
    assert "vitals" in result.output
    assert "search" in result.output


def test_typer_app_has_no_install_hook() -> None:
    """R2 — install-hook moved to plugin manifest."""
    runner = CliRunner()
    result = runner.invoke(jot_app, ["--help"])
    assert "install-hook" not in result.output