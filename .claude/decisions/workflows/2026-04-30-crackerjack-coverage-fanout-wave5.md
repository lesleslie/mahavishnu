---
status: active
role: canonical
date: 2026-07-21
last_reviewed: 2026-07-21
topic: workflows
---

# 2026-04-30-crackerjack-coverage-fanout-wave5 — workflow decision

## Status

Superseded

## Context

Wave-5 of the crackerjack coverage fan-out. Cleaned up the last small zero-coverage files, deep-dove mcp/tools and services/ai, fixed the test_full_publish_success regression, and investigated source cleanup (read-only — deletions deferred to user).

## Decision rule

Re-run this workflow when crackerjack has 4 or fewer small zero-coverage files left and the largest partial-coverage packages still sit below 60%. Expect ~25-min wall-clock; uses 7 parallel python-pro agents.

## Status history

- 2026-04-30 — Created.
- 2026-05-15 — Superseded by crackerjack-coverage-fanout-wave6.js (this workflow is now in `.archive/`).
