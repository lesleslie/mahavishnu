# Session-Buddy Polling Integration - Implementation Plan

## Overview
Production-ready async MCP polling integration from Mahavishnu to Session-Buddy for session telemetry collection.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Mahavishnu App                           │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │      SessionBuddyPoller (NEW)                        │  │
│  │  • Async MCP client over HTTP                        │  │
│  │  • Poll Session-Buddy metrics                        │  │
│  │  • Convert to OTel format                           │  │
│  │  • Push to Mahavishnu OTel collector               │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                   │
│                          │ MCP Protocol (HTTP)               │
│                          ↓                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Session-Buddy MCP Server                     │  │
│  │         (http://localhost:8678/mcp)                  │  │
│  │                                                        │  │
│  │  MCP Tools:                                           │  │
│  │  • get_activity_summary                              │  │
│  │  • get_workflow_metrics                              │  │
│  │  • get_session_analytics                             │  │
│  │  • get_performance_metrics                           │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. SessionBuddyPoller (`/Users/les/Projects/mahavishnu/mahavishnu/integrations/session_buddy_poller.py`)

**Key Features:**
- Async MCP client using httpx
- Configurable polling interval
- Graceful degradation on errors
- Circuit breaker pattern
- OTel metric conversion
- Type hints throughout

**Methods:**
- `start()` - Start polling loop
- `stop()` - Stop polling loop
- `poll_once()` - Single polling iteration
- `_call_mcp_tool()` - Call Session-Buddy MCP tool
- `_convert_to_otel()` - Convert metrics to OTel format
- `_record_metrics()` - Record metrics to OTel collector
- `_handle_error()` - Error handling with retries

### 2. Configuration Updates (`settings/mahavishnu.yaml`)

```yaml
# Session-Buddy polling integration
session_buddy_polling:
  enabled: true
  endpoint: "http://localhost:8678/mcp"
  interval_seconds: 30
  timeout_seconds: 10
  max_retries: 3
  retry_delay_seconds: 5
  circuit_breaker_threshold: 5
  metrics_to_collect:
    - activity_summary
    - workflow_metrics
    - session_analytics
    - performance_metrics
```

### 3. Configuration Model (`mahavishnu/core/config.py`)

Add `SessionBuddyPollingSettings` nested model to `MahavishnuSettings`.

### 4. App Integration (`mahavishnu/core/app.py`)

Initialize poller in `MahavishnuApp.__init__()` and manage lifecycle.

## MCP Tools to Poll

Based on Session-Buddy MCP specification:

1. **get_activity_summary**
   - Returns: Session activity data
   - Fields: active_sessions, total_sessions, recent_activity

2. **get_workflow_metrics**
   - Returns: Workflow execution metrics
   - Fields: workflows_completed, workflows_failed, avg_duration

3. **get_session_analytics**
   - Returns: Session statistics
   - Fields: total_checkpoints, avg_checkpoint_size, session_duration

4. **get_performance_metrics**
   - Returns: Performance data
   - Fields: cpu_usage, memory_usage, response_time

## OTel Metric Mapping

### Counters
- `session_buddy.sessions.total` - Total sessions
- `session_buddy.workflows.completed` - Workflows completed
- `session_buddy.workflows.failed` - Workflows failed
- `session_buddy.checkpoints.total` - Total checkpoints

### Gauges
- `session_buddy.sessions.active` - Active sessions
- `session_buddy.performance.cpu_usage` - CPU usage percent
- `session_buddy.performance.memory_usage` - Memory usage MB
- `session_buddy.performance.response_time` - Response time ms

### Histograms
- `session_buddy.workflow.duration` - Workflow duration
- `session_buddy.session.duration` - Session duration
- `session_buddy.checkpoint.size` - Checkpoint size bytes

## Error Handling

- **Connection errors**: Log and retry with backoff
- **Timeout errors**: Log and continue (graceful degradation)
- **Invalid responses**: Log and skip
- **Circuit breaker**: Open after N consecutive failures

## Graceful Degradation

- If Session-Buddy is unavailable, log warning and continue
- If MCP tool call fails, skip that metric
- If OTel recording fails, log but don't crash
- Poller always attempts to recover on next cycle

## Testing

- Unit tests for MCP client calls
- Unit tests for OTel conversion
- Integration tests with mock Session-Buddy
- Error handling tests

## Dependencies

- `httpx` - Async HTTP client (already in pyproject.toml)
- `opentelemetry-api` - OTel metrics API (already in pyproject.toml)
- `tenacity` - Retry logic (already in pyproject.toml)

## Implementation Steps

1. ✅ Create integrations directory
2. ✅ Implement SessionBuddyPoller class
3. ✅ Add configuration model
4. ✅ Update MahavishnuSettings
5. ✅ Integrate into MahavishnuApp
6. ✅ Update configuration YAML
7. ✅ Create usage examples
8. ✅ Add comprehensive docstrings
9. ⏳ Add tests (future work)

## File Structure

```
mahavishnu/
├── integrations/
│   ├── __init__.py
│   └── session_buddy_poller.py    # NEW
├── core/
│   ├── app.py                      # UPDATE
│   └── config.py                   # UPDATE
settings/
└── mahavishnu.yaml                 # UPDATE
```

## Usage Example

```python
from mahavishnu.core import MahavishnuApp

# Initialize app (poller starts automatically)
app = MahavishnuApp()

# Poller runs in background every 30 seconds
# Metrics are automatically pushed to OTel collector

# Check poller status
poller_status = await app.session_buddy_poller.get_status()

# Stop poller
await app.session_buddy_poller.stop()
```

## Configuration Override

```bash
# Disable polling via environment variable
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=false

# Override polling interval
export MAHAVISHNU_SESSION_BUDDY_POLLING__INTERVAL_SECONDS=60

# Override endpoint
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENDPOINT="http://remote-buddy:8678/mcp"
```

## Monitoring

The poller exposes its own metrics:
- `session_buddy_poller.poll_cycles_total` - Total poll cycles
- `session_buddy_poller.poll_errors_total` - Total poll errors
- `session_buddy_poller.poll_duration_seconds` - Poll duration
- `session_buddy_poller.circuit_breaker_state` - Circuit state (0=closed, 1=open)

## Future Enhancements

- Batch metric collection for efficiency
- Webhook support for push-based metrics
- Metric aggregation across multiple Session-Buddy instances
- Custom metric queries
- Alerting on metric thresholds
