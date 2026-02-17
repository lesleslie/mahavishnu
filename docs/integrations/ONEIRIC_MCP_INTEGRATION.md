# Oneiric MCP Integration for Mahavishnu

**Status:** Implementation Plan
**Date:** 2025-02-03
**Sprint:** Sprint 6 - Integration & Ecosystem

## Overview

This document describes the integration between Oneiric MCP and Mahavishnu to enable dynamic adapter discovery and resolution in workflow orchestration.

## Integration Goals

1. **Dynamic Adapter Discovery**: Mahavishnu workflows can query Oneiric's universal adapter registry
1. **gRPC Registry Connection**: Direct gRPC client for high-performance adapter queries
1. **Health Monitoring**: Track adapter health in workflow execution
1. **Fallback Strategy**: Graceful degradation when Oneiric MCP is unavailable

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Mahavishnu                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    gRPC     ┌──────────────────────────────┐ │
│  │   Adapter   │ ◄──────────► │    Oneiric MCP               │ │
│  │   Client    │             │    (gRPC Registry Server)    │ │
│  │             │             │    Port 8679 (insecure)      │ │
│  └─────────────┘             │    Port 8680 (TLS)           │ │
│       │                      └──────────────────────────────┘ │
│       │                                                    │
│       ▼                                                     │
│  ┌─────────────┐                                            │
│  │   MCP       │    Exposes adapter discovery as MCP tools   │
│  │   Tools     │                                            │
│  └─────────────┘                                            │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              Workflow Orchestration                  │ │
│  │  - Query adapters before execution                   │ │
│  │  - Validate adapter health                          │ │
│  │  - Resolve adapter instances                        │ │
│  │  - Monitor adapter health during execution          │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Workflow Definition**: Specifies adapter requirements (domain, category, provider)
1. **Adapter Query**: Query Oneiric MCP for available adapters
1. **Health Check**: Verify adapter health before execution
1. **Resolution**: Resolve adapter factory and instantiate
1. **Execution**: Execute workflow with resolved adapter
1. **Monitoring**: Track adapter health during execution

## Implementation Plan

### Phase 1: gRPC Client Integration (P0)

**Files to Create:**

- `mahavishnu/core/oneiric_client.py` - gRPC client wrapper
- `mahavishnu/core/config.py` - Add Oneiric MCP configuration
- `tests/unit/test_oneiric_client.py` - Unit tests

**Configuration:**

```yaml
# settings/mahavishnu.yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8679  # Insecure dev port
  use_tls: false   # TLS for production (port 8680)
  timeout_sec: 30
  cache_ttl_sec: 300  # Cache adapter list for 5 minutes
  jwt_enabled: false   # Enable for production
```

**API Design:**

```python
class OneiricMCPClient:
    """gRPC client for Oneiric MCP adapter registry."""

    async def list_adapters(
        self,
        project: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = False,
    ) -> list[AdapterEntry]:
        """List available adapters with optional filters."""

    async def get_adapter(self, adapter_id: str) -> AdapterEntry | None:
        """Get specific adapter by ID."""

    async def check_adapter_health(self, adapter_id: str) -> bool:
        """Check if adapter is healthy."""

    async def resolve_adapter(
        self,
        domain: str,
        category: str,
        provider: str,
    ) -> AdapterEntry | None:
        """Resolve best-matching adapter."""
```

### Phase 2: MCP Tool Integration (P0)

**Files to Create:**

- `mahavishnu/mcp/tools/oneiric_tools.py` - MCP tools for adapter discovery

**MCP Tools:**

1. **`oneiric_list_adapters`** - List available adapters
1. **`oneiric_resolve_adapter`** - Resolve adapter by domain/category/provider
1. **`oneiric_check_health`** - Check adapter health
1. **`oneiric_get_adapter`** - Get adapter details by ID

### Phase 3: Workflow Integration (P1)

**Enhancements:**

- `mahavishnu/core/workflow_state.py` - Add adapter tracking
- `mahavishnu/core/workflow_executor.py` - Create new module

**Workflow Definition Schema:**

```yaml
workflows:
  - name: "multi-repo-test"
    adapter_requirements:
      - domain: "adapter"
        category: "storage"
        provider: "s3"
      - domain: "adapter"
        category: "orchestration"
        provider: "prefect"
    steps:
      - name: "query_adapters"
        tool: "oneiric_list_adapters"
        params:
          category: "storage"
          healthy_only: true
      - name: "validate_health"
        tool: "oneiric_check_health"
        params:
          adapter_id: "${steps.query_adapters.results[0].adapter_id}"
```

### Phase 4: Health Monitoring (P1)

**Features:**

- Background health check task
- Adapter health cache
- Circuit breaker for unhealthy adapters
- Automatic adapter failover

