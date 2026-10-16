---
status: active
role: canonical
kind: decision
date: 2026-10-15
last_reviewed: 2026-10-16
superseded_by: null
topic: archive-dir-canonical
---

# Archive directory canonical path: `docs/.archive/` (top-level)

## Context

The legacy top-level `docs/archive/` (no leading dot) directory was the
*original* convention for storing dated, historical, provenance-worthy
docs across the Bodai fleet. Over 2026 the convention drifted:

- **mahavishnu** uses no top-level archive dir at all (it stores history
  in `docs/decisions/` and `docs/plans/.archive/` / `docs/specs/.archive/`
  per the plans-specs-canonical decision).
- **crackerjack** runs both `docs/archive/` (309 files — bulk historical
  dumps, ADRs, design docs from the v1+v2 quality system era) AND
  `docs/.archive/` (62 files — newer convention, dated analysis).
- **akosha, session-buddy, mcp-common, oneiric** still use `docs/archive/`
  exclusively, each with a per-repo `README.md` (or `ACB_COMPARISON.md`
  / `BUILD_PROMPTS.md`) that establishes the archive policy:

  > *"Archived docs are retained for provenance, audits, migration
  >  history, and context recovery. They are not current authority unless
  >  a current plan or root `docs/README.md` explicitly points here.
  >  Generated files, coverage reports, tarballs, and temporary
  >  artifacts should not live here long-term."*

  — `akosha/docs/archive/README.md` and `mcp-common/docs/archive/README.md`
  (text identical, original authorship unclear — preserved verbatim).

The 2026-10-14 fast hook failure on oneiric
(`docs/archive/test-artifacts/coverage__20261014-104911.json`, 2.5 MB)
surfaced a separate but related problem: the archive namespaces were
**collecting test artifacts** (coverage JSONs, test-phase Python scripts)
that the per-repo READMEs explicitly say should NOT live there. Each
repo's `gitignore` covers coverage JSONs *only when the patterns match*;
oneiric's `coverage.json` (exact) and `.coverage*` (leading-dot) neither
match the offender's filename `coverage__20261014-104911.json`. The
result: re-staged coverage JSONs trigger `check-added-large-files`.

The two problems converge on the same fix: clean up the archive
namespace and evict the test artifacts that don't belong there.

## Decision rule

**1. Canonical archive location, top-level: `docs/.archive/`
(gitignored — NOT tracked in the repo).**

Per-repo, exactly one top-level archive directory. The legacy
`docs/archive/` (no leading dot) is **untracked from the repo**, not
renamed via `git mv`. The convergence operation is:

1. `git rm -r --cached docs/archive/` (untrack, keep on disk)
2. `mv` the on-disk content to `docs/.archive/`
3. `docs/.archive/` is already covered by the existing `.archive/`
   pattern in the bodai shared gitignore (line 77 in
   oneiric's `.gitignore`, mirrored across the fleet via
   `crackerjack/templates/GITIGNORE_BODAI.md`)

**`docs/.archive/` is operator-side scratch on local disk, NOT
tracked in the repo.** Crackerjack's publish gate enforces that
all `.archive/` directories are gitignored — re-including
`docs/.archive/` via `!docs/.archive/` would fail the publish gate.
The historical content is preserved on disk for operator reference
but lives outside the repo's tracked history. This is the
2026-10-16 amendment to this decision; the original 2026-10-15
draft assumed `docs/.archive/` would be tracked, which is incorrect
for repos under the cj publish gate.

`docs/.archive/` and the previously-decided nested archives
`docs/plans/.archive/` and `docs/specs/.archive/` coexist by design:

- `docs/plans/.archive/` and `docs/specs/.archive/` are the *tracked
  per-document* supersession paths for plans and specs (decision
  `2026-10-03-plans-specs-canonical-paths.md`).
- `docs/.archive/` is the *untracked bulk-provenance* location for
  dated analysis, historical designs, ADRs, decision-quality
  reviews, and similar.

