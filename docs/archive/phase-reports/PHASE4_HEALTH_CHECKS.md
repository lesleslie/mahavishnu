# Health Check System - Phase 4 Documentation

## Overview

The Mahavishnu health check system provides comprehensive production-ready health monitoring for multi-agent orchestration. It implements Kubernetes-compatible liveness and readiness probes, deep component health checks, degraded mode detection, and circuit breaker integration.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Health Check System                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────┐ │
│  │ LivenessProbe    │  │ ReadinessProbe   │  │ Component  │ │
│  │                  │  │                  │  │ Health      │ │
│  │ • Deadlock detect│  │ • Adapter init   │  │ Checker     │ │
│  │ • Memory check   │  │ • Pool connect   │  │             │ │
│  │ • Event loop     │  │ • OpenSearch     │  │ • Adapters  │ │
│  │ • Worker heartbeat│  │ • MCP servers    │  │ • Pools     │ │
│  └──────────────────┘  └──────────────────┘  │ • MCP       │ │
│                                               │ • Circuit   │ │
│                                               │   breakers  │ │
│                                               └────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. LivenessProbe

Detects deadlocks, hangs, and crashes.

**Checks:**
- Event loop responsiveness (asyncio timeout test)
- Active workflow count (detect stuck workflows)
- Memory usage (via psutil)
- Worker heartbeat (if workers enabled)

**Example:**
```python
from mahavishnu.health import LivenessProbe
from mahavishnu.core.app import MahavishnuApp

app = MahavishnuApp()
probe = LivenessProbe(
    app,
    max_active_workflows=100,
    memory_threshold_percent=90,
    heartbeat_timeout_seconds=300,
)

result = await probe.check()
if result.alive:
    print("System is alive")
else:
    print(f"System appears dead: {result.message}")
    print(f"Details: {result.details}")
```

**Liveness Result:**
```python
@dataclass
class LivenessResult:
    alive: bool
    status: LivenessStatus  # ALIVE or DEAD
    message: str
    timestamp: datetime
    details: dict[str, Any]
```

### 2. ReadinessProbe

Checks if the system can accept traffic.

**Checks:**
- Adapter initialization (at least one adapter must be ready)
- Pool connectivity (if pools enabled)
- OpenSearch connection (if configured)
- MCP server connections (if configured)
- Configuration validation

**Example:**
```python
from mahavishnu.health import ReadinessProbe

probe = ReadinessProbe(app)
result = await probe.check()

if result.ready:
    print("System is ready to accept traffic")
else:
    print(f"System not ready: {result.message}")
    print(f"Failed checks: {result.checks}")
```

**Readiness Result:**
```python
@dataclass
class ReadinessResult:
    ready: bool
    status: ReadinessStatus  # READY or NOT_READY
    message: str
    timestamp: datetime
    checks: dict[str, bool]  # Individual component checks
    details: dict[str, Any]
```

### 3. ComponentHealthChecker

Deep health checks for individual system components.

**Component Checks:**
- Individual adapters (LlamaIndex, Prefect, Agno)
- Pool status (MahavishnuPool, SessionBuddyPool, KubernetesPool)
- MCP server connections
- External dependencies (Redis, PostgreSQL if configured)
- Circuit breaker status
- Workflow state manager

**Example:**
```python
from mahavishnu.health import ComponentHealthChecker

checker = ComponentHealthChecker(app)

# Check all components
report = await checker.check_all_components()
print(f"Overall status: {report.overall_status}")
print(f"Degraded mode: {report.degraded_mode}")
print(f"Summary: {report.summary}")
print(f"Recommendations: {report.recommendations}")

# Check specific adapter
adapter_health = await checker.check_adapter("llamaindex")
print(f"LlamaIndex: {adapter_health.status}")
print(f"Details: {adapter_health.details}")

# Check specific pool
pool_health = await checker.check_pool("pool_abc123")
print(f"Pool status: {pool_health.status}")
```

**Component Health Report:**
```python
@dataclass
class ComponentHealthReport:
    overall_status: HealthStatus  # HEALTHY, DEGRADED, UNHEALTHY
    timestamp: datetime
    components: dict[str, HealthCheckResult]
    summary: dict[str, int]  # total, healthy, degraded, unhealthy
    degraded_mode: bool
    recommendations: list[str]
```

## Health Status Levels

### HealthStatus

- **HEALTHY**: Component is fully operational
- **DEGRADED**: Component is operational but with reduced capacity/performance
- **UNHEALTHY**: Component is not operational or failing

### LivenessStatus

- **ALIVE**: System is alive and responsive
- **DEAD**: System appears dead (deadlock, hang, or crash)

### ReadinessStatus

