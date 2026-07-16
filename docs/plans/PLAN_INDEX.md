# Plan Index

**Date:** 2026-05-07
**Last structural update:** 2026-07-15
**Last priority verification:** 2026-07-15
**Purpose:** Navigation map for finding and reviewing active Mahavishnu/Bodai plans.

Use this file as the first stop before reviewing plan work. Older plans remain useful as source material, but the authority matrix below defines which document owns each kind of decision.

## Status Legend

- Lifecycle: `draft` means not yet accepted for implementation; `active` means current or next implementation candidate; `partial` means some code exists but acceptance criteria are not complete; `shipped` means all tasks complete and verified; `complete` means cross-repo work is done but retained as reference.
- Role: `canonical` means source of truth for an active area; `implementation` means task-by-task build plan; `umbrella` means cross-plan tracker that references area plans; `historical` means useful background, not current authority; `superseded` means replaced by another file.
- Legal combinations should read as lifecycle + role, for example `draft, umbrella`, `active, implementation`, or `shipped, canonical`.

## Authority Matrix

| Concern | Authority |
|---|---|
| Plan navigation and current ownership | `PLAN_INDEX.md` |
| Current convergence phase status | `2026-05-10-bodai-control-plane-convergence-plan.md` |
| Cross-repo LLM provider defaults and Bifrost model routing | `2026-05-10-minimax27-provider-migration.md` |
| Area-local designs and detailed specs | The referenced area plan/spec |
| Legacy backlog item details | `2026-05-07-mahavishnu-master-backlog.md` |
| Scheduling priority after 2026-05-10 | Convergence plan C0-C7, once C0 is accepted |
| Current open work (2026-05-14) | `2026-05-14-doc-sync-and-channel-phase2.md` |
| Bodai agent platform implementation (I0–I4) | `2026-05-10-bodai-control-plane-convergence-plan.md` (operator cockpit C3a/C3b) and `2026-07-11-phase-6-bodai-observability.md` (cross-component observability). The 2026-04-16 master implementation plan is superseded. |
| Bodai-wide observability surfacing | `2026-07-11-phase-6-bodai-observability.md` |

The master backlog is retained as delivered/historical source material. New convergence implementation should not use the 2026-05-07 active-priority table as scheduling authority unless it is reverified and explicitly promoted.

## Review Entry Points

1. **Current plan map** ← start here

   - File: [PLAN_INDEX.md](./PLAN_INDEX.md)
   - Status: `active`, `canonical`
   - Use for: navigating individual plan files and their status.

1. **Convergence tracker** ← historical implementation record

   - File: [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md)
   - Status: `complete`, `historical`
   - Use for: the finished C0-C7 convergence program and its implementation record. Remaining terminal work is tracked separately in the remaining-work queue.

1. **Current open work** ← active plan

   - File: [../superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md](../superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md)
   - Status: `active`, `implementation`
   - Use for: doc status sync (PLAN_INDEX, hatchet checkboxes, P2 backlog, config consolidation, ARCHITECTURE.md) and Session-Buddy Channel Phase 2 Dhara time-series publishing.

1. **Remaining work execution order** ← historical execution record

   - File: [2026-05-11-remaining-work-execution-order.md](./2026-05-11-remaining-work-execution-order.md)
   - Status: `complete`, `historical`
   - Use for: the completed post-convergence execution queue. All tasks (T1/T4 terminal unification, C6a/C6b/C7 convergence cleanup) finished by 2026-05-13.

1. **MiniMax provider migration** ← provider-default implementation plan

   - File: [2026-05-10-minimax27-provider-migration.md](./2026-05-10-minimax27-provider-migration.md)
   - Status: `draft`, `implementation`
   - Use for: replacing ZAI/GLM defaults with MiniMax M2.7 text routing, supported MiniMax modality integrations or explicit modality deferrals, and cross-repo provider config updates in Mahavishnu, Bifrost, Crackerjack, and Session-Buddy.

1. **Master backlog** ← historical reference only

   - File: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md)
   - Status: `shipped`, `historical`
   - Use for: delivered backlog details and source material for convergence planning. The file states all priorities were delivered by 2026-05-08; it is no longer the scheduling authority for new convergence work.

1. **Repository plan overview**

   - File: [README.md](./README.md)
   - Status: `active`, `canonical`
   - Use for: quick orientation to plan categories.

1. **External review packet**

   - File: [REVIEW_PACKET_2026-04-02.md](./REVIEW_PACKET_2026-04-02.md)
   - Status: `shipped`, `historical`
   - Use for: third-party review workflow and older required reading order.

## Canonical And Active Plan Registry

### Doc Status Sync and Session-Buddy Channel Phase 2

