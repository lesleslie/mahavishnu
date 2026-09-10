# Pool Management Reference

## Pool Types

**MahavishnuPool** — Direct local worker management. Low-latency task execution, dynamic scaling (min_workers to max_workers). Use for: local development, debugging, CI/CD.

**SessionBuddyPool** — Delegated to Session-Buddy instances. Each instance manages exactly 3 workers. Remote execution via MCP. Use for: distributed workloads, multi-server deployments.

**KubernetesPool** — Removed (Option B). Was for production deployments with K8s infrastructure; replaced by RunPodPool for cloud execution.

## Architecture

| Module | Location | Purpose | Scope |
|--------|----------|---------|-------|
| **Multi-pool orchestration** | `mahavishnu/pools/` | Task distribution across pool types | Cross-server, auto-scaling |
| **iTerm2 session pool** | `mahavishnu/terminal/adapters/` | Terminal adapter implementations (tmux, mock, crow, goose) | Local development only |
| **Process pool executor** | `mahavishnu/core/process_pool_executor.py` | CPU-bound operation offload | Single-process |

## Configuration

Enable in `settings/mahavishnu.yaml`:

```yaml
# Pool management (nested under pools:)
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"  # round_robin, least_loaded, random, affinity
  min_workers: 1
  max_workers: 10
  memory_aggregation_enabled: true
  memory_sync_interval: 60
  session_buddy_url: "http://localhost:8678/mcp"
  akosha_url: "http://localhost:8682/mcp"

# Pool WebSocket broadcasting (flat, read by websocket integration)
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
