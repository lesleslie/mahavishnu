# 2026-05-15-crackerjack-coverage-fanout-wave6 — workflow decision

## Status

Superseded

## Context

Wave-6 of the crackerjack coverage fan-out (likely final). Small focused wave on the last low-coverage tier with a stop-condition verdict — beyond this, agent cost exceeds value. Post-wave state: 71% (17,912 / 70,258 stmts missed), zero hard failures.

## Decision rule

Re-run this workflow as the final-mile pass when crackerjack has a handful of low-coverage files left and the previous wave's verify report flagged "small wave recommended." Expect ~15-min wall-clock; uses 4-5 parallel python-pro agents. Do not run beyond this wave without an explicit cost/benefit review.

## Status history

- 2026-05-15 — Created.
- 2026-05-22 — Superseded by crackerjack-cleanup-wave7.js (this workflow is now in `.archive/`).
