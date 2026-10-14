---
status: active
role: canonical
date: 2026-10-11
last_reviewed: 2026-10-11
topic: lifecycle
---

# Workflow decisions

Pair every workflow in `.claude/workflows/` with a decision file here.

Lifecycle:

- **Active** — current, run as needed. Workflow lives in `.claude/workflows/`.
- **Superseded** — replaced by a newer workflow. Move the .js to `.claude/workflows/.archive/` and update this file's Status.
- **Archived** — no longer relevant. Move to `.claude/workflows/.archive/` and update Status.

Files use `YYYY-MM-DD-<name>.md` pattern. Status header is `## Status: Active | Superseded | Archived`.

## Index

**No active workflow decisions as of 2026-10-11.** All historical coverage-fanout
decisions (crackerjack waves 1–7 + mahavishnu waves 1–2) have been moved to
`docs/decisions/workflows/.archive/` and their paired `.js` files to
`.claude/workflows/.archive/` as part of the coverage-fanout lifecycle sweep.

The archive index lives at `docs/decisions/workflows/.archive/`. No new
workflows have been added since — see the `feature-delivery-lifecycle` slash
command in `.claude/commands/workflows/` for the canonical new-workflow process.
