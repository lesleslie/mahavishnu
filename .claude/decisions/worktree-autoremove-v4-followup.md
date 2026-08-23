---
status: draft
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
superseded_by: null
blocks_on: ["worktree-autoremove-policy"]
topic: worktree-autoremove-v4-followup
related:
  - "worktree-autoremove-policy"
  - "../../docs/adr/015-worktree-and-cache-storage-v2"
  - "../../docs/adr/015-worktree-and-cache-storage-v3"
---

# Worktree auto-remove v4 follow-up — deferred

This is a **forward-looking** decision doc. It does NOT modify the
existing prohibition in `worktree-autoremove-policy.md`. All
content here is a proposal for a future, separate decision.

## Why this doc exists

`worktree-autoremove-policy.md` correctly prohibits automated removal
of worktrees (no SessionEnd hook, no cron, no hidden triggers). It
permits only explicit user CLI invocation:
`mahavishnu worktree prune-merged` (with the multi-signal classifier
in `mahavishnu/core/worktree_prune_merged.py`).

The user explicitly requested that a future automation be tracked as
a followup, even though the current prohibition is in force. This doc
captures the design constraints that any future automation must
satisfy. **It is not a permission grant.**

## Current v4 cross-references (added 2026-08-23)

The existing CLI commands (`prune_worktrees`, `prune_merged_worktrees`,
`prune_abandoned`) operate on the legacy `WorktreeProvider` ABC
interface and return `dict[str, Any]`. They are unaffected by the v4
type work because v4 §5 preserves backward compatibility.

When v4's `WorktreeHandle`-based interface is in production use,
the prune commands should be augmented (not replaced) with:

- A new `principal: Principal` argument for audit attribution
- A new `--bundle-cleanup` flag for `RemoteWorktreeProvider`-backed
  worktrees (purge the bundle in S3 + remove the `WorktreeHandle`
  from the Dhara worktree registry, not just `git worktree remove`)
- Logging to the audit log (v4 §11 keyspace:
  `mahavishnu:audit-log:<date>:<handle_id>:<seq>`)

## Constraints any future automation MUST satisfy

1. **Same multi-signal classifier.** Any auto-prune must use the
   existing merge-detection logic in
   `mahavishnu/core/worktree_prune_merged.py` (ancestry via
   `git merge-base --is-ancestor`, merge-commit guard, patch-equivalence
   via `git cherry`). `not_merged` and `undetermined` candidates are
   **never** auto-pruned.

2. **Principal scoping.** Auto-prune runs under a service principal
   (`Principal.anonymous()` or a dedicated service principal). Each
   removal writes an audit log entry per v4 §11.

3. **Rate limit + gate.** Default proposal: once per 24 h, gated by
   `MAHAVISHNU_WORKTREE_AUTOPRUNE_DAYS` env var. Per-deployment
   override.

4. **Backup of dirty worktrees.** A candidate with dirty status is
   never auto-removed; it is either backed up first or skipped.

5. **Remote-bundle cleanup.** For `RemoteWorktreeProvider`-backed
   worktrees, the prune must also purge the S3 bundle and the
   `WorktreeHandle` from the Dhara registry. The current CLI
   `worktree prune-merged` does not know about this; v4 followup
   required.

6. **Per-worktree exception log.** If any single worktree fails to
   prune (e.g., dirty status, missing main branch, permission denied
   on S3 bucket), the auto-prune skips it, logs the failure, and
   continues with the next candidate. **Failures do not abort the
   batch.** A separate alarm fires if the failure rate exceeds a
   threshold (per v4 §16 SRE observability).

7. **Pre-requisite: `RemoteWorktreeProvider` production-ready.**
   v4 §18 names `RemoteWorktreeProvider` as a Phase 1 stub. Auto-prune
   cannot ship until this provider is production-ready (real S3 client,
   real bundle roundtrip, real SHA-256 verification). This is
   flagged as a Phase 1 dependency.

## Open questions

- Scheduler: APScheduler vs. the `mahavishnu/workflows/` infrastructure
  vs. a separate cron entry. Each has different operational
  characteristics (in-process vs. out-of-process; observability;
  dependency on the Mahavishnu daemon).
- Multi-tenant safety: can one user's auto-prune accidentally
  affect another user's worktree? Per-v4 §5 `Principal` partitioning
  must be enforced.
- Locking: if a user is interactively running `worktree prune-merged`
  at the same time the auto-prune runs, do we serialize? (v4 §14
  `lock()` is the abstraction; full Redis SETNX + fencing token
  implementation is still pending.)

## Status

**Draft.** This doc does NOT modify the prohibition in
`worktree-autoremove-policy.md`. To activate any automation,
a **new** decision must be written that:
- supersedes this doc with a final-ratified status
- adds explicit acceptance criteria (gating, scope, rate limits)
- ships the prerequisite `RemoteWorktreeProvider` production-ready
