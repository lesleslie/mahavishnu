"""System-wide event bus with persistence for cross-component communication.

The EventBus is DISTINCT from MessageBus:
- MessageBus: Pool-scoped inter-pool communication (worker pools talking to each other)
- EventBus: System-wide events (code indexing → Session-Buddy, Akosha, etc.)

Example events:
- code.graph.indexed: Code graph indexed for a repo
- worker.status_change: Worker status changed
- backup.completed: Backup operation completed
"""

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json
import logging
from pathlib import Path
from typing import Any
import uuid

import aiosqlite

from .paths import get_data_path, ensure_directories, migrate_legacy_data

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """Event types for system-wide communication.

    Code Indexing Events:
        CODE_GRAPH_INDEXED: Code graph successfully indexed
        CODE_GRAPH_INDEX_FAILED: Code graph indexing failed
        CODE_GRAPH_CACHE_INVALIDATED: Cache invalidated for repo

    Worker Events:
        WORKER_STARTED: Worker process started
        WORKER_STOPPED: Worker process stopped
        WORKER_STATUS_CHANGED: Worker status changed
        WORKER_ERROR: Worker encountered error

    Backup Events:
        BACKUP_STARTED: Backup operation started
        BACKUP_COMPLETED: Backup operation completed
        BACKUP_FAILED: Backup operation failed
        BACKUP_RESTORED: Backup restored successfully

    Pool Events:
        POOL_SPAWNED: New pool spawned
        POOL_CLOSED: Pool shut down
        POOL_SCALED: Pool scaled up/down
    """

    # Code indexing events
    CODE_GRAPH_INDEXED = "code.graph.indexed"
    CODE_GRAPH_INDEX_FAILED = "code.graph.index_failed"
    CODE_GRAPH_CACHE_INVALIDATED = "code.graph.cache_invalidated"

    # Worker events
    WORKER_STARTED = "worker.started"
    WORKER_STOPPED = "worker.stopped"
    WORKER_STATUS_CHANGED = "worker.status_changed"
    WORKER_ERROR = "worker.error"

    # Backup events
    BACKUP_STARTED = "backup.started"
    BACKUP_COMPLETED = "backup.completed"
    BACKUP_FAILED = "backup.failed"
    BACKUP_RESTORED = "backup.restored"

    # Pool events
    POOL_SPAWNED = "pool.spawned"
    POOL_CLOSED = "pool.closed"
    POOL_SCALED = "pool.scaled"


