from __future__ import annotations

from mahavishnu.plan_index.errors import (
    PlanIndexError,
    PlanIndexUnavailableError,
    PlanNotFoundError,
    PlanRebuildLockedError,
)


class TestErrorHierarchy:
    def test_subclasses_inherit_from_base(self) -> None:
        assert issubclass(PlanNotFoundError, PlanIndexError)
        assert issubclass(PlanIndexUnavailableError, PlanIndexError)
        assert issubclass(PlanRebuildLockedError, PlanIndexError)

    def test_not_found_carries_plan_id(self) -> None:
        err = PlanNotFoundError("abc123")
        assert err.plan_id == "abc123"
        assert "abc123" in str(err)

    def test_unavailable_carries_reason(self) -> None:
        err = PlanIndexUnavailableError("connection timeout")
        assert err.reason == "connection timeout"

    def test_locked_carries_holder_and_age(self) -> None:
        err = PlanRebuildLockedError("deadbeef/1234", 5000)
        assert err.holder == "deadbeef/1234"
        assert err.age_ms == 5000
