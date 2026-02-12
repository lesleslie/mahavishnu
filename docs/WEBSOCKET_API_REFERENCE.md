# Mahavishnu WebSocket API Reference

**Version:** 1.0.0
**Base URL:** `ws://127.0.0.1:8690`
**Status:** Production Ready

---

## Overview

The Mahavishnu WebSocket server provides real-time updates for workflow orchestration, pool management, and system events. This document describes the complete API for connecting to and interacting with the server.

---

## Connection

### Connecting to the Server

**WebSocket URI:** `ws://127.0.0.1:8690`

```python
import websockets

async with websockets.connect("ws://127.0.0.1:8690") as websocket:
    # Connected
    pass
```

### Welcome Message

Upon successful connection, the server sends a welcome message:

```json
{
  "type": "event",
  "event": "session.created",
  "data": {
    "connection_id": "uuid",
    "server": "mahavishnu",
    "message": "Connected to Mahavishnu orchestration"
  },
  "timestamp": "2026-02-10T20:00:00Z"
}
```

---

## Message Protocol

### Message Format

All messages follow this structure:

```json
{
  "id": "uuid",
  "correlation_id": "uuid (optional)",
  "type": "request|response|event|error",
  "event": "event.name",
  "data": {...},
  "timestamp": "ISO-8601",
  "room": "room.id (optional)"
}
```

### Message Types

| Type | Description | Direction |
|------|-------------|-----------|
| `request` | Client request (expects response) | Client → Server |
| `response` | Server response to request | Server → Client |
| `event` | Broadcast event (no response) | Server → Client |
| `error` | Error message | Server → Client |

---

## Client Requests

### Subscribe to Channel

Subscribe to receive events for a specific channel.

**Request:**
```json
{
  "type": "request",
  "event": "subscribe",
  "data": {
    "channel": "workflow:abc123"
  },
  "id": "sub_001"
}
```

**Response:**
```json
{
  "type": "response",
  "event": "subscribe",
  "data": {
    "status": "subscribed",
    "channel": "workflow:abc123"
  },
  "correlation_id": "sub_001"
}
```

### Unsubscribe from Channel

**Request:**
```json
{
  "type": "request",
  "event": "unsubscribe",
  "data": {
    "channel": "workflow:abc123"
  },
  "id": "unsub_001"
}
```

**Response:**
```json
{
  "type": "response",
  "event": "unsubscribe",
  "data": {
    "status": "unsubscribed",
    "channel": "workflow:abc123"
  },
  "correlation_id": "unsub_001"
}
```

### Get Pool Status

Query the current status of a worker pool.

**Request:**
```json
{
  "type": "request",
  "event": "get_pool_status",
  "data": {
    "pool_id": "pool_local"
  },
  "id": "get_pool_001"
}
```

**Response:**
```json
{
  "type": "response",
  "event": "get_pool_status",
  "data": {
    "pool_id": "pool_local",
    "status": "active",
    "workers": ["worker_001", "worker_002"]
  },
  "correlation_id": "get_pool_001"
}
```

### Get Workflow Status

Query the current status of a workflow.

**Request:**
```json
{
  "type": "request",
  "event": "get_workflow_status",
  "data": {
    "workflow_id": "wf_abc123"
  },
  "id": "get_wf_001"
}
```

**Response:**
```json
{
  "type": "response",
  "event": "get_workflow_status",
  "data": {
    "workflow_id": "wf_abc123",
    "status": "running",
    "stages_completed": 3,
    "total_stages": 10
  },
  "correlation_id": "get_wf_001"
}
```

---

## Server Events

### Workflow Events

#### workflow.started

Broadcasted when a workflow execution begins.

```json
{
  "type": "event",
  "event": "workflow.started",
  "data": {
    "workflow_id": "wf_abc123",
    "timestamp": "2026-02-10T20:00:00Z",
    "adapter": "llamaindex",
    "prompt": "Write code"
  },
  "room": "workflow:wf_abc123"
}
```

