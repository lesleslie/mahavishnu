"""Comprehensive unit tests for the backup CLI module.

Tests cover all CLI commands registered on the backup sub-app:
- backup create (full, incremental, error handling)
- backup list (with backups, empty)
- backup restore (success, failure, error handling)
- backup info (found, not found)
- backup check (disaster recovery)
- backup procedures (recovery documentation)

All file I/O and external operations are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import typer
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures: mock data helpers
# ---------------------------------------------------------------------------


def _make_backup_info(
    backup_id: str = "backup_20260424_120000_000000",
    size_bytes: int = 10 * 1024 * 1024,
    status: str = "completed",
    files_backed_up: int = 5,
    checksum: str = "abc123",
) -> MagicMock:
    """Create a mock BackupInfo object."""
    info = MagicMock()
    info.backup_id = backup_id
    info.timestamp = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)
    info.size_bytes = size_bytes
    info.location = f"/tmp/backups/{backup_id}.tar.gz"
    info.status = status
    info.files_backed_up = files_backed_up
    info.checksum = checksum
    return info


def _make_app() -> typer.Typer:
    """Create a parent Typer app with backup commands registered."""
    app = typer.Typer()
    from mahavishnu.backup_cli import add_backup_commands

    add_backup_commands(app)
    return app


def _make_mock_mahavishnu_app() -> MagicMock:
    """Create a mock MahavishnuApp with minimal config."""
    mock_app = MagicMock()
    mock_app.config = MagicMock()
    mock_app.config.backup_directory = "/tmp/test_backups"
    mock_app.config.model_dump.return_value = {"server_name": "test"}
    mock_app.workflow_state_manager = AsyncMock()
    mock_app.workflow_state_manager.list_workflows.return_value = []
    return mock_app


def _fake_asyncio_run(coro):
    """Replace asyncio.run to execute coroutines directly."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# add_backup_commands
# ===========================================================================


class TestAddBackupCommands:
    """Tests for add_backup_commands()."""

    def test_registers_backup_sub_app(self):
        """add_backup_commands should attach a 'backup' sub-app."""
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "backup" in registered_names


# ===========================================================================
# backup create
# ===========================================================================


class TestBackupCreate:
    """Tests for the 'backup create' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_backup_full_default(self, mock_bm_cls, mock_app_cls):
        """Full backup should succeed with default type."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        backup_info = _make_backup_info()
        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(return_value=backup_info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create"])
        assert result.exit_code == 0
        assert "Backup created" in result.output
        assert backup_info.backup_id in result.output
        assert "Location:" in result.output
        assert "Size:" in result.output
        assert "Time:" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_backup_incremental(self, mock_bm_cls, mock_app_cls):
        """Incremental backup should use the specified type."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        backup_info = _make_backup_info()
        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(return_value=backup_info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create", "--type", "incremental"])
        assert result.exit_code == 0
        mock_bm.create_backup.assert_called_once_with("incremental")

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_backup_short_flag(self, mock_bm_cls, mock_app_cls):
        """Short flag -t should work for backup type."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        backup_info = _make_backup_info()
        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(return_value=backup_info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create", "-t", "incremental"])
        assert result.exit_code == 0
        mock_bm.create_backup.assert_called_once_with("incremental")

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_backup_shows_size_mb(self, mock_bm_cls, mock_app_cls):
        """Backup output should show size in MB."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        # 5 MB backup
        backup_info = _make_backup_info(size_bytes=5 * 1024 * 1024)
        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(return_value=backup_info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create"])
        assert result.exit_code == 0
        assert "5.00 MB" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_backup_error(self, mock_bm_cls, mock_app_cls):
        """Backup creation error should exit with code 1."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(side_effect=RuntimeError("Disk full"))
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create"])
        assert result.exit_code == 1
        assert "Backup failed" in result.output
        assert "Disk full" in result.output


# ===========================================================================
# backup list
# ===========================================================================


class TestBackupList:
    """Tests for the 'backup list' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_list_backups_with_results(self, mock_bm_cls, mock_app_cls):
        """Should list all available backups."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        backup1 = _make_backup_info(backup_id="backup_001", size_bytes=2 * 1024 * 1024)
        backup2 = _make_backup_info(
            backup_id="backup_002",
            size_bytes=5 * 1024 * 1024,
            status="available",
        )
        mock_bm = MagicMock()
        mock_bm.list_backups = AsyncMock(return_value=[backup1, backup2])
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "list"])
        assert result.exit_code == 0
        assert "Found 2 backup(s)" in result.output
        assert "backup_001" in result.output
        assert "backup_002" in result.output
        assert "Time:" in result.output
        assert "Size:" in result.output
        assert "Status:" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_list_backups_empty(self, mock_bm_cls, mock_app_cls):
        """Empty backup list should show informational message."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.list_backups = AsyncMock(return_value=[])
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "list"])
        assert result.exit_code == 0
        assert "No backups found" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_list_backups_single(self, mock_bm_cls, mock_app_cls):
        """Single backup should be listed correctly."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        backup = _make_backup_info(backup_id="backup_only")
        mock_bm = MagicMock()
        mock_bm.list_backups = AsyncMock(return_value=[backup])
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "list"])
        assert result.exit_code == 0
        assert "Found 1 backup(s)" in result.output
        assert "backup_only" in result.output


