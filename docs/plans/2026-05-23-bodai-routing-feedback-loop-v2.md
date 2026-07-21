---
status: complete
role: superseded
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: docs/plans/2026-05-23-bodai-routing-feedback-loop-v4.md
topic: routing-composition
---

# Bodai Ecosystem Feedback Loop — Routing Intelligence via OTel

## Status

## **v2 — revised after 3-agent review (architecture, implementation, ecosystem)** <!-- legacy status: v2 superseded — see YAML frontmatter --> **Original**: `docs/plans/2026-05-23-bodai-routing-feedback-loop.md`

## What Changed After Review

| Finding | Severity | Fix |
|---|---|---|
| Push model makes Mahavishnu a required dependency, contradicting standalone constraint | **Critical** | Removed Mahavishnu from trace path entirely. Components write locally only. Akosha polls each component's MCP endpoint directly. |
| `akosha/mcp/client.py` does not exist | **Critical** | Explicitly add to scope as new file. Build httpx-based MCP client following DharaClient pattern. |
| `query_component_traces` tool doesn't exist | **Critical** | Renamed to `query_local_traces` — new tool on each Bodai component (not just Mahavishnu). Each component exposes traces via its own MCP. |
| OTelStorageAdapter is PostgreSQL-only, not DuckDB | **Medium** | Corrected: all components use pgvector via OTelStorageAdapter. DuckDB is only Mahavishnu's HotStore path. |
| pgvector extension undocumented prerequisite | **Medium** | Added to infrastructure prerequisites. |
| Akosha in-memory buffer has no max size — OOM risk | **Moderate** | Bounded buffer: `maxlen=1000` signals, flush to DLQ after 3 failed retries. |
| Rolling window races with multi-instance Akosha | **Medium** | Added compare-and-swap via Dhara TTL + Akosha leader election or per-task_class sharding. |
| No schema validation on span attributes | **Informational** | Added validation in `query_local_traces` — reject traces missing required `bodai.task_class`. |

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
│  Each Bodai component: OTel spans → OTelStorageAdapter → local pgvector  │
│  (PostgreSQL, same schema across all components)                          │
│  Span attributes: bodai.task_class, bodai.selector, bodai.outcome,        │
│                   bodai.pool_id, bodai.duration_ms                         │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Akosha polls each component via MCP (every 60s)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  New MCP tool on each Bodai component:                                     │
│  query_local_traces(task_class, time_range_minutes) → list[TraceSummary]   │
│  (attribute-filtered SQL, not semantic search)                            │
└─────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Akosha fitness analyzer (periodic job)                                    │
│  — polls all known component endpoints                                      │
│  — computes rolling failure_rate, p99 per (task_class, selector)         │
│  — writes fitness signals to Dhara: routing_fitness/{task_class}/{sel}  │
│  — bounded in-memory buffer if Dhara is down (max 1000 signals, DLQ)     │
└─────────────────────────────────────────────────────────────────────────────┘
            │ Mahavishnu reads on each route_task()
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mahavishnu RoutingFitnessReader                                           │
│  — reads routing_fitness/{task_class}/* from Dhara                        │
│  — selects highest-score selector for the task_class                       │
│  — falls back to least_loaded if no signal or Dhara unavailable           │
│  — uses DharaStateBackend (inherits circuit breaker protection)           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: No Central Collector Required

The original plan had all components push traces to Mahavishnu, making Mahavishnu a required node. The revised architecture removes that dependency:

- Each component is independent — stores its own traces locally
- Akosha actively polls each component's MCP endpoint (pull model)
- When Akosha is down or unreachable, components keep running normally
- When Mahavishnu is down, Akosha keeps computing signals (from whatever components it can reach); Mahavishnu falls back to `least_loaded`

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

**OTelStorageAdapter** (Oneiric, no code changes needed):

- Each component already imports it. Wire existing OTel spans to `store_trace()`.
- Requires: PostgreSQL + `CREATE EXTENSION vector` — document as prerequisite.
- Buffer: `deque(maxlen=1000)`, flushes on batch size or interval.

**New MCP tool per component: `query_local_traces`**

```
query_local_traces(task_class: str, time_range_minutes: int = 60) -> list[TraceSummary]
  TraceSummary: {trace_id, task_class, selector, outcome, duration_ms, timestamp}

  SELECT trace_id, attributes->>'bodai.task_class', attributes->>'bodai.selector',
         attributes->>'bodai.outcome', attributes->>'bodai.duration_ms', start_time
  FROM otel_traces
  WHERE attributes->>'bodai.task_class' = :task_class
    AND start_time > NOW() - INTERVAL '60 minutes'
  ORDER BY start_time DESC
```

This is the most important new tool — it lets Akosha pull traces from each component independently, without requiring Mahavishnu as a central aggregator.

**File**: `mahavishnu/mcp/tools/otel_tools.py` — add `query_local_traces`

**Same tool must be added to**: Akosha, Session-Buddy, Crackerjack, Oneiric, Dhara各自的MCP server.

**Standalone behavior**: Each component runs with zero other Bodai components. `query_local_traces` returns an empty list (no traces ingested yet) or whatever is in the local store. No other component required.

### 2. Akosha — fitness analyzer + MCP client + `run_fitness_analysis` tool

**New file: `akosha/mcp/client.py`**

- `MahavishnuMCPClient` (or renamed: `BodaiComponentMCPClient`)
- httpx-based MCP client calling `query_local_traces` on each known component endpoint
- Follows `DharaClient.call_tool()` pattern
- Endpoints stored in Dhara: `component_endpoint/{component_name}` → URL

**New file: `akosha/processing/fitness_analyzer.py`**

- Periodic background job (60s interval, configurable)
- On each cycle:
  1. Read component endpoints from Dhara (or use config file as fallback)
  1. For each reachable component, call `query_local_traces(task_class, window)`
  1. Group by selector, compute failure_rate and p99
  1. Write signals to Dhara with TTL
- **Bounded in-memory buffer**: `deque(maxlen=1000)` of failed writes
- **DLQ**: after 3 consecutive failed writes to Dhara, move to DLQ (simple JSON file)
- **Circuit breaker**: uses Oneiric's `CircuitBreaker` for Dhara writes

**New MCP tool: `run_fitness_analysis`** (manual trigger for operators)

**Standalone behavior**: If no component endpoints are reachable, logs a warning and idles. No signals written. Akosha itself continues running.

### 3. Mahavishnu — RoutingFitnessReader + pool manager integration

**New: `mahavishnu/pools/routing_fitness.py`**

- `RoutingFitnessReader` class
- Reads signals from Dhara via `list_prefix("routing_fitness/{task_class}/")`
- Returns `dict[selector, float]` sorted by score, or empty dict if none
- Uses `DharaStateBackend` (inherits circuit breaker protection)
- `get_fitness_signals(task_class: str) -> dict[str, FitnessSignal]`

**Pool manager change** (`pools/manager.py`):

- Inject `RoutingFitnessReader` into `PoolManager`
- In `route_task()`: before picking a pool, call `fitness_reader.get_fitness_signals(task_class)`
- If any signals exist, select the highest-score selector for that task_class
- Fall back to `least_loaded` if no signals or Dhara unavailable (no latency added — DharaStateBackend read is fast)

**File**: `mahavishnu/mcp/tools/otel_tools.py` — add `query_local_traces`

### 4. Dhara — no structural changes

Same keyspace. Fitness signals use the namespace `routing_fitness/{task_class}/{selector}` — separate from existing `routing/v1/{task_class}/{timestamp_ms}` namespace.

Add component endpoint registry keys:

```
component_endpoint/{component_name} → URL string
```

Akosha uses this to discover where to poll. Mahavishnu can optionally register its own endpoint here too.

### 5. Infrastructure Prerequisite

**pgvector**: Every Bodai component running OTelStorageAdapter needs:

```sql
CREATE EXTENSION vector;
```

This must be documented in each component's setup instructions. No way around it — `OTelStorageAdapter` requires it (checked at startup, `otel.py:56-67`).

______________________________________________________________________

## Standalone Operation Matrix

| Components running | Behavior | Degradation |
|---|---|---|
| Any single component alone | Runs normally. Emits OTel to local store. `query_local_traces` returns available traces. | None |
| Mahavishnu only | Routes with `least_loaded`. Reads no fitness signals. | Feedback loop inactive |
| Mahavishnu + Dhara | Same as above — no Akosha means no fitness signals written. | Routing not optimized |
| Akosha only | Polls component endpoints. None reachable → logs warning, idles. | Feedback loop inactive |
| Akosha + Dhara | Buffers signals in-memory. No trace source (components down) → idles. | Signals written when components available |
| Mahavishnu + Akosha + Dhara (no other components) | Akosha polls Mahavishnu's `query_local_traces` only. Fitness from Mahavishnu's own traces. Mahavishnu routes with fitness signals. | Limited trace set but functional |
| Full chain (all Bodai components) | Complete feedback loop. | None |

______________________________________________________________________

## Implementation Priority

```
Phase 1 — Foundations (do first)
  1.1  Build akosha/mcp/client.py         — MCP client for Akosha → poll other components
  1.2  Add query_local_traces to each Bodai component's MCP tools
  1.3  Document pgvector as prerequisite in each component's setup docs

Phase 2 — Analytics (Akosha)
  2.1  Build akosha/processing/fitness_analyzer.py
  2.2  Add bounded in-memory buffer + DLQ
  2.3  Add run_fitness_analysis MCP tool

Phase 3 — Routing (Mahavishnu)
  3.1  Build mahavishnu/pools/routing_fitness.py (RoutingFitnessReader)
  3.2  Integrate into PoolManager.route_task()
  3.3  Wire Dhara component endpoint registry

Phase 4 — Integration & Polish
  4.1  End-to-end test: full chain with 2+ components
  4.2  Verify graceful degradation for each partial-chain scenario
  4.3  Document partial-chain operation in deployment guide
```

______________________________________________________________________

## Key Files to Change

| File | Change |
|---|---|
| `mahavishnu/mcp/tools/otel_tools.py` | Add `query_local_traces` MCP tool |
| `mahavishnu/pools/routing_fitness.py` | **New** — `RoutingFitnessReader` |
| `mahavishnu/pools/manager.py` | Consult `RoutingFitnessReader` in `route_task()` |
| `akosha/mcp/client.py` | **New** — `BodaiComponentMCPClient` (httpx + MCP) |
| `akosha/processing/fitness_analyzer.py` | **New** — fitness analysis + bounded buffer + DLQ |
| `akosha/mcp/tools/fitness_tools.py` | **New** — `run_fitness_analysis` tool |
| Each Bodai component's MCP tools | Add `query_local_traces` tool (same interface across all) |
| `docs/plans/PLAN_INDEX.md` | Reference this plan |

______________________________________________________________________

## Open Questions (resolved in v2)

1. **Push vs pull**: Pull model selected. Each component writes locally; Akosha polls each component's MCP endpoint directly. Mahavishnu is **not** in the trace path.

1. **Selector score formula**: Start with `1 - failure_rate`. Latency weighting deferred to post-MVP.

1. **Akosha's MCP client**: Explicitly a new file (`akosha/mcp/client.py`), not an existing module. Build following `DharaClient` pattern (httpx `call_tool`).

1. **DuckDB path for OTelStorageAdapter**: Removed. All components use PostgreSQL + pgvector via `OTelStorageAdapter`. Mahavishnu's `OtelIngester` uses DuckDB as its HotStore but that's internal to Mahavishnu.

1. **Bounding Akosha's buffer**: `deque(maxlen=1000)` + DLQ after 3 failed retries. No unbounded OOM risk.

1. **Rolling window races**: Addressed by per-task_class atomic writes (last-write-wins per selector is acceptable since each selector is independent) + TTL ensures staleness is self-healing.

______________________________________________________________________

## What This Plan Does NOT Cover

- Changes to Akosha's core memory/embedding pipeline
- Modifications to Dhara's storage format
- Real-time selector switching via WebSocket (Option B from original discussion)
- Horizontal scaling of Akosha (single-instance analyzer for now)
- Schema validation beyond `query_local_traces` attribute checks
