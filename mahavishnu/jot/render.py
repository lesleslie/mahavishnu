"""Terminal-friendly render layer (R9)."""
from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fold import FoldResult, JotDetail, JotSummary

STATUS_WIDTH = 4
SHORT_ID_WIDTH = 6
TEXT_TRUNCATE = 50
MOD_WIDTH = 16  # "YYYY-MM-DD HH:MM"


def _format_ms(ms: int) -> str:
    """ms epoch -> 'YYYY-MM-DD HH:MM' (UTC)."""
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.UTC).strftime(
        "%Y-%m-%d %H:%M"
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
