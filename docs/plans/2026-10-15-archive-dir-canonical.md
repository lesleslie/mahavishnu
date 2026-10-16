---
status: active
role: canonical
kind: plan
date: 2026-10-15
last_reviewed: 2026-10-15
superseded_by: null
topic: archive-dir-canonical
title: "Archive Directory Canonical Migration Plan"
phase_state: "phase-1-not-started; phase-2-not-started; phase-3-not-started; phase-4-not-started; phase-5-not-started; phase-6-not-started; phase-7-not-started; phase-8-not-started"

---

# Archive Directory Canonical Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the fleet on `docs/.archive/` as the single top-level archive directory and evict test artifacts from archive namespaces. Implement the convention documented in `docs/decisions/2026-10-15-archive-dir-canonical.md`. End state: `check-added-large-files` passes fleet-wide; per-repo archive READMEs survive under the new path; bulk provenance material (historical analysis, ADRs, design docs) is retained.

**Architecture:** Per-repo `git mv` (rename) where the legacy `docs/archive/` exists alone; `git rm -r --cached <test-artifacts-subdir>` before the move to keep generated files out of the rename; per-subdir `git mv` for crackerjack's merge case (which already has both `docs/archive/` and `docs/.archive/`); gitignore hardening to catch test-artifact filenames the existing patterns miss.

**Tech Stack:** git (with `mv` semantics preserved across renames), `crackerjack run -v` (merge gate), `git check-ignore` (verification primitive), `grep` (reference sed across Markdown and per-repo CLAUDE.md).

**Spec:** `docs/decisions/2026-10-15-archive-dir-canonical.md`.

**Reference investigation:** `feedback-memories-must-be-dual-stored` and `feedback-keep-plan-files-tracked`; `feedback-mcp-common-version-bump-is-user.md` (no version bumps); `feedback-bodai-push-is-user-controlled.md` (no `git push`); `bodai-pre-1.0-merge-policy.md` (direct merge to main, no PRs); `feedback-git-commit-only-pathspec-with-staged-changes.md` (use `git commit -- <pathspec>` after `git add`, not bare `git commit`, when staging is partial).

## 1. Outcome

After all 8 phases land:

1. **Zero** repos have `docs/archive/` (legacy, no dot) as a tracked directory.
2. **5** Bodai core repos have `docs/.archive/` as the canonical archive (`mahavishnu` already clean; `akosha`, `session-buddy`, `crackerjack`, `mcp-common`, `oneiric` get it post-migration).
3. **Zero** tracked test artifacts under any `docs/.archive/test-artifacts/` (or pre-migration `docs/archive/test-artifacts/`) directory.
4. `git check-ignore -v` returns a match for `coverage__<digits>-<digits>.json` and `test_<phase>.py` patterns under any `docs/archive/**` path in every Bodai core repo.
5. `crackerjack run -v` (per repo) passes after each phase merge.
6. The fast hook `check-added-large-files` does not fire on coverage JSON test artifacts in any Bodai core repo (verified by `git add -A` of an empty-tree state, then `git stash`-style re-adding).
7. The per-repo archive README survives each migration intact (or is rewritten to reference the new path).

By end of phase 8, all 6 Bodai core repos converge on the same archive convention with no test-artifact leakage.

## 2. Goals

1. **Single canonical archive dir per repo.** `docs/.archive/` everywhere; `docs/archive/` exists nowhere.
2. **Fleet-wide gitignore hardening.** All coverage JSON patterns, all test-script patterns under `docs/.archive/**` ignored.
3. **No test artifact in version control.** `git ls-files` returns empty for `docs/.archive/test-artifacts/**` fleet-wide.
4. **Verification by hook re-run.** `check-added-large-files` does not block any merge.
5. **Provenance preserved.** Historical analysis, ADRs, design docs, review summaries, and the per-repo archive policy READMEs survive the migration at the new path.

## 3. Non-Goals

