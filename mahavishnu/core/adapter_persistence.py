"""Adapter persistence layer for HybridAdapterRegistry.

This module implements the persistence layer for adapter state and health history,
using SQLite for local storage with a stub for future Dhruva MCP integration.

Key responsibilities:
- Persist adapter state (enabled/disabled, preferences)
- Store health history for trend analysis
- Provide ACID transactions for state consistency

Storage Architecture:
- Local SQLite (current): aiosqlite for async operations
- Dhruva MCP (future): Distributed state via MCP protocol at localhost:8683

Created: 2026-02-22
Version: 1.0
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any, cast

import aiosqlite

from .errors import ErrorCode, MahavishnuError
from .paths import ensure_directories, get_data_path

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class PersistenceError(MahavishnuError):
    """Error raised when persistence operations fail."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            ErrorCode.DATABASE_CONNECTION_ERROR,
            details=details,
        )


class AdapterStateError(PersistenceError):
    """Error raised when adapter state operations fail."""

    def __init__(
        self,
        adapter_id: str,
        operation: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"Adapter state {operation} failed for '{adapter_id}': {reason}",
            details={
                "adapter_id": adapter_id,
                "operation": operation,
                "reason": reason,
                **(details or {}),
            },
        )


class HealthRecordError(PersistenceError):
    """Error raised when health record operations fail."""

    def __init__(
        self,
        adapter_id: str,
        operation: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            f"Health record {operation} failed for '{adapter_id}': {reason}",
            details={
                "adapter_id": adapter_id,
                "operation": operation,
                "reason": reason,
                **(details or {}),
            },
        )


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AdapterState:
    """Persistent state for an orchestrator adapter.

    Attributes:
        adapter_id: Unique identifier for the adapter (e.g., "prefect", "agno", "llamaindex")
        enabled: Whether the adapter is currently enabled for routing
        preference_score: Routing preference score (0.0-1.0, higher = more preferred)
        last_successful_execution: Timestamp of last successful execution (None if never)
        consecutive_failures: Number of consecutive execution failures
        metadata: Additional adapter-specific metadata (config, capabilities, etc.)
        updated_at: Timestamp of last state update
    """

    adapter_id: str
    enabled: bool = True
    preference_score: float = 0.5
    last_successful_execution: datetime | None = None
    consecutive_failures: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for storage.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "adapter_id": self.adapter_id,
            "enabled": self.enabled,
            "preference_score": self.preference_score,
            "last_successful_execution": (
                self.last_successful_execution.isoformat()
                if self.last_successful_execution
                else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "metadata": json.dumps(self.metadata),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdapterState":
        """Create state from dictionary (loaded from storage).

        Args:
            data: Dictionary loaded from storage.

        Returns:
            AdapterState instance.
        """
        last_success = data.get("last_successful_execution")
        # Parse metadata, handling both JSON string and dict formats
        metadata_raw = data.get("metadata", {})
        if isinstance(metadata_raw, str):
            metadata: dict[str, Any] = cast("dict[str, Any]", json.loads(metadata_raw))
        else:
            metadata = cast("dict[str, Any]", metadata_raw)

        return cls(
            adapter_id=data["adapter_id"],
            enabled=bool(data["enabled"]),
            preference_score=float(data["preference_score"]),
            last_successful_execution=datetime.fromisoformat(last_success)
            if last_success
            else None,
            consecutive_failures=int(data["consecutive_failures"]),
            metadata=metadata,
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def __post_init__(self) -> None:
        """Validate state after initialization."""
        if not 0.0 <= self.preference_score <= 1.0:
            raise ValueError(
                f"preference_score must be between 0.0 and 1.0, got {self.preference_score}"
            )
        if self.consecutive_failures < 0:
            raise ValueError(
                f"consecutive_failures must be non-negative, got {self.consecutive_failures}"
            )


@dataclass
class HealthRecord:
    """Health check record for an adapter.

    Attributes:
        adapter_id: Unique identifier for the adapter
        timestamp: When the health check was performed
        healthy: Whether the adapter is healthy
        latency_ms: Response latency in milliseconds (None if check failed)
        error_message: Error message if unhealthy (None if healthy)
        details: Additional health check details (metrics, diagnostics, etc.)
    """

    adapter_id: str
    timestamp: datetime
    healthy: bool
    latency_ms: float | None = None
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary for storage.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "adapter_id": self.adapter_id,
            "timestamp": self.timestamp.isoformat(),
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "details": json.dumps(self.details),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HealthRecord":
        """Create record from dictionary (loaded from storage).

        Args:
            data: Dictionary loaded from storage.

        Returns:
            HealthRecord instance.
        """
        # Parse details, handling both JSON string and dict formats
        details_raw = data.get("details", {})
        if isinstance(details_raw, str):
            details: dict[str, Any] = cast("dict[str, Any]", json.loads(details_raw))
        else:
            details = cast("dict[str, Any]", details_raw)

        return cls(
            adapter_id=data["adapter_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            healthy=bool(data["healthy"]),
            latency_ms=float(data["latency_ms"]) if data.get("latency_ms") is not None else None,
            error_message=data.get("error_message"),
            details=details,
        )


# =============================================================================
# Persistence Layer
# =============================================================================


class AdapterPersistenceLayer:
    """Persistence layer for adapter state and health history.

    This class provides async SQLite storage for adapter state with a
    placeholder for future Dhruva MCP integration.

    Features:
    - ACID transactions via SQLite
    - Async operations with aiosqlite
    - Health history with configurable retention
    - Automatic cleanup of old health records

    Example:
        >>> persistence = AdapterPersistenceLayer()
        >>> await persistence.initialize()
        >>> state = AdapterState(adapter_id="prefect", enabled=True, preference_score=0.8)
        >>> await persistence.save_state(state)
        >>> loaded = await persistence.load_state("prefect")
        >>> await persistence.close()
    """

    # SQL schema version for migrations
    SCHEMA_VERSION = 1

    # Default health history retention (days)
    DEFAULT_HEALTH_RETENTION_DAYS = 30

    def __init__(self, storage_path: str | None = None) -> None:
        """Initialize the persistence layer.

        Args:
            storage_path: Path to SQLite database file. If None, uses XDG-compliant path.
        """
        if storage_path is None:
            ensure_directories()
            storage_path = str(get_data_path("adapter_persistence.db"))

        self.storage_path = Path(storage_path)
        self._db: aiosqlite.Connection | None = None
        self._initialized = False

        # Future: Dhruva MCP client stub
        # self._dhruva_client: DhruvaClient | None = None
        # self._dhruva_url = "http://localhost:8683/mcp"

        logger.debug(f"AdapterPersistenceLayer initialized with path: {self.storage_path}")

    async def initialize(self) -> None:
        """Create database tables if needed.

        This method is idempotent - calling it multiple times has no effect
        after the first initialization.

        Raises:
            PersistenceError: If database initialization fails.
        """
        if self._initialized:
            return

        try:
            self._db = await aiosqlite.connect(self.storage_path)

            # Enable WAL mode for better concurrent access
            await self._db.execute("PRAGMA journal_mode=WAL")

            # Create adapter_state table
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS adapter_state (
                    adapter_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    preference_score REAL NOT NULL DEFAULT 0.5,
                    last_successful_execution TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    CHECK (preference_score >= 0.0 AND preference_score <= 1.0),
                    CHECK (consecutive_failures >= 0)
                )
            """)

            # Create health_history table
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS health_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    adapter_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    healthy INTEGER NOT NULL,
                    latency_ms REAL,
                    error_message TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (adapter_id) REFERENCES adapter_state(adapter_id)
                )
            """)

            # Create indexes for efficient queries
            await self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_health_adapter_id
                ON health_history(adapter_id)
            """)

            await self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_health_timestamp
                ON health_history(timestamp DESC)
            """)

            # Create schema version table
            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

            # Record schema version
            await self._db.execute(
                "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
                (self.SCHEMA_VERSION,),
            )

            await self._db.commit()
            self._initialized = True

            logger.info(f"AdapterPersistenceLayer initialized: {self.storage_path}")

        except Exception as e:
            logger.error(f"Failed to initialize persistence layer: {e}")
            raise PersistenceError(
                f"Failed to initialize database at {self.storage_path}",
                details={"original_error": str(e)},
            ) from e

    async def _ensure_initialized(self) -> None:
        """Ensure the database is initialized before operations."""
        if not self._initialized or self._db is None:
            await self.initialize()

    async def save_state(self, state: AdapterState) -> None:
        """Persist adapter state.

        Uses UPSERT (INSERT OR REPLACE) to handle both insert and update cases.

        Args:
            state: Adapter state to persist.

        Raises:
            AdapterStateError: If the save operation fails.
        """
        await self._ensure_initialized()
        assert self._db is not None  # Type guard after _ensure_initialized

        try:
            data = state.to_dict()
            await self._db.execute(
                """
                INSERT OR REPLACE INTO adapter_state (
                    adapter_id, enabled, preference_score,
                    last_successful_execution, consecutive_failures,
                    metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["adapter_id"],
                    int(data["enabled"]),
                    data["preference_score"],
                    data["last_successful_execution"],
                    data["consecutive_failures"],
                    data["metadata"],
                    data["updated_at"],
                ),
            )
            await self._db.commit()

            logger.debug(f"Saved state for adapter '{state.adapter_id}': enabled={state.enabled}")

            # Future: Sync to Dhruva MCP
            # await self._sync_to_dhruva("adapter_state", data)

        except Exception as e:
            logger.error(f"Failed to save state for adapter '{state.adapter_id}': {e}")
            raise AdapterStateError(
                adapter_id=state.adapter_id,
                operation="save",
                reason=str(e),
            ) from e

    async def load_state(self, adapter_id: str) -> AdapterState | None:
        """Load adapter state by ID.

        Args:
            adapter_id: Unique identifier for the adapter.

        Returns:
            AdapterState if found, None otherwise.

        Raises:
            AdapterStateError: If the load operation fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        try:
            async with self._db.execute(
                """
                SELECT adapter_id, enabled, preference_score,
                       last_successful_execution, consecutive_failures,
                       metadata, updated_at
                FROM adapter_state
                WHERE adapter_id = ?
                """,
                (adapter_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                return None

            return AdapterState.from_dict(
                {
                    "adapter_id": row[0],
                    "enabled": row[1],
                    "preference_score": row[2],
                    "last_successful_execution": row[3],
                    "consecutive_failures": row[4],
                    "metadata": row[5],
                    "updated_at": row[6],
                }
            )

        except Exception as e:
            logger.error(f"Failed to load state for adapter '{adapter_id}': {e}")
            raise AdapterStateError(
                adapter_id=adapter_id,
                operation="load",
                reason=str(e),
            ) from e

    async def load_all_states(self) -> dict[str, AdapterState]:
        """Load all adapter states.

        Returns:
            Dictionary mapping adapter_id to AdapterState.

        Raises:
            AdapterStateError: If the load operation fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        try:
            states: dict[str, AdapterState] = {}

            async with self._db.execute("""
                SELECT adapter_id, enabled, preference_score,
                       last_successful_execution, consecutive_failures,
                       metadata, updated_at
                FROM adapter_state
            """) as cursor:
                async for row in cursor:
                    state = AdapterState.from_dict(
                        {
                            "adapter_id": row[0],
                            "enabled": row[1],
                            "preference_score": row[2],
                            "last_successful_execution": row[3],
                            "consecutive_failures": row[4],
                            "metadata": row[5],
                            "updated_at": row[6],
                        }
                    )
                    states[state.adapter_id] = state

            logger.debug(f"Loaded {len(states)} adapter states")
            return states

        except Exception as e:
            logger.error(f"Failed to load all adapter states: {e}")
            raise AdapterStateError(
                adapter_id="*",
                operation="load_all",
                reason=str(e),
            ) from e

    async def record_health(self, record: HealthRecord) -> None:
        """Store a health check record.

        Args:
            record: Health record to store.

        Raises:
            HealthRecordError: If the record operation fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        try:
            data = record.to_dict()
            await self._db.execute(
                """
                INSERT INTO health_history (
                    adapter_id, timestamp, healthy, latency_ms, error_message, details
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["adapter_id"],
                    data["timestamp"],
                    int(data["healthy"]),
                    data["latency_ms"],
                    data["error_message"],
                    data["details"],
                ),
            )
            await self._db.commit()

            logger.debug(
                f"Recorded health for adapter '{record.adapter_id}': "
                f"healthy={record.healthy}, latency={record.latency_ms}ms"
            )

            # Future: Sync to Dhruva MCP
            # await self._sync_to_dhruva("health_history", data)

        except Exception as e:
            logger.error(f"Failed to record health for adapter '{record.adapter_id}': {e}")
            raise HealthRecordError(
                adapter_id=record.adapter_id,
                operation="record",
                reason=str(e),
            ) from e

    async def get_health_history(
        self,
        adapter_id: str,
        limit: int = 100,
    ) -> list[HealthRecord]:
        """Get health history for an adapter.

        Results are ordered by timestamp descending (most recent first).

        Args:
            adapter_id: Unique identifier for the adapter.
            limit: Maximum number of records to return (default: 100).

        Returns:
            List of health records, most recent first.

        Raises:
            HealthRecordError: If the query fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        try:
            records: list[HealthRecord] = []

            async with self._db.execute(
                """
                SELECT adapter_id, timestamp, healthy, latency_ms, error_message, details
                FROM health_history
                WHERE adapter_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (adapter_id, limit),
            ) as cursor:
                async for row in cursor:
                    record = HealthRecord.from_dict(
                        {
                            "adapter_id": row[0],
                            "timestamp": row[1],
                            "healthy": row[2],
                            "latency_ms": row[3],
                            "error_message": row[4],
                            "details": row[5],
                        }
                    )
                    records.append(record)

            logger.debug(f"Loaded {len(records)} health records for adapter '{adapter_id}'")
            return records

        except Exception as e:
            logger.error(f"Failed to get health history for adapter '{adapter_id}': {e}")
            raise HealthRecordError(
                adapter_id=adapter_id,
                operation="get_history",
                reason=str(e),
            ) from e

    async def cleanup_old_health_records(
        self,
        retention_days: int | None = None,
    ) -> int:
        """Remove health records older than retention period.

        Args:
            retention_days: Number of days to retain records. Default: 30 days.

        Returns:
            Number of records deleted.

        Raises:
            HealthRecordError: If the cleanup fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        retention = retention_days or self.DEFAULT_HEALTH_RETENTION_DAYS

        try:
            cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_str = cutoff.isoformat()

            cursor = await self._db.execute(
                """
                DELETE FROM health_history
                WHERE timestamp < ?
                """,
                (cutoff_str,),
            )
            await self._db.commit()

            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(
                    f"Cleaned up {deleted} old health records (older than {retention} days)"
                )

            return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup old health records: {e}")
            raise HealthRecordError(
                adapter_id="*",
                operation="cleanup",
                reason=str(e),
            ) from e

    async def delete_state(self, adapter_id: str) -> bool:
        """Delete adapter state.

        Note: This does NOT delete associated health records (they are kept for
        historical analysis). Use cleanup_old_health_records to remove old records.

        Args:
            adapter_id: Unique identifier for the adapter.

        Returns:
            True if state was deleted, False if it didn't exist.

        Raises:
            AdapterStateError: If the delete operation fails.
        """
        await self._ensure_initialized()
        assert self._db is not None

        try:
            cursor = await self._db.execute(
                "DELETE FROM adapter_state WHERE adapter_id = ?",
                (adapter_id,),
            )
            await self._db.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted state for adapter '{adapter_id}'")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete state for adapter '{adapter_id}': {e}")
            raise AdapterStateError(
                adapter_id=adapter_id,
                operation="delete",
                reason=str(e),
            ) from e

    async def close(self) -> None:
        """Close the database connection.

        This method is safe to call multiple times.
        """
        if self._db is not None:
            try:
                await self._db.close()
                logger.debug("Closed database connection")
            except Exception as e:
                logger.warning(f"Error closing database: {e}")
            finally:
                self._db = None
                self._initialized = False

    async def __aenter__(self) -> "AdapterPersistenceLayer":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    # =========================================================================
    # Future: Dhruva MCP Integration
    # =========================================================================

    # async def _sync_to_dhruva(self, table: str, data: dict[str, Any]) -> None:
    #     """Sync data to Dhruva MCP server.
    #
    #     Placeholder for future integration with Dhruva MCP at localhost:8683.
    #
    #     Args:
    #         table: Table name (adapter_state or health_history)
    #         data: Record data to sync
    #     """
    #     if self._dhruva_client is None:
    #         return
    #
    #     try:
    #         await self._dhruva_client.call_tool(
    #             "put_persistent_object",
    #             {
    #                 "key": f"mahavishnu/{table}/{data.get('adapter_id', 'unknown')}",
    #                 "value": data,
    #                 "ttl": 86400 * 30,  # 30 days TTL
    #             }
    #         )
    #         logger.debug(f"Synced {table} to Dhruva for adapter '{data.get('adapter_id')}'")
    #     except Exception as e:
    #         logger.warning(f"Failed to sync to Dhruva: {e}")
    #         # Don't raise - local persistence is the source of truth


# =============================================================================
# Module-level convenience functions
# =============================================================================


_persistence_instance: AdapterPersistenceLayer | None = None


async def get_persistence() -> AdapterPersistenceLayer:
    """Get or create the global persistence instance.

    Returns:
        The global AdapterPersistenceLayer instance.
    """
    global _persistence_instance
    if _persistence_instance is None:
        _persistence_instance = AdapterPersistenceLayer()
        await _persistence_instance.initialize()
    return _persistence_instance


async def close_persistence() -> None:
    """Close the global persistence instance if it exists."""
    global _persistence_instance
    if _persistence_instance is not None:
        await _persistence_instance.close()
        _persistence_instance = None


__all__ = [
    # Data classes
    "AdapterState",
    "HealthRecord",
    # Exceptions
    "PersistenceError",
    "AdapterStateError",
    "HealthRecordError",
    # Main class
    "AdapterPersistenceLayer",
    # Convenience functions
    "get_persistence",
    "close_persistence",
]
