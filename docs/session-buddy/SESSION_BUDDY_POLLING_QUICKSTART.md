# Session-Buddy Polling - Quick Reference

## 5-Minute Setup

### 1. Enable Polling (1 line)

Edit `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`:

```yaml
session_buddy_polling_enabled: true
```

Or use environment variable:

```bash
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=true
```

### 2. Start Polling (2 lines)

```python
from mahavishnu.core import MahavishnuApp
app = MahavishnuApp()
await app.start_poller()
```

### 3. Monitor Status (1 line)

```python
status = await app.session_buddy_poller.get_status()
print(f"Cycles: {status.poll_cycles}, Errors: {status.errors}")
```

That's it! The poller is now collecting metrics every 30 seconds.

______________________________________________________________________

## Configuration Cheatsheet

### Minimal Config

```yaml
session_buddy_polling_enabled: true
```

### Full Config

```yaml
session_buddy_polling_enabled: true
session_buddy_polling_endpoint: "http://localhost:8678/mcp"
session_buddy_polling_interval_seconds: 30
session_buddy_polling_timeout_seconds: 10
session_buddy_polling_max_retries: 3
session_buddy_polling_retry_delay_seconds: 5
session_buddy_polling_circuit_breaker_threshold: 5
session_buddy_polling_metrics_to_collect:
  - get_activity_summary
  - get_workflow_metrics
  - get_session_analytics
  - get_performance_metrics
```

### Environment Variables

```bash
# Enable
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=true

# Endpoint
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENDPOINT="http://localhost:8678/mcp"

# Interval (seconds)
export MAHAVISHNU_SESSION_BUDDY_POLLING__INTERVAL_SECONDS=30

# Timeout (seconds)
export MAHAVISHNU_SESSION_BUDDY_POLLING__TIMEOUT_SECONDS=10

# Retries
export MAHAVISHNU_SESSION_BUDDY_POLLING__MAX_RETRIES=3

# Circuit breaker threshold
export MAHAVISHNU_SESSION_BUDDY_POLLING__CIRCUIT_BREAKER_THRESHOLD=5
```

______________________________________________________________________

## Code Patterns

### Basic Usage

```python
import asyncio
from mahavishnu.core import MahavishnuApp

async def main():
    app = MahavishnuApp()
    await app.start_poller()

    # Run forever or until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        pass

    await app.stop_poller()

asyncio.run(main())
```

### Check Status

```python
status = await app.session_buddy_poller.get_status()

# Status fields
status.running              # bool
status.poll_cycles         # int
status.errors              # int
status.last_poll_time      # datetime
status.last_error          # str | None
status.circuit_breaker_open # bool
```

### Manual Poll

```python
# Single poll cycle
result = await app.session_buddy_poller.poll_once()

print(result['poll_cycle'])       # int
print(result['timestamp'])        # ISO datetime
print(result['metrics_collected']) # list[str]
print(result['errors'])           # list[str]
```

______________________________________________________________________

## Metrics Collected

### Session Metrics

- `session_buddy.sessions.active` (gauge)
- `session_buddy.sessions.total` (counter)

### Workflow Metrics

- `session_buddy.workflows.completed` (counter)
- `session_buddy.workflows.failed` (counter)
- `session_buddy.workflow.duration` (histogram)

### Checkpoint Metrics

- `session_buddy.checkpoints.total` (counter)
- `session_buddy.checkpoint.size` (histogram)

### Performance Metrics

- `session_buddy.performance.cpu_usage` (gauge)
- `session_buddy.performance.memory_usage` (gauge)
- `session_buddy.performance.response_time` (histogram)

### Poller Metrics

- `session_buddy_poller.poll_cycles_total` (counter)
- `session_buddy_poller.poll_errors_total` (counter)
- `session_buddy_poller.poll_duration_seconds` (histogram)
- `session_buddy_poller.circuit_breaker_state` (gauge)

______________________________________________________________________

## Troubleshooting

### Poller not working?

```python
# 1. Check if initialized
if app.session_buddy_poller is None:
    print("Poller not initialized. Check config.")

# 2. Check if enabled
print(f"Enabled: {app.config.session_buddy_polling_enabled}")

# 3. Check endpoint
print(f"Endpoint: {app.config.session_buddy_polling_endpoint}")

# 4. Check status
status = await app.session_buddy_poller.get_status()
print(f"Running: {status.running}")
print(f"Circuit breaker open: {status.circuit_breaker_open}")
print(f"Last error: {status.last_error}")
```

