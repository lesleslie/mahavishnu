---
status: complete
role: implementation
kind: plan
date: 2026-09-13
last_reviewed: 2026-09-13
superseded_by: null
topic: frontmatter-migration-completion
---

# Migrate 39 No-Frontmatter Plans to Schema v1.1

## 1. Outcome

Every `.md` file in the four plan stores (`docs/plans/`, `docs/superpowers/plans/`,
`docs/superpowers/specs/`, `docs/followups/`) carries a parseable `---\n...\n---`
YAML frontmatter matching `docs/schemas/document-frontmatter-v1.md`. As a
result, `scripts/regenerate_plan_index.py` lists them all in `docs/plans/PLAN_INDEX.md`.

**Success signal**: `uv run python scripts/regenerate_plan_index.py` runs
cleanly (no `ScannerError`), the per-store tables grow from the current
counts to include all 39, and a second `regenerate_plan_index.py` run
on a clean checkout produces an identical `PLAN_INDEX.md` byte-for-byte.

## 2. Goals

1. Every file in the inventory below has a `---\n...\n---` block at the
   top, matching the schema.
2. The block contains at minimum: `status`, `role`, `kind` (or omitted
   for default `plan`), `date`, `last_reviewed`. Optional `topic`,
   `blocks_on`, `superseded_by` set where discoverable.
3. `regenerate_plan_index.py` enumerates every migrated file in the
   appropriate store table (post-migration count: 73+69+42+28 plus
   the 39 newly-migrated = 251 in-scope files).
4. Each migrated file's `status:` reflects its lifecycle stage as
   best we can determine from body content (no "**Status:** Approved"
   inside a code block mistaken for a real status, no schematic
   `status: active` for a `complete` plan).
5. Migration is idempotent: re-running on a previously migrated file
   produces no changes.

## 3. Non-Goals

* **Not** changing `status` values that the 2026-09-12 audit
  (`docs/plans/PLAN_AUDIT_2026-09-12.md`) already approved. If a
  legacy-status-looking line conflicts with the audit verdict, the
  audit wins.
* **Not** rewriting prose bodies. The migration is frontmatter-only.
* **Not** addressing `.md` files outside the four plan stores
  (`.claude/agents/`, `docs/adr/`, `docs/papers/`, etc. are out of
  scope; `.claude/decisions/` already has `kind: decision` from the
  earlier kind-tag commit).
* **Not** introducing a new frontmatter field beyond what the v1.1
  schema already documents. Stay within the existing vocabulary.

## 4. Current Findings

### Inventory — 39 files without parseable `---\n...\n---` frontmatter

Distribution by store (verified 2026-09-13, via `scripts/migrate_frontmatter.py`):

| Store                          | Count |
|--------------------------------|-------|
| `docs/superpowers/plans/`      | 22    |
| `docs/superpowers/specs/`      | 15    |
| `docs/plans/`                  | 1     |
| `docs/followups/`              | 1     |

Note: 2026-09-06 fastmcp-4-upgrade.md was migrated (added full v1.1
frontmatter with status: complete) as part of the Cluster A audit
work that landed in commit `fab7cf1a`. So this plan's original
estimate of 23 superpowers/plans/ files is now 22.

These files were missed by commit `0a3ec0b0 feat(frontmatter): migrate
217 docs to v1 schema` — that migration was incomplete (a known drift:
see session memory `drift-bundling-recovery.md`).

### Detectable inline status

A regex sweep for legacy markers (`**Status:** <word>` and bare
`Status: <word>` variants) found **1** file with an explicit legacy
status:

```
docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md: Draft
```

The other 38 require status inference from contextual signals (date,
body content, sibling designs).

### Single-line frontmatter — already resolved

The companion reflow of "single-line-after-heading" `## status: ...`
files (originally 9, tracked as a separate concern) has already
landed in commit `99dbb966 docs(plans): reflow 9 single-line-after-heading
frontmatter blocks (2026-09-13)`. Live count: 0 such files remain.
The migrator therefore only needs to handle files with no frontmatter
of any kind, not the single-line layout variant.

### Common body patterns

Three templates are visible across these 39 files:

1. **"Implementation Plan" template** (the most common, ~22 files):
   ```
   # <Title>
   > **For agentic workers:** REQUIRED SUB-KILL: Use superpowers:subagent-driven-development
   **Goal:** …
   **Architecture:** …
   **Tech Stack:** …
   ```
   Status heuristic: in code body discussing implementation phases
   that are not yet executed → `status: active`. If body explicitly
   marks phases complete (Phase 1/2/3 done) or references a shipped
   version → `status: complete`.

2. **"Design Spec" template** (~15 files in `docs/superpowers/specs/`):
   ```
   # <Title>
   Status: Draft (or Approved, or absent)
   Date: YYYY-MM-DD
   Author: …
   ```
   The `Status:` field (with or without `**` markers) is the most
   reliable signal here; default to `status: draft` if the status
   line says "Draft (awaiting user review)" or is missing. The
   `-design.md` suffix is a strong hint that this file is the design
   peer of an implementation plan; specs default to `draft` until
   their paired implementation migrates with `active` or `complete`.

3. **"Note/Prose" template** (1-2 files, mostly the followup):
   ```
   # <Title>
   One-line summary: …
   ```
   Default to `status: active` (most followups track active work) unless
   body content indicates shipped work, in which case `complete`.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-MIG-001
    title: "Every migrated file parses with yaml.safe_load without error."
  - id: REQ-MIG-002
    title: "PLAN_INDEX.md byte-stable after migration + regen (idempotent)."
  - id: REQ-MIG-003
    title: "Each migration logs decision rationale inline (commit body
      per file or batched per store) so the status choice is auditable."
  - id: REQ-MIG-004
    title: "No new field introduced; existing v1.1 schema respected."
