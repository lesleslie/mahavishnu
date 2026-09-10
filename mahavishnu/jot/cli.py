"""CLI subcommand handlers — 7 read+write commands (Task 10 adds cmd_search).

Typer wiring lives in mahavishnu/cli/jot_cli.py (Task 11). This module
exposes plain Python functions so the Typer app just delegates.

All handlers:
- Read from `log_path` (default ~/.mahavishnu/jot/log.jsonl via paths.log_path()).
- Emit a single JotEvent back to the log for state-changing commands.
- Print terminal-friendly render to stdout.
- Errors go to stderr + exit 1.

Tests use the `tmp_jot_dir` fixture (sub-plan 1's conftest.py) which
patches `paths.jot_dir()` + `paths.node_path()` + `paths.log_path()` to
return paths under tmp_path, AND seeds a fixed node ID. This makes
`get_node()` return the seeded value without polluting the real node file.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import uuid

from .errors import JotError
from .events import JotEvent, Op, serialize
from .fold import JotDetail, JotSummary, build_states
from .handle import resolve_handle
from .hlc import get_node, hlc_now, read_tail_hlc
from .paths import log_path as default_log_path
from .paths import node_path as _node_path
from .render import render_list, render_show, render_vitals


def _read_log(log_path: Path) -> list[JotEvent]:
    """Read + parse the log. Returns [] when log doesn't exist (OQ2)."""
    from .fold import parse_events
    return parse_events(log_path)


def _write_event(log_path: Path, event: JotEvent) -> None:
    """Append a single event to the log (single os.write call)."""
    line = serialize(event) + "\n"
    fd = os.open(
        str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600,
    )
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _make_event(
    op: Op, text: str, log_path: Path, *, ctx: dict[str, str] | None = None,
) -> JotEvent:
    """Build a JotEvent with HLC continuity from log tail.

    The node ID comes from `get_node(node_path())` — tests rely on the
    `tmp_jot_dir` fixture (sub-plan 1 conftest.py) to make this return a
    fixed value.
    """
    last = read_tail_hlc(log_path)
    node = get_node(_node_path())
    hlc = hlc_now(node, last)
    return JotEvent(
        id=uuid.uuid4().hex,
        op=op,
        hlc=hlc,
        text=text,
        ctx=ctx or {},
        created_ms=hlc.wall_ms,
    )


def cmd_list(
    *,
    log_path: Path | None = None,
    status: str | None = None,
    limit: int = 50,
) -> None:
    """Render the jot list (newest first, optional status filter)."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    print(render_list(result.states, status_filter=status, limit=limit))


def cmd_show(*, log_path: Path | None = None, handle: str) -> None:
    """Render one jot by handle (full ID, short_id, or unambiguous substring)."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(render_show(_detail_from_summary(s, events)))


def cmd_vitals(*, log_path: Path | None = None) -> None:
    """Print total/open/done counts."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    print(render_vitals(result))


def cmd_done(*, log_path: Path | None = None, handle: str) -> None:
    """Mark a jot done (no-op if already done)."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if s.status == "done":
        print(f"already done: {s.short_id}")
        return
    ev = _make_event("done", "", path)
    _write_event(path, ev)
    print(f"done: {s.short_id}")


def cmd_reopen(*, log_path: Path | None = None, handle: str) -> None:
    """Reopen a done jot (no-op if already open)."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if s.status == "open":
        print(f"already open: {s.short_id}")
        return
    ev = _make_event("reopen", "", path)
    _write_event(path, ev)
    print(f"reopened: {s.short_id}")


def cmd_edit(*, log_path: Path | None = None, handle: str, new_text: str) -> None:
    """Edit a jot's text."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    ev = _make_event("edit", new_text, path)
    _write_event(path, ev)
    print(f"edited: {s.short_id}")


def cmd_add(*, log_path: Path | None = None, text: str) -> None:
    """Manually create a jot (alternative to ',,' capture)."""
    path = log_path or default_log_path()
    ev = _make_event("capture", text, path, ctx={"cwd": str(Path.cwd())})
    _write_event(path, ev)
    print(f"added: {ev.id[-6:]}")


# --- helpers ---


def _detail_from_summary(
    s: JotSummary, events: list[JotEvent],
) -> JotDetail:
    """Build a JotDetail from a JotSummary by finding the matching event."""
    capture_ev = next(
        (e for e in events if e.id == s.id and e.op == "capture"),
        None,
    )
    hlc_str = ""
    created_ms = s.last_modified_ms
    ctx: dict[str, str | list[str] | None] = {}
    if capture_ev:
        hlc_str = f"{capture_ev.hlc.wall_ms}-{capture_ev.hlc.ctr}-{capture_ev.hlc.node}"
        created_ms = capture_ev.created_ms
        ctx = dict(capture_ev.ctx) if capture_ev.ctx else {}
    return JotDetail(summary=s, hlc=hlc_str, created_ms=created_ms, ctx=ctx)