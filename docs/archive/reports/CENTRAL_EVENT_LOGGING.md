# Central Event Logging - Complete Guide

## Table of Contents

1. [Overview and Architecture](#overview-and-architecture)
2. [Event Schema Reference](#event-schema-reference)
3. [Integration Guide](#integration-guide)
4. [Query Examples](#query-examples)
5. [CLI Reference](#cli-reference)
6. [API Reference](#api-reference)
7. [Real-Time Monitoring](#real-time-monitoring)
8. [Analysis and Insights](#analysis-and-insights)
9. [Troubleshooting](#troubleshooting)
10. [Performance Tuning](#performance-tuning)

---

## Overview and Architecture

### What is Central Event Logging?

The Central Event Collector is a unified event logging system that aggregates events from all ecosystem components:

- **Mahavishnu**: Orchestration workflows and pool management
- **Crackerjack**: Quality checks, testing, and validation
- **Session-Buddy**: Session management and state tracking
- **Akosha**: Analytics and insights
- **Oneiric**: Configuration and lifecycle events

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Central Event Collector                     │
│                                                                  │
│  ┌───────────────┐  ┌─────────────────┐  ┌──────────────────┐ │
│  │ Event Ingest  │  │   Query Engine  │  │    Analyzer      │ │
│  │   (1000+/s)   │  │  (Fluent API)   │  │  (Pattern Det.)  │ │
│  └───────────────┘  └─────────────────┘  └──────────────────┘ │
│           │                     │                     │          │
│           └─────────────────────┴─────────────────────┘          │
│                            │                                    │
│                     ┌──────▼──────┐                             │
│                     │  SQLite DB  │                             │
│                     │  (WAL Mode) │                             │
│                     └─────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼────┐      ┌─────▼─────┐     ┌─────▼─────┐
    │Mahavishnu│      │Crackerjack│     │Session-Buddy│
    │  Events  │      │  Events   │     │   Events    │
    └──────────┘      └───────────┘     └────────────┘
```

### Key Features

- **High Performance**: Ingest 1000+ events per second
- **Rich Event Model**: Tags, severity, correlation IDs, durations
- **Fluent Query API**: Build complex queries with a clean API
- **Pattern Detection**: Automatic anomaly detection and insights
- **Real-Time Streaming**: Subscribe to events as they occur
- **Correlation Tracing**: Track related events across systems

### Event Lifecycle

```
1. Event Creation
   ├── System component creates event
   ├── Rich metadata attached (tags, severity, correlation ID)
   └── Timestamp automatically added

2. Event Ingestion
   ├── Event validated and persisted to SQLite
   ├── Indexes updated for fast querying
   └── Subscribers notified in real-time

3. Event Querying
   ├── Fluent query builder constructs SQL
   ├── Results filtered, sorted, and limited
   └── Events returned as Event objects

4. Event Analysis
   ├── Patterns detected over time
   ├── Errors analyzed and grouped
   └── Reports generated with insights
```

---

## Event Schema Reference

### Event Object

```python
@dataclass
class Event:
    id: str                          # Unique UUID4
    timestamp: datetime              # UTC timestamp
    system: System                   # Source system
    event_type: EventType            # Event category
    severity: Severity               # Severity level
    title: str                       # Human-readable title
    description: str                 # Detailed description
    data: dict[str, Any]             # Event payload
    tags: list[str]                  # Filterable tags
    correlation_id: str | None       # For tracing
    source_component: str | None     # Source component
    duration_ms: int | None          # Duration (ms)
    metadata: dict[str, Any]         # Additional metadata
```

### System Enum

```python
class System(str, Enum):
    MAHAVISHNU = "mahavishnu"       # Orchestration
    CRACKERJACK = "crackerjack"     # Quality checks
    SESSION_BUDDY = "session_buddy" # Session management
    AKOSHA = "akosha"               # Analytics
    ONEIRIC = "oneiric"             # Configuration
```

### EventType Enum

```python
class EventType(str, Enum):
    # Lifecycle events
    LIFECYCLE_START = "lifecycle.start"
    LIFECYCLE_STOP = "lifecycle.stop"
    LIFECYCLE_RESTART = "lifecycle.restart"

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_CANCELLED = "workflow.cancelled"

    # Quality events
    QUALITY_CHECK_STARTED = "quality_check.started"
    QUALITY_CHECK_COMPLETED = "quality_check.completed"
    TEST_RUN = "test.run"
    TEST_PASSED = "test.passed"
    TEST_FAILED = "test.failed"

    # Session events
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SESSION_DELETED = "session.deleted"

    # Code indexing
    CODE_INDEXED = "code.indexed"
    CODE_INDEX_FAILED = "code.index_failed"

    # Analytics
    ANALYTICS_QUERY = "analytics.query"
    INSIGHT_DETECTED = "insight.detected"

    # Configuration
    CONFIG_CHANGED = "config.changed"
    CONFIG_RELOADED = "config.reloaded"

    # Errors
    ERROR_OCCURRED = "error.occurred"
    ERROR_RECOVERED = "error.recovered"
```

### Severity Enum

```python
class Severity(str, Enum):
    DEBUG = "debug"       # Detailed diagnostics
    INFO = "info"         # Informational
    WARNING = "warning"   # Warning conditions
    ERROR = "error"       # Error events
    CRITICAL = "critical" # Critical conditions
```

---

## Integration Guide

### 1. Mahavishnu Integration

Hook into Mahavishnu for orchestration events:

```python
from mahavishnu.core.event_collector import (
    get_event_collector,
    System,
    EventType,
    Severity,
)

# In your orchestrator
async def run_workflow(workflow_id: str, repo: str):
    collector = get_event_collector()

    # Collect workflow started
    await collector.collect(
        system=System.MAHAVISHNU,
        event_type=EventType.WORKFLOW_STARTED,
        severity=Severity.INFO,
        title=f"Workflow started: {workflow_id}",
        description=f"Starting workflow for {repo}",
        data={
            "workflow_id": workflow_id,
            "repo": repo,
            "workflow_type": "rag_pipeline",
        },
        tags=["workflow", "rag", "orchestration"],
        correlation_id=workflow_id,  # For tracing
        source_component="orchestrator",
    )

    try:
        # Run workflow...
        await execute_workflow(workflow_id)

        # Collect completion
        await collector.collect(
            system=System.MAHAVISHNU,
            event_type=EventType.WORKFLOW_COMPLETED,
            severity=Severity.INFO,
            title=f"Workflow completed: {workflow_id}",
            description="Workflow executed successfully",
            correlation_id=workflow_id,
            duration_ms=duration,
        )

    except Exception as e:
        # Collect error
        await collector.collect(
            system=System.MAHAVISHNU,
            event_type=EventType.WORKFLOW_FAILED,
            severity=Severity.ERROR,
            title=f"Workflow failed: {workflow_id}",
            description=f"Workflow error: {str(e)}",
            correlation_id=workflow_id,
            data={"error": str(e), "error_type": type(e).__name__},
        )
        raise
```

### 2. Crackerjack Integration

Hook into Crackerjack for quality events:

```python
# In your quality checker
async def run_quality_checks(repo: str):
    collector = get_event_collector()

    # Quality check started
    await collector.collect(
        system=System.CRACKERJACK,
        event_type=EventType.QUALITY_CHECK_STARTED,
        severity=Severity.INFO,
        title="Quality check started",
        description=f"Running quality checks for {repo}",
        data={"repo": repo},
        tags=["quality", "testing"],
        source_component="quality_checker",
    )

    # Run checks...
    results = await execute_checks(repo)

    # Test results
    for test in results.tests:
        await collector.collect(
            system=System.CRACKERJACK,
            event_type=EventType.TEST_PASSED if test.passed else EventType.TEST_FAILED,
            severity=Severity.INFO,
            title=f"Test {test.name}: {test.status}",
            description=f"Test {test.name} {test.status}",
            data={
                "test_name": test.name,
                "test_file": test.file,
                "duration_ms": test.duration,
            },
            tags=["test", "unit"] if test.is_unit else ["test", "integration"],
        )

    # Quality check completed
    await collector.collect(
        system=System.CRACKERJACK,
        event_type=EventType.QUALITY_CHECK_COMPLETED,
        severity=Severity.INFO,
        title="Quality check completed",
        description=f"Quality checks completed: {results.passed}/{results.total} passed",
        data={
            "passed": results.passed,
            "failed": results.failed,
            "skipped": results.skipped,
            "coverage": results.coverage,
        },
    )
```

### 3. Session-Buddy Integration

Hook into Session-Buddy for session events:

```python
# In your session manager
async def create_session(session_id: str, context: dict):
    collector = get_event_collector()

    # Session created
    await collector.collect(
        system=System.SESSION_BUDDY,
        event_type=EventType.SESSION_CREATED,
        severity=Severity.INFO,
        title=f"Session created: {session_id}",
        description="New session created",
        data={
            "session_id": session_id,
            "context": context,
        },
        tags=["session", "created"],
        correlation_id=session_id,
        source_component="session_manager",
    )

async def update_session(session_id: str, updates: dict):
    collector = get_event_collector()

    await collector.collect(
        system=System.SESSION_BUDDY,
        event_type=EventType.SESSION_UPDATED,
        severity=Severity.INFO,
        title=f"Session updated: {session_id}",
        description=f"Session updated with {len(updates)} fields",
        data={
            "session_id": session_id,
            "updates": updates,
        },
        correlation_id=session_id,
        source_component="session_manager",
    )

async def restore_session(session_id: str):
    collector = get_event_collector()

    await collector.collect(
        system=System.SESSION_BUDDY,
        event_type=EventType.SESSION_RESTORED,
        severity=Severity.INFO,
        title=f"Session restored: {session_id}",
        description="Session restored from storage",
        data={"session_id": session_id},
        correlation_id=session_id,
        source_component="session_manager",
    )
```

### 4. Akosha Integration

Hook into Akosha for analytics events:

```python
# In your analytics engine
async def execute_query(query: str, params: dict):
    collector = get_event_collector()

    # Query started
    await collector.collect(
        system=System.AKOSHA,
        event_type=EventType.ANALYTICS_QUERY,
        severity=Severity.INFO,
        title="Analytics query executed",
        description=f"Query: {query[:100]}",
        data={
            "query": query,
            "params": params,
        },
        tags=["analytics", "query"],
        source_component="analytics_engine",
    )

    # Execute...
    results = await run_query(query, params)

    # Insight detected
    if results.has_insights:
        await collector.collect(
            system=System.AKOSHA,
            event_type=EventType.INSIGHT_DETECTED,
            severity=Severity.INFO,
            title="Insight detected",
            description=f"Discovered {len(results.insights)} insights",
            data={
                "insights": results.insights,
                "confidence": results.confidence,
            },
            tags=["insight", "analytics"],
        )

    return results
```

### 5. Oneiric Integration

Hook into Oneiric for configuration events:

```python
# In your configuration manager
async def reload_config(config_path: str):
    collector = get_event_collector()

    # Config reload started
    await collector.collect(
        system=System.ONEIRIC,
        event_type=EventType.CONFIG_RELOADED,
        severity=Severity.INFO,
        title="Configuration reloaded",
        description=f"Reloaded config from {config_path}",
        data={
            "config_path": config_path,
            "config_keys": list(config.keys()),
        },
        tags=["config", "reload"],
        source_component="config_manager",
    )

async def validate_config(config: dict):
    collector = get_event_collector()

    # Validate
    errors = validate(config)

    await collector.collect(
        system=System.ONEIRIC,
        event_type=EventType.CONFIG_VALIDATED,
        severity=Severity.WARNING if errors else Severity.INFO,
        title="Configuration validated",
        description=f"Found {len(errors)} validation errors",
        data={
            "valid": len(errors) == 0,
            "errors": errors,
        },
        tags=["config", "validation"],
    )
```

### Using the Decorator

Simplify event collection with the decorator:

```python
from mahavishnu.core.event_collector import collect_event, System, EventType

@collect_event(System.MAHAVISHNU, EventType.WORKFLOW_STARTED)
async def run_workflow(repo: str):
    """
    This function will automatically collect:
    1. Workflow started event (before execution)
    2. Workflow completed event (after successful execution)
    3. Error event (if exception occurs)
    """
    # Your workflow logic here
    await process_repo(repo)
    return {"status": "success"}
```

---

## Query Examples

### Basic Queries

#### 1. Get All Events from Last Hour

```python
from mahavishnu.core.event_collector import EventQueryBuilder

builder = EventQueryBuilder(collector)
events = await builder.time_range(hours=1).execute()
```

#### 2. Get All Errors

```python
from mahavishnu.core.event_collector import Severity

errors = await EventQueryBuilder(collector).severity(Severity.ERROR).execute()
```

#### 3. Get Events by System

```python
from mahavishnu.core.event_collector import System

mahavishnu_events = await EventQueryBuilder(collector).system(System.MAHAVISHNU).execute()
```

### Advanced Queries

#### 4. Filter by Multiple Systems

```python
events = await EventQueryBuilder(collector)\
    .systems([System.MAHAVISHNU, System.CRACKERJACK])\
    .execute()
```

#### 5. Filter by Severity Levels

```python
from mahavishnu.core.event_collector import Severity

# Get errors and critical events
events = await EventQueryBuilder(collector)\
    .severities([Severity.ERROR, Severity.CRITICAL])\
    .execute()
```

#### 6. Filter by Tags (All Required)

```python
# Events with both "workflow" AND "rag" tags
events = await EventQueryBuilder(collector)\
    .tags(["workflow", "rag"])\
    .execute()
```

#### 7. Filter by Tags (Any Match)

```python
# Events with "test" OR "quality" tag
events = await EventQueryBuilder(collector)\
    .any_tags(["test", "quality"])\
    .execute()
```

#### 8. Time Range Queries

```python
from datetime import datetime, UTC, timedelta

# Explicit time range
since = datetime.now(UTC) - timedelta(hours=2)
until = datetime.now(UTC) - timedelta(hours=1)

events = await EventQueryBuilder(collector)\
    .time_range(since=since, until=until)\
    .execute()

# Last 24 hours
events = await EventQueryBuilder(collector)\
    .time_range(days=1)\
    .execute()
```

#### 9. Correlation Tracing

```python
# Trace all events in a workflow
correlation_id = "workflow_abc123"

events = await EventQueryBuilder(collector)\
    .correlation_id(correlation_id)\
    .execute()
```

#### 10. Search in Title/Description

```python
# Search for "database" in events
events = await EventQueryBuilder(collector)\
    .search("database")\
    .execute()
```

### Complex Queries

#### 11. Multi-Filter Query

```python
# Complex query: Mahavishnu errors from last hour with "workflow" tag
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .tags(["workflow"])\
    .execute()
```

#### 12. Query with Ordering

```python
# Oldest events first
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .order_by("timestamp", ascending=True)\
    .execute()

# Order by duration (longest first)
events = await EventQueryBuilder(collector)\
    .event_type(EventType.WORKFLOW_COMPLETED)\
    .order_by("duration_ms", ascending=False)\
    .execute()
```

#### 13. Query with Limit

```python
# Get last 10 errors
recent_errors = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .limit(10)\
    .execute()
```

#### 14. Count Events

```python
# Count errors in last hour
builder = EventQueryBuilder(collector)
error_count = await builder\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .count()
```

### Query Combinations

#### 15. Complete Complex Query

```python
# Find slow workflows from last 24 hours
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .event_type(EventType.WORKFLOW_COMPLETED)\
    .time_range(days=1)\
    .order_by("duration_ms", ascending=False)\
    .limit(20)\
    .execute()

# Filter for slow ones (> 5 seconds)
slow_workflows = [e for e in events if e.duration_ms and e.duration_ms > 5000]
```

---

## CLI Reference

### Event Collection CLI

```bash
# Query recent events
mahavishnu events query --hours 1

# Query errors
mahavishnu events query --severity error

# Query by system
mahavishnu events query --system mahavishnu

# Query by tags
mahavishnu events query --tags workflow,rag

# Trace correlation
mahavishnu events trace --correlation-id workflow_123

# Show statistics
mahavishnu events stats

# Generate report
mahavishnu events report --hours 24 --output report.json

# Error analysis
mahavishnu events analyze-errors --hours 24

# Health check
mahavishnu events health
```

### Query Examples

```bash
# Last hour of Mahavishnu events
mahavishnu events query --system mahavishnu --hours 1

# Critical errors from all systems
mahavishnu events query --severity critical --days 7

# Failed tests from Crackerjack
mahavishnu events query \
  --system crackerjack \
  --event-type test.failed \
  --hours 24

# Workflow tracing
mahavishnu events trace --correlation-id workflow_abc123

# All events with "production" tag
mahavishnu events query --tags production
```

---

## API Reference

### EventCollector

#### Initialization

```python
from mahavishnu.core.event_collector import EventCollector

collector = EventCollector(db_path="data/events.db")
await collector.start()
```

#### collect()

Collect an event.

```python
event = await collector.collect(
    system=System.MAHAVISHNU,
    event_type=EventType.WORKFLOW_STARTED,
    severity=Severity.INFO,
    title="Workflow started",
    description="RAG pipeline workflow",
    data={"workflow_id": "wf_123"},
    tags=["workflow", "rag"],
    correlation_id="corr_abc",
    source_component="orchestrator",
    duration_ms=1500,
    metadata={"key": "value"},
)
```

#### get_statistics()

Get event statistics.

```python
stats = await collector.get_statistics()
# Returns: {
#     "total_events": 12345,
#     "by_system": {"mahavishnu": 5000, "crackerjack": 3000, ...},
#     "by_severity": {"info": 10000, "error": 500, ...},
#     "last_hour_count": 150
# }
```

#### health_check()

Check collector health.

```python
health = await collector.health_check()
# Returns: {
#     "status": "healthy",
#     "running": True,
#     "db_path": "data/events.db",
#     "subscriber_count": 2
# }
```

### EventQueryBuilder

#### System Filters

```python
# Single system
builder.system(System.MAHAVISHNU)

# Multiple systems
builder.systems([System.MAHAVISHNU, System.CRACKERJACK])
```

#### Event Type Filters

```python
# Single type
builder.event_type(EventType.WORKFLOW_STARTED)

# Multiple types
builder.event_types([EventType.WORKFLOW_STARTED, EventType.WORKFLOW_COMPLETED])
```

#### Severity Filters

```python
# Single severity
builder.severity(Severity.ERROR)

# Multiple severities
builder.severities([Severity.ERROR, Severity.CRITICAL])
```

#### Tag Filters

```python
# All tags must be present
builder.tags(["workflow", "rag"])

# Any tag can be present
builder.any_tags(["test", "quality"])
```

#### Time Range Filters

```python
# Last N units
builder.time_range(minutes=30)
builder.time_range(hours=1)
builder.time_range(days=7)

# Explicit range
builder.time_range(
    since=datetime(2025, 1, 1),
    until=datetime(2025, 1, 2)
)
```

#### Other Filters

```python
# Correlation ID
builder.correlation_id("workflow_123")

# Source component
builder.source_component("orchestrator")

# Search text
builder.search("database error")

# Limit results
builder.limit(100)

# Order
builder.order_by("timestamp", ascending=False)
builder.order_by("duration_ms", ascending=True)
```

#### Execution

```python
# Get events
events = await builder.execute()

# Count only
count = await builder.count()
```

### EventAnalyzer

#### analyze_errors()

Analyze error patterns.

```python
analyzer = EventAnalyzer(collector)

analysis = await analyzer.analyze_errors(hours=24)
# Returns: {
#     "total_errors": 150,
#     "critical_errors": 5,
#     "errors_by_type": {...},
#     "errors_by_system": {...},
#     "errors_by_component": {...},
#     "recent_errors": [...]
# }
```

#### detect_patterns()

Detect patterns and anomalies.

```python
patterns = await analyzer.detect_patterns(days=7)
# Returns: {
#     "total_events": 50000,
#     "hourly_distribution": {...},
#     "event_types": {...},
#     "systems": {...},
#     "avg_duration_ms": 250,
#     "patterns": [...]
# }
```

#### trace_correlation()

Trace related events.

```python
events = await analyzer.trace_correlation("workflow_123")
# Returns: [Event, Event, ...] (chronological order)
```

#### generate_report()

Generate comprehensive report.

```python
report = await analyzer.generate_report(hours=24)
# Returns: {
#     "period_hours": 24,
#     "total_events": 5000,
#     "severity_distribution": {...},
#     "system_distribution": {...},
#     "event_type_distribution": {...},
#     "duration_stats": {...},
#     "recent_events": [...]
# }
```

---

## Real-Time Monitoring

### Subscribing to Events

```python
from mahavishnu.core.event_collector import get_event_collector, Event

collector = get_event_collector()

async def event_subscriber(event: Event):
    """Called for each new event."""
    print(f"New event: {event.title} from {event.system.value}")

    # Filter for errors
    if event.severity == Severity.ERROR:
        # Send alert
        await send_alert(event)

# Subscribe
collector.subscribe(event_subscriber)

# Unsubscribe
collector.unsubscribe(event_subscriber)
```

### Filtering Subscriptions

```python
# Subscribe to errors only
async def error_subscriber(event: Event):
    if event.severity in [Severity.ERROR, Severity.CRITICAL]:
        await handle_error(event)

collector.subscribe(error_subscriber)

# Subscribe to specific system
async def mahavishnu_subscriber(event: Event):
    if event.system == System.MAHAVISHNU:
        await handle_mahavishnu_event(event)

collector.subscribe(mahavishnu_subscriber)
```

### WebSocket Streaming (Future)

```python
# Stream events to WebSocket clients
async def stream_events(websocket):
    """Stream events to WebSocket client."""
    collector = get_event_collector()

    async def subscriber(event: Event):
        await websocket.send_json(event.to_dict())

    collector.subscribe(subscriber)

    try:
        # Keep connection open
        await websocket.wait_closed()
    finally:
        collector.unsubscribe(subscriber)
```

---

## Analysis and Insights

### Error Analysis

```python
analyzer = EventAnalyzer(collector)

# Analyze last 24 hours
errors = await analyzer.analyze_errors(hours=24)

print(f"Total errors: {errors['total_errors']}")
print(f"Critical errors: {errors['critical_errors']}")
print(f"Errors by system: {errors['errors_by_system']}")
print(f"Errors by component: {errors['errors_by_component']}")

# Get recent errors
for error in errors['recent_errors']:
    print(f"  - {error['title']}: {error['description']}")
```

### Pattern Detection

```python
# Detect patterns in last 7 days
patterns = await analyzer.detect_patterns(days=7)

print(f"Total events: {patterns['total_events']}")
print(f"Average duration: {patterns['avg_duration_ms']:.0f}ms")

# Check for anomalies
for anomaly in patterns['patterns']:
    print(f"Anomaly detected: {anomaly['hour']}")
    print(f"  Count: {anomaly['count']}")
    print(f"  Deviation: {anomaly['deviation']:.2f}σ")
```

### Workflow Tracing

```python
# Trace a complete workflow
workflow_id = "workflow_123"
events = await analyzer.trace_correlation(workflow_id)

print(f"Workflow has {len(events)} events")

for event in events:
    print(f"  {event.timestamp}: {event.event_type.value} - {event.title}")

# Calculate total duration
if events[0].duration_ms and events[-1].duration_ms:
    total_ms = events[-1].duration_ms - events[0].duration_ms
    print(f"Total duration: {total_ms}ms")
```

### Custom Reports

```python
# Generate custom report
report = await analyzer.generate_report(hours=24)

# Save to file
import json

with open("event_report.json", "w") as f:
    json.dump(report, f, indent=2)

# Print summary
print(f"Report Period: {report['period_hours']} hours")
print(f"Total Events: {report['total_events']}")
print(f"Severity Distribution: {report['severity_distribution']}")
print(f"System Distribution: {report['system_distribution']}")

# Duration statistics
duration = report['duration_stats']
print(f"Duration Stats:")
print(f"  Min: {duration['min']}ms")
print(f"  Max: {duration['max']}ms")
print(f"  Avg: {duration['avg']:.0f}ms")
```

---

## Troubleshooting

### Common Issues

#### 1. Events Not Appearing

**Problem**: Events collected but not returned in queries.

**Solution**:
- Check database connection: `await collector.health_check()`
- Verify filters are correct
- Check time ranges: `await builder.time_range(days=1).execute()`

#### 2. Slow Query Performance

**Problem**: Queries taking too long.

**Solutions**:
- Add more specific filters
- Use `limit()` to reduce results
- Check indexes exist: SQLite should auto-create indexes
- Consider archiving old events

#### 3. High Memory Usage

**Problem**: Event collector using too much memory.

**Solutions**:
- Archive old events regularly
- Use `cleanup_old_events()` to delete old data
- Reduce subscriber count
- Use pagination with `limit()` and `offset`

#### 4. Subscriber Errors

**Problem**: Subscriber errors affecting collector.

**Solution**:
- Subscriber errors are caught and logged
- They don't stop event collection
- Check logs for subscriber error details

#### 5. Database Locked

**Problem**: SQLite database locked errors.

**Solutions**:
- WAL mode is enabled by default
- Ensure only one collector instance
- Close connections properly
- Check for long-running transactions

### Debug Mode

Enable debug logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("mahavishnu.core.event_collector").setLevel(logging.DEBUG)
```

### Database Inspection

Inspect SQLite database directly:

```bash
sqlite3 data/events_collector.db

# Check event count
SELECT COUNT(*) FROM events;

# Check by system
SELECT system, COUNT(*) FROM events GROUP BY system;

# Check by severity
SELECT severity, COUNT(*) FROM events GROUP BY severity;

# Check recent events
SELECT * FROM events ORDER BY timestamp DESC LIMIT 10;

# Check indexes
.indexes
```

---

## Performance Tuning

### Optimization Tips

#### 1. Batch Operations

```python
# Collect multiple events efficiently
async def collect_batch(events_data):
    tasks = [
        collector.collect(
            system=data["system"],
            event_type=data["event_type"],
            severity=data["severity"],
            title=data["title"],
            description=data["description"],
        )
        for data in events_data
    ]
    await asyncio.gather(*tasks)
```

#### 2. Query Optimization

```python
# Add specific filters for faster queries
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .limit(100)\
    .execute()
```

#### 3. Use Count Instead of Query

```python
# Faster if you only need the count
count = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .count()
```

#### 4. Regular Cleanup

```python
# Clean up old events regularly
async def cleanup_events():
    deleted = await collector._storage.cleanup_old_events(retention_days=30)
    print(f"Deleted {deleted} old events")

# Run weekly
```

### Performance Benchmarks

Expected performance on modern hardware:

- **Single event ingestion**: < 10ms
- **Batch ingestion**: 1000+ events/second
- **Simple query**: < 50ms for 1000 results
- **Complex query**: < 200ms for 1000 results
- **Count query**: < 20ms
- **Health check**: < 10ms

### Monitoring Performance

```python
# Monitor collector performance
async def monitor_performance():
    while True:
        health = await collector.health_check()
        stats = await collector.get_statistics()

        print(f"Status: {health['status']}")
        print(f"Total events: {stats['total_events']}")
        print(f"Last hour: {stats['last_hour_count']}")

        await asyncio.sleep(60)  # Check every minute
```

### Scaling Considerations

For high-volume scenarios:

1. **Database File**: Place on fast storage (SSD)
2. **Connection Pooling**: Not needed for SQLite (single writer)
3. **Archiving**: Regularly archive old events
4. **Monitoring**: Track performance metrics
5. **Alternative Storage**: Consider Redis for very high throughput

---

## Best Practices

### 1. Event Design

- **Use meaningful titles**: Clear, descriptive event titles
- **Add context**: Include relevant data in event payload
- **Tag properly**: Use consistent tags for filtering
- **Set severity**: Use appropriate severity levels
- **Correlate events**: Use correlation IDs for related events

### 2. Query Design

- **Be specific**: Add filters to reduce result set
- **Use limits**: Always limit result set size
- **Order carefully**: Ordering can be expensive
- **Count first**: Use count() before querying large sets

### 3. Analysis

- **Regular reports**: Generate daily/weekly reports
- **Monitor errors**: Set up error analysis alerts
- **Trace workflows**: Use correlation IDs for debugging
- **Detect patterns**: Run pattern detection regularly

### 4. Performance

- **Clean up regularly**: Archive old events
- **Monitor metrics**: Track collector performance
- **Optimize queries**: Use specific filters
- **Batch operations**: Group related events

### 5. Integration

- **Hook early**: Integrate at component initialization
- **Handle errors**: Don't let event collection break main logic
- **Use decorators**: Simplify common patterns
- **Subscribe carefully**: Avoid expensive subscribers

---

## Appendix

### Complete Event Type List

See [Event Schema Reference](#event-schema-reference) for full enum definitions.

### Complete Severity List

See [Event Schema Reference](#event-schema-reference) for severity definitions.

### Database Schema

```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    system TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    data TEXT NOT NULL,
    tags TEXT NOT NULL,
    correlation_id TEXT,
    source_component TEXT,
    duration_ms INTEGER,
    metadata TEXT NOT NULL
);

CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_system ON events(system);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_severity ON events(severity);
CREATE INDEX idx_events_correlation ON events(correlation_id);
CREATE INDEX idx_events_component ON events(source_component);
```

### Related Documentation

- [Event Bus Documentation](event_bus.md)
- [CLI Reference](API_REFERENCE.md)
- [Architecture Guide](ECOSYSTEM_ARCHITECTURE.md)

---

**Version**: 1.0.0
**Last Updated**: 2025-02-05
**Maintainer**: Mahavishnu Team
