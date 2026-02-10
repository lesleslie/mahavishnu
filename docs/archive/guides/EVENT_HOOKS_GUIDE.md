# Event Hooks Integration Guide

Complete guide for integrating the central event collector into all 5 ecosystem systems using event hooks.

## Overview

The event hooks system provides a unified interface for emitting events from all ecosystem systems to a central event collector. This enables:

- **Centralized observability**: All events flow to a single collector
- **Cross-system correlation**: Correlation IDs track requests across systems
- **Resilient event delivery**: Retry logic, circuit breakers, and graceful degradation
- **Performance optimization**: Batch event emission to reduce HTTP overhead
- **Automatic tracking**: Decorator for automatic event emission on function calls

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Mahavishnu    │     │  Crackerjack    │     │ Session-Buddy   │
│                 │     │                 │     │                 │
│ EventHook       │     │ EventHook       │     │ EventHook       │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Event Hook Factory     │
                    │  - Create hooks         │
                    │  - Configure batching   │
                    │  - Circuit breakers     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │  Central Event Collector│
                    │  (http://localhost:8002)│
                    └─────────────────────────┘
```

## System-Specific Events

### 1. Mahavishnu Events

| Event Type | Description | Severity |
|-----------|-------------|----------|
| `workflow_started` | Workflow execution starts | info |
| `workflow_completed` | Workflow completes successfully | info |
| `workflow_failed` | Workflow fails | error |
| `agent_spawned` | New agent spawned | info |
| `pool_scaled` | Pool scales up/down | info |

### 2. Crackerjack Events

| Event Type | Description | Severity |
|-----------|-------------|----------|
| `quality_check_started` | Quality check starts | info |
| `quality_issue_found` | Issue detected | warning/error |
| `quality_score_updated` | Quality score changes | info |
| `test_completed` | Test finishes | info/warning |
| `coverage_calculated` | Coverage computed | info |

### 3. Session-Buddy Events

| Event Type | Description | Severity |
|-----------|-------------|----------|
| `session_created` | Session created | info |
| `session_restored` | Session restored | info |
| `entity_created` | Entity added to knowledge graph | info |
| `relation_created` | Relation created | info |
| `memory_checkpoint` | Memory checkpointed | info |

### 4. Akosha Events

| Event Type | Description | Severity |
|-----------|-------------|----------|
| `pattern_detected` | Pattern identified | info |
| `anomaly_detected` | Anomaly found | warning/error |
| `insight_generated` | Insight created | info |
| `correlation_found` | Correlation discovered | info |

### 5. Oneiric Events

| Event Type | Description | Severity |
|-----------|-------------|----------|
| `adapter_resolved` | Adapter resolved | info |
| `component_loaded` | Component loaded | info |
| `cache_hit` | Cache hit occurs | debug |
| `cache_miss` | Cache miss occurs | debug |

## Usage Examples

### Basic Event Emission

```python
from mahavishnu.integrations import EventHookFactory

# Create hook
hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")

# Emit event
await hook.emit_workflow_started(
    workflow_id="wf_123",
    workflow_type="quality_fix",
    adapter="llamaindex",
    repos=["/path/to/repo1", "/path/to/repo2"],
    correlation_id="corr_abc",
)
```

### With Batch Emission

```python
# Enable batch emission for better performance
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    enable_batching=True,
    batch_size=100,  # Flush after 100 events
    batch_timeout=5.0,  # Flush after 5 seconds
)

await hook.initialize()

# Events are buffered and flushed automatically
await hook.emit_workflow_started(...)
await hook.emit_agent_spawned(...)
# ... more events ...

# Flush remaining events on shutdown
await hook.shutdown()
```

### With Retry Logic

```python
hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")

# Emit with automatic retry (3 retries by default)
await hook.emit_with_retry(
    event_type="workflow_completed",
    severity="info",
    data={
        "workflow_id": "wf_123",
        "duration_seconds": 120.5,
    },
    max_retries=5,  # Custom retry count
)
```

### Using the @track_event Decorator

```python
from mahavishnu.integrations import track_event, EventHookFactory

