# tests/unit/test_skill_mcp_validator.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mahavishnu.core.skill_mcp_validator import (
    KNOWN_TOOLS,
    SkillValidationReport,
    extract_mcp_refs,
    validate_agent_file,
    validate_skill_file,
    validate_agent_dir,
    validate_skill_dir,
)


def test_extract_mcp_refs_none():
    assert extract_mcp_refs("No MCP references here.") == []


def test_extract_mcp_refs_single():
    content = "Use mcp__crackerjack__crackerjack_run for quality gates."
    assert extract_mcp_refs(content) == ["mcp__crackerjack__crackerjack_run"]


def test_extract_mcp_refs_multiple():
    content = "mcp__akosha__search_all_systems and mcp__session-buddy__checkpoint"
    refs = extract_mcp_refs(content)
    assert "mcp__akosha__search_all_systems" in refs
    assert "mcp__session-buddy__checkpoint" in refs


def test_extract_mcp_refs_triple_underscore():
    # FastMCP servers with hyphens use triple underscore
    content = "mcp__session-buddy___code_ingest_file_impl"
    assert extract_mcp_refs(content) == ["mcp__session-buddy___code_ingest_file_impl"]


def test_validate_agent_file_no_refs(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent("""\
        ---
        name: test-agent
        description: A short description with no ecosystem refs.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.stale_refs == []
    assert not report.description_too_long
    assert not report.has_ecosystem_refs  # no refs is allowed (non-targeted agent)


def test_validate_agent_file_valid_ref(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent(f"""\
        ---
        name: test-agent
        description: >-
          Short description. Ecosystem: use {list(KNOWN_TOOLS)[0]} for quality.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.stale_refs == []
    assert report.has_ecosystem_refs


def test_validate_agent_file_stale_ref(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent("""\
        ---
        name: test-agent
        description: Ecosystem: use mcp__crackerjack__nonexistent_tool.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert "mcp__crackerjack__nonexistent_tool" in report.stale_refs


def test_validate_agent_file_description_too_long(tmp_path):
    agent = tmp_path / "test-agent.md"
    long_desc = "x" * 301
    agent.write_text(textwrap.dedent(f"""\
        ---
        name: test-agent
        description: {long_desc}
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.description_too_long


def test_validate_skill_file_no_mcp_section(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("# My Skill\n\n## Overview\n\nDoes something.\n")
    report = validate_skill_file(skill)
    assert not report.has_mcp_section
    assert report.stale_refs == []


def test_validate_skill_file_with_valid_mcp_section(tmp_path):
    skill = tmp_path / "SKILL.md"
    valid_tool = list(KNOWN_TOOLS)[0]
    skill.write_text(textwrap.dedent(f"""\
        # My Skill

        ## Available MCP Servers

        | Server | Port | Context Mode | Relevant Tools | Default Timeout |
        |--------|------|-------------|---------------|----------------|
        | crackerjack | 8676 | summary | {valid_tool} | 120s |

        ## Overview

        Does something.
        """))
    report = validate_skill_file(skill)
    assert report.has_mcp_section
    assert report.stale_refs == []


def test_validate_skill_file_stale_ref(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(textwrap.dedent("""\
        # My Skill

        ## Available MCP Servers

        Use mcp__crackerjack__old_tool_name for quality.

        ## Overview

        Does something.
        """))
    report = validate_skill_file(skill)
    assert "mcp__crackerjack__old_tool_name" in report.stale_refs


def test_validate_skill_file_wrong_port(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(textwrap.dedent("""\
        # My Skill

        ## Available MCP Servers

        session-buddy on port 8765.

        ## Overview
        """))
    report = validate_skill_file(skill)
    assert any("8765" in w for w in report.wrong_ports), f"expected port 8765 in wrong_ports, got {report.wrong_ports}"
    assert any("8678" in w for w in report.wrong_ports), f"expected correct port 8678 in wrong_ports, got {report.wrong_ports}"


def test_validate_agent_dir_empty(tmp_path):
    reports = validate_agent_dir(tmp_path)
    assert reports == {}


def test_validate_skill_dir_empty(tmp_path):
    reports = validate_skill_dir(tmp_path)
    assert reports == {}
