# Distributed Pool CLI - Quick Reference

## Command Summary

### Pool Management

| Command | Purpose | Example |
|---------|---------|---------|
| `pools list` | List all pools | `mahavishnu pools list` |
| `pools get <name>` | Get pool details | `mahavishnu pools get pool-main` |
| `pools register` | Register new pool | `mahavishnu pools register --name local --type mahavishnu` |
| `pools health` | Check pool health | `mahavishnu pools health --all` |
| `pools stats` | Show statistics | `mahavishnu pools stats --by-type` |

### Task Execution

| Command | Purpose | Example |
|---------|---------|---------|
| `pools execute` | Execute on pool | `mahavishnu pools execute --pool pool-main --task-type analyze` |
| `pools execute --auto-route` | Auto-route task | `mahavishnu pools execute --auto-route --task-type compute` |
| `pools distribute` | Distribute task | `mahavishnu pools distribute --task-type transform --strategy broadcast` |
| `pools task <id>` | Get task status | `mahavishnu pools task task_abc123` |
| `pools cancel <id>` | Cancel task | `mahavishnu pools cancel task_abc123` |

### Monitoring

| Command | Purpose | Example |
|---------|---------|---------|
| `pools watch` | Real-time monitor | `mahavishnu pools watch --refresh 1` |
| `pools discover` | Discover pools | `mahavishnu pools discover --from-ecosystem` |
| `pools rebalance` | Rebalance tasks | `mahavishnu pools rebalance --strategy least_loaded` |

## Common Workflows

### 1. Setup and Execute

```bash
# Register pool
mahavishnu pools register --name local --type mahavishnu --min-workers 2 --max-workers 5

# Execute task
mahavishnu pools execute --pool local --task-type analyze --payload '{"file": "test.py"}'

# Check status
mahavishnu pools task task_abc123
```

### 2. Auto-Routing

```bash
# Register multiple pools
mahavishnu pools register --name pool1 --type mahavishnu
mahavishnu pools register --name pool2 --type kubernetes --region us-west-2

# Auto-route to best pool
mahavishnu pools execute --auto-route --task-type compute --payload '{"query": "..."}'
```

### 3. Map-Reduce

```bash
# Distribute across all pools
mahavishnu pools distribute \
    --task-type transform \
    --payload '{"items": [1,2,3,4,5]}' \
    --strategy map_reduce

# Broadcast to all Kubernetes pools
mahavishnu pools distribute \
    --task-type process \
    --payload '{"batch": [...]}' \
    --strategy broadcast \
    --pool-filter kubernetes
```

### 4. Monitoring

```bash
# Watch in real-time
mahavishnu pools watch --refresh 1

# Check health
mahavishnu pools health --all

# View statistics
mahavishnu pools stats --by-type
```

## Pool Types

| Type | Description | Use Case |
|------|-------------|----------|
| `mahavishnu` | Direct management | Local development, low latency |
| `session-buddy` | Delegated management | Distributed execution, remote workers |
| `kubernetes` | K8s-native | Cloud deployments, auto-scaling |

## Routing Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `least_loaded` | Fewest active workers | Optimal resource utilization |
| `round_robin` | Even distribution | Fair task allocation |
| `random` | Random selection | Simple load balancing |
| `affinity` | Same pool for related tasks | Stateful operations |
| `map_reduce` | Distribute and aggregate | Parallel processing |

## Distribution Strategies

| Strategy | Description |
|----------|-------------|
| `round_robin` | Distribute evenly across pools |
| `broadcast` | Send to all pools |
| `random` | Random pool selection |
| `least_loaded` | Route to least loaded pools |
| `map_reduce` | Distribute and aggregate results |

## Output Formats

| Format | Description | Use Case |
|--------|-------------|----------|
| `table` | Pretty tables with colors | Human-readable output |
| `json` | Machine-readable JSON | Scripting, automation |
| `markdown` | Documentation format | Reports, documentation |
| `progress` | Real-time progress bars | Long-running tasks |

## Task Types

Common task types (extendable):

- `analyze` - Code analysis
- `compute` - General computation
- `transform` - Data transformation
- `process` - Batch processing
- `query` - Database queries

## Payload Format

All payloads must be JSON strings:

```bash
# Simple payload
--payload '{"file": "test.py"}'

# Complex payload
--payload '{"data": [...], "options": {"parallel": true}}'

# Array payload
--payload '{"items": [1, 2, 3, 4, 5]}'
```

## Tips

1. **Start small**: Begin with `mahavishnu` pool type for local testing
2. **Use auto-routing**: Let the system choose the best pool
3. **Monitor frequently**: Use `pools watch` for real-time feedback
4. **Check health**: Run `pools health --all` before critical tasks
5. **Use JSON output**: For scripting and automation
6. **Distribute wisely**: Use `map_reduce` for parallel processing
7. **Rebalance regularly**: `pools rebalance` optimizes load distribution

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Pool not starting | Check `pools health --all` |
| Tasks failing | Check `pools stats --by-type` |
| High latency | Use `pools watch` to monitor |
| Memory issues | Check pool memory usage in Grafana |
| Pool degraded | Restart pool with `pools register` |

## Getting Help

```bash
# General help
mahavishnu pools --help

# Command help
mahavishnu pools execute --help

# Full documentation
cat docs/DISTRIBUTED_POOL_CLI.md
```

## Related Documentation

- [Complete CLI Reference](DISTRIBUTED_POOL_CLI.md)
- [Pool Architecture](POOL_ARCHITECTURE.md)
- [Grafana Dashboard](mahavishnu/integrations/grafana/pool_dashboard.json)
