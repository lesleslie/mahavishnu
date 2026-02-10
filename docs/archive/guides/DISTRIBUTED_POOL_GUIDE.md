# Distributed Computation Pool Guide

## Overview

The Distributed Computation Pool integration enables coordinating computation across multiple Mahavishnu instances and pool types, providing:

- **Multi-pool coordination** - Manage pools across the ecosystem
- **Smart routing strategies** - 5 routing strategies for optimal task placement
- **Task distribution** - Map-reduce pattern support for parallel processing
- **Health monitoring** - Automatic health checks and fault tolerance
- **Auto-discovery** - Automatic pool discovery from ecosystem endpoints

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Distributed Pool System                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐     ┌──────────────────┐                 │
│  │ PoolRegistry │◄────┤ HealthMonitor    │                 │
│  │              │     │                  │                 │
│  │ - Track      │     │ - Periodic checks│                 │
│  │ - Discover   │     │ - Status updates │                 │
│  │ - Query      │     └──────────────────┘                 │
│  └──────┬───────┘                                            │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────┐                   │
│  │   DistributedTaskExecutor             │                   │
│  │                                      │                   │
│  │  - Find capable pools                │                   │
│  │  - Select by strategy                │                   │
│  │  - Submit & monitor                  │                   │
│  └──────────────────┬───────────────────┘                   │
│                     │                                        │
│                     ▼                                        │
│  ┌──────────────────────────────────────┐                   │
│  │   TaskDistributor (Map-Reduce)       │                   │
│  │                                      │                   │
│  │  - Broadcast to pools                │                   │
│  │  - Aggregate results                 │                   │
│  └──────────────────────────────────────┘                   │
│                     │                                        │
│                     ▼                                        │
│  ┌──────────────────────────────────────┐                   │
│  │         Pool Endpoints                │                   │
│  │  ┌─────────┐ ┌─────────┐ ┌────────┐ │                   │
│  │  │Mahavishnu│ │SessionB │ │K8s Pool│ │                   │
│  │  │  Pool   │ │ uddy    │ │        │ │                   │
│  │  └─────────┘ └─────────┘ └────────┘ │                   │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. PoolRegistry

Central registry for tracking all pools in the ecosystem.

```python
from mahavishnu.integrations.distributed_pool import PoolRegistry, PoolDescriptor

# Initialize registry
registry = PoolRegistry(
    discovery_endpoints=[
        "http://localhost:8000",
        "http://localhost:8001",
    ]
)

# Register a pool
descriptor = PoolDescriptor(
    name="local-pool",
    pool_type="mahavishnu",
    endpoint="http://localhost:8000",
    capabilities=["python", "analysis", "ml"],
    max_workers=10,
    current_workers=3,
    queue_size=5,
    health_status=HealthStatus.HEALTHY,
    region="us-east-1",
)
await registry.register_pool(descriptor)

# Auto-discover pools
await registry.discover_pools()

# Query pools
all_pools = registry.get_all_pools()
active_pools = registry.get_active_pools()
python_pools = registry.find_pools_by_capability("python")
east_pools = registry.find_pools_by_region("us-east-1")

# Get pool status
pool_status = await registry.get_pool_status("local-pool")

# Registry statistics
stats = registry.get_registry_stats()
print(f"Total pools: {stats['total_pools']}")
print(f"Active pools: {stats['active_pools']}")
```

**Key Features:**
- Pool registration and discovery
- Capability-based lookup
- Region-based filtering
- Health status tracking
- Task affinity management

### 2. DistributedTaskExecutor

Orchestrates task execution across pools with smart routing.

```python
from mahavishnu.integrations.distributed_pool import (
    DistributedTaskExecutor,
    DistributedTask,
    RoutingStrategy,
)

# Initialize executor
executor = DistributedTaskExecutor(registry=registry)

# Create task
task = DistributedTask(
    task_type="compute",
    payload={"prompt": "Analyze this data", "data": [...]},
    required_capabilities=["python", "analysis"],
    routing_strategy=RoutingStrategy.LEAST_LOADED,
    timeout=300,  # seconds
    priority=5,
    metadata={"region": "us-east-1"},
)

# Execute task with specific strategy
result = await executor.execute_task(
    task,
    strategy=RoutingStrategy.LEAST_LOADED
)

# Check result
if result.status == TaskStatus.COMPLETED:
    print(f"Result: {result.output}")
    print(f"Duration: {result.duration}s")
    print(f"Pool: {result.pool_name}")
else:
    print(f"Error: {result.error}")

# Get task status later
status = await executor.get_task_status(task.task_id)

# Cancel active task
cancelled = await executor.cancel_task(task.task_id)
```

