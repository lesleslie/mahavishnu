---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: routing-composition
---

# Bodai Ecosystem Feedback Loop — Routing Intelligence via OTel

## Status

## **v4 — serverless issues fixed, env var naming corrected, Dhara story clarified** <!-- legacy status: v4 (active) — see YAML frontmatter --> **Changes since v3**: Fixed env var naming to Oneiric `__` convention; removed "Dhara already serverless-compatible" claim (has fcntl locks + hardcoded FileStorage); clarified pgvector_hot_store.py needs a non-trivial interface adapter; added coherence analysis per phase; separated OTelStorageAdapter (Oneiric) from OtelIngester (Mahavishnu)

## What Changed After Review

### v3 findings (incorporated)

| Finding | Severity | Fix |
|---|---|---|
| `OTEL_STORAGE_PG_URL` env var not wired in code | **Critical** | Wire into `OTelIngesterConfig` using Oneiric `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL` |
| `AKOSHA_STORAGE_PG_URL` not in `HotStorageConfig` | **Critical** | Wire into `HotStorageConfig` using `AKOSHA__STORAGE__HOT__PG_URL` |
| `pgvector_hot_store.py` interface mismatch | **Critical** | Clarify as non-trivial adapter: PgvectorAdapter is collection-based, HotStore is table-based, signatures differ; needs a wrapper layer |
| Dhara "already serverless-compatible" claim inaccurate | **Critical** | Removed; Dhara has fcntl locks + hardcoded FileStorage — serverless needs dedicated re-architecture (out of scope) |
| Flat env var names don't match Oneiric convention | **High** | Changed to `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL`, `AKOSHA__STORAGE__HOT__PG_URL` |
| Plan conflates `OTelStorageAdapter` (Oneiric) with `OtelIngester` (Mahavishnu) | **Medium** | Clarified throughout — these are different implementations |

### Coherence review findings (incorporated)

| Finding | Severity | Fix |
|---|---|---|
| Phase 4 depends on Phase 2/3 — text already correct in v4, coherence review read v3 | **Low** | No change needed — v4 already has correct dependency chain |
| Missing component self-registration | **High** | Added Phase 0: each component writes its own MCP endpoint to Dhara on startup |
| Standalone matrix missing hybrid Akosha-serverless + Mahavishnu-local scenario | **Low-Medium** | Added hybrid rows to Standalone Operation Matrix |

### v2 findings (still correct)

| Finding | Severity | Fix |
|---|---|---|
| Push model makes Mahavishnu a required dependency | **Critical** | Pull model — Akosha polls each component via MCP directly |
| `akosha/mcp/client.py` does not exist | **Critical** | Explicitly in scope, build following `DharaClient` pattern |
| `query_local_traces` tool missing | **Critical** | New tool added to every Bodai component's MCP interface |
| OTelStorageAdapter PostgreSQL-only | **Medium** | Corrected throughout |
| Akosha in-memory buffer unbounded | **Moderate** | `deque(maxlen=1000)` + DLQ after 3 failed retries |
| Rolling window races | **Medium** | Per-selector atomic writes + TTL self-healing |
| pgvector extension undocumented | **Medium** | Added to infrastructure prerequisites |

______________________________________________________________________

## Context & Goal

All Bodai components are OTel-instrumented. This plan builds a feedback loop that:

1. Each Bodai component stores its own traces locally via `OtelIngester` (Mahavishnu) or `HotStore` (Akosha) — serverless when backed by pgvector, zero-dependency when backed by `:memory:` DuckDB
1. Akosha discovers component endpoints and polls each one directly via MCP
1. Akosha computes fitness signals (failure rate, p99 latency per selector) and writes to Dhara
1. Mahavishnu reads fitness signals from Dhara before each routing decision

**Constraint**: Every Bodai component must run standalone without requiring any other Bodai component. The feedback loop activates only when the full chain is up; each component is fully functional without it.

**Serverless note**: Akosha and Mahavishnu can run serverless (pgvector backend survives cold-starts). Dhara cannot — it requires a persistent VM/container due to fcntl file locks and hardcoded `FileStorage`. Dhara serverless support is a separate future work item.

