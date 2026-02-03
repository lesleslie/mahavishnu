# Oneiric MCP Integration for Mahavishnu

**Integration Status:** ✓ Complete
**Version:** 1.0.0
**Last Updated:** 2025-02-03

## What is This?

This integration enables Mahavishnu to dynamically discover, resolve, and monitor adapters through Oneiric MCP's universal adapter registry. This means workflows can query for available adapters at runtime, select the best option, and monitor their health - all automatically.

## Quick Start

### 1. Start Oneiric MCP Server

```bash
# Terminal 1: Start Oneiric MCP server (insecure dev mode)
cd /Users/les/Projects/oneiric-mcp
python -m oneiric_mcp --port 8679
```

### 2. Enable Integration in Mahavishnu

Add to `settings/mahavishnu.yaml`:

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8679
  use_tls: false
  cache_ttl_sec: 300
```

Or via environment variable:

```bash
export MAHAVISHNU_ONEIRIC_MCP__ENABLED=true
```

### 3. Run Quick Start

```bash
# Terminal 2: Run quick start demo
cd /Users/les/Projects/mahavishnu
python examples/quickstart_oneiric.py
```

Expected output:
```
============================================================
Oneiric MCP Integration - Quick Start
============================================================

Step 1: Configuring Oneiric MCP client...
  ✓ Configuration created
    Host: localhost
    Port: 8679

Step 2: Creating client...
  ✓ Client created

Step 3: Checking connection...
  ✓ Connected successfully
    Status: healthy
    Adapters available: 42

Step 4: Listing available adapters...
  ✓ Found 42 adapters

  Sample adapters:
    - mahavishnu.adapter.storage.s3
      Category: storage, Provider: s3
    - session-buddy.adapter.cache.redis
      Category: cache, Provider: redis
    ...
```

## What You Can Do

### 1. List Available Adapters

```python
from mahavishnu.mcp.tools.oneiric_tools import oneiric_list_adapters

# List all storage adapters
result = await oneiric_list_adapters(
    category="storage",
    healthy_only=True
)

print(f"Found {result['count']} adapters")
for adapter in result['adapters']:
    print(f"  - {adapter['provider']}: {adapter['adapter_id']}")
```

### 2. Resolve Specific Adapter

```python
from mahavishnu.mcp.tools.oneiric_tools import oneiric_resolve_adapter

# Find S3 storage adapter
result = await oneiric_resolve_adapter(
    domain="adapter",
    category="storage",
    provider="s3"
)

if result['found']:
    adapter = result['adapter']
    print(f"Using: {adapter['factory_path']}")
```

### 3. Check Adapter Health

```python
from mahavishnu.mcp.tools.oneiric_tools import oneiric_check_health

# Check before using
health = await oneiric_check_health("mahavishnu.adapter.storage.s3")

if health['healthy']:
    print("Safe to use")
else:
    print("Use fallback adapter")
```

### 4. Use in Workflows

YAML workflow:

```yaml
workflows:
  - name: "smart-backup"
    steps:
      # Discover storage adapters
      - name: "find-storage"
        tool: "oneiric_list_adapters"
        params:
          category: "storage"
          healthy_only: true

      # Try S3 first
      - name: "try-s3"
        tool: "oneiric_resolve_adapter"
        params:
          domain: "adapter"
          category: "storage"
          provider: "s3"

      # Verify health
      - name: "check-health"
        tool: "oneiric_check_health"
        params:
          adapter_id: "${steps.try-s3.adapter.adapter_id}"

      # Use adapter if healthy
      - name: "backup"
        tool: "coord_backup_repositories"
        params:
          storage_adapter: "${steps.try-s3.adapter}"
        condition: "${steps.check-health.healthy == true}"
```

## Key Features

### ✓ Dynamic Adapter Discovery
Query adapters by domain, category, provider at runtime

### ✓ Health Monitoring
Check adapter health before use, automatic circuit breaker

### ✓ Smart Caching
5-minute cache by default, configurable, automatic invalidation

### ✓ Fallback Strategies
Try multiple adapters automatically, graceful degradation

### ✓ Production Ready
TLS/mTLS, JWT auth, circuit breaker, comprehensive logging

### ✓ Easy Integration
6 MCP tools, Python API, YAML workflow support

## MCP Tools Reference

| Tool | Description | Use For |
|------|-------------|---------|
| `oneiric_list_adapters` | List adapters with filters | Discovering available adapters |
| `oneiric_resolve_adapter` | Find specific adapter | Resolving by domain/category/provider |
| `oneiric_check_health` | Check adapter health | Health verification before use |
| `oneiric_get_adapter` | Get adapter details | Inspecting adapter configuration |
| `oneiric_invalidate_cache` | Clear cache | Force fresh adapter discovery |
| `oneiric_health_check` | Check integration health | Verify Oneiric MCP connection |

## Configuration Options

### Development (Default)

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8679      # Insecure dev port
  use_tls: false
  timeout_sec: 30
  cache_ttl_sec: 300   # 5 minutes
  jwt_enabled: false
```

### Production

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "oneiric-mcp.production.internal"
  grpc_port: 8680      # TLS port
  use_tls: true
  timeout_sec: 30
  cache_ttl_sec: 300
  jwt_enabled: true
  jwt_project: "mahavishnu"
  tls_cert_path: "/etc/mahavishnu/tls/client.crt"
  tls_key_path: "/etc/mahavishnu/tls/client.key"
  tls_ca_path: "/etc/mahavishnu/tls/ca.crt"
```

## Examples

### Example 1: List Storage Adapters

```python
from mahavishnu.core.oneiric_client import OneiricMCPClient, OneiricMCPConfig

config = OneiricMCPConfig(enabled=True)
client = OneiricMCPClient(config)

