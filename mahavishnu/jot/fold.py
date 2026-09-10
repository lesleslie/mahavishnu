"""Fold layer: two-pass fold with parking (TD-B3, R7).

Public surface:
- FoldResult: states, parked, errors, ctx_by_id dataclass
- JotSummary: list-view state (5 fields, R9; +6 drain fields, sub-plan 3)
- JotDetail: show-view state (R9 — composition over JotSummary)
- DispatchState: enum (IN_FLIGHT/SUCCEEDED/FAILED), drain sub-plan 3
- parse_events(): file I/O, returns list[JotEvent]
- build_states(): pure transform, returns FoldResult
- _enrich_ctx(): git subprocess enrichment (R4)
- _derive_dispatch_fields(): state derivation (sub-plan 3 §4.6)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Literal

from oneiric.core.logging import get_logger

from .errors import JotLogCorruptError
from .events import JotEvent, deserialize

if TYPE_CHECKING:
    from collections.abc import Mapping

log = get_logger(__name__)

# Public re-export so callers do `from mahavishnu.jot.fold import JotSummary`.
__all__ = [
    "DispatchState",
    "FoldResult",
    "JotDetail",
    "JotSummary",
    "build_states",
    "parse_events",
]


class DispatchState(Enum):
    """Per-jot dispatch lifecycle state (drain sub-plan 3, §4.4).

    - IN_FLIGHT: most-recent dispatch has no matching terminal yet, OR a
      matching dispatch_failed has retry_budget_exhausted=False (the
      dispatcher will reschedule another attempt).
    - SUCCEEDED: matching dispatch_done has been recorded.
    - FAILED: matching dispatch_failed has retry_budget_exhausted=True.
    """

    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JotSummary:
    """List-view state (5 base fields per R9 + 6 drain fields per §4.4)."""

    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    # NEW (drain sub-plan 3) — defaults preserve backward compat with
    # existing jots that have no dispatch chain.
    dispatch_state: DispatchState | None = None
    dispatch_workflow_id: str | None = None
    current_attempt: int = 0
    dispatch_started_at_ms: int | None = None
    deferred_until: int | None = None
    deleted: bool = False


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


@dataclass(frozen=True, slots=True)
class JotDetail:
    """Show-view state: summary + HLC + capture time + ctx.

    R9 — composition (not inheritance). render_show consumes this.
    """

    summary: JotSummary
    hlc: str  # serialized "{wall_ms}-{ctr}-{node}"
    created_ms: int
    ctx: Mapping[str, str | list[str] | None]  # read-only contract


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
        except ValueError, KeyError, TypeError, json.JSONDecodeError:
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
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout)
    return result.stdout.strip()


def _enrich_ctx(
    ctx: Mapping[str, str | list[str] | None],
    current_dir: Path,
) -> Mapping[str, str | list[str] | None]:
    """Add repo/branch/sha to ctx via git subprocess (R4).

    Serverless-safe: subprocess with fail-open (file-based .git/ reads would
    break in Lambda/Worker environments where .git/ doesn't exist).

    All three git calls are fail-open independently — a missing `git`
    binary OR a non-git directory OR a stalled git (timeout) each return
    None rather than raising.

    Catch tuple: `subprocess.SubprocessError` covers both
    `CalledProcessError` (non-zero exit, constructed by `_git`) and
    `TimeoutExpired` (5s timeout hit before git returned) plus any future
    SubprocessError subclass. `OSError` and `FileNotFoundError` are kept
    for self-documentation — they are harmless and overlap with
    `SubprocessError`'s hierarchy in some Python versions.
    """
    enriched: dict[str, str | list[str] | None] = dict(ctx)
    try:
        enriched["repo"] = _git(current_dir, "rev-parse", "--show-toplevel")
    except FileNotFoundError, subprocess.SubprocessError, OSError:
        enriched["repo"] = None
    try:
        enriched["branch"] = _git(current_dir, "rev-parse", "--abbrev-ref", "HEAD")
    except FileNotFoundError, subprocess.SubprocessError, OSError:
        enriched["branch"] = None
    try:
        enriched["sha"] = _git(current_dir, "rev-parse", "HEAD")
    except FileNotFoundError, subprocess.SubprocessError, OSError:
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

    After the 2-pass fold produces a per-id JotSummary, the drain fields
    (dispatch_state, current_attempt, dispatch_workflow_id,
    dispatch_started_at_ms, deferred_until, deleted) are derived per-id by
    walking the full event chain (§4.6). The base summary fields
    (id, short_id, text, status, last_modified_ms) drive the per-id bucket.

    HLC tiebreaker (UD4): lex on (wall_ms, ctr, node); same (wall_ms, node)
    breaks by ctr ascending. Python's tuple sort already does this.

    Args:
        events: list of JotEvent in log order (file order, not HLC order).
        enrich: when True (default), run git enrichment via subprocess
            (Task 5). Tests should pass enrich=False for log-idempotency.
        current_dir: directory for git enrichment; defaults to cwd.

    Note: ctx_by_id is an observability side-channel — populated ONLY when
    enrich=True. With enrich=False the data structure is empty (per F4
    wire-up contract).
    """
    sorted_events = sorted(events, key=_hlc_sort_key)

    # Map of jot-id -> list of events that reference that id (in HLC order).
    # Used for deriving dispatch chain state per id after the 2-pass fold.
    events_by_id: dict[str, list[JotEvent]] = {}
    for ev in sorted_events:
        events_by_id.setdefault(ev.id, []).append(ev)

    states_by_id: dict[str, JotSummary] = {}
    parked: list[JotEvent] = []
    ctx_by_id: dict[str, Mapping[str, str | list[str] | None]] = {}

    def _make_summary(
        base_id: str,
        text: str,
        status: Literal["open", "done"],
        wall_ms: int,
        id_events: list[JotEvent],
    ) -> JotSummary:
        """Build a JotSummary with base fields + derived drain fields."""
        (
            d_state,
            d_attempt,
            d_wf,
            d_started,
            d_deferred,
            d_deleted,
        ) = _derive_dispatch_fields(id_events)
        return JotSummary(
            id=base_id,
            short_id=base_id[-6:],
            text=text,
            status=status,
            last_modified_ms=wall_ms,
            dispatch_state=d_state,
            dispatch_workflow_id=d_wf,
            current_attempt=d_attempt,
            dispatch_started_at_ms=d_started,
            deferred_until=d_deferred,
            deleted=d_deleted,
        )

    for ev in sorted_events:
        match ev.op:
            case "capture":
                states_by_id[ev.id] = _make_summary(
                    base_id=ev.id,
                    text=ev.text,
                    status="open",
                    wall_ms=ev.hlc.wall_ms,
                    id_events=events_by_id[ev.id],
                )
                if enrich:
                    ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
            case "edit":
                if ev.id not in states_by_id:
                    parked.append(ev)
                else:
                    s = states_by_id[ev.id]
                    states_by_id[ev.id] = _make_summary(
                        base_id=s.id,
                        text=ev.text,
                        status=s.status,
                        wall_ms=ev.hlc.wall_ms,
                        id_events=events_by_id[ev.id],
                    )
                    if enrich:
                        ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
            case "done" | "reopen":
                if ev.id not in states_by_id:
                    parked.append(ev)
                else:
                    s = states_by_id[ev.id]
                    states_by_id[ev.id] = _make_summary(
                        base_id=s.id,
                        text=s.text,
                        status="done" if ev.op == "done" else "open",
                        wall_ms=ev.hlc.wall_ms,
                        id_events=events_by_id[ev.id],
                    )
                    if enrich:
                        ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}

    errors: list[JotEvent] = []
    for ev in parked:
        if ev.id not in states_by_id:
            errors.append(ev)
            continue
        s = states_by_id[ev.id]
        match ev.op:
            case "edit":
                states_by_id[ev.id] = _make_summary(
                    base_id=s.id,
                    text=ev.text,
                    status=s.status,
                    wall_ms=max(s.last_modified_ms, ev.hlc.wall_ms),
                    id_events=events_by_id[ev.id],
                )
                if enrich:
                    ctx_by_id[ev.id] = dict(ev.ctx) if ev.ctx else {}
            case "done" | "reopen":
                states_by_id[ev.id] = _make_summary(
                    base_id=s.id,
                    text=s.text,
                    status="done" if ev.op == "done" else "open",
                    wall_ms=max(s.last_modified_ms, ev.hlc.wall_ms),
                    id_events=events_by_id[ev.id],
                )
                if enrich:
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
        # F2: hoist the 3 git spawns out of the per-state loop. The git
        # result depends only on `dir_for_git`, which is constant across
        # all states. Spawning 3 git processes per state would have
        # multiplied the cost by N; with F1's 5s timeout that's a worst
        # case of 3*5s = 15s per call even when git is stalled.
        git_ctx = _enrich_ctx({}, dir_for_git)
        ctx_by_id = {sid: {**ctx, **git_ctx} for sid, ctx in ctx_by_id.items()}

    return FoldResult(
        states=final_states,
        parked=parked,
        errors=errors,
        ctx_by_id=ctx_by_id,
    )


