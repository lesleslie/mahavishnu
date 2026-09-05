"""Behavioral coverage for the backup and recovery CLI commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu import backup_cli
from mahavishnu.core import app as app_module
from mahavishnu.core import backup_recovery as backup_recovery_module


@dataclass
class BackupRecord:
    """Small stand-in for ``BackupInfo`` used by the CLI output paths."""

    backup_id: str
    timestamp: datetime
    size_bytes: int
    location: str
    status: str
    files_backed_up: int
    checksum: str


@dataclass
class BackendState:
    """Configurable behavior and call history for fake backend managers."""

    create_result: BackupRecord | None = None
    create_error: Exception | None = None
    list_result: list[BackupRecord] = field(default_factory=list)
    list_error: Exception | None = None
    restore_result: bool = True
    restore_error: Exception | None = None
    info_result: BackupRecord | None = None
    info_error: Exception | None = None
    check_result: dict[str, object] = field(default_factory=dict)
    check_error: Exception | None = None
    procedures_result: dict[str, object] = field(default_factory=dict)
    procedures_error: Exception | None = None
    create_calls: list[str] = field(default_factory=list)
    list_calls: int = 0
    restore_calls: list[str] = field(default_factory=list)
    info_calls: list[str] = field(default_factory=list)
    app_instances: int = 0
    backup_manager_apps: list[object] = field(default_factory=list)
    recovery_manager_apps: list[object] = field(default_factory=list)


@pytest.fixture
def runner() -> CliRunner:
    """Return a fresh Typer test runner."""
    return CliRunner()


@pytest.fixture
def cli_app() -> typer.Typer:
    """Build a parent app with the backup command group attached."""
    app = typer.Typer()
    backup_cli.add_backup_commands(app)
    return app


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> BackendState:
    """Replace lazily imported backend classes with configurable fakes.

    The production module imports these classes inside each command helper, so
    the patch targets the modules that own the classes rather than
    ``mahavishnu.backup_cli``.
    """
    state = BackendState()

    class FakeApp:
        def __init__(self) -> None:
            state.app_instances += 1

    class FakeBackupManager:
        def __init__(self, app: object) -> None:
            state.backup_manager_apps.append(app)

        async def create_backup(self, backup_type: str) -> BackupRecord:
            state.create_calls.append(backup_type)
            if state.create_error is not None:
                raise state.create_error
            if state.create_result is None:
                raise RuntimeError("test create result was not configured")
            return state.create_result

        async def list_backups(self) -> list[BackupRecord]:
            state.list_calls += 1
            if state.list_error is not None:
                raise state.list_error
            return state.list_result

        async def restore_backup(self, backup_id: str) -> bool:
            state.restore_calls.append(backup_id)
            if state.restore_error is not None:
                raise state.restore_error
            return state.restore_result

        async def get_backup_info(self, backup_id: str) -> BackupRecord | None:
            state.info_calls.append(backup_id)
            if state.info_error is not None:
                raise state.info_error
            return state.info_result

    class FakeRecoveryManager:
        def __init__(self, app: object) -> None:
            state.recovery_manager_apps.append(app)

        async def run_disaster_recovery_check(self) -> dict[str, object]:
            if state.check_error is not None:
                raise state.check_error
            return state.check_result

        async def get_recovery_procedures(self) -> dict[str, object]:
            if state.procedures_error is not None:
                raise state.procedures_error
            return state.procedures_result

    monkeypatch.setattr(app_module, "MahavishnuApp", FakeApp)
    monkeypatch.setattr(backup_recovery_module, "BackupManager", FakeBackupManager)
    monkeypatch.setattr(
        backup_recovery_module,
        "DisasterRecoveryManager",
        FakeRecoveryManager,
    )
    return state


def _record(
    backup_id: str = "backup_20260905_120000_000001",
    *,
    checksum: str = "abc123",
    status: str = "completed",
) -> BackupRecord:
    """Construct a deterministic record for output assertions."""
    return BackupRecord(
        backup_id=backup_id,
        timestamp=datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        size_bytes=2 * 1024 * 1024 + 512,
        location=f"/tmp/{backup_id}.tar.gz",
        status=status,
        files_backed_up=7,
        checksum=checksum,
    )


@pytest.mark.unit
def test_create_command_success_uses_requested_backup_type(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A successful create prints the returned backup metadata."""
    backend.create_result = _record()

    result = runner.invoke(cli_app, ["backup", "create", "--type", "incremental"])

    assert result.exit_code == 0
    assert "Backup created: backup_20260905_120000_000001" in result.stdout
    assert "Location: /tmp/backup_20260905_120000_000001.tar.gz" in result.stdout
    assert "Size: 2.00 MB" in result.stdout
    assert "Time: 2026-09-05T12:00:00+00:00" in result.stdout
    assert backend.create_calls == ["incremental"]
    assert len(backend.backup_manager_apps) == 1


