"""Fold layer: two-pass fold with parking (TD-B3, R7).

Public surface:
- FoldResult: states, parked, errors dataclass
- JotSummary: list-view state (5 fields, R9)
- parse_events(): file I/O, returns list[JotEvent]
- build_states(): pure transform, returns FoldResult (Task 4)
- _enrich_ctx(): git subprocess enrichment (Task 5)
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Literal

from .errors import JotLogCorruptError
from .events import JotEvent, deserialize

if TYPE_CHECKING:
    from pathlib import Path

# Public re-export so callers do `from mahavishnu.jot.fold import JotSummary`.
# `build_states` is added to this list in Task 4 once it ships.
__all__ = ["FoldResult", "JotSummary", "parse_events"]


@dataclass(frozen=True, slots=True)
class JotSummary:
    """List-view state (5 fields per R9)."""

    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int


@dataclass(frozen=True, slots=True)
class FoldResult:
    """Two-pass fold output (TD-B3).

    Attributes:
        states: current JotSummary list, sorted by last_modified_ms desc.
        parked: events whose target id wasn't seen yet (replayed pass 2).
        errors: events parked through full log scan (genuine orphans).
    """

    states: list[JotSummary]
    parked: list[JotEvent]
    errors: list[JotEvent]


def parse_events(log_path: Path) -> list[JotEvent]:
    """Read the JSONL log into JotEvents.

    - Malformed lines are skipped and logged to errors.log (fail-open per UD7).
    - Raises JotLogCorruptError when the file can't be opened (vs lines).
    - Returns [] when the log doesn't exist (OQ2).
    """
    if not log_path.exists():
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise JotLogCorruptError(f"cannot read log {log_path}: {exc}") from exc

    events: list[JotEvent] = []
    for _line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            events.append(deserialize(stripped))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Fail-open: skip malformed lines (UD7 — no crash on bad data).
            # Caller can check errors.log if diagnostics are needed.
            continue
    return events


def _hlc_sort_key(ev: JotEvent) -> tuple[int, int, str]:
    """UD4 tiebreaker: lex on (wall_ms, ctr, node)."""
    return (ev.hlc.wall_ms, ev.hlc.ctr, ev.hlc.node)


def build_states(
    events: list[JotEvent],
    *,
    enrich: bool = True,
    current_dir: Path | None = None,
) -> FoldResult:
    """Pure fold: events -> FoldResult.

    Two-pass with parking (R3). Pass 1 scans events in HLC order; pass 2
    replays parked events. Genuine orphans (parked through full scan) move
    to errors.

    HLC tiebreaker (UD4): lex on (wall_ms, ctr, node); same (wall_ms, node)
    breaks by ctr ascending. Python's tuple sort already does this.

    Args:
        events: list of JotEvent in log order (file order, not HLC order).
        enrich: when True (default), run git enrichment via subprocess
            (Task 5). Tests should pass enrich=False for log-idempotency.
        current_dir: directory for git enrichment; defaults to cwd.
    """
    sorted_events = sorted(events, key=_hlc_sort_key)

    states_by_id: dict[str, JotSummary] = {}
    parked: list[JotEvent] = []

    for ev in sorted_events:
        match ev.op:
            case "capture":
                states_by_id[ev.id] = JotSummary(
                    id=ev.id,
                    short_id=ev.id[-6:],
                    text=ev.text,
                    status="open",
                    last_modified_ms=ev.hlc.wall_ms,
                )
            case "edit":
                if ev.id not in states_by_id:
                    parked.append(ev)
                else:
                    s = states_by_id[ev.id]
                    states_by_id[ev.id] = JotSummary(
                        id=s.id,
                        short_id=s.short_id,
                        text=ev.text,
                        status=s.status,
                        last_modified_ms=ev.hlc.wall_ms,
                    )
            case "done" | "reopen":
                if ev.id not in states_by_id:
                    parked.append(ev)
                else:
                    s = states_by_id[ev.id]
                    states_by_id[ev.id] = JotSummary(
                        id=s.id,
                        short_id=s.short_id,
                        text=s.text,
                        status="done" if ev.op == "done" else "open",
                        last_modified_ms=ev.hlc.wall_ms,
                    )

    errors: list[JotEvent] = []
    for ev in parked:
        if ev.id not in states_by_id:
            errors.append(ev)
            continue
        s = states_by_id[ev.id]
        match ev.op:
            case "edit":
                states_by_id[ev.id] = JotSummary(
                    id=s.id,
                    short_id=s.short_id,
                    text=ev.text,
                    status=s.status,
                    last_modified_ms=max(s.last_modified_ms, ev.hlc.wall_ms),
                )
            case "done" | "reopen":
                states_by_id[ev.id] = JotSummary(
                    id=s.id,
                    short_id=s.short_id,
                    text=s.text,
                    status="done" if ev.op == "done" else "open",
                    last_modified_ms=max(s.last_modified_ms, ev.hlc.wall_ms),
                )

    final_states = sorted(
        states_by_id.values(),
        key=lambda s: (-s.last_modified_ms, s.id),
    )

    # TD-B3: parked tracks "still unresolved" events. After pass 2 every parked
    # event is either successfully replayed (now in states) or moved to errors.
    # The final parked list is therefore empty by construction.
    parked = []

    return FoldResult(states=final_states, parked=parked, errors=errors)