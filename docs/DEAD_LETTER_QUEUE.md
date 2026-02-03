# Dead Letter Queue (DLQ) Documentation

## Overview

The Dead Letter Queue (DLQ) is a production-grade system for handling failed workflow executions in Mahavishnu. It ensures that **no failed workflow is ever lost** by capturing failures and providing intelligent reprocessing with configurable retry policies.

## Key Features

- **Intelligent Retry Policies**: Never, Linear, Exponential, or Immediate retry strategies
- **Automatic Reprocessing**: Background processor automatically retries failed workflows
- **Persistent Storage**: OpenSearch integration with in-memory fallback
- **Error Classification**: Automatic categorization (transient, permanent, network, resource, etc.)
- **Manual Intervention**: Inspect, retry manually, or archive tasks
- **Full Observability**: Metrics, logging, and statistics
- **Circuit Breaker Integration**: Respects circuit breaker state for retries

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Workflow Execution                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Execution Fail │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Error Classifier │◄── Error Categorization
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ DLQ Integration │◄── Integration Strategy
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Dead Letter Queue│
                    │                 │
                    │ • Task Storage  │
                    │ • Retry Logic   │
                    │ • Persistence   │
                    └─────────────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
    ┌──────────────────────┐    ┌──────────────────────┐
    │  Background Processor│    │   Manual Operations   │
    │                      │    │                      │
    │ • Auto-retry         │    │ • Inspect tasks      │
    │ • Exponential backoff│    │ • Manual retry       │
    │ • Success tracking   │    │ • Archive tasks      │
    └──────────────────────┘    └──────────────────────┘
                │                           │
                └─────────────┬─────────────┘
                              ▼
                    ┌─────────────────┐
                    │  Success /      │
                    │  Exhausted      │
                    └─────────────────┘
```

## Retry Policies

### Never (`RetryPolicy.NEVER`)
- **Use Case**: Permanent errors (permissions, validation, configuration)
- **Behavior**: Task is enqueued but never automatically retried
- **Action**: Manual intervention required

### Linear (`RetryPolicy.LINEAR`)
- **Use Case**: Resource constraints, rate limits
- **Behavior**: Retry with linear backoff (5min, 10min, 15min, ...)
- **Formula**: `delay = 5 * (retry_count + 1)` minutes

### Exponential (`RetryPolicy.EXPONENTIAL`) ⭐ **Default**
- **Use Case**: Transient errors, network issues, temporary failures
- **Behavior**: Exponential backoff with 60-minute cap (1min, 2min, 4min, 8min, ...)
- **Formula**: `delay = min(2^retry_count, 60)` minutes

### Immediate (`RetryPolicy.IMMEDIATE`)
- **Use Case**: Quick retries for flaky operations
- **Behavior**: Retry on next processor cycle
- **Delay**: 0 seconds (respecting processor interval)

## Error Classification

The DLQ automatically classifies errors to determine retry strategy:

| Category | Description | Default Policy |
|----------|-------------|----------------|
| **TRANSIENT** | Rate limits, temporary errors, service busy | EXPONENTIAL |
| **NETWORK** | Connection issues, timeouts, SSL errors | EXPONENTIAL |
| **RESOURCE** | Memory, disk, quota exhaustion | LINEAR |
| **PERMISSION** | Access denied, unauthorized | NEVER |
| **VALIDATION** | Invalid input, malformed data | NEVER |
| **PERMANENT** | Unknown/uncategorized errors | NEVER |

## Configuration

### Enable DLQ

Add to `settings/mahavishnu.yaml`:

```yaml
# Dead Letter Queue configuration
dlq_enabled: true
dlq_max_size: 10000
dlq_default_retry_policy: exponential  # Options: never, linear, exponential, immediate
dlq_default_max_retries: 3
dlq_retry_processor_enabled: true
dlq_retry_interval_seconds: 60  # Check for retries every minute
```

### Environment Variables

```bash
export MAHAVISHNU_DLQ_ENABLED=true
export MAHAVISHNU_DLQ_MAX_SIZE=10000
export MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY=exponential
export MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES=3
export MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED=true
export MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS=60
```

## Usage Examples

### 1. Automatic DLQ Integration

```python
from mahavishnu.core import MahavishnuApp

