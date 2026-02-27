# Health Check System Design

**Date:** 2026-02-27
**Status:** Approved
**Authors:** Claude + User collaboration
**Related:** Expert audit of mDNS/Zeroconf and Device Discovery features

---

## Executive Summary

This document defines a lightweight health check system for the Bodai ecosystem that replaces the proposed (and rejected) Device Discovery feature. The system uses on-demand health queries instead of continuous heartbeats, and leverages platform-native service discovery for production deployments.

**Key Decisions:**
- ❌ mDNS/Zeroconf: Rejected by 5/5 experts
- ❌ Device Discovery (announce/heartbeat/poll): Rejected by 5/5 experts
- ✅ Health Check Endpoints: Recommended by 5/5 experts
- ✅ Platform-native discovery: Recommended for production

---

## Problem Statement

Services in the Bodai ecosystem need to:
1. Know if their dependencies are healthy before accepting work
2. Expose health status for monitoring and orchestration
3. Work seamlessly in both localhost development and cloud production

---

## Goals

- Each MCP server exposes standard health endpoints
- Mahavishnu can wait for dependencies on startup
- Production uses platform-native discovery (Cloud Run DNS, AWS CloudMap, etc.)
- No custom registry, no heartbeats, no background tasks
- Minimal implementation complexity (~4-6 hours)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Health Check Architecture                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Each MCP Server (6 total):                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  /health  → {"status": "ok", "uptime": 3600}            │   │
│  │  /ready   → {"ready": true, "dependencies": {...}}      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Mahavishnu Startup:                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  wait_for_dependencies()                                │   │
│  │    → GET http://localhost:8678/health (Session-Buddy)   │   │
│  │    → GET http://localhost:8682/health (Akosha)          │   │
│  │    → GET http://localhost:8683/health (Dhruva)          │   │
│  │    → Retry with exponential backoff until ready         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Production Discovery:                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  grpc_host: "${AKOSHA_HOST:-localhost}"                 │   │
│  │  → Cloud Run: akosha-xxxx-uc.a.run.app                  │   │
│  │  → AWS Fargate: akosha.service.local                    │   │
│  │  → Azure Container Apps: akosha.internal.apps           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key principle:** On-demand health queries, not continuous heartbeats.

---

## Health Endpoint Specification

### `/health` - Liveness Probe

```python
# Response schema
{
    "status": "ok" | "degraded" | "unhealthy",
    "service": "mahavishnu",
    "version": "0.3.2",
    "uptime_seconds": 3600,
    "timestamp": "2026-02-27T14:00:00Z"
}
```

| Attribute | Description |
|-----------|-------------|
| **Purpose** | "Is this service running?" |
| **Called by** | Platform health checks (Cloud Run, Kubernetes, etc.) |
| **Frequency** | Every 10-30 seconds by platform |
| **Returns** | 200 if process is alive, 503 if unhealthy |

### `/ready` - Readiness Probe

```python
# Response schema
{
    "ready": true | false,
    "service": "mahavishnu",
    "dependencies": {
        "session_buddy": {"status": "ok", "latency_ms": 5},
        "akosha": {"status": "ok", "latency_ms": 3},
        "dhruva": {"status": "ok", "latency_ms": 2}
    },
    "checks": {
        "database": "ok",
        "cache": "ok"
    }
}
```

| Attribute | Description |
|-----------|-------------|
| **Purpose** | "Is this service ready to accept work?" |
| **Called by** | Load balancers, orchestrators, other services |
| **Frequency** | On-demand (startup, before routing traffic) |
| **Returns** | 200 if all dependencies reachable, 503 if not ready |

---

## Dependency Waiting Logic

### Configuration

```yaml
# settings/mahavishnu.yaml
dependencies:
  session_buddy:
    host: "${SESSION_BUDDY_HOST:-localhost}"
    port: 8678
    required: true
    timeout_seconds: 30
  akosha:
    host: "${AKOSHA_HOST:-localhost}"
    port: 8682
    required: true
    timeout_seconds: 30
  dhruva:
    host: "${DHRUVA_HOST:-localhost}"
    port: 8683
    required: false  # Optional dependency
    timeout_seconds: 10
```

### Startup Sequence

```
Mahavishnu starts
    │
    ├─► load_config()
    │
    ├─► wait_for_dependencies()
    │       │
    │       ├─► GET http://localhost:8678/health
    │       │   └─► Retry: 1s, 2s, 4s, 8s, 16s (exponential backoff)
    │       │   └─► Fail after 30s if required=true
    │       │
    │       ├─► GET http://localhost:8682/health
    │       │   └─► Same retry pattern
    │       │
    │       └─► GET http://localhost:8683/health
    │           └─► Skip if required=false and unreachable
    │
    ├─► initialize_adapters()
    │
    └─► start_mcp_server()
```

### Key Behaviors

| Behavior | Description |
|----------|-------------|
| **Required dependencies** | Block startup, fail fast if timeout exceeded |
| **Optional dependencies** | Log warning, continue startup |
| **Parallel checks** | All dependencies checked concurrently |
| **Exponential backoff** | 1s → 2s → 4s → 8s → 16s (max 16s between retries) |

