"""CLI subcommand handlers — 8 commands mirror the 8 MCP tools (R2).

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

import asyncio
import os
from pathlib import Path
import sys
import time
import uuid

from .errors import JotError
from .events import JotEvent, Op, serialize
from .fold import DispatchState, JotDetail, JotSummary, build_states
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
        str(log_path),
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        0o600,
    )
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _make_event(
    op: Op,
    text: str,
    log_path: Path,
    *,
    ctx: dict[str, str] | None = None,
    event_id: str | None = None,
) -> JotEvent:
    """Build a JotEvent with HLC continuity from log tail.

    The node ID comes from `get_node(node_path())` — tests rely on the
    `tmp_jot_dir` fixture (sub-plan 1 conftest.py) to make this return a
    fixed value.

    ``event_id`` defaults to a fresh uuid (used by ``capture``). Edit/done/
    reopen callers MUST pass the parent jot's id so the fold can associate
    the new event with the existing JotSummary state (R3, R9 — fold by id).
    Without this, the new event is parked and dropped to errors, leaving
    the JotSummary state unchanged — a silent no-op.
    """
    last = read_tail_hlc(log_path)
    node = get_node(_node_path())
    hlc = hlc_now(node, last)
    return JotEvent(
        id=event_id or uuid.uuid4().hex,
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
    ev = _make_event("done", "", path, event_id=s.id)
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
    ev = _make_event("reopen", "", path, event_id=s.id)
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
    ev = _make_event("edit", new_text, path, event_id=s.id)
    _write_event(path, ev)
    print(f"edited: {s.short_id}")


def cmd_add(*, log_path: Path | None = None, text: str) -> None:
    """Manually create a jot (alternative to ',,' capture)."""
    path = log_path or default_log_path()
    ev = _make_event("capture", text, path, ctx={"cwd": str(Path.cwd())})
    _write_event(path, ev)
    print(f"added: {ev.id[-6:]}")


def cmd_search(
    *,
    log_path: Path | None = None,
    query: str,
    limit: int = 20,
) -> None:
    """Lexical substring search (fallback when Session-Buddy is unavailable)."""
    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    matches = [s for s in result.states if query.lower() in s.text.lower()][:limit]
    if matches:
        print(render_list(matches, limit=limit))


# --- drain subcommand handlers (Task 12, spec §3.2) ---


def cmd_drain(
    *,
    log_path: Path | None = None,
    query: str | None = None,
    limit: int = 20,
    include_in_flight: bool = False,
) -> None:
    """List drain candidates (interactive prompt is a UX polish — out of scope).

    Calls ``drain.drain_plan()`` and prints a summary table. The Typer
    registration in mahavishnu/cli/jot_cli.py (Task 13) wires this to
    ``mahavishnu jot drain``.
    """
    from . import drain as drain_module

    path = log_path or default_log_path()
    plan = drain_module.drain_plan(
        query=query,
        limit=limit,
        include_in_flight=include_in_flight,
    )
    if plan.error is not None:
        print(
            f"# drain candidates (fold error: {plan.error})",
            file=sys.stderr,
        )
        raise SystemExit(1)
    candidates = plan.candidates
    print(f"# drain candidates ({len(candidates)})")
    now_ms_ = int(time.time() * 1000)
    for cand in candidates:
        sid = cand.short_id
        text = cand.text[:60]
        action = (
            "retry"
            if cand.dispatch_state is DispatchState.FAILED
            else "skip"
            if cand.deferred_until is not None and cand.deferred_until > now_ms_
            else "dispatch"
        )
        reason = (
            "previous dispatch failed"
            if action == "retry"
            else "deferred until later"
            if action == "skip"
            else "open and ready"
        )
        print(f"  {sid}  [{action}]  {text}  ({reason})")
    # Note: log_path is unused here since drain_plan reads from the default
    # log via log_path(). Custom log_path will be honored in Task 9.
    del path


def cmd_dispatch(*, log_path: Path | None = None, handle: str) -> None:
    """Dispatch a single jot to the workflow runtime."""
    from . import drain as drain_module

    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        asyncio.run(drain_module.dispatch_jot(s.short_id, dispatched_from="cli"))
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"dispatched: {s.short_id}")


def cmd_defer(
    *,
    log_path: Path | None = None,
    handle: str,
    until_ms: int,
    reason: str | None = None,
) -> None:
    """Defer a jot until a specific timestamp (epoch ms)."""
    from . import drain as drain_module

    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        asyncio.run(
            drain_module.defer_jot(
                s.short_id,
                until_ms=until_ms,
                reason=reason,
            )
        )
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"deferred: {s.short_id} until {until_ms}")


def cmd_delete(
    *,
    log_path: Path | None = None,
    handle: str,
    reason: str | None = None,
) -> None:
    """Soft-delete a jot (audit trail preserved in the JSONL log)."""
    from . import drain as drain_module

    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        asyncio.run(drain_module.delete_jot(s.short_id, reason=reason))
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"deleted: {s.short_id}")


def cmd_retry(*, log_path: Path | None = None, handle: str) -> None:
    """Manually retry a FAILED-dispatched jot."""
    from . import drain as drain_module

    path = log_path or default_log_path()
    events = _read_log(path)
    result = build_states(events, enrich=False)
    try:
        s = resolve_handle(result.states, handle)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        asyncio.run(drain_module.retry_dispatch(s.short_id, dispatched_from="cli"))
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"retried: {s.short_id}")


def cmd_resurface(
    *,
    log_path: Path | None = None,
    trigger: str = "session_start",
    context_text: str = "",
) -> None:
    """Surface relevant jots for the given context (spec §5.2).

    Mostly internal — invoked by the session-start / tool-result hooks.
    Exposed for `mahavishnu jot resurface --trigger ... --context ...`.
    """
    from . import drain as drain_module

    path = log_path or default_log_path()
    del path  # drain.surface_relevant reads from the default log
    if trigger not in ("session_start", "tool_result"):
        print(f"error: unknown trigger {trigger!r}", file=sys.stderr)
        raise SystemExit(1)
    try:
        result = drain_module.surface_relevant(trigger, context_text)
    except JotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    matches = getattr(result, "matches", []) or []
    print(f"# resurface ({len(matches)} hits, trigger={trigger})")
    for jot in matches:
        sid = jot.short_id
        text = jot.text
        print(f"  {sid}  {text[:60]}")


# --- helpers ---


def _detail_from_summary(
    s: JotSummary,
    events: list[JotEvent],
) -> JotDetail:
    """Build a JotDetail from a JotSummary by finding the matching event.

    Spec R9: ``JotDetail.hlc`` is the **latest** HLC for this jot (after any
    later edits/done/reopen ops). The capture HLC is the anchor; the
    latest HLC is the most-recent event for the same jot id.
    """
    capture_ev = next(
        (e for e in events if e.id == s.id and e.op == "capture"),
        None,
    )
    latest_ev = max(
        (e for e in events if e.id == s.id),
        key=lambda e: (e.hlc.wall_ms, e.hlc.ctr),
        default=None,
    )
    hlc_str = ""
    created_ms = s.last_modified_ms
    ctx: dict[str, str | list[str] | None] = {}
    if capture_ev:
        created_ms = capture_ev.created_ms
        ctx = dict(capture_ev.ctx) if capture_ev.ctx else {}
    # HLC string comes from the latest event (R9), NOT the capture.
    source_hlc = (
        latest_ev.hlc
        if latest_ev is not None
        else (capture_ev.hlc if capture_ev is not None else None)
    )
    if source_hlc is not None:
        hlc_str = f"{source_hlc.wall_ms}-{source_hlc.ctr}-{source_hlc.node}"
    return JotDetail(summary=s, hlc=hlc_str, created_ms=created_ms, ctx=ctx)
