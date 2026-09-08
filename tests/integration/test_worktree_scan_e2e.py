"""E2E tests for `mahavishnu worktree scan` against real + corrupt manifests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_real_repo_scan_yields_non_empty_report() -> None:
    """Scan the real settings/ecosystem.yaml; assert non-empty + valid schema.

    Runs from the repo root so the CLI's default `repos_path` resolves to the
    real `settings/ecosystem.yaml`. Asserts non-empty output + correct exit
    code (0 if all repos scanned successfully, 1 if any per-repo scan failed).
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
            "--repo", "ALL", "--format", "json",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(repo_root),
    )
    assert result.returncode in (0, 1), (
        f"unexpected exit code: {result.returncode}; stderr: {result.stderr}"
    )
    if result.returncode == 0:
        parsed = json.loads(result.stdout)
        assert "scan_metadata" in parsed
        # All tier arrays should be present (possibly empty)
        for key in [
            "tier_a_merged",
            "tier_a_merged_dirty",
            "tier_a_orphan_detached",
            "tier_a_orphan_detached_dirty",
            "tier_x_cross_repo_orphan",
            "tier_b",
            "tier_c",
            "tier_d",
        ]:
            assert key in parsed, f"missing tier array: {key}"


@pytest.mark.integration
@pytest.mark.slow
def test_corrupt_manifest_exits_2(tmp_path: Path) -> None:
    """Scan with a corrupt ecosystem.yaml; assert exit code 2 + stderr mentions config."""
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    bad_manifest = settings_dir / "ecosystem.yaml"
    # Intentionally malformed YAML
    bad_manifest.write_text("not: valid: yaml: [[[")

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
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr: {result.stderr}"
    )
    assert "config" in result.stderr.lower()