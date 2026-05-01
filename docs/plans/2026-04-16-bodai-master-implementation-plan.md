# Bodai Master Implementation Plan

**Status:** Phase 0 complete (10/10); Phase 1A complete (6/6 acceptance criteria); Phase 1B complete (37 tests passing); CP0–CP7 all shipped (2026-04-30) — I0–I3 fully satisfied by control plane delivery
**Date:** 2026-04-16
**Last reviewed:** 2026-04-30
**Source:** [Bodai Agent Platform Master Spec](./2026-04-16-bodai-agent-platform-master-spec.md)

**Companion documents:**
- Master spec: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
- Control plane update: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)

**Phase registry (cross-plan reference):**

This document uses **Impl Phases** (I0-I4). See companion docs for their own numbering.

| Impl Phase | Focus | Maps to Spec Phase | Maps to Control Plane Phase | CP Status |
|-----------|-------|--------------------|----------------------------|-----------|
| I0 | Boundary hardening | S1 | CP Phase 0-1 | ✅ shipped |
| I1 | Review-gated learning pipeline | — | CP Phase 2-3 | ✅ shipped |
| I2 | Engine surface expansion | S2 | CP Phase 5-6 | ✅ shipped |
| I3 | Symbiotic entry points | S3 | CP Phase 7 | ✅ shipped |
| I4 | Optional extensions | S4 | — | not started |

**Status note (2026-04-24):** The previous header claimed "Phase 0 complete; Phase 1 governance foundation implemented" but the Phase 0 execution checklist (Section 4.0) has zero checked items. This was a documentation-only status advance, not a code-level completion. The `skill_governance.py` artifact schemas are implemented, but the runtime pipeline (observe, store, retrieve, synthesize, review, activate, rollback) has no owning service. Corrected above to reflect actual state.

## 1. Objective

Turn the master spec into a build order that removes overlap first and only then adds new capability.

This plan is intentionally conservative:

- do not duplicate existing engines
- do not let the TUI become a second control plane
- do not add a new memory or workflow authority unless the canonical owner is clear
- prefer thin adapters over bespoke subsystems

## 2. Implementation Principles

1. One owner per concern.
2. Cache is not authority.
3. UI is presentation, not orchestration.
4. Review-gated learning only.
5. Reuse mature external systems before building custom ones.
6. Security boundaries are explicit at every MCP protocol crossing.
7. Adapter interfaces use typed contracts (Pydantic models), not untyped dicts.
8. Every dependency has a documented degradation mode.

## 3. Non-Goals

- Rebuilding Prefect, LlamaIndex, Agno, Hermes, OpenClaw, or Temporal inside Mahavishnu
- Making the TUI own session state, memory, workflow state, or skill promotion
- Shipping autonomous self-modifying learning
- Adding new public-facing assistant surfaces before the control plane is stable
- Defining a full cross-service authentication model (that is a separate security architecture document; this plan assumes service-level auth is a prerequisite for Phase 2+)

## 4. Phase 0: Boundary Hardening

This phase removes the overlap that the reviewers flagged.

**Parallel workstream note:** Phase 0 (I0) and Control Plane Phase 0 (CP0) are independent and should run concurrently. I0 removes architectural overlap (routing, state, memory, learning boundaries) while CP0 reconciles plan state and audits tool surface redundancy. Neither blocks the other.

### 4.0 Execution checklist

