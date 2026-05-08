# Plan Index

**Date:** 2026-05-07
**Purpose:** Canonical map for finding, reviewing, and implementing active Mahavishnu/Bodai plans.

Use this file as the first stop before reviewing or implementing plan work. Older plans remain useful as source material, but the files below define the current review order and authority.

## Status Legend

- `canonical`: source of truth for an active area
- `implementation`: task-by-task build plan
- `active`: current or next implementation candidate
- `partial`: some code exists, but acceptance criteria are not complete
- `shipped`: all tasks complete, verified against codebase
- `historical`: useful background, not the current authority
- `superseded`: replaced by another file

## Review Entry Points

1. **Master backlog** ← start here

   - File: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md)
   - Status: `canonical`
   - Use for: the single authoritative list of confirmed open work, in priority order. All items verified against codebase 2026-05-07. Superseded/obsolete items moved to the backlog's closed table.

1. **Current plan map**

   - File: [PLAN_INDEX.md](./PLAN_INDEX.md)
   - Status: `canonical`
   - Use for: navigating individual plan files and their status.

1. **Repository plan overview**

   - File: [README.md](./README.md)
   - Status: `canonical`
   - Use for: quick orientation to plan categories.

1. **External review packet**

   - File: [REVIEW_PACKET_2026-04-02.md](./REVIEW_PACKET_2026-04-02.md)
   - Status: `historical`
   - Use for: third-party review workflow and older required reading order.

## Active Canonical Plans

### Bodai Agent Platform and Agno/Textual TUI