# Create hook
hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")

# Automatic event tracking
@track_event("workflow_completed", "info", hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result

# Call the function - events are emitted automatically
result = await execute_workflow("wf_123")
```

#### Decorator Options

```python
# Include function arguments in event data
@track_event("workflow", "info", include_args=True, hook=hook)
async def execute_workflow(workflow_id: str, repo: str):
    ...

# Include function result in event data
@track_event("workflow", "info", include_result=True, hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result

# Custom severity level
@track_event("workflow", "warning", hook=hook)
async def execute_workflow(workflow_id: str):
    ...
```

### Cross-System Event Tracking

```python
from mahavishnu.integrations import EventHookFactory

# Create hooks for multiple systems
mahavishnu_hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")
crackerjack_hook = EventHookFactory.create_crackerjack_hook("http://localhost:8002")

# Use same correlation ID across systems
correlation_id = "cross_system_123"

await mahavishnu_hook.emit_workflow_started(
    workflow_id="wf_123",
    workflow_type="quality_fix",
    adapter="llamaindex",
    repos=["/path/to/repo"],
    correlation_id=correlation_id,
)

await crackerjack_hook.emit_quality_check_started(
    check_type="lint",
    repository="/path/to/repo",
    check_id="check_123",
    correlation_id=correlation_id,
)
```

## Configuration

### Circuit Breaker

Prevents cascading failures by stopping requests to a failing collector.

```python
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    circuit_breaker_threshold=5,  # Failures before tripping
    circuit_breaker_timeout=60.0,  # Seconds before recovery attempt
)

# Check circuit breaker status
health = await hook.health_check()
print(health["circuit_breaker_state"])  # "closed", "open", or "half_open"
```

### Batch Buffer Configuration

```python
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    enable_batching=True,
    batch_size=100,  # Maximum events before flush
    batch_timeout=5.0,  # Maximum seconds before flush
)

# Initialize and start auto-flush
await hook.initialize()

# ... use hook ...

# Shutdown and flush remaining events
await hook.shutdown()
```

## Monitoring and Metrics

### Get Hook Metrics

```python
# Get metrics from a single hook
metrics = await hook.health_check()
print(metrics)
# {
#     "status": "healthy",
#     "system": "mahavishnu",
#     "events_emitted": 150,
#     "events_failed": 2,
#     "retry_count": 2,
#     "last_error": null,
#     "last_success_time": "2025-02-05T10:30:00Z",
#     "circuit_breaker_state": "closed",
#     ...
# }
```

### Get Metrics from Multiple Hooks

```python
from mahavishnu.integrations import get_all_hook_metrics

hooks = [
    EventHookFactory.create_mahavishnu_hook("http://localhost:8002"),
    EventHookFactory.create_crackerjack_hook("http://localhost:8002"),
    EventHookFactory.create_session_buddy_hook("http://localhost:8002"),
]

all_metrics = await get_all_hook_metrics(hooks)
print(all_metrics)
# {
#     "mahavishnu": {"status": "healthy", "events_emitted": 150, ...},
#     "crackerjack": {"status": "healthy", "events_emitted": 200, ...},
#     "session_buddy": {"status": "healthy", "events_emitted": 75, ...}
# }
```

## Integration with Existing Code

### Mahavishnu Integration

```python
# In mahavishnu/core/app.py

from mahavishnu.integrations import EventHookFactory

