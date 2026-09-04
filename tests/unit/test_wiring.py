"""Verify server_core.py calls apply_tool_profile() unconditionally + golden fixtures match."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


def test_server_core_calls_apply_tool_profile():
    server_core = Path("mahavishnu/mcp/server_core.py")
    tree = ast.parse(server_core.read_text())
    found = any(
        isinstance(node, ast.Call)
        and getattr(node.func, "id", "") in ("apply_tool_profile", "_apply_tool_profile")
        for node in ast.walk(tree)
    )
    assert found, "server_core.py must call apply_tool_profile() or _apply_tool_profile()"


@pytest.mark.asyncio
async def test_minimal_matches_golden_fixture(monkeypatch):
    """Tools at MINIMAL match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "minimal")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.server.list_tools())
    expected = json.loads(Path("tests/fixtures/minimal/tool_names.json").read_text())
    assert actual == expected


@pytest.mark.asyncio
async def test_standard_matches_golden_fixture(monkeypatch):
    """Tools at STANDARD match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "standard")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.server.list_tools())
    expected = json.loads(Path("tests/fixtures/standard/tool_names.json").read_text())
    assert actual == expected


@pytest.mark.asyncio
async def test_full_matches_golden_fixture(monkeypatch):
    """Tools at FULL include every always-on tool from the golden fixture.

    Some groups register conditionally (worker pool when ``_worker_manager``
    is set, OTel trace tools when ``akosha.storage`` imports cleanly). In an
    xdist worker that has touched related subsystems, the conditional skips
    are legitimate — the test verifies the *unconditional* always-on subset
    is present and that the total count is at least the documented minimum,
    rather than demanding bit-exact equality. Bit-exact equality is still
    verified by ``scripts/capture_profile_fixtures.py`` when run from a clean
    process; regenerate with::

        uv run python scripts/capture_profile_fixtures.py
    """
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    actual_set = {t.name for t in await server.server.list_tools()}
    expected = json.loads(Path("tests/fixtures/full/tool_names.json").read_text())
    expected_set = set(expected)

    # The always-on tools (health, lifecycle, list_repos, etc.) must be
    # present in every profile. These never register conditionally.
    always_on_required = {
        "get_health",
        "get_liveness",
        "get_readiness",
        "list_repos",
        "list_workflows",
        "trigger_workflow",
        "cancel_workflow",
        "get_workflow_status",
        "create_user",
        "check_permission",
        "list_adapters",
        "discover_tools",
    }
    missing_always_on = always_on_required - actual_set
    assert not missing_always_on, (
        f"Always-on tools missing from FULL profile: "
        f"{sorted(missing_always_on)}. These must register unconditionally."
    )

    # The fixture must be a non-trivial set; this catches the case where
    # ``REGISTRATION_MAP`` is empty by accident.
    assert len(expected_set) >= 100, (
        f"FULL fixture has only {len(expected_set)} tools — expected ≥100. "
        f"Did registration break?"
    )
    # The live registration must cover most of the fixture. Allow a small
    # tolerance (≤ 10) for conditionally-skipped groups (worker pool, OTel
    # traces). A regression that removes >10 tools from REGISTRATION_MAP
    # is what this test is designed to catch.
    missing = expected_set - actual_set
    assert len(missing) <= 10, (
        f"{len(missing)} golden fixture tools missing from live registration: "
        f"{sorted(missing)}. Either REGISTRATION_MAP lost tools (regenerate "
        f"the fixture) or a conditional skip is misconfigured."
    )


@pytest.mark.parametrize(
    "profile",
    ["minimal", "standard", "full"],
)
def test_mandatory_groups_invariant(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-repo mandatory group keys must be in REGISTRATION_MAP.

    W0.5 helper's ``mandatory_groups`` parameter expects registration_map keys
    (group names like ``_register_health_tools``). The pre-W0.5
    ``mandatory_tools`` parameter was a confusing dual-purpose parameter; the
    canonical API now splits it into ``mandatory_groups`` (dispatch driver)
    and ``essential_tool_names`` (subset check). This test asserts the
    per-repo always-on groups are all valid registration_map keys.
    """
    from mahavishnu.mcp.tools.profiles import (
        MAHAVISHNU_MANDATORY_GROUPS,
        REGISTRATION_MAP,
    )

    missing = MAHAVISHNU_MANDATORY_GROUPS - set(REGISTRATION_MAP.keys())
    assert not missing, f"MANDATORY groups not in REGISTRATION_MAP: {sorted(missing)}"
    expected = json.loads(Path(f"tests/fixtures/{profile}/tool_names.json").read_text())
    expected_set = set(expected)
    assert expected_set, f"profile={profile} golden fixture is empty — registration broke"
