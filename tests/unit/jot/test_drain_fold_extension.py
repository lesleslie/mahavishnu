"""Tests for drain sub-plan 3 fold extension.

Validates `_derive_dispatch_fields` + helpers + DispatchState enum.
See task brief: `.superpowers/sdd/2026-09-10-jot-drain/task-3-brief.md`.
"""

from __future__ import annotations

from mahavishnu.jot.drain import DispatchState
from mahavishnu.jot.events import JotEvent
from mahavishnu.jot.fold import (
    _coerce_int,
    _coerce_str,
    _compute_deferred_until,
    _derive_dispatch_fields,
    _parse_retry_budget_exhausted,
)
from mahavishnu.jot.hlc import HLC


def _ev(
    op: str,
    ctx: dict,
    *,
    wall_ms: int = 1000,
    ctr: int = 0,
    event_id: str | None = None,
) -> JotEvent:
    eid = event_id if event_id is not None else f"e{wall_ms}{ctr:02d}"
    return JotEvent(
        id=eid,
        op=op,  # type: ignore[arg-type]
        ctx=ctx,
        hlc=HLC(wall_ms=wall_ms, ctr=ctr, node="n1"),
        text="",
        created_ms=wall_ms,
    )


def test_derive_no_dispatch_yields_none_state() -> None:
    """A capture-only jot has dispatch_state=None, current_attempt=0."""
    events = [_ev("capture", {"text": "hello"})]
    state, attempt, wf, started, deferred, deleted = _derive_dispatch_fields(events)
    assert state is None
    assert attempt == 0
    assert wf is None
    assert started is None
    assert deferred is None
    assert deleted is False


def test_derive_dispatch_with_done_terminal_marks_succeeded() -> None:
    """Most recent dispatch + matching dispatch_done → SUCCEEDED."""
    events = [
        _ev("capture", {}),
        _ev("dispatch", {"workflow_id": "wf-a", "attempt": 1, "started_at_ms": 100}),
        _ev("dispatch_done", {"workflow_id": "wf-a", "summary": "ok"}),
    ]
    state, attempt, wf, started, _deferred, _deleted = _derive_dispatch_fields(events)
    assert state == DispatchState.SUCCEEDED
    assert attempt == 1
    assert wf == "wf-a"
    assert started == 100


def test_derive_dispatch_with_failed_terminal_budget_remaining_keeps_in_flight() -> None:
    """Failed dispatch on attempt 1 (budget remaining) → IN_FLIGHT, NOT FAILED."""
    events = [
        _ev("dispatch", {"workflow_id": "wf-a", "attempt": 1}),
        _ev(
            "dispatch_failed",
            {
                "workflow_id": "wf-a",
                "attempt": 1,
                "error": "x",
                "error_id": "ERROR_JOT_WORKFLOW_FAILED",
                "retry_budget_exhausted": False,  # JSON bool
            },
        ),
    ]
    state, *_ = _derive_dispatch_fields(events)
    assert state == DispatchState.IN_FLIGHT


def test_derive_dispatch_failed_budget_exhausted_marks_failed() -> None:
    """Failed dispatch on attempt 2 with retry_budget_exhausted=True → FAILED."""
    events = [
        _ev("dispatch", {"workflow_id": "wf-a", "attempt": 2}),
        _ev(
            "dispatch_failed",
            {
                "workflow_id": "wf-a",
                "attempt": 2,
                "error": "x",
                "error_id": "ERROR_JOT_WORKFLOW_FAILED",
                "retry_budget_exhausted": True,
            },
        ),
    ]
    state, attempt, *_ = _derive_dispatch_fields(events)
    assert state == DispatchState.FAILED
    assert attempt == 2


def test_derive_old_terminal_does_not_match_new_dispatch() -> None:
    """Workflow_id mismatch: old terminal from prior dispatch must NOT mark new dispatch."""
    events = [
        _ev("dispatch", {"workflow_id": "wf-a", "attempt": 1}),
        _ev("dispatch_done", {"workflow_id": "wf-a"}),
        _ev("dispatch", {"workflow_id": "wf-b", "attempt": 1}),  # manual re-dispatch
    ]
    state, attempt, wf, *_ = _derive_dispatch_fields(events)
    assert state == DispatchState.IN_FLIGHT  # not SUCCEEDED — wf-b has no terminal yet
    assert wf == "wf-b"
    assert attempt == 1


def test_derive_malformed_ctx_skips_event_continues() -> None:
    """Non-int attempt logs warning, treats as malformed, skips event."""
    events = [
        _ev("dispatch", {"workflow_id": "wf-a", "attempt": "not_an_int"}),
        _ev("dispatch", {"workflow_id": "wf-b", "attempt": 1}),
    ]
    _state, _attempt, wf, *_ = _derive_dispatch_fields(events)
    assert wf == "wf-b"  # malformed event skipped, second one wins


def test_derive_dispatch_started_at_falls_back_to_event_hlc() -> None:
    """Legacy entries without started_at_ms use ev.hlc.wall_ms."""
    events = [_ev("dispatch", {"workflow_id": "wf-a", "attempt": 1}, wall_ms=5000)]
    _state, _attempt, _wf, started, *_ = _derive_dispatch_fields(events)
    assert started == 5000  # fell back to HLC wall_ms


def test_parse_retry_budget_exhausted_accepts_bool_only() -> None:
    """Strings, ints, None → log warn + return False (defensive)."""
    assert _parse_retry_budget_exhausted(True) is True
    assert _parse_retry_budget_exhausted(False) is False
    # _parse_retry_budget_exhausted("true") → False (defensive: log warn)
    assert _parse_retry_budget_exhausted("true") is False
    assert _parse_retry_budget_exhausted(1) is False
    assert _parse_retry_budget_exhausted(None) is False


def test_coerce_int_excludes_bool_subclass() -> None:
    """Python's bool is int subclass; coerce_int must reject True/False as ints."""
    # _coerce_int(True) → None (warning); True is bool, not "real" int.
    # Since the function logs, capture log records in tests if needed; just assert return.
    assert _coerce_int(True, field="test") is None
    assert _coerce_int(42, field="test") == 42
    assert _coerce_int("42", field="test") == 42
    assert _coerce_int("not_int", field="test") is None


def test_compute_deferred_until_basic() -> None:
    """Active defer yields its until; defer_expired clears it."""
    events = [
        _ev("defer", {"until": 5000}),
    ]
    assert _compute_deferred_until(events) == 5000


def test_compute_deferred_until_with_expiry() -> None:
    """defer_expired clears the pending_until."""
    events = [
        _ev("defer", {"until": 5000}),
        _ev("defer_expired", {}),
    ]
    assert _compute_deferred_until(events) is None


def test_compute_deferred_until_malformed() -> None:
    """Malformed defer (missing/non-numeric until) → log warn, treat as no defer."""
    events = [
        _ev("defer", {}),  # missing until
        _ev("defer", {"until": "not_int"}),  # non-numeric
    ]
    assert _compute_deferred_until(events) is None


def test_coerce_str_basic() -> None:
    """Strings pass; everything else logs warn and returns None."""
    assert _coerce_str("hello", field="test") == "hello"
    assert _coerce_str(None, field="test") is None
    assert _coerce_str(42, field="test") is None