# Initialize app (DLQ is automatically integrated)
app = MahavishnuApp()

# Start DLQ retry processor
async def retry_callback(task, repos):
    """Callback for retrying failed workflows."""
    return await app.execute_workflow(task, "llamaindex", repos)

await app.start_dlq_processor()

# Execute workflow (automatically enqueues on failure)
result = await app.execute_workflow_parallel(
    task={"type": "code_sweep"},
    adapter_name="llamaindex",
    repos=["/path/to/repo"]
)

# If workflow fails, it's automatically enqueued in DLQ
if result["status"] == "failed" and result.get("dlq_enqueued"):
    print(f"Workflow enqueued: {result['dlq_task_id']}")
```

### 2. Manual DLQ Operations

```python
# Manually enqueue a failed task
from mahavishnu.core.dead_letter_queue import RetryPolicy

await app.dlq.enqueue(
    task_id="wf_abc123",
    task={"type": "code_sweep"},
    repos=["/path/to/repo"],
    error="Connection timeout",
    retry_policy=RetryPolicy.EXPONENTIAL,
    max_retries=5,
    metadata={"priority": "high"}
)

# List all pending tasks
pending_tasks = await app.dlq.list_tasks(
    status=DeadLetterStatus.PENDING,
    limit=100
)

# Get a specific task
task = await app.dlq.get_task("wf_abc123")
if task:
    print(f"Task failed at: {task.failed_at}")
    print(f"Retry count: {task.retry_count}/{task.max_retries}")
    print(f"Next retry at: {task.next_retry_at}")

# Manually retry a task
result = await app.dlq.retry_task("wf_abc123")
if result["success"]:
    print("Task succeeded on retry")
else:
    print(f"Retry failed: {result['error']}")

# Archive a task (remove from active queue)
await app.dlq.archive_task("wf_abc123")
```

### 3. DLQ Statistics

```python
# Get queue statistics
stats = await app.dlq.get_statistics()

print(f"Queue size: {stats['queue_size']}/{stats['max_size']}")
print(f"Utilization: {stats['utilization_percent']}%")
print(f"Status breakdown: {stats['status_breakdown']}")
print(f"Error categories: {stats['error_categories']}")
print(f"Retry policies: {stats['retry_policies']}")
print(f"Lifetime stats: {stats['lifetime_stats']}")

# Example output:
# Queue size: 15/10000
# Utilization: 0.15%
# Status breakdown: {'pending': 12, 'retrying': 2, 'exhausted': 1}
# Error categories: {'transient': 8, 'network': 4, 'permanent': 3}
# Retry policies: {'exponential': 12, 'linear': 2, 'never': 1}
# Lifetime stats: {
#   'enqueued_total': 50,
#   'retry_success': 30,
#   'retry_failed': 15,
#   'exhausted': 3,
#   'manually_retried': 2,
#   'archived': 0
# }
```

### 4. Integration Strategies

```python
from mahavishnu.core.dlq_integration import DLQIntegrationStrategy

# Set integration strategy
app.dlq_integration.set_strategy(DLQIntegrationStrategy.AUTOMATIC)

# Available strategies:
# AUTOMATIC - Enqueue all failed workflows (default)
# SELECTIVE - Enqueue based on error classification
# MANUAL - Only enqueue when explicitly requested
# DISABLED - Never use DLQ

# Selective strategy example
app.dlq_integration.set_strategy(DLQIntegrationStrategy.SELECTIVE)

# With selective strategy:
# - Transient errors → Enqueued with EXPONENTIAL policy
# - Network errors → Enqueued with EXPONENTIAL policy
# - Resource errors → Enqueued with LINEAR policy
# - Permission errors → NOT enqueued (NEVER policy)
# - Validation errors → NOT enqueued (NEVER policy)
# - Permanent errors → NOT enqueued (NEVER policy)
```

### 5. Custom Retry Logic

```python
from mahavishnu.core.dead_letter_queue import RetryPolicy
from mahavishnu.core.resilience import ErrorCategory

