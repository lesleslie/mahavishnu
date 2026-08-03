"""Regression tests for tool-profile drift in Mahavishnu's MCP server.

Pins the contract documented in
``docs/architecture/MEMORY_ARCHITECTURE.md`` Section 5 (Contract 5.x):
tool-profile gating must resolve to an actual dispatch site so a
declared-but-unwired profile name cannot silently no-op.

The mechanism (verified against ``mahavishnu/mcp/bootstrap.py`` and
``mahavishnu/mcp/lifecycle.py``) is ``string-gated dispatch``:

    if "_register_<group>_tools" in methods_set:
        registrar(server)

plus a tuple dispatch table ``_OPTIONAL_TOOL_BLOCKS`` for the FULL-only
groups. The names are NOT methods on ``FastMCPServer`` -- the docstring's
"scheduled vs called" framing targets exactly this dispatch topology.

Path note: existing MCP unit tests live at ``tests/unit/mcp/`` (the
sibling ``test_profiles.py`` ships alongside this file). The user's
brief referenced ``mahavishnu/tests/unit/mcp/``; that prefix does not
exist (Mahavishnu is a package, not a nested ``mahavishnu/``). The
file below lands in the canonical tests root.
"""

from __future__ import annotations

import re
from pathlib import Path

from mcp_common.tools import ToolProfile
import pytest

from mahavishnu.mcp.tools.profiles import (
    FULL_REGISTRATIONS,
    MINIMAL_REGISTRATIONS,
    PROFILE_REGISTRATIONS,
    STANDARD_REGISTRATIONS,
)

pytestmark = pytest.mark.unit


# -- Path helpers ------------------------------------------------------------


def _src_path(*parts: str) -> Path:
    """Resolve a path relative to the mahavishnu repo root."""
    return Path(__file__).resolve().parents[3].joinpath(*parts)


BOOTSTRAP_SRC = _src_path(
    "mahavishnu", "mcp", "bootstrap.py"
).read_text(encoding="utf-8")
LIFECYCLE_SRC = _src_path(
    "mahavishnu", "mcp", "lifecycle.py"
).read_text(encoding="utf-8")
SERVER_CORE_SRC = _src_path(
    "mahavishnu", "mcp", "server_core.py"
).read_text(encoding="utf-8")


# -- Dispatch-site extractors -------------------------------------------------


# A "string-gated" site is the bootstrap.py idiom:
#     if "<name>" in methods_set:
_STRING_GATE_RE = re.compile(r'"(_register_[A-Za-z0-9_]+)"\s+in\s+methods_set')


def _extract_string_gated(source: str = BOOTSTRAP_SRC) -> set[str]:
    """Return every ``_register_*`` name referenced via ``name in methods_set``."""
    return set(_STRING_GATE_RE.findall(source))


# A "table-gated" site is the ``_OPTIONAL_TOOL_BLOCKS`` tuple of
# ``(name, registrar)`` pairs that bootstrap iterates at runtime.
_TABLE_KEY_RE = re.compile(r'"(_register_[A-Za-z0-9_]+)"')


