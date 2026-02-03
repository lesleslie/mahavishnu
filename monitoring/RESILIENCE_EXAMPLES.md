"""Integration examples for circuit breaker and retry patterns.

This file shows how to use resilience patterns across the MCP ecosystem.
"""

import asyncio
from typing import Any

import httpx

# Import resilience patterns

from monitoring.resilience import (
circuit_breaker,
retry,
resilient,
with_fallback,
CircuitBreaker,
CircuitBreakerError,
CircuitState,
MaxRetriesExceededError,
Retry,
BackoffStrategy,
)

# ============================================================================

# Example 1: HTTP API Calls with Full Resilience

# ============================================================================

@resilient(
failure_threshold=5,
recovery_timeout=60,
max_attempts=3,
backoff="exponential",
expected_exception=(ConnectionError, TimeoutError, httpx.HTTPError),
)
async def call_external_api(url: str, method: str = "GET", \*\*kwargs) -> dict\[str, Any\]:
"""Make HTTP API call with full resilience protection.

```
This call is protected by:
- Circuit breaker: Opens after 5 failures
- Retry: Up to 3 attempts with exponential backoff
- Timeout protection: Automatic fail-fast on timeout

Args:
    url: API endpoint URL
    method: HTTP method
    **kwargs: Additional arguments for httpx

Returns:
    JSON response as dictionary

Raises:
    CircuitBreakerError: If circuit is open (service down)
    MaxRetriesExceededError: If all retry attempts fail
"""
async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()
```

# ============================================================================

# Example 2: Database Operations with Retry Only

# ============================================================================

@retry(
max_attempts=3,
backoff="exponential",
expected_exception=(ConnectionError, TimeoutError),
)
async def execute_database_query(query: str, params: dict[str, Any]) -> list\[dict[str, Any]\]:
"""Execute database query with retry on connection issues.

```
Database operations need retry but typically don't need circuit breakers
because database connections are usually pooled and managed.

Args:
    query: SQL query string
    params: Query parameters

Returns:
    Query results as list of dictionaries
"""
# Simulated database call
# In production: await db_pool.execute(query, params)
await asyncio.sleep(0.1)  # Simulate network delay
return [{"id": 1, "name": "test"}]
```

# ============================================================================

# Example 3: MCP Server Communication with Circuit Breaker

# ============================================================================

@circuit_breaker(
failure_threshold=3,
recovery_timeout=30,
expected_exception=(ConnectionError, TimeoutError, OSError),
)
async def call_mcp_server(server_url: str, tool_name: str, params: dict[str, Any]) -> Any:
"""Call another MCP server with circuit breaker protection.

```
Circuit breaker is crucial here because:
- We want to fail fast if the remote server is down
- We don't want to overwhelm a struggling server
- We want to automatically recover when server comes back

Args:
    server_url: MCP server URL
    tool_name: Tool to call
    params: Tool parameters

Returns:
    Tool execution result

Raises:
    CircuitBreakerError: If circuit is open (remote server down)
"""
async with httpx.AsyncClient() as client:
    response = await client.post(
        f"{server_url}/mcp",
        json={
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params,
            },
        },
    )
    response.raise_for_status()
    return response.json()
```

# ============================================================================

# Example 4: Cache Fallback Pattern

# ============================================================================

class CacheService:
"""Cache service with fallback to database."""

```
def __init__(self):
    self._cache = {}

async def get_from_cache(self, key: str) -> Any:
    """Get value from cache."""
    return self._cache.get(key)

async def set_cache(self, key: str, value: Any):
    """Set value in cache."""
    self._cache[key] = value
```

cache_service = CacheService()

async def fallback_to_database(key: str) -> Any:
"""Fallback function to load from database."""
print(f"Cache miss for {key}, loading from database")
\# Simulated database call
await asyncio.sleep(0.5)
return {"data": f"value_for\_{key}", "source": "database"}

@with_fallback(
fallback_func=fallback_to_database,
on_exception=(ConnectionError, KeyError), # Cache miss = KeyError
)
async def get_data_with_cache(key: str) -> Any:
"""Get data from cache with fallback to database.

```
Args:
    key: Cache key

Returns:
    Data from cache or database
"""
value = await cache_service.get_from_cache(key)
if value is None:
    raise KeyError(f"Cache key not found: {key}")
