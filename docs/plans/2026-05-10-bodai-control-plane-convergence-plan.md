---
status: complete
role: umbrella
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: convergence-control-plane
---

# Bodai Control Plane Convergence Plan

**Date:** 2026-05-10
**Status:** `complete`, `historical` <!-- legacy status: complete, historical — see YAML frontmatter -->
**Owner:** Core Eng
**Purpose:** Convert remaining Bodai control-plane gaps into one trackable implementation program without duplicating existing plans.

**Acceptance gate:** This plan is retained as a historical record of the convergence program. Remaining terminal refactor work is tracked separately in `2026-05-11-remaining-work-execution-order.md`.

## 1. Outcome

Bodai has enough individual capability. The missing work is convergence:

1. One event spine for lifecycle, telemetry, notifications, and WebSocket fan-out.
1. One durable operational state story for workflows, approvals, pools, routing, and operator recovery.
1. One live operator cockpit backed by canonical MCP/control-plane APIs.
1. One trustworthy ecosystem catalog with automated drift checks.
1. One golden path from incident detection to fix validation to memory/search.
1. One deletion ledger for duplicate code paths, compatibility wrappers, and repo-local implementations that should move to ecosystem foundations.

This plan is the umbrella tracker for that convergence work. Existing shipped plans remain historical references. Existing active plans remain source material. Detailed implementation progress for C0-C7 belongs here; `PLAN_INDEX.md` should change only when lifecycle status or canonical ownership changes.

## 2. Relationship To Existing Plans

| Area | Existing plan/spec | Current status | This plan's role |
|---|---|---:|---|
| Ecosystem status/control plane | `2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md` | shipped | Treat as foundation; extend, do not reimplement |
| Unified events | `2026-05-09-unified-event-bus-spec.md` | draft/active | Promote to first implementation phase |
| TUI/platform | `2026-04-16-bodai-agent-platform-master-spec.md` and `2026-04-16-bodai-master-implementation-plan.md` | partial/shipped mix | Finish operator cockpit pieces only |
| Storage/Dhara | `2026-04-02-storage-consolidation-and-akosha-role.md`, `2026-05-07-dhara-state-backend-addendum.md`, and backlog P2 | partial/deferred | Reconcile storage authority and finish operational durability follow-ups |
| Docs/catalog | `2026-04-25-ecosystem-docs-canonicalization-plan.md` | shipped | Add catalog truth/drift enforcement |
| Cross-repo coordination | `../superpowers/plans/2026-05-07-bodai-phase3-cross-repo-coordination.md` | shipped | Use CoordinationManager and coordination MCP tools as golden-path inputs |
| Refactor/deletion program | this plan | new | Track safe reduction of duplicate code across active Bodai repos |
| LLM provider defaults and Bifrost routing | `2026-05-10-minimax27-provider-migration.md` | complete | Historical sidecar plan for replacing ZAI/GLM defaults with MiniMax M2.7 and MiniMax modality routes |

## 3. Non-Goals

1. Do not add another control plane, event bus, memory authority, or dashboard authority.
1. Do not make the TUI own workflow state, memory, routing policy, or approvals.
1. Do not make Akosha, Session-Buddy, or Crackerjack transactional dependencies for Mahavishnu startup unless explicitly required by configuration.
1. Do not expand into public productization work before the internal control-plane loop is reliable.
1. Do not delete compatibility surfaces until import/call-site audits and replacement tests prove the canonical path covers the behavior.

## 4. Program Tracker

| Phase | Name | Status | Blocking dependency | Primary deliverable |
|---|---|---:|---|---|
| C0 | Plan reconciliation and acceptance gates | `completed` | none | reviewed plan, index entry, tracking rules |
| C1a | Mahavishnu event contract and local test adapter | `completed` | C0 complete, plan active | envelope helper, producer contract, in-process test transport |
| C1b | Oneiric Redis event spine integration | `complete` | C1a, Oneiric Redis adapter support | Redis-backed event transport, WebSocket handler, NotificationRouter wiring |
| C2 | Durable operational state | `complete` | C0 complete, plan active, DharaStateBackend | pool/routing/approval/workflow recovery surfaces |
| C3a | Operator cockpit reconciliation and live read-only panes | `completed` | C0 complete, plan active | verified residual gaps and MCP-backed read-only panes |
| C3b | Cockpit approvals, diffs, event stream, and Agno streaming | `complete` | C3a complete, C2 for approvals, C1b for event stream | approvals, file/diff panes, event activity, Agno stream view |
| C4 | Catalog truth and drift prevention | `complete` | current ecosystem.yaml loader | reconciled catalog and automated drift checks |
| C5-prep | Golden-path fixture and contract harness | `completed` | C0 complete, plan active | deterministic fixture, mock contracts, expected transcript |
| C5 | Incident-to-fix golden path | `complete` | C1b-C4, C5-prep | end-to-end workflow across Mahavishnu, Crackerjack, Session-Buddy, Akosha, Dhara |
| C6a | Shared foundation adoption | `complete` | C1b-C5, catalog audit | published shared contracts and migrated consumers |
| C6b | Complexity reduction and deletion pass | `complete` | C6a, per-target replacement validation | deletion ledger and removed duplicate code paths |
| C7 | Documentation and retirement pass | `complete` | C1b-C6b | retired duplicate docs/surfaces and updated runbooks |

## 4.1 Cross-Repo Complexity Targets

Initial scope is the active repo set currently listed in `settings/ecosystem.yaml`: Mahavishnu, Crackerjack, Session-Buddy, Oneiric, mcp-common, mdinject, Akosha, and Dhara. This scope must be refreshed after C4 reconciles the catalog.

| Repo | Role | Streamline target | Candidate deletions/refactors |
|---|---|---|---|
| `mahavishnu` | orchestrator | become thin control plane over canonical event/state/status APIs | legacy event bus/store/message bus; deprecated workflow state path; duplicate dashboard/status surfaces; duplicate learning/skill surfaces; oversized composition modules |
| `crackerjack` | inspector | expose quality gates and validation results, not duplicate dashboards/control-plane state | deprecated CLI aliases/options, old service roots superseded by `services/*`, duplicate health/MCP/WebSocket helpers once mcp-common covers them |
| `session-buddy` | manager | own session lifecycle/context only | duplicate health tools, realtime/WebSocket paths that become EventBridge subscribers, storage adapters that overlap Dhara/Oneiric ownership |
| `oneiric` | resolver/foundation | own EventBridge, NotificationRouter, adapter lifecycle, config/lifecycle primitives | move from examples/parallel event models to library-level primitives; delete redundant adapter/event glue after consumers migrate |
| `mcp-common` | foundation | own shared MCP server settings, auth, health, telemetry, WebSocket primitives | pull common code from services into this repo; remove local copies from service repos after adoption |
| `mdinject` | app | remain app/client surface only | avoid repo-local control-plane, memory, session, or orchestration logic; consume Bodai MCP APIs instead |
| `akosha` | seer | derived intelligence, semantic search, aggregation | remove primary-storage assumptions; retire duplicate auth/health/WebSocket copies when mcp-common/EventBridge covers them |
| `dhara` | curator | durable object/state storage | audit overlapping `file_storage`, `file_storage2`, `storage_server`, backup storage, and MCP storage APIs; keep one storage interface per supported backend |

Cross-repo ownership rules:

- Oneiric owns event subscription/dispatch contracts, EventBridge, NotificationRouter, adapter lifecycle, and lifecycle/config primitives.
- Oneiric must expose generic retry-exhaustion/dead-letter sink hooks only. Mahavishnu owns `DLQEventHandler` and Mahavishnu `DeadLetterQueue` coupling.
- mcp-common owns shared MCP server/session primitives, auth helpers, health contracts, telemetry middleware, and WebSocket protocol/server primitives.
- Service repos own domain-specific topic mapping, tool registration, and business behavior only.
- Provider defaults and model routing across Mahavishnu, Crackerjack, Session-Buddy, and Bifrost were governed by `2026-05-10-minimax27-provider-migration.md`; this convergence plan consumes those results for catalog drift checks, golden-path validation, and deletion ledgers.
- Crackerjack owns validation result schemas and quality-gate report contracts. Mahavishnu consumes those contracts; mcp-common may host shared MCP plumbing only.
- Session-Buddy retains session-local context persistence. Dhara owns operational restart/recovery checkpoints.
- Akosha writes are derived/indexed copies with source correlation IDs. Recovery reads must come from Dhara or Session-Buddy, not Akosha.
- Dhara should expose one operational state/checkpoint contract and one object/blob storage contract, even if multiple backends exist under those contracts.

Deletion safety rules:

- Every deletion must identify the canonical replacement and owning repo.
- Every deletion must include an import/call-site audit across the active repo set.
- Every deletion audit must record the exact search command, searched repos, searched module/API/CLI flag/MCP tool names, and a disposition for every hit: `migrated`, `compatibility wrapper`, `historical docs`, `test fixture`, or `blocker`.
- Compatibility wrappers need explicit removal targets and tests proving delegated behavior.
- If a feature has active external users or unclear ownership, move it to a deprecation ledger instead of deleting immediately.
- A deletion batch may start only when the specific canonical replacement for that batch is implemented, validated, documented, and adopted by all active repo call sites.
- If an upstream phase is deferred, dependent deletion targets move to the deprecation ledger only.
- Deletions touching operator cockpit, WebSocket, approval, event-stream, dashboard, or status behavior require C3b completion or an explicit per-target deferral.
- Deletions touching ZAI/GLM provider support, Bifrost model routes, or Qwen/ZAI provider-adapter compatibility require the classification outcomes recorded in M5 of `2026-05-10-minimax27-provider-migration.md`.

Deletion audit command template:

```bash
rg -n "<module|symbol|CLI flag|MCP tool name>" /Users/les/Projects/mahavishnu /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy /Users/les/Projects/oneiric /Users/les/Projects/mcp-common /Users/les/Projects/mdinject /Users/les/Projects/akosha /Users/les/Projects/dhara
```

