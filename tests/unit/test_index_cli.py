"""Unit tests for mahavishnu.cli.index_cli.

Verifies the index sub-typer is registered correctly, every subcommand
is discoverable via ``--help``, and the failure/success branches of the
command bodies run end-to-end. Heavy filesystem/git work in the
downstream helpers is patched at the function boundary so the tests
remain pure logic.

Run standalone:
    python tests/unit/test_index_cli.py

Run with pytest:
    pytest tests/unit/test_index_cli.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.cli.index_cli import add_index_commands
from mahavishnu.core.code_index.models import IndexWorkItem

EXPECTED_SUBCOMMANDS: list[str] = [
    "repo",
    "status",
    "install-hooks",
    "uninstall-hooks",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def app() -> typer.Typer:
    parent = typer.Typer()
    add_index_commands(parent)
    return parent


@pytest.fixture
def fake_work_item() -> IndexWorkItem:
    """A complete IndexWorkItem used as a canned return for index_repo."""
    return IndexWorkItem(
        repo_path="/tmp/registered",
        trigger="manual",
        files_changed=["a.py", "b.py"],
        status="complete",
        parse_failures=0,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_add_index_commands_attaches_subtyper(app: typer.Typer) -> None:
    """add_index_commands registers exactly one sub-typer named 'index'."""
    assert len(app.registered_groups) == 1
    assert app.registered_groups[0].name == "index"


def test_index_group_listed_in_parent(app: typer.Typer) -> None:
    names = [g.name for g in app.registered_groups]
    assert "index" in names


def test_index_top_level_help_runs(runner: CliRunner, app: typer.Typer) -> None:
    result = runner.invoke(app, ["index", "--help"])
    assert result.exit_code == 0
    assert "index" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Discoverability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sub", EXPECTED_SUBCOMMANDS)
def test_every_subcommand_help_runs(runner: CliRunner, app: typer.Typer, sub: str) -> None:
    result = runner.invoke(app, ["index", sub, "--help"])
    assert result.exit_code == 0, f"index {sub} --help exited {result.exit_code}"


# ---------------------------------------------------------------------------
# `index repo` command
# ---------------------------------------------------------------------------


def test_index_repo_rejects_unregistered_path(runner: CliRunner, app: typer.Typer) -> None:
    """Unknown repo paths cause validate_repo_path to raise ValueError,
    which Typer surfaces as a non-zero exit code."""
    with patch(
        "mahavishnu.cli.index_cli.validate_repo_path",
        side_effect=ValueError("not registered"),
    ):
        result = runner.invoke(app, ["index", "repo", "/no/such/repo"])
    # Typer surfaces the exception via exit_code 1; the message ends up in
    # the exception string but not in result.output.
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)


def test_index_repo_success_prints_summary(
    runner: CliRunner, app: typer.Typer, fake_work_item: IndexWorkItem
) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.indexer.index_repo",
            return_value=fake_work_item,
        ),
    ):
        result = runner.invoke(app, ["index", "repo", "/tmp/registered"])
    assert result.exit_code == 0
    assert "Indexing /tmp/registered" in result.output
    assert "Status: complete" in result.output
    assert "Files: 2" in result.output
    assert "Failures: 0" in result.output


def test_index_repo_failed_status_exits_nonzero(runner: CliRunner, app: typer.Typer) -> None:
    failed = IndexWorkItem(
        repo_path="/tmp/registered",
        trigger="manual",
        files_changed=[],
        status="failed",
        parse_failures=0,
    )
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.indexer.index_repo",
            return_value=failed,
        ),
    ):
        result = runner.invoke(app, ["index", "repo", "/tmp/registered"])
    assert result.exit_code == 1
    assert "Status: failed" in result.output


def test_index_repo_passes_full_and_trigger_flags(
    runner: CliRunner, app: typer.Typer, fake_work_item: IndexWorkItem
) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.indexer.index_repo",
            return_value=fake_work_item,
        ) as mock_index,
    ):
        result = runner.invoke(
            app,
            ["index", "repo", "/tmp/registered", "--full", "--trigger", "schedule"],
        )
    assert result.exit_code == 0
    mock_index.assert_called_once_with("/tmp/registered", trigger="schedule", full=True)


# ---------------------------------------------------------------------------
# `index status` command
# ---------------------------------------------------------------------------


def test_index_status_empty_registry(runner: CliRunner, app: typer.Typer) -> None:
    with patch(
        "mahavishnu.core.code_index.path_validation.get_registered_repos",
        return_value=set(),
    ):
        result = runner.invoke(app, ["index", "status"])
    assert result.exit_code == 0
    assert "No repositories registered" in result.output


def test_index_status_lists_repos_and_indexed_state(runner: CliRunner, app: typer.Typer) -> None:
    with (
        patch(
            "mahavishnu.core.code_index.path_validation.get_registered_repos",
            return_value={"/r/alpha", "/r/beta"},
        ),
        patch(
            "mahavishnu.core.code_index.indexer.get_last_indexed_commit",
            side_effect=lambda p: "abcdef1234567890" if p == "/r/alpha" else None,
        ),
    ):
        result = runner.invoke(app, ["index", "status"])
    assert result.exit_code == 0
    assert "Registered repos: 2" in result.output
    assert "/r/alpha: last indexed: abcdef12" in result.output
    assert "/r/beta: not indexed" in result.output


# ---------------------------------------------------------------------------
# `index install-hooks` / `index uninstall-hooks`
# ---------------------------------------------------------------------------


def test_index_install_hooks_prints_installed_names(runner: CliRunner, app: typer.Typer) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.git_hooks.install_hooks",
            return_value=["post-commit", "post-merge", "post-rewrite"],
        ),
    ):
        result = runner.invoke(app, ["index", "install-hooks", "/tmp/registered"])
    assert result.exit_code == 0
    assert "Installed hooks: post-commit, post-merge, post-rewrite" in result.output


def test_index_install_hooks_passes_force_flag(runner: CliRunner, app: typer.Typer) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.git_hooks.install_hooks",
            return_value=["post-commit"],
        ) as mock_install,
    ):
        result = runner.invoke(app, ["index", "install-hooks", "/tmp/registered", "--force"])
    assert result.exit_code == 0
    mock_install.assert_called_once_with("/tmp/registered", force=True)


def test_index_uninstall_hooks_prints_removed_names(runner: CliRunner, app: typer.Typer) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.git_hooks.uninstall_hooks",
            return_value=["post-commit", "post-merge"],
        ),
    ):
        result = runner.invoke(app, ["index", "uninstall-hooks", "/tmp/registered"])
    assert result.exit_code == 0
    assert "Removed hooks: post-commit, post-merge" in result.output


def test_index_uninstall_hooks_none_removed_message(runner: CliRunner, app: typer.Typer) -> None:
    with (
        patch(
            "mahavishnu.cli.index_cli.validate_repo_path",
            return_value="/tmp/registered",
        ),
        patch(
            "mahavishnu.core.code_index.git_hooks.uninstall_hooks",
            return_value=[],
        ),
    ):
        result = runner.invoke(app, ["index", "uninstall-hooks", "/tmp/registered"])
    assert result.exit_code == 0
    assert "Removed hooks: none" in result.output
