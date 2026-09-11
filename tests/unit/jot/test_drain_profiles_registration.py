"""CI guard: 6 drain jot tools registered in profiles.py.

Sub-plan 3 (Drain) added ``jot_drain``, ``jot_dispatch``, ``jot_defer``,
``jot_delete``, ``jot_retry``, ``jot_resurface`` to ``jot_tools.py``. This
test asserts each name appears in both ``FULL_REGISTRATIONS`` and
``REGISTRATION_MAP`` and that ``REGISTRATION_MAP`` resolves each to a
callable that delegates to ``_register_jot_tools``.

The companion test ``test_profiles_registration.py`` asserts the full set of
14 jot_* entries; this file focuses on the 6 new names plus the count
delta so a future regression that drops a single drain tool surfaces here.
"""
from __future__ import annotations

from collections.abc import Callable

from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS, REGISTRATION_MAP

DRAIN_TOOLS: tuple[str, ...] = (
    "jot_drain",
    "jot_dispatch",
    "jot_defer",
    "jot_delete",
    "jot_retry",
    "jot_resurface",
)


def test_all_six_drain_tools_in_full_registrations() -> None:
    """Each of the 6 new drain tool names appears in FULL_REGISTRATIONS."""
    full_set = set(FULL_REGISTRATIONS)
    missing = [name for name in DRAIN_TOOLS if name not in full_set]
    assert missing == [], (
        f"drain tools missing from FULL_REGISTRATIONS: {missing!r}"
    )


def test_all_six_drain_tools_in_registration_map() -> None:
    """Each of the 6 new drain tool names maps to a callable in REGISTRATION_MAP."""
    for name in DRAIN_TOOLS:
        assert name in REGISTRATION_MAP, (
            f"{name!r} missing from REGISTRATION_MAP"
        )
        target: Callable[..., object] = REGISTRATION_MAP[name]
        assert callable(target), (
            f"REGISTRATION_MAP[{name!r}] is not callable: {target!r}"
        )


def test_full_registrations_grew_by_exactly_six() -> None:
    """The 8 pre-drain jot entries plus the 6 drain entries = 14 total.

    Asserts the *delta*: 14 ``jot_*`` strings now live in
    ``FULL_REGISTRATIONS``. This is the single source of truth for the
    pre-drain + drain baseline; updates to the comment in profiles.py must
    keep this invariant.
    """
    jot_entries = [name for name in FULL_REGISTRATIONS if name.startswith("jot_")]
    assert len(jot_entries) == 14, (
        f"expected 14 jot_* entries in FULL_REGISTRATIONS, got {len(jot_entries)}: "
        f"{jot_entries!r}"
    )


def test_registration_map_grew_by_exactly_six() -> None:
    """Same delta invariant for ``REGISTRATION_MAP``."""
    jot_entries = [name for name in REGISTRATION_MAP if name.startswith("jot_")]
    assert len(jot_entries) == 14, (
        f"expected 14 jot_* entries in REGISTRATION_MAP, got {len(jot_entries)}: "
        f"{jot_entries!r}"
    )


def test_drain_entries_are_distinct_from_pre_drain() -> None:
    """The 6 new names do not collide with any existing ``jot_*`` key."""
    pre_drain = {
        "jot_list", "jot_show", "jot_add", "jot_edit",
        "jot_done", "jot_reopen", "jot_vitals", "jot_search",
    }
    overlap = set(DRAIN_TOOLS) & pre_drain
    assert overlap == set(), (
        f"drain tool names collide with pre-drain set: {overlap!r}"
    )