Each deletion ledger entry must replace the placeholder with concrete symbols and attach the transcript or a path to the transcript.

## 5. Phase C0: Plan Reconciliation And Acceptance Gates

**Goal:** Make this plan the trackable umbrella without obscuring existing source plans.

Tasks:

- [x] Add this plan to `PLAN_INDEX.md` as the active umbrella convergence plan.
- [x] Add authority matrix to `PLAN_INDEX.md`.
- [x] Link superseded or subordinate active items from this plan rather than copying their full content.
- [x] Record multi-agent review findings in this file.
- [x] Define entry criteria, exit criteria, and validation commands or named artifacts for each phase before implementation starts.
- [x] Add progress update rule: task/phase progress updates this file; update `PLAN_INDEX.md` only when lifecycle status or canonical ownership changes.
- [x] Reconcile storage authority between the storage consolidation plan and Dhara addendum.
- [x] Reconcile event-bus rollout policy between this plan and the unified event-bus spec.
- [x] Owner accepts C0 and promotes this plan from `draft, umbrella` to `active, umbrella`.

Acceptance criteria:

- `PLAN_INDEX.md` has exactly one current umbrella entry for the convergence program.
- Existing active plans point readers here when the work is convergence-level rather than area-local.
- Review findings are either resolved or explicitly deferred with rationale.
- C1-C7 each have entry criteria, exit criteria, and validation commands or named artifacts before implementation starts.
- C0 task is complete and plan status is `active, umbrella` before any downstream phase moves out of `not started`.
- Owner acceptance is recorded before the plan leaves `draft`.

Validation:

- Review `git diff -- docs/plans/PLAN_INDEX.md docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md`.
- Confirm all high/P0/P1 review findings in Section 17 are `resolved` or `deferred`.

## 6. Phase C1a: Mahavishnu Event Contract And Local Test Adapter

**Goal:** Make Mahavishnu's event contract testable without blocking on Oneiric repo changes.

Source plan: `2026-05-09-unified-event-bus-spec.md`

Entry criteria:

- C0 complete and plan status is `active, umbrella`.
- Current event producers and WebSocket direct-publish call sites are inventoried.

Tasks:

- [x] Verify Oneiric EventBridge/EventDispatcher API and Redis queue adapter extension points.
- [x] Introduce a Bodai event envelope helper with `event_id`, `source`, `correlation_id`, `causation_id`, `version`, and `timestamp` headers.
- [x] Define Mahavishnu event publisher interface and local in-process test transport.
- [x] Add tests for envelope metadata, correlation/causation propagation, and local publish/subscribe semantics.
- [x] Define atomic migration policy for old event APIs: migrate callers and remove old APIs, allowing import stubs only where needed for short-term compatibility.

Acceptance criteria:

- Event producers can target the new publisher interface under tests without Redis or Oneiric runtime.
- Event envelopes match the Bodai metadata convention from the unified event-bus spec.
- Rollout policy matches the unified event-bus spec: no mixed-format compatibility shim unless the spec is explicitly amended.

Validation:

- Add and run targeted unit tests for event envelope and local transport behavior.
- Run `uv run ruff check mahavishnu tests` after implementation.

## 7. Phase C1b: Oneiric Redis Event Spine Integration

**Goal:** Replace fragmented event-like systems with Oneiric EventBridge/EventDispatcher plus Redis Streams/Pub/Sub transport and NotificationRouter routing.

Source plan: `2026-05-09-unified-event-bus-spec.md`

Entry criteria:

- C1a complete.
- Oneiric Redis Streams/Pub/Sub support exists or has a reviewed patch plan in the Oneiric repo.

Tasks:

- [x] Add or extend Redis Streams/Pub/Sub adapter support in Oneiric if missing, with a Oneiric owner and PR/task reference before Mahavishnu migration begins.
- [x] Build Mahavishnu event transport wrapper that persists to Redis Streams and publishes to Redis Pub/Sub.
- [x] Add EventBusConsumer that replays pending stream entries and subscribes to `bodai:events:*`.
- [x] Convert WebSocket server into an EventBridge handler that can broadcast envelopes to rooms.
- [x] Route retry exhaustion to Mahavishnu's dead-letter queue.
- [x] Route alerts/notifications through Oneiric `NotificationRouter` with parity for existing email/slack/webhook behavior.
- [x] Migrate producers from `EventBus`, `TaskEventEmitter`, `MessageBus`, and alert channels in priority order.
- [x] Remove legacy event producer APIs or leave import-only stubs with explicit removal targets.
- [x] Add unit and integration tests for publish, replay, fan-out, DLQ, WebSocket room mapping, and notification routing.

Acceptance criteria:

- New lifecycle events are emitted through the unified event spine.
- WebSocket updates are received through the EventBridge handler, not direct bespoke publish calls.
- Failed event handling has deterministic retry and DLQ behavior.
- Notification routing uses Oneiric `NotificationRouter` or is explicitly deferred in the source spec.
- Legacy event paths are removed or import-only with clear removal targets.

Validation:

- Run Oneiric unit/contract tests for the Redis Streams/Pub/Sub adapter and EventBridge extension points before Mahavishnu adoption.
- Run targeted event-bus unit and integration tests.
- Run a local Redis-backed smoke test when Redis is available.
- Artifact: per-repo event adoption matrix with role `producer`, `consumer`, or `none` for Mahavishnu, Crackerjack, Session-Buddy, Oneiric, mcp-common, mdinject, Akosha, and Dhara.
- Artifact: Oneiric release/adoption note proving the event contract is available to Mahavishnu before legacy event deletion.

## 8. Phase C2: Durable Operational State

**Goal:** Finish the durability gaps that keep Mahavishnu from recovering cleanly after restart.

Source plans: storage consolidation plan, Dhara state backend addendum, and backlog P2/P8 follow-ups.

Storage authority decision:

- `DharaStateBackend` owns restart/recovery checkpoints for workflows, pools, routing decisions, and approvals.
- Mahavishnu-owned PostgreSQL/pgvector sections in the older storage consolidation plan are superseded for operational restart/recovery checkpoints unless a later accepted plan reintroduces them.
- PostgreSQL/pgvector can remain analytical/search persistence only if a future plan defines that scope separately.
- Session-Buddy owns session context. Akosha owns derived intelligence, semantic retrieval, and cross-system aggregation.

Entry criteria:

- C0 complete and plan status is `active, umbrella`.
- Current `DharaStateBackend` implementation and addendum are verified against code.

Tasks:

- [x] Confirm current `DharaStateBackend` API and key schema.
- [x] Pool state: define key contract, write hook, recovery read path, degraded-mode behavior, and tests.
- [x] Routing decisions: define key contract, batched write hook, recovery/read API, backpressure behavior, and tests.
- [x] Persist approval requests/responses through the existing durable approval path and validate recovery after restart.
- [x] Workflow lifecycle: verify current write hooks, add missing recovery/read behavior, and tests.
- [x] Add degraded-boot behavior when Dhara is unavailable and dependencies are optional.
- [x] Add operator-facing recovery summary to ecosystem status.
- [x] Update architecture docs with Dhara operational persistence boundaries.

Acceptance criteria:

- Restart recovery can report last-known workflows, approvals, pools, and routing history.
- Dhara outage does not hard-fail optional Mahavishnu operation.
- State ownership is documented: Dhara for durable operational state, Session-Buddy for session context, Akosha for derived intelligence/search.

Validation:

- Add targeted unit tests for each persisted state area.
- Add one restart/recovery integration test with Dhara mocked.
- Run `uv run pytest tests/unit -k "dhara or recovery or routing or pool or approval"`.

## 9. Phase C3a: Operator Cockpit Reconciliation And Live Read-Only Panes

**Goal:** Make the Textual TUI a live operator cockpit while preserving read-only/command-forwarding boundaries.

Source plans: Bodai Agent Platform spec and master implementation plan.

Entry criteria:

- C0 complete and plan status is `active, umbrella`.
- Current TUI implementation has been checked against the shipped CP4/control-plane DoD.

Current gap classification:

| Surface | Status | Notes |
|---|---|---|
| Overview | shipped | Live ecosystem status, workflow, adapter, and alert summary from canonical control-plane reads |
| Sweep | shipped | Live workflow recovery/history summary from ecosystem status |
| Routing | shipped | Live adapter health and routing readiness from ecosystem status |
| Alerts | shipped | Live alert summary from ecosystem status |
| Reviews | partially shipped | Canonical app-owned skill registry hook exists, with filesystem fallback still present for local visibility |
| Session | shipped | Live Session-Buddy checkpoint posture and session-local config summary |
| Recovery | shipped | Live Dhara recovery summary from canonical app/ecosystem recovery provider |

Tasks:

- [x] Verify current TUI implementation against CP4/control-plane DoD and classify residual gaps.
- [x] Replace remaining placeholder fetchers with canonical MCP/control-plane calls.
- [x] Add richer session and skill views backed by Session-Buddy and local/project skill registry surfaces.
- [x] Add TUI tests for live data adapters and boundary regressions.

Acceptance criteria:

- Residual TUI gaps are classified as already shipped, still missing, or intentionally deferred.
- Read-only panes use canonical MCP/control-plane APIs instead of local duplicate state.
- TUI performs no direct persistence writes for workflow state, memory, routing, or skill promotion.

Validation:

- Run targeted TUI unit tests.
- Run `uv run pytest tests/unit/test_tui_dashboard.py tests/unit/test_command_palette.py`.
- Artifact: C3a residual-gap classification table.

## 10. Phase C3b: Cockpit Approvals, Diffs, Event Stream, And Agno Streaming

**Goal:** Add operator interaction features after their backing APIs are durable and observable.

Entry criteria:

- C3a complete.
- C2 complete for approval flows.
- C1b complete for event-stream activity.

Tasks:

- [x] Add Agno streaming view for interactive agent execution without making the TUI an agent runtime owner.
- [x] Add inline approval review/response flow backed by durable approval APIs.
- [x] Add file/diff panes using safe read-only repository access and existing path validation.
- [x] Add event-stream activity pane fed by C1b event spine.
- [x] Keep mutating actions behind explicit command-forwarding and approval gates.
- [x] Add TUI tests for file/diff path validation, event-stream rendering, and Agno streaming boundaries.
- [x] Add TUI tests for approval command forwarding.