#### workflow.stage_completed

Broadcasted when a workflow stage completes.

```json
{
  "type": "event",
  "event": "workflow.stage_completed",
  "data": {
    "workflow_id": "wf_abc123",
    "stage_name": "code_generation",
    "result": {
      "output": "Success",
      "duration_ms": 1500
    },
    "timestamp": "2026-02-10T20:00:05Z"
  },
  "room": "workflow:wf_abc123"
}
```

#### workflow.completed

Broadcasted when a workflow completes successfully.

```json
{
  "type": "event",
  "event": "workflow.completed",
  "data": {
    "workflow_id": "wf_abc123",
    "result": {
      "final_output": "Code generated successfully",
      "total_duration_ms": 5000
    },
    "timestamp": "2026-02-10T20:00:10Z"
  },
  "room": "workflow:wf_abc123"
}
```

#### workflow.failed

Broadcasted when a workflow fails.

```json
{
  "type": "event",
  "event": "workflow.failed",
  "data": {
    "workflow_id": "wf_abc123",
    "error": "Execution timeout",
    "timestamp": "2026-02-10T20:00:08Z"
  },
  "room": "workflow:wf_abc123"
}
```

### Pool Events

#### worker.status_changed

Broadcasted when a worker's status changes.

```json
{
  "type": "event",
  "event": "worker.status_changed",
  "data": {
    "worker_id": "worker_001",
    "status": "busy",
    "pool_id": "pool_local",
    "timestamp": "2026-02-10T20:00:00Z"
  },
  "room": "pool:pool_local"
}
```

**Worker Status Values:**
- `idle` - Worker available for tasks
- `busy` - Worker executing task
- `error` - Worker encountered error
- `offline` - Worker disconnected

#### pool.status_changed

Broadcasted when pool metrics change.

```json
{
  "type": "event",
  "event": "pool.status_changed",
  "data": {
    "pool_id": "pool_local",
    "status": {
      "active_workers": 5,
      "idle_workers": 2,
      "queue_size": 10,
      "tasks_completed": 150
    },
    "timestamp": "2026-02-10T20:00:00Z"
  },
  "room": "pool:pool_local"
}
```

---

## Channels

### Channel Naming Convention

Channels use the pattern: `{resource_type}:{resource_id}`

**Examples:**
- `workflow:abc123` - Events for workflow abc123
- `pool:local` - Events for local pool
- `worker:worker_001` - Events for specific worker
- `global` - System-wide events

### Channel Types

| Channel Pattern | Description | Events |
|----------------|-------------|--------|
| `workflow:{id}` | Workflow-specific updates | workflow.started, workflow.stage_completed, workflow.completed, workflow.failed |
| `pool:{id}` | Pool status updates | worker.status_changed, pool.status_changed |
| `worker:{id}` | Worker-specific events | worker.status_changed |
| `global` | System-wide events | All events (high volume) |

---

## Error Handling

### Error Message Format

```json
{
  "type": "error",
  "error_code": "ERROR_CODE",
  "error_message": "Human-readable error description",
  "correlation_id": "uuid (optional)"
}
```

### Common Error Codes

| Error Code | Description |
|------------|-------------|
| `UNKNOWN_REQUEST` | Unknown request event type |
| `INVALID_CHANNEL` | Invalid channel name |
| `NOT_FOUND` | Resource not found |
| `SERVER_ERROR` | Internal server error |

---

## Rate Limiting

- **Max Connections:** 1000 concurrent connections
- **Message Rate Limit:** 100 messages per second per connection
- **Exceeded Limit:** Connection may be terminated

---

## Examples

### Python Client Example

