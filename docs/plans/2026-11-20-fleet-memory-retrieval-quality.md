---
status: draft
role: implementation
kind: plan
date: 2026-11-20
last_reviewed: 2026-11-20
topic: fleet-memory-retrieval
plan_kind: implementation
blocks_on:
  - docs/plans/2026-11-19-fleet-standardisation.md
related_plans:
  - mahavishnu/docs/adr/020-bodai-ecosystem-memory-architecture.md
  - mahavishnu/docs/plans/2026-11-19-fleet-standardisation.md
cross_repo_plans:
  - akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md
  - session-buddy/docs/plans/2026-11-06-conversation-transcript-ingestion.md
  - session-buddy/docs/plans/2026-11-06-fleet-embedding-width-768.md
requirements:
  - id: REQ-FLEETMEM-001
    title: "Fleet recall benchmark harness with a committed baseline"
  - id: REQ-FLEETMEM-002
    title: "Rank fusion over lexical and vector channels in the semantic owner"
  - id: REQ-FLEETMEM-003
    title: "Per-category relevance half-life in ranking, not retention"
  - id: REQ-FLEETMEM-004
    title: "MCP tool behaviour annotations across the fleet"
  - id: REQ-FLEETMEM-005
    title: "Multi-harness capture coverage for Codex and Cursor"
  - id: REQ-FLEETMEM-006
    title: "Reversible preview on memory projection writes"
---

# Fleet Memory Retrieval Quality — make the memory layer measurable, then make it good

**Date:** 2026-11-20 · **Status:** draft · **Role:** implementation · **Owner:** unassigned

**Purpose:** the fleet spine (`2026-11-19-fleet-standardisation.md`) fixes
what the fleet *stores* — one embedding model at one width, a corpus that
actually reaches Akosha, a unified warm tier. It does not measure or improve
what the fleet *retrieves*. This plan is the next spine: it makes recall
measurable, fuses the two retrieval channels the fleet already has, ranks
with time-decay, and closes three coverage gaps that no existing plan owns.

**This plan does not replace a component.** It implements ADR 020 §6
(federated retrieval, not a universal façade) and §7 (observable as a
system) for the *retrieval* slice only. The six-repository fleet plus Bodai
Kit remains the architecture; nothing here proposes a seventh store or a
new one.

---

## 0. Relationship to existing work — collision audit

This section exists because the fleet already has a spine and two draft
per-repo plans in this space. Everything below was checked against the
repositories on 2026-11-20, not inferred.

| Existing artefact | Status | What it owns | How this plan differs |
|---|---|---|---|
| `mahavishnu/docs/plans/2026-11-19-fleet-standardisation.md` | draft | Embedding model/width/chain, corpus path repair, Session-Buddy → Akosha push repair, unified warm tier, health-feed truthfulness | **This plan starts after it** (`blocks_on`) and touches none of it. No embedding, no transport, no corpus-parser work appears here. The spine makes the vectors real; this plan makes them retrievable and proves it. |
| `akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md` (Plan M) | draft | Akosha's share of the spine: unified pgvector warm tier, HNSW, tier migration | Plan M builds the **substrate** (one pgvector table, indexed, searchable). This plan builds the **consumers** on top of it — fusion, decay, and the benchmark that scores it. Phase 2 lands *inside* the tier Plan M creates. |
| `session-buddy/docs/plans/2026-11-06-conversation-transcript-ingestion.md` | draft | Conversation corpus ingestion; **already specifies Reciprocal Rank Fusion** for `search_conversations` (DuckDB FTS + vector → RRF), `embedding_status='pending'` + background filler, four delete scopes, retention sweeper, health surface | **Real overlap, deliberately not duplicated.** This plan does **not** re-specify Session-Buddy's RRF — that plan owns it. This plan supplies the *fleet benchmark* that scores it, and the Akosha-side fusion that the transcript plan does not cover. Phase 1's harness treats the Session-Buddy plan's RRF as an existing candidate implementation to be measured. |
| `session-buddy/docs/plans/2026-11-06-fleet-embedding-width-768.md` | draft (width superseded → 1536) | Embedding migration mechanics | Not touched. |
| `mahavishnu/docs/adr/020-bodai-ecosystem-memory-architecture.md` | active, canonical | The ownership model: who owns which kind of truth, the promotion path, federated retrieval, correction/deletion | **This plan is subordinate to it.** It implements ADR 020 §6/§7 for retrieval. It changes no ownership assignment and introduces no cross-component write path that ADR 020 §2 (typed overlap) does not already permit. |

### 0.1 Already-built capability this plan reuses rather than reinvents

Two corrections to a naive reading of the gap:

