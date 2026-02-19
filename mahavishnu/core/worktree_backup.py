"""Worktree backup manager for automatic backup creation (SECURITY-001 fix)."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)


class WorktreeBackupManager:
    """Manager for creating and restoring worktree backups.

    This manager creates automatic backups before force worktree removal,
    ensuring data can be recovered if the force removal was a mistake.

    Backup Strategy:
    - Timestamped backup directories (never overwrite)
    - Stored in XDG-compliant backup location
    - Automatic cleanup of old backups (configurable retention)
    - Async file operations for performance

    Example:
        >>> backup_mgr = WorktreeBackupManager()
        >>> backup_path = await backup_mgr.create_backup_before_removal(
        ...     Path("/worktrees/repo/feature-branch"),
        ...     repo_nickname="repo",
        ...     branch="feature-branch",
        ...     user_id="user-123"
        ... )
        >>> # Force removal proceeds...
    """

    def __init__(
        self,
        backup_dir: Path | None = None,
        retention_days: int = 30,
    ) -> None:
        """Initialize backup manager.

        Args:
            backup_dir: Directory for backups (default: XDG data directory)
            retention_days: Days to keep backups before cleanup
        """
        if backup_dir is None:
            from ..core.paths import get_data_path

            backup_dir = get_data_path("worktree_backups")

        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days

        logger.debug(
            f"WorktreeBackupManager initialized "
            f"(backup_dir={self.backup_dir}, retention={retention_days} days)"
        )

    async def create_backup_before_removal(
        self,
        worktree_path: Path,
        repo_nickname: str,
        branch: str,
        user_id: str | None = None,
    ) -> Path:
        """Create backup before force removal.

        Creates a timestamped backup of the worktree directory.
        This backup can be restored if the force removal was a mistake.

        Args:
            worktree_path: Path to worktree directory
            repo_nickname: Repository nickname (for naming)
            branch: Branch name (for naming)
            user_id: User ID for audit logging

        Returns:
            Path to backup directory

        Raises:
            IOError: If backup creation fails
        """
        if not worktree_path.exists():
            raise IOError(f"Worktree does not exist: {worktree_path}")

        # Generate timestamped backup path
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{repo_nickname}_{branch}_{timestamp}"
        backup_path = self.backup_dir / backup_name

        logger.info(
            f"Creating backup before force removal: {worktree_path} -> {backup_path}"
        )

        try:
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)

            # Copy all files from worktree to backup
            # Use async file operations for better performance
            await self._copy_directory_async(worktree_path, backup_path)

            # Create backup metadata
            await self._create_backup_metadata(
                backup_path,
                worktree_path,
                repo_nickname,
                branch,
                user_id,
            )

            # Log to audit trail
            self._log_backup_creation(
                worktree_path,
                backup_path,
                repo_nickname,
                branch,
                user_id,
            )

            logger.info(f"Backup created successfully: {backup_path}")
            return backup_path

        except Exception as e:
            logger.error(f"Failed to create backup: {e}", exc_info=True)
            raise IOError(f"Backup creation failed: {e}") from e

    async def _copy_directory_async(
        self,
        src: Path,
        dst: Path,
    ) -> None:
        """Copy directory contents asynchronously.

        Args:
            src: Source directory
            dst: Destination directory
        """
        # Recursively copy all files and directories
        for item in src.iterdir():
            src_item = item
            dst_item = dst / item.name

            if src_item.is_dir():
                # Recursively copy subdirectory
                dst_item.mkdir(exist_ok=True)
                await self._copy_directory_async(src_item, dst_item)
            else:
                # Copy file
                await self._copy_file_async(src_item, dst_item)

    async def _copy_file_async(
        self,
        src: Path,
        dst: Path,
    ) -> None:
        """Copy file asynchronously.

        Args:
            src: Source file
            dst: Destination file
        """
        async with aiofiles.open(src, "rb") as f_src:
            content = await f_src.read()
            async with aiofiles.open(dst, "wb") as f_dst:
                await f_dst.write(content)

    async def _create_backup_metadata(
        self,
        backup_path: Path,
        original_path: Path,
        repo_nickname: str,
        branch: str,
        user_id: str | None,
    ) -> None:
        """Create backup metadata file.

        Args:
            backup_path: Path to backup directory
            original_path: Original worktree path
            repo_nickname: Repository nickname
            branch: Branch name
            user_id: User ID
        """
        metadata = {
            "backup_path": str(backup_path),
            "original_path": str(original_path),
            "repo_nickname": repo_nickname,
            "branch": branch,
            "user_id": user_id,
            "created_at": datetime.now(tz=UTC).isoformat(),
            "backup_reason": "Force worktree removal",
        }

        metadata_file = backup_path / ".backup_metadata.json"

        async with aiofiles.open(metadata_file, "w") as f:
            import json

            await f.write(json.dumps(metadata, indent=2))

        logger.debug(f"Backup metadata created: {metadata_file}")

    def _log_backup_creation(
        self,
        worktree_path: Path,
        backup_path: Path,
        repo_nickname: str,
        branch: str,
        user_id: str | None,
    ) -> None:
        """Log backup creation to audit trail.

        Args:
            worktree_path: Original worktree path
            backup_path: Path to backup directory
            repo_nickname: Repository nickname
            branch: Branch name
            user_id: User ID
        """
        logger.info(
            f"BACKUP CREATED: user={user_id}, repo={repo_nickname}, "
            f"branch={branch}, worktree={worktree_path}, backup={backup_path}"
        )

        # Log to audit logger (for SOC 2, ISO 27001, PCI DSS compliance)
        try:
            from ..mcp.auth import get_audit_logger

            get_audit_logger().log(
                event_type="worktree_backup_created",
                user_id=user_id,
                tool_name="WorktreeBackupManager",
                params={
                    "repo_nickname": repo_nickname,
                    "branch": branch,
                    "worktree_path": str(worktree_path),
                    "backup_path": str(backup_path),
                },
                result="success",
            )
        except Exception as e:
            logger.error(f"Failed to log backup to audit trail: {e}")

    async def restore_from_backup(
        self,
        backup_path: Path,
        restore_location: Path,
    ) -> dict[str, Any]:
        """Restore worktree from backup.

        Args:
            backup_path: Path to backup directory
            restore_location: Where to restore the worktree

        Returns:
            Dictionary with restore result

        Raises:
            IOError: If restoration fails
        """
        if not backup_path.exists():
            raise IOError(f"Backup does not exist: {backup_path}")

        logger.info(f"Restoring from backup: {backup_path} -> {restore_location}")

        try:
            # Create restore location parent directory
            restore_location.parent.mkdir(parents=True, exist_ok=True)

            # Copy backup contents to restore location
            await self._copy_directory_async(backup_path, restore_location)

            logger.info(f"Worktree restored successfully: {restore_location}")

            return {
                "success": True,
                "restored_path": str(restore_location),
                "backup_path": str(backup_path),
            }

        except Exception as e:
            logger.error(f"Failed to restore from backup: {e}", exc_info=True)
            raise IOError(f"Backup restoration failed: {e}") from e

    async def cleanup_old_backups(self) -> int:
        """Clean up old backups based on retention policy.

        Removes backups older than retention_days.

        Returns:
            Number of backups removed
        """
        from datetime import timedelta

        cutoff_time = datetime.now(tz=UTC) - timedelta(days=self.retention_days)
        removed_count = 0

        logger.info(f"Cleaning up backups older than {self.retention_days} days")

        try:
            # Iterate through backup directories
            for backup_dir in self.backup_dir.iterdir():
                if not backup_dir.is_dir():
                    continue

                # Read metadata file to get creation time
                metadata_file = backup_dir / ".backup_metadata.json"
                if not metadata_file.exists():
                    # No metadata, skip (don't delete unknown directories)
                    continue

                async with aiofiles.open(metadata_file, "r") as f:
                    import json

                    metadata = json.loads(await f.read())
                    created_at_str = metadata.get("created_at")

                    if not created_at_str:
                        continue

                    created_at = datetime.fromisoformat(created_at_str)

                    # Delete if older than retention period
                    if created_at < cutoff_time:
                        # Remove entire backup directory
                        import shutil

                        shutil.rmtree(backup_dir)
                        removed_count += 1
                        logger.debug(f"Removed old backup: {backup_dir}")

            logger.info(f"Cleaned up {removed_count} old backups")
            return removed_count

        except Exception as e:
            logger.error(f"Backup cleanup failed: {e}", exc_info=True)
            return 0

    async def list_backups(
        self,
        repo_nickname: str | None = None,
    ) -> list[dict[str, Any]]:
        """List available backups.

        Args:
            repo_nickname: Filter by repository nickname (None = all)

        Returns:
            List of backup metadata dictionaries
        """
        backups = []

        try:
            for backup_dir in self.backup_dir.iterdir():
                if not backup_dir.is_dir():
                    continue

                # Read metadata file
                metadata_file = backup_dir / ".backup_metadata.json"
                if not metadata_file.exists():
                    continue

                async with aiofiles.open(metadata_file, "r") as f:
                    import json

                    metadata = json.loads(await f.read())
                    backups.append(metadata)

            # Filter by repository if specified
            if repo_nickname:
                backups = [
                    b for b in backups if b.get("repo_nickname") == repo_nickname
                ]

            # Sort by creation time (newest first)
            backups.sort(key=lambda b: b["created_at"], reverse=True)

            return backups

        except Exception as e:
            logger.error(f"Failed to list backups: {e}", exc_info=True)
            return []