return value
```

# ============================================================================

# Example 5: LLM API Calls with Custom Retry Callback

# ============================================================================

async def log_retry_attempt(attempt: int, exception: Exception):
"""Callback called after each failed retry attempt."""
print(f"Retry attempt {attempt + 1} failed: {exception}")
\# Could also send metrics to monitoring system
\# await monitoring.increment_counter("llm_api_retries")

@retry(
max_attempts=5, # LLM APIs can have transient errors, more retries
backoff=BackoffStrategy.exponential(base_delay=2.0, max_delay=60.0),
expected_exception=(ConnectionError, TimeoutError, httpx.HTTPStatusError),
on_retry=log_retry_attempt,
)
async def call_llm_api(prompt: str, model: str = "claude-3-5-sonnet-20241022") -> str:
"""Call LLM API with retry and custom logging.

```
LLM API calls benefit from:
- More retry attempts (up to 5)
- Longer exponential backoff (2s base, 60s max)
- Custom retry callback for monitoring

Args:
    prompt: Prompt to send to LLM
    model: Model identifier

Returns:
    LLM response text
"""
# Simulated LLM API call
# In production: await anthropic.messages.create(model=model, messages=[...])
await asyncio.sleep(1.0)
return f"LLM response to: {prompt[:50]}..."
```

# ============================================================================

# Example 6: Workflow Execution with Timeout

# ============================================================================

from monitoring.resilience import resilient

@resilient(
failure_threshold=3,
recovery_timeout=120, # Longer timeout for workflow recovery
max_attempts=2, # Fewer retries for workflows (idempotency concerns)
backoff="linear",
expected_exception=(ConnectionError, TimeoutError, RuntimeError),
)
async def execute_workflow(workflow_id: str, params: dict[str, Any]) -> dict\[str, Any\]:
"""Execute workflow with resilience protection.

```
Workflow execution needs:
- Circuit breaker to prevent cascading workflow failures
- Fewer retries (workflows should be idempotent)
- Linear backoff (more predictable than exponential)
- Longer recovery timeout (workflows take time to recover)

Args:
    workflow_id: Workflow identifier
    params: Workflow parameters

Returns:
    Workflow execution result
"""
# Add timeout protection
try:
    result = await asyncio.wait_for(
        _execute_workflow_internal(workflow_id, params),
        timeout=300.0,  # 5 minute timeout
    )
    return result
except asyncio.TimeoutError:
    raise TimeoutError(f"Workflow {workflow_id} timed out after 5 minutes")
```

async def \_execute_workflow_internal(workflow_id: str, params: dict[str, Any]) -> dict\[str, Any\]:
"""Internal workflow execution."""
\# Simulated workflow execution
await asyncio.sleep(2.0)
return {"workflow_id": workflow_id, "status": "completed"}

# ============================================================================

# Example 7: Manual Circuit Breaker Usage

# ============================================================================

class ServiceClient:
"""Service client with manual circuit breaker control."""

```
def __init__(self):
    self.breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60,
        expected_exception=(ConnectionError, TimeoutError),
    )

async def call_service(self, endpoint: str) -> dict[str, Any]:
    """Call service with manual circuit breaker.

    This pattern allows more control than decorators:
    - Can check circuit state before attempting call
    - Can manually reset circuit breaker
    - Can handle CircuitBreakerError specifically
    """
    # Check circuit state before attempting call
    if self.breaker.state == CircuitState.OPEN:
        print(f"Circuit is OPEN, skipping call to {endpoint}")
        # Could return cached data or fallback value here
        return {"error": "service_unavailable", "cached": True}

    try:
        result = await self.breaker.call(self._make_request, endpoint)
        return result
    except CircuitBreakerError:
        # Circuit opened during call
        print(f"Circuit breaker opened during call to {endpoint}")
        return {"error": "service_unavailable", "circuit_open": True}

async def _make_request(self, endpoint: str) -> dict[str, Any]:
    """Actual HTTP request."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://service-api/{endpoint}")
        response.raise_for_status()
        return response.json()

def reset_circuit(self):
    """Manually reset circuit breaker (e.g., after maintenance)."""
    self.breaker.reset()
```

# ============================================================================

# Example 8: Combining Multiple Resilience Patterns

# ============================================================================

class ResilientMCPClient:
"""MCP client combining all resilience patterns."""

