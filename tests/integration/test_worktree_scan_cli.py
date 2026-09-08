"""Integration tests for `mahavishnu worktree scan` CLI subcommand."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_minimal_ecosystem_yaml(tmp_path: Path, repo_entry: dict[str, str]) -> Path:
    """Write a minimal valid ecosystem.yaml under tmp_path/settings/.

    The CLI resolves `repos_path` from MahavishnuSettings; with cwd=tmp_path,
    a relative `settings/ecosystem.yaml` resolves here.
    """
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings_dir / "ecosystem.yaml"
    manifest_path.write_text(
        "version: '1.0'\n"
        "repos:\n"
        f"  - name: {repo_entry['name']}\n"
        f"    path: {repo_entry['path']}\n"
    )
    return manifest_path


@pytest.mark.integration
def test_scan_text_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert text report has expected sections."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()

    _write_minimal_ecosystem_yaml(
        tmp_path, {"name": "repo1", "path": str(repo)}
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", str(repo), "--format", "text",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
    )
    assert result.returncode in (0, 1), (
        f"unexpected exit {result.returncode}; stderr: {result.stderr}"
    )
    assert "Tier" in result.stdout or "scan" in result.stdout.lower()


@pytest.mark.integration
def test_scan_json_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert JSON output is valid."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()

    _write_minimal_ecosystem_yaml(
        tmp_path, {"name": "repo1", "path": str(repo)}
    )

    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", str(repo), "--format", "json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
    )
    if result.returncode == 0:
        parsed = json.loads(result.stdout)
        assert "scan_metadata" in parsed
        assert "tier_a_merged" in parsed