---
status: draft
role: canonical
kind: spec
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate
revision: v5
owner: platform-team
scope: cross-component substrate adoption via existing oneiric.adapters (akosha + session-buddy + mahavishnu + oneiric)
related: docs/decisions/oneiric-substrate-extraction.md; .claude/decisions/wire-up-contract.md; .claude/decisions/mcp-backend-wiring-discipline.md; docs/specs/2026-04-26-config-consolidation-design.md; feedback-bodai-core-component-taxonomy.md
title: "Shared Oneiric Substrate - Design v5"

---

# Shared Oneiric Substrate - Design v5

> **About this design (v5, 2026-09-27)**: v4 → v5 fix pass after a 2-agent final-review (code-explorer citation audit + code-reviewer logical-completeness review). Fixed: hard citation drifts (Phase A `class QueryCacheManager` line, Phase D `_embedding_cache` dict line), 7 structural gaps (Phase B V1-V6 deletion + p99 perf test + akosha-searches-sb test, Phase D llama-server vs fastembed alignment test, Phase E1 storage adapter `get_feed_state`, Phase E1 `SubstrateSettings` nested per §9 validation), high-priority hygiene (cross-component dep diagrams per wire-up-contract §2, naming hygiene, `auth__loopback_trusted` test, /health 503 trigger logic, Observability on missing tasks), and 4 spec internal contradictions (shim-then-delete vs replace-not-extend, §4.6 mis-cite, §6.6 typo, §5.3 env-prefix ambiguity reconciled below). v4 itself was a rename pass per `feedback-no-bodai-prefix-in-config-names.md`; v3 was a rewrite from scratch after a 3-agent spec audit (code-explorer, code-reviewer, architecture-council) found 31 issues across structural, logical, and factual dimensions.

## 1. Outcome

After this design ships:

- **One cache adapter in use**: `oneiric.adapters.cache.memory.MemoryCacheAdapter`. SB's hand-rolled `QueryCacheManager` (L1 OrderedDict + L2 DuckDB runtime `CREATE TABLE` in 2 places) is deleted. Akosha's `CacheConfig` (`akosha/config.py:241-258`) delegates to `MemoryCacheAdapter` instead of unbounded `dict`.
- **One warm vector adapter**: `oneiric.adapters.vector.pgvector.PgvectorAdapter` with per-component schema namespaces (`akosha.*`, `sb.*`). SB's 461 MB `reflection.duckdb` (DuckDB VSS) migrated to pgvector via `PgvectorAdapter` with `sb.reflections` table. Akosha's `akosha/storage/pgvector_warm_store.py` (already pgvector since 2026-09-27 per `akosha/config.py:71-78`) consolidated under the same adapter.
- **Mahavishnu OTel stays on `HotStore`**: no change. `mahavishnu/ingesters/otel_ingester.py:41` already imports `from oneiric.adapters.vector.hot_store import HotStore` (ADR 017). Phase work is for Akosha + SB only.
- **One cold storage adapter**: `oneiric.adapters.storage.{gcs,s3,local,azure}.*` with per-component R2 prefix ACL (`akosha/`, `sb/`). SB's `session_buddy/storage/cloud_sync.py` (S3-only) deleted in favor of `session_buddy/adapters/storage_oneiric.py` (already wired for GCS via `GCSStorageOneiric`, commit `ef09475b`). Akosha's `akosha/storage/cold_store.py` (`ColdStore` class, line 29) delegates to oneiric adapters directly.
- **One embedding service**: `oneiric.adapters.embedding.EmbeddingBase` with **forced single default model** (`ONEIRIC__SUBSTRATE__EMBEDDING__MODEL`). Phase D adds `fastembed.py`, `llama_server.py`, `ollama.py` to `oneiric/adapters/embedding/` (today only `openai.py` exists). Akosha's `akosha/processing/embeddings.py` shim (which already delegates to `oneiric.adapters.observability.embeddings`) folds to the new adapter package. SB's `session_buddy/reflection/embeddings.py` (HTTP-only with new `httpx.AsyncClient` per call, `embeddings.py:39-46, 70-76`) replaced; module-level `_embedding_cache` dict deleted; L2-normalize layer explicit.
- **One operational settings surface**: `OneiricSettings` (`oneiric/core/config.py:246`) extended with cross-component default fields via pydantic-settings nested env-prefix (`ONEIRIC__SUBSTRATE__*`). Per-component overrides via existing `{PROJECT}__*` prefix loader. No parallel `SubstrateSettings` class.
- **Feed-state hooks per adapter**: each substrate adapter exposes `get_feed_state() -> {entities_count, last_updated_timestamp, errors_total, cycles_total}` per `mcp-backend-wiring-discipline.md §3`. Component `/health` endpoints aggregate these.
- **Integration Contract per phase**: each phase has Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added per `wire-up-contract.md`.
- **Release-train deployment gates**: cross-repo phases gate on oneiric PyPI release + per-component re-pin.

**Proof it worked**:
- `grep -rn "class QueryCacheManager\|class ColdStore" session_buddy/ akosha/` returns zero hits outside migration shims.
- `grep -rn "from oneiric.adapters.vector.hot_store" mahavishnu/ session_buddy/ akosha/` returns hits in all three components.
- `grep -rn "class SubstrateSettings" .` returns zero hits.
- `pytest oneiric/tests/adapters/{cache,vector,storage,embedding}/ session_buddy/tests/ akosha/tests/ mahavishnu/tests/` all green.
- `curl http://localhost:8682/health | jq .feeds` shows akosha's four substrate feeds; same shape for SB (8678) and mahavishnu (8680).

## 2. Goals

1. **Adopt, don't abstract** — components adopt existing `oneiric.adapters.*` directly. No new `substrate.*` namespace, no parallel settings class. (Audit finding from architecture-council: a new layer on top of full-featured adapters adds indirection without capability.)
2. **Extend, don't replace** — extend `OneiricSettings` with cross-component defaults via existing pydantic-settings nested env-prefix. Components reference `OneiricSettings` (or their project's extension thereof); they don't redefine.
3. **Single embedding model across components** — `ONEIRIC__SUBSTRATE__EMBEDDING__MODEL` is the source of truth. Per-component model override is forbidden (audit finding C3: vacuous alignment test otherwise).
4. **Independent rollback per phase** — each phase ships behind a release-train gate. Reverting one does not affect the others.
5. **Feed observability enforced** — each substrate adapter carries `get_feed_state()` so `/health` aggregation can flag silent-feed failure modes per `mcp-backend-wiring-discipline.md`.

## 3. Non-Goals

- **New `substrate.*` namespace** — oneiric.adapters.* is the substrate. Adding a parallel package duplicates existing capability.
- **Parallel `SubstrateSettings` class** — extend `OneiricSettings` via pydantic-settings nested prefix; do not introduce a second settings surface in `oneiric/core/config.py`.
- **DuckDB VSS in production warm backend** — `warm__backend="duckdb_vss"` was in v1/v2; removed. DuckDB VSS exists in `oneiric.adapters.vector.duckdb_hot_store.DuckdbHotStore` for offline development; production is pgvector-only.
- **Cross-component embeddings search via Mahavishnu** — Akosha and SB each read their own namespace; cross-namespace search via Mahavishnu is a separate design.
- **Qdrant / Pinecone / multi-vector backend** — pgvector only.
- **Schema migration framework** — each component owns its migrations.
- **Component deprecation** — no Bodai component is removed.
- **Multi-region / multi-host** — out of scope.
- **Encryption at rest** — handled by R2 / Postgres platform layer.
- **Compression benchmarking** — `snappy` is default; `zstd` is the alternative.

## 4. Current Findings

### 4.1 Cache — hand-rolled + unbounded

| Component | Cache impl | Backend | L1 | L2 | Source |
|---|---|---|---|---|---|
| **Session-Buddy** | `QueryCacheManager` | in-process `OrderedDict` | yes (max 1024) | **DuckDB runtime CREATE TABLE** `query_cache_l2` | `session_buddy/cache/query_cache.py:90, 139, 150, 153, 327, 374, 432, 438, 468, 514, 632` AND `session_buddy/adapters/reflection_adapter_oneiric.py:759, 774, 777, 2732` (two runtime CREATE TABLE blocks, not migrations) |
| **A kosha** | `CacheConfig` only | unbounded `dict` | none | none | `akosha/config.py:241-258` — no standalone cache module file |
| **Mahavishnu** | none | n/a | n/a | n/a | pool state is DI singleton (process state, not cache) |

`oneiric.adapters.cache.memory.MemoryCacheAdapter` (`memory.py:29`) provides bounded LRU + TTL + delete_prefix out of the box. Adopted: zero. The two components hand-rolled cache.

### 4.2 Warm — Akosha on pgvector, SB on DuckDB VSS, Mahavishnu on HotStore