- **READY**: System is ready to accept traffic
- **NOT_READY**: System is not ready to accept traffic

## HTTP Endpoints

The health check system provides FastAPI endpoints for HTTP monitoring:

### Endpoint: `/health`

Basic health check (liveness probe).

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-02-05T12:34:56.789Z",
  "uptime_seconds": 1234.56
}
```

**HTTP Status Codes:**
- 200: System is alive
- 503: System appears dead

### Endpoint: `/ready`

Readiness probe.

**Response:**
```json
{
  "ready": true,
  "timestamp": "2025-02-05T12:34:56.789Z",
  "checks": {
    "adapters": true,
    "pools": true,
    "opensearch": true,
    "mcp_servers": true,
    "configuration": true
  }
}
```

**HTTP Status Codes:**
- 200: System is ready
- 503: System is not ready

### Endpoint: `/health/components`

Deep component health check.

**Response:**
```json
{
  "overall_status": "healthy",
  "timestamp": "2025-02-05T12:34:56.789Z",
  "components": {
    "adapter_llamaindex": {
      "status": "healthy",
      "message": "Adapter 'llamaindex' is initialized",
      "component": "llamaindex",
      "timestamp": "2025-02-05T12:34:56.789Z",
      "details": {...}
    },
    "pool_local": {
      "status": "healthy",
      "message": "Pool 'local' is active with 5 workers",
      "component": "local",
      "timestamp": "2025-02-05T12:34:56.789Z",
      "details": {...}
    },
    "circuit_breaker_main": {
      "status": "healthy",
      "message": "Main circuit breaker is closed",
      "component": "main",
      "timestamp": "2025-02-05T12:34:56.789Z",
      "details": {
        "state": "closed",
        "failure_count": 0
      }
    }
  },
  "summary": {
    "total": 10,
    "healthy": 9,
    "degraded": 1,
    "unhealthy": 0
  },
  "degraded_mode": true,
  "recommendations": [
    "Monitor 1 degraded components"
  ]
}
```

### Endpoint: `/metrics`

Prometheus metrics endpoint.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-02-05T12:34:56.789Z",
  "metrics": {
    "prometheus": "# HELP mahavishnu_workflows_total Total workflows executed\n..."
  }
}
```

## Integration with Existing Components

### Circuit Breaker Integration

The health check system integrates with `CircuitBreaker` from `mahavishnu.core.resilience`:

```python
async def _check_circuit_breakers(self) -> dict[str, HealthCheckResult]:
    """Check health of circuit breakers."""
    results = {}

    # Get circuit breakers from resilience manager
    if self.app.error_recovery_manager:
        circuit_breakers = self.app.error_recovery_manager.circuit_breakers

        for name, cb in circuit_breakers.items():
            metrics = cb.get_metrics()
            state = metrics.get("state", "closed")

            # Map circuit breaker state to health status
            if state == "closed":
                status = HealthStatus.HEALTHY
            elif state == "half_open":
                status = HealthStatus.DEGRADED
            else:  # open
                status = HealthStatus.UNHEALTHY

            results[name] = HealthCheckResult(
                status=status,
                message=f"Circuit breaker '{name}' is {state}",
                component_name=name,
                details=metrics,
            )

    return results
```

### Observability Integration

The health check system uses `ObservabilityManager` from `mahavishnu.core.observability` for metrics and logging:

```python
# Log health check results
if self.app.observability:
    self.app.observability.log_info(
        f"Liveness check completed: {result.status.value}",
        attributes={
            "alive": result.alive,
            "details": result.details,
        }
    )
```

## Degraded Mode Handling

The system automatically detects degraded mode based on component health:

### Degraded Mode Thresholds

- **DEGRADED**: Any component returns DEGRADED status
- **UNHEALTHY**: Any component returns UNHEALTHY status

### Degraded Mode Detection

```python
# Calculate overall status
unhealthy_count = sum(1 for r in components.values() if r.status == HealthStatus.UNHEALTHY)
degraded_count = sum(1 for r in components.values() if r.status == HealthStatus.DEGRADED)

if unhealthy_count > 0:
    overall_status = HealthStatus.UNHEALTHY
    recommendations.append(f"Fix {unhealthy_count} unhealthy components")
elif degraded_count > 0:
    overall_status = HealthStatus.DEGRADED
    recommendations.append(f"Monitor {degraded_count} degraded components")

degraded_mode = overall_status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
```

### Graceful Degradation

When in degraded mode:
1. System continues operating with reduced capacity
2. Circuit breakers may open for failing components
2. Recommendations are generated for recovery
4. Metrics are tagged with degraded mode

## Kubernetes Integration

