"""Unit tests for the settle state machine (:mod:`mahavishnu.settle.state_machine`).

These tests cover the pure transition logic with no IO and no mocking. The
property-based test at the bottom asserts the two invariants that the
state machine guarantees:

1. No illegal transition is reachable from any starting state.
2. All terminal states are absorbing.

If either invariant breaks, the state machine has a bug — see
``docs/decisions/2026-08-29-settle-vs-langgraph.md`` for the design
rationale.
"""

from __future__ import annotations

import itertools

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

pytestmark = pytest.mark.unit


from mahavishnu.settle.state_machine import (
    Binding,
    SettleAction,
    SettleRunRecord,
    SettleState,
    SettleTransitionError,
    initial_record,
    is_terminal,
    legal_next,
    transition,
)


def _sample_record(state: SettleState = SettleState.PROPOSED) -> SettleRunRecord:
    """Return a fresh record in ``state`` for unit tests."""
    rec = initial_record(
        run_ref="settle-test",
        worker_id="w-test",
        task_signature="unit-test",
        bindings=(Binding(path="foo.txt", base="hello\n"),),
    )
    # Force the state — we want every starting state for transition tests.
    if rec.state != state:
        rec = SettleRunRecord(
            run_ref=rec.run_ref,
            worker_id=rec.worker_id,
            task_signature=rec.task_signature,
            bindings=rec.bindings,
            state=state,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            transitions=rec.transitions,
        )
    return rec


def test_initial_record_is_proposed() -> None:
    rec = initial_record(
        run_ref="r1",
        worker_id="w1",
        task_signature="sig",
        bindings=(Binding(path="x", base=""),),
    )
    assert rec.state == SettleState.PROPOSED
    assert rec.transitions == ()


def test_initial_record_rejects_empty_run_ref() -> None:
    with pytest.raises(Exception):  # ValidationError, but don't pin the type
        initial_record(
            run_ref="",
            worker_id="w",
            task_signature="sig",
            bindings=(Binding(path="x", base=""),),
        )


def test_initial_record_rejects_empty_bindings() -> None:
    with pytest.raises(Exception):
        initial_record(
            run_ref="r",
            worker_id="w",
            task_signature="sig",
            bindings=(),
        )


def test_legal_next_for_proposed() -> None:
    assert legal_next(SettleState.PROPOSED) == (SettleAction.SELECT,)


def test_legal_next_for_selected() -> None:
    actions = legal_next(SettleState.SELECTED)
    assert SettleAction.APPLY in actions
    assert SettleAction.RELEASE in actions
    assert SettleAction.DISCARD in actions
    assert len(actions) == 3


def test_legal_next_for_terminal_states_is_empty() -> None:
    for state in (SettleState.APPLIED, SettleState.RELEASED, SettleState.DISCARDED):
        assert legal_next(state) == ()


def test_is_terminal_for_terminal_states() -> None:
    for state in (SettleState.APPLIED, SettleState.RELEASED, SettleState.DISCARDED):
        assert is_terminal(state) is True


def test_is_terminal_for_non_terminal_states() -> None:
    assert is_terminal(SettleState.PROPOSED) is False
    assert is_terminal(SettleState.SELECTED) is False


def test_proposed_to_selected() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    new = transition(rec, SettleAction.SELECT)
    assert new.state == SettleState.SELECTED
    assert new.run_ref == rec.run_ref
    assert len(new.transitions) == 1
    assert new.transitions[0]["action"] == "select"
    assert new.transitions[0]["from_state"] == "proposed"
    assert new.transitions[0]["to_state"] == "selected"


def test_selected_to_applied() -> None:
    rec = _sample_record(SettleState.SELECTED)
    new = transition(rec, SettleAction.APPLY)
    assert new.state == SettleState.APPLIED
    assert new.transitions[-1]["to_state"] == "applied"


def test_selected_to_released() -> None:
    rec = _sample_record(SettleState.SELECTED)
    new = transition(rec, SettleAction.RELEASE)
    assert new.state == SettleState.RELEASED


def test_selected_to_discarded() -> None:
    rec = _sample_record(SettleState.SELECTED)
    new = transition(rec, SettleAction.DISCARD)
    assert new.state == SettleState.DISCARDED


def test_cannot_select_from_selected() -> None:
    rec = _sample_record(SettleState.SELECTED)
    with pytest.raises(SettleTransitionError) as exc_info:
        transition(rec, SettleAction.SELECT)
    assert exc_info.value.details["current_state"] == "selected"
    assert exc_info.value.details["attempted_action"] == "select"


def test_cannot_apply_from_proposed() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    with pytest.raises(SettleTransitionError):
        transition(rec, SettleAction.APPLY)


def test_terminal_states_absorbing_for_every_action() -> None:
    """Every terminal state rejects every action."""
    for state, action in itertools.product(
        (SettleState.APPLIED, SettleState.RELEASED, SettleState.DISCARDED),
        SettleAction,
    ):
        rec = _sample_record(state)
        with pytest.raises(SettleTransitionError):
            transition(rec, action)


