# WebSocket Phase 3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement WebSocket servers for enhanced collaboration services (dhruva, excalidraw, fastblocks) with real-time event broadcasting and MCP integration.

**Architecture:** Room-based WebSocket broadcasting using mcp-common abstraction layer. Each service extends WebSocketServer base class with domain-specific broadcast methods and MCP monitoring tools.

**Tech Stack:** mcp-common.websocket, FastMCP, Python 3.11+, async/await, Pydantic validation

---

## Task 1: Dhruva WebSocket Server (Port 8693)

**Purpose:** Real-time adapter distribution events for Dhruva storage service

**Files:**
- Create: `/Users/les/Projects/dhruva/dhruva/websocket/__init__.py`
- Create: `/Users/les/Projects/dhruva/dhruva/websocket/server.py`
- Create: `/Users/les/Projects/dhruva/dhruva/mcp/websocket_tools.py`
- Create: `/Users/les/Projects/dhruva/dhruva/websocket/integration.py`
- Create: `/Users/les/Projects/dhruva/examples/websocket_client_examples.py`
- Create: `/Users/les/Projects/dhruva/tests/test_websocket_server.py`
- Modify: `/Users/les/Projects/dhruva/dhruva/__init__.py`

**Step 1: Create package initialization**

Create: `/Users/les/Projects/dhruva/dhruva/websocket/__init__.py`

```python
"""WebSocket server for Dhruva adapter distribution events."""
from .server import DhruvaWebSocketServer

__all__ = ["DhruvaWebSocketServer"]
```

**Step 2: Implement WebSocket server**

Create: `/Users/les/Projects/dhruva/dhruva/websocket/server.py`

