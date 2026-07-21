---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Implementation Feasibility Review: Bodai Routing Feedback Loop

## **Reviewer**: Implementation Reviewer (General Agent) **Plan**: `docs/plans/2026-05-23-bodai-routing-feedback-loop.md` **Date**: 2026-05-23

## Summary

The plan is well-reasoned architecturally but has **3 blocking issues** and several non-blocking discrepancies. The most critical blockers are: (1) Akosha has no MCP client module — `akosha/mcp/client.py` does not exist; (2) `query_component_traces` MCP tool does not exist in Mahavishnu; and (3) Dhara's MCP server `get` tool needs verification before the fitness reader can read signals back.

______________________________________________________________________

## 1. Oneiric OTelStorageAdapter — Verified ✅

**File**: `oneiric/adapters/observability/otel.py`

**Status**: No code changes needed. Plan's description has one non-blocking documentation inaccuracy. <!-- legacy status — see YAML frontmatter -->

**Verified capabilities**:

- `store_trace()` — buffers traces, async flush when batch_size reached (lines 115-118)
- `_flush_buffer()` — async batch writes via SQLAlchemy, embeds traces (lines 130-178)
- `find_similar_traces()` — pgvector cosine similarity, 384-dim embeddings (lines 260-306)
- `store_log()`, `store_metrics()`, `get_traces_by_error()` — all present

**Non-blocking discrepancy**: Plan says "local pgvector or DuckDB" but OTelStorageAdapter only supports PostgreSQL + pgvector. The dual-backend (DuckDB/pgvector) is Mahavishnu's OtelIngester, not Oneiric's adapter.

______________________________________________________________________

## 2. Mahavishnu OtelIngester — Core Confirmed, Query Tool Missing ⚠️

**File**: `mahavishnu/ingesters/otel_ingester.py`

**Existing API verified**:

- `ingest_trace(trace_data)` ✅
- `ingest_batch(traces)` ✅ — returns `{"success_count", "error_count", "errors"}`
- `search_traces(query, system_id, limit, threshold)` ✅ — semantic only
- `get_trace_by_id(trace_id)` ✅
- `StorageType.DUCKDB` and `StorageType.POSTGRESQL` ✅

**Gap**: `query_component_traces(task_class, time_range_minutes)` does not exist. `search_traces()` is embedding-based semantic search, not attribute-filtered SQL. The HotStore's `search_similar(query_embedding, system_id=None, limit=10, threshold=0.7)` does not support `task_class` or time range filtering.

______________________________________________________________________

## 3. Mahavishnu MCP Tools (otel_tools.py) — Tool Missing ⚠️

**File**: `mahavishnu/mcp/tools/otel_tools.py`

**Current tools** (4 total): `ingest_otel_traces`, `search_otel_traces`, `get_otel_trace`, `otel_ingester_stats`

`query_component_traces` is not present. Must be added.

______________________________________________________________________

## 4. Mahavishnu PoolManager — Fitness Reader Feasible ⚠️

**File**: `mahavishnu/pools/manager.py`

**Current `route_task()` signature** (lines 386-470):

```python
async def route_task(
    self,
    task: dict[str, Any],
    pool_selector: PoolSelector | None = None,
    pool_affinity: str | None = None,
) -> dict[str, Any]
```

**What plan requires**:

1. Inject `RoutingFitnessReader` into `PoolManager` — current `dhara_state: Any = None` (line 81) can be extended
1. `route_task()` modified to query fitness reader before selecting pool
1. `task_class` extraction via `task.get("category") or task.get("type")` — matches existing pattern at line 142

**PoolSelector enum** (lines 29-42): Values `"round_robin"`, `"least_loaded"`, `"random"`, `"affinity"` — match plan's selector naming.

______________________________________________________________________

## 5. DharaStateBackend — Key Schema Fits, Read Verified ✅

**File**: `mahavishnu/core/state_backends/dhara.py`

**Existing key patterns**:

```
workflow/v1/{execution_id}   (line 56-58)
pool/v1/{pool_id}            (line 61-63)
routing/v1/{task_class}/{timestamp_ms}  (line 66-70)
approval/v1/{request_id}     (line 73-75)
```

**Plan's proposed `routing_fitness/{task_class}/{selector}`**: Does not conflict with existing patterns. `put()` can write to any key.

**Verified read mechanisms**:

- `get(key)` at line 176 — calls `self._client.call_tool("get", {"key": key})`
- `list_prefix(prefix)` at line 202 — returns `[(key, value), ...]`

**Dhara MCP server** (`dhara/mcp/server_core.py` line 423): `kv_store.get(key=key)` — `get` tool IS registered. ✅

**`list_prefix("routing_fitness/CODE_REVIEW/")`** would return all selectors for a task class — robust read path for fitness reader.