- Plan: [../superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md](../superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md)
- Status: `active`, `implementation`
- Use for: the current work queue. Track A (Tasks 1–5): documentation housekeeping — PLAN_INDEX fixes, hatchet checkbox ticking, P2 backlog delivery notes, config consolidation sign-off, ARCHITECTURE.md Dhara section. Track B (Tasks 6–8): Session-Buddy Channel Phase 2 — `DharaChannelPublisher`, `register_channel_tracking_tools(dhara_publisher=)` wiring, `SESSION_BUDDY_DHARA_URL` env-var pickup in `server.py`.
- Current implementation note: open as of 2026-05-14; all prior convergence, terminal unification, and backlog work is complete.

### Bodai Control Plane Convergence

- Plan: [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md)
- Status: `complete`, `historical`
- Use for: the historical implementation record for the Bodai control-plane convergence program: unified event spine, durable operational state, live operator cockpit, catalog drift prevention, incident-to-fix golden path, cross-repo complexity reduction/deletions, and docs/retirement cleanup.
- Current implementation note: all C1-C7 phases are complete. Remaining terminal refactor work is tracked separately in `2026-05-11-remaining-work-execution-order.md`.
- Priority relationship: C1-C7 are complete. Update this index only when lifecycle status or canonical ownership changes.

### Remaining Work Execution Order

- Plan: [2026-05-11-remaining-work-execution-order.md](./2026-05-11-remaining-work-execution-order.md)
- Status: `complete`, `historical`
- Use for: historical record of the post-convergence execution queue. All tasks complete as of 2026-05-13: T1 (`TerminalWorkerProtocol` in `workers/protocol.py`), T4 (`TerminalAIWorker` collapsed to 65-line shim), C6a (Crackerjack validation contracts), C6b (complexity/deletion pass), C7 (docs retirement cleanup).

### MiniMax 2.7 Provider Migration

- Plan: [2026-05-10-minimax27-provider-migration.md](./2026-05-10-minimax27-provider-migration.md)
- Status: `complete`, `historical`
- Use for: replacing ZAI/GLM defaults with MiniMax M2.7 across Mahavishnu, Bifrost, Crackerjack, and Session-Buddy while preserving local fallback and routing only supported modality requests to current MiniMax modality APIs.
- Current implementation note: the sidecar provider migration is complete. Mahavishnu runtime defaults, Bifrost text routing, operator docs, Session-Buddy default-provider cutover, and Crackerjack provider support have all landed; C4/C5/C6 of the convergence plan should consume its results when catalog drift checks, golden-path tests, and deletion ledgers are updated.
- Source-verification note: MiniMax M2.7 is the text model family; modality routing uses MiniMax's current modality-specific models (`image-01`, `speech-2.8-*`, and `MiniMax-Hailuo-2.3*`) rather than invented M2.7 modality IDs.

### Bodai Routing Feedback Loop — Deployment Guide

- Plan: [2026-05-24-bodai-deployment-guide.md](./2026-05-24-bodai-deployment-guide.md)
- Status: `active`, `implementation`
- Use for: local vs serverless deployment patterns for Akosha, Mahavishnu, Dhara, and Session-Buddy. Covers pgvector setup, Oneiric env var naming, and standalone operation matrix.
- Current implementation note: Phase 5.3 doc-only. Phase 1.2 (SQL WHERE filtering) and Phase 5.1 (end-to-end test) still pending live infrastructure.

### Terminal Worker Unification

- Plan: [2026-05-10-terminal-worker-unification-plan.md](./2026-05-10-terminal-worker-unification-plan.md)
- Status: `complete`, `historical`
- Use for: historical record. All phases T0–T4 complete as of 2026-05-13. `TerminalWorkerProtocol` lives in `workers/protocol.py`; `TerminalAIWorker` is a 65-line shim over `GenericShellWorker`; registry-driven worker selection replaces all provider-name branching.

### Worktree Manage Consolidation

- Plan: [2026-05-11-worktree-manage-consolidation-plan.md](./2026-05-11-worktree-manage-consolidation-plan.md)
- Status: `complete`, `historical`
- Use for: historical record of the worktree MCP consolidation from six per-action tools into the single `worktree_manage` dispatcher.
- Current implementation note: the retirement track is complete; `worktree_manage` is the only active MCP entry point for worktree coordination.

### Bodai Agent Platform and Agno/Textual TUI

