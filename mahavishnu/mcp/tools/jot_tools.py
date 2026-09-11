"""MCP tools for the jot inbox (14 tools, TypedDict returns).

R1: CRUD-only. R11 / TD-B1 / TD-H5: every return type is a TypedDict, no Any.

Sub-plan 3 (Drain) adds 6 tools: ``jot_drain``, ``jot_dispatch``, ``jot_defer``,
``jot_delete``, ``jot_retry``, ``jot_resurface``. They live alongside the
8 CRUD tools from sub-plan 2.

The ``JotSummaryDict`` / ``JotVitalsDict`` / ``_summary_dict`` / ``_vitals_dict``
projections are NOT defined here — they live in ``mahavishnu.jot.render``
(sub-plan 3 §3.3). This module re-imports them so the wrapper layer stays
thin. ``JotDetailDict`` is the only TypedDict that remains local because it
is built from a CLI helper, not the render layer.

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
from mahavishnu.jot.drain import DispatchResultDict, DrainPlanDict
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.fold import JotSummary, build_states
from mahavishnu.jot.handle import resolve_handle
from mahavishnu.jot.hlc import hlc_now, read_tail_hlc
from mahavishnu.jot.paths import log_path as _log_path_default
from mahavishnu.jot.render import (
    JotSummaryDict,
    JotVitalsDict,
    _summary_dict,
    _vitals_dict,
)

# Re-import the default for monkeypatching in tests.
_log_path = _log_path_default


# --- TypedDicts (R11 / TD-H5) ---


class JotDetailDict(TypedDict):
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    hlc: str
    created_ms: int
    ctx: dict[str, str | list[str] | None]


# --- helpers ---


def _read_events(path: Path | None = None) -> list[JotEvent]:
    from mahavishnu.jot.fold import parse_events

    events: list[JotEvent] = parse_events(path or _log_path())
    return events


def _emit(
    op: str,
    text: str,
    ctx: dict[str, str] | None = None,
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
        id=event_id or uuid.uuid4().hex,
        op=op,
        hlc=hlc,
        text=text,
        ctx=ctx or {},
        created_ms=hlc.wall_ms,
    )
    line = serialize(ev) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


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
    status: str | None = None,
    limit: int = 50,
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
    """Return counts: open, done, dispatch_in_flight, dispatch_failed,
    deferred, deleted, log_event_count (render sub-plan 3 §3.3 shape)."""
    events = _read_events()
    result = build_states(events, enrich=False)
    return _vitals_dict(result.states, log_event_count=len(events))


def jot_search(query: str, limit: int = 20) -> list[JotSummaryDict]:
    """Lexical substring search (Session-Buddy semantic search is a future addition)."""
    events = _read_events()
    result = build_states(events, enrich=False)
    matches = [s for s in result.states if query.lower() in s.text.lower()][:limit]
    return [_summary_dict(s) for s in matches]


# --- 6 drain tools (sub-plan 3 §3.3) ---


def jot_drain(
    query: str | None = None,
    limit: int = 20,
    include_in_flight: bool = False,
) -> DrainPlanDict:
    """Build a bulk-action plan over open jots.

    Lazy import keeps module-load cost down when drain is unused (per
    sub-plan 3 §3.7 separation). Returns the plan but performs NO
    dispatch — callers invoke ``jot_dispatch`` per selected candidate.
    """
    from mahavishnu.jot import drain as _drain

    plan = _drain.drain_plan(
        query=query, limit=limit, include_in_flight=include_in_flight,
    )
    return DrainPlanDict(
        query=plan.query,
        candidates=[_summary_dict(s) for s in plan.candidates],
        action_proposals=[],
    )


def jot_dispatch(handle: str) -> DispatchResultDict:
    """Dispatch a single jot as a Mahavishnu workflow.

    Stamps ``dispatched_from="mcp"`` so the fold records the entry surface.
    """
    from mahavishnu.jot import drain as _drain

    res = _drain.dispatch_jot(handle=handle)
    return DispatchResultDict(
        handle=res.handle,
        workflow_id=res.workflow_id,
        attempt=res.attempt,
        status=res.status,
        dispatched_from="mcp",
    )


def jot_defer(
    handle: str, until_ms: int, reason: str | None = None,
) -> JotSummaryDict:
    """Snooze a jot until ``until_ms``. Rejects ``until_ms <= now_ms``."""
    from mahavishnu.jot import drain as _drain

    return _summary_dict(
        _drain.defer_jot(handle=handle, until_ms=until_ms, reason=reason),
    )


def jot_delete(handle: str, reason: str | None = None) -> JotSummaryDict:
    """Soft delete (audit log retained)."""
    from mahavishnu.jot import drain as _drain

    return _summary_dict(_drain.delete_jot(handle=handle, reason=reason))


def jot_retry(handle: str) -> DispatchResultDict:
    """Manual retry of a FAILED-dispatched jot."""
    from mahavishnu.jot import drain as _drain

    res = _drain.retry_dispatch(handle=handle)
    return DispatchResultDict(
        handle=res.handle,
        workflow_id=res.workflow_id,
        attempt=res.attempt,
        status=res.status,
        dispatched_from="mcp",
    )


def jot_resurface(
    trigger: Literal["session_start", "tool_result"],
    context_text: str,
    limit: int = 3,
) -> list[JotSummaryDict]:
    """Surface jots relevant to the given trigger + context.

    Internal hook entrypoint — invoked by ``jot-session-start`` and
    ``jot-post-tool-use``. Lexical primary, semantic fallback per spec §5.
    """
    from mahavishnu.jot import drain as _drain

    result = _drain.surface_relevant(
        trigger=trigger, context_text=context_text, limit=limit,
    )
    return [_summary_dict(s) for s in result.matches]


def register(mcp) -> None:  # type: ignore[no-untyped-def]
    """Register all 14 tools on the FastMCP instance.

    Re-decorates each module-level tool with the real FastMCP server,
    rebinding the module attribute to a FunctionTool bound to ``mcp``.
    Idempotent: re-calling replaces prior wrappers.
    """
    names = [
        "jot_list",
        "jot_show",
        "jot_add",
        "jot_edit",
        "jot_done",
        "jot_reopen",
        "jot_vitals",
        "jot_search",
        "jot_drain",
        "jot_dispatch",
        "jot_defer",
        "jot_delete",
        "jot_retry",
        "jot_resurface",
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
        "jot_list",
        "jot_show",
        "jot_add",
        "jot_edit",
        "jot_done",
        "jot_reopen",
        "jot_vitals",
        "jot_search",
        "jot_drain",
        "jot_dispatch",
        "jot_defer",
        "jot_delete",
        "jot_retry",
        "jot_resurface",
    ]
    module = sys.modules[__name__]
    for name in names:
        plain = getattr(module, name)
        setattr(module, name, FunctionTool.from_function(plain))


_wrap_at_import()
