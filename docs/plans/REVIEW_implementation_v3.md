---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Implementation Feasibility Review — v3

## **Reviewer**: implementation-review-v3 agent **Date**: 2026-05-23 **Plan**: `docs/plans/2026-05-23-bodai-routing-feedback-loop-v3.md`

## 1. New Files: All Correctly Flagged as New

| File | Verified |
|---|---|
| `akosha/storage/pgvector_hot_store.py` | **Does not exist** — glob returned no matches |
| `akosha/mcp/client.py` | **Does not exist** — glob returned no matches |
| `akosha/processing/fitness_analyzer.py` | **Does not exist** — glob returned no matches |
| `akosha/mcp/tools/fitness_tools.py` | **Does not exist** — glob returned no matches |
| `mahavishnu/pools/routing_fitness.py` | **Does not exist** — glob returned no matches |

All new files are correctly identified as non-existent. No false positives.

______________________________________________________________________

## 2. PgvectorAdapter as Hot Store Backend — VERIFIED

**File examined**: `/Users/les/Projects/oneiric/oneiric/adapters/vector/pgvector.py`

**Oneiric `PgvectorAdapter` interface** (`insert`, `upsert`, `delete`, `get`, `search`, `create_collection`, `delete_collection`, `count`, `list_collections`):

```
insert(collection, documents: list[VectorDocument]) -> list[str]
upsert(collection, documents: list[VectorDocument]) -> list[str]
delete(collection, ids: list[str]) -> bool
get(collection, ids: list[str], include_vectors=False) -> list[VectorDocument]
search(collection, query_vector, limit, filter_expr, include_vectors) -> list[VectorSearchResult]
create_collection(name, dimension, distance_metric) -> bool
delete_collection(name) -> bool
count(collection, filter_expr) -> int
list_collections() -> list[str]
```

**Akosha `HotStore` interface** (`insert`, `search_similar`, `get`, `delete`, etc.):
`HotStore` at `akosha/storage/hot_store.py` uses DuckDB and has `insert(record: HotRecord)`, `search_similar(...)`, and `get(...)` methods.

**Interface comparison**: `PgvectorAdapter` and `HotStore` are **not the same interface**. `PgvectorAdapter` uses `VectorDocument`-style dicts with `id/vector/metadata` keys; `HotStore` uses `HotRecord` Pydantic models. `PgvectorAdapter` has `insert/upsert/delete/get/search`; `HotStore` has `insert/search_similar/get`.

However, the plan's claim is that `PgvectorHotStore` (the new file) will **mirror** `HotStore`'s interface using `PgvectorAdapter` internally. This is the correct approach — wrap `PgvectorAdapter` to adapt it to `HotStore`'s expected interface.