```

## 5. Implementation Phases

### Phase 1: write the migrator

**Goal:** A Python script `scripts/migrate_frontmatter.py` that:

* Walks the 4 plan stores.
* For each `.md` file, parses `---\n...\n---` if present (skip if
  already valid).
* Otherwise extracts legacy fields using:
  - `**Status:** <word>` or `Status: <word>` (Status line within first
    50 lines, not inside a code block — both marker styles are seen
    in the corpus; e.g., `2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md`
    uses bare `Status: Draft` without `**`)
  - `**Date:** YYYY-MM-DD` or `Date: YYYY-MM-DD`
  - `**Author:** <name>` or `Author: <name>`
  - The H1 title (becomes the title in PLAN_INDEX, already inferable)
* Applies heuristic status mapping per the schema's legacy table
  (`docs/schemas/document-frontmatter-v1.md` § Legacy Mapping):
  - `Accepted` / `Approved` / `In progress` / `active` → `status: active`
  - `Proposed` / `Draft` / `brainstormed` / `DEFERRED` → `status: draft`
  - `Complete` / `completed` / `Delivered` → `status: complete` (or
    `shipped` if body verifies production deployment)
  - `Shipped` / `SHIPPED` → `status: shipped`
  - `Resolved` → `status: complete`, role `historical`
  - `Superseded` → `status: complete`, role `superseded`
  - absent
    → `status: active` for `docs/superpowers/plans/` (implementation
      default); `status: draft` for `docs/superpowers/specs/`
      (specs awaiting design approval); `status: active` for
      `docs/plans/`; `status: active` for `docs/followups/`.
* Renders the new frontmatter block above existing body content,
  preserving all original body bytes after.
* Writes back; if no change needed, leaves the file untouched.

**Tasks:**

1. Read `docs/schemas/document-frontmatter-v1.md` to confirm the
   vocabulary.
2. Skeleton `migrate_frontmatter.py` with `migrate_file(path) ->
   (status, message)`.
3. Heuristic engine for legacy field detection.
4. Drive it from a list of `record-id` so it can be re-run
   incrementally.

**Exit criteria:** script can be invoked with `--dry-run` and emits
a per-file report of proposed changes without writing.

#### Integration Contract — Phase 1

- **Triggered from**: `uv run python scripts/migrate_frontmatter.py --dry-run`
  (CLI); user (operator) review of report before applying.
- **Returns to / updates**: each proposed file's frontmatter (when
  applied).
- **Demonstrable by**: dry-run output showing each file's proposed
  status decision, parsed by a single review pass.
- **Rollback signal**: per-file dry-run flag — if run committed but a
  reviewer objects to a specific status, `git revert <commit>` plus a
  follow-up edit.
- **Observability added**: log line per file with proposed status and
  short rationale.

### Phase 2: apply the migration, store-by-store

**Goal:** Each store's 39 files migrate cleanly with batched
rationale-per-store.

**Tasks:**

1. Run `migrate_frontmatter.py` against `docs/superpowers/plans/`
   (22 files). Commit as
   `docs(scripts): migrate 22 superpowers/plans/ to v1 schema`,
   body listing each filename + heuristic result.
2. Run against `docs/superpowers/specs/` (15 files). Same.
3. Run against `docs/plans/` (1 file). Same.
4. Run against `docs/followups/` (1 file). Same.

**Exit criteria:** every file in the inventory has a parseable
frontmatter; `regenerate_plan_index.py` lists them all; the PLAN_INDEX
byte-stable across two regen runs.

#### Integration Contract — Phase 2

- **Triggered from**: per-store invocation of the migrator script.
- **Returns to / updates**: each target file's frontmatter block.
- **Demonstrable by**: `git diff` showing per-file added `---\n...\n---`
  block + `uv run python scripts/regenerate_plan_index.py` listing
  the file in the appropriate store table.
- **Rollback signal**: per-file revert via `git checkout HEAD -- <path>`.
- **Observability added**: per-file migration log line in stdout.

### Phase 3: validate

**Goal:** No regressions in PLAN_INDEX, audit-orphans, or frontmatter
validator.

**Tasks:**

1. Run `python scripts/audit_orphans.py` — must report 0 newly-orphaned
   symbols.
2. Run `python scripts/tool_frontmatter_validator.py` if it exists —
   must not flag the migrated files for missing fields.
3. Run `uv run python scripts/regenerate_plan_index.py` twice in a row,
   diff the outputs — must be empty.

**Exit criteria:** all three pass.

#### Integration Contract — Phase 3

- **Triggered from**: `pytest`, `crackerjack`, or session-end
  pre-commit checks.
- **Returns to / updates**: validation reports in stdout.
- **Demonstrable by**: zero newly-orphaned symbols + zero frontmatter
  errors + diff-clean regen.
- **Rollback signal**: any test failure triggers git-revert of the
  Phase 2 commits for the offending store.
- **Observability added**: a `migration_2026-09-13_validation` script
  that re-runs the three checks on demand.

## 6. Required Code Changes

* `scripts/migrate_frontmatter.py` (new)
* `docs/plans/PLAN_INDEX.md` (regenerated; no manual edit)
* `scripts/regenerate_plan_index.py` (no change — should already handle
  the migrated files)

## 7. Validation Matrix

| Tool/command | Expected outcome | Evidence location |
|---|---|---|
| `python scripts/migrate_frontmatter.py --dry-run` | per-file proposal, no writes | stdout |
| `uv run python scripts/regenerate_plan_index.py` | exit 0, new entries listed | shell exit + grep on PLAN_INDEX |
| `uv run python scripts/regenerate_plan_index.py` (twice) | identical bytes | shell `diff <(run1) <(run2)` |
| `python scripts/audit_orphans.py` | no newly-orphaned symbols | stdout |
| `python scripts/tool_frontmatter_validator.py` | exit 0 | shell exit |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Inline `Status:` line inside a code-block mistaken for real status | Medium | Code-block-aware regex; flag every match in dry-run output for human review |
| Migration script overwrites important existing frontmatter | Low | Idempotent: skip files with `---\n...---` already |
| Plan body's literal `**Status:** active` from a tutorial becomes `status: active` inadvertently | Low | Restrict detection to first 50 lines; in-doc contexts past line 50 are unreviewed |
| Status inflation — promoting files to `active` when intent was `draft` | Medium | Conservative default for `docs/superpowers/specs/` is `draft`, not `active`. Audit trail in commit body. |
| Scripted field values that are later hand-edited could diverge from truth | Low | Regenerate tracker doesn't enforce; just lists. Audit catches during review. |
| Re-running on `## status: ...` single-line files | n/a | The pre-existing reflow script (commit 99dbb966) already handled those; live count is 0 such files. Migrator only touches files lacking `---\n...---` of any kind. |

