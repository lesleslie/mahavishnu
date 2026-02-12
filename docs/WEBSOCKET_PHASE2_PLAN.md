# WebSocket Phase 2 Implementation Plan

**Date:** 2026-02-10
**Status:** In Progress

## Overview

Phase 2 implements WebSocket servers for high-priority ecosystem services, building on the abstraction layer created in Phase 1.

## Services to Implement

### Week 3: session-buddy (Port 8688)

**Purpose:** Real-time session synchronization and knowledge updates

**Channels:**
- `session:{session_id}` - Session-specific updates
- `knowledge:{session_id}` - Knowledge graph updates
- `checkpoint:{session_id}` - Checkpoint notifications
- `global` - System-wide announcements

**Events:**
- `session.created` - New session started
- `session.updated` - Session context changed
- `session.checkpoint` - Checkpoint created
- `session.closed` - Session ended
- `knowledge.captured` - New knowledge added
- `knowledge.search_result` - Search completed

**Implementation Files:**
- `session_buddy/websocket/server.py` - SessionBuddyWebSocketServer
- `session_buddy/websocket/handlers.py` - Event handlers
- `session_buddy/websocket/__init__.py` - Package exports

### Week 4: mahavishnu (Port 8690)

**Purpose:** Workflow orchestration and pool monitoring

**Channels:**
- `workflow:{workflow_id}` - Workflow-specific updates
- `pool:{pool_id}` - Pool status updates
- `worker:{worker_id}` - Worker-specific events
- `global` - System orchestration events

**Events:**
- `workflow.started` - Workflow execution started
- `workflow.stage_completed` - Stage finished
- `workflow.completed` - Workflow finished
- `workflow.failed` - Workflow error
- `worker.status_changed` - Worker state change
- `pool.status_changed` - Pool metrics updated

**Implementation Files:**
- `mahavishnu/websocket/server.py` - MahavishnuWebSocketServer
- `mahavishnu/websocket/handlers.py` - Event handlers
- `mahavishnu/websocket/__init__.py` - Package exports

### Week 5: akosha (Port 8692)

**Purpose:** Pattern detection and analytics streaming

**Channels:**
- `patterns:{category}` - Pattern detection updates
- `anomalies` - Anomaly detection alerts
- `insights` - Generated insights
- `metrics` - Real-time analytics

**Events:**
- `pattern.detected` - New pattern found
- `anomaly.detected` - Anomaly identified
- `insight.generated` - Insight created
- `aggregation.completed` - Data aggregation finished

**Implementation Files:**
- `akosha/websocket/server.py` - AkoshaWebSocketServer
- `akosha/websocket/handlers.py` - Event handlers
- `akosha/websocket/__init__.py` - Package exports

### Week 6: crackerjack (Port 8686)

**Purpose:** Test execution and quality gate monitoring

**Channels:**
- `test:{run_id}` - Test run updates
- `quality:{project}` - Quality gate status
- `coverage` - Coverage updates
- `global` - System-wide CI/CD events

**Events:**
- `test.started` - Test execution started
- `test.completed` - Test finished
- `test.failed` - Test failure
- `quality_gate.checked` - Quality gate evaluated
- `coverage.updated` - Coverage metrics updated

**Implementation Files:**
- `crackerjack/websocket/server.py` - CrackerjackWebSocketServer
- `crackerjack/websocket/handlers.py` - Event handlers
- `crackerjack/websocket/__init__.py` - Package exports

## Implementation Pattern

Each WebSocket server follows this pattern:

```python
from mcp_common.websocket import (
    WebSocketServer,
    WebSocketProtocol,
    EventTypes,
)
from service.core.manager import Manager

class ServiceWebSocketServer(WebSocketServer):
    def __init__(self, manager: Manager):
        super().__init__(host="127.0.0.1", port=XXXX)
        self.manager = manager

    async def on_connect(self, websocket, connection_id):
        """Handle new connection."""
        await self.manager.on_websocket_connect(connection_id)

    async def on_disconnect(self, websocket, connection_id):
        """Handle disconnection."""
        await self.leave_all_rooms(connection_id)
        await self.manager.on_websocket_disconnect(connection_id)

    async def on_message(self, websocket, message):
        """Handle incoming message."""
        if message.event == "subscribe":
            # Subscribe to channel
            channel = message.data["channel"]
            await self.join_room(channel, connection_id)

        elif message.event == "unsubscribe":
            # Unsubscribe from channel
            channel = message.data["channel"]
            await self.leave_room(channel, connection_id)

        elif message.event == "get_status":
            # Request current status
            status = await self.manager.get_status(message.data)
            response = WebSocketProtocol.create_response(
                message,
                status
            )
            await websocket.send(WebSocketProtocol.encode(response))

    # Service-specific broadcast methods
    async def broadcast_event(self, event_type: str, data: dict, room: str):
        """Broadcast event to room."""
        event = WebSocketProtocol.create_event(
            event_type,
            data,
            room=room
        )
        await self.broadcast_to_room(room, event)
```

## Integration Points

### 1. Service Manager Integration

Each service's core manager needs WebSocket hooks:

```python
class ServiceManager:
    def __init__(self):
        self.websocket_server: Optional[ServiceWebSocketServer] = None

    async def on_websocket_connect(self, connection_id: str):
        """Handle WebSocket connection."""
        logger.info(f"WebSocket connected: {connection_id}")

    async def on_websocket_disconnect(self, connection_id: str):
        """Handle WebSocket disconnection."""
        logger.info(f"WebSocket disconnected: {connection_id}")

    async def broadcast_update(self, event_type: str, data: dict, room: str):
        """Broadcast update via WebSocket."""
        if self.websocket_server:
            await self.websocket_server.broadcast_event(
                event_type, data, room
            )
```

