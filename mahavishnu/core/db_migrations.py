"""Database Migration Utilities - Migration management.

Provides database migration infrastructure:

- Migration version tracking
- Up/down migration support
- Rollback capabilities
- Migration validation
- Dependency resolution

Usage:
    from mahavishnu.core.db_migrations import MigrationManager, Migration

    manager = MigrationManager()

    migration = Migration(
        id="001",
        name="create_tasks",
        version="1.0.0",
        up_sql="CREATE TABLE tasks (id TEXT);",
        down_sql="DROP TABLE tasks;",
    )

    manager.register(migration)
    await manager.run_all_pending()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import logging
import time
from typing import Any

from mahavishnu.core.status import MigrationStatus

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """A database migration.

    Attributes:
        id: Unique migration identifier
        name: Migration name
        version: Database version this migration provides
        up_sql: SQL to apply migration
        down_sql: SQL to rollback migration
        status: Current migration status
        dependencies: List of migration IDs this depends on
        applied_at: When migration was applied
    """

    id: str
    name: str
    version: str
    up_sql: str
    down_sql: str
    status: MigrationStatus = MigrationStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    applied_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        }


@dataclass
class MigrationScript:
    """A migration script with checksum.

    Attributes:
        name: Script name
        up_script: Up migration script
        down_script: Down migration script
    """

    name: str
    up_script: str
    down_script: str

    def checksum(self) -> str:
        """Generate checksum for script content.

        Returns:
            SHA-256 checksum hex string
        """
        content = f"{self.up_script}\n---\n{self.down_script}"
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class MigrationResult:
    """Result of a migration operation.

    Attributes:
        migration_id: Migration identifier
        status: Migration status
        execution_time_ms: Execution time in milliseconds
        error: Error message if failed
        applied_at: When migration was applied
    """

    migration_id: str
    status: MigrationStatus
    execution_time_ms: float = 0.0
    error: str | None = None
    applied_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def success(self) -> bool:
        """Check if migration was successful."""
        return self.status in (
            MigrationStatus.COMPLETED,
            MigrationStatus.ROLLED_BACK,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "migration_id": self.migration_id,
            "status": self.status.value,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
            "applied_at": self.applied_at.isoformat(),
        }


@dataclass
class MigrationPlan:
    """A migration execution plan.

    Attributes:
        migrations_to_run: Migrations to apply (in order)
        migrations_to_rollback: Migrations to rollback (in order)
    """

    migrations_to_run: list[str] = field(default_factory=list)
    migrations_to_rollback: list[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Get total number of migrations."""
        return len(self.migrations_to_run) + len(self.migrations_to_rollback)

    @property
    def is_empty(self) -> bool:
        """Check if plan is empty."""
        return self.total_count == 0


