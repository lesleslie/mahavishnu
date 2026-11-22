---
status: active
role: implementation
date: 2026-11-21
last_reviewed: 2026-11-21
topic: worktree-prune
title: "Prune sweep recognises squash-merged branches and every worktree git knows about"
requirements:
  - id: REQ-PRUNE-001
    title: "A squash-merged branch is classified as merged however many commits it carried"
  - id: REQ-PRUNE-002
    title: "The prune sweep enumerates every worktree git knows about, not only the coordinator's registry"
  - id: REQ-PRUNE-003
    title: "A locked worktree is never offered for removal"
  - id: REQ-PRUNE-004
    title: "The porcelain parser reads git's block format, so the provider lists every worktree"
---

# Prune sweep recognises squash-merged branches and every worktree git knows about

## 1. Outcome

`mahavishnu worktree prune-merged` finds and removes the worktrees whose
branches are already on `main`, including the branches that were merged by
**squash** — which is the fleet's default merge mode.

Today it finds neither: the two branches merged on 2026-11-21
(`fix/merge-review-convergence`, 16 commits; `fix/cli-async-run-in-running-loop`,
20 commits) are both on `main`, and both of their worktrees are still on disk.

**Success signal:** `mahavishnu worktree prune-merged --repo mh --dry-run`
lists those two worktrees as candidates, and `classify_merge_status` returns
`merged` for both.

## 2. Goals

1. Classify a squash-merged branch as `merged` regardless of how many commits
   the squash carried.
2. Enumerate every worktree the repository actually has, so the sweep is not
   blind to a class of worktrees it cannot see.
3. Parse git's porcelain output in git's own format, so the provider stops
   reporting zero worktrees for every repository.
4. Never offer a **locked** worktree for removal — the lock is the fleet's
   existing "do not touch this" marker, and the sweep is about to become
   automatic.
5. Keep every currently-correct classification correct: a branch with content
   `main` does not have must still read `not_merged`.

## 3. Non-Goals

1. Changing the **removal** semantics — what gets deleted, the safety checks,
   the audit trail, the `--include-dirty` / `--force-reason` gate.
2. Changing the merge **policy** — the squash itself, and the decision to
   squash, are untouched.
3. Auto-pruning on the merge path beyond what stage 6 already does.
4. Deleting any branch ref. The merged branches stay on disk; their history is
   also preserved by the annotated tags `archive/fix-merge-review-convergence`
   and `archive/fix-cli-async-run-in-running-loop`.

## 4. Current Findings

**Finding 1 — `git cherry` cannot see a multi-commit squash.**

`classify_merge_status` (`mahavishnu/core/worktree_prune_merged.py:93`) used
`git cherry` as its squash signal. `git cherry` compares *patch-ids*, and a
patch-id is computed per commit. Merging N commits produces **one** commit
whose diff is the union of the N diffs — a combination that matches none of
the individual patch-ids. Every commit of the branch therefore shows `+`, and
the branch reads `not_merged`.

The single-commit case works by accident: with one commit, the squash commit's
diff *is* that commit's diff, so the patch-ids match. The existing test
`test_classify_merge_status_handles_squash_merged_branch` used exactly one
commit — so it passed, and the multi-commit case was never covered.

Measured on the real branches:

| branch | commits | `git cherry main` | classified |
|---|---|---|---|
| `fix/merge-review-convergence` | 16 | 16 × `+` | `not_merged` |
| `fix/cli-async-run-in-running-loop` | 20 | 19 × `+` | `not_merged` |

**Finding 2 — the local provider's porcelain parser matched nothing git emits.**

`_candidate_worktree_paths` consulted only the coordinator's registry. The
coordinator's provider registry reports Session-Buddy as unhealthy and falls
back to the local provider — and the local provider returned an **empty list
for every repository**.

The reason: its parser kept a line only when the line had four or more
space-separated fields, and expected the fields `path branch commit status`.
Git emits one **block** per worktree instead:

```
worktree /path/to/wt
HEAD 1a2b3c4
branch refs/heads/feature
locked initializing
```