### 2. MCP Tool Integration

Add MCP tools for WebSocket status:

```python
@mcp.tool()
async def websocket_status() -> dict:
    """Get WebSocket server status."""
    return {
        "running": manager.websocket_server.is_running if manager.websocket_server else False,
        "connections": len(manager.websocket_server.connections) if manager.websocket_server else 0,
        "port": 8688
    }

@mcp.tool()
async def broadcast_test_event(event_type: str, data: dict) -> dict:
    """Broadcast test event (development only)."""
    await manager.broadcast_update(event_type, data, "global")
    return {"status": "broadcasted"}
```

## Testing Strategy

### 1. Unit Tests

```python
import pytest
from service.websocket.server import ServiceWebSocketServer

@pytest.mark.asyncio
async def test_websocket_server_initialization():
    """Test server initializes correctly."""
    server = ServiceWebSocketServer(mock_manager)
    assert server.host == "127.0.0.1"
    assert server.port == 8688

@pytest.mark.asyncio
async def test_on_connect():
    """Test connection handling."""
    server = ServiceWebSocketServer(mock_manager)
    await server.on_connect(mock_websocket, "conn_123")
    assert "conn_123" in server.connections
```

### 2. Integration Tests

```python
import websockets
import asyncio

@pytest.mark.asyncio
async def test_websocket_client_connection():
    """Test client can connect and subscribe."""
    uri = "ws://127.0.0.1:8688"

    async with websockets.connect(uri) as websocket:
        # Subscribe to channel
        subscribe_msg = WebSocketProtocol.create_event(
            "subscribe",
            {"channel": "session:abc123"}
        )
        await websocket.send(WebSocketProtocol.encode(subscribe_msg))

        # Receive acknowledgment
        response = await websocket.recv()
        message = WebSocketProtocol.decode(response)
        assert message.type == MessageType.ACK
```

### 3. End-to-End Tests

```python
@pytest.mark.asyncio
async def test_session_update_broadcast():
    """Test session update broadcasts to subscribers."""
    # Create WebSocket client
    client = WebSocketClient("ws://127.0.0.1:8688")
    await client.connect()

    # Subscribe to session
    await client.subscribe_to_room("session:test123")

    # Update session
    await session_manager.update_session("test123", {"key": "value"})

    # Verify broadcast received
    await asyncio.sleep(0.1)  # Allow propagation
    # Assert event received

    await client.disconnect()
```

## Configuration

Add to service settings:

```yaml
# settings/service.yaml
websocket:
  enabled: true
  host: "127.0.0.1"
  port: 8688  # Service-specific port
  max_connections: 1000
  message_rate_limit: 100  # messages per second
```

Pydantic model:

```python
from pydantic import BaseModel

class WebSocketSettings(BaseModel):
    """WebSocket server configuration."""
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int
    max_connections: int = 1000
    message_rate_limit: int = 100
```

## Deployment

### 1. Service Startup

```python
async def main():
    """Main service entry point."""
    # Initialize manager
    manager = ServiceManager()

    # Start WebSocket server
    if settings.websocket.enabled:
        manager.websocket_server = ServiceWebSocketServer(manager)
        await manager.websocket_server.start()
        logger.info(f"WebSocket server started on port {settings.websocket.port}")

    # Start MCP server
    await mcp.run()

    # Cleanup on shutdown
    if manager.websocket_server:
        await manager.websocket_server.stop()
```

### 2. Process Management

Use supervisord/systemd:

```ini
[program:service-websocket]
command=/path/to/venv/bin/python -m service.websocket
autostart=true
autorestart=true
stderr_logfile=/var/log/service/websocket.err.log
stdout_logfile=/var/log/service/websocket.out.log
```

## Monitoring

### 1. Metrics

Track per server:
- Active connections
- Messages sent/received
- Broadcast operations
- Error rates
- Room subscription counts

### 2. Health Checks

```python
@mcp.tool()
async def websocket_health_check() -> dict:
    """Check WebSocket server health."""
    if not manager.websocket_server:
        return {"status": "not_initialized"}

    return {
        "status": "healthy" if manager.websocket_server.is_running else "stopped",
        "connections": len(manager.websocket_server.connections),
        "rooms": len(manager.websocket_server.connection_rooms),
        "uptime": uptime_seconds()
    }
```

## Port Allocation

| Service | HTTP Port | WebSocket Port | Offset |
|---------|-----------|----------------|---------|
| session-buddy | 8678 | 8688 | +10 |
| mahavishnu | 8680 | 8690 | +10 |
| akosha | 8682 | 8692 | +10 |
| crackerjack | 8676 | 8686 | +10 |
| dhruva | 8683 | 8693 | +10 |
| excalidraw | 3032 | 3042 | +10 |

## Progress Tracking

- [ ] session-buddy WebSocket server
- [ ] mahavishnu WebSocket server
- [ ] akosha WebSocket server
- [ ] crackerjack WebSocket server
- [ ] Integration tests for all servers
- [ ] Documentation
- [ ] Deployment guides

## Next Steps

1. Implement session-buddy WebSocket server (Week 3)
2. Add comprehensive tests
3. Document integration patterns
4. Proceed to mahavishnu WebSocket (Week 4)
5. Continue through all high-priority services