class MigrationManager:
    """Manages database migrations.

    Features:
    - Register and track migrations
    - Run migrations in order
    - Rollback migrations
    - Validate dependencies
    - Version tracking

    Example:
        manager = MigrationManager()
        manager.register(migration)
        await manager.run_all_pending()
    """

    def __init__(self) -> None:
        """Initialize migration manager."""
        self.migrations: dict[str, Migration] = {}
        self._results: list[MigrationResult] = []

    def register(self, migration: Migration) -> None:
        """Register a migration.

        Args:
            migration: Migration to register
        """
        self.migrations[migration.id] = migration
        logger.debug(f"Registered migration {migration.id}: {migration.name}")

    def get_pending_migrations(self) -> list[Migration]:
        """Get all pending migrations.

        Returns:
            List of pending migrations
        """
        return [m for m in self.migrations.values() if m.status == MigrationStatus.PENDING]

    def get_completed_migrations(self) -> list[Migration]:
        """Get all completed migrations.

        Returns:
            List of completed migrations
        """
        return [m for m in self.migrations.values() if m.status == MigrationStatus.COMPLETED]

    def get_current_version(self) -> str:
        """Get current database version.

        Returns:
            Current version string
        """
        completed = self.get_completed_migrations()
        if not completed:
            return "0.0.0"

        # Return highest version
        versions = [m.version for m in completed]
        return max(versions)

    async def run_migration(self, migration_id: str) -> MigrationResult:
        """Run a single migration.

        Args:
            migration_id: Migration ID to run

        Returns:
            MigrationResult
        """
        migration = self.migrations.get(migration_id)
        if not migration:
            return MigrationResult(
                migration_id=migration_id,
                status=MigrationStatus.FAILED,
                error=f"Migration {migration_id} not found",
            )

        logger.info(f"Running migration {migration_id}: {migration.name}")

        start_time = time.time()
        migration.status = MigrationStatus.RUNNING

        try:
            success = await self._execute_sql(migration.up_sql)

            execution_time = (time.time() - start_time) * 1000

            if success:
                migration.status = MigrationStatus.COMPLETED
                migration.applied_at = datetime.now(UTC)

                result = MigrationResult(
                    migration_id=migration_id,
                    status=MigrationStatus.COMPLETED,
                    execution_time_ms=execution_time,
                )
            else:
                migration.status = MigrationStatus.FAILED
                result = MigrationResult(
                    migration_id=migration_id,
                    status=MigrationStatus.FAILED,
                    execution_time_ms=execution_time,
                    error="SQL execution failed",
                )

            self._results.append(result)
            return result

        except Exception as e:
            migration.status = MigrationStatus.FAILED
            result = MigrationResult(
                migration_id=migration_id,
                status=MigrationStatus.FAILED,
                error=str(e),
            )
            self._results.append(result)
            return result

    async def rollback_migration(self, migration_id: str) -> MigrationResult:
        """Rollback a migration.

        Args:
            migration_id: Migration ID to rollback

        Returns:
            MigrationResult
        """
        migration = self.migrations.get(migration_id)
        if not migration:
            return MigrationResult(
                migration_id=migration_id,
                status=MigrationStatus.FAILED,
                error=f"Migration {migration_id} not found",
            )

        if migration.status != MigrationStatus.COMPLETED:
            return MigrationResult(
                migration_id=migration_id,
                status=MigrationStatus.FAILED,
                error=f"Migration {migration_id} is not completed",
            )

        logger.info(f"Rolling back migration {migration_id}: {migration.name}")

        start_time = time.time()

        try:
            success = await self._execute_sql(migration.down_sql)

            execution_time = (time.time() - start_time) * 1000

            if success:
                migration.status = MigrationStatus.ROLLED_BACK
                migration.applied_at = None

                result = MigrationResult(
                    migration_id=migration_id,
                    status=MigrationStatus.ROLLED_BACK,
                    execution_time_ms=execution_time,
                )
            else:
                result = MigrationResult(
                    migration_id=migration_id,
                    status=MigrationStatus.FAILED,
                    execution_time_ms=execution_time,
                    error="Rollback SQL execution failed",
                )

            self._results.append(result)
            return result

        except Exception as e:
            result = MigrationResult(
                migration_id=migration_id,
                status=MigrationStatus.FAILED,
                error=str(e),
            )
            self._results.append(result)
            return result

    async def run_all_pending(self) -> list[MigrationResult]:
        """Run all pending migrations in order.

        Returns:
            List of MigrationResult
        """
        pending = self.get_pending_migrations()
        results: list[MigrationResult] = []

        # Sort by version
        pending.sort(key=lambda m: m.version)

        for migration in pending:
            result = await self.run_migration(migration.id)
            results.append(result)

            if not result.success:
                logger.error(f"Migration {migration.id} failed, stopping")
                break

        return results

    async def create_plan(self, target_version: str) -> MigrationPlan:
        """Create a migration plan.

        Args:
            target_version: Target database version

        Returns:
            MigrationPlan
        """
        to_run: list[str] = []
        to_rollback: list[str] = []

        current = self.get_current_version()

        for migration in self.migrations.values():
            if (
                migration.status == MigrationStatus.PENDING
                and self._version_compare(migration.version, current) > 0
                and self._version_compare(migration.version, target_version) <= 0
            ):
                to_run.append(migration.id)

        return MigrationPlan(
            migrations_to_run=to_run,
            migrations_to_rollback=to_rollback,
        )

    def _version_compare(self, v1: str, v2: str) -> int:
        """Compare two version strings.

        Args:
            v1: First version
            v2: Second version

        Returns:
            -1 if v1 < v2, 0 if equal, 1 if v1 > v2
        """
        parts1 = [int(p) for p in v1.split(".")]
        parts2 = [int(p) for p in v2.split(".")]

        for p1, p2 in zip(parts1, parts2, strict=False):
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1

        if len(parts1) < len(parts2):
            return -1
        if len(parts1) > len(parts2):
            return 1

        return 0

    def validate_dependencies(self) -> bool:
        """Validate all migration dependencies exist.

        Returns:
            True if all dependencies are valid
        """
        for migration in self.migrations.values():
            for dep_id in migration.dependencies:
                if dep_id not in self.migrations:
                    logger.error(
                        f"Migration {migration.id} depends on non-existent migration {dep_id}"
                    )
                    return False
        return True

    async def migrate_to_version(
        self,
        target_version: str,
    ) -> list[MigrationResult]:
        """Migrate to a specific version.

        Args:
            target_version: Target database version

        Returns:
            List of MigrationResult
        """
        plan = await self.create_plan(target_version)
        results: list[MigrationResult] = []

        for migration_id in plan.migrations_to_run:
            result = await self.run_migration(migration_id)
            results.append(result)

            if not result.success:
                break

        return results

    def get_migration_history(self) -> list[Migration]:
        """Get migration history.

        Returns:
            List of applied migrations
        """
        completed = self.get_completed_migrations()
        completed.sort(key=lambda m: m.applied_at or datetime.min.replace(tzinfo=UTC))
        return completed

    async def dry_run(self) -> MigrationPlan:
        """Create a dry run plan without executing.

        Returns:
            MigrationPlan with pending migrations
        """
        pending = self.get_pending_migrations()
        pending.sort(key=lambda m: m.version)

        return MigrationPlan(
            migrations_to_run=[m.id for m in pending],
            migrations_to_rollback=[],
        )

    async def _execute_sql(self, sql: str) -> bool:
        """Execute SQL statement.

        Args:
            sql: SQL to execute

        Returns:
            True if successful
        """
        # Placeholder for actual SQL execution
        # In production, this would connect to the database
        logger.debug(f"Executing SQL: {sql[:100]}...")
        return True


__all__ = [
    "MigrationManager",
    "Migration",
    "MigrationStatus",
    "MigrationResult",
    "MigrationScript",
    "MigrationPlan",
]
