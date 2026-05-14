"""Tests for scripts.audit_ecosystem_docs."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from audit_ecosystem_docs import build_audit_report, load_catalog_snapshot
import yaml


def _write_ecosystem(tmp_path: Path, data: dict) -> Path:
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "ecosystem.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _write_docs(tmp_path: Path, text: str) -> Path:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "ECOSYSTEM.md"
    path.write_text(text)
    return path


def test_build_audit_report_detects_catalog_count_drift(tmp_path: Path) -> None:
    ecosystem_path = _write_ecosystem(
        tmp_path,
        {
            "version": "1.0",
            "last_updated": date.today().isoformat(),
            "maintainer": "les",
            "description": "test",
            "repos": [
                {
                    "name": "repo-a",
                    "path": "/tmp/a",
                    "role": "orchestrator",
                    "status": "disabled",
                }
            ],
            "mcp_servers": [],
            "claude_agents": {},
            "workflows": {},
            "skills": {},
            "tools": {},
            "roles": [{"name": "orchestrator"}],
        },
    )
    _write_docs(
        tmp_path,
        "\n".join(
            [
                "# Ecosystem",
                "",
                "- **24 git repositories** with roles, tags, and audit timestamps",
                "- **14 MCP servers** with ports, commands, health checks, and dependencies",
                "- **83 Claude agents** with categorization and relevance tracking",
                "- **18 workflows** with validation timestamps",
                "- **64 skills** with usage tracking",
                "- **49 tools** with maintenance tracking",
                "- **12 role definitions** for repository classification",
            ]
        ),
    )

    catalog, issues, summaries = build_audit_report(ecosystem_path)

    assert catalog.repo_count == 1
    assert catalog.active_repo_count == 0
    assert catalog.role_count == 1
    assert summaries == []
    assert any("24 git repositories" in issue for issue in issues)
    assert any("14 MCP servers" in issue for issue in issues)
    assert any("12 role definitions" in issue for issue in issues)


def test_build_audit_report_flags_missing_health_probe_metadata(
    tmp_path: Path,
) -> None:
    ecosystem_path = _write_ecosystem(
        tmp_path,
        {
            "version": "1.0",
            "last_updated": date.today().isoformat(),
            "maintainer": "les",
            "description": "test",
            "repos": [{"name": "repo-a", "path": "/tmp/a", "role": "orchestrator"}],
            "mcp_servers": [
                {
                    "name": "server-a",
                    "type": "http",
                    "port": 9000,
                    "category": "tool",
                    "function": "serve",
                    "command": "serve --port {port}",
                    "description": "Server A",
                    "status": "enabled",
                }
            ],
            "claude_agents": {},
            "workflows": {},
            "skills": {},
            "tools": {},
            "roles": [{"name": "orchestrator"}],
        },
    )
    _write_docs(
        tmp_path,
        "\n".join(
            [
                "# Ecosystem",
                "",
                "- **1 git repositories** with roles, tags, and audit timestamps",
                "- **1 MCP servers** with ports, commands, health checks, and dependencies",
                "- **0 Claude agents** with categorization and relevance tracking",
                "- **0 workflows** with validation timestamps",
                "- **0 skills** with usage tracking",
                "- **0 tools** with maintenance tracking",
                "- **1 role definitions** for repository classification",
            ]
        ),
    )

    _, issues, _ = build_audit_report(ecosystem_path)

    assert any("missing health_check" in issue for issue in issues)


def test_load_catalog_snapshot_counts_roles_and_repos(tmp_path: Path) -> None:
    ecosystem_path = _write_ecosystem(
        tmp_path,
        {
            "version": "1.0",
            "last_updated": date.today().isoformat(),
            "maintainer": "les",
            "description": "test",
            "repos": [
                {"name": "repo-a", "path": "/tmp/a", "role": "orchestrator"},
                {"name": "repo-b", "path": "/tmp/b", "role": "manager", "status": "disabled"},
            ],
            "mcp_servers": [],
            "claude_agents": {"a": {}, "b": {}},
            "workflows": {"x": {}},
            "skills": {"s1": {}},
            "tools": {"t1": {}, "t2": {}},
            "roles": [{"name": "orchestrator"}, {"name": "manager"}],
        },
    )

    snapshot = load_catalog_snapshot(ecosystem_path)

    assert snapshot.repo_count == 2
    assert snapshot.active_repo_count == 1
    assert snapshot.agent_count == 2
    assert snapshot.workflow_count == 1
    assert snapshot.skill_count == 1
    assert snapshot.tool_count == 2
    assert snapshot.role_count == 2
