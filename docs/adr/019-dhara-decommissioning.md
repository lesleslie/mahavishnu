---
status: complete
role: canonical
kind: decision
date: 2026-10-17
last_reviewed: 2026-10-17
superseded_by: null
blocks_on: []
related:
  - "docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md"
  - "docs/specs/2026-09-14-dhara-mcp-decomposition-design.md"
  - "docs/specs/.archive/2026-04-27-bodai-auth-standardization-design.md"
decision_date: 2026-10-17
topic: dhara-decommissioning
---

# ADR 019: Dhara Decommissioning from Bodai Core Fleet

## Status

<!-- legacy status: **Accepted** — see YAML frontmatter -->

**Accepted** on 2026-10-17.

Two scopes are involved, both shipped:

1. **Internal API surface (mahavishnu only)** — Dhara was retired from
   mahavishnu's local client surface as of 2026-10-15. The
   `dhara_client` constructor parameter on `LocalWorktreeProvider` was
   renamed to `mcp_client`; the placeholder `_FakeDharaClient` was
   removed in favor of the existing `_FakeMCPClient`. See commit
   `de1a383b`.
2. **Fleet release cadence (whole ecosystem)** — as of 2026-10-17, the
   user explicitly clarified that Dhara is still maintained by Bodai
   but is no longer a core component. The in-scope set for any fleet
   release probe becomes
   `{mahavishnu, akosha, session-buddy, crackerjack, oneiric, mcp-common}`
   — six repos, not seven.

**Date:** 2026-10-17

## Context

The Bodai ecosystem historically included seven core components:
mahavishnu (orchestrator), akosha (intelligence), session-buddy
(memory), crackerjack (quality), oneiric (foundation), mcp-common
(shared library), and dhara (storage substrate).

Two architectural movements brought Dhara's role into question:

- **The v4 substrate consolidation (2026-09-27)** migrated shared
  storage concerns into Oneiric. The Oneiric substrate spec
  (`docs/specs/2026-09-27-shared-bodai-substrate-design.md`) was
  written with the explicit posture that shared substrate primitives
  should live in Oneiric, not in Dhara. The substrate spec is now
  `partial` with `partially_superseded_by` chains pointing at the
  Oneiric rollout umbrella and the ollama→llama_server plan.
- **The Dhara MCP decomposition spec
  (`docs/specs/2026-09-14-dhara-mcp-decomposition-design.md`)** laid
  out a 12-phase plan to retire Dhara's surface area. Phases 1, 4, 6,
  and 8 effectively shipped during the Bodai Wave-2 cleanup window
  (2026-09-29 to 2026-10-13).

The substrate consolidation left Dhara without a fleet-level role to
play. The MCP decomposition left its public surface mostly retired.
The `mahavishnu-dhara-adapter-tool-boundary` ADR
(`docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md`) had already
established that `mcp__dhara__*` was the canonical surface for
catalog/state queries, but in practice the Oneiric substrate
(`mcp__oneiric__*`) has subsumed those concerns.

## Decision

Dhara is decommissioned as a core component of the Bodai ecosystem.
The decomposition has already shipped across the two scopes.

**Scope 1 — Internal API surface (mahavishnu):**

- `LocalWorktreeProvider(dhara_client=X)` →
  `LocalWorktreeProvider(mcp_client=X)` (rename-only, shipped in
  commit `de1a383b`).
- `_FakeDharaClient` placeholder removed; tests use `_FakeMCPClient`
  (already present in `tests/unit/test_oneiric_client_fallback.py`).
- No replacement class to instantiate — the Dhara-backed storage
  backend is gone.

**Scope 2 — Fleet release cadence:**

- All automated fleet probes (`bodai-radar`,
  `deployment-readiness-gate`, version-bump assessment,
  dependency-graph audit) must exclude Dhara from their in-scope set.
- The core component set is now
  `{mahavishnu, akosha, session-buddy, crackerjack, oneiric, mcp-common}`.
- Dhara is still maintained by Bodai and may ship its own tags on its
  own schedule. The component is not abandoned — its role in the
  fleet is changed.

## Consequences

### Positive

- Fleet release cadence is now a six-component coordination problem,
  not a seven-component one. Less coordination overhead, faster
  coordinated cuts.
- The `dhara-decommissioned-from-core` and
  `bodai-dhara-removed-from-mahavishnu-core` memory facts
  (Session-Buddy reflections) prevent accidental re-inclusion in
  future automated probes.
- Future Dhara-related work can proceed independently without
  coupling to fleet release schedules.
- The substrate consolidation (Oneiric substrate + substrate
  rollout umbrella) provides a single home for shared persistence
  concerns, reducing ambiguity about which component owns what.

### Negative

- Any downstream consumer that depended on Dhara via mahavishnu's
  internal client surface must use `mcp_client` instead. Migration
  path is documented in commit `de1a383b`.
- The `mahavishnu/CLAUDE.md` ecosystem table still lists Dhara; the
  description there has been stale since the v4 substrate
  consolidation (2026-09-27). Don't trust the port/role table for
  Dhara.
- The archived auth standardization spec
  (`docs/specs/.archive/2026-04-27-bodai-auth-standardization-design.md`)
  mentions Dhara in §10.1 migration-order (Step 6, "Medium risk,
  becomes reference"). The actual outcome is decommissioned, not
  "Done". Archived specs are immutable by convention; the new
  authoritative source for Dhara's status is this ADR.

## References

- `docs/specs/.archive/2026-04-27-bodai-auth-standardization-design.md`
  — archived spec; the §10.1 migration-order table still lists Dhara
  at Step 6, but the actual outcome is decommissioned.
- `docs/specs/2026-09-14-dhara-mcp-decomposition-design.md` —
  partially superseded (status `partial`); documents the original
  12-phase decomposition plan. Phases 1, 4, 6, 8 effectively
  shipped during Wave-2 cleanup.
- `docs/adr/013-mahavishnu-dhara-adapter-tool-boundary.md` —
  precursor ADR that established the tool boundary. ADR 019
  formalizes the retirement.
- `docs/specs/2026-09-27-shared-bodai-substrate-design.md` —
  substrate spec; `partially_superseded_by` chain documents the
  Oneiric substrate rollout that subsumed Dhara's role.
- `docs/plans/2026-10-15-mcp-server-fleet-modernization.md` —
  active umbrella plan that ships Phases 1, 4, 8 of the original
  decomposition.
- `docs/plans/2026-09-20-delete-all-dhara-named-code.md` —
  partially shipped plan for the crackerjack rename/delete work.
- `docs/plans/.archive/2026-09-20-bodai-layout-migration-and-registry-onboarding.md`
  — partially shipped plan for the Phase 1.5 wrapper consolidation.
- Commit `de1a383b` (2026-10-15) — the rename + drop in mahavishnu.
- Memory facts (Session-Buddy reflections):
  `dhara-decommissioned-from-core`,
  `bodai-dhara-removed-from-mahavishnu-core`.