| Component | Today | Adopts what | Source |
|---|---|---|---|
| **Akosha** | `pgvector` via `WarmStorageConfig` | `oneiric.adapters.vector.pgvector.PgvectorAdapter` | `akosha/config.py:110-141`; storage layer `akosha/storage/pgvector_warm_store.py:150` uses `_DISTANCE_METRIC` |
| **Session-Buddy** | DuckDB VSS with HNSW | `oneiric.adapters.vector.pgvector.PgvectorAdapter` | `session_buddy/adapters/reflection_adapter_oneiric.py:1049-1134`; settings `session_buddy/adapters/settings.py:24-52` (`enable_hnsw_index`, `hnsw_m=16`, `hnsw_ef_construction=200`, `hnsw_ef_search=64`, `enable_quantization`, `quantization_method="scalar"`) |
| **Mahavishnu OTel** | `HotStore` Protocol via oneiric | **no change** (ADR 017) | `mahavishnu/ingesters/otel_ingester.py:41` imports `from oneiric.adapters.vector.hot_store import HotStore`; `line 605` creates `DuckdbHotStore` for dev mode |

Mahavishnu's warm tier is **already on the oneiric substrate** (ADR 017). Phase work is for Akosha + SB consolidation only.

The settings audit (`scripts/audit_session_buddy_settings_wiring.py`) reported `enable_crackerjack_fallback` as WIRED-DYNAMIC and flagged dead-on-arrival fields for removal: `llama_server_default_model`, `llama_server_model`, `enable_global_toolkits` (per `Removed.` notes in `session_buddy/settings.py`). The earlier-v2 spec's claim of `enable_http_transport` as DEAD is **incorrect** — that field does not exist anywhere in the SB tree.

### 4.3 Cold — Akosha one wrapper, SB two surfaces

| Component | Module | Backend | Notes |
|---|---|---|---|
| **Akosha** | `akosha/storage/cold_store.py` (`class ColdStore`, line 29) | S3 / GCS / Azure via oneiric adapters | single wrapper file |
| **Session-Buddy** | `session_buddy/storage/cloud_sync.py` | **S3-only** (lazy-imports `S3StorageAdapter` from oneiric, line 54; module docstring mentions "S3/R2/MinIO", no GCS) | legacy surface |
| **Session-Buddy (new)** | `session_buddy/adapters/storage_oneiric.py` (line 338, `class GCSStorageOneiric`) | GCS via oneiric `GCSStorageAdapter` | added separately, NOT in `cloud_sync.py` |

There is **no `akosha/storage/cloud_sync.py`** — the v1/v2 spec claim is fabricated. The single wrapper is `akosha/storage/cold_store.py`.

### 4.4 Embedding — three paths, three contracts

| Component | Backend | Library | Notes |
|---|---|---|---|
| **A kosha** | oneiric shim (OpenAI-compat) | `oneiric.adapters.observability.embedding_settings.EmbeddingSettings` + `oneiric.adapters.observability.embeddings.EmbeddingService` | `akosha/processing/embeddings.py:30-31` — already a shim that subclasses oneiric's `EmbeddingService` |
| **Session-Buddy** | HTTP-only (llama-server → Ollama → None) | `httpx2.AsyncClient` created per call | `session_buddy/reflection/embeddings.py:35-97`; module-level `_embedding_cache` dict with "evict oldest 10% when size > 1024" semantics; `EMBEDDING_DIM=384` |
| **Mahavishnu OTel** | via Akosha embedding (delegates) | n/a | `EmbeddingBackend.AKOSHA = "akosha"` (otel_ingester.py:52) routes through MCP |

`oneiric.adapters.embedding.embedding_interface.py:81` already defines `EmbeddingBase` ABC with `PoolingStrategy` and `VectorNormalization` enums. **Only `openai.py` exists in `oneiric/adapters/embedding/`** — no `fastembed.py`, `llama_server.py`, `ollama.py`. Phase D adds these three adapter files.

### 4.5 Operational config — single surface exists

`OneiricSettings` (`oneiric/core/config.py:246`) is the canonical oneiric settings class with `env_prefix="ONEIRIC_"` and `env_nested_delimiter="__"`. Fields: `app`, `adapters`, `services`, `tasks`, `events`, `workflows`, `actions`, `secrets`, `remote`, `logging`, `lifecycle`, `plugins`, `profile`, `runtime_paths`, `runtime_supervisor`. `extra="allow"` is set on `model_config`, so additional fields can be added without breaking existing call sites.

The `_env_overrides` mechanism (lines 678-745) honors `{PROJECT_NAME}_*` env vars only. There is no `ONEIRIC_SUBSTRATE_*` prefix support today. Phase E1 adds `ONEIRIC__SUBSTRATE__*` resolution as a layer above `OneiricSettings` (not a parallel class).

### 4.6 MCP tool feed observability — gap

`mcp-backend-wiring-discipline.md §3` mandates `feed.entities_count`, `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total` per data feed. The Akosha, SB, and Mahavishnu MCP tools that wrap these substrates (`mcp__akosha__search_all_systems`, `mcp__session-buddy__quick_search`, `mcp__mahavishnu__pool_health`, etc.) currently do **not** expose feed-state for their substrate backing store. Phase E1 adds the methods; Phase E2 wires component `/health` endpoints to aggregate.

## 5. Architecture

### 5.1 Tier model

```
T0 hot cache: in-process LRU   → oneiric.adapters.cache.memory.MemoryCacheAdapter
T0 hot store: n/a              (no component has a hot DB distinct from warm)
T1 warm:      pgvector          → oneiric.adapters.vector.pgvector.PgvectorAdapter
T2 cold:      R2 / S3 / GCS    → oneiric.adapters.storage.{gcs,s3,local,azure}
T3 transient: process state    (DI singleton — no adapter needed)
```

Hot tier vocab rule: `cache/*` adapters are bounded + evicting; `database/*`, `vector/*`, `storage/*` are durable + queryable. "Hot tier" can be either. We name by tier label, not shape.

### 5.2 Component-to-tier mapping

```
                 Akosha                Session-Buddy           Mahavishnu OTel
T0 hot cache:    MemoryCacheAdapter   MemoryCacheAdapter      (none — process state)
T1 warm:         PgvectorAdapter      PgvectorAdapter         HotStore (via oneiric, ADR 017)
                 schema=akosha.*      schema=sb.*             (special case — see §5.5)
T2 cold:         gcs/s3 adapter       gcs/s3 adapter           (none — orchestrator)
                 prefix=akosha/       prefix=sb/
Embedding:       oneiric.embedding    oneiric.embedding        delegates to Akosha
                 (forced model=       (forced model=           via MCP (otel_ingester.py:52)
                  ONEIRIC__SUBSTRATE__EMBEDDING__    ONEIRIC__SUBSTRATE__EMBEDDING__
                  _MODEL)              _MODEL)
Operational:     OneiricSettings      OneiricSettings         OneiricSettings
                  + ONEIRIC__SUBSTRATE__* layer     + ONEIRIC__SUBSTRATE__* layer        + ONEIRIC__SUBSTRATE__* layer
```

**Schema + prefix namespaces** (one Postgres, one R2 bucket):

```
Postgres database (one):
├── akosha.*    (reflections, code graphs, traces, embeddings)
├── sb.*        (reflections, conversations, skills, knowledge_graph)
└── (reserved)  vishnu.* — out of scope; reserved for future

R2 bucket (one):
├── akosha/    (parquet archives, cold indexes)
├── sb/        (parquet archives)
└── (reserved)  vishnu/ — out of scope
```

ACL: each component's R2 token grants `ListBucket` only on its own prefix; cross-prefix reads require explicit `prefix=` parameter + audit log entry per `mcp-backend-wiring-discipline.md §3` cross-feed invariant.

### 5.3 Settings extension — `ONEIRIC__SUBSTRATE__*` layer over `OneiricSettings`

**No parallel `SubstrateSettings` class.** Cross-component defaults extend `OneiricSettings` via two mechanisms:

1. **pydantic-settings nested prefix** (`env_nested_delimiter="__"` is already set on `OneiricSettings`). New top-level fields on `OneiricSettings`:

