"""Tests for drain sub-plan 3 render extension.

Validates ``JotSummaryDict`` / ``JotVitalsDict`` typed surfaces and the
``_summary_dict`` / ``_vitals_dict`` projections in
``mahavishnu/jot/render.py``.

See spec §3.3.
"""

from __future__ import annotations

from mahavishnu.jot.fold import DispatchState, JotSummary
from mahavishnu.jot.render import (
    JotVitalsDict,
    _summary_dict,
    _vitals_dict,
)


def _summary(
    sid: str = "a3f9c2",
    text: str = "hello",
    status: str = "open",
    ms: int = 1700000000000,
    *,
    dispatch_state: DispatchState | None = None,
    dispatch_workflow_id: str | None = None,
    current_attempt: int = 0,
    dispatch_started_at_ms: int | None = None,
    deferred_until: int | None = None,
    deleted: bool = False,
) -> JotSummary:
    return JotSummary(
        id=sid.ljust(32, "0"),
        short_id=sid,
        text=text,
        status=status,  # type: ignore[arg-type]
        last_modified_ms=ms,
        dispatch_state=dispatch_state,
        dispatch_workflow_id=dispatch_workflow_id,
        current_attempt=current_attempt,
        dispatch_started_at_ms=dispatch_started_at_ms,
        deferred_until=deferred_until,
        deleted=deleted,
    )


# ----------------------------------------------------------------------------
# _summary_dict — base fields always populated; drain fields default to None/0
# ----------------------------------------------------------------------------


def test_summary_dict_base_fields_present() -> None:
    """Base 5 fields are always emitted regardless of dispatch history."""
    s = _summary()
    d = _summary_dict(s)
    assert d["id"] == s.id
    assert d["short_id"] == s.short_id
    assert d["text"] == "hello"
    assert d["status"] == "open"
    assert d["last_modified_ms"] == 1700000000000


def test_summary_dict_drain_fields_default_to_none_zero_false() -> None:
    """A capture-only jot has dispatch_state=None, attempt=0, workflow None,
    deferred_until None, deleted=False, dispatch_started_at_ms None.
    """
    s = _summary()
    d = _summary_dict(s)
    assert d["dispatch_state"] is None
    assert d["dispatch_workflow_id"] is None
    assert d["current_attempt"] == 0
    assert d["dispatch_started_at_ms"] is None
    assert d["deferred_until"] is None
    assert d["deleted"] is False


def test_summary_dict_in_flight_state() -> None:
    """IN_FLIGHT enum value surfaces as the literal ``"in_flight"``."""
    s = _summary(
        dispatch_state=DispatchState.IN_FLIGHT,
        dispatch_workflow_id="wf-42",
        current_attempt=1,
        dispatch_started_at_ms=1700000005000,
    )
    d = _summary_dict(s)
    assert d["dispatch_state"] == "in_flight"
    assert d["dispatch_workflow_id"] == "wf-42"
    assert d["current_attempt"] == 1
    assert d["dispatch_started_at_ms"] == 1700000005000


def test_summary_dict_succeeded_state_and_deferred_until_propagates() -> None:
    """SUCCEEDED + deferred_until surfaces exactly, deleted=True propagates."""
    s = _summary(
        dispatch_state=DispatchState.SUCCEEDED,
        dispatch_workflow_id="wf-7",
        current_attempt=2,
        dispatch_started_at_ms=1700000010000,
        deferred_until=1700000999000,
        deleted=True,
    )
    d = _summary_dict(s)
    assert d["dispatch_state"] == "succeeded"
    assert d["dispatch_workflow_id"] == "wf-7"
    assert d["current_attempt"] == 2
    assert d["dispatch_started_at_ms"] == 1700000010000
    assert d["deferred_until"] == 1700000999000
    assert d["deleted"] is True


# ----------------------------------------------------------------------------
# _vitals_dict — counts across open/done + drain dimensions
# ----------------------------------------------------------------------------


def test_vitals_dict_all_keys_present_on_empty_states() -> None:
    """Empty state list yields zero for every counter; log_event_count honored."""
    v = _vitals_dict([], log_event_count=0)
    expected_keys = {
        "open",
        "done",
        "dispatch_in_flight",
        "dispatch_failed",
        "deferred",
        "deleted",
        "log_event_count",
    }
    assert set(v.keys()) == expected_keys
    assert v == JotVitalsDict(
        open=0,
        done=0,
        dispatch_in_flight=0,
        dispatch_failed=0,
        deferred=0,
        deleted=0,
        log_event_count=0,
    )


def test_vitals_dict_counts_open_done_correctly() -> None:
    """open/done count partition of states (matches existing render_vitals)."""
    states = [
        _summary(sid="a3f9c2", status="open"),
        _summary(sid="b7e1d4", status="open"),
        _summary(sid="c5d2e1", status="done"),
    ]
    v = _vitals_dict(states, log_event_count=42)
    assert v["open"] == 2
    assert v["done"] == 1


def test_vitals_dict_counts_dispatch_states_and_deferred_deleted() -> None:
    """5 jots: 1 in-flight, 1 failed, 1 succeeded, 2 with no dispatch.
    Plus: 2 deferred, 1 deleted.
    Log event count is independent of the state counts.
    """
    states = [
        _summary(sid="01", dispatch_state=DispatchState.IN_FLIGHT),
        _summary(sid="02", dispatch_state=DispatchState.FAILED),
        _summary(sid="03", dispatch_state=DispatchState.SUCCEEDED),
        _summary(sid="04"),  # no dispatch
        _summary(sid="05"),  # no dispatch
        _summary(sid="06", deferred_until=1234),  # counts as deferred
        _summary(sid="07", deleted=True),  # counts as deleted
        _summary(sid="08", deferred_until=5678, deleted=True),  # both
    ]
    v = _vitals_dict(states, log_event_count=100)
    assert v["open"] == 8
    assert v["done"] == 0
    assert v["dispatch_in_flight"] == 1
    assert v["dispatch_failed"] == 1
    assert v["deferred"] == 2
    assert v["deleted"] == 2
    assert v["log_event_count"] == 100


def test_vitals_dict_succeeded_states_do_not_count_as_in_flight_or_failed() -> None:
    """SUCCEEDED is a terminal happy-path state — must NOT inflate failed/in-flight."""
    states = [
        _summary(sid="01", dispatch_state=DispatchState.SUCCEEDED),
        _summary(sid="02", dispatch_state=DispatchState.SUCCEEDED),
    ]
    v = _vitals_dict(states, log_event_count=10)
    assert v["dispatch_in_flight"] == 0
    assert v["dispatch_failed"] == 0
