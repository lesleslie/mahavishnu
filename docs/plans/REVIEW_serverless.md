---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Serverless Architecture Review — v3 Plan

## **Reviewer**: serverless-review agent **Date**: 2026-05-23 **Plan reviewed**: `docs/plans/2026-05-23-bodai-routing-feedback-loop-v3.md`

## 1. Env-Var-Driven Backend Detection

### Claim in Plan

> "Oneiric's layered config resolves `AKOSHA_STORAGE_PG_URL` / `OTEL_STORAGE_PG_URL` from the environment first. If set → pgvector backend. If unset → fall back to `:memory:` DuckDB."

### Finding: CRITICAL MISMATCH

**Oneiric's env var format does not match what the plan uses.**

Oneiric's layered config uses the format `{PROJECT_PREFIX}_{SECTION}__{FIELD}` with `__` as the nested delimiter. The env var override mechanism is in `oneiric/core/config.py:570-615` (`_env_overrides()`).

For Mahavishnu (which uses `MAHAVISHNU_` as prefix and `__` as nested delimiter), the correct env var would be:

```
MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL=postgresql://...
```

Not `OTEL_STORAGE_PG_URL`.

For Akosha (which uses `AKOSHA_` as prefix and `__` as nested delimiter):

```
AKOSHA__STORAGE__HOT__PG_URL=postgresql://...
```

Not `AKOSHA_STORAGE_PG_URL`.

The plan uses flat env var names (`OTEL_STORAGE_PG_URL`, `AKOSHA_STORAGE_PG_URL`) that **do not follow Oneiric's naming convention** and will **not be resolved** by `_env_overrides()`.

### Concrete Issue #1

- **File**: `mahavishnu/mahavishnu/ingesters/otel_ingester.py` line 1225 — factory param `hot_store_path` only accepts a file path string, not an env var
- **File**: `mahavishnu/mahavishnu/core/config.py:604-607` — `OTelIngesterConfig.hot_store_path` defaults to `:memory:` with no env var wiring for `OTEL_STORAGE_PG_URL`
- **Status**: `OTEL_STORAGE_TYPE` and `OTEL_STORAGE_PG_URL` are described in the plan but **not implemented** in code
- **Impact**: Serverless backend detection will silently fall back to `:memory:` even when the cloud Postgres URL is set, because the env vars are never read

### Concrete Issue #2

- **File**: `akosha/akosha/config.py:40-53` — `HotStorageConfig` has hardcoded defaults (`backend: str = "duckdb-memory"`, `path: str = ":memory:"`) with no env var mapping for `AKOSHA__STORAGE__HOT__PG_URL`
- **File**: `akosha/akosha/storage/hot_store.py:24` — `HotStore.__init__` accepts `database_path` but there is no logic to switch between DuckDB and pgvector backends at runtime
- **Status**: The `pgvector_hot_store.py` file **does not exist yet** (zero matches in codebase), and `HotStorageConfig` has no env-var-driven backend switching

### Severity: **Critical**

Both components are described as "serverless-ready" but the env var detection needed to trigger it is not wired up.

______________________________________________________________________

## 2. Shared Pgvector Story

### Claim in Plan

> "Akosha and Mahavishnu can share the same PostgreSQL instance (different tables) without schema conflicts."

### Finding: PARTIALLY CORRECT, PARTIALLY INCOMPLETE

**The schema separation is correct:**

- Akosha's `HotStore` DuckDB backend uses a `conversations` table (line 39-61 in `hot_store.py`)
- Mahavishnu's `OtelIngester` pgvector backend uses an `otel_traces` collection/table (plan line 148)
- These don't collide

**However, the plan misrepresents how the pgvector adapter works:**

The plan says Akosha uses Oneiric's `PgvectorAdapter` for its pgvector hot store. But:

- `PgvectorAdapter` in `oneiric/adapters/vector/pgvector.py:49` uses **collection-based** storage (one table per collection), not the same schema as DuckDB's `conversations` table
- Akosha's `HotStore` uses `HotRecord` with fields: `system_id`, `conversation_id`, `content`, `embedding`, `timestamp`, `metadata` (DuckDB schema, lines 39-61)
- A `pgvector_hot_store.py` would need to map these to a different table structure

The **interface compatibility** issue is bigger (see section 3 below).

### Severity: **Medium** — schema conflict is not the issue; interface compatibility is

______________________________________________________________________