```
def __init__(self, server_url: str):
    self.server_url = server_url
    self.breaker = CircuitBreaker(
        failure_threshold=5,
        recovery_timeout=60,
        expected_exception=(ConnectionError, TimeoutError),
    )
    self.retry = Retry(
        max_attempts=3,
        backoff=BackoffStrategy.exponential(),
        expected_exception=(ConnectionError, TimeoutError, httpx.HTTPError),
    )

async def call_tool(
    self,
    tool_name: str,
    params: dict[str, Any],
    use_cache: bool = True,
) -> Any:
    """Call MCP tool with full resilience stack.

    Resilience stack (outer to inner):
    1. Circuit breaker (fail fast if service down)
    2. Retry (handle transient failures)
    3. Cache fallback (graceful degradation)
    4. Timeout protection

    Args:
        tool_name: Tool to call
        params: Tool parameters
        use_cache: Whether to use cache fallback

    Returns:
        Tool execution result
    """
    # Try cache first if enabled
    if use_cache:
        cached = await self._get_cached_result(tool_name, params)
        if cached is not None:
            return cached

    # Call with circuit breaker + retry
    try:
        result = await self.breaker.call(
            self.retry.call,
            self._execute_tool_call,
            tool_name,
            params,
        )

        # Cache successful result
        if use_cache:
            await self._cache_result(tool_name, params, result)

        return result

    except CircuitBreakerError:
        # Service is down, try stale cache
        if use_cache:
            stale = await self._get_stale_cache(tool_name, params)
            if stale is not None:
                return stale

        # Re-raise if no fallback available
        raise

async def _execute_tool_call(self, tool_name: str, params: dict[str, Any]) -> Any:
    """Actual tool execution."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{self.server_url}/mcp",
            json={
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": params,
                },
            },
        )
        response.raise_for_status()
        return response.json()

async def _get_cached_result(self, tool_name: str, params: dict[str, Any]) -> Any:
    """Get cached result if available."""
    # Simplified cache check
    return None

async def _get_stale_cache(self, tool_name: str, params: dict[str, Any]) -> Any:
    """Get stale cache as last resort."""
    # Simplified stale cache
    return None

async def _cache_result(self, tool_name: str, params: dict[str, Any], result: Any):
    """Cache successful result."""
    # Simplified cache storage
    pass
```

# ============================================================================

# Usage Examples

# ============================================================================

async def main():
"""Demonstrate resilience patterns in action."""

```
print("=" * 60)
print("Resilience Pattern Examples")
print("=" * 60)

# Example 1: Full resilient API call
print("\n1. Full resilient API call:")
try:
    result = await call_external_api("https://api.example.com/data")
    print(f"✓ Success: {result}")
except CircuitBreakerError as e:
    print(f"✗ Circuit breaker open: {e}")
except MaxRetriesExceededError as e:
    print(f"✗ Max retries exceeded: {e}")

# Example 2: Database with retry
print("\n2. Database query with retry:")
try:
    results = await execute_database_query("SELECT * FROM users", {})
    print(f"✓ Query successful: {len(results)} rows")
except Exception as e:
    print(f"✗ Query failed: {e}")

# Example 3: MCP server call with circuit breaker
print("\n3. MCP server call with circuit breaker:")
try:
    result = await call_mcp_server(
        "http://localhost:8682",
        "search_sessions",
        {"query": "test"}
    )
    print(f"✓ MCP call successful: {result}")
except CircuitBreakerError as e:
    print(f"✗ Circuit breaker open: {e}")

# Example 4: Cache with fallback
print("\n4. Cache with fallback to database:")
result = await get_data_with_cache("user:123")
print(f"✓ Got data: {result}")

# Example 5: LLM API with retry
print("\n5. LLM API call with retry:")
try:
    response = await call_llm_api("Write Python code")
    print(f"✓ LLM response: {response[:50]}...")
except MaxRetriesExceededError as e:
    print(f"✗ LLM API failed: {e}")

# Example 6: Workflow execution
print("\n6. Workflow execution with resilience:")
try:
    result = await execute_workflow("wf_123", {"param": "value"})
    print(f"✓ Workflow completed: {result}")
except Exception as e:
    print(f"✗ Workflow failed: {e}")

# Example 7: Manual circuit breaker
print("\n7. Manual circuit breaker control:")
client = ServiceClient()
result = await client.call_service("health")
print(f"✓ Service call: {result}")

# Check circuit state
print(f"   Circuit state: {client.breaker.state}")
print(f"   Failure count: {client.breaker.failure_count}")

# Example 8: Full resilient MCP client
print("\n8. Full resilient MCP client:")
mcp_client = ResilientMCPClient("http://localhost:8682")
try:
    result = await mcp_client.call_tool("search", {"query": "test"})
    print(f"✓ MCP tool call: {result}")
except Exception as e:
    print(f"✗ MCP call failed: {e}")
```

if __name__ == "__main__":
asyncio.run(main())
