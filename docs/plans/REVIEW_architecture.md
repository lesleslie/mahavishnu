# Architecture & Design Review: Bodai Routing Feedback Loop

**Reviewer**: Architecture Reviewer
**Date**: 2026-05-23
**Plan**: `docs/plans/2026-05-23-bodai-routing-feedback-loop.md`

______________________________________________________________________

## 1. Correctness — Data Flow Analysis

### Issue #1: The "push model" contradicts the standalone constraint

**Location**: Plan lines 86–88 and Open Question 1 (lines 202–206)

The plan states two things that are in tension:

- **Line 12–13** (Constraint): *"Every Bodai component must run standalone without requiring any other Bodai component."*
- **Lines 86–88** (Component Change 2): *"When Mahavishnu is reachable: Each component optionally also pushes to Mahavishnu's OTel ingestion endpoint"*

The plan's own recommendation for Open Question 1 (line 205) is: *"Push from each component to Mahavishnu's ingestion endpoint when Mahavishnu is reachable."*

This creates a runtime dependency: the feedback loop cannot function unless Mahavishnu is reachable and running its OTel ingestion endpoint. If Mahavishnu is down, Akosha has nothing to analyze — the loop is broken even though Akosha and Dhara are both running fine. The "standalone" guarantee in the constraint only covers the case where a single component runs alone; it doesn't cover the case where the full chain runs without Mahavishnu.

**Impact**: The plan describes an optional overlay (line 13) but the push model makes Mahavishnu a required node for the feedback loop to exist at all. If the goal is truly optional overlay, the architecture needs a local-first storage path where Akosha can analyze local traces without going through Mahavishnu.

### Issue #2: `query_component_traces` is declared but not implemented

**Location**: Plan lines 106–111 vs `mahavishnu/mcp/tools/otel_tools.py`

The plan specifies a new MCP tool:

```
query_component_traces(task_class: str, time_range_minutes: int = 60) -> list[TraceSummary]
```

Reviewing the existing `otel_tools.py` (lines 13–268), the registered tools are:

- `ingest_otel_traces` — ingest traces
- `search_otel_traces` — semantic search
- `get_otel_trace` — retrieve by ID
- `otel_ingester_stats` — get statistics

`query_component_traces` does not exist. The plan treats it as a new tool to be added (line 182), but this tool needs to perform time-range filtering by `task_class` and `selector` attributes. The existing storage backends (DuckDB HotStore via `search_similar` in `otel_ingester.py` line 922, pgvector via `search` in line 946) are semantic similarity searches — they are not designed for attribute-based time-range filtering. Adding `query_component_traces` requires a new query path in the `OtelIngester` that filters by span attributes (`bodai.task_class`, `bodai.selector`) within a time window. This is non-trivial.

**Impact**: This is not a stub — it's a real missing implementation with storage backend implications. The plan should specify the query interface and acknowledge that the HotStore and pgvector backends both need a new attribute-filter query path.

### Issue #3: The rolling window has no synchronization mechanism

**Location**: Plan lines 53–65 (Fitness Signal Schema), lines 127–148 (Akosha fitness analyzer)

The schema uses `window_start` and `updated_at` timestamps:

```
Key: routing_fitness/{task_class}/{selector}
Value: { "window_start": timestamp, "updated_at": timestamp, "score": float, ... }
```

Akosha's fitness analyzer (line 127) runs as a periodic background job at 60s intervals. Two problems:

1. **Concurrent write conflict**: If two Akosha instances run simultaneously (planned for HA), they both read the same traces, compute the same signals, and write to the same Dhara keys. Last write wins — no atomic compare-and-swap. The plan doesn't address multi-instance Akosha at all.

1. **Rolling window boundary races**: The analyzer queries traces within `window_minutes` (default 60s). At t=0 and t=60s, different time windows produce different trace sets. A selector's score can oscillate wildly if the boundary falls across a gap in trace collection. The plan acknowledges 1 hour as the default (line 213) but doesn't address window alignment.

**Impact**: The fitness signal is not stable under concurrent analysis or rapid re-runs. In production with many repos, this will cause selector churn.

______________________________________________________________________

## 2. Completeness — What's Missing

### Missing #1: No Akosha-to-Mahavishnu MCP client specification

**Location**: Plan lines 215–217 (Open Question 4)

The plan says Akosha has an `akosha/mcp/client.py` that can call Mahavishnu's MCP tools. This module is not present in the codebase (confirmed by glob search — no `akosha/mcp/` directory exists). The plan references a module that doesn't exist, and the fallback ("gracefully if Mahavishnu is unreachable") is already described for the fitness analyzer but not for the MCP client itself.

\*\*Missing #2: No `routing_fitness/` read method in `DharaStateBackend`

**Location**: Plan line 184 (`mahavishnu/core/state_backends/dhara.py` — Add fitness signal read helper)

The `dhara.py` (lines 46–239) has helpers for `workflow_key`, `pool_key`, `routing_key`, and `approval_key`. There is no `routing_fitness_key()` helper, and there is no `get_fitness_signal()` method. The plan says this is a change to make, but the current file doesn't have it.

**Missing #3**: `RoutingFitnessReader` is called in `route_task()` but the plan doesn't specify the async signature or error handling contract

**Location**: Plan lines 120–123 vs `pools/manager.py` lines 386–470

The plan says `route_task()` queries `RoutingFitnessReader` before picking a pool. But `route_task()` is synchronous in the current `pools/manager.py` — it takes a task dict and returns a result dict directly. Adding a fitness read before selector decision requires either:

- Making `route_task()` async (caller changes)
- Making fitness read synchronous (blocking I/O in hot path)

