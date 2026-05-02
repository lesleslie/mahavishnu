# Bodai Ecosystem Improvement Roadmap

**Date**: 2026-05-02
**Status**: Proposal
**Scope**: Sharpen the Bodai ecosystem around Mahavishnu as the internal control plane

## Summary

The Bodai ecosystem already has the right system boundaries:

- **Mahavishnu** as the control plane
- **Session-Buddy** as the session and knowledge layer
- **Akosha** as the semantic retrieval layer
- **Dhara** as the durable storage and workflow distribution layer
- **Crackerjack** as the quality gate
- **Oneiric** and `mcp-common` as shared infrastructure

The next improvement phase should focus on operational maturity rather than inventing new top-level services. The highest-leverage work is to close the gap between planned architecture and production-ready control loops.

This roadmap proposes four priorities:

1. Replace stubbed or simulated control-plane integrations with real service-backed implementations.
2. Standardize ecosystem-wide auth, telemetry, and event contracts.
3. Promote cross-repo coordination and dependency tracking into a live operating system for the ecosystem.
4. Add code-index-backed reasoning so agents and workflows can act safely across repositories.

## Current Assessment

### What is already strong

- The repo roles and ecosystem boundaries are explicit in `settings/ecosystem.yaml`.
- Mahavishnu is already positioned clearly as the internal control plane in `README.md`.
- The ecosystem has existing plans for auth standardization, code indexing, and cross-repo coordination instead of starting from zero.
- The architecture is already MCP-first and multi-repo by design.

### What is currently weak

- Some key integrations still behave like placeholders instead of hard production dependencies.
- Shared concerns such as auth and audit are being standardized, but are not yet consistently enforced ecosystem-wide.
- Cross-repo coordination exists largely as configuration, documentation, and intent rather than as a consistently operated control loop.
- The ecosystem lacks a single canonical operational view for blockers, dependencies, workflow health, and approval state.
- Agent automation still has limited structural understanding of code impact across repos.

## Strategic Direction

The roadmap assumes the following operating stance:

- Keep **Mahavishnu** as the orchestrator, not the product shell.
- Push shared primitives into **Oneiric** and `mcp-common` where possible.
- Keep service-specific intelligence inside the domain service unless the concern is clearly cross-cutting.
- Optimize for ecosystem reliability, safe automation, and operator clarity before adding broader feature surface.

## Non-Goals

- Adding a new major top-level Bodai service.
- Repositioning Mahavishnu as a user-facing product shell.
- Replacing repo-local domain logic with an over-centralized control plane.
- Building dashboards before authoritative workflow and dependency state exists.

## Roadmap

## Phase 1: Harden the Control Plane

**Window**: 0-30 days

**Goal**: Remove the largest sources of architectural drift between documented capabilities and real execution.

### Workstreams

- Replace simulated Session-Buddy checkpoint behavior in `mahavishnu/session/checkpoint.py` with real service-backed persistence, retrieval, restore, and cleanup flows.
- Replace simulated Crackerjack QC behavior in `mahavishnu/qc/checker.py` with real quality gate execution, structured results, and failure propagation.
- Replace simulated repository messaging acknowledgments and status transitions with durable state handling where those paths affect orchestration decisions.
- Define canonical error contracts for cross-service calls:
  - unavailable dependency
  - degraded dependency
  - timeout
  - validation failure
  - policy rejection
- Add health-aware orchestration so Mahavishnu can distinguish:
  - safe to execute
  - execute in degraded mode
  - block execution and surface operator action
- Normalize service readiness and health reporting across Mahavishnu, Session-Buddy, Akosha, Dhara, and Crackerjack.

### Primary Repo Ownership

- `mahavishnu`
- `session-buddy`
- `crackerjack`
- `mcp-common`

### Success Criteria

- No control-plane integration remains "simulated" in the main execution path.
- Mahavishnu can surface actionable failure reasons when a dependency is unhealthy.
- QC results are structured, reproducible, and tied to actual tool execution.
- Session state and checkpoint restore behavior are durable enough for real orchestration recovery flows.

### Why this phase comes first

Without this phase, the ecosystem risks building more advanced automation on top of non-authoritative control loops. That would increase feature count while preserving weak operational guarantees.

## Phase 2: Standardize Trust, Audit, and Shared Contracts

**Window**: 30-60 days

**Goal**: Make inter-service communication safe, inspectable, and uniform.

### Workstreams

- Execute the shared auth migration described in `docs/superpowers/plans/2026-04-27-bodai-auth-standardization.md`.
- Move JWT verification, RBAC, audit event shapes, and service identity rules into `mcp-common`.
- Standardize request correlation IDs, actor identity, workflow IDs, and repository IDs across service boundaries.
- Define a shared event schema for:
  - workflow started
  - workflow completed
  - workflow failed
  - approval requested
  - approval granted or rejected
  - dependency degraded
  - QC passed or failed
- Align structured logging and OpenTelemetry attributes across the core services so traces are queryable as one system instead of as isolated repos.

### Primary Repo Ownership

- `mcp-common`
- `oneiric`
- `mahavishnu`
- `session-buddy`
- `akosha`
- `dhara`
- `crackerjack`

### Success Criteria

- All core Bodai services use the same auth primitives and permission vocabulary.
- Audit logs can answer who triggered what, against which repo, and under which workflow.
- Cross-service traces share enough identifiers to reconstruct an end-to-end orchestration flow.
- Adding a new ecosystem service no longer requires inventing a new auth or event model.

### Why this phase matters

This is what turns the Bodai ecosystem from "connected services" into a trustworthy internal platform. It also reduces future integration cost.

