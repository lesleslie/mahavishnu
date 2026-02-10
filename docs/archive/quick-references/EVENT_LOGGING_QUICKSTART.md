# Event Logging Quickstart Guide

## 5-Minute Setup

### 1. Initialize Event Collector

```python
from mahavishnu.core.event_collector import init_event_collector

# Start event collector
collector = await init_event_collector(db_path="data/events.db")
```

### 2. Collect Your First Event

```python
from mahavishnu.core.event_collector import System, EventType, Severity

await collector.collect(
    system=System.MAHAVISHNU,
    event_type=EventType.WORKFLOW_STARTED,
    severity=Severity.INFO,
    title="My first event",
    description="This is my first logged event",
    data={"workflow_id": "123"},
    tags=["test"],
)
```

### 3. Query Events

```python
from mahavishnu.core.event_collector import EventQueryBuilder

# Get last hour of events
events = await EventQueryBuilder(collector).time_range(hours=1).execute()

for event in events:
    print(f"{event.timestamp}: {event.title}")
```

That's it! You're now collecting and querying events.

---

## Common Queries

### Get Recent Errors

```python
from mahavishnu.core.event_collector import Severity

errors = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .limit(20)\
    .execute()
```

### Get Events by System

```python
from mahavishnu.core.event_collector import System

mahavishnu_events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .time_range(hours=24)\
    .execute()
```

### Trace Workflow

```python
# Trace all events in a workflow
workflow_events = await EventQueryBuilder(collector)\
    .correlation_id("workflow_123")\
    .execute()
```

### Get Failed Tests

```python
from mahavishnu.core.event_collector import System, EventType

failed_tests = await EventQueryBuilder(collector)\
    .system(System.CRACKERJACK)\
    .event_type(EventType.TEST_FAILED)\
    .time_range(hours=24)\
    .execute()
```

### Search Events

```python
# Search in title and description
results = await EventQueryBuilder(collector)\
    .search("database")\
    .time_range(days=7)\
    .execute()
```

### Count Events

```python
# Count errors in last hour
error_count = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .count()

print(f"Found {error_count} errors")
```

### Get Slow Workflows

```python
# Find workflows taking > 5 seconds
slow_workflows = [
    e for e in await EventQueryBuilder(collector)
        .event_type(EventType.WORKFLOW_COMPLETED)
        .time_range(hours=24)
        .execute()
    if e.duration_ms and e.duration_ms > 5000
]
```

---

## CLI Command Reference

### Basic Commands

```bash
# Show recent events
mahavishnu events query --hours 1

# Show errors only
mahavishnu events query --severity error --hours 24

# Show by system
mahavishnu events query --system mahavishnu --days 7

# Trace workflow
mahavishnu events trace --correlation-id workflow_123

# Show statistics
mahavishnu events stats

# Health check
mahavishnu events health
```

### Advanced Commands

```bash
# Filter by tags
mahavishnu events query --tags workflow,rag --hours 24

# Multiple systems
mahavishnu events query --systems mahavishnu,crackerjack --hours 1

# Error analysis
mahavishnu events analyze-errors --hours 24 --output errors.json

# Generate report
mahavishnu events report --hours 24 --output report.json

# Limit results
mahavishnu events query --hours 1 --limit 50
```

---

## Integration Examples

### Mahavishnu Workflow

```python
from mahavishnu.core.event_collector import (
    get_event_collector,
    System,
    EventType,
    Severity,
)

async def run_workflow(workflow_id: str):
    collector = get_event_collector()

    # Start
    await collector.collect(
        system=System.MAHAVISHNU,
        event_type=EventType.WORKFLOW_STARTED,
        severity=Severity.INFO,
        title=f"Workflow {workflow_id} started",
        description="",
        correlation_id=workflow_id,
    )

    try:
        # Do work...
        result = await execute_workflow(workflow_id)

        # Success
        await collector.collect(
            system=System.MAHAVISHNU,
            event_type=EventType.WORKFLOW_COMPLETED,
            severity=Severity.INFO,
            title=f"Workflow {workflow_id} completed",
            description="",
            correlation_id=workflow_id,
            duration_ms=elapsed_ms,
        )

        return result

    except Exception as e:
        # Error
        await collector.collect(
            system=System.MAHAVISHNU,
            event_type=EventType.WORKFLOW_FAILED,
            severity=Severity.ERROR,
            title=f"Workflow {workflow_id} failed",
            description=str(e),
            correlation_id=workflow_id,
        )
        raise
```

