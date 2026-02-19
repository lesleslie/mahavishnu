"""Tests for Database Migration Module.

Tests cover:
- Migration configuration
- Phase transitions
- Validation logic
- Rollback handling
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from mahavishnu.core.migrator import (
    DatabaseMigrator,
    MigrationConfig,
    MigrationMetrics,
    MigrationPhase,
    MigrationStatus,
)
from mahavishnu.core.database import DatabaseConfig


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
