"""Terminal-friendly render layer (R9).

Drain sub-plan 3 (§3.3) — TypedDict surfaces for MCP tools and CLI handlers:
- ``JotSummaryDict``: 5 base fields + 6 drain fields (extends sub-plan 2).
- ``JotVitalsDict``: 2 base count fields + 5 drain-derived counts.
- ``_summary_dict(jot)``: dataclass -> dict, with all dispatch fields.
- ``_vitals_dict(states, log_event_count)``: counts across states.

All TypedDicts are total=False (drain fields optional) or explicitly allow
``None`` where the spec mandates it. No ``Any`` per TD-H5 / R11.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from .fold import DispatchState

if TYPE_CHECKING:
    from .fold import FoldResult, JotDetail, JotSummary


STATUS_WIDTH = 4
SHORT_ID_WIDTH = 6
TEXT_TRUNCATE = 50


def _format_ms(ms: int) -> str:
    """ms epoch -> 'YYYY-MM-DD HH:MM' (UTC)."""
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC).strftime("%Y-%m-%d %H:%M")


# =============================================================================
# TypedDicts — sub-plan 3 §3.3. Used by MCP tools (Task 14) and CLI (Task 12).
# =============================================================================


class JotSummaryDict(TypedDict, total=False):
    """Surface shape returned by MCP tools / CLI list handlers.

    Base 5 fields (sub-plan 2) + 6 drain fields (sub-plan 3 §3.3, §4.4).
    ``total=False`` because every drain field is absent or None for jots
    that have no dispatch chain.
    """

    # Base fields (unchanged)
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    # NEW (drain sub-plan 3) — absent or None for jots with no dispatch history
    dispatch_state: Literal["in_flight", "succeeded", "failed"] | None
    dispatch_workflow_id: str | None
    current_attempt: int
    dispatch_started_at_ms: int | None
    deferred_until: int | None
    deleted: bool


class JotVitalsDict(TypedDict):
    """Aggregate counters for inbox monitoring (sub-plan 3 §3.3).

    Base 2 fields (open/done) + 5 drain-derived counts. All fields required
    (no ``total=False``) — callers can rely on every key being present.
    """

    open: int
    done: int
    dispatch_in_flight: int
    dispatch_failed: int
    deferred: int
    deleted: int
    log_event_count: int


def _summary_dict(jot: JotSummary) -> JotSummaryDict:
    """Project a ``JotSummary`` dataclass to its MCP/CLI dict surface.

    All 6 drain fields are emitted unconditionally (literal ``"in_flight"``
    for ``DispatchState.IN_FLIGHT``, etc.). ``None`` propagates as ``None``
    for optional fields. ``deleted`` is always emitted as a bool.
    """
    state_literal = jot.dispatch_state.value if jot.dispatch_state is not None else None
    return JotSummaryDict(
        id=jot.id,
        short_id=jot.short_id,
        text=jot.text,
        status=jot.status,
        last_modified_ms=jot.last_modified_ms,
        dispatch_state=state_literal,  # ty: ignore[invalid-key]
        dispatch_workflow_id=jot.dispatch_workflow_id,
        current_attempt=jot.current_attempt,
        dispatch_started_at_ms=jot.dispatch_started_at_ms,
        deferred_until=jot.deferred_until,
        deleted=jot.deleted,
    )


def _vitals_dict(
    states: list[JotSummary],
    log_event_count: int,
) -> JotVitalsDict:
    """Aggregate ``JotSummary`` states into the vitals surface.

    Args:
        states: per-id ``JotSummary`` list (typically from ``FoldResult.states``).
        log_event_count: total JSONL events on disk, supplied by the caller
            (the caller has the file handle; ``render`` stays I/O-free).
    """
    open_count = 0
    done_count = 0
    dispatch_in_flight = 0
    dispatch_failed = 0
    deferred = 0
    deleted = 0
    for s in states:
        if s.status == "open":
            open_count += 1
        else:
            done_count += 1
        if s.deleted:
            deleted += 1
        if s.deferred_until is not None:
            deferred += 1
        if s.dispatch_state is not None:
            if s.dispatch_state is DispatchState.IN_FLIGHT:
                dispatch_in_flight += 1
            elif s.dispatch_state is DispatchState.FAILED:
                dispatch_failed += 1
    return JotVitalsDict(
        open=open_count,
        done=done_count,
        dispatch_in_flight=dispatch_in_flight,
        dispatch_failed=dispatch_failed,
        deferred=deferred,
        deleted=deleted,
        log_event_count=log_event_count,
    )


def render_list(
    states: list[JotSummary],
    *,
    status_filter: str | None = None,
    limit: int = 50,
) -> str:
    """Render states as a table: STATUS  SHORT_ID  TEXT  MODIFIED.

    Newest first (caller passes FoldResult.states which is already sorted).
    """
    if status_filter:
        states = [s for s in states if s.status == status_filter]
    states = states[:limit]

    lines: list[str] = []
    for s in states:
        status = s.status.upper().ljust(STATUS_WIDTH)
        sid = s.short_id.ljust(SHORT_ID_WIDTH)
        text = s.text[:TEXT_TRUNCATE].ljust(TEXT_TRUNCATE)
        mod = _format_ms(s.last_modified_ms)
        lines.append(f"{status} {sid} {text} {mod}")
    return "\n".join(lines)


def render_show(detail: JotDetail) -> str:
    """Render a JotDetail as a multi-line block."""
    s = detail.summary
    lines: list[str] = [
        f"ID:        {s.id}",
        f"Status:    {s.status.upper()}",
        f"Created:   {_format_ms(detail.created_ms)}",
        f"Modified:  {_format_ms(s.last_modified_ms)}",
    ]
    ctx = detail.ctx
    if ctx.get("repo"):
        branch = ctx.get("branch") or "?"
        sha = (ctx.get("sha") or "?")[:7]
        lines.append(f"Repo:      {ctx['repo']} ({branch} @ {sha})")
    if ctx.get("session_id"):
        lines.append(f"Session:   {ctx['session_id']}")
    lines.append("")
    lines.append("Text:")
    text = s.text[:TEXT_TRUNCATE]
    lines.append(f"  {text}")
    return "\n".join(lines)


def render_vitals(result: FoldResult) -> str:
    """Render vitals summary."""
    total = len(result.states)
    open_count = sum(1 for s in result.states if s.status == "open")
    done_count = sum(1 for s in result.states if s.status == "done")
    lines: list[str] = ["Jot inbox vitals"]
    lines.append(f"  Total:   {total}")
    lines.append(f"  Open:    {open_count}")
    lines.append(f"  Done:    {done_count}")
    if result.states:
        last_ms = max(s.last_modified_ms for s in result.states)
        oldest_ms = min(s.last_modified_ms for s in result.states)
        lines.append(f"  Last:    {_format_ms(last_ms)}")
        lines.append(f"  Oldest:  {_format_ms(oldest_ms)}")
    return "\n".join(lines)
