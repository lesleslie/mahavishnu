"""Tests for PostgreSQL Database Module.

Tests cover:
- Configuration loading
- Connection management
- Pool metrics
- Health checking
- Query execution

Note: Integration tests with actual PostgreSQL are in tests/integration/
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.core.database import (
    Database,
    DatabaseConfig,
    DatabaseStatus,
    PoolMetrics,
    get_database,
    close_database,
)


class TestDatabaseConfig:
    """Test database configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = DatabaseConfig()

        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "mahavishnu"
        assert config.user == "mahavishnu"
        assert config.min_pool_size == 2
        assert config.max_pool_size == 10
        assert config.connection_timeout == 30.0
        assert config.ssl_mode == "prefer"

    def test_config_from_env(self) -> None:
        """Test configuration from environment variables."""
        env_vars = {
            "MAHAVISHNU_DB_HOST": "db.example.com",
            "MAHAVISHNU_DB_PORT": "5433",
            "MAHAVISHNU_DB_NAME": "test_db",
            "MAHAVISHNU_DB_USER": "test_user",
            "MAHAVISHNU_DB_PASSWORD": "secret",
            "MAHAVISHNU_DB_MIN_POOL_SIZE": "5",
            "MAHAVISHNU_DB_MAX_POOL_SIZE": "20",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            config = DatabaseConfig.from_env()

            assert config.host == "db.example.com"
            assert config.port == 5433
            assert config.database == "test_db"
            assert config.user == "test_user"
            assert config.password == "secret"
            assert config.min_pool_size == 5
            assert config.max_pool_size == 20

    def test_get_dsn_with_password(self) -> None:
        """Test DSN generation with password."""
        config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="mahavishnu",
            user="admin",
            password="secret123",
        )

        dsn = config.get_dsn(include_password=True)

        assert dsn == "postgresql://admin:secret123@localhost:5432/mahavishnu"

    def test_get_dsn_without_password(self) -> None:
        """Test DSN generation without password."""
        config = DatabaseConfig(
            host="localhost",
            port=5432,
            database="mahavishnu",
            user="admin",
            password="secret123",
        )

        dsn = config.get_dsn(include_password=False)

        assert dsn == "postgresql://admin@localhost:5432/mahavishnu"

    def test_get_dsn_empty_password(self) -> None:
        """Test DSN generation with empty password."""
        config = DatabaseConfig(password="")

        dsn = config.get_dsn(include_password=True)

        assert ":@" not in dsn  # No empty password in DSN


class TestPoolMetrics:
    """Test pool metrics."""

    def test_to_dict(self) -> None:
        """Test metrics serialization."""
        metrics = PoolMetrics(
            size=5,
            min_size=2,
            max_size=10,
            idle_count=3,
            active_count=2,
            waiting_count=0,
        )

        result = metrics.to_dict()

        assert result["size"] == 5
        assert result["min_size"] == 2
        assert result["max_size"] == 10
        assert result["idle_count"] == 3
        assert result["active_count"] == 2


