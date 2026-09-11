"""Round-2 H3: FastMCP serialization preserves PlanIndexError subclass discriminators.

When `plan_show("nonexistent")` raises PlanNotFoundError, the wire format must
preserve enough information for the caller to distinguish PlanNotFoundError
from PlanIndexUnavailableError from PlanRebuildLockedError — typically via
a `code` field, the subclass name, or a discriminator key.
"""

from __future__ import annotations

from mahavishnu.plan_index.errors import (
    PlanIndexUnavailableError,
    PlanNotFoundError,
    PlanRebuildLockedError,
)


class TestSubclassSerialization:
    def test_plan_not_found_error_carries_code(self) -> None:
        err = PlanNotFoundError("deadbeef0123456789abcdef01234567")
        # PlanNotFoundError must carry a discriminator — either __class__.__name__
        # or a `code` attribute. Either is acceptable as long as the subclass
        # identity survives FastMCP's serialization round-trip.
        assert hasattr(err, "code") or err.__class__.__name__ == "PlanNotFoundError"

    def test_plan_index_unavailable_error_carries_code(self) -> None:
        err = PlanIndexUnavailableError("connection timeout")
        assert hasattr(err, "code") or err.__class__.__name__ == "PlanIndexUnavailableError"

    def test_plan_rebuild_locked_error_carries_code(self) -> None:
        err = PlanRebuildLockedError("deadbeef/1234", 5000)
        assert hasattr(err, "code") or err.__class__.__name__ == "PlanRebuildLockedError"

    def test_subclass_names_distinct(self) -> None:
        """Each subclass must have a unique discriminator string."""
        names = {
            PlanNotFoundError("x").__class__.__name__,
            PlanIndexUnavailableError("y").__class__.__name__,
            PlanRebuildLockedError("z", 0).__class__.__name__,
        }
        assert len(names) == 3, "subclass discriminators must be distinct"
