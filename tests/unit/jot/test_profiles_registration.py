"""CI guard: 8 jot tools registered in profiles.py."""
from __future__ import annotations

from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS, REGISTRATION_MAP

EXPECTED = {
    "jot_list", "jot_show", "jot_add", "jot_edit",
    "jot_done", "jot_reopen", "jot_vitals", "jot_search",
}


def test_eight_jot_tools_in_full_registrations() -> None:
    """All 8 jot tools registered in the FULL profile."""
    found = {name for name in FULL_REGISTRATIONS if name.startswith("jot_")}
    assert found == EXPECTED


def test_eight_jot_tools_in_registration_map() -> None:
    """Each tool has a path in REGISTRATION_MAP."""
    found = {name for name in REGISTRATION_MAP if name.startswith("jot_")}
    assert found == EXPECTED