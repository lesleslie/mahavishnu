"""Task 5: _is_surface_eligible + _is_drain_eligible filters."""
from __future__ import annotations

import pytest

from mahavishnu.jot.drain import DispatchState, _is_drain_eligible, _is_surface_eligible
from mahavishnu.jot.fold import JotSummary


def _summary(**overrides) -> JotSummary:
    """Build a JotSummary with defaults that pass both filters, then apply overrides."""
    defaults = dict(
        id="e1234567890",
        short_id="123456",
        text="hello",
        status="open",
        last_modified_ms=1000,
        dispatch_state=None,
        dispatch_workflow_id=None,
        current_attempt=0,
        dispatch_started_at_ms=None,
        deferred_until=None,
        deleted=False,
    )
    defaults.update(overrides)
    return JotSummary(**defaults)  # type: ignore[arg-type]


def test_surface_eligible_basic_open_undispatched() -> None:
    """open + no dispatch_state + not deleted + not deferred → eligible."""
    assert _is_surface_eligible(_summary(), 1000) is True


def test_surface_eligible_failed_dispatch() -> None:
    """FAILED-dispatched → eligible (user can act)."""
    assert _is_surface_eligible(_summary(dispatch_state=DispatchState.FAILED), 1000) is True


def test_surface_eligible_done_jot_excluded() -> None:
    assert _is_surface_eligible(_summary(status="done"), 1000) is False


def test_surface_eligible_deleted_excluded() -> None:
    assert _is_surface_eligible(_summary(deleted=True), 1000) is False


def test_surface_eligible_in_flight_excluded() -> None:
    assert _is_surface_eligible(_summary(dispatch_state=DispatchState.IN_FLIGHT), 1000) is False


def test_surface_eligible_succeeded_excluded() -> None:
    assert _is_surface_eligible(_summary(dispatch_state=DispatchState.SUCCEEDED), 1000) is False


def test_surface_eligible_deferred_future_excluded() -> None:
    assert _is_surface_eligible(_summary(deferred_until=2000), 1000) is False


def test_surface_eligible_deferred_past_included() -> None:
    assert _is_surface_eligible(_summary(deferred_until=500), 1000) is True


def test_drain_eligible_in_flight_included() -> None:
    """_is_drain_eligible has NO dispatch_state filter."""
    assert _is_drain_eligible(_summary(dispatch_state=DispatchState.IN_FLIGHT), 1000) is True


def test_drain_eligible_done_excluded() -> None:
    assert _is_drain_eligible(_summary(status="done"), 1000) is False


def test_drain_eligible_deleted_excluded() -> None:
    assert _is_drain_eligible(_summary(deleted=True), 1000) is False


def test_drain_eligible_deferred_future_excluded() -> None:
    assert _is_drain_eligible(_summary(deferred_until=2000), 1000) is False
