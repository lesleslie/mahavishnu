# Pool Architecture - Multi-Pool Orchestration for Mahavishnu

## Executive Summary

The pool management architecture enables Mahavishnu to orchestrate worker tasks across multiple pool types, providing:

- **Horizontal scaling** across local, delegated, and cloud resources
- **Intelligent routing** with multiple selection strategies
- **Inter-pool communication** via async message bus
- **Unified memory aggregation** from all pools to Session-Buddy → Akosha

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Mahavishnu Orchestrator                        │
│                        (Port 8680 - MCP Server)                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    PoolManager                                    │    │
│  │  • spawn_pool(pool_type, config)                               │    │
│  │  • execute_on_pool(pool_id, task)                              │    │
│  │  • route_task(task, pool_selector)                             │    │
│  │  • aggregate_results(pool_ids)                                 │    │
│  │  • inter_pool_comm: MessageBus                                 │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                │                                        │
│           ┌────────────────────┼────────────────────┐                 │
│           ↓                    ↓                    ↓                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │ MahavishnuPool  │  │SessionBuddyPool│  │   RunPodPool    │        │
│  │   (Direct)      │  │  (Delegated)    │  │   (GPU Cloud)   │        │
│  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤        │
│  │ Wraps          │  │ Delegates to    │  │ Manages        │        │
│  │ WorkerManager  │  │ Session-Buddy   │  │ RunPod Workers │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│           │                    │                    │                 │
│           ↓                    ↓                    ↓                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │  Local Workers │  │ Session-Buddy   │  │  K8s Pods       │        │
│  │  (Qwen/Claude) │  │  Workers (3)    │  │  (Containers)   │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│                                                                         │
│  Memory Flow:                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    MemoryAggregator                             │    │
│  │  • collect_pool_memory() → Session-Buddy MCP                   │    │
│  │  • sync_to_akosha()      → Akosha MCP                         │    │
│  │  • cross_pool_search()   → Unified query                      │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
           │                                    │
           ↓                                    ↓
┌──────────────────────┐            ┌──────────────────────┐
│   Session-Buddy      │            │      Akosha          │
│   (Port 8678)        │            │   (Port 8682)        │
├──────────────────────┤            ├──────────────────────┤
│ • Pool memory        │            │ • Cross-pool         │
│ • Worker results     │            │   pattern detection │
│ • Session context    │            │ • Global analytics   │
└──────────────────────┘            └──────────────────────┘
```

## Why pool types wrap substrates, not delegate to `PoolManager.route_task`

Each pool type is a **leaf substrate wrapper**. They are peers, not children, of `PoolManager`. The pattern is:

| Pool type | Wraps | Substrate type |
|---|---|---|
| `MahavishnuPool` | `WorkerManager` | In-process worker management (CLI/PTY) |
| `SessionBuddyPool` | `CommonMCPClient` | Out-of-process MCP server (`http://localhost:8678/mcp`) |
| `RunPodPool` | `runpod_flash.Endpoint` | GPU serverless SDK |

Each pool implements the same 8 abstract methods on `BasePool` (`start`, `execute_task`, `execute_batch`, `scale`, `health_check`, `get_metrics`, `collect_memory`, `stop`) by delegating to its substrate. **`PoolManager.route_task` does not enter the picture** — it sits above all pool types, picks one pool, and calls `await pool.execute_task(task)`.

If a pool delegated `execute_task` to `PoolManager.route_task`, three problems would emerge:

1. **Circular dependency**: `PoolManager.route_task → pool.execute_task → PoolManager.route_task` (each pool type would have to hold a back-reference to `PoolManager`).
1. **Double quota enforcement**: `route_task` enforces `_QuotaState` once per dispatch. If a pool re-enters `route_task`, quota is consumed twice for one user task.
1. **Selector drift**: `route_task` may override the selector via `_apply_fitness_aware_routing` (`manager.py:703`) and `_apply_queueing_penalty`. A pool that re-enters `route_task` would get a different pool selected than itself.

### Cross-pool routing vs. in-pool dispatch

| Concern | Layer | Owner |
|---|---|---|
| "Which pool should I send this to?" | Cross-pool | `PoolManager.route_task` (selector strategies + fitness + queueing) |
| "How does the chosen pool execute the task?" | In-pool | The pool's substrate (`WorkerManager` / `CommonMCPClient` / `Endpoint`) |
| "How many calls per `CallerKind` per minute?" | Cross-pool | `PoolManager._QuotaState` (per `caller_kind`) |

Mixing layers breaks the contract. Pool types **must** stay as leaf substrate wrappers.

## What "rewrite to use `route_task` shape" would have meant