## 3. `pgvector_hot_store.py` Interface Correctness

### Claim in Plan

> "`PgvectorHotStore` implementation using Oneiric's `PgvectorAdapter`, with the same interface as `HotStore` (`insert`, `search_similar`, `get`, etc.)"

### Finding: **INTERFACE MISMATCH — CRITICAL**

**`PgvectorAdapter` (Oneiric) does NOT have the same methods as `HotStore` (Akosha):**

| HotStore method | Does PgvectorAdapter have it? |
|---|---|
| `insert(record: HotRecord)` | `insert(collection, documents: list[VectorDocument])` — different signature |
| `search_similar(query_embedding, system_id, limit, threshold)` | `search(collection, query_vector, limit, filter_expr, include_vectors)` — different signature, no `threshold` param |
| `get(id)` | `get(collection, ids, include_vectors)` — collection required |
| `delete(id)` | `delete(collection, ids)` — different signature |
| `initialize()` | `init()` — named differently |
| `close()` | `cleanup()` — named differently |

**`PgvectorAdapter` methods that HotStore doesn't have:**

- `create_collection(name, dimension, distance_metric)`
- `delete_collection(name)`
- `list_collections()`
- `upsert(collection, documents)`
- `count(collection, filter_expr)`

**Key interface differences:**

1. `PgvectorAdapter` is **collection-based** (must specify collection name on every call). `HotStore` is **table-based** (single `conversations` table).
1. `HotStore.search_similar()` has a `threshold` param; `PgvectorAdapter.search()` does not.
1. `HotStore` accepts `HotRecord` dicts; `PgvectorAdapter` accepts `VectorDocument` objects.
1. `HotStore` manages the `conversations` table schema internally; `PgvectorAdapter` requires manual `create_collection()` calls.

### Concrete Issue #3

- **File**: `akosha/akosha/storage/hot_store.py:96-120` — `insert()` signature: `insert(self, record: HotRecord) -> None`
- **File**: `oneiric/oneiric/adapters/vector/pgvector.py:222-240` — `insert()` signature: `insert(self, collection: str, documents: list[VectorDocument]) -> list[str]`
- **Problem**: A `pgvector_hot_store.py` that wraps `PgvectorAdapter` cannot be a drop-in `HotStore` replacement without significant adapter logic
- **Missing work**: Need a wrapper class that translates `HotStore` interface calls to `PgvectorAdapter` calls (collection routing, record format translation, threshold → filter conversion)

### Severity: **Critical**

The plan describes `pgvector_hot_store.py` as a drop-in replacement with the "same interface as `HotStore`", but the underlying adapters have fundamentally different method signatures. Implementation will require non-trivial adapter logic.

______________________________________________________________________

## 4. Dhara Stateless Story

### Claim in Plan

> "Dhara's MCP server (`DharaMCPServer`) wraps the persistent object store backed by `FileStorage` (file-based). With a cloud storage adapter (S3/GCS/Azure Blob), Dhara becomes fully stateless-serverless safe."

### Finding: **INACCURATE — Dhara cannot run stateless serverless today**

**Multiple architectural blockers found:**

1. **Exclusive file locks** (`dhara/dhara/file.py:81-90`):

   ```python
   def obtain_lock(self):
       fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
   ```

   `LOCK_EX | LOCK_NC` is blocking for any concurrent access. Serverless functions (Lambda, Cloud Functions) share no filesystem — this will either block forever or fail immediately in a serverless environment.

1. **Hardcoded `FileStorage` in MCP server** (`dhara/dhara/mcp/server_core.py:141-148`):

   ```python
   self.storage = FileStorage(str(storage_path), readonly=config.storage.read_only)
   ```

   The MCP server **always** uses `FileStorage`. There is no cloud storage adapter for the primary store, only for backups.

1. **Cloud storage is backup-only** (`dhara/dhara/backup/storage.py:107,259,399`):
   `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter` exist but only for the backup subsystem. The primary `StorageConfig` at `dhara/core/config.py:20-25` lists `s3, gcs, azure` as backend options, but **no S3/GCS/Azure primary store implementation exists** — only `FileStorage`, `SqliteStorage`, `MemoryStorage`.

1. **In-memory LRU cache** (`dhara/dhara/core/connection.py:408-525`):
   The `Cache` class holds deserialized objects in an `OrderedDict`. In a serverless context, each Lambda invocation starts fresh — the cache is empty, and the Connection's assumptions about object lifetime are violated.

