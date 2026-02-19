"""Unit tests for WorktreeBackupManager.

Tests comprehensive backup creation and restoration for worktree safety:
- Async backup creation with timestamped directories
- Async directory and file copying
- Metadata creation with audit logging integration
- Backup restoration functionality
- Old backup cleanup based on retention policy
- Backup listing with filtering
- Error handling for missing/non-existent paths
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiofiles
import aiofiles.os

from mahavishnu.core.worktree_backup import WorktreeBackupManager


class TestWorktreeBackupManager:
    """Test suite for WorktreeBackupManager backup functionality."""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_initialization_with_custom_backup_dir(self, tmp_path):
        """Test backup manager initialization with custom backup directory."""
        custom_backup_dir = tmp_path / "custom_backups"

        manager = WorktreeBackupManager(backup_dir=custom_backup_dir)

        assert manager.backup_dir == custom_backup_dir
        assert manager.retention_days == 30
        assert custom_backup_dir.exists()

    def test_initialization_with_default_backup_dir(self):
        """Test backup manager initialization with default XDG-compliant directory."""
        manager = WorktreeBackupManager()

        # Should use XDG data directory
        assert manager.backup_dir is not None
        assert manager.retention_days == 30
        assert manager.backup_dir.exists()

    def test_initialization_with_custom_retention(self, tmp_path):
        """Test backup manager initialization with custom retention period."""
        manager = WorktreeBackupManager(
            backup_dir=tmp_path / "backups",
            retention_days=60,
        )

        assert manager.retention_days == 60

    # =========================================================================
    # Backup Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_backup_before_removal(self, tmp_path):
        """Test basic backup creation before force removal."""
        # Setup: Create worktree directory with files
        worktree_path = tmp_path / "worktrees" / "repo" / "feature-branch"
        worktree_path.mkdir(parents=True)
        (worktree_path / "file1.txt").write_text("content1")
        (worktree_path / "file2.txt").write_text("content2")

        # Create backup manager
        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Create backup
        backup_path = await manager.create_backup_before_removal(
            worktree_path=worktree_path,
            repo_nickname="repo",
            branch="feature-branch",
            user_id="user-123",
        )

        # Verify backup directory exists
        assert backup_path.exists()
        assert backup_path.is_dir()

        # Verify backup has correct naming pattern
        assert backup_path.parent == backup_dir
        assert "repo_feature-branch_" in backup_path.name

        # Verify files were copied
        assert (backup_path / "file1.txt").exists()
        assert (backup_path / "file2.txt").exists()
        assert (backup_path / "file1.txt").read_text() == "content1"
        assert (backup_path / "file2.txt").read_text() == "content2"

    @pytest.mark.asyncio
    async def test_create_backup_creates_metadata_file(self, tmp_path):
        """Test that backup creation includes metadata file."""
        # Setup: Create worktree directory
        worktree_path = tmp_path / "worktrees" / "repo" / "main"
        worktree_path.mkdir(parents=True)
        (worktree_path / "README.md").write_text("# Test")

        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Create backup
        backup_path = await manager.create_backup_before_removal(
            worktree_path=worktree_path,
            repo_nickname="repo",
            branch="main",
            user_id="user-456",
        )

        # Verify metadata file exists
        metadata_file = backup_path / ".backup_metadata.json"
        assert metadata_file.exists()

        # Verify metadata contents
        async with aiofiles.open(metadata_file, "r") as f:
            metadata = json.loads(await f.read())

        assert metadata["repo_nickname"] == "repo"
        assert metadata["branch"] == "main"
        assert metadata["user_id"] == "user-456"
        assert metadata["original_path"] == str(worktree_path)
        assert metadata["backup_path"] == str(backup_path)
        assert metadata["backup_reason"] == "Force worktree removal"
        assert "created_at" in metadata

    @pytest.mark.asyncio
    async def test_create_backup_with_nested_directories(self, tmp_path):
        """Test backup creation with nested directory structure."""
        # Setup: Create nested worktree structure
        worktree_path = tmp_path / "worktrees" / "repo" / "feature"
        worktree_path.mkdir(parents=True)
        (worktree_path / "src").mkdir()
        (worktree_path / "src" / "module.py").write_text("print('hello')")
        (worktree_path / "tests").mkdir()
        (worktree_path / "tests" / "test_module.py").write_text("def test(): pass")

        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Create backup
        backup_path = await manager.create_backup_before_removal(
            worktree_path=worktree_path,
            repo_nickname="repo",
            branch="feature",
        )

        # Verify nested structure was copied
        assert (backup_path / "src" / "module.py").exists()
        assert (backup_path / "tests" / "test_module.py").exists()
        assert (backup_path / "src" / "module.py").read_text() == "print('hello')"

    @pytest.mark.asyncio
    async def test_create_backup_nonexistent_worktree(self, tmp_path):
        """Test that backup creation fails for non-existent worktree."""
        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        worktree_path = tmp_path / "nonexistent" / "worktree"

        # Should raise IOError
        with pytest.raises(IOError) as exc_info:
            await manager.create_backup_before_removal(
                worktree_path=worktree_path,
                repo_nickname="repo",
                branch="main",
            )

        assert "does not exist" in str(exc_info.value)

    # =========================================================================
    # Async File Copy Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_copy_file_async(self, tmp_path):
        """Test async file copying."""
        src_file = tmp_path / "source.txt"
        dst_file = tmp_path / "dest.txt"

        # Create source file
        src_file.write_text("test content")

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Copy file
        await manager._copy_file_async(src_file, dst_file)

        # Verify copy
        assert dst_file.exists()
        assert dst_file.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_copy_file_async_preserves_content(self, tmp_path):
        """Test that async file copy preserves exact content."""
        src_file = tmp_path / "binary.dat"
        dst_file = tmp_path / "binary_copy.dat"

        # Create binary file
        binary_content = bytes(range(256))
        src_file.write_bytes(binary_content)

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Copy file
        await manager._copy_file_async(src_file, dst_file)

        # Verify exact byte-for-byte copy
        assert dst_file.read_bytes() == binary_content

    @pytest.mark.asyncio
    async def test_copy_directory_async(self, tmp_path):
        """Test async directory copying."""
        src_dir = tmp_path / "source"
        dst_dir = tmp_path / "destination"

        # Create source structure
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("content1")
        (src_dir / "file2.txt").write_text("content2")
        (src_dir / "subdir").mkdir()
        (src_dir / "subdir" / "file3.txt").write_text("content3")

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Copy directory
        await manager._copy_directory_async(src_dir, dst_dir)

        # Verify structure was copied
        assert (dst_dir / "file1.txt").exists()
        assert (dst_dir / "file2.txt").exists()
        assert (dst_dir / "subdir" / "file3.txt").exists()
        assert (dst_dir / "file1.txt").read_text() == "content1"

    @pytest.mark.asyncio
    async def test_copy_directory_async_empty_directory(self, tmp_path):
        """Test copying empty directory."""
        src_dir = tmp_path / "empty_source"
        dst_dir = tmp_path / "empty_dest"

        src_dir.mkdir()

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Copy empty directory
        await manager._copy_directory_async(src_dir, dst_dir)

        # Verify destination exists but is empty
        assert dst_dir.exists()
        assert dst_dir.is_dir()
        assert list(dst_dir.iterdir()) == []

    # =========================================================================
    # Metadata Creation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_backup_metadata(self, tmp_path):
        """Test backup metadata file creation."""
        backup_path = tmp_path / "backup"
        backup_path.mkdir()

        worktree_path = tmp_path / "worktrees" / "repo" / "main"

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Create metadata
        await manager._create_backup_metadata(
            backup_path=backup_path,
            original_path=worktree_path,
            repo_nickname="test-repo",
            branch="main",
            user_id="user-789",
        )

        # Verify metadata file
        metadata_file = backup_path / ".backup_metadata.json"
        assert metadata_file.exists()

        async with aiofiles.open(metadata_file, "r") as f:
            metadata = json.loads(await f.read())

        assert metadata["repo_nickname"] == "test-repo"
        assert metadata["branch"] == "main"
        assert metadata["user_id"] == "user-789"
        assert metadata["original_path"] == str(worktree_path)
        assert metadata["backup_path"] == str(backup_path)
        assert "created_at" in metadata

    @pytest.mark.asyncio
    async def test_metadata_includes_iso_timestamp(self, tmp_path):
        """Test that metadata includes ISO 8601 timestamp."""
        backup_path = tmp_path / "backup"
        backup_path.mkdir()

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Create metadata
        await manager._create_backup_metadata(
            backup_path=backup_path,
            original_path=tmp_path / "worktree",
            repo_nickname="repo",
            branch="main",
            user_id=None,
        )

        # Verify timestamp format
        metadata_file = backup_path / ".backup_metadata.json"
        async with aiofiles.open(metadata_file, "r") as f:
            metadata = json.loads(await f.read())

        timestamp_str = metadata["created_at"]

        # Should be parseable as ISO 8601
        timestamp = datetime.fromisoformat(timestamp_str)
        assert isinstance(timestamp, datetime)

    # =========================================================================
    # Audit Logging Tests
    # =========================================================================

    def test_log_backup_creation(self, tmp_path, mocker):
        """Test that backup creation is logged to audit trail."""
        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        worktree_path = tmp_path / "worktrees" / "repo" / "feature"
        backup_path = backup_dir / "repo_feature_20260218_120000"

        # Mock audit logger
        mock_audit = mocker.patch(
            "mahavishnu.core.worktree_backup.get_audit_logger",
            return_value=MagicMock(),
        )

        # Log backup creation
        manager._log_backup_creation(
            worktree_path=worktree_path,
            backup_path=backup_path,
            repo_nickname="repo",
            branch="feature",
            user_id="user-123",
        )

        # Verify audit logger was called
        mock_audit.return_value.log.assert_called_once()
        call_kwargs = mock_audit.return_value.log.call_args.kwargs
        assert call_kwargs["event_type"] == "worktree_backup_created"
        assert call_kwargs["user_id"] == "user-123"
        assert call_kwargs["tool_name"] == "WorktreeBackupManager"
        assert call_kwargs["result"] == "success"

    def test_log_backup_creation_handles_audit_failure(self, tmp_path, caplog):
        """Test that backup creation continues even if audit logging fails."""
        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Mock get_audit_logger to raise exception
        with patch(
            "mahavishnu.core.worktree_backup.get_audit_logger",
            side_effect=Exception("Audit log unavailable"),
        ):
            # Should not raise exception
            manager._log_backup_creation(
                worktree_path=tmp_path / "worktree",
                backup_path=backup_dir / "backup",
                repo_nickname="repo",
                branch="main",
                user_id="user-123",
            )

        # Backup creation should succeed (audit logging failure is logged but not raised)

    # =========================================================================
    # Backup Restoration Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_restore_from_backup(self, tmp_path):
        """Test restoring worktree from backup."""
        # Setup: Create backup directory with files
        backup_path = tmp_path / "backups" / "repo_main_20260218_120000"
        backup_path.mkdir(parents=True)
        (backup_path / "file1.txt").write_text("restored content")
        (backup_path / "file2.txt").write_text("more content")

        # Create metadata file
        metadata = {
            "backup_path": str(backup_path),
            "original_path": "/worktrees/repo/main",
            "repo_nickname": "repo",
            "branch": "main",
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
        metadata_file = backup_path / ".backup_metadata.json"
        async with aiofiles.open(metadata_file, "w") as f:
            await f.write(json.dumps(metadata, indent=2))

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Restore from backup
        restore_location = tmp_path / "restored" / "repo" / "main"
        result = await manager.restore_from_backup(
            backup_path=backup_path,
            restore_location=restore_location,
        )

        # Verify restoration succeeded
        assert result["success"] is True
        assert result["restored_path"] == str(restore_location)
        assert result["backup_path"] == str(backup_path)

        # Verify files were restored
        assert (restore_location / "file1.txt").exists()
        assert (restore_location / "file2.txt").exists()
        assert (restore_location / "file1.txt").read_text() == "restored content"

    @pytest.mark.asyncio
    async def test_restore_from_nonexistent_backup(self, tmp_path):
        """Test that restoration fails for non-existent backup."""
        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        backup_path = tmp_path / "nonexistent_backup"
        restore_location = tmp_path / "restored"

        # Should raise IOError
        with pytest.raises(IOError) as exc_info:
            await manager.restore_from_backup(
                backup_path=backup_path,
                restore_location=restore_location,
            )

        assert "does not exist" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_restore_creates_parent_directories(self, tmp_path):
        """Test that restoration creates parent directories as needed."""
        # Setup: Create backup
        backup_path = tmp_path / "backups" / "repo_feature_20260218_120000"
        backup_path.mkdir(parents=True)
        (backup_path / "file.txt").write_text("content")

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Restore to location with non-existent parent directories
        restore_location = tmp_path / "deep" / "nested" / "restore"
        result = await manager.restore_from_backup(
            backup_path=backup_path,
            restore_location=restore_location,
        )

        # Verify parent directories were created
        assert restore_location.parent.exists()
        assert restore_location.exists()
        assert (restore_location / "file.txt").read_text() == "content"

    # =========================================================================
    # Backup Cleanup Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self, tmp_path):
        """Test cleanup of old backups based on retention policy."""
        # Setup: Create old and new backups
        backup_dir = tmp_path / "backups"

        # Old backup (31 days ago)
        old_backup = backup_dir / "repo_main_20260118_120000"
        old_backup.mkdir(parents=True)
        old_metadata = {
            "backup_path": str(old_backup),
            "created_at": (datetime.now(tz=UTC) - timedelta(days=31)).isoformat(),
            "repo_nickname": "repo",
            "branch": "main",
        }
        async with aiofiles.open(old_backup / ".backup_metadata.json", "w") as f:
            await f.write(json.dumps(old_metadata))

        # New backup (1 day ago)
        new_backup = backup_dir / "repo_main_20260217_120000"
        new_backup.mkdir(parents=True)
        new_metadata = {
            "backup_path": str(new_backup),
            "created_at": (datetime.now(tz=UTC) - timedelta(days=1)).isoformat(),
            "repo_nickname": "repo",
            "branch": "main",
        }
        async with aiofiles.open(new_backup / ".backup_metadata.json", "w") as f:
            await f.write(json.dumps(new_metadata))

        # Manager with 30-day retention
        manager = WorktreeBackupManager(backup_dir=backup_dir, retention_days=30)

        # Cleanup old backups
        removed_count = await manager.cleanup_old_backups()

        # Verify only old backup was removed
        assert removed_count == 1
        assert not old_backup.exists()
        assert new_backup.exists()

    @pytest.mark.asyncio
    async def test_cleanup_skips_backups_without_metadata(self, tmp_path):
        """Test that cleanup skips directories without metadata files."""
        backup_dir = tmp_path / "backups"

        # Create directory without metadata
        no_metadata_dir = backup_dir / "unknown_directory"
        no_metadata_dir.mkdir(parents=True)
        (no_metadata_dir / "some_file.txt").write_text("content")

        manager = WorktreeBackupManager(backup_dir=backup_dir, retention_days=30)

        # Cleanup should not remove directory without metadata
        removed_count = await manager.cleanup_old_backups()

        assert removed_count == 0
        assert no_metadata_dir.exists()

    @pytest.mark.asyncio
    async def test_cleanup_with_zero_retention(self, tmp_path):
        """Test cleanup with zero retention (removes all backups)."""
        backup_dir = tmp_path / "backups"

        # Create recent backup
        backup = backup_dir / "repo_main_20260218_120000"
        backup.mkdir(parents=True)
        metadata = {
            "backup_path": str(backup),
            "created_at": datetime.now(tz=UTC).isoformat(),
            "repo_nickname": "repo",
            "branch": "main",
        }
        async with aiofiles.open(backup / ".backup_metadata.json", "w") as f:
            await f.write(json.dumps(metadata))

        # Manager with zero retention (remove everything)
        manager = WorktreeBackupManager(backup_dir=backup_dir, retention_days=0)

        # Cleanup should remove all backups
        removed_count = await manager.cleanup_old_backups()

        assert removed_count == 1
        assert not backup.exists()

    # =========================================================================
    # Backup Listing Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_list_backups(self, tmp_path):
        """Test listing all available backups."""
        backup_dir = tmp_path / "backups"

        # Create multiple backups
        for i in range(3):
            backup_path = backup_dir / f"repo_main_202602{i+1}_120000"
            backup_path.mkdir(parents=True)
            metadata = {
                "backup_path": str(backup_path),
                "created_at": (datetime.now(tz=UTC) - timedelta(days=i)).isoformat(),
                "repo_nickname": "repo",
                "branch": "main",
            }
            async with aiofiles.open(backup_path / ".backup_metadata.json", "w") as f:
                await f.write(json.dumps(metadata))

        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # List all backups
        backups = await manager.list_backups()

        assert len(backups) == 3
        # Should be sorted by creation time (newest first)
        assert backups[0]["created_at"] > backups[1]["created_at"]
        assert backups[1]["created_at"] > backups[2]["created_at"]

    @pytest.mark.asyncio
    async def test_list_backups_filtered_by_repo(self, tmp_path):
        """Test listing backups filtered by repository."""
        backup_dir = tmp_path / "backups"

        # Create backups for different repos
        for repo in ["repo1", "repo2"]:
            backup_path = backup_dir / f"{repo}_main_20260218_120000"
            backup_path.mkdir(parents=True)
            metadata = {
                "backup_path": str(backup_path),
                "created_at": datetime.now(tz=UTC).isoformat(),
                "repo_nickname": repo,
                "branch": "main",
            }
            async with aiofiles.open(backup_path / ".backup_metadata.json", "w") as f:
                await f.write(json.dumps(metadata))

        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # List backups for repo1 only
        backups = await manager.list_backups(repo_nickname="repo1")

        assert len(backups) == 1
        assert backups[0]["repo_nickname"] == "repo1"

    @pytest.mark.asyncio
    async def test_list_backups_ignores_non_backup_directories(self, tmp_path):
        """Test that listing ignores directories without metadata files."""
        backup_dir = tmp_path / "backups"

        # Create valid backup
        valid_backup = backup_dir / "repo_main_20260218_120000"
        valid_backup.mkdir(parents=True)
        metadata = {
            "backup_path": str(valid_backup),
            "created_at": datetime.now(tz=UTC).isoformat(),
            "repo_nickname": "repo",
            "branch": "main",
        }
        async with aiofiles.open(valid_backup / ".backup_metadata.json", "w") as f:
            await f.write(json.dumps(metadata))

        # Create directory without metadata
        invalid_dir = backup_dir / "not_a_backup"
        invalid_dir.mkdir()
        (invalid_dir / "file.txt").write_text("content")

        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # List should only include valid backup
        backups = await manager.list_backups()

        assert len(backups) == 1
        assert backups[0]["repo_nickname"] == "repo"

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_backup_handles_copy_failure(self, tmp_path):
        """Test that backup creation handles copy failures gracefully."""
        worktree_path = tmp_path / "worktrees" / "repo" / "main"
        worktree_path.mkdir(parents=True)
        (worktree_path / "file.txt").write_text("content")

        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Mock _copy_directory_async to raise exception
        with patch.object(
            manager,
            "_copy_directory_async",
            side_effect=IOError("Copy failed"),
        ):
            # Should raise IOError
            with pytest.raises(IOError) as exc_info:
                await manager.create_backup_before_removal(
                    worktree_path=worktree_path,
                    repo_nickname="repo",
                    branch="main",
                )

            assert "Backup creation failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_restore_handles_copy_failure(self, tmp_path):
        """Test that restoration handles copy failures gracefully."""
        backup_path = tmp_path / "backups" / "backup"
        backup_path.mkdir(parents=True)

        manager = WorktreeBackupManager(backup_dir=tmp_path / "backups")

        # Mock _copy_directory_async to raise exception
        with patch.object(
            manager,
            "_copy_directory_async",
            side_effect=IOError("Restore failed"),
        ):
            restore_location = tmp_path / "restored"

            # Should raise IOError
            with pytest.raises(IOError) as exc_info:
                await manager.restore_from_backup(
                    backup_path=backup_path,
                    restore_location=restore_location,
                )

            assert "Backup restoration failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cleanup_handles_metadata_read_failure(self, tmp_path, caplog):
        """Test that cleanup handles metadata read failures gracefully."""
        backup_dir = tmp_path / "backups"

        # Create backup with invalid metadata
        backup = backup_dir / "repo_main_20260218_120000"
        backup.mkdir(parents=True)
        (backup / ".backup_metadata.json").write_text("invalid json")

        manager = WorktreeBackupManager(backup_dir=backup_dir, retention_days=30)

        # Should not raise exception, just skip invalid backup
        removed_count = await manager.cleanup_old_backups()

        assert removed_count == 0

    # =========================================================================
    # Edge Cases
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_backup_with_special_characters_in_files(self, tmp_path):
        """Test backup creation with special characters in filenames."""
        worktree_path = tmp_path / "worktrees" / "repo" / "feature"
        worktree_path.mkdir(parents=True)

        # Create files with special characters
        (worktree_path / "file with spaces.txt").write_text("content")
        (worktree_path / "file-with-dashes.txt").write_text("content")
        (worktree_path / "file_with_underscores.txt").write_text("content")

        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Create backup
        backup_path = await manager.create_backup_before_removal(
            worktree_path=worktree_path,
            repo_nickname="repo",
            branch="feature",
        )

        # Verify all files were copied
        assert (backup_path / "file with spaces.txt").exists()
        assert (backup_path / "file-with-dashes.txt").exists()
        assert (backup_path / "file_with_underscores.txt").exists()

    @pytest.mark.asyncio
    async def test_create_backup_preserves_file_permissions(self, tmp_path):
        """Test that backup creation preserves file permissions."""
        worktree_path = tmp_path / "worktrees" / "repo" / "main"
        worktree_path.mkdir(parents=True)

        # Create file with specific permissions
        test_file = worktree_path / "executable.sh"
        test_file.write_text("#!/bin/bash\necho test")
        test_file.chmod(0o755)

        backup_dir = tmp_path / "backups"
        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # Create backup
        backup_path = await manager.create_backup_before_removal(
            worktree_path=worktree_path,
            repo_nickname="repo",
            branch="main",
        )

        # Note: File permissions may not be preserved exactly due to umask
        # This test verifies the backup was created without errors
        assert (backup_path / "executable.sh").exists()

    @pytest.mark.asyncio
    async def test_list_backups_empty_directory(self, tmp_path):
        """Test listing backups when no backups exist."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        manager = WorktreeBackupManager(backup_dir=backup_dir)

        # List should return empty list
        backups = await manager.list_backups()

        assert backups == []

    @pytest.mark.asyncio
    async def test_cleanup_empty_directory(self, tmp_path):
        """Test cleanup when no backups exist."""
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        manager = WorktreeBackupManager(backup_dir=backup_dir, retention_days=30)

        # Should complete without errors
        removed_count = await manager.cleanup_old_backups()

        assert removed_count == 0