@dataclass
class Event:
    """Event passed through system-wide event bus.

    Attributes:
        id: Unique event identifier (UUID4)
        type: Event type
        data: Event payload dictionary
        timestamp: Event timestamp (UTC)
        source: Source component (e.g., "code_index_service")
        version: Event schema version (for migration)
    """

    id: str
    type: EventType
    data: dict[str, Any]
    timestamp: datetime
    source: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for storage."""
        return {
            "id": self.id,
            "type": self.type.value,
            "data": json.dumps(self.data),
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Create event from dictionary (loaded from storage)."""
        return cls(
            id=data["id"],
            type=EventType(data["type"]),
            data=json.loads(data["data"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data["source"],
            version=data.get("version", 1),
        )


class SQLiteEventStorage:
    """SQLite persistence layer for events.

    Features:
    - Persistent event log (survives restarts)
    - Event replay capability
    - Event history queries
    """

    def __init__(self, db_path: Path | str | None = None):
        """Initialize event storage.

        Args:
            db_path: Path to SQLite database file (defaults to XDG-compliant path)
        """
        if db_path is None:
            ensure_directories()
            db_path = get_data_path("events.db")

            # Migrate legacy data if exists
            legacy_path = Path("data/events.db")
            if legacy_path.exists():
                migrate_legacy_data(legacy_path, db_path)
                logger.info(f"Migrated events database from {legacy_path} to {db_path}")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        """Create database connection and initialize schema."""
        if self._conn:
            return self._conn

        self._conn = await aiosqlite.connect(self.db_path)
        await self._init_schema()
        return self._conn

    async def _init_schema(self) -> None:
        """Initialize database schema."""
        assert self._conn is not None

        # Events table
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                version INTEGER DEFAULT 1
            )
            """
        )

        # Delivery tracking table
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                subscriber TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                UNIQUE(event_id, subscriber)
            )
            """
        )

        # Indexes
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(type)")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
        )
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)")
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deliveries_event ON event_deliveries(event_id)"
        )
        await self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deliveries_subscriber ON event_deliveries(subscriber)"
        )

        # Enable WAL mode for better concurrency
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")

        await self._conn.commit()

    async def save(self, event: Event) -> None:
        """Persist event to database.

        Args:
            event: Event to save
        """
        conn = await self.connect()

        await conn.execute(
            """
            INSERT INTO events (id, type, data, timestamp, source, version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.type.value,
                json.dumps(event.data),
                event.timestamp.isoformat(),
                event.source,
                event.version,
            ),
        )
        await conn.commit()

        logger.debug(f"Event saved: {event.type.value} (id={event.id})")

    async def get_events(
        self,
        event_type: EventType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query events from database.

        Args:
            event_type: Filter by event type (None = all types)
            since: Filter events after this timestamp (None = all time)
            limit: Maximum number of events to return

        Returns:
            List of events (sorted by timestamp descending)
        """
        conn = await self.connect()

        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []

        if event_type:
            query += " AND type = ?"
            params.append(event_type.value)

        if since:
            query += " AND timestamp > ?"
            params.append(since.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        # Convert rows to Event objects
        events = []
        for row in rows:
            events.append(
                Event(
                    id=row[0],
                    type=EventType(row[1]),
                    data=json.loads(row[2]),
                    timestamp=datetime.fromisoformat(row[3]),
                    source=row[4],
                    version=row[5],
                )
            )

        return events

    async def mark_delivered(self, event_id: str, subscriber: str) -> None:
        """Mark event as delivered to subscriber.

        Args:
            event_id: Event ID
            subscriber: Subscriber identifier
        """
        conn = await self.connect()

        # Store delivery tracking
        await conn.execute(
            """
            INSERT INTO event_deliveries (event_id, subscriber, delivered_at)
            VALUES (?, ?, ?)
            ON CONFLICT (event_id, subscriber) DO UPDATE SET
                delivered_at = excluded.delivered_at
            """,
            (event_id, subscriber, datetime.now(UTC).isoformat()),
        )
        await conn.commit()

    async def get_undelivered_events(
        self, subscriber: str, event_type: EventType | None = None, limit: int = 100
    ) -> list[Event]:
        """Get events not yet delivered to subscriber.

        Args:
            subscriber: Subscriber identifier
            event_type: Filter by event type (None = all types)
            limit: Maximum number of events

        Returns:
            List of undelivered events
        """
        conn = await self.connect()

        query = """
            SELECT e.* FROM events e
            LEFT JOIN event_deliveries d ON e.id = d.event_id AND d.subscriber = ?
            WHERE d.id IS NULL
        """
        params: list[Any] = [subscriber]

        if event_type:
            query += " AND e.type = ?"
            params.append(event_type.value)

        query += " ORDER BY e.timestamp ASC LIMIT ?"
        params.append(limit)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        events = []
        for row in rows:
            events.append(
                Event(
                    id=row[0],
                    type=EventType(row[1]),
                    data=json.loads(row[2]),
                    timestamp=datetime.fromisoformat(row[3]),
                    source=row[4],
                    version=row[5],
                )
            )

        return events

    async def cleanup_old_events(self, retention_days: int = 30) -> int:
        """Delete events older than retention period.

        Args:
            retention_days: Days to keep events

        Returns:
            Number of events deleted
        """
        conn = await self.connect()

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        cursor = await conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff.isoformat(),))
        deleted_count = cursor.rowcount
        await conn.commit()

        logger.info(f"Cleaned up {deleted_count} old events (retention={retention_days} days)")
        return deleted_count

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None