## Phase 3: Make Cross-Repo Coordination Operational

**Window**: 60-90 days

**Goal**: Turn cross-repo coordination from a plan and config concept into a real operator workflow.

### Workstreams

- Implement the core of `docs/CROSS_REPO_COORDINATION_PLAN.md` in Mahavishnu.
- Add first-class issue, todo, dependency, and plan management backed by authoritative ecosystem state, with `settings/ecosystem.yaml` and its coordination section remaining the canonical source where appropriate.
- Build dependency validation and blocker reporting directly into Mahavishnu CLI and MCP tools.
- Expose a single ecosystem status surface for:
  - active plans
  - critical blockers
  - repo health
  - pending approvals
  - degraded dependencies
  - outstanding QC failures
- Integrate Session-Buddy so coordination history and prior remediation paths are searchable.
- Connect Akosha so operators and agents can search ecosystem issues, plans, and failure patterns semantically.

### Primary Repo Ownership

- `mahavishnu`
- `session-buddy`
- `akosha`

### Success Criteria

- Operators can ask Mahavishnu what is blocked, what is failing, and what should happen next and get a single authoritative answer.
- Cross-repo dependencies are validated regularly rather than inferred manually.
- Coordinated work across multiple repos can be tracked as one workflow with durable state and auditability.
- Ecosystem planning artifacts stop fragmenting across markdown files, local notes, and memory, and instead resolve through one canonical coordination model.

### Why this phase matters

This is the phase that makes Mahavishnu feel like an actual control plane instead of just an orchestration toolkit.

## Phase 4: Add Code-Aware Automation and Safer Agent Work

**Window**: 90-120 days

**Goal**: Give the ecosystem structural code understanding so automation can reason about blast radius and dependencies before acting.

### Workstreams

- Execute the code graph integration path in `docs/superpowers/plans/2026-04-26-code-indexing-integration.md`.
- Let Session-Buddy own the ecosystem code graph and expose code call chain and impact analysis tools.
- Let Mahavishnu orchestrate indexing, incremental refresh, and operator-facing queries.
- Add pre-execution risk checks for automated changes:
  - call graph breadth
  - cross-repo symbol reach
  - hot files
  - stale index detection
- Feed code impact data into:
  - workflow planning
  - QC scoping
  - approval routing
  - rollback planning

### Primary Repo Ownership

- `session-buddy`
- `mahavishnu`
- `mcp-common`

### Success Criteria

- Agents can answer "what will this change affect?" across repos before execution.
- Mahavishnu can scope tests and validation based on actual dependency impact.
- High-blast-radius changes trigger stronger review and approval paths automatically.
- The code graph degrades gracefully when indexing is stale or incomplete.

### Why this phase matters

Without structural code awareness, ecosystem automation stays brittle and overly conservative. With it, the platform can automate more while reducing accidental damage.

## Cross-Cutting Investments

These should progress throughout all phases instead of being isolated to one window.

### Operator Experience

- Build one canonical operator view in Mahavishnu CLI and TUI.
- Prefer task-centric answers over repo-centric output.
- Make degraded mode explicit rather than hidden.

### Testing and Verification

- Add integration tests for real service boundaries, not just isolated happy paths.
- Add failure-injection tests for dependency outages, auth failures, and stale code graph states.
- Treat ecosystem-level tests as first-class validation targets.

### Documentation Hygiene

- Keep architecture docs synchronized with actual maturity.
- Mark prototype, simulated, or degraded paths clearly.
- Maintain one authoritative roadmap per major ecosystem initiative.

## Recommended Ownership Model

- **Mahavishnu**: orchestration, approvals, routing, cross-repo workflow state, operator surface
- **Session-Buddy**: session durability, memory, code graph, historical workflow context
- **Akosha**: semantic retrieval, correlation, and discovery across ecosystem artifacts
- **Dhara**: durable workflow configuration and storage-backed distribution concerns
- **Crackerjack**: quality gates, validation results, and enforcement hooks
- **Oneiric / mcp-common**: configuration, auth primitives, shared contracts, reusable infrastructure

## Sequencing Risks

- If auth standardization slips, later coordination and approval features will accumulate inconsistent trust boundaries.
- If code indexing starts before shared event and identity contracts are stable, downstream auditability will be weaker than it should be.
- If operator surfaces are built before authoritative state is in place, the ecosystem will produce polished but misleading dashboards.

## 30/60/90/120-Day Outcomes

### By Day 30

- Real checkpointing and QC integrations are in place.
- Dependency health and degraded-mode decisions are explicit.
- The main control-plane execution path is no longer dependent on simulated integrations.

### By Day 60

- Shared auth, RBAC, and audit contracts are live across the core services.
- Cross-service tracing can reconstruct full workflow paths.
- New service integrations have a standard trust and event model.

### By Day 90

- Cross-repo issues, blockers, and dependency status are queryable through Mahavishnu.
- Operators have one ecosystem status surface for execution, risk, and approvals.
- Session-Buddy and Akosha support historical and semantic coordination lookup.

### By Day 120

- Code impact and call-chain analysis inform workflow planning and review rigor.
- Test scope and approval rules can be derived from actual code graph reach.
- Safer, more autonomous ecosystem workflows become practical.

## Recommendation

Do not broaden the Bodai ecosystem by adding more major top-level services right now. The better move is to consolidate around the existing service map and make the current control-plane story fully real, shared, and inspectable.

The practical order is:

1. Harden real integrations.
2. Standardize trust and telemetry.
3. Operationalize cross-repo coordination.
4. Add code-aware automation.

That sequence increases reliability first, then leverage, then safe autonomy.
