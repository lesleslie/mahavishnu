---
status: active
role: canonical
date: 2026-07-21
last_reviewed: 2026-07-21
topic: lifecycle
---

# Workflow decisions

Pair every workflow in `.claude/workflows/` with a decision file here.

Lifecycle:

- **Active** — current, run as needed. Workflow lives in `.claude/workflows/`.
- **Superseded** — replaced by a newer workflow. Move the .js to `.claude/workflows/.archive/` and update this file's Status.
- **Archived** — no longer relevant. Move to `.claude/workflows/.archive/` and update Status.

Files use `YYYY-MM-DD-<name>.md` pattern. Status header is `## Status: Active | Superseded | Archived`.

Index:

| Decision file | Workflow | Status | Notes |
|---|---|---|---|
| [2026-04-26-crackerjack-coverage-fanout-wave4](2026-04-26-crackerjack-coverage-fanout-wave4.md) | `crackerjack-coverage-fanout-wave4.js` | Active | Wave-4 crackerjack coverage lift to 73% |
| [2026-04-30-crackerjack-coverage-fanout-wave5](2026-04-30-crackerjack-coverage-fanout-wave5.md) | `crackerjack-coverage-fanout-wave5.js` | Active | Wave-5 crackerjack deep-dive + regression fix |
| [2026-05-15-crackerjack-coverage-fanout-wave6](2026-05-15-crackerjack-coverage-fanout-wave6.md) | `crackerjack-coverage-fanout-wave6.js` | Active | Wave-6 crackerjack final-mile + stop-condition |
| [2026-05-22-crackerjack-cleanup-wave7](2026-05-22-crackerjack-cleanup-wave7.md) | `crackerjack-cleanup-wave7.js` | Active | Wave-7 crackerjack cleanup (7 user actions) |
| [2026-06-12-mahavishnu-coverage-fanout](2026-06-12-mahavishnu-coverage-fanout.md) | `mahavishnu-coverage-fanout-wave-2026-06-12.js` | Active | Mahavishnu wave-1, 8 modules at ~94.7% |
| [2026-06-12-mahavishnu-coverage-fanout-part2](2026-06-12-mahavishnu-coverage-fanout-part2.md) | `mahavishnu-coverage-fanout-wave-2026-06-12-part2.js` | Active | Mahavishnu wave-2, next 8 modules |
