# Top 10 Workflows — Selection & Baseline Metrics

**Version**: 1.0.0
**Date**: 2026-04-05
**Initiative**: I12-1
**Scope**: Mahavishnu orchestration flows and MCP tool surfaces

## Selection Criteria

Workflows are ranked by:

1. **Integration depth** — touches adapters, pools, workers, or external services
1. **Operator exposure** — exposed via MCP tools or CLI commands
1. **Data path complexity** — number of components involved
1. **Failure surface** — where things break in production

## Top 10 Workflows

### 1. Workflow Trigger & Parallel Execution

**MCP tool**: `trigger_workflow`
**Code path**: `server_core.py:379` → `app.execute_workflow_parallel()` → adapter `execute()`
**Adapters**: langgraph, prefect, agno
**Task types**: `code_sweep`, `quality_check`

**Flow**:

```
trigger_workflow(adapter, task_type, repos)
  → resolve repos (tag filter or explicit list)
  → create task spec {type, params, id}
  → execute_workflow_parallel(task, adapter, repos)
    → for each repo: adapter.execute(task, [repo])
    → collect results, aggregate errors
  → return {workflow_id, status, repos_processed, errors}
```

**Baseline metrics**: No current instrumentation on execution time or per-repo success rate. Workflow ID is generated but not tracked post-return.

______________________________________________________________________

### 2. Code Sweep

**MCP tool**: `trigger_workflow(adapter, task_type="code_sweep", ...)`
**Implementations**: `prefect_adapter_impl.py:126`, `agno_adapter_impl.py:1197`
**What it does**: AI-driven code analysis across repositories

**Flow**:

```
trigger_workflow("agno", "code_sweep", repos)
  → AgnoAdapter.execute({type: "code_sweep"}, repos)
    → per repo: code analysis prompt → AI agent → structured findings
  → aggregate findings across repos
```

**Baseline metrics**: Execution time varies by repo size. No p50/p95 baseline captured.

______________________________________________________________________

### 3. Quality Check

**MCP tool**: `trigger_workflow(adapter, task_type="quality_check", ...)`
**Implementations**: `prefect_adapter_impl.py:180`, `agno_adapter_impl.py:1204`
**What it does**: Quality assurance evaluation of repository code

**Flow**:

```
trigger_workflow("agno", "quality_check", repos)
  → AgnoAdapter.execute({type: "quality_check"}, repos)
    → per repo: quality evaluation prompt → AI agent → quality report
  → aggregate quality reports
```

**Baseline metrics**: Not tracked separately from workflow trigger metrics.

______________________________________________________________________

### 4. Workflow Healing

**MCP tool**: `heal_workflows`
**Code path**: `server_core.py:1079`
**What it does**: Auto-retry or recover failed workflows from dead letter queue

**Flow**:

```
heal_workflows()
  → app.dead_letter_queue.get_all()
  → for each failed task: re-execute with original params
  → record recovery results
  → return {healed, failed, skipped}
```

**Baseline metrics**: Recovery success rate not tracked. DLQ size is the only indicator.

______________________________________________________________________

### 5. Fix Orchestration (with Quality Gates)

**Code path**: `core/fix_orchestrator.py:90` → pool → quality gates
**What it does**: Execute code fixes via worker pools with automated quality validation

**Flow**:

```
FixOrchestrator.execute_fix(pool_id, FixTask)
  → pool_manager.execute_on_pool(prompt, issue_id, files)
    → worker executes fix
  → _run_quality_gates() (fast_hooks, tests, comprehensive, coverage)
  → if blocking failure: return early with gate results
  → _update_issue_status() (coordination tracking)
  → return FixResult {success, stage, quality_gates, changes}
```

**Baseline metrics**: Quality gates currently return mock data (TODO at line 192). No real gate metrics yet.

______________________________________________________________________

### 6. Adapter Resolution & Routing

**MCP tool**: `adapter_resolve`
**Code path**: `adapter_registry_tools.py:86` → `TaskRouter.route_task()`
**What it does**: Select the best adapter for a given task based on capabilities and performance

**Flow**:

```
adapter_resolve(task_type, required_capabilities)
  → ResolutionCache.check(task_type, caps)  [TTL 300s]
  → CapabilityRouter.resolve(task_type, caps)
    → score adapters by capability match + historical success rate
    → return best adapter with confidence
  → cache result
```

**Baseline metrics**: ResolutionCache hit/miss tracked. RoutingMetrics exposes success rates and latency scores. No p95 baseline.

______________________________________________________________________

### 7. Backup & Restore