```python
"""WebSocket server for Dhruva adapter distribution.

Broadcasts real-time events for:
- Adapter storage and retrieval
- Adapter updates and versioning
- Storage operations
- Distribution events
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mcp_common.websocket import (
    MessageType,
    WebSocketMessage,
    WebSocketProtocol,
    WebSocketServer,
)

# Import EventTypes from protocol module
from mcp_common.websocket.protocol import EventTypes

logger = logging.getLogger(__name__)


class DhruvaWebSocketServer(WebSocketServer):
    """WebSocket server for Dhruva adapter distribution.

    Broadcasts real-time events for:
    - Adapter storage events
    - Adapter updates
    - Version management
    - Storage operations

    Channels:
    - adapter:{adapter_id} - Adapter-specific events
    - storage:{storage_type} - Storage backend events
    - distribution - Distribution-wide events
    - global - System-wide events

    Attributes:
        storage_manager: Dhruva storage manager instance
        host: Server host address
        port: Server port number (default: 8693)
    """

    def __init__(
        self,
        storage_manager: Any,
        host: str = "127.0.0.1",
        port: int = 8693,
        max_connections: int = 1000,
        message_rate_limit: int = 100,
    ):
        """Initialize Dhruva WebSocket server.

        Args:
            storage_manager: StorageManager instance for adapter state
            host: Server host address (default: "127.0.0.1")
            port: Server port number (default: 8693)
            max_connections: Maximum concurrent connections (default: 1000)
            message_rate_limit: Messages per second per connection (default: 100)
        """
        super().__init__(
            host=host,
            port=port,
            max_connections=max_connections,
            message_rate_limit=message_rate_limit,
        )

        self.storage_manager = storage_manager
        logger.info(f"DhruvaWebSocketServer initialized: {host}:{port}")

    async def on_connect(self, websocket: Any, connection_id: str) -> None:
        """Handle new WebSocket connection.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        logger.info(f"Client connected: {connection_id}")

        # Send welcome message
        welcome = WebSocketProtocol.create_event(
            EventTypes.SESSION_CREATED,
            {
                "connection_id": connection_id,
                "server": "dhruva",
                "message": "Connected to Dhruva adapter distribution",
            },
        )
        await websocket.send(WebSocketProtocol.encode(welcome))

    async def on_disconnect(self, websocket: Any, connection_id: str) -> None:
        """Handle WebSocket disconnection.

        Args:
            websocket: WebSocket connection object
            connection_id: Unique connection identifier
        """
        logger.info(f"Client disconnected: {connection_id}")
        await self.leave_all_rooms(connection_id)

    async def on_message(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle incoming WebSocket message.

        Args:
            websocket: WebSocket connection object
            message: Decoded message
        """
        if message.type == MessageType.REQUEST:
            await self._handle_request(websocket, message)
        elif message.type == MessageType.EVENT:
            await self._handle_event(websocket, message)
        else:
            logger.warning(f"Unhandled message type: {message.type}")

    async def _handle_request(
        self, websocket: Any, message: WebSocketMessage
    ) -> None:
        """Handle request message (expects response)."""
        if message.event == "subscribe":
            channel = message.data.get("channel")
            if channel:
                import uuid
                connection_id = getattr(websocket, "id", str(uuid.uuid4()))
                await self.join_room(channel, connection_id)

                response = WebSocketProtocol.create_response(
                    message,
                    {"status": "subscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "unsubscribe":
            channel = message.data.get("channel")
            if channel:
                import uuid
                connection_id = getattr(websocket, "id", str(uuid.uuid4()))
                await self.leave_room(channel, connection_id)

                response = WebSocketProtocol.create_response(
                    message,
                    {"status": "unsubscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

        elif message.event == "get_adapter_status":
            adapter_id = message.data.get("adapter_id")
            if adapter_id and self.storage_manager:
                status = await self._get_adapter_status(adapter_id)
                response = WebSocketProtocol.create_response(message, status)
                await websocket.send(WebSocketProtocol.encode(response))

        else:
            error = WebSocketProtocol.create_error(
                error_code="UNKNOWN_REQUEST",
                error_message=f"Unknown request event: {message.event}",
                correlation_id=message.correlation_id,
            )
            await websocket.send(WebSocketProtocol.encode(error))

    async def _handle_event(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle event message (no response expected)."""
        logger.debug(f"Received client event: {message.event}")

    async def _get_adapter_status(self, adapter_id: str) -> dict:
        """Get adapter status from storage manager.

        Args:
            adapter_id: Adapter identifier

        Returns:
            Adapter status dictionary
        """
        try:
            if hasattr(self.storage_manager, "get_adapter"):
                adapter = await self.storage_manager.get_adapter(adapter_id)
                return {
                    "adapter_id": adapter_id,
                    "status": "found",
                    "adapter": adapter
                }
            else:
                return {"adapter_id": adapter_id, "status": "not_found"}
        except Exception as e:
            logger.error(f"Error getting adapter status: {e}")
            return {"adapter_id": adapter_id, "status": "error", "error": str(e)}

    # Broadcast methods for adapter events

    async def broadcast_adapter_stored(
        self, adapter_id: str, metadata: dict
    ) -> None:
        """Broadcast adapter stored event.

        Args:
            adapter_id: Adapter identifier
            metadata: Adapter metadata (type, version, etc.)
        """
        event = WebSocketProtocol.create_event(
            EventTypes.ADAPTER_STORED,
            {
                "adapter_id": adapter_id,
                "timestamp": self._get_timestamp(),
                **metadata
            },
            room=f"adapter:{adapter_id}"
        )
        await self.broadcast_to_room(f"adapter:{adapter_id}", event)

    async def broadcast_adapter_updated(
        self, adapter_id: str, metadata: dict
    ) -> None:
        """Broadcast adapter updated event.

        Args:
            adapter_id: Adapter identifier
            metadata: Update metadata
        """
        event = WebSocketProtocol.create_event(
            EventTypes.ADAPTER_UPDATED,
            {
                "adapter_id": adapter_id,
                "timestamp": self._get_timestamp(),
                **metadata
            },
            room=f"adapter:{adapter_id}"
        )
        await self.broadcast_to_room(f"adapter:{adapter_id}", event)

    async def broadcast_storage_event(
        self, storage_type: str, event_data: dict
    ) -> None:
        """Broadcast storage operation event.

        Args:
            storage_type: Storage backend type
            event_data: Event details
        """
        event = WebSocketProtocol.create_event(
            EventTypes.STORAGE_EVENT,
            {
                "storage_type": storage_type,
                "timestamp": self._get_timestamp(),
                **event_data
            },
            room=f"storage:{storage_type}"
        )
        await self.broadcast_to_room(f"storage:{storage_type}", event)

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime, UTC
        return datetime.now(UTC).isoformat()
```

**Step 3: Create MCP integration tools**