**Routing Strategies:**

1. **LEAST_LOADED** (default)
   - Routes to pool with lowest load factor
   - Best for: Load balancing, unpredictable workloads
   - Formula: `load_factor = current_workers / max_workers`

2. **ROUND_ROBIN**
   - Distributes tasks evenly across pools
   - Best for: Fair distribution, similar capacity pools

3. **CAPABILITY_BASED**
   - Routes to pool with most matching capabilities
   - Best for: Specialized workloads, heterogeneous pools

4. **REGION_AWARE**
   - Routes to pool in same region as task
   - Best for: Latency-sensitive tasks, geo-distributed pools
   - Falls back to least loaded if no regional match

5. **AFFINITY**
   - Routes to pool that handled similar task before
   - Best for: Caching benefits, stateful workloads
   - Falls back to least loaded if no affinity

### 3. TaskDistributor

Distributes tasks across multiple pools for parallel processing (map-reduce pattern).

```python
from mahavishnu.integrations.distributed_pool import TaskDistributor

# Initialize distributor
distributor = TaskDistributor(
    executor=executor,
    max_parallel_tasks=10,
)

# Distribute task across specific pools
task = DistributedTask(
    task_type="analyze",
    payload={"data": "large_dataset"},
)

pools = registry.get_active_pools()[:3]  # Use first 3 pools
results = await distributor.distribute_task(
    task,
    pools=pools,
    aggregation_strategy="first_success"  # or "all_success", "majority"
)

# Process results
for result in results:
    print(f"Pool {result.pool_name}: {result.status}")

# Broadcast to all active pools
all_results = await distributor.broadcast_task(task)
for pool_name, result in all_results.items():
    print(f"{pool_name}: {result.status}")
```

**Aggregation Strategies:**

- **first_success**: Return on first successful result (fastest)
- **all_success**: Wait for all pools to complete (comprehensive)
- **majority**: Return majority result (fault tolerance)

### 4. PoolHealthMonitor

Monitors pool health and automatically updates registry.

```python
from mahavishnu.integrations.distributed_pool import PoolHealthMonitor

# Initialize monitor
monitor = PoolHealthMonitor(
    registry=registry,
    check_interval=30.0,  # seconds
    timeout=10.0,  # per pool
)

# Start periodic monitoring
await monitor.start()

# Check all pools once
health_status = await monitor.check_all_pools()
for pool_name, health in health_status.items():
    print(f"{pool_name}: {health.status.value} ({health.response_time}ms)")

# Get health history for specific pool
history = monitor.get_pool_history("local-pool")
for health in history[-10:]:  # Last 10 checks
    print(f"{health.last_check}: {health.status.value}")

# Stop monitoring
await monitor.stop()
```

**Health Monitoring Features:**
- Periodic health checks (configurable interval)
- Response time tracking
- Automatic status updates
- Health history (last 100 checks)
- Unhealthy pool alerts via message bus

## Quick Start

### Basic Setup

```python
from mahavishnu.integrations.distributed_pool import create_distributed_pool_system

# Create complete system with auto-discovery
registry, executor, monitor = await create_distributed_pool_system(
    discovery_endpoints=[
        "http://localhost:8000",
        "http://localhost:8001",
    ],
    health_check_interval=30.0,
)

# Start health monitoring
await monitor.start()

# System ready for task execution
```

### Execute Simple Task

```python
from mahavishnu.integrations.distributed_pool import DistributedTask, RoutingStrategy

# Create task
task = DistributedTask(
    task_type="compute",
    payload={"prompt": "Write Python code to analyze data"},
    required_capabilities=["python"],
)

# Execute with least-loaded routing
result = await executor.execute_task(task, RoutingStrategy.LEAST_LOADED)

if result.status == TaskStatus.COMPLETED:
    print(f"Success: {result.output}")
else:
    print(f"Failed: {result.error}")
```

