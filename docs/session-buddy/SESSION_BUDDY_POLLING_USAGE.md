# Session-Buddy Polling Integration - Usage Examples

This document provides practical usage examples for the Session-Buddy polling integration in Mahavishnu.

## Table of Contents

- [Basic Usage](#basic-usage)
- [Configuration](#configuration)
- [Advanced Usage](#advanced-usage)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## Basic Usage

### 1. Enable Polling in Configuration

Edit `/Users/les/Projects/mahavishnu/settings/mahavishnu.yaml`:

```yaml
# Session-Buddy polling integration
session_buddy_polling_enabled: true  # Enable polling
session_buddy_polling_endpoint: "http://localhost:8678/mcp"
session_buddy_polling_interval_seconds: 30  # Poll every 30 seconds
```

### 2. Start Polling with Mahavishnu App

```python
import asyncio
from mahavishnu.core import MahavishnuApp

async def main():
    # Initialize app (poller is auto-initialized if enabled in config)
    app = MahavishnuApp()

    # Start the poller
    await app.start_poller()

    # Poller now runs in background, collecting metrics every 30 seconds
    print("Poller is running...")

    # Keep application running
    try:
        while True:
            await asyncio.sleep(60)
            status = await app.session_buddy_poller.get_status()
            print(f"Poll cycles: {status.poll_cycles}, Errors: {status.errors}")
    except KeyboardInterrupt:
        pass

    # Stop poller before shutdown
    await app.stop_poller()

if __name__ == "__main__":
    asyncio.run(main())
```

### 3. Manual Polling (Single Cycle)

```python
import asyncio
from mahavishnu.core import MahavishnuApp

async def main():
    app = MahavishnuApp()

    if app.session_buddy_poller:
        # Execute a single poll cycle
        result = await app.session_buddy_poller.poll_once()

        print(f"Poll cycle: {result['poll_cycle']}")
        print(f"Metrics collected: {result['metrics_collected']}")
        print(f"Errors: {result['errors']}")

asyncio.run(main())
```

## Configuration

### YAML Configuration

```yaml
# settings/mahavishnu.yaml
session_buddy_polling_enabled: true
session_buddy_polling_endpoint: "http://localhost:8678/mcp"
session_buddy_polling_interval_seconds: 30  # Poll every 30 seconds
session_buddy_polling_timeout_seconds: 10  # HTTP timeout
session_buddy_polling_max_retries: 3  # Retry failed calls
session_buddy_polling_retry_delay_seconds: 5  # Base retry delay
session_buddy_polling_circuit_breaker_threshold: 5  # Open circuit after 5 failures
session_buddy_polling_metrics_to_collect:  # MCP tools to poll
  - get_activity_summary
  - get_workflow_metrics
  - get_session_analytics
  - get_performance_metrics
```

### Environment Variable Override

```bash
# Disable polling
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=false

# Change polling interval to 60 seconds
export MAHAVISHNU_SESSION_BUDDY_POLLING__INTERVAL_SECONDS=60

# Use remote Session-Buddy server
export MAHAVISHNU_SESSION_BUDDY_POLLING__ENDPOINT="http://remote-buddy:8678/mcp"

# Poll only specific metrics
export MAHAVISHNU_SESSION_BUDDY_POLLING__METRICS_TO_COLLECT='["get_activity_summary","get_workflow_metrics"]'
```

### Programmatic Configuration

```python
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core import MahavishnuApp

# Create custom config
config = MahavishnuSettings(
    session_buddy_polling_enabled=True,
    session_buddy_polling_endpoint="http://localhost:8678/mcp",
    session_buddy_polling_interval_seconds=15,  # Poll every 15 seconds
)

# Initialize app with custom config
app = MahavishnuApp(config=config)
```

## Advanced Usage

### Custom Metrics Collection

```python
from mahavishnu.core import MahavishnuApp
from mahavishnu.integrations import SessionBuddyPoller

async def poll_specific_metrics():
    app = MahavishnuApp()

    # Access poller directly
    poller: SessionBuddyPoller = app.session_buddy_poller

    if poller:
        # Customize which metrics to collect
        poller.metrics_to_collect = [
            "get_activity_summary",
            "get_workflow_metrics",
            # Skip session_analytics and performance_metrics
        ]

        # Start polling with custom metric list
        await poller.start()

        # Run for a while...
        await asyncio.sleep(60)

        # Stop poller
        await poller.stop()

asyncio.run(poll_specific_metrics())
```

### Poller Status Monitoring

```python
import asyncio
from mahavishnu.core import MahavishnuApp
from mahavishnu.integrations.session_buddy_poller import PollerStatus

async def monitor_poller():
    app = MahavishnuApp()
    await app.start_poller()

    # Monitor poller status every 10 seconds
    while True:
        status: PollerStatus = await app.session_buddy_poller.get_status()

        print(f"""
        Poller Status:
        - Running: {status.running}
        - Poll Cycles: {status.poll_cycles}
        - Errors: {status.errors}
        - Last Poll: {status.last_poll_time}
        - Last Error: {status.last_error}
        - Circuit Breaker Open: {status.circuit_breaker_open}
        """)

        if status.circuit_breaker_open:
            print("WARNING: Circuit breaker is open! Polling is paused.")

        await asyncio.sleep(10)

asyncio.run(monitor_poller())
```

### Integration with OpenTelemetry

The poller automatically records metrics to OpenTelemetry. Here's how to access them:

```python
import asyncio
from mahavishnu.core import MahavishnuApp

async def otel_integration():
    app = MahavishnuApp()
    await app.start_poller()

    # Metrics are automatically recorded to OTel
    # View metrics in your OTel dashboard (Grafana, Prometheus, etc.)

    # Example metric names created:
    # - session_buddy.sessions.active (gauge)
    # - session_buddy.sessions.total (counter)
    # - session_buddy.workflows.completed (counter)
    # - session_buddy.workflows.failed (counter)
    # - session_buddy.workflow.duration (histogram)
    # - session_buddy.checkpoints.total (counter)
    # - session_buddy.performance.cpu_usage (gauge)
    # - session_buddy.performance.memory_usage (gauge)

    # Run for a while to collect metrics
    await asyncio.sleep(300)  # 5 minutes

    await app.stop_poller()

asyncio.run(otel_integration())
```

### Custom Error Handling

```python
import asyncio
import logging
from mahavishnu.core import MahavishnuApp

async def poll_with_custom_error_handling():
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    app = MahavishnuApp()

    if app.session_buddy_poller:
        # The poller has built-in error handling, but you can monitor it
        await app.start_poller()

        while True:
            status = await app.session_buddy_poller.get_status()

            # Check for errors
            if status.errors > 0:
                logger.warning(f"Poller has {status.errors} errors")
                if status.last_error:
                    logger.error(f"Last error: {status.last_error}")

            # Check circuit breaker
            if status.circuit_breaker_open:
                logger.critical("Circuit breaker is open! Polling paused.")
                # Implement custom recovery logic here

            await asyncio.sleep(30)

asyncio.run(poll_with_custom_error_handling())
```

## Monitoring

### Poller Metrics

The poller exposes its own metrics:

```python
# Metrics created by the poller:
session_buddy_poller.poll_cycles_total  # Counter: Total poll cycles
session_buddy_poller.poll_errors_total  # Counter: Total poll errors
session_buddy_poller.poll_duration_seconds  # Histogram: Poll duration
session_buddy_poller.circuit_breaker_state  # Gauge: Circuit state (0=closed, 1=open)
```

### Checking Poller Health

```python
async def check_poller_health():
    app = MahavishnuApp()
    await app.start_poller()

    status = await app.session_buddy_poller.get_status()

    # Health check criteria
    is_healthy = (
        status.running and
        not status.circuit_breaker_open and
        status.errors == 0
    )

    print(f"Poller healthy: {is_healthy}")

asyncio.run(check_poller_health())
```

### Log Monitoring

```python
import logging

# Enable poller debug logging
logging.getLogger("mahavishnu.integrations.session_buddy_poller").setLevel(logging.DEBUG)

# Poller will now log:
# - Each poll cycle start/end
# - MCP tool calls
# - Metric conversion details
# - OTel recording
# - Circuit breaker state changes
# - Error details with stack traces
```

## Troubleshooting

### Poller Not Starting

```python
from mahavishnu.core import MahavishnuApp

app = MahavishnuApp()

# Check if poller is initialized
if app.session_buddy_poller is None:
    print("Poller not initialized. Check configuration:")
    print(f"  - Enabled: {app.config.session_buddy_polling_enabled}")
    print(f"  - Endpoint: {app.config.session_buddy_polling_endpoint}")
else:
    print("Poller initialized successfully")
```

### Connection Errors

```python
from mahavishnu.core import MahavishnuApp

app = MahavishnuApp()

# Test connection to Session-Buddy
if app.session_buddy_poller:
    try:
        # Try a single poll cycle
        result = await app.session_buddy_poller.poll_once()
        print(f"Connection successful! Metrics: {result['metrics_collected']}")
    except Exception as e:
        print(f"Connection failed: {e}")
        print("Check:")
        print("  1. Session-Buddy is running at the configured endpoint")
        print("  2. Endpoint URL is correct")
        print("  3. Network connectivity")
        print("  4. Firewall settings")
```

### Circuit Breaker Issues

```python
from mahavishnu.core import MahavishnuApp

async def reset_circuit_breaker():
    app = MahavishnuApp()
    await app.start_poller()

    status = await app.session_buddy_poller.get_status()

    if status.circuit_breaker_open:
        print("Circuit breaker is open. Waiting for cooldown...")

        # Circuit breaker auto-closes after cooldown period (5 * interval)
        # Or manually reset:
        app.session_buddy_poller._circuit_breaker_open = False
        app.session_buddy_poller._consecutive_failures = 0
        print("Circuit breaker manually reset")

asyncio.run(reset_circuit_breaker())
```

### No Metrics Being Collected

```python
from mahavishnu.core import MahavishnuApp

async def debug_metrics():
    app = MahavishnuApp()

    # Enable debug logging
    import logging
    logging.getLogger("mahavishnu.integrations.session_buddy_poller").setLevel(logging.DEBUG)

    # Run a single poll cycle with verbose output
    if app.session_buddy_poller:
        result = await app.session_buddy_poller.poll_once()

        print(f"Poll cycle: {result['poll_cycle']}")
        print(f"Timestamp: {result['timestamp']}")
        print(f"Metrics collected: {result['metrics_collected']}")
        print(f"Errors: {result['errors']}")

        # Check configuration
        print(f"\nConfigured metrics: {app.session_buddy_poller.metrics_to_collect}")
        print(f"Available tools: {app.session_buddy_poller.MCP_TOOLS}")

asyncio.run(debug_metrics())
```

## Production Deployment

### systemd Service Example

```ini
# /etc/systemd/system/mahavishnu.service
[Unit]
Description=Mahavishnu Orchestrator with Session-Buddy Polling
After=network.target session-buddy.service

[Service]
Type=simple
User=mahavishnu
WorkingDirectory=/opt/mahavishnu
Environment="MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=true"
Environment="MAHAVISHNU_SESSION_BUDDY_POLLING__ENDPOINT=http://localhost:8678/mcp"
ExecStart=/opt/mahavishnu/.venv/bin/python -m mahavishnu.mcp start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Docker Compose Example

```yaml
version: '3.8'
services:
  session-buddy:
    image: session-buddy:latest
    ports:
      - "8678:8678"

  mahavishnu:
    image: mahavishnu:latest
    environment:
      - MAHAVISHNU_SESSION_BUDDY_POLLING__ENABLED=true
      - MAHAVISHNU_SESSION_BUDDY_POLLING__ENDPOINT=http://session-buddy:8678/mcp
      - MAHAVISHNU_SESSION_BUDDY_POLLING__INTERVAL_SECONDS=30
    depends_on:
      - session-buddy
```

## Summary

The Session-Buddy polling integration provides:

- **Automatic metric collection** from Session-Buddy at configurable intervals
- **OTel integration** for metrics export to Prometheus, Grafana, etc.
- **Resilience** with circuit breaker and retry logic
- **Graceful degradation** when Session-Buddy is unavailable
- **Type-safe configuration** with Pydantic validation
- **Comprehensive error handling** and logging

For more details, see:

- [Implementation Plan](SESSION_BUDDY_POLLING_PLAN.md)
- [Configuration](/Users/les/Projects/mahavishnu/mahavishnu/core/config.py)
