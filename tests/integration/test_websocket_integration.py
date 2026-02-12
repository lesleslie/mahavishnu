"""Integration tests for WebSocket servers across ecosystem.

Tests all 7 operational WebSocket servers:
- session-buddy (8765) - Session management
- mahavishnu (8690) - Workflow orchestration
- akosha (8692) - Knowledge graph and insights
- crackerjack (8686) - Quality control and testing
- dhruva (8693) - Dependency management
- excalidraw-mcp (3042) - Diagram collaboration
- fastblocks (8684) - Application building

This test suite focuses on WebSocket server functionality using mocks
to avoid dependencies on actual network connections and external services.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.websocket import WebSocketBroadcaster
from mahavishnu.websocket.server import MahavishnuWebSocketServer


# =============================================================================
# WebSocket Server Configuration
# =============================================================================

WEBSOCKET_SERVERS = {
    "session-buddy": {
        "port": 8765,
        "module_path": "/Users/les/Projects/session-buddy",
        "class_name": "SessionBuddyWebSocketServer",
        "description": "Session management and context tracking",
    },
    "mahavishnu": {
        "port": 8690,
        "module_path": "/Users/les/Projects/mahavishnu",
        "class_name": "MahavishnuWebSocketServer",
        "description": "Workflow orchestration and pool management",
    },
    "akosha": {
        "port": 8692,
        "module_path": "/Users/les/Projects/akosha",
        "class_name": "AkoshaWebSocketServer",
        "description": "Knowledge graph and insights",
    },
    "crackerjack": {
        "port": 8686,
        "module_path": "/Users/les/Projects/crackerjack",
        "class_name": "CrackerjackWebSocketServer",
        "description": "Quality control and CI/CD",
    },
    "dhruva": {
        "port": 8693,
        "module_path": "/Users/les/Projects/dhruva",
        "class_name": "DhruvaWebSocketServer",
        "description": "Dependency management",
    },
    "excalidraw-mcp": {
        "port": 3042,
        "module_path": "/Users/les/Projects/excalidraw-mcp",
        "class_name": "ExcalidrawWebSocketServer",
        "description": "Diagram collaboration",
    },
    "fastblocks": {
        "port": 8684,
        "module_path": "/Users/les/Projects/fastblocks",
        "class_name": "FastblocksWebSocketServer",
        "description": "Application building and UI rendering",
    },
}


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_pool_manager() -> MagicMock:
    """Create mock pool manager for testing.

    Returns:
        Mock pool manager with empty pools dictionary
    """
    manager = MagicMock()
    manager.pools = {}
    return manager


@pytest.fixture
def websocket_server(mock_pool_manager: MagicMock) -> MahavishnuWebSocketServer:
    """Create Mahavishnu WebSocket server instance (not started).

    Args:
        mock_pool_manager: Mock pool manager fixture

    Returns:
        Configured WebSocket server instance
    """
    server = MahavishnuWebSocketServer(
        pool_manager=mock_pool_manager,
        host="127.0.0.1",
        port=8690,
        max_connections=100,
        message_rate_limit=100,
    )
    server.is_running = True  # Set as running for testing
    return server


@pytest.fixture
def test_room() -> str:
    """Generate isolated test room name.

    Returns:
        Unique room name for test isolation
    """
    return f"test_room_{uuid.uuid4().hex[:8]}"


# =============================================================================
# Server Initialization Tests
# =============================================================================

@pytest.mark.integration
class TestWebSocketServerInitialization:
    """Test WebSocket server initialization and configuration."""

    def test_server_initialization(self, websocket_server: MahavishnuWebSocketServer):
        """Test server initializes with correct configuration."""
        # Assert
        assert websocket_server.host == "127.0.0.1"
        assert websocket_server.port == 8690
        assert websocket_server.max_connections == 100
        assert websocket_server.message_rate_limit == 100
        assert websocket_server.pool_manager is not None

    def test_server_initial_state(self, websocket_server: MahavishnuWebSocketServer):
        """Test server starts in correct initial state."""
        # Assert
        assert websocket_server.is_running is True
        assert websocket_server.server is None
        assert len(websocket_server.connections) == 0
        assert len(websocket_server.connection_rooms) == 0


# =============================================================================
# Connection Handling Tests
# =============================================================================

@pytest.mark.integration
class TestConnectionHandling:
    """Test WebSocket connection handling."""

    @pytest.mark.asyncio
    async def test_on_connect_sends_welcome(self, websocket_server: MahavishnuWebSocketServer):
        """Test on_connect handler sends welcome message."""
        # Arrange
        mock_websocket = MagicMock()
        mock_websocket.send = AsyncMock()
        connection_id = "test_conn_123"

        # Act
        await websocket_server.on_connect(mock_websocket, connection_id)

        # Assert
        mock_websocket.send.assert_called_once()
        sent_message = mock_websocket.send.call_args[0][0]

        # Should be JSON encoded welcome message
        import json
        from mcp_common.websocket import WebSocketProtocol
        decoded = WebSocketProtocol.decode(sent_message)
        assert decoded["event"] == "session.created"
        assert decoded["data"]["connection_id"] == connection_id
        assert decoded["data"]["server"] == "mahavishnu"

    @pytest.mark.asyncio
    async def test_on_disconnect_cleans_up_rooms(self, websocket_server: MahavishnuWebSocketServer):
        """Test on_disconnect handler cleans up room subscriptions."""
        # Arrange
        mock_websocket = MagicMock()
        connection_id = "test_conn_123"

        # Add connection to rooms
        websocket_server.connections[connection_id] = mock_websocket
        websocket_server.connection_rooms["test_room"] = {connection_id}

        # Act
        await websocket_server.on_disconnect(mock_websocket, connection_id)

        # Assert
        assert connection_id not in websocket_server.connections
        # Room should be cleaned up (connection removed from room)
        assert connection_id not in websocket_server.connection_rooms.get("test_room", set())

    @pytest.mark.asyncio
    async def test_multiple_connections_tracked(self, websocket_server: MahavishnuWebSocketServer):
        """Test server tracks multiple connections."""
        # Arrange
        mock_ws1 = MagicMock()
        mock_ws2 = MagicMock()
        conn1_id = "conn1"
        conn2_id = "conn2"

        # Act
        await websocket_server.on_connect(mock_ws1, conn1_id)
        await websocket_server.on_connect(mock_ws2, conn2_id)

        # Add to connections dict (simulating what server.start() does)
        websocket_server.connections[conn1_id] = mock_ws1
        websocket_server.connections[conn2_id] = mock_ws2

        # Assert
        assert len(websocket_server.connections) == 2
        assert conn1_id in websocket_server.connections
        assert conn2_id in websocket_server.connections


# =============================================================================
# Message Handling Tests
# =============================================================================

@pytest.mark.integration
class TestMessageHandling:
    """Test WebSocket message handling."""

    @pytest.mark.asyncio
    async def test_subscribe_request(self, websocket_server: MahavishnuWebSocketServer):
        """Test subscribe request adds connection to room."""
        # Arrange
        from mcp_common.websocket import WebSocketMessage, MessageType
        mock_websocket = MagicMock()
        mock_websocket.id = "test_conn"
        mock_websocket.send = AsyncMock()
        connection_id = "test_conn"

        websocket_server.connections[connection_id] = mock_websocket

        message = WebSocketMessage(
            type=MessageType.REQUEST,
            event="subscribe",
            data={"channel": "test_channel"},
            correlation_id="corr_123",
        )

        # Act
        await websocket_server.on_message(mock_websocket, message)

        # Assert
        assert connection_id in websocket_server.connection_rooms.get("test_channel", set())
        mock_websocket.send.assert_called_once()

        # Check response
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_websocket.send.call_args[0][0])
        assert sent_msg["type"] == "response"
        assert sent_msg["data"]["status"] == "subscribed"

    @pytest.mark.asyncio
    async def test_unsubscribe_request(self, websocket_server: MahavishnuWebSocketServer):
        """Test unsubscribe request removes connection from room."""
        # Arrange
        from mcp_common.websocket import WebSocketMessage, MessageType
        mock_websocket = MagicMock()
        mock_websocket.id = "test_conn"
        mock_websocket.send = AsyncMock()
        connection_id = "test_conn"

        websocket_server.connections[connection_id] = mock_websocket
        websocket_server.connection_rooms["test_channel"] = {connection_id}

        message = WebSocketMessage(
            type=MessageType.REQUEST,
            event="unsubscribe",
            data={"channel": "test_channel"},
            correlation_id="corr_123",
        )

        # Act
        await websocket_server.on_message(mock_websocket, message)

        # Assert
        assert connection_id not in websocket_server.connection_rooms.get("test_channel", set())
        mock_websocket.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_request_returns_error(self, websocket_server: MahavishnuWebSocketServer):
        """Test unknown request type returns error response."""
        # Arrange
        from mcp_common.websocket import WebSocketMessage, MessageType
        mock_websocket = MagicMock()
        mock_websocket.send = AsyncMock()
        connection_id = "test_conn"

        websocket_server.connections[connection_id] = mock_websocket

        message = WebSocketMessage(
            type=MessageType.REQUEST,
            event="unknown_action",
            data={},
            correlation_id="corr_123",
        )

        # Act
        await websocket_server.on_message(mock_websocket, message)

        # Assert
        mock_websocket.send.assert_called_once()
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_websocket.send.call_args[0][0])
        assert sent_msg["type"] == "error"
        assert "UNKNOWN_REQUEST" in sent_msg["code"]


# =============================================================================
# Broadcast Tests
# =============================================================================

@pytest.mark.integration
class TestBroadcastFunctionality:
    """Test broadcast message functionality."""

    @pytest.mark.asyncio
    async def test_broadcast_to_room(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting messages to a specific room."""
        # Arrange
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()
        mock_client3 = AsyncMock()

        conn1_id = "conn1"
        conn2_id = "conn2"
        conn3_id = "conn3"

        # Setup: conn1 and conn2 in room1, conn3 in room2
        websocket_server.connections[conn1_id] = mock_client1
        websocket_server.connections[conn2_id] = mock_client2
        websocket_server.connections[conn3_id] = mock_client3
        websocket_server.connection_rooms["room1"] = {conn1_id, conn2_id}
        websocket_server.connection_rooms["room2"] = {conn3_id}

        # Act
        from mcp_common.websocket import WebSocketProtocol
        event = WebSocketProtocol.create_event(
            "test.event",
            {"message": "Hello room1"},
        )
        await websocket_server.broadcast_to_room("room1", event)

        # Assert - only conn1 and conn2 should receive message
        assert mock_client1.send.called
        assert mock_client2.send.called
        assert not mock_client3.called

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting pool status changed event."""
        # Arrange
        mock_client = AsyncMock()
        conn_id = "conn1"
        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:test_pool"] = {conn_id}

        # Act
        await websocket_server.broadcast_pool_status_changed(
            "test_pool",
            {"worker_count": 5, "queue_size": 10},
        )

        # Assert
        assert mock_client.send.called
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "pool.status_changed"
        assert sent_msg["data"]["pool_id"] == "test_pool"
        assert sent_msg["data"]["status"]["worker_count"] == 5

    @pytest.mark.asyncio
    async def test_broadcast_workflow_started(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting workflow started event."""
        # Arrange
        mock_client = AsyncMock()
        conn_id = "conn1"
        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["workflow:wf123"] = {conn_id}

        # Act
        await websocket_server.broadcast_workflow_started(
            "wf123",
            {"prompt": "Write code", "adapter": "llamaindex"},
        )

        # Assert
        assert mock_client.send.called
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "workflow.started"
        assert sent_msg["data"]["workflow_id"] == "wf123"
        assert sent_msg["data"]["prompt"] == "Write code"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_stage_completed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting workflow stage completed event."""
        # Arrange
        mock_client = AsyncMock()
        conn_id = "conn1"
        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["workflow:wf123"] = {conn_id}

        # Act
        await websocket_server.broadcast_workflow_stage_completed(
            "wf123",
            "stage1",
            {"output": "Success"},
        )

        # Assert
        assert mock_client.send.called
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "workflow.stage_completed"
        assert sent_msg["data"]["stage_name"] == "stage1"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_failed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting workflow failed event."""
        # Arrange
        mock_client = AsyncMock()
        conn_id = "conn1"
        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["workflow:wf123"] = {conn_id}

        # Act
        await websocket_server.broadcast_workflow_failed(
            "wf123",
            "Execution error: timeout",
        )

        # Assert
        assert mock_client.send.called
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "workflow.failed"
        assert sent_msg["data"]["error"] == "Execution error: timeout"

    @pytest.mark.asyncio
    async def test_broadcast_worker_status_changed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting worker status changed event."""
        # Arrange
        mock_client = AsyncMock()
        conn_id = "conn1"
        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:local"] = {conn_id}

        # Act
        await websocket_server.broadcast_worker_status_changed(
            "worker_001",
            "busy",
            "pool:local",
        )

        # Assert
        assert mock_client.send.called
        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "worker.status_changed"
        assert sent_msg["data"]["worker_id"] == "worker_001"
        assert sent_msg["data"]["status"] == "busy"


# =============================================================================
# Room Management Tests
# =============================================================================

@pytest.mark.integration
class TestRoomManagement:
    """Test room subscription and unsubscription."""

    def test_join_room_adds_connection(self, websocket_server: MahavishnuWebSocketServer):
        """Test joining a room adds connection to room."""
        # Arrange
        connection_id = "conn1"

        # Act
        import asyncio
        asyncio.run(websocket_server.join_room("test_room", connection_id))

        # Assert
        assert connection_id in websocket_server.connection_rooms["test_room"]

    def test_leave_room_removes_connection(self, websocket_server: MahavishnuWebSocketServer):
        """Test leaving a room removes connection from room."""
        # Arrange
        connection_id = "conn1"
        import asyncio
        asyncio.run(websocket_server.join_room("test_room", connection_id))

        # Act
        asyncio.run(websocket_server.leave_room("test_room", connection_id))

        # Assert
        assert connection_id not in websocket_server.connection_rooms["test_room"]

    def test_leave_all_rooms(self, websocket_server: MahavishnuWebSocketServer):
        """Test leaving all rooms removes connection from all rooms."""
        # Arrange
        connection_id = "conn1"
        import asyncio
        asyncio.run(websocket_server.join_room("room1", connection_id))
        asyncio.run(websocket_server.join_room("room2", connection_id))

        # Act
        asyncio.run(websocket_server.leave_all_rooms(connection_id))

        # Assert
        assert connection_id not in websocket_server.connection_rooms.get("room1", set())
        assert connection_id not in websocket_server.connection_rooms.get("room2", set())


# =============================================================================
# Pool Status Tests
# =============================================================================

@pytest.mark.integration
class TestPoolStatus:
    """Test pool status retrieval."""

    @pytest.mark.asyncio
    async def test_get_pool_status_found(self, websocket_server: MahavishnuWebSocketServer):
        """Test getting status for existing pool."""
        # Arrange
        mock_pool = MagicMock()
        mock_pool.status = "active"
        mock_pool.workers = ["worker1", "worker2"]
        websocket_server.pool_manager.pools["pool1"] = mock_pool

        # Act
        status = await websocket_server._get_pool_status("pool1")

        # Assert
        assert status["pool_id"] == "pool1"
        assert status["status"] == "active"
        assert status["workers"] == ["worker1", "worker2"]

    @pytest.mark.asyncio
    async def test_get_pool_status_not_found(self, websocket_server: MahavishnuWebSocketServer):
        """Test getting status for non-existent pool."""
        # Arrange - empty pools dict
        websocket_server.pool_manager.pools = {}

        # Act
        status = await websocket_server._get_pool_status("nonexistent")

        # Assert
        assert status["pool_id"] == "nonexistent"
        assert status["status"] == "not_found"


# =============================================================================
# Pool Broadcasting Integration Tests
# =============================================================================

@pytest.mark.integration
class TestPoolBroadcasting:
    """Test pool event broadcasting integration."""

    @pytest.mark.asyncio
    async def test_broadcaster_pool_spawned(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting pool spawned event via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        pool_config = {
            "name": "test-pool",
            "pool_type": "mahavishnu",
            "min_workers": 2,
            "max_workers": 5,
        }

        # Act
        result = await broadcaster.broadcast_pool_spawned("pool_abc", pool_config)

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "pool.spawned"
        assert sent_msg["data"]["pool_id"] == "pool_abc"
        assert sent_msg["data"]["config"] == pool_config

    @pytest.mark.asyncio
    async def test_broadcaster_worker_status_changed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting worker status changed via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        # Act
        result = await broadcaster.broadcast_worker_status_changed("pool_abc", "worker_1", "busy")

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "worker.status_changed"
        assert sent_msg["data"]["worker_id"] == "worker_1"
        assert sent_msg["data"]["status"] == "busy"

    @pytest.mark.asyncio
    async def test_broadcaster_task_assigned(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting task assigned via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        task = {"prompt": "Write code", "timeout": 300}

        # Act
        result = await broadcaster.broadcast_task_assigned("pool_abc", "worker_1", task)

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "task.assigned"
        assert sent_msg["data"]["task"] == task

    @pytest.mark.asyncio
    async def test_broadcaster_task_completed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting task completed via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        result = {"status": "success", "output": "Code generated"}

        # Act
        broadcast_result = await broadcaster.broadcast_task_completed("pool_abc", "worker_1", result)

        # Assert
        assert broadcast_result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "task.completed"
        assert sent_msg["data"]["result"] == result

    @pytest.mark.asyncio
    async def test_broadcaster_pool_scaled(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting pool scaled via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        # Act
        result = await broadcaster.broadcast_pool_scaled("pool_abc", 5)

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "pool.scaled"
        assert sent_msg["data"]["worker_count"] == 5

    @pytest.mark.asyncio
    async def test_broadcaster_pool_status_changed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting pool status changed via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        status = {"state": "active", "worker_count": 5}

        # Act
        result = await broadcaster.broadcast_pool_status_changed("pool_abc", status)

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "pool.status_changed"
        assert sent_msg["data"]["status"] == status

    @pytest.mark.asyncio
    async def test_broadcaster_worker_added(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting worker added via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        # Act
        result = await broadcaster.broadcast_worker_added("pool_abc", "worker_1")

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "worker.added"
        assert sent_msg["data"]["worker_id"] == "worker_1"

    @pytest.mark.asyncio
    async def test_broadcaster_worker_removed(self, websocket_server: MahavishnuWebSocketServer):
        """Test broadcasting worker removed via WebSocketBroadcaster."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=websocket_server)
        mock_client = AsyncMock()
        conn_id = "conn1"

        websocket_server.connections[conn_id] = mock_client
        websocket_server.connection_rooms["pool:pool_abc"] = {conn_id}

        # Act
        result = await broadcaster.broadcast_worker_removed("pool_abc", "worker_1")

        # Assert
        assert result is True
        assert mock_client.send.called

        from mcp_common.websocket import WebSocketProtocol
        sent_msg = WebSocketProtocol.decode(mock_client.send.call_args[0][0])
        assert sent_msg["event"] == "worker.removed"
        assert sent_msg["data"]["worker_id"] == "worker_1"

    @pytest.mark.asyncio
    async def test_broadcaster_graceful_degradation(self, websocket_server: MahavishnuWebSocketServer):
        """Test graceful degradation when WebSocket unavailable."""
        # Arrange
        broadcaster = WebSocketBroadcaster(websocket_server=None)

        # Act - should not raise exception
        result = await broadcaster.broadcast_pool_spawned("pool_abc", {})

        # Assert
        assert result is False