______________________________________________________________________

## 6. Akosha — No MCP Client Module ❌ **BLOCKER #1**

`akosha/mcp/client.py` does not exist. Entire Akosha codebase searched — no `MCPClient` class or `get_akosha_mcp_client()` function.

**What exists**:

- `akosha/mcp/server.py` — FastMCP server (server-side only)
- `akosha/mcp/tools/` — tool definitions (akosha_tools, code_graph_tools, health_tools, profiles, pycharm_tools, session_buddy_tools, tool_registry)
- `akosha/ingestion/orchestrator.py` — `BootstrapOrchestrator` with duck-typed `mahavishnu_client: Any = None` that calls `call_tool` via `hasattr` checks

No actual MCP client infrastructure exists. The plan references this in the Open Question 4 resolution ("Start with: Akosha has an MCP client module (`akosha/mcp/client.py`)") and the Key Files table.

**Impact**: Fitness analyzer job cannot call `mahavishnu_mcp.query_component_traces()` without first building an MCP client for Akosha.

______________________________________________________________________

## 7. Akosha Processing — No Fitness Analyzer ❌ **BLOCKER #2**

`akosha/processing/fitness_analyzer.py` does not exist.

**Existing `akosha/processing/`**: `analytics.py`, `deduplication.py`, `embeddings.py`, `knowledge_graph.py`

Entire section 4 of the plan (Akosha fitness analyzer job) requires creating this file from scratch.

______________________________________________________________________

## 8. Akosha MCP Tools — No `run_fitness_analysis` Tool ❌

**Existing tools in `akosha/mcp/tools/`**: `akosha_tools.py`, `code_graph_tools.py`, `health_tools.py`, `profiles.py`, `pycharm_tools.py`, `session_buddy_tools.py`, `tool_registry.py`

`run_fitness_analysis` must be created as a new file and registered.

______________________________________________________________________

## Blocking Issues Summary

### ❌ BLOCKER 1: Akosha has no MCP client module

`akosha/mcp/client.py` does not exist. Without this, Akosha cannot call `query_component_traces` on Mahavishnu.

**Fix**: Create `akosha/mcp/client.py` with `MahavishnuMCPClient` class using httpx + MCP protocol (similar to `DharaClient`'s `call_tool` pattern).

### ❌ BLOCKER 2: `query_component_traces` MCP tool does not exist

Plan requires a tool querying traces by `task_class` attribute and time window. Existing `search_otel_traces()` is semantic search only.

**Fix**: Add `query_component_traces` to `otel_tools.py` with direct storage queries filtering by span attributes and timestamp.

### ✅ BLOCKER 3: Dhara MCP server `get` tool — verified

`dhara/mcp/server_core.py` line 423: `kv_store.get(key=key)` — `get` tool IS registered. `DharaStateBackend.get()` works.

______________________________________________________________________

## Non-Blocking Discrepancies

1. **OTelStorageAdapter "local pgvector or DuckDB" claim**: Documentation inaccuracy — adapter only supports PostgreSQL/pgvector.

1. **`RoutingFitnessReader` class**: New class must be created — no existing equivalent in Mahavishnu.

1. **`route_task()` signature change**: Must consult `RoutingFitnessReader` before selecting pool. Existing `task_class` extraction at line 142 can be reused.

1. **`query_component_traces` implementation**: Needs attribute + time filtering on HotStore. `search_similar` doesn't support this — would need raw SQL or new HotStore query method.

1. **Akosha `run_fitness_analysis` tool registration**: New tool file must be created and registered in `__init__.py` or `tool_registry.py`.

______________________________________________________________________

## Verdict

**Buildable with fixes**: Yes, but 3 blockers must be resolved first.

| Component | Status |
|---|---|
| Oneiric OTelStorageAdapter | ✅ Verified — no code changes needed |
| Mahavishnu OtelIngester core | ✅ Verified — batch ingest + dual backend confirmed |
| `query_component_traces` MCP tool | ❌ Missing — BLOCKER 2 |
| PoolManager `route_task()` modification | ⚠️ Feasible — signature change needed |
| `RoutingFitnessReader` class | ⚠️ New class needed |
| DharaStateBackend fitness write | ✅ `put()` supports any key |
| DharaStateBackend fitness read | ✅ `get()` and `list_prefix()` verified |
| Akosha MCP client | ❌ Does not exist — BLOCKER 1 |
| Akosha `fitness_analyzer.py` | ❌ Does not exist — needs creation |
| Akosha `run_fitness_analysis` tool | ❌ Does not exist — needs creation |

**Implementation priority**: BLOCKER 1 (MCP client) → BLOCKER 2 (query tool) → rest.
