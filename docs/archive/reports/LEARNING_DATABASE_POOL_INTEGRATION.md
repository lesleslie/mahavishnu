# Learning Database and PoolManager Integration

## Overview

This document describes the integration between the LearningDatabase and PoolManager to capture execution telemetry from pool operations.

## Problem Statement

The LearningDatabase existed but had ZERO execution records because it wasn't connected to any data producers. The PoolManager was executing tasks but not capturing any telemetry for learning analytics.

## Solution

Modified `PoolManager` to accept an optional `LearningDatabase` parameter and automatically capture execution telemetry after every task execution.

## Changes Made

### 1. Modified `/Users/les/Projects/mahavishnu/mahavishnu/pools/manager.py`

#### Added LearningDatabase parameter to `__init__`:

```python
def __init__(
    self,
    terminal_manager,
    session_buddy_client: Any = None,
    message_bus: MessageBus | None = None,
    learning_db: Any = None,  # NEW: Optional LearningDatabase
):
    # ...
    self._learning_db = learning_db  # Can be None
```

#### Added `_create_execution_record()` method:

Creates `ExecutionRecord` from pool task execution results, mapping:
- Task metadata (type, description, repo, complexity)
- Routing decisions (model tier, pool type, routing confidence)
- Execution outcomes (success, duration, quality score)
- Cost tracking (estimate vs actual)
- Error context (type, message, inferred from error messages)
- Resource utilization (memory, CPU)
- Metadata (pool ID, worker ID, task metadata)

Key features:
- Prefers `error_message` field, falls back to `error` field
- Infers error type from message content:
  - "timeout" or "timed out" → `ErrorType.TIMEOUT`
  - "validation" → `ErrorType.VALIDATION`
  - Other → `ErrorType.UNKNOWN`
- Truncates long descriptions to 500 chars
- Estimates tokens from description length (~2 chars per token)

#### Added `_store_execution_telemetry()` method:

Stores execution record in learning database with error handling:
- Returns early if `learning_db` is `None` (graceful degradation)
- Wraps `store_execution()` in try/except
- Logs warnings but doesn't break pool operations on failure

#### Modified `execute_on_pool()` method:

Added telemetry capture:
```python
# Track timing for learning database
start_time = datetime.now(UTC)

try:
    result = await pool.execute_task(task)
    end_time = datetime.now(UTC)

    # Store execution telemetry
    await self._store_execution_telemetry(
        pool_id=pool_id,
        task=task,
        result=result,
        start_time=start_time,
        end_time=end_time,
    )

    # ... rest of success path

except Exception as e:
    # Task failed - still capture telemetry
    end_time = datetime.now(UTC)

    error_result = {
        "status": "failed",
        "error": str(e),
        "error_message": str(e),
        "success": False,
    }

    await self._store_execution_telemetry(
        pool_id=pool_id,
        task=task,
        result=error_result,
        start_time=start_time,
        end_time=end_time,
    )

    # Re-raise exception
    raise
```

### 2. Created comprehensive tests in `/Users/les/Projects/mahavishnu/tests/unit/test_pools/test_manager_learning_integration.py`

#### Test Coverage (19 tests):

**TestPoolManagerLearningIntegration:**
- `test_init_with_learning_database` - Verifies learning_db parameter is stored
- `test_init_without_learning_database` - Verifies graceful degradation
- `test_execute_on_pool_stores_execution_record` - Verifies record creation and storage
- `test_execute_on_pool_without_learning_db` - Verifies operations work without learning_db
- `test_route_task_stores_execution_record` - Verifies routing also captures telemetry
- `test_execution_record_fields_mapped_correctly` - Verifies field mapping
- `test_failed_execution_stores_error_record` - Verifies error capture
- `test_timeout_error_mapped_correctly` - Verifies timeout error type inference
- `test_learning_database_failure_doesnt_break_pool` - Verifies error handling
- `test_multiple_executions_all_stored` - Verifies all executions are captured
- `test_execution_record_includes_metadata` - Verifies metadata preservation
- `test_execution_record_duration_calculation` - Verifies duration tracking
- `test_graceful_degradation_with_none_learning_db` - Verifies None handling

**TestExecutionRecordCreation:**
- `test_create_execution_record_with_minimal_data` - Verifies default values
- `test_create_execution_record_with_full_data` - Verifies complete data
- `test_create_execution_record_with_error` - Verifies error handling
- `test_create_execution_record_infers_timeout_error` - Verifies timeout inference
- `test_create_execution_record_truncates_long_descriptions` - Verifies truncation
- `test_create_execution_record_estimates_tokens` - Verifies token estimation

## Usage Example

