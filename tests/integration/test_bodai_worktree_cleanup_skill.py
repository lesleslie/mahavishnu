"""E2E test that the bodai-worktree-cleanup skill wrapper matches direct CLI output."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_skill_invocation_matches_direct_cli_output(tmp_path: Path) -> None:
    """Invoke the wrapper; assert output is byte-identical to direct CLI (modulo timestamps)."""
    repo = tmp_path / "repo1"
    repo.mkdir()
    (repo / ".git").mkdir()
    wrapper = Path(".claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py")
    if not wrapper.exists():
        pytest.skip("wrapper missing: " + str(wrapper))
    direct = subprocess.run(
        [sys.executable, "-m", "mahavishnu.worktree_cli", "scan",
         "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    wrapped = subprocess.run(
        [sys.executable, str(wrapper), "--repo", str(repo), "--format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert direct.returncode == wrapped.returncode
    # Body should be byte-identical excluding the timestamp header line
    direct_lines = direct.stdout.splitlines()[1:]
    wrapped_lines = wrapped.stdout.splitlines()[1:]
    assert direct_lines == wrapped_lines
