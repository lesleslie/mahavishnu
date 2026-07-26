---
title: Worktree Prune-Merged CLI
status: active
date: 2026-07-26
audience: operators
---

# Worktree Prune-Merged CLI

`mahavishnu worktree prune-merged` is an explicitly invoked command for
removing worktrees whose changes are already represented on the repository's
main branch. SessionEnd and cron automation are deferred and are not installed
or permitted by the current policy amendment
(`.claude/decisions/worktree-autoremove-policy.md`).

This command is **the only** way to remove worktrees through Mahavishnu. It
classifies candidates using multi-signal merge detection, requires a clean
working tree by default, and exits non-zero if any candidate removal fails.

## Quick reference

The 15 most common invocations:

```bash
# Preview every configured repo
mahavishnu worktree prune-merged --dry-run

# Preview one repo by nickname
mahavishnu worktree prune-merged --repo=dhara --dry-run

# Remove merged-clean worktrees in one repo
mahavishnu worktree prune-merged --repo=dhara

# Apply across every configured repo
mahavishnu worktree prune-merged

# Apply with a TTL gate (only worktrees last touched > N days ago)
mahavishnu worktree prune-merged --ttl-days=7

# Machine-readable dry run
mahavishnu worktree prune-merged --dry-run --json

# Include merged-dirty worktrees (REQUIRES --force-reason)
mahavishnu worktree prune-merged --include-dirty \
    --force-reason "batch cleanup of merged dirty worktrees"

# Single-repo include-dirty with reason
mahavishnu worktree prune-merged --repo=dhara --include-dirty \
    --force-reason "dhara batch cleanup"

# Combined TTL + dry-run + JSON
mahavishnu worktree prune-merged --ttl-days=30 --dry-run --json

# JSON output after an apply
mahavishnu worktree prune-merged --repo=dhara --json

# Pipe JSON to jq for filtering
mahavishnu worktree prune-merged --dry-run --json | jq '.candidates[].branch'

# Inspect audit log for sweep events
grep worktree_prune_merged ~/.local/state/mahavishnu/audit.log | tail -10

# Verify the worktree list shrank after a sweep
git -C /Users/les/Projects/dhara worktree list

# Re-run after sweep to confirm idempotency
mahavishnu worktree prune-merged --repo=dhara --dry-run
# Expected: ✅ No merged worktrees to remove.
```

## What it does

The CLI classifies every worktree in the configured repos using a
**multi-signal merge detector** that lives in
`mahavishnu/core/worktree_prune_merged.py`. The detector applies signals in
order:

1. **Resolve `main`** — verify the branch exists via `git rev-parse --verify`.
   If absent and `master_fallback` is enabled, try `master`. If both fail,
   the worktree is classified `undetermined`.
1. **Ancestry check** — `git merge-base --is-ancestor HEAD <branch>`. If HEAD
   is an ancestor of main, classify `merged`. This handles linear fast-forward
   merges and real merge commits.
1. **Merge-commit guard** — if ancestry fails, scan `main..HEAD` for merge
   commits (`git log --merges`). If any exist, classify `undetermined`. This
   guards against `git cherry`'s `revs.max_parents = 1` filter that would
   hide unmerged conflict-resolution merge commits.
1. **Patch equivalence** — `git cherry <branch>`. With no `+` lines, classify
   `merged`. With any `+` lines, classify `not_merged`. This handles
   squash-merges, rebases, and cherry-picks.
1. **Error fallback** — any subprocess error or timeout returns `undetermined`.

The classifier **fails closed**. `not_merged` and `undetermined` candidates
are never eligible.

Dirty state is also tri-state: `clean`, `dirty`, or `undetermined`. The
default scope is `merged` + `clean`. `dirty` candidates only appear with
`--include-dirty`. `undetermined` is never eligible — a Git status command
that fails (perms, missing worktree, timeout) cannot quietly slip a dirty
worktree into a clean sweep.

## Pre-conditions

The CLI relies on the repository catalog in `settings/ecosystem.yaml`. Each
repo **must** have a `package` field set; this is the canonical identifier the
`RepositoryManager` indexes by. Repos without a `package` field cannot be
resolved by `--repo <key>` and will be silently skipped when iterating.

```yaml
# settings/ecosystem.yaml — required shape
repos:
  - name: dhara
    package: dhara           # REQUIRED for prune-merged
    path: /Users/les/Projects/dhara
    nickname: dhara
    nicknames: [dhara]
    tags: [storage]
    description: Persistent object storage
```

