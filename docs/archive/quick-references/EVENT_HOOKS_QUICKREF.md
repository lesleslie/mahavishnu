# Event Hooks Quick Reference

## Quick Start

```python
from mahavishnu.integrations import EventHookFactory

# 1. Create hook
hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")

# 2. Emit event
await hook.emit_workflow_started(
    workflow_id="wf_123",
    workflow_type="quality_fix",
    adapter="llamaindex",
    repos=["/path/to/repo"],
)
```

## All 5 System Hooks

```python
# Mahavishnu (5 events)
mahavishnu = EventHookFactory.create_mahavishnu_hook(url)
await mahavishnu.emit_workflow_started(...)
await mahavishnu.emit_workflow_completed(...)
await mahavishnu.emit_workflow_failed(...)
await mahavishnu.emit_agent_spawned(...)
await mahavishnu.emit_pool_scaled(...)

# Crackerjack (5 events)
crackerjack = EventHookFactory.create_crackerjack_hook(url)
await crackerjack.emit_quality_check_started(...)
await crackerjack.emit_quality_issue_found(...)
await crackerjack.emit_quality_score_updated(...)
await crackerjack.emit_test_completed(...)
await crackerjack.emit_coverage_calculated(...)

# Session-Buddy (5 events)
session_buddy = EventHookFactory.create_session_buddy_hook(url)
await session_buddy.emit_session_created(...)
await session_buddy.emit_session_restored(...)
await session_buddy.emit_entity_created(...)
await session_buddy.emit_relation_created(...)
await session_buddy.emit_memory_checkpoint(...)

# Akosha (4 events)
akosha = EventHookFactory.create_akosha_hook(url)
await akosha.emit_pattern_detected(...)
await akosha.emit_anomaly_detected(...)
await akosha.emit_insight_generated(...)
await akosha.emit_correlation_found(...)

# Oneiric (4 events)
oneiric = EventHookFactory.create_oneiric_hook(url)
await oneiric.emit_adapter_resolved(...)
await oneiric.emit_component_loaded(...)
await oneiric.emit_cache_hit(...)
await oneiric.emit_cache_miss(...)
```

## Common Configuration Options

```python
# Enable batch emission
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    enable_batching=True,
    batch_size=100,        # Flush after 100 events
    batch_timeout=5.0,     # Flush after 5 seconds
)

# Configure circuit breaker
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    circuit_breaker_threshold=5,   # Failures before tripping
    circuit_breaker_timeout=60.0,  # Seconds before recovery
)

# Initialize and shutdown (for batch mode)
await hook.initialize()
# ... use hook ...
await hook.shutdown()
```

## Decorator for Automatic Tracking

```python
from mahavishnu.integrations import track_event

# Basic tracking
@track_event("workflow", "info", hook=hook)
async def execute_workflow(workflow_id: str):
    return await process_workflow(workflow_id)

# With result included
@track_event("workflow", "info", include_result=True, hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result

# With arguments included
@track_event("workflow", "info", include_args=True, hook=hook)
async def execute_workflow(workflow_id: str, repo: str):
    return await process_workflow(workflow_id, repo)
```

## Cross-System Tracking

```python
# Use same correlation ID across systems
correlation_id = "cross_system_123"

await mahavishnu.emit_workflow_started(..., correlation_id=correlation_id)
await crackerjack.emit_quality_check_started(..., correlation_id=correlation_id)
await session_buddy.emit_session_created(..., correlation_id=correlation_id)
```

## Health Check

```python
# Single hook
health = await hook.health_check()
print(health["status"])  # "healthy", "degraded", or "unavailable"
print(health["events_emitted"])
print(health["events_failed"])

# Multiple hooks
from mahavishnu.integrations import get_all_hook_metrics

hooks = [mahavishnu, crackerjack, session_buddy]
all_metrics = await get_all_hook_metrics(hooks)
```

## Retry Logic

```python
# Automatic retry (3 retries by default)
await hook.emit_with_retry(
    event_type="workflow_completed",
    severity="info",
    data={"workflow_id": "wf_123"},
    max_retries=5,  # Custom retry count
)
```

## Utility Functions

```python
from mahavishnu.integrations import emit_multiple_events, get_all_hook_metrics

# Emit multiple events in parallel
events = [
    ("event1", "info", {"data": "test1"}),
    ("event2", "info", {"data": "test2"}),
]
await emit_multiple_events(events, hook, correlation_id="corr_123")

# Get metrics from multiple hooks
all_metrics = await get_all_hook_metrics([hook1, hook2, hook3])
```

## File Locations

- **Implementation**: `/Users/les/Projects/mahavishnu/mahavishnu/integrations/event_hooks.py`
- **Tests**: `/Users/les/Projects/mahavishnu/tests/unit/test_integrations/test_event_hooks.py`
- **Guide**: `/Users/les/Projects/mahavishnu/docs/EVENT_HOOKS_GUIDE.md`
- **Demo**: `/Users/les/Projects/mahavishnu/examples/event_hooks_demo.py`

## Running Tests

```bash
# Run all tests
pytest tests/unit/test_integrations/test_event_hooks.py -v

# Run specific test class
pytest tests/unit/test_integrations/test_event_hooks.py::TestMahavishnuEventHook -v

# Run with coverage
pytest tests/unit/test_integrations/test_event_hooks.py --cov=mahavishnu/integrations/event_hooks
```

## Running Demo

```bash
# Make sure event collector is running at http://localhost:8002
python examples/event_hooks_demo.py
```

## Event Severity Levels

- `debug`: Detailed diagnostic information
- `info`: General informational messages
- `warning`: Warning messages
- `error`: Error messages
- `critical`: Critical error messages

## Common Patterns

### Pattern 1: Workflow Lifecycle

```python
# Start
await hook.emit_workflow_started(workflow_id, workflow_type, adapter, repos)

try:
    # Execute workflow
    result = await execute_workflow(workflow_id)

    # Complete
    await hook.emit_workflow_completed(workflow_id, workflow_type, duration, adapter, repos_processed)
except Exception as e:
    # Fail
    await hook.emit_workflow_failed(workflow_id, workflow_type, str(e), type(e).__name__, adapter)
    raise
```

### Pattern 2: Batch Processing

```python
await hook.initialize()

for item in items:
    await hook.emit_event(item_type, "info", {"data": item})

await hook.shutdown()
```

### Pattern 3: Cross-System Workflow

```python
correlation_id = str(uuid.uuid4())

# Mahavishnu starts workflow
await mahavishnu.emit_workflow_started(..., correlation_id=correlation_id)

# Crackerjack runs quality checks
await crackerjack.emit_quality_check_started(..., correlation_id=correlation_id)

# Session-Buddy stores results
await session_buddy.emit_entity_created(..., correlation_id=correlation_id)

# Mahavishnu completes workflow
await mahavishnu.emit_workflow_completed(..., correlation_id=correlation_id)
```

## Troubleshooting

### Events not being sent

1. Check collector URL: `curl http://localhost:8002/health`
2. Check hook health: `await hook.health_check()`
3. Check circuit breaker: If "open", wait for recovery timeout

### High failure rate

1. Increase circuit breaker threshold
2. Increase retry count
3. Enable batch emission
4. Check collector capacity

### Performance issues

1. Enable batch emission
2. Increase batch size
3. Reduce batch timeout
4. Check network latency

## Further Reading

- [Complete Guide](./EVENT_HOOKS_GUIDE.md)
- [Implementation Summary](./EVENT_HOOKS_README.md)
- [Demo Script](../examples/event_hooks_demo.py)
- [Test Suite](../../tests/unit/test_integrations/test_event_hooks.py)
