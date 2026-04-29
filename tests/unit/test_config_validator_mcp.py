# tests/unit/test_config_validator_mcp.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mahavishnu.core.skill_mcp_validator import KNOWN_TOOLS
from mahavishnu.cli.config_validator import (
    check_skill_agent_drift,
    DriftReport,
)


@pytest.fixture()
def clean_agent(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    valid_tool = list(KNOWN_TOOLS)[0]
    (agents / "good-agent.md").write_text(textwrap.dedent(f"""\
        ---
        name: good-agent
        description: Short desc. Ecosystem: use {valid_tool}.
        model: sonnet
        ---
        """))
    return agents


@pytest.fixture()
def stale_agent(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "bad-agent.md").write_text(textwrap.dedent("""\
        ---
        name: bad-agent
        description: Ecosystem: use mcp__crackerjack__gone_forever.
        model: sonnet
        ---
        """))
    return agents


@pytest.fixture()
def clean_skill(tmp_path):
    skills = tmp_path / "skills" / "my-skill"
    skills.mkdir(parents=True)
    valid_tool = list(KNOWN_TOOLS)[0]
    (skills / "SKILL.md").write_text(textwrap.dedent(f"""\
        # My Skill

        ## Available MCP Servers

        | Server | Port | Context Mode | Relevant Tools | Default Timeout |
        |--------|------|-------------|---------------|----------------|
        | crackerjack | 8676 | summary | {valid_tool} | 120s |
        """))
    return tmp_path / "skills"


def test_drift_report_no_errors(clean_agent, clean_skill):
    report = check_skill_agent_drift(
        agents_dir=clean_agent,
        skills_dir=clean_skill,
    )
    assert isinstance(report, DriftReport)
    assert report.error_count == 0
    assert report.valid


def test_drift_report_stale_agent(stale_agent, clean_skill):
    report = check_skill_agent_drift(
        agents_dir=stale_agent,
        skills_dir=clean_skill,
    )
    assert not report.valid
    assert report.error_count > 0
    assert any("mcp__crackerjack__gone_forever" in e for e in report.errors)


def test_drift_report_missing_dirs(tmp_path):
    report = check_skill_agent_drift(
        agents_dir=tmp_path / "missing_agents",
        skills_dir=tmp_path / "missing_skills",
    )
    # Missing dirs produce no errors (dirs not present = nothing to validate)
    assert report.valid
    assert report.error_count == 0