Create: `/Users/les/Projects/dhruva/dhruva/mcp/websocket_tools.py`

```python
"""MCP tools for Dhruva WebSocket monitoring and management."""

from typing import Any
from fastmcp import FastMCP


def register_websocket_tools(
    server: FastMCP,
    websocket_server: Any,
) -> None:
    """Register WebSocket monitoring tools with MCP server.

    Args:
        server: FastMCP server instance
        websocket_server: DhruvaWebSocketServer instance
    """

    @server.tool()
    async def websocket_health_check() -> dict:
        """Check WebSocket server health and status.

        Returns:
            Health status dictionary with server state
        """
        if websocket_server is None or not websocket_server.is_running:
            return {
                "status": "stopped",
                "host": "127.0.0.1",
                "port": 8693,
                "server": "dhruva"
            }

        return {
            "status": "healthy",
            "host": "127.0.0.1",
            "port": 8693,
            "server": "dhruva",
            "connections": len(websocket_server.connections),
            "rooms": len(websocket_server.connection_rooms),
        }

    @server.tool()
    async def websocket_get_status() -> dict:
        """Get detailed WebSocket server status.

        Returns:
            Detailed status including connections and rooms
        """
        if websocket_server is None:
            return {"error": "WebSocket server not initialized"}

        return {
            "server": "dhruva",
            "is_running": websocket_server.is_running,
            "connections": list(websocket_server.connections.keys()),
            "rooms": {
                room: list(connections)
                for room, connections in websocket_server.connection_rooms.items()
            },
        }

    @server.tool()
    async def websocket_list_rooms() -> dict:
        """List all active rooms and their subscribers.

        Returns:
            Dictionary mapping rooms to subscriber counts
        """
        if websocket_server is None:
            return {"error": "WebSocket server not initialized"}

        return {
            "rooms": {
                room: len(connections)
                for room, connections in websocket_server.connection_rooms.items()
            }
        }

    @server.tool()
    async def websocket_broadcast_test_event(channel: str) -> dict:
        """Broadcast a test event to a channel (development only).

        Args:
            channel: Channel to broadcast test event to

        Returns:
            Broadcast result confirmation
        """
        if websocket_server is None:
            return {"error": "WebSocket server not initialized"}

        from mcp_common.websocket import WebSocketProtocol

        test_event = WebSocketProtocol.create_event(
            "test.event",
            {"message": "Test event from Dhruva WebSocket"},
            room=channel
        )

        await websocket_server.broadcast_to_room(channel, test_event)

        return {
            "status": "broadcast",
            "channel": channel,
            "subscribers": len(websocket_server.connection_rooms.get(channel, set()))
        }

    @server.tool()
    async def websocket_get_metrics() -> dict:
        """Get WebSocket server performance metrics.

        Returns:
            Server metrics including connection stats
        """
        if websocket_server is None:
            return {"error": "WebSocket server not initialized"}

        return {
            "server": "dhruva",
            "is_running": websocket_server.is_running,
            "active_connections": len(websocket_server.connections),
            "active_rooms": len(websocket_server.connection_rooms),
            "max_connections": websocket_server.max_connections,
            "message_rate_limit": websocket_server.message_rate_limit,
        }
```

**Step 4: Create integration helpers**

Create: `/Users/les/Projects/dhruva/dhruva/websocket/integration.py`

