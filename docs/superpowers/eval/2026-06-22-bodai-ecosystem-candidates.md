# Bodai Ecosystem Candidate Evaluation

**Date**: 2026-06-22
**Evaluator**: Claude (MiniMax M3), Bodai ecosystem triage
**Trigger**: 20 candidate projects/sites compiled with FOMO appetite, requested as parallel evaluation
**Scope**: Triage all 20 → deep-dive 5 high-fit survivors → recommendations
**Method**: Triage with web fetches + parallel research agents; 5 deep-dives in parallel

______________________________________________________________________

## Executive Summary

Of 20 candidate projects, **15 were triaged out** as off-topic, redundant, or commentary. The 5 deep-dive survivors cluster around three Bodai gaps: **code-intelligence memory**, **vectorless document retrieval**, and **self-hosted observability**. Two more (Emdash, Keystone) are *adjacent* to existing components rather than gaps.

| Project | Fit | Tier | Recommended action |
|---|---:|---|---|
| **OpenObserve** | **72/100** | 🟢 Investigate (POC) | Add as 3rd OTel backend option alongside DuckDB/Postgres; 2-3 day POC |
| **Emdash** | **62/100** | 🟢 Borrow patterns + client integration | Path A (Emdash→Mahavishnu provider shim, M) + Path B (`mahavishnu repo diff`/`pr`, S); skip "Emdash as pool" |
| **PageIndex** | **52/100** | 🟡 Niche spike | 2-day spike with 3 sample PDFs; gate on cost \<$0.50/doc, latency p95 \<15s |
| **Graphify** | **42/100** | 🟡 Narrow prototype | Half-day MCP-config inventory prototype; decline if it surfaces nothing new |
| **Keystone** | **38/100** | 🔴 Pilot only, read-side | Throwaway-repo pilot; **do not** make write-side authority; borrow `keystone_show` MCP pattern |

**Key takeaway**: No candidate is a slam-dunk "adopt wholesale." Three warrant real effort (OpenObserve, Emdash-as-client, PageIndex spike). Two are concrete "decline with a 1-day experiment" (Graphify, Keystone).

______________________________________________________________________

## 1. Triage Results (all 20)

| # | Project | URL | Triage | Verdict |
|---|---|---|---|---|
| 1 | **Keystone** | https://www.tacoda.dev/keystone/ | Agent harness with `.claude/skills/` projection, MCP `keystone_show` server, web dashboard. | 🟡 Adjacent — deep-dive (38/100) |
| 2 | **Milvus "7 best Claude Code context tools"** | https://milvusio.medium.com/... | Article, not a project. | 📰 Reference only |
| 3 | **"Ghost — a database for our time"** | https://levelup.gitconnected.com/... | Article about a database. | 📰 Reference only |
| 4 | **"Week 1-5 Open Source GitHub Repos"** | https://vijayasekhar-deepak.medium.com/... | Roundup article. | 📰 Reference only |
| 5 | **claude-mem** | https://github.com/thedotmack/claude-mem | Node.js persistent memory compression, v13.4.0. Overlaps with Session-Buddy memory. | 🟡 Adjacent to Session-Buddy; skip deep-dive (covered by Graphify/PageIndex memory tier) |
| 6 | **claude-memory-compiler** | https://github.com/coleam00/claude-memory-compiler | Personal KB from Claude Code conversations via Agent SDK. Overlaps with Session-Buddy. | 🟡 Adjacent to Session-Buddy; skip deep-dive |
| 7 | **Repomix** | https://github.com/yamadashy/repomix | Codebase packer (Node). Likely used by some agents already. | ✅ Probably already-used utility |
| 8 | **GSD / get-shit-done** | https://github.com/gsd-build/get-shit-done | Workflow planner. **Repo moved to `open-gsd/gsd-core`.** Partial overlap with our plan-then-execute workflow. | 🟡 Adjacent; moved-repo signal is yellow flag |
| 9 | **Emdash** | https://github.com/generalaction/emdash | Desktop app for parallel coding agents in worktrees. Direct overlap with Mahavishnu pools. | 🟡 Adjacent — deep-dive (62/100) |
| 10 | **Graphify** | https://github.com/safishamsi/graphify | YC S26 "Memory Layer" — code graph for AI agents, multimodal ingest (PDF/image/video/MCP configs). | 🟢 High fit — deep-dive (42/100) |
| 11 | **PageIndex** | https://github.com/VectifyAI/PageIndex | Vectorless reasoning-RAG via tree search. | 🟢 High fit — deep-dive (52/100) |
| 12 | **crewAI** | https://github.com/crewAIInc/crewAI | Multi-agent framework. **Already evaluated in `LIBRARY_EVALUATION_2025.md` — recommendation: deprecate in favor of LangGraph.** | ✅ Already-decided |
| 13 | **Unsloth** | https://github.com/unslothai/unsloth | LLM fine-tuning. Off-topic for orchestrator. | 🔴 Off-topic |
| 14 | **OpenObserve** | https://github.com/openobserve/openobserve | Open-source Datadog alt: logs/metrics/traces/RUM, S3-backed, 140× cheaper storage. | 🟢 High fit — deep-dive (72/100) |
| 15 | **"Prompt for senior-dev Python"** | https://levelup.gitconnected.com/... | Article about a prompt. | 📰 Reference only |
| 16 | **Arbor** (project page) | https://ruc-nlpir.github.io/Arbor/ | Autonomous research agent (hypothesis tree) for ML. | 🔴 Off-topic (academic ML) |
| 17 | **Arbor** (repo) | https://github.com/RUC-NLPIR/Arbor | Same as #16. | 🔴 Off-topic (duplicate URL) |
| 18 | **Ray** (repo) | https://github.com/ray-project/ray | Distributed Python compute. Massive operational complexity; we have pools. | 🔴 Redundant with pools |
| 19 | **Ray** (docs) | https://docs.ray.io/en/latest/ | Same as #18. | 🔴 Off-topic (duplicate URL) |
| 20 | **Firecrawl pricing** | https://www.firecrawl.dev/pricing | Commercial web crawling API. Just deferred crawl4ai; commercial route = low fit. | 🔴 Off-strategy |
| 21 | **"Production agent harness"** (article) | https://licaomeng.medium.com/... | Article about building an agent pipeline. | 📰 Reference only |