If a repo's `package` field is missing, the Pydantic validator in
`mahavishnu/core/repo_models.py` (Repository class) will reject the manifest
on load. Run `mahavishnu list-repos` to confirm every repo is registered.

## Safety model

The CLI is fail-closed in three layers:

1. **Classification** — only `merged` + (`clean` or `dirty`-with-flag) candidates
   are eligible.
2. **Removal** — every candidate is first sent to
   `WorktreeCoordinator.remove_worktree(force=False)`. The pruner escalates
   only when the coordinator reports a forceable safety block
   (`uncommitted_changes` or `dependency_block`).
3. **Backup semantics**:
   - **Default merged-clean removal**: no backup is created. The branch
     remains available; reflog can recover commits. Recreate with
     `git worktree add <path> <branch>`.
   - **`--include-dirty` removal**: the coordinator detects uncommitted
     changes, requires the supplied reason, creates a backup under
     `~/.local/share/mahavishnu/worktree_backups/`, then performs forced
     removal.

**The command does not guarantee a backup for every removal.** This is
intentional — clean removals rely on branch + reflog for recovery; backups
are reserved for the riskier forced-dirty path.

### Audit log attribution

Every applied sweep writes structured events to
`~/.local/state/mahavishnu/audit.log`:

- `worktree_prune_merged_attempt` — before any removal (records
  `candidate_count`, `ttl_days`, `include_dirty`, `trigger`).
- `worktree_prune_merged_success` — after a clean sweep (records
  `removed_count`, `backup_paths`, `trigger`).
- `worktree_prune_merged_partial` — when some candidates succeeded and others
  failed.
- `worktree_prune_merged_failure` — when all candidates failed.

The `trigger` field is hardcoded to `cli` in this tranche; SessionEnd or cron
triggers are not yet accepted.

## Restore flow

If a sweep removed a worktree you need back, the recovery paths differ by
scenario:

### Clean removal (default mode, no backup created)

The branch is still on disk and can be re-attached:

```bash
# Find the branch (it's still in `git branch -a`)
git -C /Users/les/Projects/dhara branch -a | grep <branch-name>

# Recreate the worktree pointing at the branch
git -C /Users/les/Projects/dhara worktree add <original-path> <branch-name>
```

If the branch was already deleted by a subsequent cleanup, reflog can recover
the commits:

```bash
git -C /Users/les/Projects/dhara reflog | grep <branch-name>
git -C /Users/les/Projects/dhara branch <recovered-branch> <sha>
```

### Forced-dirty removal (backup created under ~/.local/share/...)

The coordinator's `WorktreeBackupManager` created a timestamped tarball
before the forced removal. Restore via:

```bash
# Find the most recent backup for the worktree
ls -lt ~/.local/share/mahavishnu/worktree_backups/ | grep <worktree-name>

# Inspect the backup metadata
cat ~/.local/share/mahavishnu/worktree_backups/<backup-dir>/.backup_metadata.json

# Restore the working-tree files (branches and reflog are unaffected)
tar -xzf ~/.local/share/mahavishnu/worktree_backups/<backup-dir>/contents.tar.gz \
    -C <restore-path>
```

The backup captures the dirty working tree but does **not** restore the
worktree registration itself — recreate the worktree via
`git worktree add` and copy the files in.

## Manual testing guide

This is the operator's playbook for verifying the CLI before relying on it.
Run each phase in order. Stop and investigate if any phase fails.

### Phase 1: Dry-run preview

```bash
# Preview what would be removed (no filesystem mutation)
cd /Users/les/Projects/mahavishnu
uv run --quiet mahavishnu worktree prune-merged --dry-run --json | head -100
```

**Expected output**: JSON with a `candidates` array listing the 19 merged-clean
worktrees across the 8 repos. Each entry has `branch`, `worktree_path`,
`behind`, `merge_status`, `dirty_status`, `last_touched_at`.

**If it fails**: Check `~/.local/state/mahavishnu/audit.log` for the failure
reason. Common issues:

- `ecosystem.yaml` is missing the `package` field for one or more repos →
  add it
- `textual` is not installed in the venv →
  `uv pip install "textual>=8.2.7"`
- The entry point can't import → check
  `uv run python3 -c "from mahavishnu.worktree_cli import worktree_app"` works

### Phase 2: Per-repo dry-run

```bash
# Apply dry-run to a single repo
uv run --quiet mahavishnu worktree prune-merged --repo=dhara --dry-run
```

**Expected output**: human-readable list of dhara's merged worktrees. dhara
has 5 merged-clean worktrees per the 2026-07-26 audit.