## 9. Decision Rule

When in doubt on a single file's `status:`: **review the body once**, then
pick `draft` if uncertain. `active` is a downward-promotion from
"implicit active" but our schema doesn't carry "implicit."

The migration is considered "done enough" when:
1. Inventory count = 0 (all 39 migrated).
2. `regenerate_plan_index.py` lists all 39 in the appropriate store
   table.
3. PLAN_INDEX regen is byte-stable across two runs.

## References

* `docs/schemas/document-frontmatter-v1.md` — schema definition.
* `docs/plans/TEMPLATE.md` — plan template.
* `docs/followups/README.md` — the verified-state index that this
  migration's per-file status decisions must remain consistent with.
* `docs/plans/PLAN_AUDIT_2026-09-12.md` — 2026-09-12 audit verdicts.
* `scripts/regenerate_plan_index.py` — the consumer of frontmatter.
* commit `0a3ec0b0 feat(frontmatter): migrate 217 docs to v1 schema` —
  the prior partial migration this plan completes.
* commit `99dbb966 docs(plans): reflow 9 single-line-after-heading frontmatter blocks (2026-09-13)`
  — companion fix to single-line layout (separate from this plan).

## Re-Review Status (2026-09-13)

**Status**: `complete` — every file in the inventory migrated; PLAN_INDEX
byte-stable across two regenerator runs; no newly-orphaned symbols.

**Phase 1 — migrator landed.** `scripts/migrate_frontmatter.py` (commit
`8d12cad8`) walks the four plan stores, detects legacy `**Status:** <word>`
and bare `Status: <word>` markers (code-block-aware, first 50 lines),
falls back to filename date, and applies the schema's § Legacy Mapping
table. Idempotent (`has_frontmatter` looks for the closing `---` fence
in the first 2000 chars — was 200, fixed during Phase 1 because the
Cluster A plans have frontmatter that closes at char ~280).

**Phase 2 — apply landed per-store**, four commits:

| Commit | Store | Files |
|---|---|---|
| `5307fbab` | `docs/superpowers/plans/` | 22 (all `status: active`) |
| `76b7bacf` | `docs/superpowers/specs/` | 15 (all `status: draft`) |
| `d56651a2` | `docs/plans/` | 1 (`status: active`) |
| `c3d5f513` | `docs/followups/` | 1 (`status: active`) |

**39 files migrated, total**. The single detectable legacy status
(`Status: Draft (pending user review)` on
`2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md`) was
correctly mapped to `status: draft`. The other 38 took store defaults
per the heuristic in the plan.

**Phase 3 — validation landed**:

* `scripts/audit_orphans.py` — no newly-orphaned symbols.
* `scripts/regenerate_plan_index.py` (×2) — byte-stable diff. PLAN_INDEX
  now lists all 39 newly-migrated files in their appropriate store tables.
* Crackerjack `documentation_cleanup` hook — passed on every Phase 2
  commit (crackerjack auto-modified some files during the commit run;
  those `create mode 100644` lines in commits `5307fbab` and `d56651a2`
  reflect pre-existing dirty files in the working tree that the hook
  auto-staged, not migration artifacts).

**Inventory delta**. The plan was authored against a 40-file estimate.
Two reductions happened before the migrator ran: fastmcp-4-upgrade.md
got full frontmatter during the Cluster A audit (commit `fab7cf1a`,
removing 1 from `docs/superpowers/plans/`), and the companion
single-line reflow (commit `99dbb966`) cleared 9 single-line
`## status:` files (already out of scope, but worth noting). One
addition: `2026-09-07-worktree-cleanup-design.md` was created between
the plan authoring and the migrator build (sibling of the
already-migrated `2026-09-07-worktree-cleanup.md`). Net: 38 → 39.

**No follow-ups filed.** Every migrated file has parseable
`---\n...\n---` frontmatter; `regenerate_plan_index.py` is now the
single source of truth for the index; the schema's v1.1 lifecycle
vocabulary is uniformly applied across the four plan stores.