class TestDatabase:
    """Test database manager."""

    def test_initialization(self) -> None:
        """Test database manager initialization."""
        config = DatabaseConfig(host="testhost")
        db = Database(config)

        assert db.config.host == "testhost"
        assert db.status == DatabaseStatus.DISCONNECTED
        assert db._pool is None

    def test_initialization_default_config(self) -> None:
        """Test database manager with default config."""
        db = Database()

        assert db.config is not None
        assert db.config.host == "localhost"

    def test_pool_raises_when_not_initialized(self) -> None:
        """Test that accessing pool raises when not initialized."""
        db = Database()

        with pytest.raises(Exception):  # DatabaseError
            _ = db.pool

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self) -> None:
        """Test that connect creates connection pool."""
        config = DatabaseConfig()
        db = Database(config)

        # Mock asyncpg.create_pool - note that pool methods are synchronous
        mock_pool = MagicMock()  # Not AsyncMock - pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            await db.connect()

            assert db.status == DatabaseStatus.CONNECTED
            assert db._pool is mock_pool
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_is_idempotent(self) -> None:
        """Test that calling connect twice is safe."""
        config = DatabaseConfig()
        db = Database(config)

        mock_pool = MagicMock()  # Not AsyncMock - pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            await db.connect()
            await db.connect()  # Second call

            # Should only create pool once
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self) -> None:
        """Test that disconnect closes the pool."""
        config = DatabaseConfig()
        db = Database(config)

        mock_pool = MagicMock()  # Not AsyncMock - pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            await db.connect()

        await db.disconnect()

        assert db.status == DatabaseStatus.DISCONNECTED
        assert db._pool is None
        mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_is_safe_when_not_connected(self) -> None:
        """Test that disconnect is safe when not connected."""
        db = Database()

        # Should not raise
        await db.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self) -> None:
        """Test health check when disconnected."""
        db = Database()

        health = await db.health_check()

        assert health["status"] == "disconnected"
        assert health["connected"] is False

    @pytest.mark.asyncio
    async def test_health_check_connected(self) -> None:
        """Test health check when connected."""
        config = DatabaseConfig()
        db = Database(config)

        mock_pool = MagicMock()  # Not AsyncMock - pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.fetchval = AsyncMock(return_value=1)
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool
            await db.connect()

        health = await db.health_check()

        assert health["status"] == "connected"
        assert health["connected"] is True
        assert health["query_test"] is True
        assert "metrics" in health


class TestDatabaseQueries:
    """Test database query methods."""

    @pytest.fixture
    def mock_db(self) -> Database:
        """Create a database with mocked pool."""
        config = DatabaseConfig()
        db = Database(config)

        mock_pool = MagicMock()  # Pool methods are sync, connection methods are async
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2

        # Mock connection context manager
        mock_conn = AsyncMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire

        db._pool = mock_pool
        db._status = DatabaseStatus.CONNECTED

        return db

    @pytest.mark.asyncio
    async def test_execute(self, mock_db: Database) -> None:
        """Test execute method."""
        # The connection is already mocked in the fixture
        async with mock_db.connection() as conn:
            conn.execute = AsyncMock(return_value="INSERT 0 1")
            result = await conn.execute("INSERT INTO tasks (title) VALUES ($1)", "Test")
            assert result == "INSERT 0 1"

    @pytest.mark.asyncio
    async def test_fetch(self, mock_db: Database) -> None:
        """Test fetch method."""
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: f"value_{key}"

        async with mock_db.connection() as conn:
            conn.fetch = AsyncMock(return_value=[mock_record])
            result = await conn.fetch("SELECT * FROM tasks")
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetchrow(self, mock_db: Database) -> None:
        """Test fetchrow method."""
        mock_record = MagicMock()

        async with mock_db.connection() as conn:
            conn.fetchrow = AsyncMock(return_value=mock_record)
            result = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", "123")
            assert result is not None

    @pytest.mark.asyncio
    async def test_fetchval(self, mock_db: Database) -> None:
        """Test fetchval method."""
        async with mock_db.connection() as conn:
            conn.fetchval = AsyncMock(return_value=42)
            result = await conn.fetchval("SELECT count(*) FROM tasks")
            assert result == 42


class TestDatabaseSingleton:
    """Test database singleton functions."""

    @pytest.mark.asyncio
    async def test_get_database_creates_singleton(self) -> None:
        """Test that get_database creates singleton."""
        # Reset singleton
        await close_database()

        mock_pool = MagicMock()  # Pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            db1 = await get_database()
            db2 = await get_database()

            assert db1 is db2

        await close_database()

    @pytest.mark.asyncio
    async def test_close_database(self) -> None:
        """Test closing database singleton."""
        mock_pool = MagicMock()  # Pool methods are sync
        mock_pool.get_size.return_value = 2
        mock_pool.get_min_size.return_value = 2
        mock_pool.get_max_size.return_value = 10
        mock_pool.get_idle_size.return_value = 2
        mock_pool.close = AsyncMock()

        with patch("mahavishnu.core.database.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_pool

            db = await get_database()
            assert db.status == DatabaseStatus.CONNECTED

            await close_database()
            assert db.status == DatabaseStatus.DISCONNECTED