```python
# oneiric/core/config.py (extension to OneiricSettings)
class OneiricSettings(BaseModel):
    model_config = SettingsConfigDict(
        env_prefix="ONEIRIC_",
        env_nested_delimiter="__",
        extra="allow",  # already set; permits SubstrateSettings keys to coexist
        populate_by_name=True,
    )
    # ... existing fields ...
    substrate: "SubstrateSettings" = Field(default_factory=lambda: SubstrateSettings())


class SubstrateSettings(BaseModel):
    """Cross-component defaults for the Oneiric substrate.

    Loaded from `ONEIRIC__SUBSTRATE__*` env vars via the parent
    `OneiricSettings` (`env_prefix="ONEIRIC_"`, `env_nested_delimiter="__"`).
    Per-component overrides use the standard `{PROJECT_NAME}__*` prefix
    (already supported by `_env_overrides`).

    **Note (this v5 corrects v4 inconsistency)**: `SubstrateSettings`' own
    `env_prefix` field is shown as `ONEIRIC_SUBSTRATE_` here, but when nested
    under `OneiricSettings`, pydantic-settings resolves env vars through the
    **parent's** env_prefix + delimiter (`ONEIRIC__SUBSTRATE__*`). The
    `SubstrateSettings.env_prefix` is illustrative and not the resolution
    source. Don't read this field as defining env-var resolution rules; read
    the spec §7.3 resolution chain.
    """
    model_config = SettingsConfigDict(
        env_prefix="ONEIRIC_SUBSTRATE_",
        env_nested_delimiter="__",
        extra="allow",
    )
    # Tier 0 — hot cache
    cache__backend: Literal["memory", "redis", "multitier", "persistent_kv"] = "memory"
    cache__max_entries: int | None = 10000
    cache__default_ttl_seconds: float | None = 3600

    # Tier 1 — warm (shared pgvector)
    warm__backend: Literal["pgvector"] = "pgvector"  # duckdb_vss removed
    warm__pg_url: str = "postgresql+psycopg://user:pass@localhost:5432/oneiric_substrate"
    warm__pg_pool_size: int = 8  # per-component; sum must stay < max_connections
    warm__schema_namespace: Literal["akosha", "sb"]  # vishnu reserved
    warm__embedding_dim: int = 384
    warm__distance_metric: Literal["cosine", "l2", "ip"] = "cosine"
    warm__hnsw_m: int = 16
    warm__hnsw_ef_construction: int = 200
    warm__hnsw_ef_search: int = 64
    warm__enable_quantization: bool = False
    warm__quantization_method: Literal["scalar", "binary"] = "scalar"

    # Tier 2 — cold
    cold__backend: Literal["r2", "s3", "gcs", "azure", "local"] = "r2"
    cold__bucket: str = "oneiric-substrate-shared"
    cold__prefix: str  # "akosha/" or "sb/" — set per-component
    cold__compression: Literal["snappy", "zstd", "gzip"] = "snappy"
    cold__retention_days: int = 365

    # Embedding service
    embedding__backend: Literal["openai", "fastembed", "llama_server", "ollama"] = "llama_server"
    embedding__model: str = "nomic-embed-text"  # forced single default; per-component override forbidden
    embedding__dim: int = 384
    embedding__normalize: bool = True  # substrate MUST L2-normalize when True (see §5.4)
    embedding__batch_size: int = 32
    embedding__timeout_seconds: float = 30.0
    embedding__endpoint_url: str | None = None

    # Operational
    pool__workers_per_instance: int = 3
    pool__isolation: Literal["process", "subprocess"] = "subprocess"
    pool__min_workers: int = 1
    pool__max_workers: int = 10
    retry__max_attempts: int = 3
    retry__backoff_multiplier: float = 2.0
    retry__initial_delay_seconds: float = 0.5
    circuit_breaker__failure_threshold: int = 5
    circuit_breaker__reset_timeout_seconds: int = 60
    telemetry__service_namespace: str = "oneiric-substrate"
    telemetry__service_name: str  # per-component: "akosha" / "session-buddy" / "mahavishnu"
    telemetry__exporter: Literal["otlp", "console", "jaeger"] = "otlp"
    telemetry__sample_ratio: float = 1.0
    backup__retention_days: int = 30

    # Auth (preserved through adoption per feedback-bodai-localhost-no-auth.md)
    auth__enabled: bool = False
    auth__loopback_trusted: bool = True
```

2. **Per-component overrides** via existing `{PROJECT_NAME}__*` prefix:

```
.env / shell:
  ONEIRIC__SUBSTRATE__EMBEDDING__MODEL=nomic-embed-text     # global default
  ONEIRIC__SUBSTRATE__WARM__PG_URL=postgresql://...          # global
  MAHAVISHNU__POOL__WORKERS_PER_INSTANCE=10    # per-component
```

Resolution order (highest wins):
1. `{PROJECT}__<field>` (e.g., `MAHAVISHNU__POOL__WORKERS_PER_INSTANCE`)
2. `ONEIRIC__SUBSTRATE__<field>` (cross-component default)
3. Code default in `SubstrateSettings`

`OneiricSettings.substrate` is a nested field; components access via `oneiric_settings.substrate.cache__max_entries` etc.

### 5.4 Embedding normalization layer

**Required**: `EmbeddingBase.embed()` MUST L2-normalize the output vector when `embedding__normalize=True`, **regardless of backend**. Backend-provided pre-normalized vectors (OpenAI, llama-server, Ollama pre-normalized outputs) are normalized a second time to a no-op (idempotent). Backend-provided un-normalized vectors are normalized once.

**Rationale**: pgvector `<=>` operator is cosine **distance** = 1 - cosine similarity. Cosine similarity assumes unit-norm vectors; un-normalized vectors fed to `<=>` produce nonsense rankings. Forcing substrate-side normalization guarantees metric correctness even if a backend is swapped to one whose outputs are not pre-normalized.

**Metric operator pair** (per audit finding H5):
- `<=>` cosine distance → use with normalized vectors
- `<->` L2 distance → use with un-normalized vectors
- `<#>` inner product → use with unit-norm vectors as a fast cosine alternative

Default: normalized vectors + `<=>` (cosine). `SubstrateSettings.warm__distance_metric="cosine"` is paired with `embedding__normalize=True`.

### 5.5 Mahavishnu OTel — special case

Mahavishnu's OTel ingester has invariants this design does **not** touch:

- `EmbeddingBackend.AKOSHA = "akosha"` (`otel_ingester.py:52`) routes through MCP to Akosha's embedding service. Phase D's `EmbeddingService` is aware of MCP-backed embedding backends but does not require changes here.
- `TurboQuantPGVector` (`mahavishnu/ingesters/turboquant_compressor.py`) does compressed pgvector similarity search (~5-10× memory reduction at 0.978+ cosine similarity). This is **quantization on stored vectors**, not embedding generation. Out of scope.
- `DuckdbHotStore` fallback for dev mode (`otel_ingester.py:605`). Out of scope (DuckDB HotStore is `oneiric.adapters.vector.duckdb_hot_store.DuckdbHotStore`; offline mode only).

**Phase work for Mahavishnu** is limited to Phase E2 (per-component adoption of `OneiricSettings.substrate` extensions for `telemetry__*`, `pool__*`, `retry__*`). No warm-tier, cold-tier, embedding, or cache changes for Mahavishnu.

### 5.6 Feed-state observability

Per `mcp-backend-wiring-discipline.md §3`, each substrate adapter exposes:

```python
class FeedState(TypedDict):
    entities_count: int
    last_updated_timestamp: float  # unix epoch
    errors_total: int
    cycles_total: int

# Each substrate adapter:
def get_feed_state() -> FeedState: ...
```

Adapters with `get_feed_state`:
- `oneiric.adapters.cache.memory.MemoryCacheAdapter`
- `oneiric.adapters.vector.pgvector.PgvectorAdapter`
- `oneiric.adapters.vector.hot_store.HotStore` (returns aggregated state of underlying adapter)
- `oneiric.adapters.storage.{gcs,s3,local,azure}.*`
- `oneiric.adapters.embedding.EmbeddingBase`

Component `/health` endpoints aggregate these into:

```json
{
  "status": "ok",
  "feeds": {
    "warm_pgvector": { "entities_count": 12345, "last_updated_timestamp": 1735329600.0, "errors_total": 0, "cycles_total": 42 },
    "cold_r2": { "entities_count": 42, "last_updated_timestamp": 1735329500.0, "errors_total": 0, "cycles_total": 7 },
    "embedding_service": { "entities_count": 5432, "last_updated_timestamp": 1735329599.0, "errors_total": 1, "cycles_total": 42 }
  }
}
```

503 when any feed has `last_updated_timestamp` older than `5 × polling_interval` (per `mcp-backend-wiring-discipline.md §3` alerting rule).

## 6. Components (files + boundaries)

Each phase has an Integration Contract block per `wire-up-contract.md`.

### 6.1 Phase A — Cache consolidation (SB + Akosha)

**Integration Contract**:
- **Triggered from**: `mcp__session-buddy__quick_search` first call after SB restart; `mcp__akosha__search_code_patterns` first call after Akosha restart.
- **Returns to**: cache writes go to `MemoryCacheAdapter` instance; L2 DuckDB table no longer created.
- **Demonstrable by**: `grep -rn "class QueryCacheManager\|self._l1_cache: OrderedDict" session_buddy/ akosha/` returns zero hits; `pytest session_buddy/tests/cache/ akosha/tests/cache/` all green; `python -c "from oneiric.adapters.cache.memory import MemoryCacheAdapter; c = MemoryCacheAdapter(); c.set('k', 'v'); print(c.get('k'))"` returns `v`.
- **Rollback signal**: SB or Akosha `/health` returns 503 with `feeds.cache_health == degraded`; p99 `quick_search` latency > 50ms.
- **Observability added**: OTel span `cache.adapter.memory.get/set/delete_prefix` with `cache.size` and `cache.hit_ratio` attributes.

