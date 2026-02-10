# Event Collector Service

Central event collection service for ecosystem-wide event aggregation across Mahavishnu, Crackerjack, Session-Buddy, Akosha, and Oneiric.

## Overview

The Event Collector provides a unified interface for collecting, storing, and querying events from all 5 ecosystem systems. It supports multiple storage backends, provides REST and WebSocket APIs, and includes rate limiting, metrics, and health monitoring.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Event Collector Service                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  REST API    │  │  WebSocket   │  │  Integration │      │
│  │              │  │  Streaming   │  │  Protocol    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │                │
│  ┌──────▼─────────────────▼─────────────────▼───────┐      │
│  │              Event Collector Core                 │      │
│  │  - Rate Limiting (1000 req/s per system)        │      │
│  │  - Event Validation (Pydantic)                   │      │
│  │  - Metrics (OpenTelemetry)                       │      │
│  │  - Health Monitoring                             │      │
│  └──────┬──────────────────────────────────────────┬───┘  │
│         │                                          │        │
│  ┌──────▼──────┐  ┌─────────────┐  ┌──────────────▼───┐    │
│  │   Memory    │  │   SQLite    │  │  Session-Buddy   │    │
│  │  Storage    │  │  Storage    │  │  Knowledge Graph │    │
│  └─────────────┘  └─────────────┘  └──────────────────┘    │
│                                                           │
└───────────────────────────────────────────────────────────┘

     ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
     │ Mahavishnu  │    │ Crackerjack │    │ Session-Buddy│
     └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
            │                  │                    │
            └──────────────────┼────────────────────┘
                               │
                        ┌──────▼──────┐
                        │ Event Bus   │
                        └─────────────┘
```

## Features

- ✅ **Multi-System Support**: Collect events from all 5 ecosystem systems
- ✅ **Multiple Storage Backends**: Memory, SQLite, Session-Buddy knowledge graph
- ✅ **REST API**: HTTP endpoints for event collection and querying
- ✅ **WebSocket Streaming**: Real-time event streams with filtering
- ✅ **Rate Limiting**: 1000 events/second per system
- ✅ **Event Validation**: Pydantic models for type safety
- ✅ **Metrics**: OpenTelemetry metrics for observability
- ✅ **Health Monitoring**: Health checks for service and storage backends
- ✅ **Correlation Tracking**: Trace events across systems
- ✅ **Flexible Queries**: Filter by source, type, severity, time range, tags

## Installation

```bash
# Event collector is included with mahavishnu
pip install mahavishnu

# Or install from source
cd /path/to/mahavishnu
pip install -e .
```

## Quick Start

### Basic Usage

```python
from mahavishnu.integrations.event_collector import (
    EcosystemEvent,
    EventCollector,
    EventQuery,
)

# Initialize collector
collector = EventCollector(storage_backend="sqlite", db_path="events.db")
await collector.initialize()

# Collect event
event = EcosystemEvent(
    source_system="mahavishnu",
    event_type="workflow_complete",
    severity="info",
    correlation_id="wf-abc123",
    data={
        "workflow_id": "abc123",
        "duration": 5.2,
        "status": "success",
    },
    tags=["workflow", "production"],
)
await collector.collect_event(event)

# Query events
query = EventQuery(
    source_system="mahavishnu",
    severity="info",
    limit=10,
)
events = await collector.query_events(query)

for event in events:
    print(f"{event.timestamp}: {event.event_type} - {event.data}")

# Get correlated events
correlated = await collector.get_events_by_correlation("wf-abc123")

# Get statistics
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
start = now - timedelta(hours=1)
stats = await collector.get_event_stats((start, now))
print(f"Total events: {stats['total_events']}")

# Shutdown
await collector.shutdown()
```

### Register with Integration Registry

```python
from mahavishnu.integrations.event_collector import register_event_collector

# Register and initialize
collector = register_event_collector(
    storage_backend="sqlite",
    db_path="events.db",
)
await collector.initialize()

# Use collector...

# Shutdown when done
await collector.shutdown()
```

### Convenience Function

```python
from mahavishnu.integrations.event_collector import collect_event

# Register collector first
register_event_collector(storage_backend="sqlite", db_path="events.db")

# Collect event
event_id = await collect_event(
    source_system="mahavishnu",
    event_type="workflow_complete",
    severity="info",
    data={"workflow_id": "abc123"},
)
print(f"Event collected: {event_id}")
```

## Event Model

### EcosystemEvent

```python
class EcosystemEvent(BaseModel):
    """Standardized event format for ecosystem-wide event collection."""

    event_id: str  # Auto-generated UUID4
    timestamp: datetime  # Auto-generated UTC timestamp
    source_system: str  # mahavishnu, crackerjack, session_buddy, akosha, oneiric
    event_type: str  # e.g., workflow_complete, quality_issue
    severity: str  # debug, info, warning, error, critical
    correlation_id: str | None  # For cross-system tracing
    data: dict[str, Any]  # Event payload
    tags: list[str]  # For filtering and grouping
