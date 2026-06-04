"""Unit tests for mahavishnu.backup_cli.add_backup_commands.

Verifies the backup CLI sub-typer is registered correctly on the parent app
and that every subcommand is discoverable via ``--help``. Heavy modules
(MahavishnuApp, BackupManager, DisasterRecoveryManager) are never reached
because the source keeps their imports inside the command bodies; the
fixture below patches them anyway as a safety net so future refactors
that hoist the imports do not slow these tests down.

These tests intentionally avoid executing the actual command bodies.
The focus is on CLI *structure*: that the sub-typer is registered, every
command is wired up, the ``--type`` option is recognized, and the
positional ``BACKUP_ID`` argument is required.

Run standalone:
    python tests/unit/test_backup_cli.py

Run with pytest:
    pytest tests/unit/test_backup_cli.py
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.backup_cli import add_backup_commands


# Every subcommand registered by add_backup_commands. Order is preserved
# for deterministic help-text traversal in the parametrized tests below.
EXPECTED_SUBCOMMANDS: list[str] = [
    "create",
    "list",
    "restore",
    "info",
    "check",
    "procedures",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """A fresh CliRunner for every test (Click/Typer captures stdout per call)."""
    return CliRunner()


@pytest.fixture
def app() -> typer.Typer:
    """A parent Typer app with the backup sub-typer attached."""
    parent = typer.Typer()
    add_backup_commands(parent)
    return parent


@pytest.fixture(autouse=True)
def _patch_heavy_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety net: short-circuit the heavy import chain.

    The source keeps the heavy imports inside the command bodies, so a
    --help invocation never touches them. This fixture replaces them
    with MagicMocks at the module level so a future hoist-to-top refactor
    cannot accidentally drag the filesystem, asyncpg, or redis into a
    structural test.
    """
    fake_app = MagicMock(name="MahavishnuApp")
    fake_bm = MagicMock(name="BackupManager")
    fake_drm = MagicMock(name="DisasterRecoveryManager")
    monkeypatch.setattr("mahavishnu.core.app.MahavishnuApp", fake_app)
    monkeypatch.setattr("mahavishnu.core.backup_recovery.BackupManager", fake_bm)
    monkeypatch.setattr(
        "mahavishnu.core.backup_recovery.DisasterRecoveryManager", fake_drm
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


def test_add_backup_commands_attaches_subtyper(app: typer.Typer) -> None:
    """add_backup_commands registers exactly one sub-typer on the parent app."""
    assert len(app.registered_groups) == 1
    group = app.registered_groups[0]
    assert group.name == "backup"


def test_backup_subcommand_listed_in_parent(app: typer.Typer) -> None:
    """The literal name 'backup' is discoverable on the parent's groups."""
    names = [group.name for group in app.registered_groups]
    assert "backup" in names


def test_top_level_help_runs(runner: CliRunner, app: typer.Typer) -> None:
    """Invoking 'backup --help' exits 0 and prints backup-related content."""
    result = runner.invoke(app, ["backup", "--help"])
    assert result.exit_code == 0
    assert "backup" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Discoverability tests
# ---------------------------------------------------------------------------


def test_every_subcommand_help_runs(runner: CliRunner, app: typer.Typer) -> None:
    """Each registered subcommand must be invokable with --help and exit 0."""
    for sub in EXPECTED_SUBCOMMANDS:
        result = runner.invoke(app, ["backup", sub, "--help"])
        assert result.exit_code == 0, f"backup {sub} --help exited {result.exit_code}"


def test_every_subcommand_help_has_usage_block(
    runner: CliRunner, app: typer.Typer
) -> None:
    """Each --help output must include a Typer-generated 'Usage:' line."""
    for sub in EXPECTED_SUBCOMMANDS:
        result = runner.invoke(app, ["backup", sub, "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.stdout, f"backup {sub} --help missing Usage block"


def test_every_subcommand_help_is_nonempty(
    runner: CliRunner, app: typer.Typer
) -> None:
    """Each --help output must be more than a blank stub."""
    for sub in EXPECTED_SUBCOMMANDS:
        result = runner.invoke(app, ["backup", sub, "--help"])
        assert result.exit_code == 0
        assert len(result.stdout.strip()) > 0, f"backup {sub} --help is empty"


def test_top_level_help_lists_all_subcommands(
    runner: CliRunner, app: typer.Typer
) -> None:
    """'backup --help' should list every subcommand name in its output."""
    result = runner.invoke(app, ["backup", "--help"])
    assert result.exit_code == 0
    for sub in EXPECTED_SUBCOMMANDS:
        assert sub in result.stdout, f"subcommand {sub!r} missing from backup --help"


# ---------------------------------------------------------------------------
# Option & argument registration tests
# ---------------------------------------------------------------------------


def test_create_advertises_type_option(runner: CliRunner, app: typer.Typer) -> None:
    """'backup create --help' must mention both --type and -t."""
    result = runner.invoke(app, ["backup", "create", "--help"])
    assert result.exit_code == 0
    assert "--type" in result.stdout
    assert "-t" in result.stdout


def test_create_advertises_full_default(runner: CliRunner, app: typer.Typer) -> None:
    """The default value 'full' is rendered by Typer in the help output."""
    result = runner.invoke(app, ["backup", "create", "--help"])
    assert result.exit_code == 0
    # Typer renders the default value in brackets, e.g. "[default: full]".
    assert "full" in result.stdout.lower()


def test_create_accepts_type_with_help(runner: CliRunner, app: typer.Typer) -> None:
    """Passing --type together with --help should still succeed (--help wins)."""
    result = runner.invoke(
        app,
        ["backup", "create", "--type", "incremental", "--help"],
    )
    assert result.exit_code == 0
    # The --type option must be registered — it appears in the help text.
    assert "--type" in result.stdout


def test_restore_advertises_backup_id_argument(
    runner: CliRunner, app: typer.Typer
) -> None:
    """'restore' must declare a BACKUP_ID argument in its help text."""
    result = runner.invoke(app, ["backup", "restore", "--help"])
    assert result.exit_code == 0
    # Typer renders positional args in uppercase in the Usage line.
    assert "BACKUP_ID" in result.stdout


def test_info_advertises_backup_id_argument(
    runner: CliRunner, app: typer.Typer
) -> None:
    """'info' must declare a BACKUP_ID argument in its help text."""
    result = runner.invoke(app, ["backup", "info", "--help"])
    assert result.exit_code == 0
    assert "BACKUP_ID" in result.stdout


def test_restore_missing_argument_fails(
    runner: CliRunner, app: typer.Typer
) -> None:
    """Invoking 'restore' with no backup_id must exit non-zero."""
    result = runner.invoke(app, ["backup", "restore"])
    assert result.exit_code != 0


def test_info_missing_argument_fails(runner: CliRunner, app: typer.Typer) -> None:
    """Invoking 'info' with no backup_id must exit non-zero."""
    result = runner.invoke(app, ["backup", "info"])
    assert result.exit_code != 0


def test_no_arg_subcommands_have_no_positional(
    runner: CliRunner, app: typer.Typer
) -> None:
    """'list', 'check', 'procedures' take no positional BACKUP_ID."""
    for sub in ("list", "check", "procedures"):
        result = runner.invoke(app, ["backup", sub, "--help"])
        assert result.exit_code == 0
        assert "BACKUP_ID" not in result.stdout, (
            f"backup {sub} unexpectedly requires BACKUP_ID"
        )
