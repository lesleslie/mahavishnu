"""Unit tests for WebSocket pool broadcasting integration.

Tests WebSocketBroadcaster functionality with mocked WebSocket server.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.pools.websocket import WebSocketBroadcaster, create_broadcaster


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_websocket_server() -> MagicMock:
    """Create mock WebSocket server.

    Returns:
        Mock server with is_running attribute and broadcast_to_room method
    """
    server = MagicMock()
    server.is_running = True
    server.broadcast_to_room = AsyncMock()
    return server


@pytest.fixture
def broadcaster(mock_websocket_server: MagicMock) -> WebSocketBroadcaster:
    """Create WebSocketBroadcaster instance.

    Args:
        mock_websocket_server: Mock WebSocket server fixture

    Returns:
        WebSocketBroadcaster instance configured with mock server
    """
    return WebSocketBroadcaster(websocket_server=mock_websocket_server)


@pytest.fixture
def sample_pool_config() -> dict:
    """Create sample pool configuration.

    Returns:
        Sample pool configuration dictionary
    """
    return {
        "name": "test-pool",
        "pool_type": "mahavishnu",
        "min_workers": 2,
        "max_workers": 5,
    }


@pytest.fixture
def sample_task() -> dict:
    """Create sample task specification.

    Returns:
        Sample task dictionary
    """
    return {
        "prompt": "Write code",
        "timeout": 300,
        "priority": "high",
    }


@pytest.fixture
def sample_result() -> dict:
    """Create sample task result.

    Returns:
        Sample result dictionary
    """
    return {
        "status": "success",
        "output": "Code generated successfully",
        "duration": 1.5,
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestWebSocketBroadcasterInit:
    """Test WebSocketBroadcaster initialization."""

    def test_init_with_server(self, mock_websocket_server: MagicMock):
        """Test initialization with WebSocket server."""
        broadcaster = WebSocketBroadcaster(websocket_server=mock_websocket_server)

        assert broadcaster.server is mock_websocket_server
        assert broadcaster._buffer_enabled is False
        assert len(broadcaster._event_buffer) == 0

    def test_init_without_server(self):
        """Test initialization without WebSocket server."""
        broadcaster = WebSocketBroadcaster(websocket_server=None)

        assert broadcaster.server is None
        assert broadcaster._buffer_enabled is False

    def test_init_with_buffering(self):
        """Test initialization with event buffering enabled."""
        broadcaster = WebSocketBroadcaster(
            websocket_server=None,
            buffer_enabled=True,
            buffer_size=100,
        )

        assert broadcaster._buffer_enabled is True
        assert broadcaster._event_buffer.maxlen == 100

    def test_create_broadcaster_factory(self, mock_websocket_server: MagicMock):
        """Test create_broadcaster factory function."""
        broadcaster = create_broadcaster(
            websocket_server=mock_websocket_server,
            buffer_enabled=True,
        )

        assert isinstance(broadcaster, WebSocketBroadcaster)
        assert broadcaster.server is mock_websocket_server
        assert broadcaster._buffer_enabled is True


# =============================================================================
# Pool Lifecycle Events Tests
# =============================================================================


@pytest.mark.asyncio
class TestPoolLifecycleEvents:
    """Test pool lifecycle event broadcasting."""

    async def test_broadcast_pool_spawned(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock, sample_pool_config: dict
    ):
        """Test broadcasting pool spawned event."""
        # Act
        result = await broadcaster.broadcast_pool_spawned("pool_abc", sample_pool_config)

        # Assert
        assert result is True
        mock_websocket_server.broadcast_to_room.assert_called_once()

        # Verify event data
        call_args = mock_websocket_server.broadcast_to_room.call_args
        room = call_args[0][0]
        event = call_args[0][1]

        assert room == "pool:pool_abc"
        assert event["event"] == "pool.spawned"
        assert event["data"]["pool_id"] == "pool_abc"
        assert event["data"]["config"] == sample_pool_config
        assert "timestamp" in event["data"]

    async def test_broadcast_pool_scaled(self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock):
        """Test broadcasting pool scaled event."""
        # Act
        result = await broadcaster.broadcast_pool_scaled("pool_abc", 5)

        # Assert
        assert result is True
        mock_websocket_server.broadcast_to_room.assert_called_once()

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "pool.scaled"
        assert event["data"]["pool_id"] == "pool_abc"
        assert event["data"]["worker_count"] == 5

    async def test_broadcast_pool_status_changed_string(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock
    ):
        """Test broadcasting pool status changed with string status."""
        # Act
        result = await broadcaster.broadcast_pool_status_changed("pool_abc", "active")

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "pool.status_changed"
        assert event["data"]["status"]["state"] == "active"

    async def test_broadcast_pool_status_changed_dict(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock
    ):
        """Test broadcasting pool status changed with dict status."""
        # Arrange
        status = {
            "state": "active",
            "worker_count": 5,
            "queue_size": 10,
        }

        # Act
        result = await broadcaster.broadcast_pool_status_changed("pool_abc", status)

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["data"]["status"] == status

    async def test_broadcast_pool_closed(self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock):
        """Test broadcasting pool closed event."""
        # Act
        result = await broadcaster.broadcast_pool_closed("pool_abc")

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "pool.closed"
        assert event["data"]["pool_id"] == "pool_abc"


# =============================================================================
# Worker Events Tests
# =============================================================================


@pytest.mark.asyncio
class TestWorkerEvents:
    """Test worker event broadcasting."""

    async def test_broadcast_worker_added(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock
    ):
        """Test broadcasting worker added event."""
        # Act
        result = await broadcaster.broadcast_worker_added("pool_abc", "worker_1")

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "worker.added"
        assert event["data"]["pool_id"] == "pool_abc"
        assert event["data"]["worker_id"] == "worker_1"

    async def test_broadcast_worker_removed(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock
    ):
        """Test broadcasting worker removed event."""
        # Act
        result = await broadcaster.broadcast_worker_removed("pool_abc", "worker_1")

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "worker.removed"
        assert event["data"]["worker_id"] == "worker_1"

    async def test_broadcast_worker_status_changed(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock
    ):
        """Test broadcasting worker status changed event."""
        # Act
        result = await broadcaster.broadcast_worker_status_changed("pool_abc", "worker_1", "busy")

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "worker.status_changed"
        assert event["data"]["worker_id"] == "worker_1"
        assert event["data"]["status"] == "busy"


# =============================================================================
# Task Events Tests
# =============================================================================


@pytest.mark.asyncio
class TestTaskEvents:
    """Test task event broadcasting."""

    async def test_broadcast_task_assigned(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock, sample_task: dict
    ):
        """Test broadcasting task assigned event."""
        # Act
        result = await broadcaster.broadcast_task_assigned("pool_abc", "worker_1", sample_task)

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "task.assigned"
        assert event["data"]["pool_id"] == "pool_abc"
        assert event["data"]["worker_id"] == "worker_1"
        assert event["data"]["task"] == sample_task

    async def test_broadcast_task_completed(
        self, broadcaster: WebSocketBroadcaster, mock_websocket_server: MagicMock, sample_result: dict
    ):
        """Test broadcasting task completed event."""
        # Act
        result = await broadcaster.broadcast_task_completed("pool_abc", "worker_1", sample_result)

        # Assert
        assert result is True

        call_args = mock_websocket_server.broadcast_to_room.call_args
        event = call_args[0][1]

        assert event["event"] == "task.completed"
        assert event["data"]["result"] == sample_result


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling and graceful degradation."""

    async def test_broadcast_without_server(self):
        """Test broadcasting when server is None."""
        broadcaster = WebSocketBroadcaster(websocket_server=None)

        result = await broadcaster.broadcast_pool_spawned("pool_abc", {})

        assert result is False

    async def test_broadcast_with_server_not_running(self):
        """Test broadcasting when server is not running."""
        mock_server = MagicMock()
        mock_server.is_running = False

        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        result = await broadcaster.broadcast_pool_spawned("pool_abc", {})

        assert result is False

    async def test_broadcast_with_exception(self):
        """Test broadcasting when server raises exception."""
        mock_server = MagicMock()
        mock_server.is_running = True
        mock_server.broadcast_to_room = AsyncMock(side_effect=Exception("Connection error"))

        broadcaster = WebSocketBroadcaster(websocket_server=mock_server)

        result = await broadcaster.broadcast_pool_spawned("pool_abc", {})

        assert result is False

    async def test_set_server(self):
        """Test setting WebSocket server after initialization."""
        broadcaster = WebSocketBroadcaster(websocket_server=None)
        mock_server = MagicMock()
        mock_server.is_running = True
        mock_server.broadcast_to_room = AsyncMock()

        # Act
        broadcaster.set_server(mock_server)
        result = await broadcaster.broadcast_pool_spawned("pool_abc", {})

        # Assert
        assert broadcaster.server is mock_server
        assert result is True


