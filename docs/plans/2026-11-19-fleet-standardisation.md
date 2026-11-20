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

______________________________________________________________________

## 1. What "working as intended" means

Five outcomes, each independently checkable:

| # | Outcome | How it is checked |
|---|---|---|
| **O1** | One **index** model (`text-embedding-3-large`) at one width (1024), produced by one client (Oneiric's), under one contract — `(model, dimensions, space_version)` — with a **frozen index space** and a **separately configurable ranker** | Every component reports the same index model, width and space id on `/health`; the ranker's model and space id are reported separately |
| **O2** | No health feed is empty because its producer is dead, mis-wired, or filtered | `/health` `_aggregate.status == "ok"` and `data_feeds_ok == true`; each feed's `source` names a producer that is running |
| **O3** | The conversation corpus reaches the store that analyses it | `conversations` has rows, written by a named producer |
| **O4** | Semantic search, trends, anomalies, correlation, the knowledge graph and fitness analysis all return real data | Each tool returns rows, not "Insufficient data" and not a fallback placeholder |
| **O5** | Aging moves hot→warm→cold on a schedule, and the warm tier is searchable | `akosha_warm` has an HNSW index; `EXPLAIN` shows an index scan; the cold exporter has exported records |

### Settled decisions — do not reopen these

| Decision | Value | Why |
|---|---|---|
| Fleet width | **1024** — a **fixed fleet width, independent of the model** | Operator decision, 2026-11-20. The rule is that a **model must be admissible at the fleet width** (natively, or by Matryoshka truncation), *not* that the width follows the model. 1024 is the only width that satisfies every hard constraint at once. (a) It indexes as plain `vector` with HNSW in pgvector, whose ceiling is **2000 dimensions** — 3072 and 2048 both exceed it and would need a `halfvec` type plus a cast-expression index. (b) It is admitted by **every** candidate model in the field; 1536 is a legacy width that only OpenAI and the retired `embed-v4` still offer, and the whole Voyage family excludes it. (c) The quality difference among 1024 / 1536 / 3072 is far below what our corpus can measure. A fixed width keeps the storage contract stable, so a model change costs one re-embed rather than a re-embed *plus* a schema migration — and the migration is the expensive half, because DuckDB cannot widen a fixed-size ARRAY and `CREATE TABLE IF NOT EXISTS` never alters. See §1.1. |
| Llama.cpp `dimensions` | **not sent** | llama.cpp does not implement the `dimensions` parameter (issue #25210 open). Truncation must be client-side, and the fleet's client is OpenAI-compatible. |
| Local fallback legs | **llama-server, model2vec and the mock leave the semantic chain** | Hardware-limited today, and the mock is a startup failure, not a fallback. A different model is a different vector space, not a failover. The *capability* of an OpenAI-compatible leg stays in the contract, so a local server remains a configuration change rather than a project (§3.2). |
| The `dimensions` parameter itself | **sent whenever the target width is not the model's native width** | `text-embedding-3-large` is natively 3072, so reaching 1024 *requires* `dimensions: 1024` on every request. The rule is not "never send" (that would make 3-large unreachable) and not "always send" (on a native-width model it is a no-op that invites a reader to think truncation is in play). The client decides from a **declared capability on the leg**, never from the model's name — and the capability must include **how the width is requested**, because the field name is per-vendor (`dimensions` for OpenAI, `output_dimension` for Voyage and Cohere, `output_dimensionality` for Gemini) — see §3.2. |
| The model itself | **`text-embedding-3-large`**, a contract field with a re-embed path, not a constant | Operator decision, 2026-11-20. Chosen over `text-embedding-3-small` on retrieval quality (MTEB retrieval nDCG@10 **55.4** against **51.7**) at a price difference that is immaterial at fleet volume (10M tokens/month is $1.30 against $0.20). Provisional: §1.1 names `cohere embed-v4` at 1024 as the candidate the recall benchmark must score against it. |
| Index space vs ranker | **the index space is frozen; the ranker is separately configurable** | The corpus is re-embedded only when the *index* model changes. Ranking quality lives in a separate leg with its own model and space id, so the ranker can be upgraded — or replaced by a cross-encoder — without touching a single stored vector. See §1.2. |
| Records | **may be lost** | Operator decision, 2026-11-19. No legacy support, no backwards-compat shims. Rebuilds are cheap; the data is not worth a shim. |
| Provider failover | **same model, same space** | A failover to a different model is not a failover — it is a different vector space with the same width, and it is silently mixable. |

### 1.1 Why `text-embedding-3-large`, and when that changes

The model is the one decision here with a shelf life, so the reasoning is
recorded here rather than left implicit.

**What the fleet runs today.** Nothing is at 1024. Session-Buddy serves
**768** (`memory/embedding_dim.py:39` `DEFAULT_EMBEDDING_DIM = 768`;
`reflection/embeddings.py:81` `OPENAI_EMBEDDING_DIM = 768`) and asks
`text-embedding-3-small` for `{"dimensions": 768}` — a truncation of that
model's native 1536. Mahavishnu resolves to the 384-wide mock;
Crackerjack runs 384-wide SHA-256 hashes. 1024 is therefore a *target*,
not a current state, and reaching it is a re-embed of a small corpus
rather than a migration of a large one.

**The corpus, measured.** Session-Buddy's reflection store holds 156
conversations, all with embeddings. Akosha's `public.vectors_otel_traces`
holds 7 rows, all 384-dim. Session-Buddy's `conversations` table holds 0
rows. Small, but not empty — this plan's earlier "empty corpus" wording
overstated it.

**Why 3-large over 3-small.** On the one internally-consistent
comparison available (MTEB retrieval, nDCG@10), `text-embedding-3-large`
scores **55.4** against `text-embedding-3-small`'s **51.7**; on the
composite average, 64.6 against 62.3. Caveat: OpenAI's figures come from
its own 2024 evaluation and are not comparable to the MTEB v2 boards the
newer models report on — and **retrieval**, not the composite, is what a
memory fleet is judged on.

**Price does not settle it, and neither does the switching cost.** At
fleet volume the entire embedding bill is single-digit dollars a month —
10M tokens/month is $0.20 at 3-small and $1.30 at 3-large, so the 6.5x
difference is a rounding error. And the switching cost is near zero
*because* nothing is embedded at 1024 yet: `text-embedding-3-large` at
1024 is the same provider, the same base URL, the same `x-bf-vk` auth and
the same SDK as the model it replaces, with one extra request field.

**Why 1024.** Three independent constraints, each of which the other
candidate widths fail.

1. **3072 is not indexable at all.** pgvector's *column* type cap is
   16,000 dimensions (`VECTOR_MAX_DIM`), but its **index** cap is
   **2000 dimensions** for the float32 `vector` type (4000 for
   `halfvec`, 64,000 for `bit`), and it has not moved since pgvector
   0.4.0 in January 2023. A `vector(3072)` column therefore ingests rows
   without complaint and then fails at `CREATE INDEX` with *"column
   cannot have more than 2000 dimensions for hnsw index"* — and it
   fails twice over, because an HNSW element tuple must fit inside one
   8 kB page: a `vector(3072)` tuple needs 12,360 bytes, so even if
   the dimension check were lifted it would fail with *"index tuple too
   large"*. Akosha's warm tier is the pgvector store, and the plan's
   outcome O5 requires an HNSW index on it. The only supported path is
   `halfvec(3072)` with a cast-expression index
   (`((embedding::halfvec(3072)) halfvec_cosine_ops)`) — a change to the
   distance function's precision, not just a number — and that path
   **costs exactly what `vector(1536)` costs** (6,152 bytes per vector,
   index included), so 3072 buys nothing over 1536 even once it is
   reachable. **2048 fails the same way.** 1024 and 1536 index as plain
   `vector`.
2. **1536 is a legacy width, and it excludes the field's leader.**
   Voyage's own documentation states that `voyage-4-large`, `voyage-4`,
   `voyage-4-lite`, `voyage-3-large`, `voyage-3.5`, `voyage-3.5-lite` and
   `voyage-code-3` support `output_dimension` ∈ **{2048, 1024 (default),
   512, 256}** — 1536 is not a Voyage width. Matryoshka truncates
   downward only, so a 1536-wide fleet standard permanently excludes the
   entire Voyage family (`voyage-4-large` is the retrieval leader: it
   beat Gemini Embedding 001 by 3.87%, `embed-v4` by 8.20% and
   `text-embedding-3-large` by 14.05% on Voyage's RTEB evaluation), plus
   `jina-v5`, `BGE-M3`, `mistral-embed`, `nomic-embed-text-v2-moe` and
   `embeddinggemma`. **1024 is admitted by every one of them** — it is
   Voyage's *default*, and it is a supported MRL breakpoint for
   `text-embedding-3-large`, `embed-v4`, `embed-5`, `gemini-embedding`,
   `Qwen3-Embedding` and `voyage-4-nano`. Counted across a 25-model
   survey of the field, **1024 is admissible for 21 of them and 1536 for
   12**; Cohere's own engineering guidance for its newest model points
   the same way — *"For most deployments, we recommend 1,024-dimensional
   int8 vectors as the ideal performance-efficiency point."*
3. **The quality difference is below what our corpus can measure.**
   `text-embedding-3-large` scores 64.0 at 1024 against 64.6 at 3072 on
   OpenAI's own MTEB evaluation, and the fleet holds **163 embedded
   documents** (156 conversations, 7 trace rows). A retrieval benchmark
   on 163 documents can resolve a large gap, not a 0.6-point one — so
   quality cannot decide this, and the decision must be made on
   structure instead. Nor can the published numbers settle it: the MTEB
   leaderboard averages each model over a *different* subset of tasks
   (`text-embedding-3-large` has 8 of the 10 English-v2 retrieval tasks,
   `gemini-embedding-001` has 4, and the Voyage 4 and Cohere v4/v5
   families have **zero** — they are scored on RTEB), so a cross-model
   average is not like-for-like.

**Why the width is fixed rather than native.** A fixed width means the
storage contract, the DDL, the indexes and the migration path are
model-independent, so a model change costs one re-embed. The native-width
alternative (3072 for `text-embedding-3-large`) makes every future model
change also a width change, and a width change is a schema rebuild in
all three stores rather than a re-embed alone. That is the expensive
half, because DuckDB cannot widen a fixed-size ARRAY and
`CREATE TABLE IF NOT EXISTS` never alters.

**The gateway is not a constraint, and that is now proven.** Live probe
against the local Bifrost (v2.5.1) using `text-embedding-3-small`, whose
native width is 1536 and which supports Matryoshka truncation: requesting
1536 / 1024 / 768 / 256 each returned exactly that width, and omitting
the field returned the native 1536. Any width a model can serve is
reachable through the gateway, so the width is decided by the storage
layer and by admissibility — not by the gateway.

**What 1024 costs.** pgvector stores a float32 `vector` as
`4 × dimensions + 8` bytes — **4,104** bytes at 1024, **6,152** at 1536,
**12,300** at 3072 — so 1024 is a third less than 1536 and two thirds
less than 3072. The HNSW index is not a small overlay on top of that:
every index tuple embeds a copy of the vector (`memcpy(&etup->data, valuePtr, …)` in `hnswutils.c`), so the index adds roughly another full
column plus ~200 bytes per row of neighbour pointers. Table plus HNSW
index is therefore ≈8.5 GB per million vectors at 1024 against ≈12.6 GB
at 1536. (IVFFlat stores one centroid per list instead of a copy of
every vector and is ~430× smaller again — but O5 requires an HNSW index,
and `PgvectorSettings` has no IVFFlat knob either.) Nothing else changes:
the price is identical (OpenAI bills input tokens, and output dimensions
are free), and embedding latency is unchanged — the same forward pass,
only a smaller response payload.

**A caveat on the int8 warm store — width is not the lever that protects
it.** The intuition that quantisation error grows with √dimensions is
real for the *absolute* L2 error of a quantised vector, but it is not the
quantity that decides retrieval quality. Qdrant's published sweep
reports scalar-quantisation error as "less significant for
high-dimensional vectors" and finds one-bit binary quantisation *worse*
at 512 dimensions than at 3,072; Elastic's optimised-scalar-quantisation
write-up finds recall degrading where the score distribution is dense —
which is our case, because one codebase's corpus is homogeneous and its
scores sit close together. The rule that follows is not "narrow the
width" but **"if you quantise, re-rank at full precision"**. Width does
not protect the warm tier; re-ranking does.

**One bonus that only 1024 and 2048 get.** The Voyage 4 family shares a
single embedding space across all its models — *"All embeddings created
with the 4 series are compatible with each other"*. At 1024 that means
the index can be written by `voyage-4-large` and queried by
`voyage-4-lite` in the same space, at different cost and latency. That
is the frozen-index-space / swappable-ranker design (§1.2) working at
the *provider* level rather than only within one model.

**What is provisional.** The decision is *not* that 3-large is the best
model available — it is that it is the best model reachable without
adding a dependency. The candidate that scores higher is `cohere embed-v4` (MTEB retrieval 58.4, 128K context, built-in int8/binary
output), and it is **named in the benchmark's candidate set** (§5, and the
2026-11-20 memory-retrieval-quality plan's Phase 1). It is not the
standard today for three concrete reasons:

1. It is a **new provider leg** with a new credential, and Bifrost's
   Cohere route has to convert OpenAI's request shape into Cohere's
   (`texts`, `input_type`, `output_dimension`) — a dependency the fleet
   does not have today.
2. **Width control for Cohere is demonstrably unreliable.** Vercel's AI
   Gateway issue #16272 shows `cohere/embed-v4.0` intermittently
   returning 1536 when a narrower width was requested, while the OpenAI
   control behaves. The fleet cannot adopt a model whose width the
   gateway may silently change — that is exactly the corruption the
   `space_version` contract exists to prevent.
3. Its own numbers are **softly measured**: MTEB for `embed-v4` ranges
   from ~55 to ~66.3 across sources, against 62.3 / 64.6 for the two
   OpenAI models, which come from one vendor evaluation. A 3-point
   retrieval advantage that is not consistently reproduced is not a
   reason to add a dependency.

**The trigger.** The model is re-opened when the recall benchmark exists
and the baseline shows retrieval quality is the binding constraint. Until
then the standard is what §5 verifies. If the benchmark puts `embed-v4`
— or `voyage-3-large` at 1024 (retrieval 59.8), if its Bifrost route can
be added — materially ahead, the model changes and the corpus is
re-embedded, which is cheap precisely because the contract carries the
space id.

### 1.2 The index space is frozen; the ranker is not

The corpus is re-embedded only when the **index** model changes. Ranking
quality lives in a **separate leg with its own model and space id**, so
the ranker can be upgraded — or replaced outright by a cross-encoder —
without touching a single stored vector.

This is the structural decision that makes the fleet's embeddings
future-proof, and it is why the rerank stage is in scope (§3.4, §3.5):

```
query ─► embed(index model) ─► vector search ─► fuse with FTS ─┐
                                                                 ├─► rerank ─► top-k
        candidate ─► embed(ranker model) ───────────────────────┘
```

That is the **bi-encoder** form: the ranker embeds each candidate in its
own space and re-scores. It is the general shape — a ranker in a
different space from the index — but it is **not** the practical
populator, because it costs one extra embedding call per candidate. At a
rerank depth of 20 that is 20 round trips per query, which is seconds,
not milliseconds.

The practical form is a **cross-encoder**, which scores the query and
each candidate *together* in one call and needs no second space at all:

```
query ─► embed(index model) ─► vector search ─► fuse with FTS ─► cross-encoder ─► top-k
```

So the stage's contract is "a ranker over the fused candidates, in its
own space or none", and its populator is a hosted cross-encoder — the
only kind that is both fast and a genuine upgrade over the bi-encoder
index. That is a second provider and a second credential, which is why
it is deferred rather than built (§1.2's closing note).

- The **index space** (`text-embedding-3-large`, 1024, `space_version`
  recorded with every row) is written once, and it is the expensive
  thing.
- The **ranker** is a configured leg with its own model, width and space
  id. Today it is the same model as the index; the point is that it
  *can* be different tomorrow.
- Because the ranker lives in a **different space** from the index, it
  is free to change model, provider or class (bi-encoder →
  cross-encoder) with **zero corpus migration**.

The contract therefore has two faces: `(model, dimensions, space_version)`
describes an embedding space, and a **pipeline** names an index space
plus a ranker. `/health` reports both. A ranker that shared the index's
space would gain nothing and would re-introduce the coupling this design
removes.

The populator for the rerank stage is **deferred**, and the reason is
worth stating rather than hiding: this machine is an Intel i5-1038NG7 at
2.0 GHz with integrated graphics and no CUDA, so a local cross-encoder
is not viable — a 0.6B-parameter bi-encoder on this CPU is seconds per
query, and a first re-embed of the corpus is tens of hours. A hosted
cross-encoder is fast and cheap, but it is a second provider and a
second credential. The **interface and the contract** ship in this plan;
the populator is a later decision with its own cost and latency review.

______________________________________________________________________

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
  `use("vector", provider="pgvector")` → `LifecycleError: Swap failed for adapter:vector (pgvector)`; `use("embedding", provider="openai")` → the
  same. The settings model is already on `AdapterMetadata` and
  `DomainBridge.get_settings()` already builds it — the wiring never
  reaches the constructor.

The mock's 384 dimensions exactly matched Akosha's stale `INT8[384]` warm
column. **The system was self-consistent while broken** — which is why the
original dimension defect stayed invisible until a real provider came up.

Three separate components each carry their own now-stale idea of the width:
Akosha's `BACKEND_DEFAULT_DIMS` (`mock 384, model2vec 256, llama_cpp 768, minimax 1024` — and `embo-01` is actually **1536**, so even that entry is
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

______________________________________________________________________

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
  already distinguishes `FAILED` + `[feed_never_populated,     ingester_not_running]` from `WARMING_UP` + `[warming_up_empty_feed]`
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
  \- **Remove the Ollama leg.** It is in the approved design
  (`:59`); Ollama has since been retired fleet-wide.
  \- **`llama_cpp_base_url` default `http://localhost:8080` → `:8081`**
  (`adapters/observability/embedding_settings.py:48`). Port 8080 is
  too common a default and the fleet moved to 8081.
  \- **Add the OpenAI legs, first:** `openai_gateway` (Bifrost,
  `x-bf-vk`) → `openai_direct` (`OPENAI_API_KEY`), reusing
  `adapters/embedding/openai.py` rather than writing a parallel
  HTTP client.
  \- **MiniMax `embo-01` is natively 1536, not 1024** — the August
  design's dimension note (`:239`) is stale, and so is Akosha's
  `BACKEND_DEFAULT_DIMS`. It stays as a *tier* (a different model is
  a different space), never as a provider failover.
  \- **Model2Vec (256) and the mock (384) leave the semantic chain.**
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
- [ ] **Send `dimensions` on the OpenAI legs only, and decide that from a
  declared capability, not from the model's name.**
  `_probe_encode_via` (`:375`) and `_encode_llama_cpp` (`:397`) both
  send a fixed `{"model","input"}`. `_probe_encode_via` also sends
  **no headers at all**, so it cannot be reused as-is against an
  authenticated endpoint — it needs a `headers=` parameter.
  llama.cpp rejects unknown body fields, so the `dimensions` key must
  not be added there.
  `text-embedding-3-large` is natively 3072 and the fleet width is
  1024, so the OpenAI legs **must** send `dimensions: 1024`.
  **Where that decision is made today is the bug.**
  `adapters/embedding/openai.py:206-220` gates the field on
  `model.startswith("text-embedding-3")` — a hard-coded vendor naming
  convention inside the shared substrate. Swap the model to
  `cohere/embed-v4`, `voyage-3-large` or anything self-hosted and the
  field is dropped **silently**: the provider answers at its native
  width and a mis-sized vector reaches the store. Replace the name
  check with a **declared capability on the leg** (`native_width`,
  `supports_server_truncation`), so the client sends `dimensions`
  exactly when the target width differs from the declared native
  width, and a leg that cannot truncate is either refused or
  truncated client-side.
- [ ] **The width parameter is per-vendor, so the leg must declare how
  it sets the width — not merely what the width is.**
  OpenAI's field is `dimensions`. Voyage's is `output_dimension`;
  Cohere's is `output_dimension` too, and Cohere's
  `/compatibility/v1/embeddings` endpoint lists `dimensions` under
  **"Unsupported parameters"** — a call through it drops the field
  and returns the default width. Gemini's native field is
  `output_dimensionality`; Vertex AI has no documented
  OpenAI-compatible embeddings endpoint at all; Ark's *text*
  endpoint has no width parameter (only its multimodal one does);
  and Nomic's endpoint is not OpenAI-shaped at all.
  **The dangerous case is silent**: Bifrost forwards `dimensions`
  verbatim to a *generic* OpenAI-type custom provider, so a Voyage
  model behind Bifrost returns its 1024-dim default with no error
  and no warning — and the vector lands in a 1024-wide store
  looking entirely correct. Bifrost renames the field per upstream
  only for its *built-in* providers.
  So the leg's declared capability needs a third field alongside
  `native_width` and `supports_server_truncation`: **how the width
  is requested** (`width_parameter`, and whether the endpoint can
  set it at all). A leg whose endpoint cannot set the width is
  eligible only when its declared `native_width` equals the fleet
  width — otherwise it must be refused, not silently accepted.
  Perplexity's `pplx-embed-v1-*` is a trap of its own: its
  `encoding_format` enum is `base64_int8` / `base64_binary` only,
  with no float, so it needs a decode plus an L2 normalisation — the
  provider states that casting the int8 values to float "does not
  restore a full-precision embedding".
- [ ] **Make the OpenAI-compatible leg generic over
  `(base_url, model, dimensions, auth)`.** The chain has separate code
  paths per provider today — `openai_gateway`, `openai_direct`,
  `llama_embed`, `llama_server` — each with its own request builder.
  Bifrost, direct OpenAI, Cohere's OpenAI-compatible endpoint, a local
  llama.cpp server, or any future vendor should be **one leg type with
  four configuration values**, not four functions. This is the change
  that makes a future provider a configuration edit rather than a new
  adapter module, and it keeps the self-hosted option alive as a
  *possibility* even though this machine cannot run one (Intel i5 at
  2.0 GHz, no CUDA — see §1.2).
- [ ] **Make the fallback a hard failure.** `initialize()` never raises;
  it always lands on the 384-wide mock (`:130-136`).
  `OpenAIEmbeddingAdapter.init()` (`openai.py:84-86`) already raises
  `LifecycleError` — and already *calls* `embed_text("initialization     test")`, so it is a real reachability probe. That is the natural
  gate; wire it into the chain.
- [ ] **Add `FLEET_EMBEDDING_MODEL` / `_DIM` / `_SPACE` constants and a
  construction-time cross-check** that a configured width equals
  `FLEET_EMBEDDING_DIM`.
- [ ] **Widen the four hard-coded 384s in the observability subsystem.**
  They would reject every 1024-wide vector the new leg produces:
  `observability/models.py:31` `Vector(384)`;
  `observability/queries.py:55` `shape != (384,)`;
  `observability/migrations.py:22` `embedding VECTOR(384)`;
  `observability/settings.py:36` `embedding_dimension` (default 384,
  `le=1024`).
- [ ] **Raise the `le=1024` validation bounds — and note that the fleet
  width lands exactly on the current ceiling.** Four fields in the
  fleet cap a width at 1024: `EmbeddingCreate.embedding_dim` and
  `EmbeddingCreate.embedding` (mahavishnu
  `core/repositories/embeddings.py:78-83`, `ge=128, le=1024` and
  `min_length=128, max_length=1024`),
  `OTelStorageSettings.embedding_dimension` (oneiric
  `adapters/observability/settings.py:35-37`, `ge=128, le=1024`), and
  `SemanticConfig.embedding_dimension` (crackerjack
  `models/semantic_models.py:168-173`, `ge=128, le=1024`).
  **1024 passes all four exactly at the bound; 1536 and 3072 are
  rejected at construction.** That is not a reason to pick 1024 on
  its own — it is a reason to know the cost of any other width: the
  oneiric bound is the sharp one, because
  `mahavishnu/core/config.py:1035` subclasses
  `OTelStorageSettings` (`class OTelStorageConfig(_OneiricOTelStorageSettings)`)
  and loads it from `settings/mahavishnu.yaml:119`, so **a width
  above 1024 fails Mahavishnu's entire settings load until Oneiric
  releases.** Raise them to `le=4096` so the bound stops being a
  hidden ceiling on the contract.
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
  embeddings route**, and `text-embedding-3-large` appears nowhere in
  Mahavishnu's Bifrost wiring. The `openai` *provider* is configured,
  so the route is the missing piece, not the provider — but its key
  allowlist must now carry **`text-embedding-3-large`**. A model
  outside the allowlist fails locally with `no_key_supports_model`
  before the request is ever sent, so this is a hard gate, not a
  preference.
- [ ] **The gateway's `cache_mode` is `semantic`, and it is NOT part of the
  fleet's embedding contract.** Its plugin is configured
  `embedding_model: text-embedding-3-small`, `dimension: 1536`,
  `provider: openai`, `threshold: 0.95`, `ttl: 30m`. It is an
  **LLM-response** cache: it embeds requests and responses to decide
  whether a cached response matches, and those vectors are its own
  cache keys, not the fleet's semantic vectors. It can therefore keep
  using `text-embedding-3-small` at 1536 whatever width the fleet's
  semantic model uses, **and changing the fleet's model does not
  invalidate its cache** — there is nothing to flush and nothing to
  repoint. The only coupling is that the model the plugin names must
  stay allowed for that provider key, and this plan adds a model
  rather than removing one. Note the known upstream issue where this
  plugin cannot resolve a local/custom embedding provider inside its
  `PreLLMHook` even when the same provider/model succeeds through
  `/v1/embeddings`, and its 8192-token input limit below.
- [ ] **Watch the gateway's 8192-token input limit.** The semantic-cache
  plugin does not truncate: 514 of 869 consulted requests failed on
  that limit. And the model must be in the provider key's `models: [...]`
  allowlist, or every attempt fails locally with `no_key_supports_model`.
  The direct `/v1/embeddings` round trip is verified live at 1024; the
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
  \- `mahavishnu/ingesters/otel_ingester.py` carries its **own**
  embedder, separate from the shared service: `EmbeddingBackend.FASTEMBED`
  (`:61`), `FastEmbedWrapper` (`:126`), a guarded
  `import fastembed` (`:23-39`), and `_map_to_fastembed_model`.
  The guard is *always false* — `fastembed` is not a dependency —
  so the leg is unreachable, not merely unused.
  \- `mahavishnu/ingestion_cli.py` carries four CLI help strings
  advertising `"fastembed|openai"` as a provider choice.
  \- `settings/embeddings.yaml:35` sets `provider: fastembed` in a
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
  `STANDARD_EMBEDDING_DIMENSION = 384` → 1024, and
  `_validate_dimension` (`:206-222`) must *reject* a mismatch rather
  than count it. As it stands, a width mismatch returns `False`, every
  tier falls through, and `generate_embedding` lands on the mock tier
  (`:227-252`) — so a width change becomes **100% mock embeddings
  with one `logger.warning` per call**, and no error anywhere.
- [ ] **Carry the width in the embedding cache key.**
  `core/embedding_cache.py:190` declares `model_version: str = "1.0.0"`
  and the cache key is `f"{model_version}:{text_hash}"` (`:347`) —
  it carries **no width and no space id**. A width change without
  bumping `model_version` serves stale-width vectors out of the L1/L2
  cache. The key must include the space id, not a hand-bumped
  version string.
- [ ] **Raise `EmbeddingCreate`'s width bounds.**
  `core/repositories/embeddings.py:78-83` caps `embedding_dim` at
  `le=1024` and `embedding` at `max_length=1024`, while the column it
  writes to is `vector(384)`
  (`migrations/versions/V202604021200__initial_consolidated_schema.sql:166`).
  The check accepts widths the schema rejects — and
  `core/search/hybrid_search.py:623-639` writes the same table with
  **raw SQL**, bypassing `EmbeddingCreate` entirely, so a wide
  embedding reaches `vector(384)` with no validation gate at all.
  Two write paths, two different gates, one table: both must go
  through the contract.
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
  `[MHV-002] Unexpected database error: PostgreSQL server at     "localhost:5432" rejected SSL upgrade`.
- [ ] **Re-embed the live pgvector table.** In the `mahavishnu` database,
  `public.vectors_otel_traces` holds **7 rows, all 384-dim**, with the
  fork's exact schema and its HNSW (`m=16, ef_construction=64`) and GIN
  indexes. The rows carry `task.class` values of
  `CODE_GENERATION`/`REASONING`/`SEARCH` — **never** `mcp_tool_call` —
  and are from a manual run, not a live feed. A 1024 move needs a new
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
  rebuild `conversations` at 1024 (it holds 0 rows, so this is close to
  free; `hot.db` is 894 MB and needs `hot.db` **and** `hot.db.wal`
  backed up together).
- [ ] **Parameterize the one hard-coded width left in Akosha's executable
  path: `embedding INT8[384]`** at `storage/warm_store.py:77`.
  `WarmStore.__init__` (`:49`) takes **no dimension parameter at
  all**, so the DDL cannot be parameterized today — and DuckDB
  rejects the cast outright (verified: *"Cannot cast list with length
  1024 to array with length 384"*). This breaks every hot→warm
  migration, and the exception is **swallowed** at `storage/aging.py:253`
  (`except Exception` → `stats.errors += len(batch)`), so the aging
  tier quietly stops migrating and reports only an error count.
  `create_warm_store` (`storage/__init__.py:243`) must thread the
  resolved dimension through, mirroring `PgvectorWarmStore`.
  **This single line breaks the fleet** — it is the first thing to
  fix.
- [ ] **Fix the ingestion worker's zero-vector fallback.**
  `ingestion/worker.py:564` writes `embedding=conv.get("embedding",     [0.0] * 384)` — a 384-wide fallback regardless of the schema. At the
  fleet width a payload with no `embedding` key produces a
  wrong-width zero vector → `ValueError` from `HotStore.insert` →
  caught at `:580` → **the conversation is silently dropped**.
- [ ] **Fix the byte-accounting constants.** `storage/aging.py:144` and
  `:246` add a flat `2500` bytes per record ("int8 embedding (384B)").
  At the fleet width that under-reports. Derive it from the width.
- [ ] **Widen `akosha_store_memory`'s dimension check.**
  `mcp/tools/session_buddy_tools.py:138-145` compares the incoming
  width against a hardcoded 384 and, on a mismatch, **logs a warning
  and proceeds** — it does not reject. Only a `None` embedding is
  rejected, and its error message ("must be a 384-dimensional vector")
  is itself stale. So this does **not** block Session-Buddy's push;
  it fires a misleading warning on every push at the fleet width.
  Fix it to check the fleet width against the *contract*, not a
  literal — and against the **live schema width**, not a second
  literal, or the check and the column disagree in both directions.
  It also discards ten lineage fields (`:26-42`), so the
  pushed rows carry no provenance — the same vocabulary problem the
  aging filter has.
- [ ] **Carry the space id on every stored vector.** The warm tier's
  `public.vectors_otel_traces` has no width column and no model
  column, and Crackerjack's `embeddings` table has neither. Without
  them, "which rows came from the old model?" is a guess rather than
  a query, and a model change becomes a blind rebuild. Add
  `embedding_model` and `embedding_dim` (or a single `space_version`)
  to every vector-bearing table, write them on every insert, and
  assert the pair on read. This is the difference between a re-embed
  being a `DELETE` and it being a `SELECT ... WHERE`.
- [ ] **Add the rerank stage to the retrieval pipeline.**
  `retrieve (vector) → fuse with FTS (RRF) → rerank → top-k`. The
  rerank leg is a separately configured model with **its own** space
  id, deliberately *not* the index space (§1.2), so the ranker can be
  changed without re-embedding the corpus. Today the stage is a
  documented pass-through that reports its configuration; the
  populator is deferred (§1.2). `/health` reports the index space and
  the ranker's model and space id separately, and the search response
  carries `rerank: {model, applied, reordered}` so the stage is
  observable rather than invisible.
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
| Width served | **768**, not 1024 |
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

Live-probed consequence: raising only `DEFAULT_EMBEDDING_DIM` to 1024
moves `EMBEDDING_DIM` to 1024 while every leg still *declares* 768
(OpenAI), 768 (`llama_embed`) or 4096 (`llama_server`). **No leg is
eligible; the chain returns `None` for every request**
(`chain result (width=1024): None`) and every write degrades to a NULL
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

- [ ] **Move 768 → 1024 in both constants, atomically**
  (`memory/embedding_dim.py:39` **and** `reflection/embeddings.py:81`).
  Leaving `llama_server` declared at its true 4096 and `llama_embed`
  at 768 is *correct* — they then become ineligible, which is the
  intended outcome, not a bug to fix.
- [ ] **Point the request body at the fleet model and width.** Both OpenAI
  legs send `{"model", "input", "dimensions": OPENAI_EMBEDDING_DIM}`
  (`reflection/embeddings.py:323` and `:339`), and the model names
  come from `BIFROST_EMBEDDING_MODEL` / `OPENAI_EMBEDDING_MODEL`,
  both defaulting to `text-embedding-3-small`. Change the default to
  **`text-embedding-3-large`** and keep `dimensions` — 3-large is
  natively 3072, so `dimensions: 1024` is now **required**, not
  optional (§1). The field is what makes the *same* width reachable
  from a model of a different native width, so it stays part of the
  request; what changes is that it is now load-bearing. Note the
  current bug it papers over: today that field asks
  `text-embedding-3-small` for a **768-wide truncation of a
  native-1536 model**, so the fleet has been running a lossy vector
  and calling it the model's width.
- [ ] **Add the hard startup gate.** A `verify_provider_reachable()` that
  probes the eligible legs and returns the serving leg + width; the
  lifespan calls it and **aborts startup** on failure. The failure
  message must name both ("no real embedding provider reachable;
  required width 1024"). Do not follow the surrounding
  swallow-everything pattern.
- [ ] **Add an embedding health feed** and expose `get_embedding_system_info()`
  via an MCP tool and in `/health` (mirroring the `skills_signer`
  pattern at `server_optimized.py:460-475`). The feed reports the
  **index space** and the **ranker's** model and space id separately
  (§1.2) — a single space id cannot express both.
- [ ] **Stop storing embedding-less rows.** `coerce_embedding` and the
  write path (`adapters/reflection_adapter_oneiric.py:1284-1292`)
  must raise on a missing or wrong-width vector, not log a warning
  and store a degraded row.
- [ ] **Rebuild the database at 1024.**
  `scripts/migrate_embedding_dim.py --to-dim 1024 --replace --re-embed`.
  **Without `--re-embed` the database comes back 100% NULL-embedded**
  (the script drops every vector, `:235-236`). Stop the server first
  — DuckDB is single-writer. 313 vectors in a 53 MB database, so the
  rebuild is cheap.
- [ ] **Migrate the BLOB-backed embeddings separately.** The script only
  sees `FLOAT[N]` (`:96-120`). `skill_invocation.embedding` and
  `centroid_embedding` are BLOBs; `EMBEDDING_BYTES` must go to 4096
  at 1024 (`storage/skills_embeddings.py:46-47`) and every existing
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
  1\. `storage/akosha_sync.py:191` uses `config.cloud_endpoint` — the
  **Cloudflare R2 S3 endpoint** — as the Akosha base URL.
  2\. `:1067` appends `/mcp/v1`; Akosha mounts `/mcp` only (404).
  3\. **The tool names do not exist.** The live Akosha server
  registers 39 tools, and only two are in the store family:
  `akosha_store_memory` and `akosha_batch_store_memories`.
  Session-Buddy calls `store_reflection` (`:540`),
  `create_entity` (`:700`), `create_relation` (`:732`) and
  `batch_store_memories` (`:981`) — none of them unprefixed, and
  **`create_entity` and `create_relation` have no counterpart on
  the Akosha side at all**, prefixed or not. The knowledge-graph
  write path Session-Buddy intends has no receiver; it has to be
  designed, not renamed.
  4\. `storage/akosha_config.py:222-224` reads `HOSTNAME`, which macOS
  does not export into a launchd process — the live `system_id` is
  **`"unknown-system"`**, not the hostname. `socket.gethostname()`
  is the fix (as `bodai_events_publisher.py:191` already does).
  5\. Akosha's dimension check compares against a hardcoded 384
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
  as the automated path once Akosha's width moves to 1024.
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
- [ ] **Update `2026-11-06-fleet-embedding-width-768.md`** to 1024 and
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
  (`_parse_semantic_config` default); `cli/semantic_handlers.py:39,     100, 189, 257` and the hard-coded display row `"384"` at `:211`.
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
  `{"model":"text-embedding-3-large","input",...,"dimensions":1024}`
  on the OpenAI legs — 3-large is natively 3072, so the `dimensions`
  field is **required** to reach the fleet width (§1) — and
  `{"model","input"}` on llama (llama.cpp rejects unknown body
  fields). The client is **sync** (`httpx2.Client`, per the
  repo's `import httpx2 as httpx` convention).
- [ ] **Make `embedding_backend` mean something** — it should gate which
  legs are eligible: `"auto"` = the chain, `"openai"` = OpenAI legs
  only, `"local"` = local legs only. Today it selects nothing.
- [ ] **Record the index width and rebuild on mismatch.** The `embeddings`
  table has no width column, so a stale 384-wide BLOB is read as if
  it were 1024. Add an `embedding_dim` column (or a `meta` table);
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

______________________________________________________________________

## 4. Sequencing

### 4.1 The five things to fix first

The width change touches more code than the literals suggest, and the
failure modes are uneven: some are loud, some are silent, and the silent
ones are worse. In dependency order:

1. **`akosha/storage/warm_store.py:77` — `embedding INT8[384]`.** The
   only hard-coded width in Akosha's executable path, and the one that
   breaks the fleet: DuckDB rejects the cast outright, and the exception
   is swallowed by the aging service, so the warm tier quietly stops
   migrating. `WarmStore.__init__` takes no dimension parameter today.
2. **The four `le=1024` validation bounds** (oneiric's
   `OTelStorageSettings.embedding_dimension`, mahavishnu's
   `EmbeddingCreate` pair, crackerjack's `SemanticConfig`). Nothing can
   be tested above 1024 until they are raised, and the oneiric one gates
   **Mahavishnu's entire settings load**.
3. **`session_buddy/reflection/embeddings.py:81` —
   `OPENAI_EMBEDDING_DIM`.** A hard-coded duplicate of
   `DEFAULT_EMBEDDING_DIM` that is not derived from it. Move the
   constant and the two OpenAI legs become *ineligible* — the chain
   silently has no provider, and the only signal is a
   `skipped_providers` entry in `get_embedding_system_info()`.
4. **`mahavishnu/core/resilient_embeddings.py:206-224` —
   `_validate_dimension`.** It must raise, not count. As written, a
   width mismatch falls through every tier to the mock, turning the
   change into 100% mock embeddings with one warning per call.
5. **The schema literals no constant can reach** — oneiric's
   `observability/models.py:31` and `migrations.py:22`, and
   `queries.py:55`'s `(384,)` shape gate; mahavishnu's
   `migrations/init.sql:126,285` and
   `V202604021200__initial_consolidated_schema.sql:166`. Each needs the
   literal changed **and** a real widening migration: `CREATE TABLE IF NOT EXISTS` never alters, and DuckDB cannot widen a fixed-size ARRAY
   in place — the vectors must be dropped and re-embedded, because they
   carry no meaning in the new space.

Then, so that the width is one fact rather than five guesses: **`FLEET_ EMBEDDING_DIM` does not exist anywhere in the fleet.** Oneiric already
has `embedding__dim` and `warm__embedding_dim` with the right bounds
(`le=4096`) and docstrings that *promise* enforcement that exists
nowhere — wire them or delete them. Session-Buddy's
`memory/embedding_dim.py` is the cleanest existing source-of-truth
implementation and should be the model. Every check must read the
**live schema width**, never a second literal: today ten such
check-vs-schema disagreements exist, and each one is a place where the
fleet accepts a width its own column will reject.

```
  mcp-common: emit task_class/selector/outcome   ─┐
                                                    ├─► mcp_tool_call_feed populates
  Akosha: fix the subscriber + decode the shape  ─┘

  Oneiric: registry wiring + Bifrost header + the   ──► release
           OpenAI legs + 1024                        │
                                                    │
  Akosha: adopt it, rebuild conversations, widen  ┤
           store_memory's accepted width  ─────────┤
  Session-Buddy: both constants → 1024, rebuild,  ┤
           startup gate, health feed ──────────────┤
  Mahavishnu: subclass the adapter, fix ef_search ┤
  Crackerjack: real embeddings at 1024 ───────────┘
                                                    │
                                                    ▼
                              operator bumps pins, publishes
                                                    │
                                                    ▼
                        unified pgvector warm tier → enable aging
                                                    │
                                                    ▼
              Session-Buddy pushes conversations → Akosha (now 1024)
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
at the wrong width is *accepted* — but a 1024-wide vector cannot bind
into a 384-wide DuckDB `FLOAT[N]` column at all. Widening the producer
without widening the receiver produces rows that cannot be written, or
that must be re-embedded later.

______________________________________________________________________

## 5. Verification gate

The fleet is up to speed when all of these hold. **None of them is an HTTP
status code.**

- [ ] `/health` on every server: `_aggregate.status == "ok"`,
  `data_feeds_ok == true`.

- [ ] Every feed's `source` names a producer that is **running**, and the
  feed's `entities_count > 0`.

- [ ] Every component reports the same embedding model, width and space
  id; `embeddings.mode == "real"` on Akosha. The model is
  `text-embedding-3-large` and the width is **1024**.

- [ ] **The request body carries `dimensions: 1024`, and the response is
  1024-wide.** 3-large is natively 3072, so this asserts the
  truncation actually happened rather than trusting the request. A
  3072-wide response against a 1024-wide store is the silent
  corruption this gate exists to catch.

- [x] **`text-embedding-3-large` is on the OpenAI provider key's model
  allowlist.** Verified live: the gateway answers HTTP 403 — *"Model
  'text-embedding-3-large' is not allowed for virtual key
  'bodai-pi-pool'"*. The virtual key itself allows everything
  (`allow_all_keys=1`, `allowed_models=["*"]`); the gate is the
  provider key `openai-primary`'s `models_json`, which lists
  `text-embedding-3-small` and not `-large`. A model outside that
  allowlist fails locally, before the request ever reaches OpenAI.
  **Done on 2026-11-20**: `config_keys.id = 3` (`openai-primary`) now
  reads `["gpt-5.4","gpt-5.4-mini","gpt-5.6-luna","gpt-5.3-codex","text-embedding-3-small","text-embedding-3-large"]`,
  confirmed by reading it back, and the round trip below proves the
  model is now reachable.

- [x] **The gateway forwards `dimensions` — verified; keep it that way.**
  Live probe against the local Bifrost, using `text-embedding-3-small`,
  whose native width is 1536 and which supports Matryoshka truncation:
  requesting 1536 / 1024 / 768 / 256 each returned exactly that width,
  and omitting the field returned the native 1536. **Any width a model
  can serve natively or by truncation is therefore reachable through the
  gateway, and the fleet width is not constrained by the gateway.**
  Re-run in the gate: a gateway that dropped the field would answer at
  the native width, and a mis-sized vector would reach the store.
  **Re-run it with `text-embedding-3-large`**, not `-small`: the point
  of the probe is that the *fleet's* model honours the field.
  **Done on 2026-11-20**, against the v2.6.0 transport, with the
  fleet's own model at the fleet's width:

  | model | requested | returned width |
  |---|---|---|
  | `text-embedding-3-small` | 1024 | 1024 |
  | `text-embedding-3-large` | **1024** | **1024** |
  | `text-embedding-3-large` | 3072 | 3072 |
  | `text-embedding-3-large` | omitted | 3072 (native) |

  The third row is the control: it proves the field is forwarded
  rather than clamped, and the fourth proves the model's own native
  width is still 3072 — so the 1024 in the second row is a real
  truncation, not a different model.

- [ ] **Re-run the probe after any transport upgrade.** The transport
  pin moves the gateway's binary, and the `compat` component is where
  a provider's width handling lives. This one passed on v2.6.0
  (`compat` v0.5.7 altered only Baseten decision models), but a
  future upgrade could change it silently — the probe is cheap and
  the failure mode is a mis-sized vector reaching the store.

- [ ] The index space and the **ranker's** space id are reported
  separately, and the search response carries
  `rerank: {model, applied, reordered}` (§1.2).

- [ ] Every stored vector row carries its `embedding_model` and
  `embedding_dim` (or `space_version`), and a row written before the
  last model change is *queryable* by it.

- [ ] A live Bifrost `/v1/embeddings` round trip returns 1024-wide
  unit-norm vectors, and the direct-OpenAI failover returns vectors in
  the **same** space.

- [ ] A wrong-width vector is rejected; so is a right-width vector from
  the wrong model.

- [ ] **The recall benchmark scores the candidates, not just the
  incumbent.** The committed baseline is recorded for
  `text-embedding-3-large` at 1024 *and* for `cohere embed-v4` at
  1024 (§1.1), so the model decision rests on our corpus rather than
  on a leaderboard. This is the 2026-11-20 memory-retrieval-quality
  plan's Phase 1; the standardisation plan does not ship without it.

- [ ] **The benchmark also measures the *width* on our own corpus, at
  three widths of one model.** Take `text-embedding-3-large` at
  3072, 1536 and 1024 and measure nDCG@10 on our own labelled
  queries at each. Every vendor curve says the answer will be
  "1024 is fine" — OpenAI's own table puts 1024 within 0.5 points
  of 3072, and the measured loss across models is 0.3 to 1.05
  points, which is inside a leaderboard run's noise — but only our
  corpus can confirm it. This is the one measurement that could
  reopen the width, so it is the one measurement to run.

- [ ] **The candidate set includes the models that post-date the
  decision**: `cohere embed-v5.0-pro` / `-fast` (released 30 Sep
  2026, native 2048, admissible at 1024, Pro and Fast share one
  embedding space), and `perplexity pplx-embed-v1-4b` (native 2560,
  MRL to 128, int8/binary output only — its `encoding_format` enum
  has no float, so it needs a decode and an L2 normalisation).

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

- [ ] **Both** Session-Buddy width constants read 1024. A check that
  reads only `memory/embedding_dim.py` is not a check.

- [ ] No embedding-less rows: the count of rows with a NULL embedding is
  zero, and no write path logs a warning and stores a degraded row.

- [ ] `conversations_v2` rows carry a non-NULL `source_type`, written by a
  named producer — and `session_buddy_search_by_source` returns rows
  under at least one real category rather than only `[all sources]`.

______________________________________________________________________

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

______________________________________________________________________

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
