---
status: active
role: canonical
date: 2026-07-26
last_reviewed: 2026-07-26
superseded_by: null
topic: worktree-autoremove
---

# Worktree prune-merged — explicit CLI exception

## Amendment to session-worktree-defaults.md Rule 2

The original Rule 2 ("Never auto-removes worktrees") is hereby amended to add the following narrow exception:

> "...EXCEPT via the `mahavishnu worktree prune-merged` CLI, which is permitted to remove *merged* worktrees when explicitly invoked by the user. SessionEnd hooks and cron automation are NOT permitted under this amendment; they require a separate decision."

The scope of this amendment:
- Permits: explicit user invocation of `mahavishnu worktree prune-merged`
- Permits: manual removal of merged worktrees via the existing `mahavishnu worktree remove` command
- Excludes: any SessionEnd automation
- Excludes: any cron or scheduled automation
- Excludes: any removal of un-merged worktrees

The phrase "merged" in this amendment means the worktree's branch has been fully merged into the main branch using the multi-signal check defined in `mahavishnu/core/worktree_prune_merged.py` (ancestry via `git merge-base --is-ancestor`, merge-commit guard, and patch-equivalence via `git cherry`).

## Context

`session-worktree-defaults.md` Rule 2 prohibits automatic removal of
worktrees. Operators nevertheless need a safe, explicit way to remove
worktrees whose changes are already represented on the repository's main
branch.

This decision permits one user-invoked CLI. It does not permit SessionEnd,
cron, or other unattended invocation. The amended rule is recorded in
`.claude/decisions/session-worktree-defaults.md` § Decision rule, item 2.

## Decision rule

1. `mahavishnu worktree prune-merged` may remove only candidates classified
   exactly as `merged` by the multi-signal classifier documented in
   `docs/WORKTREE_AUTOREMOVE.md`.
2. `not_merged` and `undetermined` candidates are never removed.
3. The default scope is merged worktrees whose dirty status is exactly
   `clean`.
4. `--include-dirty` requires an explicit `--force-reason`. Dirty forced
   removals use the coordinator's existing backup path. Clean removals
   do not create backups.
5. SessionEnd hooks, cron wrappers, hidden automated triggers, and the
   `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS` gate are outside this amendment.
   They require a new decision after the CLI passes the plan's Wave 4 manual
   testing sequence.

## Threat model

| Threat | Mitigation |
|---|---|
| An unmerged merge commit is hidden from `git cherry` | Check ancestry, then refuse branches containing merge commits in `main..HEAD`, before using patch equivalence. |
| A Git status command fails and a dirty worktree is treated as clean | Dirty status is tri-state; `undetermined` is always excluded. |
| A nickname differs from the repository folder name | CLI resolves the repository once and passes its canonical nickname through the helper to the coordinator. |
| A partial sweep looks successful to automation or the shell | Any failed result produces CLI exit code 1 after complete output. |
| User expects a backup for a clean removal | Docs state that clean removals use branch/reflog recovery; backups are for forced dirty removal only. |

## Cross-references

- Original rule: `.claude/decisions/session-worktree-defaults.md` Rule 2
- Plan: `docs/superpowers/plans/2026-07-26-worktree-autoremove.md`
- Operator guide: `docs/WORKTREE_AUTOREMOVE.md`
- CLI: `mahavishnu worktree prune-merged`