### Parallel Processing

```python
from mahavishnu.integrations.distributed_pool import TaskDistributor

# Create distributor
distributor = TaskDistributor(executor=executor)

# Create large task
task = DistributedTask(
    task_type="process",
    payload={"data": "large_dataset"},
)

# Distribute across all pools
results = await distributor.broadcast_task(task)

# Aggregate results
successful = sum(1 for r in results.values() if r.status == TaskStatus.COMPLETED)
print(f"Completed on {successful}/{len(results)} pools")
```

## API Reference

### Models

#### PoolDescriptor

```python
class PoolDescriptor(BaseModel):
    name: str                              # Unique pool name
    pool_type: str                         # "mahavishnu", "session_buddy", "kubernetes"
    endpoint: str                          # API endpoint URL
    capabilities: list[str]                # Pool capabilities
    max_workers: int                       # Maximum workers
    current_workers: int                   # Current active workers
    queue_size: int                        # Current queue size
    health_status: HealthStatus            # Pool health
    region: str | None                     # Geographic region
    metadata: dict[str, Any]               # Additional metadata

    @property
    def load_factor(self) -> float: ...    # Worker utilization (0.0-1.0)

    @property
    def is_available(self) -> bool: ...    # Can pool accept tasks?

    @property
    def utilization(self) -> str: ...      # "30.0% (3/10)"
```

#### DistributedTask

```python
class DistributedTask(BaseModel):
    task_id: str                           # Auto-generated UUID
    task_type: str                         # "compute", "analyze", etc.
    payload: dict[str, Any]                # Task data
    required_capabilities: list[str]       # Required capabilities
    routing_strategy: RoutingStrategy      # Routing preference
    timeout: int                           # Timeout in seconds (1-3600)
    priority: int                          # Priority (0-100)
    metadata: dict[str, Any]               # Additional data
```

#### DistributedTaskResult

```python
class DistributedTaskResult(BaseModel):
    task_id: str                           # Task identifier
    pool_name: str                         # Executing pool
    status: TaskStatus                     # Execution status
    output: dict[str, Any] | None          # Result data
    error: str | None                      # Error message
    duration: float                        # Execution time (seconds)
    metadata: dict[str, Any]               # Additional data
```

### Enums

#### HealthStatus

```python
class HealthStatus(str, Enum):
    HEALTHY = "healthy"                    # Fully operational
    DEGRADED = "degraded"                  # Reduced capacity
    UNAVAILABLE = "unavailable"            # Not accessible
```

#### TaskStatus

```python
class TaskStatus(str, Enum):
    PENDING = "pending"                    # Waiting to execute
    RUNNING = "running"                    # Currently executing
    COMPLETED = "completed"                # Success
    FAILED = "failed"                      # Execution failed
    TIMEOUT = "timeout"                    # Timed out
    CANCELLED = "cancelled"                # Cancelled by user
```

#### RoutingStrategy

```python
class RoutingStrategy(Enum):
    LEAST_LOADED = "least_loaded"          # Lowest utilization
    ROUND_ROBIN = "round_robin"            # Even distribution
    CAPABILITY_BASED = "capability_based"  # Most capabilities
    REGION_AWARE = "region_aware"          # Same region
    AFFINITY = "affinity"                  # Previous pool
```

## Configuration

### Environment Variables

```bash
# Pool configuration
export MAHAVISHNU_POOLS__ENABLED=true
export MAHAVISHNU_POOLS__DEFAULT_TYPE=mahavishnu
export MAHAVISHNU_POOLS__ROUTING_STRATEGY=least_loaded
export MAHAVISHNU_POOLS__MIN_WORKERS=1
export MAHAVISHNU_POOLS__MAX_WORKERS=10

# Memory aggregation
export MAHAVISHNU_POOLS__MEMORY_AGGREGATION_ENABLED=true
export MAHAVISHNU_POOLS__MEMORY_SYNC_INTERVAL=60

# Service endpoints
export MAHAVISHNU_POOLS__SESSION_BUDDY_URL=http://localhost:8678/mcp
export MAHAVISHNU_POOLS__AKOSHA_URL=http://localhost:8682/mcp
```

