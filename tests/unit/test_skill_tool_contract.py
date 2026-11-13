"""Guard the MCP tool and CLI contracts named by the repo's skills.

A skill that names an MCP tool or a CLI command which does not exist has a
broken contract: its activation table can never fire and its examples cannot
run. The ``auto-coordinate`` skill sat that way for months — it triggered on
``coord_create_issue`` and friends, tools that were never registered on the
running server — and nothing caught it because the skill was untracked.

This test scans every skill under ``.claude/skills/`` and asserts that each
MCP tool name resolves against a live ``tools/list`` fixture and each
``mahavishnu <group> <command>`` resolves against a real CLI subcommand.

The live surface comes from the checked-in profile fixtures, so the guard
needs no running server.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / ".claude/skills"
MAHAVISHNU_FIXTURE = REPO_ROOT / "tests/fixtures/full/tool_names.json"
COORDINATION_CLI = REPO_ROOT / "mahavishnu/coordination_cli.py"

# Sibling repos that own the tool surface a skill may reference. Their
# fixture is only present on a developer checkout, so a missing sibling
# skips that server's tools rather than failing the guard.
SIBLING_REPOS = {
    "session-buddy": "session-buddy",
    "akosha": "akosha",
    "crackerjack": "crackerjack",
}

# References another in-flight change owns. Each entry names the work that
# resolves it; the reference is allowed to be stale until then. Entries are
# only a bridge — the named work should remove them.
KNOWN_STALE_TOOL_REFS = {
    "mcp__mahavishnu__pool_execute": (
        "renamed to pool_route_execute by "
        "docs/plans/2026-11-07-mcp-tool-disambiguation.md Phase 3; the "
        "feat/component-prefix-sweep branch already carries the fix"
    ),
}

MCP_TOOL_PATTERN = re.compile(r"mcp__([a-z][a-z0-9-]*)__([a-z_0-9]+)")
CLI_COMMAND_PATTERN = re.compile(
    r"\bmahavishnu\s+([a-z][a-z0-9-]*)\s+([a-z][a-z0-9-]*)"
)


def _skill_files() -> list[Path]:
    """Every tracked skill document under ``.claude/skills``."""
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def _mcp_tools_in(text: str) -> set[str]:
    """Fully qualified ``mcp__server__tool`` names mentioned in ``text``."""
    return {f"mcp__{server}__{tool}" for server, tool in MCP_TOOL_PATTERN.findall(text)}


def _live_tools_for(server: str) -> set[str] | None:
    """The live tool names for ``server``, or None when its fixture is absent."""
    if server == "mahavishnu":
        fixture = MAHAVISHNU_FIXTURE
    else:
        repo = SIBLING_REPOS.get(server)
        if repo is None:
            return None
        fixture = REPO_ROOT.parent / repo / "tests/fixtures/full/tool_names.json"
    if not fixture.is_file():
        return None
    return set(json.loads(fixture.read_text()))


def _coord_cli_commands() -> set[str]:
    """The subcommands the ``mahavishnu coord`` group actually registers."""
    source = COORDINATION_CLI.read_text()
    return set(re.findall(r'@coord_app\.command\("([^"]+)"\)', source))


def test_the_repo_has_skills_to_guard() -> None:
    """Guard against the scan silently matching nothing."""
    assert _skill_files(), f"no skills found under {SKILLS_DIR}"


@pytest.mark.parametrize("skill", _skill_files(), ids=lambda p: p.parent.name)
def test_mcp_tools_named_by_a_skill_exist(skill: Path) -> None:
    """Every MCP tool a skill names must be served by a live server."""
    named = _mcp_tools_in(skill.read_text())
    unknown: list[str] = []

    for full_name in sorted(named):
        server = full_name.split("__")[1]
        live = _live_tools_for(server)
        if live is None:
            # No fixture for this server on this checkout — cannot judge.
            continue
        tool = full_name.split("__", 2)[2]
        if tool not in live and full_name not in KNOWN_STALE_TOOL_REFS:
            unknown.append(full_name)

    assert not unknown, (
        f"{skill.relative_to(REPO_ROOT)} names MCP tools that no live server "
        f"serves: {unknown}. Either the tool was renamed or the skill is "
        f"stale."
    )


@pytest.mark.parametrize("skill", _skill_files(), ids=lambda p: p.parent.name)
def test_coord_cli_commands_named_by_a_skill_exist(skill: Path) -> None:
    """Every ``mahavishnu coord <command>`` a skill names must be real."""
    commands = _coord_cli_commands()
    unknown: list[str] = []

    for group, command in sorted(set(CLI_COMMAND_PATTERN.findall(skill.read_text()))):
        if group != "coord":
            continue
        if command not in commands:
            unknown.append(command)

    assert not unknown, (
        f"{skill.relative_to(REPO_ROOT)} names 'mahavishnu coord' commands "
        f"that do not exist: {unknown}. Real commands: {sorted(commands)}"
    )


def test_the_auto_coordinate_skill_names_no_coordination_mcp_tools() -> None:
    """The coordination MCP surface was deleted; no skill may name it.

    ``mahavishnu/mcp/tools/coordination_tools.py`` defined 15 ``coord_*``
    tools that were never registered, so they never appeared in
    ``tools/list``. The module was deleted on 2026-11-12; the capability
    lives behind the ``mahavishnu coord`` CLI. A skill that names a
    ``coord_*`` tool is reviving a contract that cannot be satisfied.
    """
    skill = SKILLS_DIR / "auto-coordinate/SKILL.md"
    assert skill.is_file(), "auto-coordinate skill is not tracked in the repo"

    coordination_tools = {
        name
        for name in _mcp_tools_in(skill.read_text())
        if name.split("__")[2].startswith("coord_")
    }
    assert not coordination_tools, (
        f"the auto-coordinate skill names coordination MCP tools that do not "
        f"exist: {sorted(coordination_tools)}"
    )


def test_the_auto_coordinate_skill_is_tracked_in_the_repo() -> None:
    """The skill must live in the repo so its contract is reviewable.

    An untracked skill has no pull request, no review, and no CI — which is
    how the previous version sat broken against a tool surface that had
    moved underneath it.
    """
    skill = SKILLS_DIR / "auto-coordinate/SKILL.md"
    assert skill.is_file(), (
        "the auto-coordinate skill is not tracked under .claude/skills/. "
        "Keep it in the repo so the contract it names is reviewable."
    )