**MCP tools**: `create_backup`, `restore_backup`, `list_backups`
**Code path**: `server_core.py` → backup manager
**What it does**: System state backup and disaster recovery

**Flow**:

```
create_backup(backup_type="full")
  → snapshot config, repo registry, coordination state
  → persist to backup storage
  → return {backup_id, status, size}

restore_backup(backup_id)
  → validate backup integrity
  → restore config, repos, coordination
  → return {status, restored_components}
```

**Baseline metrics**: Backup duration and size not tracked. No backup health check.

______________________________________________________________________

### 8. Pool Execution (Task Routing)

**MCP tools**: `pool_spawn`, `pool_execute`, `pool_route_execute`
**Code path**: `pool_tools.py` → `PoolManager` → worker pools
**What it does**: Spawn worker pools and route AI tasks with load balancing

**Flow**:

```
pool_route_execute(prompt, selector="least_loaded")
  → PoolManager.select_pool(selector)
    → check pool health, worker availability
    → route to pool with lowest load
  → pool.execute(prompt, timeout)
    → dispatch to available worker
    → collect result
  → return {pool_id, output, duration}
```

**Baseline metrics**: Pool monitor exposes active workers, task queue depth. No execution time baseline.

______________________________________________________________________

### 9. Health Check & Readiness

**MCP tools**: `get_health`, `get_liveness`, `get_readiness`, `health_check_all`, `health_check_service`
**Code path**: `health_tools.py` → dependency health endpoints
**What it does**: System health verification for operator dashboards and load balancers

**Flow**:

```
health_check_all()
  → for each configured dependency:
    → HTTP GET /health with timeout
    → record {status, latency, error}
  → aggregate: all healthy / degraded / unhealthy
  → return {status, services: {name: {status, latency}}}

get_readiness()
  → check all required dependencies healthy
  → return {ready: bool, dependencies: {...}}
```

**Baseline metrics**: Health check latency tracked per service. No alerting on degradation trends.

______________________________________________________________________

### 10. Review & Auto-Fix (Self-Improvement)

**MCP tool**: `review_and_fix`
**Code path**: `self_improvement_tools.py:418` → `ReviewEngine._run_review()` → `_auto_fix()`
**What it does**: Automated code review with optional auto-fix for issues

**Flow**:

```
review_and_fix(scope="critical", auto_fix=True, dry_run=False)
  → ReviewEngine._run_review(scope)
    → scan codebase for issues (security, performance, quality, critical)
    → collect findings with severity and location
  → if auto_fix: ReviewEngine._auto_fix(findings)
    → apply fixes for safe, deterministic issues
    → track changes made
  → return {findings_count, fixes_applied, errors}
```

**Baseline metrics**: Findings count tracked per review. No trend analysis over time.

______________________________________________________________________

## Baseline Metrics Summary

| # | Workflow | Latency Baseline | Success Rate Baseline | Observability |
|---|----------|-----------------|-----------------------|---------------|
| 1 | Workflow Trigger | Not tracked | Not tracked | Workflow ID only |
| 2 | Code Sweep | Not tracked | Not tracked | Adapter logs |
| 3 | Quality Check | Not tracked | Not tracked | Adapter logs |
| 4 | Workflow Healing | Not tracked | DLQ size | DLQ depth |
| 5 | Fix Orchestration | Not tracked | Mock (100%) | Quality gates TODO |
| 6 | Adapter Routing | ~300s cache TTL | Per-adapter stats | RoutingMetrics |
| 7 | Backup & Restore | Not tracked | Not tracked | Backup ID only |
| 8 | Pool Execution | Not tracked | Not tracked | Pool monitor |
| 9 | Health Check | Per-service latency | Binary pass/fail | Health dashboard |
| 10 | Review & Auto-Fix | Not tracked | Findings count | Review results |

## Gaps Identified

1. **No end-to-end latency tracking** — only adapter routing has any timing data
1. **No success rate aggregation** — individual adapters track stats but no cross-workflow view
1. **Quality gates are mocked** — FixOrchestrator returns placeholder data
1. **No workflow lifecycle tracking** — workflow IDs are generated but not persisted or queried
1. **Health checks are point-in-time** — no trend detection or degradation alerting

## Recommended Next Steps (I12-2)

1. Add `workflow_duration_seconds` histogram to workflow trigger path
1. Persist workflow lifecycle (created → running → completed/failed) with timestamps
1. Wire real quality gate integration into FixOrchestrator
1. Add success rate metrics to pool execution
1. Define canonical CLI pathways for each workflow
