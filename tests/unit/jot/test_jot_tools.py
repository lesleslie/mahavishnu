"""MCP tools return TypedDicts (R11, TD-B1, TD-H5)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

from mahavishnu.jot import hlc as hlc_module
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.fold import build_states, parse_events
from mahavishnu.jot.paths import log_path as default_log_path

# Load jot_tools directly to bypass mahavishnu/mcp/tools/__init__.py (which
# currently imports sibling WIP modules that aren't on disk). Direct file
# import avoids triggering the broken __init__.py while still exercising
# the module's full top-level wrapper code.
_jot_tools_path = Path(__file__).resolve().parents[3] / "mahavishnu" / "mcp" / "tools" / "jot_tools.py"
_spec = importlib.util.spec_from_file_location("jot_tools_under_test", _jot_tools_path)
jot_tools = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = jot_tools
_spec.loader.exec_module(jot_tools)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _redirect_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Redirect jot files to tmp_path and seed a fixed node ID.

    Mirrors the `_redirect_to_tmp` helper in test_cli.py so the brief's
    test bodies (which call ``default_log_path()`` directly) operate on
    a sandboxed directory instead of polluting ~/.mahavishnu/jot/.
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hlc_module._node = None  # ensure get_node() re-reads after redirect
    jot = tmp_path / ".mahavishnu" / "jot"
    jot.mkdir(parents=True, exist_ok=True)
    (jot / "node").write_text("a" * 8)


def _seed(events: list[JotEvent]) -> None:
    log = default_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(serialize(e) + "\n" for e in events))


def _capture(event_id: str, text: str, wall_ms: int) -> JotEvent:
    return JotEvent(
        id=event_id.ljust(32, "0"), op="capture",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text, ctx={}, created_ms=wall_ms,
    )


def test_jot_list_returns_list_of_typed_dicts(tmp_path: Path) -> None:
    _seed([_capture("a" * 32, "x", wall_ms=1)])
    result = jot_tools.jot_list.fn(status=None, limit=50)  # access underlying fn
    assert isinstance(result, list)
    assert isinstance(result[0], dict)
    assert set(result[0].keys()) >= {"id", "short_id", "text", "status", "last_modified_ms"}


def test_jot_show_returns_typed_dict_with_ctx(tmp_path: Path) -> None:
    _seed([_capture("a" * 32, "hello", wall_ms=1)])
    result = jot_tools.jot_show.fn(handle="a" * 6)
    assert "ctx" in result
    assert "hlc" in result


def test_jot_add_writes_capture_event(tmp_path: Path) -> None:
    jot_tools.jot_add.fn(text="new jot")
    events = parse_events(default_log_path())
    assert events[-1].op == "capture"
    assert events[-1].text == "new jot"


def test_jot_vitals_returns_counts(tmp_path: Path) -> None:
    # Brief's body seeds two captures; we additionally append a done event
    # for the second jot so the fold transitions one to "done" — otherwise
    # both captures remain status="open" and the assertion below fails.
    _seed([
        _capture("a" * 32, "open", wall_ms=1),
        _capture("b" * 32, "done", wall_ms=2),
        JotEvent(
            id="b" * 32, op="done",
            hlc=HLC(wall_ms=3, ctr=0, node="a" * 8),
            text="", ctx={}, created_ms=3,
        ),
    ])
    result = jot_tools.jot_vitals.fn()
    assert result["total"] == 2
    assert result["open"] == 1
    assert result["done"] == 1


def test_jot_search_returns_substring_matches(tmp_path: Path) -> None:
    _seed([
        _capture("a" * 32, "refactor fold", wall_ms=1),
        _capture("b" * 32, "investigate", wall_ms=2),
    ])
    result = jot_tools.jot_search.fn(query="fold", limit=20)
    assert len(result) == 1
    assert "refactor" in result[0]["text"]


def test_jot_edit_done_reopen_round_trip(tmp_path: Path) -> None:
    _seed([_capture("a" * 32, "v1", wall_ms=1)])
    jot_tools.jot_edit.fn(handle="a" * 6, new_text="v2")
    jot_tools.jot_done.fn(handle="a" * 6)
    jot_tools.jot_reopen.fn(handle="a" * 6)
    events = parse_events(default_log_path())
    assert [e.op for e in events] == ["capture", "edit", "done", "reopen"]
    result = build_states(events, enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "v2"
    assert result.states[0].status == "open"
    assert result.errors == []
    assert result.parked == []


def test_jot_vitals_preserves_epoch_zero_oldest_ms(tmp_path: Path) -> None:
    """Final-review #1: `or None` collapsed legitimate 0 to None.

    A state with ``last_modified_ms=0`` (epoch) is a legitimate data point,
    not "missing" — vitals must preserve it.
    """
    _seed([
        _capture("a" * 32, "epoch jot", wall_ms=0),
        _capture("b" * 32, "later", wall_ms=1),
    ])
    result = jot_tools.jot_vitals.fn()
    assert result["oldest_ms"] == 0
    assert result["last_capture_ms"] == 1


def test_jot_vitals_returns_none_when_no_states(tmp_path: Path) -> None:
    """When the log has no captured states, oldest_ms and last_capture_ms are None."""
    _seed([])
    result = jot_tools.jot_vitals.fn()
    assert result["total"] == 0
    assert result["oldest_ms"] is None
    assert result["last_capture_ms"] is None