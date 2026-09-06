______________________________________________________________________

## status: active role: implementation topic: persistence date: 2026-07-15 last_reviewed: 2026-09-06 superseded_by: null blocks_on: []

# Session-Buddy Checkpoint Stash-Clobber Pattern (Second Observation)

## **Created**: 2026-07-15 **Status**: Recurring defect — second observation; companion to parent memory **Parent memory**: `session-buddy-checkpoint-hooks-fire-during-subagent-sessions` (`~/.claude/projects/-Users-les-Projects-mahavishnu/memory/session-buddy-checkpoint-hooks-fire-during-subagent-sessions.md`) **Recorded in pickup prompt**: `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` (Step 3e verification + acceptance criterion #6) **Originating session**: 2026-07-15 comprehensive-hooks-cleanup wave (checkpoint at `docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`)

> **Verification (2026-09-06):** *Partially resolved, NOT closed.*
> The session-buddy SubagentDetector infrastructure (`session_buddy/checkpoint/subagent_detector.py`) is in place and wired into both `policy.py` and `orchestrator.py` — but only the **read side**. Per the docstring at `subagent_detector.py:33-41`:
>
> > "The `.write()` method has no in-codebase caller at present; the producer (creating `<working_dir>/.session-buddy/subagent.lock` when a subagent starts) is owned by the subagent-runtime team and tracked externally. Until the producer lands, the re-check branch (`subagent_active_during_capture`) is effectively a no-op; the primary `wait_until_idle` gate still protects end-of-task commits because it uses the same lockfile with fail-open → True semantics."
>
> In practical terms: `SubagentDetector.is_active()` returns False when the lockfile doesn't exist, and nothing in this codebase creates the lockfile. So the stash-clobber protection is **constructed but inert** — it would activate if/when an external producer creates the lockfile, but no such producer is wired today. The followup's "Option A" (detect-and-defer) is *structurally* in place but functionally dormant.
>
> Action: keep this followup `active`. Add a sibling note that the **producer half** (lockfile creation at subagent start, owned by the subagent-runtime team) is the actual remaining work. Plan reference: `docs/superpowers/plans/2026-08-10-auto-checkpoint-implementation-summary.md` (C-1).

## Summary

A second manifestation of the subagent-checkpoint interference pattern
was observed in the originating session: the auto-checkpoint hook
**re-applied the stash while the subagent was still working**, not just
between commits. This is a *working-tree corruption* pattern, distinct
from the parent memory's *commit-ordering* pattern (auto-checkpoint
commits appearing between plan and implementer commits).

## Symptom

- A subagent is dispatched (e.g. via Task tool) and begins editing files.
- A Session-Buddy auto-checkpoint fires mid-task.
- The checkpoint hook performs `git stash` followed by `git stash pop`
  (or equivalent stash cycle).
- The `git stash pop` re-applies stashed state *while the agent is
  still editing*, clobbering the agent's in-flight changes.
- After subagent completion, `git status` does not reflect the agent's
  expected output; instead it shows the pre-stash snapshot.

## Why this is distinct from the parent memory's symptom

| Aspect | Parent memory | This observation |
|---|---|---|
| Corruption target | Commit graph (extra commits between plan and implementer) | Working tree (stale files overwrite live edits) |
| Trigger event | Auto-checkpoint commit creation | `git stash pop` re-application |
| Recovery shape | `git reset --soft BASE` + targeted `git add <files>` | Same, plus `git checkout -- <files>` if working tree was overwritten with stale state |
| Detection latency | Visible in `git log` after the fact | Visible in `git status` immediately after subagent completion |
| Severity (silent loss) | Low (commits recoverable from reflog) | Medium (in-flight edits can be permanently lost if not snapshotted) |

## Recovery (when observed)

1. Stop dispatching further subagents until the working tree is clean.
1. `git stash list` — confirm the offending stash entry exists; do NOT
   drop it yet.
1. Inspect the stash contents: `git stash show -p stash@{N}` — verify
   it matches pre-subagent state (not the agent's intended output).
1. Restore the agent's intended output via one of:
   - Re-dispatch the agent for the affected files only (preferred when
     the clobber is widespread).
   - Reconstruct from the agent's intermediate output captured in the
     task transcript (use sparingly; transcripts aren't always complete).
1. Surgical `git reset --soft BASE` + targeted `git add <files>` to
   reconstruct the intended commit (identical to parent memory recovery).
1. **Then** drop the stash: `git stash drop stash@{N}`.
1. Disable or fix the offending checkpoint hook before dispatching
   another subagent.

## Recommended fix (proposed)

Make checkpoint hooks *idempotent against active subagent work*:

- **Option A (preferred)**: Detect an active subagent dispatch (e.g.
  presence of a Task-tool marker in working state) and skip stash
  operations during that window. Re-emit the checkpoint *after* the
  subagent commits.
- **Option B**: Replace the stash cycle with a working-tree-only
  snapshot (e.g. `git diff > /tmp/snapshot.patch`) that does not
  require re-application via `git stash pop`. The checkpoint then
  records a snapshot reference without mutating the working tree.
- **Option C (defensive)**: Capture a content-hash of the working tree
  before the stash and refuse the `git stash pop` if the post-stash
  working tree has drifted from the agent's last seen state.

## Tracking

- Originating observation: 2026-07-15 comprehensive-hooks-cleanup wave
  (checkpoint at `docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`).
- Recorded in pickup prompt: `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md`
  (Step 3e verification + acceptance criterion #6).
- Parent memory: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/session-buddy-checkpoint-hooks-fire-during-subagent-sessions.md`.
- Resolution doc (when complete): `docs/followups/2026-07-15-bodai-hooks-sb-debug-resolution.md`
  (per pickup prompt Step 6).
