# Bodai Ecosystem Feedback Loop — Routing Intelligence via OTel

## Context & Goal

All Bodai components (Mahavishnu, Akosha, Dhara, Session-Buddy, Crackerjack, Oneiric) are
instrumented with OpenTelemetry (OTel). This plan implements a feedback loop that:

1. Collects trace data from all components
1. Akosha analyzes routing outcomes to compute per-selector fitness signals
1. Mahavishnu's pool manager uses those signals to pick the best routing strategy

**Constraint**: Every Bodai component must run standalone without requiring any other Bodai component.
The feedback loop is a pure optional overlay — each component functions normally without it.

______________________________________________________________________

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Each Bodai component emits OTel spans locally via OTelStorageAdapter      │
│  (Oneiric OTelStorageAdapter → local pgvector or DuckDB)                 │
│  Span attributes: task_class, selector, outcome, duration_ms, pool_id     │
└─────────────────────────────────────────────────────────────────────────────┘
            │ optional push (only when Mahavishnu is reachable)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mahavishnu OTel Ingester (central trace store, optional)                 │
│  — same schema as local, aggregated view                                  │
│  — exposed via MCP tool: query_traces(task_class, time_range)            │
└─────────────────────────────────────────────────────────────────────────────┘
            │ periodic pull (Akosha on its own schedule)
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Akosha Fitness Analyzer (periodic job, own event loop)                   │
│  — queries Mahavishnu's trace store via MCP                              │
│  — computes rolling failure_rate, p99 latency per (task_class, selector) │
│  — writes fitness signals to Dhara: routing_fitness/{task_class}/{sel}   │
│  — graceful fallback: in-memory buffer if Dhara is down                   │
└─────────────────────────────────────────────────────────────────────────────┘
            │ read on each routing decision
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Mahavishnu Pool Manager                                                  │
│  — RoutingFitnessReader reads signals from Dhara before each route_task() │
│  — selects selector with best score for that task_class                  │
│  — fallback to least_loaded if no signal or Dhara unavailable           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Fitness Signal Schema (Dhara)

```
Key:   routing_fitness/{task_class}/{selector}
Value: {
  "score": float,           # 1 - failure_rate (higher = better)
  "samples": int,           # number of routing decisions in window
  "failure_rate": float,    # fraction of outcomes where outcome=error
  "p99_latency_ms": float,  # 99th percentile duration
  "updated_at": timestamp,
  "window_start": timestamp  # start of rolling window
}
```

Rolling window: 1 hour default (configurable). Signals expire after 2× window if not refreshed.

______________________________________________________________________

## Component Changes

### 1. Oneiric OTelStorageAdapter — no changes needed

Already fully implemented. Used as-is. Each Bodai component already imports it.

### 2. All Bodai Components — wire OTelStorageAdapter to existing OTel export

**Change**: Each component's OTel exporter pushes to the local `OTelStorageAdapter` instance
(running in-process, async flush to local pgvector). No new dependencies, no other Bodai
components required.

**Standalone behavior**: Each component works without any other Bodai component. Traces go
to local storage only.

**When Mahavishnu is reachable**: Each component optionally also pushes to Mahavishnu's
OTel ingestion endpoint (configurable, off by default). Mahavishnu aggregates them into the
central trace store.

**Span attributes** (standardized across all components):

```python
span.set_attribute("bodai.task_class", task_class)    # e.g., "CODE_REVIEW"
span.set_attribute("bodai.selector", selector)          # e.g., "least_loaded"
span.set_attribute("bodai.outcome", outcome)           # "success" | "error" | "timeout"
span.set_attribute("bodai.pool_id", pool_id)           # which pool handled it
span.set_attribute("bodai.duration_ms", duration_ms)  # wall time
```

### 3. Mahavishnu — trace collector + query tool + fitness reader

**a. Trace collection** (already exists in OtelIngester)

- Already handles trace ingestion from any OTel source
- Already has DuckDB and pgvector backends with HNSW indexing
- Existing MCP tool `ingest_otel_traces` accepts trace data

**b. New MCP tool: `query_component_traces`**

```
query_component_traces(task_class: str, time_range_minutes: int = 60) -> list[TraceSummary]
  # Returns traces from the central store matching task_class within the time window
  # TraceSummary: {trace_id, task_class, selector, outcome, duration_ms, timestamp}
```

This lets Akosha pull traces on its own schedule.

**c. New: `RoutingFitnessReader`**

