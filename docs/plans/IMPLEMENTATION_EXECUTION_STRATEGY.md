# Implementation Execution Strategy

**Date**: 2026-04-02
**Purpose**: Parallel execution strategy using Mahavishnu's own orchestration features
**Related**: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`

## Overview

This strategy **dogfoods Mahavishnu's pool orchestration** to implement the Storage Consolidation plan. We spawn specialized worker pools that execute workstreams in parallel, coordinated via WebSocket events and MessageBus.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     MAHAVISHNU ORCHESTRATION LAYER                      │
│  ┌─────────────┐  ┌──────────────────┐  ┌────────────────────────────┐ │
│  │ PoolManager │  │ WebSocket Server │  │ MessageBus (inter-pool)    │ │
│  │ (router)    │  │ :8690 (events)   │  │ pub/sub coordination      │ │
│  └──────┬──────┘  └────────┬─────────┘  └─────────────┬──────────────┘ │
└─────────┼──────────────────┼──────────────────────────┼────────────────┘
          │                  │                          │
    ┌─────▼──────────────────▼──────────────────────────▼─────┐
    │              PARALLEL WORKSTREAM POOLS                   │
    ├─────────────────┬─────────────────┬─────────────────────┤
    │   POOL-SCHEMA   │   POOL-REPO     │   POOL-DECOUPLE     │
    │   (2 workers)   │   (2 workers)   │   (2 workers)       │
    ├─────────────────┼─────────────────┼─────────────────────┤
    │ W1: Migrations  │ W1: Interfaces  │ W1: Akosha deps     │
    │ W2: Constraints │ W2: Feature flg │ W2: Enum cleanup    │
    └─────────────────┴─────────────────┴─────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   SHARED STATE    │
                    │ (PostgreSQL,      │
                    │  Feature Flags)   │
                    └───────────────────┘
```

## Workstream Definitions

### Workstream A: Schema Foundation (`pool-schema`)

**Pool ID**: `pool-schema`
**Workers**: 2
**Duration**: ~3 days
**Blocking**: None (can start immediately)

| Worker | Task | Description |
|--------|------|-------------|
| `schema-1` | Create migration baseline | V202604021200__initial_schemas.sql |
| `schema-2` | Add CHECK constraints | Status/priority enum enforcement |

**Deliverables**:
- `migrations/versions/V202604021200__initial_schemas.sql`
- `migrations/versions/V202604021300__enum_constraints.sql`
- Schema validation tests

**Dependencies**: None

### Workstream B: Repository Layer (`pool-repo`)

**Pool ID**: `pool-repo`
**Workers**: 2
**Duration**: ~4 days
**Blocking**: Waits for `pool-schema` migrations

| Worker | Task | Description |
|--------|------|-------------|
| `repo-1` | Repository interfaces | TaskRepository, RunRepository, etc. |
| `repo-2` | Feature flag infrastructure | `PERSISTENCE_WRITE_MODE`, `PERSISTENCE_READ_SOURCE` |

**Deliverables**:
- `mahavishnu/persistence/repositories/` (interfaces)
- `mahavishnu/core/feature_flags.py` (cutover flags)
- Integration tests

**Dependencies**: `pool-schema` migrations complete

### Workstream C: Akosha Decoupling (`pool-decouple`)

**Pool ID**: `pool-decouple`
**Workers**: 2
**Duration**: ~2 days
**Blocking**: None (can start immediately)

| Worker | Task | Description |
|--------|------|-------------|
| `decouple-1` | Remove Akosha from critical deps | Update health config, startup |
| `decouple-2` | Complete enum consolidation | Migrate remaining local enums |

**Deliverables**:
- Updated `settings/mahavishnu.yaml` (Akosha optional)
- Updated health check configuration
- Enum migration complete

**Dependencies**: None

## Execution Timeline

```
Day 1-2:  [pool-schema] ──────┐
          [pool-decouple] ────┼──> Parallel execution
                               │
Day 3:    [pool-schema] ──────┤
          [pool-decouple] ────┘
                               │
Day 3-4:  [pool-repo] <────────┘ (waits for schema)
                               │
Day 5-6:  [pool-repo] ──────────┘
```

## Pool Configuration

```yaml
# Orchestration pool configuration
pools:
  pool-schema:
    type: mahavishnu
    min_workers: 2
    max_workers: 2
    worker_type: terminal-claude
    affinity: schema-migrations

  pool-repo:
    type: mahavishnu
    min_workers: 2
    max_workers: 2
    worker_type: terminal-claude
    affinity: repository-layer

  pool-decouple:
    type: mahavishnu
    min_workers: 2
    max_workers: 2
    worker_type: terminal-claude
    affinity: dependency-decoupling
```