They do not collapse into one another, and the tracked/untracked
status is a feature: plans/specs need revision history,
bulk-provenance does not.

**2. Test artifacts must NEVER live under `docs/.archive/`.**

Specifically:

- Coverage JSONs (`coverage*.json`, `coverage__*.json`, `coverage*.xml`)
- Test-phase Python scripts (`test_*.py`, `*.test.py`, ad-hoc verification
  scripts named `test_<thing>.py`)
- Any other generated artifact (`.tar.gz`, `.dump`, complexipy output,
  pytest-benchmark dumps)

The per-repo `tests/archived/` (or similar) pattern, the dot-prefixed
hidden cache directories, and the explicit `coverage/*` patterns are the
correct locations. Coverage outputs that operators want to retain live
in `coverage/` (the canonical pytest-cov output dir) or are explicitly
named in `.gitignore` with a glob.

**3. The README policy is a contract, not aspirational.**

The per-repo archive README is the *authoritative* statement of which
content belongs there. If a future operator proposes to put generated
output or test scripts into `docs/.archive/`, the README needs to be
updated **first**, and the change recorded in `docs/decisions/`.

## Migration (per repo)

| Repo | Pre-migration state | Post-migration action | Status |
|---|---|---|---|
| **mahavishnu** | none (clean) | Add defensive gitignore: `docs/archive/`. No file moves. | **pending** (deferred to operator) |
| **akosha** | `docs/archive/` (25 files, 6 subdirs: analysis, checkpoints, completion-reports, docs, implementation-plans + root README) | `git rm -r --cached docs/archive/` (untrack all 25); `mv` 6 subdirs + README on disk to `docs/.archive/`; `rmdir` empty `docs/archive/`. `.gitignore` already had `coverage*.json` and the recursive `.archive/` rule; added the missing `docs/archive/` defensive ignore (3 lines). **NOT** a `git mv` — would have tracked `docs/.archive/` and failed the cj publish gate. | ✓ landed at `17cfa20` on 2026-10-16 |
| **session-buddy** | `docs/archive/` (9 files, 3 subdirs: implementation-reports, summaries, test-artifacts) | `git rm -r --cached docs/archive/` (untrack all 9); `mv` 2 historical subdirs on disk to `docs/.archive/`; `rm` 2 test-artifacts (`test_phase4_mcp_with_db.py`, `test_qwen_integration.py`) from disk; `rmdir` empty subdirs. `.gitignore` added `coverage*.json` (line 54), `docs/archive/` defensive ignore (line 207), and removed a stale `docs/archive/test-artifacts/coverage__*.json` rule (dir gone). **NOT** a `git mv` — same reason. | ✓ landed at `9b62186c` on 2026-10-16 |
| **crackerjack** | `docs/archive/` (309 files, 22 subdirs) AND existing `docs/.archive/` (62 files, 7 subdirs) — **the merge case** | `git rm -r --cached docs/archive/` (untrack 309) + `git rm -r --cached docs/.archive/` (untrack 62 existing). On-disk merge: 11 legacy-only subdirs moved whole; 6 common subdirs (`analysis`, `audits`, `implementation-plans`, `implementation-reports`, `investigations`, `sprints-and-fixes`) merged with `mv -n` (no-clobber); 2 root files (`MAHAVISHNU_POOL_INTEGRATION.md`, `MAHAVISHNU_POOL_QUICKSTART.md`) moved. Evicted 128 test artifacts from `docs/archive/test-artifacts/`. Removed 4 stale `!docs/.archive/` and `!docs/.archive/**` negation rules via `git commit --amend` (would have re-tracked the canonical-gitignored location and failed cj publish gate; per-area negation rules for `docs/plans/.archive/`, `docs/specs/.archive/`, `docs/decisions/.archive/` were preserved unchanged). Added `coverage*.json` and `docs/archive/` defensive ignore rules. **1 filename collision** handled: `analysis/SESSION_CHECKPOINT_2025-01-30.md` existed in both legacy (7037 bytes) and existing (5766 bytes) with different content — legacy preserved at `.legacy.md` suffix. Worktree's `docs/.archive/` (243 files) copied to main checkout via Python no-clobber (181 new + 62 preserved = 244 total). | ✓ landed at `e4600fc0` on 2026-10-16 |
| **mcp-common** | `docs/archive/` (19 files, 4 subdirs: analysis, completion-reports, docs, + 2 root files `document-frontmatter-v1.md`, `topic-vocabulary-v1.md`) | `git rm -r --cached docs/archive/` (untrack all 19); `mv` 4 subdirs + 2 root files + README on disk to `docs/.archive/`; `rm` 1 test artifact (`test-artifacts/test_coverage_analysis.py`) from disk; `rmdir` empty subdirs. `.gitignore` added `coverage*.json`, broadened with `test_*.py`, and `docs/archive/` defensive ignore. **NOT** a `git mv` — same reason. | ✓ landed at `1c83641` on 2026-10-16 |
| **oneiric** | `docs/archive/` (30 files, 4 subdirs: analysis, implementation-plans, implementation-reports, summaries + 2 coverage JSONs in test-artifacts) | `git rm -r --cached docs/archive/` (untrack all 30); `mv` 28 historical files on disk to `docs/.archive/{analysis,implementation-plans,implementation-reports,summaries}/`; `rm` the 2 coverage JSONs (`coverage__20261014-104911.json` 2.5 MB + sibling) from disk; `rmdir` empty subdirs. Added `coverage*.json` gitignore pattern (catches the original `coverage__<date>-<time>.json` offender) and `docs/archive/` defensive ignore (regression prevention). **NOT** a `git mv` — would have tracked `docs/.archive/` and failed cj publish gate. | ✓ landed at `68732b7` on 2026-10-16 (fast-hook failure root cause) |