try:
    adapters = await client.list_adapters(
        domain="adapter",
        category="storage",
        healthy_only=True
    )

    for adapter in adapters:
        print(f"{adapter.provider}: {adapter.adapter_id}")
finally:
    await client.close()
```

### Example 2: Resolve with Fallback

```python
# Try S3 first
s3 = await client.resolve_adapter(
    domain="adapter",
    category="storage",
    provider="s3",
    healthy_only=True
)

if not s3:
    # Fallback to SQLite
    sqlite = await client.resolve_adapter(
        domain="adapter",
        category="storage",
        provider="sqlite",
        healthy_only=True
    )
    adapter = sqlite
else:
    adapter = s3

# Use adapter
print(f"Using: {adapter.factory_path}")
```

### Example 3: Health Monitoring

```python
# Check all adapter health
adapters = await client.list_adapters()

unhealthy = []
for adapter in adapters:
    is_healthy = await client.check_adapter_health(adapter.adapter_id)
    if not is_healthy:
        unhealthy.append(adapter.adapter_id)

if unhealthy:
    print(f"Warning: {len(unhealthy)} unhealthy adapters")
    for adapter_id in unhealthy:
        print(f"  - {adapter_id}")
```

## Testing

### Run Unit Tests (No Server Required)

```bash
cd /Users/les/Projects/mahavishnu
pytest tests/unit/test_oneiric_client.py -v
```

### Run Integration Tests (Requires Server)

```bash
# Terminal 1: Start Oneiric MCP server
cd /Users/les/Projects/oneiric-mcp
python -m oneiric_mcp --port 8679

# Terminal 2: Run integration tests
cd /Users/les/Projects/mahavishnu
pytest tests/integration/test_oneiric_integration.py -v
```

### Run Examples

```bash
cd /Users/les/Projects/mahavishnu
python examples/oneiric_workflow_examples.py
```

## Troubleshooting

### Problem: Cannot Connect

```
ConnectionError: Timeout connecting to Oneiric MCP at localhost:8679
```

**Solutions:**
1. Start Oneiric MCP server: `cd /Users/les/Projects/oneiric-mcp && python -m oneiric_mcp --port 8679`
2. Check port: `telnet localhost 8679`
3. Verify config: Check `oneiric_mcp.grpc_port` in settings

### Problem: No Adapters Found

```
"count": 0, "adapters": []
```

**Solutions:**
1. Register adapters in Oneiric MCP
2. Check Oneiric MCP server logs
3. Try without filters: `await client.list_adapters()`

### Problem: Adapter Unhealthy

```
"healthy": false, "adapter_id": "mahavishnu.adapter.storage.s3"
```

**Solutions:**
1. Check adapter health status in Oneiric MCP
2. Verify adapter is running
3. Check adapter's health check URL
4. Use fallback adapter

## Performance

### Caching

By default, adapter lists are cached for 5 minutes:

```python
# First query: ~50ms (fetch from server)
adapters1 = await client.list_adapters()

# Second query: ~1ms (from cache)
adapters2 = await client.list_adapters()

# Force fresh query
await client.invalidate_cache()
adapters3 = await client.list_adapters()  # ~50ms again
```

### Circuit Breaker

Adapters that fail 3 times are blocked for 5 minutes:

```python
# Prevents cascading failures
# Automatically unblocks after timeout
# Resets on successful call
```

## Documentation

- **Design Doc:** `/Users/les/Projects/mahavishnu/ONEIRIC_MCP_INTEGRATION.md`
- **User Guide:** `/Users/les/Projects/mahavishnu/docs/ONEIRIC_MCP_INTEGRATION.md`
- **Implementation Summary:** `/Users/les/Projects/mahavishnu/ONEIRIC_MCP_INTEGRATION_SUMMARY.md`
- **Examples:** `/Users/les/Projects/mahavishnu/examples/`

## Files Delivered

### Core Implementation
- `mahavishnu/core/oneiric_client.py` - gRPC client (600+ lines)
- `mahavishnu/core/config.py` - Configuration (updated with OneiricMCPConfig)

### MCP Tools
- `mahavishnu/mcp/tools/oneiric_tools.py` - 6 MCP tools (400+ lines)

### Examples
- `examples/quickstart_oneiric.py` - Quick start script
- `examples/oneiric_workflow_examples.py` - 7 Python examples
- `examples/workflow_oneiric_examples.yaml` - 7 YAML workflows

### Tests
- `tests/unit/test_oneiric_client.py` - Unit tests
- `tests/integration/test_oneiric_integration.py` - Integration tests

### Documentation
- `ONEIRIC_MCP_INTEGRATION.md` - Design document
- `ONEIRIC_MCP_INTEGRATION_SUMMARY.md` - Implementation summary
- `docs/ONEIRIC_MCP_INTEGRATION.md` - User guide

## Success Criteria

✓ Functional - Mahavishnu can query and resolve adapters from Oneiric MCP
✓ Reliable - Graceful fallback when Oneiric MCP unavailable
✓ Performant - <100ms cached, <500ms uncached queries
✓ Secure - JWT auth and TLS support for production
✓ Observable - Full logging, health checks, error reporting

## Next Steps

1. **Get Started:** Run `python examples/quickstart_oneiric.py`
2. **Try Examples:** Run `python examples/oneiric_workflow_examples.py`
3. **Read Documentation:** See `docs/ONEIRIC_MCP_INTEGRATION.md`
4. **Configure Production:** Enable TLS, JWT, monitoring
5. **Register Adapters:** Add your adapters to Oneiric MCP registry

## Support

- **Issues:** Check troubleshooting section or logs
- **Questions:** See user guide documentation
- **Examples:** Check examples/ directory
- **Tests:** Run unit tests for usage patterns

---

**Integration complete and ready for use!** 🎉