### Liveness Probe Configuration

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mahavishnu
spec:
  containers:
  - name: mahavishnu
    image: mahavishnu:latest
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
```

### Readiness Probe Configuration

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mahavishnu
spec:
  containers:
  - name: mahavishnu
    image: mahavishnu:latest
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 3
```

### Startup Probe Configuration

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mahavishnu
spec:
  containers:
  - name: mahavishnu
    image: mahavishnu:latest
    startupProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 0
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 30  # 30 * 5 = 150 seconds max startup time
```

## Usage Examples

### Example 1: Basic Health Check

```python
import asyncio
from mahavishnu.health import LivenessProbe, ReadinessProbe
from mahavishnu.core.app import MahavishnuApp

async def main():
    app = MahavishnuApp()

    # Check liveness
    liveness = LivenessProbe(app)
    live_result = await liveness.check()
    print(f"Liveness: {live_result.alive} - {live_result.message}")

    # Check readiness
    readiness = ReadinessProbe(app)
    ready_result = await readiness.check()
    print(f"Readiness: {ready_result.ready} - {ready_result.message}")

asyncio.run(main())
```

### Example 2: Component Health Monitoring

```python
import asyncio
from mahavishnu.health import ComponentHealthChecker
from mahavishnu.core.app import MahavishnuApp

async def main():
    app = MahavishnuApp()
    checker = ComponentHealthChecker(app)

    # Check all components
    report = await checker.check_all_components()

    print(f"Overall Status: {report.overall_status.value}")
    print(f"Degraded Mode: {report.degraded_mode}")
    print(f"\nSummary:")
    print(f"  Total: {report.summary['total']}")
    print(f"  Healthy: {report.summary['healthy']}")
    print(f"  Degraded: {report.summary['degraded']}")
    print(f"  Unhealthy: {report.summary['unhealthy']}")

    if report.recommendations:
        print(f"\nRecommendations:")
        for rec in report.recommendations:
            print(f"  - {rec}")

    # Check specific components
    for name, result in report.components.items():
        if result.status.value != "healthy":
            print(f"\n{name}: {result.status.value}")
            print(f"  Message: {result.message}")
            print(f"  Details: {result.details}")

asyncio.run(main())
```

### Example 3: HTTP Health Server

```python
import asyncio
from datetime import UTC, datetime
from mahavishnu.health import create_health_app
from mahavishnu.core.app import MahavishnuApp

async def main():
    app = MahavishnuApp()
    startup_time = datetime.now(UTC)

    # Create health check FastAPI app
    health_app = create_health_app(
        server_name="mahavishnu",
        startup_time=startup_time,
        app=app,  # Pass app for deep health checks
    )

    # Run health server
    import uvicorn
    await uvicorn.run(health_app, host="0.0.0.0", port=8080)

asyncio.run(main())
```

## Configuration

### Liveness Probe Configuration

```python
from mahavishnu.health import LivenessProbe

# Custom thresholds
probe = LivenessProbe(
    app=app,
    max_active_workflows=100,      # Max workflows before considering stuck
    memory_threshold_percent=90,   # Memory usage threshold (0-100)
    heartbeat_timeout_seconds=300, # Worker heartbeat timeout
)
```

### Health Check Server Configuration

```python
from mahavishnu.health import create_health_app, run_health_server

# Create custom health server
health_app = create_health_app(
    server_name="mahavishnu-prod",
    startup_time=datetime.now(UTC),
    app=app,  # Optional: pass MahavishnuApp for deep checks
)

# Run server
await run_health_server(
    host="0.0.0.0",
    port=8080,
    server_name="mahavishnu-prod",
    startup_time=datetime.now(UTC),
    app=app,
)
```

## Testing

### Unit Tests

```bash
# Run health check tests
pytest tests/unit/test_health.py -v
```

### Integration Tests

```python
import pytest
from mahavishnu.health import LivenessProbe, ReadinessProbe, ComponentHealthChecker
from mahavishnu.core.app import MahavishnuApp

@pytest.mark.asyncio
async def test_liveness_probe():
    """Test liveness probe."""
    app = MahavishnuApp()
    probe = LivenessProbe(app)

    result = await probe.check()
    assert result.alive is True
    assert result.status.value == "alive"

@pytest.mark.asyncio
async def test_readiness_probe():
    """Test readiness probe."""
    app = MahavishnuApp()
    probe = ReadinessProbe(app)

    result = await probe.check()
    assert isinstance(result.ready, bool)
    assert isinstance(result.checks, dict)

@pytest.mark.asyncio
async def test_component_health_checker():
    """Test component health checker."""
    app = MahavishnuApp()
    checker = ComponentHealthChecker(app)

    report = await checker.check_all_components()
    assert report.overall_status in ["healthy", "degraded", "unhealthy"]
    assert isinstance(report.summary, dict)
