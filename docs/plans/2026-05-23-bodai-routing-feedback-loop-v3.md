# Bodai Ecosystem Feedback Loop — Routing Intelligence via OTel

## Status

**v3 — updated with serverless deployment support and hot store storage backend options**
**Changes since v2**: Added hot store storage backend strategy, serverless deployment defaults, environment detection via Oneiric layered config

______________________________________________________________________

## What Changed After Review

### v2 findings (incorporated)

| Finding | Severity | Fix |
|---|---|---|
| Push model makes Mahavishnu a required dependency | **Critical** | Pull model — Akosha polls each component via MCP directly |
| `akosha/mcp/client.py` does not exist | **Critical** | Explicitly in scope, build following `DharaClient` pattern |
| `query_local_traces` tool missing | **Critical** | New tool added to every Bodai component's MCP interface |
| OTelStorageAdapter PostgreSQL-only | **Medium** | Corrected throughout |
| Akosha in-memory buffer unbounded | **Moderate** | `deque(maxlen=1000)` + DLQ after 3 failed retries |
| Rolling window races | **Medium** | Per-selector atomic writes + TTL self-healing |
| pgvector extension undocumented | **Medium** | Added to infrastructure prerequisites |

### v3 findings (new in this revision)

| Finding | Severity | Fix |
|---|---|---|
| Akosha HotStore defaults to `:memory:` — not serverless-safe | **Critical** | Add pgvector as storage backend option; detect via env var |
| Mahavishnu OtelIngester DuckDB defaults to `:memory:` | **Medium** | Honor `OTEL_STORAGE_TYPE` env var consistently; clarify defaults |
| No serverless deployment story in the plan | **Critical** | Add deployment section with local vs serverless defaults |
| Shared hot store potential not documented | **Medium** | Document that Akosha and Mahavishnu can share a pgvector backend |

______________________________________________________________________

## Context & Goal

All Bodai components are OTel-instrumented. This plan builds a feedback loop that:

1. Each Bodai component stores its own traces locally via Oneiric's `OTelStorageAdapter` (PostgreSQL + pgvector)
1. Akosha discovers component endpoints and polls each one directly via MCP
1. Akosha computes fitness signals (failure rate, p99 latency per selector) and writes to Dhara
1. Mahavishnu reads fitness signals from Dhara before each routing decision

**Constraint**: Every Bodai component must run standalone without requiring any other Bodai component. The feedback loop activates only when the full chain is up; each component is fully functional without it.

