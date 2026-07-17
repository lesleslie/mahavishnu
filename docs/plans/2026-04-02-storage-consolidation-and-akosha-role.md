---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: storage-consolidation
---

# Storage Consolidation And Akosha Role Plan

**Date**: 2026-04-02
**Status**: Proposed  <!-- legacy status: Proposed — see YAML frontmatter -->
**Scope**: `mahavishnu`, `akosha`, `session-buddy`, `bodai`

## Plan Workflow Integration (2026-04-02)

This plan is now the primary workflow anchor for storage, retrieval, and cross-system intelligence boundaries.

Items from earlier plans that are carried forward into this workflow:

1. Adaptive routing metrics and learning loops:
   - Keep `ExecutionTracker`, statistical routing, cost optimization, and A/B testing.
   - Change persistence target from Dhara-style metrics storage to PostgreSQL tables owned by Mahavishnu.
1. Self-improvement workflow:
   - Keep review/fix orchestration and approval workflows.
   - Replace placeholder quality and coordination integrations with real service integrations.
   - Persist findings, approvals, and fix events in Mahavishnu PostgreSQL event/search schemas.
1. Status enum consolidation:
   - Keep as an enabling refactor.
   - Complete migration to `mahavishnu/core/status.py` before broad persistence cutover to reduce state drift.
1. Health dependency behavior:
   - Keep health-check architecture.
   - Update startup dependency policy so Akosha is optional for core Mahavishnu operation.

Items treated as secondary or out-of-scope for this workflow:

1. Prefect adapter expansion beyond currently required capability.
1. TLS/WebSocket ecosystem hardening tasks outside storage and persistence critical path.

## Supersession Matrix

- `docs/plans/2025-02-11-adaptive-router-feedback-loops.md`
  - Partially superseded for storage target assumptions only.
  - Routing and learning objectives remain active.
- `docs/plans/2026-02-20-self-improvement-implementation.md`
  - Partially superseded for persistence/integration assumptions.
  - Core self-improvement objectives remain active.
- `docs/plans/2026-02-20-status-enum-consolidation.md`
  - Not superseded. Explicitly pulled into this workflow as a prerequisite refactor.
- `docs/plans/PREFECT_ADAPTER_COMPLETION_PLAN.md`
  - Not superseded. Reprioritized behind storage consolidation.
- `docs/plans/TLS_IMPLEMENTATION_SUMMARY.md`
  - Historical summary with remaining items not on this workflow's critical path.

## Summary

This plan consolidates operational persistence and semantic search into a single PostgreSQL system with the `pgvector` extension enabled, with `Mahavishnu` as the primary owner of writes, schema, and lifecycle state.

It also redefines `Akosha` as an optional ecosystem intelligence layer rather than a critical-path persistence service.

## Decisions

### Primary Decisions

1. `Mahavishnu` owns operational persistence.
1. `Mahavishnu` owns primary search persistence.
1. `PostgreSQL + pgvector` is one logical database system, not two systems.
1. `Session-Buddy` remains best-effort and asynchronous for context/history.
1. `Akosha` is removed from the critical storage path.

### Why

- The orchestrator should own the lifecycle data it creates.
- Splitting source-of-truth writes across `Mahavishnu` and `Akosha` creates dual-write complexity.
- `pgvector` already covers vector search inside PostgreSQL.
- `Session-Buddy` is useful as context memory, but not as required transactional storage.
- `Akosha` is more valuable as a derived intelligence service than as a primary database.

## Target Architecture

### Ownership

- `Mahavishnu`

  - tasks
  - task runs
  - dependencies
  - events
  - searchable documents
  - embeddings
  - hybrid search APIs

- `Session-Buddy`

  - session context
  - conversation history
  - assistant-facing memory
  - best-effort mirrored writes only

- `Akosha`

  - analytics
  - pattern detection
  - cross-system aggregation
  - federated search and reranking

