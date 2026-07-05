"""Tests for scripts/migrate_config_to_project.py."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fake_home(tmp_path):
    """Create a minimal fake ~/.claude structure for testing."""
    claude = tmp_path / ".claude"
    agents = claude / "agents"
    agents.mkdir(parents=True)
    (agents / "python-pro.md").write_text("---\nname: python-pro\n---\n")
    (agents / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")

    skills = claude / "skills"
    skill_dir = skills / "manage-pools"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Manage Pools\n")

    commands = claude / "commands"
    commands.mkdir(parents=True)
    (commands / "start.md").write_text("# Start\n")

    hooks = claude / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "mcp-hooks.json").write_text('{"hooks": []}')

    (claude / "CLAUDE.md").write_text("# Ecosystem manifest\n")

    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "crackerjack": {
                        "command": "uvx",
                        "args": ["crackerjack-mcp"],
                        "env": {"API_KEY": "secret-value"},
                    },
                    "akosha": {
                        "url": "http://localhost:8682",
                    },
                },
                "otherAppState": "preserved",
            }
        )
    )

    return tmp_path


def _make_dest(tmp_path: Path) -> Path:
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    (dest / ".claude").mkdir()
    (dest / ".claude" / "settings.local.json").write_text(json.dumps({"additionalDirectories": []}))
    return dest


def test_dry_run_makes_no_changes(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=True,
    )
    runner.run()

    assert not (dest / ".claude" / "agents").exists()
    assert not (dest / ".mcp.json").exists()


def test_full_migration_copies_agents(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    dest_claude = dest / ".claude"
    dest_claude.mkdir()
    (dest_claude / "settings.local.json").write_text(
        json.dumps({"additionalDirectories": [str(fake_home / ".claude"), "/other/path"]})
    )

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    assert (dest / ".claude" / "agents" / "python-pro.md").exists()
    assert (dest / ".claude" / "agents" / "code-reviewer.md").exists()


def test_env_blocks_stripped_from_mcp_json(fake_home, tmp_path):
    dest = _make_dest(tmp_path)

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    mcp_json = json.loads((dest / ".mcp.json").read_text())
    assert "env" not in mcp_json["mcpServers"]["crackerjack"]
    assert mcp_json["mcpServers"]["crackerjack"]["command"] == "uvx"


def test_other_app_state_preserved_in_claude_json(fake_home, tmp_path):
    dest = _make_dest(tmp_path)

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    remaining = json.loads((fake_home / ".claude.json").read_text())
    assert "mcpServers" not in remaining
    assert remaining["otherAppState"] == "preserved"


def test_additional_directories_updated(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    (dest / ".claude").mkdir()
    (dest / ".claude" / "settings.local.json").write_text(
        json.dumps({"additionalDirectories": [str(fake_home / ".claude"), "/keep/me"]})
    )

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    updated = json.loads((dest / ".claude" / "settings.local.json").read_text())
    dirs = updated["additionalDirectories"]
    assert str(fake_home / ".claude") not in dirs
    assert "/keep/me" in dirs


def test_skills_copied(fake_home, tmp_path):
    dest = _make_dest(tmp_path)

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    assert (dest / ".claude" / "skills" / "manage-pools" / "SKILL.md").exists()


def test_existing_skill_not_overwritten(fake_home, tmp_path):
    dest = _make_dest(tmp_path)
    existing = dest / ".claude" / "skills" / "manage-pools"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# Original\n")

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    assert (dest / ".claude" / "skills" / "manage-pools" / "SKILL.md").read_text() == "# Original\n"


def test_mcp_json_has_all_servers(fake_home, tmp_path):
    dest = _make_dest(tmp_path)

    from migrate_config_to_project import MigrationRunner

    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    mcp_json = json.loads((dest / ".mcp.json").read_text())
    assert "crackerjack" in mcp_json["mcpServers"]
    assert "akosha" in mcp_json["mcpServers"]
    assert mcp_json["mcpServers"]["akosha"]["url"] == "http://localhost:8682"