# ===========================================================================
# backup restore
# ===========================================================================


class TestBackupRestore:
    """Tests for the 'backup restore' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_restore_backup_success(self, mock_bm_cls, mock_app_cls):
        """Successful restore should show success message."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.restore_backup = AsyncMock(return_value=True)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "restore", "backup_001"])
        assert result.exit_code == 0
        assert "Restored backup" in result.output
        assert "backup_001" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_restore_backup_failure(self, mock_bm_cls, mock_app_cls):
        """Restore returning False should exit with code 1."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.restore_backup = AsyncMock(return_value=False)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "restore", "backup_bad"])
        assert result.exit_code == 1
        assert "Restore failed" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_restore_backup_error(self, mock_bm_cls, mock_app_cls):
        """Restore exception should exit with code 1 and show error."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.restore_backup = AsyncMock(side_effect=FileNotFoundError("Backup not found"))
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "restore", "backup_missing"])
        assert result.exit_code == 1
        assert "Restore error" in result.output

    def test_restore_backup_missing_argument(self):
        """Missing backup ID argument should show error."""
        app = _make_app()
        result = runner.invoke(app, ["backup", "restore"])
        assert result.exit_code != 0


# ===========================================================================
# backup info
# ===========================================================================


class TestBackupInfo:
    """Tests for the 'backup info' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_backup_info_found(self, mock_bm_cls, mock_app_cls):
        """Should display backup information when found."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        info = _make_backup_info(
            backup_id="backup_info_test",
            files_backed_up=42,
            checksum="sha256abc123",
        )
        mock_bm = MagicMock()
        mock_bm.get_backup_info = AsyncMock(return_value=info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "info", "backup_info_test"])
        assert result.exit_code == 0
        assert "Backup ID: backup_info_test" in result.output
        assert "Time:" in result.output
        assert "Size:" in result.output
        assert "Location:" in result.output
        assert "Status: completed" in result.output
        assert "Files: 42" in result.output
        assert "Checksum: sha256abc123" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_backup_info_not_found(self, mock_bm_cls, mock_app_cls):
        """Should exit with code 1 when backup not found."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.get_backup_info = AsyncMock(return_value=None)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "info", "nonexistent"])
        assert result.exit_code == 1
        assert "Backup not found" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_backup_info_no_checksum(self, mock_bm_cls, mock_app_cls):
        """Should not show checksum line when checksum is empty."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        info = _make_backup_info(checksum="")
        mock_bm = MagicMock()
        mock_bm.get_backup_info = AsyncMock(return_value=info)
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "info", "backup_nochk"])
        assert result.exit_code == 0
        assert "Checksum:" not in result.output

    def test_backup_info_missing_argument(self):
        """Missing backup ID argument should show error."""
        app = _make_app()
        result = runner.invoke(app, ["backup", "info"])
        assert result.exit_code != 0


# ===========================================================================
# backup check
# ===========================================================================