### Connection errors?

```bash
# Test Session-Buddy is reachable
curl http://localhost:8678/mcp

# Check Session-Buddy logs
tail -f /path/to/session-buddy/logs

# Check Mahavishnu logs
tail -f /path/to/mahavishnu/logs
```

### Circuit breaker open?

```python
# Wait for auto-close (5 * interval seconds)
# Or manually reset:
app.session_buddy_poller._circuit_breaker_open = False
app.session_buddy_poller._consecutive_failures = 0
```

______________________________________________________________________

## Common Use Cases

### Development

```yaml
# settings/mahavishnu.yaml
session_buddy_polling_enabled: true
session_buddy_polling_interval_seconds: 10  # Frequent polling
```

### Production

```yaml
session_buddy_polling_enabled: true
session_buddy_polling_interval_seconds: 60  # Less frequent
session_buddy_polling_max_retries: 5        # More retries
session_buddy_polling_circuit_breaker_threshold: 10  # Higher threshold
```

### Testing

```bash
# Disable polling in tests
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=false
```

### High-Frequency Monitoring

```yaml
session_buddy_polling_interval_seconds: 5   # Poll every 5 seconds
session_buddy_polling_timeout_seconds: 3    # Quick timeout
```

______________________________________________________________________

## Health Checks

### Basic Health

```python
status = await app.session_buddy_poller.get_status()

is_healthy = (
    status.running and
    not status.circuit_breaker_open and
    status.errors == 0
)

print(f"Healthy: {is_healthy}")
```

### Detailed Health

```python
status = await app.session_buddy_poller.get_status()

health_report = {
    "poller_running": status.running,
    "circuit_breaker": "OPEN" if status.circuit_breaker_open else "CLOSED",
    "poll_cycles": status.poll_cycles,
    "error_count": status.errors,
    "last_poll": status.last_poll_time,
    "last_error": status.last_error,
}

import json
print(json.dumps(health_report, indent=2, default=str))
```

______________________________________________________________________

## File Locations

### Implementation

- `/Users/les/Projects/mahavishnu/mahavishnu/integrations/session_buddy_poller.py`

### Configuration

- `/Users/les/Projects/mahavishnu/mahavishnu/core/config.py`
- `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`

### App Integration

- `/Users/les/Projects/mahavishnu/mahavishnu/core/app.py`

### Documentation

- `/Users/les/Projects/mahavishnu/SESSION_BUDDY_POLLING_PLAN.md`
- `/Users/les/Projects/mahavishnu/SESSION_BUDDY_POLLING_USAGE.md`
- `/Users/les/Projects/mahavishnu/SESSION_BUDDY_POLLING_SUMMARY.md`
- `/Users/les/Projects/mahavishnu/SESSION_BUDDY_POLLING_QUICKSTART.md` (this file)

______________________________________________________________________

## Key Facts

- **Default Interval**: 30 seconds
- **Default Timeout**: 10 seconds
- **Default Retries**: 3
- **Circuit Breaker**: Opens after 5 consecutive failures
- **Cooldown Period**: 5 * interval seconds (150s default)
- **MCP Protocol**: HTTP-based, uses httpx async client
- **Metrics Format**: OpenTelemetry (OTel)
- **Error Handling**: Graceful degradation, continues on individual failures
- **Dependencies**: httpx, opentelemetry-api (already in project)

______________________________________________________________________

## One-Line Summary

```python
# Enable polling and start collecting metrics
app = MahavishnuApp(); await app.start_poller()
```

______________________________________________________________________

## Need Help?

1. **Quick Issues**: Check this guide
1. **Usage Examples**: See `SESSION_BUDDY_POLLING_USAGE.md`
1. **Architecture**: See `SESSION_BUDDY_POLLING_PLAN.md`
1. **Full Details**: See `SESSION_BUDDY_POLLING_SUMMARY.md`
1. **Source Code**: Check `session_buddy_poller.py` docstrings

______________________________________________________________________

**Status**: Production-Ready ✅
**Version**: 1.0.0
**Date**: 2026-01-31