**Files (modify)**:
- `session_buddy/cache/query_cache.py` — DELETE `class QueryCacheManager`. Per §12 replace-not-extend, deletion lands in the same commit that adopts `MemoryCacheAdapter`. **No** deprecation shim-for-one-release (this v5 corrects v4 §6.1 wording; v5 honors §12 over the obsolete "shim-then-delete" framing).
- `session_buddy/cache/query_cache.py:139-155` — DELETE runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` block.
- `session_buddy/adapters/reflection_adapter_oneiric.py:759-778` — DELETE runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` block (the duplicate at the second location).
- `session_buddy/adapters/reflection_adapter_oneiric.py:2732` — DELETE `"query_cache_l2"` string (used by `delete_table_names`).
- `akosha/config.py` — `CacheConfig` delegates to `MemoryCacheAdapter` instead of unbounded dict.

**Files (create)**:
- `session_buddy/cache/__init__.py` — re-export `MemoryCacheAdapter` so external callers can `from session_buddy.cache import MemoryCacheAdapter`.
- `akosha/cache/__init__.py` — same for Akosha.

**Tests (create/modify)**:
- `session_buddy/tests/cache/test_memory_adapter.py` — LRU eviction, TTL, delete_prefix behaviors match `MemoryCacheAdapter`.
- `akosha/tests/cache/test_memory_adapter.py` — same.
- `tests/integration/test_query_cache_l2_orphaned.py` — assert no path reads/writes `query_cache_l2` after Phase A.

**Rollback**: revert Phase A commits. Phase A is pure-substitution (no schema change); rollback restores the old `QueryCacheManager` and the two runtime `CREATE TABLE` blocks. Existing SB instances that ran Phase A lose their in-memory cache state on rollback but no data is corrupted.

### 6.2 Phase B — SB warm tier = pgvector

**Integration Contract**:
- **Triggered from**: `mcp__session-buddy__quick_search` first call after SB restart; SB warm write from `mcp__session-buddy__store_reflection`.
- **Returns to**: SB reflections persist in `sb.reflections` table (pgvector); 461 MB `reflection.duckdb` becomes cold-tier archive.
- **Demonstrable by**: `grep -rn "duckdb.*reflection\|reflection.duckdb" session_buddy/storage/ session_buddy/adapters/reflection_adapter_oneiric.py` returns zero hits; `SELECT count(*) FROM sb.reflections` matches pre-migration count; `python -c "import session_buddy.adapters.reflection_adapter_oneiric as r; print(r.SCHEMA_VERSION)"` prints `"pgvector_v1"`.
- **Rollback signal**: SB p99 `quick_search` latency > 200ms; pgvector connection error rate > 1% over 5 minutes.
- **Observability added**: OTel span `warm.pgvector.upsert/search` with `namespace`, `entities_count`, `latency_ms` attributes.

**Files (create)**:
- `scripts/migrate_sb_reflection_duckdb_to_pgvector.py` — one-shot migration script. Reads `~/.claude/data/reflection.duckdb` (461 MB), exports via Parquet intermediate, ingests into pgvector `sb.reflections` table. Verifies count + embedding equality with `numpy.allclose(old, new, atol=1e-5)` per audit finding M2.
- `session_buddy/storage/pgvector.py` — `SBWarmStore` class wrapping `PgvectorAdapter` with `warm__schema_namespace="sb"`.

**Files (modify)**:
- `session_buddy/adapters/reflection_adapter_oneiric.py` — switch from DuckDB VSS to `SBWarmStore`. Remove DuckDB HNSW knobs (`hnsw_m`, `hnsw_ef_construction`, `hnsw_ef_search`).

**Files (delete after migration verified + 90-day cold-tier archive window)**:
- `session_buddy/storage/migrations/V1__V6__*.sql` (DuckDB) — none of V1-V6 are about `query_cache_l2`; they're `initial_schema`, `add_semantic_search`, `add_workflow_correlation`, `phase4_extensions`, `ulid_migration`, `ulid_contract`. Delete only after migration script verifies zero data loss.
- `akosha/storage/migrations/` — does NOT exist as a directory; no work needed.

**Tests (create)**:
- `session_buddy/tests/integration/test_sb_warm_pgvector.py` — SB writes to pgvector; SB reads back; result matches pre-migration DuckDB round-trip within float tolerance.
- `tests/integration/test_sb_migrated_from_duckdb.py` — migration script produces counts and embeddings within tolerance.
- `tests/performance/test_sb_pgvector_p99.py` — p99 read latency ≤ 10ms from local Postgres.
- `akosha/tests/integration/test_akosha_searches_sb_namespace.py` — Akosha reads `sb.reflections` via cross-namespace search (when explicit `prefix=` granted per ACL).

**Rollback** (delete-only per audit finding 3 / pre-1.0 replace-not-extend):
1. Revert `session_buddy/adapters/reflection_adapter_oneiric.py` and `session_buddy/storage/pgvector.py` to pre-Phase-B commits.
2. Delete `scripts/migrate_sb_reflection_duckdb_to_pgvector.py`.
3. The 461 MB `reflection.duckdb` file is already kept as cold-tier archive per §10 risks; that is the recovery path, not "switch back to DuckDB". Reverting to a live DuckDB backend violates pre-1.0 replace-not-extend.
4. Schema: `warm__backend: Literal["pgvector"]` (DuckDB removed entirely; offline mode is `oneiric.adapters.vector.duckdb_hot_store.DuckdbHotStore`, not a warm backend literal).

### 6.3 Phase C — Cold consolidation (Akosha + SB)

**Integration Contract**:
- **Triggered from**: SB cold-tier write via `mcp__session-buddy__backup`; Akosha cold-tier write via `akosha.create_backup`.
- **Returns to**: cold writes land in shared R2 bucket at per-component prefix (`akosha/`, `sb/`).
- **Demonstrable by**: `grep -rn "class ColdStore\|class CloudSync" akosha/ session_buddy/` returns zero hits; `aws s3 ls s3://oneiric-substrate-shared/sb/ --profile sb-token` lists SB's archive files; SB token denied for `akosha/` prefix per ACL test.
- **Rollback signal**: R2 5xx rate > 0.5%; `cold.compression` mismatch on read.
- **Observability added**: OTel span `cold.adapter.{gcs,s3}.put/get` with `prefix`, `object_key`, `bytes`, `compression`.

**Files (modify)**:
- `akosha/storage/cold_store.py` — `ColdStore` class delegates to `oneiric.adapters.storage.{gcs,s3,azure}` directly. Drop bespoke wrapper layer.
- `session_buddy/storage/cloud_sync.py` — DELETE file (S3-only legacy surface).
- `session_buddy/adapters/storage_oneiric.py` — `GCSStorageOneiric` (already at line 338) remains; becomes the only cold adapter for SB.

**Files (create)**:
- `oneiric/adapters/storage/acl.py` — `PrefixACL` class. Maps `component_name → allowed_prefixes[]`. R2/S3/GCS policy binding happens at deployment time; `PrefixACL` enforces at runtime in dev/test environments where shared credentials are used.
- `akosha/tests/cold/test_prefix_acl.py` — Akosha token denied for `sb/*`; SB token denied for `akosha/*`; admin token can read all.
- `session_buddy/tests/cold/test_prefix_acl.py` — same.

**Tests (create)**:
- `tests/e2e/test_cold_tier_round_trip.py` — SB writes to `sb/`; Akosha reads `sb/` (when admin); data identical.
- `tests/e2e/test_cold_acl_enforced.py` — per-component prefix enforcement.

**Rollback**: revert Phase C commits. Components revert to their bespoke cold wrappers; `cloud_sync.py` is restored.

### 6.4 Phase D — Embedding consolidation

**Integration Contract**:
- **Triggered from**: `mcp__akosha__*` embedding calls; `mcp__session-buddy__*` embedding calls.
- **Returns to**: components import `oneiric.adapters.embedding` adapters directly; per-component override of model name forbidden.
- **Demonstrable by**: `grep -rn "_LLAMA_SERVER_BASE\|_try_llama_server" session_buddy/reflection/ akosha/processing/` returns zero hits; `pytest oneiric/tests/adapters/embedding/` green; alignment test passes — same text embedded via `llama_server` and `fastembed` produces same vector (within `numpy.allclose(atol=1e-5)` tolerance) when both backends use the same model.
- **Rollback signal**: SB embedding service error rate > 1%; embedding dimension mismatch between cache and warm store.
- **Observability added**: OTel span `embedding.{backend}.embed` with `backend`, `model`, `dim`, `normalize`, `latency_ms`, `cache.hit_ratio`.

**Files (create)**:
- `oneiric/adapters/embedding/fastembed.py` — `FastembedEmbeddingAdapter(EmbeddingBase)`. ONNX in-process.
- `oneiric/adapters/embedding/llama_server.py` — `LlamaServerEmbeddingAdapter(EmbeddingBase)`. HTTP to llama.cpp server. **Single `httpx.AsyncClient` per service instance** (audit finding L4), not per-call. Timeout `embedding__timeout_seconds`.
- `oneiric/adapters/embedding/ollama.py` — `OllamaEmbeddingAdapter(EmbeddingBase)`. HTTP to Ollama `/api/embed`.

