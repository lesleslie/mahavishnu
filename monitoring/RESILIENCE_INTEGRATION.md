# Circuit Breakers & Retries - Integration Guide

Production-ready resilience patterns for the MCP ecosystem.

## Quick Start

### 1. Install Dependencies

```bash
# No additional dependencies required!
# Resilience patterns use only Python standard library.
```

### 2. Basic Usage

```python
from monitoring.resilience import circuit_breaker, retry

@circuit_breaker(failure_threshold=5, recovery_timeout=60)
@retry(max_attempts=3, backoff="exponential")
async def call_external_api(url: str):
    async with httpx.AsyncClient() as client:
        return await client.get(url)
```

### 3. Run Tests

```bash
# Run resilience tests
pytest monitoring/tests/test_resilience.py -v

# Run with coverage
pytest monitoring/tests/test_resilience.py --cov=monitoring.resilience --cov-report=html
```

## Integration by MCP Server

### Mahavishnu

Add to `mahavishnu/core/adapters/base.py`:

```python
from monitoring.resilience import resilient

class OrchestratorAdapter:
    @resilient(
        failure_threshold=5,
        recovery_timeout=120,
        max_attempts=2,
        backoff="linear",
    )
    async def execute_workflow(self, workflow_config: dict) -> WorkflowResult:
        # Existing workflow execution logic
        pass
```

### Session-Buddy

Add to session storage operations in `session_buddy/storage.py`:

```python
from monitoring.resilience import retry

@retry(max_attempts=3, backoff="exponential")
async def save_session(self, session_id: str, data: dict):
    # Database save operation
    pass
```

### Akosha

Add to `akosha/aggregation.py` for memory sync:

```python
from monitoring.resilience import circuit_breaker

@circuit_breaker(failure_threshold=3, recovery_timeout=60)
async def sync_from_session_buddy(self, instance_url: str):
    # Sync operation
    pass
```

### Excalidraw-MCP

Add to `excalidraw_mcp/export.py`:

```python
from monitoring.resilience import resilient

@resilient(failure_threshold=3, max_attempts=2)
async def export_to_png(self, elements: list) -> bytes:
    # Export operation using Playwright
    pass
```

### Mailgun-MCP

Add to `mailgun_mcp/tools/messages.py`:

```python
from monitoring.resilience import retry

@retry(max_attempts=3, backoff="exponential")
async def send_email(self, to: str, subject: str, body: str):
    # Mailgun API call
    pass
```

### UniFi-MCP

Add to `unifi_mcp/controllers.py`:

```python
from monitoring.resilience import circuit_breaker

@circuit_breaker(failure_threshold=5, recovery_timeout=30)
async def list_devices(self):
    # UniFi API call
    pass
```

### RaindropIO-MCP

Add to `raindropio_mcp/client.py`:

```python
from monitoring.resilience import resilient

@resilient(failure_threshold=3, max_attempts=3)
async def get_bookmarks(self, collection_id: int):
    # RaindropIO API call
    pass
```

## Configuration Patterns

### API Calls (High Latency Tolerance)

```python
@resilient(
    failure_threshold=5,    # Open circuit after 5 failures
    recovery_timeout=60,    # Wait 60s before recovery
    max_attempts=3,         # Retry up to 3 times
    backoff="exponential",  # Exponential backoff: 1s, 2s, 4s
)
async def call_llm_api(prompt: str):
    # LLM API calls can have variable latency
    pass
```

### Database Operations (Low Latency Tolerance)

```python
@retry(
    max_attempts=2,         # Fewer retries for fast operations
    backoff="linear",       # Predictable backoff
)
async def execute_query(query: str):
    # Database queries should be fast
    pass
```

### MCP Server Communication (Fail Fast)

```python
@circuit_breaker(
    failure_threshold=3,    # Open circuit quickly
    recovery_timeout=30,    # Short recovery time
)
async def call_mcp_server(url: str, tool: str):
    # MCP server calls should fail fast if server is down
    pass
```

### External Services (Conservative)

```python
@resilient(
    failure_threshold=10,   # More failures before opening
    recovery_timeout=300,   # 5 minutes before recovery
    max_attempts=5,         # More retries
    backoff="exponential",
)
async def call_payment_gateway(amount: float):
    # Payment gateways need more resilience
    pass
```

## Monitoring Integration

### Metrics to Track

```python
from monitoring.metrics import (
    circuit_breaker_state,
    circuit_breaker_failures,
    retry_attempts,
    retry_success,
)

# Update circuit breaker metrics
async def update_circuit_breaker_metrics(breaker: CircuitBreaker, name: str):
    circuit_breaker_state.labels(
        breaker_name=name,
        state=breaker.state.value,
    ).set(1)

    circuit_breaker_failures.labels(
        breaker_name=name,
    ).set(breaker.failure_count)

# Update retry metrics
async def on_retry_callback(attempt: int, exception: Exception):
    retry_attempts.labels(
        exception_type=type(exception).__name__,
    ).inc()

async def on_retry_success():
    retry_success.labels().inc()
```

### Logging Best Practices

