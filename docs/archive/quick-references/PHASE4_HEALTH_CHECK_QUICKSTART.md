# Health Check System - Quick Start Guide

## Import

```python
from mahavishnu.health import (
    LivenessProbe,
    ReadinessProbe,
    ComponentHealthChecker,
    HealthStatus,
    LivenessStatus,
    ReadinessStatus,
    create_health_app,
)
from mahavishnu.core.app import MahavishnuApp
```

## Basic Usage

### 1. Liveness Check

```python
app = MahavishnuApp()
probe = LivenessProbe(app)

result = await probe.check()
print(result.alive)  # True or False
print(result.message)
print(result.details)
```

### 2. Readiness Check

```python
probe = ReadinessProbe(app)

result = await probe.check()
print(result.ready)  # True or False
print(result.checks)  # Dict of individual checks
print(result.message)
```

### 3. Component Health Check

```python
checker = ComponentHealthChecker(app)

# Check all components
report = await checker.check_all_components()
print(report.overall_status)  # HealthStatus enum
print(report.degraded_mode)  # True or False
print(report.summary)  # Dict with counts
print(report.recommendations)  # List of recommendations

# Check specific adapter
adapter_health = await checker.check_adapter("llamaindex")
print(adapter_health.status)  # HealthStatus enum
print(adapter_health.message)
print(adapter_health.details)

# Check specific pool
pool_health = await checker.check_pool("pool_abc123")
print(pool_health.status)
print(pool_health.message)
```

## HTTP Endpoints

### Start Health Server

```python
from datetime import UTC, datetime

app = MahavishnuApp()
startup_time = datetime.now(UTC)

# Create health app
health_app = create_health_app(
    server_name="mahavishnu",
    startup_time=startup_time,
    app=app,  # Optional: pass for deep health checks
)

# Run with uvicorn
import uvicorn
await uvicorn.run(health_app, host="0.0.0.0", port=8080)
```

### Endpoints

```bash
# Liveness probe
curl http://localhost:8080/health

# Readiness probe
curl http://localhost:8080/ready

# Component health
curl http://localhost:8080/health/components

# Metrics
curl http://localhost:8080/metrics

# API info
curl http://localhost:8080/
```

## Health Status Values

### HealthStatus
- `HealthStatus.HEALTHY` - Fully operational
- `HealthStatus.DEGRADED` - Operational with reduced capacity
- `HealthStatus.UNHEALTHY` - Not operational

### LivenessStatus
- `LivenessStatus.ALIVE` - System is alive
- `LivenessStatus.DEAD` - System appears dead

### ReadinessStatus
- `ReadinessStatus.READY` - Ready to accept traffic
- `ReadinessStatus.NOT_READY` - Not ready to accept traffic

## Configuration

### Liveness Probe Thresholds

```python
probe = LivenessProbe(
    app=app,
    max_active_workflows=100,      # Max workflows before stuck
    memory_threshold_percent=90,   # Memory threshold (0-100)
    heartbeat_timeout_seconds=300, # Worker heartbeat timeout
)
```

## Result Methods

All health check results support:

```python
# Convert to dict (JSON serializable)
result_dict = result.to_dict()

# Check if healthy (includes degraded)
is_healthy = result.is_healthy()
```

## Error Handling

```python
try:
    result = await probe.check()
    if not result.alive:
        print(f"System unhealthy: {result.message}")
        print(f"Error: {result.error}")
        print(f"Details: {result.details}")
except Exception as e:
    print(f"Health check failed: {e}")
```

## Testing

```python
# Run tests
pytest tests/unit/test_health.py -v

# Run specific test
pytest tests/unit/test_health.py::TestHealthEndpoint -v
```

## Documentation

- Full Guide: `/Users/les/Projects/mahavishnu/docs/PHASE4_HEALTH_CHECKS.md`
- Implementation: `/Users/les/Projects/mahavishnu/mahavishnu/health.py`
- Tests: `/Users/les/Projects/mahavishnu/tests/unit/test_health.py`
