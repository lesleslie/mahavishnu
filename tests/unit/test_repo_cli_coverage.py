"""Coverage-push tests for the 5 missed lines in mahavishnu/repo_cli.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mahavishnu import repo_cli
from mahavishnu.repo_cli import _load_catalog

KNOWN_REPO_PATH = "/Users/les/Projects/mahavishnu"


@pytest.fixture(autouse=True)
def _populate_catalog() -> None:
    """Seed the module-level catalog so catalog-backed calls succeed."""
    repo_cli._CATALOG.clear()
    repo_cli._CATALOG[KNOWN_REPO_PATH] = "mahavishnu"


def test_load_catalog_returns_empty_when_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Line 25: _load_catalog returns {} when settings/repos.yaml does not exist."""
    monkeypatch.setattr(repo_cli, "REPOS_CATALOG_PATH", tmp_path / "missing.yaml")
    assert _load_catalog() == {}


def test_diff_command_echoes_diff_repo_output() -> None:
    """Lines 106-107: the `diff` subcommand calls diff_repo and echoes the result."""
    runner = CliRunner()
    with patch("mahavishnu.repo_cli.diff_repo") as mock_diff:
        mock_diff.return_value = "diff --git a/x b/x\n"
        result = runner.invoke(
            repo_cli.repo_app,
            ["diff", "--path", KNOWN_REPO_PATH, "--ref1", "HEAD", "--ref2", "main"],
        )
    assert result.exit_code == 0
    mock_diff.assert_called_once_with(KNOWN_REPO_PATH, ref1="HEAD", ref2="main")
    assert "diff --git a/x b/x" in result.output


def test_pr_create_command_echoes_pr_url() -> None:
    """Lines 115-116: the `pr-create` subcommand calls create_pr and echoes the URL."""
    runner = CliRunner()
    with patch("mahavishnu.repo_cli.create_pr") as mock_create:
        mock_create.return_value = "https://github.com/owner/repo/pull/1"
        result = runner.invoke(
            repo_cli.repo_app,
            ["pr-create", "--path", KNOWN_REPO_PATH],
        )
    assert result.exit_code == 0
    mock_create.assert_called_once_with(KNOWN_REPO_PATH)
    assert "https://github.com/owner/repo/pull/1" in result.output