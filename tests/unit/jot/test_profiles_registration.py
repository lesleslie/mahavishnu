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
    "mahavishnu_jot_list",
    "mahavishnu_jot_show",
    "mahavishnu_jot_add",
    "mahavishnu_jot_edit",
    "mahavishnu_jot_done",
    "mahavishnu_jot_reopen",
    "mahavishnu_jot_vitals",
    "mahavishnu_jot_search",
    # Drain additions (sub-plan 3).
    "mahavishnu_jot_drain",
    "mahavishnu_jot_dispatch",
    "mahavishnu_jot_defer",
    "mahavishnu_jot_delete",
    "mahavishnu_jot_retry",
    "mahavishnu_jot_resurface",
}


def test_fourteen_jot_tools_in_full_registrations() -> None:
    """All 14 jot tools registered in the FULL profile."""
    found = {name for name in FULL_REGISTRATIONS if name.startswith(("jot_", "mahavishnu_jot_"))}
    assert found == EXPECTED


def test_fourteen_jot_tools_in_registration_map() -> None:
    """Each tool has a path in REGISTRATION_MAP."""
    found = {name for name in REGISTRATION_MAP if name.startswith(("jot_", "mahavishnu_jot_"))}
    assert found == EXPECTED