1. **Touching `docs/plans/.archive/` or `docs/specs/.archive/`.** Those are governed by `2026-10-03-plans-specs-canonical-paths.md`; this plan does not rename, move, or delete those.
2. **Rewriting historical provenance docs.** `ACB_COMPARISON.md`'s inline *"Superseded by `docs/ONEIRIC_VS_ACB.md`"* references stay verbatim — rewriting would falsify authorial context.
3. **Mass reference sed across all repos.** Per-repo reference updates only for code paths and per-repo `CLAUDE.md` / decisions that mention `docs/archive/`. Cross-repo migration is out of scope; mahavishnu owns the convention, other repos adopt it.
4. **Bumping any project's version.** Per `feedback-mcp-common-version-bump-is-user.md`. If this plan lands a release-worthy change in a Bodai core repo (it doesn't), the user bumps via `crackerjack run -p minor`.
5. **Auto-push to `origin/main`.** Per `feedback-bodai-push-is-user-controlled.md`. Commits land on local `main` via squash-merge; the `MAHAVISHNU_AUTO_MERGE=1` push happens automatically when the SessionEnd hook fires — but I never invoke `git push` directly.
6. **Cleaning up trash outside `docs/archive/`.** Stale `tracker_metadata.local.yaml`, orphaned worktrees, etc. are separate work items.

## 4. Current Findings (verified 2026-10-15)