Acceptance criteria:

- TUI answers "what is broken, blocked, running, waiting for me, and what changed" from live sources.
- TUI performs no direct persistence writes for workflow state, memory, routing, or skill promotion.
- Approval actions are durable and auditable.

Validation:

- Run targeted TUI approval/file-diff/event-stream tests.
- Run an MCP-backed manual smoke test when local Mahavishnu MCP is running.
- Artifact: operator-cockpit smoke transcript for approval, diff, and event-stream flows.

## 11. Phase C4: Catalog Truth And Drift Prevention

**Goal:** Make `settings/ecosystem.yaml` and operator docs agree and stay correct.

Entry criteria:

- C0 complete and plan status is `active, umbrella`.
- Existing docs audit command and script are verified against current code.

Tasks:

- [x] Reconcile `docs/ECOSYSTEM.md` inventory counts with `settings/ecosystem.yaml`.
- [x] Extend `mahavishnu docs audit` / `scripts/audit_ecosystem_docs.py` with catalog-count and stale-claim checks.
- [x] Add drift checks for stale docs claims about repo count, MCP server count, agents, skills, tools, workflows, and roles.
- [x] Add status freshness checks for audit timestamps and health probe metadata.
- [x] Make generated/catalog-derived docs clearly generated or explicitly manually maintained.
- [x] Add tests for catalog count drift and invalid role/server references.

Acceptance criteria:

- A fresh checkout has one canonical ecosystem inventory.
- Docs and plan index cannot silently claim inventory counts that conflict with the catalog.
- Operator commands report stale or missing audit metadata.

Validation:

- Run `uv run mahavishnu docs audit`.
- Run targeted docs/catalog audit tests.

## 12. Phase C5-prep: Golden-Path Fixture And Contract Harness

**Goal:** Prepare deterministic integration proof artifacts before C1-C4 finish.

Entry criteria:

- C0 complete and plan status is `active, umbrella`.
- Current coordination, Session-Buddy, Akosha, Dhara, and Crackerjack MCP/service interfaces are inventoried.

Tasks:

- [x] Define one deterministic test incident fixture.
- [x] Define mock service contracts for Crackerjack, Session-Buddy, Akosha, and Dhara.
- [x] Define expected correlation-ID trace assertions.
- [x] Define expected operator transcript and TUI/status observations.

Acceptance criteria:

- C5 can run from a named fixture without relying on live external services.
- Mock contracts match current MCP/service interfaces or explicitly document gaps.

Validation:

- Add fixture/contract tests that run without live services.
- Artifact: golden-path fixture and mock-service contract packet.

## 13. Phase C5: Incident-To-Fix Golden Path

**Goal:** Prove Bodai works as one ecosystem, not a set of connected demos.

Entry criteria:

- C1b, C2, C3a, C4, and C5-prep complete.
- C3b complete if the golden path includes live TUI approvals or event stream.
- MiniMax migration M1-M4 and M5 classification are complete for repos used by the golden path, or the C5 transcript explicitly records a local/Ollama provider deferral.

Representative flow:

1. Mahavishnu detects a degraded service or failing quality gate.
1. Event spine emits incident context with correlation ID.
1. `CoordinationManager` and coordination MCP tools record blocker/todo/owner.
1. Session-Buddy records session context.
1. Crackerjack runs validation or targeted checks.
1. Mahavishnu routes fix work to the right adapter/worker/pool.
1. Approval gate pauses risky action.
1. Dhara persists operational state throughout.
1. Akosha indexes derived incident/fix knowledge for semantic retrieval.
1. Operator cockpit shows progress and final validation result.

Tasks:

- [x] Implement orchestration path using existing MCP tools/service layers, not ad hoc scripts.
- [x] Add Crackerjack validation handoff and result ingestion.
- [x] Add Session-Buddy context tracking handoff.
- [x] Add Akosha derived-memory/search handoff.
- [x] Add Dhara recovery checkpoints at each stage.
- [x] Add TUI/operator status view for the full correlation ID.
- [x] Add end-to-end test with external services mocked and one opt-in live smoke test.

Acceptance criteria:

- A single correlation ID traces the incident from detection to validated fix.
- Operator can resume after Mahavishnu restart and see the same workflow state.
- The completed incident is searchable semantically and visible in session history.

Validation:

- Add end-to-end test with external services mocked.
- Add one opt-in live smoke test skipped unless required service env vars are present.
- Run the repo-approved Crackerjack quality gate for each touched repo and attach the validation result artifact.
- Artifact: correlation-ID trace transcript from detection to validation.

## 14. Phase C6a: Shared Foundation Adoption

**Goal:** Publish and adopt shared foundation contracts before deleting local duplicate implementations.

Entry criteria:

- C1b-C5 are complete for the specific capability family being migrated, or the target is ledger-only.
- C4 catalog audit has refreshed the active repo list.
- Shared API owner is identified for each capability family.

Tasks:

- [x] Build a cross-repo deletion/adoption ledger with owner repo, candidate file/module, replacement, preserved public API/CLI/MCP surfaces, docs/config references, exact import/call-site audit command, hit disposition, risk level, migration/deprecation decision, parity tests, Crackerjack quality-gate artifact, rollback plan, release note requirement, validation command, and removal target date.
- [x] Oneiric: promote EventBridge, NotificationRouter, adapter lifecycle, and config/lifecycle primitives as stable library contracts used by other repos.
- [x] mcp-common: absorb shared MCP settings, auth, health, telemetry, and WebSocket primitives currently copied across service repos.
- [x] Crackerjack: publish validation result schemas and quality-gate report contracts for Mahavishnu consumption.
- [x] Define per-repo event adoption roles: `producer`, `consumer`, or `none`.
- [x] Define mcp-common vs Oneiric WebSocket/event boundary tests.
- [x] Add migration PR/task entries for each active repo consumer before deletion starts.

Acceptance criteria:

- Shared contracts are published, documented, and covered by contract tests.
- Consumer repos have migrated call sites or explicit ledger deferrals.
- No deletion batch is approved without a replacement and parity evidence.

Validation:

- Artifact: completed cross-repo deletion/adoption ledger.
- Artifact: shared-contract test matrix for Oneiric and mcp-common primitives.
- Run repo-local contract tests for every shared foundation repo touched.
- Run the repo-approved Crackerjack quality gate for every touched repo once Crackerjack publishes the validation result schema.

## 15. Phase C6b: Complexity Reduction And Deletion Pass

**Goal:** Reduce ecosystem LOC and operational complexity by removing duplicate implementations after canonical replacements are live.

Entry criteria:

- C6a complete for the specific deletion batch.
- The canonical replacement for the batch is implemented, validated, documented, and adopted by all active repo call sites.
- Deletion ledger entry includes owner, replacement surface, preserved public API/CLI/MCP surfaces, docs/config references, parity tests, rollback plan, release note requirement, and validation command.
- If an upstream replacement was deferred, the dependent deletion target is moved to the deprecation ledger only.
- Deletions touching operator cockpit, WebSocket, approval, event-stream, dashboard, or status behavior require C3b completion or explicit per-target deferral.

Tasks:

- [x] Mahavishnu: retire legacy event bus/store/message bus paths after C1b migration.
- [x] Mahavishnu: remove deprecated workflow-state authority after C2 recovery paths are complete.
- [x] Mahavishnu: collapse duplicate dashboard/status surfaces onto `ecosystem_status`.
- [x] Mahavishnu: audit duplicate learning/team-learning surfaces; delete only after a canonical review-gated skill lifecycle and parity tests exist, otherwise ledger-only.
- [x] Mahavishnu: split large composition roots (`core/app.py`, `mcp/server_core.py`, `core/config.py`) so they wire services rather than own domain logic.
- [x] Crackerjack: remove deprecated CLI aliases/options and old service roots superseded by canonical `services/*` modules.
- [x] Crackerjack: delegate shared MCP/auth/health/WebSocket primitives to `mcp-common` where feasible.
- [x] Session-Buddy: consolidate health/MCP monitoring tools and move realtime event fan-out behind EventBridge subscriptions where applicable.
- [x] Session-Buddy: clarify storage adapter ownership relative to Dhara and Oneiric; retain session-local context persistence and remove only adapters that duplicate canonical operational-checkpoint behavior.
- [x] mcp-common: remove local service copies only after C6a shared primitives are adopted.
- [x] Akosha: keep derived intelligence/search only; remove primary-storage assumptions and duplicate platform primitives after shared adoption; ensure all writes carry source correlation IDs.
- [x] Dhara: audit and consolidate overlapping storage entry points (`file_storage`, `file_storage2`, `storage_server`, backup storage, MCP storage APIs) under one operational state contract and one object/blob storage contract.
- [x] mdinject: explicitly audit direct event, session, memory, orchestration, and storage dependencies; expected result may be no changes.
- [x] Add regression tests or contract tests before each deletion batch.

Acceptance criteria:

- Every removed code path has a named canonical replacement and passing validation.
- No active repo imports deleted modules after the deletion batch.
- Every search hit in the import/call-site audit has an accepted disposition: `migrated`, `compatibility wrapper`, `historical docs`, `test fixture`, or `blocker`; no deletion proceeds while a `blocker` remains.
- Public/operator-facing capability is preserved or improved with fewer authorities.
- The deletion ledger is updated with final disposition for each candidate.

Validation:

- Run repo-local tests for each touched repo.
- Run cross-repo import/call-site audit for deleted modules with the command template from Section 4.1 and attach the transcript.
- Run the repo-approved Crackerjack quality gate for every touched repo.
- Run `uv run mahavishnu docs audit` after catalog/docs updates.
- Artifact: deletion ledger final disposition and import-audit transcript.

## 16. Phase C7: Documentation And Retirement Pass

**Goal:** Remove ambiguity after the implementation lands.

Entry criteria:

- C1b-C6b are complete or explicitly deferred with accepted rationale.

