"""Smoke tests for ``scripts/install-bodai-git-hooks.sh``.

The script is operator-side — operators run it after ``git clone`` to
wire up the Phase 12a dispatcher wrappers. These tests verify the
script's CONTRACT (idempotency, --force semantics, --uninstall mode,
correct wrapper content for each hook) without depending on a
working ``mahavishnu`` CLI install — the wrappers don't execute
during tests, they're just shell scripts that ``exec`` into the CLI.

Test fixture creates a temp git repo so the script sees a real
``$GIT_DIR/hooks`` layout. Uses ``subprocess.run`` to invoke the
script (NOT ``os.system``) per crackerjack-compliant-code.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "install-bodai-git-hooks.sh"
EXPECTED_HOOKS = ("pre-commit", "post-commit", "post-merge", "post-rewrite")


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a throwaway git repo under ``tmp_path``.

    Returns the repo root (NOT ``.git/hooks``). The fixture also
    sets ``GIT_DIR`` so the install script's preflight sees a git
    working tree.
    """
    repo = tmp_path / "throwaway"
    repo.mkdir()
    env = os.environ.copy()
    env["GIT_DIR"] = str(repo / ".git")
    # git init with explicit GIT_DIR avoids touching the operator's real
    # ``~/.gitconfig`` and keeps the fixture hermetic.
    subprocess.run(
        ["git", "init", str(repo)],
        check=True,
        capture_output=True,
        env=env,
    )
    (repo / ".git" / "hooks").mkdir(exist_ok=True)
    return repo


def _run_script(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the install script against ``repo`` (cwd = repo)."""
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(repo),
    )


def test_script_exists_and_is_executable() -> None:
    """The install script must exist and have the executable bit set."""
    assert SCRIPT.is_file(), f"missing: {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), f"not executable: {SCRIPT}"


def test_help_exits_zero_and_prints_usage(temp_git_repo: Path) -> None:
    """--help prints usage info and exits 0."""
    result = _run_script(temp_git_repo, "--help")
    assert result.returncode == 0
    assert "install-bodai-git-hooks" in result.stdout
    assert "--uninstall" in result.stdout
    assert "--force" in result.stdout


def test_install_writes_all_four_wrappers(temp_git_repo: Path) -> None:
    """First install writes all four wrappers with the expected markers."""
    result = _run_script(temp_git_repo)
    assert result.returncode == 0, result.stderr

    hooks_dir = temp_git_repo / ".git" / "hooks"
    for hook in EXPECTED_HOOKS:
        path = hooks_dir / hook
        assert path.is_file(), f"missing wrapper: {path}"
        assert os.access(path, os.X_OK), f"not executable: {path}"
        content = path.read_text()
        assert "install-bodai-git-hooks.sh" in content
        assert "mahavishnu git-hook" in content


def test_install_is_idempotent_without_force(temp_git_repo: Path) -> None:
    """Re-running without --force leaves existing wrappers untouched."""
    hooks_dir = temp_git_repo / ".git" / "hooks"
    first_post = hooks_dir / "post-commit"
    first_marker = "# sentinel-original-content"

    _run_script(temp_git_repo, "--force")  # ensure installed
    first_post.write_text(first_marker + "\n" + first_post.read_text())

    second = _run_script(temp_git_repo)  # no --force
    assert second.returncode == 0
    assert first_marker in first_post.read_text(), \
        "second run without --force must not overwrite existing wrapper"


def test_force_flag_overwrites_existing(temp_git_repo: Path) -> None:
    """--force overwrites existing wrappers."""
    hooks_dir = temp_git_repo / ".git" / "hooks"
    _run_script(temp_git_repo)  # initial install
    (hooks_dir / "post-commit").write_text("# stale wrapper\n")

    result = _run_script(temp_git_repo, "--force")
    assert result.returncode == 0
    content = (hooks_dir / "post-commit").read_text()
    assert "mahavishnu git-hook" in content
    assert "stale wrapper" not in content


def test_pre_commit_includes_project_specific_guards(temp_git_repo: Path) -> None:
    """The pre-commit wrapper retains the mahavishnu-repo-specific guards
    (secrets audit + findings budget) BEFORE the git-hook exec."""
    _run_script(temp_git_repo)
    content = (temp_git_repo / ".git" / "hooks" / "pre-commit").read_text()
    assert "audit_no_secrets_in_mcp.py" in content
    assert "validate_findings.py" in content
    assert "findings.md" in content


def test_other_hooks_are_bare_one_liner_exec(temp_git_repo: Path) -> None:
    """post-{commit,merge,rewrite} are bare exec one-liners — no
    project-specific guard logic."""
    _run_script(temp_git_repo)
    hooks_dir = temp_git_repo / ".git" / "hooks"
    for hook in ("post-commit", "post-merge", "post-rewrite"):
        content = (hooks_dir / hook).read_text()
        assert "audit_no_secrets_in_mcp.py" not in content, \
            f"{hook} should not contain secrets audit guard"
        assert "mahavishnu git-hook" in content


def test_uninstall_removes_only_our_wrappers(temp_git_repo: Path) -> None:
    """--uninstall removes wrappers WE wrote and preserves foreign ones."""
    hooks_dir = temp_git_repo / ".git" / "hooks"
    _run_script(temp_git_repo)

    # Add a foreign hook that we should NOT remove.
    foreign = hooks_dir / "post-update"
    foreign.write_text("#!/bin/sh\n# foreign hook from elsewhere\n")
    foreign.chmod(0o755)

    result = _run_script(temp_git_repo, "--uninstall")
    assert result.returncode == 0, result.stderr

    for hook in EXPECTED_HOOKS:
        assert not (hooks_dir / hook).exists(), \
            f"uninstall should have removed {hook}"
    assert foreign.exists(), "foreign wrapper must be preserved"


def test_uninstall_is_idempotent(temp_git_repo: Path) -> None:
    """--uninstall on a clean repo exits 0 (no-op)."""
    _run_script(temp_git_repo, "--uninstall")
    second = _run_script(temp_git_repo, "--uninstall")
    assert second.returncode == 0


def test_unknown_flag_exits_nonzero(temp_git_repo: Path) -> None:
    """Unknown CLI args exit 2 with a clear error message."""
    result = _run_script(temp_git_repo, "--bogus")
    assert result.returncode == 2
    assert "unknown arg" in result.stderr


def test_script_outside_git_repo_exits_nonzero(tmp_path: Path) -> None:
    """Running outside a git working tree fails the preflight check."""
    result = _run_script(tmp_path)
    assert result.returncode != 0
    assert "not inside a git working tree" in result.stderr
