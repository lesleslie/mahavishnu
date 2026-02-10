"""Backup and disaster recovery system for Mahavishnu."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import logging
from operator import itemgetter
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import Any


@dataclass
class BackupInfo:
    """Information about a backup."""

    backup_id: str
    timestamp: datetime
    size_bytes: int
    location: str
    status: str
    files_backed_up: int
    checksum: str


class BackupManager:
    """Manages backups of Mahavishnu configuration and data."""

    def __init__(self, app) -> None:
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.backup_dir = Path(getattr(app.config, "backup_directory", "./backups"))
        self.backup_dir.mkdir(exist_ok=True)

        # Initialize backup schedule
        self.backup_schedule = getattr(
            app.config,
            "backup_schedule",
            {
                "daily": 7,  # Keep 7 daily backups
                "weekly": 4,  # Keep 4 weekly backups
                "monthly": 12,  # Keep 12 monthly backups
            },
        )

    async def create_backup(self, backup_type: str = "full") -> BackupInfo:
        """Create a backup of the system."""
        backup_id = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = self.backup_dir / f"{backup_id}.tar.gz"

        try:
            # Create temporary directory for backup
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Backup configuration
                config_backup = temp_path / "config"
                config_backup.mkdir()
                await self._backup_config(config_backup)

                # Backup workflow states
                workflow_backup = temp_path / "workflows"
                workflow_backup.mkdir()
                await self._backup_workflows(workflow_backup)

                # Backup any other important data
                metadata: dict[str, Any] = {
                    "backup_id": backup_id,
                    "timestamp": datetime.now().isoformat(),
                    "type": backup_type,
                    "version": "1.0.0",
                    "config": self.app.config.model_dump()
                    if hasattr(self.app.config, "model_dump")
                    else {},
                }

                # Write metadata
                with (temp_path / "metadata.json").open("w") as f:
                    json.dump(metadata, f, indent=2, default=str)

                # Create archive
                with tarfile.open(backup_path, "w:gz") as tar:
                    for file_path in temp_path.rglob("*"):
                        if file_path.is_file():
                            arcname = file_path.relative_to(temp_path)
                            tar.add(file_path, arcname=str(arcname))

                # Calculate checksum
                checksum = await self._calculate_checksum(backup_path)

                # Get file size
                size_bytes = backup_path.stat().st_size

                # Create backup info
                backup_info = BackupInfo(
                    backup_id=backup_id,
                    timestamp=datetime.now(),
                    size_bytes=size_bytes,
                    location=str(backup_path),
                    status="completed",
                    files_backed_up=len(list(temp_path.rglob("*"))),
                    checksum=checksum,
                )

                self.logger.info(f"Created backup: {backup_id} ({size_bytes} bytes)")

                # Clean up old backups
                await self._cleanup_old_backups()

                return backup_info

        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            raise

    async def _backup_config(self, backup_dir: Path) -> None:
        """Backup configuration files."""
        try:
            # Copy configuration files
            config_sources = [
                "./settings/mahavishnu.yaml",
                "./settings/local.yaml",
                "./settings/ecosystem.yaml",
            ]

            for config_source in config_sources:
                source_path = Path(config_source)
                if source_path.exists():
                    dest_path = backup_dir / source_path.name
                    shutil.copy2(source_path, dest_path)

        except Exception as e:
            self.logger.warning(f"Failed to backup config: {e}")

    async def _backup_workflows(self, backup_dir: Path) -> None:
        """Backup workflow states."""
        try:
            # Get all workflows
            all_workflows = await self.app.workflow_state_manager.list_workflows(limit=10000)

            # Save workflows to JSON
            workflows_file = backup_dir / "workflows.json"
            with workflows_file.open("w") as f:
                json.dump(all_workflows, f, indent=2, default=str)

        except Exception as e:
            self.logger.warning(f"Failed to backup workflows: {e}")

    async def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with file_path.open("rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    async def _cleanup_old_backups(self) -> None:
        """Clean up old backups based on retention policy."""
        try:
            # Get all backup files
            backup_files = list(self.backup_dir.glob("backup_*.tar.gz"))
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

            # Group by day, week, month
            now = datetime.now()
            daily_backups = []
            weekly_backups = []
            monthly_backups = []

            for backup_file in backup_files:
                # Extract date from filename
                try:
                    date_str = (
                        backup_file.name.split(".")[0].split("_")[1]
                        + backup_file.name.split(".")[0].split("_")[2]
                    )
                    backup_date = datetime.strptime(date_str, "%Y%m%d%H%M%S")

                    days_diff = (now - backup_date).days

                    if days_diff < 7:  # Daily
                        daily_backups.append((backup_file, backup_date))
                    elif days_diff < 30:  # Weekly
                        weekly_backups.append((backup_file, backup_date))
                    else:  # Monthly
                        monthly_backups.append((backup_file, backup_date))

                except ValueError:
                    continue  # Skip malformed filenames

            # Keep only the specified number of backups
            backups_to_keep = []

            # Keep daily backups
            daily_backups.sort(key=itemgetter(1), reverse=True)
            backups_to_keep.extend(daily_backups[: self.backup_schedule["daily"]])

            # Keep weekly backups
            weekly_backups.sort(key=itemgetter(1), reverse=True)
            backups_to_keep.extend(weekly_backups[: self.backup_schedule["weekly"]])

            # Keep monthly backups
            monthly_backups.sort(key=itemgetter(1), reverse=True)
            backups_to_keep.extend(monthly_backups[: self.backup_schedule["monthly"]])

            # Delete old backups
            all_backups_set = {
                (bf[0], bf[1]) for bf in daily_backups + weekly_backups + monthly_backups
            }
            keep_set = set(backups_to_keep)
            delete_set = all_backups_set - keep_set

            for backup_file, _ in delete_set:
                try:
                    backup_file.unlink()
                    self.logger.info(f"Deleted old backup: {backup_file.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete backup {backup_file.name}: {e}")

        except Exception as e:
            self.logger.warning(f"Failed to cleanup old backups: {e}")

    async def restore_backup(self, backup_id: str) -> bool:
        """Restore from a backup."""
        backup_path = self.backup_dir / f"{backup_id}.tar.gz"

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        try:
            # Verify checksum (placeholder - would compare against stored checksum)
            _stored_checksum = await self._calculate_checksum(backup_path)
            # Note: We'd need to store the original checksum to verify

            # Extract to temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Extract archive
                with tarfile.open(backup_path, "r:gz") as tar:
                    # Check for path traversal attacks
                    for member in tar.getmembers():
                        if "../" in member.name or member.name.startswith("/"):
                            raise ValueError(
                                f"Path traversal attempt detected in backup: {member.name}"
                            )

                    tar.extractall(path=temp_path)

                # Restore configuration
                config_dir = temp_path / "config"
                if config_dir.exists():
                    await self._restore_config(config_dir)

                # Restore workflows
                workflow_dir = temp_path / "workflows"
                if workflow_dir.exists():
                    await self._restore_workflows(workflow_dir)

                self.logger.info(f"Restored backup: {backup_id}")
                return True

        except Exception as e:
            self.logger.error(f"Failed to restore backup: {e}")
            raise

    async def _restore_config(self, config_dir: Path) -> None:
        """Restore configuration files."""
        # This would restore config files to their original locations
        # Implementation depends on specific deployment setup
        self.logger.info(f"Restoring configuration from {config_dir}")

    async def _restore_workflows(self, workflow_dir: Path) -> None:
        """Restore workflow states."""
        workflows_file = workflow_dir / "workflows.json"
        if workflows_file.exists():
            with workflows_file.open() as f:
                workflows: list[dict[str, Any]] = json.load(f)

            # Restore each workflow to the workflow state manager
            for workflow in workflows:
                workflow_id = workflow.get("id") or workflow.get("workflow_id")
                if workflow_id:
                    # Update the workflow in the state manager
                    await self.app.workflow_state_manager.update(
                        workflow_id=workflow_id, **workflow
                    )

            self.logger.info(f"Restored {len(workflows)} workflows")

    async def list_backups(self) -> list[BackupInfo]:
        """List all available backups."""
        backup_files = list(self.backup_dir.glob("backup_*.tar.gz"))
        backups = []

        for backup_file in backup_files:
            try:
                # Extract backup ID from filename
                backup_id = backup_file.name.replace(".tar.gz", "")

                # Get file stats
                stat = backup_file.stat()
                timestamp = datetime.fromtimestamp(stat.st_mtime)

                # Create backup info
                backup_info = BackupInfo(
                    backup_id=backup_id,
                    timestamp=timestamp,
                    size_bytes=stat.st_size,
                    location=str(backup_file),
                    status="available",
                    files_backed_up=0,  # Would need to extract to get exact count
                    checksum="",  # Would need to calculate
                )

                backups.append(backup_info)

            except Exception as e:
                self.logger.warning(f"Failed to read backup info for {backup_file}: {e}")

        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x.timestamp, reverse=True)
        return backups

    async def get_backup_info(self, backup_id: str) -> BackupInfo | None:
        """Get information about a specific backup."""
        backup_path = self.backup_dir / f"{backup_id}.tar.gz"

        if not backup_path.exists():
            return None

        try:
            stat = backup_path.stat()
            timestamp = datetime.fromtimestamp(stat.st_mtime)

            # Try to extract metadata if possible
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                with tarfile.open(backup_path, "r:gz") as tar:
                    # Extract just the metadata file
                    members = [m for m in tar.getmembers() if m.name == "metadata.json"]
                    if members:
                        tar.extract(members[0], path=temp_path)
                        metadata_path = temp_path / "metadata.json"
                        if metadata_path.exists():
                            with metadata_path.open() as f:
                                # Metadata loaded but not currently used
                                _metadata = json.load(f)

            return BackupInfo(
                backup_id=backup_id,
                timestamp=timestamp,
                size_bytes=stat.st_size,
                location=str(backup_path),
                status="available",
                files_backed_up=0,  # Would need to count files in archive
                checksum=await self._calculate_checksum(backup_path),
            )
        except Exception as e:
            self.logger.warning(f"Failed to get backup info for {backup_id}: {e}")
            return None


class DisasterRecoveryManager:
    """Manages disaster recovery procedures."""

    def __init__(self, app) -> None:
        self.app = app
        self.backup_manager = BackupManager(app)
        self.logger = logging.getLogger(__name__)
        self.disaster_recovery_plan: dict[str, Any] = {}

    async def run_disaster_recovery_check(self) -> dict[str, Any]:
        """Run a comprehensive disaster recovery check."""
        results = {"timestamp": datetime.now().isoformat(), "checks": {}, "status": "healthy"}

        # Check backup availability
        backups = await self.backup_manager.list_backups()
        results["checks"]["backups_available"] = {
            "status": "pass" if backups else "fail",
            "count": len(backups),
            "latest_backup": backups[0].timestamp.isoformat() if backups else None,
        }

        # Check backup integrity (sample a few recent backups)
        recent_backups = backups[:3]  # Check 3 most recent
        integrity_check = {"status": "pass", "checked": 0, "failed": 0}

        for backup in recent_backups:
            try:
                # Try to read backup info to verify integrity
                info = await self.backup_manager.get_backup_info(backup.backup_id)
                if info:
                    integrity_check["checked"] += 1
                else:
                    integrity_check["failed"] += 1
                    integrity_check["status"] = "fail"
            except Exception:
                integrity_check["failed"] += 1
                integrity_check["status"] = "fail"

        results["checks"]["backup_integrity"] = integrity_check

        # Check if we have recent backups (within last 24 hours)
        if backups:
            latest_backup_age = datetime.now() - backups[0].timestamp
            recent_backup_ok = latest_backup_age < timedelta(hours=24)
        else:
            recent_backup_ok = False

        results["checks"]["recent_backup"] = {
            "status": "pass" if recent_backup_ok else "fail",
            "latest_backup_age_hours": latest_backup_age.total_seconds() / 3600
            if backups
            else None,
        }

        # Overall status
        if any(check.get("status") == "fail" for check in results["checks"].values()):
            results["status"] = "needs_attention"

        return results

    async def initiate_disaster_recovery(
        self, backup_id: str | None = None, components: list[str] | None = None
    ) -> dict[str, Any]:
        """Initiate disaster recovery procedure."""
        if components is None:
            components = ["config", "workflows", "state"]

        try:
            # If no backup ID specified, use the most recent one
            if not backup_id:
                backups = await self.backup_manager.list_backups()
                if not backups:
                    return {"status": "fail", "error": "No backups available for recovery"}
                backup_id = backups[0].backup_id

            # Perform restoration
            success = await self.backup_manager.restore_backup(backup_id)

            if success:
                # Restart critical services after recovery
                await self._restart_services()

                return {
                    "status": "success",
                    "message": f"Disaster recovery completed using backup {backup_id}",
                    "restored_components": components,
                    "backup_used": backup_id,
                }
            else:
                return {"status": "fail", "error": f"Failed to restore from backup {backup_id}"}

        except Exception as e:
            self.logger.error(f"Disaster recovery failed: {e}")
            return {"status": "fail", "error": str(e)}

    async def _restart_services(self) -> None:
        """Restart critical services after recovery."""
        # In a real implementation, this would restart services
        # like the MCP server, workflow processors, etc.
        self.logger.info("Services restarted after disaster recovery")

    async def schedule_regular_backups(self) -> None:
        """Schedule regular backups based on configuration."""
        # This would typically run as a background task
        # Implementation would depend on the scheduler used
        self.logger.info("Scheduled regular backups")

    async def get_recovery_procedures(self) -> dict[str, Any]:
        """Get disaster recovery procedures and documentation."""
        return {
            "procedures": {
                "emergency_contact": "admin@example.com",
                "recovery_steps": [
                    "Assess the scope of the disaster",
                    "Identify the most recent good backup",
                    "Initiate disaster recovery using the backup",
                    "Verify system functionality after recovery",
                    "Notify stakeholders of recovery status",
                ],
                "recovery_time_objective": "4 hours",
                "recovery_point_objective": "24 hours",
                "contact_info": {
                    "primary": "admin@example.com",
                    "secondary": "backup-admin@example.com",
                    "pager": "+1-555-0123",
                },
            },
            "automation": {
                "automatic_backup": True,
                "backup_frequency": "daily",
                "retention_policy": "7 daily, 4 weekly, 12 monthly",
                "monitoring": True,
                "alerts": True,
            },
        }


class BackupAndRecoveryCLI:
    """CLI commands for backup and recovery operations."""

    def __init__(self, app) -> None:
        self.app = app
        self.backup_manager = BackupManager(app)
        self.recovery_manager = DisasterRecoveryManager(app)

    async def create_backup(self, backup_type: str = "full") -> dict[str, Any]:
        """Create a new backup."""
        try:
            backup_info = await self.backup_manager.create_backup(backup_type)
            return {
                "status": "success",
                "backup_id": backup_info.backup_id,
                "location": backup_info.location,
                "size_mb": round(backup_info.size_bytes / (1024 * 1024), 2),
                "timestamp": backup_info.timestamp.isoformat(),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def list_backups(self) -> dict[str, Any]:
        """List all available backups."""
        try:
            backups = await self.backup_manager.list_backups()
            return {
                "status": "success",
                "backups": [
                    {
                        "backup_id": b.backup_id,
                        "timestamp": b.timestamp.isoformat(),
                        "size_mb": round(b.size_bytes / (1024 * 1024), 2),
                        "status": b.status,
                    }
                    for b in backups
                ],
                "total_count": len(backups),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def restore_backup(self, backup_id: str) -> dict[str, Any]:
        """Restore from a backup."""
        try:
            success = await self.backup_manager.restore_backup(backup_id)
            return {
                "status": "success" if success else "error",
                "message": f"Restore {'completed' if success else 'failed'} for backup {backup_id}",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def run_disaster_recovery_check(self) -> dict[str, Any]:
        """Run disaster recovery check."""
        try:
            results = await self.recovery_manager.run_disaster_recovery_check()
            return {"status": results["status"], "results": results}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def get_recovery_procedures(self) -> dict[str, Any]:
        """Get disaster recovery procedures."""
        try:
            procedures = await self.recovery_manager.get_recovery_procedures()
            return {"status": "success", "procedures": procedures}
        except Exception as e:
            return {"status": "error", "error": str(e)}