## PostgreSQL And pgvector

### Clarification

`pgvector` is a PostgreSQL extension. The recommended design is:

- one PostgreSQL cluster
- `pgvector` enabled in that cluster
- separate schemas/tables for operational and search concerns

This is not a separate vector database architecture unless proven necessary later by scale or performance.

## Concrete Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS orchestration;
CREATE SCHEMA IF NOT EXISTS search;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS integration;

CREATE TABLE orchestration.tasks (
    id UUID PRIMARY KEY,
    external_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    repository TEXT,
    pool_name TEXT,
    worker_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    created_by TEXT,
    assigned_to TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_tasks_status ON orchestration.tasks (status);
CREATE INDEX idx_tasks_repository ON orchestration.tasks (repository);
CREATE INDEX idx_tasks_assigned_to
ON orchestration.tasks (assigned_to)
WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_tasks_created_at ON orchestration.tasks (created_at DESC);
CREATE INDEX idx_tasks_metadata_gin ON orchestration.tasks USING gin (metadata);

CREATE TABLE orchestration.task_runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    run_number INT NOT NULL,
    pool_name TEXT,
    worker_id TEXT,
    worker_type TEXT,
    engine TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    exit_code INT,
    error_message TEXT,
    result_summary TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (task_id, run_number)
);

CREATE INDEX idx_task_runs_task_id ON orchestration.task_runs (task_id);
CREATE INDEX idx_task_runs_status ON orchestration.task_runs (status);
CREATE INDEX idx_task_runs_started_at ON orchestration.task_runs (started_at DESC);

CREATE TABLE orchestration.task_dependencies (
    task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL DEFAULT 'blocks'
        CHECK (dependency_type IN ('blocks', 'requires', 'relates_to')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE TABLE audit.task_events (
    id BIGSERIAL,
    task_id UUID REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    run_id UUID REFERENCES orchestration.task_runs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, event_time)
) PARTITION BY RANGE (event_time);

CREATE TABLE audit.task_events_default
    PARTITION OF audit.task_events DEFAULT;

CREATE TABLE audit.task_events_2026_04
    PARTITION OF audit.task_events
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX idx_task_events_task_id ON audit.task_events (task_id);
CREATE INDEX idx_task_events_run_id ON audit.task_events (run_id);
CREATE INDEX idx_task_events_type_time ON audit.task_events (event_type, event_time DESC);
CREATE INDEX idx_task_events_payload_gin ON audit.task_events USING gin (payload);

CREATE TABLE search.documents (
    id UUID PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id UUID,
    source_key TEXT,
    title TEXT,
    content TEXT NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))
    ) STORED,
    repository TEXT,
    system_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_search_documents_source ON search.documents (source_type, source_id);
CREATE INDEX idx_search_documents_repo ON search.documents (repository);
CREATE INDEX idx_search_documents_tsv ON search.documents USING gin (content_tsv);
CREATE INDEX idx_search_documents_metadata_gin ON search.documents USING gin (metadata);

`search.documents.source_id` intentionally does not have a foreign key to `orchestration.tasks(id)`.
The table is polymorphic by design so documents can represent tasks, runs, reports, docs, and other searchable artifacts without forcing all sources into one ownership model.