async def custom_enqueue_handler(task_id, task, repos, error):
    """Custom error handling with DLQ."""
    # Classify error
    error_category = await app.error_recovery_manager.classify_error(error)

    # Determine retry policy based on error
    if error_category == ErrorCategory.TRANSIENT:
        retry_policy = RetryPolicy.EXPONENTIAL
        max_retries = 5
    elif error_category == ErrorCategory.NETWORK:
        retry_policy = RetryPolicy.EXPONENTIAL
        max_retries = 3
    elif error_category == ErrorCategory.RESOURCE:
        retry_policy = RetryPolicy.LINEAR
        max_retries = 2
    else:
        # Don't retry permanent errors
        return None

    # Enqueue in DLQ
    failed_task = await app.dlq.enqueue(
        task_id=task_id,
        task=task,
        repos=repos,
        error=str(error),
        retry_policy=retry_policy,
        max_retries=max_retries,
        error_category=error_category.value,
        metadata={"handler": "custom"}
    )

    return failed_task
```

## Integration with MahavishnuApp

### Initialize DLQ in MahavishnuApp

Add to `mahavishnu/core/app.py` in `MahavishnuApp.__init__()`:

```python
# Initialize Dead Letter Queue
if self.config.dlq_enabled:
    from .dead_letter_queue import DeadLetterQueue
    from .dlq_integration import create_dlq_integration

    self.dlq = DeadLetterQueue(
        max_size=self.config.dlq_max_size,
        opensearch_client=self.opensearch_integration.client if self.opensearch_integration else None,
        observability_manager=self.observability,
    )

    self.dlq_integration = create_dlq_integration(self)
else:
    self.dlq = None
    self.dlq_integration = None
```

### Add DLQ Configuration

Add to `mahavishnu/core/config.py` in `MahavishnuSettings` class:

```python
# Dead Letter Queue configuration
dlq_enabled: bool = Field(
    default=True,
    description="Enable Dead Letter Queue for failed workflow reprocessing",
)
dlq_max_size: int = Field(
    default=10000,
    ge=100,
    le=100000,
    description="Maximum number of tasks in DLQ (100-100000)",
)
dlq_default_retry_policy: str = Field(
    default="exponential",
    description="Default retry policy (never, linear, exponential, immediate)",
)
dlq_default_max_retries: int = Field(
    default=3,
    ge=0,
    le=10,
    description="Default maximum retry attempts (0-10)",
)
dlq_retry_processor_enabled: bool = Field(
    default=True,
    description="Enable automatic DLQ retry processor",
)
dlq_retry_interval_seconds: int = Field(
    default=60,
    ge=10,
    le=3600,
    description="DLQ retry processor check interval in seconds (10-3600)",
)

@field_validator("dlq_default_retry_policy")
@classmethod
def validate_dlq_retry_policy(cls, v: str) -> str:
    '''Validate DLQ retry policy value.'''
    valid_policies = ["never", "linear", "exponential", "immediate"]
    if v not in valid_policies:
        raise ValueError(
            f"dlq_default_retry_policy must be one of {valid_policies}, got '{v}'"
        )
    return v