class TestBackupCheck:
    """Tests for the 'backup check' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.DisasterRecoveryManager")
    def test_check_healthy(self, mock_drm_cls, mock_app_cls):
        """Healthy disaster recovery check should pass."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_drm = MagicMock()
        mock_drm.run_disaster_recovery_check = AsyncMock(
            return_value={
                "status": "healthy",
                "checks": {
                    "backups_available": {"status": "pass", "count": 3},
                    "backup_integrity": {"status": "pass", "checked": 3, "failed": 0},
                    "recent_backup": {"status": "pass", "latest_backup_age_hours": 2.0},
                },
            }
        )
        mock_drm_cls.return_value = mock_drm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "check"])
        assert result.exit_code == 0
        assert "Status: healthy" in result.output
        assert "backups_available" in result.output
        assert "backup_integrity" in result.output
        assert "recent_backup" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.DisasterRecoveryManager")
    def test_check_needs_attention(self, mock_drm_cls, mock_app_cls):
        """Check with failures should show needs_attention status."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_drm = MagicMock()
        mock_drm.run_disaster_recovery_check = AsyncMock(
            return_value={
                "status": "needs_attention",
                "checks": {
                    "backups_available": {"status": "fail", "count": 0},
                    "backup_integrity": {"status": "fail", "checked": 0, "failed": 0},
                    "recent_backup": {"status": "fail", "latest_backup_age_hours": 48.0},
                },
            }
        )
        mock_drm_cls.return_value = mock_drm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "check"])
        assert result.exit_code == 0
        assert "Status: needs_attention" in result.output

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.DisasterRecoveryManager")
    def test_check_mixed_results(self, mock_drm_cls, mock_app_cls):
        """Mixed pass/fail results should show individual statuses."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_drm = MagicMock()
        mock_drm.run_disaster_recovery_check = AsyncMock(
            return_value={
                "status": "needs_attention",
                "checks": {
                    "backups_available": {"status": "pass", "count": 5},
                    "backup_integrity": {"status": "fail", "checked": 2, "failed": 1},
                    "recent_backup": {"status": "pass", "latest_backup_age_hours": 1.0},
                },
            }
        )
        mock_drm_cls.return_value = mock_drm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "check"])
        assert result.exit_code == 0
        # Should show check names
        assert "backups_available" in result.output
        assert "backup_integrity" in result.output
        assert "recent_backup" in result.output


# ===========================================================================
# backup procedures
# ===========================================================================


class TestBackupProcedures:
    """Tests for the 'backup procedures' command."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.DisasterRecoveryManager")
    def test_procedures_output(self, mock_drm_cls, mock_app_cls):
        """Should display recovery procedures as JSON."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        procedures = {
            "procedures": {
                "emergency_contact": "admin@example.com",
                "recovery_steps": [
                    "Assess the scope",
                    "Identify backup",
                ],
                "recovery_time_objective": "4 hours",
            },
            "automation": {
                "automatic_backup": True,
                "backup_frequency": "daily",
            },
        }
        mock_drm = MagicMock()
        mock_drm.get_recovery_procedures = AsyncMock(return_value=procedures)
        mock_drm_cls.return_value = mock_drm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "procedures"])
        assert result.exit_code == 0
        assert "admin@example.com" in result.output
        assert "Assess the scope" in result.output
        assert "4 hours" in result.output
        assert "daily" in result.output


# ===========================================================================
# asyncio.run edge case
# ===========================================================================


class TestAsyncioRunEdgeCases:
    """Tests for asyncio.run edge cases in backup CLI."""

    @patch("mahavishnu.core.app.MahavishnuApp")
    @patch("mahavishnu.core.backup_recovery.BackupManager")
    def test_create_raises_typer_exit(self, mock_bm_cls, mock_app_cls):
        """When create_backup raises, the inner function should propagate typer.Exit."""
        mock_app = _make_mock_mahavishnu_app()
        mock_app_cls.return_value = mock_app

        mock_bm = MagicMock()
        mock_bm.create_backup = AsyncMock(side_effect=ValueError("corrupt"))
        mock_bm_cls.return_value = mock_bm

        with patch("mahavishnu.backup_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["backup", "create"])
        assert result.exit_code == 1
        assert "Backup failed" in result.output
