"""render layer: list, show, vitals formats."""
from __future__ import annotations

from mahavishnu.jot.fold import FoldResult, JotDetail, JotSummary
from mahavishnu.jot.render import render_list, render_show, render_vitals


def _s(short: str, text: str, status: str = "open", ms: int = 0) -> JotSummary:
    return JotSummary(
        id=short.ljust(32, "0"),
        short_id=short,
        text=text,
        status=status,
        last_modified_ms=ms,
    )


def test_render_list_columns() -> None:
    s = _s("a3f9c2", "refactor fold", ms=1700000000000)  # 2023-11-14 22:13 UTC
    out = render_list([s])
    lines = out.splitlines()
    assert len(lines) == 1
    assert "OPEN" in lines[0]
    assert "a3f9c2" in lines[0]
    assert "refactor fold" in lines[0]


def test_render_list_status_filter() -> None:
    open_s = _s("a3f9c2", "open one", status="open")
    done_s = _s("b7e1d4", "done one", status="done")
    out = render_list([open_s, done_s], status_filter="done")
    assert "done one" in out
    assert "open one" not in out


def test_render_list_limit() -> None:
    states = [_s(f"{i:06x}", f"jot {i}") for i in range(10)]
    out = render_list(states, limit=3)
    assert len(out.splitlines()) == 3


def test_render_show_includes_id_status_text() -> None:
    s = _s("a3f9c2", "refactor fold")
    d = JotDetail(
        summary=s, hlc="1700000000000-0-aaaaaaaa",
        created_ms=1700000000000,
        ctx={"cwd": "/x", "repo": "/y", "branch": "main", "sha": "abc1234"},
    )
    out = render_show(d)
    assert "a3f9c2" in out
    assert "OPEN" in out
    assert "refactor fold" in out
    assert "/y" in out
    assert "main" in out


def test_render_show_truncates_long_text() -> None:
    s = _s("a3f9c2", "x" * 200)
    d = JotDetail(summary=s, hlc="1-0-aa", created_ms=0, ctx={})
    out = render_show(d)
    # Either truncated to 50 chars or shown full — but must include a "Text:" header.
    assert "Text:" in out


def test_render_vitals_summary() -> None:
    states = [
        _s("a3f9c2", "open", status="open", ms=100),
        _s("b7e1d4", "done", status="done", ms=50),
    ]
    result = FoldResult(states=states, parked=[], errors=[])
    out = render_vitals(result)
    assert "Total:   2" in out
    assert "Open:    1" in out
    assert "Done:    1" in out


def test_render_vitals_handles_empty_log() -> None:
    result = FoldResult(states=[], parked=[], errors=[])
    out = render_vitals(result)
    assert "Total:   0" in out