- [x] Replace global Prefect-first default routing with task-class-aware routing
- [x] Add `BATCH_TASK` and `INTERACTIVE_TASK` to the `TaskType` enum in `core/task_router.py`
- [x] Document the two-router composition between `core/task_router.py` (engine selection) and `workers/task_router.py` (model selection) → ADR 011
- [x] Make `TaskRouter.StateManager` the canonical workflow-state owner for live coordination (already the case; no competing authority in live code paths)
- [x] Add persistence strategy for `StateManager` (persist to Dhara via MCP or Session-Buddy; do not leave purely in-memory) → file-based JSON persistence in `data/workflow_state/workflows.json`; Dhara migration deferred to Phase 2
- [x] Wrap `workflow_state.py` as a compatibility shim that delegates to `StateManager`; remove OpenSearch-backed persistence path (durable workflow history stays with Prefect) → already deprecated (only test files import it); deprecation notice updated in docstring
- [x] Make Agno memory off or externalized by default for Bodai/TUI paths (externalized target: Session-Buddy, not local SQLite) → already done: `AgnoMemoryConfig.backend` defaults to `MemoryBackend.NONE`
- [x] De-authorize `team_learning.py` as the canonical learning authority; remove its MCP tool registrations, CLI exposure, and imports from `goal_team_tools.py` and `team_cli.py`; classify as experimental/cache-only
  - MCP registration call and dead method removed from `server_core.py`
  - `__init__.py` and `profiles.py` updated
  - `team_cli.py` commands emit deprecation notice and exit
  - `goal_team_tools.py` gated blocks replaced with no-op log messages
- [x] Lock the TUI to read-only / command-forwarding behavior for stateful surfaces → already enforced (zero persistence writes in TUI modules)
- [x] Add regression tests for all of the above → `tests/unit/test_bodai_phase0_regression.py` (14 tests)

### 4.1 Canonical routing

Target:

- `AI_TASK` routes to Agno first
- `RAG_QUERY` routes to LlamaIndex first
- `WORKFLOW` and `BATCH_TASK` route to Prefect first
- `INTERACTIVE_TASK` routes to Agno first

Work:

- update `task_router.py` so default routing is task-class aware, not Prefect-first for every task
- update `unified_orchestrator.py` to respect task-specific preference orders
- remove the global Prefect-first execution path as the default root behavior
- add regression tests for AI, RAG, workflow, and batch routing

Acceptance criteria:

- routing tests show the correct first-choice adapter per task class
- fallback order remains explicit and observable
- no task class silently falls back to a single global ordering
- `UnifiedOrchestrator` no longer hardcodes `Prefect -> Agno -> LlamaIndex` for all tasks

### 4.2 Canonical workflow state

Target:

- `TaskRouter.StateManager` is the canonical owner for in-flight workflow coordination state
- `workflow_state.py` becomes a compatibility wrapper or is deprecated after migration
- durable workflow execution history remains with Prefect, not the runtime state store
- `StateManager` gains persistence (currently in-memory only; all state lost on Mahavishnu restart)

Work:

- migrate all runtime workflow reads and writes to `task_router.py`'s state manager
- collapse or wrap `workflow_state.py` so it delegates to the canonical state manager
- add a persistence backend for `StateManager` — delegate to Dhara via MCP for durable in-flight state, or store in Session-Buddy if Dhara persistence is not yet available
- remove local-memory fallback as an authority, leaving it only as a cache if absolutely required
- remove the OpenSearch-backed persistence path from `workflow_state.py` (Prefect owns durable execution history)
- add a deprecation notice for direct `workflow_state.py` usage
- add tests that prove one workflow ID has one canonical record
- add tests that verify state survives a Mahavishnu process restart (once persistence is wired)

Acceptance criteria:

- one active workflow record per workflow
- no duplicate workflow authorities in the runtime path
- workflow state retrieval returns the same source of truth across modules
- `workflow_state.py` is no longer a competing authority in the steady state
- in-flight workflow state survives Mahavishnu restart (via persistence backend)

### 4.3 Safe Agno memory defaults

Target:

- Agno memory is off or externalized by default for Bodai/TUI paths

Work:

- change adapter defaults so local SQLite memory is not the default authority
- require explicit opt-in for local persistent Agno memory
- when memory is "externalized," the target is Session-Buddy (not local SQLite and not an unspecified destination)
- keep TUI-facing Agno usage aligned with Session-Buddy / Akosha policy
- add tests for default config and TUI-specific config

Acceptance criteria:

- default Bodai configuration does not create a hidden local memory authority
- TUI path cannot accidentally persist to an independent Agno store
- Bodai/TUI startup paths fail closed if a local persistent Agno store would be created implicitly
- the "externalized" destination is explicitly Session-Buddy in configuration and documentation

### 4.4 Learning surface consolidation

Target:

- `team_learning.py` is de-authoritized as the canonical learning authority
- the canonical learning pipeline is a review-gated ecosystem service owned by Bodai, not the TUI or Agno
- `team_learning.py` is fully unwired from the live MCP server, CLI, and tool imports

Work:

- classify `team_learning.py` as experimental/cache-only until promotion exists
- remove MCP tool registrations for `team_learning.py` from `mahavishnu/mcp/server_core.py`
- remove imports of `team_learning.py` from `goal_team_tools.py` and `team_cli.py`
- remove or gate the `team_cli.py` CLI surface
- add a clear boundary to the docs and code comments stating it is not canonical learning state
- define the migration path to the review-gated learning pipeline
- define the artifact schema for evidence, draft skills, approvals, and rollbacks
- define the promotion policy and review gate explicitly
- make rollback semantics versioned and deterministic

Acceptance criteria:

- no code path treats `team_learning.py` as the canonical skill promotion system
- `team_learning.py` is not registered as an MCP tool
- `team_learning.py` is not imported by any live tool or CLI module
- learning artifacts have a single intended destination
- the learning pipeline has named states and named owners for each transition

### 4.5 TUI boundary enforcement

Target:

- TUI remains presentation-only

Work:

- keep TUI skills browsing read-only
- keep session history views read-only
- keep diff/file views read-only
- treat subagent wiring as command forwarding, not orchestration ownership
- treat Agno streaming as transport-only rendering, not runtime ownership
- forward commands to Mahavishnu; do not embed engine control logic

Acceptance criteria:

- TUI code has no persistence authority
- no TUI module writes workflow or learning state directly
- any state displayed by the TUI comes from canonical backend APIs
- TUI cannot be the first writer of any authoritative state

## 5. Phase 1: Review-Gated Learning Pipeline

After the boundaries are clean, add the learning loop in the ecosystem layer.

Current status:

- the governed learning artifact schemas and promotion policy are implemented in `mahavishnu/core/skill_governance.py`
- runtime integration into the broader ecosystem is intentionally deferred until the ownership model is finalized
- **Blocking gap (2026-04-24 review):** Phase 1 Section 5.2 says the "owning service" is "a dedicated Bodai learning service or worker managed by Mahavishnu." This service does not exist yet. Phase 1 is split below into two sub-phases to unblock work that can proceed now.

### 5.1 Phase 1A: Schemas, Review Gate, and Rollback (complete)

This sub-phase can proceed immediately after Phase 0 boundary hardening.

**Completion status (2026-04-26):** All 6 acceptance criteria met. 24 regression tests passing.

Work items:

- [x] validate that `skill_governance.py` artifact schemas are complete and tested
- [x] implement the review queue surface (read-only) in the TUI
- [x] implement the review gate integration point with Crackerjack
- [x] implement rollback semantics: each activation records the previous active version; rollback restores it without mutating evidence
- [x] add promotion state machine enforcement: `draft -> review -> active -> deprecated` with no self-promotion path
- [x] add tests for promotion and rollback paths
- [x] add security validation: skill synthesis inputs must be sanitized; draft skills are isolated in a `draft` namespace

Acceptance criteria:

- [x] A1: `skill_governance.py` artifact schemas pass schema validation tests
- [x] A2: Crackerjack review gate integration point is wired and returns accept/reject
- [x] A3: rollback restores the previous active skill version without mutating evidence history
- [x] A4: promotion state machine rejects invalid transitions (e.g., `draft -> active` without passing through `review`)
- [x] A5: draft skills are isolated in a `draft` namespace and cannot be loaded by runtime
- [x] A6: TUI review queue surface renders read-only

Implementation summary:

- `mahavishnu/core/review_gate.py` — 5 quality checks (body validation, triggers, metadata, injection warning, Crackerjack integration)
- `mahavishnu/core/skill_registry.py` — in-memory version tracking with rollback execution and evidence preservation
- `mahavishnu/core/skill_security.py` — body sanitization (redaction, truncation) and draft isolation validation
- `mahavishnu/tui/app.py` — `ReviewsScreen` with colored state markup, added as 5th tab
- `mahavishnu/core/skill_governance.py` — fixed `promote_draft()` guard clause to assert REVIEW state instead of validating REVIEW→REVIEW transition
- `tests/unit/test_bodai_phase1a_regression.py` — 24 regression tests covering A1–A6