```python
"""Integration helpers for Dhruva WebSocket server."""

from typing import Any
import logging

logger = logging.getLogger(__name__)


async def start_websocket_server(
    storage_manager: Any,
    host: str = "127.0.0.1",
    port: int = 8693,
) -> Any:
    """Initialize and start Dhruva WebSocket server.

    Args:
        storage_manager: StorageManager instance
        host: Server host address
        port: Server port number

    Returns:
        Started WebSocket server instance
    """
    from dhruva.websocket import DhruvaWebSocketServer

    server = DhruvaWebSocketServer(
        storage_manager=storage_manager,
        host=host,
        port=port,
    )

    await server.start()
    logger.info(f"Dhruva WebSocket server started on {host}:{port}")
    return server


async def stop_websocket_server(server: Any) -> None:
    """Gracefully stop WebSocket server.

    Args:
        server: WebSocketServer instance
    """
    if server and server.is_running:
        await server.stop()
        logger.info("Dhruva WebSocket server stopped")


async def get_websocket_status(server: Any) -> dict:
    """Get WebSocket server status.

    Args:
        server: WebSocketServer instance

    Returns:
        Status dictionary
    """
    if server is None:
        return {"status": "not_initialized"}

    return {
        "status": "running" if server.is_running else "stopped",
        "connections": len(server.connections),
        "rooms": len(server.connection_rooms),
    }


async def broadcast_adapter_event(
    server: Any,
    event_type: str,
    adapter_id: str,
    metadata: dict,
) -> bool:
    """Broadcast adapter event to subscribers.

    Args:
        server: WebSocketServer instance
        event_type: Event type (stored, updated, etc.)
        adapter_id: Adapter identifier
        metadata: Event metadata

    Returns:
        True if broadcast successful
    """
    if server is None or not server.is_running:
        return False

    try:
        if event_type == "stored":
            await server.broadcast_adapter_stored(adapter_id, metadata)
        elif event_type == "updated":
            await server.broadcast_adapter_updated(adapter_id, metadata)
        return True
    except Exception as e:
        logger.error(f"Failed to broadcast adapter event: {e}")
        return False


class WebSocketBroadcaster:
    """Helper class for broadcasting adapter events via WebSocket."""

    def __init__(self, server: Any):
        """Initialize broadcaster.

        Args:
            server: DhruvaWebSocketServer instance
        """
        self.server = server

    async def adapter_stored(self, adapter_id: str, metadata: dict) -> bool:
        """Broadcast adapter stored event."""
        return await broadcast_adapter_event(
            self.server, "stored", adapter_id, metadata
        )

    async def adapter_updated(self, adapter_id: str, metadata: dict) -> bool:
        """Broadcast adapter updated event."""
        return await broadcast_adapter_event(
            self.server, "updated", adapter_id, metadata
        )
```

**Step 5: Create client examples**

Create: `/Users/les/Projects/dhruva/examples/websocket_client_examples.py`

```python
"""WebSocket client examples for Dhruva adapter distribution."""

import asyncio
import json
from typing import Callable, Optional


class DhruvaWebSocketClient:
    """WebSocket client for Dhruva adapter events."""

    def __init__(self, uri: str = "ws://127.0.0.1:8693"):
        """Initialize client.

        Args:
            uri: WebSocket server URI
        """
        self.uri = uri
        self.websocket: Optional[Any] = None
        self.connected = False
        self.event_handlers: dict[str, Callable] = {}

    async def connect(self) -> None:
        """Connect to WebSocket server."""
        import websockets
        self.websocket = await websockets.connect(self.uri)
        self.connected = True
        print(f"Connected to Dhruva WebSocket: {self.uri}")

    async def disconnect(self) -> None:
        """Disconnect from server."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            print("Disconnected from Dhruva WebSocket")

    async def subscribe_to_channel(self, channel: str) -> None:
        """Subscribe to events channel.

        Args:
            channel: Channel name (e.g., "adapter:abc123")
        """
        message = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": channel},
            "id": f"sub_{channel}"
        }
        await self.websocket.send(json.dumps(message))
        print(f"Subscribed to channel: {channel}")

    async def unsubscribe_from_channel(self, channel: str) -> None:
        """Unsubscribe from events channel.

        Args:
            channel: Channel name
        """
        message = {
            "type": "request",
            "event": "unsubscribe",
            "data": {"channel": channel},
            "id": f"unsub_{channel}"
        }
        await self.websocket.send(json.dumps(message))
        print(f"Unsubscribed from channel: {channel}")

    def on_event(self, event_type: str) -> Callable:
        """Decorator for event handlers.

        Args:
            event_type: Event type to handle

        Returns:
            Decorator function
        """
        def decorator(func: Callable) -> Callable:
            self.event_handlers[event_type] = func
            return func
        return decorator

    async def listen(self) -> None:
        """Listen for incoming messages."""
        if not self.websocket:
            raise RuntimeError("Not connected")

        async for message in self.websocket:
            data = json.loads(message)
            await self._handle_message(data)

    async def _handle_message(self, data: dict) -> None:
        """Handle incoming message.

        Args:
            data: Message data
        """
        if data["type"] == "event":
            event_type = data["event"]
            handler = self.event_handlers.get(event_type)
            if handler:
                await handler(data["data"])


async def example_adapter_monitoring():
    """Example: Monitor adapter storage events."""
    client = DhruvaWebSocketClient()

    @client.on_event("adapter.stored")
    async def on_adapter_stored(data: dict):
        print(f"Adapter stored: {data['adapter_id']}")

    @client.on_event("adapter.updated")
    async def on_adapter_updated(data: dict):
        print(f"Adapter updated: {data['adapter_id']}")

    await client.connect()
    await client.subscribe_to_channel("adapter:test123")
    await client.listen()


async def example_multi_channel():
    """Example: Subscribe to multiple channels."""
    client = DhruvaWebSocketClient()

    await client.connect()
    await client.subscribe_to_channel("adapter:adapter1")
    await client.subscribe_to_channel("storage:filesystem")
    await client.listen()
```

