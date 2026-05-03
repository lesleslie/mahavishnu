"""Tests for Database Migration Module.

Tests cover:
- Migration configuration
- Phase transitions
- Validation logic
- Rollback handling
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.database import DatabaseConfig
from mahavishnu.core.errors import DatabaseError
from mahavishnu.core.migrator import (
    DatabaseMigrator,
    MigrationConfig,
    MigrationMetrics,
    MigrationPhase,
    run_migration,
)


class TestMigrationConfig:
    """Test migration configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = MigrationConfig()

        assert config.sqlite_path == "data/mahavishnu.db"
        assert config.batch_size == 1000
        assert config.validation_sample_size == 100
        assert config.latency_threshold_multiplier == 2.0
        assert config.error_rate_threshold == 0.05
        assert config.enable_dual_write is True
        assert config.enable_validation is True

    def test_config_with_postgres(self) -> None:
        """Test configuration with PostgreSQL config."""
        pg_config = DatabaseConfig(host="postgres.example.com")
        config = MigrationConfig(postgres_config=pg_config)

        assert config.postgres_config is not None
        assert config.postgres_config.host == "postgres.example.com"


class TestMigrationMetrics:
    """Test migration metrics."""

    def test_to_dict(self) -> None:
        """Test metrics serialization."""
        metrics = MigrationMetrics(
            phase=MigrationPhase.DUAL_WRITE,
            rows_migrated=1000,
            rows_validated=1000,
            validation_errors=0,
        )

        result = metrics.to_dict()

        assert result["phase"] == "dual_write"
        assert result["rows_migrated"] == 1000
        assert result["rows_validated"] == 1000
        assert result["validation_errors"] == 0


class TestDatabaseMigrator:
    """Test database migrator."""

    def test_initialization(self) -> None:
        """Test migrator initialization."""
        config = MigrationConfig()
        migrator = DatabaseMigrator(config)

        assert migrator.config is not None
        assert migrator.current_phase == MigrationPhase.NOT_STARTED
        assert migrator.metrics is not None

    def test_current_phase(self) -> None:
        """Test phase tracking."""
        migrator = DatabaseMigrator()

        assert migrator.current_phase == MigrationPhase.NOT_STARTED

    @pytest.mark.asyncio
    async def test_cleanup_connections(self) -> None:
        """Test connection cleanup."""
        migrator = DatabaseMigrator()

        # Should not raise even without connections
        await migrator._cleanup_connections()


class TestMigrationPhases:
    """Test migration phase transitions."""

    @pytest.fixture
    def migrator(self) -> DatabaseMigrator:
        """Create migrator with mocked databases."""
        config = MigrationConfig(enable_validation=False)
        return DatabaseMigrator(config)

    def test_phase_enum_values(self) -> None:
        """Test phase enum has expected values."""
        assert MigrationPhase.NOT_STARTED.value == "not_started"
        assert MigrationPhase.DUAL_WRITE.value == "dual_write"
        assert MigrationPhase.DUAL_READ.value == "dual_read"
        assert MigrationPhase.CUTOVER.value == "cutover"
        assert MigrationPhase.CLEANUP.value == "cleanup"
        assert MigrationPhase.COMPLETED.value == "completed"
        assert MigrationPhase.ROLLED_BACK.value == "rolled_back"

    @pytest.mark.asyncio
    async def test_rollback_sets_phase(self, migrator: DatabaseMigrator) -> None:
        """Test that rollback sets correct phase."""
        await migrator._rollback()

        assert migrator.current_phase == MigrationPhase.ROLLED_BACK
        assert migrator.metrics.phase == MigrationPhase.ROLLED_BACK


class TestValidation:
    """Test migration validation."""

    @pytest.fixture
    def migrator_with_mocks(self) -> DatabaseMigrator:
        """Create migrator with mocked database connections."""
        config = MigrationConfig(enable_validation=False)

        migrator = DatabaseMigrator(config)

        # Mock PostgreSQL
        mock_postgres = MagicMock()
        mock_postgres.health_check = AsyncMock(return_value={"connected": True})
        mock_postgres.fetchval = AsyncMock(return_value=10)
        mock_postgres.disconnect = AsyncMock()
        migrator._postgres = mock_postgres

        # Mock SQLite
        mock_sqlite = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("tasks",)]
        mock_cursor.fetchone.side_effect = [(1,), (10,)]  # Table count, row count
        mock_sqlite.cursor.return_value = mock_cursor
        migrator._sqlite_conn = mock_sqlite

        return migrator

    @pytest.mark.asyncio
    async def test_validate_row_counts(self, migrator_with_mocks: DatabaseMigrator) -> None:
        """Test row count validation."""
        result = await migrator_with_mocks._validate_row_counts()

        assert "tables" in result
        assert "total_rows" in result
        assert "mismatches" in result


