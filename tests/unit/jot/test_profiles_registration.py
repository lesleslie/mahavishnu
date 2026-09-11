"""CI guard: 14 jot tools registered in profiles.py.

Sub-plan 3 (Drain) appended ``jot_drain``, ``jot_dispatch``, ``jot_defer``,
``jot_delete``, ``jot_retry``, ``jot_resurface`` to the 8-tool baseline.
See ``test_drain_profiles_registration.py`` for the focused drain delta
guard (those tests are a subset of this one's invariant).
"""
from __future__ import annotations

from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS, REGISTRATION_MAP

EXPECTED = {
    # Pre-drain baseline (Task 13).
    "jot_list", "jot_show", "jot_add", "jot_edit",
    "jot_done", "jot_reopen", "jot_vitals", "jot_search",
    # Drain additions (sub-plan 3).
    "jot_drain", "jot_dispatch", "jot_defer",
    "jot_delete", "jot_retry", "jot_resurface",
}


def test_fourteen_jot_tools_in_full_registrations() -> None:
    """All 14 jot tools registered in the FULL profile."""
    found = {name for name in FULL_REGISTRATIONS if name.startswith("jot_")}
    assert found == EXPECTED


def test_fourteen_jot_tools_in_registration_map() -> None:
    """Each tool has a path in REGISTRATION_MAP."""
    found = {name for name in REGISTRATION_MAP if name.startswith("jot_")}
    assert found == EXPECTED
