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
| (none yet) | | | |
