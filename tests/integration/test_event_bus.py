"""Integration test for EventBus system.

This test demonstrates:
1. Event publishing
2. Event subscription
3. Event persistence (survives restarts)
4. Event replay for new subscribers
"""

import asyncio
import tempfile
from pathlib import Path

from mahavishnu.core.event_bus import (
    EventBus,
    EventType,
    Event,
    init_event_bus,
)


async def test_basic_publish_subscribe():
    """Test basic event publishing and subscription."""

    print("=== Test 1: Basic Publish/Subscribe ===")

    # Create temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"
        bus = EventBus(storage_path=db_path)
        await bus.start()

        # Track received events
        received_events = []

        # Subscribe to code graph indexed events
        async def on_code_indexed(event: Event):
            print(f"  📥 Received event: {event.type.value} (id={event.id})")
            print(f"     Repo: {event.data['repo']}")
            print(f"     Stats: {event.data['stats']}")
            received_events.append(event)

        bus.subscribe(
            EventType.CODE_GRAPH_INDEXED,
            on_code_indexed,
            subscriber_name="test_subscriber",
        )

        # Publish some events
        print("\n  📤 Publishing events...")

        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={
                "repo": "/Users/les/Projects/mahavishnu",
                "stats": {"nodes": 1500, "edges": 3200, "duration_seconds": 45},
            },
            source="code_index_service",
        )

        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={
                "repo": "/Users/les/Projects/session-buddy",
                "stats": {"nodes": 800, "edges": 1600, "duration_seconds": 30},
            },
            source="code_index_service",
        )

        # Wait for async delivery
        await asyncio.sleep(0.5)

        # Verify events were received
        assert len(received_events) == 2, f"Expected 2 events, got {len(received_events)}"
        print(f"\n  ✅ Successfully received {len(received_events)} events")

        # Check stats
        stats = bus.get_stats()
        print(f"\n  📊 Stats: {stats}")
        assert stats["total_subscribers"] == 1
        assert stats["running"] is True

        await bus.stop()
        print("  ✅ Test passed!")


async def test_event_persistence():
    """Test that events persist across restarts."""

    print("\n=== Test 2: Event Persistence ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"

        # Phase 1: Publish events and stop
        print("\n  📤 Phase 1: Publishing events...")
        bus1 = EventBus(storage_path=db_path)
        await bus1.start()

        await bus1.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "/path/to/repo1", "stats": {"nodes": 100}},
            source="test_service",
        )

        await bus1.publish(
            EventType.WORKER_STARTED,
            data={"worker_id": "worker_123", "worker_type": "ssh"},
            source="worker_manager",
        )

        await bus1.stop()
        print("  ✅ Events published and bus stopped")

        # Phase 2: Restart and verify events persisted
        print("\n  🔄 Phase 2: Restarting bus...")
        bus2 = EventBus(storage_path=db_path)
        await bus2.start()

        # Replay events from storage
        events = await bus2.replay_events(
            subscriber="test_replay",
            since=None,  # Get all events
        )

        print(f"  📥 Replayed {len(events)} events")
        assert len(events) == 2, f"Expected 2 replayed events, got {len(events)}"

        for event in events:
            print(f"     - {event.type.value}: {event.data}")

        await bus2.stop()
        print("  ✅ Test passed!")


async def test_multiple_subscribers():
    """Test multiple subscribers to same event type."""

    print("\n=== Test 3: Multiple Subscribers ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"
        bus = EventBus(storage_path=db_path)
        await bus.start()

        # Track received events per subscriber
        session_buddy_events = []
        akosha_events = []

        # Session-Buddy subscriber
        async def session_buddy_handler(event: Event):
            print(f"  📥 Session-Buddy received: {event.type.value}")
            session_buddy_events.append(event)

        # Akosha subscriber
        async def akosha_handler(event: Event):
            print(f"  📥 Akosha received: {event.type.value}")
            akosha_events.append(event)

        # Subscribe both
        bus.subscribe(
            EventType.CODE_GRAPH_INDEXED,
            session_buddy_handler,
            subscriber_name="session_buddy",
        )

        bus.subscribe(
            EventType.CODE_GRAPH_INDEXED,
            akosha_handler,
            subscriber_name="akosha",
        )

        # Publish single event
        print("\n  📤 Publishing event...")
        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "/test/repo"},
            source="test",
        )

        # Wait for delivery
        await asyncio.sleep(0.5)

        # Verify both received it
        assert len(session_buddy_events) == 1
        assert len(akosha_events) == 1
        print(f"\n  ✅ Both subscribers received event")

        # Check stats
        stats = bus.get_stats()
        print(f"  📊 Stats: {stats}")
        assert stats["total_subscribers"] == 2

        await bus.stop()
        print("  ✅ Test passed!")


async def test_event_filtering():
    """Test event filtering by type."""

    print("\n=== Test 4: Event Filtering ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"
        bus = EventBus(storage_path=db_path)
        await bus.start()

        # Subscribe only to CODE_GRAPH_INDEXED
        received = []

        async def handler(event: Event):
            received.append(event)

        bus.subscribe(EventType.CODE_GRAPH_INDEXED, handler, subscriber_name="filter_test")

        # Publish multiple event types
        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "repo1"},
            source="test",
        )

        await bus.publish(
            EventType.WORKER_STARTED,
            data={"worker_id": "worker1"},
            source="test",
        )

        await bus.publish(
            EventType.CODE_GRAPH_INDEXED,
            data={"repo": "repo2"},
            source="test",
        )

        # Wait for delivery
        await asyncio.sleep(0.5)

        # Should only receive CODE_GRAPH_INDEXED events
        assert len(received) == 2
        assert all(e.type == EventType.CODE_GRAPH_INDEXED for e in received)
        print(f"  ✅ Received {len(received)} filtered events (ignored other types)")

        await bus.stop()
        print("  ✅ Test passed!")


async def main():
    """Run all tests."""
    print("🚀 Starting EventBus integration tests...\n")

    try:
        await test_basic_publish_subscribe()
        await test_event_persistence()
        await test_multiple_subscribers()
        await test_event_filtering()

        print("\n" + "=" * 50)
        print("✅ All tests passed!")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