______________________________________________________________________

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Each Bodai component: OTel spans → OtelIngester / HotStore → backend      │
│  (pgvector on serverless, :memory: DuckDB locally)                         │
│  Span attributes: bodai.task_class, bodai.selector, bodai.outcome,        │
│                   bodai.pool_id, bodai.duration_ms                          │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Akosha polls each component via MCP (every 60s)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  New MCP tool on each Bodai component:                                      │
│  query_local_traces(task_class, time_range_minutes) → list[TraceSummary] │
└─────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Akosha fitness analyzer (periodic job)                                    │
│  — polls all known component endpoints                                      │
│  — computes rolling failure_rate, p99 per (task_class, selector)           │
│  — writes fitness signals to Dhara: routing_fitness/{task_class}/{sel}     │
│  — bounded in-memory buffer if Dhara is down (max 1000 signals, DLQ)       │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Mahavishnu reads on each route_task()
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mahavishnu RoutingFitnessReader                                           │
│  — reads routing_fitness/{task_class}/* from Dhara                         │
│  — selects highest-score selector for the task_class                       │
│  — falls back to least_loaded if no signal or Dhara unavailable             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: No Central Collector Required

- Each component stores traces locally — no dependency on Mahavishnu
- Akosha actively polls each component's MCP endpoint (pull model)
- Mahavishnu only appears at the end: reads fitness signals from Dhara
- Shared hot store: when deployed serverless, Akosha and Mahavishnu can share the same PostgreSQL + pgvector instance (different tables/collections) via environment detection

### Two Different Storage Systems (Not One)

This plan touches **two distinct** storage systems — they are not the same:

| System | Component | Backend options | Used for |
|---|---|---|---|
| `OtelIngester` | Mahavishnu, Session-Buddy, Crackerjack | `:memory:` DuckDB (local) / pgvector (serverless) | OTel trace storage + semantic search |
| `HotStore` | Akosha | `:memory:` DuckDB (Lite) / pgvector (Standard) | Conversation embedding storage |
| `OTelStorageAdapter` | Oneiric (separate from Mahavishnu's OtelIngester) | PostgreSQL + pgvector | Oneiric-native OTel traces, not directly used here |

The plan's original text conflated these. `OTelStorageAdapter` (Oneiric's own OTel storage) is **not** the same as `OtelIngester` (Mahavishnu's custom trace ingester). This plan uses `OtelIngester` for all Bodai components except Akosha.

______________________________________________________________________

## Storage Backends & Serverless Strategy

### The Problem

Akosha's `HotStore` and Mahavishnu's `OtelIngester` default to `:memory:` DuckDB — fine locally, but every cold-start wipes all data in a serverless environment. This plan addresses it without forcing a new service.

### The Solution: Env-Var-Driven Backend Detection

Both components already support the same storage backends. The change is to make the backend selection env-var-driven using Oneiric's layered config convention (`__` as section delimiter):

| Environment | Effective Backend | How triggered |
|---|---|---|
| Local dev (unset) | `:memory:` DuckDB — zero deps, just works | No env var set → code default |
| Local dev pointed at local Postgres | Shared pgvector — persists across restarts | `*__*__PG_URL` set to local Postgres URL |
| Serverless deployed | Shared pgvector — survives cold-starts | `*__*__PG_URL` set to cloud Postgres URL |
| Akosha Lite mode | `:memory:` DuckDB | `AKOSHA_MODE=lite` env var (explicit override) |
| Akosha Standard mode | pgvector + Redis L2 | `AKOSHA__STORAGE__HOT__PG_URL` set |

**Env var naming**: Oneiric uses `{PROJECT_PREFIX}_{SECTION}__{FIELD}` with `__` as the nested delimiter. The correct names are:

- Mahavishnu: `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE` (duckdb/postgresql) and `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL`
- Akosha: `AKOSHA__STORAGE__HOT__BACKEND` (duckdb/pgvector) and `AKOSHA__STORAGE__HOT__PG_URL`

Flat names without `__` will **not** be resolved by Oneiric's `_env_overrides()`.

### Akosha Hot Store Backend Options

**Lite mode (local dev, no deps)**:

- Backend: DuckDB `:memory:`
- Frictionless local dev — `python -m akosha.main` just works

**Standard mode with pgvector (serverless-ready)**:

- Backend: PostgreSQL + pgvector (shared)
- Akosha creates its own table (`conversations`) with HNSW index
- Same Postgres instance Mahavishnu uses, different table
- Redis L2 cache still works on top (standard mode)

### Mahavishnu OtelIngester Backend Options

**DuckDB (local dev default)**:

- `hot_store_path=":memory:"` — zero deps locally
- Or `hot_store_path="/tmp/mahavishnu_traces.db"` for file-backed persistence

**PostgreSQL + pgvector (serverless-ready)**:

- `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE=postgresql` + `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL` env vars
- Uses `PgvectorAdapter` from Oneiric
- Same Postgres instance Akosha uses, different table (`otel_traces`)

### Shared Hot Store Architecture

When both components use pgvector against the same PostgreSQL instance:

```
                    ┌─────────────────────────────┐
                    │   PostgreSQL + pgvector       │
                    │   (cloud-hosted, survives    │
                    │    cold-starts)               │
                    └──────────┬────────────────────┘
                               │
           ┌───────────────────┴────────────────────┐
           │                                          │
    Akosha Hot Store                          Mahavishnu OtelIngester
    Table: conversations                     Table: otel_traces
    HNSW index                               HNSW index
```

No table name collision. No schema interference. Both use `PgvectorAdapter` from Oneiric but different tables. Connection pooling is handled by the hosted Postgres service.

### Dhara — NOT Serverless

Dhara cannot run in a serverless environment today due to architectural blockers:

1. **fcntl file locks** (`dhara/dhara/file.py:89`) — exclusive locks on local files, incompatible with Lambda/Cloud Functions
1. **Hardcoded `FileStorage`** (`dhara/dhara/mcp/server_core.py:144`) — MCP server always uses `FileStorage`; no cloud primary store
1. **Cloud adapters are backup-only** (`dhara/dhara/backup/storage.py`) — S3/GCS/Azure adapters only work for the backup subsystem, not the primary store
1. **In-memory LRU cache** (`dhara/dhara/core/connection.py`) — assumes object lifetime across invocations

**Impact**: Dhara must be deployed on a persistent VM/container. This is fine for the Bodai ecosystem — the standalone constraint is met as long as Dhara is available, not specifically serverless. Dhara serverless re-architecture is a **separate future work item** and is **out of scope for this plan**.

______________________________________________________________________

## Fitness Signal Schema (Dhara)

```
Key:   routing_fitness/{task_class}/{selector}
Value: {
  "score": float,              # 1 - failure_rate (higher = better)
  "samples": int,              # routing decisions in window
  "failure_rate": float,       # fraction where outcome=error
  "p99_latency_ms": float,     # 99th percentile duration
  "updated_at": timestamp,
  "window_start": timestamp,  # start of rolling window
  "component_count": int      # how many components contributed traces
}
```

TTL: signals expire after 2× window (2 hours at default 1-hour window) if not refreshed.

______________________________________________________________________

## Component Changes

### 0. All Bodai Components — self-register MCP endpoint to Dhara on startup

**Problem**: Akosha polls component endpoints from Dhara's `component_endpoint/{name}` keyspace. If no component registers itself, Akosha has no targets to poll — the feedback loop cannot bootstrap.

**Solution**: Each Bodai component writes its own MCP endpoint to Dhara on startup:

```
Key:   component_endpoint/{component_name}
Value: MCP server URL string (e.g. "http://localhost:8680/mcp")
```

This is a minimal Phase 0 task — one `set()` call to Dhara using the component's own MCP URL (already known from its config). No new files needed.

**Implementation**:

- Mahavishnu: add to startup hook — writes `MAHAVISHNU_MCP_URL` env var value to `component_endpoint/mahavishnu`
- Akosha: add to startup routine — writes `AKOSHA_MCP_URL` to `component_endpoint/akosha`
- Session-Buddy, Crackerjack: same pattern

**If Dhara unreachable at startup**: component logs a warning and continues. Endpoint not registered — Akosha will have no target for that component until it restarts successfully.

### 1. All Bodai Components — add `query_local_traces` MCP tool

**Storage** (per component):

- Mahavishnu / Session-Buddy / Crackerjack: `OtelIngester` with env-var-driven backend (`MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE`, `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL`)
- Akosha: `HotStore` with env-var-driven backend (`AKOSHA__STORAGE__HOT__BACKEND`, `AKOSHA__STORAGE__HOT__PG_URL`)

**New MCP tool: `query_local_traces`**

```
query_local_traces(task_class: str, time_range_minutes: int = 60) -> list[TraceSummary]
  TraceSummary: {trace_id, task_class, selector, outcome, duration_ms, timestamp}

  # Attribute-filtered SQL — NOT semantic similarity search
  # The backend stores traces with OTel span attributes; query filters on those.
  # For pgvector backends: use SQL WHERE on attributes JSON field
  # For DuckDB backends: use SQL WHERE on attributes JSON field
  SELECT trace_id, attributes->>'bodai.task_class', ...
  FROM otel_traces
  WHERE attributes->>'bodai.task_class' = :task_class
    AND start_time > NOW() - INTERVAL '60 minutes'
```

**Implementation note**: `query_local_traces` requires **attribute-based time-range SQL filtering**, not semantic similarity search. This is non-trivial for pgvector backends — the filter must apply on the JSON `attributes` field, not on the embedding vector. The HNSW index is **not** used for this query. This should be a separate Phase 1.2c task.

**Standalone behavior**: Each component runs with zero other Bodai components. Returns empty list or whatever is in the local store.

### 2. Akosha — pgvector hot store + fitness analyzer + MCP client + `run_fitness_analysis`

**New: `akosha/storage/pgvector_hot_store.py`**

- `PgvectorHotStore` — wraps Oneiric's `PgvectorAdapter` to match `HotStore` interface
- **Non-trivial adapter work required**: `PgvectorAdapter` is collection-based (specify collection on every call); `HotStore` is table-based (single `conversations` table). Method signatures differ: `HotStore.insert(record: HotRecord)` vs `PgvectorAdapter.insert(collection, documents: list[VectorDocument])`. The wrapper must translate between these.
- Methods to implement: `insert(record)`, `search_similar(...)`, `get_by_id(...)`, `delete(...)`, `initialize()`, `close()`
- Detects `AKOSHA__STORAGE__HOT__BACKEND` env var at startup; `pgvector` → uses `PgvectorHotStore`; `duckdb` → falls back to `HotStore` with DuckDB

**Modified: `akosha/storage/hot_store.py`**

- No changes to existing `HotStore` class (it stays as-is for DuckDB backend)
- `pgvector_hot_store.py` is a **new separate class** that can be used as a drop-in backend replacement

**New file: `akosha/mcp/client.py`**

- `BodaiComponentMCPClient` — httpx-based MCP client, follows `DharaClient` pattern
- Calls `query_local_traces` on each component endpoint
- Endpoints stored in Dhara: `component_endpoint/{component_name}` → URL

**New file: `akosha/processing/fitness_analyzer.py`**

- Periodic background job (60s interval, configurable)
- **Bounded buffer**: `deque(maxlen=1000)` + DLQ after 3 failed retries
- **Circuit breaker**: Oneiric's `CircuitBreaker` for Dhara writes

**New MCP tool: `run_fitness_analysis`** (manual trigger for operators)

**Standalone behavior**: If no component endpoints reachable → logs warning, idles. Akosha continues running.

### 3. Mahavishnu — pgvector backend + RoutingFitnessReader

**Modified: `mahavishnu/ingesters/otel_ingester.py`**

- Honor `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE` and `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL` env vars
- When storage type is `postgresql` and `PG_URL` is set → uses pgvector via `PgvectorAdapter`
- Default (unset): `:memory:` DuckDB — zero deps locally

**Modified: `mahavishnu/core/config.py`**

- Wire `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE` and `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL` into `OTelIngesterConfig` using `Field(default_factory=lambda: os.getenv(...))` pattern

**New: `mahavishnu/pools/routing_fitness.py`**

- `RoutingFitnessReader` — reads signals from Dhara via `list_prefix()`
- Uses `DharaStateBackend` (inherits circuit breaker protection)
- `get_fitness_signals(task_class: str) -> dict[str, FitnessSignal]`

**Modified: `mahavishnu/pools/manager.py`**

- In `route_task()`: consult `RoutingFitnessReader` before selecting pool
- Fall back to `least_loaded` if no signals or Dhara unavailable

**New MCP tool: `query_local_traces`** (same interface as other components)

### 4. Dhara — no structural changes for this plan

Same keyspace. Add component endpoint registry:

```
component_endpoint/{component_name} → URL string
```

**Note**: Dhara serverless re-architecture is out of scope for this plan.

______________________________________________________________________

## Environment Detection & Defaults

### Configuration Priority (Oneiric standard)

1. Environment variable: `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE`, `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL`, `AKOSHA__STORAGE__HOT__BACKEND`, `AKOSHA__STORAGE__HOT__PG_URL`
1. `settings/local.yaml` (gitignored, local dev overrides)
1. `settings/{component}.yaml` (committed defaults)
1. Code default: `:memory:` DuckDB

### Default Behavior by Environment

| Scenario | Hot store backend | How triggered |
|---|---|---|
| Fresh local clone, no setup | `:memory:` DuckDB | No env var set → code default |
| Local Postgres running | Shared pgvector | `*__*__PG_URL` set to local Postgres URL |
| Serverless deployment | Shared pgvector | `*__*__PG_URL` set to cloud Postgres URL |
| Akosha Lite mode | `:memory:` DuckDB | `AKOSHA_MODE=lite` env var (explicit override) |
| Akosha Standard mode | pgvector + Redis L2 | `AKOSHA__STORAGE__HOT__PG_URL` set |

### Infrastructure Prerequisite

```sql
CREATE EXTENSION vector;
```

Document this in each component's setup instructions. Required for `PgvectorHotStore` and pgvector-backed `OtelIngester`.

______________________________________________________________________

## Standalone Operation Matrix

| Components running | Behavior | Degradation |
|---|---|---|
| Any single component alone (local dev) | `:memory:` DuckDB, zero deps. `query_local_traces` works. | None |
| Any single component alone (deployed) | pgvector via cloud Postgres. Survives cold-starts. | None |
| Mahavishnu only | Routes with `least_loaded`. OTel ingester stores locally. | Feedback loop inactive |
| Mahavishnu + Dhara | No fitness signals (Akosha down) → fallback to `least_loaded` | Routing not optimized |
| Akosha only | Polls component endpoints. None reachable → logs warning, idles. | Feedback loop inactive |
| Akosha + Dhara | Buffers in-memory. No trace source → idles. | Signals when components available |
| Mahavishnu + Akosha + Dhara | Complete loop. Akosha polls Mahavishnu's traces. | Limited trace set |
| Full chain (all components) | Complete feedback loop. | None |
| Akosha (serverless) + Mahavishnu (local) | Akosha polls Mahavishnu via MCP. Mahavishnu has `:memory:` — traces lost on restart. Akosha writes signals to Dhara. | Traces incomplete but loop active |
| Akosha (local) + Mahavishnu (serverless) | Akosha polls via local network. Mahavishnu pgvector survives cold-starts. | Works if network reachable |

**Dhara serverless note**: Dhara must run on a persistent VM/container (not serverless). All rows in this matrix where Dhara appears as "running" assume a persistent deployment.

______________________________________________________________________

## Phase Dependencies & Coherence

### Dependency Graph

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
  │             │
  │             └─► 1.1b, 1.1c can run in parallel after 1.1a
  │
  └─ 0 (component self-registration) must complete before Phase 2
        — Akosha cannot poll without registered endpoints
```

**Phase 0** (component self-registration): Each component writes its MCP URL to Dhara on startup. Must complete before Phase 2 — Akosha's fitness analyzer (Phase 3) needs endpoints to poll.

**Internal Phase 1 ordering**:

- 1.1a (PgvectorHotStore interface adapter) must precede 1.1b and 1.1c (env var wiring)
- 1.1b (Mahavishnu env var wiring) and 1.1c (Akosha env var wiring) can run in parallel once 1.1a is done
- 1.2 (CREATE EXTENSION vector docs) is independent — can run any time
- 1.3 (end-to-end pgvector test) depends on 1.1a, 1.1b, 1.1c all complete

**Phase 2 note**: `query_local_traces` SQL filtering is independent of the pgvector backend — works on both DuckDB and pgvector. However, it is a non-trivial implementation item and should be its own subtask.

**Phase 3 depends on Phase 2**: The fitness analyzer needs the MCP client (Phase 2.1) to poll component endpoints. Phase 3 can begin after Phase 2.1 is complete.

**Phase 4 depends on Phase 3**: `RoutingFitnessReader` reads fitness signals written by the fitness analyzer (Phase 3). Phase 4 can begin after Phase 3.1 is complete.

### What This Plan Does NOT Cover

- Akosha's existing Redis L2 cache integration (already works, no change needed)
- **Dhara serverless re-architecture** — fcntl locks, hardcoded FileStorage, backup-only cloud adapters need separate work
- Horizontal scaling of Akosha fitness analyzer (single-instance for now)
- Real-time selector switching via WebSocket
- Akosha cold/warm tier migration (unchanged)

______________________________________________________________________

## Implementation Priority

```
Phase 0 — Component Self-Registration
  0.1  Mahavishnu: write MCP URL to Dhara component_endpoint/mahavishnu on startup
  0.2  Akosha: write MCP URL to Dhara component_endpoint/akosha on startup
  0.3  Session-Buddy, Crackerjack: same pattern
        [0.1, 0.2, 0.3 are independent — can run in parallel]

Phase 1 — Storage Backend Foundation
  1.1a Build pgvector_hot_store.py adapter  (akosha/storage/pgvector_hot_store.py)
        — non-trivial wrapper: HotStore interface → PgvectorAdapter calls
        — implements: insert, search_similar, get_by_id, delete, initialize, close
        — maps HotRecord dicts ↔ VectorDocument objects
  1.1b Wire MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE + __PG_URL into OTelIngesterConfig
  1.1c Wire AKOSHA__STORAGE__HOT__BACKEND + __PG_URL into HotStorageConfig
  1.2  Implement query_local_traces SQL filtering (attribute-based, NOT semantic search)
  1.3  Add CREATE EXTENSION vector to each component's setup docs
  1.4  End-to-end: verify shared pgvector works for both components

Phase 2 — MCP Client & Trace Query
  2.1  Build akosha/mcp/client.py          (BodaiComponentMCPClient)
  2.2  Add query_local_traces to Mahavishnu MCP tools
  2.3  Add query_local_traces to Akosha, Session-Buddy, Crackerjack MCP tools
        [2.2 and 2.3 are independent — can run in parallel]

Phase 3 — Fitness Analytics (Akosha)
  3.1  Build akosha/processing/fitness_analyzer.py
  3.2  Add bounded in-memory buffer + DLQ
  3.3  Add run_fitness_analysis MCP tool
        [3.2 and 3.3 are independent after 3.1]

Phase 4 — Routing Integration (Mahavishnu)
  4.1  Build mahavishnu/pools/routing_fitness.py (RoutingFitnessReader)
  4.2  Integrate into PoolManager.route_task()
  4.3  Wire Dhara component endpoint registry
        [4.2 and 4.3 are independent after 4.1]

Phase 5 — Integration & Polish
  5.1  End-to-end test: full chain with 2+ components
  5.2  Verify graceful degradation for each partial-chain scenario
  5.3  Document local vs serverless deployment in guide
```

______________________________________________________________________

## Key Files to Change

| File | Change |
|---|---|
| `akosha/storage/pgvector_hot_store.py` | **New** — `PgvectorHotStore` wrapper (HotStore interface → PgvectorAdapter calls) |
| `akosha/storage/__init__.py` | Export `PgvectorHotStore` |
| `akosha/config.py` | Wire `AKOSHA__STORAGE__HOT__BACKEND` + `AKOSHA__STORAGE__HOT__PG_URL` |
| `mahavishnu/core/config.py` | Wire `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE` + `__PG_URL` into `OTelIngesterConfig` |
| `mahavishnu/ingesters/otel_ingester.py` | Honor env vars for backend selection |
| `mahavishnu/mcp/tools/otel_tools.py` | Add `query_local_traces` MCP tool |
| `mahavishnu/pools/routing_fitness.py` | **New** — `RoutingFitnessReader` |
| `mahavishnu/pools/manager.py` | Consult `RoutingFitnessReader` in `route_task()` |
| `akosha/mcp/client.py` | **New** — `BodaiComponentMCPClient` (httpx + MCP) |
| `akosha/processing/fitness_analyzer.py` | **New** — fitness analysis + bounded buffer + DLQ |
| `akosha/mcp/tools/fitness_tools.py` | **New** — `run_fitness_analysis` tool |
| Each Bodai component's MCP tools | Add `query_local_traces` tool |
| `docs/plans/PLAN_INDEX.md` | Reference this plan |

______________________________________________________________________

## Open Questions (Resolved)

1. **query_local_traces on pgvector**: `PgvectorAdapter` is SQLAlchemy-backed. PostgreSQL JSONB columns support SQL `WHERE attributes->>'bodai.task_class' = :task_class`. The HNSW index is not used for this query (correct — this is attribute filtering, not semantic search). No additional SQLAlchemy layer needed. **Answer: proceed with JSONB filtering.**

1. **HotStore threshold param**: Implement in Python post-query. `query_local_traces` filters on attributes, not embeddings — threshold check is just `if score >= threshold` after fetching. `PgvectorAdapter.search()` lacking a `threshold` param is therefore irrelevant for this use case. **Answer: Python post-query filter.**

1. **Akosha pgvector collection naming**: Use `conversations` as the collection name. The `PgvectorHotStore` wrapper hardcodes it. **Answer: `conversations`.**