```

### Start DLQ Processor

Add async method to `MahavishnuApp`:

```python
async def start_dlq_processor(self) -> None:
    """Start the DLQ retry processor if configured."""
    if not self.config.dlq_enabled or not self.dlq:
        return

    if not self.config.dlq_retry_processor_enabled:
        self.logger.info("DLQ retry processor disabled in configuration")
        return

    # Define retry callback
    async def dlq_retry_callback(task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Callback for DLQ retry attempts."""
        adapter_name = task.get("adapter", "llamaindex")
        return await self.execute_workflow_parallel(
            task=task,
            adapter_name=adapter_name,
            repos=repos,
        )

    # Start processor
    await self.dlq.start_retry_processor(
        callback=dlq_retry_callback,
        check_interval_seconds=self.config.dlq_retry_interval_seconds,
    )

    self.logger.info(
        f"DLQ retry processor started "
        f"(interval={self.config.dlq_retry_interval_seconds}s)"
    )

async def stop_dlq_processor(self) -> None:
    """Stop the DLQ retry processor."""
    if self.dlq:
        await self.dlq.stop_retry_processor()
        self.logger.info("DLQ retry processor stopped")
```

## OpenSearch Integration

The DLQ persists tasks to OpenSearch for durability and searchability:

### Index Schema

```
Index: mahavishnu_dlq

Fields:
- task_id: keyword (primary key)
- task: object
- repos: keyword[]
- error: text
- failed_at: date
- retry_count: integer
- max_retries: integer
- retry_policy: keyword
- next_retry_at: date
- status: keyword
- metadata: object
- error_category: keyword
- last_error: text
- total_attempts: integer
- updated_at: date
```

### Example Queries

```python
# Find all exhausted tasks
query = {
    "query": {
        "term": {"status.keyword": "exhausted"}
    }
}

# Find tasks by error category
query = {
    "query": {
        "term": {"error_category.keyword": "transient"}
    }
}

# Find tasks ready for retry in next hour
query = {
    "query": {
        "range": {
            "next_retry_at": {
                "lte": "now+1h"
            }
        }
    }
}
```

## Testing

### Run DLQ Tests

```bash
# Run all DLQ tests
pytest tests/unit/test_dead_letter_queue.py -v

# Run specific test
pytest tests/unit/test_dead_letter_queue.py::TestDeadLetterQueue::test_enqueue_task -v

# Run with coverage
pytest tests/unit/test_dead_letter_queue.py --cov=mahavishnu.core.dead_letter_queue --cov-report=html
```

### Test Coverage

The test suite covers:
- ✅ Task enqueue and retrieval
- ✅ Retry policy calculations (never, linear, exponential, immediate)
- ✅ Automatic retry processing
- ✅ Manual retry operations
- ✅ Task archiving
- ✅ Queue statistics
- ✅ Queue full handling
- ✅ Exhausted retry handling
- ✅ OpenSearch persistence
- ✅ Integration with workflow execution

## Troubleshooting

### DLQ is Full

```python
# Check queue size
stats = await app.dlq.get_statistics()
print(f"Queue utilization: {stats['utilization_percent']}%")

# Archive exhausted tasks
exhausted_tasks = await app.dlq.list_tasks(status=DeadLetterStatus.EXHAUSTED)
for task in exhausted_tasks:
    await app.dlq.archive_task(task.task_id)

# Or clear all tasks (WARNING: destructive)
count = await app.dlq.clear_all()
print(f"Cleared {count} tasks")
```

### Retries Not Working

```python
# Check if processor is running
stats = await app.dlq.get_statistics()
if not stats["is_processor_running"]:
    print("Retry processor is not running!")
    await app.start_dlq_processor()

# Check retry interval
print(f"Retry interval: {stats['retry_interval_seconds']}s")

# Manually trigger retry for a specific task
result = await app.dlq.retry_task("wf_abc123")
```

### High Exhausted Task Count

```python
# Analyze exhausted tasks
exhausted_tasks = await app.dlq.list_tasks(status=DeadLetterStatus.EXHAUSTED)

# Group by error category
from collections import Counter
error_categories = Counter(task.error_category for task in exhausted_tasks if task.error_category)
print("Error categories:", error_categories)

# Common causes:
# - Max retries too low → Increase dlq_default_max_retries
# - Permanent errors being retried → Adjust integration strategy to SELECTIVE
# - Transient errors need more retries → Increase specific task max_retries
```

## Best Practices

### 1. Choose the Right Integration Strategy

- **AUTOMATIC**: Use for critical workflows where all failures should be retried
- **SELECTIVE**: Use for mixed workloads to avoid retrying permanent errors
- **MANUAL**: Use when you want full control over what gets retried
- **DISABLED**: Use for testing or when you have your own retry logic

### 2. Set Appropriate Retry Limits

```python
# Transient errors (rate limits, temporary failures)
await dlq.enqueue(..., retry_policy=RetryPolicy.EXPONENTIAL, max_retries=5)

# Network errors (connection issues)
await dlq.enqueue(..., retry_policy=RetryPolicy.EXPONENTIAL, max_retries=3)

# Resource errors (memory, disk)
await dlq.enqueue(..., retry_policy=RetryPolicy.LINEAR, max_retries=2)

# Permanent errors (permissions, validation)
await dlq.enqueue(..., retry_policy=RetryPolicy.NEVER, max_retries=0)
```

### 3. Monitor Queue Health

```python
# Set up monitoring
async def monitor_dlq():
    while True:
        stats = await app.dlq.get_statistics()

        # Alert if queue is getting full
        if stats["utilization_percent"] > 80:
            print(f"WARNING: DLQ is {stats['utilization_percent']}% full!")

        # Alert if many exhausted tasks
        exhausted_count = stats["status_breakdown"]["exhausted"]
        if exhausted_count > 100:
            print(f"WARNING: {exhausted_count} exhausted tasks in DLQ!")

        # Alert if retry success rate is low
        total_retries = stats["lifetime_stats"]["retry_success"] + stats["lifetime_stats"]["retry_failed"]
        if total_retries > 0:
            success_rate = stats["lifetime_stats"]["retry_success"] / total_retries
            if success_rate < 0.5:
                print(f"WARNING: Low retry success rate: {success_rate:.1%}")

        await asyncio.sleep(300)  # Check every 5 minutes
```

### 4. Use Metadata for Context

```python
await dlq.enqueue(
    task_id="wf_abc123",
    task=task,
    repos=repos,
    error=error,
    metadata={
        "workflow_type": "code_sweep",
        "priority": "high",
        "business_unit": "payments",
        "slos": {"max_delay_minutes": 15},
        "on_call_team": "platform-team",
    }
)
```

### 5. Archive Old Tasks Regularly

```python
async def archive_old_tasks():
    """Archive tasks that have been exhausted for > 7 days."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    exhausted_tasks = await dlq.list_tasks(status=DeadLetterStatus.EXHAUSTED)

    for task in exhausted_tasks:
        if task.failed_at < cutoff:
            await dlq.archive_task(task.task_id)
```

## Performance Considerations

### Queue Size

- **Default**: 10,000 tasks
- **Memory**: ~1KB per task in-memory
- **OpenSearch**: Additional storage for persistence
- **Recommendation**: Monitor utilization and archive exhausted tasks

### Retry Processor

- **Default Interval**: 60 seconds
- **Per-Cycle Processing**: All ready tasks processed in parallel
- **Optimization**: Lower interval for faster retries, higher for less CPU

### Persistence

- **OpenSearch**: Enables durability and searchability
- **In-Memory**: Faster, but lost on restart
- **Recommendation**: Use OpenSearch in production

## Security Considerations

### Task Data

- Tasks may contain sensitive information
- OpenSearch should be secured with authentication
- Consider encryption for sensitive metadata

### Access Control

```python
# Implement RBAC for DLQ operations
async def check_dlq_access(user_id: str, operation: str) -> bool:
    if operation == "retry":
        return await rbac_manager.check_permission(user_id, "dlq", "retry")
    elif operation == "archive":
        return await rbac_manager.check_permission(user_id, "dlq", "archive")
    # etc.
```

## Future Enhancements

- [ ] Priority queues (high/medium/low priority tasks)
- [ ] Dead letter queue web UI for visualization
- [ ] Automatic alerting on exhausted tasks
- [ ] Task dependencies (retry B after A succeeds)
- [ ] Custom backoff functions
- [ ] DLQ task templates for common failure patterns
- [ ] Integration with incident management systems

## References

- [Dead Letter Queue Pattern](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)
- [Exponential Backoff](https://cloud.google.com/architecture/rate-limiting-strategies-techniques)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
