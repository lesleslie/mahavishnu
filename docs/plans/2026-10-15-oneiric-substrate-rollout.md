---
status: active
role: umbrella
date: 2026-10-15
last_reviewed: 2026-10-15
superseded_by: null
blocks_on: []
topic: oneiric-substrate-rollout
title: "Oneiric Substrate Rollout — Consolidated Parent Plan"

---

# Oneiric Substrate Rollout — Consolidated Parent Plan

**Date:** 2026-10-15
**Status:** `active`, `umbrella`
**Purpose:** Consolidate the rollout of Oneiric substrate (`OneiricSettings.substrate.{cache,warm,cold,embedding,auth,pool}`) across the Bodai component repos. The substrate layer is shipped; the per-component adoption is the active work.

This is a **consolidation plan**, not a new workstream — the actual work is described in the three child plans below. This plan adds: (1) a single index of in-flight adoption; (2) a sequenced view of remaining gaps; (3) explicit `superseded_by` pointers so future readers see this umbrella.

## Child Plans

| Plan | Topic | Status (per 2026-10-15 audit) | Role in this umbrella |
|---|---|---|---|
| `2026-09-26-oneiric-runtime-config-registry.md` (removed) | Oneiric registry (`oneiric_report_runtime` MCP tool) + Mahavishnu push on boot | `partial` (Phases 1-2 done; Phase 3 component-boot hooks pending) | Foundation: other components push runtime facts into Oneiric on startup. |
| `2026-10-04-session-buddy-settings-oneiric-shape.md` (removed) | Convert `SessionMgmtSettings` → `SessionBuddySettings` (Oneiric-shaped) | `partial` (Phase 1 schema landed in session-buddy; Phases 2-3 consumer migration pending) | Session-buddy-side adoption of Oneiric substrate. |
| `2026-09-27-shared-bodai-substrate-phase-b.md` (removed) | SB Warm Tier = pgvector (oneiric PgvectorAdapter migration) | `stale-status` (work supplanted by Phase E2 substrate adoption + 2026-10-04 settings reshape) | Specifying earlier that the warm-tier migration is now partially absorbed — see Resolution Note. |

## Sequenced Remaining Work

1. **Finish Oneiric Phase 3 component-boot hooks** (runtime-config-registry plan):
   - `akosha/cli.py` and `session_buddy/cli/base.py` should call `oneiric_report_runtime` on startup
   - Crackerjack may need a similar hook
2. **Finish SessionBuddySettings consumer migration** (session-buddy settings plan):
   - Phase 2: load method + module helpers across session-buddy's 27 production files + 50 test files
   - Phase 3: YAML reshape + docs
3. **Defer Pgvector warm-tier migration** (substrate Phase B): supplanted by Phase E2 work; mark `superseded_by` 2026-10-04-session-buddy-settings-oneiric-shape.md

## Resolution Notes

- **`2026-09-27-shared-bodai-substrate-phase-b.md`** originally called for migrating SB's DuckDB VSS warm tier to oneiric's PgvectorAdapter. This work has been quietly supplanted by:
  - Phase E2 substrate adoption (commit `9c9ab67` for Akosha; `aeaa6800` for Session-Buddy embedding/auth)
  - `2026-10-04-session-buddy-settings-oneiric-shape.md` (the settings reshape)
  - The Pgvector migration script is no longer called for by any active plan; mark the original Phase B plan `superseded_by` the settings plan.

- **`2026-10-02-bodai-task-system-v1.1.md`** also touched substrate adoption via its lifespan-publisher work. The lifespan-publisher Cluster 3 resolution (separate commit `df418f54`) noted that v1.1's `_lifespan_with_dhara_cleanup` modification was superseded by `2026-10-04-session-buddy-lifespan-publisher-inline.md`'s `session_lifecycle` install path. v1.1's remaining work (orphan sweeper + subscriber patch) is OUT of this umbrella — it has its own dispatch path through `tasks_handoff_to_workflow`.

## Decision Rules

- **Add a new component to substrate?** Only after that component's settings class is Oneiric-shaped (per the session-buddy pattern).
- **Add a new runtime fact?** Only after `oneiric_report_runtime` is wired in the producing component's CLI bootstrap.
- **Mark a child plan superseded_by this umbrella?** Done for the three child plans (this umbrella is the canonical index).

## Acceptance Criteria

- Every Bodai core MCP server calls `oneiric_report_runtime` on startup
- Every Bodai core settings class extends `OneiricSettings` (or Oneiric-shaped)
- Phase E2 substrate adoption complete (cache/warm/cold/embedding/auth/pool) for Akosha + Session-Buddy
- Phase E2 substrate adoption verified for Mahavishnu + Crackerjack

## Provenance

Created by the 2026-10-15 plan audit (10-batch parallel workflow). Supersedes the consolidation suggestion in:

- Cluster 2 in the audit synthesis
- The `2026-09-27-shared-bodai-substrate-design-v5.md` spec's validation matrix (§9)
