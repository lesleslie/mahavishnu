"""Tests for Permission.READ_PLAN_INDEX enum member."""

from __future__ import annotations

from mahavishnu.core.permissions import Permission


class TestReadPlanIndexPermission:
    def test_permission_exists(self) -> None:
        assert hasattr(Permission, "READ_PLAN_INDEX")
        assert Permission.READ_PLAN_INDEX.name == "READ_PLAN_INDEX"
        assert Permission.READ_PLAN_INDEX.value == "read_plan_index"

    def test_permission_in_values(self) -> None:
        assert "read_plan_index" in [p.value for p in Permission]
