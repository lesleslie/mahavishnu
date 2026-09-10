"""Fold layer: FoldResult dataclass + parse_events (I/O only) + build_states."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.jot.events import HLC, JotEvent
from mahavishnu.jot.fold import FoldResult, JotSummary, build_states, parse_events

if TYPE_CHECKING:
    from pathlib import Path


def test_fold_result_is_a_dataclass_with_three_fields() -> None:
    """TD-B3: orphan/parked/errors are observable, not silently dropped."""
    result = FoldResult(states=[], parked=[], errors=[])
    assert hasattr(result, "states")
    assert hasattr(result, "parked")
    assert hasattr(result, "errors")


def test_jot_summary_has_five_fields_per_r9() -> None:
    """R9 — list view: id, short_id, text, status, last_modified_ms."""
    s = JotSummary(
        id="a" * 32,
        short_id="a" * 6,
        text="hello",
        status="open",
        last_modified_ms=1234,
    )
    assert s.id == "a" * 32
    assert s.short_id == "a" * 6
    assert s.text == "hello"
    assert s.status == "open"
    assert s.last_modified_ms == 1234


def test_jot_summary_is_frozen() -> None:
    s = JotSummary(
        id="a" * 32, short_id="a" * 6, text="x", status="open", last_modified_ms=0
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        s.text = "y"  # type: ignore[misc]


def test_parse_events_returns_empty_list_for_missing_log(tmp_path: Path) -> None:
    assert parse_events(tmp_path / "nope.jsonl") == []


def test_parse_events_skips_malformed_lines(tmp_path: Path) -> None:
    """JotParseError is logged, not raised — fold is fail-open on lines."""
    log = tmp_path / "log.jsonl"
    good = JotEvent(
        id="a" * 32, op="capture",
        hlc=HLC(wall_ms=1, ctr=0, node="a" * 8),
        text="ok", ctx={}, created_ms=1,
    )
    from mahavishnu.jot.events import serialize
    log.write_text(serialize(good) + "\n{this is not json}\n")
    events = parse_events(log)
    assert len(events) == 1
    assert events[0].id == "a" * 32


def test_parse_events_returns_events_in_file_order(tmp_path: Path) -> None:
    """Fold sorts later; parse_events preserves file order (caller's job)."""
    from mahavishnu.jot.events import serialize
    log = tmp_path / "log.jsonl"
    evs = [
        JotEvent(
            id=f"{i:032x}", op="capture",
            hlc=HLC(wall_ms=i, ctr=0, node="a" * 8),
            text=f"t{i}", ctx={}, created_ms=i,
        )
        for i in range(3)
    ]
    log.write_text("".join(serialize(e) + "\n" for e in evs))
    parsed = parse_events(log)
    assert [e.text for e in parsed] == ["t0", "t1", "t2"]


def test_parse_events_raises_log_corrupt_on_unreadable_file(tmp_path: Path) -> None:
    """JotLogCorruptError for unreadable (vs unparseable) log."""
    from mahavishnu.jot.errors import JotLogCorruptError
    # Directory instead of file -> read_text raises IsADirectoryError
    with pytest.raises(JotLogCorruptError):
        parse_events(tmp_path)  # tmp_path is a directory


def _event(event_id: str, op: str, text: str, wall_ms: int, created_ms: int | None = None) -> JotEvent:
    return JotEvent(
        id=event_id, op=op,
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text, ctx={}, created_ms=created_ms if created_ms is not None else wall_ms,
    )


def test_build_states_handles_single_capture(tmp_path: Path) -> None:
    e = _event("a" * 32, "capture", "hello", wall_ms=1)
    result = build_states([e], enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "hello"
    assert result.states[0].status == "open"


def test_build_states_applies_edit_over_capture(tmp_path: Path) -> None:
    """Latest edit wins; last_modified_ms reflects the edit's HLC."""
    cap = _event("a" * 32, "capture", "v1", wall_ms=1)
    edit = _event("a" * 32, "edit", "v2", wall_ms=2)
    result = build_states([cap, edit], enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "v2"
    assert result.states[0].last_modified_ms == 2


def test_build_states_applies_done(tmp_path: Path) -> None:
    cap = _event("a" * 32, "capture", "x", wall_ms=1)
    done = _event("a" * 32, "done", "", wall_ms=2)
    result = build_states([cap, done], enrich=False)
    assert result.states[0].status == "done"


def test_build_states_applies_reopen(tmp_path: Path) -> None:
    cap = _event("a" * 32, "capture", "x", wall_ms=1)
    done = _event("a" * 32, "done", "", wall_ms=2)
    reopen = _event("a" * 32, "reopen", "", wall_ms=3)
    result = build_states([cap, done, reopen], enrich=False)
    assert result.states[0].status == "open"


def test_build_states_done_then_done_is_noop(tmp_path: Path) -> None:
    cap = _event("a" * 32, "capture", "x", wall_ms=1)
    done1 = _event("a" * 32, "done", "", wall_ms=2)
    done2 = _event("a" * 32, "done", "", wall_ms=3)
    result = build_states([cap, done1, done2], enrich=False)
    assert result.states[0].status == "done"


def test_build_states_short_id_is_last_six_chars() -> None:
    """UD5 — short_id is event_id[-6:], not [6:6]."""
    e = _event("0123456789abcdef0123456789abcdef", "capture", "x", wall_ms=1)
    result = build_states([e], enrich=False)
    assert result.states[0].short_id == "abcdef"


def test_build_states_sorts_by_last_modified_desc() -> None:
    e1 = _event("1" * 32, "capture", "first", wall_ms=1)
    e2 = _event("2" * 32, "capture", "second", wall_ms=2)
    result = build_states([e1, e2], enrich=False)
    assert [s.text for s in result.states] == ["second", "first"]


def test_build_states_returns_empty_result_for_empty_input() -> None:
    result = build_states([], enrich=False)
    assert result == FoldResult(states=[], parked=[], errors=[])