| Repo | `docs/archive/` content (count) | `docs/.archive/` content | Tracked test artifacts | gitignore coverage |
|---|---|---|---|---|
| **mahavishnu** | 0 | 0 | 0 | `coverage.json` (exact), `.coverage*` (dot) — passes minimal |
| **akosha** | README + analysis/INTEGRATION_REVIEW_SUMMARY (2 md) | 0 | 0 | `coverage.json`, `.coverage*` — passes |
| **session-buddy** | README + implementation-reports/* (≥2 md) | 0 | `test-artifacts/*.py` (2 files) | `docs/archive/test-artifacts/coverage__*.json` (does NOT catch `.py`) |
| **crackerjack** | 309 files (historical + 2026-08-06 cleanup) | 62 files (dated analysis) | `test-artifacts/coverage__*.json` (3 files) | `coverage`/`coverage.json`/`.coverage*` — partial only |
| **mcp-common** | README + analysis/TEST_COVERAGE_EXPANSION (2 md) | 0 | `test-artifacts/test_coverage_analysis.py` | `coverage.json`, `coverage*.json` (line 106 — does NOT catch `.py` under test-artifacts) |
| **oneiric** | ACB_COMPARISON + BUILD_PROMPTS (2 md) | 0 | `test-artifacts/coverage__20260812-121049.json` + `coverage__20261014-104911.json` (both 2.5 MB) | `coverage.json` exact, `.coverage*` dot-prefix — **NEITHER matches `coverage__*.json`** |

**Root cause of the fast hook failure:**

```
File: docs/archive/test-artifacts/coverage__20261014-104911.json (oneiric)
Size: 2.5 MB (above 500 KB threshold)
Hook:  pre-commit stock `check-added-large-files` → FAIL
```

The gitignore patterns in oneiric are `coverage.json` (literal) and `.coverage*` (dot-prefix). The offender's filename is `coverage__20261014-104911.json` — patterns don't match, file is committed, hook fires on re-stage.

**Committing history proves this regression slipped a partial cleanup:**

```
2b000e6  chore: bump version to 0.29.3
72533ee  chore: untrack 38 historical archive files     ← partial cleanup
5366c76  chore: bump version to 0.16.3                 ← older
```

Commit `72533ee` untracked 38 archive files but missed the two coverage JSONs — probably because the untracker ran before the JSONs were re-added.

**The broader test-artifact fleet pattern:**

Crackerjack has the same vulnerability (`test-artifacts/coverage__20260501-*.json` × 3, multi-MB); session-buddy has the symmetric problem with `.py` instead of `.json`; mcp-common has both. Every repo except akosha and mahavishnu needs eviction.

**Per-repo reference sed scope (verified by `git grep -n 'docs/archive/'`):**

- oneiric: 0 in-repo references (archive is undocumented outside the dir itself)
- akosha: 0 (no CLAUDE.md mention, no code reference)
- session-buddy: 1 reference (`session-buddy/.gitignore:138-146` — the existing `.archive/` rules + the `docs/archive/test-artifacts/coverage__*.json` rule; the rule itself moves with the rename)
- mcp-common: 0 in-repo (the `coverage*.json` gitignore rule is generic)
- crackerjack: 0 in-repo (both archive dirs coexist independent of code)

(Reference grep run via `git -C <repo> grep -l "docs/archive/"` per-repo on 2026-10-15 — all returns 0 or 1 line in the gitignore itself, which moves with the rename.)

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-201-DEC
    title: "Decision doc exists at mahavishnu/docs/decisions/2026-10-15-archive-dir-canonical.md with status=active"
  - id: REQ-202-PLAN
    title: "This plan exists with status=active and per-phase Integration Contract blocks"
  - id: REQ-203-RENAME
    title: "Each affected repo's working tree has exactly ONE top-level archive directory: docs/.archive/"
  - id: REQ-204-EVICT
    title: "git ls-files docs/.archive/test-artifacts/** returns empty for all 6 Bodai core repos"
  - id: REQ-205-GITIGNORE
    title: "Each repo's gitignore covers docs/.archive/test-artifacts/** AND the filename patterns that escaped previously (coverage__*.json on oneiric; *.py under test-artifacts on session-buddy, mcp-common)"
  - id: REQ-206-HOOK
    title: "check-added-large-files pre-commit hook passes on a synthetic re-stage of test artifact filenames in every Bodai core repo"
  - id: REQ-207-PIPELINE
    title: "Per repo, crackerjack run -v passes post-merge (gates the squash-merge per docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md)"
  - id: REQ-208-README
    title: "Per-repo archive README survives the migration (renamed to docs/.archive/README.md; content updated only to reference the new path)"
  - id: REQ-209-REFERENCES
    title: "Per-repo grep for 'docs/archive/' returns 0 matches in code/comments/Markdown outside the gitignore itself, post-migration"
  - id: REQ-210-NO-AUTO-PUSH
    title: "No `git push` invocation anywhere in the migration; push is handled by MAHAVISHNU_AUTO_MERGE=1 SessionEnd pipeline per feedback-bodai-push-is-user-controlled.md"
```

## 5. Implementation Phases

Each phase is one repo. Per-phase order is by (priority, blast radius): the immediate failure source first, then the merge case, then the uniform-rename fleet sweep.

### Phase 1: mahavishnu — land decision + plan docs

**Goal:** Capture the convention rule in `docs/decisions/2026-10-15-archive-dir-canonical.md` (already drafted) and the implementation plan (this document). Squash-merge to local `main` first so every downstream per-repo phase has a reference to the canonical convention.

#### Integration Contract ← Phase 1
- **Triggered from**: this plan; no upstream dependency.
- **Returns to / updates**: mahavishnu `main` carries the decision + plan pair; `docs/plans/PLAN_INDEX.md` (manually maintained) gains the new entry.
- **Demonstrable by**: `gh api /repos/lesleslie/mahavishnu/contents/docs/decisions/2026-10-15-archive-dir-canonical.md` (post-merge). On local: `git -C ~/Projects/mahavishnu log --oneline -1 -- docs/decisions/2026-10-15-archive-dir-canonical.md docs/plans/2026-10-15-archive-dir-canonical.md`.
- **Rollback signal**: if the merge pipeline rejects (crackerjack FAILED), revert the working tree commit per the local merge workflow. Decision and plan go together — do not merge one without the other.
- **Observability added**: `docs/decisions/README.md` index lists the new decision under `topic: archive-dir-canonical`.

**Files (Phase 1):**
- Create: `docs/decisions/2026-10-15-archive-dir-canonical.md`
- Create: `docs/plans/2026-10-15-archive-dir-canonical.md`
- Modify: `docs/decisions/README.md` (index entry, manual)

**Tasks (one step per action — 2-5 minutes each):**

- [ ] **Task 1.1: Stage + commit on the `docs-archive-canonical-2026-10-15` worktree**
  ```bash
  git add docs/decisions/2026-10-15-archive-dir-canonical.md \
          docs/plans/2026-10-15-archive-dir-canonical.md \
          docs/decisions/README.md
  git commit -- docs/decisions/2026-10-15-archive-dir-canonical.md \
                 docs/plans/2026-10-15-archive-dir-canonical.md \
                 docs/decisions/README.md \
    -m "docs(decision): canonical archive dir is docs/.archive/ (req REQ-201-DEC, REQ-202-PLAN)"
  ```
  Per `feedback-commit-plan-files-immediately.md`: COMMIT the decision + plan first, before any other action.
  Per `feedback-git-commit-only-pathspec-with-staged-changes.md`: use `git commit -- <pathspec>` after `git add`.

- [ ] **Task 1.2: Squash-merge to local `main` per the merge workflow**
  Use the trunk-based agent-review merge pattern: in a fresh mahavishnu worktree, run `crackerjack run -v` (NOT `-p` per `feedback-crackerjack-publish-stage-is-user.md`); squash-merge to local `main`. Do NOT `git push`.

- [ ] **Task 1.3: Verify on local main**
  `git -C ~/Projects/mahavishnu log --oneline -1 -- docs/decisions/2026-10-15-archive-dir-canonical.md` returns the merge commit. `PLAN_INDEX.md` (or current index) shows the new entry.

### Phase 2: oneiric — the immediate failure source

**Goal:** Rename `docs/archive/` to `docs/.archive/`, evict the two coverage JSONs, add the missing gitignore pattern. The original fast hook failure.

#### Integration Contract ← Phase 2
- **Triggered from**: Decision doc on mahavishnu `main` (Phase 1).
- **Returns to / updates**: oneiric `main` carries `docs/.archive/` (not `docs/archive/`); `git ls-files docs/.archive/test-artifacts/` returns empty.
- **Demonstrable by**: `git -C oneiric ls-files docs/archive | wc -l` returns 0. `git -C oneiric ls-files docs/.archive | wc -l` returns 3 (ACB_COMPARISON, BUILD_PROMPTS, README from rename — actually 2 since ACB_COMPARISON.md and BUILD_PROMPTS.md remain; the README didn't exist in oneiric's `docs/archive/`, the rename only moves what's there). `crackerjack run -v` passes.
- **Rollback signal**: `git revert` of the merge commit restores the previous state with the offending JSONs back in tracking; the fast hook re-fires.
- **Observability added**: oneiric's `/health` body (operationally unchanged — this is a docs/repo-shape change, not an API change).

**Files (Phase 2):**
- Modify (via `git mv`): `docs/archive/{ACB_COMPARISON,BUILD_PROMPTS}.md` → `docs/.archive/`
- Delete (via `git rm -r --cached`): `docs/archive/test-artifacts/` (2 JSONs)
- Modify: `.gitignore` (add `coverage__*.json` pattern)
- Stage the rename + the eviction in two commits, per `feedback-git-commit-only-pathspec-with-staged-changes.md`

**Tasks:**

- [ ] **Task 2.0: Create oneiric worktree at Vishnu bucket**
  ```bash
  git worktree add ~/.local/state/mahavishnu/worktrees/oneiric/docs-archive-canonical-2026-10-15 \
    -b docs-archive-canonical-2026-10-15 main
  cd ~/.local/state/mahavishnu/worktrees/oneiric/docs-archive-canonical-2026-10-15
  ```

- [ ] **Task 2.1: Untrack the test artifacts BEFORE the rename**
  ```bash
  git rm -r --cached docs/archive/test-artifacts/   # untrack
  # (files remain on disk; cleanup is Task 2.4)
  ```
  Adding the `--cached` flag means pre-commit's `check-added-large-files` will not see re-add (which it would on `git add .`). Cleanup of the on-disk files happens AFTER the rename so the working tree state matches the index.

- [ ] **Task 2.2: Rename the legit content**
  ```bash
  git mv docs/archive docs/.archive
  ```

- [ ] **Task 2.3: Harden `.gitignore`**
  Add (before the bodai-shared-gitignore block) or as part of the existing coverage block:
  ```gitignore
  # coverage snapshots escaped from earlier gitignore (req REQ-205)
  coverage__*.json
  docs/.archive/test-artifacts/
  docs/archive/test-artifacts/
  ```
  Verify with `git check-ignore -v docs/.archive/test-artifacts/coverage__<digits>-<digits>.json` returns a matching pattern.

- [ ] **Task 2.4: Remove the untracked on-disk files**
  ```bash
  rm -rf docs/.archive/test-artifacts/   # was untracked; safe to delete from disk
  ```

- [ ] **Task 2.5: Stage + commit in two separate commits**
  Per the per-repo convention (one squash-merge per repo, but multiple commits within the worktree are fine and the squash flattens them).
  ```bash
  git add docs/.archive .gitignore
  git commit -- . \
    -m "fix(oneiric): evict test artifacts, rename docs/archive -> docs/.archive (req REQ-203..205)"
  ```
  The `git rm --cached` already happened in Task 2.1; `--cached` deletes from the index in the staged commit if staged; this final commit captures the rename + gitignore diff.

- [ ] **Task 2.6: Squash-merge to local oneiric `main`**
  `crackerjack run -v` (per memory). Squash-merge. Do NOT `git push`.

- [ ] **Task 2.7: Validation**
  ```bash
  git ls-files docs/archive | wc -l          # expect 0
  git ls-files docs/.archive/test-artifacts | wc -l  # expect 0
  git check-ignore -v docs/.archive/test-artifacts/coverage__XXXX.json  # expect a pattern match
  git stash <(echo docs/.archive/test-artifacts/coverage__SYNTHETIC.json > /tmp/x; git add -N /tmp/x; rm /tmp/x)
  ```

### Phase 3: crackerjack — the merge case

**Goal:** Merge 309 files from `docs/archive/` into the existing 62 files in `docs/.archive/`, then delete `docs/archive/`. The largest diff and most test artifacts to evict (3 coverage JSONs).

#### Integration Contract ← Phase 3
- **Triggered from**: oneiric merge (Phase 2) — establishes the rename precedent and the eviction shape.
- **Returns to / updates**: crackerjack `main` carries `docs/.archive/` with the merged content set; `docs/archive/` no longer exists.
- **Demonstrable by**: `git -C crackerjack ls-files docs/archive | wc -l` returns 0; `git -C crackerjack ls-files docs/.archive | wc -l` returns ≥ 62 (current) + the moved content from `docs/archive/` minus the test artifacts.
- **Rollback signal**: `git revert` of the merge commit restores both directories.
- **Observability added**: crackerjack's `/health` (unchanged — repo shape, not API).

**Tasks:**

- [ ] **Task 3.0: Create crackerjack worktree (at Vishnu bucket)**
  ```bash
  git worktree add ~/.local/state/mahavishnu/worktrees/crackerjack/docs-archive-canonical-2026-10-15 \
    -b docs-archive-canonical-2026-10-15 main
  ```

- [ ] **Task 3.1: Inventory before merge — capture the move map**
  List the top-level entries of `docs/archive/`; check each against existing `docs/.archive/` subdirs. Document the move map (`grep '^docs/archive/[^/]*/' docs/archive/...`). Document any collisions in the commit message or a `move-map.txt` for posterity.