- **Mahavishnu already implements rank fusion.**
  `mahavishnu/core/vector_search.py:_hybrid_search` computes vector
  similarity (`1 - (e.embedding <=> $1::vector)`) and FTS rank
  (`ts_rank(...)`) and merges them with reciprocal rank fusion — and it is
  **wired**, exposed as `mahavishnu_hybrid_search`
  (`mahavishnu/mcp/tools/search_tools.py:284`). Phase 2 is therefore a
  **port**, not an invention, and it should carry the same function shape
  rather than a new one.
- **Session-Buddy already has an exponential-decay primitive.**
  `session_buddy/memory/causal.py` decays causal-chain strength with a
  half-life of `3600·ln2 ≈ 5197 s` (≈ 86.6 min). What does not exist
  anywhere in the fleet is a **per-category relevance half-life** applied to
  general memory ranking — Phase 3 adds the policy, not the maths.

### 0.2 Fleet-wide absence checks (2026-11-20)

`rg` over the six repositories, excluding `tests/` and `.venv/`:

| Capability | mahavishnu | session-buddy | akosha | crackerjack | oneiric | mcp-common |
|---|---|---|---|---|---|---|
| Rank fusion (RRF) in code | **1** (`core/vector_search.py`) | 0 | **0** | 0 | 0 | 0 |
| Per-category half-life | 0 | 0 (causal-only) | 0 | 0 | 0 | 0 |
| MCP behaviour annotations | **0** | 0 | 0 | 0 | 0 | 0 |
| Codex / Cursor capture hooks | 0 | 0 | 0 | 0 | 0 | 0 |
| `dry_run` on the memory projection path | 0 | 0 | 0 | 0 | 0 | 0 |

The `codex` string does appear in mahavishnu and akosha — as the
`terminal-codex` **worker type**, the Codex subscription **token** command,
and OTEL `service.name` resource comments. None of it is capture. Session-Buddy's
hook set covers `SessionStart`, `SessionEnd`, `PreCompact`, `Stop` and
`PostToolUse` for **Claude Code only**.

---

## 1. Outcome

**A published, reproducible recall number exists for every memory surface in
the fleet, and it moves.** A harness runs a fixed public dataset against the
live MCP surfaces, commits per-question results, and reports R@5 and R@10 for
each. The baseline is committed on day one. A change that improves recall is
visible as a diff against that baseline; a change that regresses it fails CI.

The user-observable change: "is our memory actually working?" acquires an
answer that anyone can reproduce with one command, instead of an assertion.

**Success signal:** `benchmarks/recall/RESULTS.md` exists with a committed
baseline for at least the Akosha cross-system surface and the Session-Buddy
conversation surface, and the harness runs in CI against a floor.

## 2. Goals

1. **Measure recall.** A harness, a dataset, a committed baseline, a CI floor.
2. **Fuse the retrieval channels** in the component that owns semantic
   intelligence (Akosha), porting mahavishnu's existing RRF rather than
   writing a second one.
3. **Rank with time.** A per-category relevance half-life so that a
   two-year-old decision does not outrank today's context.
4. **Make tool schemas self-describing** so an agent can pick a read-only
   tool without probing.
5. **Capture every harness we actually run.** A session we do not capture is
   a session we cannot remember.
6. **Make memory writes previewable** so a destructive projection is
   reversible rather than merely logged.

## 3. Non-Goals

- **No new store.** No seventh component, no new database, no "unified
  memory database". ADR 020 rejects that outright.
- **No change to ownership assignments.** ADR 020's table is authoritative
  and untouched.
- **No embedding, transport, or corpus-parser work.** That is the spine's.
- **No per-component vector search rewrite.** Mahavishnu's fusion works and
  is wired; this plan ports its shape, not its code, into Akosha.
- **No relevance decay that deletes.** Half-life affects *ranking only*.
  Retention and deletion remain the owner's decision under ADR 020 §8.
