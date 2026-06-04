# Technical Debt Roadmap

One-line summary: consolidates the 5 side discoveries surfaced during
the recent `scripts/test_matrix.py` review (Groups 1-4) and the broader
`.claude/agents/` cleanup work, with effort, risk, and a recommended
order. This is a *plan*, not a backlog — each item still needs its
own PR with its own review.

## Why this file lives here

The follow-up tracker
(`.claude/decisions/test-matrix-review-followups.md`) is for items
*discovered during a specific review*. This file is for items
discovered *along the way* while fixing those — they belong with the
project's repo-local decisions because they have a multi-PR horizon
and benefit from a coordinated approach.

If the count of these files grows past ~5, consider promoting the
structure to `.claude/decisions/roadmap/*.md` and an
`.claude/decisions/roadmap/README.md` index. Today there is one file,
and the parent README indexes it.

## How to pick this up

A future PR should pick **one item at a time** and ship that item
in a single PR. The "Recommended order" section at the bottom
sequences them so a single contributor can knock out several in
sequence without context-switching cost.

For each item:

1. Open the item's PR.
2. Reference this file from the PR description.
3. Update the "Status" row in the per-item table when the PR lands.
4. When all items are resolved, do **not** delete this file —
   archive the resolved version to `.archive/` and start a new
   roadmap for the next round of findings.

## Items

### TD-1 — Backslash-underscore file-format bug in 99 other agent files

- **Severity**: MEDIUM (cosmetic but visible; breaks visual grep)
- **Location**: `.claude/agents/*.md` (the 2 I edited in Group 3 are
  clean; the remaining ~99 still have the bug)
- **Effort**: S (mechanical text replacement across ~99 files)
- **Risk**: LOW (no semantic change, just character substitution)
- **Why it matters**: Every `mcp__X` reference in every agent file
  was written with literal `\_` (backslash + underscore) instead of
  just `__` (double underscore). The character pair is displayed
  correctly in some renderers and as a phantom backslash in others,
  and it breaks `grep` for tool names (`grep "mcp__dhara__put"`
  misses the files with the bug). The 2 files I edited in Group 3
  (M5 and M6) are clean; the other ~99 are not.
