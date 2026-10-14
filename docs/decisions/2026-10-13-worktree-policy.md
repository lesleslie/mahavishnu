---
status: active
role: canonical
kind: decision
date: 2026-10-13
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: worktree-management
---

# Worktree Policy (consolidated)

This decision file consolidates three former single-topic decisions that
together govern Mahavishnu worktree lifecycle:

1. Worktree Cleanup Policy (2026-09-07 cleanup sweep codification)
2. Worktree Auto-Remove Policy (prune-merged exception)
3. Worktree Auto-Remove v4 Follow-up (forward-looking v4 proposal)

Each section preserves the original content verbatim. Cross-references
between the three are unchanged.

---

## 1. Worktree Cleanup Policy (formerly `worktree-cleanup-policy.md`)

# Worktree Cleanup Policy

## Context

The 2026-09-07 sweep of 31 active Bodai repos found 117 extra worktrees (108 non-main in 20 of 31 repos; zero `[gone]` branches). 86 were removed, 3 were preserved (2 <9d `agent-*` candidates + 1 `agent-a894dd931068d8836` locked by live Claude PID 74005). The cleanup made tier-rubric + salvage + lock + live-PID decisions in-line; this doc codifies them.

Five existing decisions touch worktree policy: `session-worktree-defaults.md` (Rule 2: never auto-remove), `worktree-autoremove-policy.md` (Rule 2 amendment + Rule 4: --force-reason for dirty merged), `worktree-autoremove-v4-followup.md` (draft, NOT a permission grant), `2026-08-28-cross-repo-fanout-cwd-isolation.md` (cross-repo fanout cleanup), `mahavishnu-tool-preference-policy.md` (unrelated). None address today's findings.

## Why this decision

This doc is **additive**. The five existing decisions stay intact. Cross-references are bidirectional: see § Cross-references for the back-links added in the same commit.

---

## Decision rule

The tier rubric. **First-match-wins by row order.** The classifier emits ONE tier per worktree; the operator's action depends on the tier.

| Tier | Condition (explicit boundaries) | Removal action |
|------|---------------------------------|----------------|
| **A-merged** | `classify_merge_status(worktree_path) == "merged"` AND `is_dirty == False` | `git worktree remove` (no `--force`) — but only via `mahavishnu worktree prune-merged` |
| **A-merged-dirty** | `classify_merge_status(...) == "merged"` AND `is_dirty == True` | `git worktree remove --force --force-reason="<reason>"` per `worktree-autoremove-policy.md` Rule 4 |
| **A-orphan-detached** | Detached HEAD AND branch-name NOT a `git bisect`/`git rebase` pattern AND not in `PLAN_ORPHAN_PATTERNS` | `git worktree remove` (no `--force`); pass `--yes-delete-detached` for the shortcut |
| **A-orphan-detached-dirty** | Detached HEAD AND dirty | `git worktree remove --force` |
| **X** (cross-repo plan-orphan) | Branch matches `PLAN_ORPHAN_PATTERNS` regex AND same-date signature in ≥ 2 repos AND `is_locked == False` | Same as A-merged or A-orphan-detached. **Tier X entries are reported EXCLUSIVELY in `tier_x_cross_repo_orphan` and do NOT appear under Tier A.** |
| **B** | Path matches `<get_worktree_base_path()>/agent-*` OR `*/.claude/worktrees/agent-*` | `git worktree remove --force` per Salvage rule |
| **C** | `9.0 ≤ age_days < 30.0` AND `is_locked == False` AND not classified above | `git worktree remove --force` per Salvage rule |
| **D** | `age_days < 9.0` | Manual review required (might be active) |

### Boundary inclusivity

Pin in code comments: `age_days < 9.0 → D`, `9.0 ≤ age_days < 30.0 → C`, `age_days ≥ 30.0 → A-*`. Never ambiguous.

### Plan-orphan patterns

`PLAN_ORPHAN_PATTERNS` is maintained in `mahavishnu/core/worktree_scan.py` as a tuple of regex patterns. Current contents:

| Pattern | Source plan | Last seen |
|---------|-------------|-----------|
| `^w4-claude-md-breadcrumb` | Wave 4 plan (Aug 2026) | 2026-08-23 |
| `^plan7-phase5` | Plan 7 phase 5 (Aug 2026) | 2026-08-22 |
| `^wave8-diagram-corrections` | Wave 8 diagram corrections (Aug 2026) | 2026-08-16 |

A guard test (`tests/unit/test_worktree_scan.py::TestPlanOrphanPatternsSync`) asserts the doc/code parity.

## Salvage procedure

Before `--force` on any worktree with untracked files, copy untracked files to `~/.mahavishnu/salvage/<YYYY-MM-DD>-<sanitized-worktree-name>/` where `<sanitized-worktree-name>` is `Path(p).name`, then rejected if it equals `.`, `..`, empty, or contains characters outside `[A-Za-z0-9._-]`. Stashes survive `git worktree remove` (they live in the branch reflog, not the worktree directory) and need no salvage. Modified tracked files are recoverable from git history; no salvage.

Path traversal and base-path resolution reuse `mahavishnu/core/worktree_validation.py::WorktreePathValidator` and `mahavishnu/core/paths.py::get_worktree_base_path()`.

## Lock + live-PID semantics

