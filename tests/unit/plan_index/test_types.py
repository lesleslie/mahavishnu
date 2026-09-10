"""Tests for plan_index TypedDict surface types."""

from __future__ import annotations

from typing import get_args, get_type_hints

from mahavishnu.plan_index.types import (
    PlanDegradedDict,
    PlanListResultDict,
    PlanRebuildErrorDict,
    PlanRebuildStatusDict,
    PlanRecordDict,
    PlanVitalsDict,
    RebuildErrorCtx,
    TripwireState,
)


class TestTripwireState:
    def test_exactly_four_distinct_states(self) -> None:
        states: tuple[TripwireState, ...] = get_args(TripwireState)
        assert len(states) == 4
        assert len(set(states)) == 4  # all distinct
        assert "ok" in states
        assert "review_cadence_lagging" in states


class TestPlanRecordDict:
    def test_required_fields_present(self) -> None:
        hints = get_type_hints(PlanRecordDict)
        for required in (
            "plan_id", "path", "title", "status", "role", "topic",
            "date", "last_reviewed", "blocks_on", "sha", "repo",
            "updated_at_ms",
        ):
            assert required in hints, f"missing required field: {required}"


class TestRebuildErrorCtx:
    def test_all_fields_not_required(self) -> None:
        hints = get_type_hints(RebuildErrorCtx, include_extras=True)
        # NotRequired fields have the marker
        assert "plan_id" in hints
        assert "path_hash" in hints  # never raw path
        assert "op" in hints


class TestPlanVitalsTripwire:
    def test_tripwire_field_uses_literal(self) -> None:
        hints = get_type_hints(PlanVitalsDict)
        assert hints["tripwire"] is TripwireState


class TestPlanRebuildStatusLockHeldBy:
    def test_lock_held_by_field_is_optional(self) -> None:
        hints = get_type_hints(PlanRebuildStatusDict)
        assert "lock_held_by" in hints


class TestPlanListResultDictStatus:
    def test_status_field_uses_literal(self) -> None:
        hints = get_type_hints(PlanListResultDict)
        # Literal["ok", "degraded"] — not dict[str, Any]
        args = get_args(hints["status"])
        assert args == ("ok", "degraded")


class TestPlanRebuildErrorCtx:
    def test_ctx_is_typed_dict_not_dict(self) -> None:
        hints = get_type_hints(PlanRebuildErrorDict)
        # TypedDict hints are typed fields, not dict[str, Any]
        assert hints["ctx"] is RebuildErrorCtx


class TestPlanDegradedDictNoStatusField:
    def test_no_status_literal_field(self) -> None:
        hints = get_type_hints(PlanDegradedDict)
        # The type IS the discriminator; single-value Literal is a code smell.
        assert "status" not in hints