- **Suggested approach**:
  1. Write a one-shot Python script that walks `.claude/agents/`,
     finds lines containing `mcp\_\_X\_\_Y` (backslash-underscore
     pattern), replaces them with `mcp__X__Y`, and reports what
     changed.
  2. Run the script with a dry-run flag first to count the
     affected files and the change footprint.
  3. Run it for real. Commit as a single PR.
  4. Verify the `agent_metadata_audit.py` parser still parses all
     101 agents (it should — the parser doesn't care about literal
     vs. escaped underscores, since it operates on `re.search`
     patterns that match either).
  5. Verify the smoke test for `test_matrix.py` still passes (it
     doesn't touch agent files, but a sanity check is cheap).
- **Estimated diff size**: 99 files × ~2 occurrences per file = ~200
  line changes, all in agent frontmatter lines.

### TD-2 — Pre-existing ruff warnings in `scripts/test_matrix.py`

- **Severity**: LOW (4 warnings, all pre-existing; flagged in the
  Group 1 review and explicitly out of scope per "one group at a
  time")
- **Location**: `scripts/test_matrix.py` lines 27, 36, 38, 560
- **Effort**: XS (mostly auto-fixable)
- **Risk**: LOW (auto-fixes are mechanical; the 2 manual ones
  require a careful read)
- **Why it matters**: `python -m ruff check scripts/test_matrix.py`
  reports 4 warnings:
  - I001 import block un-sorted or un-formatted (line 27)
  - UP035 `from typing import Iterable` should be
    `from collections.abc import Iterable` (line 36)
  - N817 CamelCase `ElementTree` imported as acronym `ET` (line 38)
  - F841 local variable `mark` is assigned but never used
    (line 560, in `render_markdown`)
- **Suggested approach**:
  1. Run `python -m ruff check scripts/test_matrix.py --fix` to
     handle the 2 auto-fixable items (I001, UP035).
  2. For N817: rename `ET` to a non-acronym name like `_XML_TREE`
     or restructure the import. The latter is cleaner:
     `from defusedxml import ElementTree as XmlTree` is acceptable.
  3. For F841: delete the dead `mark = "covered" if cell.covered
     else "missing"` line in `render_markdown` (the value is never
     used; the row-marking logic is below it).
  4. Commit as a single PR titled `chore(lint): resolve pre-existing
     ruff warnings in scripts/test_matrix.py`.
- **Estimated diff size**: 4-5 lines.

### TD-3 — Pre-existing `tool_frontmatter_validator.py` ZeroDivisionError

- **Severity**: LOW (validator-script bug, not a content issue;
  surfaces in any clean tree with no `tools/`)
- **Location**: `scripts/tool_frontmatter_validator.py` lines 376,
  391
- **Effort**: XS
- **Risk**: LOW (a 2-line guard fixes it)
- **Why it matters**: The validator crashes with `ZeroDivisionError:
  division by zero` when no tools are found. This happens in:
  - the Mahavishnu repo itself (which has zero `tools/` files
    matching the validator's pattern)
  - any other repo that hasn't adopted the tool-command convention
  The crash hides the report from the user. The validator's other
  subcommands (`fix-ids`, `report-stale`, `add-categories`) work
  fine.
- **Suggested approach**:
  1. In `_print_summary`, add a guard: if `total == 0`, print
     `"No tools found"` and return early.
  2. In `report_results`, also short-circuit if there are no
     results.
  3. Commit as `fix(validator): handle empty tool set without
     dividing by zero`.
- **Estimated diff size**: 4-6 lines.

### TD-4 — Hardcoded `agents_dir` in `scripts/agent_metadata_audit.py`

- **Severity**: LOW (works for the documented use case; confusing
  for anyone who reads the source)
- **Location**: `scripts/agent_metadata_audit.py` line 150
  (`agents_dir = "/Users/les/.claude/agents"`)
- **Effort**: XS
- **Risk**: LOW
- **Why it matters**: The script's `main()` hardcodes a *user's
  global* agents dir. When run from the project root (per
  `.claude/CLAUDE.md`'s "Validation" section), it audits the global
  dir, not the project dir. The script happens to work for the
  current user (me) because both the global and project dirs have
  ~100 agents in the same format. Anyone else who clones the repo
  will get a misleading report.
- **Suggested approach**:
  1. Derive the project agents dir from the script's own location:
     `Path(__file__).resolve().parent.parent / ".claude" / "agents"`.
     This makes the script work from any clone of the repo without
     configuration.
  2. Optionally, accept a CLI arg to override the dir for ad-hoc
     audits of the global dir.
  3. Commit as `fix(audit): derive agents_dir from script location`.
- **Estimated diff size**: 2-4 lines + an `argparse` block if option
  2 is taken.

### TD-5 — 3.3% test coverage (BIG one)

- **Severity**: HIGH (this is the single biggest score lever — the
  per-checkpoint quality score is filesystem-based, and test
  coverage is a top-weighted factor)
- **Location**: project-wide (`mahavishnu/` modules)
- **Effort**: L (real test-writing work; the actual code coverage
  is 2.98% per the conftest hook, target is 80%)
- **Risk**: MEDIUM (writing meaningful tests requires understanding
  what each module does; the test surface is large)
- **Why it matters**: The quality-score report from
  `mcp__session-buddy__checkpoint` consistently shows "Critical:
  Increase test coverage (3.3% → target 80%+)". This is the lever
  that moves the headline number. Every other fix in this roadmap
  is small-change, big-quality; this one is medium-change, very-big
  quality.
- **Suggested approach (sequenced for incremental wins)**:
  1. **Start with the highest-leverage modules**: `mahavishnu/workers/`,
     `mahavishnu/pools/`, `mahavishnu/mcp/`, `mahavishnu/core/`. These
     are the orchestrator's spine; tests here have outsized value
     and the code is already designed for testability.
  2. **Write a `tests/unit/test_<module>.py` per high-leverage
     module** using the `tmp_path` + dependency-injection pattern
     the Group 1 smoke test established. Avoid mocking the
     filesystem; prefer real fixtures.
  3. **Skip the wrapper/adapter code** (`mahavishnu/cli/`,
     `mahavishnu/ingesters/`) until later — these are mostly thin
     glue over `mahavishnu/core/` and the `core/` tests will
     exercise them transitively.
  4. **Use the `scripts/test_matrix.py` tool itself** to find
     gaps: `python scripts/test_matrix.py --project . --stack python
     --types unit,integration --out test-matrix.json` reports
     which components have no tests at all. Use `summary.components_
     with_no_tests` to prioritize.
  5. **Target the 20 components the matrix identifies** as a
     rolling goal. Reaching 80% project-wide probably takes
     ~10-15 PR-sized chunks.
- **Estimated diff size**: 10-50 PRs of 200-500 lines each.

## Recommended order

The 5 items in this roadmap break into 3 size classes:

| Class | Items | Strategy |
|-------|-------|----------|
| **XS (one-liner cleanup)** | TD-2, TD-3, TD-4 | Batch into a single "codebase hygiene" PR. Together they're ~15 lines of changes. Ship as one commit. |
| **S (mechanical sweep)** | TD-1 | Single PR with a one-shot script. Ship as one commit. |
| **L (real work)** | TD-5 | Multi-PR effort. The roadmap captures the strategy; each PR is its own review. |

Suggested sequence for the next contributor who wants to clear
the roadmap:

1. Land TD-2 + TD-3 + TD-4 as one "codebase hygiene" PR.
2. Land TD-1 as a separate PR.
3. Start the TD-5 multi-PR effort, using `scripts/test_matrix.py` to
   identify the next component to cover.

This sequence:
- Closes 4 of 5 roadmap items in 2 PRs (fast, visible quality wins).
- Sets up TD-5 with the right tooling (TD-1 cleans up the agent
  file format so audit-script reports are accurate, TD-2 makes
  `test_matrix.py` lint-clean, TD-3 makes the validator usable).
- Leaves the long-tail coverage work as a separate, paced effort.

## Status

- **TD-1**: open
- **TD-2**: open
- **TD-3**: open
- **TD-4**: open
- **TD-5**: open (long-running, multi-PR)

When an item lands, update its status row and the per-item
"Status" line. When all items are resolved, archive this file to
`.archive/`.