Validation:

```bash
uv run pytest tests/unit/test_bodai_phase1a_regression.py -v
```

### 5.2 Phase 1B: Full Pipeline Runtime (complete)

**Design decision resolved (2026-04-27):** ADR 012 — Mahavishnu internal async service, following the `MemoryAggregator` pattern. No Prefect dependency. See `docs/adr/012-learning-pipeline-runtime-owner.md`.

**Completion status (2026-04-27):** All 11 work items implemented. 37 tests passing.

**Phase 1B work items:**

- [x] implement `LearningPipelineService` with asyncio periodic collection (observe→store→retrieve→synthesize cycle)
- [x] implement the observe stage: record successful sessions, tool usage, and outcomes as `LearningEvidence` artifacts
- [x] implement the store stage: persist evidence to Session-Buddy via MCP with provenance metadata
- [x] implement the retrieve stage: use Akosha semantic search to find similar successes and failures
- [x] implement the synthesize stage: draft candidate `SkillDraft` proposals from clustered evidence
- [x] wire the full pipeline: observe -> store -> retrieve -> synthesize -> review gate -> activate
- [x] add rate limiting and retention policy for evidence collection
- [x] add MCP tools for the governed pipeline (create evidence, list drafts, trigger synthesis)
- [x] wire `LearningPipelineService` into `MahavishnuApp` startup/shutdown
- [x] add configuration fields for pipeline control (`learning.enabled`, `learning.collection_interval_seconds`, `learning.max_evidence_per_cycle`)
- [x] add tests for end-to-end pipeline execution

Acceptance criteria:

- every skill promotion has a traceable record: evidence -> draft -> review -> activation
- test queries a skill's promotion history and receives a complete chain of artifact IDs, timestamps, and reviewer identities
- the pipeline runtime executes as an asyncio service within MahavishnuApp
- rate limiting prevents unbounded evidence collection
- pipeline can be disabled via `learning.enabled: false`

Validation:

```bash
uv run pytest tests/unit/test_skill_governance.py tests/unit/test_learning_pipeline.py -v
```

### 5.3 Pipeline stages

1. Observe
2. Store
3. Retrieve
4. Synthesize
5. Review
6. Activate
7. Rollback

### 5.4 Ownership

- owning service: a dedicated Bodai learning service or worker managed by Mahavishnu (see Section 5.2 design decision)
- Session-Buddy stores session evidence and checkpoints
- Akosha retrieves similar successes and failures
- Dhara stores durable artifacts when needed
- a dedicated skill-synthesis worker drafts candidate skills
- Crackerjack validates and gates promotion
- Mahavishnu coordinates the flow
- the TUI may display the review queue, but not own it

### 5.5 Artifact schema

The learning pipeline should operate on a small set of explicit artifact types:

- `learning_evidence`
  - source session, repo, task, tool calls, outcome, and supporting metadata
- `skill_draft`
  - proposed name, description, trigger conditions, body, provenance, and target version
- `skill_review`
  - reviewer, decision, rationale, required changes, and timestamp
- `skill_activation`
  - approved version, activation time, and origin of approval
- `skill_rollback`
  - prior active version, rollback reason, and replacement version

### 5.6 Promotion policy

- generated skills are drafts until approved
- authored skills remain the baseline source of truth unless superseded by an approved draft
- promotion requires human review plus policy validation
- activation must be versioned and reversible
- if promotion fails, the draft stays inert

### 5.7 Rollback semantics

- each activation records the previous active version
- rollback restores the prior active version without mutating historical evidence
- rollback is a first-class operation, not an ad hoc manual edit

### 5.8 Review gate

- Crackerjack or the designated review gate must approve skill activation
- the TUI may surface the queue but cannot approve by itself unless explicitly authorized for that workflow
- no automatic self-promotion path is allowed

## 6. Phase 2: Engine Surface Expansion

This phase expands the mature engines already in the stack.