**Files (modify)**:
- `oneiric/adapters/embedding/embedding_interface.py` — `EmbeddingBase.embed()` enforces L2-normalize when `embedding__normalize=True` (audit finding H5). Unit test asserts idempotence.
- `akosha/processing/embeddings.py` — shim delegates to new `EmbeddingBase` (not to `oneiric.adapters.observability.embeddings`). Or, fold shim entirely and migrate callers.
- `session_buddy/reflection/embeddings.py` — DELETE file. Replace callers with `oneiric.adapters.embedding.EmbeddingBase` import.
- `session_buddy/reflection/embeddings.py:138-141` — DELETE module-level `_embedding_cache` dict (audit finding L3); rely on `MemoryCacheAdapter`.

**Tests (create)**:
- `oneiric/tests/adapters/embedding/test_fastembed.py`
- `oneiric/tests/adapters/embedding/test_llama_server.py` (mock HTTP).
- `oneiric/tests/adapters/embedding/test_ollama.py` (mock HTTP).
- `oneiric/tests/adapters/embedding/test_normalize_layer.py` — L2-normalize enforced when `normalize=True`; idempotent on already-normalized vectors.
- `tests/integration/test_cross_component_embedding_alignment.py` — Akosha + SB produce same vector for same text under same backend (audit finding C3 + user-confirmed keep).

**Rollback**: revert Phase D commits. SB restores `session_buddy/reflection/embeddings.py`; Akosha restores the observability-shim path. Pre-Phase-D `oneiric.adapters.embedding` had only `openai.py`; rollback restores that single-adapter state.

### 6.5 Phase E1 — Settings substrate + feed-state methods

**Integration Contract**:
- **Triggered from**: any component's settings loader call (`oneiric_settings = load_settings(...)`).
- **Returns to**: `OneiricSettings.substrate.*` populated; cross-component defaults from `ONEIRIC__SUBSTRATE__*` env vars resolved.
- **Demonstrable by**: `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5 python -c "from oneiric.core.config import load_settings; s = load_settings(); print(s.substrate.cache__max_entries)"` prints `5`; `python -c "from oneiric.adapters.vector.pgvector import PgvectorAdapter; a = PgvectorAdapter(); print(a.get_feed_state())"` returns valid `FeedState`.
- **Rollback signal**: any component fails to load settings (`load_settings` raises); `get_feed_state` raises.
- **Observability added**: OTel span `settings.load` with `project_name`, `overrides_applied` count.

**Files (modify)**:
- `oneiric/core/config.py` — add `SubstrateSettings` nested class. Extend `OneiricSettings.substrate` field. Add `ONEIRIC__SUBSTRATE__` prefix scan in `_env_overrides`.
- `oneiric/adapters/cache/memory.py` — `MemoryCacheAdapter.get_feed_state()` returns `{entities_count: len(self._store), last_updated_timestamp: self._last_op_ts, errors_total: 0, cycles_total: self._ops_count}`.
- `oneiric/adapters/vector/pgvector.py` — `PgvectorAdapter.get_feed_state()`.
- `oneiric/adapters/vector/hot_store.py` — `HotStore` Protocol gains `get_feed_state` method.
- `oneiric/adapters/embedding/embedding_interface.py` — `EmbeddingBase.get_feed_state()`.

**Files (create)**:
- `oneiric/adapters/storage/acl.py` — `PrefixACL` class (audit finding H4).
- `oneiric/docs/substrate.md` — usage guide for component authors.

**Tests (create)**:
- `oneiric/tests/test_substrate_settings.py` — `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES=5` resolves correctly; per-component override wins.
- `oneiric/tests/test_get_feed_state.py` — each adapter returns valid `FeedState` with all four keys.
- `oneiric/tests/test_acl_enforced.py` — `PrefixACL` denies cross-prefix reads.

**Rollback** (pure-additive): revert Phase E1 commits. No component code touched; existing settings loaders continue working. Feed-state methods are additive; calling code that hasn't been updated simply doesn't use them.

### 6.6 Phase E2 — Per-component adoption of settings substrate

**Integration Contract**:
- **Triggered from**: Akosha, SB, Mahavishnu restart with new settings.
- **Returns to**: components read from `OneiricSettings.substrate.*` instead of their own config keys. Auth short-circuit preserved.
- **Demonstrable by**: `grep -rn "auth.enabled" akosha/config.py session_buddy/settings.py mahavishnu/core/config.py` returns references to `OneiricSettings.substrate.auth__enabled`; `auth.enabled=false` still short-circuits middleware + decorator gates per `feedback-bodai-localhost-no-auth.md`. **Note (this v5 fixes v4 typo):** SB's settings module path is `session_buddy/settings.py`, not `session_buddy/config.py` (which does not exist).
- **Rollback signal**: any component fails to start with new settings; `auth__enabled` doesn't propagate.
- **Observability added**: OTel span `settings.substrate.access` with `component`, `field`.

**Files (modify)**:
- `akosha/config.py` — replace per-component cache + warm settings with `OneiricSettings.substrate` references. Preserve `auth.enabled` short-circuit by reading from `OneiricSettings.substrate.auth__enabled`.
- `session_buddy/settings.py` — same pattern for SB.
- `mahavishnu/core/config.py` — same for Mahavishnu.

**Atomic per-file rule** (audit finding M3): each file's "delete local config + adopt OneiricSettings.substrate" lands in the SAME commit, gated by per-file flag. Partial migration during E2 rollout window is forbidden — a component's `core/config.py` cannot read from `OneiricSettings.substrate.pool__workers_per_instance` while still defining its own `MAHAVISHNU_RETRY__MAX_ATTEMPTS` (resolution order becomes ambiguous).

**Tests (create)**:
- `akosha/tests/test_substrate_settings_via_oneiric.py` — Akosha picks up `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES`.
- `session_buddy/tests/test_substrate_settings_via_oneiric.py` — same.
- `mahavishnu/tests/test_substrate_settings_via_oneiric.py` — Mahavishnu picks up `ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE`.
- `tests/integration/test_auth_short_circuit_preserved.py` — `auth.enabled=false` on each component still short-circuits both middleware AND decorator gates.

**Rollback**: revert per-component adoption commits. E1 substrate remains in place but unused. Each component's local config is restored; per-component override resolution returns to pre-Phase-E2 behavior.

### 6.7 Deployment-order contract (release-train gates)

Cross-repo rollout requires explicit ordering. The `feedback-mcp-common-version-bump-is-user.md` rule (user controls version bumps) means the user pins oneiric's new version after each Phase's oneiric-side commit lands.

```
Phase A1: oneiric MemoryCacheAdapter (already exists)
         oneiric NO-OP
Phase A2: SB + Akosha adopt MemoryCacheAdapter
         gates: BOTH components green + user bumps oneiric (no-op, already shipped)
                 + user bumps SB + user bumps Akosha
Phase B1: oneiric PgvectorAdapter (already exists) + ACL
         oneiric NO-OP on adapter; oneiric ADDS prefix ACL module
         gates: oneiric green + user bumps oneiric
Phase B2: SB migration script + pgvector adoption
         gates: oneiric ACL shipped to PyPI + SB green + user bumps oneiric + user bumps SB
                 + DuckDB → pgvector migration verified (count + numpy.allclose)
                 + freeze window: no SB reflection writes during migration script run
Phase C1: oneiric storage adapters (already exist)
         oneiric ADDS PrefixACL module (already in E1; this is just sequencing)
Phase C2: Akosha + SB drop cold wrappers
         gates: Akosha + SB green + ACL test passes
Phase D1: oneiric adds fastembed + llama_server + ollama adapters
         gates: oneiric green + L2-normalize enforcement tested
                 + cross-component alignment test green
Phase D2: Akosha + SB adopt EmbeddingBase
         gates: D1 shipped + Akosha + SB green + re-embed migration of SB reflections
Phase E1: oneiric adds SubstrateSettings + get_feed_state methods
         gates: oneiric green + feed-state aggregation tested
                 + ONEIRIC__SUBSTRATE__* env var resolution tested
Phase E2: Akosha + SB + Mahavishnu adopt OneiricSettings.substrate
         gates: E1 shipped + atomic per-file adoption in each component
                 + auth short-circuit preserved test green
```

**Freeze window for Phase B2** (audit finding 7): "no SB reflection writes for the duration of the DuckDB→pgvector migration script run". Without this, the script can't verify count/embedding equality because both stores accumulate writes during cutover. Implementation: SB `/health` returns 503 with `state=migrating` during freeze; load balancer or pool router rejects writes.

**Cross-namespace search enforcement** (audit finding 7): `WarmSubstrate.search(query, namespace="sb")` raises `PermissionError` when called from a process whose `OneiricSettings.substrate.warm__schema_namespace` is `"akosha"` AND no explicit `cross_namespace_grant` is set. **Phase B's** tests assert this (this v5 corrects v4 §6.7 mis-cite; Phase A predates cross-namespace ACL — Phase A Tests lack warm-tier semantics).

## 7. Data flow

