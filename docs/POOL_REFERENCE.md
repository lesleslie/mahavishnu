# Pool Management Reference

## Pool Types

**MahavishnuPool** — Direct local worker management. Low-latency task execution, dynamic scaling (min_workers to max_workers). Use for: local development, debugging, CI/CD.

**SessionBuddyPool** — Delegated to Session-Buddy instances. Each instance manages exactly 3 workers. Remote execution via MCP. Use for: distributed workloads, multi-server deployments.

**KubernetesPool** — Deploys workers as K8s Jobs/Pods with HorizontalPodAutoscaler. Use for: production deployments, auto-scaling workloads.

## Architecture

| Module | Location | Purpose | Scope |
|--------|----------|---------|-------|
| **Multi-pool orchestration** | `mahavishnu/pools/` | Task distribution across pool types | Cross-server, auto-scaling |
| **iTerm2 session pool** | `mahavishnu/terminal/pool.py` | macOS iTerm2 terminal session management | Local development only |
| **Process pool executor** | `mahavishnu/core/process_pool_executor.py` | CPU-bound operation offload | Single-process |

## Configuration

Enable in `settings/mahavishnu.yaml`:

```yaml
pools_enabled: true
default_pool_type: "mahavishnu"
pool_routing_strategy: "least_loaded"  # round_robin, least_loaded, random, affinity
memory_aggregation_enabled: true
memory_sync_interval: 60
session_buddy_pool_url: "http://localhost:8678/mcp"
akosha_url: "http://localhost:8682/mcp"
pool_websocket_enabled: true
pool_websocket_port: 8691
```

## Key Features

- **Auto-routing**: 4 strategies (round_robin, least_loaded, random, affinity)
- **Inter-pool communication**: Async message bus for coordination
- **Memory aggregation**: Automatic sync from pools → Session-Buddy → Akosha
- **Dynamic scaling**: Scale pools up/down based on load
- **Health monitoring**: Track pool and worker status
- **WebSocket broadcasting**: Real-time pool events to connected clients

## Documentation

- [Pool Architecture](POOL_ARCHITECTURE.md) — Complete design guide
- [Pool Migration](POOL_MIGRATION.md) — From WorkerManager to pools
- [MCP Tools Spec](MCP_TOOLS_SPECIFICATION.md) — Pool MCP tool reference

## Usage

```python
from mahavishnu.pools import PoolManager, PoolConfig, PoolSelector

# Spawn pool
config = PoolConfig(name="local", pool_type="mahavishnu", min_workers=2, max_workers=5)
pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

# Execute task
result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Write code"})

# Auto-route to best pool
result = await pool_mgr.route_task(
    {"prompt": "Write tests"},
    pool_selector=PoolSelector.LEAST_LOADED,
)
```
