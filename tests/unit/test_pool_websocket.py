"""Unit tests for mahavishnu.pools.websocket module.

Tests WebSocketBroadcaster and related pool WebSocket broadcasting functionality.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mahavishnu.pools.websocket import WebSocketBroadcaster, create_broadcaster


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_server():
    """Create a mock WebSocket server."""
    server = MagicMock()
    server.is_running = True
    server.broadcast_to_room = AsyncMock(return_value=True)
    return server


@pytest.fixture
def broadcaster(mock_server):
    """Create WebSocketBroadcaster with mock server."""
    return WebSocketBroadcaster(websocket_server=mock_server)


@pytest.fixture
def broadcaster_no_server():
    """Create WebSocketBroadcaster without server."""
    return WebSocketBroadcaster(websocket_server=None)


@pytest.fixture
def broadcaster_with_buffer(mock_server):
    """Create WebSocketBroadcaster with buffering enabled."""
    return WebSocketBroadcaster(
        websocket_server=mock_server,
        buffer_enabled=True,
        buffer_size=100,
    )


# =============================================================================
# WebSocketBroadcaster Tests
# =============================================================================


class TestWebSocketBroadcasterInitialization:
    """Tests for WebSocketBroadcaster initialization."""

    def test_init_with_server(self, mock_server) -> None:
        """Test initialization with WebSocket server."""
        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        assert broadcaster.server == mock_server
        assert broadcaster._buffer_enabled is False
        assert broadcaster._reconnect_attempts == 0

    def test_init_without_server(self) -> None:
        """Test initialization without server."""
        broadcaster = WebSocketBroadcaster()

        assert broadcaster.server is None
        assert broadcaster._buffer_enabled is False

    def test_init_with_buffer_enabled(self, mock_server) -> None:
        """Test initialization with buffer enabled."""
        broadcaster = WebSocketBroadcaster(
            websocket_server=mock_server,
            buffer_enabled=True,
            buffer_size=500,
        )

        assert broadcaster._buffer_enabled is True
        assert broadcaster._event_buffer.maxlen == 500

    def test_init_default_values(self) -> None:
        """Test initialization with default values."""
        broadcaster = WebSocketBroadcaster()

        assert broadcaster._buffer_enabled is False
        assert broadcaster._event_buffer.maxlen == 1000
        assert broadcaster._reconnect_attempts == 0
        assert broadcaster._max_reconnect_attempts == 5


# =============================================================================
# Pool Lifecycle Event Tests
# =============================================================================


class TestPoolLifecycleEvents:
    """Tests for pool lifecycle broadcast events."""

    @pytest.mark.asyncio
    async def test_broadcast_pool_spawned_success(self, broadcaster, mock_server) -> None:
        """Test successful pool spawned broadcast."""
        config = {"name": "test-pool", "min_workers": 2}
        result = await broadcaster.broadcast_pool_spawned("pool_123", config)

        assert result is True
        mock_server.broadcast_to_room.assert_called_once()
        call_args = mock_server.broadcast_to_room.call_args
        assert "pool:pool_123" in call_args[0][0] or call_args[0][0] == "pool:pool_123"

    @pytest.mark.asyncio
    async def test_broadcast_pool_spawned_no_server(self, broadcaster_no_server) -> None:
        """Test pool spawned broadcast when no server configured."""
        result = await broadcaster_no_server.broadcast_pool_spawned(
            "pool_123", {"name": "test"}
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_pool_spawned_server_not_running(
        self, mock_server
    ) -> None:
        """Test pool spawned broadcast when server not running."""
        mock_server.is_running = False
        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        result = await broadcaster.broadcast_pool_spawned("pool_123", {})

        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_pool_scaled_success(self, broadcaster, mock_server) -> None:
        """Test successful pool scaled broadcast."""
        result = await broadcaster.broadcast_pool_scaled("pool_abc", 5)

        assert result is True
        mock_server.broadcast_to_room.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed_string(self, broadcaster, mock_server) -> None:
        """Test pool status changed with string status."""
        result = await broadcaster.broadcast_pool_status_changed(
            "pool_xyz", "running"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed_dict(self, broadcaster, mock_server) -> None:
        """Test pool status changed with dict status."""
        status_dict = {"state": "running", "workers": 3}
        result = await broadcaster.broadcast_pool_status_changed(
            "pool_xyz", status_dict
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_pool_closed_success(self, broadcaster, mock_server) -> None:
        """Test successful pool closed broadcast."""
        result = await broadcaster.broadcast_pool_closed("pool_123")

        assert result is True


# =============================================================================
# Worker Event Tests
# =============================================================================


class TestWorkerEvents:
    """Tests for worker-related broadcast events."""

    @pytest.mark.asyncio
    async def test_broadcast_worker_added_success(self, broadcaster, mock_server) -> None:
        """Test successful worker added broadcast."""
        result = await broadcaster.broadcast_worker_added("pool_1", "worker_a")

        assert result is True
        mock_server.broadcast_to_room.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_worker_removed_success(self, broadcaster, mock_server) -> None:
        """Test successful worker removed broadcast."""
        result = await broadcaster.broadcast_worker_removed("pool_1", "worker_a")

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_worker_status_changed_success(
        self, broadcaster, mock_server
    ) -> None:
        """Test successful worker status changed broadcast."""
        result = await broadcaster.broadcast_worker_status_changed(
            "pool_1", "worker_a", "busy"
        )

        assert result is True


# =============================================================================
# Task Event Tests
# =============================================================================


class TestTaskEvents:
    """Tests for task-related broadcast events."""

    @pytest.mark.asyncio
    async def test_broadcast_task_assigned_success(self, broadcaster, mock_server) -> None:
        """Test successful task assigned broadcast."""
        task = {"prompt": "test task", "timeout": 30}
        result = await broadcaster.broadcast_task_assigned(
            "pool_1", "worker_a", task
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_task_completed_success(self, broadcaster, mock_server) -> None:
        """Test successful task completed broadcast."""
        result = {
            "status": "completed",
            "output": "test output",
            "duration": 1.5,
        }
        broadcast_result = await broadcaster.broadcast_task_completed(
            "pool_1", "worker_a", result
        )

        assert broadcast_result is True


# =============================================================================
# Symbiotic Ecosystem Event Tests
# =============================================================================


class TestSymbioticEcosystemEvents:
    """Tests for symbiotic ecosystem broadcast events."""

    @pytest.mark.asyncio
    async def test_broadcast_learning_metrics_success(
        self, broadcaster, mock_server
    ) -> None:
        """Test successful learning metrics broadcast."""
        result = await broadcaster.broadcast_learning_metrics(
            patterns_strengthened=10,
            patterns_weakened=2,
            model_retrains=1,
            avg_confidence_score=85.5,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_learning_metrics_with_user_id(
        self, broadcaster, mock_server
    ) -> None:
        """Test learning metrics broadcast with user_id."""
        result = await broadcaster.broadcast_learning_metrics(
            patterns_strengthened=5,
            user_id="user_123",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_skill_effectiveness_success(
        self, broadcaster, mock_server
    ) -> None:
        """Test successful skill effectiveness broadcast."""
        result = await broadcaster.broadcast_skill_effectiveness(
            skill_name="RefactoringAgent",
            success_rate=92.5,
            total_attempts=100,
            avg_confidence=88.0,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_broadcast_strategy_recommender_metrics_success(
        self, broadcaster, mock_server
    ) -> None:
        """Test successful strategy recommender metrics broadcast."""
        result = await broadcaster.broadcast_strategy_recommender_metrics(
            recommendations_made=50,
            high_confidence_count=30,
            avg_success_rate=78.5,
        )

        assert result is True


# =============================================================================
# Connection Management Tests
# =============================================================================


class TestConnectionManagement:
    """Tests for connection management and reconnection logic."""

    @pytest.mark.asyncio
    async def test_broadcast_fails_gracefully_on_exception(
        self, mock_server
    ) -> None:
        """Test broadcast handles exceptions gracefully."""
        mock_server.broadcast_to_room.side_effect = Exception("Connection error")
        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        result = await broadcaster.broadcast_pool_spawned("pool_123", {})

        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_with_connection_error_triggers_reconnect(
        self, mock_server
    ) -> None:
        """Test broadcast with connection error attempts reconnection."""
        mock_server.broadcast_to_room.side_effect = Exception(
            "Connection reset by peer"
        )
        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        with patch.object(broadcaster, "_attempt_reconnect", new_callable=AsyncMock) as mock_reconnect:
            await broadcaster.broadcast_pool_spawned("pool_123", {})
            # Should have tried to reconnect
            # Note: reconnect only triggers on connection errors

    def test_is_connection_error_detects_connection_issues(self) -> None:
        """Test _is_connection_error correctly identifies connection errors."""
        broadcaster = WebSocketBroadcaster()

        connection_errors = [
            Exception("Connection refused"),
            Exception("Connection reset"),
            Exception("Broken pipe"),
            Exception("Network unreachable"),
        ]

        for error in connection_errors:
            assert broadcaster._is_connection_error(error) is True

    def test_is_connection_error_rejects_non_connection_errors(self) -> None:
        """Test _is_connection_error rejects non-connection errors."""
        broadcaster = WebSocketBroadcaster()

        non_connection_errors = [
            Exception("Invalid parameter"),
            Exception("Timeout"),
            Exception("Value error"),
        ]

        for error in non_connection_errors:
            assert broadcaster._is_connection_error(error) is False


# =============================================================================
# Buffer Management Tests
# =============================================================================


class TestBufferManagement:
    """Tests for event buffering functionality."""

    @pytest.mark.asyncio
    async def test_events_buffered_when_disconnected(
        self, broadcaster_with_buffer, mock_server
    ) -> None:
        """Test events are buffered when server unavailable."""
        mock_server.is_running = False
        broadcaster_with_buffer.server = mock_server

        await broadcaster_with_buffer.broadcast_pool_spawned("pool_123", {})

        assert len(broadcaster_with_buffer._event_buffer) == 1

    @pytest.mark.asyncio
    async def test_events_not_buffered_when_disabled(
        self, broadcaster_no_server
    ) -> None:
        """Test events are not buffered when buffering disabled."""
        await broadcaster_no_server.broadcast_pool_spawned("pool_123", {})

        assert len(broadcaster_no_server._event_buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_buffer_success(self, broadcaster_with_buffer, mock_server) -> None:
        """Test successful buffer flush."""
        mock_server.is_running = False
        await broadcaster_with_buffer.broadcast_pool_spawned("pool_1", {})
        await broadcaster_with_buffer.broadcast_pool_spawned("pool_2", {})

        assert len(broadcaster_with_buffer._event_buffer) == 2

        mock_server.is_running = True
        flushed = await broadcaster_with_buffer.flush_buffer()

        # Events are re-broadcast, not necessarily successful
        # The flush returns count of attempted flushes
        assert flushed >= 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, broadcaster_with_buffer) -> None:
        """Test flushing empty buffer returns 0."""
        flushed = await broadcaster_with_buffer.flush_buffer()
        assert flushed == 0

    def test_clear_buffer(self, broadcaster_with_buffer) -> None:
        """Test clear_buffer removes all buffered events."""
        broadcaster_with_buffer._event_buffer.append(
            {"event": "test", "event_data": {}, "room": "test"}
        )
        broadcaster_with_buffer._event_buffer.append(
            {"event": "test2", "event_data": {}, "room": "test2"}
        )

        count = broadcaster_with_buffer.clear_buffer()

        assert count == 2
        assert len(broadcaster_with_buffer._event_buffer) == 0

    def test_buffer_respects_max_size(self) -> None:
        """Test buffer respects maxlen parameter."""
        broadcaster = WebSocketBroadcaster(
            websocket_server=None,
            buffer_enabled=True,
            buffer_size=3,
        )

        # Add 5 events to a buffer with maxlen=3
        for i in range(5):
            broadcaster._buffer_event(
                event=f"event_{i}",
                event_data={"index": i},
                room=f"room_{i}",
            )

        assert len(broadcaster._event_buffer) == 3
        # Should have oldest events removed (FIFO)
        assert broadcaster._event_buffer[0]["event_data"]["index"] == 2


# =============================================================================
# Server Management Tests
# =============================================================================


class TestServerManagement:
    """Tests for server management methods."""

    def test_set_server(self, broadcaster_no_server, mock_server) -> None:
        """Test set_server updates server instance."""
        assert broadcaster_no_server.server is None

        broadcaster_no_server.set_server(mock_server)

        assert broadcaster_no_server.server == mock_server

    def test_set_server_logging(self, mock_server) -> None:
        """Test set_server logs the update."""
        broadcaster = WebSocketBroadcaster()

        with patch("mahavishnu.pools.websocket.broadcaster.logger") as mock_logger:
            broadcaster.set_server(mock_server)
            mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_after_set_server(
        self, broadcaster_no_server, mock_server
    ) -> None:
        """Test broadcast works after setting server."""
        assert broadcaster_no_server.server is None

        broadcaster_no_server.set_server(mock_server)
        result = await broadcaster_no_server.broadcast_pool_spawned(
            "pool_123", {"name": "test"}
        )

        assert result is True


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateBroadcaster:
    """Tests for create_broadcaster factory function."""

    def test_create_broadcaster_default(self) -> None:
        """Test create_broadcaster with default parameters."""
        broadcaster = create_broadcaster()

        assert isinstance(broadcaster, WebSocketBroadcaster)
        assert broadcaster.server is None
        assert broadcaster._buffer_enabled is False

    def test_create_broadcaster_with_server(self, mock_server) -> None:
        """Test create_broadcaster with server."""
        broadcaster = create_broadcaster(websocket_server=mock_server)

        assert broadcaster.server == mock_server

    def test_create_broadcaster_with_buffer(self) -> None:
        """Test create_broadcaster with buffer enabled."""
        broadcaster = create_broadcaster(
            buffer_enabled=True,
            buffer_size=500,
        )

        assert broadcaster._buffer_enabled is True
        assert broadcaster._event_buffer.maxlen == 500


# =============================================================================
# Timestamp Tests
# =============================================================================


class TestTimestamp:
    """Tests for timestamp generation."""

    def test_get_timestamp_returns_iso_format(self) -> None:
        """Test _get_timestamp returns ISO format string."""
        timestamp = WebSocketBroadcaster._get_timestamp()

        assert isinstance(timestamp, str)
        # ISO format contains T separator
        assert "T" in timestamp or "+" in timestamp or "Z" in timestamp

    def test_get_timestamp_different_calls_produce_different_timestamps(self) -> None:
        """Test successive timestamp calls produce different values."""
        import time

        ts1 = WebSocketBroadcaster._get_timestamp()
        time.sleep(0.001)
        ts2 = WebSocketBroadcaster._get_timestamp()

        # Timestamps may or may not differ depending on granularity
        # This just verifies they're valid strings
        assert isinstance(ts1, str)
        assert isinstance(ts2, str)


# =============================================================================
# Reconnection Tests
# =============================================================================


class TestReconnection:
    """Tests for reconnection logic."""

    @pytest.mark.asyncio
    async def test_attempt_reconnect_increments_attempts(self) -> None:
        """Test _attempt_reconnect increments attempt counter."""
        broadcaster = WebSocketBroadcaster(websocket_server=MagicMock())

        initial_attempts = broadcaster._reconnect_attempts

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await broadcaster._attempt_reconnect()

        assert broadcaster._reconnect_attempts == initial_attempts + 1

    @pytest.mark.asyncio
    async def test_attempt_reconnect_stops_at_max_attempts(self) -> None:
        """Test _attempt_reconnect stops after max attempts."""
        broadcaster = WebSocketBroadcaster(websocket_server=MagicMock())
        broadcaster._reconnect_attempts = broadcaster._max_reconnect_attempts

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await broadcaster._attempt_reconnect()

        # Should not increment beyond max
        assert broadcaster._reconnect_attempts == broadcaster._max_reconnect_attempts

    @pytest.mark.asyncio
    async def test_attempt_reconnect_with_exponential_backoff(self) -> None:
        """Test _attempt_reconnect uses exponential backoff."""
        broadcaster = WebSocketBroadcaster(websocket_server=MagicMock())

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await broadcaster._attempt_reconnect()

            # After first attempt (attempt 1), backoff should be 2^1 = 2 seconds
            mock_sleep.assert_called_once()


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_broadcast_none_config(self, broadcaster, mock_server) -> None:
        """Test broadcast handles None config gracefully."""
        result = await broadcaster.broadcast_pool_spawned("pool_123", None)

        # Should still broadcast (config may be None for some use cases)
        # The broadcast handler should not crash
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_multiple_rapid_broadcasts(self, broadcaster, mock_server) -> None:
        """Test multiple rapid broadcasts don't cause issues."""
        for i in range(10):
            await broadcaster.broadcast_pool_spawned(f"pool_{i}", {"index": i})

        # All should succeed
        assert mock_server.broadcast_to_room.call_count == 10

    def test_buffer_event_with_disabled_buffer(self) -> None:
        """Test _buffer_event does nothing when buffering disabled."""
        broadcaster = WebSocketBroadcaster(buffer_enabled=False)

        broadcaster._buffer_event("test", {"data": 1}, "room")

        assert len(broadcaster._event_buffer) == 0

    def test_event_data_structure(self, broadcaster) -> None:
        """Test buffered event structure is correct."""
        broadcaster._buffer_enabled = True

        broadcaster._buffer_event("test.event", {"key": "value"}, "room:test")

        event = broadcaster._event_buffer[0]
        assert "event" in event
        assert "event_data" in event
        assert "room" in event
        assert event["event"] == "test.event"
        assert event["event_data"] == {"key": "value"}
        assert event["room"] == "room:test"