```

### Valid Source Systems

- `mahavishnu`: Workflow orchestration events
- `crackerjack`: Quality control events
- `session_buddy`: Session management events
- `akosha`: Analytics events
- `oneiric`: Configuration events

### Valid Severity Levels

- `debug`: Detailed debugging information
- `info`: General informational messages
- `warning`: Warning messages
- `error`: Error events
- `critical`: Critical failures

## Event Query

```python
class EventQuery(BaseModel):
    """Query model for filtering and searching events."""

    source_system: str | None = None  # Filter by source system
    event_type: str | None = None  # Filter by event type
    severity: str | None = None  # Filter by severity level
    start_time: datetime | None = None  # Filter events after this timestamp
    end_time: datetime | None = None  # Filter events before this timestamp
    correlation_id: str | None = None  # Filter by correlation ID
    tags: list[str] = []  # Filter by tags (ALL must match)
    limit: int = 100  # Max results (1-1000)
    offset: int = 0  # Pagination offset
    sort_by: str = "timestamp"  # Sort field
    sort_order: str = "desc"  # Sort order (asc or desc)
```

### Query Examples

```python
# Query by source system
query = EventQuery(source_system="mahavishnu", limit=50)

# Query by severity
query = EventQuery(severity="error", limit=100)

# Query by time range
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
start = now - timedelta(hours=24)
query = EventQuery(start_time=start, end_time=now)

# Query by correlation
query = EventQuery(correlation_id="wf-abc123")

# Query by tags
query = EventQuery(tags=["production", "workflow"])

# Complex query
query = EventQuery(
    source_system="mahavishnu",
    event_type="workflow_complete",
    severity="info",
    start_time=start,
    end_time=now,
    tags=["production"],
    limit=50,
    sort_by="timestamp",
    sort_order="desc",
)
```

## Storage Backends

### Memory Storage

**Best for**: Testing and development

```python
collector = EventCollector(storage_backend="memory")
```

**Features**:
- Fast in-memory storage
- No persistence (data lost on restart)
- No external dependencies
- Suitable for unit tests

**Limitations**:
- Data loss on process restart
- Limited by available RAM
- Not suitable for production

### SQLite Storage

**Best for**: Production with moderate event volumes

```python
collector = EventCollector(
    storage_backend="sqlite",
    db_path="events.db",
)
```

**Features**:
- Persistent local storage
- Automatic indexing
- ACID transactions
- Suitable for < 1M events

**Advantages**:
- No external dependencies
- Fast queries with indexes
- Easy backup and migration

**Limitations**:
- Single-server only (no replication)
- Performance degrades with > 1M events

### Session-Buddy Storage

**Best for**: Production with knowledge graph correlation

```python
collector = EventCollector(
    storage_backend="session_buddy",
    session_buddy_url="http://localhost:8678/mcp",
)
```

**Features**:
- Knowledge graph storage
- Cross-system correlation
- Semantic search
- Relationship tracking

**Advantages**:
- Event relationships via graph edges
- Correlation tracking across systems
- Integration with Session-Buddy analytics

**Requirements**:
- Session-Buddy MCP server running
- Network connectivity

## REST API

### Start API Server

```python
import uvicorn
from mahavishnu.integrations.event_collector import EventCollector

collector = EventCollector(storage_backend="sqlite", db_path="events.db")
await collector.initialize()

# Start server
uvicorn.run(collector.app, host="0.0.0.0", port=8000)
```

### API Endpoints

#### POST /events

Collect a single event.

```bash
curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{
    "source_system": "mahavishnu",
    "event_type": "workflow_complete",
    "severity": "info",
    "correlation_id": "wf-abc123",
    "data": {"workflow_id": "abc123", "duration": 5.2},
    "tags": ["production"]
  }'
```

**Response** (201 Created):
```json
{
  "event_id": "abc-123-def-456",
  "status": "collected"
}
```

#### POST /events/batch

Collect multiple events.

```bash
curl -X POST http://localhost:8000/events/batch \
  -H "Content-Type: application/json" \
  -d '[
    {"source_system": "mahavishnu", "event_type": "test", "severity": "info"},
    {"source_system": "crackerjack", "event_type": "test", "severity": "warning"}
  ]'
