---
name: worktree-autoremove
status: built
date: 2026-07-26
owner: mahavishnu
plan: docs/superpowers/plans/2026-07-26-worktree-autoremove.md
policy: .claude/decisions/worktree-autoremove-policy.md
user_docs: docs/WORKTREE_AUTOREMOVE.md
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
- New policy: `.claude/decisions/worktree-autoremove-policy.md` (explicit
  Rule 2 amendment)
- New tests: 15 unit tests in `tests/unit/test_worktree_prune_merged.py`

## Wired

- CLI registered in `mahavishnu worktree` Typer app
- Module-level imports for `monkeypatch.setattr` compatibility
- Multi-signal merge detection: `git merge-base --is-ancestor` +
  merge-commit guard + `git cherry`
- Tri-state dirty check (clean / dirty / undetermined)
- Nickname-aware repo resolution via `repo_manager.get_repo()`
- Two-phase force escalation via `coordinator.remove_worktree`
  (force=False first, then True on block)
- Exit code 1 on partial failure

## Adopted (NOT YET)

- Operator manual testing required (see `docs/WORKTREE_AUTOREMOVE.md` 6-phase
  guide)
- The 19 merged-clean worktrees across 8 repos (per 2026-07-26 audit) are
  pending cleanup
- SessionEnd hook + cron wrapper are DEFERRED until CLI is validated