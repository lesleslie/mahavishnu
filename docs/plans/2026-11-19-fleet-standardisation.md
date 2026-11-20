---
status: draft
role: implementation
kind: plan
date: 2026-11-19
last_reviewed: 2026-11-19
topic: fleet-standardisation
plan_kind: implementation
related_plans:
  - akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md
  - session-buddy/docs/plans/2026-11-06-fleet-embedding-width-768.md
  - session-buddy/docs/plans/2026-11-06-conversation-transcript-ingestion.md
  - oneiric/docs/plans/2026-08-22-hybrid-embeddings-design.md
  - mahavishnu/docs/plans/2026-11-05-config-that-nobody-reads.md
  - mahavishnu/docs/plans/2026-10-14-decision-adapter-category.md
---

# Fleet Standardisation — getting Akosha, Mahavishnu, Session-Buddy, Oneiric, Crackerjack and mcp-common working as intended

**Goal:** one embedding model at one width produced by one client under one
fleet contract; every health feed reporting real data; the conversation
corpus reaching the store that analyses it; and the warm tier searchable.

**This plan is the fleet spine.** It sequences work across six repositories
and points at the per-repo plans that hold the detail. It does not repeat
their task lists.

**It finishes an approved-but-abandoned design rather than starting a new
one.** Oneiric's `docs/plans/2026-08-22-hybrid-embeddings-design.md`
(`status: active`, *"Approved Design"*) already specified consolidating
every embedding implementation into oneiric behind a single probe chain. Its
Phases 1–4 were partly built; **Phase 5 — "Runtime verification: all
components restart, all tools work end-to-end" — was never done**, and that
is what this plan discovers and completes.

---

## 1. What "working as intended" means

Five outcomes, each independently checkable:

| # | Outcome | How it is checked |
|---|---|---|
| **O1** | One embedding model (`text-embedding-3-small`) at one width (1536 native), produced by one client (Oneiric's), under one contract — `(model, dimensions, space_version)` | Every component reports the same model, width and space id on `/health` |
| **O2** | No health feed is empty because its producer is dead, mis-wired, or filtered | `/health` `_aggregate.status == "ok"` and `data_feeds_ok == true`; each feed's `source` names a producer that is running |
| **O3** | The conversation corpus reaches the store that analyses it | `conversations` has rows, written by a named producer |
| **O4** | Semantic search, trends, anomalies, correlation, the knowledge graph and fitness analysis all return real data | Each tool returns rows, not "Insufficient data" and not a fallback placeholder |
| **O5** | Aging moves hot→warm→cold on a schedule, and the warm tier is searchable | `akosha_warm` has an HNSW index; `EXPLAIN` shows an index scan; the cold exporter has exported records |

### Settled decisions — do not reopen these

| Decision | Value | Why |
|---|---|---|
| Fleet width | **1536, native** (`text-embedding-3-small`, no `dimensions` truncation) | Operator decision, 2026-11-19. The corpus is small but **not empty** — Session-Buddy holds 156 embedded conversations at 768, Akosha holds 7 trace vectors at 384 — so a quality gap is not provably worthless; it is simply not yet *measured*. The contract makes a later model change a re-embed, not a migration. See §1.1. |
| Llama.cpp `dimensions` | **not sent** | llama.cpp does not implement the `dimensions` parameter (issue #25210 open). Truncation must be client-side, and the fleet's client is OpenAI-compatible. |
| Local fallback legs | **llama-server, model2vec and the mock leave the semantic chain** | Hardware-limited today, and the mock is a startup failure, not a fallback. A different model is a different vector space, not a failover. |
| The `dimensions` parameter itself | **sent only when the target width is not the model's native width** | 1536 is `text-embedding-3-small`'s native width, so sending it is a no-op that invites a future reader to think truncation is in play. But the rule cannot be "never send": `text-embedding-3-large` at 1536 *requires* `dimensions: 1536`, and a rule of "never send" would make that model unreachable. Omit when native, send when truncating — and record the sent value in the contract either way. |
| The model itself | **a contract field with a re-embed path, not a constant** | `text-embedding-3-small` has not been updated since late 2023 and sits well behind the current open-weights leader. Price is *not* the reason to keep it — at fleet volume the entire embedding bill is single-digit dollars a month. See §1.1 for the review trigger. |
| Records | **may be lost** | Operator decision, 2026-11-19. No legacy support, no backwards-compat shims. Rebuilds are cheap; the data is not worth a shim. |
| Provider failover | **same model, same space** | A failover to a different model is not a failover — it is a different vector space with the same width, and it is silently mixable. |

### 1.1 Why `text-embedding-3-small`, and when that changes

The model is the one decision here with a shelf life, so the reasoning is
recorded here rather than left implicit.

**What the fleet runs today.** Nothing is at 1536. Session-Buddy serves
**768** (`memory/embedding_dim.py:39` `DEFAULT_EMBEDDING_DIM = 768`;
`reflection/embeddings.py:81` `OPENAI_EMBEDDING_DIM = 768`) and asks
`text-embedding-3-small` for `{"dimensions": 768}` — a **truncation of a
native-1536 model**. Mahavishnu resolves to the 384-wide mock;
Crackerjack runs 384-wide SHA-256 hashes. "1536 native" is therefore a
*target*, not a current state, and reaching it is a re-embed of a small
corpus rather than a migration of a large one.

**The corpus, measured.** Session-Buddy's reflection store holds 156
conversations, all with embeddings. Akosha's `public.vectors_otel_traces`
holds 7 rows, all 384-dim. Session-Buddy's `conversations` table holds 0
rows. Small, but not empty — this plan's earlier "empty corpus" wording
overstated it.

**The quality gap is real.** `text-embedding-3-small` scores ~62.3 MTEB
and **51.7 on MTEB retrieval (nDCG@10)**, against ~64.6 / 55.4 for
`text-embedding-3-large` and ~65.2 / 58.4 for `cohere embed-v4`. Two
caveats: OpenAI's figures come from its own 2024 evaluation and are not
comparable to the MTEB v2 boards the newer models report on, and
**retrieval**, not the composite average, is what a memory fleet is judged
on.

**Price does not settle it.** At fleet volume the entire embedding bill is
single-digit dollars a month — 10M tokens/month is $0.20 at 3-small and
$1.30 at 3-large. The 6.5x difference is a rounding error, and it must
not be allowed to decide the fleet's retrieval quality.

**What actually holds the decision in place.** Two things, and only the
second is real:

1. *The gateway wiring.* The semantic-cache plugin is configured for
   `text-embedding-3-small` at `dimension: 1536`, and the OpenAI key's
   allowlist contains it. This is **not** a constraint: it is a model id
   in a config, and changing it is a one-line edit plus a cache re-key.
2. *No measurement.* Nobody has run a retrieval benchmark against the
   fleet's own corpus. The 2026-11-20 memory-retrieval-quality plan
   (Phase 1: a recall benchmark with a committed baseline) is the
   instrument that settles it.

**The trigger.** Re-open the model when the recall benchmark exists and
the baseline shows retrieval quality is the binding constraint — not when
a newer model is published. At that point the field is
`text-embedding-3-large` at 1536 (same provider, same base URL, same
auth, one extra request field) against `cohere embed-v4` at 1536 (better
retrieval, 128K context, built-in int8/binary output — but a new
provider, a new credential, and a gateway that does not reliably honour
the requested width for Cohere: Vercel's AI Gateway issue #16272 shows
`cohere/embed-v4.0` intermittently returning 1536 when a narrower
`dimensions` was requested, while the OpenAI control behaves).

---

## 2. The three root causes

Everything that is not green traces to three causes. Fixing them in order is
the whole job.

### RC-1 — The chain cannot reach the fleet's standard provider, and the fallback hides the break

Oneiric's `EmbeddingService` probes four legs and no more
(`oneiric/adapters/observability/embeddings.py:110-112`):

```
llama_cpp → minimax → model2vec → mock
```

**There is no `openai` leg**, even though `oneiric/adapters/embedding/openai.py`
ships full `dimensions` support and is exercised only by Oneiric's own tests.
The `llama_cpp` leg sends **no auth header and no `dimensions`**
(`:391-403`), so pointing it at Bifrost returns `401 virtual_key_required`,
the probe returns `None`, and the service **silently** selects the mock.

**Two further blocks sit behind the missing leg**, and they are the reason
"just add an OpenAI leg" is not a one-line change:

- **The OpenAI adapter cannot authenticate to Bifrost.**
  `adapters/embedding/openai.py:98-106` passes no `default_headers`, so it
  sends `Authorization: Bearer <provider key>` — and Bifrost rejects a
  provider key with `401 virtual_key_required`. The SDK accepts
  `default_headers`, and Oneiric's own **LLM** adapter already does exactly
  this for Bifrost (`adapters/llm/config.py:61`,
  `adapters/llm/provider.py:113-140`).
- **Neither adapter can be instantiated through the registry.**
  `oneiric/core/lifecycle.py:327-334` calls `factory()` with no arguments;
  `PgvectorAdapter.__init__` and `OpenAIEmbeddingAdapter.__init__` both
  require `settings` positionally. Live:
  `use("vector", provider="pgvector")` → `LifecycleError: Swap failed for
  adapter:vector (pgvector)`; `use("embedding", provider="openai")` → the
  same. The settings model is already on `AdapterMetadata` and
  `DomainBridge.get_settings()` already builds it — the wiring never
  reaches the constructor.

The mock's 384 dimensions exactly matched Akosha's stale `INT8[384]` warm
column. **The system was self-consistent while broken** — which is why the
original dimension defect stayed invisible until a real provider came up.

Three separate components each carry their own now-stale idea of the width:
Akosha's `BACKEND_DEFAULT_DIMS` (`mock 384, model2vec 256, llama_cpp 768,
minimax 1024` — and `embo-01` is actually **1536**, so even that entry is
wrong), Mahavishnu's `EmbeddingConfig.provider`/`model`
(`FASTEMBED` / `BAAI/bge-small-en-v1.5`, both ignored by the chain), and
the substrate's five `embedding__*` knobs, which have **one** production
reader in the whole fleet.

### RC-2 — The producer never emits the vocabulary the consumer filters on

Akosha's OTLP receiver already promotes `task_class`, `selector`, `outcome`
and `duration_ms` into `spans_substrate`'s typed columns
(`akosha/observability/otlp_receiver.py:1934-1937`), and the feed filters on
`task_class = 'mcp_tool_call'` (`akosha/mcp/server.py:2142`). The vocabulary
was defined and the columns exist. **Two independent producers fail to speak
it, and both must be fixed:**

**Gate 1 — the shared middleware never sets the attributes.**
`mcp_common/server/telemetry.py:111-134` sets `rpc.system`, `rpc.method`,
`service.*`, `mcp.tool.name`, `mcp.component.name`, `mcp.message.type`,
`mcp.result.*`. It sets **`task_class`, `selector` and `outcome` never** —
`grep -rn "task_class" mcp_common/` returns nothing. Every MCP server in
the fleet therefore emits spans that the feed cannot match. Sampling 200
live spans across all five services: `task_class` and `selector` are `NULL`
for every one.

**Gate 2 — Mahavishnu's enricher is switched off.**
`mahavishnu/mcp/tool_call_enricher.py:96-100` writes all four attributes
correctly. But its only production caller,
`ToolCallEnrichmentMiddleware.on_message`
(`mahavishnu/mcp/tool_call_middleware.py:132`), is registered behind an
early return:

```python
observability = getattr(self.app.config, "observability", None)
if observability is None or not getattr(observability, "tool_enrichment_enabled", False):
    return                                    # mahavishnu/mcp/server_core.py:258-262
```

The live effective value is **`tool_enrichment_enabled = False`**. The
middleware is never registered, so the enricher never runs — and
`query_local_traces` on the live server *requires* `task_class` as a
mandatory argument, the field Mahavishnu never produces.

**A third, subtler blocker sits behind gate 2.**
`mahavishnu/core/observability.py:296-299` records that the global tracer
provider is installed by `mcp_common.server.launcher` *before* Mahavishnu
builds, so `trace.set_tracer_provider` is a **no-op** on the launchd path.
`trace.get_current_span()` would therefore land in mcp-common's provider,
not Mahavishnu's — so even with gate 2 open, the enricher could annotate
the wrong span. **This is an argument for fixing gate 1 in mcp-common
instead**: the middleware already holds its own span and can set attributes
on it directly, with no dependency on the global-provider race.

### RC-3 — The corpus path is severed in three places

| Path | State |
|---|---|
| Redis `bodai:events` → `conversations` | The subscriber decodes only `envelope=<JSON>` and `{topic, payload_json, headers_json}`; the live producer writes `{channel, headers, payload}`. It filters to `topic == "websocket_tool_invocation"` — **which appears zero times in 13,506 stream entries**. `_index_envelope` additionally requires `payload["version"] == "1.0.0"`, which the hook payloads do not have. The consumer group holds **405,790 consumers** and 660 pending entries, producing 3,021 `xreadgroup` timeouts. |
| Session-Buddy → Akosha HTTP push | The base URL is `config.cloud_endpoint` — the **Cloudflare R2 S3 endpoint** — with `http://localhost:8682/mcp` only as the fallback; the fallback then appends `/mcp/v1` → `http://localhost:8682/mcp/mcp/v1` → **404**. It calls `batch_store_memories`; Akosha exposes `akosha_batch_store_memories` (and nothing else in that family — `create_entity`/`create_relation` have no counterpart at all). It sends 768-dim vectors and stamps `system_id: "unknown-system"`. |
| Session-Buddy → S3/R2 → Akosha pull | `IngestionWorker` exists but **is never instantiated** (`akosha/main.py:118`). |

**The corpus is nonetheless already flowing.** A read-only channel histogram
over the first 2,000 entries of `bodai:events`:

| channel | count |
|---|---|
| `bodai.hooks.user-prompt-submit` | 1218 |
| `bodai.hooks.post-tool-use` | 483 |
| `bodai.hooks.session-start` | 274 |
| `bodai.hooks.session-end` | 20 |
| `mcp.tool.call` | 4 |
| `websocket_tool_invocation` | **0** |

These are pushed by **Mahavishnu's** hook bridge
(`mahavishnu/mahavishnu/bodai_hook_bridge.py:379`), and the payload carries
**`transcript_path` and `session_id`** — the exact fields the never-built
November transcript ingester was designed to consume
(`session-buddy/docs/specs/2026-11-05-conversation-transcript-ingestion-design.md`,
`role: canonical`; `grep -rn "ingest_turns"` → **zero hits** repo-wide).

**So the transport exists and the parser does not.** That makes the corpus
repair a decode-and-filter job, not a new-pipeline job.

---

## 3. The work, by repository

Ordered by dependency, not by repo. Each item is *what must change*; the
per-repo plans hold the task lists.

### 3.1 mcp-common — the highest leverage change in the fleet

Eight lines, and every MCP server in the fleet starts emitting enriched
spans.

- [ ] **`mcp_common/server/telemetry.py:125-126`** — in the `tools/call`
      branch, add `task_class = "mcp_tool_call"` and
      `selector = component_name`. Both values are already in hand: the
      method is `context.method`, the tool name is `component_name`.
- [ ] **`_annotate_result` (`:136-152`)** — set `outcome` from the result:
      `"error"` when `mcp.result.error` is present, else `"success"`.
- [ ] **Set the attributes on the middleware's own span**, not via
      `trace.get_current_span()`. The launcher installs the global tracer
      provider before any component builds, so `trace.set_tracer_provider`
      is a no-op on the launchd path
      (`mahavishnu/core/observability.py:296-299`) — a `get_current_span()`
      lookup can land in the wrong provider. The middleware already has
      its span.
- [ ] The receiver already promotes all three attributes into typed
      columns, and `spans_substrate` already indexes
      `(selector, task_class, outcome, received_at_unix_nano DESC)`.
- [ ] **mcp-common → release → every server picks it up.** This is the
      single change that makes `mcp_tool_call_feed` populate for
      mahavishnu, akosha, session-buddy and crackerjack at once.
- [ ] **Mahavishnu's `tool_enrichment_enabled` must also be turned on**
      (`mahavishnu/core/config.py:1580`) — it is the second, independent
      gate on the producer. With mcp-common fixed, the enricher is
      redundant for `task_class`, but leaving it off keeps the
      `task.class` attribute (a second spelling the receiver also accepts)
      unavailable.
- [ ] **Mahavishnu's `/health` needs a `data_feeds_ok` field and a
      `source` string per feed.** Both are absent from the payload
      entirely, so "which feeds are live" has no machine-readable answer
      on that component.
- [ ] **Populate `ingester_running` truthfully — it is the whole
      dead-vs-warming discriminator.** mcp-common's feed vocabulary
      already distinguishes `FAILED` + `[feed_never_populated,
      ingester_not_running]` from `WARMING_UP` + `[warming_up_empty_feed]`
      on the strength of `ingester_running`
      (`mcp_common/health/feed.py:202-235`). But **Crackerjack hard-codes
      `True`** (`crackerjack/mcp/health.py:74`) and **Akosha uses
      out-of-contract keys** (`akosha/mcp/server.py:2105-2106`), so
      Akosha's `source_producer_running: false` produces **no**
      `ingester_not_running` code. Live, a dead producer reports as
      merely `warming_up` — which is exactly what Akosha's
      `mcp_tool_call_feed` (0 entities, 16,365 cycles) does today. A feed
      that has cycled 16,365 times and holds nothing is not warming up.
- [ ] **Align the health envelope shape.** Crackerjack's `/health`
      envelope drops the four counters mcp-common's aggregator produces
      (`entities_count`, `last_updated_timestamp`, `cycles_total`,
      `errors_total`) — `crackerjack/mcp/health.py:108-129`. Oneiric keeps
      them; Crackerjack and Akosha must be checked against the same shape.
- [ ] **Three `ReasonCode` members are dead** —
      `warming_up_never_cycled`, `no_producer_ever_cycled`,
      `producer_not_alive` (`mcp_common/health/feed.py:60-76`). Implement
      them or delete them; the vocabulary's value is that it is
      exhaustive.

### 3.2 Oneiric — the foundation

**Two blockers sit in front of everything else here**, and neither is
about embeddings.

- [ ] **BLOCKER 1 — the embedding and pgvector adapters cannot be
      instantiated through the registry.**
      `oneiric/core/lifecycle.py:327-334` calls `factory()` with no
      arguments; `PgvectorAdapter.__init__` (`pgvector.py:85`) and
      `OpenAIEmbeddingAdapter.__init__` (`openai.py:61`) both require
      `settings` positionally. Live: `use("vector", provider="pgvector")`
      → `LifecycleError: Swap failed for adapter:vector (pgvector)`;
      `use("embedding", provider="openai")` → the same. The settings model
      is already declared on `AdapterMetadata`
      (`settings_model=PgvectorSettings`) and `DomainBridge.get_settings()`
      already builds it (`domains/base.py:65-70`) — the wiring just never
      reaches the constructor. **Until this is fixed, no component can get
      the fleet's vector adapter or its embedding adapter through the
      registry.**
- [ ] **BLOCKER 2 — the OpenAI embedding adapter cannot authenticate to
      Bifrost.** `adapters/embedding/openai.py:98-106` passes no
      `default_headers`, so the adapter authenticates with
      `Authorization: Bearer <provider key>` — and Bifrost rejects a
      provider key with `401 virtual_key_required`. The SDK *accepts*
      `default_headers`, and Oneiric's own **LLM** adapter already does
      exactly this for Bifrost (`adapters/llm/config.py:61`,
      `adapters/llm/provider.py:113-140`). Copy that mechanism — do not
      invent a second one.

**Then the chain itself.**

- [ ] **Finish the August hybrid-embeddings design**, with the leg list
      corrected for the operator's decisions:
      - **Remove the Ollama leg.** It is in the approved design
        (`:59`); Ollama has since been retired fleet-wide.
      - **`llama_cpp_base_url` default `http://localhost:8080` → `:8081`**
        (`adapters/observability/embedding_settings.py:48`). Port 8080 is
        too common a default and the fleet moved to 8081.
      - **Add the OpenAI legs, first:** `openai_gateway` (Bifrost,
        `x-bf-vk`) → `openai_direct` (`OPENAI_API_KEY`), reusing
        `adapters/embedding/openai.py` rather than writing a parallel
        HTTP client.
      - **MiniMax `embo-01` is natively 1536, not 1024** — the August
        design's dimension note (`:239`) is stale, and so is Akosha's
        `BACKEND_DEFAULT_DIMS`. It stays as a *tier* (a different model is
        a different space), never as a provider failover.
      - **Model2Vec (256) and the mock (384) leave the semantic chain.**
        The mock becomes a **startup failure** in any tier that holds
        semantic vectors.
- [ ] **Add the legs at the chain's real seam.** The order is decided in
      one place — `EmbeddingService.initialize()`'s `probe_order` tuple
      (`adapters/observability/embeddings.py:109-113`). The OpenAI legs go
      in front of `llama_cpp` there, not inside the probe functions.
- [ ] **Two conventions coexist, deliberately.** The OpenAI legs use a
      base URL that **includes `/v1`** (the SDK appends `/embeddings`);
      the existing `llama_cpp` leg uses a **bare root**. Do not "fix" the
      llama leg.
- [ ] **Send `dimensions` on the OpenAI legs only.**
      `_probe_encode_via` (`:375`) and `_encode_llama_cpp` (`:397`) both
      send a fixed `{"model","input"}`. `_probe_encode_via` also sends
      **no headers at all**, so it cannot be reused as-is against an
      authenticated endpoint — it needs a `headers=` parameter.
      llama.cpp rejects unknown body fields, so the `dimensions` key must
      not be added there.
- [ ] **Make the fallback a hard failure.** `initialize()` never raises;
      it always lands on the 384-wide mock (`:130-136`).
      `OpenAIEmbeddingAdapter.init()` (`openai.py:84-86`) already raises
      `LifecycleError` — and already *calls* `embed_text("initialization
      test")`, so it is a real reachability probe. That is the natural
      gate; wire it into the chain.
- [ ] **Add `FLEET_EMBEDDING_MODEL` / `_DIM` / `_SPACE` constants and a
      construction-time cross-check** that a configured width equals
      `FLEET_EMBEDDING_DIM`.
- [ ] **Widen the four hard-coded 384s in the observability subsystem.**
      They would reject every 1536-wide vector the new leg produces:
      `observability/models.py:31` `Vector(384)`;
      `observability/queries.py:55` `shape != (384,)`;
      `observability/migrations.py:22` `embedding VECTOR(384)`;
      `observability/settings.py:36` `embedding_dimension` (default 384,
      `le=1024`).
- [ ] **Make `SubstrateSettings` the source of truth for the width, and
      add the missing validator.** `embedding__dim` (`:211-219`) and
      `warm__embedding_dim` (`:106-115`) both default **384**. Their
      bounds (`ge=64, le=4096`) **already admit 1536** — the problem is
      the default and the absence of a consumer, not the bound. Add a
      `model_validator` asserting `embedding__dim == warm__embedding_dim`;
      the docstring at `:216-218` already promises it and nothing
      enforces it. (The three `le=1024` bounds at `:132`, `:141`, `:230`
      are **HNSW `ef_construction`, HNSW `ef_search` and `batch_size`** —
      not dimensions. Leave them alone.)
- [ ] **Wire or delete the substrate's `embedding__*` knobs.** They are
      declared, they resolve, and **nothing reads them** — a fleet-wide
      grep returns only the definitions and one test file. This plan's
      sibling `mahavishnu/docs/plans/2026-11-05-config-that-nobody-reads.md`
      already states the requirement (**REQ-DEAD-001/002/003**); the
      embedding knobs are the largest instance of it in the fleet.
- [ ] **Reconcile `embedding__backend`'s vocabulary.** Its `Literal` is
      `["openai","fastembed","llama_server"]` — which matches neither the
      chain's actual leg names (`llama_cpp`, `minimax`, `model2vec`,
      `mock`) nor has a leg for `"fastembed"`. It cannot select anything
      until the vocabulary agrees.
- [ ] **`EmbeddingSettings` is a plain `pydantic.BaseModel`, not
      `BaseSettings`** — it reads **nothing** from the environment today.
      It needs a `from_env()` factory (or to become a `BaseSettings`).
- [ ] `PgvectorAdapter`: add `halfvec` and HNSW; read the substrate's
      `warm__hnsw_*` parameters (today it creates **ivfflat** with
      `lists=100` and `PgvectorSettings` has no HNSW knobs at all, while
      `warm__hnsw_m` / `_ef_construction` / `_ef_search` are declared and
      read by nothing — the substrate advertises an ANN configuration it
      cannot deliver); derive the index name from the index method (today
      the fork's `{t}_embedding_hnsw_idx` and Oneiric's `{t}_embedding_idx`
      never collide, so switching a table silently leaves **two** ANN
      indexes on one column); detect a build-parameter mismatch, because
      `CREATE INDEX IF NOT EXISTS` matches on name only.
- [ ] **Pin the vector provider.** Unpinned `use("vector")` resolves to
      **agentdb** (priority 600), not pgvector (450) — and
      `settings/oneiric.yaml` pins only `queue: "redis-streams"`. The
      fleet intends pgvector for the warm tier; say so in config.
- [ ] **`DuckdbHotStore` is not an adapter.** It is a plain class with no
      `AdapterMetadata`, is not exported from `vector/__init__.py`, and is
      unreachable through `use("vector", provider="duckdb_hot_store")`.
      Register it or document that it is deliberately out of the registry.
- [ ] **Add an embeddings route to the Bifrost gateway.** The gateway's
      `routes` currently contains only LLM routes
      (`ONEIRIC_BIFROST_ROUTES=claude_route,qwen_route`) — **there is no
      embeddings route**, and `text-embedding-3-small` appears nowhere in
      Mahavishnu's Bifrost wiring. The `openai` *provider* is configured
      and its key allowlist already contains `text-embedding-3-small`, so
      the route is the missing piece, not the provider.
- [ ] **The gateway's `cache_mode` is `semantic`** — its semantic-cache
      plugin is configured for `text-embedding-3-small` at
      `dimension: 1536`, the native width this plan selects. The gateway's
      internals already agree with the standard; the fleet's components do
      not. Note the known upstream issue where that plugin cannot resolve
      a local/custom embedding provider inside its `PreLLMHook` even when
      the same provider/model succeeds through `/v1/embeddings`.
- [ ] **Watch the gateway's 8192-token input limit.** The semantic-cache
      plugin does not truncate: 514 of 869 consulted requests failed on
      that limit. And the model must be in the provider key's `models: [...]`
      allowlist, or every attempt fails locally with `no_key_supports_model`.
      The direct `/v1/embeddings` round trip is verified live at 1536; the
      *plugin* path is the one with the limit.
- [ ] **Release, then the operator bumps each consumer's pin.**

### 3.3 Mahavishnu

**Live state:** the embedding backend resolves to **`mock` at 384 dims**
(`backend_name=mock`, `dimension=384`, `is_available()=False`,
`get_available_providers() == []`). The mock is not a fallback that
sometimes engages — it is what the running server uses.

- [ ] **Adopt the shared embedding client** and delete the local
      `EmbeddingService` subclass in favour of Oneiric's — the August
      design's Phase 4 ("Simplify mahavishnu"), never done. Mahavishnu
      currently subclasses Oneiric's service but builds
      `_OneiricEmbeddingSettings()` from library defaults, so it never
      sees the fleet's settings either.
- [ ] **Delete the dead config.** `EmbeddingConfig.provider` and
      `.model` (`mahavishnu/core/embeddings_oneiric.py:48-57`) have no
      effect: `EmbeddingService(provider=...)` at `:232` is
      *accepted-and-ignored* (`:149-158` — *"retained for API
      compatibility but ignored"*). `openai_model` (`:64`),
      `openai_api_key` (`:60`) and `model` (`:54`) are written and read by
      nothing. The `backend == "openai"` branch at `embeddings.py:218-221`
      is unreachable. This is `REQ-DEAD-001` again, in the same file.
- [ ] **Remove the FastEmbed traces the dead-config work does not
      reach.** FastEmbed survives in two places that are not the dead
      config:
      - `mahavishnu/ingesters/otel_ingester.py` carries its **own**
        embedder, separate from the shared service: `EmbeddingBackend.FASTEMBED`
        (`:61`), `FastEmbedWrapper` (`:126`), a guarded
        `import fastembed` (`:23-39`), and `_map_to_fastembed_model`.
        The guard is *always false* — `fastembed` is not a dependency —
        so the leg is unreachable, not merely unused.
      - `mahavishnu/ingestion_cli.py` carries four CLI help strings
        advertising `"fastembed|openai"` as a provider choice.
      - `settings/embeddings.yaml:35` sets `provider: fastembed` in a
        file nothing reads, and `settings/mahavishnu.yaml:414` comments
        `# auto, fastembed, openai` on a key that is accepted and
        ignored. A reader who finds either will believe FastEmbed is a
        live choice.
      `EmbeddingProvider.FASTEMBED` goes with `EmbeddingConfig.provider`
      in the same edit as the subclass removal; the OTel leg, the CLI
      strings and the two settings go with it.
- [ ] **The committed `embeddings:` YAML block is unreachable.**
      `settings/mahavishnu.yaml:413` nests it under `embeddings:`, but
      `EmbeddingConfig` has no such sub-model and pydantic's
      `extra="ignore"` drops the nested dict — it only reads **top-level**
      `provider`/`model`/`openai_model` keys, which the file does not have.
      The file that *does* carry a correct block, `settings/embeddings.yaml`,
      is **never read** (only schema-validated,
      `mahavishnu/core/unified_config.py:24`). Also fix `load()`
      replacing rather than merging (`:173`) and its CWD-relative paths
      (`:168-171`).
- [ ] **Remove the mock tier from `ResilientEmbeddingClient`.**
      `mahavishnu/core/resilient_embeddings.py:26-27` documents Tier 4 as
      *"Mock Embedding (last resort) — Non-semantic but functional"* and
      implements it at `:236-246`. It is live, via
      `mahavishnu/pools/memory_aggregator.py:66`. This is the clearest
      single violation of the fleet rule.
- [ ] **Fix the ecosystem dimension constant.**
      `mahavishnu/core/resilient_embeddings.py:53`
      `STANDARD_EMBEDDING_DIMENSION = 384` → 1536, and
      `_validate_dimension` (`:206-222`) must *reject* a mismatch rather
      than count it.
- [ ] **Delete the committed `bifrost:` block or make it live.**
      `settings/mahavishnu.yaml:110-112` (`route_qwen_code`,
      `ssl_show_warn`) is inert — `bifrost` is **not** a
      `MahavishnuSettings` field, and oneiric's `BifrostLLMSettings`
      (`oneiric/adapters/llm/bifrost.py:218-275`) is a `BaseSettings` with
      an env prefix that reads **env vars only**, never YAML. Same for
      `settings/local.yaml:86`.
- [ ] **Make the pgvector fork a true subclass of Oneiric's.** It is a
      standalone 715-line class with zero `oneiric` imports
      (`mahavishnu/adapters/pgvector_adapter.py:143`), despite its own
      docstring at `:3`. Oneiric's adapter has **no HNSW**, no GIN index
      and no `created_at`/`updated_at`; the fork has all three and none of
      Oneiric's safety controls (namespace ACL, JSONB decode, injectable
      pool factory). **Do not ship that asymmetry.** Either port HNSW +
      GIN + timestamps *upstream* and delete the fork, or add the three
      safety features to the fork. **Deleting the fork on the stated
      rationale — "Oneiric's class supports HNSW per the verified source"
      (`docs/specs/2026-10-14-decision-adapter-category-design.md:596-598`)
      — would silently drop HNSW indexing.**
- [ ] **Fix `ef_search`.** `SET LOCAL hnsw.ef_search = $1` (`:238`) is
      rejected by PostgreSQL — `SET` is a utility statement and takes no
      bind parameters — and it runs on a different pooled connection from
      the query (`:236` vs `:259`). The portable form is
      `SELECT set_config('hnsw.ef_search', $1, true)` on the same
      connection inside an explicit transaction. The configured value has
      **never** reached a query.
- [ ] **Add a real-Postgres integration test for that path.** The
      `AsyncMock` harness structurally cannot catch a SQL syntax error —
      which is why the bug survived.
- [ ] **Fix the JSONB decode.** asyncpg returns JSONB as `str`;
      `register_vector` registers no jsonb codec. `otel_ingester.py:986`
      does `result["metadata"].get(...)` on a `str` and raises
      `AttributeError`, which the MCP tool's broad `except Exception`
      swallows into an empty result list. The GET path at `:1073-1078`
      already works around it.
- [ ] **Make the MCP tool path honour `storage_type`.**
      `mahavishnu/mcp/tools/otel_tools.py:166,381,421` construct
      `OtelIngester(...)` without `storage_type` or `pgvector_dsn`, so the
      server always uses DuckDB regardless of the XDG
      `otel_ingester.storage_type: postgresql`. Only
      `create_otel_ingester()` reads the config, and it has **no
      production caller** — only tests and examples.
- [ ] **Stop reporting a hardcoded backend.**
      `mahavishnu/mcp/tools/otel_tools.py:203` and the default at `:36`
      return the literal `"duckdb_hotstore"`. Read
      `ingester.storage_type` instead.
- [ ] **Fix the live `mahavishnu_hybrid_search` break.**
      `mahavishnu/core/database.py:74-83` defaults `ssl_mode="prefer"` and
      `_get_ssl_config()` (`:238-248`) returns `None` for `"prefer"`, but
      the DSN handling still attempts an SSL upgrade that Homebrew
      Postgres rejects — the tool errors live with
      `[MHV-002] Unexpected database error: PostgreSQL server at
      "localhost:5432" rejected SSL upgrade`.
- [ ] **Re-embed the live pgvector table.** In the `mahavishnu` database,
      `public.vectors_otel_traces` holds **7 rows, all 384-dim**, with the
      fork's exact schema and its HNSW (`m=16, ef_construction=64`) and GIN
      indexes. The rows carry `task.class` values of
      `CODE_GENERATION`/`REASONING`/`SEARCH` — **never** `mcp_tool_call` —
      and are from a manual run, not a live feed. A 1536 move needs a new
      column or table plus a re-embed; the rows cannot be reused.
- [ ] **Promote `transcript_path` and `prompt_id` to the top level of the
      hook payload.** `mahavishnu/bodai_hook_bridge.py:159-187`
      (`_normalize`) — both are already present on every live entry but
      **one level down inside `raw`**, and no consumer reads them there.
      `raw.prompt` (the user's prompt text) and `raw.tool_response` are
      also flowing and unread. This is the cheapest path to an Akosha
      conversation corpus.
- [ ] **Register the `hook_bridge_feed`.** The name at
      `bodai_hook_bridge.py:360` appears nowhere else; `_health_monitor`
      (`:706`) is set only by tests. The bridge's `errors_total` and
      `publish_failures_total` are a permanent no-op.
- [ ] Delete the dead `HNSWIndexConfig` (`core/config.py:989-1032`), the
      third pgvector implementation in `core/vector_search.py`, and the
      0-byte `scripts/setup_otel_storage.sh` (referenced by three docs).

### 3.4 Akosha

Plan M (`akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md`) holds
the detail. The fleet-relevant additions:

- [ ] **Phase 0** — adopt Oneiric's client; delete `BACKEND_DEFAULT_DIMS`;
      rebuild `conversations` at 1536 (it holds 0 rows, so this is close to
      free; `hot.db` is 894 MB and needs `hot.db` **and** `hot.db.wal`
      backed up together).
- [ ] **Widen `akosha_store_memory`'s dimension check.**
      `mcp/tools/session_buddy_tools.py:138-145` compares the incoming
      width against a hardcoded 384 and, on a mismatch, **logs a warning
      and proceeds** — it does not reject. Only a `None` embedding is
      rejected, and its error message ("must be a 384-dimensional vector")
      is itself stale. So this does **not** block Session-Buddy's push;
      it fires a misleading warning on every push at the fleet width.
      Fix it to check the fleet width against the *contract*, not a
      literal. It also discards ten lineage fields (`:26-42`), so the
      pushed rows carry no provenance — the same vocabulary problem the
      aging filter has.
- [ ] **The Redis subscriber.** Per-process consumer name → XAUTOCLAIM the
      660 pending entries → delete the 405,790 stale consumers in pages →
      decode `{channel, headers, payload}` → drop the
      `payload["version"] == "1.0.0"` check → **widen the topic filter to
      the `bodai.hooks.*` channels** → read the PEL, not `>`. Log decode
      failures; a silent drop is how a retired producer survived unnoticed.
- [ ] **The false-negative health flag.** `subscriber_wiring.py:128` reads
      `.running` off the *orchestrator*, which has no such property — it
      exists only on the inner subscriber. So `_event_subscriber_running`
      is always False while the consumer is demonstrably alive.
- [ ] **The analytics instance that is never initialised.**
      `group_registers.py:73` creates a **second** `TimeSeriesAnalytics()`
      that never gets `initialize()`d, while the real one
      (`server.py:931-934`) is only used at shutdown. **47,386 rows sit in
      `~/.akosha/state/metrics.db` and are never loaded**, so four
      advertised analytics tools return "Insufficient data". A one-line
      wiring fix turns four dead tools into working ones.
- [ ] **The metadata conventions.** `AgingService` filters
      `metadata->>'task_class' = 'mcp_tool_call'` — a *span* vocabulary —
      over a table holding both spans and memories. The Session-Buddy
      push path sets no `task_class` and discards ten lineage fields
      (`session_buddy_tools.py:26-42`). Settle the vocabulary **before**
      building the writer, or the writer produces rows no consumer can see.
- [ ] `suppress(Exception)` around the feed count (a raised query reads as
      zero); `local_traces_feed` counts `query_traces` only while claiming
      `spans_substrate` too; `metrics_substrate` has 1,000 rows and **no MCP
      tool reads it**; `fitness_analyzer` has no `declared_pairs`;
      `discover_tools` is mcp-common's, not Akosha's.
- [ ] **Phase 2** — the unified pgvector warm tier.

### 3.5 Session-Buddy

Session-Buddy has the fleet's **best** embedding chain and its **worst**
failure modes. The chain resolves a real provider (Bifrost, HTTP 200,
live vector) and every failure is silent. It is also the component
closest to Les's original design intent — a central store that every
machine pushes conversations to — and the furthest from it in practice:
**156 rows, every one a synthetic marker, `source_type` NULL on all of
them, zero real conversation turns.**

**What works today**

| Thing | State |
|---|---|
| `openai_gateway` leg (Bifrost) | **live**, HTTP 200, real vector |
| `openai_direct` leg | live (eligible) |
| `llama_embed` leg | live (eligible) — but a *different vector space* |
| `llama_server` leg | **skipped** — declared 4096 ≠ 768, and nothing on :8081 |
| Width served | **768**, not 1536 |
| MCP tools registered | **227** (215 `session_buddy_*` + 12 bare) |
| Search surface | functionally live, **semantically empty** |

**The two-constant trap (M1 — blocks everything else).**

`session_buddy/memory/embedding_dim.py:39` holds
`DEFAULT_EMBEDDING_DIM = 768`, and `reflection/embeddings.py:55` binds
`EMBEDDING_DIM = DEFAULT_EMBEDDING_DIM` — an alias, so those two are
already in lockstep. The stray literal is
`reflection/embeddings.py:81`: **`OPENAI_EMBEDDING_DIM = 768`**, written
out by hand. The chain's legs declare their widths from that constant
(`_PROVIDER_LEGS`, `:379-384`), and `_eligible_legs` (`:392-405`) admits
a leg only when `leg.width == EMBEDDING_DIM`.

Live-probed consequence: raising only `DEFAULT_EMBEDDING_DIM` to 1536
moves `EMBEDDING_DIM` to 1536 while every leg still *declares* 768
(OpenAI), 768 (`llama_embed`) or 4096 (`llama_server`). **No leg is
eligible; the chain returns `None` for every request**
(`chain result (width=1536): None`) and every write degrades to a NULL
embedding. The November plan's fleet-width check (B6, `:744-748`) reads
only `memory/embedding_dim.py:39` — which is exactly the constant that
*looks* right and is not the one that breaks. **The two literals must
move in one change, and the check must read both.**

**The three silent gates.** Session-Buddy has three independent places
where an embedding can be lost, none of which raise:

1. **Eligibility** (`_eligible_legs`, `:392-405`) — filters by declared
   width, no network.
2. **Validation** (`_try_http_embedding_providers`, `:428-441`) —
   length-checks the response and rejects on mismatch.
3. **Coercion** (`coerce_embedding`, `memory/embedding_dim.py:44-77`) —
   drops the vector **at the write boundary**: the row is still stored,
   the instance still reports healthy.

There is **no startup gate**. `initialize_embedding_system()`
(`embeddings.py:581-590`) is a no-op stub, and every startup path in
`server_optimized.py` explicitly must *not* block startup (`:212`, `:218`,
`:229`, `:248`, `:296`, `:312`). The embedding gate must be the
deliberate exception to that pattern.

There is **no embedding health feed**. `get_embedding_system_info()`
(`embeddings.py:538-575`) computes exactly the right diagnostic —
active provider, eligible and skipped legs, provider URLs — and is
exported to **nothing**. `/health` carries two feeds (`skills_signer`,
`bodai_events`); the latter is stale-but-green (its publisher has been
idle since boot, and `health()` returns true on `entities_count > 0`).

- [ ] **Move 768 → 1536 in both constants, atomically**
      (`memory/embedding_dim.py:39` **and** `reflection/embeddings.py:81`).
      Leaving `llama_server` declared at its true 4096 and `llama_embed`
      at 768 is *correct* — they then become ineligible, which is the
      intended outcome, not a bug to fix.
- [ ] **Take `dimensions` out of the request body.** Both OpenAI legs
      send `{"model", "input", "dimensions": OPENAI_EMBEDDING_DIM}`
      (`reflection/embeddings.py:323` and `:339`). Today that asks
      `text-embedding-3-small` for a **768-wide truncation of a
      native-1536 model**. At 1536 the field is a no-op, and per the
      settled decision it is not sent (§1) — but it is also the field
      that makes a *different* model at the same width reachable, so it
      belongs to the contract rather than to the constant: the client
      sends it only when the target width differs from the model's
      native width.
- [ ] **Add the hard startup gate.** A `verify_provider_reachable()` that
      probes the eligible legs and returns the serving leg + width; the
      lifespan calls it and **aborts startup** on failure. The failure
      message must name both ("no real embedding provider reachable;
      required width 1536"). Do not follow the surrounding
      swallow-everything pattern.
- [ ] **Add an embedding health feed** and expose `get_embedding_system_info()`
      via an MCP tool and in `/health` (mirroring the `skills_signer`
      pattern at `server_optimized.py:460-475`).
- [ ] **Stop storing embedding-less rows.** `coerce_embedding` and the
      write path (`adapters/reflection_adapter_oneiric.py:1284-1292`)
      must raise on a missing or wrong-width vector, not log a warning
      and store a degraded row.
- [ ] **Rebuild the database at 1536.**
      `scripts/migrate_embedding_dim.py --to-dim 1536 --replace --re-embed`.
      **Without `--re-embed` the database comes back 100% NULL-embedded**
      (the script drops every vector, `:235-236`). Stop the server first
      — DuckDB is single-writer. 313 vectors in a 53 MB database, so the
      rebuild is cheap.
- [ ] **Migrate the BLOB-backed embeddings separately.** The script only
      sees `FLOAT[N]` (`:96-120`). `skill_invocation.embedding` and
      `centroid_embedding` are BLOBs; `EMBEDDING_BYTES` must go to 6144
      at 1536 (`storage/skills_embeddings.py:46-47`) and every existing
      blob must be re-embedded and re-packed, or `unpack_embedding`
      (`:98-99`) raises.
- [ ] **Remove the `llama_embed` leg from the fleet chain.** It is
      width-eligible at 768 alongside the two OpenAI legs, but it is a
      *different model in a different vector space* — the same width, a
      different meaning, silently mixable.
- [ ] **Adopt the shared client, or pin SB's chain to the same constants
      and the same startup-failure rule.** Two embedding clients is the
      problem; SB's chain is currently the best of them, which is why it
      is worth keeping — but it must obey the same contract.
- [ ] **Fix the push client — five defects, not one.** The current push
      does not reach Akosha at all:
      1. `storage/akosha_sync.py:191` uses `config.cloud_endpoint` — the
         **Cloudflare R2 S3 endpoint** — as the Akosha base URL.
      2. `:1067` appends `/mcp/v1`; Akosha mounts `/mcp` only (404).
      3. **The tool names do not exist.** The live Akosha server
         registers 39 tools, and only two are in the store family:
         `akosha_store_memory` and `akosha_batch_store_memories`.
         Session-Buddy calls `store_reflection` (`:540`),
         `create_entity` (`:700`), `create_relation` (`:732`) and
         `batch_store_memories` (`:981`) — none of them unprefixed, and
         **`create_entity` and `create_relation` have no counterpart on
         the Akosha side at all**, prefixed or not. The knowledge-graph
         write path Session-Buddy intends has no receiver; it has to be
         designed, not renamed.
      4. `storage/akosha_config.py:222-224` reads `HOSTNAME`, which macOS
         does not export into a launchd process — the live `system_id` is
         **`"unknown-system"`**, not the hostname. `socket.gethostname()`
         is the fix (as `bodai_events_publisher.py:191` already does).
      5. Akosha's dimension check compares against a hardcoded 384
         (`akosha/mcp/tools/session_buddy_tools.py:138-145`). It only
         **warns** — it does not reject — so it does not block the push,
         but it fires a misleading warning on every row. Fix it
         alongside Akosha's own width move; Session-Buddy should not
         paper over it.
      A **second** URL defect lives in `sync.py:521-527`
      (`POST {akosha_url}/store_memory` → 404); it must be an MCP
      `tools/call` to `/mcp` with the tool name `akosha_store_memory`.
- [ ] **Interim path: use the MCP tool directly**
      (`akosha_batch_store_memories`) — it is already reachable and its
      payload matches the existing serializer. Land the HTTP-push repair
      as the automated path once Akosha's width moves to 1536.
      **Do not use Redis** — the Redis path publishes only `task.*`
      envelopes and a heartbeat, never conversation content.
- [ ] **Build the transcript ingester, or decode the Redis hook events.**
      The receiving schema is ready (`source_type` CHECK, the
      `claude_turn` category, `turn_parent_id`, and an adapter writer that
      takes `source_type`); the *producer* is missing. **The corpus is
      already on the stream** — the `bodai.hooks.*` topics carry
      `transcript_path` and `session_id` — so decoding them needs no new
      transport and restores the original intent. Until one of these
      ships, `conversations_v2` stays 156 synthetic markers and every
      semantic search over it is meaningless.
- [ ] **Route the MCP `store_conversation` path through the
      provenance-capable writer** — the current path writes no
      `source_type`, so the manual tool would still write NULL provenance
      even after the ingester lands.
- [ ] **Update `2026-11-06-fleet-embedding-width-768.md`** to 1536 and
      startup failure, and **retract its line 36** ("the `mock` fallback
      widens 384 → 768") — under startup failure the mock is not a write
      path. Its status is `draft`, 8-agent reviewed; it should be
      *updated*, not replaced. The companion spec
      (`2026-11-05-conversation-transcript-ingestion-design.md`) is also
      `draft` and must be marked superseded for its fleet section.
- [ ] **Re-pin the stale fixtures and claims**: the test constants and
      `FLOAT[384]` DDL in the test suite, the `embeddings.py` docstring
      (claims `FLOAT[1536]`, live is `FLOAT[768]`), and `CLAUDE.md`
      (claims `FLOAT[384]` + a local ONNX MiniLM that was removed).

### 3.6 Crackerjack

**There is one semantic path, not two.** `crackerjack/fixers/semantic.py`
was **deleted on 2026-11-14** (`5bce2eaa`); `git ls-tree HEAD crackerjack/`
shows no `fixers` or `agents` directory at all. The November plan's B5
Steps 5/7/9/11 and its `tests/fixers/test_semantic.py` references are
stale against HEAD. The AI-fix subsystem is gone — what remains is the
**search** path, at 384, running on **hash** vectors.

The current state is worse than "wrong width":

| Thing | State |
|---|---|
| Embedding implementation | SHA-256 hash pseudo-vectors, 384 wide (`services/ai/embeddings.py:99-111`); the ONNX path is a stub (`self._session = None`) and `is_model_available()` is always `False` |
| Semantic index | **EMPTY** — 0 files, 0 chunks on disk; `search_semantic` returns `status: degraded` |
| `/health` | says **healthy** while the index is empty and the vectors are hashes |
| Vector store | SQLite **BLOB** (JSON) — **no width column, no width check** |
| `embedding_dimension` | default **384**; bound `le=1024` — live proof: `SemanticConfig(embedding_dimension=1536)` raises `ValidationError` |
| `embedding_backend` | `Literal["auto","onnxruntime","fallback"]` — **never read anywhere**; a `mode` key in `config_json` is silently ignored |
| Cross-service embedding reads | **none** — `akosha_search_code_patterns` is regex/PyCharm-index; Session-Buddy reads metrics and skills only |

- [ ] **Replace the hash embedder with real embeddings** at the fleet
      width. A hash is not a semantic vector; every similarity against one
      is noise — and the index that would hold them is empty anyway.
- [ ] **Raise the `embedding_dimension` bound**
      (`crackerjack/models/semantic_models.py:171`, `le=1024` → `le=4096`)
      and its default (`:169`, 384 → the fleet constant).
- [ ] **Widen every 384 literal to the fleet constant**:
      `semantic_models.py:169`; `services/ai/embeddings.py:108, 111` (the
      hash pad/slice — both, not a magic number); `:290`
      (`get_model_info`); `services/vector_store.py:488` (the
      `index_size_mb` math); `mcp/tools/semantic_tools.py:566`
      (`_parse_semantic_config` default); `cli/semantic_handlers.py:39,
      100, 189, 257` and the hard-coded display row `"384"` at `:211`.
- [ ] **Create the leaf dimension constant**
      (`crackerjack/services/ai/dimensions.py` — does not exist). Both
      `semantic_models.py` and `services/ai/embeddings.py` must import it,
      and it must import nothing from `crackerjack.*` — otherwise the
      `semantic_models → embeddings → semantic_models` cycle makes
      `import crackerjack.models.semantic_models` fail.
- [ ] **Add an OpenAI leg to the embedder**: Bifrost first (base URL from
      `get_router().resolve(LLMProvider.OPENAI)` — Crackerjack already
      uses this resolver at `adapters/ai/unified.py:68`; credential
      `BIFROST_VIRTUAL_KEY`), then direct OpenAI (`OPENAI_API_KEY`), then
      local llama, then a local lexical embedder. Send
      `{"model","input"}` on the OpenAI legs — 1536 is
      `text-embedding-3-small`'s native width, so `dimensions` is omitted
      (§1) — and `{"model","input"}` on llama (llama.cpp rejects unknown
      body fields). The client is **sync** (`httpx2.Client`, per the
      repo's `import httpx2 as httpx` convention).
- [ ] **Make `embedding_backend` mean something** — it should gate which
      legs are eligible: `"auto"` = the chain, `"openai"` = OpenAI legs
      only, `"local"` = local legs only. Today it selects nothing.
- [ ] **Record the index width and rebuild on mismatch.** The `embeddings`
      table has no width column, so a stale 384-wide BLOB is read as if
      it were 1536. Add an `embedding_dim` column (or a `meta` table);
      compare on open and rebuild. The current failure mode is a loud
      numpy shape `ValueError` — the rebuild makes it deliberate.
- [ ] **Fix the `file_types` filter** (`services/vector_store.py:396-416`)
      — the stored value is `Path.suffix` (dotted, `.py`) but callers
      pass `"py"`, and the SQL `WHERE file_type IN (?)` is exact-match, so
      the filter silently returns zero rows. Cheap, and strictly an
      improvement rather than a standard-alignment blocker.
- [ ] **Add a semantic-index health feed.** `/health` reports `healthy`
      while the index is empty and the vectors are hashes, so the fleet
      cannot see the semantic subsystem fail. A `semantic_index` feed
      (`entities_count` = indexed chunks, `ingester_running` = whether a
      producer exists) closes this.
- [ ] **Do not plan against the deleted fixer path.** The on-disk plan's
      B5 task list is stale; there is nothing to align.

### 3.7 Operational — the operator's actions

- [ ] **Oneiric release → pin bumps → publishes.** The floor moves in this
      order: oneiric → mcp-common → each consumer. The version bump is the
      operator's, per the standing rule.
- [ ] **Restart every server after the pins move.** The running Mahavishnu
      reports version **0.39.0** while its repo is at **0.40.0** — it has
      been up ~85 hours and predates the current tree. The same is likely
      elsewhere; compare process start time against commit time before
      trusting any live observation.
- [ ] **The gateway's virtual key is present and the gateway is live**
      (`x-bf-vk` auth, `BIFROST_VIRTUAL_KEY` in the environment and
      mirrored as `BODAI_BIFROST_VK`). No credential needs to be created
      or moved — but no credential should ever be written into a committed
      file or a plan.
- [ ] **Do not run `/tmp/akosha-pgvector-activation.py`.** It is obsolete:
      it sets `shard_count: 16` for a per-shard design the unified tier
      deletes, and sets `AKOSHA__STORAGE__WARM__PG_URL` — which
      `akosha/mcp/server.py:1833` ignores, because the lifespan hard-codes
      `create_warm_store(backend="duckdb-ssd")`.
- [ ] **Do not run `/tmp/pgbouncer-add-crackerjack.py`.** The `crackerjack`
      route is already in `pgbouncer.ini`.
- [ ] **pgbouncer and Postgres are already in place**: `127.0.0.1:6432`,
      `auth_type=trust`, `pool_mode=transaction`,
      `default_pool_size=20`, `max_client_conn=1000`; PostgreSQL 18.6 with
      routes for `akosha_pgvector`, `mahavishnu`, `otel`, `postgres` and
      `crackerjack`. **No infrastructure work is needed for this plan.**
- [ ] Pushes are the operator's. Currently unpushed: oneiric 7,
      session-buddy 11, mahavishnu 5, mcp-common 2, crackerjack 0 — all
      docs, coverage and release-tooling work, none of it this plan.
      Akosha is on `fix/pgvector-warm-backend`, 7 commits ahead of
      `origin/main`: 4 warm-tier commits plus 3 unrelated (a coverage
      ratchet, a coverage-doc fix, and a plan-index wrapper).
- [ ] **Do not run `scripts/regenerate_plan_index.py` in this repo.** It
      rewrites `PLAN_INDEX.md` into a broken shape — it prepends an
      unrelated document's frontmatter to the index and drops the whole
      table. The fix already exists as `5464a2c` ("make the plan-index
      script a wrapper over the one renderer") on Akosha's
      `fix/pgvector-warm-backend` branch; it has not reached `main` here.
      Use `crackerjack.tools.plan_index_sync` until it does.

---

## 4. Sequencing

```
  mcp-common: emit task_class/selector/outcome   ─┐
                                                    ├─► mcp_tool_call_feed populates
  Akosha: fix the subscriber + decode the shape  ─┘

  Oneiric: registry wiring + Bifrost header + the   ──► release
           OpenAI legs + 1536                        │
                                                    │
  Akosha: adopt it, rebuild conversations, widen  ┤
           store_memory's accepted width  ─────────┤
  Session-Buddy: both constants → 1536, rebuild,  ┤
           startup gate, health feed ──────────────┤
  Mahavishnu: subclass the adapter, fix ef_search ┤
  Crackerjack: real embeddings at 1536 ───────────┘
                                                    │
                                                    ▼
                              operator bumps pins, publishes
                                                    │
                                                    ▼
                        unified pgvector warm tier → enable aging
                                                    │
                                                    ▼
              Session-Buddy pushes conversations → Akosha (now 1536)
```

**The Oneiric release is the critical path, and two things must land in
it:** the registry wiring (without it the adapters are unreachable) and
the Bifrost header (without it the OpenAI legs authenticate wrongly). The
leg order and the width are third and fourth — they are what everyone
expects to be the hard part, and they are not.

**Three independent tracks.** The producer track (mcp-common + Akosha's
subscriber) needs nothing from the embedding work and can start today. The
embedding track needs the Oneiric release before the consumers can move.
The warm tier needs both.

**One ordering constraint inside the embedding track.** Akosha's
`conversations` table must be at the fleet width **before** Session-Buddy
pushes to it. Akosha's own dimension check is only a warning, so a push
at the wrong width is *accepted* — but a 1536-wide vector cannot bind
into a 384-wide DuckDB `FLOAT[N]` column at all. Widening the producer
without widening the receiver produces rows that cannot be written, or
that must be re-embedded later.

---

## 5. Verification gate

The fleet is up to speed when all of these hold. **None of them is an HTTP
status code.**

- [ ] `/health` on every server: `_aggregate.status == "ok"`,
      `data_feeds_ok == true`.
- [ ] Every feed's `source` names a producer that is **running**, and the
      feed's `entities_count > 0`.
- [ ] Every component reports the same embedding model, width and space
      id; `embeddings.mode == "real"` on Akosha.
- [ ] A live Bifrost `/v1/embeddings` round trip returns 1536-wide
      unit-norm vectors, and the direct-OpenAI failover returns vectors in
      the **same** space.
- [ ] A wrong-width vector is rejected; so is a right-width vector from
      the wrong model.
- [ ] **`use("vector", provider="pgvector")` and
      `use("embedding", provider="openai")` both resolve and instantiate.**
      They currently raise `LifecycleError: Swap failed`. If they do not
      work, no component can reach the fleet's adapters.
- [ ] **`ingester_running` is truthful on every feed.** A feed that has
      cycled thousands of times and holds nothing must read `FAILED` with
      `ingester_not_running`, not `WARMING_UP` with
      `warming_up_empty_feed`.
- [ ] `conversations` has rows, written by a named producer.
- [ ] `akosha_search_all_systems` returns real rows and the response does
      **not** carry `mode: "fallback"`.
- [ ] `akosha_get_system_metrics` returns a non-zero `total_metrics`.
- [ ] `knowledge_graph_feed` reports entities **and** edges.
- [ ] `akosha_warm` has an HNSW index; `EXPLAIN` shows an index scan.
- [ ] `mcp_tool_call_feed.entities_count > 0` **and** the row count of the
      table aging reads is greater than zero. Both, not either.
- [ ] The mock is unreachable in any semantic tier — a startup failure.
- [ ] **Session-Buddy refuses to start** when no real provider is
      reachable, and the failure names the required width. Its `/health`
      reports the serving leg and the width, and
      `get_embedding_system_info()` is reachable from a tool.
- [ ] **Both** Session-Buddy width constants read 1536. A check that
      reads only `memory/embedding_dim.py` is not a check.
- [ ] No embedding-less rows: the count of rows with a NULL embedding is
      zero, and no write path logs a warning and stores a degraded row.
- [ ] `conversations_v2` rows carry a non-NULL `source_type`, written by a
      named producer — and `session_buddy_search_by_source` returns rows
      under at least one real category rather than only `[all sources]`.

---

## 6. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The Oneiric release slips | High | The producer track (mcp-common, Akosha's subscriber) does not depend on it. Two tracks, one gate. |
| The Oneiric release ships the legs but not the registry wiring | High | The adapters would still be unreachable — `use("vector", provider="pgvector")` raises `LifecycleError` today. Assert both in the release gate: the legs resolve **and** the adapter instantiates. |
| The OpenAI adapter authenticates with a provider key | High | Bifrost answers `401 virtual_key_required`. Copy the LLM adapter's `default_headers` mechanism (`adapters/llm/config.py:61`) rather than writing a second one. Assert a live Bifrost round trip through the *adapter*, not a raw `curl`. |
| The Bifrost semantic-cache plugin's 8192-token limit bites | Medium | The plugin does not truncate; 514 of 869 consulted requests failed on it. Long documents must be chunked before embedding, and the plugin's own path (not just `/v1/embeddings`) must be exercised. |
| `embedding_backend` keeps selecting nothing | Medium | Crackerjack's `embedding_backend` and Oneiric's `embedding__backend` are both declared and never read, and their vocabularies do not even match the chains they are meant to select. Wire them or delete them — do not leave a selector that reads as live. |
| A consumer's pin moves before the release | High | The floor moves one repo at a time: oneiric → mcp-common → consumers. The operator publishes in that order. |
| The corpus path is repaired but the vocabulary still mismatches | High | Settle `task_class` before building the writer (Akosha §3.4). |
| The 405,790-consumer cleanup strands pending entries | Medium | XAUTOCLAIM **before** DELCONSUMER. `XGROUP DESTROY` loses the pending entries and the group position outright. |
| A consumer rebuild loses data | Medium | Records may be lost by decision — but back up `hot.db` **and** `hot.db.wal` together, and stop the server first (DuckDB is single-writer). |
| The mock reappears in a semantic tier | High | Startup failure plus `/health` exposing the active leg and space id, asserted in the gate. |
| The Redis `bodai:hooks.*` payloads change shape | Medium | The decoder must log failures — a silent drop is how a retired producer survived unnoticed. |
| The `conversations` schema freezes at the wrong width | Medium | `CREATE TABLE IF NOT EXISTS` never alters, and DuckDB cannot widen a fixed-size ARRAY. Rebuild, don't edit. |
| Session-Buddy's **two** width constants diverge | High | `memory/embedding_dim.py:39` and `reflection/embeddings.py:81` are independent. Moving one makes every leg ineligible and the chain returns `None` — silent, and every write degrades to a NULL vector. Move both in one change; assert both. |
| Session-Buddy's BLOB embeddings are missed by the migration | Medium | `migrate_embedding_dim.py` only sees `FLOAT[N]`. `skill_invocation.embedding` and `centroid_embedding` are BLOBs and need their own re-embed and re-pack, or `unpack_embedding` raises. |

---

## 7. Explicitly not being done

- **Moving `spans_substrate` or `metrics_substrate` to Postgres.** They are
  columnar observability data with no embedding column. DuckDB is the right
  tool. What standardises is the **vector** store technology.
- **The cold store** (R2/S3) and the cold tier's record shape.
- **Cross-component shared vector tables.** The warm table is
  Akosha-scoped and default-deny.
- **Legacy record retention and backwards-compatibility shims.** Pre-1.0:
  replace, do not extend.
- **A per-shard pgvector layout.** One table; shard routing leaves the
  warm path entirely.
- **Redis as an L2 cache.** It is advertised in `CLAUDE.md` and
  `docs/ARCHITECTURE.md` and does not exist. Either build it or remove the
  claim — but not in this plan.
