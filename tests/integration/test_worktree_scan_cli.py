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
@pytest.mark.slow
def test_scan_text_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert text report has tier section
    headers AND a scan-complete footer (F-QA-9 vacuous-assertion tightening)."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True, capture_output=True, timeout=15,
    )

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
    # Successful single-repo scan must exit 0 (no failed repos).
    assert result.returncode == 0, (
        f"unexpected exit {result.returncode}; stderr: {result.stderr}"
    )
    # Every tier section header must be present (text is always emitted,
    # even when the corresponding bucket is empty).
    for tier in (
        "Tier A-merged",
        "Tier A-merged-dirty",
        "Tier A-orphan-detached",
        "Tier A-orphan-detached-dirty",
        "Tier X",
        "Tier B",
        "Tier C",
        "Tier D",
    ):
        assert tier in result.stdout, f"missing section: {tier}"
    assert "Scan complete:" in result.stdout
    assert "exit 0." in result.stdout


@pytest.mark.integration
@pytest.mark.slow
def test_scan_json_format(tmp_path: Path) -> None:
    """Scan a single-repo fixture; assert JSON output is valid AND contains
    every expected tier key (F-QA-10 vacuous-assertion tightening)."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True, capture_output=True, timeout=15,
    )

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
    # Successful single-repo scan must exit 0.
    assert result.returncode == 0, (
        f"unexpected exit {result.returncode}; stderr: {result.stderr}"
    )
    parsed = json.loads(result.stdout)
    assert "scan_metadata" in parsed
    for key in (
        "scan_metadata",
        "tier_a_merged",
        "tier_a_merged_dirty",
        "tier_a_orphan_detached",
        "tier_a_orphan_detached_dirty",
        "tier_x_cross_repo_orphan",
        "tier_b",
        "tier_c",
        "tier_d",
        "locked_live",
        "locked_orphan",
        "locked_unknown",
        "dirty",
    ):
        assert key in parsed, f"missing tier array in JSON: {key}"
    # L4 followup: single-repo success -> repos_scanned == 1.
    assert parsed["scan_metadata"]["repos_scanned"] == 1


@pytest.mark.integration
def test_nonexistent_path_exits_1_with_stderr(tmp_path: Path) -> None:
    """F-QA-1 — a manifest pointing at a nonexistent path exits 1 and the
    stderr message identifies the bad path with the canonical prefix.

    Uses `--repo=ALL` to exercise the manifest-iteration path-existence branch;
    `--repo=<path>` switches to single-repo mode and skips that branch.
    """
    (tmp_path / "settings").mkdir(parents=True, exist_ok=True)
    (tmp_path / "settings" / "ecosystem.yaml").write_text(
        "version: '1.0'\n"
        "repos:\n"
        "  - name: missing\n"
        f"    path: {tmp_path / 'never_existed'}\n"
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", "ALL",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1, (
        f"expected exit 1, got {result.returncode}; stderr: {result.stderr!r}"
    )
    assert "path does not exist" in result.stderr


@pytest.mark.integration
def test_all_repos_nonexistent_exits_1(tmp_path: Path) -> None:
    """F-QA-2 — every repo path missing still drives exit 1 (whole-manifest fail)."""
    (tmp_path / "settings").mkdir(parents=True, exist_ok=True)
    (tmp_path / "settings" / "ecosystem.yaml").write_text(
        "version: '1.0'\n"
        "repos:\n"
        "  - name: ghost\n"
        "    path: /nonexistent/a\n"
        "  - name: ghost2\n"
        "    path: /nonexistent/b\n"
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", "ALL",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_path),
    )
    assert result.returncode == 1
    assert "/nonexistent/a" in result.stderr
    assert "/nonexistent/b" in result.stderr


@pytest.mark.integration
@pytest.mark.slow
def test_repo_all_format_text_smoke(tmp_path: Path) -> None:
    """L5 + F-QA-3 — `--repo=ALL --format=text` against a single-repo manifest.

    Confirms the text-format path works when --repo=ALL is selected (text
    output is exercised by the e2e JSON path; this anchors the text branch).
    """
    repo = tmp_path / "repo1"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True, capture_output=True, timeout=15,
    )
    _write_minimal_ecosystem_yaml(
        tmp_path, {"name": "repo1", "path": str(repo)}
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", "ALL", "--format", "text",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, (
        f"unexpected exit {result.returncode}; stderr: {result.stderr}"
    )
    assert "Tier A-merged" in result.stdout
    assert "Scan complete" in result.stdout


@pytest.mark.integration
def test_driver_failure_exits_1(tmp_path: Path) -> None:
    """L3 — when `git worktree list` returns non-zero inside the scan driver,
    the CLI must surface the failure to stderr and exit 1.

    Monkeypatches `_run_git_scanned` so the real `git` binary is bypassed
    and every `worktree list` returns rc=128, simulating a corrupt repo.
    """
    from unittest.mock import MagicMock, patch

    # Write a valid manifest pointing at a real dir; the monkeypatch will
    # intercept before any actual git invocation happens.
    repo = tmp_path / "corrupt_repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    _write_minimal_ecosystem_yaml(
        tmp_path, {"name": "corrupt_repo", "path": str(repo)}
    )
    with patch(
        "mahavishnu.core.worktree_scan._run_git_scanned"
    ) as mock_git:
        mock_git.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: not a git repository"
        )
        result = subprocess.run(
            [
                sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
                "--repo", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(tmp_path),
        )
    assert result.returncode == 1, (
        f"expected exit 1 on driver failure; stderr: {result.stderr!r}"
    )
    assert "driver_failure" in result.stderr or "128" in result.stderr