---

## Implementation Components

### Files to Create/Modify

| File | Purpose | Changes |
|------|---------|---------|
| `mahavishnu/core/health.py` | New module | `HealthChecker`, `DependencyWaiter` classes |
| `mahavishnu/core/health_schemas.py` | New module | Pydantic models for `/health` and `/ready` responses |
| `mahavishnu/mcp/tools/health_tools.py` | New module | MCP tools for health endpoints |
| `mahavishnu/core/config.py` | Modify | Add `dependencies` config section |
| `mahavishnu/core/app.py` | Modify | Call `wait_for_dependencies()` on startup |
| `settings/mahavishnu.yaml` | Modify | Add dependencies configuration |

### Core Classes

```python
# mahavishnu/core/health.py

from dataclasses import dataclass

@dataclass
class DependencyConfig:
    """Configuration for a service dependency."""
    host: str
    port: int
    required: bool = True
    timeout_seconds: int = 30
    use_tls: bool = False


class HealthChecker:
    """Check health of a single service."""

    async def check(self, url: str, timeout: float = 5.0) -> HealthResult:
        """Perform health check against a single service.

        Args:
            url: Health endpoint URL
            timeout: Request timeout in seconds

        Returns:
            HealthResult with status and latency
        """
        pass


class DependencyWaiter:
    """Wait for all dependencies to become healthy."""

    async def wait_for_all(
        self,
        dependencies: dict[str, DependencyConfig]
    ) -> WaitResult:
        """Wait for all dependencies to become healthy.

        Args:
            dependencies: Map of service name to config

        Returns:
            WaitResult with success/failure status per dependency
        """
        pass


class HealthEndpoint:
    """Provide /health and /ready endpoints for this service."""

    async def liveness(self) -> HealthResponse:
        """Return liveness status for this service."""
        pass

    async def readiness(self) -> ReadyResponse:
        """Return readiness status, checking all dependencies."""
        pass
```

### MCP Tools

```python
# mahavishnu/mcp/tools/health_tools.py

from mcp import FastMCP

mcp = FastMCP("mahavishnu-health")


@mcp.tool()
async def health_check_service(service_name: str) -> dict:
    """Check health of a specific service.

    Args:
        service_name: Name of the service (e.g., "session_buddy")

    Returns:
        Health status dictionary
    """
    pass


@mcp.tool()
async def health_check_all() -> dict:
    """Check health of all known services.

    Returns:
        Dictionary with health status of all services
    """
    pass


@mcp.tool()
async def wait_for_dependency(
    service_name: str,
    timeout: int = 30
) -> dict:
    """Wait for a specific dependency to become healthy.

    Args:
        service_name: Name of the service to wait for
        timeout: Maximum wait time in seconds

    Returns:
        Result indicating success or timeout
    """
    pass
```

---

## Production Configuration

### Development (Default)

```yaml
# settings/mahavishnu.yaml
dependencies:
  session_buddy:
    host: "localhost"
    port: 8678
    required: true
  akosha:
    host: "localhost"
    port: 8682
    required: true
  dhruva:
    host: "localhost"
    port: 8683
    required: false
```

### Production Overrides

```yaml
# settings/local.yaml (gitignored) or environment variables

dependencies:
  session_buddy:
    host: "${SESSION_BUDDY_HOST}"
    port: 443
    use_tls: true
  akosha:
    host: "${AKOSHA_HOST}"
    port: 8682
  dhruva:
    host: "${DHRUVA_HOST}"
    port: 8683
```

### Cloud Provider Examples

| Provider | Service URL Pattern | Configuration |
|----------|---------------------|---------------|
| **Google Cloud Run** | `service-xxxx-uc.a.run.app` | `host: "${SERVICE_HOST}"` |
| **AWS Fargate** | `service.namespace.local:port` | CloudMap DNS |
| **Azure Container Apps** | `service.internal.region.azurecontainerapps.dev` | Built-in DNS |
| **Fly.io** | `service-name.fly.dev` | `host: "${FLY_APP_NAME}.fly.dev"` |
| **Kubernetes** | `service.namespace.svc.cluster.local` | K8s DNS |

**No code changes needed between environments** - only configuration.

---

## Error Handling

### Error Hierarchy

```python
class HealthCheckError(Exception):
    """Base error for health check failures."""
    pass


class DependencyTimeoutError(HealthCheckError):
    """Dependency did not respond within timeout."""
    pass


class DependencyUnavailableError(HealthCheckError):
    """Dependency returned unhealthy status."""
    pass


class CircularDependencyError(HealthCheckError):
    """Detected circular dependency in wait chain."""
    pass
```

### Failure Modes

| Scenario | Behavior |
|----------|----------|
| **Dependency not responding** | Retry with exponential backoff, fail after timeout |
| **Dependency returns 503** | Same as not responding - retry |
| **Dependency returns 200 but degraded** | Log warning, continue (service is up) |
| **All retries exhausted** | If `required=true`: raise `DependencyError`, abort startup |
| **Optional dependency fails** | Log warning at WARNING level, continue startup |
| **Health check timeout** | 5 second timeout per request, then retry |