def test_transition_preserves_bindings_and_signature() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    new = transition(rec, SettleAction.SELECT)
    assert new.bindings == rec.bindings
    assert new.task_signature == rec.task_signature
    assert new.worker_id == rec.worker_id


def test_transition_appends_audit_entry() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    selected = transition(rec, SettleAction.SELECT)
    applied = transition(selected, SettleAction.APPLY)
    assert len(applied.transitions) == 2
    assert applied.transitions[0]["action"] == "select"
    assert applied.transitions[1]["action"] == "apply"


def test_transition_updates_updated_at() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    original = rec.updated_at
    new = transition(rec, SettleAction.SELECT)
    assert new.updated_at >= original


def test_to_dict_round_trip() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    selected = transition(rec, SettleAction.SELECT)
    payload = selected.to_dict()
    restored = SettleRunRecord.from_dict(payload)
    assert restored.state == selected.state
    assert restored.run_ref == selected.run_ref
    assert restored.bindings == selected.bindings
    assert restored.transitions == selected.transitions


def test_from_dict_tolerates_missing_optional_fields() -> None:
    payload = {
        "run_ref": "r",
        "worker_id": "w",
        "task_signature": "sig",
        "bindings": [{"path": "x", "base": ""}],
    }
    rec = SettleRunRecord.from_dict(payload)
    assert rec.state == SettleState.PROPOSED
    assert rec.transitions == ()


def test_from_dict_rejects_missing_run_ref() -> None:
    from mahavishnu.core.errors import ValidationError

    with pytest.raises(ValidationError):
        SettleRunRecord.from_dict({"worker_id": "w", "bindings": [{"path": "x", "base": ""}]})


def test_from_dict_rejects_missing_bindings() -> None:
    from mahavishnu.core.errors import ValidationError

    with pytest.raises(ValidationError):
        SettleRunRecord.from_dict(
            {"run_ref": "r", "worker_id": "w", "bindings": "not-a-list"}
        )


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------

_states = st.sampled_from(list(SettleState))
_actions = st.sampled_from(list(SettleAction))


@settings(max_examples=200, deadline=None)
@given(start=_states, action=_actions)
def test_no_illegal_transition_is_reachable(start: SettleState, action: SettleAction) -> None:
    """Every (state, action) pair is either legal-and-returns-a-record, or raises.

    The state machine must never silently produce a record for an
    illegal transition.
    """
    rec = _sample_record(start)
    try:
        new = transition(rec, action)
    except SettleTransitionError:
        # Illegal — that's the only acceptable outcome.
        return
    # Legal — must be in the transition table.
    assert new.state != start or is_terminal(start)
    # And must be reachable via a single transition.
    assert (start, action) in {
        (SettleState.PROPOSED, SettleAction.SELECT),
        (SettleState.SELECTED, SettleAction.APPLY),
        (SettleState.SELECTED, SettleAction.RELEASE),
        (SettleState.SELECTED, SettleAction.DISCARD),
    }


@settings(max_examples=200, deadline=None)
@given(start=_states, action=_actions)
def test_terminal_states_absorbing(start: SettleState, action: SettleAction) -> None:
    """From any terminal state, NO action is legal — every attempt raises.

    This is the absorbing-state invariant.
    """
    if not is_terminal(start):
        return  # not a terminal, skip
    rec = _sample_record(start)
    with pytest.raises(SettleTransitionError):
        transition(rec, action)


@settings(max_examples=100, deadline=None)
@given(action=_actions)
def test_initial_state_only_allows_select(action: SettleAction) -> None:
    """PROPOSED only admits SELECT; everything else is illegal."""
    rec = _sample_record(SettleState.PROPOSED)
    if action == SettleAction.SELECT:
        new = transition(rec, action)
        assert new.state == SettleState.SELECTED
    else:
        with pytest.raises(SettleTransitionError):
            transition(rec, action)


@settings(max_examples=100, deadline=None)
@given(actor=st.text(min_size=0, max_size=32))
def test_transition_preserves_actor_field(actor: str) -> None:
    """The actor field round-trips into the transition log."""
    rec = _sample_record(SettleState.PROPOSED)
    new = transition(rec, SettleAction.SELECT, actor=actor)
    assert new.transitions[-1]["actor"] == actor


def test_terminal_states_dict_round_trip() -> None:
    """SettleRunRecord.to_dict / from_dict preserves terminal state."""
    rec = _sample_record(SettleState.SELECTED)
    applied = transition(rec, SettleAction.APPLY)
    restored = SettleRunRecord.from_dict(applied.to_dict())
    assert restored.state == SettleState.APPLIED
    assert is_terminal(restored.state)


def test_pure_transition_does_not_mutate_input() -> None:
    """transition() returns a new record without mutating the input."""
    rec = _sample_record(SettleState.PROPOSED)
    original_state = rec.state
    original_transitions = rec.transitions
    _ = transition(rec, SettleAction.SELECT)
    assert rec.state == original_state
    assert rec.transitions == original_transitions


def test_created_at_preserved_across_transitions() -> None:
    rec = _sample_record(SettleState.PROPOSED)
    original_created = rec.created_at
    new = transition(rec, SettleAction.SELECT)
    assert new.created_at == original_created