Tasks:

- [x] Update `README.md`, `docs/architecture/ARCHITECTURE.md`, and runbooks for the converged architecture.
- [ ] Mark subordinate source plans as shipped/superseded where appropriate.
- [x] Add migration notes for deprecated event APIs and legacy operator surfaces.
- [x] Update MCP tool reference with canonical status/event/state/cockpit tools.
- [x] Remove or archive obsolete docs that still describe old event/state ownership.

Acceptance criteria:

- New contributors can identify the canonical event, state, catalog, and operator surfaces from `PLAN_INDEX.md`.
- Deprecated surfaces have explicit replacement guidance.
- Docs no longer present shipped placeholder/TUI behavior as active reality.

Validation:

- Run docs audit after documentation updates.
- Review `PLAN_INDEX.md` and affected source plans for stale ownership claims.

## 17. Review Log

Use this section to record multi-agent review findings.

| ID | Date | Severity | Source | Affected phase | Required change | Disposition |
|---|---|---:|---|---|---|---|
| R1 | 2026-05-10 | P0 | Architecture review | C2 | Reconcile Dhara vs PostgreSQL/pgvector storage authority | Resolved in C2 storage authority decision |
| R2 | 2026-05-10 | P1 | Architecture review | C1a, C1b | Align event-bus shim policy with unified event-bus spec | Resolved by C1a/C1b atomic migration policy |
| R3 | 2026-05-10 | P1 | Architecture review | C1b | Add NotificationRouter as an event-bus acceptance gate | Resolved in C1b tasks and acceptance criteria |
| R4 | 2026-05-10 | P1 | Architecture/docs review | C0, index | Clarify plan/index/backlog authority and priority order | Resolved in `PLAN_INDEX.md` authority matrix and C0 gate |
| R5 | 2026-05-10 | P2 | Architecture review | C5 | Fix cross-repo coordination source path and name concrete coordination surface | Resolved in relationship table and C5 flow |
| R6 | 2026-05-10 | P2 | Architecture review | C4 | Extend existing docs-audit tooling instead of creating parallel validator | Resolved in C4 tasks |
| R7 | 2026-05-10 | P2 | Architecture review | C3a | Reconcile current TUI state before implementation | Resolved by C3a pre-task |
| R8 | 2026-05-10 | High | Implementation review | C1a, C1b | Split Oneiric-dependent work from Mahavishnu-local work | Resolved by C1a/C1b split |
| R9 | 2026-05-10 | High | Implementation review | C3a, C3b | Split C3 work by prerequisites | Resolved by C3a/C3b split |
| R10 | 2026-05-10 | High | Implementation/docs review | All phases | Add validation commands/artifacts | Resolved with per-phase validation sections |
| R11 | 2026-05-10 | Medium | Implementation review | C2 | Break broad persistence tasks into trackable work units | Resolved in C2 task breakdown |
| R12 | 2026-05-10 | Medium | Implementation/docs review | C4 | Define local enforcement point for catalog drift | Resolved by extending `mahavishnu docs audit` |
| R13 | 2026-05-10 | Medium | Implementation review | C5 | Move fixture/contract harness earlier | Resolved by C5-prep |
| R14 | 2026-05-10 | Medium | Docs review | Index | Extend status vocabulary and legal combinations | Resolved in `PLAN_INDEX.md` status legend |
| R15 | 2026-05-10 | Medium | Docs review | C0, index | Avoid multi-place detailed progress drift | Resolved by progress update rule |
| R16 | 2026-05-10 | High | Re-review | C6a, C6b | Split shared-foundation adoption from deletion and forbid deletion when replacements are deferred | Resolved by C6a/C6b split and deletion safety gates |
| R17 | 2026-05-10 | High | Cross-repo review | C1b, C6a | Clarify cross-repo event, DLQ, WebSocket, mcp-common, and Oneiric ownership | Resolved by cross-repo ownership rules |
| R18 | 2026-05-10 | Medium | Cross-repo review | C6b | Add Crackerjack, Session-Buddy, Akosha, Dhara, and mdinject deletion guardrails | Resolved in C6a/C6b tasks and ownership rules |
| R19 | 2026-05-10 | P1 | Tracking re-review | C0, index | Replace undefined `accepted` status and parent C1/C3 references | Resolved by active-status gate and phase-label updates |
| R20 | 2026-05-10 | High | Multi-agent review | C6a, C6b | Make deletion audit executable with command template and hit dispositions | Resolved in deletion safety rules and C6 validation |
| R21 | 2026-05-10 | High | Multi-agent review | C5, C6a, C6b | Add Crackerjack quality-gate artifacts as first-class validation gates | Resolved in C5/C6 validation |
| R22 | 2026-05-10 | Medium | Multi-agent review | C1b | Add Oneiric owner/release/adoption gate for event spine support | Resolved in C1b tasks and validation |
| R23 | 2026-05-10 | Medium | Multi-agent review | C3b, C5 | Tighten tracker dependencies for C3b and provider gate for C5 | Resolved in tracker and C5 entry criteria |

## 18. Progress Log

Use this log for implementation updates that change phase status.

