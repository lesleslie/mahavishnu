"""Unit tests for backup and recovery functionality."""

from datetime import UTC, datetime
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
from unittest.mock import AsyncMock, Mock

import pytest
import typer

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.backup_recovery import (
    BackupInfo,
    BackupManager,
    DisasterRecoveryManager,
)


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.adapters = {}
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    return app


@pytest.mark.asyncio
async def test_backup_info_structure():
    """Test the structure of BackupInfo dataclass."""
    backup_info = BackupInfo(
        backup_id="test_backup_123",
        timestamp=datetime.now(UTC),
        size_bytes=1024,
        location="/path/to/backup.tar.gz",
        status="completed",
        files_backed_up=10,
        checksum="abc123",
    )

    # Verify all fields are set correctly
    assert backup_info.backup_id == "test_backup_123"
    assert isinstance(backup_info.timestamp, datetime)
    assert backup_info.size_bytes == 1024
    assert backup_info.location == "/path/to/backup.tar.gz"
    assert backup_info.status == "completed"
    assert backup_info.files_backed_up == 10
    assert backup_info.checksum == "abc123"


@pytest.mark.asyncio
async def test_backup_manager_initialization():
    """Test that BackupManager initializes correctly."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"

    backup_manager = BackupManager(app)

    # Verify backup directory was created
    assert backup_manager.backup_dir.exists()
    assert backup_manager.backup_dir.name == "test_backups"


@pytest.mark.asyncio
async def test_backup_manager_create_backup():
    """Test creating a backup."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a mock app with a temporary backup directory
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        # Create a backup
        backup_info = await backup_manager.create_backup("full")

        # Verify backup was created
        assert backup_info is not None
        assert backup_info.backup_id.startswith("backup_")
        assert backup_info.status == "completed"
        assert backup_info.size_bytes > 0
        assert backup_info.files_backed_up >= 0  # Might be 0 if no workflows exist

        # Verify backup file exists
        backup_path = Path(backup_info.location)
        assert backup_path.exists()
        assert backup_path.name.endswith(".tar.gz")

        # The checksum is recorded next to the archive, so a restore can
        # check the archive against the checksum it was made with.
        sidecar = backup_manager._checksum_sidecar(backup_path)
        assert sidecar.exists()
        assert sidecar.read_text().strip() == backup_info.checksum


@pytest.mark.asyncio
async def test_a_restore_checks_the_archive_against_its_checksum():
    """A tampered archive is refused before anything is restored."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)
        backup_info = await backup_manager.create_backup("full")
        backup_path = Path(backup_info.location)

        # Tamper with the archive after it was made.
        backup_path.write_bytes(backup_path.read_bytes() + b"tampered")

        with pytest.raises(ValueError, match="checksum mismatch"):
            await backup_manager.restore_backup(backup_info.backup_id)


@pytest.mark.asyncio
async def test_a_restore_refuses_a_backup_id_that_is_a_path():
    """The id becomes a file name, so it must not carry a path."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        with pytest.raises(ValueError, match="Invalid backup id"):
            await backup_manager.restore_backup("../../etc/passwd")


@pytest.mark.asyncio
async def test_a_failed_archive_delete_keeps_its_checksum_sidecar(
    monkeypatch: pytest.MonkeyPatch,
):
    """A surviving archive keeps the checksum that verifies it.

    Deleting the sidecar when the archive could not be deleted would
    leave an archive with no recorded checksum -- and _verify_checksum
    restores an archive that has no sidecar WITHOUT verifying it. The
    tamper check would be skipped for the very archive the cleanup
    failed to delete.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.config.backup_schedule = {"daily": 0, "weekly": 0, "monthly": 0}
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        archive = Path(temp_dir) / "backup_20010101_000000_000000.tar.gz"
        archive.write_bytes(b"stale")
        sidecar = Path(str(archive) + ".sha256")
        sidecar.write_text("deadbeef\n")

        real_unlink = Path.unlink

        def _unlink(self, *args, **kwargs):
            if self == archive:
                raise PermissionError("read-only file system")
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _unlink)

        await backup_manager._cleanup_old_backups()

        assert archive.exists()
        assert sidecar.exists()


@pytest.mark.asyncio
async def test_backup_info_refuses_a_backup_id_that_is_a_path():
    """The same rule as the restore: the id becomes a file name.

    ``get_backup_info`` builds the same path the restore builds, so an
    id carrying a path separator reaches outside the backup directory
    there too.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        with pytest.raises(ValueError, match="Invalid backup id"):
            await backup_manager.get_backup_info("../../etc/passwd")