**Step 6: Create test suite**

Create: `/Users/les/Projects/dhruva/tests/test_websocket_server.py`

```python
"""Tests for Dhruva WebSocket server."""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from dhruva.websocket import DhruvaWebSocketServer


def test_server_initialization():
    """Test server initialization."""
    storage_manager = MagicMock()
    server = DhruvaWebSocketServer(
        storage_manager=storage_manager,
        host="127.0.0.1",
        port=8693,
    )

    assert server.host == "127.0.0.1"
    assert server.port == 8693
    assert server.max_connections == 1000
    assert server.storage_manager is not None


@pytest.mark.asyncio
async def test_broadcast_adapter_stored():
    """Test adapter stored broadcast."""
    storage_manager = MagicMock()
    server = DhruvaWebSocketServer(
        storage_manager=storage_manager,
        host="127.0.0.1",
        port=8693,
    )

    # Add mock client
    mock_client = AsyncMock()
    server.connections["test_conn"] = mock_client
    server.connection_rooms["adapter:test123"] = {"test_conn"}

    await server.broadcast_adapter_stored("test123", {"type": "test"})

    assert mock_client.send.called


@pytest.mark.asyncio
async def test_broadcast_adapter_updated():
    """Test adapter updated broadcast."""
    storage_manager = MagicMock()
    server = DhruvaWebSocketServer(
        storage_manager=storage_manager,
        host="127.0.0.1",
        port=8693,
    )

    mock_client = AsyncMock()
    server.connections["test_conn"] = mock_client
    server.connection_rooms["adapter:test456"] = {"test_conn"}

    await server.broadcast_adapter_updated("test456", {"version": "2.0"})

    assert mock_client.send.called
```

**Step 7: Run tests**

Run: `cd /Users/les/Projects/dhruva && pytest tests/test_websocket_server.py -v`

Expected: All tests pass

**Step 8: Commit changes**

```bash
cd /Users/les/Projects/dhruva
git add dhruva/websocket/ dhruva/mcp/websocket_tools.py examples/websocket_client_examples.py tests/test_websocket_server.py
git commit -m "feat: add WebSocket server for adapter distribution events"
```

---

## Task 2: Excalidraw WebSocket Server (Port 3042)

**Purpose:** Real-time diagram collaboration for Excalidraw MCP

**Files:**
- Create: `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/__init__.py`
- Create: `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/server.py`
- Create: `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/mcp/websocket_tools.py`
- Create: `/Users/les/Projects/excalidraw-mcp/examples/websocket_client_examples.py`
- Create: `/Users/les/Projects/excalidraw-mcp/tests/test_websocket_server.py`

**Step 1: Create package initialization**

Create: `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/__init__.py`

```python
"""WebSocket server for Excalidraw diagram collaboration."""
from .server import ExcalidrawWebSocketServer

__all__ = ["ExcalidrawWebSocketServer"]
```

**Step 2: Implement WebSocket server**

Create: `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/websocket/server.py`