### 7.1 Cross-component embedding + warm-tier write/read

```mermaid
sequenceDiagram
    participant SB as Session-Buddy (sb.* schema)
    participant Embed as oneiric.embedding.LlamaServerEmbeddingAdapter
    participant Warm as oneiric.adapters.vector.pgvector.PgvectorAdapter
    participant PG as Postgres (substrate DB, sb. schema)
    participant Akosha as Akosha (akosha.* schema)

    SB->>Embed: embed(reflection.text)
    Embed->>Embed: L2-normalize (when SubstrateSettings.substrate.embedding__normalize=True)
    Embed-->>SB: list[float] (dim=384, unit norm)

    SB->>Warm: upsert_embedding(sb.reflections, embedding, metadata)
    Warm->>PG: INSERT INTO sb.reflections (...)  -- oneiric handles schema namespace
    PG-->>Warm: row id
    Warm-->>SB: ack

    Note over Warm: get_feed_state() → {entities_count: 12345, last_updated_timestamp: now, errors_total: 0, cycles_total: 42}

    Akosha->>Warm: search(query_embedding, top_k=10, namespace="sb")  -- explicit cross-namespace
    Warm->>Warm: assert caller_namespace == "akosha" → grant cross_namespace permission via ACL
    Warm->>PG: SELECT ... FROM sb.reflections ORDER BY embedding <=> $1 LIMIT 10
    PG-->>Warm: 10 rows
    Warm-->>Akosha: results

    Note over Akosha: Cross-namespace search is explicit and audited;<br/>Akosha typically searches akosha.* only
```

### 7.2 Cold-tier write with prefix + ACL

```mermaid
sequenceDiagram
    participant SB as Session-Buddy
    participant Cold as oneiric.adapters.storage.gcs.GCSStorageAdapter
    participant ACL as oneiric.adapters.storage.acl.PrefixACL
    participant R2 as R2 bucket (shared)

    SB->>ACL: assert_write("sb/", "reflections_archive/2026-09-27.parquet")
    ACL-->>SB: allowed

    SB->>Cold: write_parquet(table="reflections_archive", rows=1000)
    Cold->>Cold: build key = "{cold.prefix}{table}/2026-09-27.parquet" = "sb/reflections_archive/2026-09-27.parquet"
    Cold->>Cold: compress snappy (SubstrateSettings.substrate.cold__compression)
    Cold->>R2: PUT sb/reflections_archive/2026-09-27.parquet
    R2-->>Cold: etag

    Note over Cold: get_feed_state() → {entities_count: 42, last_updated_timestamp: now, errors_total: 0, cycles_total: 7}

    Akosha->>ACL: assert_read("sb/", "reflections_archive/2026-09-27.parquet")
    ACL->>ACL: deny — akosha not in sb/ prefix allowlist
    ACL-->>Akosha: PermissionError
```

### 7.3 Settings resolution chain

```
.env / shell:
  ONEIRIC__SUBSTRATE__EMBEDDING__MODEL=nomic-embed-text          # global default (forced single model)
  ONEIRIC__SUBSTRATE__WARM__PG_URL=postgresql://...               # global
  MAHAVISHNU__POOL__WORKERS_PER_INSTANCE=10         # per-component override

Resolution:
  load_settings(project_name="mahavishnu")
    → OneiricSettings (env_prefix="ONEIRIC_")
        .substrate = SubstrateSettings (env_prefix="ONEIRIC_SUBSTRATE_")
          .embedding__model  ←  ONEIRIC__SUBSTRATE__EMBEDDING__MODEL (resolved)
          .pool__workers_per_instance
              ←  MAHAVISHNU__POOL__WORKERS_PER_INSTANCE  (per-component, wins)
              ←  ONEIRIC__SUBSTRATE__POOL__WORKERS_PER_INSTANCE  (global default, fallback)
              ←  default=3  (code default, final fallback)
        .auth__enabled  ←  ONEIRIC__SUBSTRATE__AUTH__ENABLED  (or per-component override)
        .auth__loopback_trusted  ←  ONEIRIC__SUBSTRATE__AUTH__LOOPBACK_TRUSTED
```

## 8. Testing

### Layer 1 — Unit tests (substrate / adapters)

| Test file | Asserts |
|---|---|
| `oneiric/tests/adapters/cache/test_memory_get_feed_state.py` | `get_feed_state` returns valid `FeedState`; counters increment correctly |
| `oneiric/tests/adapters/vector/test_pgvector_get_feed_state.py` | same |
| `oneiric/tests/adapters/embedding/test_normalize_layer.py` | L2-normalize enforced when `normalize=True`; idempotent on already-normalized |
| `oneiric/tests/adapters/embedding/test_llama_server.py` | mock HTTP; one AsyncClient per service instance, not per call |
| `oneiric/tests/test_substrate_settings.py` | `ONEIRIC__SUBSTRATE__*` env vars resolve; per-component override wins; defaults match |
| `oneiric/tests/test_acl_enforced.py` | PrefixACL denies cross-prefix reads |

### Layer 2 — Component integration tests

| Test file | Asserts |
|---|---|
| `session_buddy/tests/cache/test_memory_adapter.py` | LRU eviction + TTL + delete_prefix behavior matches `MemoryCacheAdapter` |
| `session_buddy/tests/integration/test_sb_warm_pgvector.py` | SB writes to pgvector; SB reads back; result matches pre-migration within tolerance |
| `akosha/tests/cache/test_memory_adapter.py` | Akosha cache delegates to `MemoryCacheAdapter` |
| `akosha/tests/integration/test_akosha_searches_sb_namespace.py` | Cross-namespace search via ACL grant |
| `akosha/tests/test_substrate_settings_via_oneiric.py` | Akosha picks up `ONEIRIC__SUBSTRATE__CACHE__MAX_ENTRIES` |
| `session_buddy/tests/test_substrate_settings_via_oneiric.py` | same |
| `mahavishnu/tests/test_substrate_settings_via_oneiric.py` | same |
| `tests/integration/test_auth_short_circuit_preserved.py` | `auth.enabled=false` still short-circuits middleware + decorator gates |
| `tests/integration/test_cross_component_embedding_alignment.py` | Akosha + SB produce same vector for same text under same backend (audit C3) |
| `tests/e2e/test_cold_tier_round_trip.py` | SB writes `sb/`; Akosha reads `sb/` (admin); data identical |
| `tests/e2e/test_cold_acl_enforced.py` | per-component prefix enforcement |

### Layer 3 — Migration + feed-state e2e

| Test file | Asserts |
|---|---|
| `tests/integration/test_sb_migrated_from_duckdb.py` | Migration script: count + numpy.allclose(atol=1e-5) match (audit M2) |
| `tests/performance/test_sb_pgvector_p99.py` | p99 read latency ≤ 10ms from local Postgres |
| `tests/integration/test_health_feed_state_aggregated.py` | Each component's `/health` aggregates four feed signals per `mcp-backend-wiring-discipline.md §3` |
| `tests/integration/test_query_cache_l2_orphaned.py` | No path reads/writes `query_cache_l2` after Phase A |

### Test infrastructure (no new project deps)

- Local Postgres + pgvector: **v5 correction** — `akosha/dev/docker-compose.yml` does not exist in the akosha tree. Operators must either (a) add a `dev/` directory with a docker-compose for local pgvector (CREATE task in Phase B Task 1 of `phase-b.md`), or (b) use Homebrew `postgres` + `pgvector` extension, or (c) reuse a sibling repo's compose file. Per Phase B Task 1 Step 4 the implementer picks one.
- Local R2: existing `fake-gcs-server` (Homebrew) covers S3-compat endpoint + GCS-compat endpoint.
- Local llama-server: existing setup at `http://localhost:8081`.
- Local Ollama: existing setup at `http://localhost:11434`.

### Test parity per phase

Each phase has unit + integration tests AND a regression test that proves legacy behavior is preserved.

- Phase A: legacy query_cache tests still pass for non-L2 cases; L2 references removed from code.
- Phase B: legacy `reflection.duckdb` test passes against pgvector mirror (read-only mode) during transition window; `query_cache_l2` orphaned-table test verifies no path reads it.
- Phase C: legacy cold_store tests still pass via new oneiric adapter delegates.
- Phase D: legacy embedding tests pass via new `EmbeddingBase`; alignment test proves backend abstraction.
- Phase E1: no component tests touched (substrate additive).
- Phase E2: legacy operational-config tests pass after adoption; auth short-circuit preserved.

## 9. Validation

**Pre-merge** (per phase):
- `pytest oneiric/tests/ akosha/tests/ session_buddy/tests/ mahavishnu/tests/` all green.
- `grep -rn "class QueryCacheManager\|class ColdStore\|class CloudSync" akosha/ session_buddy/` returns hits only in migration shims (target: zero).
- `grep -rn "class SubstrateSettings" .` returns exactly one hit (in `oneiric/core/config.py` as nested field; NOT a top-level class).
- `grep -rn "_LLAMA_SERVER_BASE\|_try_llama_server" session_buddy/reflection/ akosha/processing/` returns zero hits post-Phase D.
- `grep -rn "fastembed\." akosha/ session_buddy/` returns hits only in `oneiric/adapters/embedding/`.