- Reads fitness signals from Dhara (key: `routing_fitness/{task_class}/{selector}`)
- Returns the best selector for a given task_class
- Fallback: returns `None` if no signal or Dhara unavailable → pool manager uses default
- Circuit breaker: uses Oneiric's `CircuitBreaker` to handle Dhara unavailability

**d. Pool manager change**

- `route_task()` queries `RoutingFitnessReader` before picking a pool
- If a fitness signal exists for the task_class, use that selector
- Otherwise fall back to configured default (`least_loaded`)

### 4. Akosha — fitness analyzer job

**New module: `akosha/processing/fitness_analyzer.py`**

Runs as a background task (async loop, configurable interval, default 60s).
Can also be triggered on-demand via MCP tool.

**Logic:**

```python
async def compute_fitness_signals(task_class: str, window_minutes: int = 60) -> dict:
    # 1. Query Mahavishnu's trace store
    traces = await mahavishnu_mcp.query_component_traces(task_class, window_minutes)
    # 2. Group by selector
    by_selector = group_by(traces, lambda t: t.selector)
    # 3. For each selector group:
    #    - failure_rate = count(outcome=error) / total
    #    - p99 = percentile(duration_ms, 0.99)
    #    - score = 1 - failure_rate  (penalize failures heavily)
    # 4. Write signals to Dhara with TTL
```

**Standalone behavior**: If Mahavishnu is unreachable, log a warning and skip. If Dhara is
down, buffer signals in-memory (dict with TTL) and retry on next cycle. Uses Oneiric's
`CircuitBreaker` for Dhara writes.

**New MCP tool: `run_fitness_analysis`** (manual trigger for operators)

### 5. Dhara — schema addition

No structural changes. Just new key patterns under the existing keyspace:

```
routing_fitness/{task_class}/{selector} → fitness signal JSON
```

Existing Dhara schema remains unchanged.

______________________________________________________________________

## Standalone Operation Matrix

| Component running alone | Behavior |
|---|---|
| Mahavishnu only | Routes with `least_loaded` (default). OTel ingester stores traces locally. |
| Akosha only | Fitness job runs but finds no traces → logs warning, idles. No signals written. |
| Dhara only | Stores whatever is written to it. No active role. |
| Session-Buddy only | Emits OTel locally. No routing decisions. |
| Crackerjack only | Emits OTel locally. No routing decisions. |
| Full chain up | Complete feedback loop. Akosha → Dhara → Mahavishnu. |

______________________________________________________________________

## Key Files to Change

| File | Change |
|---|---|
| `oneiric/adapters/observability/otel.py` | No change (already complete) |
| `mahavishnu/mcp/tools/otel_tools.py` | Add `query_component_traces` MCP tool |
| `mahavishnu/pools/manager.py` | Add `RoutingFitnessReader`, consult it in `route_task()` |
| `mahavishnu/core/state_backends/dhara.py` | Add fitness signal read helper |
| `akosha/processing/fitness_analyzer.py` | **New file** — fitness analysis job |
| `akosha/mcp/tools/` | Add `run_fitness_analysis` MCP tool |
| Each Bodai component's startup | Wire existing OTel spans to `OTelStorageAdapter` (minimal change per component) |

______________________________________________________________________

## Not in Scope

- Changing Mahavishnu's default routing algorithm (always falls back to `least_loaded`)
- Akosha triggering real-time selector changes via WebSocket (Option B from prior discussion)
- Any changes to Akosha's core memory/embedding pipeline
- Modifying Dhara's storage format or adding new key types

______________________________________________________________________

## Open Questions

1. **Trace push model**: Should non-Mahavishnu components push traces *to* Mahavishnu when reachable,
   or should Mahavishnu pull from them? Push is simpler (existing OTLP exporter), pull requires
   Akosha to know component addresses.
   → **Recommendation**: Push from each component to Mahavishnu's ingestion endpoint when
   Mahavishnu is reachable. Configure via env var `MAHAVISHNU_OTEL_ENDPOINT`.

1. **Selector score formula**: Simple `1 - failure_rate` is a starting point. Could add latency
   weighting: `score = (1 - failure_rate) * exp(-p99_latency_ms / threshold)`.
   → **Start with**: simple failure rate. Refine once real data is flowing.

1. **Rolling window**: 1 hour is the starting default. Should be configurable per task_class.
   → **Start with**: global config, per-task override in Akosha's analyzer config.

1. **Akosha's Mahavishnu MCP client**: How does Akosha call `query_component_traces`?
   → **Start with**: Akosha has an MCP client module (`akosha/mcp/client.py`) that can call
   Mahavishnu's MCP tools. Use that. Falls back gracefully if Mahavishnu is unreachable.
