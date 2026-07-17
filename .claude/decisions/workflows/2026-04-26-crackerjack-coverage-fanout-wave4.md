# 2026-04-26-crackerjack-coverage-fanout-wave4 — workflow decision

## Status

Superseded

## Context

Wave-4 of the crackerjack coverage fan-out. Lifted the smallest remaining zero-coverage tier, added a memory-package deep dive, fixed the 26 remaining regressions, and investigated the cli/handlers shadowing bug. Post-wave state: 73% (18,904 / 70,258 stmts missed) with one stable + one flaky failure.

## Decision rule

Re-run this workflow when crackerjack total coverage drops below 70% or when a new package reaches the smallest-zero-coverage tier. Expect ~30-min wall-clock; uses 12 parallel python-pro agents.

## Status history

- 2026-04-26 — Created.
- 2026-04-30 — Superseded by crackerjack-coverage-fanout-wave5.js (this workflow is now in `.archive/`).