**Net**: 5 deep-dive survivors (Keystone, Emdash, Graphify, PageIndex, OpenObserve). 15 triaged out.

______________________________________________________________________

## 2. Deep-Dive Evaluations

### 2.1 OpenObserve — 72/100 🟢

**What it is**: Self-hostable observability platform (Rust + TS/Vue). Ingests logs, metrics, traces, RUM into a single binary, stores as Parquet on S3, serves via SQL (logs/traces) + PromQL (metrics).

**Why it fits Bodai**:

- **OTel-native ingestion** — drop-in target for `mahavishnu/ingesters/otel_ingester.py`. Zero protocol translation.
- **140× cheaper storage** via Parquet + S3 columnar format — meaningful cost lever at scale.
- **Multi-protocol fan-in** (OTLP, Prom, Loki, Fluent Bit, Vector, Kinesis, Syslog) — future-proofs ingest.
- **SQL query layer** — aligns with our DuckDB/SQL posture; lower learning curve than KQL/Lucene.
- **Production-grade** — 19.4k stars, 206 releases, v0.91.0 today, ~weekly stable cadence, PB-scale production users.

**Cons / risks**:

- **AGPL-3.0** — copyleft on network-accessible use. Mitigated by using as unmodified external service (no AGPL trigger).
- **Pre-1.0** (v0.91) — minor versions can break APIs/configs/dashboards.
- **No native vector search** — not a substitute for Akosha's embeddings; pgvector stays for that.
- **HA = 4-service deploy** (O2 + PostgreSQL + NATS + S3/MinIO). "Single binary" marketing is dev/POC only.
- **Enterprise SSO/audit/BAA paywalled** — OSS has RBAC but no SSO.

**Integration shape**:

- **Complement, do not replace.** Keep DuckDB (zero-dep dev) and pgvector (semantic search); add `openobserve` as 3rd backend option. Selection via `MAHAVISHNU_OTEL_BACKEND=duckdb|postgres|openobserve`.

**Effort**: M (Medium) total — POC (S, 1-2 days) → production deploy (M, ~1 week) → optional Grafana datasource consolidation (L, 2-4 weeks, optional).

**Recommended next step**: Run the docker-run POC. Verify OTel end-to-end through `otel_ingester.py` with new `OpenObserveBackend` shim. Measure resource footprint at 1k spans/sec for 1 hour. Decision memo in `docs/plans/openobserve-poc.md`. **No production code merged until go-decision.**

______________________________________________________________________

### 2.2 Emdash — 62/100 🟢 (with conditions)

**What it is**: Cross-platform Electron desktop app (Apache-2.0, YC W26, General Action Inc.). Runs multiple AI coding agents in parallel, each in its own Git worktree. Supports 31 CLI agent providers (Claude Code, Codex, OpenCode, Gemini, Amp, Cursor, etc.). Linear/GitHub/Jira/GitLab/Asana/Featurebase/Monday/Forgejo/Plain integration. Local-first SQLite state, SSH/SFTP remote projects.

**Why it fits Bodai**:

- Solves a real UX problem Mahavishnu **under-serves**: humans want to *see* what each parallel agent did, review diffs, click merge.
- 31-provider breadth is unmatched; Mahavishnu is MiniMax/cloud-API centric.
- Excellent worktree ergonomics (`.emdash/worktrees/<project>/<branch>`).
- SSH/SFTP remote projects — keep code/build on a beefy server, drive from the laptop. Mahavishnu's K8s pool covers scale but not this.

**Why it doesn't fit as a pool**:

- Wrong deployment shape — desktop, no headless/server mode, no CI deployment.
- Single-user, local-first by design — no shared memory (Session-Buddy), no Dhara persistence.
- MCP *consumer*, not MCP *server* — integrates with external MCP servers but doesn't expose Mahavishnu's tools.
- No routing/scaling primitives (no `least_loaded`, no K8s HPA).
- Electron memory/CPU footprint inappropriate for embedding inside another orchestrator's worker.

**Cons / risks**:

- YC-backed productized offering — roadmap owned by General Action, Inc.
- Forking would be a constant maintenance tax.

**Integration shape — three options ranked**:

1. **Emdash as a CLIENT of Mahavishnu (best)**: A thin `mahavishnu-emdash-bridge` CLI that calls `pool_route_execute` and streams progress back over a PTY-compatible interface. Register as a provider in Emdash's 31-CLI registry. Users get Mahavishnu's routing/observability/memory aggregation + Emdash's UI/review workflow. **Effort: M**.
1. **Borrow Emdash's patterns (cheap)**: Implement `mahavishnu repo diff <worktree-id>` + `mahavishnu repo pr create <worktree-id> --fill` in `mahavishnu/cli/`. `mahavishnu ingest issue --from <tracker>` mirroring `content_ingester.py` shape. Document local-first single-machine pool pattern. **Effort: S–M, scattered**.
1. **Emdash as a MahavishnuPool implementation (skip)**: Would require extracting the git-worktree + agent-spawn + diff-render core from Electron and re-hosting as a Node CLI. **Effort: L. Recommendation: NO.**

**Recommended next step**: Spike Path A (1 week) + Path B (1 week) = 2-week scoped commitment. After spike, evaluate full M-scope (A+B+C+D+F) vs. stop at B as standalone QoL improvement.

______________________________________________________________________

### 2.3 PageIndex — 52/100 🟡 (niche)

**What it is**: Vectorless reasoning-based RAG. Builds a hierarchical TOC tree of long documents, uses LLM reasoning to walk the tree at query time. No embeddings, no vector DB, no chunking. Inspired by AlphaGo. Self-hostable. Has MCP server (`pageindex-mcp`) and Cloud chat.

**Why it fits Bodai**:

- **MIT-licensed core + MCP server.** Zero licensing friction for control-plane-first internal product.
- **Best-in-class explainability for long-doc QA** — returns explicit page/section references (useful when Crackerjack agents need to cite a regulatory clause).
- **No vector DB to operate** — tree JSON in Dhara or local FS is enough; one less operational dependency than pgvector.
- **MCP-first delivery matches our posture** — `pageindex-mcp` is HTTP-transport + Bearer auth, same shape as Akosha/Crackerjack/Session-Buddy.
- **Tracks with our deferred-crawl4ai decision** — PageIndex also defers content-acquisition complexity (no headless browser needed at query time).

**Why it doesn't fit broadly**:

- **Cost**: Multi-call LLM reasoning per query is 10–100× more expensive than embedding cosine search. High-QPS workloads (logs, traces) are the wrong fit.
- **Latency**: Multi-step agentic search is seconds-to-tens-of-seconds per query. Vector ANN is sub-100ms. Breaks real-time WebSocket UX (port 8690).
- **Single-source benchmark claim** — 98.7% on FinanceBench is from the vendor's own Mafin 2.5 product; no third-party replication.
- **No formal releases on Python core** — 296 commits but zero SemVer tags. Must pin to commit SHA — ugly for `pyproject.toml` and lockfile hygiene.
- **PyPDF-only, no OCR in self-host** — scanned PDFs (a large fraction of regulatory/legal corpora) require the cloud tier. Locks highest-value use case behind paid product.
- **No EPUB support** — our existing content ingester handles EPUB; PageIndex doesn't.
- **Poor fit for OTel trace ingestion** — flat event streams have no TOC/chapter structure to navigate.

**Integration shape — sidecar index, not replacement**:

- Add `retrieval_mode: vector | tree` config knob. PDFs and EPUBs (where structure exists) get PageIndex tree generation alongside existing embeddings. Akosha stores both representations; `mcp__mahavishnu__ingest_content` returns the union.
- **Default for long PDFs (>50 pages), regulatory, legal, financial docs.**
- Tree index stored in **Dhara** (not Akosha — tree JSON is structured state, not memory). Add `tree_index_id` field to `IngestionResult.metadata`.
- Keep vector path as default for non-PDF and short content.

**Effort**: M (10–12 days, one engineer, one PR cycle).

**Recommended next step**: 2-day spike with 3 sample PDFs (10-K excerpt, regulatory filing, technical manual). Record: tree depth, node count, indexing LLM cost, query latency, accuracy vs. known answer key. Gate on cost \<$0.50/doc (self-host viability), latency p95 \<15s, accuracy acceptable. Draft `docs/specs/pageindex-integration.md` in parallel. If no-go, document in `docs/decisions/rejected-pageindex.md` (same pattern as `docs/specs/defer-crawl4ai.md`).

______________________________________________________________________

### 2.4 Graphify — 42/100 🟡 (narrow only)