______________________________________________________________________

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Each Bodai component: OTel spans → OTelStorageAdapter → storage backend  │
│  (pgvector on serverless, :memory: DuckDB locally)                        │
│  Span attributes: bodai.task_class, bodai.selector, bodai.outcome,      │
│                   bodai.pool_id, bodai.duration_ms                        │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Akosha polls each component via MCP (every 60s)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  New MCP tool on each Bodai component:                                     │
│  query_local_traces(task_class, time_range_minutes) → list[TraceSummary]│
└─────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Akosha fitness analyzer (periodic job)                                    │
│  — polls all known component endpoints                                     │
│  — computes rolling failure_rate, p99 per (task_class, selector)         │
│  — writes fitness signals to Dhara: routing_fitness/{task_class}/{sel}     │
│  — bounded in-memory buffer if Dhara is down (max 1000 signals, DLQ)       │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Mahavishnu reads on each route_task()
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mahavishnu RoutingFitnessReader                                           │
│  — reads routing_fitness/{task_class}/* from Dhara                         │
│  — selects highest-score selector for the task_class                       │
│  — falls back to least_loaded if no signal or Dhara unavailable            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: No Central Collector Required

- Each component stores traces locally — no dependency on Mahavishnu
- Akosha actively polls each component's MCP endpoint (pull model)
- Mahavishnu only appears at the end: reads fitness signals from Dhara
- Shared hot store: when deployed serverless, Akosha and Mahavishnu can share the same PostgreSQL + pgvector instance (different tables/collections) via environment detection

______________________________________________________________________

## Storage Backends & Serverless Strategy

### The Problem

Both Akosha's `HotStore` and Mahavishnu's `OtelIngester` default to `:memory:` DuckDB — fine locally, but every cold-start wipes all data in a serverless environment. This plan addresses it without forcing a new service.

### The Solution: Env-Var-Driven Backend Detection

Both components already support the same storage backends. The change is to make the backend selection env-var-driven:

| Environment | `AKOSHA_STORAGE_PG_URL` / `OTEL_STORAGE_PG_URL` | Effective Backend |
|---|---|---|
| Local dev (unset) | Not set | `:memory:` DuckDB — zero deps, just works |
| Local dev pointed at local Postgres | Set → `postgresql://localhost:5432/...` | Shared pgvector — persists across restarts |
| Serverless deployed | Set → cloud Postgres URL | Shared pgvector — survives cold-starts |

**How it works**: Oneiric's layered config resolves `AKOSHA_STORAGE_PG_URL` / `OTEL_STORAGE_PG_URL` from the environment first. If set → pgvector backend. If unset → fall back to `:memory:` DuckDB. No flag flipping, no config file changes needed.

### Akosha Hot Store Backend Options

**Lite mode (local dev, no deps)**:

- Backend: DuckDB `:memory:`
- Frictionless local dev — `python -m akosha.main` just works

**Standard mode with pgvector (serverless-ready)**:

- Backend: PostgreSQL + pgvector (shared)
- Akosha creates its own table (`conversations`) with HNSW index
- Same Postgres instance Mahavishnu uses, different table
- Redis L2 cache still works on top (standard mode)

**New file: `akosha/storage/pgvector_hot_store.py`** — `PgvectorHotStore` implementation using Oneiric's `PgvectorAdapter`, with the same interface as `HotStore` (`insert`, `search_similar`, `get`, etc.)

### Mahavishnu OtelIngester Backend Options

**DuckDB (local dev default)**:

- `hot_store_path=":memory:"` — zero deps locally
- Or `hot_store_path="/tmp/mahavishnu_traces.db"` for file-backed persistence

**PostgreSQL + pgvector (serverless-ready)**:

- `OTEL_STORAGE_TYPE=postgresql` + `OTEL_STORAGE_PG_URL` env var
- Uses same `PgvectorAdapter` from Oneiric
- Same Postgres instance Akosha uses, different table (`otel_traces`)

### Shared Hot Store Architecture

When both components use pgvector against the same PostgreSQL instance:

```
                    ┌─────────────────────────────┐
                    │   PostgreSQL + pgvector      │
                    │   (cloud-hosted, survives   │
                    │    cold-starts)             │
                    └──────────┬──────────────────┘
                               │
          ┌────────────────────┴────────────────────┐
          │                                         │
   Akosha Hot Store                           Mahavishnu OtelIngester
   Table: conversations                       Table: otel_traces
   Columns: system_id, conversation_id,     Columns: trace_id, span_id,
   content TEXT, embedding FLOAT[384],       name, status, duration_ms,
   timestamp, metadata JSON                  embedding FLOAT[384], ...
   HNSW index                                HNSW index
```

No table name collision. No schema interference. Both use the same `PgvectorAdapter` from Oneiric but different collections/tables. Connection pooling is handled by the hosted Postgres service.

### Dhara — Already Stateless-Ready

Dhara's MCP server (`DharaMCPServer`) wraps the persistent object store backed by `FileStorage` (file-based). With a cloud storage adapter (S3/GCS/Azure Blob), Dhara becomes fully stateless-serverless safe. Its design is already compatible — the keyspace is just key-value, no local state needed.

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

### 1. All Bodai Components — wire OTelStorageAdapter, add `query_local_traces`

**OTelStorageAdapter** (Oneiric):

- Requires: PostgreSQL + `CREATE EXTENSION vector`
- Buffer: `deque(maxlen=1000)`, flushes on batch size or interval

**New MCP tool: `query_local_traces`**

```
query_local_traces(task_class: str, time_range_minutes: int = 60) -> list[TraceSummary]
  TraceSummary: {trace_id, task_class, selector, outcome, duration_ms, timestamp}

  # Attribute-filtered SQL, not semantic search
  SELECT trace_id, attributes->>'bodai.task_class', ...
  FROM otel_traces
  WHERE attributes->>'bodai.task_class' = :task_class
    AND start_time > NOW() - INTERVAL '60 minutes'
```

**Standalone behavior**: Each component runs with zero other Bodai components. Returns empty list or whatever is in the local store.

### 2. Akosha — pgvector hot store + fitness analyzer + MCP client + `run_fitness_analysis`

**New: `akosha/storage/pgvector_hot_store.py`**

- `PgvectorHotStore` — mirrors `HotStore` interface using Oneiric's `PgvectorAdapter`
- `insert(record)`, `search_similar(...)`, `get_by_id(...)`, `delete(...)`
- Detects `AKOSHA_STORAGE_PG_URL` env var at startup; falls back to DuckDB `:memory:` if unset

**Modified: `akosha/storage/hot_store.py`**

- `HotStore` already accepts `database_path` — no change needed
- Add `AKOSHA_STORAGE_BACKEND` env var: `duckdb` (default locally) or `pgvector` (serverless)

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

- `hot_store_path` parameter: accepts file path or `:memory:`
- `OTEL_STORAGE_TYPE` env var: `duckdb` (default) or `postgresql`
- `OTEL_STORAGE_PG_URL` env var: connection string for pgvector backend
- When `OTEL_STORAGE_TYPE=postgresql` and `OTEL_STORAGE_PG_URL` is set → uses pgvector

**New: `mahavishnu/pools/routing_fitness.py`**

- `RoutingFitnessReader` — reads signals from Dhara via `list_prefix()`
- Uses `DharaStateBackend` (inherits circuit breaker protection)
- `get_fitness_signals(task_class: str) -> dict[str, FitnessSignal]`

**Modified: `mahavishnu/pools/manager.py`**

- In `route_task()`: consult `RoutingFitnessReader` before selecting pool
- Fall back to `least_loaded` if no signals or Dhara unavailable

**New MCP tool: `query_local_traces`** (same interface as other components)

### 4. Dhara — no structural changes

Same keyspace. Add component endpoint registry:

```
component_endpoint/{component_name} → URL string
```

______________________________________________________________________

## Environment Detection & Defaults

### Configuration Priority (Oneiric standard)

1. Environment variable: `MAHAVISHNU_OTEL_STORAGE_PG_URL`, `AKOSHA_STORAGE_PG_URL`
1. `settings/local.yaml` (gitignored, local dev overrides)
1. `settings/{component}.yaml` (committed defaults)
1. Code default: `:memory:` DuckDB

### Default Behavior by Environment

| Scenario | Hot store backend | How triggered |
|---|---|---|
| Fresh local clone, no setup | `:memory:` DuckDB | No env var set → code default |
| Local Postgres running | Shared pgvector | `*_STORAGE_PG_URL` set to local Postgres URL |
| Serverless deployment | Shared pgvector | `*_STORAGE_PG_URL` set to cloud Postgres URL |
| Akosha Lite mode | `:memory:` DuckDB | `AKOSHA_MODE=lite` env var (explicit override) |
| Akosha Standard mode | pgvector + Redis L2 | `AKOSHA_STORAGE_PG_URL` set |

### Infrastructure Prerequisite

```sql
CREATE EXTENSION vector;
```

Document this in each component's setup instructions. Required for `OTelStorageAdapter` and `PgvectorHotStore`.

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

______________________________________________________________________

## Implementation Priority

```
Phase 1 — Storage Backend Foundation
  1.1  Add pgvector hot store to Akosha  (akosha/storage/pgvector_hot_store.py)
  1.2  Wire OTEL_STORAGE_PG_URL env var detection into Mahavishnu OtelIngester
  1.3  Add AKOSHA_STORAGE_BACKEND + AKOSHA_STORAGE_PG_URL env var detection
  1.4  Add CREATE EXTENSION vector to each component's setup docs
  1.5  End-to-end: verify shared pgvector works for both components

Phase 2 — MCP Client & Trace Query
  2.1  Build akosha/mcp/client.py          (BodaiComponentMCPClient)
  2.2  Add query_local_traces to Mahavishnu MCP tools
  2.3  Add query_local_traces to Akosha, Session-Buddy, Crackerjack MCP tools

Phase 3 — Fitness Analytics (Akosha)
  3.1  Build akosha/processing/fitness_analyzer.py
  3.2  Add bounded in-memory buffer + DLQ
  3.3  Add run_fitness_analysis MCP tool

Phase 4 — Routing Integration (Mahavishnu)
  4.1  Build mahavishnu/pools/routing_fitness.py (RoutingFitnessReader)
  4.2  Integrate into PoolManager.route_task()
  4.3  Wire Dhara component endpoint registry

Phase 5 — Integration & Polish
  5.1  End-to-end test: full chain with 2+ components
  5.2  Verify graceful degradation for each partial-chain scenario
  5.3  Document local vs serverless deployment in guide
```

______________________________________________________________________

## Key Files to Change

| File | Change |
|---|---|
| `akosha/storage/pgvector_hot_store.py` | **New** — `PgvectorHotStore` using Oneiric `PgvectorAdapter` |
| `akosha/storage/__init__.py` | Export `PgvectorHotStore` |
| `akosha/storage/hot_store.py` | Add `AKOSHA_STORAGE_BACKEND` env var detection |
| `akosha/config.py` | Add `AKOSHA_STORAGE_PG_URL` env var config |
| `mahavishnu/ingesters/otel_ingester.py` | Honor `OTEL_STORAGE_TYPE` + `OTEL_STORAGE_PG_URL` env vars |
| `mahavishnu/mcp/tools/otel_tools.py` | Add `query_local_traces` MCP tool |
| `mahavishnu/pools/routing_fitness.py` | **New** — `RoutingFitnessReader` |
| `mahavishnu/pools/manager.py` | Consult `RoutingFitnessReader` in `route_task()` |
| `akosha/mcp/client.py` | **New** — `BodaiComponentMCPClient` (httpx + MCP) |
| `akosha/processing/fitness_analyzer.py` | **New** — fitness analysis + bounded buffer + DLQ |
| `akosha/mcp/tools/fitness_tools.py` | **New** — `run_fitness_analysis` tool |
| Each Bodai component's MCP tools | Add `query_local_traces` tool |
| `docs/plans/PLAN_INDEX.md` | Reference this plan |

______________________________________________________________________

## What This Plan Does NOT Cover

- Akosha's existing Redis L2 cache integration (already works, no change needed)
- Dhara cloud storage adapter for full stateless serverless (already compatible — separate concern)
- Horizontal scaling of Akosha fitness analyzer (single-instance for now)
- Real-time selector switching via WebSocket
- Akosha cold/warm tier migration (unchanged)