**Prerequisite note:** Phase 2 requires inter-service authentication between Mahavishnu and ecosystem services (Session-Buddy, Akosha, Dhara, Crackerjack). The master spec Section 10.1 flags this explicitly. Without a defined auth model, expanding engine surfaces to remote services creates unauthenticated MCP call paths. A separate security architecture document must exist before Phase 2 work begins. If no auth document exists by the time Phase 0 and Phase 1A are complete, Phase 2 is blocked.

### 6.1 Prefect

Work:

- expand blocks usage for secrets and environment configuration
- expand event or automation coverage where useful
- improve work-pool visibility and operational controls

Acceptance criteria:

- workflow configuration uses Prefect Blocks for secrets and environment variables; audit shows no inline credential or environment references in workflow definitions
- at least 2 operational workflow types (deployment lifecycle, scheduled sweeps) emit or consume Prefect events; event coverage is documented in adapter capability metadata

### 6.2 LlamaIndex

Work:

- expand connectors beyond repo-local ingestion
- improve retrieval evaluation and observability
- add explicit knowledge-pipeline tests

Acceptance criteria:

- LlamaIndex ingester supports at least 3 connector types beyond filesystem using LlamaIndex native connectors, not custom adapters
- retrieval evaluation pipeline produces quantifiable metrics (relevance, faithfulness, correctness) for at least one query set; results are comparable across runs

### 6.3 Agno

Work:

- keep Agno as the interactive runtime behind Mahavishnu
- expose only the controls that fit the canonical architecture
- avoid reintroducing Agno-local persistence as the system of record

Acceptance criteria:

- Agno adapter has zero persistence authority, zero session ownership, and zero direct MCP tool registration
- all state flows through Mahavishnu/Session-Buddy APIs
- integration test confirms no Agno-owned storage paths are created during execution

### 6.4 Code Knowledge Graph

**Design spec:** [2026-04-26-code-indexing-integration-design.md](../superpowers/specs/2026-04-26-code-indexing-integration-design.md)

This section adds three code intelligence capabilities by extending existing infrastructure (DuckDB/DuckPGQ, tree-sitter, mcp-common) rather than introducing new dependencies. No Neo4j, no TiDB, no external graph database.

**Incremental delivery order:**

| Delivery | Capability | Effort | Value |
|----------|-----------|--------|-------|
| 1st | Call chain resolution | Medium | Highest — "who calls this?" queries |
| 2nd | Change impact analysis | Medium | High — "what breaks if I change this?" |
| 3rd | Incremental re-indexing | Low | Medium — automation, not strictly required |

**Prerequisites (all must resolve before this section begins):**

- Inter-service auth between Mahavishnu and Session-Buddy (hard gate — no unauthenticated MCP calls)
- Storage path reconciliation decision: extend DuckPGQ `kg_entities`/`kg_relationships` tables with code-graph-specific columns (Option A recommended), extend reflection DB (Option B), or create new dedicated tables (Option C)
- Upsert logic (ON CONFLICT DO UPDATE) implemented in Session-Buddy's code graph storage

**6.4.1 Storage reconciliation**

Work:

- audit the two existing code graph storage paths in Session-Buddy:
  - DuckPGQ path: `kg_entities`/`kg_relationships` tables (populated by `KGExtractor`)
  - Reflection DB path: `store_code_graph_from_mahavishnu` (consumed by Akosha `CodeGraphIngester`)
- resolve which path becomes the canonical code graph store (recommendation: extend DuckPGQ tables)
- implement the chosen reconciliation approach
- if Option A: add `repo_path`, `commit_hash`, `is_deleted`, `complexity` to `kg_entities.properties` JSON blob; migrate existing reflection DB data; update Akosha ingestion path
- if Option B: add PGQ-compatible query layer to reflection DB
- implement upsert logic for the canonical storage path: the reflection DB already has `INSERT OR REPLACE`; the DuckPGQ path (`kg_entities`/`kg_relationships`) needs `ON CONFLICT DO UPDATE` if Option A is chosen

Acceptance criteria:

- one canonical storage path for code graph data (verified by grep: no duplicate writes)
- Akosha `CodeGraphIngester` pulls from the canonical path
- upsert semantics verified: re-indexing the same file does not create duplicate nodes
- existing code graph data is migrated without loss
- all new tools return Pydantic-typed responses with no raw dicts
- no new infrastructure dependencies (no Neo4j, no TiDB, no external graph DB)
- Session-Buddy remains the single authority for code graph storage (verified by grep)

Validation:

```bash
uv run pytest tests/integration/test_upsert_semantics.py
uv run pytest tests/unit/test_storage_reconciliation.py
```

**6.4.2 Call chain resolution**

Work:

- implement `code_call_chain` MCP tool in Session-Buddy
- input: qualified symbol ID (`repo_path:file:function:name`), direction (callers/callees/both), max depth (default 5), optional edge type filter
- output: Pydantic-typed `CallChainResult` with chains, total_nodes, truncated flag, stale flag, last_indexed_at
- implement PGQ query for bounded BFS traversal with edge-type filtering
- Session-Buddy independently validates all MCP tool inputs using the same Pydantic models
- symbol IDs validated against format regex; no string interpolation into PGQ queries
- `max_depth` field validator with upper bound of 10 (default 5)
- result size limit: 1000 nodes max; query timeout: 30 seconds
- add `stale: true` flag when index is > 24 hours old
- add Tier 4 degradation: structured `CodeGraphUnavailable` response when DuckDB is down; fallback to tree-sitter single-file AST queries
- implement qualified symbol ID format: `{repo_path}:{file_path}:{symbol_type}:{symbol_name}` (extends existing `{file_id}:function:{name}` format used by CodeGraphAnalyzer)

Acceptance criteria:

- transitive callers/callees returned up to 5 hops with correct qualified symbol IDs, file paths, and edge types
- stale flag is set when index is > 24 hours old
- Tier 4 returns structured response, never empty list or untyped error
- PGQ handles depth-5 queries on repos under 50k symbols; if performance insufficient, materialized views per edge type are created

Validation:

```bash
uv run pytest tests/unit/test_code_call_chain.py
uv run pytest tests/unit/test_code_graph_degradation.py
```

**6.4.3 Change impact analysis**

Work:

- implement `code_impact_analysis` MCP tool in Session-Buddy
- input: qualified symbol ID, optional repo_path, include_indirect (default true), max depth (default 5)
- output: Pydantic-typed `ImpactAnalysisResult` with direct/indirect dependents, affected files, risk level (low/medium/high based on direct dependents only), stale flag
- implement reverse call graph traversal via PGQ
- risk level: low (< 3 direct dependents), medium (3-10), high (> 10)

Acceptance criteria:

- all direct and indirect dependents returned with correct depth and dependency type
- `affected_files` list is verified against actual file imports
- `dependency_type` field accuracy verified
- risk level classification matches the defined thresholds
- stale flag is set when index is > 24 hours old
- `last_indexed_at` timestamp is included in response

Validation:

```bash
uv run pytest tests/unit/test_code_impact_analysis.py
```

**6.4.4 Incremental re-indexing**

Work:

- implement `index-code-graph` Prefect workflow in Mahavishnu
- trigger mechanisms (priority order):
  1. Git hook (`post-commit`, `post-merge`, `post-rewrite`) calls `mahavishnu index --trigger git-event --repo <path>`
  2. Scheduled sweep (default: every 15 minutes) calls `mahavishnu index --all-repos`
  3. Manual CLI: `mahavishnu index --repo <path>` for on-demand full re-index
- git event handling:
  - merge conflict: use `git merge-base HEAD MERGE_HEAD` for correct diff
  - force push: full re-index fallback when last-indexed commit hash is not an ancestor of HEAD
  - branch deletion: soft-delete symbols from pruned branch files
- per-file parse failure handling: log, skip, continue; warn if > 25% failure rate
- atomic replacement: write to staging table, swap in single transaction; rollback on failure
- CLI: `mahavishnu index --install-hooks`, `--uninstall-hooks`, `--force`, `--status`
- hook security: validate `--repo` against `repos.yaml`; header comment; overwrite protection; permission 0755; owner verification
- concurrent indexing safety: per-repo file-based lock (`.git/mahavishnu-index.lock`); skip with log if lock held
- comprehensive audit trail: log index_started, index_completed, index_failed, signature_redacted, hook_installed, hook_removed events