@pytest.mark.unit
def test_create_command_failure_returns_exit_one(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A create exception is rendered as an error and converted to exit 1."""
    backend.create_error = RuntimeError("storage unavailable")

    result = runner.invoke(cli_app, ["backup", "create"])

    assert result.exit_code == 1
    assert "Backup failed: storage unavailable" in result.output
    assert backend.create_calls == ["full"]


@pytest.mark.unit
def test_list_command_prints_all_available_backup_fields(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """Listing backups renders each record and its status."""
    backend.list_result = [
        _record("backup_new", status="available"),
        _record("backup_old", status="completed"),
    ]

    result = runner.invoke(cli_app, ["backup", "list"])

    assert result.exit_code == 0
    assert "Found 2 backup(s):" in result.stdout
    assert "- backup_new" in result.stdout
    assert "- backup_old" in result.stdout
    assert result.stdout.count("Time: 2026-09-05T12:00:00+00:00") == 2
    assert result.stdout.count("Size: 2.00 MB") == 2
    assert "Status: available" in result.stdout
    assert "Status: completed" in result.stdout
    assert backend.list_calls == 1


@pytest.mark.unit
def test_list_command_reports_when_no_backups_exist(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """An empty list gets a friendly success response."""
    result = runner.invoke(cli_app, ["backup", "list"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "No backups found"
    assert backend.list_calls == 1


@pytest.mark.unit
def test_list_command_propagates_backend_error_as_cli_failure(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A list backend failure produces a non-zero command result."""
    backend.list_error = RuntimeError("database is offline")

    result = runner.invoke(cli_app, ["backup", "list"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert backend.list_calls == 1


@pytest.mark.unit
def test_restore_command_confirms_success(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A truthy restore result prints the restored backup ID."""
    backup_id = "backup_restore_me"

    result = runner.invoke(cli_app, ["backup", "restore", backup_id])

    assert result.exit_code == 0
    assert f"Restored backup: {backup_id}" in result.stdout
    assert backend.restore_calls == [backup_id]


@pytest.mark.unit
def test_restore_command_handles_false_result(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A false restore result prints ONLY ``Restore failed`` (not ``Restore error:``).

    Regression: previously the broad ``except Exception`` caught the
    ``typer.Exit(1)`` raised on the False path, causing the user to see
    BOTH "Restore failed: ..." and "Restore error: ...". The fix moves the
    False-path exit OUT of the try so only the genuine-exception path
    produces the "Restore error:" message.
    """
    backup_id = "backup_not_restored"
    backend.restore_result = False

    result = runner.invoke(cli_app, ["backup", "restore", backup_id])

    assert result.exit_code == 1
    assert "Restore failed: backup_not_restored" in result.output
    assert "Restore error:" not in result.output
    assert backend.restore_calls == [backup_id]


@pytest.mark.unit
def test_restore_command_handles_backend_exception(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A restore exception is rendered and converted to exit 1."""
    backend.restore_error = ValueError("corrupt archive")

    result = runner.invoke(cli_app, ["backup", "restore", "backup_bad"])

    assert result.exit_code == 1
    assert "Restore error: corrupt archive" in result.output


@pytest.mark.unit
def test_info_command_prints_metadata_and_checksum(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """Info displays all fields, including a non-empty checksum."""
    backup_id = "backup_details"
    backend.info_result = _record(backup_id)

    result = runner.invoke(cli_app, ["backup", "info", backup_id])

    assert result.exit_code == 0
    assert "Backup ID: backup_details" in result.stdout
    assert "Time: 2026-09-05T12:00:00+00:00" in result.stdout
    assert "Size: 2.00 MB" in result.stdout
    assert "Location: /tmp/backup_details.tar.gz" in result.stdout
    assert "Status: completed" in result.stdout
    assert "Files: 7" in result.stdout
    assert "Checksum: abc123" in result.stdout
    assert backend.info_calls == [backup_id]


@pytest.mark.unit
def test_info_command_omits_empty_checksum(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """Info does not print a checksum line when the record has none."""
    backend.info_result = _record("backup_without_checksum", checksum="")

    result = runner.invoke(cli_app, ["backup", "info", "backup_without_checksum"])

    assert result.exit_code == 0
    assert "Backup ID: backup_without_checksum" in result.stdout
    assert "Checksum:" not in result.stdout


@pytest.mark.unit
def test_info_command_fails_for_unknown_backup(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A missing record produces an error and exit code 1."""
    backup_id = "backup_missing"

    result = runner.invoke(cli_app, ["backup", "info", backup_id])

    assert result.exit_code == 1
    assert f"Backup not found: {backup_id}" in result.output
    assert backend.info_calls == [backup_id]


@pytest.mark.unit
def test_info_command_propagates_backend_error(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A backend exception in info produces a failed CLI invocation."""
    backend.info_error = OSError("metadata read failed")

    result = runner.invoke(cli_app, ["backup", "info", "backup_error"])

    assert result.exit_code == 1
    assert isinstance(result.exception, OSError)


@pytest.mark.unit
def test_check_command_renders_pass_and_fail_checks(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """The check command maps check statuses to the expected symbols."""
    backend.check_result = {
        "status": "needs_attention",
        "checks": {
            "backups_available": {"status": "pass"},
            "backup_integrity": {"status": "fail"},
            "recent_backup": {"status": "pass"},
        },
    }

    result = runner.invoke(cli_app, ["backup", "check"])

    assert result.exit_code == 0
    assert "Status: needs_attention" in result.stdout
    assert "Checks:" in result.stdout
    assert "✓ backups_available: pass" in result.stdout
    assert "✗ backup_integrity: fail" in result.stdout
    assert "✓ recent_backup: pass" in result.stdout


@pytest.mark.unit
def test_check_command_propagates_backend_error(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A disaster-recovery check backend error makes the command fail."""
    backend.check_error = RuntimeError("checker unavailable")

    result = runner.invoke(cli_app, ["backup", "check"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)


@pytest.mark.unit
def test_procedures_command_prints_indented_json(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """The procedures command serializes the manager response as JSON."""
    backend.procedures_result = {
        "procedures": {"contact": "ops@example.com", "steps": ["assess", "restore"]},
        "automation": {"enabled": True},
    }

    result = runner.invoke(cli_app, ["backup", "procedures"])

    assert result.exit_code == 0
    assert '"procedures": {' in result.stdout
    assert '"contact": "ops@example.com"' in result.stdout
    assert '"steps": [' in result.stdout
    assert '"automation": {' in result.stdout
    assert '"enabled": true' in result.stdout


@pytest.mark.unit
def test_procedures_command_propagates_backend_error(
    runner: CliRunner,
    cli_app: typer.Typer,
    backend: BackendState,
) -> None:
    """A procedures backend failure produces a non-zero result."""
    backend.procedures_error = RuntimeError("runbook unavailable")

    result = runner.invoke(cli_app, ["backup", "procedures"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