### Crackerjack Test

```python
async def run_test(test_name: str):
    collector = get_event_collector()

    await collector.collect(
        system=System.CRACKERJACK,
        event_type=EventType.TEST_RUN,
        severity=Severity.INFO,
        title=f"Test: {test_name}",
        description="",
        tags=["test"],
    )

    try:
        await run_test(test_name)

        await collector.collect(
            system=System.CRACKERJACK,
            event_type=EventType.TEST_PASSED,
            severity=Severity.INFO,
            title=f"Test passed: {test_name}",
            description="",
            tags=["test", "passed"],
        )
    except AssertionError:
        await collector.collect(
            system=System.CRACKERJACK,
            event_type=EventType.TEST_FAILED,
            severity=Severity.ERROR,
            title=f"Test failed: {test_name}",
            description="",
            tags=["test", "failed"],
        )
```

### Using Decorator

```python
from mahavishnu.core.event_collector import collect_event, System, EventType

@collect_event(System.MAHAVISHNU, EventType.WORKFLOW_STARTED)
async def run_workflow(repo: str):
    """Automatically collects start/completion/error events."""
    await process_repo(repo)
    return {"status": "success"}
```

---

## Analysis Examples

### Error Analysis

```python
from mahavishnu.core.event_collector import EventAnalyzer

analyzer = EventAnalyzer(collector)

# Analyze last 24 hours
analysis = await analyzer.analyze_errors(hours=24)

print(f"Total errors: {analysis['total_errors']}")
print(f"Critical errors: {analysis['critical_errors']}")
print(f"By system: {analysis['errors_by_system']}")
print(f"By component: {analysis['errors_by_component']}")
```

### Pattern Detection

```python
# Detect patterns in last 7 days
patterns = await analyzer.detect_patterns(days=7)

print(f"Total events: {patterns['total_events']}")
print(f"Average duration: {patterns['avg_duration_ms']:.0f}ms")

# Check for anomalies
for anomaly in patterns['patterns']:
    print(f"Anomaly: {anomaly['hour']} - {anomaly['count']} events")
```

### Generate Report

```python
# Generate comprehensive report
report = await analyzer.generate_report(hours=24)

print(f"Period: {report['period_hours']} hours")
print(f"Total events: {report['total_events']}")
print(f"Severity distribution: {report['severity_distribution']}")
print(f"System distribution: {report['system_distribution']}")

# Save to file
import json

with open("report.json", "w") as f:
    json.dump(report, f, indent=2)
```

---

## Real-Time Monitoring

### Subscribe to Events

```python
from mahavishnu.core.event_collector import Event

async def monitor_errors(event: Event):
    """Called for each new event."""
    if event.severity == Severity.ERROR:
        # Send alert
        print(f"ERROR: {event.title}")
        await send_alert(event)

# Subscribe
collector.subscribe(monitor_errors)
```

### Filter Subscriptions

```python
# Subscribe to specific system
async def mahavishnu_monitor(event: Event):
    if event.system == System.MAHAVISHNU:
        print(f"Mahavishnu: {event.title}")

collector.subscribe(mahavishnu_monitor)

# Subscribe to critical events
async def critical_monitor(event: Event):
    if event.severity == Severity.CRITICAL:
        print(f"CRITICAL: {event.title}")
        await page_oncall(event)

collector.subscribe(critical_monitor)
```

---

## Troubleshooting

### Events Not Appearing

```python
# Check health
health = await collector.health_check()
print(f"Status: {health['status']}")

# Check connection
if not health['running']:
    await collector.start()

# Verify query
events = await EventQueryBuilder(collector).execute()
print(f"Total events: {len(events)}")
```

