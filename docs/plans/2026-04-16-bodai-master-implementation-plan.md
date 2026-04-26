# Bodai Master Implementation Plan

**Status:** Phase 0 in progress; Phase 1 governance schemas implemented (runtime deferred)
**Date:** 2026-04-16
**Last reviewed:** 2026-04-24
**Source:** [Bodai Agent Platform Master Spec](./2026-04-16-bodai-agent-platform-master-spec.md)

**Companion documents:**
- Master spec: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
- Control plane update: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)

**Phase registry (cross-plan reference):**

This document uses **Impl Phases** (I0-I4). See companion docs for their own numbering.

| Impl Phase | Focus | Maps to Spec Phase | Maps to Control Plane Phase |
|-----------|-------|--------------------|----------------------------|
| I0 | Boundary hardening | S1 | CP Phase 0-1 |
| I1 | Review-gated learning pipeline | — | CP Phase 2-3 |
| I2 | Engine surface expansion | S2 | CP Phase 5-6 |
| I3 | Symbiotic entry points | S3 | CP Phase 7 |
| I4 | Optional extensions | S4 | — |

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

- [ ] Replace global Prefect-first default routing with task-class-aware routing
- [ ] Add `BATCH_TASK` and `INTERACTIVE_TASK` to the `TaskType` enum in `core/task_router.py`
- [ ] Document the two-router composition between `core/task_router.py` (engine selection) and `workers/task_router.py` (model selection)
- [ ] Make `TaskRouter.StateManager` the canonical workflow-state owner for live coordination
- [ ] Add persistence strategy for `StateManager` (persist to Dhara via MCP or Session-Buddy; do not leave purely in-memory)
- [ ] Wrap `workflow_state.py` as a compatibility shim that delegates to `StateManager`; remove OpenSearch-backed persistence path (durable workflow history stays with Prefect)
- [ ] Make Agno memory off or externalized by default for Bodai/TUI paths (externalized target: Session-Buddy, not local SQLite)
- [ ] De-authorize `team_learning.py` as the canonical learning authority; remove its MCP tool registrations, CLI exposure, and imports from `goal_team_tools.py` and `team_cli.py`; classify as experimental/cache-only
- [ ] Lock the TUI to read-only / command-forwarding behavior for stateful surfaces
- [ ] Add regression tests for all of the above

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

### 5.1 Phase 1A: Schemas, Review Gate, and Rollback (unblocked)

This sub-phase can proceed immediately after Phase 0 boundary hardening.

Work items:

- validate that `skill_governance.py` artifact schemas are complete and tested
- implement the review queue surface (read-only) in the TUI
- implement the review gate integration point with Crackerjack
- implement rollback semantics: each activation records the previous active version; rollback restores it without mutating evidence
- add promotion state machine enforcement: `draft -> review -> active -> deprecated` with no self-promotion path
- add tests for promotion and rollback paths
- add security validation: skill synthesis inputs must be sanitized; draft skills are isolated in a `draft` namespace

Acceptance criteria:

- `skill_governance.py` artifact schemas pass schema validation tests
- Crackerjack review gate integration point is wired and returns accept/reject
- rollback restores the previous active skill version without mutating evidence history
- promotion state machine rejects invalid transitions (e.g., `draft -> active` without passing through `review`)
- draft skills are isolated in a `draft` namespace and cannot be loaded by runtime
- TUI review queue surface renders read-only

Validation:

```bash
uv run pytest tests/unit/test_skill_governance.py tests/unit/test_tui_dashboard.py
```

### 5.2 Phase 1B: Full Pipeline Runtime (blocked on design decision)

This sub-phase requires a concrete answer to "what is the learning service?" before work begins.

**Open design decision:** The learning pipeline runtime needs an owning process. Options:

| Option | Description | Tradeoff |
|--------|-------------|----------|
| A: Prefect workflow | Learning pipeline as a scheduled Prefect flow | Leverages existing engine; adds learning as a first-class workflow type |
| B: Mahavishnu worker | Dedicated worker in the existing pool | Simpler deployment; competes with task execution for pool resources |
| C: Standalone service | New Python process managed by Mahavishnu | Clean isolation; adds operational complexity |

**Recommendation:** Option A (Prefect workflow) aligns with the "one owner per concern" principle — Prefect owns durable workflows, and the learning pipeline is fundamentally a durable workflow with review gates. This avoids introducing a new service type.

**Owner and target date:** This decision requires input from the ecosystem architecture owner. Target resolution: before Phase 1A is complete (so Phase 1B can begin immediately after). Add a decision record to `docs/adr/` once resolved.

**While the design decision is pending, the following preparatory work can proceed:**
- refine and test the `learning_evidence` artifact schema
- define the Akosha retrieval interface as a protocol
- define the Session-Buddy evidence storage interface as a protocol

**Phase 1B work items (after design decision):**

- implement the observe stage: record successful sessions, tool usage, and outcomes in Session-Buddy
- implement the store stage: persist evidence with provenance metadata
- implement the retrieve stage: use Akosha to find similar successes and failures
- implement the synthesize stage: draft candidate skills from evidence
- wire the full pipeline: observe -> store -> retrieve -> synthesize -> review gate -> activate
- add rate limiting and retention policy for evidence collection
- add tests for end-to-end pipeline execution

Acceptance criteria:

- every skill promotion has a traceable record: evidence -> draft -> review -> activation
- test queries a skill's promotion history and receives a complete chain of artifact IDs, timestamps, and reviewer identities
- the pipeline runtime executes within the configured owning process
- rate limiting prevents unbounded evidence collection

Validation:

```bash
uv run pytest tests/unit/test_skill_governance.py tests/integration/test_learning_pipeline.py
```

Note: `tests/integration/test_learning_pipeline.py` does not exist yet. It must be created as part of Phase 1B when the pipeline runtime is implemented.

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
