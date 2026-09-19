---
status: active
role: canonical
kind: decision
date: 2026-09-19
last_reviewed: 2026-09-19
topic: sdd-bundling-defensive-pattern
---

# SDD Bundling Defensive Pattern

## Context

During plan `2026-09-10-jot-drain` execution, Task 19's implementer
committed `def3eb7a` with `git add .`-style staging. The working tree
held Task 17's staged-but-uncommitted files (3 hook wrappers +
`.claude/settings.json` + capture_hook + integration tests). All
landed on `main` in a single commit. Final state was correct (no
extra files beyond what both tasks intended), but a downstream task's
`git add` reached into an upstream task's staged state.

## Decision rule

In a multi-task SDD plan where upstream tasks have staged-but-uncommitted
work:

- **Downstream tasks MUST use `git add <specific-paths>`** — never
  `git add .` or `git add -A`.
- **Detect dirty trees before committing** — `git status --porcelain`
  is cheap; do it once before each commit. If staged entries exist
  that this task didn't produce, stop and reconcile.
- **The SDD controller runs the audit** — if a task lands with
  unexpected files in the diff, the controller flags the bundling
  and either (a) splits the commit or (b) accepts the bundle with
  an explicit ruling in the ledger.

## Status

Active. First rule for any new SDD plan run on this repo.