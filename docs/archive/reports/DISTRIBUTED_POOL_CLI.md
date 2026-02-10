# Distributed Computation Pool CLI - Complete Documentation

## Overview

The Distributed Computation Pool CLI provides a user-friendly interface for managing and orchestrating computation across multiple worker pools. It supports three pool types (Mahavishnu, Session-Buddy, Kubernetes), five routing strategies, and task distribution with map-reduce capabilities.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Pool Types](#pool-types)
- [CLI Commands](#cli-commands)
- [Task Execution Modes](#task-execution-modes)
- [Output Formatters](#output-formatters)
- [Grafana Dashboard](#grafana-dashboard)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Installation

The Distributed Pool CLI is included with Mahavishnu. No additional installation required.

```bash
# Verify installation
mahavishnu pools --help
```

## Quick Start

### 1. Register Your First Pool

```bash
# Register a local Mahavishnu pool
mahavishnu pools register \
    --name "local-pool" \
    --type "mahavishnu" \
    --min-workers 2 \
    --max-workers 5
```

### 2. List Active Pools

```bash
# List all pools
mahavishnu pools list

# List only active pools
mahavishnu pools list --active-only
```

### 3. Execute a Task

```bash
# Execute on specific pool
mahavishnu pools execute \
    --pool "local-pool" \
    --task-type "analyze" \
    --payload '{"file": "test.py"}'
```

### 4. Monitor in Real-Time

```bash
# Watch pools in real-time
mahavishnu pools watch
```

## Pool Types

### 1. MahavishnuPool (Direct Management)

**Use Cases:**
- Local development
- Low-latency execution
- Debugging
- CI/CD automation

**Configuration:**

```bash
mahavishnu pools register \
    --name "local" \
    --type "mahavishnu" \
    --min-workers 2 \
    --max-workers 10 \
    --worker-type "terminal-qwen"
```

**Architecture:**
- Wraps existing WorkerManager
- Workers run locally in Mahavishnu process
- Dynamic scaling (min to max workers)

### 2. SessionBuddyPool (Delegated Management)

**Use Cases:**
- Distributed execution
- Remote workers
- Multi-server deployments
- Session-Buddy memory integration

**Configuration:**

```bash
mahavishnu pools register \
    --name "delegated" \
    --type "session-buddy" \
    --endpoint "http://localhost:8678/mcp"
```

**Architecture:**
- Each Session-Buddy instance manages 3 workers
- Communication via MCP protocol (HTTP)
- Fixed worker count (scale by spawning more pools)

### 3. KubernetesPool (K8s-Native)

**Use Cases:**
- Cloud deployments
- Auto-scaling workloads
- Multi-cluster execution
- Resource quotas

**Configuration:**

```bash
mahavishnu pools register \
    --name "cloud-pool" \
    --type "kubernetes" \
    --namespace "mahavishnu" \
    --container-image "python:3.13-slim" \
    --region "us-west-2"
```

**Architecture:**
- Workers deployed as K8s Jobs/Pods
- Python k8s client for job management
- Auto-scaling via HorizontalPodAutoscaler (HPA)

## CLI Commands

### 1. List Pools

**Command:**
```bash
mahavishnu pools list [OPTIONS]
```

**Options:**
- `--active-only`: Show only running pools
- `--by-type <TYPE>`: Filter by pool type (mahavishnu, session-buddy, kubernetes)
- `--format, -f <FORMAT>`: Output format (table, json, markdown)

**Examples:**

```bash
# List all pools
mahavishnu pools list

# List only active Kubernetes pools
mahavishnu pools list --active-only --by-type kubernetes

# JSON output
mahavishnu pools list --format json
```

**Output (Table):**
```
Active Pools
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓
┃ Pool ID            ┃ Name      ┃ Type         ┃ Status ┃ Workers┃ Range  ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━┩
│ pool_abc123...      │ local     │ mahavishnu   │ ●      │     5  │ 2-10   │
│ pool_def456...      │ k8s-pool  │ kubernetes   │ ●      │    10  │ 5-20   │
└────────────────────┴───────────┴──────────────┴────────┴────────┴────────┘
```

### 2. Get Pool Details

**Command:**
```bash
mahavishnu pools get <POOL_NAME>
```

**Options:**
- `--format, -f <FORMAT>`: Output format (table, json, markdown)

**Examples:**

```bash
# Get pool details
mahavishnu pools get local-pool

# JSON output
mahavishnu pools get local-pool --format json
```

**Output:**
```
Pool: pool_abc123def456
Name: local-pool
Type: mahavishnu
Status: ● RUNNING
Workers: 5 (2-10)
Region: default

Metrics:
  Tasks Completed: 152
  Tasks Failed: 3
  Avg Duration: 4.23s
  Memory Usage: 245.3 MB
```

### 3. Register Pool

**Command:**
```bash
mahavishnu pools register [OPTIONS]
```

**Required Options:**
- `--name, -n <NAME>`: Pool name
- `--type, -t <TYPE>`: Pool type (mahavishnu, session-buddy, kubernetes)

**Optional Options:**
- `--endpoint <URL>`: Pool endpoint URL (for session-buddy)
- `--max-workers, -w <COUNT>`: Maximum workers (default: 10)
- `--min-workers, -m <COUNT>`: Minimum workers (default: 1)
- `--worker-type <TYPE>`: Worker type (default: terminal-qwen)
- `--region, -r <REGION>`: Pool region (default: default)
- `--namespace <NS>`: Kubernetes namespace (default: mahavishnu)
- `--container-image <IMAGE>`: K8s container image (default: python:3.13-slim)

**Examples:**

```bash
# Register Mahavishnu pool
mahavishnu pools register \
    --name "local" \
    --type "mahavishnu" \
    --min-workers 2 \
    --max-workers 5

# Register Session-Buddy pool
mahavishnu pools register \
    --name "delegated" \
    --type "session-buddy" \
    --endpoint "http://localhost:8678/mcp"

# Register Kubernetes pool
mahavishnu pools register \
    --name "cloud-pool" \
    --type "kubernetes" \
    --region "us-west-2" \
    --max-workers 20
```

### 4. Execute Task

**Command:**
```bash
mahavishnu pools execute [OPTIONS]
```

**Required Options:**
- `--task-type, -t <TYPE>`: Task type
- `--payload <JSON>`: Task payload (JSON string)

**Execution Mode Options:**
- `--pool, -p <POOL_ID>`: Execute on specific pool
- `--auto-route`: Auto-route to best pool

**Optional Options:**
- `--timeout, -T <SECONDS>`: Task timeout (default: 300)
- `--format, -f <FORMAT>`: Output format (table, json, markdown)

**Examples:**

```bash
# Execute on specific pool
mahavishnu pools execute \
    --pool "local-pool" \
    --task-type "analyze" \
    --payload '{"file": "test.py"}'

# Auto-route to best pool
mahavishnu pools execute \
    --auto-route \
    --task-type "compute" \
    --payload '{"query": "SELECT * FROM users"}'

# With custom timeout
mahavishnu pools execute \
    --pool "local-pool" \
    --task-type "process" \
    --payload '{"data": [...]}' \
    --timeout 600
```

**Output:**
```
✓ Routed to pool: pool_abc123
✓ Task completed
  Status: completed
  Output: Analysis complete: 15 issues found
```

### 5. Distribute Task (Map-Reduce)

**Command:**
```bash
mahavishnu pools distribute [OPTIONS]
```

**Required Options:**
- `--task-type, -t <TYPE>`: Task type
- `--payload <JSON>`: Task payload (JSON string)

**Optional Options:**
- `--strategy, -s <STRATEGY>`: Distribution strategy (default: round_robin)
  - `round_robin`: Distribute evenly
  - `broadcast`: Send to all pools
  - `random`: Random selection
  - `least_loaded`: Route to least loaded pool
  - `map_reduce`: Distribute and aggregate results
- `--pool-filter <TYPE>`: Filter pools by type
- `--timeout, -T <SECONDS>`: Task timeout (default: 300)
- `--format, -f <FORMAT>`: Output format

**Examples:**

```bash
# Broadcast to all pools
mahavishnu pools distribute \
    --task-type "transform" \
    --payload '{"items": [1, 2, 3, 4, 5]}' \
    --strategy broadcast

# Map-reduce across Kubernetes pools
mahavishnu pools distribute \
    --task-type "analyze" \
    --payload '{"files": ["a.py", "b.py", "c.py"]}' \
    --strategy map_reduce \
    --pool-filter kubernetes

# Distribute with round-robin
mahavishnu pools distribute \
    --task-type "process" \
    --payload '{"batch": [...]}' \
    --strategy round_robin
```

**Output:**
```
Distributing task across 3 pools...
  Strategy: map_reduce
✓ Distribution completed
  Total: 3
  Successful: 3
  Failed: 0
```

### 6. Check Health

**Command:**
```bash
mahavishnu pools health [OPTIONS]
```

**Options:**
- `--pool, -p <POOL_NAME>`: Specific pool name
- `--all, -a`: Check all pools (default)
- `--format, -f <FORMAT>`: Output format

**Examples:**

```bash
# Check all pools
mahavishnu pools health --all

# Check specific pool
mahavishnu pools health --pool local-pool
```

**Output:**
```
Pool Manager Health: HEALTHY
Active Pools: 2

Pool Status:
  ● pool_abc123: 5 workers
  ● pool_def456: 10 workers
```

### 7. Monitor Pools (Real-Time)

**Command:**
```bash
mahavishnu pools watch [OPTIONS]
```

**Options:**
- `--refresh, -r <SECONDS>`: Refresh interval (default: 1.0)

**Examples:**

```bash
# Monitor with default refresh
mahavishnu pools watch

# Faster refresh
mahavishnu pools watch --refresh 0.5
```

**Output:**
```
Pool Monitor (Active: 2)
┏━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━┓
┃ Pool ID      ┃ Name   ┃ Type         ┃ Status ┃ Workers┃ Comple┃ Failed┃
┡━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━┩
│ pool_abc...  │ local  │ mahavishnu   │ ●      │     5  │   152  │     3 │
│ pool_def...  │ k8s    │ kubernetes   │ ●      │    10  │   891  │    12 │
└──────────────┴────────┴──────────────┴────────┴────────┴────────┴───────┘
```

### 8. Discover Pools

**Command:**
```bash
mahavishnu pools discover [OPTIONS]
```

**Options:**
- `--from-ecosystem`: Discover from ecosystem repos
- `--auto-register`: Auto-register discovered pools

**Examples:**

```bash
# Discover from ecosystem
mahavishnu pools discover --from-ecosystem

# Discover and auto-register
mahavishnu pools discover --from-ecosystem --auto-register
```

### 9. Rebalance Pools

**Command:**
```bash
mahavishnu pools rebalance [OPTIONS]
```

**Options:**
- `--strategy, -s <STRATEGY>`: Rebalancing strategy (default: least_loaded)
  - `least_loaded`: Route to pools with fewest workers
  - `round_robin`: Distribute evenly
  - `random`: Random selection

**Examples:**

```bash
# Rebalance with least_loaded strategy
mahavishnu pools rebalance --strategy least_loaded

# Rebalance with round-robin
mahavishnu pools rebalance -s round_robin
```

### 10. Get Task Status

**Command:**
```bash
mahavishnu pools task <TASK_ID> [OPTIONS]
```

**Options:**
- `--format, -f <FORMAT>`: Output format

**Examples:**

```bash
# Get task status
mahavishnu pools task task_abc123

# JSON output
mahavishnu pools task task_abc123 --format json
```

**Output:**
```
Task: task_abc123
Status: RUNNING
Type: analyze
Pool: pool_abc123
Worker: worker_1
Created: 2026-02-05 10:23:45
Started: 2026-02-05 10:23:46
Duration: 5.23s
Result:
  Analysis complete: 15 issues found
```

### 11. Cancel Task

**Command:**
```bash
mahavishnu pools cancel <TASK_ID>
```

**Examples:**

```bash
# Cancel task
mahavishnu pools cancel task_abc123
```

### 12. Get Statistics

**Command:**
```bash
mahavishnu pools stats [OPTIONS]
```

**Options:**
- `--by-type`: Group by pool type
- `--format, -f <FORMAT>`: Output format

**Examples:**

```bash
# Show all stats
mahavishnu pools stats

# Group by type
mahavishnu pools stats --by-type

# JSON output
mahavishnu pools stats --format json
```

**Output:**
```
Pool Statistics
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Metric              ┃ Value  ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Total Pools         │      3 │
│ Total Workers       │     25 │
│ Active Pools        │      3 │
│ Degraded Pools      │      0 │
│ Failed Pools        │      0 │
│ mahavishnu_pools    │      1 │
│ mahavishnu_workers  │      5 │
│ kubernetes_pools    │      2 │
│ kubernetes_workers  │     20 │
└─────────────────────┴────────┘
```

## Task Execution Modes

### 1. Single Pool Execution

Execute task on a specific pool:

```bash
mahavishnu pools execute \
    --pool "local-pool" \
    --task-type "analyze" \
    --payload '{"file": "test.py"}'
```

**Use Cases:**
- Targeted execution on specific hardware
- Debugging pool-specific issues
- Testing pool capabilities

### 2. Auto-Routed Execution

Let system choose best pool:

```bash
mahavishnu pools execute \
    --auto-route \
    --task-type "compute" \
    --payload '{"query": "..."}'
```

**Routing Strategies:**
- `least_loaded`: Routes to pool with fewest active workers (default)
- `round_robin`: Distributes tasks evenly
- `random`: Random pool selection
- `affinity`: Routes to same pool for related tasks

**Use Cases:**
- Optimal resource utilization
- Load balancing
- General task execution

### 3. Distributed Execution (Map-Reduce)

Distribute task across multiple pools:

```bash
mahavishnu pools distribute \
    --task-type "transform" \
    --payload '{"items": [...]}' \
    --strategy map_reduce
```

**Distribution Strategies:**
- `round_robin`: Distribute evenly across pools
- `broadcast`: Send to all pools
- `random`: Random pool selection
- `least_loaded`: Route to least loaded pools
- `map_reduce`: Distribute and aggregate results

**Use Cases:**
- Parallel data processing
- Batch job execution
- Cross-pool analytics

## Output Formatters

### Table Formatter

Human-readable tables with colors and icons:

```bash
mahavishnu pools list --format table
```

**Features:**
- Color-coded status (● running, ◐ initializing, ⚠ degraded, ✗ failed)
- Column alignment
- Pretty formatting

### JSON Formatter

Machine-readable JSON output:

```bash
mahavishnu pools list --format json
```

**Output:**
```json
{
  "pools": [
    {
      "pool_id": "pool_abc123",
      "name": "local-pool",
      "pool_type": "mahavishnu",
      "status": "running",
      "workers": 5,
      "min_workers": 2,
      "max_workers": 10
    }
  ]
}
```

**Use Cases:**
- Integration with other tools
- Scripting and automation
- Log parsing

### Markdown Formatter

Documentation-ready markdown:

```bash
mahavishnu pools list --format markdown
```

**Output:**
```markdown
## Active Pools

| Pool ID | Name | Type | Status | Workers | Region |
|---------|------|------|--------|---------|--------|
| pool_abc123 | local | mahavishnu | running | 5 | default |
```

**Use Cases:**
- Documentation generation
- Report creation
- Wiki integration

### Progress Formatter

Real-time progress bars:

```bash
mahavishnu pools execute --format progress
```

**Features:**
- Spinner animation
- Progress percentage
- Time remaining

**Use Cases:**
- Long-running tasks
- Batch operations
- User feedback

## Grafana Dashboard

The Distributed Pool CLI integrates with Grafana for comprehensive monitoring.

### Dashboard Panels (15)

1. **Pool Overview**
   - Total pools
   - Active pools
   - Degraded pools
   - Failed pools

2. **Worker Metrics**
   - Total workers
   - Active workers
   - Idle workers
   - Worker utilization

3. **Task Execution**
   - Tasks completed (per pool)
   - Tasks failed (per pool)
   - Task success rate
   - Average task duration

4. **Pool Health**
   - Pool status (per pool)
   - Worker health
   - Memory usage
   - CPU usage

5. **Task Distribution**
   - Tasks by pool
   - Tasks by type
   - Tasks by status
   - Task queue size

6. **System Throughput**
   - Tasks per minute
   - Tasks per hour
   - Peak throughput
   - Throughput trend

7. **Pool Utilization**
   - Worker utilization heatmap
   - Pool capacity
   - Pool efficiency
   - Resource allocation

8. **Latency Metrics**
   - Task execution time (P50)
   - Task execution time (P95)
   - Task execution time (P99)
   - Queuing time

9. **Error Tracking**
   - Error rate (per pool)
   - Error types
   - Error frequency
   - Error trends

10. **Memory Usage**
    - Memory per pool
    - Memory per worker
    - Memory trend
    - Memory alerts

11. **Routing Statistics**
    - Tasks per strategy
    - Routing effectiveness
    - Pool selection distribution
    - Routing latency

12. **Scaling Events**
    - Scale-up events
    - Scale-down events
    - Auto-scaling triggers
    - Scaling frequency

13. **Task History**
    - Recent tasks
    - Task outcomes
    - Task duration trend
    - Task patterns

14. **Pool Comparison**
    - Performance by pool type
    - Cost per pool
    - Efficiency comparison
    - Pool rankings

15. **Alert Summary**
    - Active alerts
    - Alert severity
    - Alert frequency
    - Alert history

### Deploy Dashboard

```bash
# Deploy to Grafana
cd /Users/les/Projects/mahavishnu/mahavishnu/integrations/grafana
./deploy_dashboard.sh
```

### Access Dashboard

```
URL: http://localhost:3000/d/pool-monitoring
Username: admin
Password: admin (change on first login)
```

## Integration

### Mahavishnu Workflows

Integrate with Mahavishnu workflows for task orchestration:

```python
from mahavishnu.core.app import MahavishnuApp

maha_app = MahavishnuApp()

# Spawn pool
config = PoolConfig(name="workflow-pool", pool_type="mahavishnu")
pool_id = await maha_app.pool_manager.spawn_pool("mahavishnu", config)

# Execute workflow tasks
task = {"task_type": "workflow_step", "payload": {...}}
result = await maha_app.pool_manager.execute_on_pool(pool_id, task)
```

### EventCollector Logging

Log pool events to EventCollector:

```python
from mahavishnu.integrations.event_collector import EventCollector

collector = EventCollector()

# Log pool event
await collector.collect_event({
    "type": "pool_task_completed",
    "pool_id": pool_id,
    "task_id": task_id,
    "duration": 5.23,
    "status": "completed",
})
```

### Session-Buddy Storage

Store task history in Session-Buddy:

```python
from mahavishnu.pools import MemoryAggregator

aggregator = MemoryAggregator()

# Sync pool memory to Session-Buddy
await aggregator.collect_and_sync(pool_manager)

# Search across pools
results = await aggregator.cross_pool_search(
    query="API implementation",
    pool_manager=pool_manager,
    limit=100,
)
```

### Grafana Monitoring

Monitor pools with Grafana:

```yaml
# Prometheus configuration
scrape_configs:
  - job_name: 'mahavishnu_pools'
    static_configs:
      - targets: ['localhost:8680']
    metrics_path: '/metrics'
```

## Best Practices

### 1. Pool Type Selection

- **Local Development**: Use `MahavishnuPool`
- **Production**: Use `SessionBuddyPool` for distributed execution
- **Cloud**: Use `KubernetesPool` for auto-scaling

### 2. Routing Strategy

- **Default**: Use `LEAST_LOADED` for optimal resource utilization
- **Stateful**: Use `AFFINITY` for related tasks
- **Fair Distribution**: Use `ROUND_ROBIN` for even load spread

### 3. Memory Management

- Enable periodic sync for long-running pools
- Use `cross_pool_search` for unified query
- Monitor memory usage via `pools stats`

### 4. Scaling

- Start with minimum workers
- Scale based on load metrics
- Use `pools health` to monitor before scaling

### 5. Error Handling

- Use `--format json` for machine-readable error output
- Check pool health before task execution
- Monitor task failure rates via Grafana

### 6. Security

- Use TLS for Session-Buddy pools
- Restrict pool access with authentication
- Rotate credentials regularly

### 7. Performance

- Use auto-routing for optimal performance
- Distribute large tasks across pools
- Monitor latency metrics in Grafana

## Troubleshooting

### Pool Won't Start

**Symptoms:**
- `mahavishnu pools register` fails
- Pool status stuck at `PENDING`

**Solutions:**

```bash
# Check if pools enabled
mahavishnu pools health

# Check configuration
cat settings/mahavishnu.yaml | grep pools

# View logs
tail -f /tmp/mahavishnu.log

# Verify dependencies
mahavishnu validate-production --check configuration
```

### Tasks Not Executing

**Symptoms:**
- Task status stuck at `PENDING`
- No output from `pools execute`

**Solutions:**

```bash
# Check pool health
mahavishnu pools health --all

# List active pools
mahavishnu pools list --active-only

# Check worker counts
mahavishnu pools stats --by-type

# Verify pool manager initialized
mahavishnu shell
>>> maha_app.pool_manager
```

### Memory Not Syncing

**Symptoms:**
- `cross_pool_search` returns no results
- Session-Buddy has no pool memory

**Solutions:**

```bash
# Check Session-Buddy connection
curl http://localhost:8678/mcp/health

# Check Akosha connection
curl http://localhost:8682/mcp/health

# View memory stats
mahavishnu pools stats

# Manual sync
mahavishnu shell
>>> from mahavishnu.pools import MemoryAggregator
>>> aggregator = MemoryAggregator()
>>> await aggregator.collect_and_sync(maha_app.pool_manager)
```

### High Task Failure Rate

**Symptoms:**
- Many tasks showing `FAILED` status
- Grafana shows high error rate

**Solutions:**

```bash
# Check pool health
mahavishnu pools health --all

# View error details
mahavishnu pools task <task_id> --format json

# Check worker capacity
mahavishnu pools stats --by-type

# Scale up if needed
mahavishnu pool scale <pool_id> --target 20
```

### Pool Degraded Status

**Symptoms:**
- Pool shows `DEGRADED` status
- Workers failing or unresponsive

**Solutions:**

```bash
# Check pool details
mahavishnu pools get <pool_name>

# View worker health
mahavishnu pools watch

# Restart pool
mahavishnu pool close <pool_id>
mahavishnu pools register --name <pool_name> --type <type>
```

## Additional Resources

- [Pool Architecture](POOL_ARCHITECTURE.md) - Complete architecture guide
- [Pool Migration Guide](POOL_MIGRATION.md) - From WorkerManager to pools
- [MCP Tools Specification](MCP_TOOLS_SPECIFICATION.md) - Pool MCP tool reference
- [Grafana Dashboard](mahavishnu/integrations/grafana/README.md) - Dashboard setup guide

## Support

For issues, questions, or contributions:
- GitHub Issues: [Mahavishnu Issues](https://github.com/yourusername/mahavishnu/issues)
- Documentation: [Mahavishnu Docs](https://github.com/yourusername/mahavishnu/docs)
- CLI Help: `mahavishnu pools --help`
