# Deferred MEDIUM / LOW Findings — `scripts/test_matrix.py` review

One-line summary: tracks the medium- and low-severity items from the recent
multi-agent review of `scripts/test_matrix.py` and the surrounding
`.claude/decisions/`, `.claude/agents/`, and `.claude/commands/...` files. These
items were intentionally **not** fixed in the original PR; this file is the
pickup list for future work.

## Why this file lives here

The repo has no dedicated follow-up directory (no `docs/todos/`, no
`docs/follow-ups/`, no `.claude/decisions/pending/`, no root `TODO.md`).
`.claude/decisions/` is the closest existing convention: it is the
repo-local store for decisions and policy, and `removed-scripts.md`
already lives there. We use the same directory rather than introduce a
new one, with a filename that makes the file's role as a *follow-up
tracker* explicit (`test-matrix-review-followups.md`, not
`test-matrix-decision.md`).

If a future contributor adds 5+ more deferred-item files, consider
promoting this directory layout to `.claude/decisions/pending/*.md` and
an `.claude/decisions/README.md` index. (See LOW #8 in Group 2.)

## How to pick this up

A future PR should pick **one group at a time** and ship all items in
that group in a single PR. Do not mix groups — each group touches a
different sub-area of the repo and reviewers will be different.

1. Pick a group below.
1. Read each item in the group, including the "Why it matters" paragraph.
1. For each code-level fix, add a unit test (the script has no test
   suite today; the *minimum* is a smoke test in `tests/unit/`
   asserting the script runs end-to-end against a fixture project).
1. Run `python scripts/test_matrix.py --project . --stack python
   --types unit,integration --out /tmp/test-matrix.json` to confirm no
   regression.
1. Update this file: mark the item as resolved with the PR link, or
   delete it if no longer applicable.

When all items in a group are resolved, do **not** delete this file —
archive the resolved version to `.archive/` and start a new follow-up
doc for the next review.

## Group 1 — `scripts/test_matrix.py` code follow-ups

**Status: RESOLVED (commit landed; 13-test smoke suite in
`tests/unit/test_test_matrix.py`)**

Code-level changes in the matrix generator. Line numbers below refer
to the pre-resolution state of `scripts/test_matrix.py` (post
Wave 1+2). Each item was fixed and a smoke test was added; resolutions
are noted in the per-item "Status" line.

### H4 — N×M discovery in `assemble_python_matrix`

- **Severity**: HIGH (in the context of a deferred-item list)
- **Location**: `scripts/test_matrix.py:337-339`
- **Effort**: S
- **Why it matters**: `discover_python_tests(project, test_type)` is
  called inside the `(component × test_type)` loop, so a project with
  20 components and 5 test types triggers 100 filesystem walks when
  one walk per test type (5 total) would suffice. On a large monorepo
  this is the difference between instant and seconds.
- **Suggested fix**: Hoist discovery out of the per-component loop. Run
  `discover_python_tests(project, t)` once per test type, then iterate
  components against the cached mapping. The downstream
  `map_test_files_to_components` call also does not need to be inside
  the per-component loop — call it once per test type, then look up.

### M2 — `--stack mixed` pollutes component list on Python-only projects

- **Severity**: MEDIUM
- **Location**: `scripts/test_matrix.py:632-637`
- **Effort**: S
- **Why it matters**: The Go detection block in mixed mode adds *every*
  non-excluded top-level dir as a "Go component". On a Python-only
  project (e.g. this one, which has no `*.go` files) the resulting
  matrix still lists `htmlcov/`, `dist/`, `backups/`, etc. as Go
  components with zero coverage. The output is noisy and the resulting
  coverage percentage is misleading.
- **Suggested fix**: Gate Go/Node detection on the presence of the
  relevant project markers (`go.mod`, `package.json`, `src/`). The
  Python block already does this implicitly via `mahavishnu/`
  detection; mirror that pattern.

### M3 — Module-level `_MARKER_FILE_CACHE` masks file changes

- **Severity**: MEDIUM
- **Location**: `scripts/test_matrix.py:243-257`
- **Effort**: S
- **Why it matters**: The cache is keyed by file path only. If a test
  file is edited between two invocations of `_has_marker`, the cached
  marker set is reused. This is fine for a single CLI run, but the
  module-level lifetime means the script is unsafe to import as a
  library and call multiple times against changing test files.
- **Suggested fix**: Cache by `(mtime, markers)` tuple. On lookup,
  compare stored mtime to current `Path.stat().st_mtime`; if changed,
  re-read the file. Alternatively, scope the cache into a class or
  context manager and pass it explicitly.

### M4 — `assemble_python_matrix` returns `uncovered_components` that `main()` discards

- **Severity**: MEDIUM
- **Location**: `scripts/test_matrix.py:355` (return), and the
  discarded callers at `:649, :651, :655, :661, :663, :664`
- **Effort**: S
- **Why it matters**: The function builds an `uncovered_components`
  mapping as a side effect of the matrix build, but `main()` throws
  it away with `_`. Either the data is valuable and should reach the
  JSON output, or the code that builds it is dead. The current state
  is the worst of both: computation cost paid, value never seen.
- **Suggested fix**: Surface it in the JSON output as
  `summary.components_with_no_tests` (a list of `{"component": "...",
  "missing_test_types": [...]}` objects), or change the return type to
  drop the second tuple element and inline the uncovered-tracking
  logic where it's used (currently nowhere).

### M10 — `--out` has no path validation

- **Severity**: MEDIUM
- **Location**: `scripts/test_matrix.py:684-686`
- **Effort**: S
- **Why it matters**: A user could pass `--out /etc/mahavishnu/matrix.json`
  or `--out /tmp/../../etc/passwd` and the script would write there.
  Most CLI tools that emit a project-relative artifact validate that
  the output path stays under the project root.
- **Suggested fix**: After resolving `args.out`, assert
  `args.out.resolve().is_relative_to(Path.cwd())` (or against
  `args.project.resolve()` if project-relative output is the desired
  semantics). Apply the same check to `--out-md` at `:698-699`.

### M11 — `parse_coverage_xml` returns filenames verbatim

- **Severity**: MEDIUM
- **Location**: `scripts/test_matrix.py:293-317`
- **Effort**: S
- **Why it matters**: The function returns filenames as Cobertura
  records them (e.g. `mahavishnu/core/app.py`). The matrix keys
  components as `mahavishnu/core` (directory-style). Cross-referencing
  the two requires the caller to know the convention; the function
  itself does not document the format, so the caller has to guess.
- **Suggested fix**: Either document the return format in the
  docstring (verbatim Cobertura paths) or normalize to the matrix key
  style (strip the extension and treat the parent dir as the
  component).

### LOW #7 — `_IMPORT_RE` doesn't handle multi-line parenthesized imports

- **Severity**: LOW
- **Location**: `scripts/test_matrix.py:130-133`
- **Effort**: S
- **Why it matters**: A test file written as
  `from mahavishnu\n    .core import X` is not currently matched. The
  Wave 1+2 fix handled the no-dot case (`from mahavishnu import X`) but
  not the multi-line dotted case. As long as every test in the project
  uses single-line imports, the bug is invisible.
- **Suggested fix**: Allow optional whitespace **and** newlines between
  `mahavishnu` and the dot. The current `\s+` between `mahavishnu` and
  the dot group already accepts whitespace; verify with a test that
  the regex matches the multi-line case after the fix.

### LOW #10 — `frozen=True` on `ComponentCoverage` is misleading

- **Severity**: LOW
- **Location**: `scripts/test_matrix.py:59-65`
- **Effort**: XS
- **Why it matters**: `frozen=True` prevents reassignment of the
  dataclass attributes but does not prevent in-place mutation of
  mutable defaults like `files: list[str] = field(default_factory=list)`.
  A future reader will reasonably assume the lists are also
  immutable, which is not true.
- **Suggested fix**: Drop `frozen=True` (and document the dataclass as
  value-like but not deeply immutable), or convert the lists to
  `tuple`s and use `frozen=True` honestly. The former is the smaller
  change.

### LOW #11 — `assemble_node_matrix` and `assemble_go_matrix` put files only in the first test type

- **Severity**: LOW
- **Location**: `scripts/test_matrix.py:378` (node), `:406` (go)
- **Effort**: S
- **Why it matters**: The `covered` flag is set for *all* test types
  (because `bool(matched)` doesn't care which `t` we're in), but the
  `files` list is only populated for `t == test_types[0]`. Downstream
  consumers reading `cells[component][type].files` will get an empty
  list for every type except the first, even when coverage is real.
- **Suggested fix**: Replicate the same `files` list across all `t`
  values, matching how `covered` already works. If the intent is
  "Node/Go don't distinguish test types", drop the per-type `files`
  field and put it at the component level.

### LOW #15 — Filename heuristic produces phantom components

- **Severity**: LOW
- **Location**: `scripts/test_matrix.py:157-182`
- **Effort**: S
- **Why it matters**: `infer_component_from_filename` returns
  `mahavishnu/<stem>` based on the test file name, but the stem may
  not correspond to an actual subpackage. If the result is not in the
  `detect_components` output, the matrix cell shows a "covered" flag
  for a component that doesn't exist, which the validator can mistake
  for a real coverage signal.
- **Suggested fix**: In `map_test_files_to_components`, when the
  inferred component isn't in the valid set, fall back to the catch-all
  `mahavishnu` bucket (the same fallback that already exists for the
  `None` case).

### Group 1 resolution notes

All 10 Group 1 items were fixed in a single commit, with a 13-test
smoke suite in `tests/unit/test_test_matrix.py`. The smoke test pins
each fix so future regressions are caught at the unit level.

| Item | Resolution | New line range in `scripts/test_matrix.py` |
|------|------------|--------------------------------------------|
| H4 | Discovery hoisted: `discover_python_tests` and `map_test_files_to_components` are now called once per test type; `per_type_mappings` caches the result. Loop count dropped from `N×M` to `M`. | `assemble_python_matrix` ~358-393 |
| M2 | Node detection gated on `package.json`; Go detection gated on `go.mod`. Python-only projects no longer list `htmlcov/`, `dist/`, `backups/`, `docs/`, `scripts/`, `tests/` as Go components. | `main()` ~700, 707 |
| M3 | Cache now stores `(mtime_ns, markers)` tuples. On lookup, `Path.stat().st_mtime_ns` is compared; if changed, file is re-read. `OSError` on `stat` is handled. | `_MARKER_FILE_CACHE` ~252, `_has_marker` ~265-285 |
| M4 | `summary.components_with_no_tests: list[{"component", "missing_test_types"}]` added to JSON output. Computed in `build_summary` from the cells (the simpler alternative, not threaded through assemblers). Assemblers now return just the cells dict (the uncovered tuple element was dropped). | `build_summary` ~477-498 |
| M10 | New validation loop after `project.resolve()`: both `args.out` and `args.out_md` must be `is_relative_to(project_root)`. Error message: `f"error: {label} {resolved} is outside the project root {project_root}"`. Returns 1 on failure. | `main()` ~673-686 |
| M11 | Docstring updated to state: "Returns `{relative_path_from_project: line_rate}` — paths are verbatim Cobertura paths (relative to the project root, NOT stripped of extension)." No code change. | `parse_coverage_xml` ~321-333 |
| LOW #7 | No code change needed. Verified empirically: the regex's `(?:\s*\.\s*\|\s+)` already matches multi-line imports (`\s` matches newlines in Python regex). A regression test now pins this. | unchanged (test added) |
| LOW #10 | `frozen=True` dropped. Docstring note added: "Value-like but not deeply immutable — `files` and `gaps` lists are mutable. If you need an immutable view, copy with `dataclasses.replace()`." | `ComponentCoverage` ~59-72 |
| LOW #11 | `files=matched if t == test_types[0] else []` replaced with `files = list(matched)` hoisted out of the type loop. All `t` values now get the same file list. | `assemble_node_matrix` ~396-417; `assemble_go_matrix` ~424-444 |
| LOW #15 | New `valid_components: set[str] \| None` parameter on `map_test_files_to_components`. When the inferred component isn't in the set, the test file is bucketed into the catch-all `"mahavishnu"` bucket. Passed from `assemble_python_matrix` as `set(components)`. | `map_test_files_to_components` ~189-216 |

**Smoke test added**: `tests/unit/test_test_matrix.py` (445 lines, 13
test functions). Covers: detect_components filtering, multi-line
import regex, docstring-ignore, phantom-component fallback, full
pipeline run, unsafe-path rejection, unknown-test-type rejection,
coverage.xml parsing, `ComponentCoverage` mutability, summary field
presence, and markdown rendering.

**Lint**: 4 pre-existing warnings in `scripts/test_matrix.py` remain
out of scope for this PR (I001 import sort, UP035 `Iterable` from
`collections.abc`, N817 `ET` acronym, F841 unused `mark` variable in
`render_markdown`). The new test file is clean.

## Group 4 — Post-Group-1 findings

Items discovered during the Group 1 review or smoke-test writing. Not
in scope for the original Group 1 PR.

### M-NEW-1 — `_IMPORT_RE` captures the `import` keyword as the head

- **Severity**: LOW
- **Location**: `scripts/test_matrix.py:130-133`
- **Effort**: XS
- **Why it matters**: A test file written as
  `from mahavishnu import X` (no submodule — the rare-but-legal case
  where a test imports the package itself) is mapped to the component
  `"mahavishnu/import"` instead of the catch-all `"mahavishnu"` or a
  real component. The regex's first alternative greedily captures the
  word "import" as the head, because the second alternative requires
  a dot, and the `\s+` path between `mahavishnu` and the head doesn't
  kick in when the head is the literal token "import" the way a
  future reader might expect. The smoke test pins this behavior with
  a comment so a future contributor can either accept it (rare case)
  or fix it.
- **Suggested fix**: When the captured head is `"import"`, treat the
  result as the catch-all `"mahavishnu"` bucket. Or rewrite the
  regex to require at least one dot before the head for the `from`
  alternative, so `from mahavishnu import X` doesn't match (and
  falls through to filename-based discovery). Either is fine; the
  first is the smaller change.

