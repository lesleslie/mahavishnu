"""Fold layer: FoldResult dataclass + parse_events (I/O only) + build_states."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from mahavishnu.jot.events import HLC, JotEvent
from mahavishnu.jot.fold import FoldResult, JotSummary, build_states, parse_events


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


def _event(
    event_id: str,
    op: str,
    text: str,
    wall_ms: int,
    created_ms: int | None = None,
    ctr: int = 0,
    node: str = "a" * 8,
) -> JotEvent:
    return JotEvent(
        id=event_id, op=op,
        hlc=HLC(wall_ms=wall_ms, ctr=ctr, node=node),
        text=text, ctx={}, created_ms=created_ms if created_ms is not None else wall_ms,
    )


def test_build_states_handles_single_capture() -> None:
    e = _event("a" * 32, "capture", "hello", wall_ms=1)
    result = build_states([e], enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "hello"
    assert result.states[0].status == "open"


def test_build_states_applies_edit_over_capture() -> None:
    """Latest edit wins; last_modified_ms reflects the edit's HLC."""
    cap = _event("a" * 32, "capture", "v1", wall_ms=1)
    edit = _event("a" * 32, "edit", "v2", wall_ms=2)
    result = build_states([cap, edit], enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "v2"
    assert result.states[0].last_modified_ms == 2


def test_build_states_applies_done() -> None:
    cap = _event("a" * 32, "capture", "x", wall_ms=1)
    done = _event("a" * 32, "done", "", wall_ms=2)
    result = build_states([cap, done], enrich=False)
    assert result.states[0].status == "done"


def test_build_states_applies_reopen() -> None:
    cap = _event("a" * 32, "capture", "x", wall_ms=1)
    done = _event("a" * 32, "done", "", wall_ms=2)
    reopen = _event("a" * 32, "reopen", "", wall_ms=3)
    result = build_states([cap, done, reopen], enrich=False)
    assert result.states[0].status == "open"


def test_build_states_done_then_done_is_noop() -> None:
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


def test_build_states_hlc_tiebreak_by_ctr() -> None:
    """UD4: same wall_ms → ctr ascending breaks the tie."""
    earlier = _event("a" * 32, "capture", "ctr0", wall_ms=5, ctr=0)
    later = _event("a" * 32, "edit", "ctr1", wall_ms=5, ctr=1)
    # File order is reversed; HLC sort must place ctr=0 first.
    result = build_states([later, earlier], enrich=False)
    assert result.states[0].text == "ctr1"
    assert result.states[0].last_modified_ms == 5


def test_build_states_hlc_tiebreak_by_node() -> None:
    """UD4: same (wall_ms, ctr) → lex on node."""
    a = _event("a" * 32, "capture", "node-a", wall_ms=5, ctr=0, node="aaaaaaaa")
    b = _event("b" * 32, "capture", "node-b", wall_ms=5, ctr=0, node="bbbbbbbb")
    # Reverse the input order; lex on node places node-a first, then node-b.
    result = build_states([b, a], enrich=False)
    assert [s.text for s in result.states] == ["node-a", "node-b"]


def test_build_states_orphan_edit_lands_in_errors() -> None:
    """Edit with no matching capture (replayed through full log) → errors."""
    orphan = _event("a" * 32, "edit", "v1", wall_ms=1)
    result = build_states([orphan], enrich=False)
    assert result.states == []
    assert result.parked == []
    assert len(result.errors) == 1
    assert result.errors[0].id == "a" * 32


def test_build_states_parked_edit_replay_clamps_last_modified() -> None:
    """Parking replay must clamp last_modified_ms to non-decreasing (R9).

    Edit arrives before capture (parked in pass 1), capture arrives later
    (creates state in pass 1), pass 2 replays edit. State must reflect the
    edit's text but last_modified_ms = max(capture.wall_ms, edit.wall_ms).
    """
    edit = _event("a" * 32, "edit", "v2", wall_ms=2)
    capture = _event("a" * 32, "capture", "v1", wall_ms=5)
    # Both in pass 1: edit is parked (no capture yet); capture creates state.
    # Pass 2: replay edit → text=v2, last_modified_ms = max(5, 2) = 5.
    result = build_states([edit, capture], enrich=False)
    assert len(result.states) == 1
    assert result.states[0].text == "v2"
    assert result.states[0].status == "open"
    assert result.states[0].last_modified_ms == 5
    assert result.parked == []


def test_enrich_ctx_returns_repo_branch_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.jot.fold import _enrich_ctx
    fake = {
        "rev-parse --show-toplevel": "/Users/les/Projects/mahavishnu",
        "rev-parse --abbrev-ref HEAD": "main",
        "rev-parse HEAD": "a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d",
    }

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout=fake[" ".join(args[1:])], stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    enriched = _enrich_ctx({}, Path("/Users/les/Projects/mahavishnu"))
    assert enriched["repo"] == "/Users/les/Projects/mahavishnu"
    assert enriched["branch"] == "main"
    assert enriched["sha"] == "a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d"


def test_enrich_ctx_fail_open_on_git_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from mahavishnu.jot.fold import _enrich_ctx

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    enriched = _enrich_ctx({}, Path("/tmp"))
    assert enriched["repo"] is None
    assert enriched["branch"] is None
    assert enriched["sha"] is None


def test_enrich_ctx_fail_open_on_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """F3: real-world failure mode is non-zero exit (e.g. non-git directory
    → git exits 128), not a raised CalledProcessError. `_git` uses
    `check=False` so subprocess.run returns the result; `_git` then
    constructs and raises CalledProcessError itself. This test stubs the
    real exit-code path, not the impossible "subprocess.run raises"
    path.
    """
    from mahavishnu.jot.fold import _enrich_ctx

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=128, stdout="",
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    enriched = _enrich_ctx({}, Path("/tmp"))
    assert enriched["repo"] is None
    assert enriched["branch"] is None
    assert enriched["sha"] is None


def test_enrich_ctx_fail_open_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """F1: TimeoutExpired (subprocess.run with timeout=5) inherits from
    SubprocessError, NOT from OSError. Widen catch to subprocess.SubprocessError
    so a stalled git (NFS repo, credential prompt, index lock) doesn't take
    down the entire build_states call.
    """
    from mahavishnu.jot.fold import _enrich_ctx

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "git", timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    enriched = _enrich_ctx({}, Path("/tmp"))
    assert enriched["repo"] is None
    assert enriched["branch"] is None
    assert enriched["sha"] is None


def test_enrich_ctx_spawns_three_git_calls_not_per_state() -> None:
    """F2: _enrich_ctx spawns 3 git subprocesses (one per rev-parse) — NOT
    3 per state. Verify the call count is bounded. Integration is tested
    separately in test_build_states_enrich_populates_ctx_by_id which
    asserts the hoisted git_ctx is reused across all states.
    """
    from mahavishnu.jot.fold import _enrich_ctx
    calls: list[tuple[str, ...]] = []

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(args))
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout="/r\n" if "show-toplevel" in args else "x",
            stderr="",
        )

    import unittest.mock
    with unittest.mock.patch.object(subprocess, "run", side_effect=fake_run):
        _enrich_ctx({"cwd": "/x"}, Path("/r"))

    # Exactly 3 git calls regardless of how large the input ctx is.
    assert len(calls) == 3
    assert any("--show-toplevel" in c for c in calls)
    assert any("--abbrev-ref" in c for c in calls)
    assert any(c == ("git", "rev-parse", "HEAD") for c in calls)