**What it is**: Claude Code skill + CLI (`graphify`). Ingests mixed-content folders (code, docs, PDFs, images, videos, MCP configs, package manifests) and produces a persistent, locally-stored knowledge graph (`graph.json` + `graph.html` + `GRAPH_REPORT.md`) with confidence-tagged edges (EXTRACTED / INFERRED / AMBIGUOUS). Tree-sitter for code AST (36 languages), Claude/Gemini/Ollama for semantic extraction on non-code. Local-first, NetworkX + Leiden community detection, exports to Obsidian / Neo4j / Gephi / MCP stdio.

**Maturity signals**: MIT, YC S26, 70.8k stars, 7.1k forks, 140 releases, v0.8.45 (2026-06-22), 803 commits, 100% Python, single-author `safishamsi`. Companion product **Penpax** (graphifylabs.ai) is the commercial funnel; OSS is the developer-acquisition channel.

**Why it fits Bodai (narrowly)**:

- **Multimodal ingestion is genuinely novel for Bodai**: PDFs, images, video, MCP configs, Terraform, Salesforce Apex — none first-class in Akosha/Session-Buddy today.
- **MCP-config awareness** — parses `.mcp.json`, `claude_desktop_config.json`. Could power cross-repo MCP-server inventorying that doesn't exist today. **Bodai uses MCP everywhere.**
- **Confidence tags (EXTRACTED/INFERRED/AMBIGUOUS)** — the kind of provenance Akosha's `analyze_imports`/`find_function_usage` lack.
- MIT + 100% Python + uv-managed — zero friction; matches Python 3.13/uv stack.
- Local-first + no telemetry — matches privacy posture.

**Why it doesn't fit broadly**:

- **Direct overlap with Session-Buddy's code-graph tools**: `code_ingest_directory`, `code_call_chain`, `code_impact_analysis`, `code_get_symbol_graph` already exist. Adding Graphify creates two pipelines and two truth sources.
- **Single-author solo project despite YC signal** — temporary `graphifyy` PyPI name (because `graphify` is "being reclaimed") is a yellow flag; commercial-funnel concern.
- **Backend sprawl** — even with local-first code, every non-code artifact hits the model API (Gemini → Kimi → Claude → OpenAI → ...). For internal-first posture, larger leak surface than current local-only ingesters.
- **No hooks into Bodai's MCP layer today** — Graphify's `--mcp` export is a stdio server; integrating with `mcp_test_connection` / `mcp_list_tools` / `mcp_get_metrics` requires glue that doesn't exist.

**Integration shape**:

1. **Akosha ingester pipeline** (M effort) — ship `graphifyy` as optional dep; new `mahavishnu/ingesters/graphify_ingester.py` calls `graphify <path> --update --json` and pipes into Akosha; new MCP tool `mcp__mahavishnu__ingest_graphify <repo_path>`. Confidence-tag passthrough.
1. **Mahavishnu CLI utility** (S effort) — `mahavishnu code graphify <path>` wrapper for orchestrators.
1. **Decline** (zero effort) — multimodal/MCP-config gap is real but could be filled in-tree by ~200 LOC of `ingesters/content_ingester.py` extensions.

**Recommended next step** (more conservative than full Akosha integration):