## Integration Points

### 1. Pool Orchestration

**Use Case:** Worker pools need storage adapters for memory aggregation

```python
# mahavishnu/pools/manager.py

class PoolManager:
    def __init__(self, oneiric_client: OneiricMCPClient):
        self.oneiric = oneiric_client

    async def get_storage_adapter(self) -> AdapterEntry:
        """Resolve storage adapter for memory aggregation."""
        adapters = await self.oneiric.list_adapters(
            domain="adapter",
            category="storage",
            healthy_only=True
        )
        return adapters[0] if adapters else None
```

### 2. Worker Orchestration

**Use Case:** Workers need orchestration adapters for task execution

```python
# mahavishnu/workers/manager.py

class WorkerManager:
    async def resolve_orchestration_adapter(
        self,
        provider: str  # "prefect", "llamaindex"
    ) -> OrchestratorAdapter:
        """Resolve orchestration adapter from Oneiric."""
        adapter = await self.oneiric.resolve_adapter(
            domain="adapter",
            category="orchestration",
            provider=provider
        )
        return self._instantiate_adapter(adapter)
```

### 3. Coordination System

**Use Case:** Cross-repository coordination needs caching adapters

```python
# mahavishnu/core/coordination/manager.py

class CoordinationManager:
    async def setup_caching(self):
        """Setup distributed caching using Oneiric adapters."""
        cache_adapters = await self.oneiric.list_adapters(
            domain="adapter",
            category="cache",
            healthy_only=True
        )
        # Select best cache adapter (Redis, Memcached, etc.)
```

## Testing Strategy

### Unit Tests

```bash
# Test gRPC client
pytest tests/unit/test_oneiric_client.py

# Test MCP tools
pytest tests/unit/test_oneiric_tools.py
```

### Integration Tests

```bash
# Test with real Oneiric MCP server
pytest tests/integration/test_oneiric_integration.py
```

### E2E Workflow Tests

```bash
# Test complete workflow with adapter resolution
pytest tests/e2e/test_workflow_with_oneiric.py
```

## Error Handling

### Fallback Strategy

1. **Oneiric MCP Unavailable**: Use local adapter registry
1. **Adapter Not Found**: Raise specific error with suggestions
1. **Adapter Unhealthy**: Mark unhealthy, try next candidate
1. **Resolution Timeout**: Use cached adapter list if available

### Circuit Breaker

```python
class AdapterCircuitBreaker:
    """Circuit breaker for failing adapters."""

    def __init__(self, failure_threshold: int = 3):
        self.failure_threshold = failure_threshold
        self.failures: dict[str, int] = {}
        self.blocked_until: dict[str, datetime] = {}

    async def is_available(self, adapter_id: str) -> bool:
        """Check if adapter is available (not blocked)."""
        if adapter_id in self.blocked_until:
            if datetime.now() < self.blocked_until[adapter_id]:
                return False
        return True

    async def record_failure(self, adapter_id: str):
        """Record adapter failure and potentially block it."""
        self.failures[adapter_id] = self.failures.get(adapter_id, 0) + 1
        if self.failures[adapter_id] >= self.failure_threshold:
            # Block for 5 minutes
            self.blocked_until[adapter_id] = datetime.now() + timedelta(minutes=5)
```

## Performance Considerations

### Caching Strategy

```python
class CachedOneiricClient:
    """Oneiric client with adapter list caching."""

    def __init__(self, client: OneiricMCPClient, ttl_sec: int = 300):
        self.client = client
        self.cache: dict[str, tuple[list[AdapterEntry], datetime]] = {}
        self.ttl_sec = ttl_sec

    async def list_adapters(self, **kwargs) -> list[AdapterEntry]:
        """List adapters with cache lookup."""
        cache_key = self._make_cache_key(**kwargs)

        if cache_key in self.cache:
            adapters, cached_at = self.cache[cache_key]
            if (datetime.now() - cached_at).total_seconds() < self.ttl_sec:
                return adapters

        # Cache miss or expired
        adapters = await self.client.list_adapters(**kwargs)
        self.cache[cache_key] = (adapters, datetime.now())
        return adapters
```

### Connection Pooling

- Reuse gRPC channel across requests
- Keep connection alive with health checks
- Graceful reconnection on failure

## Security

### Authentication

```yaml
# Production configuration
oneiric_mcp:
  jwt_enabled: true
  jwt_secret: "${MAHAVISHNU_ONEIRIC_JWT_SECRET}"
  jwt_project: "mahavishnu"
```

### TLS Configuration

```yaml
oneiric_mcp:
  use_tls: true
  grpc_port: 8680
  tls_cert_path: "/path/to/client.crt"
  tls_key_path: "/path/to/client.key"
  tls_ca_path: "/path/to/ca.crt"
```

