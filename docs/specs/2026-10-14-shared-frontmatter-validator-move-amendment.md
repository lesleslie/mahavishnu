---
title: Shared Frontmatter Validator Move — Amendment to 2026-07-26 Spec
date: 2026-10-14
last_reviewed: 2026-10-14
status: complete
role: canonical
topic: shared-frontmatter-validator
amends: 2026-07-26-shared-frontmatter-validator-design.md
amended-by-plan: 2026-07-26-shared-frontmatter-validator.md
---

# Shared Frontmatter Validator Move — Amendment to 2026-07-26 Spec

## Purpose

Audit the 2026-07-26 spec against the current repo state and capture what
changed since the spec was written, so a followup implementation plan
can be drafted from accurate ground truth rather than stale assumptions.

## Audit findings (2026-10-14)

The 2026-07-26 plan (`docs/plans/2026-07-26-shared-frontmatter-validator.md`,
status `draft`, 1958 lines) and its companion spec are mostly executed.
Phase 1 (foundation in crackerjack) and the consumer-repo script deletions
are already done. This amendment documents the divergence between the
spec's stated state and reality, and identifies the small remaining
work to land the change.

### What the 2026-07-26 spec said

```
crackerjack/validators/                      # NEW PACKAGE
├── __init__.py
├── frontmatter.py           # MOVED from scripts/...
├── git_root.py              # NEW
```

The spec named a new `crackerjack/validators/` package.

### What actually happened

```
crackerjack/services/
├── frontmatter.py            # ACTUAL: validator module lives here, not in validators/
└── frontmatter_validator.py  # MODIFIED: in-process call to frontmatter module
```

**Divergence 1: package placement.** The validator module was placed in
the existing `crackerjack/services/` package, not in a new
`crackerjack/validators/` package. This was probably the right call at
implementation time (less new surface area, mirrors the wrapper's
existing location) but the spec was never updated to match.

**Divergence 2: `git_root.py` was not created as a separate module.**
The plan called for `crackerjack/validators/git_root.py` holding
`get_git_root`. Instead, the function was likely inlined into the
`FrontmatterValidator` class or absorbed into existing
`crackerjack/tools/_git_utils.py` (the plan's Task 1 says it was
"half-wired" via `conftest_reset.py:169`). Not a problem, just a
documentation drift.

**Divergence 3: `crackerjack docs validate` flag name is already
`--repo-root`**, not `--path` as the plan said. The Typer Option
declaration at `crackerjack/cli/docs_cli.py:191` confirms this. The
plan's "Refactor `crackerjack docs validate` CLI subcommand: rename
`--path` → `--repo-root`" task is already done.

**Divergence 4: the duplicate `docs/plans/` typo in `DEFAULT_STORES`
was preserved.** Both the mcp-common script and crackerjack's
`crackerjack/services/frontmatter.py` have
`DEFAULT_STORES = ("docs/adr/", "docs/plans/", "docs/specs/",
"docs/plans/", ".claude/decisions/", "docs/followups/")` — the
`docs/plans/` appears twice and `docs/initiatives/` (now a real
top-level dir in 5+ repos) is missing. This is harmless today
(`discover_files` dedupes by absolute path) but the canonical home
should be `docs/initiatives/`, not `docs/plans/` twice. The amendment
captures this as a small drive-by fix.

### What consumer repos look like (2026-10-14)

```
$ for r in session-buddy akosha crackerjack oneiric mahavishnu; do
    [ -f "/Users/les/Projects/$r/scripts/validate_document_frontmatter.py" ] \
      && echo "HAS_SCRIPT: $r" || echo "no-script: $r"
  done
no-script: /Users/les/Projects/session-buddy
no-script: /Users/les/Projects/akosha
no-script: /Users/les/Projects/crackerjack
no-script: /Users/les/Projects/oneiric
no-script: /Users/les/Projects/mahavishnu
```

**All 5 consumer repos have already deleted `scripts/validate_document_frontmatter.py`.**
The plan's "Delete `scripts/validate_document_frontmatter.py` from 5
consumer repos" task is done. (The `dhara` repo mentioned in the
plan has been merged into mahavishnu per the 2026-09 substrate
consolidation, so the consumer count is 5 not 6.)