```

**Response** (201 Created):
```json
{
  "collected": 2,
  "failed": 0,
  "status": "batch_completed"
}
```

#### GET /events/{event_id}

Get event by ID.

```bash
curl http://localhost:8000/events/abc-123-def-456
```

**Response** (200 OK):
```json
{
  "event_id": "abc-123-def-456",
  "timestamp": "2025-02-05T12:00:00Z",
  "source_system": "mahavishnu",
  "event_type": "workflow_complete",
  "severity": "info",
  "correlation_id": "wf-abc123",
  "data": {"workflow_id": "abc123"},
  "tags": ["production"]
}
```

#### GET /events

Query events with filters.

```bash
curl "http://localhost:8000/events?source_system=mahavishnu&severity=info&limit=10"
```

**Response** (200 OK):
```json
{
  "events": [...],
  "count": 10,
  "query": {
    "source_system": "mahavishnu",
    "severity": "info",
    "limit": 10,
    "offset": 0
  }
}
```

#### GET /events/correlation/{correlation_id}

Get correlated events.

```bash
curl http://localhost:8000/events/correlation/wf-abc123
```

**Response** (200 OK):
```json
{
  "correlation_id": "wf-abc123",
  "events": [...],
  "count": 5
}
```

#### GET /events/stats

Get event statistics.

```bash
curl "http://localhost:8000/events/stats?start_time=2025-02-05T00:00:00Z&end_time=2025-02-05T23:59:59Z"
```

**Response** (200 OK):
```json
{
  "total_events": 1234,
  "by_source_system": {
    "mahavishnu": 800,
    "crackerjack": 200,
    "session_buddy": 150,
    "akosha": 50,
    "oneiric": 34
  },
  "by_event_type": {
    "workflow_complete": 400,
    "quality_issue": 200,
    ...
  },
  "by_severity": {
    "info": 800,
    "warning": 300,
    "error": 100,
    "debug": 30,
    "critical": 4
  },
  "time_range": {
    "start": "2025-02-05T00:00:00Z",
    "end": "2025-02-05T23:59:59Z"
  }
}
```

#### GET /health

Health check endpoint.

```bash
curl http://localhost:8000/health
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "collector": {
    "healthy": true,
    "started": true,
    "storage_type": "SQLiteEventStorage",
    "events_processed": 1234,
    "active_websockets": 3
  },
  "storage": {
    "status": "healthy",
    "storage_type": "sqlite",
    "db_path": "events.db",
    "total_events": 1234
  }
}
```

## WebSocket Streaming

### Connect to WebSocket Stream

```python
import asyncio
import websockets
import json

async def stream_events():
    uri = "ws://localhost:8000/events/stream?source_system=mahavishnu&severity=warning"

    async with websockets.connect(uri) as websocket:
        while True:
            event = json.loads(await websocket.recv())
            print(f"Received: {event}")

asyncio.run(stream_events())
```

### WebSocket Query Parameters

- `source_system`: Filter by source system
- `event_type`: Filter by event type
- `severity`: Filter by minimum severity level

**Example**: `ws://localhost:8000/events/stream?source_system=mahavishnu&severity=warning`

## Rate Limiting

Each source system has a rate limit of 1000 events/second with a burst capacity of 2000 events.

```python
# Rate limiting is automatic
for i in range(1500):
    event = EcosystemEvent(
        source_system="mahavishnu",
        event_type="test",
    )
    try:
        await collector.collect_event(event)
    except MahavishnuError as e:
        if "rate limit" in str(e):
            print(f"Rate limited at event {i}")
            break
```

### Rate Limit Configuration

```python
from mahavishnu.integrations.event_collector import RateLimiter

# Custom rate limiter
collector.rate_limiters["mahavishnu"] = RateLimiter(
    requests_per_second=100,  # Lower limit
    burst_size=500,
)
```

## Metrics

The event collector automatically tracks metrics with OpenTelemetry:

- `event_collector_events_collected`: Total events collected (by source_system)
- `event_collector_events_stored`: Total events stored (by source_system)
- `event_collector_queries`: Total event queries
- `event_collector_rate_limit_rejections`: Total rate limit rejections (by source_system)

### View Metrics

```python
from prometheus_client import start_http_server
import time

# Start Prometheus metrics server
start_http_server(9090)

# Collector will automatically emit metrics
collector = EventCollector()
await collector.initialize()

# Metrics available at http://localhost:9090/metrics
```

## Health Monitoring

### Check Health Status

```python
health = await collector.health_check()

print(f"Status: {health['status']}")
print(f"Collector: {health['collector']}")
print(f"Storage: {health['storage']}")
```

### Health Response

```json
{
  "status": "healthy",
  "collector": {
    "healthy": true,
    "started": true,
    "storage_type": "SQLiteEventStorage",
    "events_processed": 1234,
    "active_websockets": 3
  },
  "storage": {
    "status": "healthy",
    "storage_type": "sqlite",
    "db_path": "events.db",
    "total_events": 1234
  }
}
```

## Event Cleanup

Delete old events to manage storage size.

