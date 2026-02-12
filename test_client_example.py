"""Test script for WebSocket client functionality."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, "/Users/les/Projects/mahavishnu")

from examples.websocket_client_examples import MahavishnuWebSocketClient


async def test_client_initialization():
    """Test client initialization."""
    print("Testing WebSocket client initialization...")

    client = MahavishnuWebSocketClient("ws://127.0.0.1:8690")

    assert client.uri == "ws://127.0.0.1:8690"
    assert not client.connected

    print("✓ Client initialized successfully")
    print(f"  - URI: {client.uri}")


async def test_client_subscription():
    """Test client subscription functionality."""
    print("\nTesting client subscription...")

    # Mock the websocket connection
    client = MahavishnuWebSocketClient("ws://127.0.0.1:8690")

    # Create mock websocket with async methods
    mock_ws = MagicMock()
    mock_ws.send = AsyncMock()

    # Mock recv to return subscription confirmation
    async def mock_recv():
        return json.dumps({
            "type": "response",
            "event": "subscribe",
            "data": {"status": "subscribed", "channel": "workflow:test123"}
        })

    mock_ws.recv = mock_recv

    # Set up client state
    client.websocket = mock_ws
    client.connected = True

    # Test subscription
    await client.subscribe_to_channel("workflow:test123")

    # Verify subscribe message was sent
    assert mock_ws.send.called
    sent_message = json.loads(mock_ws.send.call_args[0][0])
    assert sent_message["type"] == "request"
    assert sent_message["event"] == "subscribe"
    assert sent_message["data"]["channel"] == "workflow:test123"

    print("✓ Client subscription works correctly")


async def test_broadcaster_helper():
    """Test WebSocketBroadcaster helper."""
    print("\nTesting WebSocketBroadcaster helper...")

    from mahavishnu.websocket.integration import WebSocketBroadcaster

    # Create mock server
    mock_server = MagicMock()
    mock_server.is_running = True
    mock_server.connection_rooms = {"workflow:test": {"conn1"}}
    mock_server.connections = {"conn1": AsyncMock()}

    # Make broadcast methods async
    async def mock_broadcast(*args, **kwargs):
        pass

    mock_server.broadcast_workflow_started = mock_broadcast

    broadcaster = WebSocketBroadcaster(mock_server)

    # Test workflow started broadcast
    result = await broadcaster.workflow_started("test123", {"prompt": "Test"})

    assert result == True
    print("✓ WebSocketBroadcaster works correctly")


def main():
    """Run all client tests."""
    print("=" * 60)
    print("WebSocket Client Tests")
    print("=" * 60)

    try:
        asyncio.run(test_client_initialization())
        asyncio.run(test_client_subscription())
        asyncio.run(test_broadcaster_helper())

        print("\n" + "=" * 60)
        print("✓ ALL CLIENT TESTS PASSED")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
