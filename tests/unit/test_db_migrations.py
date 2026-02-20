"""Tests for Database Migration Utilities - Migration management."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.db_migrations import (
    MigrationManager,
    Migration,
    MigrationStatus,
    MigrationResult,
    MigrationScript,
    MigrationPlan,
)


@pytest.fixture
def sample_migration() -> Migration:
    """Create a sample migration."""
    return Migration(
        id="001",
        name="create_tasks_table",
        version="1.0.0",
        up_sql="CREATE TABLE tasks (id TEXT PRIMARY KEY);",
        down_sql="DROP TABLE tasks;",
    )


class TestMigrationStatus:
    """Tests for MigrationStatus enum."""

    def test_migration_statuses(self) -> None:
        """Test available migration statuses."""
        assert MigrationStatus.PENDING.value == "pending"
        assert MigrationStatus.RUNNING.value == "running"
        assert MigrationStatus.COMPLETED.value == "completed"
        assert MigrationStatus.FAILED.value == "failed"
        assert MigrationStatus.ROLLED_BACK.value == "rolled_back"


class TestMigration:
    """Tests for Migration class."""

    def test_create_migration(self) -> None:
        """Create a migration."""
        migration = Migration(
            id="001",
            name="test_migration",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        )

        assert migration.id == "001"
        assert migration.name == "test_migration"
        assert migration.version == "1.0.0"

    def test_migration_defaults(self) -> None:
        """Test migration defaults."""
        migration = Migration(
            id="001",
            name="test",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        )

        assert migration.status == MigrationStatus.PENDING
        assert migration.dependencies == []

    def test_migration_with_dependencies(self) -> None:
        """Create migration with dependencies."""
        migration = Migration(
            id="002",
            name="add_columns",
            version="1.1.0",
            up_sql="ALTER TABLE tasks ADD COLUMN status TEXT;",
            down_sql="ALTER TABLE tasks DROP COLUMN status;",
            dependencies=["001"],
        )

        assert migration.dependencies == ["001"]

    def test_migration_to_dict(self) -> None:
        """Convert migration to dictionary."""
        migration = Migration(
            id="001",
            name="test",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        )

        d = migration.to_dict()

        assert d["id"] == "001"
        assert d["name"] == "test"
        assert d["status"] == "pending"


class TestMigrationScript:
    """Tests for MigrationScript class."""

    def test_create_script(self) -> None:
        """Create a migration script."""
        script = MigrationScript(
            name="create_users",
            up_script="CREATE TABLE users (id TEXT);",
            down_script="DROP TABLE users;",
        )

        assert script.name == "create_users"
        assert "CREATE TABLE" in script.up_script

    def test_script_checksum(self) -> None:
        """Generate script checksum."""
        script = MigrationScript(
            name="test",
            up_script="SELECT 1;",
            down_script="SELECT 0;",
        )

        checksum = script.checksum()

        assert checksum is not None
        assert len(checksum) == 64  # SHA-256 hex length

    def test_script_checksum_consistent(self) -> None:
        """Checksum is consistent for same content."""
        script1 = MigrationScript(
            name="test",
            up_script="SELECT 1;",
            down_script="SELECT 0;",
        )
        script2 = MigrationScript(
            name="test",
            up_script="SELECT 1;",
            down_script="SELECT 0;",
        )

        assert script1.checksum() == script2.checksum()

    def test_script_checksum_different(self) -> None:
        """Checksum differs for different content."""
        script1 = MigrationScript(
            name="test",
            up_script="SELECT 1;",
            down_script="SELECT 0;",
        )
        script2 = MigrationScript(
            name="test",
            up_script="SELECT 2;",
            down_script="SELECT 0;",
        )

        assert script1.checksum() != script2.checksum()


class TestMigrationResult:
    """Tests for MigrationResult class."""

    def test_success_result(self) -> None:
        """Create a successful result."""
        result = MigrationResult(
            migration_id="001",
            status=MigrationStatus.COMPLETED,
            execution_time_ms=150.0,
        )

        assert result.migration_id == "001"
        assert result.status == MigrationStatus.COMPLETED
        assert result.success is True

    def test_failed_result(self) -> None:
        """Create a failed result."""
        result = MigrationResult(
            migration_id="001",
            status=MigrationStatus.FAILED,
            error="Table already exists",
        )

        assert result.status == MigrationStatus.FAILED
        assert result.success is False
        assert result.error == "Table already exists"

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = MigrationResult(
            migration_id="001",
            status=MigrationStatus.COMPLETED,
            execution_time_ms=150.0,
        )

        d = result.to_dict()

        assert d["migration_id"] == "001"
        assert d["status"] == "completed"
        assert d["success"] is True


class TestMigrationPlan:
    """Tests for MigrationPlan class."""

    def test_create_plan(self) -> None:
        """Create a migration plan."""
        plan = MigrationPlan(
            migrations_to_run=["001", "002"],
            migrations_to_rollback=[],
        )

        assert plan.migrations_to_run == ["001", "002"]
        assert len(plan.migrations_to_rollback) == 0

    def test_plan_total_count(self) -> None:
        """Get total migration count."""
        plan = MigrationPlan(
            migrations_to_run=["001", "002", "003"],
            migrations_to_rollback=["004"],
        )

        assert plan.total_count == 4

    def test_plan_is_empty(self) -> None:
        """Check if plan is empty."""
        empty_plan = MigrationPlan(migrations_to_run=[], migrations_to_rollback=[])
        non_empty_plan = MigrationPlan(migrations_to_run=["001"], migrations_to_rollback=[])

        assert empty_plan.is_empty is True
        assert non_empty_plan.is_empty is False


class TestMigrationManager:
    """Tests for MigrationManager class."""

    def test_create_manager(self) -> None:
        """Create a migration manager."""
        manager = MigrationManager()

        assert manager is not None
        assert len(manager.migrations) == 0

    def test_register_migration(
        self,
        sample_migration: Migration,
    ) -> None:
        """Register a migration."""
        manager = MigrationManager()

        manager.register(sample_migration)

        assert len(manager.migrations) == 1
        assert manager.migrations["001"] == sample_migration

    def test_get_pending_migrations(self) -> None:
        """Get pending migrations."""
        manager = MigrationManager()

        # Register migrations
        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
            status=MigrationStatus.COMPLETED,
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            status=MigrationStatus.PENDING,
        ))

        pending = manager.get_pending_migrations()

        assert len(pending) == 1
        assert pending[0].id == "002"

    def test_get_completed_migrations(self) -> None:
        """Get completed migrations."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
            status=MigrationStatus.COMPLETED,
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            status=MigrationStatus.PENDING,
        ))

        completed = manager.get_completed_migrations()

        assert len(completed) == 1
        assert completed[0].id == "001"

    def test_get_current_version(self) -> None:
        """Get current database version."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
            status=MigrationStatus.COMPLETED,
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            status=MigrationStatus.COMPLETED,
        ))

        version = manager.get_current_version()

        assert version == "1.1.0"

    def test_get_current_version_no_migrations(self) -> None:
        """Get version when no migrations exist."""
        manager = MigrationManager()

        version = manager.get_current_version()

        assert version == "0.0.0"

    @pytest.mark.asyncio
    async def test_run_migration(
        self,
        sample_migration: Migration,
    ) -> None:
        """Run a migration."""
        manager = MigrationManager()
        manager.register(sample_migration)

        with patch.object(manager, '_execute_sql', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = True

            result = await manager.run_migration("001")

            assert result.success is True
            assert result.status == MigrationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_run_migration_not_found(self) -> None:
        """Run migration that doesn't exist."""
        manager = MigrationManager()

        result = await manager.run_migration("999")

        assert result.success is False
        assert result.status == MigrationStatus.FAILED

    @pytest.mark.asyncio
    async def test_rollback_migration(
        self,
        sample_migration: Migration,
    ) -> None:
        """Rollback a migration."""
        manager = MigrationManager()
        sample_migration.status = MigrationStatus.COMPLETED
        manager.register(sample_migration)

        with patch.object(manager, '_execute_sql', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = True

            result = await manager.rollback_migration("001")

            assert result.success is True
            assert result.status == MigrationStatus.ROLLED_BACK

    @pytest.mark.asyncio
    async def test_run_all_pending(self) -> None:
        """Run all pending migrations."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
        ))

        with patch.object(manager, '_execute_sql', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = True

            results = await manager.run_all_pending()

            assert len(results) == 2
            assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_create_plan(self) -> None:
        """Create migration plan."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
            status=MigrationStatus.COMPLETED,
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            status=MigrationStatus.PENDING,
        ))

        plan = await manager.create_plan(target_version="1.1.0")

        assert "002" in plan.migrations_to_run

    def test_validate_dependencies(self) -> None:
        """Validate migration dependencies."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            dependencies=["001"],
        ))

        is_valid = manager.validate_dependencies()

        assert is_valid is True

    def test_validate_dependencies_missing(self) -> None:
        """Validate with missing dependencies."""
        manager = MigrationManager()

        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
            dependencies=["001"],  # 001 doesn't exist
        ))

        is_valid = manager.validate_dependencies()

        assert is_valid is False

    @pytest.mark.asyncio
    async def test_migrate_to_version(self) -> None:
        """Migrate to specific version."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
        ))
        manager.register(Migration(
            id="002",
            name="second",
            version="1.1.0",
            up_sql="SELECT 2;",
            down_sql="SELECT 2;",
        ))

        with patch.object(manager, '_execute_sql', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = True

            results = await manager.migrate_to_version("1.1.0")

            assert len(results) == 2

    def test_get_migration_history(self) -> None:
        """Get migration history."""
        manager = MigrationManager()

        manager.register(Migration(
            id="001",
            name="first",
            version="1.0.0",
            up_sql="SELECT 1;",
            down_sql="SELECT 1;",
            status=MigrationStatus.COMPLETED,
            applied_at=datetime.now(UTC),
        ))

        history = manager.get_migration_history()

        assert len(history) == 1
        assert history[0].id == "001"

    @pytest.mark.asyncio
    async def test_dry_run(
        self,
        sample_migration: Migration,
    ) -> None:
        """Dry run migration."""
        manager = MigrationManager()
        manager.register(sample_migration)

        plan = await manager.dry_run()

        assert "001" in plan.migrations_to_run
