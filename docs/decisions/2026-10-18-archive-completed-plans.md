---
status: active
role: canonical
kind: decision
date: 2026-10-18
last_reviewed: 2026-10-18
superseded_by: null
topic: archive-completed-plans
title: "Archive Policy for Completed Plans"
---

# Archive Policy for Completed Plans

## Context

The `docs/plans/` directory had accumulated 14+ plans with `status: complete` or
`status: superseded`, dating back to 2026-05. PLAN_INDEX regenerates mechanically
from frontmatter, so completed plans still show as rows in the active/archived
plan table. The `archive-dir-canonical` decision (2026-10-15) established that
`docs/plans/.archive/` is the canonical per-document archive path for plans,
but didn't codify *when* a plan should be archived.

## Decision rule

**1. A plan transitions to `shipped` only when verified in production.**

Per the canonical frontmatter vocab:

- `complete` — delivered; verification or follow-up may still be open
- `shipped` — delivered **and verified in production**; closed

A plan stays at `complete` while its umbrella has open children, while its
body lacks a "Verified complete YYYY-MM-DD" annotation, or while the
implementation has not landed on disk. Once verified, flip to `shipped`
and queue for archive on the next triage pass.

**2. Plans being archived must have `status: shipped` first.**

This is the gate. Mechanical "complete → archive" is not allowed; the
gate forces per-plan verification.

**3. Move archived plans to `docs/plans/.archive/` via `git rm --cached` + on-disk `mv` (NOT `git mv`, NOT `git add -f`).**

The `docs/plans/.archive/` directory is matched by the fleet-wide recursive
`.archive/` gitignore pattern (`crackerjack/templates/GITIGNORE_BODAI.md`),
so the archived plan is preserved on local disk for operator reference but
is untracked. This matches the `archive-dir-canonical` decision's convention:
`docs/.archive/` (untracked bulk-provenance) and `docs/plans/.archive/`
(per-document) are both untracked in practice; the distinction is path
semantics, not git tracking.

**4. Cross-references to archived plans must be updated in the same commit.**

Two patterns:

- **Umbrella body** — when an umbrella's child plan is archived, the child
  table should note "(removed and archived YYYY-MM-DD)" or similar. The
  umbrella's `superseded_by:` list of active plans should be canonical.
- **`related:` fields** — the `related:` frontmatter list is for *currently
  active* related work. If a related plan is archived, remove the reference
  or replace with a pointer to the umbrella or successor.

**5. Don't archive plans that are still in the PLAN_INDEX Authority Matrix.**

The Authority Matrix has hardcoded links to authority plans (e.g., the
Bodai-wide observability surface). Archiving an authority plan breaks the
Matrix link. For authority plans, either:

- Update the Authority Matrix to point at a different file (only if the
  work has truly moved)
- Add a redirect/pointer file at the archived path
- Defer the archive until the Authority Matrix has a stable non-archived home

**6. Plans with `role: umbrella` should be archived only when the umbrella is closed AND all child work is closed.**

Umbrellas track child work. An active child (e.g., a test backfill plan
referenced by the umbrella) means the umbrella is still doing useful
work. Archive the umbrella when its last child is `complete, superseded`
or `shipped`.

**7. Don't archive `draft` plans.**

Drafts are in-progress, not historical. A 99-day-old draft may be "stale"
but is not "completed" — archive is the wrong operation. The right
operations are: activate, park as `partial`, or supersede.

## Migration

The 2026-10-18 batch applied this policy to 10 plans. See the commit on
the same date. The deferred cases:

- `2026-09-14-common-mcp-client-transport-unification.md` (`complete,
  umbrella`) — held because the active child
  `2026-10-12-mcp-common-test-backfill.md` is still in flight.
- `2026-07-11-phase-6-bodai-observability.md` (`complete, implementation`)
  — held because it is the Authority Matrix link target for
  "Bodai-wide observability surface" (PLAN_INDEX line 50).
- `2026-09-20-delete-all-dhara-named-code.md` (`complete, implementation`,
  9 cross-references) — held pending cross-reference review.

## Cross-references

- **Sibling decisions:**
  - `2026-10-15-archive-dir-canonical.md` — establishes the per-doc
    archive path (`docs/plans/.archive/`) and the gitignore pattern.
  - `2026-10-03-plans-specs-canonical-paths.md` — governs plan/spec
    path conventions.
- **Canonical frontmatter vocab:** `docs/schemas/document-frontmatter-v1.md` —
  defines `complete` vs `shipped` distinction.
- **PLAN_INDEX behavior:** `scripts/regenerate_plan_index.py` lines 109,
  145, 149, 258 auto-skip `.archive/` — archived plans drop out of the
  index automatically.

## Notes

- The "complete" vs "shipped" distinction in the vocab is preserved. This
  decision codifies the *when*, not the *what*. The `complete` → `shipped`
  flip is a meaningful signal that the work is production-verified, and
  mechanical archiving would erase that signal.
- Archived plans remain queryable via `git log --follow` (if previously
  tracked) and via on-disk `find docs/plans/.archive/`. Operators
  searching for a past decision can still find it; the plan is just no
  longer noise in the active registry.
- This is a recurring rule, not a one-time operation. Future triage
  passes should apply this policy as new plans reach `shipped` status.