### What `crackerjack` looks like (2026-10-14)

- `crackerjack/services/frontmatter.py` exists (867 lines, contains
  `extract_frontmatter`, `validate_file`, `discover_files`,
  `build_parser`, `main`, `LIFECYCLE_VALUES`, `ROLE_VALUES`, etc.)
- `crackerjack/services/frontmatter_validator.py` exists (208 lines,
  imports `from crackerjack.services import frontmatter as _validator` —
  in-process, no subprocess)
- `crackerjack docs validate` CLI subcommand exists and is wired to
  the wrapper via the `validate` Typer function at
  `crackerjack/cli/docs_cli.py:175`
- Tests for both: `tests/unit/test_frontmatter_validator.py` (208 lines)
  and `tests/unit/test_validate_frontmatter.py`

The Phase 1 foundation is complete in crackerjack.

### What `mcp-common` looks like (2026-10-14, post Tier 1)

- `mcp-common/scripts/validate_document_frontmatter.py` still exists.
  It is the canonical source the crackerjack copy was forked from
  (modulo the recent Tier 1 followup: `VocabFileNotFoundError` +
  `--vocab-path` flag, committed as `21223ee` on branch
  `tier1-validator-patherror-2026-10-14`).
- After the cross-repo move is complete, this file should be **deleted
  entirely** — keeping it would re-introduce the drift the move was
  designed to eliminate.

## Decision: amendment scope

The amendment covers three things the original spec/plan did not account
for:

1. **Drive-by: fix the `DEFAULT_STORES` typo in
   `crackerjack/services/frontmatter.py`.** Replace the duplicate
   `docs/plans/` with `docs/initiatives/` (or add it). This is a
   1-line code change that should be folded into the move's first
   commit so the crackerjack-owned validator is correct from day one.

2. **Drive-by: apply the Tier 1 fix to the crackerjack-owned module.**
   The `VocabFileNotFoundError` + `--vocab-path` flag from
   `mcp-common` commit `21223ee` need to be ported to
   `crackerjack/services/frontmatter.py` so the moved module inherits
   the better behavior. The user is the one who controls the
   `mcp-common` version bump, so the timing here is: port to
   crackerjack first, then delete mcp-common's script in the same
   release.

3. **Drive-by: delete `mcp-common/scripts/validate_document_frontmatter.py`**
   once all consumer repos are confirmed running the crackerjack CLI.
   This is the final step that closes the drift loop.

## Decision: skip the spec-vs-actual reconciliation

The spec's diagram is wrong about package placement. Rather than
write a "package placement amendment" section, this amendment states
the actual placement in one line and moves on. The cost of a
textual reconciliation is higher than the cost of just updating the
spec to match reality at some future point (e.g. when someone
references the spec for new work and notices the discrepancy).

## Non-Goals (unchanged from 2026-07-26 spec)

- Consolidating `docs/schemas/document-frontmatter-v1.md` or
  `topic-vocabulary-v1.md` (still seed-copied; tracked separately).
- Consolidating `scripts/regenerate_plan_index.py`.
- Adding a new docs-group command.
- Changing the JSON output shape.

## Remaining work (post-amendment, before execution)

1. **Implementation plan** derived from the original plan with the
   three drive-bys applied. Expected size: ~30 lines of plan
   (the heavy task-by-task instructions in the 2026-07-26 plan are
   mostly already executed; what remains is a small verification +
   release coordination sequence).
2. **Cross-repo execution** in 5 repos: crackerjack (the source
   change), session-buddy, akosha, oneiric, mahavishnu (the
   consumer followup work — `uv sync --upgrade crackerjack` + a
   smoke test that `crackerjack docs validate` works).
3. **Version bumps** in 4 repos (crackerjack, session-buddy, akosha,
   oneiric). User-controlled per `feedback-mcp-common-version-bump-is-user.md`.
4. **No push** without explicit approval per
   `feedback-bodai-push-is-user-controlled.md`.