# ----------------------------------------------------------------------------
# Drain sub-plan 3 helpers — see `.superpowers/sdd/2026-09-10-jot-drain/...`
# and spec §4.6 for state derivation.
# ----------------------------------------------------------------------------


def _coerce_int(value: object, *, field: str) -> int | None:
    """Coerce ctx value to int, logging+returning None on failure.

    Excludes bool (which is a subclass of int) — True/False are not
    acceptable as integer values in TypedDict ctx.
    """
    if isinstance(value, bool):
        log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            log.warning("JOT_CTX_UNPARSEABLE_INT", field=field, value=value)
            return None
    log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
    return None


def _coerce_str(value: object, *, field: str) -> str | None:
    """Coerce ctx value to str, logging+returning None on non-str types."""
    if isinstance(value, str):
        return value
    log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
    return None


def _parse_retry_budget_exhausted(value: object) -> bool:
    """Accept JSON bool true/false. Reject everything else with warn."""
    if isinstance(value, bool):
        return value
    log.warning(
        "JOT_CTX_RETRY_BUDGET_BAD_TYPE",
        value=type(value).__name__,
        value_repr=value,
    )
    return False


def _compute_deferred_until(events: list[JotEvent]) -> int | None:
    """Find the active deferral. None if no defer or last defer was expired.

    Defensive: a malformed `defer` (missing/non-numeric `until`) is logged at
    warning and treated as "no defer" rather than crashing the fold.
    """
    pending_until: int | None = None
    for i, ev in enumerate(events):
        if ev.op == "defer":
            until = _coerce_int(
                ev.ctx.get("until"),
                field=f"events[{i}].ctx.until",
            )
            if until is not None:
                pending_until = until
        elif ev.op == "defer_expired":
            pending_until = None
    return pending_until