```python
from mahavishnu.learning.database import LearningDatabase
from mahavishnu.pools.manager import PoolManager

# Initialize learning database
learning_db = LearningDatabase(database_path="data/learning.db")
await learning_db.initialize()

# Create pool manager with learning database
pool_mgr = PoolManager(
    terminal_manager=tm,
    learning_db=learning_db,  # Optional - can be None
)

# Spawn pools
config = PoolConfig(name="local", pool_type="mahavishnu", min_workers=2)
pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

# Execute task - automatically captured in learning database
result = await pool_mgr.execute_on_pool(
    pool_id,
    {
        "prompt": "Write a function",
        "task_type": "code_generation",
        "repo": "my_project",
        "complexity_score": 75,
    }
)

# Execution record is now in learning database with:
# - Task metadata (type, description, repo)
# - Routing decisions (pool type, model tier)
# - Execution outcomes (success, duration, quality)
# - Cost tracking (estimate vs actual)
# - Error context (if failed)
# - Resource utilization
```

## Field Mapping

| Pool Result Field | ExecutionRecord Field | Notes |
|-------------------|----------------------|-------|
| `task.task_id` | `task_id` | Falls back to `uuid4()` |
| `task.task_type` | `task_type` | Falls back to `"unknown"` |
| `task.prompt` or `task.description` | `task_description` | Truncated to 500 chars |
| `task.repo` or `task.repo_path` | `repo` | Falls back to `"unknown"` |
| `result.files_changed` | `file_count` | Falls back to `task.file_count` or `0` |
| Calculated | `estimated_tokens` | ~2 tokens per character |
| `result.model_tier` or `task.model_tier` | `model_tier` | Falls back to `"unknown"` |
| Pool config | `pool_type` | From pool configuration |
| `task.swarm_topology` | `swarm_topology` | Optional |
| `task.routing_confidence` | `routing_confidence` | Defaults to `1.0` |
| `task.complexity_score` or `result.complexity` | `complexity_score` | Defaults to `50` |
| `result.status == "completed"` or `result.success` | `success` | Boolean |
| Calculated | `duration_seconds` | `end_time - start_time` |
| `result.quality_score` | `quality_score` | Optional |
| `task.cost_estimate` or `result.cost` | `cost_estimate` | Defaults to `actual_cost` |
| `result.cost` | `actual_cost` | Defaults to `0.0` |
| Inferred | `error_type` | From error message |
| `result.error_message` or `result.error` | `error_message` | Truncated to 1000 chars |
| N/A | `user_accepted` | Always `None` (no feedback yet) |
| N/A | `user_rating` | Always `None` (no feedback yet) |
| `result.peak_memory_mb` | `peak_memory_mb` | Optional |
| `result.cpu_time_seconds` | `cpu_time_seconds` | Optional |
| `result.solution_summary` | `solution_summary` | Optional |
| Constructed | `metadata` | Pool ID, worker ID, task metadata |

## Error Type Inference

The integration automatically infers error types from error messages:

| Error Message Pattern | Error Type |
|---------------------|------------|
| Contains "timeout" or "timed out" | `ErrorType.TIMEOUT` |
| Contains "validation" | `ErrorType.VALIDATION` |
| Other errors | `ErrorType.UNKNOWN` |

This allows for better analytics and error tracking without requiring explicit error type classification from pool implementations.

## Graceful Degradation

The integration is designed to be non-breaking:

1. **Optional parameter**: `learning_db` can be `None`
2. **Early return**: `_store_execution_telemetry()` returns early if `learning_db` is `None`
3. **Error handling**: Database failures are logged but don't break pool operations
4. **Backward compatibility**: Existing code works without any changes

## Benefits

1. **Automatic telemetry capture**: All pool executions are automatically tracked
2. **Learning analytics**: Enables model router auto-tuning and pool selection optimization
3. **Error tracking**: Captures both successful and failed executions with error context
4. **Cost tracking**: Estimates vs actual costs for budget optimization
5. **Performance analysis**: Duration, quality scores, and resource utilization metrics
6. **Solution patterns**: Enables extraction of successful execution patterns

## Testing

All tests passing:
- 19 new integration tests
- 37 existing pool manager tests (unchanged)
- Total: 56 tests passing

Run tests with:
```bash
# New integration tests
pytest tests/unit/test_pools/test_manager_learning_integration.py -v

# All pool manager tests
pytest tests/unit/test_pools/test_manager.py -v
```

## Future Enhancements

1. **User feedback**: Add `user_accepted` and `user_rating` fields when feedback mechanism is implemented
2. **Batch execution**: Capture telemetry for batch operations
3. **Pool-specific metrics**: Add pool-specific performance metrics
4. **Real-time monitoring**: Stream telemetry to monitoring systems
5. **Analytics dashboards**: Build dashboards for visualizing pool performance
