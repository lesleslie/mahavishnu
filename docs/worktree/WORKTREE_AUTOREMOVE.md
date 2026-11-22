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
(`docs/decisions/2026-10-13-worktree-policy.md`).

This command is **the only** way to remove worktrees through Mahavishnu. It
classifies candidates using multi-signal merge detection, requires a clean
working tree by default, and exits non-zero if any candidate removal fails.

## Quick reference

The 15 most common invocations:

```bash
# Preview every configured repo
mahavishnu worktree prune-merged --dry-run

# Preview one repo by nickname
mahavishnu worktree prune-merged --repo=oneiric --dry-run

# Remove merged-clean worktrees in one repo
mahavishnu worktree prune-merged --repo=oneiric

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
mahavishnu worktree prune-merged --repo=oneiric --include-dirty \
    --force-reason "oneiric batch cleanup"

# Combined TTL + dry-run + JSON
mahavishnu worktree prune-merged --ttl-days=30 --dry-run --json

# Restrict the sweep to ONE worktree (this is what the merge cycle's
# stage 6 does: it removes the worktree it just merged, and nothing else)
mahavishnu worktree prune-merged --path=/path/to/worktree --dry-run

# JSON output after an apply
mahavishnu worktree prune-merged --repo=oneiric --json

# Pipe JSON to jq for filtering
mahavishnu worktree prune-merged --dry-run --json | jq '.candidates[].branch'

# Inspect audit log for sweep events
grep worktree_prune_merged ~/.local/state/mahavishnu/audit.log | tail -10

# Verify the worktree list shrank after a sweep
git -C /Users/les/Projects/oneiric worktree list

# Re-run after sweep to confirm idempotency
mahavishnu worktree prune-merged --repo=oneiric --dry-run
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
2. **Ancestry check** — `git merge-base --is-ancestor HEAD <branch>`. If HEAD
   is an ancestor of main, classify `merged`. This handles linear fast-forward
   merges and real merge commits.
3. **Merge-commit guard** — if ancestry fails, scan `main..HEAD` for merge
   commits (`git log --merges`). If any exist, classify `undetermined`. This
   guards against `git cherry`'s `revs.max_parents = 1` filter that would
   hide unmerged conflict-resolution merge commits.
4. **Content equivalence** — `git merge-tree --write-tree <branch> HEAD`.
   This computes the merge in memory and asks the question that matters:
   *would merging HEAD into `<branch>` change anything?* It exits 0 on a
   clean merge and prints the resulting tree. When that tree equals
   `<branch>`'s tree, the merge is a no-op — every change HEAD carries is
   already present — so the branch is `merged`, whatever produced it. Exit 0
   alone is **not** enough: a branch with genuinely new content also merges
   cleanly, and its resulting tree differs. Both conditions are required.
   This is the signal that sees a squash of **any** number of commits; see
   the note on `git cherry` below.
5. **Patch equivalence** — `git cherry <branch>`. With no `+` lines, classify
   `merged`. With any `+` lines, classify `not_merged`. This handles
   squash-merges, rebases, and cherry-picks — but only where the content
   signal above has not already decided.
6. **Error fallback** — any subprocess error or timeout returns `undetermined`.

> **Why a content signal is needed.** `git cherry` compares *patch-ids*, and a
> patch-id is computed per commit. Merging N commits produces **one** commit
> whose diff is the union of the N diffs — a combination that matches none
> of the individual patch-ids. Every commit of a squash-merged branch
> therefore shows `+`, and the branch reads `not_merged` even though its
> content is on `main`. A squash of a **single** commit works by accident
> (the squash commit's diff *is* that commit's diff), which is why a
> one-commit test fixture passed while the multi-commit case — the fleet's
> normal case — did not.

> **Locked worktrees are never removed.** `git worktree lock` is the fleet's
> existing "do not touch this" marker. The sweep skips a locked worktree
> unconditionally: the lock is the refusal, and there is no
> `--include-locked` escape hatch.

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
  - name: oneiric
    package: oneiric         # REQUIRED for prune-merged
    path: /Users/les/Projects/oneiric
    nickname: oneiric
    nicknames: [oneiric]
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
git -C /Users/les/Projects/oneiric branch -a | grep <branch-name>

# Recreate the worktree pointing at the branch
git -C /Users/les/Projects/oneiric worktree add <original-path> <branch-name>
```

