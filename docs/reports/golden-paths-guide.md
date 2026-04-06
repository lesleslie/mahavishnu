# Golden Paths Guide

**Version**: 1.0.0  
**Date**: 2026-04-05  
**Initiative**: I12-3  
**Scope**: Canonical CLI and MCP pathways for top workflows

## Overview

Golden paths are the recommended ways to invoke Mahavishnu workflows. Each
top-10 workflow has exactly **one CLI command** and **one MCP tool** as its
canonical entry point. Internal Python APIs still work but emit guidance
pointing to these canonical pathways.

**Why golden paths?** Canonical pathways guarantee:
- Consistent logging, metrics, and error handling
- Documented, versioned interfaces
- Forward-compatible upgrades (internal APIs may change; CLI/MCP contracts are stable)

---

## Top 10 Workflows — Canonical Pathways

### 1. Workflow Trigger & Parallel Execution

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow sweep --adapter <name> [--repos ...]` |
| **MCP** | `trigger_workflow(adapter, task_type, repos)` |

Internal API: `MahavishnuApp.execute_workflow_parallel()` — use only from
canonical CLI/MCP layers.

### 2. Code Sweep

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow sweep --adapter <name> [--repos ...]` |
| **MCP** | `trigger_workflow(adapter, "code_sweep", repos)` |

### 3. Quality Check

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow quality-check --adapter <name> [--repos ...]` |
| **MCP** | `trigger_workflow(adapter, "quality_check", repos)` |

### 4. Workflow Healing

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow heal` |
| **MCP** | `heal_workflows()` |

Internal API: `DeadLetterQueue.retry_task()` — use only from canonical layers.

### 5. Fix Orchestration (with Quality Gates)

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow fix --pool-id <id> --prompt <prompt>` |
| **MCP** | `pool_execute(pool_id, prompt)` (via pool tools) |

Internal API: `FixOrchestrator.execute_fix()` — use only from canonical layers.

### 6. Adapter Resolution & Routing

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu adapter resolve --task-type <type> --capabilities <caps>` |
| **MCP** | `adapter_resolve(task_type, required_capabilities)` |

Internal API: `HybridAdapterRegistry.resolve()` — use only from canonical layers.

### 7. Backup & Restore

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu backup create [--type full\|incremental\|config]` |
| **MCP** | `create_backup(backup_type)` / `restore_backup(backup_id)` |

Internal APIs: `BackupManager.create_backup()` / `restore_backup()`.

### 8. Pool Execution (Task Routing)

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow fix --pool-id <id>` (uses pool execution) |
| **MCP** | `pool_route_execute(prompt, pool_selector)` / `pool_execute(pool_id, prompt)` |

### 9. Health Check & Readiness

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu mcp health` |
| **MCP** | `get_health()` / `get_readiness()` / `health_check_all()` |

Internal API: `HybridAdapterRegistry.check_all_health()` — use only from canonical layers.

### 10. Review & Auto-Fix (Self-Improvement)

| Channel | Command |
|---------|---------|
| **CLI** | `mahavishnu workflow review [--scope critical\|all] [--auto-fix] [--dry-run]` |
| **MCP** | `review_and_fix(scope, auto_fix, dry_run)` |

Internal API: `SelfImprovementTools.review_and_fix()` — use only from canonical layers.

---

## CLI Quick Reference

```
# Workflows
mahavishnu workflow sweep --adapter agno --tag python
mahavishnu workflow quality-check --adapter langgraph --repos repo1 repo2
mahavishnu workflow heal
mahavishnu workflow fix --pool-id pool_abc --prompt "Fix the auth bug"
mahavishnu workflow review --scope all --auto-fix

# Adapters
mahavishnu adapter list [--domain orchestration]
mahavishnu adapter resolve --task-type workflow --capabilities execute
mahavishnu adapter health [--name agno]

# System
mahavishnu mcp health
mahavishnu mcp status
mahavishnu backup create --type full
mahavishnu backup restore --id backup_20260405_120000
```

---

## Non-Canonical Usage Warnings

Internal Python APIs (in `mahavishnu/core/`) now include **docstring notices**
pointing to the canonical pathway. These are informational — the APIs continue
to work — but direct usage outside the CLI/MCP layers is discouraged because:

1. **No guaranteed stability** — internal APIs may change between minor versions
2. **Missing observability** — bypassing canonical layers skips metrics and tracing
3. **Inconsistent error handling** — canonical layers add structured error responses

### Affected Internal APIs

| Module | Method | Canonical Alternative |
|--------|--------|-----------------------|
| `core/app.py` | `MahavishnuApp.execute_workflow_parallel()` | CLI: `workflow sweep` / MCP: `trigger_workflow` |
| `core/fix_orchestrator.py` | `FixOrchestrator.execute_fix()` | CLI: `workflow fix` / MCP: `pool_execute` |
| `core/dead_letter_queue.py` | `DeadLetterQueue.retry_task()` | CLI: `workflow heal` / MCP: `heal_workflows` |
| `core/adapter_registry.py` | `HybridAdapterRegistry.resolve()` | CLI: `adapter resolve` / MCP: `adapter_resolve` |
| `core/adapter_registry.py` | `HybridAdapterRegistry.list_adapters()` | CLI: `adapter list` / MCP: `adapter_list` |
| `core/adapter_registry.py` | `HybridAdapterRegistry.check_all_health()` | CLI: `adapter health` / MCP: `adapter_health` |
| `core/backup_recovery.py` | `BackupManager.create_backup()` | CLI: `backup create` / MCP: `create_backup` |
| `core/backup_recovery.py` | `BackupManager.restore_backup()` | CLI: `backup restore` / MCP: `restore_backup` |
| `mcp/tools/self_improvement_tools.py` | `SelfImprovementTools.review_and_fix()` | CLI: `workflow review` / MCP: `review_and_fix` |

---

## Adding a New Golden Path

When introducing a new high-value workflow:

1. **Add a CLI command** in `_main_cli.py` under the appropriate sub-app
2. **Add an MCP tool** in `mahavishnu/mcp/tools/` and register in `server_core.py`
3. **Add a golden-path docstring notice** to the underlying internal API method
4. **Update this guide** with the new entry
5. **Add a test** in `tests/unit/test_workflow_cli.py` (AST-based)

---

## Related Documentation

- **Initiative plan**: `docs/plans/initiatives/12-golden-paths-workflows.md`
- **Baseline metrics**: `docs/reports/top-10-workflows-baseline.md`
- **Deprecation guide**: `docs/reports/deprecation-migration.md`