- Spec: [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
- Implementation plan: [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
- Status: `canonical`, `partial`
- Use for: Agno-backed interactive agent runtime, Textual TUI boundaries, engine ownership, learning pipeline boundaries, and implementation order.
- Current implementation note: Phase 0/Phase 1 governance and a read-only Textual dashboard shell exist, but Agno streaming, inline approvals, MCP-backed TUI data, file/diff panes, and richer session/skill views are not complete.

### Mahavishnu Ecosystem Control Plane

- Plan: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
- Status: `shipped` — all CP0–CP7 phases complete as of 2026-04-30
- Use for: canonical ecosystem status report, health contract cleanup, capability discovery, routing observability, and wiring the TUI to live read-only data.
- Delivered: `CanonicalStatus`, `EcosystemStatusService`, `EcosystemStatusReport`, `RoutingDecision` observability model, `RoutingDecisionBuffer`, `_collect_capabilities`, `_generate_recommendations`, `experiment_id` cardinality fix, `AdapterResolutionResult` rename. CLI (`mahavishnu ecosystem status/capabilities`), MCP tools (`ecosystem_status`, `ecosystem_capabilities`, `ecosystem_routing_readiness`), and TUI all wired to the canonical report.

### Ecosystem Docs Canonicalization

- Plan: [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md)
- Status: `shipped` — All phases complete (2026-04-30). `mahavishnu docs audit` wired; `scripts/audit_ecosystem_docs.py` is the backing implementation.

### Type Adapter Migration

- Plan: [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md)
- Status: `shipped` — all phases (0–3) complete as of 2026-04-30; `ty`, `pyrefly`, `zuban` adapters refreshed and canary-promoted
- Use for: reference only. All capability-based AI-fix routing is live in Crackerjack.

### Storage Consolidation and Akosha Role

- Plan: [2026-04-02-storage-consolidation-and-akosha-role.md](./2026-04-02-storage-consolidation-and-akosha-role.md)
- Status: `canonical`
- Use for: storage ownership, Akosha optionality, and consolidated storage architecture.

### Nanobot Worker Integration

- Plan: [2026-04-05-nanobot-worker-integration.md](./2026-04-05-nanobot-worker-integration.md)
- Status: `partial` — Phase B (`NanobotWorker` class, `WorkerManager` wiring, exports) complete; Phase A (`claude mcp serve` autostart via Supergateway) not started
- Use for: Phase A only — wiring `claude mcp serve` into the autostart script and `~/.claude.json`.

### Bodai Inter-Service Authentication

- Spec: [../superpowers/specs/2026-04-27-bodai-auth-standardization-design.md](../superpowers/specs/2026-04-27-bodai-auth-standardization-design.md)
- Plan: [../superpowers/plans/2026-04-27-bodai-auth-standardization.md](../superpowers/plans/2026-04-27-bodai-auth-standardization.md)
- Status: `complete` — shipped 2026-04-30, all 14 tasks done, all 6 repos pushed
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
- Status: `shipped` — all tasks complete as of 2026-05-01
- Delivered: `skill_mcp_validator.py` (stale-ref validator), `DriftReport`/`check_skill_agent_drift` wired into `mahavishnu config validate`, 15 agent descriptions enriched with ecosystem MCP refs, 28 active skills with "Available MCP Servers" sections, `akasha-specialist` renamed to `akosha-specialist`, validator skips `.archive/` by default.
- Use for: reference only.

### Superpowers Implementation Plans

#### Akosha Skills

- Plan: [../superpowers/plans/2026-04-14-akosha-skills.md](../superpowers/plans/2026-04-14-akosha-skills.md)
- Status: `shipped` — `code-archaeologist` and `quality-pulse` skills exist at `~/.claude/skills/code-archaeologist/SKILL.md` and `~/.claude/skills/quality-pulse/SKILL.md`
- Use for: reference only.

#### Bodai Radar

- Plan: [../superpowers/plans/2026-04-14-bodai-radar.md](../superpowers/plans/2026-04-14-bodai-radar.md)
- Status: `shipped` — skill exists at `~/.claude/skills/bodai-radar/SKILL.md`
- Use for: reference only.

#### Session Archaeologist

- Plan: [../superpowers/plans/2026-04-14-session-archaeologist.md](../superpowers/plans/2026-04-14-session-archaeologist.md)
- Status: `shipped` — skill exists at `~/.claude/skills/session-archaeologist/SKILL.md`
- Use for: reference only.

#### Code Indexing Integration

- Spec: [../superpowers/specs/2026-04-26-code-indexing-integration-design.md](../superpowers/specs/2026-04-26-code-indexing-integration-design.md)
- Plan: [../superpowers/plans/2026-04-26-code-indexing-integration.md](../superpowers/plans/2026-04-26-code-indexing-integration.md)
- Status: `shipped` — all 42 tasks complete as of 2026-04-30
- Use for: reference only. Call chain resolution, impact analysis, and incremental re-indexing are live.

#### Pattern Learning and Scaffolding

- Spec: [../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md](../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md)
- Plan: [../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md](../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md)
- Status: `shipped` — all 63 tasks complete as of 2026-04-30
- Use for: reference only. Pattern library, scaffolding engine, and Fastblocks pattern extraction are live.

#### Splashstand ACB → Oneiric Migration

- Spec: [../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md](../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md)
- Plan: [../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md](../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md)
- Status: `shipped` — all 43 tasks complete; 0 `from acb` imports remain in Splashstand codebase
- Use for: reference only.

### Hatchet Integration

- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priorities 7, 8, 10
- Status: `active` — P7 (rate-limiting pattern) and P8 (approval durable wait) are plan-only; P10 (HatchetAdapter) requires spec first
- Hatchet is an MIT-licensed durable task queue on Postgres (<20ms start, per-key rate limiting, WaitForEvent). P7 and P8 are pattern borrows (no SDK dependency). P10 adds `hatchet-sdk` and a full `OrchestratorAdapter` implementation gated on `adapters.hatchet: true`.
- Use for: P7/P8 implementation details are inline in the backlog. P10 spec file path: `docs/plans/2026-05-07-hatchet-adapter-spec.md` (to be written).

### OpenWebUI Integration

- Backlog: [2026-05-07-mahavishnu-master-backlog.md](./2026-05-07-mahavishnu-master-backlog.md) — Priority 9
- Status: `active` — Docker compose sidecar + tool registration, no Mahavishnu code changes
- OpenWebUI is a self-hosted web UI for LLMs; `mcpo` bridges Mahavishnu's MCP server (stdio/SSE) to Streamable HTTP for OpenWebUI consumption.
- Use for: P9 tasks are inline in the backlog. Output doc: `docs/integrations/openwebui.md`.

## Execution Board and Initiative Plans

- Board: [2026-04-04-ecosystem-execution-board.md](./2026-04-04-ecosystem-execution-board.md)
- Initiative index: [initiatives/README.md](./initiatives/README.md)
- Status: `historical`, `partial`
- Use for: previously prioritized 90-day execution board and initiative-level work packages.

Important reconciliation notes:

- Initiatives `00` through `15` are all complete as of 2026-04-30 (verified against initiative progress logs).
- I09 (Typed Event Envelope), I11 (Cache/Tiered Retrieval), I12 (Golden Paths), I14 (Grafana Alignment), I15 (Content Quality ML): all marked complete in their progress logs.
- I10 (Tool Retirement): I10-2 and I10-3 done; worktree tools consolidation deferred to v0.6.0 — treat as `partial`.
- I13 (Dashboard Phase 2): superseded and delivered by the Ecosystem Control Plane plan (CP0–CP7 shipped 2026-04-30).
- New ecosystem-health/dashboard work should start from the [ecosystem control plane update plan](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md), not directly from the older dashboard initiative.

## Current Implementation Priority

*Last verified: 2026-05-07. Canonical priority order is in the [master backlog](./2026-05-07-mahavishnu-master-backlog.md). The list below is a summary; the backlog is authoritative.*

**Active priorities (all open as of 2026-05-07):**

| # | Item | Plan / Spec |
|---|------|-------------|
| 1 | Session-Buddy Multi-Channel Tracking | [spec](./session-buddy-multi-channel-spec.md) |
| 2 | Dhara Storage Consolidation | [plan](./2026-04-02-storage-consolidation-and-akosha-role.md) |
| 3 | Config Consolidation (schema validation) | [spec](../superpowers/specs/2026-04-26-config-consolidation-design.md) / [plan](../superpowers/plans/2026-04-26-config-consolidation.md) |
| 4 | RunPod Pool — remaining subtasks | [plan](../superpowers/plans/2026-05-01-runpod-flash-pool.md) |
| 5 | Nanobot Phase A (Supergateway autostart) | [plan](./2026-04-05-nanobot-worker-integration.md) |
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

   - Plan: [2026-04-05-nanobot-worker-integration.md](./2026-04-05-nanobot-worker-integration.md)
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

- Superseded plan: [../../AGNO_ADAPTER_IMPLEMENTATION_PLAN.md](../../AGNO_ADAPTER_IMPLEMENTATION_PLAN.md) (phases 4-6 only)
- Reason: Phase 4 (ecosystem memory) → Session-Buddy + Akosha; Phase 5 (OTel) → `otel_ingester.py`; Phase 6 (pool integration) → existing pool system. Phases 1-3 shipped.
- Closed: 2026-05-07

## Review Checklist

Before implementing from any plan:

- Verify the plan is listed in this index as `canonical`, `active`, or `implementation`.
- Check whether the plan has a supersession entry.
- Check existing code before adding new abstractions.
- Update the relevant plan progress log when implementation changes status.
- Keep TUI work read-only unless a plan explicitly defines command forwarding through Mahavishnu.
- Keep external service ports, URLs, and credentials in configuration.