```python
"""WebSocket server for Excalidraw diagram collaboration.

Broadcasts real-time events for:
- Diagram creation and updates
- Cursor movement
- User presence
- Collaborative editing
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_common.websocket import (
    MessageType,
    WebSocketMessage,
    WebSocketProtocol,
    WebSocketServer,
)
from mcp_common.websocket.protocol import EventTypes

logger = logging.getLogger(__name__)


class ExcalidrawWebSocketServer(WebSocketServer):
    """WebSocket server for Excalidraw diagram collaboration.

    Channels:
    - diagram:{diagram_id} - Diagram-specific updates
    - cursor:{diagram_id} - Cursor position updates
    - presence:{diagram_id} - User presence events
    - global - System-wide events

    Attributes:
        diagram_manager: Diagram manager instance
        host: Server host address
        port: Server port number (default: 3042)
    """

    def __init__(
        self,
        diagram_manager: Any,
        host: str = "127.0.0.1",
        port: int = 3042,
        max_connections: int = 100,
        message_rate_limit: int = 60,
    ):
        """Initialize Excalidraw WebSocket server.

        Args:
            diagram_manager: DiagramManager instance
            host: Server host address
            port: Server port number
            max_connections: Maximum concurrent connections
            message_rate_limit: Messages per second per connection
        """
        super().__init__(
            host=host,
            port=port,
            max_connections=max_connections,
            message_rate_limit=message_rate_limit,
        )

        self.diagram_manager = diagram_manager
        logger.info(f"ExcalidrawWebSocketServer initialized: {host}:{port}")

    async def on_connect(self, websocket: Any, connection_id: str) -> None:
        """Handle new connection."""
        logger.info(f"Client connected: {connection_id}")

        welcome = WebSocketProtocol.create_event(
            EventTypes.SESSION_CREATED,
            {
                "connection_id": connection_id,
                "server": "excalidraw",
                "message": "Connected to Excalidraw collaboration",
            },
        )
        await websocket.send(WebSocketProtocol.encode(welcome))

    async def on_disconnect(self, websocket: Any, connection_id: str) -> None:
        """Handle disconnection."""
        logger.info(f"Client disconnected: {connection_id}")
        await self.leave_all_rooms(connection_id)

    async def on_message(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle incoming message."""
        if message.type == MessageType.REQUEST:
            await self._handle_request(websocket, message)

    async def _handle_request(self, websocket: Any, message: WebSocketMessage) -> None:
        """Handle request message."""
        if message.event == "subscribe":
            channel = message.data.get("channel")
            if channel:
                import uuid
                connection_id = getattr(websocket, "id", str(uuid.uuid4()))
                await self.join_room(channel, connection_id)

                response = WebSocketProtocol.create_response(
                    message,
                    {"status": "subscribed", "channel": channel}
                )
                await websocket.send(WebSocketProtocol.encode(response))

    # Broadcast methods

    async def broadcast_diagram_created(
        self, diagram_id: str, metadata: dict
    ) -> None:
        """Broadcast diagram created event."""
        event = WebSocketProtocol.create_event(
            EventTypes.DIAGRAM_CREATED,
            {
                "diagram_id": diagram_id,
                "timestamp": self._get_timestamp(),
                **metadata
            },
            room=f"diagram:{diagram_id}"
        )
        await self.broadcast_to_room(f"diagram:{diagram_id}", event)

    async def broadcast_cursor_moved(
        self, diagram_id: str, user_id: str, position: dict
    ) -> None:
        """Broadcast cursor moved event."""
        event = WebSocketProtocol.create_event(
            EventTypes.CURSOR_MOVED,
            {
                "diagram_id": diagram_id,
                "user_id": user_id,
                "position": position,
                "timestamp": self._get_timestamp(),
            },
            room=f"cursor:{diagram_id}"
        )
        await self.broadcast_to_room(f"cursor:{diagram_id}", event)

    async def broadcast_user_joined(
        self, diagram_id: str, user_id: str, user_info: dict
    ) -> None:
        """Broadcast user joined event."""
        event = WebSocketProtocol.create_event(
            EventTypes.USER_JOINED,
            {
                "diagram_id": diagram_id,
                "user_id": user_id,
                "user_info": user_info,
                "timestamp": self._get_timestamp(),
            },
            room=f"presence:{diagram_id}"
        )
        await self.broadcast_to_room(f"presence:{diagram_id}", event)

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime, UTC
        return datetime.now(UTC).isoformat()
```

**Step 3: Create MCP tools and tests**

Similar structure to Dhruva, create:
- `/Users/les/Projects/excalidraw-mcp/excalidraw_mcp/mcp/websocket_tools.py`
- `/Users/les/Projects/excalidraw-mcp/examples/websocket_client_examples.py`
- `/Users/les/Projects/excalidraw-mcp/tests/test_websocket_server.py`