**Also found**: Mahavishnu ships its own `PgvectorAdapter` at `mahavishnu/adapters/pgvector_adapter.py` (separate from Oneiric's). This adapter has an identical interface to `OtelIngester`'s pgvector usage. Either could be used for `PgvectorHotStore`. The plan references the Oneiric adapter, which is the correct choice.

**Verdict**: The plan correctly calls for `PgvectorHotStore` as a **wrapper** around `PgvectorAdapter` that adapts its interface to match `HotStore`. Feasible.

______________________________________________________________________

## 3. OtelIngester Honors OTEL_STORAGE_TYPE — PARTIALLY VERIFIED, INCOMPLETE

**File examined**: `/Users/les/Projects/mahavishnu/mahavishnu/ingesters/otel_ingester.py`

**Current behavior**:

- `OtelIngester.__init__` accepts `storage_type: StorageType | str = StorageType.DUCKDB` (line 427) and `pgvector_dsn: str | None = None` (line 428) as constructor arguments.
- `StorageType` enum has `DUCKDB = "duckdb"` and `POSTGRESQL = "postgresql"` (lines 56–60).
- `_initialize_pgvector()` at line 628 reads `self._pgvector_dsn` (the constructor arg), **not** an env var.

**Env var detection**: The plan claims `OTEL_STORAGE_TYPE` and `OTEL_STORAGE_PG_URL` env vars are honored. There is **no code in `otel_ingester.py` that reads `OTEL_STORAGE_TYPE` or `OTEL_STORAGE_PG_URL`** as environment variables. The plan's own implementation task (Phase 1.2: "Wire OTEL_STORAGE_PG_URL env var detection into Mahavishnu OtelIngester") is correctly identified as a **future change**, not an existing feature.

**Config layer**: The `OTelIngesterConfig` in `mahavishnu/core/config.py` (line 597) only has `hot_store_path`, `embedding_model`, `cache_size`, `similarity_threshold`, `turboquant_bits` — no `storage_type` or `pg_url` fields.

**Verdict**: `OtelIngester` does **not** currently honor `OTEL_STORAGE_TYPE` / `OTEL_STORAGE_PG_URL` env vars. This is correctly listed as a planned change in Phase 1.2. The plan's description is accurate.

______________________________________________________________________

## 4. akosha/config.py Reads AKOSHA_STORAGE_PG_URL — NOT VERIFIED

**File examined**: `/Users/les/Projects/akosha/akosha/config.py`

`AkoshaConfig` (line 124) uses `HotStorageConfig` for its `hot:` field (line 161). `HotStorageConfig` (line 40) has fields `backend` (default `"duckdb-memory"`), `path` (default `":memory:"`), `write_ahead_log`, `wal_path` — **no `pg_url` or `AKOSHA_STORAGE_PG_URL` field**.

There is **no `AKOSHA_STORAGE_PG_URL` env var handling** in `AkoshaConfig` or `HotStorageConfig`. The `backend` field defaults to `"duckdb-memory"` — no env var override.

The plan's claim that "Akosha HotStore... detects `AKOSHA_STORAGE_PG_URL` env var at startup" is **not yet implemented**. This is correctly identified as a Phase 1.3 change.

**Verdict**: `akosha/config.py` does **not** currently read `AKOSHA_STORAGE_PG_URL`. This is a planned change.

______________________________________________________________________

## 5. akosha/storage/__init__.py Exports HotStore — VERIFIED

**File examined**: `/Users/les/Projects/akosha/akosha/storage/__init__.py`

Line 5: `from akosha.storage.hot_store import HotStore`
Line 23–40 `__all__` includes `"HotStore"` at line 30.

**Verdict**: Confirmed. `HotStore` is exported from `akosha.storage`.

______________________________________________________________________

## 6. Additional Findings

### A. `OTelStorageConfig` vs `OTelIngesterConfig` — Two Separate Configs

There are two distinct OTel-related configs in Mahavishnu's `core/config.py`:

- `OTelStorageConfig` (line 457): PostgreSQL + pgvector backend, controlled via `MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING` env var. Uses `MahavishnuPgvectorAdapter` pattern.
- `OTelIngesterConfig` (line 597): DuckDB/Akosha HotStore backend, controlled via `hot_store_path`. Uses Akosha HotStore.

The plan uses `OTelIngester` for trace ingestion. The `OTelStorageConfig` appears to be a separate legacy/alternative config. This should not cause confusion — they are distinct configs for distinct use cases.

### B. `query_local_traces` Tool — Not Yet in otel_tools.py

The plan calls for adding `query_local_traces` to Mahavishnu's MCP tools. Currently `otel_tools.py` (line 13) registers 4 tools: `ingest_otel_traces`, `search_otel_traces`, `get_otel_trace`, `otel_ingester_stats`. The `query_local_traces` tool is **not yet implemented**, which is correct per the plan.

**Note**: The plan mentions this tool needs to do **attribute-based time-range SQL filtering** (`WHERE attributes->>'bodai.task_class' = :task_class AND start_time > NOW() - INTERVAL '60 minutes'`), not semantic similarity search. The current `OtelIngester` storage backends (DuckDB HotStore's `search_similar` and pgvector's `search`) only support semantic search — they are not designed for attribute-based time-range filtering. This is a **non-trivial addition** that requires a new query method in `OtelIngester` or a raw SQL path. Implementers should be aware this is more complex than a simple wrapper.

### C. Mahavishnu's Own `PgvectorAdapter`

`mahavishnu/adapters/pgvector_adapter.py` exists and has the same interface. The plan references using Oneiric's `PgvectorAdapter`. The Mahavishnu adapter has HNSW support already built in. Either could work — using Oneiric's is the right choice for consistency.

### D. `AKOSHA_MODE` vs `AKOSHA_STORAGE_BACKEND` Env Vars

The plan references `AKOSHA_STORAGE_BACKEND` env var (`duckdb` vs `pgvector`). Looking at `akosha/config.py` line 158, `AKOSHA_MODE` env var already exists (values `"lite"` or `"standard"`). The plan correctly proposes a separate `AKOSHA_STORAGE_BACKEND` env var rather than coupling storage backend to mode, which is the right design.

______________________________________________________________________

## Summary of Verification

| Check | Status | Notes |
|---|---|---|
| New files don't exist yet | ✅ All verified | All 5 new files confirmed absent |
| PgvectorAdapter as hot store backend | ✅ Feasible | Plan correctly calls for PgvectorHotStore wrapper |
| OtelIngester honors OTEL_STORAGE_TYPE | ⚠️ Not yet | Phase 1.2 work, not current behavior |
| akosha/config.py reads AKOSHA_STORAGE_PG_URL | ❌ Not yet | Phase 1.3 work, not current behavior |
| akosha/storage/__init__.py exports HotStore | ✅ Verified | Confirmed at line 30 |