- [ ] **Task 3.2: Untrack `docs/archive/test-artifacts/` and per-file `git rm` if needed**
  ```bash
  git rm -r --cached docs/archive/test-artifacts/
  # 3 coverage JSONs leave the index; on-disk files remain
  ```

- [ ] **Task 3.3: Per-subdir `git mv` into existing `docs/.archive/`**
  ```bash
  git mv docs/archive/<subdir> docs/.archive/<subdir-or-renamed>
  ```
  Repeat for each top-level subdir (e.g., `2026-08-06-ai-fix-removal-cleanup`, `analysis`, etc.). If a name collides with existing `docs/.archive/<subdir>`, merge into the existing dir or pick a non-colliding target.

- [ ] **Task 3.4: Delete the now-empty `docs/archive/` (git + on-disk)**
  After all subdirs are moved, `git rm -r docs/archive/` if the dir is in the index, or `rmdir docs/archive/` if untracked.

- [ ] **Task 3.5: Cleanup the untracked test artifacts**
  ```bash
  rm -rf docs/.archive/test-artifacts/
  ```

- [ ] **Task 3.6: Harden `.gitignore`** — same shape as Phase 2.3 but at the crackerjack location.

- [ ] **Task 3.7: Stage + commit per the merge workflow**
  ```bash
  git add -A .   # the move + gitignore diff
  git commit -m "fix(crackerjack): merge docs/archive -> docs/.archive, evict test artifacts (req REQ-203, REQ-204, REQ-205)"
  ```

