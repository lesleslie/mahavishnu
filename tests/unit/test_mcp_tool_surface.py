"""Guard the fleet's MCP tool surface against drift.

Phase 4 of ``docs/plans/2026-11-07-mcp-tool-disambiguation.md`` asks for
a guard that makes the *next* duplicate fail the build instead of
waiting to be found. This module runs that guard's analysis over a
checked-in snapshot of the fleet's ``tools/list`` responses, so CI
catches the defect even when the servers are down.

The snapshot lives at
``tests/fixtures/mcp_surface/tools_list.json`` and is regenerated with:

    python scripts/check_mcp_tool_surface.py --capture \\
        tests/fixtures/mcp_surface/tools_list.json

Regenerate it whenever a server's tool surface changes. A stale
snapshot is itself a defect: it would let a regression through.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_mcp_tool_surface.py"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "mcp_surface" / "tools_list.json"


def _load_guard() -> ModuleType:
    """Import the guard script as a module."""
    spec = importlib.util.spec_from_file_location("check_mcp_tool_surface", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before executing: the script's dataclasses resolve their
    # own module through sys.modules, and an unregistered module makes
    # @dataclass fail with a confusing AttributeError.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    """The guard module under test."""
    return _load_guard()


@pytest.fixture(scope="module")
def surface(guard: ModuleType) -> Any:
    """The analysed fleet surface, built from the checked-in snapshot."""
    assert FIXTURE_PATH.is_file(), (
        f"the MCP surface snapshot is missing: {FIXTURE_PATH}. "
        "Regenerate it with scripts/check_mcp_tool_surface.py --capture."
    )
    return guard.load_fixture(FIXTURE_PATH)


def test_the_snapshot_covers_the_whole_fleet(guard: ModuleType, surface: Any) -> None:
    """The snapshot must hold every server the guard knows about."""
    assert set(surface.tools) == set(guard.SERVER_URLS)
    assert len(surface.served_names) > 400, (
        f"the snapshot only holds {len(surface.served_names)} tool names, "
        "which is too few to be the fleet"
    )


def test_the_fleet_surface_has_no_violations(guard: ModuleType, surface: Any) -> None:
    """The checked-in fleet surface must be clean.

    This is the check that matters: an empty description makes a tool
    unusable, a duplicate bare name makes the Claude Code picker
    ambiguous, a phantom registry entry sends callers after a tool that
    does not exist, and a drifting parameter signature breaks a caller
    that swaps one server's tool for another's.
    """
    findings = guard.analyse(surface)

    reported = {
        label: items for label, items in findings.items() if items
    }
    assert not reported, "MCP tool surface violations:\n" + "\n".join(
        f"  {label}: {items}" for label, items in reported.items()
    )


def test_a_duplicate_tool_name_is_reported(guard: ModuleType, surface: Any) -> None:
    """A duplicated bare name must fail the analysis.

    Proves the guard fires rather than passing vacuously.
    """
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    broken = copy.deepcopy(payload)
    broken["servers"]["akosha"]["tools"].append(
        {
            "name": "mahavishnu_only_tool",
            "description": "A tool that belongs to one server only.",
            "signature": "",
        }
    )
    broken["servers"]["session-buddy"]["tools"].append(
        {
            "name": "mahavishnu_only_tool",
            "description": "A tool that belongs to one server only.",
            "signature": "",
        }
    )

    findings = guard.analyse(guard.load_fixture_from_payload(broken))
    assert findings["duplicate tool name"], (
        "a name served by two servers must be reported as a duplicate"
    )


def test_an_empty_description_is_reported(guard: ModuleType, surface: Any) -> None:
    """A tool with no description must fail the analysis."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    broken = copy.deepcopy(payload)
    broken["servers"]["akosha"]["tools"].append(
        {"name": "akosha_only_tool", "description": None, "signature": ""}
    )

    findings = guard.analyse(guard.load_fixture_from_payload(broken))
    assert any(
        "akosha_only_tool" in item for item in findings["empty description"]
    ), "a tool with no description must be reported"


def test_a_registry_phantom_is_reported(guard: ModuleType, surface: Any) -> None:
    """A registry entry nothing serves must fail the analysis."""
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    broken = copy.deepcopy(payload)
    broken["servers"]["mahavishnu"]["tools"] = [
        tool for tool in broken["servers"]["mahavishnu"]["tools"]
        if tool["name"] != "get_tool_versions"
    ]

    findings = guard.analyse(guard.load_fixture_from_payload(broken))
    assert any(
        "get_tool_versions" in item for item in findings["version registry drift"]
    ), "a registry entry no server serves must be reported as a phantom"


def test_the_shared_baseline_set_is_not_reported_as_a_duplicate(
    guard: ModuleType,
    surface: Any,
) -> None:
    """The shared baseline tools are allowed to appear on several servers.

    ``discover_tools`` and the health trio are served by more than one
    server by design. Flagging them would make the guard noise.
    """
    findings = guard.analyse(surface)
    for item in findings["duplicate tool name"]:
        assert item.split()[0] not in guard.SHARED_BASELINE_TOOLS, (
            f"{item} names a shared baseline tool, which is allowed"
        )