```

## Troubleshooting

### Common Issues

#### Issue: Liveness probe returns DEAD

**Symptoms:**
- `/health` endpoint returns 503
- Liveness check shows `alive=False`

**Possible Causes:**
1. Event loop deadlock
2. Memory exhaustion (>90%)
3. Too many active workflows (>100)
4. Worker heartbeat timeout

**Solutions:**
1. Check for blocking code in event loop
2. Increase memory or reduce memory_threshold_percent
3. Investigate stuck workflows
4. Check worker manager status

#### Issue: Readiness probe returns NOT_READY

**Symptoms:**
- `/ready` endpoint returns 503
- Readiness check shows `ready=False`

**Possible Causes:**
1. No adapters initialized
2. Pools not connected (if enabled)
3. OpenSearch connection failed
4. Configuration validation failed

**Solutions:**
1. Check adapter initialization in logs
2. Verify pool manager status
3. Check OpenSearch endpoint configuration
4. Validate configuration files

#### Issue: Component health shows DEGRADED

**Symptoms:**
- `/health/components` shows degraded components
- Circuit breakers in HALF_OPEN state
- Pools with no workers

**Possible Causes:**
1. Circuit breaker opened and recovering
2. Pool workers crashed or not started
3. Adapter returning degraded status

**Solutions:**
1. Wait for circuit breaker recovery
2. Restart pool workers
3. Check adapter logs for errors

## Performance Considerations

### Health Check Overhead

- **Liveness check**: ~10-50ms (event loop test + memory check)
- **Readiness check**: ~50-200ms (adapter + pool + dependency checks)
- **Component health check**: ~100-500ms (deep checks on all components)

### Optimization Tips

1. **Cache results**: Cache health check results for 5-10 seconds
2. **Parallel checks**: Run component checks in parallel
3. **Timeout enforcement**: Use timeouts for external dependency checks
4. **Selective checks**: Only check enabled components

```python
# Example: Timeout enforcement
import asyncio

async def check_with_timeout(check_func, timeout=5.0):
    """Run health check with timeout."""
    try:
        return await asyncio.wait_for(check_func(), timeout=timeout)
    except asyncio.TimeoutError:
        return HealthCheckResult(
            status=HealthStatus.UNHEALTHY,
            message="Health check timeout",
            details={"timeout_seconds": timeout},
        )
```

## Security Considerations

### Authentication

For production deployments, add authentication to health endpoints:

```python
from fastapi import HTTPException, Header, status

async def verify_auth(x_api_key: str = Header(...)):
    """Verify API key for health endpoints."""
    if x_api_key != os.getenv("HEALTH_CHECK_API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

@app.get("/health", dependencies=[Depends(verify_auth)])
async def health_check():
    ...
```

### Rate Limiting

Prevent abuse of health endpoints:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/health")
@limiter.limit("60/minute")
async def health_check(request: Request):
    ...
```

## Monitoring and Alerting

### Prometheus Metrics

```prometheus
# Health check status
mahavishnu_health_status{status="alive"} 1

# Component health status
mahavishnu_component_health_status{component="llamaindex",status="healthy"} 1
mahavishnu_component_health_status{component="pool_local",status="healthy"} 1

# Circuit breaker state
mahavishnu_circuit_breaker_state{name="main",state="closed"} 1
```

### Alert Rules

```yaml
groups:
- name: mahavishnu_health
  rules:
  - alert: MahavishnuUnhealthy
    expr: mahavishnu_health_status{status="alive"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Mahavishnu is unhealthy"
      description: "Liveness probe failed for 1 minute"

  - alert: MahavishnuComponentUnhealthy
    expr: mahavishnu_component_health_status{status="unhealthy"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Mahavishnu component is unhealthy"
      description: "Component {{ $labels.component }} is unhealthy"
```

## Conclusion

The Mahavishnu health check system provides comprehensive production-ready health monitoring with:

- **Liveness probes**: Detect deadlocks, hangs, and crashes
- **Readiness probes**: Check if system can accept traffic
- **Component health checks**: Deep health monitoring for all components
- **Degraded mode detection**: Automatic detection and handling
- **Circuit breaker integration**: Health-based circuit breaking
- **Kubernetes compatibility**: Standard HTTP endpoints for probes

For more information, see:
- `/Users/les/Projects/mahavishnu/mahavishnu/health.py` - Implementation
- `/Users/les/Projects/mahavishnu/tests/unit/test_health.py` - Unit tests
- `/Users/les/Projects/mahavishnu/docs/PHASE4_HEALTH_CHECKS.md` - This document