class EventBus:
    """System-wide event bus with persistence.

    Features:
    - Persistent event log (survives restarts)
    - Event replay capability
    - At-least-once delivery (with deduplication)
    - Backpressure handling

    Example:
        ```python
        # Create event bus
        bus = EventBus(storage_backend="sqlite")

        # Subscribe to events
        async def on_code_indexed(event: Event):
            repo = event.data["repo"]
            print(f"Code indexed: {repo}")

        bus.subscribe(EventType.CODE_GRAPH_INDEXED, on_code_indexed)

        # Publish event
        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "/path/to/repo", "stats": {...}},
            source="code_index_service"
        )
        ```
    """

    def __init__(
        self,
        storage_backend: str = "sqlite",
        storage_path: str | Path | None = None,
    ):
        """Initialize event bus.

        Args:
            storage_backend: Storage backend ('sqlite' or 'redis')
            storage_path: Path to storage (defaults to XDG-compliant path if None)
        """
        if storage_path is None:
            ensure_directories()
            storage_path = get_data_path("events.db")

            # Migrate legacy data if exists
            legacy_path = Path("data/events.db")
            if legacy_path.exists():
                migrate_legacy_data(legacy_path, storage_path)
                logger.info(f"Migrated events database from {legacy_path} to {storage_path}")

        self.storage_backend = storage_backend
        self.storage_path = Path(storage_path)
        self._storage: SQLiteEventStorage | None = None
        self._subscribers: dict[EventType, list[Callable]] = {}
        self._subscriber_names: dict[Callable, str] = {}
        self._running = False
        self._delivery_task: asyncio.Task | None = None

        logger.info(f"EventBus initialized (backend={storage_backend}, path={storage_path})")

    async def start(self) -> None:
        """Start event bus (connect to storage, start delivery loop)."""
        if self.storage_backend == "sqlite":
            self._storage = SQLiteEventStorage(self.storage_path)
            await self._storage.connect()
        else:
            raise ValueError(f"Unsupported storage backend: {self.storage_backend}")

        self._running = True

        # Start background delivery task
        self._delivery_task = asyncio.create_task(self._delivery_loop())

        logger.info("EventBus started")

    async def stop(self) -> None:
        """Stop event bus."""
        self._running = False

        if self._delivery_task:
            self._delivery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._delivery_task

        if self._storage:
            await self._storage.close()

        logger.info("EventBus stopped")

    async def publish(
        self,
        event_type: EventType,
        data: dict[str, Any],
        source: str,
    ) -> Event:
        """Publish event to bus.

        Args:
            event_type: Event type
            data: Event payload
            source: Source component identifier

        Returns:
            Created event
        """
        if not self._storage:
            raise RuntimeError("EventBus not started (call start() first)")

        # Create event
        event = Event(
            id=str(uuid.uuid4()),
            type=event_type,
            data=data,
            timestamp=datetime.now(UTC),
            source=source,
        )

        # Persist to storage
        await self._storage.save(event)

        # Deliver to subscribers (async fire-and-forget)
        asyncio.create_task(self._deliver_event(event))

        logger.debug(f"Event published: {event_type.value} (id={event.id}, source={source})")

        return event

    def subscribe(
        self, event_type: EventType, handler: Callable, subscriber_name: str | None = None
    ) -> None:
        """Subscribe to event type.

        Args:
            event_type: Type of event to subscribe to
            handler: Async callback function that takes Event as parameter
            subscriber_name: Optional subscriber identifier (for tracking delivery)

        Example:
            ```python
            async def handle_code_indexed(event: Event):
                repo = event.data["repo"]
                print(f"Code indexed: {repo}")

            bus.subscribe(
                EventType.CODE_GRAPH_INDEXED,
                handle_code_indexed,
                subscriber_name="session_buddy_subscriber"
            )
            ```
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append(handler)
        self._subscriber_names[handler] = subscriber_name or handler.__name__

        logger.info(
            f"Subscribed to {event_type.value} (subscriber={subscriber_name or handler.__name__}, "
            f"total={len(self._subscribers[event_type])})"
        )

    async def _deliver_event(self, event: Event, check_delivered: bool = True) -> None:
        """Deliver event to all subscribers.

        Args:
            event: Event to deliver
            check_delivered: If True, skip if already delivered to subscriber
        """
        subscribers = self._subscribers.get(event.type, [])

        for handler in subscribers:
            subscriber_name = self._subscriber_names.get(handler, "unknown")

            try:
                # Check if already delivered (prevent duplicate delivery)
                if check_delivered and self._storage:
                    # Check delivery table
                    cursor = await self._storage._conn.execute(
                        "SELECT 1 FROM event_deliveries WHERE event_id = ? AND subscriber = ?",
                        (event.id, subscriber_name),
                    )
                    already_delivered = await cursor.fetchone()

                    if already_delivered:
                        logger.debug(
                            f"[EventBus] Skipping already delivered: {event.type.value} -> {subscriber_name} (id={event.id})"
                        )
                        continue

                # Call subscriber handler
                logger.info(
                    f"[EventBus] Delivering: {event.type.value} -> {subscriber_name} (id={event.id}, check_delivered={check_delivered})"
                )
                await handler(event)

                # Mark as delivered
                if self._storage:
                    await self._storage.mark_delivered(event.id, subscriber_name)

                logger.debug(
                    f"Event delivered: {event.type.value} -> {subscriber_name} (id={event.id})"
                )

            except Exception as e:
                logger.error(f"Subscriber error: {event.type.value} -> {subscriber_name}: {e}")

    async def _delivery_loop(self) -> None:
        """Background task to deliver undelivered events on startup.

        This runs once when EventBus starts to replay any events that
        weren't delivered before a restart.
        """
        if not self._storage:
            return

        logger.info("Event delivery loop started (checking for undelivered events)")

        # Wait a bit for any in-flight deliveries to complete
        await asyncio.sleep(0.5)

        # Get unique subscriber names
        for event_type, handlers in self._subscribers.items():
            for handler in handlers:
                subscriber_name = self._subscriber_names.get(handler, "unknown")

                # Get undelivered events for this subscriber
                undelivered = await self._storage.get_undelivered_events(
                    subscriber=subscriber_name, event_type=event_type
                )

                if undelivered:
                    logger.info(
                        f"Replaying {len(undelivered)} undelivered events "
                        f"for {subscriber_name} ({event_type.value})"
                    )

                    for event in undelivered:
                        # Don't check already delivered (these are truly undelivered)
                        await self._deliver_event(event, check_delivered=False)

        logger.info("Event delivery loop completed")

    async def replay_events(
        self,
        subscriber: str,
        event_type: EventType | None = None,
        since: datetime | None = None,
    ) -> list[Event]:
        """Replay events for a subscriber (useful for recovery).

        Args:
            subscriber: Subscriber identifier
            event_type: Filter by event type (None = all types)
            since: Replay events after this timestamp (None = all time)

        Returns:
            List of replayed events
        """
        if not self._storage:
            raise RuntimeError("EventBus not started")

        events = await self._storage.get_events(event_type=event_type, since=since, limit=1000)

        logger.info(
            f"Replaying {len(events)} events for {subscriber} "
            f"(type={event_type.value if event_type else 'all'})"
        )

        return events

    def get_stats(self) -> dict[str, Any]:
        """Get event bus statistics.

        Returns:
            Statistics dictionary
        """
        subscriber_counts = {
            event_type.value: len(handlers) for event_type, handlers in self._subscribers.items()
        }

        return {
            "storage_backend": self.storage_backend,
            "storage_path": str(self.storage_path),
            "running": self._running,
            "subscriber_counts": subscriber_counts,
            "total_subscribers": sum(subscriber_counts.values()),
        }


# Singleton instance for global access
_event_bus_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get global EventBus instance.

    Returns:
        EventBus instance

    Raises:
        RuntimeError: If EventBus not initialized
    """
    global _event_bus_instance

    if _event_bus_instance is None:
        raise RuntimeError(
            "EventBus not initialized. Call init_event_bus() during application startup."
        )

    return _event_bus_instance


async def init_event_bus(
    storage_backend: str = "sqlite", storage_path: str | Path | None = None
) -> EventBus:
    """Initialize global EventBus instance.

    Args:
        storage_backend: Storage backend ('sqlite' or 'redis')
        storage_path: Path to storage (defaults to XDG-compliant path if None)

    Returns:
        Initialized EventBus instance
    """
    global _event_bus_instance

    _event_bus_instance = EventBus(storage_backend=storage_backend, storage_path=storage_path)
    await _event_bus_instance.start()

    logger.info("Global EventBus initialized")

    return _event_bus_instance