**Step 4: Run tests**

Run: `cd /Users/les/Projects/excalidraw-mcp && pytest tests/test_websocket_server.py -v`

**Step 5: Commit**

```bash
cd /Users/les/Projects/excalidraw-mcp
git add excalidraw_mcp/websocket/ excalidraw_mcp/mcp/websocket_tools.py examples/ tests/
git commit -m "feat: add WebSocket server for diagram collaboration"
```

---

## Task 3: Fastblocks WebSocket Server (Port TBD)

**Purpose:** Real-time UI update streams for Fastblocks framework

**Files:**
- Create: `/Users/les/Projects/fastblocks/fastblocks/websocket/__init__.py`
- Create: `/Users/les/Projects/fastblocks/fastblocks/websocket/server.py`
- Create: `/Users/les/Projects/fastblocks/fastblocks/mcp/websocket_tools.py`
- Create: `/Users/les/Projects/fastblocks/examples/websocket_client_examples.py`
- Create: `/Users/les/Projects/fastblocks/tests/test_websocket_server.py`

**Step 1-5:** Similar pattern to Dhruva and Excalidraw, with Fastblocks-specific broadcast methods:
- `broadcast_ui_updated()` - UI component updates
- `broadcast_component_rendered()` - Component render events
- `broadcast_state_changed()` - State management events

**Port:** Use 8684 (following pattern: HTTP port 8674 + 10)

---

## Task 4: Update Implementation Summary

**Files:**
- Modify: `/Users/les/.claude/skills/IMPLEMENTATION_SUMMARY.md`

**Step 1: Update Phase 3 status**

Add to IMPLEMENTATION_SUMMARY.md:

```markdown
### Phase 3: Enhanced Collaboration - COMPLETE ✓

**Completed Services:**

| Service | Port | Files Created | Status |
|---------|------|---------------|--------|
| **dhruva** | 8693 | `/dhruva/websocket/server.py` | ✅ Complete |
| **excalidraw-mcp** | 3042 | `/excalidraw_mcp/websocket/server.py` | ✅ Complete |
| **fastblocks** | 8684 | `/fastblocks/websocket/server.py` | ✅ Complete |

**Total WebSocket Servers:** 7 services fully operational
```

**Step 2: Commit summary update**

```bash
git add IMPLEMENTATION_SUMMARY.md
git commit -m "docs: update WebSocket Phase 3 completion status"
```

---

## Task 5: Create Comprehensive Documentation

**Files:**
- Create: `/Users/les/Projects/mahavishnu/docs/WEBSOCKET_PHASE3_COMPLETE.md`

**Step 1: Write completion report**

Create comprehensive report documenting:
- All 7 WebSocket servers across ecosystem
- Port allocation and purpose
- Event catalogs for each service
- Integration patterns
- Testing coverage
- Deployment considerations

**Step 2: Commit documentation**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/WEBSOCKET_PHASE3_COMPLETE.md
git commit -m "docs: add WebSocket Phase 3 completion report"
```

---

## Testing Strategy

### Unit Tests
Each service should have:
- Server initialization tests
- Broadcast method tests
- Connection handling tests
- Room subscription tests

### Integration Tests
- Real WebSocket connections
- Multi-client scenarios
- Event propagation verification

### Test Commands
```bash
# Dhruva
cd /Users/les/Projects/dhruva && pytest tests/test_websocket_server.py -v

# Excalidraw
cd /Users/les/Projects/excalidraw-mcp && pytest tests/test_websocket_server.py -v

# Fastblocks
cd /Users/les/Projects/fastblocks && pytest tests/test_websocket_server.py -v
```

---

## Deployment Checklist

For each service:
- [ ] WebSocket server implemented
- [ ] MCP tools registered
- [ ] Integration helpers created
- [ ] Client examples provided
- [ ] Unit tests passing
- [ ] API documentation complete
- [ ] Port allocated and documented
- [ ] Event catalog published

---

## Success Criteria

- ✅ All 3 Phase 3 services have WebSocket servers
- ✅ Each server has MCP integration tools
- ✅ Test coverage >80% for each service
- ✅ Complete API documentation
- ✅ Client examples for each service
- ✅ Ecosystem-wide event catalog

---

**Total Implementation:** 7 WebSocket servers across ecosystem with full MCP integration and comprehensive testing.
