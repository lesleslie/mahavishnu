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
        isinstance(node, ast.Call) and getattr(node.func, "id", "") == "apply_tool_profile"
        for node in ast.walk(tree)
    )
    assert found, "server_core.py must call apply_tool_profile()"


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
    """Tools at FULL match the captured golden fixture."""
    monkeypatch.setenv("MAHAVISHNU_TOOL_PROFILE", "full")
    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    actual = sorted(t.name for t in await server.server.list_tools())
    expected = json.loads(Path("tests/fixtures/full/tool_names.json").read_text())
    assert actual == expected


@pytest.mark.parametrize(
    "profile",
    ["minimal", "standard", "full"],
)
def test_mandatory_tools_invariant(profile: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-repo mandatory group keys must be in REGISTRATION_MAP.

    W0 helper's default MANDATORY_TOOLS set uses tool names ('get_liveness',
    etc.) but the dispatch loop looks them up in REGISTRATION_MAP. Mahavishnu
    uses group keys ('_register_health_tools', ...) so the per-repo subset
    is asserted against REGISTRATION_MAP, not the W0 default set. This is
    the W0 API gap recorded in the task report.
    """
    from mahavishnu.mcp.tools.profiles import (
        MAHAVISHNU_MANDATORY_TOOLS,
        REGISTRATION_MAP,
    )

    missing = MAHAVISHNU_MANDATORY_TOOLS - set(REGISTRATION_MAP.keys())
    assert not missing, f"MANDATORY groups not in REGISTRATION_MAP: {sorted(missing)}"
    expected = json.loads(Path(f"tests/fixtures/{profile}/tool_names.json").read_text())
    expected_set = set(expected)
    assert expected_set, f"profile={profile} golden fixture is empty — registration broke"