Implementation plan: `docs/plans/2026-10-15-archive-dir-canonical.md`.

## Fleet rollout

Per the merge workflow (`docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`):

1. **mahavishnu first** — drop the decision + plan docs (this document +
   the linked plan). Squash-merge to local `main`, auto-push.
2. **oneiric second** — the immediate failure source. Untrack test
   artifacts, rename, add the missing gitignore pattern. Squash-merge.
3. **crackerjack third** — the merge case. The largest diff (309 files
   in flight), but mechanically simple: `git rm --cached test-artifacts`
   then per-subdir `git mv` into existing `docs/.archive/`.
4. **akosha, session-buddy, mcp-common** — uniform rename + eviction.
   Order among them is arbitrary; the test-artifact eviction is the
   critical-path work.

Each per-repo commit is one squash-merge landing on that repo's
`main`. Per `feedback-bodai-push-is-user-controlled.md`: I never push;
the auto-push pipeline in `MAHAVISHNU_AUTO_MERGE=1` handles that when
the SessionEnd hook fires.

## Threat model

| Threat | Mitigation |
|---|---|
| Future operator regenerates a coverage JSON inside `docs/.archive/` and triggers the same fast hook | `crackerjack/templates/GITIGNORE_BODAI.md` adds `docs/.archive/test-artifacts/` (or per-pattern equivalents). `crackerjack gitignore sync` propagates fleet-wide. The per-repo archive README is the contract; deviations need a decision-record update. |
| The merge case (crackerjack) creates filename collisions in `docs/.archive/` after the per-subdir `git mv`s | Inventory `docs/archive/` top-level entries before the merge; check against existing `docs/.archive/` subdirs. The unique content set is dated historical material; the existing `.archive/` is dated analysis. Most likely no collision. If collision: rename the legacy path's content (e.g., `2026-08-06-ai-fix-removal-cleanup` → already prefixed) or move under a date-prefixed subdir. |
| An external document link points at `docs/archive/X` and breaks after rename | Per-repo grep for `docs/archive/` references before merge; sed across Markdown and the per-repo `CLAUDE.md`; record all references to be updated in the plan's per-repo phase. |
| Documentation removed by the migration (e.g., oneiric's `BUILD_PROMPTS.md`) cannot be recovered | `git log -- docs/archive/BUILD_PROMPTS.md` + reflog give 90-day recoverability per the plans-specs-canonical decision. The migration uses `git mv` (not delete), so the rename commits preserve history. |
| The per-repo README policy ("Generated files should not live here") is forgotten over time | The README is staged **post-rename** with updated wording that names the new path (`docs/.archive/`). The README + the decision doc are the duplicate-record pair. |
| A repo with no current top-level archive (`mahavishnu`) regresses by accident | Defensive gitignore (`docs/archive/`) — `git add` of a new `docs/archive/X.md` would fail the same hook that caught this issue, surfacing it at staging time instead of merge time. |

## Notes

- This decision does **not** affect `docs/plans/.archive/` or
  `docs/specs/.archive/`. Those are governed by
  `2026-10-03-plans-specs-canonical-paths.md`.
- The per-repo archive README policy ("retained for provenance,
  audits, migration history, and context recovery") is preserved on
  local disk at `docs/.archive/README.md` for repos that had a
  legacy `docs/archive/README.md`. The README + the decision doc
  are the duplicate-record pair; the README is now untracked
  (operator-side) rather than tracked.
- The test-artifact exception (`*.coverage.json`, `test_*.py`, etc.)
  is a permanent rule, not a per-migration cleanup.
- This decision is opt-in per repo: each operator decides whether to
  ship the rename now or defer to a follow-up PR. The plan's per-repo
  phases are independently mergeable.
- 90-day reflog: any file `git rm --cached`-ed during this migration
  stays recoverable via `git reflog` until 2027-01-13. Files
  preserved on local disk under `docs/.archive/` are immediately
  available (no reflog lookup needed) — only the `git log` history
  is gone for them.
- **2026-10-16 cj-publish-gate clarification**: the original
  2026-10-15 draft of this decision assumed `docs/.archive/` would
  be tracked (i.e., re-included via `!docs/.archive/` in `.gitignore`).
  The oneiric migration on 2026-10-16 revealed that Crackerjack's
  publish gate enforces all `.archive/` directories are gitignored.
  This decision is now updated to reflect that constraint. The first
  oneiric migration commit (`fed2195` on local branch
  `oneiric-archive-canonical-2026-10-16`, since superseded) used
  `git mv` to track the moves into `docs/.archive/`, which would
  have failed the cj publish gate. The corrected commit (`68732b7`)
  uses `git rm --cached` + on-disk `mv`, keeping `docs/.archive/`
  untracked. Future migrations of `akosha`, `session-buddy`,
  `crackerjack`, and `mcp-common` must follow the same pattern
  (untrack + on-disk move, not `git mv`).

## Cross-references

- **Sibling decision**: `2026-10-03-plans-specs-canonical-paths.md` —
  governs `docs/plans/.archive/` and `docs/specs/.archive/` (per-document
  supersession). This decision governs the top-level bulk-provenance
  archive; the two are non-overlapping.
- **Wire-up discipline**: `docs/decisions/mcp-backend-wiring-discipline.md`
  applies to operator-facing changes — this migration is mostly
  file-system, but per-repo `crackerjack run -v` is the integration
  contract for each phase.
- **Process discipline**: `docs/decisions/wire-up-contract.md` —
  per-plan-phase Integration Contract blocks are mandatory; see the
  linked plan.
- **Implementation plan**: `docs/plans/2026-10-15-archive-dir-canonical.md`.
- **Recent incident**: session-buddy's `2026-10-05 .gitignore.bak.*`
  pattern (referenced in the existing gitignore comments) — same
  pattern-miss class of bug, fixed there by adding the `.bak.*` infix
  pattern. This migration is the equivalent fix for the test-artifact
  class.