**Status: RESOLVED.** Chose the first option: in
`infer_component_from_imports`, when the captured head is the
literal token `"import"`, return `None` so the caller's existing
fallback chain (`map_test_files_to_components`) routes the file
through the filename heuristic and then the catch-all bucket.
The smoke test was updated to assert `None` (the correct behavior)
instead of `"mahavishnu/import"` (the previously documented bug).
All 13 smoke tests pass after the fix.

## Group 2 — Decision-doc wording follow-ups

**Status: RESOLVED (committed; 2 files rewritten + 1 new index file)**

Docs-level changes in `.claude/decisions/removed-scripts.md`,
`.claude/CLAUDE.md`, and the new `.claude/decisions/README.md`. These
are content-quality issues, not code correctness — none of them break
a build, but each one is the kind of imprecision that will mislead a
future contributor. Resolutions are noted per-item at the end of the
group.

### M7 — `privacy_matrix.py` removal reason is awkwardly phrased

- **Severity**: MEDIUM
- **Location**: `.claude/decisions/removed-scripts.md:15`
- **Effort**: XS
- **Why it matters**: The current text ("Would imply regulatory authority
  a script cannot have") is technically correct but reads like legal
  hedging. A future contributor reading the policy should immediately
  understand *why* privacy classification is out of scope, not have to
  decode the wording.
- **Suggested fix**: Rewrite to explain that privacy classification is
  contextual legal/policy work requiring human sign-off, and that a
  generic script cannot produce a defensible classification. Example:
  "Privacy classification requires legal/policy review on a
  case-by-case basis; a generic script would produce a false sense of
  authority."

### M8 — `release_checklist.py` reason hand-waves "adequately"

- **Severity**: MEDIUM
- **Location**: `.claude/decisions/removed-scripts.md:14`
- **Effort**: XS
- **Why it matters**: "The LLM produces release checklists adequately
  at runtime" is a justification that will be challenged every time
  someone considers adding the script back. A future contributor needs
  the *criterion* — what makes a release checklist something the LLM
  handles correctly — not a vibe-check.
- **Suggested fix**: Make the criterion explicit. Example: "Release
  checklists are repo-context summaries that the LLM can generate from
  `git log` and `pyproject.toml` on demand; a pre-built script would
  freeze the checklist shape and rot against repo changes."

### M9 — Self-dating counts in the opening

- **Severity**: MEDIUM
- **Location**: `.claude/decisions/removed-scripts.md:3, 7`
- **Effort**: XS
- **Why it matters**: "Six scripts were previously referenced... Five
  are staying removed; one is being implemented" will rot the moment a
  7th script is referenced. A reader of the doc two releases from now
  will not know whether 5+1=6 was accurate at write time or has been
  superseded.
- **Suggested fix**: Rephrase as a description of the *policy*, not a
  tally. Example opening: "This document records scripts referenced
  from `required_scripts:` blocks in tool command frontmatter that are
  not committed, and the policy for handling such references."

### M10 (docs) — "Defer" rows lack a "Revisit when" trigger

- **Severity**: MEDIUM
- **Location**: `.claude/decisions/removed-scripts.md:13-17`
- **Effort**: S
- **Why it matters**: Three scripts are marked "Defer" with no criterion
  for un-deferring. A future contributor who wants to revisit one has
  to redo the analysis the original author did.
- **Suggested fix**: Add a "Revisit when" sentence or column per
  defer-row. Example for `dependency_report.py`: "Revisit when a
  CVE-feed integration is added to the project." Example for
  `telemetry_audit.py`: "Revisit when SLO contracts land in
  `settings/slo.yaml`."

### LOW #7 (docs) — `## Decisions` section in `.claude/CLAUDE.md` is under-specified

- **Severity**: LOW
- **Location**: `.claude/CLAUDE.md:24-26`
- **Effort**: S
- **Why it matters**: The current section is a single line pointing at
  the directory. A new contributor won't know when to add a decision
  file, what the difference is between `.claude/decisions/` and
  `docs/adr/`, or what the expected file shape is.
- **Suggested fix**: Expand to mirror the style of the `## Validation`
  section above it. Cover: when to add a file (a non-trivial choice
  that future readers will benefit from understanding), the difference
  between this directory and `docs/adr/`, and a one-line template
  (e.g. "## Decision / ## Context / ## Decision rule").

### LOW #8 (docs) — `.claude/decisions/` lacks an index

- **Severity**: LOW
- **Location**: `.claude/decisions/` (no `README.md` present)
- **Effort**: XS
- **Why it matters**: With one file today this is fine. With five the
  directory becomes a junk drawer. A `README.md` index listing
  decision files (one line each) keeps the directory navigable.
- **Suggested fix**: Add `.claude/decisions/README.md` listing each
  file with a one-line summary, sorted newest-first. When a new file
  is added, add a row to the index.

### LOW #9 (docs) — Decision rule ambiguous about empty `required_scripts: []`

- **Severity**: LOW
- **Location**: `.claude/decisions/removed-scripts.md:29-34`
- **Effort**: XS
- **Why it matters**: The rule is stated as "Do not add speculative
  `required_scripts:` entries". A reader could reasonably interpret an
  empty list `[]` as a placeholder that the rule forbids. The intent
  is the opposite: an empty list means "no scripts are required", which
  is a legitimate value.
- **Suggested fix**: Add a clarifying sentence: "An empty list is
  acceptable and means 'no required scripts'; only non-empty lists
  pointing at uncommitted scripts are forbidden by this policy."

### Group 2 resolution notes

| Item | Resolution | Where |
|------|------------|-------|
| M7 | Rewrote the row to explain the criterion (legal/policy sign-off) rather than legal-hedging phrasing. | `removed-scripts.md` table |
| M8 | Rewrote the row to state the criterion (LLM generates from `git log` + `pyproject.toml` on demand; a pre-built script would freeze shape and rot). | `removed-scripts.md` table |
| M9 | Replaced the "Six scripts were previously referenced... Five are staying removed" tally with a policy-focused description. | `removed-scripts.md` opening |
| M10 (docs) | Added a "Revisit when" column to the table. Each defer-row now has a concrete trigger. | `removed-scripts.md` table |
| LOW #7 (docs) | Expanded the `## Decisions` section in `CLAUDE.md` to cover: when to add a file, when to use `docs/adr/` instead, expected file shape, index pointer. | `.claude/CLAUDE.md` |
| LOW #8 (docs) | Created `.claude/decisions/README.md` as a 2-row index. Sorted newest-first. | new file: `.claude/decisions/README.md` |
| LOW #9 (docs) | Added a clarifying sentence to the Decision rule: empty list is acceptable; only non-empty lists pointing at uncommitted scripts are forbidden. | `removed-scripts.md` Decision rule |

The pre-existing `tool_frontmatter_validator.py` ZeroDivisionError on
"Total Tools: 0" was observed during verification but is unrelated
to Group 2 (it's a validator-script bug, not a content issue in
the consumer tool commands).

## Group 3 — Architecture follow-ups

**Status: RESOLVED (committed; 4 files touched)**

Cross-cutting items in `.claude/agents/` and the `quality-validation.md`
tool command. The first two are labeling bugs from the recent review;
the last two are pre-existing structural issues the review surfaced
but did not address. Resolutions are noted per-item at the end of the
group.

### M5 — `mcp__dhara__put` is mislabeled for a SQL-focused agent

- **Severity**: MEDIUM
- **Location**: `.claude/agents/database-operations-specialist.md:3`
- **Effort**: XS
- **Why it matters**: The `database-operations-specialist.md` is
  documented as covering "SQL, migrations, and query optimization", but
  the parenthetical on `mcp__dhara__put` calls it the "persistence
  layer". `put` is a KV-with-TTL primitive, not a SQL tool. A future
  agent caller will look at the frontmatter and conclude this agent
  can run schema migrations through `put`, which it cannot.
- **Suggested fix**: Either swap the parenthetical to a SQL-appropriate
  tool (e.g. `mcp__dhara__query` if it exists, or `mcp__dhara__migrate`
  if applicable) or re-label `put` parenthetically to make clear it is
  for non-relational persistence state, not the SQL workflow the
  agent is named for.

### M6 — `mcp__dhara__aggregate_patterns` is time-series telemetry, not architecture

- **Severity**: MEDIUM
- **Location**: `.claude/agents/architecture-council.md:3`
- **Effort**: XS
- **Why it matters**: `aggregate_patterns` is described in the
  frontmatter as "pattern aggregation" alongside `mcp__akosha__search_code_patterns`,
  but the two are not peers. `aggregate_patterns` is time-series
  telemetry about *which patterns have been observed*; `search_code_patterns`
  is a structural code-graph query. Putting them side-by-side
  suggests the architecture council can answer "what patterns exist in
  the codebase?", when in fact it can only answer "what patterns have
  been observed in the telemetry stream?".
- **Suggested fix**: Drop the `aggregate_patterns` reference from the
  frontmatter (the council doesn't need it for its primary job) or
  relabel the parenthetical to make the time-series nature explicit
  (e.g. "telemetry-derived pattern frequency").

### LOW #8 (pre-existing) — Stray troubleshooting sections in `quality-validation.md`

- **Severity**: LOW (pre-existing, out of scope for the recent review)
- **Location**: `.claude/commands/tools/development/testing/quality-validation.md:64-116`
  (the prompt cited `:59-112`; the actual stray content extends to `:116`)
- **Effort**: S
- **Why it matters**: After the "Dependencies" section ends at line 62,
  the file restarts with a "Verify user is in required groups" bullet
  and two full "Issue 3: Resource Not Found" / "Issue 4: Timeout"
  troubleshooting sections that don't belong in a Quality Validation
  Toolkit. These are leftovers from a template that was never
  trimmed. The file is currently used by `required_scripts: scripts/test_matrix.py`,
  so the noise is at least visible.
- **Suggested fix**: Delete lines 64-116 (the stray groups check, both
  Issue sections, and the trailing "Getting Help" block). Verify the
  remaining file is still valid YAML frontmatter and a coherent
  Quality Validation toolkit.

### LOW #9 (pre-existing) — Agent files have no YAML frontmatter

- **Severity**: LOW (pre-existing, codebase-wide)
- **Location**: All files in `.claude/agents/`
- **Effort**: L
- **Why it matters**: Every agent file uses a collapsed single-line
  frontmatter (`## name: ... description: ... model: ...`) rather
  than the YAML delimiter style used by tool commands. The validation
  script `scripts/agent_metadata_audit.py` reports
  "unknown: 101" because it expects YAML. This is a pre-existing
  codebase-wide issue that the recent review didn't introduce.
- **Suggested fix**: Two options, in order of preference:
  1. Retrofit YAML frontmatter across all 101 agent files. Mechanical
     transformation; safe but tedious.
  2. Rewrite `agent_metadata_audit.py` to parse the current
     single-line `name: ... description: ... model: ...` format.
     Smaller blast radius; preserves the existing convention.

  Either fix removes the "unknown: 101" report. Option 2 is the
  smaller change and matches the project's apparent preference for
  compact frontmatter.

### Group 3 resolution notes

| Item | Resolution | Where |
|------|------------|-------|
| M5 | Relabeled `mcp__dhara__put` parenthetical to make clear it is non-relational persistence state, not a SQL tool. Cleaned up the same pre-existing backslash-underscore file-format bug. | `.claude/agents/database-operations-specialist.md` |
| M6 | Dropped the `mcp__dhara__aggregate_patterns` reference entirely. Council's primary job is architecture review, not telemetry pattern aggregation. | `.claude/agents/architecture-council.md` |
| LOW #8 (pre-existing) | Deleted stray troubleshooting content (lines 64-116): "Verify user is in required groups", "Issue 3: Resource Not Found", "Issue 4: Timeout or Performance Issues", "Getting Help" — all leftovers from an untrimmed template. | `.claude/commands/tools/development/testing/quality-validation.md` |
| LOW #9 (pre-existing) | Rewrote `extract_frontmatter` in `scripts/agent_metadata_audit.py` to parse the collapsed `## name: ... description: ... model: ...` format. Handles both `description: <text>` and `description: >- <text>` variants. | `scripts/agent_metadata_audit.py` |

Verification: ran the parser against all 98 agents in `.claude/agents/`.
Result: 98/98 parsed, 0 unknown. Real model distribution surfaces:
sonnet 63, opus 17, haiku 15, haiku-4.5 3. "No critical metadata
issues found" is the new output for METADATA ISSUES section.

The pre-existing `tool_frontmatter_validator.py` ZeroDivisionError on
"Total Tools: 0" is unrelated to Group 3.

## Status

- **Group 1**: RESOLVED (10/10 items). Smoke test added. See the
  "Group 1 resolution notes" table inserted at the end of the
  Group 1 section.
- **Group 2**: RESOLVED (7/7 items). Doc-only changes: rewrote
  `removed-scripts.md`, expanded `CLAUDE.md` Decisions section, new
  `.claude/decisions/README.md` index. See the "Group 2 resolution
  notes" table.
- **Group 3**: RESOLVED (4/4 items). Fixed M5/M6 agent labels,
  deleted stray troubleshooting content from `quality-validation.md`,
  rewrote audit script to parse the collapsed frontmatter format
  (98/98 agents now parse, real model distribution surfaces). See the
  "Group 3 resolution notes" table.
- **Group 4**: RESOLVED (1/1 item: M-NEW-1 regex `import`-keyword
  bug fixed by returning `None` from the parser and letting the
  caller's fallback chain route to the catch-all bucket).

When a group is picked up, update this file to record the resolving
PR link or mark the item as no-longer-applicable.