- Spec: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
- Implementation plan: [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
- Status: `superseded`, `historical` — superseded 2026-07-15 by [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md) and [2026-07-11-phase-6-bodai-observability.md](./2026-07-11-phase-6-bodai-observability.md)
- Use for: reference only. The convergence plan owns operator-cockpit convergence implementation (C3a/C3b) and Phase 6 owns the Bodai activity subscriber surface. The master implementation plan's remaining area-local work was either delivered through convergence or superseded by event-bridge-driven observability.
- Current implementation note: Phase 0/Phase 1 governance and the read-only operator cockpit surfaces are implemented via the convergence plan (C3a/C3b). The remaining area-local plan work is broader platform/runtime ownership beyond the cockpit slice, not the live read-only panes.
- Supersession relationship: the [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md) convergence plan owns C3a/C3b cockpit implementation; [2026-07-11-phase-6-bodai-observability.md](./2026-07-11-phase-6-bodai-observability.md) owns the cross-component observability surface. Future work in this domain should start from those documents, not the master implementation plan.

### Mahavishnu Ecosystem Control Plane

- Plan: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
- Status: `shipped`, `historical` — all CP0–CP7 phases complete as of 2026-04-30. Promoted 2026-07-15 after drift-sync verified all items complete.
- Use for: canonical ecosystem status report, health contract cleanup, capability discovery, routing observability, and wiring the TUI to live read-only data.
- Delivered: `CanonicalStatus`, `EcosystemStatusService`, `EcosystemStatusReport`, `RoutingDecision` observability model, `RoutingDecisionBuffer`, `_collect_capabilities`, `_generate_recommendations`, `experiment_id` cardinality fix, `AdapterResolutionResult` rename. CLI (`mahavishnu ecosystem status/capabilities`), MCP tools (`ecosystem_status`, `ecosystem_capabilities`, `ecosystem_routing_readiness`), and TUI all wired to the canonical report.

### Ecosystem Docs Canonicalization

- Plan: [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md)
- Status: `shipped`, `canonical` — All phases complete (2026-04-30). `mahavishnu docs audit` wired; `scripts/audit_ecosystem_docs.py` is the backing implementation.

### Type Adapter Migration

- Plan: [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md)
- Status: `shipped`, `canonical` — all phases (0–3) complete as of 2026-04-30; `ty`, `pyrefly`, `zuban` adapters refreshed and canary-promoted
- Use for: reference only. All capability-based AI-fix routing is live in Crackerjack.

### Storage Consolidation and Akosha Role

- Plan: [2026-04-02-storage-consolidation-and-akosha-role.md](./2026-04-02-storage-consolidation-and-akosha-role.md)
- Current addendum: [2026-05-07-dhara-state-backend-addendum.md](./2026-05-07-dhara-state-backend-addendum.md)
- Status: `active`, `canonical`
- Use for: storage ownership, Akosha optionality, and consolidated storage architecture.
- Convergence relationship: the 2026-05-07 Dhara addendum is the current authority for restart/recovery checkpoints. C2 in [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md) tracks implementation of remaining operational durability work.

### Nanobot Worker Integration

- Plan: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md#priority-5--nanobot-worker-phase-a-removed-2026-05-07)
- Status: `complete`, `historical` — Nanobot integration was removed from the codebase; the historical removal record lives in the master backlog.
- Use for: historical reference only.

### Bodai Unified Event Bus

- Spec + Implementation Plan: [2026-05-09-unified-event-bus-spec.md](./2026-05-09-unified-event-bus-spec.md)
- Status: `complete`, `historical`
- Use for: standardizing all Bodai event/messaging/notification systems on Oneiric's EventBridge + EventDispatcher + NotificationRouter, with Redis Streams as transport. Replaces Mahavishnu's `EventBus`, `TaskEventEmitter`, `MessageBus`, and `AlertChannel` with a single unified event bus. WebSocket becomes an EventBridge handler.
- Scope: Oneiric library integration, DLQ wiring, WebSocket handler, all notification adapters wired.
- Convergence relationship: implementation progress was tracked under C1a/C1b in [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md); the convergence plan is now the active implementation record and this spec is retained as historical design context.

### Bodai Inter-Service Authentication

- Spec: [../superpowers/specs/2026-04-27-bodai-auth-standardization-design.md](../superpowers/specs/2026-04-27-bodai-auth-standardization-design.md)
- Plan: [../superpowers/plans/2026-04-27-bodai-auth-standardization.md](../superpowers/plans/2026-04-27-bodai-auth-standardization.md)
- Status: `complete`, `historical` — shipped 2026-04-30, all 14 tasks done, all 6 repos pushed
- Use for: reference only. `mcp_common.auth` is now the canonical JWT package. See memory entry for API, env vars, and commit SHAs.
- Relationship: unblocks Phase 2 engine surface expansion. Must be implemented before adding new inter-service calls or promoting any service to production auth.

### Config Consolidation

- Spec: [../superpowers/specs/2026-04-26-config-consolidation-design.md](../superpowers/specs/2026-04-26-config-consolidation-design.md)
- Plan: [../superpowers/plans/2026-04-26-config-consolidation.md](../superpowers/plans/2026-04-26-config-consolidation.md)
- Status: `active`, `implementation`
- Use for: migrating all Claude Code configuration (agents, skills, settings, MCP server config) from global `~/.claude/` into the versioned `mahavishnu/.claude/` project directory for portability and multi-tool access.
- Relationship: prerequisite for Agent & Skill Modernization. Must run before enriching agent/skill content.

### Agent & Skill Modernization

- Spec: [../superpowers/specs/2026-04-26-agent-skill-modernization-design.md](../superpowers/specs/2026-04-26-agent-skill-modernization-design.md)
- Plan: [../superpowers/plans/2026-04-26-agent-skill-modernization.md](../superpowers/plans/2026-04-26-agent-skill-modernization.md)
- Status: `shipped`, `historical` — all tasks complete as of 2026-05-01
- Delivered: `skill_mcp_validator.py` (stale-ref validator), `DriftReport`/`check_skill_agent_drift` wired into `mahavishnu config validate`, 15 agent descriptions enriched with ecosystem MCP refs, 28 active skills with "Available MCP Servers" sections, `akasha-specialist` renamed to `akosha-specialist`, validator skips `.archive/` by default.
- Use for: reference only.

### Superpowers Implementation Plans

#### Constellation TUI (Bodai Activity in Claude Code)

- Spec: [../superpowers/specs/2026-07-15-constellation-tui-design.md](../superpowers/specs/2026-07-15-constellation-tui-design.md)
- Plan: [../superpowers/plans/2026-07-15-constellation-tui.md](../superpowers/plans/2026-07-15-constellation-tui.md)
- Status: `draft`, `implementation` — spec approved 2026-07-15; 10-task plan written, not yet executed
- Use for: surfacing Bodai ecosystem activity (pools, workers, workflows, lifecycle events) inside Claude Code via three extension surfaces — extended `statusLine`, new `subagentStatusLine`, and OSC 777 native toasts. New `mahavishnu/constellation/` subpackage + `mahavishnu constellation install` CLI. Wired to the existing EventBridge (channel `bodai:events`); no transport changes.
- Current implementation note: deferred per user direction (2026-07-15). Plan indexed for future pickup. Companion spec for the Toad/ACP track is at [2026-07-15-mahavishnu-acp-server-design.md](../superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md) — also deferred.

#### Mahavishnu ACP Server (Toad/Editor Integration)

- Spec: [../superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md](../superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md)
- Status: `draft`, `implementation` — spec approved 2026-07-15; implementation plan not yet written
- Use for: exposing Mahavishnu as an **ACP (Agent Client Protocol) server** so ACP clients (Toad, Zed, JetBrains, VS Code, future ACP tooling) can drive Mahavishnu directly via stdio JSON-RPC 2.0, alongside the existing A2A HTTP+SSE server. New `mahavishnu/acp/` subpackage with `mahavishnu acp serve` CLI command. EventBridge envelopes synthesize into ACP `session/update` notifications. `session/cancel` maps to Mahavishnu-side `asyncio.CancelledError`.
- Current implementation note: deferred per user direction (2026-07-15). Indexed for future pickup. Toad has no public A2A roadmap; ACP is the integration path. A2A server unchanged. MCP-over-ACP RFD follow-on when upstream lands.
- Relationship: complements the existing A2A server (`mahavishnu/a2a/server.py`) — second protocol, not replacement.

#### Akosha Skills

- Plan: [../superpowers/plans/2026-04-14-akosha-skills.md](../superpowers/plans/2026-04-14-akosha-skills.md)
- Status: `shipped`, `historical` — `code-archaeologist` and `quality-pulse` skills exist at `~/.claude/skills/code-archaeologist/SKILL.md` and `~/.claude/skills/quality-pulse/SKILL.md`
- Use for: reference only.

#### Bodai Radar

- Plan: [../superpowers/plans/2026-04-14-bodai-radar.md](../superpowers/plans/2026-04-14-bodai-radar.md)
- Status: `shipped`, `historical` — skill exists at `~/.claude/skills/bodai-radar/SKILL.md`
- Use for: reference only.

#### Session Archaeologist

- Plan: [../superpowers/plans/2026-04-14-session-archaeologist.md](../superpowers/plans/2026-04-14-session-archaeologist.md)
- Status: `shipped`, `historical` — skill exists at `~/.claude/skills/session-archaeologist/SKILL.md`
- Use for: reference only.

#### Code Indexing Integration

- Spec: [../superpowers/specs/2026-04-26-code-indexing-integration-design.md](../superpowers/specs/2026-04-26-code-indexing-integration-design.md)
- Plan: [../superpowers/plans/2026-04-26-code-indexing-integration.md](../superpowers/plans/2026-04-26-code-indexing-integration.md)
- Status: `shipped`, `historical` — all 42 tasks complete as of 2026-04-30
- Use for: reference only. Call chain resolution, impact analysis, and incremental re-indexing are live.

#### Pattern Learning and Scaffolding

- Spec: [../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md](../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md)
- Plan: [../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md](../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md)
- Status: `shipped`, `historical` — all 63 tasks complete as of 2026-04-30
- Use for: reference only. Pattern library, scaffolding engine, and Fastblocks pattern extraction are live.

#### Splashstand ACB → Oneiric Migration

- Spec: [../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md](../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md)
- Plan: [../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md](../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md)
- Status: `shipped`, `historical` — all 43 tasks complete; 0 `from acb` imports remain in Splashstand codebase
- Use for: reference only.

### Hatchet Integration

- Plan: [../superpowers/plans/2026-05-08-hatchet-adapter.md](../superpowers/plans/2026-05-08-hatchet-adapter.md)
- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priorities 7, 8, 10
- Status: `complete`, `historical`
- Use for: historical record. P7 (sliding-window `RateLimiter` in `task_router.py`), P8 (durable approval persistence via `ApprovalManager` + Dhara), and P10 (`HatchetAdapterImpl` in `mahavishnu/engines/hatchet_adapter_impl.py` with `WaitForEvent` approval bridge, `TaskCategory.AGENT_LOOP`) are all delivered as of 2026-05-08.

### Bodai Unified Exception Logging

- Design: [2026-05-23-unified-exception-logging.md](./2026-05-23-unified-exception-logging.md)
- Status: `complete`, `historical`
- Use for: structured `exception` dicts (AI-friendly) replacing `format_exc_info` string tracebacks across all Bodai components. Breaking change: `traceback_style="dict"` default for JSON output; Console uses `"string"` to avoid structlog 25.5.0 RichTracebackFormatter crash.
- Delivered: Oneiric `LoggingConfig` updated (`traceback_style`, `exc_show_locals`, `exc_max_frames`), Crackerjack migrated (3 call sites + dead-code cleanup), Session-Buddy `run_server()` startup call, Akosha CLI/main startup calls, Dhara full stdlib→structlog swap via Oneiric (preserving public API: `get_logger`, `log_operation`, `log_context`), all 26 Crackerjack logging tests passing.
- Current implementation note: complete as of 2026-05-23. `_configure_structlog_correlation` does NOT call `configure_logging` (prevents double-configure crash). Console output uses string tracebacks. Note: structlog 25.5.0's `log.exception()` outputs string rather than dict even with `traceback_style="dict"` configured — config is correct, behavior is a structlog version artifact.

### Bodai Routing Feedback Loop (OTel-based)

- Plan: [2026-05-23-bodai-routing-feedback-loop-v4.md](./2026-05-23-bodai-routing-feedback-loop-v4.md)
- Status: `active`, `implementation`
- Use for: Akosha polls OTel traces from all Bodai components via MCP → computes fitness signals (failure rate, p99 per task_class/selector) → writes to Dhara → Mahavishnu reads before each routing decision. Pull model; all components run standalone without requiring each other.
- Phase 1: pgvector hot store (Akosha) + env var wiring (Mahavishnu + Akosha) + query_local_traces SQL filtering
- Phase 2: BodaiComponentMCPClient + query_local_traces MCP tool on all components
- Phase 3: Akosha fitness analyzer + bounded buffer + DLQ
- Phase 4: Mahavishnu RoutingFitnessReader + pool integration
- Phase 5: end-to-end test + degradation verification
- Serverless: Akosha + Mahavishnu can run serverless (pgvector survives cold-starts); Dhara cannot (fcntl locks, hardcoded FileStorage) — separate future work item
- Current implementation note: Phases 0–5 complete as of 2026-05-30. Phase 5.1 (end-to-end test) verified functional — Akosha `run_fitness_analysis` successfully queries Dhara for `component_endpoint/mahavishnu`, calls `query_local_traces` via MCP, and returns traces. Phase 5.2 (graceful degradation) inherently verified by design — fallback behavior documented in deployment guide. Phase 5.3 (deployment guide) complete — `2026-05-24-bodai-deployment-guide.md` covers all deployment modes.

### OpenWebUI Integration

- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priority 9
- Status: `active`, `implementation` — Docker compose sidecar + tool registration, no Mahavishnu code changes
- OpenWebUI is a self-hosted web UI for LLMs; `mcpo` bridges Mahavishnu's MCP server (stdio/SSE) to Streamable HTTP for OpenWebUI consumption.
- Use for: P9 tasks are inline in the backlog. Output doc: `docs/integrations/openwebui.md`.

### Ultracode Integration Wiring

- Plan: [2026-07-11-ultracode-integration-wiring.md](./2026-07-11-ultracode-integration-wiring.md)
- Status: `partial`, `implementation` — many Phase 1/2/3 symbols shipped; remaining work is wiring, settings, CLI metrics, and Phase 4/5 deliverables
- Use for: hardening the boundary between Mahavishnu's control-plane primitives and ultracode's reasoning-plane primitives. Three phases: (1) diverse-refuter adversarial verification gate at the cross-repo / self-improvement proposal entry points, (2) opt-in loop-until-dry for `clone_detect_ecosystem` and `get_cross_project_patterns`, (3) MCP bridge completion — `dispatch_to_pool` MCP tool with `caller_kind`, `parent_session_id`, async-callback, and per-caller quota enforcement.
- Feature tracking: [verification-gate](../feature-tracking/2026-07-11-verification-gate.md), [loop-until-dry](../feature-tracking/2026-07-11-loop-until-dry.md), [dispatch-to-pool](../feature-tracking/2026-07-11-dispatch-to-pool.md). Tier 2 deferred ideas: [ultracode-tier2-parking-lot](../feature-tracking/2026-07-11-ultracode-tier2-parking-lot.md).
- Current implementation note: drift-sync on 2026-07-15 marked 11 stale-done items shipped (verification core + tests + get_verification_result, loop_helpers + tests, CallerKind + _caller_quota + caller_kind + parent_session_id in manager.py, dispatch_to_pool + pool_route_execute forwarding, mahavishnu-tool-preference-policy.md). Remaining work: settings (verification_*, caller_quota_*), CLI metrics (`mahavishnu metrics verification` / `dispatch`), decision docs (`dhara-key-prefixes-2026-07-11.md`), Phase 4 docstring/subagent/skill work, Phase 5 hook work. Companion to the Bodai Routing Feedback Loop plan.

### Shared Foundation Adoption Matrix

- Plan: [2026-05-11-shared-foundation-adoption-matrix.md](./2026-05-11-shared-foundation-adoption-matrix.md)
- Status: `shipped`, `historical` — C6a companion matrix; all rows populated. Promoted 2026-07-15 after drift-sync verified all items complete.
- Use for: reference only. Defines event adoption roles, WebSocket boundaries, and migration-task framing for the active repos in scope before C6a deletion batches could start.

### Bodai Deletion and Adoption Ledger

- Plan: [2026-05-11-bodai-deletion-adoption-ledger.md](./2026-05-11-bodai-deletion-adoption-ledger.md)
- Status: `shipped`, `historical` — C6a seed ledger; all rows have status. Promoted 2026-07-15 after drift-sync verified 0 unchecked items.
- Use for: reference only. Tracks cross-repo deletion/adoption candidates and their audit, parity, rollback, and release-note prerequisites.

### Phase 6 — Bodai-Wide Observability Surfacing

- Plan: [2026-07-11-phase-6-bodai-observability.md](./2026-07-11-phase-6-bodai-observability.md)
- Status: `shipped`, `historical` — all Phase 6 items checked off in the plan. Promoted 2026-07-15 after drift-sync verified all items complete.
- Use for: reference only. Defines the Bodai activity subscriber pattern that replaces Mahavishnu's per-component activity hook with a single canonical EventBridge subscriber.

### Oneiric EventEnvelope Wire Standardization

- Plan: [2026-07-14-oneiric-event-envelope-wire-standardization.md](./2026-07-14-oneiric-event-envelope-wire-standardization.md)
- Status: `shipped`, `historical` — all Tasks 0–9 shipped via commit f103bcc4 (merge bcc7affa). Promoted 2026-07-15 after drift-sync verified the merge commit on main.
- Use for: reference only. Standardizes Mahavishnu's cross-process EventBridge and Redis event records on Oneiric's `EventEnvelope` while preserving the in-process Pydantic contract. Includes the canonical boundary, decoder, and observability counters/logs.

### Cross-Repo Plans: Dhara Cache-Adapter Consolidation

The cache-adapter consolidation is a cross-cutting change between Dhara (the consumer) and Oneiric (the canonical cache-adapter owner). It was originally a single plan and has been split into two files in `dhara/docs/superpowers/{specs,plans}/`. Both are referenced here for navigation; the canonical design doc is the spec, the implementation is in the two plans.

#### Oneiric-side companion plan (executable now, independent of async-migration)

- Plan: [../../../dhara/docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md](../../../dhara/docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md)
- Spec: [../../../dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md](../../../dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md)
- Status: `active`, `implementation` — ready to execute now. Lives in the Oneiric repo; lands four commits (factory-string fix in `redis.py`/`memory.py`, two new `RedisCacheSettings` fields, `set`/`get` consumer code, companion tests) and direct-merges to Oneiric `main` per Bodai pre-1.0 policy.
- Use for: stripping the leading space from `AdapterMetadata.factory`; adding `ttl_seconds` and `stampede_jitter_ms` (with consumer code) to `RedisCacheSettings`; documenting the existing `enable_client_cache=True` default per spec D7. Stronger regression-guard tests parse the raw factory string and exercise `getattr(module, attr)` directly.

#### Dhara-side main plan (blocked on async-migration + companion)

- Plan: [../../../dhara/docs/superpowers/plans/2026-07-15-dhara-cache-adapter-oneiric-consolidation-plan.md](../../../dhara/docs/superpowers/plans/2026-07-15-dhara-cache-adapter-oneiric-consolidation-plan.md)
- Spec: [../../../dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md](../../../dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md)
- Status: `draft`, `implementation` — **blocked on external sequencing**. Cannot start until (a) `dhara/docs/2026-07-15-async-migration-cleanup.md` lands on Dhara `main`, AND (b) the Oneiric-side companion above has shipped. Both are preconditions verified explicitly by Phase 0 and Phase 1 of this plan.
- Use for: introducing `dhara/mcp/adapter_lookup.py:resolve_cache_adapter` (registry-mediated lookup reading `entry["factory_path"]` from `AsyncAdapterRegistry.get_adapter_async`); moving `_async_adapter_registry` initialization ahead of the cache block in `server_core.py`; deleting deprecated config fields; deleting `dhara/storage/redis_cache.py` only — `dhara/storage/memory.py` (`AsyncMemoryStorage`) is explicitly preserved. `Connection.Cache` (`dhara/core/connection.py:841`) remains out of scope per spec D8.

## Execution Board and Initiative Plans

- Board: [2026-04-04-ecosystem-execution-board.md](./2026-04-04-ecosystem-execution-board.md)
- Initiative index: [initiatives/README.md](./initiatives/README.md)
- Status: `partial`, `historical`
- Use for: previously prioritized 90-day execution board and initiative-level work packages.

Important reconciliation notes:

- Initiatives `00` through `15` are all complete as of 2026-04-30 (verified against initiative progress logs).
- I09 (Typed Event Envelope), I11 (Cache/Tiered Retrieval), I12 (Golden Paths), I14 (Grafana Alignment), I15 (Content Quality ML): all marked complete in their progress logs.
- I10 (Tool Retirement): I10-2 and I10-3 done; worktree tools consolidation deferred to v0.6.0 — treat as `partial`.
- I13 (Dashboard Phase 2): superseded and delivered by the Ecosystem Control Plane plan (CP0–CP7 shipped 2026-04-30).
- New ecosystem-health/dashboard work should start from the [ecosystem control plane update plan](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md), not directly from the older dashboard initiative.

## Current Implementation Priority

*Last priority verification: 2026-05-14. All backlog priorities (P0–P10), convergence phases (C0–C7), and the remaining-work execution queue (T1/T4) are complete.*

**Current implementation queue:** [Doc Status Sync and Session-Buddy Channel Phase 2](../superpowers/plans/2026-05-14-doc-sync-and-channel-phase2.md). This plan completes documentation housekeeping and implements Session-Buddy Channel Phase 2 (Dhara time-series publishing).

**After that plan completes, open work is:**

- OpenWebUI P9 manual UI steps (tool registration in OpenWebUI Admin, model arena run) — no code changes
- Bodai Agent Platform I4 optional extensions — gated on product justification document
- Ultracode integration wiring (draft) — three phases, see [2026-07-11-ultracode-integration-wiring.md](./2026-07-11-ultracode-integration-wiring.md)

**Historical priorities (open as of 2026-05-07, delivered by 2026-05-08 unless noted in the backlog):**

| # | Item | Plan / Spec |
|---|------|-------------|
| 1 | Session-Buddy Multi-Channel Tracking | [spec](./session-buddy-multi-channel-spec.md) |
| 2 | Dhara Storage Consolidation | [plan](./2026-04-02-storage-consolidation-and-akosha-role.md) |
| 3 | Config Consolidation (schema validation) | [spec](../superpowers/specs/2026-04-26-config-consolidation-design.md) / [plan](../superpowers/plans/2026-04-26-config-consolidation.md) |
| 4 | RunPod Pool — remaining subtasks | [plan](../superpowers/plans/2026-05-01-runpod-flash-pool.md) |
| 5 | Nanobot Phase A (Supergateway autostart) | plan |
| 6 | TUI Completion (command palette + skill drafts) | inline in backlog |
| 7 | Hatchet rate-limiting pattern | inline in backlog |
| 8 | Approval flow durable wait pattern | inline in backlog (requires P2) |
| 9 | OpenWebUI mcpo bridge | inline in backlog |
| 10 | HatchetAdapter (spec-first) | spec TBD (requires P2) |
| — | README update | final gate (after all above) |

*Completed items before 2026-05-07 are listed below for reference only.*

1. **Config Consolidation** — shipped 2026-04-30

   - Plan: [../superpowers/plans/2026-04-26-config-consolidation.md](../superpowers/plans/2026-04-26-config-consolidation.md)
   - Delivered: migration script, drift detection, inventory CLI commands, `.claude/` committed to project.

1. **Ecosystem Docs** — shipped 2026-04-30

   - Plan: [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md)
   - Delivered: `mahavishnu docs audit` CLI command wrapping `scripts/audit_ecosystem_docs.py`.

1. **Agent & Skill Modernization** — shipped 2026-05-01

   - Plan: [../superpowers/plans/2026-04-26-agent-skill-modernization.md](../superpowers/plans/2026-04-26-agent-skill-modernization.md)
   - Delivered: validator, DriftReport wired into `config validate`, 15 agents enriched, 28 skills with MCP sections, `akosha-specialist` rename.

1. **Nanobot Worker Phase B completion** — `shipped` 2026-05-02

   - Plan: 2026-04-05-nanobot-worker-integration.md
   - Delivered: `nanobot-ai>=0.1.4` dep (corrected from wrong `nanobot` robotics package), `_init_nanobot_provider()` fixed to use `ZAI_API_KEY` + `https://api.z.ai/api/coding/paas/v4`, `tests/unit/workers/test_nanobot_worker.py` (6 tests). `gpt4all` dep removed (ollama is the local inference backend).
   - Use for: reference only.

1. **Bodai Agent Platform I4 Optional Extensions** — gate: written product justification required per extension

   - Plans: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md), [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
   - Extensions: browser automation, plugin/hook system, public API-server mode, additional routing/fallback layers.
   - Do not start any I4 extension without first writing a product justification document.

### RunPod Flash Pool

- Plan: [../superpowers/plans/2026-05-01-runpod-flash-pool.md](../superpowers/plans/2026-05-01-runpod-flash-pool.md)
- Status: `shipped` — all 7 tasks complete, merged and pushed 2026-05-01
- Delivered: `mahavishnu/pools/runpod_pool.py` (`RunPodPool` implementing `BasePool` via `runpod-flash~=1.7`), registered in `PoolManager` factory as `pool_type="runpod"`, exported from `mahavishnu.pools`, `runpod_pool:` config stanza in `settings/mahavishnu.yaml` (disabled by default), `RUNPOD_API_KEY` documented in `CLAUDE.md`, 9 unit tests + 2 opt-in integration smoke tests.
- Use for: reference only. Subclass `RunPodPool` and override `_build_endpoint` to register a real GPU handler.

## Supersession Map

### TUI

- Superseded: [../superpowers/specs/2026-04-09-tui-design.md](../superpowers/specs/2026-04-09-tui-design.md)
- Canonical replacement: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)