**Post-merge** (all phases shipped):
- Akosha + SB + Mahavishnu each install only `oneiric` as substrate dependency; no direct embedding/cold/warm imports outside oneiric adapters.
- Cross-component embedding alignment test: Akosha + SB produce same vector for same text under same backend.
- Cold-tier ACL test: SB token denied for `akosha/`; admin token can read all.
- Feed-state aggregation: `curl http://localhost:8682/health | jq .feeds` shows four substrate feeds per component (warm, cold, cache, embedding).
- Auth short-circuit preserved: `auth.enabled=false` on any component still short-circuits both middleware AND decorator gates.

## 10. Risks

| Risk | Mitigation |
|---|---|
| **SB migration from DuckDB → pgvector loses data** | Migration script writes Parquet intermediate; verifies count + numpy.allclose(atol=1e-5); 461 MB DuckDB file kept as cold-tier archive for 90 days; freeze window during migration |
| **pgvector connection pool saturation** | `SubstrateSettings.substrate.warm__pg_pool_size=8` per component; sum = 24 connections (Akosha + SB + Mahavishnu OTel); default Postgres `max_connections=100` has headroom; Prometheus alert on `pg_stat_activity` count > 80 |
| **Cross-namespace data leak** via shared R2 bucket | `PrefixACL` denies cross-prefix reads by default; explicit `cross_namespace_grant` required; ACL test in `tests/e2e/test_cold_acl_enforced.py` |
| **Embedding backend drift** — Akosha on fastembed, SB on llama-server produces different vectors | Phase D forces single default model `ONEIRIC__SUBSTRATE__EMBEDDING__MODEL`; per-component override forbidden; Phase D2 includes re-embed migration of SB's existing reflections via the chosen backend |
| **Embedding normalization drift** — backend returns un-normalized vectors, metric wrong | `EmbeddingBase.embed()` enforces L2-normalize when `embedding__normalize=True` regardless of backend; unit test `test_normalize_layer.py` asserts idempotence and metric operator pairing (`<=>` for cosine + normalized) |
| **Operational settings override conflict** during E2 partial migration | Atomic per-file adoption rule: each file's "delete local config + adopt OneiricSettings.substrate" lands in same commit; partial migration forbidden |
| **Oneiric is now a hard substrate dependency** for SB + Akosha | Add `oneiric>=<pinned>` to `[project.dependencies]` in each component's `pyproject.toml`; CI guard test for minimum version |
| **Cross-component import direction violation** | Per audit finding 7: Phase A tests assert cross-namespace reads raise `PermissionError` without explicit grant |
| **Rollback complexity** — 6 phases across 4 repos | Each phase has release-train gate + atomic per-file adoption in Phase E2; reverting one phase does not break others |

## 11. Decision rule

The phases land in order A → B → C → D → E1 → E2. Each phase has a release-train gate (§6.7) that must clear before the next phase begins. Within each phase:

1. **Adapter module first** (adopt or extend existing oneiric.adapters).
2. **Adapter / wiring layer second** (component imports adapter directly).
3. **Legacy code deleted third** (after migration verified).
4. **Tests added at every step** (red → green → refactor).
5. **Rollback test last** (verify revert path restores pre-phase behavior).

If any step fails, stop. Don't proceed to the next phase until the current phase is green.

## 12. Universal invariants (apply to all phases)

- **Pre-1.0 replace, not deprecate** (`feedback-no-backwards-compat-pre-1.0.md`). Old code paths deleted in the same commit that replaces them.
- **Direct merge to main, no PRs** (`bodai-pre-1.0-merge-policy.md`).
- **No `git push` for bodai** without explicit approval (`feedback-bodai-push-is-user-controlled.md`).
- **No version bumps** in any Bodai `pyproject.toml` — user does (`feedback-mcp-common-version-bump-is-user.md`).
- **No `Co-Authored-By` trailer** (`feedback-no-claude-code-coauthor-attribution.md`).
- **Author email** `les@wedgwoodwebworks.com` (`git-author-email-correct-domain.md`).
- **Auth short-circuit preserved** across substrate adoption. `auth.enabled: false` on any consumer MUST continue to short-circuit both middleware AND decorator gates per `feedback-bodai-localhost-no-auth.md`. Phase E2 explicitly carries `auth__enabled` and `auth__loopback_trusted` through `OneiricSettings.substrate`.
- **Wire-up contract per `.claude/decisions/wire-up-contract.md`** — every phase has an Integration Contract block (Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added). Verified at plan-promotion time per the `tests/test_plan_citations.py` CI guard.
- **MCP backend wiring discipline per `.claude/decisions/mcp-backend-wiring-discipline.md`** — every substrate adapter exposes `get_feed_state() -> {entities_count, last_updated_timestamp, errors_total, cycles_total}`; component `/health` aggregates.
- **Cross-component imports show dependency direction** — REQ entries that touch shared state include one-line dependency diagram. Akosha → Mahavishnu imports (inverted case) forbidden except via MCP/HTTP.

## 13. Critical files

### oneiric (extend existing; no new packages)

- `oneiric/core/config.py` — add `SubstrateSettings` nested class; extend `OneiricSettings.substrate` field; add `ONEIRIC__SUBSTRATE__` prefix scan in `_env_overrides` (Phase E1)
- `oneiric/adapters/cache/memory.py` — add `get_feed_state()` method (Phase E1)
- `oneiric/adapters/vector/pgvector.py` — add `get_feed_state()` method (Phase E1)
- `oneiric/adapters/vector/hot_store.py` — `HotStore` Protocol gains `get_feed_state` method (Phase E1)
- `oneiric/adapters/embedding/embedding_interface.py` — `EmbeddingBase.embed()` enforces L2-normalize; add `get_feed_state()` (Phase D + E1)
- `oneiric/adapters/embedding/fastembed.py` — new adapter (Phase D)
- `oneiric/adapters/embedding/llama_server.py` — new adapter (Phase D)
- `oneiric/adapters/embedding/ollama.py` — new adapter (Phase D)
- `oneiric/adapters/storage/acl.py` — `PrefixACL` class (Phase C + E1)

### akosha (substrate adoption via existing oneiric adapters)

- `akosha/storage/cold_store.py` — `ColdStore` class delegates to `oneiric.adapters.storage.*` directly (Phase C)
- `akosha/processing/embeddings.py` — shim delegates to `oneiric.adapters.embedding.EmbeddingBase` (Phase D)
- `akosha/config.py` — `CacheConfig` delegates to `MemoryCacheAdapter` (Phase A); `auth__enabled` propagates from `OneiricSettings.substrate` (Phase E2)
- `akosha/storage/pgvector_warm_store.py` — already on pgvector since 2026-09-27; consolidate naming (Phase B)

### session-buddy (substrate adoption)