```python
import logging

logger = logging.getLogger(__name__)

@circuit_breaker(failure_threshold=5, recovery_timeout=60)
async def protected_function():
    try:
        # Your code here
        pass
    except CircuitBreakerError as e:
        logger.warning(f"Circuit breaker is OPEN: {e}")
        raise
    except MaxRetriesExceededError as e:
        logger.error(f"Max retries exceeded: {e}")
        raise
```

## Testing

### Unit Testing with Mocked Dependencies

```python
import pytest
from monitoring.resilience import CircuitBreaker, CircuitBreakerError

@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    breaker = CircuitBreaker(failure_threshold=3)

    async def failing_function():
        raise ConnectionError("Failed")

    # Trigger 3 failures
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await breaker.call(failing_function)

    # Circuit should be open
    assert breaker.state == CircuitState.OPEN

    # Next call should fail fast
    with pytest.raises(CircuitBreakerError):
        await breaker.call(failing_function)
```

### Integration Testing with Real Services

```python
@pytest.mark.integration
async def test_external_api_with_resilience():
    from monitoring.resilience import resilient

    @resilient(failure_threshold=3, max_attempts=2)
    async def call_api():
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.example.com/health")
            response.raise_for_status()
            return response.json()

    result = await call_api()
    assert result["status"] == "healthy"
```

## Troubleshooting

### Circuit Breaker Won't Close

**Problem**: Circuit breaker stays OPEN even after service recovers.

**Solution**:

- Check `recovery_timeout` - make sure enough time has passed
- Verify service is actually healthy
- Manually reset: `breaker.reset()`

### Too Many Retries

**Problem**: System overwhelmed by retry attempts.

**Solution**:

- Reduce `max_attempts`
- Increase backoff delay
- Use circuit breaker to fail fast

### Retries Not Happening

**Problem**: Functions fail immediately without retry.

**Solution**:

- Verify exception type matches `expected_exception`
- Check that `max_attempts > 1`
- Ensure function is async (if using async decorators)

### Performance Impact

**Problem**: Resilience patterns adding too much latency.

**Solution**:

- Use `backoff="fixed"` with small delay for fast operations
- Reduce `max_attempts` for low-latency requirements
- Consider removing circuit breaker for internal services

## Best Practices

### DO ✓

1. **Use circuit breakers for external service calls** - Prevents cascading failures
1. **Use retry for transient failures** - Handles network blips
1. **Combine both for critical paths** - Maximum resilience
1. **Monitor circuit breaker state** - Track OPEN/CLOSED transitions
1. **Set appropriate timeouts** - Don't wait indefinitely
1. **Use exponential backoff** - Prevents thundering herd
1. **Log all failures** - Essential for debugging
1. **Test failure scenarios** - Verify resilience works

### DON'T ✗

1. **Don't use retry for non-idempotent operations** - Could cause duplicate actions
1. **Don't set failure_threshold too low** - Opens circuit too easily
1. **Don't set recovery_timeout too short** - Doesn't give service time to recover
1. **Don't use circuit breaker for fast local operations** - Adds unnecessary overhead
1. **Don't ignore CircuitBreakerError** - Handle it explicitly
1. **Don't retry on validation errors** - Those won't succeed on retry
1. **Don't forget to test resilience** - Must verify it works
1. **Don't set max_attempts too high** - Wastes resources on dead services

## Migration Guide

### Step 1: Identify Critical Paths

List all external API calls and database operations:

```bash
# Find HTTP client usage
grep -r "httpx.Client" mahavishnu/
grep -r "requests.post" session-buddy/

# Find database operations
grep -r "asyncpg.connect" akosha/
```

### Step 2: Add Resilience Incrementally

Start with most critical operations:

1. LLM API calls (highest latency)
1. Payment processing (highest risk)
1. User-facing operations (highest impact)

### Step 3: Monitor Metrics

Track before and after:

- Error rate
- Latency (p50, p95, p99)
- Circuit breaker openings
- Retry attempts

### Step 4: Tune Parameters

Adjust based on observed behavior:

- If too many circuit openings → increase `failure_threshold`
- If too slow → reduce `max_attempts` or `backoff` delay
- If not resilient enough → increase `recovery_timeout`

## Success Criteria

✅ All external API calls protected by circuit breaker
✅ All database operations have retry logic
✅ Monitoring shows reduced error rate
✅ Latency remains acceptable (\<1s p95)
✅ Circuit breakers prevent cascading failures
✅ System recovers automatically when services come back
✅ Tests verify resilience patterns work
✅ Documentation is up to date

## References

- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Retry Pattern](https://docs.microsoft.com/en-us/azure/architecture/patterns/retry)
- [Resilience Patterns](https://docs.microsoft.com/en-us/azure/architecture/patterns/category/resiliency)
- [Example Integration](RESILIENCE_EXAMPLES.md)
- [Test Suite](tests/test_resilience.py)

## Support

For issues or questions:

- Check test suite: `pytest monitoring/tests/test_resilience.py -v`
- Review examples: `monitoring/RESILIENCE_EXAMPLES.md`
- Monitoring guide: `monitoring/MONITORING_GUIDE.md`
