---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: followups-lifecycle
---

# `docs/followups/` lifecycle

## Context

`docs/followups/` holds dated notes that pair a bug/task with its
investigation and (when closed) its resolution. Historically the directory
had no index, no archiving, and no way to tell a resolved note from an open
one except by opening it and reading a hand-edited `**Status:**` line.

A 2026-07-16 audit verified all eight notes against the current code and
found two that self-declare `Resolved` while the code is only partially
fixed (`2026-06-29-dlq-silent-fallback.md`,
`2026-06-29-opensearch-diverged-flags.md`) — demonstrating that an unverified
status line is a claim, not a guarantee.

This adopts the convention already used by `.claude/decisions/` (a README
index plus archive-on-completion), so the two follow-up stores are
consistent.

## Decision rule

1. `docs/followups/README.md` is the index and the single source of truth
   for each note's verified state. Update it whenever a note is added,
   resolved, or archived.
1. A `**Status:** Resolved` line should cite the fix location and a named
   regression test. Treat an uncited "Resolved" as unverified.
1. When a note is genuinely resolved, `git mv` it into
   `docs/followups/.archive/` — never delete it. The record must survive a
   clean checkout, so `.gitignore` re-includes that path
   (`!docs/followups/.archive/` and `!docs/followups/.archive/**`) despite
   the repo-wide `.archive/` ignore.
1. Move the note's row from the Active table to the Archived table in the
   README at the same time.

## Status <!-- legacy status: Active — see YAML frontmatter -->

Active. Adopted 2026-07-16. Initial backfill moved the three
audit-verified-complete notes (agno config-field-path, pydantic-settings
source-resolution, comprehensive-hooks-cleanup checkpoint) into `.archive/`.