Every line of the real output has exactly **two** parts (measured: 77 of 77).
The old predicate therefore matched nothing. `mahavishnu worktree list --repo mh` reported **"0 total"** while `git worktree list` reported 75.

The provider's tests did not catch it because they fed the parser a
four-field line of their own invention — a format git does not produce — so
the suite agreed with the bug. That is the same failure shape as Finding 1:
a fixture that satisfies the implementation's assumption, and thereby hides
the case the assumption breaks.

**Finding 3 — the enumeration never asked git, and never fell back to it.**

`_candidate_worktree_paths` returned the coordinator's list and, on a
coordinator exception, returned an **empty** list — making the direct git
fallback unreachable. A transient registry outage therefore silenced the
sweep completely.

**Finding 4 — the merge gate does not run pytest**, so a green gate did not
mean the classification was right.

## 4.5 Requirements

- **REQ-PRUNE-001** — A squash-merged branch is classified as `merged`
  however many commits the squash carried.
- **REQ-PRUNE-002** — The prune sweep enumerates every worktree git knows
  about, not only the coordinator's registry.
- **REQ-PRUNE-003** — A locked worktree is never offered for removal.
- **REQ-PRUNE-004** — The porcelain parser reads git's block format, so the
  provider lists every worktree.

## 5. Implementation Phases

### Phase 1: Content-equivalence classification

**Goal:** Replace the patch-id signal with a content signal.

**Tasks:** Add `_content_already_in_branch`, which asks
`git merge-tree --write-tree <branch> HEAD` — "would merging HEAD into
`<branch>` change anything?" — and reports a match only when the resulting
tree equals `<branch>`'s tree. Insert it ahead of the `git cherry` fallback,
so it can only ever *upgrade* a branch to `merged`; every earlier
`undetermined` is left alone.

**Exit criteria:** The two real branches classify as `merged`; every
genuinely-unmerged branch still classifies as `not_merged`.

#### Integration Contract

- **Triggered from**: `classify_merge_status` in
  `mahavishnu/core/worktree_prune_merged.py`, reached from
  `find_merged_worktrees` → `_prune_candidate_for` →
  `mahavishnu worktree prune-merged` (`mahavishnu/worktree_cli.py:437`) and
  from merge-pipeline stage 6 cleanup.
- **Returns to / updates**: the `merge_status` field of
  `WorktreePruneCandidate`, which decides whether the worktree is offered for
  removal. No new state.
- **Demonstrable by**:
  `pytest tests/unit/test_worktree_prune_merged.py::test_classify_merge_status_handles_multi_commit_squash_merged_branch`
  and the live classification of the two real branches.
- **Rollback signal**: a branch with content `main` lacks being classified
  `merged` — visible as a worktree removed that `git diff main <branch>`
  still shows as changed. The test
  `test_classify_merge_status_reports_not_merged_when_the_branch_adds_content`
  and
  `test_classify_merge_status_reports_not_merged_for_a_clean_unmerged_branch`
  are the regression detectors.
- **Observability added**: none — a classification decision, not a runtime
  event. The existing prune audit trail
  (`mahavishnu/core/worktree_audit.py`) records the outcome of each removal.

### Phase 2: Enumeration that sees every worktree

**Goal:** Make the sweep's candidate list match reality.

**Tasks:** Union the coordinator's list with `git worktree list`, and fall
back to the git listing when the coordinator raises or reports failure,
instead of returning an empty list.

**Exit criteria:** The CLI dry-run lists the repo-scoped worktrees; a
coordinator outage does not silence the sweep.

#### Integration Contract

- **Triggered from**: `_candidate_worktree_paths`, reached from
  `find_merged_worktrees` → `mahavishnu worktree prune-merged`
  (`mahavishnu/worktree_cli.py:358`).
- **Returns to / updates**: the candidate list passed to `WorktreePruner.remove`,
  which writes the audit events. A path git cannot resolve classifies as
  `undetermined` and is never removed.
- **Demonstrable by**:
  `pytest tests/unit/test_worktree_prune_merged.py::test_find_merged_worktrees_finds_worktrees_the_coordinator_omits`
  and `::test_find_merged_worktrees_survives_a_failing_coordinator`.