- **No adoption of MemPalace, Basic Memory, or MemoryPlugin.** A comparison
  on 2026-11-20 concluded the fleet should continue with Kit + Session-Buddy
  + Akosha (ADR 020's ownership model already encodes that). These systems
  contributed *patterns*, which are named in §5 — not code.
- **No benchmark numbers claimed without a committed run.** No published
  figure that a `git log` cannot reproduce.

---

## 4. Current findings

All claims here were verified against the repositories on 2026-11-20.

**F-1 — The fleet has no memory benchmark.** `rg -i "longmemeval|locomo|membench|recall@|r@5"`
matches **zero files** in session-buddy and akosha; neither repo has a
`benchmarks/` directory. The fleet's spine plan verifies that tools "return
real data" — it never verifies that the data returned is *relevant*. A
pipeline can be fully green and return the wrong rows.

**F-2 — Akosha has no rank fusion.** `rg -i "reciprocal.rank|\brrf\b"` in
`akosha/` → 0 hits; `rg -i "bm25"` → 0 hits. Akosha's pgvector stores compute
`distance_metric="cosine"` (`akosha/storage/pgvector_hot_store.py:87`,
`akosha/storage/pgvector_warm_store.py:67`) and filter on it — a pure
vector channel. The lexical channel exists only in mahavishnu.

**F-3 — Mahavishnu's fusion is the reference implementation, and it works.**
`mahavishnu/core/vector_search.py:463` documents "Hybrid search combining
vector + FTS with reciprocal rank fusion"; it is reachable as
`mahavishnu_hybrid_search` (`mahavishnu/mcp/tools/search_tools.py:284`).
It is the shape to port, and the proof that this fleet can build it once.

**F-4 — Decay exists, but only for causal chains, and at one hour.**
`session_buddy/memory/causal.py:25` documents `time_decay =
exp(-Δseconds / 3600)`, half-life ≈ 5197 s. There is no category-scoped
decay anywhere in the fleet — no `half_life` symbol outside that one module.

**F-5 — No MCP tool anywhere in the fleet declares its behaviour.**
`rg -i "readOnlyHint|destructiveHint|idempotentHint|openWorldHint|ToolAnnotations"`
→ **0 hits in all six repositories.** The fleet exposes 178 (mahavishnu),
227 (session-buddy) and 39 (akosha) tools with no machine-readable statement
of which are safe to call speculatively and which mutate. The fleet's
`discover_tools` meta-tool compensates with an extra round trip.

**F-6 — Capture covers one harness.** Session-Buddy's hook set is
`SessionStart`/`SessionEnd`/`PreCompact`/`Stop`/`PostToolUse`. `codex` and
`cursor` appear in the fleet only as a worker type, a token command and
OTEL resource attributes. MemPalace ships Claude Code + Codex CLI + Cursor
hooks; the fleet ships Claude Code only.

**F-7 — Memory projection writes have no preview.** `dry_run` appears 35
times in mahavishnu and 33 in crackerjack, all in CLI and migration scripts.
`rg -i "dry_run"` in `akosha/akosha/mcp/tools/session_buddy_tools.py` and
`session_buddy/session_buddy/storage/akosha_sync.py` → **0 hits**. The write
paths that create cross-component memory have no dry-run, and near-duplicate
detection produces merges rather than reversible drafts.

**F-8 — The corpus the spine repairs is the corpus this plan scores.** The
spine repairs three severed paths (Redis `bodai:events` → `conversations`;
Session-Buddy → Akosha push; S3 → Akosha pull) and notes the corpus is
already flowing on `bodai.hooks.*` with `transcript_path` and `session_id`.
Phase 1's benchmark is the honest test of whether that repair worked.

**F-9 — The patterns to adopt are named, and their sources are external.**
Kit's published architecture gives the exact fusion formula — FTS
`ts_rank_cd` + vector cosine merged by RRF (k=60) — plus per-category
half-lives (sessions 5 d, decisions 90 d, preferences 365 d), cosine-0.92
hard dedup, cosine-0.55 edge promotion, and `dry_run=true` on destructive
operations. Basic Memory supplies the MCP behaviour-annotation model
(read-only / destructive / idempotent / open-world). MemPalace supplies the
benchmark discipline and the "closets are a ranking signal, never a gate"
rule — an index layer must never gate the primary store, or low-signal
indexes hide rows the primary store would have found.

---

## 4.5 Requirements

| ID | Title | Satisfied by | Repo |
|---|---|---|---|
| `REQ-FLEETMEM-001` | Fleet recall benchmark harness with a committed baseline | Phase 1 | mahavishnu |
| `REQ-FLEETMEM-002` | Rank fusion over lexical and vector channels in the semantic owner | Phase 2 | akosha |
| `REQ-FLEETMEM-003` | Per-category relevance half-life in ranking, not retention | Phase 3 | akosha, kit |
| `REQ-FLEETMEM-004` | MCP tool behaviour annotations across the fleet | Phase 4 | mcp-common |
| `REQ-FLEETMEM-005` | Multi-harness capture coverage for Codex and Cursor | Phase 5 | session-buddy |
| `REQ-FLEETMEM-006` | Reversible preview on memory projection writes | Phase 2 | akosha, session-buddy |

Declared in the frontmatter `requirements:` block, which is what
`scripts/audit_requirements.py` reads. Implementations mark themselves with
`# req: REQ-FLEETMEM-00N` (inline), `# Implements: REQ-FLEETMEM-00N`
(docstring) or `@pytest.mark.req(["REQ-FLEETMEM-00N"])` (test marker).

---

## 5. Implementation phases

### Phase 1: The recall benchmark harness

**Goal:** make recall measurable before changing anything that affects it.

**Why first:** retrofitting a benchmark after changing the retriever is how a
team ends up claiming a win it cannot prove. This phase needs no embeddings
and no corpus repair, so it runs **in parallel with the spine** rather than
behind it.

**Tasks:**

- [ ] Create `mahavishnu/benchmarks/recall/` with a dataset loader for
  LongMemEval (R@5, 500 questions) and LoCoMo (R@10), plus a MemBench
  slice if it runs within the time budget.
- [ ] Write a runner that queries the **live MCP surfaces** — not internal
      functions — so the harness measures what an agent actually gets:
      `mcp__akosha__akosha_search_all_systems`,
      `mcp__session-buddy__session_buddy_quick_search`,
      `mcp__akosha__akosha_search_code_patterns`, and the
      `mahavishnu_hybrid_search` reference surface.
- [ ] Record, per question: the query, the returned ids, the rank of the
      expected id (or a not-found marker), and the surface that answered.
      Commit the per-question files, not only the aggregates.
- [ ] Write `benchmarks/recall/RESULTS.md` with the baseline table
      (surface × dataset × R@k) and the exact reproduction command.
- [ ] Add a CI job with a **floor** per surface. The floor is set at the
      measured baseline; it is not aspirational.
- [ ] Capture the **pre-spine** baseline first if the corpus is still
      severed — that number is the control. After the spine lands, re-run and
      publish the delta.

**Exit criteria:** `RESULTS.md` exists with a committed baseline; the
harness runs end to end; a deliberately broken surface **fails** the floor.

#### Integration Contract

- **Triggered from:** `python -m benchmarks.recall.run --dataset all --publish`
  (CI job `.github/workflows/recall-benchmark.yml`, and manually). Entry
  point `mahavishnu/benchmarks/recall/run.py:main`.
- **Returns to / updates:** `mahavishnu/benchmarks/recall/results/<dataset>/<surface>/<run_id>.jsonl`
  and `mahavishnu/benchmarks/recall/RESULTS.md`. The baseline file is the
  only artefact that changes a gate; the per-question files are evidence.
- **Demonstrable by:** `python -m benchmarks.recall.run --dataset longmemeval --surface akosha_search_all_systems --limit 50`
  prints a per-question table and a recall figure; and
  `pytest mahavishnu/tests/benchmarks/test_recall_floor.py` fails when a
  surface's result set is emptied.
- **Rollback signal:** the CI job fails on `recall_floor_violated`, or the
  runner exits non-zero on `dataset_fetch_failed` — a harness that cannot
  fetch its dataset must fail loudly, never skip.
- **Observability added:** structured log lines `recall.run.started`,
  `recall.run.completed` (with surface, dataset, R@k) and a metric
  `mahavishnu.recall.at_k{surface,dataset,k}`; a `recall_benchmark` health
  feed entry on mahavishnu's `/health` reporting the last run's timestamp
  and floor.

---

### Phase 2: Rank fusion in the semantic owner, and previewable projection writes

**Goal:** give Akosha the two-channel retrieval it lacks, and make its
writes reversible.

**Depends on:** `akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md`
(Plan M) — the unified pgvector warm tier is the substrate this lands on.
FTS on the same table is a prerequisite for the lexical channel.

**Tasks — fusion:**

- [ ] Port mahavishnu's fusion shape into Akosha: a lexical channel
      (`ts_rank_cd`) and a vector channel (cosine) over the **same**
      pgvector table, merged by RRF.
- [ ] Use `ts_rank_cd`, not `ts_rank` — cover density is the better signal,
      and it is the form Kit publishes.
- [ ] Make RRF's `k` a named constant with a default of **60**, matching the
      published reference. Do not tune it silently; changing it changes the
      ranking and must show up in the Phase 1 benchmark delta.
- [ ] Apply the MemPalace rule as an invariant: **the lexical and vector
      channels are both always queried; neither gates the other.** A
      low-signal channel must never hide rows the other channel would
      return. Encode it as a test, not a comment.
- [ ] Expose the fusion mode on `akosha_search_all_systems` and
      `akosha_query_knowledge_graph` — as an explicit `mode` parameter
      (`vector` / `lexical` / `hybrid`), not a default flip. A silent
      default change alters every caller's results.

**Tasks — previewable writes:**

- [ ] Add `dry_run: bool = False` to `akosha_store_memory` and
      `akosha_batch_store_memories`. With `dry_run=true`, the tool performs
      the full validation and ranking work and returns the rows it *would*
      write, without writing them.
- [ ] Add the same flag to Session-Buddy's push path
      (`session_buddy/storage/akosha_sync.py`) so the producer can rehearse
      a batch against the live receiver.
- [ ] Make near-duplicate detection produce a **reversible draft** rather
      than a merge. A duplicate that is silently merged cannot be un-merged;
      a draft can be rejected. This mirrors Kit's cosine-0.92 hard-dedup /
      reversible-draft split and its `dry_run=true` on destructive
      operations.

**Exit criteria:** `akosha_search_all_systems` with `mode="hybrid"` returns
rows neither channel returns alone, verified by the Phase 1 harness; a
`dry_run=true` write returns a non-empty preview and the store's row count
is unchanged.

#### Integration Contract

- **Triggered from:** MCP `tools/call` on `akosha_search_all_systems` with
  `mode="hybrid"`, and on `akosha_store_memory` with `dry_run=true`.
  Entry points `akosha/akosha/mcp/tools/akosha_tools.py` and
  `akosha/akosha/mcp/tools/session_buddy_tools.py`.
- **Returns to / updates:** the unified pgvector warm table's
  `search_vector` column (populated for the lexical channel) and the
  `memories` rows the vector channel reads. A `dry_run` write updates
  **nothing**.
- **Demonstrable by:** `pytest akosha/tests/test_hybrid_fusion.py -k
  "rrf_merge or no_channel_gates"` — the second test asserts that a query
  matching only the lexical channel still returns rows, and vice versa;
  and `pytest akosha/tests/test_store_memory_dry_run.py` asserting the
  preview is non-empty and the row count is unchanged.
- **Rollback signal:** `akosha.fusion.fallback_to_single_channel` is
  logged when one channel errors and the tool degrades to the other —
  the same silent-degradation class the spine calls out. If that counter
  is non-zero over a run window, fusion is broken and the mode should
  revert to `vector`.
- **Observability added:** counters `akosha.fusion.queries`,
  `akosha.fusion.channel_hits{channel=lexical|vector|both}`,
  `akosha.fusion.channel_errors{channel}`; a
  `memory_projection_preview` metric on `dry_run` calls; a `dry_run` result
  carrying `preview_rows` and `would_write_rows`.

---

### Phase 3: Per-category relevance half-life

**Goal:** make ranking respect how fast a memory kind goes stale.

**Scope note — this is ranking, not retention.** A half-life reduces a
record's *score* as it ages. It never deletes anything. ADR 020 §8 keeps
correction and deletion with the semantic owner, and a retention policy
stays a separate, explicit decision. Conflating the two would let a ranking
tweak silently destroy operator history.

**Tasks:**

- [ ] Define the category → half-life table in one place, per ADR 020 §1
      (Oneiric owns shared configuration; Akosha and Kit consume it):
      | Category | Half-life | Rationale |
      |---|---|---|
      | sessions | 5 days | a transcript's value decays within a week |
      | decisions | 90 days | a decision holds until it is superseded |
      | preferences | 365 days | a preference is durable until corrected |
- [ ] Implement as a multiplicative score factor, `0.5 ** (age / half_life)`,
      applied **after** fusion and **before** any importance weighting.
      Document the ordering explicitly — the order changes results.
- [ ] Apply it in Akosha for derived records, and in Kit for
      operator-continuity records. Kit's published values are the reference;
      the table is shared, not forked per component.
- [ ] Record the half-life **id** and the computed factor on every returned
      row, so a score is explainable after the fact. An unexplainable score
      is indistinguishable from a bug.
- [ ] Add a `decay_policy` field to the memory-projection payload profile
      (`mcp_common/contracts.py`, `memory-projection/1.0.0`) so the policy
      travels with the record rather than being re-derived per consumer.

**Exit criteria:** the Phase 1 harness shows no regression on queries whose
answers are recent, and a measurable improvement on queries whose answers
are aged; every returned row carries its half-life id and factor.

#### Integration Contract

- **Triggered from:** every retrieval path that returns scored rows —
  `akosha_search_all_systems`, `akosha_query_knowledge_graph`,
  `session_buddy_quick_search` — and Kit's `recall`. Entry points are the
  retrieval functions themselves, so the factor is applied in one place.
- **Returns to / updates:** the scored result rows (`decay_factor`,
  `decay_policy_id`) and the shared half-life configuration consumed by
  Akosha and Kit.
- **Demonstrable by:** `pytest akosha/tests/test_relevance_decay.py -k
  "half_life_halves_score and order_is_decay_after_fusion"`, asserting that
  an item exactly one half-life old scores `0.5×` its fresh equivalent, and
  that the fusion-then-decay ordering is asserted rather than incidental.
- **Rollback signal:** `akosha.decay.factor_applied` counter diverges from
  the query count — the factor was skipped on some path. Divergence means
  ranking is inconsistent across paths, which is worse than no decay.
- **Observability added:** per-category counters
  `akosha.decay.applied{category}`; the `decay_factor` and
  `decay_policy_id` fields on every result row; a `recall_decay` health
  feed entry reporting the active policy table version.

---

### Phase 4: MCP tool behaviour annotations

**Goal:** let an agent pick a tool correctly without probing it.

**Why mcp-common owns this:** the fleet registers 178 + 227 + 39 tools
through a shared FastMCP base. One change in the registration helper
annotates every tool in every component. Six changes would drift.

**Tasks:**

- [ ] Define the annotation set in mcp-common — modelled on Basic Memory's
      and the MCP specification's `ToolAnnotations`:
      `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`.
- [ ] Populate them **declaratively**, at registration, from the tool's
      existing metadata — not from a hand-maintained per-tool table, which
      would rot exactly the way the fleet's dead `embedding_backend`
      selectors rotted (a selector that reads as live but selects nothing).
- [ ] Set sensible defaults for every tool: `readOnlyHint` default `false`,
      `destructiveHint` default `true`, `idempotentHint` default `false`,
      `openWorldHint` default `true`. **Fail toward caution**: an
      unannotated tool must be assumed to mutate.
- [ ] Add a checker that fails when a tool is served without annotations,
      so a new tool cannot ship unannotated. Wire it into
      `scripts/check_mcp_tool_surface.py`, which already audits the served
      surface against a snapshot.
- [ ] Cross-check against the fleet's own dead-config record
      (`mahavishnu/docs/plans/2026-11-05-config-that-nobody-reads.md`,
      REQ-DEAD-001/002/003): an annotation nobody reads is worse than none.
      The checker must assert the annotations reach the served schema, not
      merely that they were set in Python.

**Exit criteria:** every tool on every fleet server's `tools/list` carries
the four annotations; the checker fails on a deliberately unregistered
annotation.

#### Integration Contract

- **Triggered from:** server startup — the registration helper applies the
  annotations while building the tool registry. Entry point:
  mcp-common's FastMCP registration wrapper used by all servers.
- **Returns to / updates:** the served `tools/list` schema for every MCP
  server in the fleet. Nothing else mutates.
- **Demonstrable by:** `python scripts/check_mcp_tool_surface.py` reports
  zero unannotated tools across the fleet's servers, and
  `pytest mcp-common/tests/test_tool_annotations.py -k "defaults_fail_toward_caution"`
  asserts an unannotated default is `destructive=True`.
- **Rollback signal:** the checker reports unannotated tools — that means a
  registration path bypassed the helper. The fix is to route the path
  through the helper, never to relax the default.
- **Observability added:** a `tool_annotations` health feed entry per server
  reporting annotated-count / total-count; a `mcp_common.tool.annotation_missing`
  counter.

---

### Phase 5: Multi-harness capture — Codex CLI and Cursor

**Goal:** capture the sessions the fleet is actually run in.

**Depends on:** the spine's corpus repair. The transport already exists
(`bodai.hooks.*` on Redis carrying `transcript_path` and `session_id`);
this phase adds the **producers** for the two harnesses we lack.

**Tasks:**

- [ ] Add a Codex CLI hook set mirroring Session-Buddy's existing events
      (`SessionStart`, `SessionEnd`, `PreCompact`) into
      `session_buddy/hooks/`. Codex's transcript location differs from
      Claude Code's — resolve it from the hook payload, not a hardcoded
      path.
- [ ] Add a Cursor IDE hook set, including a transcript snapshot before
      compaction. Cursor's session files are not Claude Code JSONL; the
      reader must handle its format explicitly rather than assuming.
- [ ] Publish to the same `bodai.hooks.*` channels the spine's decoder
      already consumes, so **no new transport is created**.
- [ ] Keep the capture contract narrow: the hook writes `transcript_path`,
      `session_id` and the harness identity. It does **not** parse or
      store content — that is the spine's corpus path, and Session-Buddy
      remains the capture owner under ADR 020 §1.
- [ ] Record harness identity in the projection payload so a recall can be
      filtered by origin. A session from Cursor and a session from Claude
      Code are different evidence.

**Exit criteria:** a Codex CLI session and a Cursor session each appear in
the corpus with a non-null `source_type` and a harness tag; the Phase 1
harness can answer a query whose answer exists only in a Codex session.

#### Integration Contract

- **Triggered from:** the Codex CLI and Cursor hook entry points, invoked by
  the host harness. Entry points `session_buddy/hooks/<harness>/` and the
  publisher that writes to `bodai.hooks.*`.
- **Returns to / updates:** the `bodai:events` Redis stream (the channel the
  spine's decoder reads) and, downstream, `conversations_v2` via the
  spine's corpus path. This phase writes to the stream only.
- **Demonstrable by:** run one Codex CLI session and one Cursor session,
  then `pytest session-buddy/tests/integration/test_capture_harness.py -k
  "codex or cursor"` asserting the event arrives with `transcript_path`,
  `session_id` and `harness` set.
- **Rollback signal:** `session_buddy.capture.events_published{channel}`
  flat across a session window — the hook registered but never fired. A
  hook that does not fire is invisible; the counter is the detector.
- **Observability added:** counters
  `session_buddy.capture.events_published{harness}`,
  `session_buddy.capture.publish_failures{harness}`; a `capture_coverage`
  health feed entry listing the harnesses with hooks wired and the last
  event time per harness.

---

## 6. Required code changes

**mahavishnu**

- `mahavishnu/benchmarks/recall/__init__.py` *(new)*
- `mahavishnu/benchmarks/recall/datasets.py` *(new)* — LongMemEval, LoCoMo, MemBench loaders
- `mahavishnu/benchmarks/recall/surfaces.py` *(new)* — MCP surface adapters
- `mahavishnu/benchmarks/recall/run.py` *(new)* — runner, per-question records, aggregates
- `mahavishnu/benchmarks/recall/RESULTS.md` *(new)* — committed baseline
- `mahavishnu/tests/benchmarks/test_recall_floor.py` *(new)*
- `mahavishnu/scripts/check_mcp_tool_surface.py` — extend to assert annotations

**akosha**

- `akosha/akosha/processing/fusion.py` *(new)* — RRF merge, ported in shape from `mahavishnu/core/vector_search.py`
- `akosha/akosha/processing/decay.py` *(new)* — half-life policy application
- `akosha/akosha/storage/pgvector_warm_store.py` — populate and query `search_vector` (lexical channel)
- `akosha/akosha/mcp/tools/akosha_tools.py` — `mode` parameter on the search tools
- `akosha/akosha/mcp/tools/session_buddy_tools.py` — `dry_run` on the store tools
- `akosha/tests/test_hybrid_fusion.py` *(new)*
- `akosha/tests/test_relevance_decay.py` *(new)*
- `akosha/tests/test_store_memory_dry_run.py` *(new)*

**session-buddy**

- `session_buddy/hooks/codex/` *(new)* — Codex CLI hook set
- `session_buddy/hooks/cursor/` *(new)* — Cursor IDE hook set
- `session_buddy/storage/akosha_sync.py` — `dry_run` on the push path
- `session-buddy/tests/integration/test_capture_harness.py` *(new)*

**mcp-common**

- `mcp_common/` registration helper — apply the four `ToolAnnotations` with caution-first defaults
- `mcp_common/contracts.py` — add `decay_policy` to the `memory-projection/1.0.0` payload profile
- `mcp-common/tests/test_tool_annotations.py` *(new)*

**kit**

- Kit's `recall` — apply the shared half-life table; carry `decay_policy_id` on results

## 7. Validation matrix

| Check | Expected | Evidence |
|---|---|---|
| `python -m benchmarks.recall.run --dataset all --publish` | Baseline table for every surface, per-question files committed | `benchmarks/recall/RESULTS.md` |
| `pytest mahavishnu/tests/benchmarks/test_recall_floor.py` | Pass at baseline; **fail** when a surface's results are emptied | test output |
| `pytest akosha/tests/test_hybrid_fusion.py` | Fusion merges both channels; neither gates the other | test output |
| `pytest akosha/tests/test_relevance_decay.py` | One half-life old ⇒ `0.5×`; ordering fusion→decay asserted | test output |
| `pytest akosha/tests/test_store_memory_dry_run.py` | Preview non-empty; row count unchanged | test output |
| `python scripts/check_mcp_tool_surface.py` | Zero unannotated tools across the fleet | script output |
| `pytest mcp-common/tests/test_tool_annotations.py` | Unannotated default is `destructive=True` | test output |
| `pytest session-buddy/tests/integration/test_capture_harness.py` | Codex and Cursor sessions reach `bodai.hooks.*` with `harness` set | test output |
| `akosha_search_all_systems(mode="hybrid")` | Returns rows neither single channel returns | Phase 1 harness delta |
| Recall floor after the spine lands | Delta vs the pre-spine control published | `RESULTS.md` revision history |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The benchmark's dataset fetch fails and the job silently skips | Medium | The runner exits non-zero on `dataset_fetch_failed`. A harness that cannot fetch must fail, never skip. |
| The floor is set above the measured baseline, making CI permanently red | Medium | The floor is set *from* the measured baseline, in the same commit that publishes it. No aspirational floors. |
| Phase 2 lands before Plan M's unified pgvector tier exists | Medium | Phase 2 is `blocks_on` Plan M. Fusion needs one indexed table with both channels; a split table cannot fuse. |
| Fusion silently degrades to one channel and nobody notices | Medium | `akosha.fusion.channel_errors` counter plus a Phase 1 harness check that hybrid results differ from single-channel results. |
| The `mode` parameter's default changes and alters every caller's results | Low | The default stays `vector`; the change is explicit and opt-in. The Phase 1 harness catches unintended shifts. |
| Half-life decay is read as a retention policy and something deletes records | Medium | The requirement is titled "in ranking, not retention"; decay writes no deletion. A test asserts no record is removed by a decay pass. |
| Decay penalises a still-relevant old decision | Medium | The decisions half-life is 90 days, not 5; the Phase 1 harness gates the floor so a regression is visible. |
| Annotations drift into a hand-maintained table and rot | Medium | Annotations are derived at registration from existing metadata, and the checker fails on any unannotated tool. |
| Unannotated tools are assumed safe by a client that defaults `readOnlyHint=false` correctly but `destructiveHint` optimistically | Low | Defaults fail toward caution: unannotated ⇒ mutating. |
| Codex/Cursor hook registers but never fires | Medium | `capture.events_published{harness}` flat over a window is the detector. A registered-but-dead hook is otherwise invisible. |
| The harness measures the wrong thing — fast, irrelevant results | Medium | The harness measures R@k against a labelled dataset, not latency. Latency is a separate metric. |
| This plan competes with the spine for the same engineers | Medium | Phase 1 is deliberately parallel to the spine and needs no embeddings. Phase 2+ is downstream. |

## 9. Decision rule

**This plan is done when a recall number exists, is committed, and moves for
a reason.** Concretely:

1. `benchmarks/recall/RESULTS.md` exists with a committed baseline for the
   Akosha cross-system surface and the Session-Buddy conversation surface,
   and `pytest mahavishnu/tests/benchmarks/test_recall_floor.py` runs in CI.
2. Akosha's `mode="hybrid"` returns rows neither channel returns alone, and
   the Phase 1 harness shows a non-negative delta against the baseline.
3. Every tool the fleet serves carries the four behaviour annotations, and
   the surface checker fails on an unannotated one.
4. A Codex session and a Cursor session both reach the corpus with harness
   identity set.
5. The pre-spine control and the post-spine result are both published, so
   the spine's corpus repair has a measured effect on recall.

**Scope pressure — what to cut, in order:** the MemBench slice (Phase 1) →
the Cursor hook set (Phase 5, Codex first) → the edge-promotion threshold
(cosine 0.55) → the `openWorldHint` annotation (the other three carry the
safety value). **What must never be cut:** the benchmark and its committed
baseline (Phase 1), and the caution-first annotation defaults (Phase 4).
A retriever whose quality cannot be measured is a retriever that cannot be
improved, and an annotation scheme that defaults to optimistic is a
correctness bug with extra steps.

---

## References

- `mahavishnu/docs/adr/020-bodai-ecosystem-memory-architecture.md` — ownership model, promotion path, federated retrieval (§6), system observability (§7), correction and deletion (§8). **Authoritative.**
- `mahavishnu/docs/plans/2026-11-19-fleet-standardisation.md` — the fleet spine this plan follows.
- `akosha/docs/plans/2026-11-17-unified-pgvector-warm-tier.md` — the substrate Phase 2 lands on.
- `session-buddy/docs/plans/2026-11-06-conversation-transcript-ingestion.md` — owns Session-Buddy's RRF; Phase 1 scores it.
- `session-buddy/docs/plans/2026-11-06-fleet-embedding-width-768.md` — embedding mechanics (width superseded).
- `mahavishnu/docs/plans/2026-11-05-config-that-nobody-reads.md` — REQ-DEAD-001/002/003; the reason Phase 4 asserts reachability, not just presence.
- `mahavishnu/core/vector_search.py` — the reference fusion implementation Phase 2 ports.
- `session_buddy/memory/causal.py` — the existing decay primitive Phase 3 builds on.
- `docs/decisions/wire-up-contract.md` — the policy the Integration Contract blocks implement.
- `docs/plans/TEMPLATE.md` — the template this plan follows.