---

## Testing Strategy

### Test Types

| Type | Coverage |
|------|----------|
| **Unit tests** | `HealthChecker.check()`, `DependencyWaiter.wait_for_all()` |
| **Integration tests** | Full startup sequence with mock dependencies |
| **Contract tests** | Verify `/health` and `/ready` response schemas |
| **Chaos tests** | Simulate network failures, slow responses, timeouts |

### Test Fixtures

```python
# tests/fixtures/health_fixtures.py

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def healthy_service():
    """Mock service returning 200 OK."""
    with patch("httpx.AsyncClient.get") as mock:
        mock.return_value.status_code = 200
        mock.return_value.json.return_value = {"status": "ok"}
        yield mock


@pytest.fixture
def unhealthy_service():
    """Mock service returning 503."""
    with patch("httpx.AsyncClient.get") as mock:
        mock.return_value.status_code = 503
        yield mock


@pytest.fixture
def slow_service():
    """Mock service with 10s response time."""
    with patch("httpx.AsyncClient.get") as mock:
        mock.return_value.elapsed.total_seconds.return_value = 10.0
        yield mock


@pytest.fixture
def flaky_service():
    """Mock service that fails first 3 attempts, then succeeds."""
    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise ConnectionError("Connection refused")
        response = AsyncMock()
        response.status_code = 200
        response.json.return_value = {"status": "ok"}
        return response

    with patch("httpx.AsyncClient.get", side_effect=side_effect):
        yield
```

### Example Test

```python
# tests/unit/test_health.py

import pytest
from mahavishnu.core.health import DependencyWaiter, DependencyConfig


@pytest.mark.asyncio
async def test_wait_for_dependencies_all_healthy(healthy_service):
    """Test successful wait when all dependencies are healthy."""
    waiter = DependencyWaiter()
    dependencies = {
        "session_buddy": DependencyConfig(host="localhost", port=8678),
        "akosha": DependencyConfig(host="localhost", port=8682),
    }

    result = await waiter.wait_for_all(dependencies)

    assert result.success
    assert all(r.status == "ok" for r in result.dependencies.values())


@pytest.mark.asyncio
async def test_wait_for_dependencies_timeout(unhealthy_service):
    """Test timeout when dependency is unhealthy."""
    waiter = DependencyWaiter()
    dependencies = {
        "session_buddy": DependencyConfig(
            host="localhost",
            port=8678,
            timeout_seconds=5
        ),
    }

    with pytest.raises(DependencyTimeoutError):
        await waiter.wait_for_all(dependencies)
```

---

## Implementation Checklist

- [ ] Create `mahavishnu/core/health_schemas.py` with Pydantic models
- [ ] Create `mahavishnu/core/health.py` with `HealthChecker`, `DependencyWaiter`
- [ ] Create `mahavishnu/mcp/tools/health_tools.py` with MCP tools
- [ ] Add `dependencies` section to `MahavishnuSettings` in `config.py`
- [ ] Add `wait_for_dependencies()` call in `MahavishnuApp._initialize()`
- [ ] Update `settings/mahavishnu.yaml` with dependencies config
- [ ] Add `/health` and `/ready` endpoints to MCP server
- [ ] Write unit tests for health check logic
- [ ] Write integration tests for startup sequence
- [ ] Update documentation

---

## Estimated Effort

| Task | Hours |
|------|-------|
| Core health module | 2 |
| MCP tools | 1 |
| Config changes | 0.5 |
| App integration | 0.5 |
| Testing | 2 |
| **Total** | **6 hours** |

---

## Expert Panel Summary

The following features were evaluated by 5 domain experts:

### mDNS/Zeroconf - ❌ Rejected (5/5 against)

| Expert | Concern |
|--------|---------|
| Cloud Architect | Complexity overhead outweighs benefits |
| DevOps | Cloud Run doesn't support mDNS |
| Security | Attack surface expansion, no authentication |
| Backend Dev | Doesn't work across Cloud Run instances |
| Platform Engineer | Service catalog is better investment |

### Device Discovery (push/pull) - ❌ Rejected (5/5 against)

| Expert | Concern |
|--------|---------|
| Cloud Architect | Architectural overkill for 6 services |
| DevOps | Redundant with PoolManager + Prometheus |
| Security | Identity spoofing risk, no cryptographic proof |
| Backend Dev | Race conditions, timing-dependent tests |
| Platform Engineer | Three overlapping patterns already exist |

### Health Check System - ✅ Approved (5/5 for)

All experts recommended this simpler approach using:
- `/health` and `/ready` endpoints
- `wait_for_dependencies()` on startup
- Platform-native discovery for production
- No heartbeats, no registry, no background tasks

---

## References

- `docs/analysis/OTEL_AND_DEVICE_DISCOVERY.md` - Original device discovery proposal
- `docs/adr/009-hybrid-adapter-registry.md` - Adapter discovery architecture
- `docs/ONEIRIC_MCP_INTEGRATION.md` - Oneiric gRPC client documentation
