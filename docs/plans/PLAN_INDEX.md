# Plan Index

**Date:** 2026-04-26
**Purpose:** Canonical map for finding, reviewing, and implementing active Mahavishnu/Bodai plans.

Use this file as the first stop before reviewing or implementing plan work. Older plans remain useful as source material, but the files below define the current review order and authority.

## Status Legend

- `canonical`: source of truth for an active area
- `implementation`: task-by-task build plan
- `active`: current or next implementation candidate
- `partial`: some code exists, but acceptance criteria are not complete
- `historical`: useful background, not the current authority
- `superseded`: replaced by another file

## Review Entry Points

1. **Current plan map**
   - File: [PLAN_INDEX.md](./PLAN_INDEX.md)
   - Status: `canonical`
   - Use for: deciding which plan to review or implement next.

2. **Repository plan overview**
   - File: [README.md](./README.md)
   - Status: `canonical`
   - Use for: quick orientation to plan categories.

3. **External review packet**
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
- Status: `active`, `implementation`
- Use for: cleaning `docs/` directories across active ecosystem repos, separating current docs from archive material, and adding cross-repo docs drift checks.
- Relationship: should be run before broad implementation review so reviewers are reading current docs and not stale completion reports.

### Type Adapter Migration

- Plan: [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md)
- Status: `active`, `implementation`
- Use for: refreshing `ty`, `pyrefly`, and `zuban` adapters to current upstream docs and aligning AI-fix routing with native fix/suppress/baseline capabilities.
- Relationship: should be implemented before promoting `ty` or `pyrefly` out of experimental/canary usage.

### Storage Consolidation and Akosha Role

- Plan: [2026-04-02-storage-consolidation-and-akosha-role.md](./2026-04-02-storage-consolidation-and-akosha-role.md)
- Status: `canonical`
- Use for: storage ownership, Akosha optionality, and consolidated storage architecture.

### Nanobot Worker Integration

- Plan: [2026-04-05-nanobot-worker-integration.md](./2026-04-05-nanobot-worker-integration.md)
- Status: `active`
- Use for: nanobot worker integration and Claude MCP serve autostart work.

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
- Status: `active`, `implementation`
- Use for: enriching 15 agent descriptions with ecosystem MCP tool references, adding "Available MCP Servers" sections to all 22 native skills, fixing stale references, and wiring automated drift validation into `mahavishnu config validate`.
- Relationship: depends on Config Consolidation. Run after agents/skills are in the Mahavishnu project directory.

### Superpowers Implementation Plans

#### Akosha Skills

- Plan: [../superpowers/plans/2026-04-14-akosha-skills.md](../superpowers/plans/2026-04-14-akosha-skills.md)
- Status: `active`, `implementation`
- Use for: creating the Code Archaeologist and Quality Pulse Claude Code skills that compose Akosha MCP tools into focused discovery and trend-analysis workflows.
- Relationship: independent of TUI/auth work — can execute in parallel.

#### Bodai Radar

- Plan: [../superpowers/plans/2026-04-14-bodai-radar.md](../superpowers/plans/2026-04-14-bodai-radar.md)
- Status: `active`, `implementation`
- Use for: creating the Bodai Radar skill — a unified traffic-light health dashboard across all 5 Bodai network components in a single command.
- Relationship: independent — can execute in parallel. Supersedes ad hoc health checks.

#### Session Archaeologist

- Plan: [../superpowers/plans/2026-04-14-session-archaeologist.md](../superpowers/plans/2026-04-14-session-archaeologist.md)
- Status: `active`, `implementation`
- Use for: creating the Session Archaeologist skill — recovers past decisions, solutions, and session context from across all Session-Buddy instances via Akosha semantic search.
- Relationship: independent — can execute in parallel.

#### Code Indexing Integration

