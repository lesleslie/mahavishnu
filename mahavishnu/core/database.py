"""PostgreSQL Database Module for Mahavishnu Task Orchestration.

Provides async database operations with:
- Connection pooling via asyncpg
- Transaction management
- Health checking
- Metrics collection

Usage:
    from mahavishnu.core.database import Database, get_database

    db = await get_database()
    async with db.transaction() as conn:
        result = await conn.fetch("SELECT * FROM tasks")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import asyncpg
from asyncpg import Pool, Connection
from asyncpg.exceptions import PostgresError

from mahavishnu.core.errors import DatabaseError, MahavishnuError

logger = logging.getLogger(__name__)


class DatabaseStatus(str, Enum):
    """Database connection status."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class DatabaseConfig:
    """Database configuration.

    Configuration can be provided via:
    1. Direct initialization
    2. Environment variables (MAHAVISHNU_DB_*)
    3. Oneiric settings
    """

    host: str = "localhost"
    port: int = 5432
    database: str = "mahavishnu"
    user: str = "mahavishnu"
    password: str = ""
    min_pool_size: int = 2
    max_pool_size: int = 10
    connection_timeout: float = 30.0
    command_timeout: float = 60.0
    ssl_mode: str = "prefer"  # disable, prefer, require

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Create configuration from environment variables."""
        return cls(
            host=os.getenv("MAHAVISHNU_DB_HOST", "localhost"),
            port=int(os.getenv("MAHAVISHNU_DB_PORT", "5432")),
            database=os.getenv("MAHAVISHNU_DB_NAME", "mahavishnu"),
            user=os.getenv("MAHAVISHNU_DB_USER", "mahavishnu"),
            password=os.getenv("MAHAVISHNU_DB_PASSWORD", ""),
            min_pool_size=int(os.getenv("MAHAVISHNU_DB_MIN_POOL_SIZE", "2")),
            max_pool_size=int(os.getenv("MAHAVISHNU_DB_MAX_POOL_SIZE", "10")),
            connection_timeout=float(os.getenv("MAHAVISHNU_DB_TIMEOUT", "30.0")),
            command_timeout=float(os.getenv("MAHAVISHNU_DB_COMMAND_TIMEOUT", "60.0")),
            ssl_mode=os.getenv("MAHAVISHNU_DB_SSL_MODE", "prefer"),
        )

    def get_dsn(self, include_password: bool = True) -> str:
        """Get database connection string.

        Args:
            include_password: Whether to include password in DSN

        Returns:
            PostgreSQL connection string
        """
        password_part = f":{self.password}" if include_password and self.password else ""
        return f"postgresql://{self.user}{password_part}@{self.host}:{self.port}/{self.database}"


@dataclass
class PoolMetrics:
    """Connection pool metrics."""

    size: int = 0
    min_size: int = 0
    max_size: int = 0
    idle_count: int = 0
    active_count: int = 0
    waiting_count: int = 0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "size": self.size,
            "min_size": self.min_size,
            "max_size": self.max_size,
            "idle_count": self.idle_count,
            "active_count": self.active_count,
            "waiting_count": self.waiting_count,
            "last_updated": self.last_updated,
        }


class Database:
    """Async PostgreSQL database manager with connection pooling.

    Features:
    - Connection pooling via asyncpg
    - Transaction management with context managers
    - Automatic reconnection on errors
    - Health checking
    - Metrics collection

    Example:
        db = Database(config)
        await db.connect()

        async with db.transaction() as conn:
            await conn.execute("INSERT INTO tasks (...) VALUES (...)")

        await db.disconnect()
    """

    def __init__(self, config: DatabaseConfig | None = None):
        """Initialize database manager.

        Args:
            config: Database configuration. If None, uses environment variables.
        """
        self.config = config or DatabaseConfig.from_env()
        self._pool: Pool | None = None
        self._status = DatabaseStatus.DISCONNECTED
        self._metrics = PoolMetrics()
        self._lock = asyncio.Lock()

    @property
    def status(self) -> DatabaseStatus:
        """Get current database status."""
        return self._status

    @property
    def pool(self) -> Pool:
        """Get connection pool.

        Raises:
            DatabaseError: If pool is not initialized
        """
        if self._pool is None:
            raise DatabaseError(
                "Database pool not initialized",
                details={"status": self._status.value},
            )
        return self._pool

    async def connect(self) -> None:
        """Establish database connection pool.

        Raises:
            DatabaseError: If connection fails
        """
        async with self._lock:
            if self._pool is not None:
                logger.debug("Database pool already connected")
                return

            self._status = DatabaseStatus.CONNECTING
            logger.info(f"Connecting to database: {self.config.host}:{self.config.port}")

            try:
                # Build SSL configuration
                ssl_config = self._get_ssl_config()

                self._pool = await asyncio.wait_for(
                    asyncpg.create_pool(
                        host=self.config.host,
                        port=self.config.port,
                        database=self.config.database,
                        user=self.config.user,
                        password=self.config.password,
                        min_size=self.config.min_pool_size,
                        max_size=self.config.max_pool_size,
                        timeout=self.config.connection_timeout,
                        command_timeout=self.config.command_timeout,
                        ssl=ssl_config,
                    ),
                    timeout=self.config.connection_timeout + 5,
                )

                self._status = DatabaseStatus.CONNECTED
                self._update_metrics()
                logger.info(f"Database connected with pool size {self.config.min_pool_size}-{self.config.max_pool_size}")

            except asyncio.TimeoutError as e:
                self._status = DatabaseStatus.ERROR
                raise DatabaseError(
                    "Database connection timeout",
                    details={"timeout": self.config.connection_timeout},
                ) from e
            except PostgresError as e:
                self._status = DatabaseStatus.ERROR
                raise DatabaseError(
                    f"Database connection failed: {e}",
                    details={"error": str(e)},
                ) from e
            except Exception as e:
                self._status = DatabaseStatus.ERROR
                raise DatabaseError(
                    f"Unexpected database error: {e}",
                    details={"error": str(e)},
                ) from e

    def _get_ssl_config(self) -> Any:
        """Get SSL configuration based on ssl_mode."""
        import ssl

        if self.config.ssl_mode == "disable":
            return False
        elif self.config.ssl_mode == "require":
            # Require SSL but don't verify certificate
            return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            return ssl_context
        else:  # prefer
            # Prefer SSL but allow fallback
            return True

    async def disconnect(self) -> None:
        """Close database connection pool."""
        async with self._lock:
            if self._pool is None:
                return

            logger.info("Disconnecting from database")
            try:
                await self._pool.close()
            except Exception as e:
                logger.warning(f"Error closing database pool: {e}")
            finally:
                self._pool = None
                self._status = DatabaseStatus.DISCONNECTED
                self._metrics = PoolMetrics()

    async def health_check(self) -> dict[str, Any]:
        """Perform database health check.

        Returns:
            Dictionary with health status and metrics
        """
        health: dict[str, Any] = {
            "status": self._status.value,
            "connected": self._status == DatabaseStatus.CONNECTED,
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "database": self.config.database,
            },
        }

        if self._pool is not None:
            try:
                # Test query
                async with asyncio.timeout(5.0):
                    result = await self._pool.fetchval("SELECT 1")
                    health["query_test"] = result == 1
            except Exception as e:
                health["query_test"] = False
                health["error"] = str(e)

            # Update metrics
            self._update_metrics()
            health["metrics"] = self._metrics.to_dict()

        return health

    def _update_metrics(self) -> None:
        """Update pool metrics."""
        if self._pool is None:
            return

        self._metrics = PoolMetrics(
            size=self._pool.get_size(),
            min_size=self._pool.get_min_size(),
            max_size=self._pool.get_max_size(),
            idle_count=self._pool.get_idle_size(),
            active_count=self._pool.get_size() - self._pool.get_idle_size(),
            waiting_count=0,  # asyncpg doesn't expose this directly
            last_updated=time.time(),
        )

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Connection]:
        """Get a connection from the pool.

        Yields:
            Database connection

        Raises:
            DatabaseError: If connection cannot be acquired
        """
        if self._pool is None:
            await self.connect()

        async with self.pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Start a transaction.

        Yields:
            Database connection with active transaction

        Raises:
            DatabaseError: If transaction fails
        """
        async with self.connection() as conn:
            async with conn.transaction():
                yield conn

    async def execute(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,
    ) -> str:
        """Execute a query and return status.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Query timeout

        Returns:
            Query status string
        """
        async with self.connection() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,
    ) -> list[asyncpg.Record]:
        """Execute a query and return all rows.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Query timeout

        Returns:
            List of records
        """
        async with self.connection() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
        timeout: float | None = None,
    ) -> asyncpg.Record | None:
        """Execute a query and return first row.

        Args:
            query: SQL query
            *args: Query parameters
            timeout: Query timeout

        Returns:
            First record or None
        """
        async with self.connection() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self,
        query: str,
        *args: Any,
        column: int = 0,
        timeout: float | None = None,
    ) -> Any:
        """Execute a query and return single value.

        Args:
            query: SQL query
            *args: Query parameters
            column: Column index
            timeout: Query timeout

        Returns:
            Single value
        """
        async with self.connection() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)


# Singleton instance
_database: Database | None = None


async def get_database(config: DatabaseConfig | None = None) -> Database:
    """Get or create the database singleton.

    Args:
        config: Database configuration. Only used on first call.

    Returns:
        Database instance
    """
    global _database
    if _database is None:
        _database = Database(config)
        await _database.connect()
    return _database


async def close_database() -> None:
    """Close the database singleton."""
    global _database
    if _database is not None:
        await _database.disconnect()
        _database = None