class MahavishnuApp:
    def __init__(self, config):
        self.config = config
        self.event_hook = EventHookFactory.create_mahavishnu_hook(
            collector_url=config.event_collector_url,
            enable_batching=True,
        )

    async def execute_workflow(self, task, adapter_name, repos):
        workflow_id = f"wf_{int(time.time())}"

        # Emit workflow started
        await self.event_hook.emit_workflow_started(
            workflow_id=workflow_id,
            workflow_type=task.get("type", "unknown"),
            adapter=adapter_name,
            repos=repos,
        )

        try:
            # Execute workflow
            result = await self._execute_workflow_impl(task, adapter_name, repos)

            # Emit workflow completed
            await self.event_hook.emit_workflow_completed(
                workflow_id=workflow_id,
                workflow_type=task.get("type", "unknown"),
                duration_seconds=result["duration"],
                adapter=adapter_name,
                repos_processed=len(repos),
            )

            return result

        except Exception as e:
            # Emit workflow failed
            await self.event_hook.emit_workflow_failed(
                workflow_id=workflow_id,
                workflow_type=task.get("type", "unknown"),
                error_message=str(e),
                error_type=type(e).__name__,
                adapter=adapter_name,
            )
            raise
```

### Crackerjack Integration

```python
# In crackerjack/quality.py

from mahavishnu.integrations import EventHookFactory

class QualityChecker:
    def __init__(self, event_collector_url: str):
        self.event_hook = EventHookFactory.create_crackerjack_hook(
            collector_url=event_collector_url,
        )

    async def run_quality_check(self, repository: str, check_type: str):
        check_id = f"check_{int(time.time())}"

        # Emit check started
        await self.event_hook.emit_quality_check_started(
            check_type=check_type,
            repository=repository,
            check_id=check_id,
        )

        issues = []
        for issue in await self._run_check(repository):
            # Emit issue found
            await self.event_hook.emit_quality_issue_found(
                issue_type=issue["type"],
                severity=issue["severity"],
                file_path=issue["file_path"],
                line_number=issue["line_number"],
                message=issue["message"],
                check_id=check_id,
            )
            issues.append(issue)

        # Calculate and emit score
        old_score = 75.0
        new_score = self._calculate_score(issues)

        await self.event_hook.emit_quality_score_updated(
            repository=repository,
            old_score=old_score,
            new_score=new_score,
            score_change=new_score - old_score,
            check_id=check_id,
        )

        return issues
```

## Error Handling

### Graceful Degradation

If the event collector is unavailable, hooks will:

1. **Log events locally**: Events are logged with a warning
2. **Continue execution**: Application continues without interruption
3. **Retry automatically**: Retry logic with exponential backoff
4. **Circuit breaker**: Stop attempting after threshold failures

```python
# Even if collector is down, your code continues to work
await hook.emit_workflow_started(
    workflow_id="wf_123",
    workflow_type="quality_fix",
    adapter="llamaindex",
    repos=["/path/to/repo"],
)

# Check if events are failing
health = await hook.health_check()
if health["status"] == "unavailable":
    print("Event collector is unavailable, events are being logged locally")
```

## Best Practices

1. **Use Correlation IDs**: Always use correlation IDs for cross-system tracking

```python
correlation_id = str(uuid.uuid4())