def test_enrich_ctx_preserves_existing_keys() -> None:
    from mahavishnu.jot.fold import _enrich_ctx
    enriched = _enrich_ctx({"cwd": "/x", "session_id": "s"}, Path("/x"))
    assert enriched["cwd"] == "/x"
    assert enriched["session_id"] == "s"


def test_build_states_enrich_populates_ctx_by_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """F4 wire-up: enrich=True wires _enrich_ctx output into FoldResult.ctx_by_id.

    Verifies:
    - Original capture ctx keys (cwd, session_id) are preserved.
    - Repo / branch / sha are populated from the git subprocess.
    - With enrich=False (default in tests), ctx_by_id is empty.
    """
    import unittest.mock

    fake = {
        "rev-parse --show-toplevel": "/r",
        "rev-parse --abbrev-ref HEAD": "m",
        "rev-parse HEAD": "abc1234",
    }

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout=fake[" ".join(args[1:])], stderr="",
        )

    cap = _event("a" * 32, "capture", "v1", wall_ms=1)
    cap_with_ctx = JotEvent(
        id=cap.id, op=cap.op, hlc=cap.hlc, text=cap.text,
        ctx={"cwd": "/x", "session_id": "s"},
        created_ms=cap.created_ms,
    )

    with unittest.mock.patch.object(subprocess, "run", side_effect=fake_run):
        result = build_states(
            [cap_with_ctx], enrich=True, current_dir=tmp_path,
        )

    assert result.ctx_by_id[cap.id]["cwd"] == "/x"
    assert result.ctx_by_id[cap.id]["session_id"] == "s"
    assert result.ctx_by_id[cap.id]["repo"] == "/r"
    assert result.ctx_by_id[cap.id]["branch"] == "m"
    assert result.ctx_by_id[cap.id]["sha"] == "abc1234"


def test_build_states_enrich_false_leaves_ctx_by_id_empty() -> None:
    """F4: enrich=False (the default in tests) leaves ctx_by_id empty.

    Per the brief, ctx_by_id is an observability side-channel — only
    populated when the caller explicitly opts in to git subprocess cost.
    """
    cap = _event("a" * 32, "capture", "v1", wall_ms=1)
    result = build_states([cap], enrich=False)
    assert result.ctx_by_id == {}