1. **`shelf.py:88`** also calls `file.obtain_lock()` — same fcntl issue.

### Severity: **Critical**

The plan says Dhara is "already compatible" with serverless and that cloud storage adapters would "complete" the story. In reality, the cloud adapters exist only for backups, the MCP server hardcodes `FileStorage`, and fcntl locks make serverless impossible even with cloud storage. A significant re-architecture of Dhara would be needed.

______________________________________________________________________

## 5. Standalone Constraint Analysis

### Claim in Plan

> "Constraint: Every Bodai component must run standalone without requiring any other Bodai component."

### Finding: **STANDALONE CONSTRAINT STILL HOLDS for Akosha and Mahavishnu**

The standalone constraint is about **runtime dependency**, not about storage backend. Both components can:

- Start with `:memory:` DuckDB (no external deps)
- Start with pgvector on cloud Postgres (no other Bodai component required)
- Operate with `query_local_traces` returning whatever is in the local store

**Akosha standalone behavior** (plan line 227): "If no component endpoints reachable → logs warning, idles. Akosha continues running." ✅ Correct
**Mahavishnu standalone behavior** (plan line 291): ":memory:`DuckDB, zero deps.`query_local_traces\` works." ✅ Correct

### Dhara standalone: **CONTRADICTION**

Dhara currently **requires** local filesystem storage (`FileStorage`). It cannot start in a serverless environment at all, so the standalone constraint for Dhara is **not met** in the serverless scenario.

However, if Dhara is deployed on a persistent VM/container (not serverless), it works fine.

### Severity: **Low** — the standalone constraint is not broken for Akosha and Mahavishnu. Dhara's standalone story requires local storage, which is fine for non-serverless deployments.

______________________________________________________________________

## Summary of Concrete Issues

| # | Issue | Severity | Location |
|---|---|---|---|
| 1 | `OTEL_STORAGE_PG_URL` env var is described but not wired — serverless detection silently fails | Critical | `mahavishnu/mahavishnu/ingesters/otel_ingester.py:1225`, `config.py:604-607` |
| 2 | `AKOSHA__STORAGE__HOT__PG_URL` not in `HotStorageConfig` — Akosha pgvector backend not env-var-switchable | Critical | `akosha/akosha/config.py:40-53`, `storage/hot_store.py:24` |
| 3 | `PgvectorHotStore` cannot be a drop-in `HotStore` replacement — method signatures differ fundamentally | Critical | `oneiric/oneiric/adapters/vector/pgvector.py:222-240` vs `akosha/akosha/storage/hot_store.py:96-120` |
| 4 | `pgvector_hot_store.py` does not exist — needs non-trivial adapter wrapper | Critical | Not implemented |
| 5 | Dhara has fcntl-based file locks, hardcoded FileStorage, and no primary cloud storage — serverless blocked | Critical | `dhara/dhara/file.py:89`, `dhara/mcp/server_core.py:144`, `backup/storage.py` backup-only |
| 6 | Plan uses flat env var names (`AKOSHA_STORAGE_PG_URL`) that don't match Oneiric's `__` nested delimiter convention | High | Plan lines 101, 107, 209, 233 |
| 7 | Plan conflates Oneiric's `OTelStorageAdapter` (SQLAlchemy/OTel-native) with Mahavishnu's custom `OtelIngester` (different architecture) | Medium | Plan lines 37, 186 |

______________________________________________________________________

## Recommendations

1. **Fix env var naming**: Use `MAHAVISHNU__OTEL_INGESTER__STORAGE__PG_URL` and `AKOSHA__STORAGE__HOT__PG_URL` per Oneiric convention
1. **Wire env vars into config classes**: Add `Field(default_factory=lambda: os.getenv(...))` patterns to `OTelIngesterConfig` and `HotStorageConfig`
1. **Implement pgvector_hot_store.py with an adapter layer**: The wrapper must translate `HotStore` calls (single table, `HotRecord`, `threshold`) to `PgvectorAdapter` calls (collection-based, `VectorDocument`, filter expressions)
1. **Acknowledge Dhara's serverless gap**: The plan's claim that Dhara is "already compatible" with serverless is inaccurate. Either remove serverless from Dhara's story or add a dedicated "Dhara cloud storage adapter" phase to the implementation plan
1. **Separate OTelStorageAdapter (Oneiric) from OtelIngester (Mahavishnu)**: These are different implementations — the plan conflates them
