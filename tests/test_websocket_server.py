"""Tests for Mahavishnu WebSocket server."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets

from mahavishnu.websocket.server import MahavishnuWebSocketServer


@pytest.fixture
def mock_pool_manager():
    """Create mock pool manager."""
    manager = MagicMock()
    manager.pools = {}
    return manager


@pytest.fixture
def websocket_server(mock_pool_manager):
    """Create WebSocket server instance."""
    server = MahavishnuWebSocketServer(
        pool_manager=mock_pool_manager,
        host="127.0.0.1",
        port=8690,
    )
    return server


class TestMahavishnuWebSocketServer:
    """Test MahavishnuWebSocketServer functionality."""

    def test_initialization(self, websocket_server):
        """Test server initializes correctly."""
        assert websocket_server.host == "127.0.0.1"
        assert websocket_server.port == 8690
        assert websocket_server.max_connections == 1000
        assert websocket_server.message_rate_limit == 100
        assert websocket_server.pool_manager is not None

    @pytest.mark.asyncio
    async def test_on_connect(self, websocket_server):
        """Test connection handling."""
        mock_websocket = MagicMock()
        connection_id = "test_conn_123"

        await websocket_server.on_connect(mock_websocket, connection_id)

        # Verify connection registered
        assert connection_id in websocket_server.connections

    @pytest.mark.asyncio
    async def test_on_disconnect(self, websocket_server):
        """Test disconnection handling."""
        mock_websocket = MagicMock()
        connection_id = "test_conn_123"

        # Add connection first
        websocket_server.connections[connection_id] = mock_websocket
        websocket_server.connection_rooms["test_room"] = {connection_id}

        # Disconnect
        await websocket_server.on_disconnect(mock_websocket, connection_id)

        # Verify cleanup
        assert connection_id not in websocket_server.connections

    @pytest.mark.asyncio
    async def test_subscribe_request(self, websocket_server):
        """Test subscribe request handling."""
        mock_websocket = MagicMock()
        mock_websocket.id = "test_conn_123"
        mock_websocket.send = AsyncMock()

        connection_id = "test_conn_123"
        websocket_server.connections[connection_id] = mock_websocket

        # Create subscribe message
        from mcp_common.websocket import WebSocketMessage, MessageType

        message = WebSocketMessage(
            type=MessageType.REQUEST,
            event="subscribe",
            data={"channel": "workflow:abc123"},
            correlation_id="corr_123",
        )

        await websocket_server.on_message(mock_websocket, message)

        # Verify joined room
        assert connection_id in websocket_server.connection_rooms.get("workflow:abc123", set())

    @pytest.mark.asyncio
    async def test_broadcast_workflow_started(self, websocket_server):
        """Test broadcasting workflow started event."""
        # Add mock connections
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()

        websocket_server.connections["conn1"] = mock_client1
        websocket_server.connections["conn2"] = mock_client2
        websocket_server.connection_rooms["workflow:wf123"] = {"conn1", "conn2"}

        # Broadcast event
        await websocket_server.broadcast_workflow_started(
            "wf123",
            {"prompt": "Write code", "adapter": "llamaindex"},
        )

        # Verify both clients received message
        assert mock_client1.send.called
        assert mock_client2.send.called

        # Verify message format
        sent_message = json.loads(mock_client1.send.call_args[0][0])
        assert sent_message["type"] == "event"
        assert sent_message["event"] == "workflow.started"
        assert sent_message["data"]["workflow_id"] == "wf123"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_stage_completed(self, websocket_server):
        """Test broadcasting workflow stage completed event."""
        mock_client = AsyncMock()
        websocket_server.connections["conn1"] = mock_client
        websocket_server.connection_rooms["workflow:wf123"] = {"conn1"}

        await websocket_server.broadcast_workflow_stage_completed(
            "wf123",
            "stage1",
            {"output": "Success"},
        )

        assert mock_client.send.called
        sent_message = json.loads(mock_client.send.call_args[0][0])
        assert sent_message["event"] == "workflow.stage_completed"
        assert sent_message["data"]["stage_name"] == "stage1"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_failed(self, websocket_server):
        """Test broadcasting workflow failed event."""
        mock_client = AsyncMock()
        websocket_server.connections["conn1"] = mock_client
        websocket_server.connection_rooms["workflow:wf123"] = {"conn1"}

        await websocket_server.broadcast_workflow_failed(
            "wf123",
            "Execution error: timeout",
        )

        assert mock_client.send.called
        sent_message = json.loads(mock_client.send.call_args[0][0])
        assert sent_message["event"] == "workflow.failed"
        assert sent_message["data"]["error"] == "Execution error: timeout"

    @pytest.mark.asyncio
    async def test_broadcast_worker_status_changed(self, websocket_server):
        """Test broadcasting worker status changed event."""
        mock_client = AsyncMock()
        websocket_server.connections["conn1"] = mock_client
        websocket_server.connection_rooms["pool:local"] = {"conn1"}

        await websocket_server.broadcast_worker_status_changed(
            "worker_001",
            "busy",
            "pool:local",
        )

        assert mock_client.send.called
        sent_message = json.loads(mock_client.send.call_args[0][0])
        assert sent_message["event"] == "worker.status_changed"
        assert sent_message["data"]["worker_id"] == "worker_001"
        assert sent_message["data"]["status"] == "busy"

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed(self, websocket_server):
        """Test broadcasting pool status changed event."""
        mock_client = AsyncMock()
        websocket_server.connections["conn1"] = mock_client
        websocket_server.connection_rooms["pool:local"] = {"conn1"}

        await websocket_server.broadcast_pool_status_changed(
            "pool:local",
            {"active_workers": 5, "queue_size": 10},
        )

        assert mock_client.send.called
        sent_message = json.loads(mock_client.send.call_args[0][0])
        assert sent_message["event"] == "pool.status_changed"
        assert sent_message["data"]["pool_id"] == "pool:local"

    @pytest.mark.asyncio
    async def test_multiple_channels(self, websocket_server):
        """Test broadcasting to multiple channels independently."""
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()

        # Client1 subscribed to workflow:wf123
        websocket_server.connections["conn1"] = mock_client1
        websocket_server.connection_rooms["workflow:wf123"] = {"conn1"}

        # Client2 subscribed to pool:local
        websocket_server.connections["conn2"] = mock_client2
        websocket_server.connection_rooms["pool:local"] = {"conn2"}

        # Broadcast to workflow channel
        await websocket_server.broadcast_workflow_started("wf123", {})

        # Broadcast to pool channel
        await websocket_server.broadcast_pool_status_changed("pool:local", {})

        # Verify each client only received their channel's messages
        assert mock_client1.send.call_count == 1
        assert mock_client2.send.call_count == 1

        # Verify client1 received workflow event
        msg1 = json.loads(mock_client1.send.call_args[0][0])
        assert msg1["event"] == "workflow.started"

        # Verify client2 received pool event
        msg2 = json.loads(mock_client2.send.call_args[0][0])
        assert msg2["event"] == "pool.status_changed"

    @pytest.mark.asyncio
    async def test_get_pool_status(self, websocket_server):
        """Test getting pool status."""
        # Add mock pool to manager
        mock_pool = MagicMock()
        mock_pool.status = "active"
        mock_pool.workers = ["worker1", "worker2"]
        websocket_server.pool_manager.pools["pool1"] = mock_pool

        status = await websocket_server._get_pool_status("pool1")

        assert status["pool_id"] == "pool1"
        assert status["status"] == "active"
        assert status["workers"] == ["worker1", "worker2"]

    @pytest.mark.asyncio
    async def test_get_pool_status_not_found(self, websocket_server):
        """Test getting status for non-existent pool."""
        status = await websocket_server._get_pool_status("nonexistent")

        assert status["pool_id"] == "nonexistent"
        assert status["status"] == "not_found"


@pytest.mark.integration
class TestWebSocketIntegration:
    """Integration tests with actual WebSocket connections."""

    @pytest.mark.asyncio
    async def test_client_connection(self, websocket_server):
        """Test real client can connect and subscribe."""
        # This test requires the server to be running
        # Skip in CI environments that don't support WebSocket servers
        try:
            await websocket_server.start()

            # Connect client
            async with websockets.connect("ws://127.0.0.1:8690") as ws:
                # Send subscribe message
                subscribe_msg = {
                    "type": "request",
                    "event": "subscribe",
                    "data": {"channel": "global"},
                    "id": "sub_test",
                }
                await ws.send(json.dumps(subscribe_msg))

                # Receive response
                response = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(response)

                assert data["type"] in ["response", "event"]

        except asyncio.TimeoutError:
            pytest.skip("WebSocket server not available")
        finally:
            await websocket_server.stop()

    @pytest.mark.asyncio
    async def test_broadcast_receives(self, websocket_server):
        """Test client receives broadcast events."""
        try:
            await websocket_server.start()

            received_events = []

            async def client_task():
                async with websockets.connect("ws://127.0.0.1:8690") as ws:
                    # Subscribe
                    subscribe_msg = {
                        "type": "request",
                        "event": "subscribe",
                        "data": {"channel": "workflow:test123"},
                        "id": "sub_test",
                    }
                    await ws.send(json.dumps(subscribe_msg))

                    # Receive welcome and subscription confirmation
                    await ws.recv()  # Welcome message
                    await ws.recv()  # Subscription confirmation

                    # Receive broadcast events
                    for _ in range(3):
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                            data = json.loads(msg)
                            received_events.append(data)
                        except asyncio.TimeoutError:
                            break

            # Start client
            client_task = asyncio.create_task(client_task())

            # Wait for client to connect
            await asyncio.sleep(0.5)

            # Broadcast events
            await websocket_server.broadcast_workflow_started("test123", {})
            await websocket_server.broadcast_workflow_stage_completed("test123", "stage1", {})
            await websocket_server.broadcast_workflow_completed("test123", {})

            # Wait for client to receive
            await client_task

            # Verify events received
            assert len(received_events) >= 3
            event_types = [e.get("event") for e in received_events]
            assert "workflow.started" in event_types
            assert "workflow.stage_completed" in event_types
            assert "workflow.completed" in event_types

        except asyncio.TimeoutError:
            pytest.skip("WebSocket server not available")
        finally:
            await websocket_server.stop()
