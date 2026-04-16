# Bodai Master Implementation Plan

**Status:** Phase 0 complete; Phase 1 governance foundation implemented
**Date:** 2026-04-16
**Source:** [Bodai Agent Platform Master Spec](./2026-04-16-bodai-agent-platform-master-spec.md)

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

## 3. Non-Goals

- Rebuilding Prefect, LlamaIndex, Agno, Hermes, OpenClaw, or Temporal inside Mahavishnu
- Making the TUI own session state, memory, workflow state, or skill promotion
- Shipping autonomous self-modifying learning
- Adding new public-facing assistant surfaces before the control plane is stable

## 4. Phase 0: Boundary Hardening

This phase removes the overlap that the reviewers flagged.

### 4.0 Execution checklist

- [ ] Replace global Prefect-first default routing with task-class-aware routing
- [ ] Make `TaskRouter.StateManager` the canonical workflow-state owner for live coordination
- [ ] Deprecate `workflow_state.py` as a competing runtime authority
- [ ] Make Agno memory off or externalized by default for Bodai/TUI paths
- [ ] De-authorize `team_learning.py` as the canonical learning authority
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

Work:

- migrate all runtime workflow reads and writes to `task_router.py`'s state manager
- collapse or wrap `workflow_state.py` so it delegates to the canonical state manager
- remove local-memory fallback as an authority, leaving it only as a cache if absolutely required
- add a deprecation notice for direct `workflow_state.py` usage
- add tests that prove one workflow ID has one canonical record

Acceptance criteria:

- one active workflow record per workflow
- no duplicate workflow authorities in the runtime path
- workflow state retrieval returns the same source of truth across modules
- `workflow_state.py` is no longer a competing authority in the steady state

### 4.3 Safe Agno memory defaults

Target:

- Agno memory is off or externalized by default for Bodai/TUI paths

Work:

- change adapter defaults so local SQLite memory is not the default authority
- require explicit opt-in for local persistent Agno memory
- keep TUI-facing Agno usage aligned with Session-Buddy / Akosha policy
- add tests for default config and TUI-specific config

Acceptance criteria:

- default Bodai configuration does not create a hidden local memory authority
- TUI path cannot accidentally persist to an independent Agno store
- Bodai/TUI startup paths fail closed if a local persistent Agno store would be created implicitly

### 4.4 Learning surface consolidation

Target:

- `team_learning.py` is de-authoritized as the canonical learning authority
- the canonical learning pipeline is a review-gated ecosystem service owned by Bodai, not the TUI or Agno

Work:

- classify `team_learning.py` as experimental/cache-only until promotion exists
- add a clear boundary to the docs and code comments stating it is not canonical learning state
- define the migration path to the review-gated learning pipeline
- define the artifact schema for evidence, draft skills, approvals, and rollbacks
- define the promotion policy and review gate explicitly
- make rollback semantics versioned and deterministic

Acceptance criteria:

- no code path treats `team_learning.py` as the canonical skill promotion system
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

### 5.1 Pipeline stages

1. Observe
2. Store
3. Retrieve
4. Synthesize
5. Review
6. Activate
7. Rollback

### 5.2 Ownership

- owning service: a dedicated Bodai learning service or worker managed by Mahavishnu
- Session-Buddy stores session evidence and checkpoints
- Akosha retrieves similar successes and failures
- Dhara stores durable artifacts when needed
- a dedicated skill-synthesis worker drafts candidate skills
- Crackerjack validates and gates promotion
- Mahavishnu coordinates the flow
- the TUI may display the review queue, but not own it

### 5.3 Artifact schema

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

### 5.4 Promotion policy

- generated skills are drafts until approved
- authored skills remain the baseline source of truth unless superseded by an approved draft
- promotion requires human review plus policy validation
- activation must be versioned and reversible
- if promotion fails, the draft stays inert

### 5.5 Rollback semantics

- each activation records the previous active version
- rollback restores the prior active version without mutating historical evidence
- rollback is a first-class operation, not an ad hoc manual edit

### 5.6 Review gate

- Crackerjack or the designated review gate must approve skill activation
- the TUI may surface the queue but cannot approve by itself unless explicitly authorized for that workflow
- no automatic self-promotion path is allowed

### 5.7 Work items

- define artifact schemas for learning evidence and skill drafts
- define promotion states: `draft`, `review`, `active`, `deprecated`
- define rollback semantics and versioning
- add a review queue surface in the TUI as read-only
- add tests for promotion and rollback paths

### 5.8 Acceptance criteria

- no skill can self-promote without review
- generated skills and authored skills remain separate
- rollback restores the previous active skill version
- the learning system can be audited end-to-end
- the owner and state transitions are explicit in code and docs

## 6. Phase 2: Engine Surface Expansion

This phase expands the mature engines already in the stack.

### 6.1 Prefect

Work:

- expand blocks usage for secrets and environment configuration
- expand event or automation coverage where useful
- improve work-pool visibility and operational controls

Acceptance criteria:

- workflow configuration is less ad hoc
- operational workflows are event-aware where appropriate

### 6.2 LlamaIndex

Work:

- expand connectors beyond repo-local ingestion
- improve retrieval evaluation and observability
- add explicit knowledge-pipeline tests

Acceptance criteria:

- more data sources can be ingested without custom one-off adapters
- retrieval quality can be measured and compared

### 6.3 Agno

Work:

- keep Agno as the interactive runtime behind Mahavishnu
- expose only the controls that fit the canonical architecture
- avoid reintroducing Agno-local persistence as the system of record

Acceptance criteria:

- Agno remains an execution engine, not a second platform

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

## 8. Phase 4: Optional Extensions

Only pursue these if they map to a real product need.

- browser automation
- plugin/hook system
- deeper public API-server mode
- additional provider routing/fallback layers

## 9. Immediate Next Steps

1. Fix routing to match task-class ownership.
2. Collapse workflow-state authority.
3. Disable local memory as the default Agno authority.
4. Mark `team_learning.py` as transitional.
5. Keep the TUI read-only around stateful surfaces.
6. Define the learning pipeline schemas and promotion policy.

## 10. Success Criteria

The implementation plan is successful when:

- the ecosystem has one owner per concern
- the TUI can be developed without stealing backend authority
- learning is review-gated and auditable
- the system can grow without duplicating core responsibilities
- Hermes, OpenClaw, Agno, Prefect, and LlamaIndex remain complementary instead of redundant