- **Rollback signal**: a candidate appearing that the coordinator never
  reported **and** that git cannot resolve — surfaced by the existing
  `undetermined` skip, and by the prune audit trail recording a failure.
- **Observability added**: none new — the prune audit trail already records
  per-worktree outcomes.

### Phase 3: Parse git's porcelain format

**Goal:** Make the local provider list the worktrees that exist.

**Tasks:** Replace both copies of the line-oriented parser with one
`_parse_worktree_porcelain` helper that reads git's block format. Update the
provider's tests to carry real porcelain output, and add a test that runs the
real command against the real repository — a fixture can only prove the parser
agrees with the fixture.

**Exit criteria:** `mahavishnu worktree list --repo mh` reports the
repository's worktrees rather than zero.

#### Integration Contract

- **Triggered from**: `DirectGitWorktreeProvider.list_worktrees` and
  `_list_worktrees_via_git` in
  `mahavishnu/core/worktree_providers/local.py`, reached from
  `mahavishnu worktree list`, the MCP `list_worktrees` tool, and the
  coordinator's enumeration.
- **Returns to / updates**: the `worktrees` list in the provider's result
  envelope, which the coordinator normalises into the listing the CLI and the
  MCP tool print.
- **Demonstrable by**:
  `pytest tests/unit/test_core_worktree_providers_local.py::TestPorcelainParserAgainstRealGit`
  and `mahavishnu worktree list --repo mh`.
- **Rollback signal**: the listing reports fewer worktrees than
  `git worktree list --porcelain` — the exact symptom this phase fixes, and
  the one the real-output test now pins.
- **Observability added**: none — a listing, not a runtime event.

### Phase 4: Never remove a locked worktree

**Goal:** Keep the now-automatic sweep from touching a live session's
worktree.

**Tasks:** Read the `locked` marker out of `git worktree list --porcelain`
and skip a locked worktree in `_prune_candidate_for`, unconditionally.

**Exit criteria:** A locked, clean, merged worktree is never a candidate.

#### Integration Contract

- **Triggered from**: `find_merged_worktrees` →
  `_locked_worktree_paths` → `_prune_candidate_for` in
  `mahavishnu/core/worktree_prune_merged.py`.
- **Returns to / updates**: the candidate list; a locked worktree is absent
  from it, so `WorktreePruner.remove` never sees it.
- **Demonstrable by**:
  `pytest tests/unit/test_worktree_prune_merged.py::test_find_merged_worktrees_skips_a_locked_worktree`.
- **Rollback signal**: a locked worktree appears in the candidate list, or in
  the prune audit trail as a removal.
- **Observability added**: none — a filter, not a runtime event.

### Phase 5: Scope the merge cycle's cleanup to its own worktree

**Goal:** Stop the merge cycle from sweeping every repository on every merge.

**Tasks:** Add `--path` to `prune-merged`, restricting the sweep to one
worktree, and have stage 6 of the merge pipeline pass the worktree it just
merged.

The filter has to apply to the **scan**, not only to the removal set.
Classifying a worktree costs a handful of git subprocesses — `git status --short` alone measured 0.26 s — so a filter applied after the sweep still
pays for every worktree in every repository. `only_path` therefore reaches
`find_merged_worktrees`, and the repositories that cannot contain the path
are skipped: the owning repository is asked of git
(`git rev-parse --git-common-dir`), because a worktree lives OUTSIDE its
repository's directory and its path's parents say nothing about who owns
it.

Measured on this machine (26 configured repositories, 76 worktrees in this
one):

| run | before | after |
|---|---|---|
| fleet-wide dry run | 83.9 s | 36.3 s |
| `--path` dry run | 39.5 s | 10.9 s |
| repositories scanned with `--path` | 26 | 1 |

About 10 s of the scoped run is the CLI's own startup (import 3.0 s,
`MahavishnuApp.load()` 7.2 s), not the sweep.