If the branch was already deleted by a subsequent cleanup, reflog can recover
the commits:

```bash
git -C /Users/les/Projects/oneiric reflog | grep <branch-name>
git -C /Users/les/Projects/oneiric branch <recovered-branch> <sha>
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

**Expected output**: JSON with a `candidates` array listing the merged and
clean worktrees the sweep would remove. Each entry has `branch`,
`worktree_path`, `behind`, `merge_status`, `dirty_status`, `last_touched_at`.

**How many to expect**: whatever the repository actually holds — the count is
not a fixed number, and it is not 19. Before 2026-11-21 the sweep's
enumeration was blind (the local provider's porcelain parser matched nothing
git emits, so it reported zero worktrees for every repository) and the
classifier mis-read a squash of more than one commit as "not merged". Both
are fixed, so the sweep now sees the worktrees that were always there. On
the mahavishnu repository at that point: 27 worktrees classified `merged`,
22 of them dirty and 19 of those locked, leaving 5 clean, merged and
unlocked. Expect the count to track the repository, not a number in this
document.

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
uv run --quiet mahavishnu worktree prune-merged --repo=oneiric --dry-run
```

**Expected output**: human-readable list of oneiric's merged worktrees. oneiric
has 5 merged-clean worktrees per the 2026-07-26 audit.

### Phase 3: Apply to a single repo

```bash
# Apply to oneiric (a safe target — 5 merged-clean worktrees)
uv run --quiet mahavishnu worktree prune-merged --repo=oneiric
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
git -C /Users/les/Projects/oneiric worktree list
```

**Expected output**: 5 fewer worktree entries than before Phase 3.

### Phase 6: Re-run for idempotency

```bash
# After Phase 5, the merged-clean worktrees should be gone
uv run --quiet mahavishnu worktree prune-merged --repo=oneiric --dry-run
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
`uv run python3 -c "from mahavishnu.core.app import MahavishnuApp; MahavishnuApp.load()"` for a stack trace.

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
git merge-tree --write-tree main HEAD    # exit 0 + tree == main's tree = merged
git cherry main                          # any "+" = not_merged (last resort)
git status --short                       # any output = dirty
```

`git cherry` showing `+` lines is **not** by itself proof that a worktree is
unmerged. A branch merged by a squash of more than one commit always shows
`+`, because the squash commit's patch-id matches none of the individual
commits' — see the note on `git cherry` above. The content signal decides
first: `git merge-tree --write-tree main HEAD` exits 0 **and** prints a tree
equal to `main`'s tree when the worktree's content is already on `main`.

So: `git cherry` shows `+` lines, `git log main..HEAD --merges` is empty, and
`git merge-tree` produces a tree **different** from `main`'s → the worktree
is genuinely `not_merged`, and that refusal is correct. If `git merge-tree`
produces `main`'s own tree, the worktree is merged and the sweep should
offer it.

## Cross-references

- **Policy**: `docs/decisions/2026-10-13-worktree-policy.md` (the consolidated
  record; it carries the explicit-CLI amendment to the "never auto-remove"
  rule and its 2026-11-21 amendments)
- **Plan**: `docs/plans/2026-11-21-prune-squash-merged-detection.md`
- **Core module**: `mahavishnu/core/worktree_prune_merged.py`
- **CLI**: `mahavishnu/worktree_cli.py` (`prune-merged_worktrees`)
- **General worktree docs**: `./WORKTREE_MANAGEMENT.md`
- **Audit log**: `~/.local/state/mahavishnu/audit.log`