## Deployment

### Development

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8679
  use_tls: false
  jwt_enabled: false
```

### Production

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "oneiric-mcp.production.internal"
  grpc_port: 8680
  use_tls: true
  jwt_enabled: true
  jwt_secret: "${MAHAVISHNU_ONEIRIC_JWT_SECRET}"
  tls_cert_path: "/etc/mahavishnu/tls/client.crt"
  tls_key_path: "/etc/mahavishnu/tls/client.key"
  tls_ca_path: "/etc/mahavishnu/tls/ca.crt"
```

## Monitoring

### Metrics

- `oneiric_adapter_queries_total` - Total adapter queries
- `oneiric_adapter_query_duration_seconds` - Query duration
- `oneiric_adapter_health_checks_total` - Health check count
- `oneiric_cache_hits_total` - Cache hit rate
- `oneiric_cache_misses_total` - Cache miss rate

### Health Checks

```python
async def health_check() -> dict[str, Any]:
    """Health check for Oneiric MCP integration."""
    client = get_oneiric_client()

    try:
        # Test connection
        adapters = await client.list_adapters(limit=1)

        return {
            "status": "healthy",
            "oneiric_mcp_connected": True,
            "adapter_count": len(adapters),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "oneiric_mcp_connected": False,
            "error": str(e),
        }
```

## Example Workflows

### Workflow 1: Dynamic Storage Selection

```yaml
name: "backup-with-dynamic-storage"
description: "Backup repositories with dynamically selected storage"

steps:
  - name: "find-storage"
    tool: "oneiric_list_adapters"
    params:
      domain: "adapter"
      category: "storage"
      healthy_only: true

  - name: "select-s3"
    tool: "oneiric_get_adapter"
    params:
      adapter_id: "${steps.find-storage.results[?provider=='s3'].adapter_id}"

  - name: "verify-health"
    tool: "oneiric_check_health"
    params:
      adapter_id: "${steps.select-s3.adapter_id}"

  - name: "backup-repos"
    tool: "coord_backup_repositories"
    params:
      storage_adapter: "${steps.select-s3}"
      repos: "${input.repos}"
```

### Workflow 2: Orchestration Adapter Resolution

```yaml
name: "execute-with-prefect"
description: "Execute workflow using Prefect orchestration"

steps:
  - name: "resolve-prefect"
    tool: "oneiric_resolve_adapter"
    params:
      domain: "adapter"
      category: "orchestration"
      provider: "prefect"

  - name: "verify-health"
    tool: "oneiric_check_health"
    params:
      adapter_id: "${steps.resolve-prefect.adapter_id}"

  - name: "execute-flow"
    tool: "worker_execute_flow"
    params:
      adapter: "${steps.resolve-prefect}"
      flow_def: "${input.flow}"
```

## Implementation Checklist

### Phase 1: Core Integration (P0)

- [ ] Create `OneiricMCPClient` class
- [ ] Add Oneiric MCP configuration to `MahavishnuConfig`
- [ ] Implement gRPC channel management
- [ ] Add connection health checks
- [ ] Implement caching layer
- [ ] Add unit tests
- [ ] Add integration tests

### Phase 2: MCP Tools (P0)

- [ ] Create `oneiric_list_adapters` tool
- [ ] Create `oneiric_resolve_adapter` tool
- [ ] Create `oneiric_check_health` tool
- [ ] Create `oneiric_get_adapter` tool
- [ ] Add tool tests
- [ ] Update MCP tools documentation

### Phase 3: Workflow Integration (P1)

- [ ] Add adapter requirements to workflow schema
- [ ] Implement adapter resolution in workflow executor
- [ ] Add adapter health monitoring
- [ ] Implement circuit breaker pattern
- [ ] Add workflow tests

### Phase 4: Production Hardening (P2)

- [ ] Implement TLS/mTLS support
- [ ] Add JWT authentication
- [ ] Add comprehensive monitoring
- [ ] Add performance metrics
- [ ] Add rate limiting
- [ ] Add security tests
- [ ] Update deployment documentation

## Success Criteria

1. **Functional**: Mahavishnu can query and resolve adapters from Oneiric MCP
1. **Reliable**: Graceful fallback when Oneiric MCP is unavailable
1. **Performant**: \<100ms for cached adapter queries, \<500ms for uncached
1. **Secure**: JWT authentication and TLS in production
1. **Observable**: Full metrics and logging for integration health

## References

- Oneiric MCP: `/Users/les/Projects/oneiric-mcp`
- Oneiric gRPC Schema: `oneiric_mcp/grpc/registry_pb2.py`
- Mahavishni Architecture: `ARCHITECTURE.md`
- MCP Tools Reference: `docs/MCP_TOOLS_REFERENCE.md`
