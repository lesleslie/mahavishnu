---
status: active
date: 2026-10-14
last_reviewed: 2026-10-14
topic: parallel-sessions-vs-bypass-gate
---

# 2026-10-14 — `--no-consolidation-gate` and parallel sessions

## Context

The 2026-10-13 pre-push consolidation gate (see
[`2026-10-13-prepushconsolidationgate.md`](2026-10-13-prepushconsolidationgate.md))
added a stage 4.5 check that holds back stage 5 push when co-located
worktrees have unmerged WIP or pending commits are not squash-merge-shaped.
It carries an operator escape hatch
`/merge-to-main --no-consolidation-gate` for documented hotfix cases.

On 2026-10-14 that escape hatch was used in a context it was not designed
for: a parallel session held a stash with 3 files targeting the same
canonical filenames (`docs/plans/2026-10-14-decision-adapter-category.md`,
`docs/specs/...`, `.claude/decisions/...`) that the active session had
already committed on `main` under a different shape (3 adapters vs 2,
Decision 3.0 + quantization field, multimodal extension, decision file
at `docs/decisions/` not `.claude/decisions/`).

The bypass-commit synchronization performed `git stash pop` against the
conflicting main content. Git produced conflict markers
(`<<<<<<< Updated upstream` / `=======` / `>>>>>>> Stashed changes`) and
the landed commit (`fd9b61ed`) carried those markers verbatim. The plan
file was ~1.5K lines of conflict-marker text on `main` for roughly 10
minutes until reverted in `b11c72ed`.

This is a new failure mode for the bypass gate. The pre-push gate's
documented purpose (sticky-failure on dirty worktrees, non-squash-merge-
shaped commits) catches one class of risk; it does NOT catch a parallel
session's stash being popped into a conflicting main tree.

## Decision rule

1. **The `--no-consolidation-gate` operator escape hatch requires an
   additional pre-condition**: before invocation, the operator must
   confirm that no parallel session is working on the same canonical
   filenames. Concretely:
   - Run `git stash list`; for each non-empty stash entry, diff its
     `git stash show -p <stash> --name-only` against the target commit's
     path set.
   - If any path overlaps, the bypass is REFUSED. The parallel session
     must reconcile (rebase, drop, or land separately on a different
     filename) before the bypass is retried.
   - This is enforced procedurally, not by a script. The cost of a
     false positive (one extra round-trip) is far less than the cost of
     1.5K lines of conflict markers landing on `main`.
2. **Conflict markers MUST NOT appear in any committed file.** Add a
   `grep -r '<<<<<<<' docs/ .claude/decisions/` fast-hook in crackerjack
   that fails the run if any `<<<<<<<`, `=======`, or `>>>>>>>` line is
   found in a tracked markdown file. This is a belt for the procedural
   rule above.
3. **The bypass does NOT loosen the gate's other checks** (squash-merge
   shape, dirty-worktree hold-back). Per
   `2026-10-13-prepushconsolidationgate.md`, the gate's job is unchanged;
   this decision adds ONE more thing the operator must verify before
   invoking it.

## Status

Active. Recorded from the 2026-10-14 incident (`fd9b61ed` →
revert `b11c72ed`). Review on 2026-11-14; if the crackerjack conflict-
marker guard from Rule 2 lands, downgrade this to "amends
2026-10-13-prepushconsolidationgate" and link the two.
