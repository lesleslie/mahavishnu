"""CI guard: pin ``_register_plan_tools`` into the FULL profile registration.

Without these tests a future refactor that drops the plan_* tools from
``FULL_REGISTRATIONS`` / ``REGISTRATION_MAP`` (or accidentally replaces the
factory with a non-callable) would silently strip the five ``plan_*`` MCP
tools at runtime. The drift would be invisible until an operator ran a
``plan_list`` call against a live FULL-profile server.

This complements the wider ``test_tool_profile_drift.py`` family which
covers the historical drift surface (Phase 0 W0 wiring). Task 12 added
the plan_index registration dance as a five-edit change (bootstrap.py +
profiles.py + this file); the three tests below pin the dance.
"""

from __future__ import annotations

from mahavishnu.mcp.tools import profiles


class TestPlanToolsProfileRegistration:
    def test_plan_tools_in_full_registrations(self) -> None:
        assert "_register_plan_tools" in profiles.FULL_REGISTRATIONS

    def test_plan_tools_in_registration_map(self) -> None:
        assert "_register_plan_tools" in profiles.REGISTRATION_MAP

    def test_registration_map_values_are_callable(self) -> None:
        for key, factory in profiles.REGISTRATION_MAP.items():
            assert callable(factory), f"{key} is not callable"
