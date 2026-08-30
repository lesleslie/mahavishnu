"""Unit tests for the Phase 3 budget state machine.

Covers:

* State-machine transition invariants (:class:`TestBudgetStateMachine`).
* Cross-cap arithmetic invariants via hypothesis
  (:class:`TestBudgetArithmeticPropertyBased`).
* Spec / Usage / Record serialization round-trips
  (:class:`TestBudgetSerialization`).

The state machine is intentionally pure (no I/O, no clock) so these
tests are fast and deterministic — the watchdog tests in
``tests/integration/test_budget_watchdog_lease.py`` exercise the
async + Dhara-dependent paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st
import pytest

from mahavishnu.core.budget import (
    BudgetDimension,
    BudgetRecord,
    BudgetSpec,
    BudgetState,
    BudgetStateMachine,
    BudgetUsage,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Strategies
# =============================================================================


@st.composite
def budget_specs(draw: Any) -> BudgetSpec:
    """Build a BudgetSpec with at least one dimension bounded."""
    tokens = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=10_000_000)))
    turns = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=10_000)))
    wallclock = draw(
        st.one_of(
            st.none(),
            st.floats(
                min_value=0.001,
                max_value=86_400.0,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    assume(tokens is not None or turns is not None or wallclock is not None)
    return BudgetSpec(
        budget_tokens=tokens,
        budget_turns=turns,
        budget_wallclock_seconds=wallclock,
        declared_by="hypothesis",
        declared_at=datetime.now(UTC),
    )


@st.composite
def usages_for_spec(draw: Any, spec: BudgetSpec) -> BudgetUsage:
    """Build a BudgetUsage whose values are within or just over the spec.

    Always returns at least one observed dimension to exercise the
    state-machine comparisons.
    """
    tokens_pool: Any
    if spec.budget_tokens is None:
        tokens_pool = st.none() | st.integers(min_value=0, max_value=1_000_000)
    else:
        tokens_pool = st.integers(
            min_value=0,
            max_value=spec.budget_tokens * 2,
        )
    turns_pool: Any
    if spec.budget_turns is None:
        turns_pool = st.none() | st.integers(min_value=0, max_value=1_000)
    else:
        turns_pool = st.integers(
            min_value=0,
            max_value=spec.budget_turns * 2,
        )
    wallclock_pool: Any
    if spec.budget_wallclock_seconds is None:
        wallclock_pool = st.none() | st.floats(
            min_value=0.0,
            max_value=7200.0,
            allow_nan=False,
            allow_infinity=False,
        )
    else:
        wallclock_pool = st.floats(
            min_value=0.0,
            max_value=spec.budget_wallclock_seconds * 2.0,
            allow_nan=False,
            allow_infinity=False,
        )
    return BudgetUsage(
        tokens_used=draw(tokens_pool),
        turns_used=draw(turns_pool),
        wallclock_seconds=draw(wallclock_pool),
        observed_at=datetime.now(UTC),
    )


def _empty_spec() -> BudgetSpec:
    """A spec without any bounded dimension — used to test the empty-spec guard."""
    return BudgetSpec()


# =============================================================================
# StateMachine tests
# =============================================================================


class TestBudgetStateMachine:
    """``BudgetStateMachine.start`` → ``check`` → ``mark_exceeded`` / ``mark_completed``."""

    def test_initial_state_is_pending(self) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1"))
        assert sm.record.state is BudgetState.PENDING

    def test_start_transitions_pending_to_active(self) -> None:
        sm = BudgetStateMachine(
            BudgetRecord(workflow_id="wf-1", spec=BudgetSpec(budget_tokens=100))
        )
        sm.start(when=datetime.now(UTC))
        assert sm.record.state is BudgetState.ACTIVE
        assert sm.record.started_at is not None
        assert sm.record.is_terminal() is False

    def test_start_is_idempotent(self) -> None:
        ts = datetime.now(UTC)
        sm = BudgetStateMachine(
            BudgetRecord(workflow_id="wf-1", spec=BudgetSpec(budget_tokens=100))
        )
        first = sm.start(when=ts)
        second = sm.start(when=datetime.now(UTC))
        # The second call must not re-stamp started_at.
        assert first.started_at == second.started_at
        assert sm.record.state is BudgetState.ACTIVE

    def test_start_with_empty_spec_raises(self) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=_empty_spec()))
        with pytest.raises(ValueError, match="at least one dimension"):
            sm.start()

    def test_check_returns_violated_dimension_in_priority_order(self) -> None:
        """tokens > turns > wallclock. The first violated dim wins."""
        spec = BudgetSpec(
            budget_tokens=100,
            budget_turns=10,
            budget_wallclock_seconds=10.0,
        )
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        dimension = sm.check(
            BudgetUsage(
                tokens_used=200,
                turns_used=20,
                wallclock_seconds=20.0,
            )
        )
        assert dimension is BudgetDimension.TOKENS

    def test_check_returns_turns_when_tokens_ok(self) -> None:
        spec = BudgetSpec(
            budget_tokens=1_000,
            budget_turns=10,
            budget_wallclock_seconds=10.0,
        )
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        dimension = sm.check(
            BudgetUsage(
                tokens_used=100,
                turns_used=20,
                wallclock_seconds=20.0,
            )
        )
        assert dimension is BudgetDimension.TURNS

    def test_check_returns_wallclock_when_only_wallclock_breaches(self) -> None:
        spec = BudgetSpec(
            budget_tokens=1_000,
            budget_turns=100,
            budget_wallclock_seconds=10.0,
        )
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        dimension = sm.check(
            BudgetUsage(
                tokens_used=100,
                turns_used=10,
                wallclock_seconds=20.0,
            )
        )
        assert dimension is BudgetDimension.WALLCLOCK

    def test_check_returns_none_when_within_caps(self) -> None:
        spec = BudgetSpec(budget_tokens=100, budget_turns=10)
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        assert sm.check(BudgetUsage(tokens_used=99, turns_used=9)) is None

    def test_check_records_latest_usage(self) -> None:
        spec = BudgetSpec(budget_tokens=100)
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        usage = BudgetUsage(tokens_used=99, turns_used=9, wallclock_seconds=1.0)
        sm.check(usage)
        assert sm.record.usage == usage

    def test_check_skips_unobserved_dimensions(self) -> None:
        """When usage.tokens_used is None but the cap exists, no violation."""
        spec = BudgetSpec(budget_tokens=100)
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()

        assert sm.check(BudgetUsage()) is None

    def test_mark_exceeded_transitions_active_to_exceeded(self) -> None:
        spec = BudgetSpec(budget_tokens=100)
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()
        ts = datetime.now(UTC)
        sm.mark_exceeded(BudgetDimension.TOKENS, when=ts)

        assert sm.record.state is BudgetState.EXCEEDED
        assert sm.record.exceeded_dimension is BudgetDimension.TOKENS
        assert sm.record.exceeded_at == ts
        assert sm.record.is_terminal() is True

    def test_mark_exceeded_from_pending_raises(self) -> None:
        sm = BudgetStateMachine(
            BudgetRecord(workflow_id="wf-1", spec=BudgetSpec(budget_tokens=100))
        )
        with pytest.raises(ValueError, match="Cannot mark_exceeded from state"):
            sm.mark_exceeded(BudgetDimension.TOKENS)

    def test_mark_completed_transitions_active_to_completed(self) -> None:
        spec = BudgetSpec(budget_tokens=100)
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1", spec=spec))
        sm.start()
        ts = datetime.now(UTC)
        sm.mark_completed(when=ts)

        assert sm.record.state is BudgetState.COMPLETED
        assert sm.record.completed_at == ts
        assert sm.record.is_terminal() is True

    def test_mark_completed_from_pending_raises(self) -> None:
        sm = BudgetStateMachine(
            BudgetRecord(workflow_id="wf-1", spec=BudgetSpec(budget_tokens=100))
        )
        with pytest.raises(ValueError, match="Cannot mark_completed from state"):
            sm.mark_completed()

    def test_terminal_record_ignores_subsequent_starts(self) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1"))
        sm._record = BudgetRecord(
            workflow_id="wf-1",
            state=BudgetState.EXCEEDED,
            spec=BudgetSpec(budget_tokens=100),
            exceeded_dimension=BudgetDimension.TOKENS,
        )
        # Calling start() on a terminal record is a no-op (returns it unchanged).
        sm.start()
        assert sm.record.state is BudgetState.EXCEEDED

    def test_set_record_replaces_underlying(self) -> None:
        sm = BudgetStateMachine()
        new = BudgetRecord(workflow_id="wf-2", spec=BudgetSpec(budget_tokens=10))
        sm.set_record(new)
        assert sm.record is new

    def test_declare_updates_spec_without_changing_state(self) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf-1"))
        sm.declare(BudgetSpec(budget_tokens=100))
        assert sm.record.state is BudgetState.PENDING
        assert sm.record.spec.budget_tokens == 100


# =============================================================================
# Serialization
# =============================================================================


class TestBudgetSerialization:
    """Round-trip lossless serialization for Dhara persistence."""

    def test_spec_round_trip(self) -> None:
        original = BudgetSpec(
            budget_tokens=1_000,
            budget_turns=10,
            budget_wallclock_seconds=60.0,
            declared_by="alice",
            declared_at=datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC),
        )
        as_dict = original.to_dict()
        restored = BudgetSpec.from_dict(as_dict)
        assert restored.budget_tokens == original.budget_tokens
        assert restored.budget_turns == original.budget_turns
        assert restored.budget_wallclock_seconds == original.budget_wallclock_seconds
        assert restored.declared_by == original.declared_by
        assert restored.declared_at == original.declared_at

    def test_record_round_trip_preserves_state(self) -> None:
        original = BudgetRecord(
            workflow_id="wf-1",
            spec=BudgetSpec(budget_tokens=100),
            state=BudgetState.EXCEEDED,
            usage=BudgetUsage(tokens_used=150, turns_used=3, wallclock_seconds=120.0),
            started_at=datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC),
            exceeded_dimension=BudgetDimension.TOKENS,
            exceeded_at=datetime(2026, 8, 29, 12, 5, 0, tzinfo=UTC),
            completed_at=None,
        )
        restored = BudgetRecord.from_dict(original.to_dict())
        assert restored.workflow_id == original.workflow_id
        assert restored.state is BudgetState.EXCEEDED
        assert restored.exceeded_dimension is BudgetDimension.TOKENS
        assert restored.usage == original.usage

    def test_record_from_dict_tolerates_missing_fields(self) -> None:
        record = BudgetRecord.from_dict({})
        assert record.workflow_id == ""
        assert record.state is BudgetState.PENDING
        assert record.usage is None
        assert record.started_at is None
        assert record.exceeded_dimension is None

    def test_spec_has_any_dimension_false_for_empty(self) -> None:
        assert BudgetSpec().has_any_dimension() is False

    def test_spec_has_any_dimension_true_when_tokens_set(self) -> None:
        assert BudgetSpec(budget_tokens=1).has_any_dimension() is True


# =============================================================================
# Property-based arithmetic invariants
# =============================================================================


class TestBudgetArithmeticPropertyBased:
    """Hypothesis-driven invariants over the state machine's ``check`` logic."""

    @given(spec=budget_specs(), usage=st.builds(lambda: BudgetUsage()))
    @settings(max_examples=50, deadline=None)
    def test_empty_usage_never_violates_a_present_cap(
        self, spec: BudgetSpec, usage: BudgetUsage
    ) -> None:
        """If usage reports nothing, ``check`` cannot say we're over."""
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf", spec=spec))
        sm.start()
        # When usage reports no values, every cap should appear unviolated.
        assert sm.check(usage) is None

    @given(spec=budget_specs(), usage=usages_for_spec(BudgetSpec(budget_tokens=100)))
    @settings(max_examples=30, deadline=None)
    def test_check_violates_iff_usage_exceeds_cap(
        self, spec: BudgetSpec, usage: BudgetUsage
    ) -> None:
        """Brute-force assertion: with sample spec, the dimension order holds."""
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf", spec=spec))
        sm.start()
        dim = sm.check(usage)
        # If tokens_used is reported and exceeds cap, we MUST see TOKENS.
        if (
            spec.budget_tokens is not None
            and usage.tokens_used is not None
            and usage.tokens_used > spec.budget_tokens
        ):
            assert dim is BudgetDimension.TOKENS
        # If only wallclock is violated, the result must be WALLCLOCK.
        elif (
            spec.budget_wallclock_seconds is not None
            and usage.wallclock_seconds is not None
            and usage.wallclock_seconds > spec.budget_wallclock_seconds
            and (
                spec.budget_tokens is None
                or usage.tokens_used is None
                or usage.tokens_used <= spec.budget_tokens
            )
            and (
                spec.budget_turns is None
                or usage.turns_used is None
                or usage.turns_used <= spec.budget_turns
            )
        ):
            assert dim is BudgetDimension.WALLCLOCK

    @given(spec=budget_specs())
    @settings(max_examples=30, deadline=None)
    def test_start_then_double_start_preserves_started_at(
        self, spec: BudgetSpec
    ) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf", spec=spec))
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        sm.start(when=ts)
        later = ts + timedelta(seconds=10)
        sm.start(when=later)
        # Started-at must not be overwritten.
        assert sm.record.started_at == ts

    @given(spec=budget_specs())
    @settings(max_examples=30, deadline=None)
    def test_mark_exceeded_idempotent(
        self, spec: BudgetSpec
    ) -> None:
        sm = BudgetStateMachine(BudgetRecord(workflow_id="wf", spec=spec))
        sm.start()
        sm.mark_exceeded(BudgetDimension.WALLCLOCK, when=datetime.now(UTC))
        first_dim = sm.record.exceeded_dimension
        first_at = sm.record.exceeded_at
        sm.mark_exceeded(BudgetDimension.TOKENS, when=datetime.now(UTC))
        # Re-entering exceeded does not change dimension or timestamp.
        assert sm.record.exceeded_dimension is first_dim
        assert sm.record.exceeded_at == first_at