- [ ] **Task 3.8: Squash-merge to local `crackerjack main`; `crackerjack run -v`; no push.

- [ ] **Task 3.9: Validation**
  `git ls-files docs/.archive/test-artifacts/ | wc -l` → 0.
  `git ls-files docs/archive | wc -l` → 0.
  `git ls-files docs/.archive | wc -l` → ≥ 62 (current) + moved content - test artifacts.

### Phase 4: akosha — uniform rename, no test artifacts

**Goal:** Simple `git mv docs/archive docs/.archive` — no eviction needed.

#### Integration Contract ← Phase 4
- **Triggered from**: crackerjack merge (Phase 3) — same merge shape, smaller diff.
- **Returns to / updates**: akosha `main` carries `docs/.archive/` with the existing README + INTEGRATION_REVIEW_SUMMARY.
- **Demonstrable by**: `git -C akosha ls-files docs/archive | wc -l` → 0; `git -C akosha ls-files docs/.archive | wc -l` → 2 (README + INTEGRATION_REVIEW_SUMMARY).
- **Rollback signal**: `git revert` of the merge commit.
- **Observability added**: unchanged.

**Tasks:** `git worktree add ... akosha`, `git mv docs/archive docs/.archive`, harden `.gitignore`, `crackerjack run -v`, squash-merge. No eviction; no per-subdir move logic.