CREATE TABLE search.document_embeddings (
    document_id UUID PRIMARY KEY REFERENCES search.documents(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    embedding_dim INT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_document_embeddings_hnsw
ON search.document_embeddings
USING hnsw (embedding vector_cosine_ops);

CREATE TABLE integration.session_context_links (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    session_buddy_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (sync_status IN ('pending', 'synced', 'failed', 'retrying', 'skipped')),
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_session_context_links_task_id ON integration.session_context_links (task_id);
CREATE INDEX idx_session_context_links_status ON integration.session_context_links (sync_status);
```

## Query Pattern

### Hybrid Search

```sql
SELECT
    d.id,
    d.source_type,
    d.title,
    d.content,
    1 - (e.embedding <=> $1::vector) AS semantic_score,
    ts_rank(d.content_tsv, plainto_tsquery('english', $2)) AS lexical_score
FROM search.documents d
JOIN search.document_embeddings e ON e.document_id = d.id
WHERE d.repository = COALESCE($3, d.repository)
ORDER BY
    ($4::float * (1 - (e.embedding <=> $1::vector))) +
    ($5::float * ts_rank(d.content_tsv, plainto_tsquery('english', $2))) DESC
LIMIT 20;
```

Default query-time weights:

- `$4 = 0.7` semantic
- `$5 = 0.3` lexical

## Retention And Partitioning Policy

1. Partition `audit.task_events` monthly by `event_time`.
1. Keep a rolling 12 months in primary storage by default.
1. Archive older partitions to object storage before detach/drop.
1. Add automated partition management (create next 2 months, retire expired partitions).
1. Use `pg_partman` where available; otherwise use a scheduled Mahavishnu maintenance job.
1. Track retention metrics with alerts.

## Embedding Model Strategy

1. v1 baseline uses `vector(384)` with explicit `model_name`.
1. If model dimension changes, add a model-specific embedding table and backfill asynchronously.
1. Keep reads behind repository interfaces so model migration does not break callers.
1. Validate recall/precision before switching default retrieval model.

## Runtime Connection Management

1. Use application-level pooling for Mahavishnu DB clients.
1. Use PgBouncer in transaction pooling mode for production deployments.
1. Standardize settings:
   - `pool_min_size`
   - `pool_max_size`
   - `pool_acquire_timeout_ms`
   - `pool_idle_timeout_ms`
1. Add alerts for pool saturation and connection errors.

## Migration And Backfill Strategy

1. Existing task data:
   - migrate task/task_run/task_event rows with idempotent scripts
   - preserve original identifiers and timestamps
1. Search documents:
   - backfill `search.documents` from current searchable artifacts
   - generate embeddings in background batches with checkpoints
   - tune batch size and checkpoint frequency during rollout based on DB latency, embedding throughput, and retry behavior
1. Cutover expectations:
   - no full downtime required
   - brief read-only window allowed only for final consistency verification if needed
1. Validation:
   - row-count parity checks
   - status distribution parity checks
   - search sample quality checks

## Rough Timeline Estimates

1. Phase 1: ~1 week
1. Phase 2: ~2 weeks
1. Phase 3: ~1 week
1. Phase 4: ~1 week for role correction and initial Akosha refactor
1. Phase 5: ~1 week including cutover rehearsal and validation
1. Phase 6: ~2 to 3 days

## Implementation Plan

```markdown
# PostgreSQL + pgvector Consolidation Plan

## Goal
Consolidate operational data and semantic search into one PostgreSQL system with pgvector, making Mahavishnu the primary persistence owner.

## Architecture Decisions
- PostgreSQL is the single source of truth.
- pgvector is enabled in the same PostgreSQL cluster.
- Mahavishnu writes all task/run/event/searchable-document records.
- Session-Buddy remains async/best-effort for conversational context.
- Akosha is removed from the critical storage path.
- Akosha is retained as an optional analytics and federated-search sidecar.
- Connection pooling is required in production.

## Phase 1: Foundation
1. Add PostgreSQL settings to Mahavishnu config.
2. Add migration support for PostgreSQL + pgvector.
   - Migration naming convention: `V{YYYYMMDDHHMM}__{description}.sql`
3. Create schemas:
   - orchestration
   - audit
   - search
   - integration
4. Add base repository layer in Mahavishnu for:
   - tasks
   - task_runs
   - task_dependencies
   - task_events
   - search_documents
   - embeddings
5. Add application pool settings and PgBouncer deployment profile.
6. Add migrations for status/priority `CHECK` constraints.

## Phase 2: Mahavishnu Persistence
1. Replace in-memory task/state storage with PostgreSQL repositories.
2. Write task lifecycle events to `audit.task_events`.
3. Persist worker execution summaries to `orchestration.task_runs`.
4. Add a search indexing service:
   - create `search.documents`
   - generate embeddings
   - store `search.document_embeddings`
5. Add hybrid search API in Mahavishnu.
6. Add configurable semantic/lexical weighting in the search API.

## Phase 3: Session-Buddy Integration
1. Change Session-Buddy integration to async mirror writes only.
2. Record sync state in `integration.session_context_links`.
3. Do not block task creation/execution on Session-Buddy availability.
4. Add retryable background sync job.

## Phase 4: Akosha Refactor
1. Remove Akosha as required dependency for Mahavishnu startup.
2. Adopt fixed role: Akosha is an optional analytics/reporting and federated-search service over PostgreSQL.
3. Initial retained capabilities only:
   - federated search and reranking
   - pattern detection for recurring failures and bottlenecks
4. Defer non-core capabilities until after cutover stabilization.
5. Point Akosha analytics at PostgreSQL event/search tables.
6. Remove mock MCP search and duplicated storage responsibility.
7. Stop treating Akosha as source-of-truth storage.

## Phase 5: Cutover
1. Enable dual-write from Mahavishnu:
   - PostgreSQL required
   - Session-Buddy best-effort
   - Akosha optional/off
2. Backfill existing task/run/event/search artifacts into PostgreSQL-owned schemas.
3. Validate:
   - task lifecycle
   - worker execution persistence
   - hybrid search quality
   - background Session-Buddy sync
4. Run data consistency checks between old/new paths.
5. Flip read-path feature flag to PostgreSQL.
6. Keep rollback feature flag active during stabilization window.
7. Remove obsolete storage pathways and docs after stabilization.

## Phase 5a: Rollback Procedure (Required)
1. Feature flags:
   - `PERSISTENCE_WRITE_MODE=dual|legacy|postgres`
   - `PERSISTENCE_READ_SOURCE=legacy|postgres`
2. Immediate rollback path:
   - set reads to `legacy`
   - set writes to `dual` or `legacy` depending on incident severity
   - restart affected services
3. Reconciliation:
   - rerun consistency validator
   - replay durable event backlog into PostgreSQL if needed
4. Exit criteria:
   - parity checks pass
   - error budget recovered
   - search quality restored to baseline

## Phase 6: Cleanup
1. Update architecture docs and ADRs.
2. Remove Akosha from critical-path health dependencies.
3. Remove or reduce duplicate memory/search configs.
4. Add dashboards for:
   - DB latency
   - embedding generation time
   - search latency
   - Session-Buddy sync failures
5. Finalize partition automation:
   - configure `pg_partman` if available
   - otherwise ship scheduled maintenance job for partition creation and retirement

## Deliverables
- PostgreSQL migrations
- Mahavishnu repository layer
- Hybrid search API
- Async Session-Buddy sync worker
- Akosha role reduction or refactor
- Updated docs and health checks
- rollback and reconciliation runbook
- data consistency validator scripts
```

## Mahavishnu Changes

### Add

- PostgreSQL config and validation
- migration support for PostgreSQL + `pgvector`
- repository layer for operational entities
- search indexing service
- embedding generation pipeline
- hybrid search APIs and tools
- background Session-Buddy sync worker

### Change

- replace any in-memory operational persistence with PostgreSQL
- make Akosha optional or remove it from startup-critical dependencies
- move primary search reads and writes into Mahavishnu
- update docs that still assume multi-system persistence

### Expected Outcome

`Mahavishnu` becomes the single owner of:

- operational data
- task lifecycle data
- search indexing and retrieval
- consistency guarantees

## Akosha Changes

### Remove From Critical Path

`Akosha` should no longer be responsible for:

- primary task persistence
- authoritative operational storage
- required startup dependencies for Mahavishnu

### Recommended New Role

`Akosha` becomes an ecosystem intelligence layer.

### Retained Responsibilities

- analytics
- event consumption
- pattern mining
- federated search and reranking

### Refactor Priorities

1. Remove or de-emphasize mocked storage ownership claims.
1. Stop presenting Akosha as a source-of-truth search store.
1. Add PostgreSQL-backed derived reads if retained.
1. Focus MCP APIs on higher-order intelligence rather than basic storage.

## Session-Buddy Impact

### What Changes

- `Session-Buddy` is no longer part of the required write path.
- Context and history writes become asynchronous.
- Failures in `Session-Buddy` should not fail task creation or task execution.

### What Does Not Change

- `Session-Buddy` still remains useful for assistant context and session history.
- It does not need to become a transactional task database.
- It does not need to own operational task state.

### Recommended Integration Pattern

1. Write task and run data to PostgreSQL synchronously.
1. Queue async context write to `Session-Buddy`.
1. Track sync outcome in `integration.session_context_links`.
1. Retry failures later.

## Akosha V2 Charter

### One-Sentence Charter

`Akosha` is the ecosystem intelligence layer: it consumes events and memories from other systems, builds derived knowledge, and initially provides federated search, pattern detection, and analytics without owning core operational state.

## Longer-Term Roles Modern AI Ecosystems Commonly Need

### Strong Candidate Roles For Akosha After Initial Cutover

- analytics sidecar
- cross-system search broker
- event consumer and intelligence indexer
- memory distillation service
- knowledge graph and relationship engine
- recommendation engine
- evaluation and feedback loop service
- observability intelligence layer

## Recommended Akosha Capabilities

### 1. Federated Search

Search across:

- Mahavishnu tasks and runs
- Session-Buddy context
- Crackerjack reports
- docs
- logs
- repo metadata

Capabilities:

- result merging
- deduplication
- reranking
- provenance display

### 2. Pattern Detection

Detect:

- repeated failures
- workflow bottlenecks
- recurring remediation paths
- noisy tools
- unstable workers
- anomalous execution patterns

Deferred until after successful cutover stabilization:

- recommendation API
- graph exploration
- memory distillation
- evaluation telemetry
- observability intelligence

## Akosha Non-Goals

Akosha should not be:

- the transactional system of record
- the required operational database for Mahavishnu
- the synchronous write path for task creation
- the only copy of important task state

## Akosha V2 Roadmap

### Phase 1: Role Correction

1. Remove critical-path claims from docs and integration.
1. Make Mahavishnu the only required owner of task and search persistence.
1. Reduce Akosha startup coupling.

### Phase 2: Derived Read Models

1. Add read-only PostgreSQL integration.
1. Build event-derived analytics tables or materialized views.
1. Add real federated search and reranking.

### Phase 3: Intelligence APIs

1. Pattern-detection endpoints
1. targeted recommendation endpoints, only after post-cutover stability is established
1. optional summarization endpoints, only if backed by demonstrated operator need

### Phase 4: Feedback Loops

1. Measure orchestration outcomes.
1. Compare workers, prompts, and tools.
1. Feed recommendations back into Mahavishnu as optional hints.

## Recommended Responsibility Matrix

### Mahavishnu

- orchestration
- task lifecycle
- worker execution
- source-of-truth persistence
- primary search persistence

### Session-Buddy

- conversational context
- session memory
- assistant-facing history
- optional semantic recall

### Akosha

- aggregation
- analytics
- federated search
- pattern detection

## Final Recommendation

Build the ecosystem around this boundary:

1. `Mahavishnu` writes and owns.
1. `Session-Buddy` mirrors context asynchronously.
1. `Akosha` derives intelligence from what already happened.

This gives the ecosystem:

- fewer failure modes
- cleaner ownership
- simpler debugging
- better long-term extensibility

```
```
