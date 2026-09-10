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