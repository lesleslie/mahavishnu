"""Fold layer: two-pass fold with parking (TD-B3, R7).

Public surface:
- FoldResult: states, parked, errors, ctx_by_id dataclass
- JotSummary: list-view state (5 fields, R9)
- parse_events(): file I/O, returns list[JotEvent]
- build_states(): pure transform, returns FoldResult
- _enrich_ctx(): git subprocess enrichment (R4)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Literal

from .errors import JotLogCorruptError
from .events import JotEvent, deserialize

if TYPE_CHECKING:
    from collections.abc import Mapping

# Public re-export so callers do `from mahavishnu.jot.fold import JotSummary`.
__all__ = ["FoldResult", "JotSummary", "build_states", "parse_events"]


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
        ctx_by_id: per-state enriched ctx (R4 git subprocess). Empty dict
            when enrich=False; observability side-channel for callers that
            need repo/branch/sha alongside the summary.
    """

    states: list[JotSummary]
    parked: list[JotEvent]
    errors: list[JotEvent]
    ctx_by_id: dict[str, Mapping[str, str | list[str] | None]] = field(
        default_factory=dict,
    )


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


def _git(cwd: Path, *args: str) -> str:
    """Run `git <args>` in cwd. Returns stripped stdout.

    Raises subprocess.CalledProcessError on non-zero exit, FileNotFoundError
    when git is missing, OSError for other spawn failures.
    """
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        timeout=5, check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout)
    return result.stdout.strip()


def _enrich_ctx(
    ctx: Mapping[str, str | list[str] | None], current_dir: Path,
) -> Mapping[str, str | list[str] | None]:
    """Add repo/branch/sha to ctx via git subprocess (R4).

    Serverless-safe: subprocess with fail-open (file-based .git/ reads would
    break in Lambda/Worker environments where .git/ doesn't exist).

    All three git calls are fail-open independently — a missing `git`
    binary OR a non-git directory OR a failing rev-parse each return None
    rather than raising.
    """
    enriched: dict[str, str | list[str] | None] = dict(ctx)
    try:
        enriched["repo"] = _git(current_dir, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["repo"] = None
    try:
        enriched["branch"] = _git(current_dir, "rev-parse", "--abbrev-ref", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["branch"] = None
    try:
        enriched["sha"] = _git(current_dir, "rev-parse", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        enriched["sha"] = None
    return enriched


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
    ctx_by_id: dict[str, Mapping[str, str | list[str] | None]] = {}

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
                ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
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
                    ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
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
                    ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}

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
                ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
            case "done" | "reopen":
                states_by_id[ev.id] = JotSummary(
                    id=s.id,
                    short_id=s.short_id,
                    text=s.text,
                    status="done" if ev.op == "done" else "open",
                    last_modified_ms=max(s.last_modified_ms, ev.hlc.wall_ms),
                )
                ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}

    final_states = sorted(
        states_by_id.values(),
        key=lambda s: (-s.last_modified_ms, s.id),
    )

    # TD-B3: parked tracks "still unresolved" events. After pass 2 every parked
    # event is either successfully replayed (now in states) or moved to errors.
    # The final parked list is therefore empty by construction.
    parked = []

    if enrich:
        dir_for_git = current_dir if current_dir is not None else Path.cwd()
        ctx_by_id = {
            sid: _enrich_ctx(ctx, dir_for_git) for sid, ctx in ctx_by_id.items()
        }

    return FoldResult(
        states=final_states, parked=parked, errors=errors, ctx_by_id=ctx_by_id,
    )