If you wanted pool types to use `route_task` semantics, you'd need a different design: `PoolManager` as the only entry point (no pool type ever sees `execute_task` from above). That collapses the architecture into a single layer — which means losing the `BasePool` contract, losing peer extensibility (you can't add a new pool type without registering it with `PoolManager`), and breaking every existing pool implementation (`SessionBuddyPool`, `RunPodPool`, `pi_pool`, `gpu_handler_pool`).

That's the architectural alternative, not a "rewrite" of one file.

## Pool Types

### 1. MahavishnuPool (Direct Management)

**Purpose**: Direct worker management by Mahavishnu

**Use Cases**:

- Local development and testing
- Low-latency task execution
- Debugging and monitoring
- CI/CD pipeline automation

**Implementation**:

- Wraps existing `WorkerManager`
- Workers run locally in Mahavishnu's process
- Supports dynamic scaling (min_workers to max_workers)

**Example**:

```python
config = PoolConfig(
    name="local-pool",
    pool_type="mahavishnu",
    min_workers=2,
    max_workers=5,
    worker_type="terminal-qwen",
)

pool_id = await pool_mgr.spawn_pool("mahavishnu", config)
result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Write code"})
```

**Architecture**:

```
┌─────────────────────────────────────┐
│         MahavishnuPool              │
│  ┌───────────────────────────────┐  │
│  │    WorkerManager (EXISTING)   │  │
│  │  • spawn_workers()            │  │
│  │  • execute_task()             │  │
│  │  • execute_batch()            │  │
│  └───────────────────────────────┘  │
│           │                          │
│           ↓                          │
│  ┌───────────────────────────────┐  │
│  │      Local Workers            │  │
│  │  • TerminalAIWorker (Qwen)    │  │
│  │  • TerminalAIWorker (Claude)  │  │
│  │  • AppleContainer/E2B microVM │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

### 2. SessionBuddyPool (Delegated Management)

**Purpose**: Delegates worker management to Session-Buddy instances

**Use Cases**:

- Distributed worker management
- Remote worker execution
- Session-Buddy memory integration
- Multi-server deployments

**Implementation**:

- Each Session-Buddy instance manages exactly 3 workers
- Communication via MCP protocol (HTTP)
- Fixed worker count (scaling requires spawning more pools)

**Example**:

```python
config = PoolConfig(
    name="delegated-pool",
    pool_type="session-buddy",
)

pool_id = await pool_mgr.spawn_pool("session-buddy", config)
result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Analyze code"})
```

**Architecture**:

```
┌─────────────────────────────────────┐
│      SessionBuddyPool              │
│  • HTTP MCP client                 │
│  • worker_spawn (3 workers)        │
│  • worker_execute                  │
└─────────────────────────────────────┘
            │ HTTP (MCP)
            ↓
┌───────────────────────┐
│  Session-Buddy MCP    │
│  (Port 8678)          │
├───────────────────────┤
│  WorkerManager        │
│  • 3 workers          │
│  • Memory storage     │
└───────────────────────┘
```

### 3. KubernetesPool — REMOVED 2026-06-23

KubernetesPool was removed as part of the serverless-only pivot. The
project now relies on managed serverless (Cloud Run) and RunPod for
cloud GPU workloads. K8s manifests remain in `mahavishnu/core/k8s_manifests.py`
for deployment documentation only; the pool implementation is gone.
├───────────────────────┤
│ Namespace: mahavishnu│
│ • Jobs │
│ • Pods │
└───────────────────────┘

````

## Pool Routing Strategies

### ROUND_ROBIN

Distributes tasks evenly across all pools in sequence.

**Best For**:

- General load balancing
- Predictable distribution
- Fair task allocation

**Example**:

```python
result = await pool_mgr.route_task(
    {"prompt": "Task"},
    pool_selector=PoolSelector.ROUND_ROBIN,
)
# Routes: pool0 → pool1 → pool2 → pool0 → ...
````

### LEAST_LOADED

Routes to pool with fewest active workers.

**Best For**:

- Optimal resource utilization
- Preventing overload
- Dynamic load balancing

**Example**:

```python
result = await pool_mgr.route_task(
    {"prompt": "Task"},
    pool_selector=PoolSelector.LEAST_LOADED,
)
# Routes to pool with lowest worker count
```

### RANDOM

Randomly selects a pool for each task.

**Best For**:

- Even distribution over time
- Simple strategy
- Avoiding routing patterns

**Example**:

```python
result = await pool_mgr.route_task(
    {"prompt": "Task"},
    pool_selector=PoolSelector.RANDOM,
)
# Routes to random pool
```