### YAML Configuration

```yaml
# settings/mahavishnu.yaml
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"
  min_workers: 1
  max_workers: 10

  memory_aggregation_enabled: true
  memory_sync_interval: 60

  session_buddy_url: "http://localhost:8678/mcp"
  akosha_url: "http://localhost:8682/mcp"
```

## Performance

### Benchmarks

- **Task routing**: <100ms (O(log n) heap-based)
- **Task submission**: <200ms (HTTP overhead)
- **Health checks**: 10s concurrent for 100 pools
- **Task distribution**: 500ms for 10 pools (parallel)
- **Throughput**: 1000+ tasks/hour per pool

### Optimization Tips

1. **Use appropriate routing strategy**
   - LEAST_LOADED for general workloads
   - CAPABILITY_BASED for specialized tasks
   - REGION_AWARE for latency-sensitive tasks

2. **Enable health monitoring**
   - Prevents routing to unhealthy pools
   - Automatic fault tolerance

3. **Use task distribution wisely**
   - Limit parallel tasks to avoid overwhelming pools
   - Choose aggregation strategy based on requirements

4. **Monitor pool utilization**
   - Scale pools before hitting capacity
   - Use load_factor to identify bottlenecks

## Fault Tolerance

### Automatic Recovery

```python
# Unhealthy pools automatically excluded
pool.health_status = HealthStatus.UNAVAILABLE
# Pool removed from active_pools automatically

# Failed tasks can be retried
result = await executor.execute_task(task)
if result.status == TaskStatus.FAILED:
    # Retry with different pool (affinity cleared)
    result = await executor.execute_task(task)
```

### Circuit Breaker Pattern

```python
# Pool marked as degraded after failures
# Tasks routed to degraded pool only if no healthy pools available
# Automatic recovery after successful health check
```

### Timeout Handling

```python
# Tasks timeout automatically
task = DistributedTask(
    task_type="compute",
    payload={...},
    timeout=300,  # 5 minutes
)
result = await executor.execute_task(task)
# Returns with status=TaskStatus.TIMEOUT after 300s
```

## Monitoring

### Metrics

```python
# Registry statistics
stats = registry.get_registry_stats()
print(f"Total pools: {stats['total_pools']}")
print(f"Active pools: {stats['active_pools']}")
print(f"Pool types: {stats['pool_types']}")
print(f"Capabilities: {stats['capabilities']}")

# Executor statistics
stats = executor.get_executor_stats()
print(f"Active tasks: {stats['active_tasks']}")
print(f"Completed tasks: {stats['completed_tasks']}")
print(f"Status breakdown: {stats['task_status_breakdown']}")

# Monitor statistics
stats = monitor.get_monitor_stats()
print(f"Check interval: {stats['check_interval']}s")
print(f"Pools monitored: {stats['pools_monitored']}")
print(f"Total checks: {stats['total_health_checks']}")
```

### Health History

```python
# Get health history for pool
history = monitor.get_pool_history("local-pool")

# Analyze trends
recent = history[-10:]  # Last 10 checks
avg_response_time = sum(h.response_time for h in recent) / len(recent)
unhealthy_count = sum(1 for h in recent if h.status != HealthStatus.HEALTHY)

print(f"Avg response time: {avg_response_time:.2f}ms")
print(f"Unhealthy checks: {unhealthy_count}/{len(recent)}")
```

## Best Practices

### 1. Pool Registration

```python
# Register pools with detailed metadata
descriptor = PoolDescriptor(
    name="production-pool-1",
    pool_type="mahavishnu",
    endpoint="http://prod-pool-1:8000",
    capabilities=["python", "ml", "gpu"],
    max_workers=20,
    region="us-east-1",
    metadata={
        "environment": "production",
        "cost_tier": "high",
        "gpu_enabled": True,
    },
)
await registry.register_pool(descriptor)
```

### 2. Task Design

