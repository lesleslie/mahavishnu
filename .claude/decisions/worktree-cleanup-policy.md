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

<!-- Decision rule, Salvage, Lock, Negative rules sections follow in Tasks 1.2 - 1.6 -->