A `--path` that **no repository owns** is an ERROR, not an empty result: the
run exits 1 with a stderr diagnostic. The merge cycle reads a zero return
code from stage 6 as `cleanup_performed: true`, so a silent no-op would have
the merge report a cleanup that never happened while the worktree stayed on
disk. Two cases are errors: git cannot say who owns the path at all, and
git names an owner that is not among the configured repositories. The
owning repository is also resolved ONCE, before the repository loop — the
question is loop-invariant, and answering it per repository re-ran a git
subprocess for every configured repo.

The skip for a non-owning repository also happens BEFORE the "no canonical
nickname" check: a repository this sweep has no reason to scan must not be
able to abort the run.

**Exit criteria:** `mahavishnu worktree prune-merged --path <wt> --dry-run`
lists only that worktree and scans only the repository that owns it; a
`--path` no repository owns exits 1; stage 6 removes its own worktree and
nothing else.

#### Integration Contract

- **Triggered from**: `_run_cleanup` in
  `mahavishnu/core/merge_to_main.py`, reached from `run_pipeline` stage 6.
- **Returns to / updates**: the worktree's removal, and the `cleanup_performed`
  flag in the pipeline's result.
- **Demonstrable by**:
  `pytest tests/unit/test_worktree_prune_merged.py::test_cli_prune_merged_path_restricts_the_sweep_to_one_worktree`,
  `::test_find_merged_worktrees_only_path_classifies_one_worktree`,
  `::test_cli_prune_merged_scans_only_the_repository_that_owns_the_worktree`,
  and the two `::test_cli_prune_merged_fails_when_*` cases.
- **Rollback signal**: a merge leaves behind a worktree it merged (the
  pipeline reports `cleanup_performed: false`), or a sweep removes a
  worktree the merge cycle did not merge.
- **Observability added**: none — a scoping change to an existing command.

### Phase 6: Never force-remove a detached worktree

**Goal:** Keep the sibling `prune_worktrees` path from discarding
uncommitted work.

**Tasks:** Report a detached worktree's branch as `None` (the convention
`worktree_scan` already uses) rather than a fake branch name, and make
`WorktreeCoordinator.prune_worktrees` read the detached state from git and
skip such a worktree.

**Exit criteria:** A detached worktree is never force-removed by
`mahavishnu worktree prune` or the MCP prune action.

#### Integration Contract

- **Triggered from**: `WorktreeCoordinator.prune_worktrees` in
  `mahavishnu/core/worktree_coordination.py`, reached from `mahavishnu worktree prune` and the MCP prune action.
- **Returns to / updates**: the `pruned_count` in the prune result and the
  audit trail's prune event.
- **Demonstrable by**:
  `pytest tests/unit/test_worktree_coordination.py::TestWorktreeCoordination::test_prune_worktrees`
  — the detached worktree is in the provider's list and is not removed.
- **Rollback signal**: a detached worktree appears in the prune audit
  trail as a removal.
- **Observability added**: a log line — `Skipping detached worktree: <path>`.

## 6. Required Code Changes

- [x] `mahavishnu/core/worktree_prune_merged.py` — `_content_already_in_branch`
  helper; `classify_merge_status` gains the content signal ahead of the
  cherry fallback; `_candidate_worktree_paths` unions the coordinator's
  list with git's and falls back to git on failure;
  `_locked_worktree_paths` plus the lock guard in `_prune_candidate_for`.
- [x] `mahavishnu/core/worktree_providers/local.py` —
  `_parse_worktree_porcelain` reads git's block format; both former
  parser sites use it.
- [x] `tests/unit/test_worktree_prune_merged.py` — the multi-commit squash
  case, the two "not merged" guards, the two enumeration cases, the lock
  guard.
- [x] `tests/unit/test_core_worktree_providers_local.py` — the parser against
  real porcelain output, including a test that runs the real command.
- [x] `tests/unit/test_core_worktree_providers_local_extended.py` — the same
  fixtures corrected.
- [x] `docs/worktree/WORKTREE_AUTOREMOVE.md`,
  `docs/feature-tracking/worktree-autoremove.md`,
  `docs/decisions/2026-10-13-worktree-policy.md` — the normative
  definition of "merged" now names the content signal, and the operator
  guidance no longer reads `+` as "not merged".