```python
# Design tasks with clear requirements
task = DistributedTask(
    task_type="ml_training",
    payload={
        "model": "transformer",
        "dataset": "s3://bucket/data",
        "epochs": 100,
    },
    required_capabilities=["python", "ml", "gpu"],
    routing_strategy=RoutingStrategy.CAPABILITY_BASED,
    timeout=3600,  # 1 hour for training
    priority=10,  # High priority
    metadata={
        "cost_limit": 100.0,
        "checkpoint_interval": 10,
    },
)
```

### 3. Error Handling

```python
# Always check task status
result = await executor.execute_task(task)

match result.status:
    case TaskStatus.COMPLETED:
        process_result(result.output)
    case TaskStatus.FAILED:
        log_error(result.error)
        # Retry with different strategy
        result = await executor.execute_task(
            task,
            strategy=RoutingStrategy.ROUND_ROBIN
        )
    case TaskStatus.TIMEOUT:
        log_timeout(result.task_id)
        # Increase timeout and retry
        task.timeout *= 2
    case TaskStatus.CANCELLED:
        log_cancellation(result.task_id)
```

### 4. Resource Management

```python
# Always cleanup when done
try:
    # Use system
    await monitor.start()

    # Execute tasks
    ...

finally:
    # Cleanup
    await monitor.stop()
    await executor.close()
```

## Troubleshooting

### Pool Discovery Issues

```python
# Check discovery endpoints
endpoints = ["http://localhost:8000", "http://localhost:8001"]
registry = PoolRegistry(discovery_endpoints=endpoints)

# Verify pools registered
await registry.discover_pools()
print(f"Discovered {len(registry.pools)} pools")

# Check pool endpoints are accessible
for pool in registry.get_all_pools():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{pool.endpoint}/health")
            print(f"{pool.name}: {response.status_code}")
    except Exception as e:
        print(f"{pool.name}: Error - {e}")
```

### Task Execution Failures

```python
# Check pool capabilities
task = DistributedTask(
    task_type="compute",
    payload={...},
    required_capabilities=["python", "specialized-lib"],
)

# Verify capable pools exist
capable = await executor._find_capable_pools(task)
print(f"Capable pools: {len(capable)}")

# Check pool health
for pool in capable:
    status = await registry.get_pool_status(pool.name)
    print(f"{pool.name}: {status.health_status}, {status.utilization}")
```

### Performance Issues

```python
# Monitor pool load factors
for pool in registry.get_all_pools():
    print(f"{pool.name}: load_factor={pool.load_factor:.2f}")

# Check for bottlenecks
overloaded = [p for p in registry.get_all_pools() if p.load_factor > 0.8]
if overloaded:
    print(f"Overloaded pools: {[p.name for p in overloaded]}")
    # Consider scaling or adding more pools
```

## Testing

```python
import pytest
from mahavishnu.integrations.distributed_pool import *

@pytest.mark.asyncio
async def test_task_execution():
    # Create test system
    registry = PoolRegistry()
    executor = DistributedTaskExecutor(registry=registry)

    # Register test pool
    pool = PoolDescriptor(
        name="test-pool",
        pool_type="mahavishnu",
        endpoint="http://localhost:8000",
        capabilities=["python"],
    )
    await registry.register_pool(pool)

    # Create task
    task = DistributedTask(
        task_type="compute",
        payload={"prompt": "Test"},
        required_capabilities=["python"],
    )

    # Mock HTTP client
    with patch("httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": task.task_id,
            "status": "completed",
            "output": {"result": "success"},
        }
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_response
        )

        # Execute task
        result = await executor.execute_task(task)

        # Verify
        assert result.status == TaskStatus.COMPLETED
        assert result.output["result"] == "success"
```

## Examples

See `/examples/distributed_pool_examples.py` for complete examples:
- Basic task execution
- Parallel processing
- Health monitoring
- Fault tolerance
- Performance optimization

## Further Reading

- [Pool Architecture](/docs/POOL_ARCHITECTURE.md) - Complete pool architecture guide
- [MCP Tools Specification](/docs/MCP_TOOLS_SPECIFICATION.md) - Pool MCP tool reference
- [Integration Tests](/tests/integration/test_distributed_pool.py) - Test examples
