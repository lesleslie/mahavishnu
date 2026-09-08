---
status: active
role: canonical
date: 2026-09-07
last_reviewed: 2026-09-07
superseded_by: null
topic: worktree-cleanup
trigger: 2026-09-07 cleanup removed 86 of 117 extra worktrees across 20 Bodai repos; existing policy (worktree-autoremove-policy.md) covers only prune-merged clean-removal; the 86 removals required rules no current decision codified.
---

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
6. **Lock file parser**: extract PID via fixed regex `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`. No `eval`, no `exec`, no shell. Invalid format → `pid_liveness = "none"` + `notes: ["unparseable lock format"]`.

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
