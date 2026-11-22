---
status: active
role: canonical
kind: decision
date: 2026-10-13
last_reviewed: 2026-10-13
superseded_by:
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

______________________________________________________________________

## 1. Worktree Cleanup Policy (formerly `worktree-cleanup-policy.md`)

# Worktree Cleanup Policy

## Context

The 2026-09-07 sweep of 31 active Bodai repos found 117 extra worktrees (108 non-main in 20 of 31 repos; zero `[gone]` branches). 86 were removed, 3 were preserved (2 \<9d `agent-*` candidates + 1 `agent-a894dd931068d8836` locked by live Claude PID 74005). The cleanup made tier-rubric + salvage + lock + live-PID decisions in-line; this doc codifies them.

Five existing decisions touch worktree policy: `session-worktree-defaults.md` (Rule 2: never auto-remove), `worktree-autoremove-policy.md` (Rule 2 amendment + Rule 4: --force-reason for dirty merged), `worktree-autoremove-v4-followup.md` (draft, NOT a permission grant), `2026-08-28-cross-repo-fanout-cwd-isolation.md` (cross-repo fanout cleanup), `mahavishnu-tool-preference-policy.md` (unrelated). None address today's findings.

> **On the paths below.** The first three of those decisions were later
> consolidated into this document, and their former paths no longer resolve.
> They are named here as history: the content they carried is in this
> document, under § Amendment to session-worktree-defaults.md Rule 2 and
> § Worktree Auto-Remove v4 Follow-up. A path reference to a decision
> that no longer exists is not a live link — read this document.

## Why this decision

This doc is **additive**. The five existing decisions stay intact. Cross-references are bidirectional: see § Cross-references for the back-links added in the same commit.

______________________________________________________________________

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

______________________________________________________________________

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

The phrase "merged" in this amendment means the worktree's branch has been fully merged into the main branch using the multi-signal check defined in `mahavishnu/core/worktree_prune_merged.py` (ancestry via `git merge-base --is-ancestor`, merge-commit guard, content-equivalence via `git merge-tree --write-tree`, and patch-equivalence via `git cherry` as the final fallback).