| Date | Phase | Change | Validation |
|---|---|---|---|
| 2026-05-10 | C0 | Initial umbrella plan drafted | Pending review |
| 2026-05-10 | C0 | Multi-agent review completed and high-priority findings incorporated | Review log R1-R15 |
| 2026-05-10 | C0 | Multi-agent re-review completed; governance, deletion-audit, Crackerjack validation, Oneiric event, and provider-gating findings incorporated | Review log R20-R23; `git diff --check` |
| 2026-05-10 | C0 | Owner acceptance recorded; plan promoted to `active, umbrella`; C0 marked complete | `git diff --check` |
| 2026-05-10 | C1a | Event envelope helper, publisher protocol, in-memory transport, and tests landed; Oneiric API verification completed | `uv run pytest --no-cov tests/unit/test_event_envelope.py tests/unit/test_event_contract.py tests/unit/test_event_bus.py`, `uv run ruff check mahavishnu/core/events tests/unit/test_event_envelope.py tests/unit/test_event_contract.py` |
| 2026-05-10 | C1b | Oneiric EventBridge/Redis Streams APIs verified and Redis pub/sub methods added to the queue adapter with tests | `uv run pytest --no-cov /Users/les/Projects/oneiric/tests/adapters/test_redis_streams_queue.py /Users/les/Projects/oneiric/tests/runtime/test_parity_prototypes.py /Users/les/Projects/oneiric/tests/runtime/test_notifications.py /Users/les/Projects/oneiric/tests/domains/test_specialized_bridges.py`, `uv run ruff check /Users/les/Projects/oneiric/oneiric/adapters/queue/redis_streams.py /Users/les/Projects/oneiric/tests/adapters/test_redis_streams_queue.py` |
| 2026-05-10 | C1b | Mahavishnu Redis event transport wrapper, replay consumer, and WebSocket event bridge landed | `uv run pytest --no-cov tests/unit/test_event_transport.py tests/unit/test_event_contract.py tests/unit/test_event_envelope.py tests/unit/test_websocket_server.py`, `uv run ruff check mahavishnu/core/events tests/unit/test_event_transport.py tests/unit/test_event_contract.py tests/unit/test_event_envelope.py mahavishnu/websocket/server.py mahavishnu/websocket/integration.py tests/unit/test_websocket_server.py` |
| 2026-05-10 | C1b | Mahavishnu notification bridge now routes canonical envelopes through Oneiric `NotificationRouter` when notification metadata is present | `uv run pytest --no-cov tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py tests/unit/test_websocket_server.py`, `uv run ruff check mahavishnu/core/events/transport.py mahavishnu/websocket/integration.py tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py` |
| 2026-05-11 | C1b | Added retry wrappers and DLQ routing for exhausted event handler failures | `uv run pytest --no-cov tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py tests/unit/test_websocket_server.py`, `uv run ruff check mahavishnu/core/events/transport.py mahavishnu/websocket/integration.py tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py` |
| 2026-05-11 | C1b | TaskEventEmitter now publishes canonical `task.*` envelopes through the event transport when configured | `uv run pytest --no-cov tests/unit/test_task_notifications.py tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py`, `uv run ruff check mahavishnu/core/task_notifications.py tests/unit/test_task_notifications.py` |
| 2026-05-11 | C1b | MessageBus and RepositoryMessenger now publish canonical pool/repository envelopes through the event transport when configured | `uv run pytest --no-cov tests/unit/test_pools.py tests/unit/test_repository_messenger.py tests/unit/test_task_notifications.py`, `uv run ruff check mahavishnu/mcp/protocols/message_bus.py mahavishnu/messaging/repository_messenger.py mahavishnu/pools/manager.py mahavishnu/factories.py tests/unit/test_pools.py tests/unit/test_repository_messenger.py` |
| 2026-05-11 | C1b | Legacy EventBus publish/init APIs now emit deprecation warnings and point callers to the canonical envelope path | `uv run pytest --no-cov tests/unit/test_event_bus.py`, `uv run ruff check mahavishnu/core/event_bus.py tests/unit/test_event_bus.py` |
| 2026-05-11 | C1b | Health probe no longer constructs the legacy EventBus; it checks the canonical event transport availability instead | `uv run pytest --no-cov tests/unit/core/test_health.py tests/unit/test_event_bus.py`, `uv run ruff check mahavishnu/health.py tests/unit/core/test_health.py mahavishnu/core/event_bus.py tests/unit/test_event_bus.py` |
| 2026-05-11 | C1b | Removed the legacy EventBus module and dedicated event bus tests; updated migration docs to describe the archived event shape without the old module name | `uv run pytest --no-cov tests/unit/core/test_health.py tests/unit/test_event_envelope.py tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py tests/unit/test_task_notifications.py tests/unit/test_pools.py tests/unit/test_repository_messenger.py`, `uv run ruff check mahavishnu/core/events/migration.py mahavishnu/core/events/transport.py mahavishnu/websocket/integration.py mahavishnu/core/task_notifications.py mahavishnu/mcp/protocols/message_bus.py mahavishnu/messaging/repository_messenger.py mahavishnu/pools/manager.py mahavishnu/factories.py tests/unit/core/test_health.py tests/unit/test_event_envelope.py tests/unit/test_event_transport.py tests/unit/test_websocket_integration.py tests/unit/test_task_notifications.py tests/unit/test_pools.py tests/unit/test_repository_messenger.py` |
| 2026-05-11 | C6b | Collapsed the monitoring dashboard MCP tool into a compatibility wrapper over `ecosystem_status`, and marked the tool-version registry as deprecated in favor of the canonical status payload | `uv run pytest --no-cov tests/integration/test_mcp_tools.py tests/integration/test_ecosystem_contracts.py tests/unit/test_utility_modules.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/tool_versions.py tests/integration/test_mcp_tools.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Audited the duplicate learning/team-learning surfaces and confirmed they remain compatibility wrappers over the review-gated learning pipeline until parity tests and canonical skill-governance coverage are ready | `git diff --check` |
| 2026-05-11 | C6b | Started extracting runtime control-surface helpers from `core/app.py` into `core/control_surface.py` and bootstrap helpers into `core/bootstrap.py`, then moved config/repo loading plus adapter/context/terminal-manager initialization onto the bootstrap helper path so the composition root stays focused on wiring | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/control_surface.py mahavishnu/core/bootstrap.py tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `git diff --check` |
| 2026-05-11 | C6b | Extracted `mcp/bootstrap.py` and moved FastMCP terminal-manager initialization out of `mcp/server_core.py`, trimming server startup wiring while keeping tool registration behavior unchanged | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/bootstrap.py mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Extracted observability and health-endpoint initialization out of `core/app.py` into `core/bootstrap.py`, further reducing direct service construction in the composition root while preserving the same startup behavior | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/bootstrap.py mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Extracted the remaining runtime-service construction out of `core/app.py` into `core/bootstrap.py`, leaving the app constructor responsible for top-level orchestration wiring rather than service instantiation | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/bootstrap.py mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Removed the now-redundant Session-Buddy poller initializer from `core/app.py`; the poller setup is fully owned by `core/bootstrap.py` alongside the rest of the runtime-service wiring | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py tests/unit/test_session_buddy_poller.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/bootstrap.py mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Extracted HTTP health-route registration out of `mcp/server_core.py` into `mcp/bootstrap.py`, keeping the server constructor focused on composition while preserving `/health`, `/healthz`, and `/metrics` behavior | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Removed the redundant `FastMCPServer` health-route wrapper so the constructor calls the shared bootstrap helper directly, completing the current MCP bootstrap trim | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Extracted the profile-gated tool-registration orchestration out of `mcp/server_core.py` into `mcp/bootstrap.py`, so `start()` now just sequences startup and the bootstrap helper owns registration policy | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C6b | Removed the remaining `FastMCPServer` tool-group wrapper methods after moving registration policy into `mcp/bootstrap.py`, leaving the server class to focus on tool definitions and startup sequencing | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/mcp/server_core.py mahavishnu/mcp/bootstrap.py`, `git diff --check` |
| 2026-05-11 | C2 | Confirmed Dhara key schema helpers and threaded Dhara-backed pool/routing persistence plus recovery summary surfaces into the app and ecosystem status models | `uv run pytest --no-cov tests/unit/test_dhara_state_backend.py tests/unit/test_pools.py tests/unit/test_ecosystem_status.py`, `uv run ruff check mahavishnu/core/state_backends/dhara.py mahavishnu/pools/manager.py mahavishnu/factories.py mahavishnu/core/app.py mahavishnu/core/ecosystem_status.py tests/unit/test_dhara_state_backend.py tests/unit/test_pools.py tests/unit/test_ecosystem_status.py` |
| 2026-05-11 | C2 | Live app context now exposes recovery summary to the ecosystem tools and TUI when the app instance is present | `uv run pytest --no-cov tests/unit/test_dhara_state_backend.py tests/unit/test_pools.py tests/unit/test_ecosystem_status.py tests/unit/test_ecosystem_tools.py`, `uv run ruff check mahavishnu/core/state_backends/dhara.py mahavishnu/pools/manager.py mahavishnu/factories.py mahavishnu/core/app.py mahavishnu/core/ecosystem_status.py mahavishnu/core/context.py mahavishnu/mcp/tools/ecosystem_tools.py mahavishnu/tui/app.py tests/unit/test_dhara_state_backend.py tests/unit/test_pools.py tests/unit/test_ecosystem_status.py tests/unit/test_ecosystem_tools.py` |
| 2026-05-11 | C2 | Verified pool lifecycle operations continue to succeed when Dhara persistence throws, covering spawn, execute, route, and close degraded-mode behavior | `uv run pytest --no-cov tests/unit/test_pools.py`, `uv run ruff check tests/unit/test_pools.py` |
| 2026-05-11 | C2 | Workflow restart recovery now uses the Dhara workflow recovery helper and app startup tests prove running workflows and pending approvals survive restart replay | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_approval_manager.py tests/unit/test_dhara_state_backend.py`, `uv run ruff check mahavishnu/core/app.py tests/unit/test_app_recovery.py` |
| 2026-05-11 | C2 | Routing recovery now has a public app read API plus Dhara filtering coverage, with routing-decision recovery listed in the operator summary | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_dhara_state_backend.py`, `uv run ruff check mahavishnu/core/app.py tests/unit/test_app_recovery.py tests/unit/test_dhara_state_backend.py` |
| 2026-05-11 | C2 | Active docs and the Dhara addendum now describe Dhara as the durable recovery store for workflows, pools, routing, and approvals while keeping Session-Buddy session-local | `git diff --check` |
| 2026-05-11 | C2 | Durable operational state phase complete after routing recovery API, workflow/approval restart recovery, pool degraded-mode coverage, and docs boundary cleanup landed | `git diff --check` |
| 2026-05-11 | C3a | Added a live Recovery pane to the Textual cockpit and classified the remaining gaps across overview, sweep, routing, alerts, reviews, recovery, and session surfaces | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py` |
| 2026-05-11 | C3a | Added canonical registry-backed Reviews lookup fallback and a live Session pane for checkpoint posture; the cockpit now covers the remaining read-only surfaces | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py mahavishnu/core/app.py` |
| 2026-05-11 | C3a | Closed the cockpit reconciliation slice after the Session pane and registry-aware Reviews path landed, with read-only tabs now covering overview, sweep, routing, alerts, reviews, session, and recovery | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py mahavishnu/core/app.py` |
| 2026-05-11 | C3b | Added cockpit approvals, file previews/diffs, event activity, and Agno activity panes plus supporting app activity buffers and tests | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py tests/unit/test_event_transport.py tests/unit/test_adapters/test_agno_adapter.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/events/transport.py mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py tests/unit/test_event_transport.py` |
| 2026-05-11 | C3b | Added explicit approval-request/response forwarders to the cockpit so mutating actions stay behind durable approval APIs rather than direct UI writes | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py` |
| 2026-05-11 | C3b | Added the inline approval review/response flow in the cockpit approvals pane with approve/reject actions routed through the durable manager | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py` |
| 2026-05-11 | C3b | Closed the cockpit approvals/diffs/event/Agno slice after the actionable approval pane, event activity feed, and read-only file/diff views were verified | `uv run pytest --no-cov tests/unit/test_tui_dashboard.py`, `uv run ruff check mahavishnu/tui/app.py tests/unit/test_tui_dashboard.py` |
| 2026-05-11 | C4 | Reconciled docs/ECOSYSTEM counts and added catalog drift/freshness checks to `mahavishnu docs audit`, with role taxonomy and health-metadata validation aligned to the current ecosystem catalog | `uv run pytest --no-cov tests/unit/test_ecosystem.py tests/unit/test_ecosystem_cli.py tests/unit/test_audit_ecosystem_docs.py`, `uv run ruff check scripts/audit_ecosystem_docs.py mahavishnu/core/ecosystem.py mahavishnu/ecosystem_cli.py tests/unit/test_ecosystem.py tests/unit/test_ecosystem_cli.py tests/unit/test_audit_ecosystem_docs.py`, `uv run mahavishnu docs audit` |
| 2026-05-11 | C5-prep | Deterministic golden-path fixture, mock service contracts, trace assertions, and operator transcript packet added for the incident-to-fix contract harness | `uv run pytest --no-cov tests/unit/test_golden_path_contract.py`, `uv run ruff check tests/fixtures/golden_path_fixture.py tests/unit/test_golden_path_contract.py docs/reports/golden-path-contract-packet.md` |
| 2026-05-11 | C5 | Mocked incident-to-fix integration harness now exercises CoordinationMemory, fix orchestration, Session-Buddy checkpointing, Dhara persistence, and approval gating against the golden-path contract packet | `uv run pytest --no-cov tests/integration/test_golden_path_flow.py tests/unit/test_golden_path_contract.py`, `uv run ruff check tests/integration/test_golden_path_flow.py tests/fixtures/golden_path_fixture.py tests/unit/test_golden_path_contract.py` |
| 2026-05-11 | C5 | Opt-in live smoke test added for Session-Buddy checkpointing, Akosha memory/search, and Dhara durable-state persistence; skipped unless live service URLs are provided | `uv run pytest --no-cov tests/integration/test_golden_path_live_smoke.py`, `uv run ruff check tests/integration/test_golden_path_live_smoke.py` |
| 2026-05-11 | C5 | FixOrchestrator now defaults to app-managed pool, coordination, approval, and quality-control services so the CLI fix path uses existing service layers end-to-end instead of ad hoc construction | `uv run pytest --no-cov tests/unit/test_fix_orchestrator.py tests/unit/test_main_cli.py -k 'fix or workflow_fix'`, `uv run ruff check mahavishnu/core/fix_orchestrator.py tests/unit/test_fix_orchestrator.py` |
| 2026-05-11 | C5 | Fix orchestration now records session checkpoints, coordination-memory updates/search, and correlation-aware trace entries; the cockpit exposes the fix trace timeline for operator review | `uv run pytest --no-cov tests/unit/test_fix_orchestrator.py tests/integration/test_golden_path_flow.py tests/unit/test_tui_dashboard.py -k 'fix or golden_path or trace or correlation'`, `uv run ruff check mahavishnu/core/fix_orchestrator.py mahavishnu/core/app.py mahavishnu/core/coordination/memory.py mahavishnu/tui/app.py tests/unit/test_fix_orchestrator.py tests/integration/test_golden_path_flow.py tests/unit/test_tui_dashboard.py` |
| 2026-05-11 | C5/C6a | Closed the incident-to-fix golden path in the tracker, seeded the cross-repo deletion/adoption ledger, and advanced the umbrella plan to the shared-foundation adoption phase | `uv run pytest --no-cov tests/unit/test_fix_orchestrator.py tests/integration/test_golden_path_flow.py tests/unit/test_tui_dashboard.py -k 'fix or golden_path or trace or correlation'`, `git diff --check` |
| 2026-05-11 | C6a | Seeded the shared-foundation adoption matrix with event roles, WebSocket/event boundary tests, and migration-task framing for active repos | `git diff --check` |
| 2026-05-11 | C6a | Expanded the adoption matrix with concrete Oneiric, mcp-common, Crackerjack, and Session-Buddy task packets so later migration batches can attach exact module anchors | `git diff --check` |
| 2026-05-11 | C6a | Added explicit migration-task entries for Oneiric, mcp-common, Crackerjack, Session-Buddy, Akosha, Dhara, and mdinject to make the shared-foundation adoption ledger actionable | `git diff --check` |
| 2026-05-12 | C6b | Audited mcp-common for local service-copy deletions and found the server/auth/health/websocket surfaces are already the canonical shared foundation modules, so item 7 is now an audit-backed hold rather than an open deletion target | `rg -n "BaseOneiricServerMixin|create_runtime_components|get_availability_status|register_health_tools|FastMCPOpenTelemetryMiddleware" /Users/les/Projects/mcp-common/mcp_common /Users/les/Projects/mcp-common/tests`, `git diff --check` |
| 2026-05-11 | C6a | Added the first audit-backed Mahavishnu adoption transcript and promoted the learning/team-learning and composition-root rows from seed to audit-backed | `uv run mahavishnu docs audit`, `git diff --check` |
| 2026-05-11 | C6a | Landed Oneiric's canonical event-envelope helper and EventBridge emit path, plus mcp-common's shared-contract facade and regression coverage for websocket/auth/health primitives | `uv run pytest --no-cov tests/runtime/test_parity_prototypes.py tests/domains/test_specialized_bridges.py tests/runtime/test_notifications.py`, `uv run pytest --no-cov tests/test_contracts.py tests/auth/test_core.py tests/test_health.py tests/test_websocket_server.py`, `uv run ruff check oneiric/runtime/events.py oneiric/domains/events.py oneiric/tests/runtime/test_parity_prototypes.py oneiric/tests/domains/test_specialized_bridges.py mcp_common/contracts.py tests/test_contracts.py tests/test_websocket_server.py` |
| 2026-05-11 | C6a | Added the Crackerjack repo-local shared-contract facade, normalized websocket auth token handling for supported permission spellings, and broadened websocket channel ACLs to accept the current read/admin permission vocabulary | `uv run pytest --no-cov tests/test_websocket_auth.py tests/unit/test_websocket_auth.py tests/test_shared_contracts.py tests/adapters/test_provider_chain.py tests/test_health_check.py`, `uv run ruff check crackerjack/contracts.py crackerjack/websocket/auth.py crackerjack/websocket/server.py crackerjack/cli/handlers/health.py tests/test_shared_contracts.py tests/test_websocket_auth.py tests/unit/test_websocket_auth.py` |
| 2026-05-11 | C6a | Added Session-Buddy realtime subscriber hooks so the metrics websocket can fan out snapshots to external listeners without changing checkpoint persistence | `uv run pytest --no-cov tests/test_websocket_server.py`, `uv run ruff check session_buddy/realtime/websocket_server.py tests/test_websocket_server.py` |
| 2026-05-11 | C6a | Added Akosha Session-Buddy ingestion metadata normalization so correlation IDs survive writes into HotStore while keeping the derived-search boundary intact | `uv run pytest --no-cov tests/test_session_buddy_tools_coverage.py tests/unit/test_session_buddy_tools.py`, `uv run ruff check akosha/mcp/tools/session_buddy_tools.py tests/test_session_buddy_tools_coverage.py tests/unit/test_session_buddy_tools.py` |
| 2026-05-12 | C6b | Collapsed Akosha's duplicate health wrapper into the package entrypoint and removed the placeholder `get_storage_status` system tool so the live MCP surface stays focused on derived memory/search primitives | `uv run pytest --no-cov tests/unit/test_mcp_health_tools.py tests/unit/test_mcp_akosha_tools.py tests/unit/test_mcp_akosha_tools_simple.py`, `uv run ruff check akosha/mcp/tools/__init__.py akosha/mcp/tools/akosha_tools.py akosha/mcp/tools/profiles.py tests/unit/test_mcp_health_tools.py tests/unit/test_mcp_akosha_tools.py tests/unit/test_mcp_akosha_tools_simple.py`, `git diff --check` |
| 2026-05-12 | C6b | Removed the legacy `dhara.file_storage` shim and updated the compatibility test and migration docs so Dhara now only teaches `dhara.storage.file` for the file-storage backend | `uv run pytest --no-cov tests/test_compat.py tests/test_storage_file.py tests/test_main.py -k 'compat or file_storage or storage_server'`, `uv run ruff check tests/test_compat.py docs/MIGRATION_GUIDE.md docs/LEGACY_COMPATIBILITY_AND_REMOVAL_PLAN.md`, `git diff --check` |
| 2026-05-12 | C6b | Removed the top-level Dhara `connection` and `persistent*` compatibility shims, rewired `file_storage2` to `dhara.core.connection.ROOT_OID`, and updated the compatibility tests/docs to treat those shims as removed | `uv run pytest --no-cov tests/test_compat.py tests/test_file_storage2.py tests/test_storage_file.py tests/test_main.py`, `uv run ruff check dhara/file_storage2.py tests/test_compat.py tests/test_file_storage2.py`, `git diff --check` |
| 2026-05-11 | C6a | Added Dhara compatibility-shim coverage proving `dhara.file_storage` and `dhara.storage_server` stay importable while active code continues to use `dhara.storage.file` and the canonical server module | `uv run pytest --no-cov tests/test_compat.py tests/test_storage_file.py tests/test_main.py -k 'compat or file_storage or storage_server'`, `uv run ruff check tests/test_compat.py` |
| 2026-05-11 | C6a | Added the mdinject audit report and confirmed no direct Bodai event/session/memory/orchestration/storage dependency requires deletion in this phase; runtime remains client-surface only | `rg -n "event|session|memory|orchestration|storage|mcp|websocket|workspace|checkpoint|slack|discord" /Users/les/Projects/mdinject/mdinject /Users/les/Projects/mdinject/tests -g '!**/__pycache__/**'`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete Dhara `storage_server` compatibility shim after confirming active runtime imports use `dhara.server.server`; preserved the canonical server surface and the remaining `dhara.file_storage` shim for now | `uv run pytest --no-cov tests/test_compat.py tests/test_storage_file.py tests/test_main.py -k 'compat or file_storage or storage_server'`, `uv run ruff check tests/test_compat.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `core/dashboard_config.py` compatibility wrapper after moving dashboard model tests to `core.monitoring`, reducing one more duplicate surface without changing the canonical monitoring models | `uv run pytest --no-cov tests/unit/test_dashboard_config.py tests/unit/test_utility_modules.py`, `uv run ruff check mahavishnu/core/monitoring.py tests/unit/test_dashboard_config.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Completed the mdinject direct event/session/memory/orchestration/storage dependency audit with no deletion target identified | `rg -n "event|session|memory|orchestration|storage|mcp|websocket|workspace|checkpoint|slack|discord" /Users/les/Projects/mdinject/mdinject /Users/les/Projects/mdinject/tests -g '!**/__pycache__/**'`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `core/monitoring_infra.py` compatibility wrapper after moving monitoring tests to `core.monitoring`, preserving the canonical monitoring models and alert manager APIs only | `uv run pytest --no-cov tests/unit/test_monitoring.py tests/unit/test_monitoring_infra.py`, `uv run ruff check mahavishnu/core/monitoring.py tests/unit/test_monitoring.py tests/unit/test_monitoring_infra.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `ingesters/quality_evaluator.py` compatibility wrapper after moving ingester tests and package exports to `ingesters.quality_scorer`, reducing the content-quality surface to one canonical scorer module | `uv run pytest --no-cov tests/unit/test_quality_scorer.py tests/unit/test_utility_modules.py`, `uv run ruff check mahavishnu/ingesters/__init__.py tests/unit/test_quality_scorer.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `core/health_schemas.py` compatibility wrapper after moving health tools and tests to `core.health`, leaving only the canonical health/checkpoint module in active use | `uv run pytest --no-cov tests/unit/core/test_health.py tests/unit/core/test_health_schemas.py tests/unit/test_config_validation_cli.py tests/unit/test_mcp_utility_tools.py tests/unit/test_cli_extended.py tests/unit/test_main_cli.py`, `uv run ruff check mahavishnu/core/health.py mahavishnu/mcp/tools/health_tools.py tests/unit/core/test_health.py tests/unit/core/test_health_schemas.py tests/unit/test_config_validation_cli.py tests/unit/test_mcp_utility_tools.py tests/unit/test_cli_extended.py tests/unit/test_main_cli.py`, `git diff --check` |
| 2026-05-11 | C6b | Switched remaining runtime callers of `core.health_schemas` to `core.health` and removed the compatibility import warning surface from the utility tests | `uv run pytest --no-cov tests/unit/core/test_health.py tests/unit/core/test_health_schemas.py tests/unit/test_config_validation_cli.py tests/unit/test_mcp_utility_tools.py tests/unit/test_cli_extended.py tests/unit/test_main_cli.py tests/unit/test_utility_modules.py`, `uv run ruff check mahavishnu/mcp/tools/health_tools.py mahavishnu/cli/config_validator.py mahavishnu/health.py tests/unit/core/test_health.py tests/unit/core/test_health_schemas.py tests/unit/test_config_validation_cli.py tests/unit/test_mcp_utility_tools.py tests/unit/test_cli_extended.py tests/unit/test_main_cli.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the compatibility wrappers for `engines/prefect_adapter.py`, `engines/agno_adapter.py`, `engines/llamaindex_adapter.py`, and `mcp/otel_middleware.py` after moving core imports, factory paths, and tests to the canonical impl/telemetry modules | `uv run pytest --no-cov tests/unit/test_mcp_otel_middleware.py tests/unit/test_adapter_registry.py tests/unit/test_oneiric_client_fallback.py tests/integration/test_agno_adapter.py tests/integration/test_prefect_adapter.py tests/unit/test_context.py tests/unit/test_adapter_lifecycle_contract.py tests/unit/test_llamaindex_adapter.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/context.py mahavishnu/engines/prefect_adapter_impl.py mahavishnu/engines/agno_adapter_impl.py mahavishnu/mcp/server_core.py tests/unit/test_mcp_otel_middleware.py tests/unit/test_adapter_registry.py tests/unit/test_oneiric_client_fallback.py tests/fixtures/shell_fixtures.py tests/unit/test_adapters/README.md`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the redundant adapter package re-export shims under `adapters/workflow`, `adapters/ai`, and `adapters/rag` after confirming there were no live importers, leaving the canonical adapter implementations and direct package modules only | `uv run pytest --no-cov tests/unit/adapters/ai/test_pydantic_ai_adapter.py tests/unit/test_adapter_lifecycle_contract.py tests/unit/test_minimal.py`, `uv run ruff check mahavishnu/adapters/__init__.py tests/unit/adapters/ai/test_pydantic_ai_adapter.py tests/unit/test_adapter_lifecycle_contract.py tests/unit/test_minimal.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `mcp/server.py` wrapper after confirming all live MCP callers already use `mcp/server_core.py`, keeping the FastMCP server path canonical | `uv run pytest --no-cov tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py tests/integration/test_mcp_tools.py`, `uv run ruff check mahavishnu/mcp/server_core.py tests/unit/test_mcp_otel_middleware.py`, `git diff --check` |
| 2026-05-11 | C6b | Trimmed the eager adapter re-exports from `adapters/__init__.py` to keep only the package surfaces still used locally, and fixed registry test teardown so adapter-persistence SQLite connections close before the event loop shuts down | `uv run pytest --no-cov tests/unit/test_minimal.py tests/unit/adapters/ai/test_pydantic_ai_adapter.py tests/unit/test_adapter_lifecycle_contract.py tests/unit/test_adapter_registry.py tests/unit/test_adapter_registry_core.py`, `uv run ruff check mahavishnu/adapters/__init__.py tests/unit/test_minimal.py tests/unit/adapters/ai/test_pydantic_ai_adapter.py tests/unit/test_adapter_lifecycle_contract.py tests/unit/test_adapter_registry.py tests/unit/test_adapter_registry_core.py`, `git diff --check` |
| 2026-05-11 | C6b | Switched the OTel ingester to import Pgvector types directly from `adapters.pgvector_adapter`, removed the package-level Pgvector re-export, and added a package-surface regression test so the adapter package stays trimmed | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/unit/test_minimal.py tests/unit/test_adapter_registry.py tests/unit/test_adapter_registry_core.py`, `uv run ruff check mahavishnu/ingesters/otel_ingester.py mahavishnu/adapters/__init__.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Switched `mcp/tools/otel_tools.py` to import `OtelIngester` from the canonical module directly instead of the package re-export, reducing the last live `ingesters` package-level dependency in the tool path | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/unit/test_mcp_server_simple.py`, `uv run ruff check mahavishnu/mcp/tools/otel_tools.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Collapsed `ingesters/__init__.py` to a content-ingestion-only convenience surface after confirming OTel and quality exports were no longer used by live code, and added a package-surface regression test to keep the package trimmed | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/test_content_ingestion.py`, `uv run ruff check mahavishnu/ingesters/__init__.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Updated the OTel ingester README to use canonical module imports for `OtelIngester` and `create_otel_ingester`, so the docs now match the trimmed package surface | `rg -n "from mahavishnu\\.ingesters import OtelIngester|from mahavishnu\\.ingesters import create_otel_ingester" mahavishnu/ingesters/README.md`, `git diff --check` |
| 2026-05-11 | C6b | Removed the last content-ingestion package re-export usage by switching tests/examples/docstrings to `ingesters.content_ingester`, then emptied `ingesters/__init__.py` so the package no longer exposes convenience imports | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/test_content_ingestion.py`, `uv run ruff check mahavishnu/ingesters/__init__.py mahavishnu/ingesters/content_ingester.py tests/unit/test_utility_modules.py tests/test_content_ingestion.py examples/book_ingestion_example.py examples/web_ingestion_example.py examples/quick_test_otel.py examples/test_mcp_otel_tools.py examples/otel_ingester_example.py examples/quick_test_with_path.py`, `git diff --check` |
| 2026-05-11 | C6b | Rewrote the live and archived OTel/content docs to use canonical module imports instead of `mahavishnu.ingesters` package-level examples, aligning the documentation with the now-empty package surface | `rg -n "from mahavishnu\\.ingesters import" docs/ mahavishnu/ingesters/README.md`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `core.task_router` compatibility singleton aliases after confirming no live code or tests imported them, keeping the routing singleton surface canonical in `core.routing` only | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/unit/test_routing.py`, `uv run ruff check mahavishnu/core/task_router.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-11 | C6b | Deleted the obsolete `core.adapter_discovery` oneiric compatibility aliases after confirming no live code or tests referenced them, keeping discovery on the canonical Dhara path only | `uv run pytest --no-cov tests/unit/test_utility_modules.py tests/unit/test_adapter_discovery.py`, `uv run ruff check mahavishnu/core/adapter_discovery.py tests/unit/test_utility_modules.py`, `git diff --check` |
| 2026-05-12 | C6b | Removed the deprecated Crackerjack CLI alias options (`show_progress`, `advanced_monitor`, `coverage_report`, `clean_releases`) and rewired the canonical `track_progress` / `cleanup_pypi` flags in the CLI option model, entrypoint, profile handling, and focused tests | `uv run pytest --no-cov tests/unit/cli/test_cli_options.py tests/test_cli_entry_point.py tests/unit/cli/test_facade.py`, `git diff --check` |
| 2026-05-12 | C6b | Delegated Crackerjack health registration to `mcp-common.health.register_health_tools`, removed the local `mcp/tools/health_tools.py` wrapper, and kept the shared dependency defaults in `server_core.py` | `uv run pytest --no-cov tests/test_mcp_server.py tests/unit/cli/test_facade.py`, `uv run ruff check crackerjack/mcp/server_core.py crackerjack/mcp/tools/__init__.py tests/test_mcp_server.py tests/unit/cli/test_facade.py`, `git diff --check` |
| 2026-05-12 | C6b | Reconciled the Crackerjack service-root audit as a no-op for now: the CLI alias cleanup and `mcp/server.py` wrapper deletion are complete, and the remaining old service-root modules are live implementations rather than safe deletion targets | `rg -n "from crackerjack\\.(core\\.(performance_monitor|proactive_workflow|workflow_orchestrator|service_watchdog)|services\\.(performance_monitor|proactive_workflow|workflow_orchestrator|service_watchdog))|import crackerjack\\.(core\\.(performance_monitor|proactive_workflow|workflow_orchestrator|service_watchdog)|services\\.(performance_monitor|proactive_workflow|workflow_orchestrator|service_watchdog))" crackerjack tests`, `git diff --check` |
| 2026-05-12 | C6b | Trimmed the Session-Buddy monitoring package re-export so `register_prometheus_metrics_tools` is imported directly from the canonical module, keeping the remaining monitoring fan-out work focused on actual runtime ownership and subscriber wiring | `uv run pytest --no-cov tests/unit/test_server_tools.py tests/unit/test_serverless_mode.py tests/mcp/tools/test_ide_tools.py`, `uv run ruff check session_buddy/mcp/server.py session_buddy/mcp/tools/monitoring/prometheus_metrics_tools.py`, `git diff --check` |
| 2026-05-12 | C6b | Trimmed the Session-Buddy subscriber package re-export so `register_code_graph_tools` is imported directly from `subscribers.code_graph_subscriber`, keeping cross-system integration anchored on the concrete subscriber module | `uv run pytest --no-cov tests/unit/test_server_tools.py tests/unit/test_serverless_mode.py`, `uv run ruff check session_buddy/mcp/tools/__init__.py session_buddy/mcp/server.py`, `git diff --check` |
| 2026-05-12 | C6b | Delegated Session-Buddy health registration to `mcp-common.health.register_health_tools`, removed the local `mcp/tools/health_tools.py` wrapper, and kept the shared dependency defaults in `session_buddy/mcp/tools/__init__.py` | `uv run pytest --no-cov tests/unit/test_server_tools.py tests/unit/test_serverless_mode.py`, `uv run ruff check session_buddy/mcp/tools/__init__.py session_buddy/mcp/server.py`, `git diff --check` |
| 2026-05-12 | C6b | Collapsed the Session-Buddy storage registry compatibility shim by switching `SessionStorageAdapter` and lifecycle initialization to `storage_oneiric` directly, removing the old `storage_registry.py` module and the fallback branch | `uv run pytest --no-cov tests/unit/test_session_storage_adapter.py tests/unit/test_lifecycle_cleanup.py`, `uv run ruff check session_buddy/adapters/lifecycle.py session_buddy/adapters/session_storage_adapter.py session_buddy/mcp/tools/__init__.py session_buddy/mcp/server.py tests/unit/test_session_storage_adapter.py tests/unit/test_lifecycle_cleanup.py`, `git diff --check` |
| 2026-05-12 | C6b | Collapsed the Akosha health wrapper into the package entrypoint by deleting `mcp/tools/health_tools.py` and delegating to `mcp-common.health.register_health_tools`; the remaining `get_storage_status` cleanup stays open | `uv run pytest --no-cov tests/unit/test_mcp_health_tools.py tests/unit/test_mcp_akosha_tools.py`, `git diff --check` |
| 2026-05-12 | C6b | Extracted repository/role lookup, repo-path validation, health, workflow-gauge, and Dhara workflow-persistence helpers from `core/app.py` into `core/repository_surface.py`, keeping the composition root focused on wiring while preserving the public app methods | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_roles.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/repository_surface.py tests/unit/test_app_recovery.py tests/unit/test_roles.py`, `git diff --check` |
| 2026-05-12 | C6b | Continued the composition-root split by moving the remaining workflow-execution helpers in `core/app.py` into focused helpers, including workflow initialization, QC gating, session checkpoints, parallel repo processing, finalization, and error handling | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_roles.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/repository_surface.py tests/unit/test_app_recovery.py tests/unit/test_roles.py`, `git diff --check` |
| 2026-05-12 | C6b | Continued the composition-root split by moving the poller, learning-pipeline, and worktree-coordinator lifecycle helpers in `core/app.py` into `core/lifecycle.py`, keeping the public API intact | `uv run pytest --no-cov tests/unit/test_lifecycle.py tests/unit/test_app_recovery.py tests/unit/test_roles.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/lifecycle.py tests/unit/test_lifecycle.py`, `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C6b | Continued the composition-root split by moving MCP server start/stop and worktree-tool registration into `mcp/lifecycle.py`, keeping `server_core.py` focused on composition and tool wiring | `uv run pytest --no-cov tests/unit/test_mcp_lifecycle.py tests/unit/test_mcp_server.py tests/unit/test_mcp_server_simple.py tests/unit/test_mcp_otel_middleware.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/lifecycle.py mahavishnu/mcp/server_core.py mahavishnu/mcp/lifecycle.py tests/unit/test_mcp_lifecycle.py`, `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C6b | Continued Session-Buddy storage ownership cleanup by switching the remaining storage adapter test and doc examples to direct module imports from `session_buddy.adapters.session_storage_adapter` and `session_buddy.adapters.serverless_storage_adapter` | `uv run pytest --no-cov tests/unit/test_session_storage_adapter.py tests/unit/test_lifecycle_cleanup.py tests/unit/test_server_tools.py`, `uv run ruff check session_buddy/adapters/session_storage_adapter.py session_buddy/adapters/serverless_storage_adapter.py tests/unit/test_session_storage_adapter.py`, `git diff --check` |
| 2026-05-12 | C6b | Continued Akosha storage-assumption cleanup by changing the standard-mode and mode-package wording to treat cold storage as optional rather than the default primary posture | `uv run pytest --no-cov tests/unit/test_modes/test_standard_mode.py tests/unit/test_modes/test_base_mode.py tests/unit/test_modes/test_lite_mode.py`, `uv run ruff check akosha/modes/__init__.py akosha/modes/base.py akosha/modes/standard.py akosha/main.py tests/unit/test_modes/test_standard_mode.py`, `git diff --check` |
| 2026-05-12 | C6b | Continued Dhara storage-entry consolidation by documenting the canonical `dhara.storage.file.FileStorage` path separately from the legacy `dhara.file_storage2` file-format helper in the migration and removal plans | `git diff --check` |
| 2026-05-12 | C6b | Tightened the Dhara `file_storage2` boundary in the live entrypoint/tests so it is explicitly described as legacy DFS20 compatibility rather than a preferred storage path | `uv run pytest --no-cov tests/test_main.py tests/test_compat.py`, `uv run ruff check dhara/__main__.py tests/test_main.py tests/test_compat.py`, `git diff --check` |
| 2026-05-12 | C6b | Continued the `core/app.py` decomposition by moving the dependency-wait and Dhara recovery gating into `core/dependency_waiter.py`, keeping startup health validation and recovery triggers out of the composition root | `uv run pytest --no-cov tests/unit/test_dependency_waiter.py tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/dependency_waiter.py tests/unit/test_dependency_waiter.py`, `git diff --check` |
| 2026-05-12 | C6b | Closed the C6b complexity-reduction pass after finalizing the composition-root split and classifying the remaining Session-Buddy, Akosha, and Dhara storage/monitoring surfaces as resolved or compatibility-held rather than additional deletion targets | `uv run pytest --no-cov tests/unit/test_dependency_waiter.py tests/unit/test_app_recovery.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py tests/unit/test_adapter_package_surface.py tests/unit/test_session_storage_adapter.py tests/unit/test_lifecycle_cleanup.py tests/unit/test_server_tools.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/dependency_waiter.py tests/unit/test_dependency_waiter.py`, `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-11 | C7 | Retired the remaining ADR reference to `discover_from_oneiric_mcp` so the adapter-registry design notes now point at the canonical Dhara discovery path | `rg -n "discover_from_oneiric_mcp" docs/adr/009-hybrid-adapter-registry.md`, `git diff --check` |
| 2026-05-11 | C7 | Seeded a dedicated `worktree_manage` consolidation plan and kept `worktree_tools.py` on a documented retirement path instead of deleting it before consolidation exists | `git diff --check` |
| 2026-05-11 | C7 | Implemented `worktree_manage(...)`, kept the compatibility wrappers live, and updated the worktree docs/deprecation notes to point at the consolidated entry point | `uv run pytest --no-cov tests/unit/test_worktree_tools.py tests/integration/test_worktree_mcp_tools.py tests/unit/test_mcp_server_simple.py`, `uv run ruff check mahavishnu/mcp/tools/worktree_tools.py mahavishnu/mcp/server_core.py mahavishnu/mcp/tool_versions.py tests/unit/test_worktree_tools.py tests/integration/test_worktree_mcp_tools.py`, `git diff --check` |
| 2026-05-11 | C7 | Retired the legacy worktree wrapper entry points, leaving `worktree_manage` as the only active worktree MCP tool and closing the dedicated worktree consolidation plan | `uv run pytest --no-cov tests/unit/test_worktree_tools.py tests/integration/test_worktree_mcp_tools.py tests/unit/test_mcp_server_simple.py`, `uv run ruff check mahavishnu/mcp/tools/worktree_tools.py mahavishnu/mcp/server_core.py mahavishnu/mcp/tool_versions.py tests/unit/test_worktree_tools.py tests/integration/test_worktree_mcp_tools.py docs/WORKTREE_MANAGEMENT.md docs/reports/deprecation-migration.md`, `git diff --check` |
| 2026-05-12 | C6b | Continued the `core/app.py` decomposition by moving the workflow-execution helper block into `core/workflow_execution.py`, including workflow initialization, QC gating, session checkpoints, parallel repo processing, finalization, and error handling | `uv run pytest --no-cov tests/unit/test_app_recovery.py tests/unit/test_roles.py tests/unit/test_ecosystem_status.py tests/unit/test_tui_dashboard.py tests/unit/test_task_router_core.py tests/unit/test_approval_manager.py`, `uv run ruff check mahavishnu/core/app.py mahavishnu/core/repository_surface.py mahavishnu/core/workflow_execution.py`, `git diff --check` |
| 2026-05-12 | C7 | Reworded `docs/ECOSYSTEM.md` so `ecosystem.yaml` is described as canonical, `repos.yaml` is explicitly legacy compatibility, and Session-Buddy code-intel helpers are framed as shims rather than primary surfaces | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Updated the gateway/LLM inventory docs and bifrost runbook so Nanobot is treated as retired historical state rather than an active client, keeping only explicit compatibility notes where needed | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Marked the migration-note task complete after aligning the current docs and runbooks with the canonical repo manifest, canonical MCP surfaces, and retired Nanobot references | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |
| 2026-05-12 | C7 | Closed the documentation and retirement pass; the remaining historical references live only in archived plans and design notes, while the active queue is now terminal-only | `git diff --check`, `UV_CACHE_DIR=/private/tmp/uv-cache uv run mahavishnu docs audit` |