### Bodai Master Implementation Plan

- Superseded: [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
- Reason: Phase 0/Phase 1 governance and the read-only operator cockpit surfaces were implemented under the convergence plan's C3a/C3b, and the cross-component observability surface lives in the Phase 6 plan. The master implementation plan's remaining area-local work has either been delivered through convergence or superseded by event-bridge-driven observability.
- Canonical replacements: [2026-05-10-bodai-control-plane-convergence-plan.md](./2026-05-10-bodai-control-plane-convergence-plan.md) and [2026-07-11-phase-6-bodai-observability.md](./2026-07-11-phase-6-bodai-observability.md)
- Closed: 2026-07-15

### Dashboard / Ecosystem Health

- Older initiative: [initiatives/13-dashboard-phase2-textual.md](./initiatives/13-dashboard-phase2-textual.md)
- Canonical next implementation plan: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)

### Health Contract

- Historical design:
  - [2026-02-27-health-check-system-design.md](./2026-02-27-health-check-system-design.md)
  - [2026-02-27-health-check-implementation-plan.md](./2026-02-27-health-check-implementation-plan.md)
- Completed initiative: [initiatives/01-health-contract-and-command.md](./initiatives/01-health-contract-and-command.md)
- Canonical cleanup/extension: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)

### TensorZero Gateway