### Slow Queries

```python
# Add specific filters
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .limit(100)\
    .execute()

# Use count for faster results
count = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .time_range(hours=1)\
    .count()
```

### High Memory

```python
# Clean up old events
deleted = await collector._storage.cleanup_old_events(retention_days=30)
print(f"Deleted {deleted} old events")
```

---

## Performance Tips

### 1. Use Limits

```python
# Always limit results
events = await EventQueryBuilder(collector)\
    .time_range(hours=1)\
    .limit(100)\
    .execute()
```

### 2. Be Specific

```python
# Add filters for faster queries
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .severity(Severity.ERROR)\
    .tags(["workflow"])\
    .execute()
```

### 3. Use Count

```python
# Count is faster than querying
count = await EventQueryBuilder(collector)\
    .severity(Severity.ERROR)\
    .count()
```

### 4. Regular Cleanup

```python
# Clean up old events weekly
import asyncio

async def cleanup_task():
    while True:
        await asyncio.sleep(7 * 24 * 60 * 60)  # 1 week
        deleted = await collector._storage.cleanup_old_events(30)
        print(f"Cleaned up {deleted} events")
```

---

## Quick Reference Card

### Event Collection

```python
await collector.collect(
    system=System.MAHAVISHNU,
    event_type=EventType.WORKFLOW_STARTED,
    severity=Severity.INFO,
    title="Event title",
    description="Event description",
    data={"key": "value"},
    tags=["tag1", "tag2"],
    correlation_id="trace_123",
    duration_ms=1500,
)
```

### Query Builder

```python
events = await EventQueryBuilder(collector)\
    .system(System.MAHAVISHNU)\
    .event_type(EventType.WORKFLOW_STARTED)\
    .severity(Severity.INFO)\
    .tags(["workflow"])\
    .time_range(hours=1)\
    .search("keyword")\
    .limit(100)\
    .order_by("timestamp")\
    .execute()
```

### Analyzer

```python
analyzer = EventAnalyzer(collector)

# Error analysis
errors = await analyzer.analyze_errors(hours=24)

# Pattern detection
patterns = await analyzer.detect_patterns(days=7)

# Correlation tracing
traced = await analyzer.trace_correlation("trace_123")

# Generate report
report = await analyzer.generate_report(hours=24)
```

### Systems

- `System.MAHAVISHNU` - Orchestration
- `System.CRACKERJACK` - Quality checks
- `System.SESSION_BUDDY` - Session management
- `System.AKOSHA` - Analytics
- `System.ONEIRIC` - Configuration

### Event Types (Common)

- `EventType.WORKFLOW_STARTED` - Workflow started
- `EventType.WORKFLOW_COMPLETED` - Workflow completed
- `EventType.WORKFLOW_FAILED` - Workflow failed
- `EventType.TEST_RUN` - Test executed
- `EventType.TEST_PASSED` - Test passed
- `EventType.TEST_FAILED` - Test failed
- `EventType.ERROR_OCCURRED` - Error occurred
- `EventType.CODE_INDEXED` - Code indexed

### Severities

- `Severity.DEBUG` - Debug info
- `Severity.INFO` - Informational
- `Severity.WARNING` - Warning
- `Severity.ERROR` - Error
- `Severity.CRITICAL` - Critical

---

## Next Steps

1. **Read Full Guide**: See [CENTRAL_EVENT_LOGGING.md](CENTRAL_EVENT_LOGGING.md)
2. **Explore Examples**: Check `examples/` directory
3. **Run Tests**: `pytest tests/integration/test_event_collector.py`
4. **Monitor Performance**: Use `mahavishnu events stats`

---

**Need Help?**

- Check [CENTRAL_EVENT_LOGGING.md](CENTRAL_EVENT_LOGGING.md) for detailed docs
- Run `mahavishnu events health` to check status
- Enable debug logging: `logging.basicConfig(level=logging.DEBUG)`

---

**Version**: 1.0.0
**Last Updated**: 2025-02-05