# =============================================================================
# Event Buffering Tests
# =============================================================================


@pytest.mark.asyncio
class TestEventBuffering:
    """Test event buffering functionality."""

    def test_buffer_disabled_by_default(self):
        """Test that buffering is disabled by default."""
        broadcaster = WebSocketBroadcaster(websocket_server=None, buffer_enabled=False)

        assert broadcaster._buffer_enabled is False
        assert len(broadcaster._event_buffer) == 0

    async def test_buffer_enabled(self):
        """Test event buffering when enabled."""
        broadcaster = WebSocketBroadcaster(websocket_server=None, buffer_enabled=True)

        # Broadcast while disconnected
        await broadcaster.broadcast_pool_spawned("pool_abc", {})
        await broadcaster.broadcast_worker_added("pool_abc", "worker_1")

        # Assert
        assert len(broadcaster._event_buffer) == 2
        assert broadcaster._event_buffer[0]["event_name"] == "pool.spawned"
        assert broadcaster._event_buffer[1]["event_name"] == "worker.added"

    async def test_buffer_max_size(self):
        """Test buffer respects maximum size."""
        broadcaster = WebSocketBroadcaster(
            websocket_server=None, buffer_enabled=True, buffer_size=3
        )

        # Add more events than buffer size
        for i in range(5):
            await broadcaster.broadcast_pool_spawned(f"pool_{i}", {})

        # Assert - should only keep last 3 events
        assert len(broadcaster._event_buffer) == 3

    async def test_clear_buffer(self):
        """Test clearing event buffer."""
        broadcaster = WebSocketBroadcaster(websocket_server=None, buffer_enabled=True)

        await broadcaster.broadcast_pool_spawned("pool_abc", {})
        await broadcaster.broadcast_pool_spawned("pool_def", {})

        # Act
        count = broadcaster.clear_buffer()

        # Assert
        assert count == 2
        assert len(broadcaster._event_buffer) == 0

    async def test_flush_buffer_success(self):
        """Test flushing buffered events successfully."""
        # Arrange - buffer events while disconnected
        broadcaster = WebSocketBroadcaster(
            websocket_server=None, buffer_enabled=True, buffer_size=10
        )
        await broadcaster.broadcast_pool_spawned("pool_abc", {})
        await broadcaster.broadcast_pool_spawned("pool_def", {})

        # Connect server and flush
        mock_server = MagicMock()
        mock_server.is_running = True
        mock_server.broadcast_to_room = AsyncMock()
        broadcaster.set_server(mock_server)

        # Act
        flushed = await broadcaster.flush_buffer()

        # Assert
        assert flushed == 2
        assert len(broadcaster._event_buffer) == 0
        assert mock_server.broadcast_to_room.call_count == 2

    async def test_flush_buffer_partial_failure(self):
        """Test flush buffer with some events failing."""
        # Arrange
        broadcaster = WebSocketBroadcaster(
            websocket_server=None, buffer_enabled=True, buffer_size=10
        )
        await broadcaster.broadcast_pool_spawned("pool_abc", {})
        await broadcaster.broadcast_pool_spawned("pool_def", {})

        # Server that fails on second call
        call_count = [0]

        async def failing_broadcast(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("Broadcast failed")

        mock_server = MagicMock()
        mock_server.is_running = True
        mock_server.broadcast_to_room = AsyncMock(side_effect=failing_broadcast)
        broadcaster.set_server(mock_server)

        # Act
        flushed = await broadcaster.flush_buffer()

        # Assert
        assert flushed == 1
        assert len(broadcaster._event_buffer) == 1  # Second event still in buffer


# =============================================================================
# Utility Methods Tests
# =============================================================================


class TestUtilityMethods:
    """Test utility methods."""

    def test_get_timestamp(self):
        """Test timestamp generation."""
        timestamp = WebSocketBroadcaster._get_timestamp()

        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO format

    def test_is_connection_error(self):
        """Test connection error detection."""
        broadcaster = WebSocketBroadcaster()

        assert broadcaster._is_connection_error(Exception("Connection lost")) is True
        assert broadcaster._is_connection_error(Exception("WebSocket error")) is True
        assert broadcaster._is_connection_error(Exception("Network unreachable")) is True
        assert broadcaster._is_connection_error(Exception("Value error")) is False
        assert broadcaster._is_connection_error(Exception("Random error")) is False