- Superseded plan: [tensorzero-gateway-plan.md](./tensorzero-gateway-plan.md)
- Reason: Mahavishnu already has ZAI (primary), Bifrost (`openclaw_gateway.py`), mcp-common `llm/`, and `task_router.py`. A separate TensorZero process duplicates this stack without adding value.
- Closed: 2026-05-07

### Claw-Inspired Orchestration

- Superseded plan: [claw-inspired-orchestration-proposal.md](./claw-inspired-orchestration-proposal.md)
- Reason: All three patterns shipped under different names — verification loops → `quality_gate_manager.py`; event routing → `event_bus.py` + `event_store.py`; audit trails → `task_audit.py` + `statistical_router.py` + `unified_orchestrator.py`.
- Closed: 2026-05-07

### Agno Phases 4-6

- Superseded plan: ../../AGNO_ADAPTER_IMPLEMENTATION_PLAN.md (phases 4-6 only)
- Reason: Phase 4 (ecosystem memory) → Session-Buddy + Akosha; Phase 5 (OTel) → `otel_ingester.py`; Phase 6 (pool integration) → existing pool system. Phases 1-3 shipped.
- Closed: 2026-05-07

## Review Checklist

Before implementing from any plan:

- Verify the plan is listed in this index with a lifecycle + role status such as `active, implementation`, `draft, implementation`, `partial, canonical`, or `shipped, historical`.
- Check whether the plan has a supersession entry.
- Check existing code before adding new abstractions.
- Update the relevant plan progress log when implementation changes status.
- Keep TUI work read-only unless a plan explicitly defines command forwarding through Mahavishnu.
- Keep external service ports, URLs, and credentials in configuration.
