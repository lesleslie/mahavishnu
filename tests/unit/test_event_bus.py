"""Tests for core/event_bus.py — EventType, Event, SQLiteEventStorage, EventBus."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.event_bus import (
    Event,
    EventBus,
    EventType,
    SQLiteEventStorage,
    get_event_bus,
)

# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------


class TestEventType:
    def test_all_members(self):
        members = list(EventType)
        assert len(members) >= 12

    def test_code_events(self):
        assert EventType.CODE_GRAPH_INDEXED == "code.graph.indexed"
        assert EventType.CODE_GRAPH_INDEX_FAILED == "code.graph.index_failed"
        assert EventType.CODE_GRAPH_CACHE_INVALIDATED == "code.graph.cache_invalidated"

    def test_worker_events(self):
        assert EventType.WORKER_STARTED == "worker.started"
        assert EventType.WORKER_STOPPED == "worker.stopped"

    def test_backup_events(self):
        assert EventType.BACKUP_STARTED == "backup.started"
        assert EventType.BACKUP_COMPLETED == "backup.completed"
        assert EventType.BACKUP_FAILED == "backup.failed"
        assert EventType.BACKUP_RESTORED == "backup.restored"

    def test_pool_events(self):
        assert EventType.POOL_SPAWNED == "pool.spawned"
        assert EventType.POOL_CLOSED == "pool.closed"
        assert EventType.POOL_SCALED == "pool.scaled"

    def test_string_values(self):
        for member in EventType:
            assert isinstance(member.value, str)
            assert "." in member.value  # dot-namespace convention

    def test_from_string(self):
        assert EventType("code.graph.indexed") is EventType.CODE_GRAPH_INDEXED


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


def _make_event(**overrides):
    defaults = {
        "id": "test-id-123",
        "type": EventType.CODE_GRAPH_INDEXED,
        "data": {"repo": "/path/to/repo", "files": 42},
        "timestamp": datetime.now(UTC),
        "source": "test_service",
        "version": 1,
    }
    defaults.update(overrides)
    return Event(**defaults)


class TestEvent:
    def test_creation(self):
        event = _make_event()
        assert event.id == "test-id-123"
        assert event.type == EventType.CODE_GRAPH_INDEXED
        assert event.data["repo"] == "/path/to/repo"
        assert event.version == 1

    def test_default_version(self):
        event = Event(
            id="id", type=EventType.WORKER_STARTED, data={}, timestamp=datetime.now(UTC), source="s"
        )
        assert event.version == 1

    def test_to_dict(self):
        event = _make_event()
        d = event.to_dict()
        assert d["id"] == "test-id-123"
        assert d["type"] == "code.graph.indexed"
        assert d["source"] == "test_service"
        assert d["version"] == 1
        assert "timestamp" in d
        # data should be JSON-serialized string
        assert isinstance(d["data"], str)

    def test_to_dict_with_envelope(self):
        event = _make_event(data={"repo": "/r", "_envelope": '{"version":"1.0.0"}'})
        d = event.to_dict()
        assert "_envelope" in d
        assert d["_envelope"] == '{"version":"1.0.0"}'

    def test_to_dict_without_envelope(self):
        event = _make_event(data={"repo": "/r"})
        d = event.to_dict()
        assert "_envelope" not in d

    def test_from_dict(self):
        original = _make_event()
        d = original.to_dict()
        restored = Event.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.data == original.data
        assert restored.source == original.source

    def test_from_dict_with_envelope(self):
        event = _make_event(data={"repo": "/r", "_envelope": '{"version":"1.0.0"}'})
        d = event.to_dict()
        restored = Event.from_dict(d)
        assert restored.data["_envelope"] == '{"version":"1.0.0"}'

    def test_from_dict_with_explicit_version(self):
        event = _make_event(version=2)
        d = event.to_dict()
        restored = Event.from_dict(d)
        assert restored.version == 2

    def test_from_dict_default_version(self):
        event = _make_event()
        d = event.to_dict()
        d.pop("version", None)
        restored = Event.from_dict(d)
        assert restored.version == 1


# ---------------------------------------------------------------------------
# SQLiteEventStorage (using real temp SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSQLiteEventStorage:
    async def test_connect_creates_schema(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        conn = await storage.connect()
        assert conn is not None

        # Verify tables exist
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in await cursor.fetchall()}
        assert "events" in tables
        assert "event_deliveries" in tables

        await storage.close()

    async def test_save_and_get_events(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        event = _make_event()
        await storage.save(event)

        events = await storage.get_events()
        assert len(events) == 1
        assert events[0].id == event.id
        assert events[0].type == event.type

        await storage.close()

    async def test_get_events_by_type(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        e1 = _make_event(id="e1", type=EventType.CODE_GRAPH_INDEXED)
        e2 = _make_event(id="e2", type=EventType.WORKER_STARTED)
        await storage.save(e1)
        await storage.save(e2)

        code_events = await storage.get_events(event_type=EventType.CODE_GRAPH_INDEXED)
        assert len(code_events) == 1
        assert code_events[0].id == "e1"

        worker_events = await storage.get_events(event_type=EventType.WORKER_STARTED)
        assert len(worker_events) == 1
        assert worker_events[0].id == "e2"

        await storage.close()

    async def test_get_events_since(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        old = _make_event(id="old", timestamp=datetime(2020, 1, 1, tzinfo=UTC))
        recent = _make_event(id="recent", timestamp=datetime(2026, 1, 1, tzinfo=UTC))
        await storage.save(old)
        await storage.save(recent)

        since = datetime(2025, 1, 1, tzinfo=UTC)
        events = await storage.get_events(since=since)
        assert len(events) == 1
        assert events[0].id == "recent"

        await storage.close()

    async def test_get_events_limit(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        for i in range(10):
            await storage.save(_make_event(id=f"e{i}"))

        events = await storage.get_events(limit=3)
        assert len(events) == 3

        await storage.close()

    async def test_mark_delivered(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        event = _make_event()
        await storage.save(event)
        await storage.mark_delivered(event.id, "subscriber_1")

        # Verify delivery was recorded
        cursor = await storage._conn.execute(
            "SELECT subscriber FROM event_deliveries WHERE event_id = ?",
            (event.id,),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "subscriber_1"

        await storage.close()

    async def test_get_undelivered_events(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        e1 = _make_event(id="delivered")
        e2 = _make_event(id="undelivered")
        await storage.save(e1)
        await storage.save(e2)

        await storage.mark_delivered(e1.id, "sub1")

        undelivered = await storage.get_undelivered_events("sub1")
        assert len(undelivered) == 1
        assert undelivered[0].id == "undelivered"

        await storage.close()

    async def test_get_undelivered_by_type(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        e1 = _make_event(id="code_evt", type=EventType.CODE_GRAPH_INDEXED)
        e2 = _make_event(id="worker_evt", type=EventType.WORKER_STARTED)
        await storage.save(e1)
        await storage.save(e2)

        undelivered = await storage.get_undelivered_events(
            "sub1", event_type=EventType.WORKER_STARTED
        )
        assert len(undelivered) == 1
        assert undelivered[0].id == "worker_evt"

        await storage.close()

    async def test_cleanup_old_events(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()

        old = _make_event(id="old", timestamp=datetime(2020, 1, 1, tzinfo=UTC))
        recent = _make_event(id="recent", timestamp=datetime.now(UTC))
        await storage.save(old)
        await storage.save(recent)

        deleted = await storage.cleanup_old_events(retention_days=30)
        assert deleted >= 1

        remaining = await storage.get_events()
        assert len(remaining) == 1
        assert remaining[0].id == "recent"

        await storage.close()

    async def test_connect_idempotent(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        conn1 = await storage.connect()
        conn2 = await storage.connect()
        assert conn1 is conn2
        await storage.close()

    async def test_close_sets_none(self, tmp_path):
        storage = SQLiteEventStorage(tmp_path / "test_events.db")
        await storage.connect()
        await storage.close()
        assert storage._conn is None


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEventBus:
    async def test_start_and_stop(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()
        assert bus._running is True
        assert bus._storage is not None

        await bus.stop()
        assert bus._running is False

    async def test_publish_requires_start(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        with pytest.raises(RuntimeError, match="not started"):
            await bus.publish(
                EventType.CODE_GRAPH_INDEXED,
                data={"repo": "/r"},
                source="test",
            )

    async def test_publish_and_retrieve(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        event = await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "/path", "files": 10},
            source="indexer",
        )

        assert event.id is not None
        assert event.type == EventType.CODE_GRAPH_INDEXED
        assert event.source == "indexer"

        await bus.stop()

    async def test_publish_generates_uuid(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        event = await bus.publish(
            EventType.WORKER_STARTED,
            data={"worker_id": "w1"},
            source="pool",
        )

        # UUID4 format: 8-4-4-4-12 hex chars
        assert len(event.id) == 36
        assert event.id.count("-") == 4

        await bus.stop()

    async def test_subscribe_and_deliver(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(EventType.CODE_GRAPH_INDEXED, handler)

        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "/r"},
            source="test",
        )

        # Give delivery task time to execute
        await asyncio.sleep(0.3)

        assert len(received) == 1
        assert received[0].data["repo"] == "/r"

        await bus.stop()

    async def test_multiple_subscribers(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        received_a = []
        received_b = []

        async def handler_a(event):
            received_a.append(event)

        async def handler_b(event):
            received_b.append(event)

        bus.subscribe(EventType.WORKER_STARTED, handler_a)
        bus.subscribe(EventType.WORKER_STARTED, handler_b)

        await bus.publish(
            EventType.WORKER_STARTED,
            data={"wid": "w1"},
            source="pool",
        )
        await asyncio.sleep(0.3)

        assert len(received_a) == 1
        assert len(received_b) == 1

        await bus.stop()

    async def test_subscriber_error_doesnt_crash(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        async def bad_handler(event):
            raise ValueError("boom!")

        good_received = []

        async def good_handler(event):
            good_received.append(event)

        bus.subscribe(EventType.BACKUP_COMPLETED, bad_handler)
        bus.subscribe(EventType.BACKUP_COMPLETED, good_handler)

        await bus.publish(
            EventType.BACKUP_COMPLETED,
            data={"size": 1024},
            source="backup",
        )
        await asyncio.sleep(0.3)

        # Good handler should still receive despite bad_handler error
        assert len(good_received) == 1

        await bus.stop()

    async def test_get_stats(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        await bus.start()

        async def handler(event):
            pass

        bus.subscribe(EventType.CODE_GRAPH_INDEXED, handler)

        stats = bus.get_stats()
        assert stats["storage_backend"] == "sqlite"
        assert stats["running"] is True
        assert stats["total_subscribers"] == 1
        assert "subscriber_counts" in stats

        await bus.stop()

    async def test_unsupported_backend_raises(self):
        bus = EventBus(storage_backend="redis", storage_path="/tmp/redis_dummy")
        with pytest.raises(ValueError, match="Unsupported storage backend"):
            await bus.start()

    async def test_publish_envelope_requires_start(self, tmp_path):
        bus = EventBus(storage_path=tmp_path / "bus.db")
        import uuid as uuid_mod

        from mahavishnu.core.events.envelope import EventEnvelope

        envelope = EventEnvelope(
            event_id=uuid_mod.uuid4(),
            event_type=EventType.CODE_GRAPH_INDEXED.value,
            version="1.0.0",
            timestamp=datetime.now(UTC),
            source="test",
            payload={"repo": "/r"},
        )
        with pytest.raises(RuntimeError, match="not started"):
            await bus.publish_envelope(envelope)


# ---------------------------------------------------------------------------
# get_event_bus singleton
# ---------------------------------------------------------------------------


class TestGetEventBus:
    def test_not_initialized_raises(self):
        import mahavishnu.core.event_bus as mod

        original = mod._event_bus_instance
        mod._event_bus_instance = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                get_event_bus()
        finally:
            mod._event_bus_instance = original

    def test_returns_instance(self):
        import mahavishnu.core.event_bus as mod

        mock_bus = MagicMock()
        original = mod._event_bus_instance
        mod._event_bus_instance = mock_bus
        try:
            assert get_event_bus() is mock_bus
        finally:
            mod._event_bus_instance = original