The current `route_task()` implementation (lines 386–470) is `async def` already, so async is possible. But the fitness read is a Dhara network call — adding it to every routing decision adds ~10–50ms latency per call. The plan doesn't address this.

______________________________________________________________________

## 3. Scalability — 100+ Repos

### Scalability Issue: Central polling doesn't scale

**Location**: Plan lines 35–41 (Akosha pulls from Mahavishnu on its own schedule)

The current design has Akosha polling Mahavishnu's trace store every 60 seconds. With 100+ repos:

- Each repo pushes traces to Mahavishnu's central store
- Mahavishnu's `query_component_traces` must filter across all repos
- Akosha processes all traces from all repos in one job

There is no parallelization strategy. The plan doesn't mention:

- Can multiple Akosha instances run in parallel? (No — see Issue #3 above)
- Does `query_component_traces` support pagination for large result sets?
- Can Akosha shard work by `task_class` or time window across workers?

For 100+ repos with high trace volume, the single Akosha fitness analyzer job will become a bottleneck. The plan should either specify horizontal scaling of Akosha or a distributed computation approach (e.g., each repo computes its own fitness locally and Akosha aggregates).

______________________________________________________________________

## 4. Failure Modes

### Well-handled: Dhara circuit breaker (Plan lines 41, 118, 148)

The plan correctly uses Oneiric's `CircuitBreaker` for Dhara writes. The existing `dhara.py` already implements this pattern (lines 81–106): 3 consecutive failures opens the circuit for 30s, then half-open probing. This is a solid pattern that the plan builds on correctly.

### Well-handled: In-memory buffer fallback (Plan lines 41, 147)

Akosha buffers signals in-memory when Dhara is down and retries on next cycle. This is correct — it prevents feedback loop stall when Dhara is temporarily unavailable.

### Missing #4: No DLQ for failed Akosha writes

**Location**: Plan lines 127–148 (fitness analyzer)

When Akosha fails to write a fitness signal to Dhara (even after circuit breaker backoff), the signal is lost for that cycle. The plan mentions "retry on next cycle" but doesn't handle permanent failures. The `OTelStorageAdapter` has a DLQ (`_send_to_dlq` in `otel.py` line 180) — Akosha's fitness analyzer should have a similar dead-letter mechanism so failed signals can be inspected and replayed.

### Missing #5: No trace ingestion failure handling

**Location**: Plan lines 86–88 (component push model)

When a component fails to push traces to Mahavishnu (network error, Mahavishnu down), traces are lost. The component stores locally via OTelStorageAdapter, but if the component also pushes and the push fails, there's no mention of a local retry queue or DLQ for the push channel. This means the feedback loop has a data loss hole at the component→Mahavishnu boundary.

______________________________________________________________________

## 5. Oneiric `OTelStorageAdapter` Usage

### Correct: The adapter is used correctly as a local store

**Location**: Plan lines 23–26 and `oneiric/adapters/observability/otel.py` lines 18–230

The plan correctly identifies OTelStorageAdapter as the local store per component. The adapter's design is:

- Buffer traces in a deque (line 28: `_write_buffer: deque[dict]`)
- Flush periodically or when batch size is reached (lines 117–118)
- Store to PostgreSQL with pgvector (lines 42–80)
- Dead-letter queue for failed writes (line 180)

This is correct. The DLQ is a good pattern that the plan should reference more explicitly.

### Issue #4: OTelStorageAdapter requires PostgreSQL — not "local zero-dependency"

**Location**: Plan line 24 ("local pgvector or DuckDB") vs `otel.py` lines 34–80

The plan says: *"OTelStorageAdapter → local pgvector or DuckDB"* (line 24)

But looking at `otel.py` lines 34–80, `OTelStorageAdapter.init()` requires:

```python
conn_str = self._settings.connection_string.replace("postgresql://", "postgresql+asyncpg://")
self._engine = create_async_engine(conn_str, ...)
```

It creates a `sqlalchemy.ext.asyncio` async engine connected to PostgreSQL. There is no DuckDB path in `OTelStorageAdapter`. The plan's line 24 is inaccurate — `OTelStorageAdapter` always requires PostgreSQL + pgvector. The plan should reference the correct adapter per component:

- Mahavishnu: uses `OtelIngester` with DuckDB HotStore or pgvector (correct, per `otel_ingester.py` lines 421–489)
- Other Bodai components: would need to use `OTelStorageAdapter` which requires PostgreSQL

If the goal is for all components to run with zero external dependencies (matching the standalone constraint), then `OTelStorageAdapter` is not suitable for non-Mahavishnu components without adding DuckDB support.

______________________________________________________________________

## Summary

| Area | Finding | Severity |
|---|---|---|
| Correctness | Push model makes Mahavishnu required, contradicting standalone constraint | High |
| Correctness | `query_component_traces` tool doesn't exist and needs new storage query path | High |
| Correctness | No synchronization for rolling window — multi-instance Akosha races | Medium |
| Completeness | `RoutingFitnessReader` API is underspecified (sync vs async, latency) | Medium |
| Completeness | `routing_fitness/` read helper missing from `DharaStateBackend` | Medium |
| Scalability | Central polling by single Akosha instance doesn't scale to 100+ repos | High |
| Failure modes | No DLQ for failed fitness signal writes | Low |
| Failure modes | No retry queue for component→Mahavishnu trace push failures | Medium |
| OTelStorageAdapter | Plan says "pgvector or DuckDB" but adapter only supports PostgreSQL | Medium |

**At least 3 issues are implementation-blocking:**

1. `query_component_traces` doesn't exist — requires new query path in both `OtelIngester` and its storage backends
1. Scalability: single Akosha analyzer cannot handle 100+ repos' trace volume
1. Push model contradicts the standalone constraint — the feedback loop requires Mahavishnu to be running