- `session_buddy/cache/query_cache.py` — DELETE `class QueryCacheManager`; DELETE runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` block at line 139 (Phase A)
- `session_buddy/adapters/reflection_adapter_oneiric.py` — DELETE runtime `CREATE TABLE IF NOT EXISTS query_cache_l2` block at line 759; DELETE `"query_cache_l2"` reference at line 2732 (Phase A); switch warm tier to `PgvectorAdapter` (Phase B)
- `session_buddy/storage/cloud_sync.py` — DELETE S3-only legacy surface (Phase C)
- `session_buddy/storage/pgvector.py` — `SBWarmStore` class wrapping `PgvectorAdapter` (Phase B)
- `session_buddy/storage/migrations/V1__V6__*.sql` — DELETE after Phase B migration verified (none of these migrations are about `query_cache_l2`; actual contents: `initial_schema`, `add_semantic_search`, `add_workflow_correlation`, `phase4_extensions`, `ulid_migration`, `ulid_contract`)
- `session_buddy/reflection/embeddings.py` — DELETE; callers use `oneiric.adapters.embedding.EmbeddingBase` (Phase D)
- `session_buddy/settings.py` — references `OneiricSettings.substrate.auth__enabled` for short-circuit (Phase E2)

### mahavishnu (settings-only adoption; OTel stays on HotStore per ADR 017)

- `mahavishnu/core/config.py` — references `OneiricSettings.substrate.{pool,telemetry,retry}__*` (Phase E2)
- `mahavishnu/ingesters/otel_ingester.py` — UNCHANGED (HotStore already adopted per ADR 017)
- `mahavishnu/ingesters/turboquant_compressor.py` — UNCHANGED (TurboQuantPGVector out of scope)

### Tests

- `oneiric/tests/test_substrate_settings.py` (Phase E1)
- `oneiric/tests/test_get_feed_state.py` (Phase E1)
- `oneiric/tests/test_acl_enforced.py` (Phase C + E1)
- `oneiric/tests/adapters/embedding/test_fastembed.py` (Phase D)
- `oneiric/tests/adapters/embedding/test_llama_server.py` (Phase D)
- `oneiric/tests/adapters/embedding/test_ollama.py` (Phase D)
- `oneiric/tests/adapters/embedding/test_normalize_layer.py` (Phase D)
- `session_buddy/tests/cache/test_memory_adapter.py` (Phase A)
- `session_buddy/tests/integration/test_sb_warm_pgvector.py` (Phase B)
- `session_buddy/tests/test_substrate_settings_via_oneiric.py` (Phase E2)
- `akosha/tests/cache/test_memory_adapter.py` (Phase A)
- `akosha/tests/integration/test_akosha_searches_sb_namespace.py` (Phase B)
- `akosha/tests/cold/test_prefix_acl.py` (Phase C)
- `akosha/tests/test_substrate_settings_via_oneiric.py` (Phase E2)
- `mahavishnu/tests/test_substrate_settings_via_oneiric.py` (Phase E2)
- `tests/e2e/test_cold_tier_round_trip.py` (Phase C)
- `tests/e2e/test_cold_acl_enforced.py` (Phase C)
- `tests/integration/test_sb_migrated_from_duckdb.py` (Phase B)
- `tests/integration/test_cross_component_embedding_alignment.py` (Phase D)
- `tests/integration/test_auth_short_circuit_preserved.py` (Phase E2)
- `tests/integration/test_health_feed_state_aggregated.py` (Phase E2)
- `tests/test_plan_citations.py` (per `wire-up-contract.md` additional requirements — CI guard)

### Migrations

- `scripts/migrate_sb_reflection_duckdb_to_pgvector.py` (Phase B, one-shot)

### Documentation

- `docs/specs/2026-09-27-shared-bodai-substrate-design.md` — this file (v4)
- `docs/plans/2026-09-27-shared-bodai-substrate-phase-{a,b,c,d,e1,e2}.md` — six plan files (one per phase), each with Integration Contract block at top per `wire-up-contract.md`
- `oneiric/docs/substrate.md` — usage guide for component authors (Phase E1)
- `akosha/docs/migrated-to-oneiric-substrate.md` — migration note (Phase A + B + C)
- `session-buddy/docs/migrated-to-oneiric-substrate.md` — migration note (Phase A + B + C + D)

## 14. References

- `feedback-bodai-core-component-taxonomy.md` — Bodai Core = 5 (vishnu/ak/sb/cj/oneiric); mcp-common is Library.
- `feedback-bodai-push-is-user-controlled.md` — no push without approval.
- `feedback-mcp-common-version-bump-is-user.md` — no version bumps in pyproject.toml.
- `feedback-no-backwards-compat-pre-1.0.md` — replace, not deprecate.
- `bodai-pre-1.0-merge-policy.md` — direct merge to main, no PRs.
- `feedback-bodai-localhost-no-auth.md` — `auth.enabled:false` short-circuits all gates.
- `feedback-no-bodai-mentions-in-mcp-repos.md` — `*-mcp` repos are NOT ecosystem members.
- `.claude/decisions/wire-up-contract.md` — Integration Contract blocks per phase.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — `get_feed_state()` per adapter.
- `oneiric/adapters/vector/hot_store.py:40` — `class HotStore(Protocol)` (ADR 017).
- `oneiric/core/config.py:246` — `class OneiricSettings(BaseModel)` (canonical settings class).
- `akosha/config.py:71-78` — `HotStorageConfig` migration note (2026-09-27).
- `akosha/processing/embeddings.py:30-31` — Akosha embedding shim delegates to oneiric.

## 15. Revision history

| Date | Revision | Author | Notes |
|---|---|---|---|
| 2026-09-27 | v1 | platform-team | Initial design: 5 substrate moves (tier simplification + 4 config consolidations) consolidated into 5 phases. |
| 2026-09-27 | v2 | platform-team | Split Phase E into E1 (operations substrate, oneiric-only, additive) + E2 (per-component adoption). Total: 6 phases. Self-review fixes: replaced "TBD" with verification step; annotated `duckdb_vss` as offline-mode-only; clarified `vishnu` schema namespace. |
| 2026-09-27 | v3 | platform-team | **Rewrite from scratch after 3-agent spec audit (code-explorer + code-reviewer + architecture-council) found 31 issues.** Corrected: removed proposed `oneiric.substrate.*` namespace (existing `oneiric.adapters.*` is the substrate); removed parallel `SubstrateSettings` class (extend `OneiricSettings` via pydantic-settings nested prefix); dropped `duckdb_vss` from warm backend literal; corrected file paths (e.g., `akosha/storage/cold_store.py` not `akosha/cold_store.py`; `akosha/processing/embeddings.py` not `akosha/embeddings.py`; `session_buddy/reflection/embeddings.py` not `session_buddy/embeddings.py`); corrected V1-V6 migration contents (none are `query_cache_l2`; the table is created at runtime in 2 places); corrected DEAD field names (`enable_global_toolkits`, `llama_server_default_model`, `llama_server_model` — not `enable_http_transport`); acknowledged Mahavishnu OTel already on `HotStore` via ADR 017 (Phase work is for Akosha + SB only); added Integration Contract blocks per phase per `wire-up-contract.md`; added deployment-order release-train gates per phase; added `get_feed_state()` instrumentation per `mcp-backend-wiring-discipline.md §3`; added `PrefixACL` for cold-tier cross-namespace reads; defined embedding normalization layer (`L2-normalize when normalize=True`); forced single default embedding model across components; defined atomic per-file adoption rule for Phase E2. |
| 2026-09-27 | v5 | platform-team | **Fix pass after 2-agent final-review.** Hard citation drifts fixed (`class QueryCacheManager` actual line 59 not 90 in phase-a cited files; `_embedding_cache` dict actual line 116 not 138-141 in phase-d). Structural gaps closed: Phase B adds Task 6 (V1-V6 SQL migration deletion after archive window) + Task 7 (`tests/performance/test_sb_pgvector_p99.py`); Phase B Task 5 adds `akosha/tests/integration/test_akosha_searches_sb_namespace.py` (positive cross-namespace path); Phase D Task 6 renamed to "Cross-backend alignment" and adds llama-server vs fastembed alignment test required by §6.4 Demonstrable by; Phase E1 adds Task 7 (`get_feed_state()` on storage adapters per §5.6); Phase E1 `SubstrateSettings` nested in `oneiric/core/config.py` per §9 validation (was sibling module). High-priority hygiene: cross-component dep diagrams added per wire-up-contract §2 across all 6 plans; cache_max_entries → cache__max_entries (double underscore) per spec §5.3; `auth__loopback_trusted` exercised by parametrized test in phase-e2 Task 4; `normalize=True` pulled from `SubstrateSettings.embedding__normalize` in phase-d Task 4; /health 503 trigger logic asserted via mocked stale feed in phase-e2 Task 5; task-level IC blocks + Observability added per missing-task gaps. Soft drift fixes (citation name corrections): `class CloudSync` → `class CloudSyncMethod` (line 66 of `cloud_sync.py`); `delete_table_names` → `reset_database` (line 2705); `httpx.AsyncClient` → `httpx2.AsyncClient` (`import httpx2 as httpx`); `akosha/dev/docker-compose.yml` → either CREATEd task or alternative local stack (operator decision); `mahavishnu/mcp/server.py` → `mahavishnu/mcp/server_core.py`. **Spec internal contradictions fixed**: §6.1 "thin shim for one release then delete" reverted — pre-1.0 replace-not-extend per §12 (no shim-for-one-release); §4.6 + §6.7 mis-cite "Phase A's tests assert this" → corrected to Phase B; §6.6 typo `session_buddy/config.py` → `session_buddy/settings.py`; §5.3 env_prefix ambiguity resolved (parent `env_prefix` + delimiter is the resolution source, not the nested `SubstrateSettings.env_prefix`). |
| 2026-09-27 | v4 | platform-team | **Rename pass per `feedback-no-bodai-prefix-in-config-names.md`.** Env var prefix `BODAI__*` → `ONEIRIC__SUBSTRATE__*`; settings class `BodaiSettings` → `SubstrateSettings`; field access `OneiricSettings.bodai.X` → `OneiricSettings.substrate.X`; test file names `test_bodai_settings*` → `test_substrate_settings*`; R2 bucket `bodai-shared` → `oneiric-substrate-shared`; Postgres DB `bodai` → `oneiric_substrate`; OTel span `settings.bodai.access` → `settings.substrate.access`; OTel namespace `telemetry__service_namespace` default `"bodai"` → `"oneiric-substrate"`; spec topic slug `shared-bodai-substrate` → `shared-oneiric-substrate`. Rationale: oneiric is the foundation that publishes substrate defaults — components outside the Bodai ecosystem may adopt oneiric without opting into Bodai, so prefixing defaults with `BODAI__*` misleads operators about scope. Reserve `BODAI__*` for settings that genuinely require Bodai-orchestration membership (Mahavishnu pool state, Akosha↔Mahavishnu coordination, ecosystem-wide observability tags). Memory file references in §14 (e.g., `feedback-bodai-*`) and the spec file path itself retain `bodai` because those are pre-existing identifiers, not new config names. |