- **Half-day prototype**: write `scripts/eval/graphify_mcp_inventory.py` that runs `graphify .` against the Mahavishnu repo, emits markdown listing every MCP server declared in `.mcp.json`/`pyproject.toml [tool.mcp]`, plus every non-code artifact (PDFs, images) under `docs/`.
- **If the report surfaces anything new** (MCP servers or docs Bodai doesn't already know about): promote to one-file ingester at `mahavishnu/ingesters/mcp_inventory.py`. Otherwise decline entirely and note in `.claude/decisions/`: *"Graphify evaluated 2026-06-22; declined because Session-Buddy code-graph tools + existing ingesters cover Bodai's actual needs, and the multimodal/MCP-config gap is small enough to fill in-tree."*

______________________________________________________________________

### 2.5 Keystone — 38/100 🔴 (pilot only, read-side)

**What it is**: Agent harness framework — single Go binary (`brew install tacoda/tap/keystone`). Authors versioned markdown harness into every repo at `.keystone/harness/`, projects it into host agent surfaces (Claude Code, Cursor, Codex), exposes CLI + MCP server + localhost dashboard. v2.4.1 is "read-surface parity" — composition primitives (concern, include, tags, severity from v2.3.0) now available via both MCP and web dashboard. MIT.

**Composition model (concrete)**:

- **`concern`** — leaf primitive at `.keystone/harness/concerns/<id>.md` (frontmatter + `tools`/`tags`/`host_triggers`/`triggers`). Cannot declare `includes:` — depth-1 by construction.
- **`includes: [<concern-id>, ...]`** on host primitives — union-merges list fields; host-wins scalars.
- **`tags:`** orthogonal taxonomy, kebab-case, enforced by `keystone lint`. Concern tags propagate.
- **`severity:`** (sensor) — `must` (blocks), `should` (warning), `may` (informational).

**MCP `keystone_show` (v2.4.1)**: single-call composed view + forward/reverse cross-refs (`includes`/`included_by`, `traces`/`traced_by`, host hooks, tags, model, severity, phase). Saves N follow-up `keystone_get_primitive` calls. **The right MCP shape** — pattern worth borrowing for Mahavishnu regardless of adoption.

**Why it partially fits Bodai**:

- **Clean composition model** solves the "rule duplicated across 4 reviewer agents" problem.
- **Cross-repo vendoring with pinned, hash-verified policies** (`[<host>/]<owner>/<repo>[@<version>]`). Genuinely useful for org-level rule distribution.
- MIT + single binary + read-only surfaces — fits Bodai's "internal-first, MCP-first, control-plane scope" posture.

**Why it largely doesn't fit**:

- **Doubles the rules layer.** Every Bodai rule would need to exist in (a) Bodai memory (Session-Buddy / Akosha) and (b) Keystone primitives. CLAUDE.md / AGENTS.md collision is unavoidable.
- **Skill projection collision.** `keystone init` writes `.claude/skills/keystone-*`. Bodai already has a curated skills inventory. Two skill namespaces to maintain.
- **Additive ambient load** — 23,547 tokens across 6 ports loaded at session start. Bodai's context budget is already non-trivial.
- **Shape mismatch is fundamental** — Keystone's primitives are *file-level* (markdown + frontmatter); Bodai's cross-repo sharing is *behavioral* (Session-Buddy memory + Akosha semantic recall). Keystone could be a downstream file-format target, but that's translation overhead without removing the underlying duplication.
- **Schema churn pre-3.0** — v2.3.0 broke composition; v2.4.1 is additive. `keystone migrate up` is required for existing repos.
- **Single-vendor risk + unknown community size** — no public Discord / forum. If `tacoda` pauses, Bodai inherits a per-repo maintenance burden.

**Integration shape — narrow read-side pilot only**:

- **DO NOT** promote Keystone to write-side authority for Bodai rules.
- **DO** run `keystone init` in one throwaway Bodai repo (suggest `session-buddy` — small surface, already memory-rich). Capture overlap count, ambient-load delta, dashboard utility score.
- **DO** consider borrowing the `keystone_show` MCP shape for Mahavishnu's own primitive composability story.

**Effort**: S in code, L in coordination cost if promoted to authority.

**Recommended next step**: Read-side pilot only. Run `brew install tacoda/tap/keystone && keystone init` in a throwaway Bodai repo. Report back with overlap count, ambient-load delta, dashboard utility score, and a binary decision on whether to integrate `keystone_show` as a Mahavishnu MCP bridge (read-only consumer) or skip entirely.

______________________________________________________________________

## 3. Cross-Cutting Recommendations

### 3.1 What to invest in

1. **OpenObserve POC** — highest fit (72/100), addresses a real cost/operational concern (Parquet/S3 retention), OTLP-native so the protocol work is zero.
1. **Emdash as a client of Mahavishnu** (Path A) — addresses a genuine UX gap (human review of parallel-agent diffs). Apache-2.0, YC-backed, the 31-provider registry is the right extension point.
1. **PageIndex 2-day spike** — narrow but well-defined use case (long structured PDF QA). Spike with hard go/no-go criteria prevents sunk-cost commitment.

### 3.2 What to decline (with experiments to prove it)

4. **Graphify broad integration** — narrow MCP-config-inventory prototype only. Decline if it surfaces nothing new. The Session-Buddy code-graph tools + existing ingesters likely cover actual needs.
1. **Keystone write-side authority** — shape mismatch is too large. Read-side pilot only; borrow the `keystone_show` MCP pattern regardless of adoption decision.

### 3.3 What to acknowledge and move on

6. **claude-mem / claude-memory-compiler** — both overlap with Session-Buddy; not deep-dived. If the user wants memory-tool FOMO addressed, spin a separate evaluation of "memory compiler for Bodai" using the patterns from these two.
1. **crewAI** — already decided in `LIBRARY_EVALUATION_2025.md` (deprecate in favor of LangGraph). No re-evaluation needed.
1. **Repomix** — likely already used by some agents. No action.
1. **GSD** — moved-repo signal is a yellow flag. If plan-then-execute workflow needs enhancement, look at GSD's patterns in-tree rather than adopting the framework.
1. **Ray / Unsloth / Firecrawl / Arbor** — off-topic or off-strategy. No action.
1. **5 Medium articles** — kept as reference reading. If user wants a follow-up "what did we learn from these articles" summary, can be a separate ask.

### 3.4 What to update in the repo

- This report committed to `docs/superpowers/eval/2026-06-22-bodai-ecosystem-candidates.md`.
- If OpenObserve POC proceeds, draft `docs/plans/openobserve-poc.md` with storage cost comparison + lock-in assessment.
- If PageIndex spike proceeds, draft `docs/specs/pageindex-integration.md` (schema, MCP tool contract, cost model, non-goals).
- If Emdash bridge proceeds, capture decision in `docs/adr/` (architecture-level — affects pool strategy) and `.claude/decisions/` (operational patterns from Emdash worth borrowing).
- If Keystone is declined after pilot, write `docs/decisions/rejected-keystone.md` so the next person doesn't repeat the experiment.

______________________________________________________________________

## 4. Decision Gates

| Decision | Gate criteria | Owner |
|---|---|---|
| OpenObserve POC → production | OTel end-to-end works; resource footprint acceptable; storage cost < current | Mahavishnu engineer + Crackerjack review |
| Emdash-as-client (Path A) | Bridge shim works end-to-end against a local `MahavishnuPool`; Emdash upstream responsive to provider-registry entry | Mahavishnu CLI engineer |
| Emdash borrow (Path B) | `mahavishnu repo diff` + `pr create` land with tests; `docs/CLI_REFERENCE.md` updated | Mahavishnu CLI engineer |
| PageIndex adoption | Spike cost \<$0.50/doc; latency p95 \<15s; tree quality acceptable | Mahavishnu ingest engineer |
| Graphify narrow prototype | MCP-config inventory surfaces something new in 4 hours of effort | Mahavishnu engineer |
| Keystone read-side pilot | Overlap count, ambient-load delta, dashboard utility score in `.claude/decisions/` | Any Bodai engineer |

______________________________________________________________________

## 5. Source URLs (verified 2026-06-22)

### Deep-dive sources

- Keystone: https://www.tacoda.dev/keystone/ · https://github.com/tacoda/keystone
- Emdash: https://github.com/generalaction/emdash · https://emdash.sh
- Graphify: https://github.com/safishamsi/graphify · https://graphifylabs.ai
- PageIndex: https://github.com/VectifyAI/PageIndex · https://github.com/VectifyAI/pageindex-mcp · https://pageindex.ai
- OpenObserve: https://github.com/openobserve/openobserve · https://openobserve.ai

### Triaged-out sources (reference only)

- claude-mem: https://github.com/thedotmack/claude-mem
- claude-memory-compiler: https://github.com/coleam00/claude-memory-compiler
- Repomix: https://github.com/yamadashy/repomix · https://repomix.com
- GSD: https://github.com/gsd-build/get-shit-done → moved to https://github.com/open-gsd/gsd-core
- crewAI: https://github.com/crewAIInc/crewAI (already evaluated in `docs/LIBRARY_EVALUATION_2025.md`)
- Unsloth: https://github.com/unslothai/unsloth
- Ray: https://github.com/ray-project/ray · https://docs.ray.io
- Firecrawl: https://www.firecrawl.dev/pricing
- Arbor: https://ruc-nlpir.github.io/Arbor/ · https://github.com/RUC-NLPIR/Arbor
- 5 Medium articles (Milvus, Ghost DB, GitHub repos roundup, senior-dev prompt, production agent harness) — see triage table §1

### Existing Bodai context referenced

- `docs/LIBRARY_EVALUATION_2025.md` — prior library evaluation, crewAI recommendation
- `docs/specs/defer-crawl4ai.md` — precedent for documenting a declined-but-informative evaluation
- `mahavishnu/ingesters/otel_ingester.py` — current OTel ingestion backends
- `mahavishnu/ingesters/content_ingester.py` — current content ingestion pipeline
- `mahavishnu/pools/` — multi-pool orchestration
- `mahavishnu/workers/cloud_worker.py` + `mahavishnu/workers/task_router.py` — worker model + task routing

______________________________________________________________________

## 6. Cross-references for future work

- \[[openobserve-poc]\] (proposed) — POC plan if OpenObserve proceeds
- \[[pageindex-integration]\] (proposed) — spec if PageIndex spike succeeds
- \[[emdash-bridge]\] (proposed) — ADR if Emdash-as-client proceeds
- \[[rejected-graphify-broad]\] (proposed) — decline memo if Graphify narrow prototype surfaces nothing
- \[[rejected-keystone-write-side]\] (proposed) — decline memo if Keystone read-side pilot doesn't justify promotion

______________________________________________________________________

## 7. Recommendation

**Ranked picks** (highest ROI first):

- **#1** `mahavishnu repo diff` + `mahavishnu repo pr create` (Tier 1, S, reimplement) — closes the "what did each parallel agent do?" UX gap; ships immediately regardless of any external decision.
- **#2** `mcp__mahavishnu__show_primitive` (Tier 1, S, reimplement) — borrows Keystone's `keystone_show` pattern; single-call composed view of Bodai rules/skills. Worth doing regardless of Keystone adoption.
- **#3** `mcp__session-buddy__export_markdown` + `lint_memory` (Tier 1, S+M, reimplement) — closes "memory is opaque" gap; surfaces orphans/staleness/contradictions.
- **#4** OpenObserve docker POC (Tier 2, S 2-3d, run as service) — validates Parquet/S3 retention lever.
- **#5** `mode: keyword` for `quick_search` (Tier 3, ~1 line, reimplement) — zero-embedding-cost fallback; default stays `"semantic"` for backward compat.
- **#6** Tier 2 spikes in sequence: Graphify 4h → Maxun 30-min pre-check + 1.5d → OpenObserve 2-3d → PageIndex 2d → Keystone pilot 1d → Emdash bridge 1-2w. All hard-gated with decision memos. Nothing graduates without written decision.
- **#7** Backlog / Tier 3 (`mahavishnu ingest issue`, `mahavishnu workflow wait --for-ci`, 31-provider detection refactor, `POOL_ARCHITECTURE.md` doc). Ship after Tier 1 lands.

______________________________________________________________________

## 8. Action Plan

Per-action fields: **description**, **effort** (S/M/L), **probability** of success (synthesized by reviewer unless sourced), **owner-skill** needed, **blocking dependencies**.

### Tier 1 — Quick wins, high confidence (8 actions, 70–85% probability each)

1. **`mahavishnu repo diff <worktree-id>`** — Effort: S. Probability: 90%. Owner: CLI/tooling. Blockers: none. Tier: 1.
1. **`mahavishnu repo pr create <worktree-id> --fill`** — Effort: S. Probability: 80%. Owner: CLI/tooling. Blockers: `gh` system prereq. Tier: 1.
1. **`mcp__mahavishnu__show_primitive`** — Effort: S. Probability: 85%. Owner: Mahavishnu MCP. Blockers: scan logic for skills/rules. Tier: 1.
1. **`mcp__mahavishnu__list_primitives` (companion)** — Effort: XS. Probability: 90%. Owner: Mahavishnu MCP. Blockers: tied to #3. Tier: 1.
1. **`mcp__session-buddy__export_markdown`** — Effort: S. Probability: 85%. Owner: Session-Buddy MCP. Blockers: bulk-export adapter. Tier: 1.
1. **`mcp__session-buddy__lint_memory` (broken_links)** — Effort: S. Probability: 90%. Owner: Session-Buddy MCP. Blockers: v2 schema verification. Tier: 1.
1. **`mcp__session-buddy__lint_memory` (orphans + staleness)** — Effort: S. Probability: 85%. Owner: Session-Buddy MCP. Blockers: v2 schema verification. Tier: 1.
1. **`mcp__session-buddy__lint_memory` (contradictions)** — Effort: M. Probability: 70%. Owner: Session-Buddy MCP. Blockers: LLM cost ceiling for fingerprinting deltas. Tier: 1.

### Tier 2 — Time-boxed spikes (5 actions, 35–75% go-probability each, hard go/no-go criteria)

9. **Graphify MCP-inventory prototype** — Effort: XS (4h). Probability: 60%. Owner: experimental. Blockers: none. Tier: 2.
1. **Maxun pre-check (Playwright dependency audit)** — Effort: XS (30m). Probability: 80% (re-defer). Owner: experimental. Blockers: none. Tier: 2.
1. **Maxun full spike (only if pre-check passes)** — Effort: S (1.5d). Probability: 50%. Owner: experimental. Blockers: pre-check passes. Tier: 2.
1. **OpenObserve docker POC** — Effort: S (2-3d). Probability: 65%. Owner: observability. Blockers: AGPL legal review. Tier: 2.
1. **PageIndex 2-day spike** — Effort: S (2d). Probability: 55%. Owner: content ingestion. Blockers: SHA pin if no SemVer. Tier: 2.
1. **Keystone read-side pilot** — Effort: XS (1d). Probability: 70%. Owner: experimental. Blockers: brew tap availability. Tier: 2.
1. **Emdash-as-client bridge (separate repo)** — Effort: M (1-2w). Probability: 35%. Owner: CLI/integration. Blockers: Emdash upstream responsiveness (14-day window). Tier: 2.

### Tier 3 — Backlog (7 actions, conditional on Tier 1 patterns landing)

16. **`mode: keyword` for `quick_search`** — Effort: M. Probability: 95%. Owner: Session-Buddy MCP. Blockers: requires `db.search_conversations` class-method signature change. Tier: 3.
01. **`mahavishnu ingest issue --from <tracker>`** — Effort: M. Probability: 80%. Owner: ingesters. Blockers: token env vars. Tier: 3.
01. **`mahavishnu workflow wait --for-ci`** — Effort: M. Probability: 80%. Owner: integrations/ci. Blockers: Item 13 lands first. Tier: 3.
01. **31-provider worker-registry refactor** — Effort: S. Probability: 90%. Owner: workers/registry. Blockers: none. Tier: 3.
01. **`POOL_ARCHITECTURE.md` doc** — Effort: S. Probability: 95%. Owner: docs. Blockers: none. Tier: 3.
01. **`docs/MONITORING.md`** — Effort: M (1-2h). Probability: 95%. Owner: docs. Blockers: identifies new health surfaces. Tier: 3.
01. **`THIRD_PARTY_NOTICES.md` at both repos** — Effort: XS (30m). Probability: 95%. Owner: docs. Blockers: AGPL posture verification. Tier: 3.

### Tier 4 — Decline with experiment (4 actions, decision memo only)

23. **Crawl4A** — Re-deferred per `docs/specs/defer-crawl4ai.md`. Decision memo only.
01. **Firecrawl** — Commercial; decline. Decision memo only.
01. **AutoGen / CrewAI / LangGraph** — Out of strategy (already-decided per `docs/LIBRARY_EVALUATION_2025.md`). Decision memo only.
01. **Hermes / MAOS runtime** — Conceptual pattern source; no implementation. Decision memo only.

### Tier 5 — Acknowledge / move on (3 actions, no work)

27. **Arbor** — Niche academic; not strategic. No implementation.
01. **Ghost DB** — Hobby project; no traction. No implementation.
01. **5 Medium articles** — Pattern sources only (already cited). No implementation.

### Tier 6 — Skip (5 actions, no work)

30. **GitHub repos roundup** — Already covered by Tier 1-3 actions.
01. **Senior-dev prompt patterns** — Reference material only.
01. **Production agent harness** — Article source; conceptual only.

______________________________________________________________________

## 9. Implementation Strategy

Three integration modes govern how external projects are adopted.

### Mode 1 — Reimplement

Borrow the pattern, build it in-tree. Used when external project is small/stable enough that the code is a reference, not a dep.

- Keystone `keystone_show` → `mcp__mahavishnu__show_primitive`
- Emdash worktree ergonomics → `mahavishnu repo diff` / `repo pr create`
- Emdash's `keystone_list_primitives` → `mcp__mahavishnu__list_primitives`

### Mode 2 — Wrap as service

Run external binary/daemon as an unmodified subprocess/OTLP target, talk via stdio/HTTP/OTLP.

- **OpenObserve** — Docker container + OTel collector + storage backend. Persistent.
- **PageIndex** — HTTP MCP server. Persistent tree index.

### Mode 3 — Run as CLI subprocess (no daemon)

Invoke on demand, no long-lived process. Stateless.

- **Graphify** — One-shot folder ingest, outputs JSON. No daemon.
- **Keystone** — Read-pilot only; borrow `keystone_show` shape, do not adopt binary.
- **Emdash bridge** — Single-user request/response via Emdash CLI. Stateless.
- **Maxun** — If pre-check passes: 4 robot types (Extract/Scrape/Crawl/Search) via SDK + CLI + HTTP API.

### Per-candidate mode assignment

| Candidate | Mode | Rationale |
|---|---|---|
| OpenObserve | Wrap as service | OTel collector + storage backend; persistent |
| Emdash bridge | Run as CLI subprocess | Single-user request/response; stateless |
| PageIndex | Wrap as service (if go) | HTTP MCP server, persistent tree index |
| Graphify | Run as CLI subprocess | One-shot folder ingest, output JSON |
| Keystone | Reimplement pattern only; run CLI for read-pilot | Borrow `keystone_show` shape; do not adopt binary |
| Maxun | Wrap as service (if go) | Serverless-friendly, 4 robot types |

### AGPL/SSPL posture

Adopted third-party projects under AGPL-3.0 (OpenObserve, Maxun, possibly others) require:

1. **No source linking** — Bodai code does NOT import AGPL libraries directly. Only via unmodified external subprocess / OTLP / HTTP.
1. **No source distribution** — Bodai repos do NOT bundle AGPL source. Distributed binary contains only Bodai code.
1. **Attribution** — `THIRD_PARTY_NOTICES.md` at every repo root lists AGPL projects with version, license, URL, copyright.
1. **Legal review (recommended)** — Before any Phase 3 promotion of an AGPL project, formal legal sign-off.
1. **Loki/Grafana precedent** — Existing Grafana/Loki integration (same AGPL-3.0, same OTLP/PromQL pattern, same conclusion) is the established precedent.

### Implementation order (re-stated)

1. Phase 1 (Tier 1, 8 actions, 3 PRs): ~1-2 weeks. Items 1+2 share `repo_cli.py`; items 5-8 share `export_tools.py`; item 3+4 share `primitive_tools.py`.
1. Phase 2 (Tier 2 spikes, sequential): ~2.5 weeks. Graphify 4h → Maxun 30m+1.5d → OpenObserve 2-3d → PageIndex 2d → Keystone 1d → Emdash 1-2w.
1. Phase 3 (decisions, contingent): promote-or-decline per spike. Promotion = full implementation (2-4 weeks more per go).
1. Phase 4 (Tier 3 backlog): ~1 week. Items 11/14/15 parallel with Phase 1; Item 12 after Item 13; Item 16 in parallel.

**Total deterministic** (Phases 0, 1, 2, 4): **5-7 weeks**.
**Total contingent** (Phase 3): **0-12 weeks additional**, depends on Phase 2 outcomes.
**Grand total range**: **5-19 weeks**. Best case 5 weeks (no Tier 2 promotions), worst case 19 weeks (all 3 promote).