### AFFINITY

Routes to same pool for related tasks.

**Best For**:

- Task groups requiring same context
- Caching warm-up
- Stateful operations

**Example**:

```python
result = await pool_mgr.route_task(
    {"prompt": "Follow-up task"},
    pool_selector=PoolSelector.AFFINITY,
    pool_affinity="pool_abc",  # Always route to this pool
)
# Always routes to pool_abc
```

## Inter-Pool Communication

### Message Types

| Message Type | Purpose |
|-------------|---------|
| `TASK_DELEGATE` | Delegate task from one pool to another |
| `RESULT_SHARE` | Share execution result between pools |
| `STATUS_UPDATE` | Broadcast pool status |
| `HEARTBEAT` | Regular health check |
| `POOL_CREATED` | Announce new pool creation |
| `POOL_CLOSED` | Announce pool shutdown |
| `TASK_COMPLETED` | Announce task completion |

### MessageBus API

```python
from mahavishnu.mcp.protocols.message_bus import MessageBus, MessageType

# Create message bus
bus = MessageBus(max_queue_size=1000)

# Subscribe to messages
async def handle_task_delegate(msg):
    print(f"Task from {msg.source_pool_id}: {msg.payload}")

bus.subscribe(MessageType.TASK_DELEGATE, handle_task_delegate)

# Publish message
await bus.publish({
    "type": "task_delegate",
    "source_pool_id": "pool_abc",
    "target_pool_id": "pool_def",
    "task": {"prompt": "Process this"},
})

# Receive messages for specific pool
msg = await bus.receive("pool_def", timeout=5.0)
```

## Memory Architecture

### Memory Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Memory Flow Architecture                     │
└─────────────────────────────────────────────────────────────────┘

1. LOCAL POOL MEMORY
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │ MahavishnuPool  │  │SessionBuddyPool │  │   RunPodPool    │
   ├─────────────────┤  ├─────────────────┤  ├─────────────────┤
   │ • Worker results│  │ • Worker results│  │ • Job logs      │
   │ • Pool metrics  │  │ • Pool metrics  │  │ • Pod status    │
   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 ↓
2. POOL AGGREGATION
   ┌─────────────────────────────────────────────────────────────┐
   │                  MemoryAggregator                           │
   │  • collect_pool_memory() from all pools                    │
   │  • Transform to Session-Buddy format                       │
   │  • Batch insert to Session-Buddy                           │
   └─────────────────────┬───────────────────────────────────────┘
                          ↓ HTTP (MCP)
3. SESSION-BUDDY STORAGE
   ┌─────────────────────────────────────────────────────────────┐
   │              Session-Buddy (Port 8678)                      │
   ├─────────────────────────────────────────────────────────────┤
   │  • store_memory() - Worker executions                       │
   │  • search_conversations() - Cross-pool query               │
   └─────────────────────┬───────────────────────────────────────┘
                          ↓ Periodic sync
4. AKOSHA AGGREGATION
   ┌─────────────────────────────────────────────────────────────┐
   │                  Akosha (Port 8682)                         │
   ├─────────────────────────────────────────────────────────────┤
   │  • Cross-pool pattern detection                            │
   │  • Global analytics across all Session-Buddy instances     │
   └─────────────────────────────────────────────────────────────┘
```

### MemoryAggregator API

```python
from mahavishnu.pools.memory_aggregator import MemoryAggregator

# Initialize aggregator
aggregator = MemoryAggregator(
    session_buddy_url="http://localhost:8678/mcp",
    akosha_url="http://localhost:8682/mcp",
    sync_interval=60.0,  # seconds
)

# Start periodic sync
await aggregator.start_periodic_sync(pool_manager)

# Manual sync
stats = await aggregator.collect_and_sync(pool_manager)
print(f"Synced {stats['memory_items_synced']} items")

# Cross-pool search
results = await aggregator.cross_pool_search(
    query="API implementation",
    pool_manager=pool_manager,
    limit=100,
)
```

## Configuration

### Environment Variables

```bash
# Enable pool management
export MAHAVISHNU_POOLS_ENABLED=true

# Default pool type
export MAHAVISHNU_DEFAULT_POOL_TYPE=mahavishnu

# Pool routing strategy
export MAHAVISHNU_POOL_ROUTING_STRATEGY=least_loaded

# Memory aggregation
export MAHAVISHNU_MEMORY_AGGREGATION_ENABLED=true
export MAHAVISHNU_MEMORY_SYNC_INTERVAL=60

# External services
export MAHAVISHNU_SESSION_BUDDY_POOL_URL=http://localhost:8678/mcp
export MAHAVISHNU_AKOSHA_URL=http://localhost:8682/mcp

