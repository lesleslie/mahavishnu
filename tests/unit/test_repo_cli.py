"""Tests for mahavishnu.repo_cli (Plan 3 Tier 1 — repo diff + repo pr create)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu import repo_cli
from mahavishnu.repo_cli import create_pr, diff_repo

KNOWN_REPO_PATH = "/Users/les/Projects/mahavishnu"
UNKNOWN_REPO_PATH = "/not/in/yaml"


@pytest.fixture(autouse=True)
def _populate_catalog() -> None:
    """Populate the module-level catalog so paths can be looked up."""
    repo_cli._CATALOG.clear()
    repo_cli._CATALOG[KNOWN_REPO_PATH] = "mahavishnu"


def test_diff_repo_runs_git_diff() -> None:
    """diff_repo should invoke `git diff main..HEAD` inside the repo."""
    with patch("mahavishnu.repo_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="diff --git a/x b/x", returncode=0)
        diff_repo(KNOWN_REPO_PATH, ref1="main", ref2="HEAD")
        mock_run.assert_called_once()
        call = mock_run.call_args
        cmd = call.args[0]
        cwd = call.kwargs.get("cwd")
        assert cmd[:3] == ["git", "diff", "main..HEAD"]
        assert cwd == KNOWN_REPO_PATH


def test_diff_repo_defaults_main_vs_head() -> None:
    """diff_repo should default to `git diff HEAD..main` when no refs given."""
    with patch("mahavishnu.repo_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        diff_repo(KNOWN_REPO_PATH)
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "git"
        assert cmd[1] == "diff"
        assert cmd[2] == "HEAD..main"


def test_create_pr_invokes_gh() -> None:
    """create_pr should invoke `gh pr create` inside the repo."""
    with patch("mahavishnu.repo_cli.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="https://github.com/x/y/pull/1\n", returncode=0)
        url = create_pr(KNOWN_REPO_PATH)
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[0:2] == ["gh", "pr"]
        assert cmd[2] == "create"
        assert "https://github.com/x/y/pull/1" in url


def test_path_not_in_catalog_raises() -> None:
    """diff_repo should raise ValueError when path is not in the repos catalog."""
    with pytest.raises(ValueError, match="not in repo catalog"):
        diff_repo(UNKNOWN_REPO_PATH)


def test_cli_registers_repo_subcommand() -> None:
    """The main CLI should register the `repo` subcommand (Plan 3 Tier 1)."""
    main_cli_path = Path(repo_cli.__file__).resolve().parent / "_main_cli.py"
    main_src = main_cli_path.read_text()
    assert "from .repo_cli import repo_app" in main_src, (
        "_main_cli.py must import the `repo_app` typer sub-app"
    )
    assert 'app.add_typer(repo_app, name="repo")' in main_src, (
        "_main_cli.py must register the `repo` subcommand"
    )
