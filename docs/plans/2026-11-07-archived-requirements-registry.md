---
status: active
role: canonical
kind: reference
date: '2026-11-07'
last_reviewed: '2026-11-07'
superseded_by: null
topic: archived-requirements-registry
title: Archived requirements registry — declarations carried forward from retired plans
requirements:
- id: REQ-MATH-001
  title: Queueing library exposes M/M/c fit and Kingman/Erlang-C wait-time prediction
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-002
  title: Queueing-theoretic wait estimate is an additive routing signal
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-003
  title: Predicted vs. observed wait time persisted alongside the routing-decision record
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-004
  title: Change-point library exposes CUSUM and Page-Hinkley with ARL₀ ≥ 10,000
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-005
  title: Change-point detector integrates with mahavishnu/core/observability.py
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-006
  title: Reference 3-sigma detector remains available as gated fallback alongside change-point
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-007
  title: Tier 2 and Phase D re-evaluation triggers implemented in scripts/feature_eligibility.py
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-008
  title: Per-pool arrival timestamps recorded at the route boundary
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-MATH-009
  title: Continuous metric sample stream available via new fixed-cadence sampler
  origin_plan: docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md
- id: REQ-ORC-001
  title: Routing fitness scoring respects affinity classes
  origin_plan: docs/plans/.archive/2026-08-29-orchestrator-research-synthesis.md
- id: REQ-ORC-002
  title: Pool routing strategies cover affinity, peer affinity, least-loaded, round-robin, random
  origin_plan: docs/plans/.archive/2026-08-29-orchestrator-research-synthesis.md
- id: REQ-ORC-003
  title: Multi-pool orchestration routes work across heterogeneous backends
  origin_plan: docs/plans/.archive/2026-08-29-orchestrator-research-synthesis.md
- id: REQ-ORC-004
  title: Cross-component orchestration includes Akosha, Dhara, Session-Buddy, Crackerjack integrations
  origin_plan: docs/plans/.archive/2026-08-29-orchestrator-research-synthesis.md
- id: REQ-ORC-005
  title: Health-aware pool selection can mark degraded pools unavailable
  origin_plan: docs/plans/.archive/2026-08-29-orchestrator-research-synthesis.md
- id: REQ-PI-001
  title: PiPool npx_command allowlist (rejects arbitrary binaries)
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-002
  title: PiPool implements BasePool ABC contract
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-003
  title: PiPool subprocess env stripping (sensitive keys never leaked)
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-004
  title: PiPool.scale raises NotImplementedError for n>1 (matches SessionBuddyPool)
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-005
  title: PiPool.start runs startup_self_test and records version
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-006
  title: PiPool.health_check exposes rpc_latency_ms and startup_self_test block
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-007
  title: PiPool.execute_task maps RPC errors to pool result shape
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-PI-008
  title: PiPool unit tests cover scale, env-stripping, npx-allowlist, and registry
  origin_plan: docs/plans/.archive/2026-09-07-pi-pool-backend.md
- id: REQ-SM-001
  title: Pluggable MergeStrategy enum on MahavishnuSettle.apply path
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-002
  title: Mergiraf shell-out driver with lazy first-call PATH probe
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-003
  title: Loud-failure MergeDriverUnavailableError when mergiraf missing under SEMANTIC
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-004
  title: Per-binding merge_strategy field in SettleRunRecord (Dhara-persisted)
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-005
  title: MahavishnuSettings.merge_driver_required startup guard (MahavishnuApp._init_observability)
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-006
  title: git-merge-tree --name-only diagnostic subprocess for SEMANTIC strategy (deferred)
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-007
  title: MergeStrategy serialization round-trip (to_dict → from_dict → equal)
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-008
  title: scripts/check_merge_driver.py probes binary + tree-sitter grammars + git version
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
- id: REQ-SM-009
  title: /health merge_driver.{available, binary, version, grammars, degraded_since}
  origin_plan: docs/plans/.archive/2026-09-10-settle-semantic-merge.md
---

# Archived requirements registry — declarations carried forward from retired plans

> **Why this file exists.** `scripts/audit_requirements.py` reads requirement
> declarations from plan frontmatter. The plans under `docs/plans/.archive/`
> hold declarations whose implementations are still live in this repository,
> but `.archive/` is **git-ignored and untracked** (`.gitignore`: `.archive/`),
> so those declarations exist only on machines that archived the plans
> locally. The audit now skips `.archive/` entirely, which is what makes its
> verdict identical on every machine — and it means these IDs need a tracked
> home, which is this file.
>
> Each entry names the retired plan that originally declared it. Edit the
> original plan if it still exists on your machine; edit nothing here unless
> you are correcting a title.
>
> **Regenerating.** The set is derived from the audit: every requirement ID
> referenced in this repository that no tracked plan declares. Re-run
> `python scripts/audit_requirements.py` after adding a plan and check that
> nothing new is undeclared.

**31 requirements carried forward.** Every one of them has a live
code reference in this repository, so none of them is an orphan.