| 2026-05-11 | C6a | Started the Crackerjack validation-result and quality-gate report contract publication and added the Mahavishnu consumer bridge for the shared report shape | `git diff --check` |
| 2026-05-11 | C6a | Published the Crackerjack validation-result and quality-gate report contract module, and validated the Mahavishnu consumer bridge with contract-shaped payloads | `uv run pytest --no-cov tests/unit/test_validation_contracts.py`, `uv run pytest --no-cov tests/unit/test_fix_orchestrator.py`, `uv run ruff check crackerjack/models/validation_contracts.py crackerjack/models/__init__.py tests/unit/test_validation_contracts.py mahavishnu/core/fix_orchestrator.py tests/unit/test_fix_orchestrator.py`, `git diff --check` |
| 2026-05-11 | C6a | Closed the Crackerjack validation-result and quality-gate report contract work by wiring the Crackerjack websocket quality-gate surface to the new report shape and validating the updated producer/test surface | `uv run pytest --no-cov tests/unit/test_validation_contracts.py tests/unit/test_websocket_server.py`, `uv run ruff check crackerjack/websocket/server.py crackerjack/models/validation_contracts.py crackerjack/models/__init__.py tests/unit/test_validation_contracts.py tests/unit/test_websocket_server.py`, `git diff --check` |
| 2026-05-11 | C6b | Switched the live workflow authority from the deprecated `WorkflowState` module to `TaskRouter.StateManager`, kept the deprecated module only for compatibility tests, and validated the workflow-state state-manager CRUD path | `uv run pytest --no-cov tests/unit/test_task_router_core.py tests/unit/test_workflow_state.py tests/unit/test_task_router_and_auth.py -k 'WorkflowState or workflow_state or adapter_manager_and_state_manager_basics'`, `uv run ruff check mahavishnu/core/task_router.py tests/unit/test_task_router_core.py mahavishnu/core/app.py`, `git diff --check` |
