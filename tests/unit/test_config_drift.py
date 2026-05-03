"""Tests for check_skill_mcp_drift in mahavishnu/core/config_validator.py."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def project_layout(tmp_path):
    """Fake project with .mcp.json and one skill with a port reference."""
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "crackerjack": {"url": "http://localhost:8676"},
                    "akosha": {"url": "http://localhost:8682"},
                }
            }
        )
    )
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "## Available MCP Servers\n| crackerjack | 9999 | Inspector |\n"
    )
    return tmp_path


def test_detects_port_drift(project_layout):
    from mahavishnu.core.config_validator import check_skill_mcp_drift

    issues = check_skill_mcp_drift(project_layout)
    assert len(issues) == 1
    assert "9999" in issues[0]
    assert "8676" in issues[0]


def test_no_drift_when_ports_match(tmp_path):
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"crackerjack": {"url": "http://localhost:8676"}}}))
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("| crackerjack | 8676 | Inspector |")

    from mahavishnu.core.config_validator import check_skill_mcp_drift

    issues = check_skill_mcp_drift(tmp_path)
    assert issues == []


def test_returns_empty_when_no_mcp_json(tmp_path):
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("| crackerjack | 8676 |")

    from mahavishnu.core.config_validator import check_skill_mcp_drift

    assert check_skill_mcp_drift(tmp_path) == []


def test_returns_empty_when_no_skills_dir(tmp_path):
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"crackerjack": {"url": "http://localhost:8676"}}}))

    from mahavishnu.core.config_validator import check_skill_mcp_drift

    assert check_skill_mcp_drift(tmp_path) == []


def test_servers_without_urls_are_skipped(tmp_path):
    """Servers with no url (e.g. local command-only) should not cause drift issues."""
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"local-tool": {"command": "uvx", "args": ["tool"]}}}))
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("| local-tool | 9999 |")

    from mahavishnu.core.config_validator import check_skill_mcp_drift

    assert check_skill_mcp_drift(tmp_path) == []