```python
import asyncio
import json
import websockets

async def monitor_workflow():
    uri = "ws://127.0.0.1:8690"

    async with websockets.connect(uri) as ws:
        # Subscribe to workflow
        subscribe = {
            "type": "request",
            "event": "subscribe",
            "data": {"channel": "workflow:abc123"},
            "id": "sub_001"
        }
        await ws.send(json.dumps(subscribe))

        # Listen for events
        while True:
            message = await ws.recv()
            data = json.loads(message)

            if data["event"] == "workflow.started":
                print(f"Workflow started: {data['data']['workflow_id']}")
            elif data["event"] == "workflow.completed":
                print(f"Workflow completed!")
                break

asyncio.run(monitor_workflow())
```

### JavaScript Client Example

```javascript
const ws = new WebSocket('ws://127.0.0.1:8690');

ws.onopen = () => {
    // Subscribe to workflow
    ws.send(JSON.stringify({
        type: 'request',
        event: 'subscribe',
        data: { channel: 'workflow:abc123' },
        id: 'sub_001'
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.event === 'workflow.started') {
        console.log('Workflow started:', data.data.workflow_id);
    } else if (data.event === 'workflow.completed') {
        console.log('Workflow completed!');
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('Disconnected');
};
```

---

## Best Practices

### 1. Subscribe to Specific Channels

Subscribe to specific channels rather than `global` to receive only relevant events.

```python
# Good - specific channel
await client.subscribe_to_channel("workflow:abc123")

# Avoid - global channel (high volume)
await client.subscribe_to_channel("global")
```

### 2. Handle Reconnection

Implement automatic reconnection with exponential backoff.

```python
import asyncio
import websockets

async def connect_with_retry():
    retry_delay = 1

    while True:
        try:
            async with websockets.connect("ws://127.0.0.1:8690") as ws:
                retry_delay = 1  # Reset on successful connect
                # Handle connection...
        except Exception as e:
            print(f"Connection failed: {e}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # Max 60s
```

### 3. Validate Messages

Always validate incoming message structure.

```python
def is_valid_message(data):
    required = ['type', 'event', 'data']
    return all(key in data for key in required)

# Usage
message = await ws.recv()
data = json.loads(message)

if not is_valid_message(data):
    logger.error(f"Invalid message: {data}")
    continue
```

### 4. Use Correlation IDs

Include correlation IDs in requests for tracking.

```python
import uuid

request = {
    "type": "request",
    "event": "get_workflow_status",
    "data": {"workflow_id": "wf_123"},
    "id": str(uuid.uuid4()),  # Unique correlation ID
    "correlation_id": "my_request_123"
}
```

---

## Troubleshooting

### Connection Refused

**Problem:** Cannot connect to WebSocket server

**Solutions:**
1. Verify server is running: Check if port 8690 is listening
2. Check firewall settings
3. Verify correct host/port

### No Events Received

**Problem:** Connected but no events received

**Solutions:**
1. Verify subscribed to correct channel
2. Check if events are being broadcast
3. Check server logs for errors

### Connection Drops

**Problem:** Connection closes unexpectedly

**Solutions:**
1. Implement reconnection logic
2. Check network stability
3. Verify not exceeding rate limits

---

## Performance Considerations

- **Broadcast Latency:** <10ms for local connections
- **Message Size:** Keep event data under 1KB
- **Connection Pool:** Reuse connections when possible
- **Event Volume:** Monitor subscription to high-volume channels

---

## Security

### Authentication

Currently, WebSocket connections do not require authentication. This is suitable for local development. For production:

1. Implement token-based authentication
2. Use TLS/WSS for encrypted connections
3. Validate channel subscriptions

### Authorization

Clients can only subscribe to channels; they cannot publish events. All events are broadcast by the server based on internal state changes.

---

## Support

For issues or questions:
- Check server logs: `/var/log/mahavishnu/websocket.log`
- Review health status: Use MCP `websocket_health_check` tool
- API issues: Open issue on GitHub

---

## Changelog

### Version 1.0.0 (2026-02-10)
- Initial release
- Workflow event broadcasting
- Pool status monitoring
- Worker status tracking