```python
from datetime import datetime, timedelta, timezone

# Delete events older than 30 days
cutoff = datetime.now(timezone.utc) - timedelta(days=30)
deleted = await collector.storage.delete_events_before(cutoff)

print(f"Deleted {deleted} old events")
```

## Integration with Ecosystem

### Process IntegrationEvent

The event collector implements `IntegrationProtocol` and can process `IntegrationEvent` objects:

```python
from mahavishnu.integrations.base import IntegrationEvent, IntegrationRegistry

# Register collector
registry.register(collector)
await registry.initialize_all()

# Publish event to all integrations (including collector)
event = IntegrationEvent(
    source_system="mahavishnu",
    event_type="workflow_complete",
    severity="info",
    data={"workflow_id": "abc123"},
)

await registry.publish_event(event)

# Event is automatically collected
```

## Testing

### Unit Tests

```bash
# Run all tests
pytest tests/unit/test_integrations/test_event_collector.py

# Run specific test
pytest tests/unit/test_integrations/test_event_collector.py::TestEcosystemEvent::test_create_minimal_event

# Run with coverage
pytest --cov=mahavishnu/integrations/event_collector \
       tests/unit/test_integrations/test_event_collector.py
```

### Integration Tests

```python
import pytest
from mahavishnu.integrations.event_collector import EventCollector, EcosystemEvent

@pytest.mark.asyncio
async def test_full_workflow():
    """Test complete event collection workflow."""
    collector = EventCollector(storage_backend="memory")
    await collector.initialize()

    # Collect event
    event = EcosystemEvent(
        source_system="mahavishnu",
        event_type="test",
    )
    await collector.collect_event(event)

    # Query event
    from mahavishnu.integrations.event_collector import EventQuery
    query = EventQuery(source_system="mahavishnu")
    events = await collector.query_events(query)

    assert len(events) == 1
    assert events[0].event_id == event.event_id

    await collector.shutdown()
```

## Best Practices

### 1. Use Correlation IDs

Always include correlation IDs for related events:

```python
import uuid

correlation_id = str(uuid.uuid4())

# Multiple events with same correlation
for step in ["init", "process", "complete"]:
    await collect_event(
        source_system="mahavishnu",
        event_type="workflow_step",
        correlation_id=correlation_id,
        data={"step": step},
    )
```

### 2. Use Tags for Filtering

Add tags for easy filtering:

```python
await collect_event(
    source_system="mahavishnu",
    event_type="deployment",
    tags=["production", "backend", "api"],
)
```

### 3. Choose Appropriate Storage

- **Development/Testing**: Memory storage
- **Production (< 1M events)**: SQLite storage
- **Production (> 1M events)**: Session-Buddy storage
- **Cross-system correlation**: Session-Buddy storage

### 4. Handle Rate Limits

Implement backoff when rate limited:

```python
import asyncio

async def collect_with_backoff(event, max_retries=3):
    for attempt in range(max_retries):
        try:
            await collector.collect_event(event)
            return
        except MahavishnuError as e:
            if "rate limit" in str(e) and attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
```

### 5. Monitor Health

Regularly check health status:

```python
async def monitor_health(collector, interval=60):
    while True:
        health = await collector.health_check()
        if health["status"] != "healthy":
            print(f"Unhealthy: {health}")
        await asyncio.sleep(interval)
```

## Troubleshooting

### Rate Limit Exceeded

**Error**: `MahavishnuError: Rate limit exceeded for mahavishnu`

**Solution**:
- Reduce event frequency
- Use batch collection
- Increase rate limit (custom RateLimiter)

### Storage Connection Failed

**Error**: `MahavishnuError: Failed to connect to SQLite database`

**Solution**:
- Check database file path
- Verify write permissions
- Ensure database file not locked

### Event Not Found

**Error**: Event query returns empty results

**Solution**:
- Verify event was collected
- Check query filters
- Ensure correct time range

### WebSocket Disconnected

**Error**: WebSocket connection drops

**Solution**:
- Implement reconnection logic
- Check network connectivity
- Verify server health

## API Reference

See inline documentation for complete API reference:

```python
from mahavishnu.integrations import event_collector
help(event_collector.EcosystemEvent)
help(event_collector.EventCollector)
help(event_collector.EventQuery)
```

## Performance

### Throughput

- **Memory Storage**: > 100,000 events/second
- **SQLite Storage**: ~10,000 events/second
- **Session-Buddy Storage**: ~5,000 events/second

### Query Performance

- Indexed queries (event_id, source_system, timestamp): < 10ms
- Correlation queries: < 50ms
- Complex filtered queries: < 100ms

### Storage Requirements

- Average event size: ~500 bytes
- 1M events ≈ 500 MB (SQLite)
- Overhead: Indexes (~20% additional space)

## License

MIT License - See LICENSE file for details.
