---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: followups-index
---

# `docs/followups/` index

One-line summary: dated follow-up notes — each pairs a bug/task with its
investigation and (when closed) its resolution. This file is the index and
the single source of truth for each note's state; update it whenever a note
is added, resolved, or archived.

## Active follow-ups

Sorted newest-first. **Verified state** is the state confirmed against the
*current code* by the 2026-07-16 audit — which may differ from a note's own
`**Status:**` line (see [Lifecycle](#lifecycle)).

| File | Topic | Verified state (2026-07-16) |
|------|-------|------------------------------|
| `2026-07-15-sb-checkpoint-stash-clobber.md` | Recurring: auto-checkpoint hook re-applies a `git stash` over in-flight subagent edits. | 🔴 **Open** — second observation; fix only *proposed* (Options A/B/C). Culprit lives in external `session-buddy` repo. |
| `2026-06-29-crow-mcp-client-wiring.md` | `mahavishnu mcp start` crash — crow adapter constructed with `mcp_client=None`. | ✅ **Addressed** for stated scope (helper + 3 call sites + tests). Adjacent gaps: no end-to-end env-precedence test; `core/adapters/worker.py:72-75` non-CLI caller still passes `None`. |
| `2026-06-29-dlq-silent-fallback.md` | DLQ silently falls back to a per-process in-memory deque when OpenSearch is down (data loss). | *archived* — see `.archive/` row. |
| `2026-06-29-opensearch-diverged-flags.md` | Duplicate `OPENSEARCH_AVAILABLE` flags can diverge and silently swallow tasks. | ✅ **Resolved for live paths** — `opensearch_integration.py` + `dead_letter_queue.py` share `opensearch_constants.py` (guard test enforces it). Residual: the **deprecated, test-only** `workflow_state.py:17-23` keeps its own flag, but its OpenSearch path is retired — no live divergence risk. |

## Archived (`.archive/`)

Resolved notes, kept for the record. These are **git-tracked and never
deleted** — `.gitignore` re-includes `docs/followups/.archive/` despite the
repo-wide `.archive/` ignore.

| File | Topic | Why archived |
|------|-------|--------------|
| `.archive/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md` | Session checkpoint: 3-wave comprehensive-hooks cleanup (complexity refactor, ty/DRY fix, PEP 735 manifest reshuffle). | ✅ All described changes present in `HEAD` (audit-verified). |
| `.archive/2026-07-15-bodai-hooks-sb-debug.md` | Pickup prompt: debug Session-Buddy MCP transport drops (`-32000`) + audit Bodai Claude Code hook firing. | ✅ **Resolved** — root cause is `.claude/settings.json` flat-layout (silently ignored) + multi-session MCP contention, not a server bug. Failing test pinned at `tests/unit/test_claude_settings_hooks_format.py`; fix documented in paired `.archive/2026-07-15-bodai-hooks-sb-debug-resolution.md` (not auto-applied per multi-session safety policy). |
| `.archive/2026-07-15-bodai-hooks-sb-debug-resolution.md` | Paired resolution doc: root-cause + failing test + proposed fix for the flat-layout bug. | ✅ Resolution written and archived together with its pickup note (per lifecycle rule's "2026-07-15 style"). Open follow-up: multi-session MCP contention architectural fix tracked under new followup entry. |
| `.archive/2026-06-29-agno-adapter-config-field-path.md` | Agno adapter rejected user config via duplicated config classes and silently fell back to Ollama. | ✅ Canonical shared classes + 3 regression tests verified in current code. |
| `.archive/2026-06-29-pydantic-settings-source-resolution.md` | pydantic-settings merge order let YAML mask env/`local.yaml` overrides for nested settings. | ✅ Source-order fix + 36-test regression suite + original reproduction all pass. |

## Lifecycle

How a note moves open → resolved → archived, and how you know which state
it's in.

### Status convention

- Every note carries a `**Status:**` line near the top. Values in use:
  `open` / `Recurring defect` / `Partially resolved` / `Resolved`.
- A `Resolved` claim **should cite the fix location and a named regression
  test** so it can be re-verified. Treat an *uncited* `Resolved` as a claim,
  not a guarantee.

### Closing and archiving

- When a note is genuinely resolved (fix **and** test present), `git mv` it
  into `docs/followups/.archive/`. **Never delete it** — the record must
  survive a clean checkout.
- Move the note's row from the **Active** table to the **Archived** table in
  this index at the same time.
- 2026-07-15 style: some threads instead close by writing a paired
  `-resolution.md` note; when that lands, archive the pickup prompt and its
  companion notes together.

### How you know a follow-up is addressed

- **This index's "Verified state" column is the source of truth** — not the
  note's own `**Status:**` line.
- The 2026-07-16 audit found two notes (`dlq-silent-fallback`,
  `opensearch-diverged-flags`) that self-declare `Resolved` while the current
  code is only partially fixed. That gap is exactly why the verified-state
  column exists and why `Resolved` claims should cite a runnable test.

### Relationship to `.claude/decisions/`

This directory follows the same conventions as `.claude/decisions/`
(a README index plus archive-on-completion into `.archive/`, never delete).
The policy is recorded at `.claude/decisions/followups-lifecycle.md`.
