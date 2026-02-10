# Event Query Interface - Complete Guide

The Event Query Interface provides powerful querying capabilities for the central event log in Mahavishnu. It includes a fluent query API, advanced analysis tools, and a comprehensive CLI.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [API Usage](#api-usage)
4. [CLI Reference](#cli-reference)
5. [Output Formatters](#output-formatters)
6. [Real-Time Monitoring](#real-time-monitoring)
7. [Examples](#examples)

## Overview

The Event Query Interface consists of several components:

- **EventQueryBuilder**: Fluent query builder for filtering events
- **EventAnalyzer**: Advanced analysis and insights
- **CLI Tool**: Command-line interface for event queries
- **Output Formatters**: Multiple output formats (table, JSON, markdown, HTML)
- **Real-Time Monitoring**: Live event streaming capabilities

## Architecture

### Data Flow

```
┌─────────────────┐
│  EventBus       │
│  (SQLite Store) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│EventQueryBuilder│ ◄─── Filters: system, type, severity, time range
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ EventAnalyzer   │ ◄─── Patterns, Anomalies, Correlations
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Output Formatters│ ◄─── Table, JSON, Markdown, HTML
└─────────────────┘
```

### Key Components

#### EventQueryBuilder

Fluent query builder with chainable methods:

```python
from mahavishnu.integrations.event_query import EventQueryBuilder
from mahavishnu.core.event_bus import get_event_bus

bus = get_event_bus()
query = EventQueryBuilder(bus)

# Build complex query
events = await query.from_system("mahavishnu") \
                    .of_type("worker.started") \
                    .in_last_hours(24) \
                    .execute(limit=100)
```

#### EventAnalyzer

Advanced analysis capabilities:

```python
from mahavishnu.integrations.event_query import EventAnalyzer

analyzer = EventAnalyzer(bus)

# Detect patterns
patterns = await analyzer.detect_patterns()

# Find anomalies
anomalies = await analyzer.find_anomalies()

# Analyze errors
errors = await analyzer.error_analysis()

# Performance analysis
perf = await analyzer.performance_analysis()
```

## API Usage

### Basic Querying

```python
from mahavishnu.integrations.event_query import EventQueryBuilder
from mahavishnu.core.event_bus import get_event_bus

bus = get_event_bus()
query = EventQueryBuilder(bus)

# Get all events
events = await query.execute()

# Get first event
first = await query.first()

# Count events
count = await query.count()

# Check existence
exists = await query.exists()
```

### Filtering

```python
# Filter by source system
query = query.from_system("mahavishnu")

# Filter by event type
query = query.of_type("worker.started")
# or using EventType enum
query = query.of_type(EventType.WORKER_STARTED)

# Filter by severity
query = query.with_severity("error")

# Filter by correlation ID
query = query.with_correlation_id("abc-123")

# Filter by tags
query = query.with_tags("production", "critical")

# Time range filtering
query = query.in_time_range(start, end)
query = query.in_last_hours(24)
query = query.in_last_days(7)

# Filter by data fields
query = query.with_data("worker_id", "worker_1")

# Filter by data containing value
query = query.with_data_contains("tags", "important")

# Limit results
query = query.limit(100)
```

### Grouping and Aggregation

```python
# Group by event type
type_counts = await query.group_by_type()
# {'worker.started': 42, 'worker.error': 3, ...}

# Group by severity
severity_counts = await query.group_by_severity()
# {'info': 100, 'warning': 25, 'error': 5, ...}

# Group by source system
source_counts = await query.group_by_system()
# {'mahavishnu': 150, 'code_index_service': 42, ...}

# Generate timeline
timeline = await query.timeline(interval="1h")
# [{'timestamp': '2025-01-01T00:00:00', 'count': 42}, ...]
```

### Analysis

```python
from mahavishnu.integrations.event_query import EventAnalyzer

analyzer = EventAnalyzer(bus)

# Detect patterns
patterns = await analyzer.detect_patterns()
for pattern in patterns:
    print(f"{pattern.pattern_type}: {pattern.description}")
    print(f"  Frequency: {pattern.frequency}")
    print(f"  Confidence: {pattern.confidence:.0%}")

# Find anomalies
anomalies = await analyzer.find_anomalies()
for anomaly in anomalies:
    print(f"{anomaly.anomaly_type}: {anomaly.description}")
    print(f"  Severity: {anomaly.severity}")

# Trace correlation
correlation = await analyzer.trace_correlation("abc-123")
print(f"Duration: {correlation.duration}")
print(f"Systems: {correlation.systems}")
print(f"Events: {len(correlation.events)}")

# Generate comprehensive report
report = await analyzer.generate_report(
    start=datetime.now(UTC) - timedelta(days=7),
    end=datetime.now(UTC),
)
print(f"Total events: {report.total_events}")
print(f"Event types: {report.event_types}")

# Error analysis
error_analysis = await analyzer.error_analysis()
print(f"Total errors: {error_analysis.total_errors}")
print(f"Recommendations: {error_analysis.recommendations}")

# Performance analysis
perf_analysis = await analyzer.performance_analysis()
print(f"Avg event rate: {perf_analysis.avg_event_rate:.2f} events/sec")
print(f"Peak rate: {perf_analysis.peak_event_rate:.2f} events/sec")
```

## CLI Reference

### Query Events

```bash
# Basic query
mahavishnu events query

# Filter by system
mahavishnu events query --system mahavishnu

# Filter by type
mahavishnu events query --type worker.started

# Filter by severity
mahavishnu events query --severity error

# Time range filtering
mahavishnu events query --last-hours 24
mahavishnu events query --start "2025-01-01T00:00:00" --end "2025-01-31T23:59:59"

# Combine filters
mahavishnu events query \
    --system mahavishnu \
    --type worker.started \
    --last-hours 24 \
    --limit 50

# Output formats
mahavishnu events query --output json
mahavishnu events query --output markdown
```

### Get Event by ID

```bash
mahavishnu events get <event_id>

# With JSON output
mahavishnu events get <event_id> --output json
```

### Trace Correlation

```bash
mahavishnu events trace <correlation_id>
```

### Generate Report

```bash
# Generate table report
mahavishnu events report \
    --start "2025-01-01T00:00:00" \
    --end "2025-01-31T23:59:59"

# Generate markdown report
mahavishnu events report \
    --start "2025-01-01T00:00:00" \
    --end "2025-01-31T23:59:59" \
    --output markdown \
    --file report.md

# Generate HTML report
mahavishnu events report \
    --start "2025-01-01T00:00:00" \
    --end "2025-01-31T23:59:59" \
    --output html \
    --file report.html
```

### Live Tail

```bash
# Tail all events
mahavishnu events tail

# Tail specific system
mahavishnu events tail --system mahavishnu

# Tail errors only
mahavishnu events tail --severity error

# Tail critical errors
mahavishnu events tail --severity critical
```

### Analyze Events

```bash
# Detect patterns
mahavishnu events analyze patterns --last-hours 24

# Find anomalies
mahavishnu events analyze anomalies --last-hours 24

# Analyze errors
mahavishnu events analyze errors --last-hours 24

# Performance analysis
mahavishnu events analyze performance --last-hours 24
```

### Timeline View

```bash
# Hourly timeline
mahavishnu events timeline --interval 1h --last-hours 24

# Daily timeline
mahavishnu events timeline --interval 1d --last-days 30
```

### Statistics

```bash
# Group by type
mahavishnu events stats --group-by type --last-hours 24

# Group by system
mahavishnu events stats --group-by system --last-hours 24

# Group by severity
mahavishnu events stats --group-by severity --last-hours 24
```

## Output Formatters

### TableFormatter

Pretty-printed tables using Rich:

```python
from mahavishnu.integrations.event_query import TableFormatter

formatter = TableFormatter()

# Format events
formatter.format_events(events)

# Format patterns
formatter.format_patterns(patterns)

# Format anomalies
formatter.format_anomalies(anomalies)

# Format correlation
formatter.format_correlation(correlation)

# Format report
formatter.format_report(report)
```

### JSONFormatter

Machine-readable JSON output:

```python
from mahavishnu.integrations.event_query import JSONFormatter

json_str = JSONFormatter.format_events(events)
json_str = JSONFormatter.format_patterns(patterns)
json_str = JSONFormatter.format_report(report)
```

### MarkdownFormatter

Markdown reports:

```python
from mahavishnu.integrations.event_query import MarkdownFormatter

markdown_str = MarkdownFormatter.format_report(report)
```

### HTMLFormatter

HTML reports with charts (using Chart.js):

```python
from mahavishnu.integrations.event_query import HTMLFormatter

html_str = HTMLFormatter.format_report(report)
```

## Real-Time Monitoring

Live event streaming with callbacks:

```python
from mahavishnu.integrations.event_query import tail_events

async def my_callback(event: Event):
    print(f"New event: {event.type.value} from {event.source}")

# Tail all events
await tail_events(bus, {}, my_callback, interval=1.0)

# Tail with filters
filters = {
    "system": "mahavishnu",
    "severity": "error",
}
await tail_events(bus, filters, my_callback)
```

## Examples

### Example 1: Monitor Worker Errors

```python
from mahavishnu.integrations.event_query import EventQueryBuilder, EventAnalyzer

bus = get_event_bus()
query = EventQueryBuilder(bus)

# Get worker errors from last 24 hours
errors = await query.from_system("mahavishnu") \
                    .of_type("worker.error") \
                    .in_last_hours(24) \
                    .execute()

print(f"Found {len(errors)} worker errors")

# Analyze error patterns
analyzer = EventAnalyzer(bus)
error_analysis = await analyzer.error_analysis()

print(f"Top error sources: {error_analysis.top_error_sources}")
print(f"Recommendations:")
for rec in error_analysis.recommendations:
    print(f"  - {rec}")
```

### Example 2: Trace Request Flow

```python
from mahavishnu.integrations.event_query import EventAnalyzer

analyzer = EventAnalyzer(bus)

# Trace correlation chain
correlation = await analyzer.trace_correlation("req-abc-123")

print(f"Request flow: {correlation.correlation_id}")
print(f"Duration: {correlation.duration}")
print(f"Systems involved: {', '.join(correlation.systems)}")
print(f"\nTimeline:")
for entry in correlation.timeline:
    print(f"  {entry['timestamp']}: {entry['type']} ({entry['source']})")
```

### Example 3: Generate Daily Report

```python
from datetime import UTC, datetime, timedelta
from mahavishnu.integrations.event_query import EventAnalyzer, MarkdownFormatter

analyzer = EventAnalyzer(bus)

# Generate report for yesterday
yesterday_start = datetime.now(UTC).replace(hour=0, minute=0, second=0) - timedelta(days=1)
yesterday_end = yesterday_start + timedelta(days=1)

report = await analyzer.generate_report(yesterday_start, yesterday_end)

# Save as markdown
markdown = MarkdownFormatter.format_report(report)
with open("daily_report.md", "w") as f:
    f.write(markdown)

print(f"Report generated: {report.total_events} events, {len(report.errors)} errors")
```

### Example 4: Performance Analysis

```python
from mahavishnu.integrations.event_query import EventAnalyzer

analyzer = EventAnalyzer(bus)
perf = await analyzer.performance_analysis()

print(f"Performance Analysis (last 24h)")
print(f"  Avg rate: {perf.avg_event_rate:.2f} events/sec")
print(f"  Peak rate: {perf.peak_event_rate:.2f} events/sec")

if perf.slowest_operations:
    print(f"\nSlowest Operations:")
    for op in perf.slowest_operations[:5]:
        print(f"  - {op['type']}: {op['duration_ms']}ms")

if perf.bottlenecks:
    print(f"\nBottlenecks:")
    for bottleneck in perf.bottlenecks:
        print(f"  - {bottleneck}")
```

### Example 5: Real-Time Alerting

```python
from mahavishnu.integrations.event_query import tail_events
from mahavishnu.core.event_bus import Event

async def alert_callback(event: Event):
    # Alert on critical errors
    if event.data.get("severity") == "critical":
        print(f"🚨 CRITICAL: {event.type.value}")
        print(f"   Source: {event.source}")
        print(f"   Data: {event.data}")
        # Send alert (email, Slack, etc.)

# Tail for critical errors
await tail_events(bus, {}, alert_callback, interval=5.0)
```

## Data Models

### EventPattern

```python
@dataclass
class EventPattern:
    pattern_type: str      # Type of pattern
    description: str       # Human-readable description
    frequency: int         # How often it occurs
    confidence: float      # Confidence score (0-1)
    examples: list[Event]  # Example events
```

### Anomaly

```python
@dataclass
class Anomaly:
    anomaly_type: str        # Type of anomaly
    description: str         # Human-readable description
    severity: Severity       # Anomaly severity
    timestamp: datetime      # When detected
    events: list[Event]      # Related events
```

### EventCorrelation

```python
@dataclass
class EventCorrelation:
    correlation_id: str            # Correlation identifier
    events: list[Event]            # All events in chain
    duration: timedelta            # Total duration
    systems: set[str]              # Systems involved
    timeline: list[dict[str, Any]] # Chronological timeline
```

### EventReport

```python
@dataclass
class EventReport:
    start_time: datetime
    end_time: datetime
    total_events: int
    event_types: dict[str, int]
    top_sources: list[tuple[str, int]]
    errors: list[Event]
    patterns: list[EventPattern]
    anomalies: list[Anomaly]
```

### ErrorAnalysis

```python
@dataclass
class ErrorAnalysis:
    total_errors: int
    error_types: dict[str, int]
    error_trend: list[dict[str, Any]]
    top_error_sources: list[tuple[str, int]]
    critical_errors: list[Event]
    recommendations: list[str]
```

### PerformanceAnalysis

```python
@dataclass
class PerformanceAnalysis:
    avg_event_rate: float
    peak_event_rate: float
    slowest_operations: list[dict[str, Any]]
    bottlenecks: list[str]
    timeline: list[dict[str, Any]]
```

## Best Practices

1. **Use Time Limits**: Always limit queries by time range to avoid scanning entire event log
   ```python
   await query.in_last_hours(24).execute()
   ```

2. **Use Result Limits**: Set reasonable limits on query results
   ```python
   await query.limit(100).execute()
   ```

3. **Leverage Grouping**: Use grouping for statistics instead of loading all events
   ```python
   counts = await query.group_by_type()
   ```

4. **Schedule Regular Reports**: Automate daily/weekly reports
   ```python
   # Run daily via cron
   report = await analyzer.generate_report(yesterday_start, yesterday_end)
   ```

5. **Monitor Critical Events**: Use tail_events for real-time alerting
   ```python
   await tail_events(bus, {}, alert_callback)
   ```

6. **Analyze Trends**: Use timeline analysis to identify trends
   ```python
   timeline = await query.timeline(interval="1h")
   ```

## Performance Considerations

- Event queries use SQLite with indexed fields (type, timestamp, source)
- Time-based filtering is efficient due to timestamp indexing
- Complex data filtering (e.g., `with_data`) loads events into memory
- For large event logs, consider:
  - Reducing query time windows
  - Using result limits
  - Pre-aggregating statistics
  - Periodic cleanup of old events

## Troubleshooting

### EventBus not initialized

```bash
Error: EventBus not initialized
```

Solution: Start Mahavishnu with EventBus enabled:
```bash
mahavishnu mcp start
```

### No events found

```bash
# Check if events exist
mahavishnu events stats --group-by type
```

### Slow queries

```bash
# Reduce time window
mahavishnu events query --last-hours 1

# Use result limit
mahavishnu events query --limit 50
```

## Related Documentation

- [EventBus Documentation](/Users/les/Projects/mahavishnu/mahavishnu/core/event_bus.py)
- [Integration Guide](/Users/les/Projects/mahavishnu/docs/INTEGRATION_GUIDE.md)
- [A2A Protocol](/Users/les/Projects/mahavishnu/docs/a2a_protocol.md)