@pytest.mark.asyncio
async def test_the_cleanup_takes_the_checksum_sidecar_with_the_archive():
    """A deleted backup leaves no checksum sidecar behind.

    The sidecar records the archive's checksum. Leaving it behind when
    the archive goes means a later backup with the same id finds a
    stale checksum for an archive that is not there.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.config.backup_schedule = {"daily": 0, "weekly": 0, "monthly": 0}
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        # An old archive (2001) and its sidecar. The retention policy
        # is zeroed, so this one is deleted rather than kept.
        archive = Path(temp_dir) / "backup_20010101_000000_000000.tar.gz"
        archive.write_bytes(b"stale")
        sidecar = Path(str(archive) + ".sha256")
        sidecar.write_text("deadbeef\n")

        await backup_manager._cleanup_old_backups()

        assert not archive.exists()
        assert not sidecar.exists()


@pytest.mark.asyncio
async def test_backup_manager_list_backups():
    """Test listing backups."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        # Initially no backups
        backups = await backup_manager.list_backups()
        assert len(backups) == 0

        # Create a backup
        await backup_manager.create_backup("full")

        # Now there should be one backup
        backups = await backup_manager.list_backups()
        assert len(backups) == 1
        assert backups[0].backup_id.startswith("backup_")


@pytest.mark.asyncio
async def test_backup_manager_get_backup_info():
    """Test getting backup info."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        # Create a backup
        backup_info = await backup_manager.create_backup("full")
        backup_id = backup_info.backup_id

        # Get backup info
        retrieved_info = await backup_manager.get_backup_info(backup_id)

        # Verify the info matches
        assert retrieved_info is not None
        assert retrieved_info.backup_id == backup_id
        assert retrieved_info.size_bytes > 0
        assert retrieved_info.status == "available"


@pytest.mark.asyncio
async def test_disaster_recovery_manager_initialization():
    """Test that DisasterRecoveryManager initializes correctly."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()

    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

    dr_manager = DisasterRecoveryManager(app)

    # Verify components were initialized
    assert dr_manager.backup_manager is not None
    assert dr_manager.app == app


@pytest.mark.asyncio
async def test_disaster_recovery_check():
    """Test disaster recovery check functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        dr_manager = DisasterRecoveryManager(app)

        # Run disaster recovery check
        results = await dr_manager.run_disaster_recovery_check()

        # Verify structure of results
        assert "timestamp" in results
        assert "checks" in results
        assert "status" in results

        # Verify specific checks exist
        checks = results["checks"]
        assert "backups_available" in checks
        assert "backup_integrity" in checks
        assert "recent_backup" in checks


@pytest.mark.asyncio
async def test_disaster_recovery_procedures():
    """Test getting disaster recovery procedures."""
    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()

    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

    dr_manager = DisasterRecoveryManager(app)

    # Get procedures
    procedures = await dr_manager.get_recovery_procedures()

    # Verify structure of procedures
    assert "procedures" in procedures
    assert "automation" in procedures

    proc_details = procedures["procedures"]
    assert "emergency_contact" in proc_details
    assert "recovery_steps" in proc_details
    assert "recovery_time_objective" in proc_details
    assert "recovery_point_objective" in proc_details
    assert "contact_info" in proc_details

    automation = procedures["automation"]
    assert "automatic_backup" in automation
    assert "backup_frequency" in automation
    assert "retention_policy" in automation
    assert "monitoring" in automation
    assert "alerts" in automation


@pytest.mark.asyncio
async def test_backup_and_recovery_cli_initialization():
    """Test that BackupAndRecoveryCLI initializes correctly."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI

    app = Mock(spec=MahavishnuApp)
    app.config = Mock()
    app.config.backup_directory = "./test_backups"
    app.workflow_state_manager = Mock()

    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

    cli = BackupAndRecoveryCLI(app)

    # Verify components were initialized
    assert cli.app == app
    assert cli.backup_manager is not None
    assert cli.recovery_manager is not None