**Amendment (2026-11-21) — the deciding signal for a squash.** `git cherry`
compares patch-ids, and a patch-id is computed per commit: merging N commits
produces ONE commit whose diff is the union of N diffs, and that union
matches none of the individual patch-ids. Every commit of a squash-merged
branch therefore shows `+`, and a branch merged by a multi-commit squash — the
fleet's normal case — was classified `not_merged` and never pruned. The
content signal (`git merge-tree --write-tree <branch> HEAD`, merged only when
the merge is a no-op **and** the resulting tree equals `<branch>`'s tree) now
decides a squash, and `git cherry` remains only as the last resort. Any
future automation built to this decision must use the same signal, or it will
ship the multi-commit-squash bug this amendment removes.

**Amendment (2026-11-21) — locked worktrees.** A worktree git reports as
locked (`git worktree list --porcelain`, a `locked` line) is never removed.
The lock is the fleet's existing "do not touch this" marker, and the sweep
honours it unconditionally — there is no override flag.

**Note for the operator (2026-11-21) — the sweep's reach.** This decision
permits *explicit* invocation of the CLI and excludes unattended automation.
The merge pipeline's stage 6 nevertheless ran `mahavishnu worktree prune-merged --json` with no `--repo` and no `--ttl-days`, so every merge
swept every configured repository. That sweep was nearly inert until
2026-11-21 — the enumeration returned nothing for every repository — and
from that date it was effective: its measured radius on this repository was 5
clean, merged, unlocked worktrees, of which 3 belonged to other sessions.

**Amendment (2026-11-21) — stage 6 is scoped.** The merge cycle's stage 6 now
passes `--path <the worktree it just merged>`, so it removes exactly that
worktree and nothing else. The unattended fleet-wide sweep is gone: the
operator's explicit invocation of `mahavishnu worktree prune-merged` is the
only path that sweeps every repository, which is what this decision
permits. The lock guard and the dirty check remain as the second and third
lines of defence.

**Amendment (2026-11-22) — a scoped sweep fails loudly.** `--path` scopes
the SCAN, not only the removal set: the repositories that cannot contain
the named worktree are skipped outright, so their worktrees are never
classified. The owning repository is asked of git
(`git rev-parse --git-common-dir`), because a worktree lives outside its
repository's directory and its path's parents say nothing about who owns
it.

A `--path` that no repository owns is an ERROR, not an empty result: the
command writes a diagnostic to stderr and exits non-zero. Two cases are
errors — git cannot name an owner at all, and git names an owner that is
not among the configured repositories. The reason is this decision's own
logic: the merge cycle reads a zero return code from stage 6 as "cleanup
performed", so a silent no-op would have a merge report a cleanup that
never happened while the worktree stayed on disk. A filter that matches
nothing is the absence of an answer, and only "there was nothing to do"
may answer with success.

The same rule covers a FAILED scan. Under `--path` the whole result
rests on one repository's scan — the owning one — so a scan that raises
is an unknown answer, and the run exits non-zero with the diagnostic on
stderr, including under `--json`, where the JSON payload would otherwise
be the only thing on stdout and the failure would be invisible. Without
`--path` the leniency stands, because the fleet-wide sweep is the
operator's explicit invocation and one unreadable repository must not
cost the other twenty-five; the result there does not rest on a single
scan. The leniency is about the EXIT CODE, not about the silence: the
diagnostic is emitted on stderr in both modes, because stderr cannot
corrupt the JSON stdout contract, and suppressing it made a `--json`
fleet sweep read as "this repository has no worktrees" — a short
candidate list with no explanation anywhere.

A git failure has to REACH that rule rather than being absorbed below
it. The enumeration used to swallow a failed `git worktree list` and
return no paths, which is indistinguishable from "this repository has
no worktrees" — so the sweep reported nothing to do and the merge cycle
read that as a cleanup that had happened. Enumeration failures now
raise, and it is the caller that decides: skip the repository and say
so (fleet sweep), or fail (scoped sweep).

The third unknown answer is a scan that SUCCEEDS and yields no removal
candidate for a worktree that still exists. That is not "there was
nothing to do" — the caller named one worktree, it is still on disk,
and it was not removed. Under `--path` the run exits non-zero. A dry run
is exempt: there, "what would you remove?" is legitimately answered
with "nothing", and the worktree is not supposed to be gone yet.

And a path that is NOT THERE is the one answer that may exit zero: the
worktree is gone, so the desired end state is already reached, and
there is nothing to remove. A path that exists but that git cannot
attribute is a different case — an unknown answer — and stays an error.

The reason has to reach the operator, in both places it can. The
pipeline prints the CLI's stderr, and the merge-log entry carries one
line of it, because the durable record used to say only "the cleanup
failed" and leave the reason in transient output. The SessionEnd
hook's pointer is equally conditional: it points at
`.review-state.json` only when a sticky marker was actually written
for the stage that failed. The cleanup path writes none, so pointing
an operator at that file sent them looking for a reason that was not
there.

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
   `docs/worktree/WORKTREE_AUTOREMOVE.md`.
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
6. `--path` names one worktree and scopes the scan to the repository that
   owns it. A `--path` that no configured repository owns exits non-zero
   with a diagnostic; it never reports an empty sweep as a success.

## Threat model

| Threat | Mitigation |
|---|---|
| An unmerged merge commit is hidden from `git cherry` | Check ancestry, then refuse branches containing merge commits in `main..HEAD`, before using patch equivalence. |
| A squash-merged branch is misread as unmerged because `git cherry` compares per-commit patch-ids | The content signal (`git merge-tree --write-tree`) decides a squash before `git cherry` is consulted; it requires the merge to be a no-op **and** the resulting tree to equal the branch's tree. |
| A live session's clean worktree is removed by an automatic sweep | A locked worktree is never a candidate; the dirty check excludes the rest. |
| A Git status command fails and a dirty worktree is treated as clean | Dirty status is tri-state; `undetermined` is always excluded. |
| A nickname differs from the repository folder name | CLI resolves the repository once and passes its canonical nickname through the helper to the coordinator. |
| A partial sweep looks successful to automation or the shell | Any failed result produces CLI exit code 1 after complete output. |
| User expects a backup for a clean removal | Docs state that clean removals use branch/reflog recovery; backups are for forced dirty removal only. |

## Cross-references

- Original rule: `.claude/decisions/session-worktree-defaults.md` Rule 2
- Plan: `docs/plans/2026-07-26-worktree-autoremove.md`
- Operator guide: `docs/worktree/WORKTREE_AUTOREMOVE.md`
- CLI: `mahavishnu worktree prune-merged`
- v4 worktree types: `docs/adr/015-worktree-and-cache-storage-v2.md` §13
  (`WorktreeHandle`, `RemoteWorktreeProvider`, `Principal`)
- v4 followup for automated cleanup (draft, not yet permitted):
  `.claude/decisions/worktree-autoremove-v4-followup.md`
- **See also**: [worktree-cleanup-policy.md] — tier rubric, salvage procedure, lock + live-PID semantics (2026-09-07)

______________________________________________________________________

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
  from the durable key-value worktree registry, not just `git worktree remove`)
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
   `WorktreeHandle` from the durable key-value registry. The current CLI
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

______________________________________________________________________

**See also**: [worktree-cleanup-policy.md] — tier rubric, salvage procedure, lock + live-PID semantics (2026-09-07)
