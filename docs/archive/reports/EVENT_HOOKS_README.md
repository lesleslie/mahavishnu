# Event Hooks Implementation Summary

## Overview

A comprehensive event hooks system has been implemented to integrate the central event collector into all 5 ecosystem systems: Mahavishnu, Crackerjack, Session-Buddy, Akosha, and Oneiric.

## Implementation Location

**Main Implementation**: `/Users/les/Projects/mahavishnu/mahavishnu/integrations/event_hooks.py`

**Tests**: `/Users/les/Projects/mahavishnu/tests/unit/test_integrations/test_event_hooks.py`

**Documentation**: `/Users/les/Projects/mahavishnu/docs/EVENT_HOOKS_GUIDE.md`

**Demo**: `/Users/les/Projects/mahavishnu/examples/event_hooks_demo.py`

## Features Implemented

### 1. Base Event Hook

The `BaseEventHook` class provides shared functionality for all event hooks:

- **Async event emission** with HTTP POST to collector
- **Retry logic** with exponential backoff (configurable max retries)
- **Circuit breaker** for collector failures (prevents cascading failures)
- **Batch event emission** to reduce HTTP overhead
- **Automatic correlation ID** generation and propagation
- **System context enrichment** (adds system name, timestamp to all events)
- **Graceful degradation** (logs locally if collector unavailable)
- **Metrics tracking** (events_emitted, events_failed, retry_count, last_error)

### 2. System-Specific Event Hooks

#### Mahavishnu Event Hook (5 events)

- `workflow_started`: When workflow execution starts
- `workflow_completed`: When workflow completes successfully
- `workflow_failed`: When workflow fails
- `agent_spawned`: When new agent is spawned
- `pool_scaled`: When pool scales up/down

#### Crackerjack Event Hook (5 events)

- `quality_check_started`: When quality check starts
- `quality_issue_found`: When issue is detected
- `quality_score_updated`: When score changes
- `test_completed`: When test finishes
- `coverage_calculated`: When coverage is computed

#### Session-Buddy Event Hook (5 events)

- `session_created`: When session is created
- `session_restored`: When session is restored
- `entity_created`: When entity is added to knowledge graph
- `relation_created`: When relation is created
- `memory_checkpoint`: When memory is checkpointed

#### Akosha Event Hook (4 events)

- `pattern_detected`: When pattern is identified
- `anomaly_detected`: When anomaly is found
- `insight_generated`: When insight is created
- `correlation_found`: When correlation is discovered

#### Oneiric Event Hook (4 events)

- `adapter_resolved`: When adapter is resolved
- `component_loaded`: When component is loaded
- `cache_hit`: When cache hit occurs
- `cache_miss`: When cache miss occurs

**Total: 23 distinct event types across 5 systems**

### 3. Event Hook Factory

The `EventHookFactory` provides a consistent interface for creating system-specific hooks:

```python
hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")
hook = EventHookFactory.create_crackerjack_hook("http://localhost:8002")
hook = EventHookFactory.create_session_buddy_hook("http://localhost:8002")
hook = EventHookFactory.create_akosha_hook("http://localhost:8002")
hook = EventHookFactory.create_oneiric_hook("http://localhost:8002")
```

### 4. @track_event Decorator

Automatic event emission on function calls:

```python
@track_event("workflow_completed", "info", include_result=True, hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result

# Events are emitted automatically:
# - Before execution: workflow_completed_starting
# - After success: workflow_completed_success (with result)
# - After failure: workflow_completed_failed (with error)
```

### 5. Batch Event Buffer

Buffer for batch event emission to reduce HTTP overhead:

- Automatic flushing when buffer reaches size limit (default: 100 events)
- Automatic flushing after timeout (default: 5 seconds)
- Graceful shutdown with flush
- Thread-safe for async operations

### 6. Utility Functions