### Phase 5: session-buddy — rename + evict `.py` test artifacts

**Goal:** Mirror Phase 2 shape; the test artifacts here are `.py` files (not JSONs).

#### Integration Contract ← Phase 5
- **Triggered from**: akosha merge (Phase 4).
- **Returns to / updates**: session-buddy `main` carries `docs/.archive/` with README, implementation-reports/* ; no tracked test artifacts.
- **Demonstrable by**: `git -C session-buddy ls-files docs/.archive/test-artifacts/ | wc -l` → 0.

**Tasks:** Worktree, `git rm -r --cached docs/archive/test-artifacts/` (catches the 2 `.py` files), `git mv docs/archive docs/.archive`, broaden `.gitignore` rule (existing line 50 `docs/archive/test-artifacts/coverage__*.json` becomes `docs/.archive/test-artifacts/coverage__*.json` AND `/test-artifacts/*.py`), `crackerjack run -v`, squash-merge.

### Phase 6: mcp-common — rename + evict `.py` test artifact

**Goal:** Mirror Phase 5.

#### Integration Contract ← Phase 6
- **Triggered from**: session-buddy merge (Phase 5).
- **Returns to / updates**: mcp-common `main` carries `docs/.archive/` with README + TEST_COVERAGE_EXPANSION; no tracked test artifacts.
- **Demonstrable by**: `git -C mcp-common ls-files docs/.archive/test-artifacts/ | wc -l` → 0.

**Tasks:** Worktree, `git rm -r --cached docs/archive/test-artifacts/` (catches `test_coverage_analysis.py`), `git mv docs/archive docs/.archive`, broaden gitignore, `crackerjack run -v`, squash-merge.

### Phase 7: validation fleet-wide

**Goal:** Re-run the fast hook on each repo to prove REQ-206.

#### Integration Contract ← Phase 7
- **Triggered from**: all 5 per-repo phases merged.
- **Returns to / updates**: a `docs/followups/2026-10-15-archive-migration-validation.md` (followups not archived per `followups-lifecycle.md`) summarizing the post-merge state per repo.
- **Demonstrable by**: for each Bodai core repo, run `check-added-large-files` (via `crackerjack run -v` per REQ-207) with a re-staged test artifact filename (synthetic — touched file in /tmp, never committed) — the hook passes.
- **Rollback signal**: if any hook still fires on a re-stage, the per-repo gitignore is incomplete; revisit that phase.
- **Observability added**: a per-repo checklist in the validation followup.

**Tasks:**

- [ ] **Task 7.1: Per-repo `git check-ignore -v` on synthetic test artifacts**
  For each repo, run:
  ```bash
  git -C <repo> check-ignore -v docs/.archive/test-artifacts/coverage__SYNTHETIC.json
  git -C <repo> check-ignore -v docs/.archive/test-artifacts/test_SYNTHETIC.py
  ```
  Each returns a matching gitignore pattern.

- [ ] **Task 7.2: Per-repo `crackerjack run -v` (post-merge smoke)**
  Per REQ-207.

- [ ] **Task 7.3: Fleet-state summary table**
  Per-repo row: `ls-files docs/archive count`, `ls-files docs/.archive count`, `ls-files docs/.archive/test-artifacts count`, `gitignore pattern count`, `crackerjack run -v` status. Save to `docs/followups/2026-10-15-archive-migration-validation.md`.

### Phase 8: cleanup

**Goal:** Remove transient worktrees per `feedback-worktree-update-ref-drops-parallel-commits.md` style cleanup.

**Tasks:**

- [ ] **Task 8.1: Per-repo worktree prune**
  After each phase's squash-merge, `git worktree remove ~/.local/state/mahavishnu/worktrees/<repo>/docs-archive-canonical-2026-10-15`.
- [ ] **Task 8.2: Branch cleanup**
  `git -C <repo> branch -d docs-archive-canonical-2026-10-15` post-merge.
- [ ] **Task 8.3: mahavishnu worktree cleanup**
  Same.

## 6. Required Code Changes

```
mahavishnu/
├── docs/decisions/
│   ├── README.md                                  [MODIFY] index entry
│   └── 2026-10-15-archive-dir-canonical.md        [CREATE] this decision
├── docs/plans/
│   └── 2026-10-15-archive-dir-canonical.md        [CREATE] this plan
└── docs/followups/
    └── 2026-10-15-archive-migration-validation.md  [CREATE] Phase 7 result

oneiric/
├── docs/.archive/                                  [RENAME] from docs/archive/
│   ├── ACB_COMPARISON.md                          [MOVE from docs/archive/]
│   ├── BUILD_PROMPTS.md                           [MOVE from docs/archive/]
│   └── test-artifacts/                            [EVICT, untracked delete]
├── .gitignore                                     [MODIFY] add coverage__*.json pattern

akosha/
├── docs/.archive/                                  [RENAME] from docs/archive/
│   ├── README.md                                   [MOVE]
│   └── analysis/INTEGRATION_REVIEW_SUMMARY.md     [MOVE]
└── .gitignore                                     [MODIFY] add test-artifacts/* pattern

session-buddy/
├── docs/.archive/                                  [RENAME] from docs/archive/
│   ├── README.md                                   [MOVE]
│   ├── implementation-reports/                    [MOVE]
│   └── test-artifacts/                            [EVICT]
└── .gitignore                                     [MODIFY] broaden test-artifacts/* pattern to .py

crackerjack/
├── docs/.archive/                                  [MERGE] docs/archive contents into existing
│   ├── + all moved content from docs/archive/
│   └── test-artifacts/                            [EVICT, 3 JSONs]
├── docs/archive/                                   [DELETE after merge]
└── .gitignore                                     [MODIFY] coverage*.json + test-artifacts/*.py

mcp-common/
├── docs/.archive/                                  [RENAME] from docs/archive/
│   ├── README.md                                   [MOVE]
│   ├── analysis/TEST_COVERAGE_EXPANSION.md        [MOVE]
│   └── test-artifacts/                            [EVICT]
└── .gitignore                                     [MODIFY] broaden test-artifacts/* pattern
```

## 7. Validation Matrix

| Tool/command | Expected outcome | Evidence |
|---|---|---|
| `git -C <repo> ls-files docs/archive | wc -l` (all 6 repos post-Phase 6) | `0` | shell |
| `git -C <repo> ls-files docs/.archive/test-artifacts | wc -l` (all 6 repos) | `0` | shell |
| `git -C <repo> check-ignore -v docs/.archive/test-artifacts/coverage__2026xxxxxxxx.json` (synthetic filename) | matching pattern | shell |
| `git -C <repo> check-ignore -v docs/.archive/test-artifacts/test_foo.py` (synthetic filename) | matching pattern | shell |
| `crackerjack run -v` (per repo post-Phase 6) | passes | CI-equivalent |
| `gh api /repos/lesleslie/<repo>/contents/docs/archive` (post-Phase 6, where applicable) | HTTP 404 (dir does not exist) | shell |
| `gh api /repos/lesleslie/<repo>/contents/docs/.archive` (post-Phase 1) | HTTP 200 with directory listing | shell |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Crackerjack merge collision (same name in both archive dirs) | Low | Phase 3.1 inventories before the move; collision prefix with date or rename target. |
| A per-repo reference (CLAUDE.md, decisions) mentions `docs/archive/` and breaks after rename | Low (verified zero non-gitignore refs in 5 repos) | Phase 0 reference grep; per-phase sed in the worktree commit. |
| `git rm --cached` followed by `rm -rf` for the test artifacts loses recoverable history | Low | 90-day reflog covers all operations; `git log --follow` works across renames. |
| One of the per-repo renames triggers `check-added-large-files` because the rename moves a large file through staging in some git version | Resolved | `check-added-large-files` checks newly added files; `git mv` doesn't re-add — it renames the index entry. The hook does not fire. Verified via `git mv` semantics. |
| Per-repo merge fails (`crackerjack run -v` rejects) | Medium | The fix is local to the failing repo's archive/`.gitignore`/`.crackerjack/` left-over cruft. Per-repo retry. |
| Worktree goes stale mid-phase (concurrent session edits) | Low | Each phase uses an isolated worktree; main is not touched directly. Per `feedback-worktree-update-ref-drops-parallel-commits.md`, ref-level ops stay in-worktree. |
| A repo's `tests/archived/` (some repos have this) is confused with `docs/archive/` | Low | `tests/archived/` is already gitignored; the plan does not touch it. The migration is docs-only. |
| Phase ordering creates a half-applied state where one repo has the rename and another doesn't | Low (status quo is "all messy"; intermediate states are all "less messy than before") | Each repo is independent; the migration can stop and resume per repo. |
| The user's auto-push pipeline (`MAHAVISHNU_AUTO_MERGE=1`) fires too eagerly | Low | Per `feedback-bodai-push-is-user-controlled.md`: never `git push`; the SessionEnd hook handles it. This plan does NOT modify `MAHAVISHNU_AUTO_MERGE`. |

## 9. Decision Rule

This plan is **done enough** when:

1. All 6 Bodai core repos have `docs/.archive/` (canonical) and no `docs/archive/` (legacy).
2. All 6 have test-artifact-eviction gitignore rules; no tracked files under `docs/.archive/test-artifacts/**`.
3. `crackerjack run -v` passes per repo (REQs 207, 208).
4. Phase 7's fleet-state summary commit is on mahavishnu `main`.

If scope pressure forces a cut: **Phases 4–6 (akosha, session-buddy, mcp-common) are the most cuttable** — they are uniform renames with no immediate failure source. Phases 1–3 are non-cuttable: they capture the convention, fix the immediate hook failure, and handle the merge case. If `crackerjack run -v` passes nowhere: revert ALL phase merges and re-issue this plan with a smaller per-phase scope.

---

**Plan written by:** writing-plans skill + superseding/migrating a fast-hook failure observed 2026-10-15 22:43 UTC.

**Date:** 2026-10-15

**Estimated scope:** ~30 numbered tasks across 8 phases (Phase 1=3, Phase 2=8, Phase 3=10, Phase 4=4, Phase 5=5, Phase 6=5, Phase 7=3, Phase 8=3). Per-repo failures abort the affected phase only; the other repos remain independent.

**See also:**
- [[docs/decisions/2026-10-15-archive-dir-canonical.md]] — the convention rule
- [[docs/decisions/2026-10-03-plans-specs-canonical-paths.md]] — sibling decision about `docs/plans/.archive/` and `docs/specs/.archive/`
- [[feedback-bodai-push-is-user-controlled]] — `git push` is user-owned
- [[feedback-mcp-common-version-bump-is-user]] — version bumps are user-owned
- [[feedback-crackerjack-publish-stage-is-user]] — never `crackerjack run -p`; debug with `-v` only
- [[feedback-crackerjack-merge-gate-is-vf]] — merge gate is `crackerjack run -v -f`
- [[feedback-commit-plan-files-immediately]] — commit decision + plan pair before any other action
- [[feedback-keep-plan-files-tracked]] — `git add` the plan + decision files explicitly
