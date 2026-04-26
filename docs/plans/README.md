# Plans README

This directory contains active and historical planning documents for Mahavishnu and the Bodai ecosystem.

## Start Here

1. Current plan map, implementation priority, and supersession notes:
   - [PLAN_INDEX.md](./PLAN_INDEX.md)
2. Current Agno/Textual TUI and Bodai platform architecture:
   - [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md)
3. Current Agno/Textual TUI and Bodai platform implementation plan:
   - [2026-04-16-bodai-master-implementation-plan.md](./2026-04-16-bodai-master-implementation-plan.md)
4. Current ecosystem-health/control-plane implementation plan:
   - [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md)
5. Current ecosystem docs cleanup plan:
   - [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md)
6. Current type adapter migration plan:
   - [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md)

## Plan Categories

- `20YY-MM-DD-*.md`: dated architecture, review, or implementation plans.
- `initiatives/`: work-package plans from the 2026-04-04 ecosystem execution board.
- `reviews/`: focused review notes and audit findings.
- `archive/`: older implementation plans and completion reports.

## Current Authority

- Use [PLAN_INDEX.md](./PLAN_INDEX.md) as the source of truth for which plans are active, canonical, superseded, or historical.
- Use [2026-04-16-bodai-agent-platform-master-spec.md](./2026-04-16-bodai-agent-platform-master-spec.md) for Agno/Textual TUI boundaries.
- Use [2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md](./2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md) for ecosystem health, capability discovery, dashboard live-data wiring, and status normalization.
- Use [2026-04-25-ecosystem-docs-canonicalization-plan.md](./2026-04-25-ecosystem-docs-canonicalization-plan.md) for cross-repo docs cleanup and drift prevention.
- Use [2026-04-25-type-adapter-migration-plan.md](./2026-04-25-type-adapter-migration-plan.md) for `ty`, `pyrefly`, and `zuban` adapter refresh and AI-fix routing updates.

## Maintenance Rules

- Add new active plans to [PLAN_INDEX.md](./PLAN_INDEX.md).
- If a plan is superseded, leave a pointer in the old file or add it to the supersession map.
- Keep status labels aligned with code reality. A UI shell with placeholder data is `partial`, not complete.
- Prefer adding progress notes to existing active plans before creating new overlapping plans.
- Do not move or delete historical plans unless a separate archive cleanup is explicitly approved.