- Spec: [../superpowers/specs/2026-04-26-code-indexing-integration-design.md](../superpowers/specs/2026-04-26-code-indexing-integration-design.md)
- Plan: [../superpowers/plans/2026-04-26-code-indexing-integration.md](../superpowers/plans/2026-04-26-code-indexing-integration.md)
- Status: `active`, `implementation`
- Use for: call chain resolution, impact analysis, and incremental re-indexing for Mahavishnu. Session-Buddy owns the code graph; Mahavishnu provides CLI and query tools.
- Relationship: feeds into the ecosystem control plane (priority #2) by providing code-aware intelligence for health and routing.

#### Pattern Learning and Scaffolding

- Spec: [../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md](../superpowers/specs/2026-04-26-pattern-learning-scaffolding-design.md)
- Plan: [../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md](../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md)
- Status: `active`, `implementation`
- Use for: pattern library, scaffolding engine, and pattern extraction ("Lovable for Fastblocks"). Extracts web development patterns from existing projects and scaffolds new apps.
- Relationship: independent of TUI/control-plane work — can execute in parallel.

#### Splashstand ACB → Oneiric Migration

- Spec: [../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md](../superpowers/specs/2026-04-26-splashstand-oneiric-migration-design.md)
- Plan: [../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md](../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md)
- Status: `active`, `implementation`
- Use for: mechanical import rename across 17 Splashstand files. ACB → Oneiric, `depends.inject` → `resolve_dep()`, `dump`/`load` → `yaml`/`json` stdlib.
- Relationship: independent migration — can execute in parallel with Mahavishnu work.

## Execution Board and Initiative Plans

- Board: [2026-04-04-ecosystem-execution-board.md](./2026-04-04-ecosystem-execution-board.md)
- Initiative index: [initiatives/README.md](./initiatives/README.md)
- Status: `historical`, `partial`
- Use for: previously prioritized 90-day execution board and initiative-level work packages.

Important reconciliation notes:

- Initiatives `00` through `08` are marked complete in the board.
- Initiatives `09` through `15` remain open in the board.
- [initiatives/13-dashboard-phase2-textual.md](./initiatives/13-dashboard-phase2-textual.md) previously marked the Textual dashboard as complete, but current code shows a shell with placeholder data. Treat it as `partial` until live data acceptance criteria are met.
- New ecosystem-health/dashboard work should start from the [ecosystem control plane update plan](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md), not directly from the older dashboard initiative.

## Current Implementation Priority

1. **Plan reconciliation**
   - Plan: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
   - Phase: `0`
   - Goal: make active/superseded plan state explicit.

2. **Canonical ecosystem status**
   - Plan: [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
   - Phases: `1` through `3`
   - Goal: normalize health/status semantics and expose one CLI/MCP report.

3. **Live read-only TUI wiring**
   - Plans:
     - [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
     - [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
   - Goal: replace placeholder TUI data with MCP/backend data while preserving the TUI boundary.

4. **Agno/Textual interactive agent work**
   - Plans:
     - [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
     - [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
   - Goal: continue Phase 1 work after boundary and live-data surfaces are stable.

5. **Ecosystem docs canonicalization**
   - Plan: [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md)
   - Goal: make current docs, plans, specs, and runbooks easy to find across active repos.

6. **Type adapter migration**
   - Plan: [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md)
   - Goal: refresh type checker adapters and make AI-fix capability-aware.

7. **Splashstand ACB → Oneiric migration** (independent, parallel-safe)
   - Plan: [../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md](../superpowers/plans/2026-04-26-splashstand-oneiric-migration.md)
   - Goal: replace all ACB imports with Oneiric across 17 files in Splashstand.

8. **Pattern learning and scaffolding** (independent, parallel-safe)
   - Plan: [../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md](../superpowers/plans/2026-04-26-pattern-learning-scaffolding.md)
   - Goal: extract Fastblocks/Oneiric patterns from existing projects, scaffold new web apps.

9. **Code indexing integration** (feeds into control plane)
   - Plan: [../superpowers/plans/2026-04-26-code-indexing-integration.md](../superpowers/plans/2026-04-26-code-indexing-integration.md)
   - Goal: call chain resolution, impact analysis, incremental re-indexing for Mahavishnu.

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

## Review Checklist

Before implementing from any plan:

- Verify the plan is listed in this index as `canonical`, `active`, or `implementation`.
- Check whether the plan has a supersession entry.
- Check existing code before adding new abstractions.
- Update the relevant plan progress log when implementation changes status.
- Keep TUI work read-only unless a plan explicitly defines command forwarding through Mahavishnu.
- Keep external service ports, URLs, and credentials in configuration.
