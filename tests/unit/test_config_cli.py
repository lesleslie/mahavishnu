"""Tests for config inventory CLI commands added by add_config_inventory_commands."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.cli.config_validator import add_config_inventory_commands

runner = CliRunner()


@pytest.fixture
def config_app(tmp_path, monkeypatch):
    """Create a Typer app with inventory commands wired to a temp project root."""
    monkeypatch.setenv("MAHAVISHNU_PROJECT_ROOT", str(tmp_path))
    app = typer.Typer()
    add_config_inventory_commands(app)
    return app, tmp_path


def test_list_agents_shows_agents(config_app):
    app, root = config_app
    agents_dir = root / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "python-pro.md").write_text("---\nname: python-pro\n---\n")
    (agents_dir / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")

    result = runner.invoke(app, ["list-agents"])
    assert result.exit_code == 0
    assert "python-pro" in result.output
    assert "code-reviewer" in result.output
    assert "2 agents" in result.output


def test_list_agents_missing_dir(config_app):
    app, root = config_app
    result = runner.invoke(app, ["list-agents"])
    assert result.exit_code == 1
    assert "migration" in result.output.lower()


def test_list_skills_shows_skills(config_app):
    app, root = config_app
    for name in ("manage-pools", "bodai-radar"):
        skill = root / ".claude" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n")

    result = runner.invoke(app, ["list-skills"])
    assert result.exit_code == 0
    assert "manage-pools" in result.output
    assert "bodai-radar" in result.output
    assert "2 skills" in result.output


def test_list_mcp_servers_shows_servers(config_app):
    app, root = config_app
    (root / ".mcp.json").write_text(
        json.dumps({
            "mcpServers": {
                "crackerjack": {"url": "http://localhost:8676"},
                "akosha": {"url": "http://localhost:8682"},
            }
        })
    )

    result = runner.invoke(app, ["list-mcp-servers"])
    assert result.exit_code == 0
    assert "crackerjack" in result.output
    assert "akosha" in result.output
    assert "2 MCP servers" in result.output


def test_list_mcp_servers_missing_file(config_app):
    app, root = config_app
    result = runner.invoke(app, ["list-mcp-servers"])
    assert result.exit_code == 1
    assert ".mcp.json" in result.output
