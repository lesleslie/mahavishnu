"""MCP tools for the jot inbox (8 tools, TypedDict returns).

R1: CRUD-only. R11 / TD-B1 / TD-H5: every return type is a TypedDict, no Any.

These functions are decorated with @mcp.tool() in the registration
function below; tests access the underlying function via `.fn` (the
FastMCP convention).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Literal, TypedDict
import uuid

from mahavishnu.jot.cli import _detail_from_summary
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.fold import JotSummary, build_states
from mahavishnu.jot.handle import resolve_handle
from mahavishnu.jot.hlc import hlc_now, read_tail_hlc
from mahavishnu.jot.paths import log_path as _log_path_default

# Re-import the default for monkeypatching in tests.
_log_path = _log_path_default


# --- TypedDicts (R11 / TD-H5) ---


class JotSummaryDict(TypedDict):
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int


class JotDetailDict(TypedDict):
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    hlc: str
    created_ms: int
    ctx: dict[str, str | list[str] | None]


class JotVitalsDict(TypedDict):
    total: int
    open: int
    done: int
    last_capture_ms: int | None
    oldest_ms: int | None


# --- helpers ---


def _read_events(path: Path | None = None) -> list[JotEvent]:
    from mahavishnu.jot.fold import parse_events

    events: list[JotEvent] = parse_events(path or _log_path())
    return events


def _emit(
    op: str, text: str, ctx: dict[str, str] | None = None,
    event_id: str | None = None,
) -> None:
    """Append one event to the log.

    ``event_id`` defaults to a fresh uuid (used by ``capture``). Edit/done/
    reopen callers MUST pass the parent jot's id so the fold can associate
    the new event with the existing JotSummary state (R3, R9 — fold by id).
    """
    path = _log_path()
    last = read_tail_hlc(path)
    from mahavishnu.jot.hlc import get_node
    from mahavishnu.jot.paths import node_path as _node_path_fn
    node = get_node(_node_path_fn())
    hlc = hlc_now(node, last)
    ev = JotEvent(
        id=event_id or uuid.uuid4().hex, op=op, hlc=hlc, text=text,
        ctx=ctx or {}, created_ms=hlc.wall_ms,
    )
    line = serialize(ev) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _summary_dict(s: JotSummary) -> JotSummaryDict:
    return JotSummaryDict(
        id=s.id,
        short_id=s.short_id,
        text=s.text,
        status=s.status,
        last_modified_ms=s.last_modified_ms,
    )


def _detail_dict(s: JotSummary, events: list[JotEvent]) -> JotDetailDict:
    d = _detail_from_summary(s, events)
    return JotDetailDict(
        id=s.id,
        short_id=s.short_id,
        text=s.text,
        status=s.status,
        last_modified_ms=s.last_modified_ms,
        hlc=d.hlc,
        created_ms=d.created_ms,
        ctx=dict(d.ctx),
    )


# --- 8 tool functions ---


def jot_list(
    status: str | None = None, limit: int = 50,
) -> list[JotSummaryDict]:
    """List jots, newest first. status filter: 'open' | 'done' | None for all."""
    events = _read_events()
    result = build_states(events, enrich=False)
    states = result.states
    if status:
        states = [s for s in states if s.status == status]
    return [_summary_dict(s) for s in states[:limit]]


def jot_show(handle: str) -> JotDetailDict:
    """Show one jot by id (32 hex) or short_id (6 hex).

    Raises JotNotFoundError or JotAmbiguousHandleError.
    """
    events = _read_events()
    result = build_states(events, enrich=False)
    s = resolve_handle(result.states, handle)
    return _detail_dict(s, events)


def jot_add(text: str) -> JotDetailDict:
    """Manually create a jot (alternative to ',,' capture). Writes capture event."""
    _emit("capture", text, ctx={"cwd": str(Path.cwd())})
    events = _read_events()
    result = build_states(events, enrich=False)
    s = result.states[-1]  # the just-added jot is newest
    return _detail_dict(s, events)


def jot_edit(handle: str, new_text: str) -> JotDetailDict:
    """Edit a jot's text. Writes edit event.

    Raises JotNotFoundError or JotAmbiguousHandleError.
    """
    events = _read_events()
    result = build_states(events, enrich=False)
    s = resolve_handle(result.states, handle)  # raises if missing/ambiguous
    _emit("edit", new_text, event_id=s.id)
    events = _read_events()
    result = build_states(events, enrich=False)
    s = result.states[-1]
    return _detail_dict(s, events)


def jot_done(handle: str) -> JotDetailDict:
    """Mark a jot as done. No-op if already done.

    Raises JotNotFoundError or JotAmbiguousHandleError.
    """
    events = _read_events()
    result = build_states(events, enrich=False)
    s = resolve_handle(result.states, handle)
    if s.status != "done":
        _emit("done", "", event_id=s.id)
        events = _read_events()
        result = build_states(events, enrich=False)
        s = result.states[-1]
    return _detail_dict(s, events)


def jot_reopen(handle: str) -> JotDetailDict:
    """Reopen a done jot. No-op if already open.

    Raises JotNotFoundError or JotAmbiguousHandleError.
    """
    events = _read_events()
    result = build_states(events, enrich=False)
    s = resolve_handle(result.states, handle)
    if s.status != "open":
        _emit("reopen", "", event_id=s.id)
        events = _read_events()
        result = build_states(events, enrich=False)
        s = result.states[-1]
    return _detail_dict(s, events)


def jot_vitals() -> JotVitalsDict:
    """Return counts: total, open, done, last_capture_ms, oldest_ms."""
    events = _read_events()
    result = build_states(events, enrich=False)
    states = result.states
    return JotVitalsDict(
        total=len(states),
        open=sum(1 for s in states if s.status == "open"),
        done=sum(1 for s in states if s.status == "done"),
        last_capture_ms=max((s.last_modified_ms for s in states), default=None),
        oldest_ms=min((s.last_modified_ms for s in states)) if states else None,
    )


def jot_search(query: str, limit: int = 20) -> list[JotSummaryDict]:
    """Lexical substring search (Session-Buddy semantic search is a future addition)."""
    events = _read_events()
    result = build_states(events, enrich=False)
    matches = [s for s in result.states if query.lower() in s.text.lower()][:limit]
    return [_summary_dict(s) for s in matches]


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    """Register all 8 tools on the FastMCP instance.

    Re-decorates each module-level tool with the real FastMCP server,
    rebinding the module attribute to a FunctionTool bound to ``mcp``.
    Idempotent: re-calling replaces prior wrappers.
    """
    names = [
        "jot_list", "jot_show", "jot_add", "jot_edit",
        "jot_done", "jot_reopen", "jot_vitals", "jot_search",
    ]
    module = sys.modules[__name__]
    for name in names:
        plain = getattr(module, name).fn
        wrapped = mcp.tool()(plain)
        setattr(module, name, wrapped)


# Wrap each tool at module load so `jot_tools.jot_list.fn(...)` works for tests
# (FastMCP convention: a decorated function is a FunctionTool with the
# original callable exposed via `.fn`). ``FunctionTool.from_function`` creates
# a FunctionTool without requiring a live FastMCP server — the real server's
# ``register(mcp)`` call above rebinds the module attrs against the live server
# (and the ``.fn`` accessor continues to work).
def _wrap_at_import() -> None:
    """Bind each ``jot_*`` function to a FunctionTool for testability.

    Best-effort: if FastMCP is not installed (lean CLI-only installs) or its
    public API has drifted, leave the plain callables in place so the CLI and
    other callers can still use the module. FastMCP registration itself is
    performed by ``register(mcp)`` against a live server.
    """
    try:
        from fastmcp.tools.function_tool import FunctionTool
    except ImportError:
        return

    names = [
        "jot_list", "jot_show", "jot_add", "jot_edit",
        "jot_done", "jot_reopen", "jot_vitals", "jot_search",
    ]
    module = sys.modules[__name__]
    for name in names:
        plain = getattr(module, name)
        setattr(module, name, FunctionTool.from_function(plain))


_wrap_at_import()