1. **Orphaned `initializing` lock** (no PID in the lock file) → `git worktree unlock` + `git worktree remove`. Safe.
2. **Live Claude PID** (lock file contains `(pid <N>)` AND `ps -p <N>` returns 0) → DO NOT TOUCH. The CLI emits the lock content + PID liveness in the report.
3. **`ps -p` is checked at scan time only**; re-check at removal time is the operator's responsibility (the CLI does not perform removal).
4. **PID reuse validation**: before trusting `ps -p <pid>` liveness, also call `ps -p <pid> -o command=` and verify the command starts with a known pattern (`claude`, `python.*mahavishnu`). Mismatch → treat as `unknown`, not `alive`. PID recycling is real.
5. **`--force -f -f` is the unlock-equivalent** for confirmed-dead PID cases. `git worktree remove --force` alone does NOT bypass locks. (`git worktree remove --help` documents `-f` as repeated-force; the unlock-equivalent uses two `-f` flags.)
6. **Lock file parser**: extract PID via fixed regex `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`. No `eval`, no `exec`, no shell. Invalid format → `pid_liveness = "none"` + `notes: ["unparsable lock format"]`.

## Agent-dispatch reap rule

`EnterWorktree` and dispatched agents SHOULD reap on completion. The CLI emits a list of `agent-*` dispatch leftovers and the user invokes removal explicitly. (No SessionEnd hook — per `worktree-autoremove-policy.md` Rule 2 prohibition.)

This is a soft convention enforced by the scanner, not by tooling. Add `mahavishnu worktree scan` to agent exit checklists for ops.

## Cross-repo plan-orphan rule

When a plan creates worktrees across N repos and the plan completes, all N worktrees are likely orphans simultaneously. Detection: same-date pattern across multiple repos (e.g., 9 repos × `w4-claude-md-breadcrumb` at 15.9d on the 2026-09-07 sweep).

The CLI flags these via `classification: "cross_repo_plan_orphan"` and groups by date-pattern. Pattern list is `PLAN_ORPHAN_PATTERNS` (see Decision rule § Plan-orphan patterns). Add a plan-completion sweep to the post-merge plan checklist.

## Negative rules

What NOT to do:

- **Don't auto-remove** even when `--force` would succeed. The CLI is scan-and-report only.
- **Don't trust the lock file as authoritative**; the liveness check (`ps -p`) is the only signal. Lock content is advisory.
- **Don't invoke `-f -f`** without a fresh `ps -p <pid>` AND command-line identity check (`ps -p <pid> -o command=`).
- **Don't point `--repo=` at paths outside the user's expected workspace** (`~/Projects`). The CLI uses `PathValidator.validate_path` for containment.
- **Don't reuse PIDs** in `ps -p` output without verifying the command line. PID recycling is real.
- **Don't edit `mahavishnu/core/worktree_prune_merged.py`** in cleanup commits; classifier reuse is read-only via import.
- **Don't read `MAHAVISHNU_AUTO_WORKTREE_ROOT`** directly (legacy alias). Use `get_worktree_base_path()` from `paths.py`.
- **Don't modify `BODAI_REPO_REGISTRY.md` as a runtime manifest**; it's human-readable prose.

## Cross-references

- Pickup from: 2026-09-07 worktree sweep (this doc)
- Sibling decisions:
  - `session-worktree-defaults.md` — opt-in per-session worktree isolation (`MAHAVISHNU_WORKTREE_BASE_PATH` env var)
  - `worktree-autoremove-policy.md` — Rule 2 amendment (only `prune-merged` may remove); Rule 4 (`--force-reason` for dirty merged)
  - `worktree-autoremove-v4-followup.md` — future automation constraints; NOT a permission grant
  - `2026-08-28-cross-repo-fanout-cwd-isolation.md` — `Workflow({parallel()})` CWD isolation; `/tmp/<branch>` cleanup
- Implementation: `mahavishnu/core/worktree_scan.py` (the classifier + scan driver)
- Tests: `tests/unit/test_decision_doc_sync.py` (doc/code parity)

> **Note on the back-link target list**: `mahavishnu-tool-preference-policy.md` (tool-steering channels) is intentionally not cross-referenced — it relates to tool-docstring marketing copy, not to worktree lifecycle. (Per plan amendment F43.)

---

## 2. Worktree Auto-Remove Policy (formerly `worktree-autoremove-policy.md`)

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
- Plan: `docs/plans/2026-07-26-worktree-autoremove.md`
- Operator guide: `docs/WORKTREE_AUTOREMOVE.md`
- CLI: `mahavishnu worktree prune-merged`
- v4 worktree types: `docs/adr/015-worktree-and-cache-storage-v2.md` §13
  (`WorktreeHandle`, `RemoteWorktreeProvider`, `Principal`)
- v4 followup for automated cleanup (draft, not yet permitted):
  `.claude/decisions/worktree-autoremove-v4-followup.md`
- **See also**: [worktree-cleanup-policy.md](../../.claude/decisions/.archive/worktree-cleanup-policy.md) — tier rubric, salvage procedure, lock + live-PID semantics (2026-09-07)

---

## 3. Worktree Auto-Remove v4 Follow-up (formerly `worktree-autoremove-v4-followup.md`)

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

---

**See also**: [worktree-cleanup-policy.md](../../.claude/decisions/.archive/worktree-cleanup-policy.md) — tier rubric, salvage procedure, lock + live-PID semantics (2026-09-07)