# Pool defaults
export MAHAVISHNU_POOL_DEFAULT_MIN_WORKERS=1
export MAHAVISHNU_POOL_DEFAULT_MAX_WORKERS=10
```

### YAML Configuration

**settings/mahavishnu.yaml**:

```yaml
# Pool configuration
pools_enabled: true
default_pool_type: mahavishnu
pool_routing_strategy: least_loaded

# Memory aggregation
memory_aggregation_enabled: true
memory_sync_interval: 60
session_buddy_pool_url: "http://localhost:8678/mcp"
akosha_url: "http://localhost:8682/mcp"

# Pool defaults
pool_default_min_workers: 1
pool_default_max_workers: 10
```

## MCP Tools

### Pool Management Tools

| Tool | Description |
|------|-------------|
| `pool_spawn` | Create new pool |
| `pool_execute` | Execute task on specific pool |
| `pool_route_execute` | Execute with auto-routing |
| `pool_list` | List all active pools |
| `pool_monitor` | Monitor pool metrics |
| `pool_scale` | Scale pool worker count |
| `pool_close` | Close specific pool |
| `pool_close_all` | Close all pools |
| `pool_health` | Get health status |
| `pool_search_memory` | Search memory across pools |

### MCP Tool Examples

```python
# Spawn pool
result = await mcp.call_tool("pool_spawn", {
    "pool_type": "mahavishnu",
    "name": "local",
    "min_workers": 2,
    "max_workers": 5,
})

# Execute with auto-routing
result = await mcp.call_tool("pool_route_execute", {
    "prompt": "Write tests",
    "pool_selector": "least_loaded",
})

# List pools
pools = await mcp.call_tool("pool_list", {})

# Health check
health = await mcp.call_tool("pool_health", {})

# Search memory
results = await mcp.call_tool("pool_search_memory", {
    "query": "API implementation",
    "limit": 50,
})
```

## Performance Considerations

### Pool Selection Overhead

- **Routing**: < 10ms overhead per task
- **MessageBus**: Async, non-blocking
- **Memory Aggregation**: Batch operations every 60s

### Scaling Limits

- **Maximum Pools**: 100+ concurrent pools
- **Maximum Workers per Pool**: 100 (configurable)
- **Total Concurrent Tasks**: 10,000+ across all pools

### Resource Usage

- **Memory**: ~50MB per pool (base) + worker memory
- **CPU**: Minimal for idle pools
- **Network**: Session-Buddy pools require HTTP connection

## Best Practices

### 1. Pool Type Selection

- **Local Development**: Use `MahavishnuPool`
- **Production**: Use `SessionBuddyPool` for distributed execution
- **Cloud GPU**: Use `RunPodPool` for serverless GPU workloads

### 2. Routing Strategy

- **Default**: Use `LEAST_LOADED` for optimal resource utilization
- **Stateful**: Use `AFFINITY` for related tasks
- **Fair Distribution**: Use `ROUND_ROBIN` for even load spread

### 3. Memory Management

- Enable periodic sync for long-running pools
- Use `cross_pool_search` for unified query
- Monitor memory usage via `pool_monitor`

### 4. Scaling

- Start with minimum workers
- Scale based on load metrics
- Use `pool_health` to monitor before scaling

## Troubleshooting

### Pool Won't Start

```bash
# Check if pools enabled
mahavishnu pool health

# Check configuration
echo $MAHAVISHNU_POOLS_ENABLED

# View logs
tail -f /tmp/mahavishnu.log
```

### Tasks Not Executing

```bash
# Check pool health
mahavishnu pool health

# List active pools
mahavishnu pool list

# Check worker counts
mahavishnu pool monitor
```

### Memory Not Syncing

```bash
# Check Session-Buddy connection
curl http://localhost:8678/mcp/health

# Check Akosha connection
curl http://localhost:8682/mcp/health

# View memory stats
mahavishnu pool search-memory --query "test"
```

## Migration Guide

See [POOL_MIGRATION.md](POOL_MIGRATION.md) for:

- Migrating from WorkerManager to pools
- Example workflows
- Best practices
- Common pitfalls

## Future Enhancements

- [ ] Custom pool type plugins
- [ ] Advanced scheduling algorithms
- [ ] Pool federation across multiple Mahavishnu instances
- [ ] GPU worker pools for ML workloads
- [ ] Cost optimization algorithms

## References

- [BasePool API](#basepool-api)
- [PoolManager API](#poolmanager-api)
- [MemoryAggregator API](#memoryaggregator-api)
- Implementation Progress
