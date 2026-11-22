---
name: worktree-autoremove
status: built
date: 2026-07-26
last_reviewed: 2026-11-21
owner: mahavishnu
role: canonical
plan: docs/plans/2026-11-21-prune-squash-merged-detection.md
policy: docs/decisions/2026-10-13-worktree-policy.md
user_docs: docs/worktree/WORKTREE_AUTOREMOVE.md
---

# Worktree Autoremove — feature tracking

## State: built

Wave 1 (policy), Wave 2 (core module), and Wave 3 (CLI) shipped. The
`mahavishnu worktree prune-merged` CLI is operational against worktrees whose
branches are detected as merged by the multi-signal classifier.

## Built

- New CLI: `mahavishnu worktree prune-merged`
- New module: `mahavishnu/core/worktree_prune_merged.py`
- New audit events: `worktree_prune_merged_attempt`,
  `worktree_prune_merged_success`, `worktree_prune_merged_partial`,
  `worktree_prune_merged_failure`
- New policy: `docs/decisions/2026-10-13-worktree-policy.md` (the
  consolidated record, carrying the explicit-CLI amendment)
- New tests: 22 unit tests in `tests/unit/test_worktree_prune_merged.py`

## Wired

- CLI registered in `mahavishnu worktree` Typer app
- Module-level imports for `monkeypatch.setattr` compatibility
- Multi-signal merge detection: `git merge-base --is-ancestor` +
  merge-commit guard + **content equivalence**
  (`git merge-tree --write-tree <branch> HEAD`, merged only when the
  merge is a no-op) + `git cherry` as the final fallback
- Tri-state dirty check (clean / dirty / undetermined)
- Lock guard: a locked worktree is never a candidate
- Enumeration unions the coordinator's registry with `git worktree list`,
  and falls back to git when the coordinator is unavailable
- Nickname-aware repo resolution via `repo_manager.get_repo()`
- Two-phase force escalation via `coordinator.remove_worktree`
  (force=False first, then True on block)
- Exit code 1 on partial failure

## Changed (2026-11-21)

- The **content-equivalence** signal replaced `git cherry` as the deciding
  signal for a squash-merge. `git cherry` compares patch-ids, and a squash
  of N commits produces ONE commit whose diff is the union of N diffs — a
  combination that matches none of the individual patch-ids. Every commit
  of a squash-merged branch showed `+`, so a branch merged by a multi-commit
  squash was classified `not_merged` and its worktree was never pruned.
- The **local provider's porcelain parser** now reads git's block format.
  It previously expected four space-separated fields on one line and matched
  nothing git emits, so the provider reported zero worktrees for every
  repository.
- The **lock guard** keeps a locked worktree out of the candidate set.
- The **merge cycle's cleanup is scoped**: stage 6 passes `--path` and
  removes exactly the worktree it just merged. It used to sweep every
  configured repository, unattended, on every merge — which the policy
  decision reserves for explicit operator invocation. An explicit
  `mahavishnu worktree prune-merged` is the only path that sweeps
  everything. The `--path` filter applies to the *scan*, not only to the
  removal set: the repositories that cannot contain the path are skipped
  outright, so their worktrees are never classified. A `--path` that no
  repository owns is an error (exit 1, diagnostic on stderr) rather than
  an empty result — the merge cycle reads a zero exit code as "cleanup
  performed", and a silent no-op would have the merge report a cleanup
  that never happened. The same rule covers a failed scan (including a
  `git worktree list` that could not be run — enumeration failures
  raise rather than returning no paths, which is indistinguishable from
  "this repository has no worktrees") and a scan that succeeds but
  yields no removal candidate for a worktree that still exists. A dry
  run is exempt from the last one: there, "what would you remove?" is
  legitimately answered with "nothing". Without `--path` the sweep
  stays lenient — one unreadable repository does not abort the other
  twenty-five — because the fleet-wide result does not rest on a single
  scan.
- A **detached worktree is never force-removed**. The provider's list
  feeds `WorktreeCoordinator.prune_worktrees`, which force-removes any
  worktree whose branch no longer resolves; a detached worktree reported
  with a fake branch name read as "branch deleted" and would have been
  removed with its uncommitted work discarded. The parser now reports no
  branch for a detached worktree, and the coordinator reads the detached
  state from git and skips it — the guard does not depend on the parser.

## Adopted (NOT YET)

- Operator manual testing required (see `docs/worktree/WORKTREE_AUTOREMOVE.md` 6-phase
  guide)
- The 19 merged-clean worktrees across 8 repos (per 2026-07-26 audit) are
  pending cleanup
- SessionEnd hook + cron wrapper are DEFERRED until CLI is validated