def _extract_optional_block_body(source: str) -> str:
    """Return the body of the ``_OPTIONAL_TOOL_BLOCKS`` tuple (the part inside the outer parens).

    The tuple body contains nested parens via the ``Callable[...]`` type
    annotation, so a balanced-paren walker is safer than a regex.
    """
    header = re.search(r"_OPTIONAL_TOOL_BLOCKS\s*:\s*tuple[^\n]*=\s*\(", source)
    if header is None:
        return ""
    start = header.end()
    depth = 1
    for offset, ch in enumerate(source[start:]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return source[start : start + offset]
    return ""


def _extract_table_gated(source: str = BOOTSTRAP_SRC) -> set[str]:
    """Return every ``_register_*`` key declared in ``_OPTIONAL_TOOL_BLOCKS``."""
    body = _extract_optional_block_body(source)
    return set(_TABLE_KEY_RE.findall(body))


def _extract_unconditional_registrations(source: str = BOOTSTRAP_SRC) -> set[str]:
    """Return profile names that bootstrap registers unconditionally (always-on).

    Profiles place a ``_register_*`` name in MINIMAL/STANDARD/FULL, but the
    registrar function may also be called after the gated dispatch loop.
    That name is "marker-only" -- the registration has no profile effect.
    """
    # Every registrar is named ``register_<group>_tools`` in
    # ``mahavishnu.mcp.tools.*``; bootstrap imports them and calls them
    # without a ``methods_set`` check after the gated block.
    post_gate = source.split("_register_optional_tools(server, methods_set)")[-1]
    keys: set[str] = set(_TABLE_KEY_RE.findall(post_gate))
    keys.update(
        re.findall(
            r"register_([a-z_]+_tools)\s*\(", post_gate,
        ),
    )
    # Map back to the ``_register_*`` form (the profile-list naming).
    return {f"_register_{name}" for name in keys}


# -- Tests -------------------------------------------------------------------


def _all_profile_names() -> set[str]:
    """Return every name declared across PROFILE_REGISTRATIONS, with duplicates removed."""
    names: set[str] = set()
    for lst in PROFILE_REGISTRATIONS.values():
        names.update(lst)
    return names


def test_no_orphan_registrations() -> None:
    """Every ``PROFILE_REGISTRATIONS`` name must resolve to a dispatch site.

    Resolution surface (any one of):
    1. ``bootstrap.py`` string-gated site: ``if "<name>" in methods_set``
    2. ``bootstrap.py`` table-gated site: key in ``_OPTIONAL_TOOL_BLOCKS``
    3. ``bootstrap.py`` unconditional: registrar invoked outside the gated
       dispatch loop (always-on tool group whose profile marker is nominal)

    Any name absent from all three surfaces is ORPHANED: declared in a
    profile but never wired to a registrar. This is the drift vector the
    doc warns about ("scheduled vs called").
    """
    names = _all_profile_names()
    string_gated = _extract_string_gated()
    table_gated = _extract_table_gated()
    unconditional = _extract_unconditional_registrations()

    dispatched = string_gated | table_gated | unconditional
    orphans = sorted(names - dispatched)

    assert not orphans, (
        "Profile names with no dispatch site in mahavishnu/mcp/bootstrap.py: "
        f"{orphans}. Each PROFILE_REGISTRATIONS entry must either gate a "
        "registrar (string-gate or _OPTIONAL_TOOL_BLOCKS key) or be "
        "registered unconditionally. See "
        "docs/architecture/MEMORY_ARCHITECTURE.md Section 5 Contract 5.x."
    )


def test_profile_subset_invariant() -> None:
    """MINIMAL_REGISTRATIONS ⊆ STANDARD_REGISTRATIONS ⊆ FULL_REGISTRATIONS.

    Each higher tier must be a strict superset so callers can rely on
    "if STANDARD, X is loaded" semantics. Standard is the doc-pinned
    contract for daily-development surfaces.
    """
    minimal_set = set(MINIMAL_REGISTRATIONS)
    standard_set = set(STANDARD_REGISTRATIONS)
    full_set = set(FULL_REGISTRATIONS)

    assert minimal_set <= standard_set, (
        f"MINIMAL has names absent from STANDARD: {minimal_set - standard_set}"
    )
    assert standard_set <= full_set, (
        f"STANDARD has names absent from FULL: {standard_set - full_set}"
    )


def test_profile_application_present() -> None:
    """The lifecycle must import and reference both profile symbols.

    Specifically, ``mahavishnu/mcp/lifecycle.py`` -- the only caller of
    ``register_profile_tools`` -- must ``import PROFILE_REGISTRATIONS``
    and ``get_active_profile`` and use them to drive registration.
    """
    assert "PROFILE_REGISTRATIONS" in LIFECYCLE_SRC, (
        "lifecycle.py is missing the `PROFILE_REGISTRATIONS` import -- "
        "start_server() cannot look up the active profile's registrations."
    )
    assert "get_active_profile" in LIFECYCLE_SRC, (
        "lifecycle.py is missing the `get_active_profile` call -- the "
        "active profile is never resolved, so registration runs at the "
        "default tier silently."
    )
    # Verify start_server actually consults PROFILE_REGISTRATIONS to pick
    # the methods list. Without this the import would be dead code.
    assert re.search(
        r"PROFILE_REGISTRATIONS\s*\[", LIFECYCLE_SRC,
    ), "lifecycle.py never indexes PROFILE_REGISTRATIONS[...] -- registration cannot dispatch."

    # And discover_tools (server_core) must surface profile state.
    # This guards against the discover_tools response shape drifting away
    # from the profile summary the operator dashboard reads.
    assert "PROFILE_REGISTRATIONS" in SERVER_CORE_SRC, (
        "server_core.discover_tools() lost its PROFILE_REGISTRATIONS import -- "
        "the MCP read surface stops surfacing `profile_methods_scheduled`."
    )
    assert "get_active_profile" in SERVER_CORE_SRC, (
        "server_core.discover_tools() lost its get_active_profile() call -- "
        "the profile field is no longer reflective of the env var."
    )


def test_lazy_profile_methods_recoverable() -> None:
    """Every FULL_REGISTRATIONS name must resolve to a dispatch site in bootstrap.py.

    This is the strict version of ``test_no_orphan_registrations``: it
    fails specifically when a FULL-tier feature group is declared but
    not wired, catching the "function got renamed or removed" case.
    """
    full_names = set(FULL_REGISTRATIONS)
    string_gated = _extract_string_gated()
    table_gated = _extract_table_gated()
    unconditional = _extract_unconditional_registrations()

    dispatched = string_gated | table_gated | unconditional
    orphans = sorted(full_names - dispatched)

    assert not orphans, (
        "FULL_REGISTRATIONS names with no dispatch site in bootstrap.py: "
        f"{orphans}. Each FULL-tier group must wire to a registrar in "
        "_register_core_integration_tools, _register_worker_pool_tools, "
        "_register_optional_tools, or be unconditionally invoked at "
        "register_profile_tools() exit."
    )


def test_active_profile_default_is_full() -> None:
    """When ``MAHAVISHNU_TOOL_PROFILE`` is unset, resolution lands on FULL.

    Pins the contract that omitting the env var does NOT accidentally
    land on MINIMAL/STANDARD. Operators rely on FULL as the zero-config
    default (CLAUDE.md "Tool Profile System" -> "Default: FULL").
    """
    import os

    env = os.environ.pop("MAHAVISHNU_TOOL_PROFILE", None)
    try:
        result = ToolProfile.from_env("MAHAVISHNU_TOOL_PROFILE")
    finally:
        if env is not None:
            os.environ["MAHAVISHNU_TOOL_PROFILE"] = env

    assert result == ToolProfile.FULL, (
        f"ToolProfile.from_env returned {result!r} when "
        "MAHAVISHNU_TOOL_PROFILE was unset; FULL is the pinned default "
        "for backward compatibility. See CLAUDE.md Tool Profile System "
        "and MEMORY_ARCHITECTURE.md Section 5 (Contract 5.x)."
    )


def test_every_profile_name_has_a_string_or_table_or_unconditional_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auxiliary: pairwise check tying each profile to bootstrap.

    Walks every profile name explicitly and reports the resolution path
    (string-gate / table / unconditional). Useful diagnostic for future
    maintainers -- surfaces drift instead of swallowing it.
    """
    monkeypatch.delenv("MAHAVISHNU_TOOL_PROFILE", raising=False)
    string_gated = _extract_string_gated()
    table_gated = _extract_table_gated()
    unconditional = _extract_unconditional_registrations()

    report: dict[str, str] = {}
    for profile, methods in PROFILE_REGISTRATIONS.items():
        for name in methods:
            if name in string_gated:
                report[f"{profile.value}/{name}"] = "string-gate"
            elif name in table_gated:
                report[f"{profile.value}/{name}"] = "table-gate"
            elif name in unconditional:
                report[f"{profile.value}/{name}"] = "unconditional"
            else:
                report[f"{profile.value}/{name}"] = "ORPHAN"

    orphans = [k for k, v in report.items() if v == "ORPHAN"]
    assert not orphans, (
        f"Orphaned profile names (no dispatch site): {orphans}. Full report: {report}"
    )