## Coordination Protocol

### WebSocket Events

```python
# Pool status broadcasts
{
    "type": "pool_status",
    "pool_id": "pool-schema",
    "status": "working|blocked|completed",
    "progress": {"completed": 1, "total": 2}
}

# Dependency notifications
{
    "type": "dependency_satisfied",
    "dependent_pool": "pool-repo",
    "dependency_pool": "pool-schema",
    "task": "migrations_complete"
}

# Cutover readiness
{
    "type": "cutover_ready",
    "pools_ready": ["pool-schema", "pool-repo", "pool-decouple"],
    "feature_flags": {
        "PERSISTENCE_WRITE_MODE": "dual",
        "PERSISTENCE_READ_SOURCE": "legacy"
    }
}
```

### MessageBus Topics

| Topic | Purpose |
|-------|---------|
| `pool.schema.progress` | Migration progress updates |
| `pool.repo.progress` | Repository implementation progress |
| `pool.decouple.progress` | Decoupling progress |
| `orchestration.sync` | Cross-pool synchronization |
| `orchestration.cutover` | Cutover coordination |

## Feature Flag Configuration

```python
# mahavishnu/core/feature_flags.py

class PersistenceMode(StrEnum):
    DUAL = "dual"        # Write to both, read from legacy
    LEGACY = "legacy"    # Use old storage only
    POSTGRES = "postgres"  # Use new PostgreSQL storage


class PersistenceFeatureFlags:
    """Feature flags for storage consolidation cutover."""

    WRITE_MODE: PersistenceMode = PersistenceMode.DUAL
    READ_SOURCE: str = "legacy"  # legacy | postgres

    # Per-component overrides
    TASK_STORE_WRITE: PersistenceMode | None = None
    SEARCH_WRITE: PersistenceMode | None = None
    EVENT_WRITE: PersistenceMode | None = None

    @classmethod
    def get_write_mode(cls, component: str) -> PersistenceMode:
        """Get write mode for component with override support."""
        override = getattr(cls, f"{component.upper()}_WRITE", None)
        return override or cls.WRITE_MODE
```

## Rollback Procedure

1. **Immediate rollback**: Set `PERSISTENCE_READ_SOURCE=legacy`, restart services
2. **Data reconciliation**: Run consistency validator
3. **Recovery**: Replay event backlog if needed

## Monitoring & Observability

### Grafana Dashboard Panels

1. Pool worker utilization per workstream
2. Migration execution progress
3. Feature flag state
4. WebSocket event throughput
5. Cross-pool message latency

### Alerts

- `pool_blocked`: Pool waiting on dependency > 30 minutes
- `migration_failed`: Migration execution error
- `cutover_validation_failed`: Consistency check failed

## Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| Schema migrations complete | All migrations applied, tests pass |
| Repository interfaces complete | All CRUD operations implemented |
| Akosha optional | Mahavishnu starts without Akosha |
| Feature flags working | Can toggle between dual/legacy/postgres |
| Zero data loss | Consistency validator passes |
| Rollback tested | Rollback procedure executed successfully |

## Implementation Commands

```bash
# 1. Spawn orchestration pools
mahavishnu pool spawn --type mahavishnu --name schema --min 2 --max 2
mahavishnu pool spawn --type mahavishnu --name repo --min 2 --max 2
mahavishnu pool spawn --type mahavishnu --name decouple --min 2 --max 2

# 2. Execute workstreams in parallel
mahavishnu pool execute pool-schema --prompt "Execute Workstream A: Schema Foundation"
mahavishnu pool execute pool-decouple --prompt "Execute Workstream C: Akosha Decoupling"

# 3. After schema complete, execute repo workstream
mahavishnu pool execute pool-repo --prompt "Execute Workstream B: Repository Layer"

# 4. Monitor progress
mahavishnu pool health
mahavishnu monitor pools

# 5. Validate cutover readiness
mahavishnu validate cutover-readiness

# 6. Execute cutover (with rollback ready)
mahavishnu cutover execute --mode dual --rollback-timeout 300
```

## Next Steps

1. **Create migration baseline** (`pool-schema/worker-1`)
2. **Remove Akosha from critical deps** (`pool-decouple/worker-1`)
3. **Define repository interfaces** (`pool-repo/worker-1`)