await mahavishnu_hook.emit_workflow_started(..., correlation_id=correlation_id)
await crackerjack_hook.emit_quality_check_started(..., correlation_id=correlation_id)
```

2. **Enable Batching for High-Volume Events**: Reduce HTTP overhead

```python
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    enable_batching=True,
    batch_size=100,
    batch_timeout=5.0,
)
```

3. **Use @track_event for Automatic Tracking**: Decorate functions for automatic events

```python
@track_event("workflow_completed", "info", include_result=True, hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result
```

4. **Monitor Health**: Regularly check hook health

```python
health = await hook.health_check()
if health["status"] != "healthy":
    logger.warning(f"Event hook health: {health['status']}")
```

5. **Graceful Shutdown**: Always shutdown hooks to flush remaining events

```python
try:
    # ... use hooks ...
finally:
    await hook.shutdown()
```

## Testing

```python
# Mock the event collector for testing
from unittest.mock import patch
import httpx

async def test_workflow_execution():
    hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value.raise_for_status = MagicMock()

        await hook.emit_workflow_started(
            workflow_id="wf_123",
            workflow_type="test",
            adapter="test",
            repos=["/test"],
        )

        assert hook.events_emitted == 1
```

## Complete Example

```python
import asyncio
from mahavishnu.integrations import EventHookFactory

async def main():
    # Create hooks for all systems
    mahavishnu_hook = EventHookFactory.create_mahavishnu_hook(
        collector_url="http://localhost:8002",
        enable_batching=True,
    )

    crackerjack_hook = EventHookFactory.create_crackerjack_hook(
        collector_url="http://localhost:8002",
    )

    # Initialize hooks
    await mahavishnu_hook.initialize()

    # Use correlation ID for cross-system tracking
    correlation_id = "example_123"

    try:
        # Mahavishnu: Workflow started
        await mahavishnu_hook.emit_workflow_started(
            workflow_id="wf_example",
            workflow_type="quality_fix",
            adapter="llamaindex",
            repos=["/path/to/repo"],
            correlation_id=correlation_id,
        )

        # Crackerjack: Quality check
        await crackerjack_hook.emit_quality_check_started(
            check_type="lint",
            repository="/path/to/repo",
            check_id="check_example",
            correlation_id=correlation_id,
        )

        # ... do work ...

        # Mahavishnu: Workflow completed
        await mahavishnu_hook.emit_workflow_completed(
            workflow_id="wf_example",
            workflow_type="quality_fix",
            duration_seconds=120.5,
            adapter="llamaindex",
            repos_processed=1,
            correlation_id=correlation_id,
        )

        # Get metrics
        mahavishnu_health = await mahavishnu_hook.health_check()
        print(f"Mahavishnu events: {mahavishnu_health['events_emitted']}")

    finally:
        # Shutdown hooks
        await mahavishnu_hook.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

## API Reference

### EventHookFactory

| Method | Description |
|--------|-------------|
| `create_mahavishnu_hook(url)` | Create Mahavishnu event hook |
| `create_crackerjack_hook(url)` | Create Crackerjack event hook |
| `create_session_buddy_hook(url)` | Create Session-Buddy event hook |
| `create_akosha_hook(url)` | Create Akosha event hook |
| `create_oneiric_hook(url)` | Create Oneiric event hook |

### BaseEventHook

| Method | Description |
|--------|-------------|
| `emit_event(type, severity, data, correlation_id, tags)` | Emit event |
| `emit_with_retry(type, severity, data, max_retries, tags)` | Emit with retry |
| `initialize()` | Initialize hook |
| `shutdown()` | Shutdown hook |
| `get_metrics()` | Get metrics |
| `health_check()` | Check health |

### Decorators

| Decorator | Description |
|-----------|-------------|
| `@track_event(type, severity, include_args, include_result, hook)` | Auto-track function calls |

### Utility Functions

| Function | Description |
|----------|-------------|
| `emit_multiple_events(events, hook, correlation_id)` | Emit multiple events |
| `get_all_hook_metrics(hooks)` | Get metrics from multiple hooks |

## Troubleshooting

### Events Not Being Sent

1. Check collector URL is correct
2. Verify collector is running: `curl http://localhost:8002/health`
3. Check hook health: `await hook.health_check()`
4. Check circuit breaker state: If "open", wait for recovery timeout

### High Event Failure Rate

1. Increase circuit breaker threshold
2. Increase retry count
3. Enable batch emission
4. Check collector capacity

### Performance Issues

1. Enable batch emission
2. Increase batch size
3. Reduce batch timeout
4. Check network latency to collector

## Further Reading

- [IntegrationEvent Schema](../mahavishnu/integrations/base.py) - Event data structure
- [Resilience Patterns](../mahavishnu/core/resilience.py) - Circuit breaker implementation
- [Observability Manager](../mahavishnu/core/observability.py) - Correlation ID management
- [Test Suite](../../tests/unit/test_integrations/test_event_hooks.py) - Comprehensive tests