- [ ] `docs/plans/PLAN_INDEX.md` — add this plan.

## 7. Validation Matrix

| tool/command | expected outcome | evidence location |
|---|---|---|
| `pytest tests/unit/test_worktree_prune_merged.py` | passes | test output |
| `pytest tests/unit/test_core_worktree_providers_local.py` | passes | test output |
| `pytest tests/unit/test_worktree_scan.py` | passes (shares the classifier) | test output |
| `crackerjack run -v -f` | exit 0 | gate output |
| `mahavishnu worktree list --repo mh` | reports the repository's worktrees | CLI output |
| `mahavishnu worktree prune-merged --repo mh --dry-run` | the two targets listed | CLI output |

## 8. Risks

**The measured blast radius of the now-automatic sweep.** Stage 6 of the merge
pipeline runs `mahavishnu worktree prune-merged --json` with no `--repo` and
no `--ttl-days`, so every merge sweeps every configured repository and
removes. Before this change the sweep was nearly inert (the enumeration
returned nothing). After it, the classification is right — so the radius has
to be measured rather than assumed:

| population (this repository, 75 worktrees) | count |
|---|---|
| classified `merged` | 27 |
| of those, dirty (skipped by the dirty check) | 22 |
| of those, **locked** (skipped by the lock guard) | 19 |
| clean, merged, **unlocked** — actually removable | 5 |
| of those, this branch's own two targets | 2 |

The remaining three are agent-scoped leftovers whose branches are already on
`main`. Phase 4 is the gate that keeps the other 19 out of reach; the dirty
check keeps another 18 of them out.

**Phase 5 removes the automatic radius altogether.** The measurement above is
what an *explicit* fleet sweep would reach. The merge cycle's stage 6 no
longer performs one: it passes `--path` and removes exactly the worktree it
just merged.

| risk | likelihood | mitigation |
|---|---|---|
| A branch with real new content is classified `merged` and its worktree removed | low | the tree comparison requires the merge to be a *no-op*; two dedicated tests cover the "clean merge that changes main" case |
| A live session's clean worktree is removed by an automatic sweep | low | Phase 5 scopes the merge cycle's cleanup to the worktree it merged; Phase 4 keeps locked worktrees out of the candidate set; the dirty check covers the rest |
| A merge in one repository prunes another repository's worktrees | low | Phase 5: the merge cycle removes exactly its own worktree. A fleet sweep is an explicit operator invocation |
| Fixing the provider activates a sibling path that force-removes worktrees | **real, and it happened** | Phase 6: a detached worktree is never force-removed. The sibling path (`mahavishnu worktree prune`) asks `git branch --list <branch>` whether the branch still exists, and a detached worktree — reported with a fake branch name — reads as "the branch was deleted", which force-removes it and discards its uncommitted work |
| `git merge-tree --write-tree` writes tree objects into the object database | certain, benign | unreferenced objects; `git gc` collects them |
| An old git without `--write-tree` | low | the helper returns False on any failure and the cherry fallback still decides |
| The provider's listing now returns real worktrees, so every `list_worktrees()` consumer sees more than before | certain | that is the fix. `mahavishnu worktree list`, the MCP tool, and the coordinator now report the truth instead of zero |
| `mahavishnu worktree scan` now classifies many worktrees as `A-merged` that were `not_merged` | certain | the scan is a REPORT — it removes nothing — and its tier rubric is the operator's triage aid. Its tier A is `A-merged-dirty`, so the entries it now surfaces are dirty ones the prune sweep would skip anyway. Note the scan's `--repo` takes a PATH, not a nickname. |

## 9. Decision Rule

Done when the two target worktrees are listed by
`mahavishnu worktree prune-merged --dry-run`, every genuinely-unmerged branch
in the repository still classifies as `not_merged`, `mahavishnu worktree list`
reports the repository's worktrees, a locked worktree is never a candidate,
and the branch is merged onto local `main`. **Not** done when the
classification is right but the worktrees are still on disk — that removal is
the operator's call.
