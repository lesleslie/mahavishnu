---
status: active
role: implementation
date: 2026-07-15
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: convergence-control-plane
---

# Convergence Control Plane v1.0 — SOP Deferrals

This followup consolidates 6 design+implementation pairs that all defer
the v1.0 SOP layer of the Convergence Control Plane. Each topic below
shipped draft design + impl documentation, but no live SOP evidence
emerged in the 2026-09 / 2026-10 ecosystem window. Each pair is archived
together under this umbrella until a re-evaluation trigger fires.

## Deferred topics

| # | Topic | Plan (impl) | Spec (design) | Deferral reason | Re-evaluation trigger |
|---|-------|-------------|-------------------------------|------------------|--------------------------|
| 1 | Adapter Runtime Observability v1.0 | `docs/plans/.archive/2026-06-22-adapter-runtime-observability.md` | `docs/specs/.archive/2026-06-22-adapter-runtime-observability-design.md` | Crackerjack + Akosha already cover adapter runtime visibility; SOP tier redundant. | First user-visible complaint about adapter-runtime drift. |
| 2 | Live Observe (Presence Over Gate) v1.0 | `docs/plans/.archive/2026-06-22-live-observe-presence-over-gate.md` | `docs/specs/.archive/2026-06-22-live-observe-presence-over-gate-design.md` | CLI presence signal never wired; block only useful when paired with workspace token. | Token-based workspace ID surfaces. |
| 3 | Multi-Tenant Context Packs v1.0 | `docs/plans/.archive/2026-06-22-multi-tenant-context-packs.md` | `docs/specs/.archive/2026-06-22-multi-tenant-context-packs-design.md` | Mahavishnu is single-tenant; second tenant surfaces (e.g. cloud tenancy) needed before SOP. | First non-mahavishnu operator onboarded. |
| 4 | Precommitment Hypothesis Lock v1.1 | `docs/plans/.archive/2026-06-22-precommitment-hypothesis-lock.md` | `docs/specs/.archive/2026-06-22-precommitment-hypothesis-lock-design.md` | SOP gate can be skipped via direct-to-main; lock has no live enforcement path. | First hypothesis-lock incident. |
| 5 | Project-Scoped SOP Evolution v1.0 | `docs/plans/.archive/2026-06-22-project-scoped-sop-evolution.md` | `docs/specs/.archive/2026-06-22-project-scoped-sop-evolution-design.md` | SOP evolution is implicit via `crackerjack run`; no per-project override surfaces. | First request to fork SOP per-repo. |
| 6 | Three-Zone Skill Pipeline v1.0 | `docs/plans/.archive/2026-06-22-three-zone-skill-pipeline.md` | `docs/specs/.archive/2026-06-22-three-zone-skill-pipeline-design.md` | Skill registry is flat; zoning adds friction without observable need. | Skill count >500. |

## Re-evaluation rule

When ANY trigger column fires, the matching topic is unsuppressed:
1. Open a new plan under `docs/plans/YYYY-MM-DD-<topic>-resume.md`.
2. Reference this followup file and the archived siblings.
3. Update this table's row to (re-filed, in flight).

Until then, the 12 archived siblings stay in `.archive/` and remain
discoverable via the regenerator's body-index pass.
