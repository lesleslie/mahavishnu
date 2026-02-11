# Real-Time Monitoring Demos

This directory contains interactive terminal demonstrations of Mahavishnu's WebSocket infrastructure for real-time orchestration monitoring.

## Overview

These demos showcase real-time updates from Mahavishnu's WebSocket server, including:
- Pool status monitoring with worker tracking
- Workflow execution monitoring with progress tracking
- Multi-service unified dashboard

## Requirements

All demos require:
- Python 3.13+
- `websockets` library (already installed)
- `rich` library for terminal UI
- `typer` library for CLI

Dependencies are already installed via `mahavishnu[dev]`.

## Available Demos

### 1. Pool Monitor

Monitor pool status, workers, and tasks in real-time.

```bash
python examples/realtime_monitoring/pool_monitor.py pool_local
python examples/realtime_monitoring/pool_monitor.py pool_local --host localhost --port 8690
```

**Features:**
- Real-time pool status (worker count, queue size)
- Worker status tracking (idle, busy, error)
- Task assignment/completion events
- Connection status indicator
- Event history with timestamps
- Color-coded output (green=healthy, yellow=warning, red=error)

### 2. Workflow Monitor

Monitor workflow execution progress with stage tracking.

```bash
python examples/realtime_monitoring/workflow_monitor.py wf_123
python examples/realtime_monitoring/workflow_monitor.py wf_123 --host localhost --port 8690
```

**Features:**
- Workflow status tracking (pending, running, completed, failed)
- Stage completion progress bar
- Current stage indicator
- Stage history with timestamps
- Worker status changes
- Workflow completion/failure notifications

### 3. Multi-Service Dashboard

Unified dashboard for all Mahavishnu ecosystem services.

```bash
python examples/realtime_monitoring/multi_service_dashboard.py
python examples/realtime_monitoring/multi_service_dashboard.py --mahavishnu-host localhost --mahavishnu-port 8690
```

**Features:**
- Three-panel layout (Mahavishnu, Pool, Akosha)
- Concurrent updates from all services
- Connection status indicators
- Message counters
- Event history per service
- 100ms refresh rate

## Usage Patterns

### Starting the WebSocket Server

Before running demos, ensure the Mahavishnu WebSocket server is running:

```bash
# Start MCP server with WebSocket support
mahavishnu mcp start
```

### Running Demos

All demos support the `--help` flag for usage information:

```bash
python examples/realtime_monitoring/pool_monitor.py --help
python examples/realtime_monitoring/workflow_monitor.py --help
python examples/realtime_monitoring/multi_service_dashboard.py --help
```

### Graceful Shutdown

All demos support graceful shutdown via `Ctrl+C`. The connection will be properly closed.

## WebSocket Protocol

### Connection

Demos connect using standard WebSocket protocol:

```
ws://127.0.0.1:8690
```

### Subscription Pattern

Subscribe to channels using request messages:

```json
{
  "type": "request",
  "event": "subscribe",
  "data": {"channel": "pool:pool_local"},
  "id": "sub_pool_local"
}
```

### Event Messages

Receive real-time events:

```json
{
  "type": "event",
  "event": "pool.status_changed",
  "data": {"worker_count": 5, "queue_size": 10},
  "timestamp": "2026-02-10T23:59:59.999Z"
}
```

## Event Types

### Pool Events

- `pool.status_changed` - Pool status update
- `pool.scaling` - Pool scaling event
- `worker.status_changed` - Worker status change
- `task.assigned` - Task assigned to worker
- `task.completed` - Task completed by worker

### Workflow Events

- `workflow.started` - Workflow execution started
- `workflow.stage_completed` - Workflow stage completed
- `workflow.completed` - Workflow completed successfully
- `workflow.failed` - Workflow execution failed

### Akosha Events

- `insight.generated` - New insight generated
- `pattern.detected` - Pattern detected in data

## Architecture

### Client Implementation

Each demo uses the `websockets` library for WebSocket connections:

```python
import websockets

async with websockets.connect("ws://127.0.0.1:8690") as websocket:
    await websocket.send(json.dumps(message))
    response = await websocket.recv()
```

### Terminal UI

All demos use `rich` library for rich terminal UI:

- **Tables** - Structured data display
- **Panels** - Bordered containers
- **Layouts** - Multi-panel layouts
- **Progress bars** - Visual progress tracking
- **Live updates** - Real-time refresh

### Async/Await Pattern

All demos use async/await for concurrent operations:

```python
async def listen():
    while running:
        message = await websocket.recv()
        await handle_message(message)
```

## Testing

### Manual Testing

Test demos with a running WebSocket server:

```bash
# Terminal 1: Start WebSocket server
mahavishnu mcp start

# Terminal 2: Run pool monitor
python examples/realtime_monitoring/pool_monitor.py pool_local

# Terminal 3: Run workflow monitor
python examples/realtime_monitoring/workflow_monitor.py wf_123

# Terminal 4: Run multi-service dashboard
python examples/realtime_monitoring/multi_service_dashboard.py
```

### Auto-Reconnection

Demos include auto-reconnection logic (to be implemented):

```python
async def connect_with_retry():
    retry_delay = 1
    while True:
        try:
            await connect()
            return
        except ConnectionError:
            await asyncio.sleep(retry_delay)
            retry_delay *= 2  # Exponential backoff
```

## Troubleshooting

### Connection Refused

If you see "Connection refused", ensure:
1. WebSocket server is running (`mahavishnu mcp start`)
2. Correct host/port specified
3. No firewall blocking port 8690

### No Events Received

If no events appear:
1. Verify subscription to correct channel
2. Check WebSocket server logs
3. Ensure pool/workflow IDs are valid

### Terminal UI Issues

If terminal UI doesn't render correctly:
1. Ensure terminal supports ANSI colors
2. Try different terminal (iTerm2, Terminal.app)
3. Increase terminal window size

## Development

### Adding New Demos

To add a new monitoring demo:

1. Create new file in `examples/realtime_monitoring/`
2. Use `from __future__ import annotations` as first import
3. Implement async WebSocket client with `websockets` library
4. Use `rich` for terminal UI (tables, panels, layouts)
5. Add `--help` documentation via typer
6. Implement graceful shutdown on SIGINT

### Code Style

All demos follow Mahavishnu code standards:
- Type hints for all functions
- Comprehensive docstrings
- Modern async/await patterns
- Error handling with user-friendly messages
- Color-coded terminal output

## Future Enhancements

- Auto-reconnection with exponential backoff
- Historical data replay from event logs
- Alert system for threshold violations
- Export events to file/database
- Custom channel subscriptions
- Filter events by type/severity
- Performance metrics (latency, throughput)
