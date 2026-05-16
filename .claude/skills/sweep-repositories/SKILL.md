______________________________________________________________________

## name: sweep-repositories description: Use when executing workflow sweeps across multiple repositories. Use when user asks to apply workflows, run sweeps, or orchestrate tasks across multiple repos by tag, role, or capability. Use when coordinated multi-repository operations are needed.

# Sweep Repositories

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| mahavishnu | 8680 | summary | mcp\_\_mahavishnu\_\_list_repos, mcp\_\_mahavishnu\_\_trigger_workflow | 60s |

A sweep executes a workflow across multiple target repositories, aggregating results for analysis. This skill guides you through selecting targets, choosing the adapter, and executing sweeps efficiently.

**Core principle:** Target repositories precisely using role/tag filters to minimize failed executions.

## When to Use

**Use when:**

- User asks to "sweep repos", "run across all backends", "apply to all python repos"
- Coordinated workflow execution across multiple repositories needed
- User needs to aggregate results from multiple repositories
- Bulk operations on repositories (testing, documentation, refactoring)

**Don't use when:**

- Single repository workflow (use `orchestrate-workflow`)
- Pool management (use `manage-pools`)
- Repository discovery without execution (use `find-capability`)

## Quick Reference

```bash
# 1. Discover targets
mahavishnu list-repos --role app
mahavishnu list-repos --tag python

# 2. Execute sweep
mahavishnu sweep --role app --adapter llamaindex
mahavishnu sweep --tag python --adapter llamaindex

# 3. Combine filters
mahavishnu sweep --tag backend --tag ml --adapter llamaindex

# 4. View sweep status
mahavishnu sweep-status <sweep_id>
```

## Implementation

### Step 1: Identify Target Repositories

**By Role (Recommended):**

```bash
# End-user applications
mahavishnu list-repos --role app

# Backend services
mahavishnu list-repos --role backend

# All MCP tools
mahavishnu list-repos --role tool
```

**By Tag:**

```bash
# Python repositories
mahavishnu list-repos --tag python

# Multiple tags
mahavishnu list-repos --tag backend --tag api
```

**Via MCP:**

```python
repos = await mcp.call_tool("mcp__mahavishnu__list_repos", {
    "role": "app",
    "tags": ["python"]
})
```

### Step 2: Choose Adapter

| Task Type | Recommended Adapter | Status |
|-----------|---------------------|--------|
| RAG pipelines, document processing | `llamaindex` | ✅ Production-ready |
| Complex DAG orchestration | `prefect` | ⚠️ Stub only |
| Agent-based workflows | `agno` | ⚠️ Stub only |

**Verify adapter availability:**

```bash
mahavishnu mcp status
```

### Step 3: Execute Sweep

**CLI:**

```bash
# Basic sweep
mahavishnu sweep --role app --adapter llamaindex

# With parameters
mahavishnu sweep \
  --tag python \
  --adapter llamaindex \
  --param workflow_type=rag_pipeline \
  --param query="analyze API patterns"
```

**Via MCP:**

```python
sweep_id = await mcp.call_tool("mcp__mahavishnu__trigger_workflow", {
    "repo": "*",  # Sweep across discovered repos
    "adapter": "llamaindex",
    "filters": {
        "role": "app",
        "tags": ["python"]
    },
    "params": {
        "workflow_type": "rag_pipeline",
        "query": "user query here"
    }
})
```

### Step 4: Monitor Progress

```python
# Check sweep status
status = await mcp.call_tool("mcp__mahavishnu__get_workflow_status", {
    "workflow_id": sweep_id
})

# Status includes:
# - Total repositories
# - Completed/Failed/In-progress counts
# - Per-repository results
# - Aggregated output
```

### Step 5: Aggregate Results

```python
# Get sweep results
results = await mcp.call_tool("mcp__mahavishnu__search_workflows", {
    "query": f"sweep:{sweep_id}"
})

# Results include:
# - Success/failure summary
# - Per-repository outputs
# - Errors and warnings
# - Performance metrics
```

## Sweep Strategies

### Parallel Execution (Default)

```yaml
execution_mode: parallel
max_concurrent: 10  # Limit concurrent workflows
```

**Use for:** Independent workflows, I/O-bound tasks

### Sequential Execution

```yaml
execution_mode: sequential
```

**Use for:** Resource-intensive tasks, dependencies between repos

### Batched Execution

```yaml
execution_mode: batched
batch_size: 5
delay_between_batches: 30  # seconds
```

**Use for:** Rate limiting, API quotas

## Validation Checklist

Before sweep:

- [ ] Adapter enabled and healthy
- [ ] Target repositories identified (preview count)
- [ ] Workflow parameters validated
- [ ] Pool capacity available (if using pools)
- [ ] Execution strategy configured

After sweep:

- [ ] Review per-repository results
- [ ] Check failure rate (target: \<5%)
- [ ] Verify aggregated output completeness
- [ ] Document errors and warnings
- [ ] Archive sweep results for reference

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Sweeping all repositories** | High failure rate (>30%), slow execution | Use role/tag filters to target appropriately |
| **Wrong adapter for task** | Workflow not supported, fails immediately | Match task to adapter capabilities |
| **Not previewing targets** | Executing on unexpected repositories | Always `list-repos` first to verify targets |
| **Ignoring pool capacity** | Tasks timeout, pool exhaustion | Check pool health before sweep |
| **Not aggregating results** | Incomplete data from sweep | Always retrieve and review sweep results |

## Real-World Impact

**Before this skill:**

- Sweeps executed on all repos → 45% failure rate
- No filtering → 20-minute execution time
- Manual result aggregation → data loss

**After this skill:**

- Targeted sweeps → 95% success rate
- Role-based filtering → 3-minute execution time
- Automatic aggregation → complete results

## Example Workflows

**Document Generation Sweep:**

```bash
# Generate README.md for all app repos
mahavishnu sweep \
  --role app \
  --adapter llamaindex \
  --param workflow_type=document_generation \
  --param output_file=README.md
```

**Testing Sweep:**

```bash
# Run tests across all backend services
mahavishnu sweep \
  --role backend \
  --adapter llamaindex \
  --param workflow_type=test_execution \
  --param test_type=integration
```

**Refactoring Sweep:**

```bash
# Apply type hints to all python repos
mahavishnu sweep \
  --tag python \
  --adapter llamaindex \
  --param workflow_type=refactor \
  --param refactor_type=add_type_hints
```

## Related Skills

- **REQUIRED:** `orchestrate-workflow` - Sweeps are coordinated multi-repo workflows
- **REQUIRED:** `find-capability` - For discovering target repositories
- **REQUIRED:** `manage-pools` - For pool-backed sweep execution

## Related Documentation

- MCP Tools Specification - Complete tool reference
- Pool Architecture - Pool-based sweep execution