Acceptance criteria:

- incremental re-index processes only changed files (parse count == diff count)
- per-file parse failures logged and skipped without aborting batch
- parse failure rate > 25% emits a warning
- soft delete mechanism (is_deleted flag) verified for renamed/removed symbols
- atomic replacement: failed swaps leave existing graph intact
- `--install-hooks` creates hooks with mahavishnu header; `--force` overwrites with confirmation; `--uninstall-hooks` removes only mahavishnu hooks
- `--repo` rejects unregistered repositories
- full re-index of single repo under 100k LOC completes in under 60 seconds

Validation:

```bash
uv run pytest tests/unit/test_reindex_workflow.py
uv run pytest tests/unit/test_hook_installation.py
uv run pytest tests/unit/test_path_validation.py
```

**6.4.5 Security hardening**

Work:

- implement signature redaction: scan function signatures for secret patterns (API_KEY, PASSWORD, TOKEN, SECRET) and replace matches with `"<REDACTED>"` before storage
- set DuckDB file permissions: 0600 for database file, 0700 for database directory
- verify auth gate: all MCP calls to Session-Buddy require valid auth token; fail immediately with `AuthenticationRequired` error if not configured

Acceptance criteria:

- signatures containing secret patterns are redacted in stored graph nodes
- DuckDB file and directory permissions verified at creation and on startup
- DuckDB corruption triggers automatic re-index from scratch with a logged corruption event
- workflow fails immediately when auth is not configured (no silent fallback)

Validation:

```bash
uv run pytest tests/unit/test_signature_redaction.py
uv run pytest tests/unit/test_auth_gate.py
```

**Authority verification:**

```bash
# No competing code graph authorities
grep -r "PropertyGraphIndex" mahavishnu/ session-buddy/  # zero results
grep -r "code_graph" mahavishnu/ --include="*.py" | grep -v "mcp" | grep -v "test"  # no direct writes
```

**6.4.6 Repo skill generation (--skills)**

Uses Leiden community detection on the code graph to identify functional areas and generate auto-generated `SKILL.md` files that give AI agents targeted context.

**Design spec reference:** Section 4.5 of the code indexing design spec.

**Work:**

- implement community detection using NetworkX (`networkx.community.louvain` or `python-louvain`)
  - build undirected graph from code nodes (functions, classes, modules) and edges (calls + imports)
  - weight calls higher than imports
  - run Leiden algorithm with resolution 1.0
  - merge communities with < 3 symbols into nearest neighbor
- analyze each community:
  - identify entry points via betweenness centrality
  - compute internal execution flow via topological ordering
  - identify cross-area connections (edges crossing community boundaries)
  - compute metrics: symbol count, edge density, cross-community coupling
- generate SKILL.md per community:
  - output to `.claude/skills/generated/{community_name}/SKILL.md`
  - follow existing skill format (frontmatter + overview, key files, entry points, execution flow, cross-area connections)
  - include community metrics and last-generated timestamp
- CLI integration:
  - `mahavishnu index --skills --repo <path>`
  - `mahavishnu index --skills --all-repos`
  - `mahavishnu index --all-repos --with-skills` (combined with scheduled sweep)
- regeneration semantics:
  - full regeneration on each run (no incremental update)
  - overwrite previous generated skills
  - `generated/` prefix distinguishes from hand-written skills

Acceptance criteria:

- `mahavishnu index --skills --repo <path>` generates at least one SKILL.md in `.claude/skills/generated/`
- each generated skill follows the existing skill format (frontmatter + required sections)
- entry points list symbols with betweenness centrality > community mean
- communities with < 3 symbols are merged into neighboring communities
- no duplicate skill names generated for the same repo
- generated skills placed under `generated/` prefix — never overwrite hand-written skills
- fails with `CodeGraphRequired` error if no graph data exists for the target repo

Validation:

```bash
uv run pytest tests/unit/test_skill_generation.py
uv run pytest tests/unit/test_community_detection.py
```

## 7. Phase 3: Symbiotic Entry Points

Once the core boundaries and learning pipeline are stable, add external surfaces.

### 7.1 Hermes-style entry points

- user-facing assistant entry
- voice
- context-file semantics
- checkpoint-driven work continuation

### 7.2 OpenClaw-style delivery entry points

- channel-aware delivery/runtime entry
- handoffs
- notifications
- message routing

### 7.3 ACP/editor integration

- only if it adds meaning beyond the TUI and existing editor workflows

Acceptance criteria:

- Hermes/OpenClaw-style surfaces hand work to Mahavishnu instead of bypassing it
- new entry points do not create a second control plane
- each new entry point registers itself as a task source in the canonical routing layer; no entry point bypasses `TaskRouter`
- voice entry points (if implemented) stream audio through Mahavishnu's MCP boundary; audio data does not bypass the trust boundary
- channel-aware delivery entries (Telegram, Discord, Slack) delegate message routing to Mahavishnu; they do not maintain independent routing tables
- context-file semantics are consistent across all entry points (verified by integration test)

Validation:

```bash
uv run pytest tests/integration/test_entry_point_routing.py tests/unit/test_task_router.py
```

## 8. Phase 4: Optional Extensions

Only pursue these if they map to a real product need.

- browser automation
- plugin/hook system
- deeper public API-server mode
- additional provider routing/fallback layers

Acceptance criteria:

- each extension has a written justification linking it to a specific product need before implementation begins
- each extension passes the "one owner per concern" test: a single canonical owner is named for every state surface it introduces
- browser automation runs in an isolated sandbox; no filesystem or network access beyond explicitly configured targets
- plugin/hook system uses typed contracts (Pydantic models) for all plugin interfaces; no untyped `dict[str, Any]` plugin APIs
- public API-server mode exposes the same canonical `EcosystemStatusReport` shape as CLI/MCP; no divergent response schemas
- additional provider routing layers do not introduce routing loops (verified by integration test)

Validation:

```bash
uv run pytest tests/integration/test_extension_contracts.py tests/unit/test_plugin_interfaces.py
```

## 9. Immediate Next Steps

1. Fix routing to match task-class ownership.
2. Collapse workflow-state authority.
3. Disable local memory as the default Agno authority.
4. Mark `team_learning.py` as transitional.
5. Keep the TUI read-only around stateful surfaces.
6. Define the learning pipeline schemas and promotion policy.

## 10. Success Criteria

The implementation plan is successful when all of the following are verified by tests or inspection:

**Ownership and authority:**
- grep for `team_learning.py` imports in live modules returns zero results
- `TaskRouter` routing tests show correct first-choice adapter per task class (no global Prefect-first default)
- `workflow_state.py` has no competing authority in the steady state (delegates to `StateManager`)
- TUI module grep for persistence writes returns zero results

**Learning pipeline:**
- skill promotion has a traceable record chain: evidence -> draft -> review -> activation
- promotion state machine rejects invalid transitions (e.g., `draft -> active` without `review`)
- rollback restores the previous active version without mutating evidence history

**Operational readiness:**
- every dependency has a documented degradation mode
- `ecosystem_status` returns a structurally valid `EcosystemStatusReport` (schema validation test)
- health checks distinguish liveness from readiness (integration test)
- routing telemetry uses bounded labels only (no unbounded `task_id` or `workflow_id` in Prometheus)

**Ecosystem coherence:**
- Hermes/OpenClaw-style surfaces route through Mahavishnu, not around it
- adapter interface contracts use typed Pydantic models, not `dict[str, Any]`
- no duplicate MCP tool names exist in the `standard` tool profile
- Agno adapter has zero persistence authority (verified by integration test)

**Cross-plan alignment:**
- Impl Phase 0 completion is verified against its checklist (Section 4.0)
- CP Phase 0 completion is verified against its checklist
- I0 and CP0 are confirmed as parallel workstreams with independent completion criteria
- Phase 2 has an explicit inter-service auth prerequisite documented