### Phase 3: Apply to a single repo

```bash
# Apply to dhara (a safe target — 5 merged-clean worktrees)
uv run --quiet mahavishnu worktree prune-merged --repo=dhara
```

**Expected output**: 5 removal lines, each with `✅` icon, branch name,
worktree path, and `💾 Backup: ...` line. The `💾 Backup:` line is **NOT**
expected for clean removals — the existing coordinator only backs up on
dirty forced removals. Clean removals rely on git reflog for recovery.

Final line: `✅ Removed 5/5 worktree(s).`

### Phase 4: Verify backups

```bash
# Check the audit log
grep worktree_prune_merged ~/.local/state/mahavishnu/audit.log | tail -5
```

**Expected output**: 5 `worktree_remove_success` events (one per worktree)
plus 1 `worktree_prune_merged_success` event (the sweep-level roll-up).

### Phase 5: Spot-check the worktrees

```bash
git -C /Users/les/Projects/dhara worktree list
```

**Expected output**: 5 fewer worktree entries than before Phase 3.

### Phase 6: Re-run for idempotency

```bash
# After Phase 5, the merged-clean worktrees should be gone
uv run --quiet mahavishnu worktree prune-merged --repo=dhara --dry-run
```

**Expected output**: `✅ No merged worktrees to remove.`

If Phase 6 reports candidates again, investigate — the CLI may be
misclassifying a worktree as merged when it isn't.

## Troubleshooting

### "Repo not found: <name>"

**Cause**: The repo's nickname/package isn't in `settings/ecosystem.yaml` or
is missing the `package` field.

**Fix**: Edit `settings/ecosystem.yaml`, ensure the repo entry has `name`,
`package`, `path`, `nickname`, and `nicknames`. The Pydantic model in
`mahavishnu/core/repo_models.py` requires `package`.

### "force_reason is required when --include-dirty is set"

**Cause**: Invoked `--include-dirty` without `--force-reason`. The CLI
deliberately blocks this — dirty forced removals are high-risk and require
operator accountability.

**Fix**: Add `--force-reason "<audit-trail-friendly reason>"`. The reason is
recorded in the audit log and the coordinator's backup metadata.

### "Repository manager not available"

**Cause**: `MahavishnuApp.load()` couldn't initialize the repo manager.

**Fix**: Check that `settings/ecosystem.yaml` exists and parses. Run
`uv run python3 -c "from mahavishnu.core.app import MahavishnuApp;
MahavishnuApp.load()"` for a stack trace.

### "All candidates must have merge_status='merged'" (audit log)

**Cause**: A code-level guard in `WorktreePruner.remove` rejected a candidate.
This indicates a bug in classification, not user error.

**Fix**: Open an issue with the audit log excerpt and the worktree path. Do
not retry the sweep — investigate first.

### Exit code 1 after a partial sweep

**Cause**: Some candidates were removed successfully, but at least one
failed. The CLI prints or serializes all results before exiting 1.

**Fix**: Inspect the failed candidate's `error` field. If the failure was a
transient provider issue (Session-Buddy timeout, etc.), re-run with
`--repo=<nickname>` scoped to just the failed worktree.

### The CLI reports 0 candidates but you know worktrees are merged

**Cause**: Either the dirty state is `undetermined` (a Git status failure),
or the worktree's HEAD is not an ancestor of `main` and contains merge
commits (the merge-commit guard classifies this as `undetermined`).

**Fix**: Verify manually:

```bash
cd <worktree-path>
git merge-base --is-ancestor HEAD main && echo "merged by ancestry"
git log main..HEAD --merges --oneline    # any output = undetermined
git cherry main                          # any "+" = not_merged
git status --short                       # any output = dirty
```

If `git cherry` shows `+` lines but `git log main..HEAD --merges` is empty,
the worktree should classify as `not_merged` (correct refusal). If you
believe it is actually merged, open an issue with the full output.

## Cross-references

- **Policy**: `.claude/decisions/worktree-autoremove-policy.md`
- **Original rule**: `.claude/decisions/session-worktree-defaults.md` Rule 2
- **Plan**: `docs/superpowers/plans/2026-07-26-worktree-autoremove.md`
- **Core module**: `mahavishnu/core/worktree_prune_merged.py`
- **CLI**: `mahavishnu/worktree_cli.py` (`prune-merged_worktrees`)
- **General worktree docs**: `docs/WORKTREE_MANAGEMENT.md`
- **Audit log**: `~/.local/state/mahavishnu/audit.log`