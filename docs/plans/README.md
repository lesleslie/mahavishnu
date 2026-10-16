---
status: active
role: canonical
kind: reference
date: 2026-07-16
last_reviewed: 2026-09-13
superseded_by: null
topic: convergence-control-plane
title: "Plans README"

---

# Plans README

This directory contains active and historical planning documents for Mahavishnu and the Bodai ecosystem.

## Start Here

1. Current plan map, implementation priority, and supersession notes:
   - [PLAN_INDEX.md](./PLAN_INDEX.md)
1. **Authority for topic-specific plans**: see `PLAN_INDEX.md` (it lists the current spec/implementation plan for each concern, including Agno/TUI architecture, ecosystem health, docs canonicalization, and type-adapter migration). The historical plans formerly linked from this README (2026-04-16 master spec/impl, 2026-04-25 ecosystem update / docs canonicalization / type-adapter migration, 2026-05-11 remaining-work queue) are now under `docs/plans/.archive/` and tracked from `PLAN_INDEX.md`.

## Plan Categories

- `20YY-MM-DD-*.md`: dated architecture, review, or implementation plans.
- `initiatives/`: work-package plans from the 2026-04-04 ecosystem execution board.
- `reviews/`: focused review notes and audit findings.
- `.archive/` (untracked): older implementation plans and completion reports moved out of the active tree per the 2026-10-14 untrack.

## Current Authority

- Use [PLAN_INDEX.md](./PLAN_INDEX.md) as the single source of truth for which plans are active, canonical, superseded, or historical. It enumerates the current spec/implementation plan for each concern (Agno/TUI boundaries, ecosystem health, docs canonicalization, type-adapter migration, etc.) — do not duplicate that mapping here.

## Maintenance Rules

- Add new active plans to [PLAN_INDEX.md](./PLAN_INDEX.md).
- If a plan is superseded, leave a pointer in the old file or add it to the supersession map.
- Keep status labels aligned with code reality. A UI shell with placeholder data is `partial`, not complete.
- Prefer adding progress notes to existing active plans before creating new overlapping plans.
- Do not move or delete historical plans unless a separate archive cleanup is explicitly approved.