@pytest.mark.asyncio
async def test_backup_cli_create_backup():
    """Test BackupAndRecoveryCLI create_backup functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI

    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        cli = BackupAndRecoveryCLI(app)

        # Create a backup via CLI
        result = await cli.create_backup("full")

        # Verify result structure
        assert result["status"] == "success"
        assert "backup_id" in result
        assert "location" in result
        assert "size_mb" in result
        assert "timestamp" in result

        # Verify backup was created
        assert result["backup_id"].startswith("backup_")


@pytest.mark.asyncio
async def test_backup_cli_list_backups():
    """Test BackupAndRecoveryCLI list_backups functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI

    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        cli = BackupAndRecoveryCLI(app)

        # Initially no backups
        result = await cli.list_backups()
        assert result["status"] == "success"
        assert result["total_count"] == 0
        assert len(result["backups"]) == 0

        # Create a backup
        await cli.create_backup("full")

        # Now there should be one backup
        result = await cli.list_backups()
        assert result["status"] == "success"
        assert result["total_count"] == 1
        assert len(result["backups"]) == 1


@pytest.mark.asyncio
async def test_backup_cli_run_dr_check():
    """Test BackupAndRecoveryCLI run_dr_check functionality."""
    from mahavishnu.core.backup_recovery import BackupAndRecoveryCLI

    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()

        # Mock the workflow state manager
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        cli = BackupAndRecoveryCLI(app)

        # Run DR check via CLI
        result = await cli.run_disaster_recovery_check()

        # Verify result structure
        assert result["status"] in ["success", "needs_attention"]
        assert "results" in result


@pytest.mark.asyncio
async def test_backup_info_reports_the_checksum_recorded_at_creation():
    """The reported checksum is the one the backup was MADE with.

    ``list_backups`` reports the recorded checksum and a restore
    verifies the archive against it. Reporting a fresh hash of the
    file instead would report the checksum of a TAMPERED archive as
    the backup's own.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)

        backup_id = "backup_20210101_000000_000000"
        archive = Path(temp_dir) / f"{backup_id}.tar.gz"

        def _make_archive(payload: bytes) -> bytes:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                info = tarfile.TarInfo("metadata.json")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            return buffer.getvalue()

        archive.write_bytes(_make_archive(b'{"kind": "original"}'))
        recorded = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(str(archive) + ".sha256").write_text(f"{recorded}\n")
        # A different, still-valid archive in the archive's place: the
        # file on disk no longer hashes to what was recorded.
        archive.write_bytes(_make_archive(b'{"kind": "tampered"}'))

        info = await backup_manager.get_backup_info(backup_id)

        assert info is not None
        assert info.checksum == recorded


def test_the_backup_info_command_refuses_an_invalid_id_without_a_traceback():
    """An id that is not a backup id is an error the operator reads.

    ``get_backup_info`` refuses an id carrying a path separator, the
    same rule ``restore_backup`` follows. The CLI catches it and exits
    1 with a message, rather than letting the traceback reach the
    terminal.
    """
    from typer.testing import CliRunner

    from mahavishnu.backup_cli import add_backup_commands

    backup_app = typer.Typer()
    add_backup_commands(backup_app)

    result = CliRunner().invoke(backup_app, ["backup", "info", "../../etc/passwd"])

    assert result.exit_code == 1, result.output
    assert "Invalid backup id" in result.output
    assert "Traceback" not in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "member_name",
    [
        "../escaped.txt",
        # The shape a substring check misses: ".." is a whole path
        # COMPONENT here, not the two characters "../".
        "escape/..",
    ],
)
async def test_a_restore_refuses_an_archive_with_a_traversal_member(member_name):
    """An archive that would write outside the restore directory is refused.

    The check is on the member's path PARTS, so ``..`` is caught whether
    it is written as ``../escaped.txt`` or as a component of a longer
    path. The readable ValueError comes first; ``filter="data"`` is
    behind it, for the shapes this check cannot see.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        app = Mock(spec=MahavishnuApp)
        app.config = Mock()
        app.config.backup_directory = temp_dir
        app.workflow_state_manager = Mock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        backup_manager = BackupManager(app)
        backup_info = await backup_manager.create_backup("full")
        backup_path = Path(backup_info.location)

        # Replace the archive with one whose member would escape.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            payload = b"escaped"
            member = tarfile.TarInfo(member_name)
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
        backup_path.write_bytes(buffer.getvalue())

        # The sidecar has to match, or the restore is refused for the
        # WRONG reason -- the checksum, not the traversal.
        sidecar = backup_path.with_suffix(backup_path.suffix + ".sha256")
        sidecar.write_text(f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n")

        with pytest.raises(ValueError, match="Path traversal"):
            await backup_manager.restore_backup(backup_info.backup_id)