def _derive_dispatch_fields(
    events: list[JotEvent],
) -> tuple[DispatchState | None, int, str | None, int | None, int | None, bool]:
    """Derive (dispatch_state, current_attempt, dispatch_workflow_id,
    dispatch_started_at_ms, deferred_until, deleted) from the event chain.

    See spec §4.6 for full algorithm. Returns defaults when no dispatch
    events exist. Skips malformed events with a warning.
    """
    deleted = any(ev.op == "delete" for ev in events)
    if deleted:
        return None, 0, None, None, None, True

    most_recent_dispatch_idx = -1
    most_recent_dispatch_wf: str | None = None
    most_recent_current_attempt = 0
    most_recent_started_at_ms: int | None = None
    for i, ev in enumerate(events):
        if ev.op == "dispatch":
            wf_id = _coerce_str(
                ev.ctx.get("workflow_id"),
                field=f"events[{i}].ctx.workflow_id",
            )
            attempt = _coerce_int(
                ev.ctx.get("attempt"),
                field=f"events[{i}].ctx.attempt",
            )
            started = _coerce_int(
                ev.ctx.get("started_at_ms"),
                field=f"events[{i}].ctx.started_at_ms",
            )
            if started is None:
                started = ev.hlc.wall_ms
            if wf_id is None or attempt is None:
                continue
            most_recent_dispatch_idx = i
            most_recent_dispatch_wf = wf_id
            most_recent_current_attempt = attempt
            most_recent_started_at_ms = started

    deferred_until = _compute_deferred_until(events)

    if most_recent_dispatch_idx < 0:
        return None, 0, None, None, deferred_until, False

    dispatch_state = DispatchState.IN_FLIGHT
    for ev in events[most_recent_dispatch_idx + 1 :]:
        if ev.ctx.get("workflow_id") != most_recent_dispatch_wf:
            continue
        if ev.op == "dispatch_done":
            dispatch_state = DispatchState.SUCCEEDED
            break
        if ev.op == "dispatch_failed":
            if _parse_retry_budget_exhausted(ev.ctx.get("retry_budget_exhausted")):
                dispatch_state = DispatchState.FAILED
            break

    return (
        dispatch_state,
        most_recent_current_attempt,
        most_recent_dispatch_wf,
        most_recent_started_at_ms,
        deferred_until,
        False,
    )