class TestMigratorCoverageBoost:
    """Additional targeted branch coverage for migrator internals."""

    @pytest.mark.asyncio
    async def test_migrate_full_success_and_phase_completed(self) -> None:
        migrator = DatabaseMigrator(
            MigrationConfig(enable_dual_write=False, enable_validation=False)
        )
        migrator._run_phase = AsyncMock()
        migrator._cleanup_connections = AsyncMock()

        metrics = await migrator.migrate()

        assert metrics.phase == MigrationPhase.COMPLETED
        assert migrator._run_phase.await_count == 3
        migrator._cleanup_connections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_migrate_failure_triggers_rollback_and_database_error(self) -> None:
        migrator = DatabaseMigrator(
            MigrationConfig(enable_dual_write=True, enable_validation=False)
        )
        migrator._run_phase = AsyncMock(side_effect=RuntimeError("boom"))
        migrator._rollback = AsyncMock()
        migrator._cleanup_connections = AsyncMock()

        with pytest.raises(DatabaseError) as exc:
            await migrator.migrate()

        assert "rolled back" in str(exc.value)
        assert migrator.metrics.rollback_triggered is True
        migrator._rollback.assert_awaited_once()
        migrator._cleanup_connections.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_phase_with_duration_and_failure(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig())
        phase_func = AsyncMock()
        with patch("mahavishnu.core.migrator.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            await migrator._run_phase(MigrationPhase.DUAL_WRITE, phase_func, duration_seconds=5)
        phase_func.assert_awaited_once()
        sleep_mock.assert_awaited_once_with(5)
        assert migrator.current_phase == MigrationPhase.DUAL_WRITE

        with pytest.raises(ValueError):
            await migrator._run_phase(
                MigrationPhase.CUTOVER, AsyncMock(side_effect=ValueError("x"))
            )

    @pytest.mark.asyncio
    async def test_connect_postgres_caches_connection(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig())
        db_instance = MagicMock()
        db_instance.connect = AsyncMock()
        with patch("mahavishnu.core.migrator.Database", return_value=db_instance) as db_cls:
            a = await migrator._connect_postgres()
            b = await migrator._connect_postgres()
        assert a is b
        db_cls.assert_called_once()
        db_instance.connect.assert_awaited_once()

    def test_connect_sqlite_sets_row_factory_and_reuses_connection(self, tmp_path) -> None:
        db_path = tmp_path / "data" / "m.db"
        migrator = DatabaseMigrator(MigrationConfig(sqlite_path=str(db_path)))
        conn1 = migrator._connect_sqlite()
        conn2 = migrator._connect_sqlite()
        assert conn1 is conn2
        assert migrator._sqlite_conn is not None
        assert migrator._sqlite_conn.row_factory == sqlite3.Row
        conn1.close()

    @pytest.mark.asyncio
    async def test_enable_dual_read_validation_error_raises(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig(enable_validation=True))
        migrator._validate_data_integrity = AsyncMock(return_value={"errors": 2})
        with pytest.raises(DatabaseError):
            await migrator._enable_dual_read()

    @pytest.mark.asyncio
    async def test_cutover_calls_validate_when_enabled(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig(enable_validation=True))
        migrator._validate_migration = AsyncMock()
        await migrator._cutover()
        migrator._validate_migration.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verify_connections_postgres_disconnected_and_sqlite_error(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig())
        migrator._postgres = MagicMock()
        migrator._postgres.health_check = AsyncMock(return_value={"connected": False})
        migrator._sqlite_conn = MagicMock()
        with pytest.raises(DatabaseError, match="PostgreSQL connection failed"):
            await migrator._verify_connections()

        migrator._postgres.health_check = AsyncMock(return_value={"connected": True})
        bad_cursor = MagicMock()
        bad_cursor.execute.side_effect = sqlite3.Error("bad sqlite")
        migrator._sqlite_conn.cursor.return_value = bad_cursor
        with pytest.raises(DatabaseError, match="SQLite connection failed"):
            await migrator._verify_connections()

    @pytest.mark.asyncio
    async def test_copy_table_zero_and_batched_rows(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig(batch_size=2))
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        assert await migrator._copy_table("t", cursor) == 0

        cursor = MagicMock()
        cursor.fetchone.return_value = (5,)
        cursor.fetchall.side_effect = [[(1,), (2,)], [(3,), (4,)], [(5,)]]
        cursor.description = [("id",)]
        assert await migrator._copy_table("t", cursor) == 5

    @pytest.mark.asyncio
    async def test_validate_row_counts_mismatch_and_fetch_exception(self, tmp_path) -> None:
        migrator = DatabaseMigrator(MigrationConfig(sqlite_path=str(tmp_path / "v.db")))
        sqlite_conn = migrator._connect_sqlite()
        cur = sqlite_conn.cursor()
        cur.execute("CREATE TABLE t1 (id INTEGER)")
        cur.execute("INSERT INTO t1 (id) VALUES (1), (2)")
        sqlite_conn.commit()

        migrator._postgres = MagicMock()
        migrator._postgres.fetchval = AsyncMock(side_effect=Exception("missing table"))
        result = await migrator._validate_row_counts()
        assert result["total_rows"] == 2
        assert result["mismatches"] == 1
        assert result["tables"]["t1"]["postgres"] == 0
        sqlite_conn.close()

    @pytest.mark.asyncio
    async def test_validate_migration_raises_on_integrity_errors(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig())
        migrator._validate_row_counts = AsyncMock(return_value={"total_rows": 7})
        migrator._validate_data_integrity = AsyncMock(return_value={"errors": 1})
        with pytest.raises(DatabaseError):
            await migrator._validate_migration()
        assert migrator.metrics.rows_validated == 7
        assert migrator.metrics.validation_errors == 1

    @pytest.mark.asyncio
    async def test_run_migration_wrapper_uses_migrator(self) -> None:
        cfg = MigrationConfig(enable_dual_write=False, enable_validation=False)
        expected = MigrationMetrics(phase=MigrationPhase.COMPLETED)
        with patch("mahavishnu.core.migrator.DatabaseMigrator") as migrator_cls:
            instance = migrator_cls.return_value
            instance.migrate = AsyncMock(return_value=expected)
            result = await run_migration(cfg)
        assert result is expected
        migrator_cls.assert_called_once_with(cfg)

    @pytest.mark.asyncio
    async def test_enable_dual_write_and_validate_data_integrity_default(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig())
        migrator._connect_postgres = AsyncMock()
        migrator._connect_sqlite = MagicMock()
        migrator._verify_connections = AsyncMock()
        migrator._copy_sqlite_to_postgres = AsyncMock()
        await migrator._enable_dual_write()
        migrator._connect_postgres.assert_awaited_once()
        migrator._connect_sqlite.assert_called_once()
        migrator._verify_connections.assert_awaited_once()
        migrator._copy_sqlite_to_postgres.assert_awaited_once()

        result = await migrator._validate_data_integrity()
        assert result["errors"] == 0
        assert result["sample_size"] == migrator.config.validation_sample_size

    @pytest.mark.asyncio
    async def test_cleanup_and_cleanup_connections_and_rollback_branches(self, tmp_path) -> None:
        migrator = DatabaseMigrator(MigrationConfig(sqlite_path=str(tmp_path / "a.db")))
        sqlite_conn = migrator._connect_sqlite()
        migrator._sqlite_conn = sqlite_conn
        await migrator._cleanup()
        assert migrator._sqlite_conn is None

        migrator._postgres = MagicMock()
        migrator._postgres.disconnect = AsyncMock()
        postgres = migrator._postgres
        migrator._sqlite_conn = sqlite3.connect(str(tmp_path / "b.db"))
        await migrator._cleanup_connections()
        postgres.disconnect.assert_awaited_once()
        assert migrator._postgres is None
        assert migrator._sqlite_conn is None

        migrator._postgres = MagicMock()
        migrator._postgres.disconnect = AsyncMock()
        postgres_rollback = migrator._postgres
        await migrator._rollback()
        assert migrator.current_phase == MigrationPhase.ROLLED_BACK
        postgres_rollback.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_verify_connections_success_and_copy_sqlite_to_postgres(self, tmp_path) -> None:
        migrator = DatabaseMigrator(MigrationConfig(sqlite_path=str(tmp_path / "c.db")))
        sqlite_conn = migrator._connect_sqlite()
        cur = sqlite_conn.cursor()
        cur.execute("CREATE TABLE t1 (id INTEGER)")
        cur.execute("INSERT INTO t1 (id) VALUES (1), (2), (3)")
        sqlite_conn.commit()

        migrator._sqlite_conn = sqlite_conn
        migrator._postgres = MagicMock()
        migrator._postgres.health_check = AsyncMock(return_value={"connected": True})

        await migrator._verify_connections()

        migrator._copy_table = AsyncMock(side_effect=[3])
        await migrator._copy_sqlite_to_postgres()
        assert migrator.metrics.rows_migrated == 3
        sqlite_conn.close()

    @pytest.mark.asyncio
    async def test_copy_table_breaks_when_fetchall_empty(self) -> None:
        migrator = DatabaseMigrator(MigrationConfig(batch_size=2))
        cursor = MagicMock()
        cursor.fetchone.return_value = (2,)
        cursor.fetchall.side_effect = [[]]
        assert await migrator._copy_table("t", cursor) == 0

    @pytest.mark.asyncio
    async def test_migrate_with_validation_enabled_and_validate_success_path(self) -> None:
        migrator = DatabaseMigrator(
            MigrationConfig(enable_dual_write=False, enable_validation=True)
        )
        migrator._run_phase = AsyncMock()
        migrator._validate_migration = AsyncMock()
        migrator._cleanup_connections = AsyncMock()
        await migrator.migrate()
        migrator._validate_migration.assert_awaited_once()

        # Hit _enable_dual_read success branch with validation disabled
        migrator_no_validation = DatabaseMigrator(MigrationConfig(enable_validation=False))
        await migrator_no_validation._enable_dual_read()

        # Hit validation "passed" line
        migrator_ok = DatabaseMigrator(MigrationConfig())
        migrator_ok._validate_row_counts = AsyncMock(return_value={"total_rows": 5})
        migrator_ok._validate_data_integrity = AsyncMock(return_value={"errors": 0})
        await migrator_ok._validate_migration()