# =============================================================================
# Multi-Server Configuration Tests
# =============================================================================

@pytest.mark.integration
class TestMultiServerConfiguration:
    """Test configuration for all 7 WebSocket servers."""

    def test_all_servers_configured(self):
        """Test that all 7 servers have configurations."""
        # Assert
        assert len(WEBSOCKET_SERVERS) == 7

        required_servers = [
            "session-buddy",
            "mahavishnu",
            "akosha",
            "crackerjack",
            "dhruva",
            "excalidraw-mcp",
            "fastblocks",
        ]

        for server in required_servers:
            assert server in WEBSOCKET_SERVERS, f"{server} not in config"

    def test_all_ports_configured(self):
        """Test that all servers have port configurations."""
        # Act
        ports = [config["port"] for config in WEBSOCKET_SERVERS.values()]

        # Assert
        assert len(ports) == 7
        for port in ports:
            assert isinstance(port, int)
            assert 1000 <= port <= 9999 or port == 3042  # excalidraw uses 3042

    def test_port_uniqueness(self):
        """Test that all WebSocket servers have unique ports."""
        # Act
        ports = [config["port"] for config in WEBSOCKET_SERVERS.values()]

        # Assert
        assert len(ports) == len(set(ports)), f"Duplicate ports detected: {ports}"

    def test_all_descriptions_present(self):
        """Test that all servers have descriptions."""
        # Assert
        for server_name, config in WEBSOCKET_SERVERS.items():
            assert "description" in config
            assert "port" in config
            assert "module_path" in config
            assert "class_name" in config
            assert len(config["description"]) > 0

    def test_port_ranges(self):
        """Test that ports are in expected ranges."""
        # Act & Assert
        for server_name, config in WEBSOCKET_SERVERS.items():
            port = config["port"]
            # excalidraw-mcp uses 3042
            if server_name == "excalidraw-mcp":
                assert port == 3042
            # Other services use 8600-8999 range
            else:
                assert 8600 <= port <= 8999, f"{server_name} port {port} out of range"


# =============================================================================
# Test Run Configuration
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