- `emit_multiple_events()`: Emit multiple events in parallel
- `get_all_hook_metrics()`: Get metrics from multiple hooks

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Your Application                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ @track_event or manual emit
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              System-Specific Event Hooks                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │Mahavishnu│  │Crackerjack│  │Session   │  │Akosha    │  │
│  │   Hook   │  │   Hook    │  │  Buddy   │  │  Hook    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │             │              │              │         │
│       └─────────────┴──────────────┴──────────────┘         │
│                         │                                   │
│                   ┌─────┴─────┐                             │
│                   │BaseEventHook│                            │
│                   │             │                            │
│                   │ • Retry    │                            │
│                   │ • Circuit  │                            │
│                   │   Breaker  │                            │
│                   │ • Batch    │                            │
│                   │   Buffer   │                            │
│                   │ • Metrics  │                            │
│                   └─────┬──────┘                             │
└────────────────────────┼────────────────────────────────────┘
                         │
                         │ HTTP POST
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Central Event Collector                         │
│            (http://localhost:8002)                          │
│                                                             │
│  • Receives events from all systems                         │
│  • Stores events in database                                │
│  • Enables cross-system correlation tracking                │
│  • Provides query and analysis API                          │
└─────────────────────────────────────────────────────────────┘
```

## Resilience Features

### 1. Circuit Breaker Pattern

Prevents cascading failures by stopping requests to a failing collector:

- **CLOSED**: Normal operation, requests flow through
- **OPEN**: Circuit tripped, requests are blocked
- **HALF_OPEN**: Testing if collector has recovered

Configuration:
```python
hook = EventHookFactory.create_mahavishnu_hook(
    collector_url="http://localhost:8002",
    circuit_breaker_threshold=5,  # Failures before tripping
    circuit_breaker_timeout=60.0,  # Seconds before recovery attempt
)
```

### 2. Retry Logic with Exponential Backoff

Automatic retry with exponential backoff and jitter:

- Default: 3 retries with 2x backoff
- Configurable max retries
- Jitter to prevent thundering herd

```python
await hook.emit_with_retry(
    event_type="workflow_completed",
    severity="info",
    data={"test": "data"},
    max_retries=5,  # Custom retry count
)
```

### 3. Graceful Degradation

If collector is unavailable:
- Events are logged locally with warning
- Application continues without interruption
- No exceptions propagated to caller
- Circuit breaker prevents repeated failures

## Testing

Comprehensive test suite with 48 tests covering:

- Base event hook functionality
- All 5 system-specific hooks
- Event factory methods
- Decorator for automatic event tracking
- Batch event buffering
- Circuit breaker behavior
- Retry logic with exponential backoff
- Metrics collection
- Health checks
- Graceful degradation
- Cross-system event tracking

Run tests:
```bash
pytest tests/unit/test_integrations/test_event_hooks.py -v
```

Test Results:
- **48 tests passed**
- **0 tests failed**
- **Test coverage**: Comprehensive coverage of all functionality

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

### Cross-System Tracking

```python
# Create hooks for multiple systems
mahavishnu_hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")
crackerjack_hook = EventHookFactory.create_crackerjack_hook("http://localhost:8002")

# Use same correlation ID across systems
correlation_id = "cross_system_123"

await mahavishnu_hook.emit_workflow_started(..., correlation_id=correlation_id)
await crackerjack_hook.emit_quality_check_started(..., correlation_id=correlation_id)
```

### Automatic Event Tracking

```python
from mahavishnu.integrations import track_event

@track_event("workflow_completed", "info", include_result=True, hook=hook)
async def execute_workflow(workflow_id: str):
    result = await process_workflow(workflow_id)
    return result

# Events emitted automatically
result = await execute_workflow("wf_123")
```

### Batch Emission

```python
# Enable batch emission
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

## Metrics and Monitoring

Each hook provides comprehensive metrics:

```python
metrics = await hook.health_check()
# {
#     "status": "healthy",
#     "system": "mahavishnu",
#     "events_emitted": 150,
#     "events_failed": 2,
#     "retry_count": 2,
#     "last_error": null,
#     "last_success_time": "2025-02-05T10:30:00Z",
#     "circuit_breaker_state": "closed",
#     "circuit_breaker_metrics": {
#         "state": "closed",
#         "failure_count": 0,
#         "success_count": 0,
#         "failure_threshold": 5,
#         "recovery_timeout": 60.0
#     }
# }
```

Get metrics from multiple hooks:

```python
from mahavishnu.integrations import get_all_hook_metrics

hooks = [
    EventHookFactory.create_mahavishnu_hook("http://localhost:8002"),
    EventHookFactory.create_crackerjack_hook("http://localhost:8002"),
]

all_metrics = await get_all_hook_metrics(hooks)
# {
#     "mahavishnu": {"status": "healthy", "events_emitted": 150, ...},
#     "crackerjack": {"status": "healthy", "events_emitted": 200, ...}
# }
```

## Files Created/Modified

### Created Files

1. `/Users/les/Projects/mahavishnu/mahavishnu/integrations/event_hooks.py`
   - Main implementation (1,200+ lines)
   - All 5 system hooks
   - Base event hook
   - Event hook factory
   - Decorator
   - Utility functions

2. `/Users/les/Projects/mahavishnu/tests/unit/test_integrations/test_event_hooks.py`
   - Comprehensive test suite (48 tests)
   - Tests for all hooks
   - Integration tests
   - Mocked HTTP calls

3. `/Users/les/Projects/mahavishnu/docs/EVENT_HOOKS_GUIDE.md`
   - Complete usage guide
   - API reference
   - Best practices
   - Troubleshooting

4. `/Users/les/Projects/mahavishnu/examples/event_hooks_demo.py`
   - Demonstration script
   - Shows all features
   - Cross-system tracking example

### Modified Files

1. `/Users/les/Projects/mahavishnu/mahavishnu/integrations/__init__.py`
   - Added exports for event hooks
   - Maintains backward compatibility

## Integration Checklist

To integrate event hooks into your application:

1. **Install dependencies** (already present):
   - `httpx` (for HTTP requests)
   - Existing observability and resilience modules

2. **Create event hooks**:
   ```python
   from mahavishnu.integrations import EventHookFactory

   hook = EventHookFactory.create_mahavishnu_hook("http://localhost:8002")
   ```

3. **Emit events**:
   ```python
   await hook.emit_workflow_started(...)
   ```

4. **Initialize and shutdown** (if using batch mode):
   ```python
   await hook.initialize()
   # ... use hook ...
   await hook.shutdown()
   ```

5. **Monitor health**:
   ```python
   metrics = await hook.health_check()
   ```

## Next Steps

1. **Start the event collector** at `http://localhost:8002`
2. **Run the demo**: `python examples/event_hooks_demo.py`
3. **Run tests**: `pytest tests/unit/test_integrations/test_event_hooks.py -v`
4. **Read the guide**: See `docs/EVENT_HOOKS_GUIDE.md` for complete documentation
5. **Integrate into your application** using the examples provided

## Summary

The event hooks system provides:

- **23 event types** across 5 ecosystem systems
- **Resilient delivery** with retry logic and circuit breakers
- **Performance optimization** with batch emission
- **Automatic tracking** with decorators
- **Cross-system correlation** with correlation IDs
- **Comprehensive testing** with 48 passing tests
- **Complete documentation** with guide and demo
- **Production-ready** with graceful degradation

All hooks are ready to use and fully integrated with the existing Mahavishnu ecosystem.
