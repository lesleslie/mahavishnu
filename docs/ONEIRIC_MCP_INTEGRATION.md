# Oneiric MCP Integration Guide

**Version:** 1.0.0
**Last Updated:** 2025-02-03
**Status:** Production Ready

## Overview

Mahavishnu integrates with Oneiric MCP to provide dynamic adapter discovery and resolution capabilities. This integration enables workflows to query, resolve, and monitor adapters at runtime, providing flexibility and resilience in adapter selection.

## Table of Contents

1. [Architecture](#architecture)
1. [Configuration](#configuration)
1. [MCP Tools](#mcp-tools)
1. [Python API](#python-api)
1. [Workflow Integration](#workflow-integration)
1. [Examples](#examples)
1. [Testing](#testing)
1. [Troubleshooting](#troubleshooting)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Mahavishnu                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              OneiricMCPClient                            │  │
│  │  - gRPC connection management                            │  │
│  │  - Adapter list caching (TTL: 300s)                      │  │
│  │  - Circuit breaker (threshold: 3, duration: 300s)       │  │
│  │  - Health monitoring                                     │  │
│  └─────────────┬────────────────────────────────────────────┘  │
│                │ gRPC (port 8679 insecure, 8680 TLS)          │
│                ▼                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │         Oneiric MCP Server                           │    │
│  │  - Adapter Registry (gRPC)                           │    │
│  │  - Health Monitoring                                 │    │
│  │  - JWT Authentication (production)                   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              MCP Tools                                │  │
│  │  - oneiric_list_adapters                             │  │
│  │  - oneiric_resolve_adapter                           │  │
│  │  - oneiric_check_health                              │  │
│  │  - oneiric_get_adapter                               │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Development Configuration

Add to `settings/mahavishnu.yaml`:

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8679  # Insecure dev port
  use_tls: false
  timeout_sec: 30
  cache_ttl_sec: 300  # 5 minutes
  jwt_enabled: false
```

### Production Configuration

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "oneiric-mcp.production.internal"
  grpc_port: 8680  # TLS port
  use_tls: true
  timeout_sec: 30
  cache_ttl_sec: 300
  jwt_enabled: true
  jwt_project: "mahavishnu"
  tls_cert_path: "/etc/mahavishnu/tls/client.crt"
  tls_key_path: "/etc/mahavishnu/tls/client.key"
  tls_ca_path: "/etc/mahavishnu/tls/ca.crt"
  circuit_breaker_threshold: 3
  circuit_breaker_duration_sec: 300
```

### Environment Variables

```bash
# Enable Oneiric MCP integration
export MAHAVISHNU_ONEIRIC_MCP__ENABLED=true

# gRPC connection
export MAHAVISHNU_ONEIRIC_MCP__GRPC_HOST=localhost
export MAHAVISHNU_ONEIRIC_MCP__GRPC_PORT=8679

# Cache settings
export MAHAVISHNU_ONEIRIC_MCP__CACHE_TTL_SEC=300

# JWT authentication (production)
export MAHAVISHNU_ONEIRIC_MCP__JWT_ENABLED=true
export MAHAVISHNU_ONEIRIC_MCP__JWT_SECRET=your-secret-key
export MAHAVISHNU_ONEIRIC_MCP__JWT_PROJECT=mahavishnu

# TLS (production)
export MAHAVISHNU_ONEIRIC_MCP__USE_TLS=true
export MAHAVISHNU_ONEIRIC_MCP__TLS_CERT_PATH=/path/to/client.crt
export MAHAVISHNU_ONEIRIC_MCP__TLS_KEY_PATH=/path/to/client.key
export MAHAVISHNU_ONEIRIC_MCP__TLS_CA_PATH=/path/to/ca.crt
```

## MCP Tools

### oneiric_list_adapters

List available adapters with optional filtering.

**Parameters:**

- `project` (optional): Filter by project name
- `domain` (optional): Filter by domain (e.g., "adapter", "service")
- `category` (optional): Filter by category (e.g., "storage", "orchestration")
- `healthy_only` (optional): Only return healthy adapters (default: false)
- `use_cache` (optional): Use cached results (default: true)

**Returns:**

```python
{
    "count": 5,
    "adapters": [
        {
            "adapter_id": "mahavishnu.adapter.storage.s3",
            "project": "mahavishnu",
            "domain": "adapter",
            "category": "storage",
            "provider": "s3",
            "capabilities": ["read", "write", "delete"],
            "factory_path": "mahavishnu.adapters.storage.S3StorageAdapter",
            "health_status": "healthy",
            ...
        }
    ],
    "cached": true
}
```

**Example:**

```python
# List all healthy storage adapters
result = await oneiric_list_adapters(
    category="storage",
    healthy_only=True
)

print(f"Found {result['count']} storage adapters")
for adapter in result['adapters']:
    print(f"  - {adapter['adapter_id']}")
```

### oneiric_resolve_adapter

Resolve best-matching adapter by domain, category, and provider.

**Parameters:**

- `domain` (required): Adapter domain
- `category` (required): Adapter category
- `provider` (required): Adapter provider
- `project` (optional): Project filter
- `healthy_only` (optional): Only return healthy adapters (default: true)

**Returns:**

```python
{
    "found": true,
    "adapter": {
        "adapter_id": "mahavishnu.adapter.storage.s3",
        ...
    }
}
```

**Example:**

```python
# Resolve S3 storage adapter
result = await oneiric_resolve_adapter(
    domain="adapter",
    category="storage",
    provider="s3"
)

if result['found']:
    adapter = result['adapter']
    print(f"Resolved: {adapter['adapter_id']}")
    print(f"Factory: {adapter['factory_path']}")
```

### oneiric_check_health

Check health status of a specific adapter.

**Parameters:**

- `adapter_id` (required): Adapter's unique ID

**Returns:**

```python
{
    "healthy": true,
    "adapter_id": "mahavishnu.adapter.storage.s3"
}
```

**Example:**

```python
# Check adapter health before use
health = await oneiric_check_health("mahavishnu.adapter.storage.s3")

if health['healthy']:
    print("Adapter is healthy, safe to use")
else:
    print("Adapter is unhealthy, use fallback")
```

### oneiric_get_adapter

Get detailed information about a specific adapter.

**Parameters:**

- `adapter_id` (required): Adapter's unique ID

**Returns:**

```python
{
    "found": true,
    "adapter": {
        "adapter_id": "mahavishnu.adapter.storage.s3",
        "project": "mahavishnu",
        "domain": "adapter",
        "category": "storage",
        "provider": "s3",
        "capabilities": ["read", "write"],
        "factory_path": "mahavishnu.adapters.storage.S3StorageAdapter",
        "health_check_url": "http://localhost:8080/health",
        "metadata": {"region": "us-east-1"},
        "health_status": "healthy",
        "registered_at": "2025-02-03T12:00:00Z",
        "last_heartbeat": "2025-02-03T12:05:00Z"
    }
}
```

**Example:**

```python
# Get adapter details
result = await oneiric_get_adapter("mahavishnu.adapter.storage.s3")

if result['found']:
    adapter = result['adapter']
    print(f"Provider: {adapter['provider']}")
    print(f"Capabilities: {adapter['capabilities']}")
```

### oneiric_invalidate_cache

Invalidate the adapter list cache.

**Returns:**

```python
{
    "success": true,
    "message": "Adapter cache invalidated successfully"
}
```

**Example:**

```python
# Invalidate cache after registering new adapter
await oneiric_invalidate_cache()

# Now list_adapters will fetch fresh results
adapters = await oneiric_list_adapters()
```

### oneiric_health_check

Check overall health of Oneiric MCP integration.

**Returns:**

```python
{
    "status": "healthy",
    "connected": true,
    "adapter_count": 42,
    "cache_entries": 5
}
```

**Example:**

```python
# Check integration health before critical workflow
health = await oneiric_health_check()

if health['status'] != 'healthy':
    logger.warning(f"Oneiric MCP unhealthy: {health.get('error')}")
    # Use fallback mechanism
```

## Python API

### Creating a Client

```python
from mahavishnu.core.oneiric_client import (
    OneiricMCPClient,
    OneiricMCPConfig,
)

# Create configuration
config = OneiricMCPConfig(
    enabled=True,
    grpc_host="localhost",
    grpc_port=8679,
    use_tls=False,
    cache_ttl_sec=300,
)

# Create client
client = OneiricMCPClient(config)
```

### Listing Adapters

```python
# List all adapters
adapters = await client.list_adapters()

# List with filters
storage_adapters = await client.list_adapters(
    domain="adapter",
    category="storage",
    healthy_only=True,
)

# Without cache
fresh_adapters = await client.list_adapters(use_cache=False)
```

### Resolving Adapters

```python
# Resolve specific adapter
adapter = await client.resolve_adapter(
    domain="adapter",
    category="storage",
    provider="s3",
    healthy_only=True,
)

if adapter:
    print(f"Found: {adapter.adapter_id}")
    print(f"Factory: {adapter.factory_path}")
```

### Health Checking

```python
# Check adapter health
is_healthy = await client.check_adapter_health("mahavishnu.adapter.storage.s3")

# Overall integration health
health = await client.health_check()
print(f"Status: {health['status']}")
print(f"Adapters: {health['adapter_count']}")
```

### Cache Management

```python
# Invalidate cache
await client.invalidate_cache()

# Next query will fetch fresh results
adapters = await client.list_adapters()
```

### Cleanup

```python
# Always close client when done
await client.close()
```

## Workflow Integration

### YAML Workflow Example

```yaml
workflows:
  - name: "backup-with-dynamic-storage"
    steps:
      # Discover storage adapters
      - name: "discover-storage"
        tool: "oneiric_list_adapters"
        params:
          domain: "adapter"
          category: "storage"
          healthy_only: true
        outputs:
          - storage_adapters

      # Resolve S3 adapter
      - name: "resolve-s3"
        tool: "oneiric_resolve_adapter"
        params:
          domain: "adapter"
          category: "storage"
          provider: "s3"
        outputs:
          - s3_adapter

      # Verify health
      - name: "check-health"
        tool: "oneiric_check_health"
        params:
          adapter_id: "${steps.resolve-s3.adapter.adapter_id}"
        outputs:
          - health

      # Use adapter if healthy
      - name: "backup"
        tool: "coord_backup_repositories"
        params:
          adapter: "${steps.resolve-s3.adapter}"
        condition: "${steps.check-health.healthy == true}"
```

### Python Workflow Example

```python
async def backup_workflow(repos: list[str]):
    """Backup repositories using dynamically discovered storage adapter."""

    # Configure client
    config = OneiricMCPConfig(enabled=True)
    client = OneiricMCPClient(config)

    try:
        # Discover storage adapters
        adapters = await client.list_adapters(
            domain="adapter",
            category="storage",
            healthy_only=True,
        )

        if not adapters:
            raise Exception("No storage adapters available")

        # Select S3 if available, otherwise first adapter
        adapter = next(
            (a for a in adapters if a.provider == "s3"),
            adapters[0]
        )

        # Verify health
        is_healthy = await client.check_adapter_health(adapter.adapter_id)
        if not is_healthy:
            raise Exception(f"Adapter unhealthy: {adapter.adapter_id}")

        # Perform backup
        # ... (backup logic using adapter.factory_path)

        return True

    finally:
        await client.close()
```

## Examples

See `/Users/les/Projects/mahavishnu/examples/` for complete examples:

- `oneiric_workflow_examples.py` - Python workflow examples
- `workflow_oneiric_examples.yaml` - YAML workflow definitions

### Running Examples

```bash
# Start Oneiric MCP server (in separate terminal)
cd /Users/les/Projects/oneiric-mcp
python -m oneiric_mcp --port 8679

# Run Python examples
cd /Users/les/Projects/mahavishnu
python examples/oneiric_workflow_examples.py

# Or run specific example
python -c "
import asyncio
from examples.oneiric_workflow_examples import example_1_list_storage_adapters
asyncio.run(example_1_list_storage_adapters())
"
```

## Testing

### Unit Tests

```bash
# Run unit tests (don't require Oneiric MCP server)
pytest tests/unit/test_oneiric_client.py -v
```

### Integration Tests

```bash
# Start Oneiric MCP server first
cd /Users/les/Projects/oneiric-mcp
python -m oneiric_mcp --port 8679

# Run integration tests (in separate terminal)
cd /Users/les/Projects/mahavishnu
pytest tests/integration/test_oneiric_integration.py -v
```

### Test Coverage

```bash
# Run with coverage
pytest tests/unit/test_oneiric_client.py \
    tests/integration/test_oneiric_integration.py \
    --cov=mahavishnu.core.oneiric_client \
    --cov=mahavishnu.mcp.tools.oneiric_tools \
    --cov-report=html
```

## Troubleshooting

### Connection Issues

**Problem:** Cannot connect to Oneiric MCP server

```python
# Error
ConnectionError: Timeout connecting to Oneiric MCP at localhost:8679

# Solutions:
1. Verify Oneiric MCP server is running:
   ps aux | grep oneiric_mcp

2. Check correct port:
   # Development: 8679 (insecure)
   # Production: 8680 (TLS)

3. Test connection:
   grpcurl -plaintext localhost:8679 list

4. Check firewall:
   telnet localhost 8679
```

### TLS Configuration Errors

**Problem:** TLS certificate errors

```python
# Error
ValueError: tls_cert_path and tls_key_path must be provided when use_tls is true

# Solutions:
1. Ensure certificate paths are correct:
   ls -la /etc/mahavishnu/tls/

2. Set via environment:
   export MAHAVISHNU_ONEIRIC_MCP__TLS_CERT_PATH=/path/to/client.crt
   export MAHAVISHNU_ONEIRIC_MCP__TLS_KEY_PATH=/path/to/client.key

3. For mTLS, also set CA path:
   export MAHAVISHNU_ONEIRIC_MCP__TLS_CA_PATH=/path/to/ca.crt
```

### Adapter Not Found

**Problem:** Adapter not found in registry

```python
# Error
"found": false,
"error": "No adapter found matching the criteria"

# Solutions:
1. List all adapters to see what's available:
   adapters = await client.list_adapters()

2. Check adapter is registered:
   # Start Oneiric MCP server and check logs

3. Verify filters match registered adapter:
   # Check domain, category, provider are correct

4. Try without healthy_only filter:
   adapter = await client.resolve_adapter(
       domain="adapter",
       category="storage",
       provider="s3",
       healthy_only=False,  # Include unhealthy adapters
   )
```

### Circuit Breaker Blocking

**Problem:** Adapter blocked by circuit breaker

```python
# Error
"Adapter is blocked by circuit breaker"

# Solutions:
1. Wait for block duration to expire (default: 5 minutes)

2. Check adapter health:
   health = await client.check_adapter_health(adapter_id)

3. If adapter is healthy, circuit breaker will reset on success

4. Adjust circuit breaker settings:
   config = OneiricMCPConfig(
       circuit_breaker_threshold=5,  # More failures before blocking
       circuit_breaker_duration_sec=60,  # Shorter block duration
   )
```

### Cache Issues

**Problem:** Stale adapter list in cache

```python
# Solutions:
1. Invalidate cache:
   await client.invalidate_cache()

2. Disable cache for critical queries:
   adapters = await client.list_adapters(use_cache=False)

3. Reduce cache TTL:
   config = OneiricMCPConfig(cache_ttl_sec=60)  # 1 minute

4. Disable cache entirely:
   config = OneiricMCPConfig(cache_ttl_sec=0)
```

### Performance Issues

**Problem:** Slow adapter queries

```python
# Solutions:
1. Enable caching:
   config = OneiricMCPConfig(cache_ttl_sec=300)

2. Use parallel queries:
   import asyncio
   results = await asyncio.gather(
       client.list_adapters(category="storage"),
       client.list_adapters(category="cache"),
       client.list_adapters(category="memory"),
   )

3. Increase timeout for slow networks:
   config = OneiricMCPConfig(timeout_sec=60)

4. Use healthy_only=False to avoid health checks:
   adapters = await client.list_adapters(
       category="storage",
       healthy_only=False,  # Skip health filter
   )
```

## Monitoring

### Metrics

The Oneiric MCP client exposes the following metrics (when observability enabled):

- `oneiric_adapter_queries_total` - Total adapter queries
- `oneiric_adapter_query_duration_seconds` - Query duration histogram
- `oneiric_adapter_health_checks_total` - Total health checks
- `oneiric_cache_hits_total` - Cache hit count
- `oneiric_cache_misses_total` - Cache miss count
- `oneiric_circuit_breaker_blocks_total` - Circuit breaker triggers

### Health Checks

```python
# Programmatic health check
health = await client.health_check()

if health['status'] == 'healthy':
    print(f"Connected: {health['connected']}")
    print(f"Adapters: {health['adapter_count']}")
    print(f"Cache entries: {health['cache_entries']}")
else:
    print(f"Error: {health.get('error')}")
```

### Logging

Enable debug logging for troubleshooting:

```python
import logging
logging.getLogger('mahavishnu.core.oneiric_client').setLevel(logging.DEBUG)
```

## Best Practices

1. **Always close client**: Use `async with` or `finally` block
1. **Enable caching in production**: Set `cache_ttl_sec=300`
1. **Use circuit breaker**: Prevent cascading failures
1. **Implement fallback chains**: Try multiple adapters
1. **Monitor health**: Check adapter health before critical operations
1. **Handle connection errors**: Graceful degradation when Oneiric MCP unavailable
1. **Use parallel queries**: Batch adapter discovery for better performance
1. **Invalidate cache strategically**: After adapter registration changes

## References

- Oneiric MCP: `/Users/les/Projects/oneiric-mcp`
- Integration Design: `/Users/les/Projects/mahavishnu/ONEIRIC_MCP_INTEGRATION.md`
- Example Workflows: `/Users/les/Projects/mahavishnu/examples/`
- MCP Tools Reference: `/Users/les/Projects/mahavishnu/docs/MCP_TOOLS_REFERENCE.md`
