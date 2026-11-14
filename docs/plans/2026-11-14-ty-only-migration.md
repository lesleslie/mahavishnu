---
status: complete
role: implementation
kind: plan
date: 2026-11-14
last_reviewed: 2026-11-14
superseded_by: null
topic: ty-only-migration
title: "Migrate the fleet from mypy-syntax suppressions to ty"
---

# Ty-Only Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ty the only type checker in the Bodai fleet — remove every mypy-syntax
suppression, drop mypy configuration, and leave the `ty-ignore-syntax` hook as the
enforcing gate.

**Architecture:** Three phases in strict dependency order. Phase A deletes what is
provably inert (2,711 bracketed mypy codes that ty never reads). Phase B converts
what is live (105 blanket `# type: ignore` directives) into specific
`# ty: ignore[<rule>]` directives, then fixes the defects that conversion exposes.
Phase C removes mypy's configuration and enables the hook so the policy is
machine-enforced from then on.

**Tech Stack:** ty 0.0.104, Python 3.14, `tokenize` for directive parsing,
`crackerjack.tools` for the reusable migration tooling.

**Spec:** `docs/decisions/ty-ignore-codes.md` (the policy this plan enforces).

## Global Constraints

- **Never add a `Co-Authored-By:` trailer** to a commit message.
- **Author email must be `les@wedgwoodwebworks.com`** in every repo.
- **Push is user-controlled** — never push.
- **Never edit another session's WIP.** Use `git commit --only <paths>` with explicit
  paths. Do not use `--no-verify`; do not kill the pre-commit hook.
- **Line length 88.** `from __future__ import annotations` first in every source file.
- **ty, not mypy.** A ty diagnostic is named by the code ty actually reports.
- **A ty suppression is line-based**: it must sit on the same line as the diagnostic
  it suppresses. A directive on the closing line of a multi-line expression is dead.
- **Only real COMMENT tokens count.** A `# type: ignore` inside a string or docstring
  is not a directive and must not be edited.
- **Match offsets are relative to the comment token's string**, not to the file line.
  They must be added to the token's start column before slicing a line.
- **Cache directories are not source**: `.crackerjack/`, `.venv/`, `node_modules/`,
  `dist/`, `htmlcov/` hold vendored copies of the source and must be excluded from
  every scan.

## Review Focus

Five failure modes this migration invites that no per-repo task's tests directly
exercise:

1. **A directive placed on the wrong line.** Converting a blanket to
   `# ty: ignore[rule]` on the old directive's line leaves it dead if ty attributes
   the diagnostic to a different line — the conversion must place the directive on
   the line ty reports, and assert the result is not `unused-ignore-comment`.
2. **A line with two different diagnostics.** A blanket suppresses both; a specific
   directive must list both rules, or the second diagnostic resurfaces.
3. **A directive inside a string or docstring.** Editing it corrupts user-visible
   text. The migration must touch COMMENT tokens only.
4. **A deletion that empties a block.** Removing a comment-only line that was the
   sole content of an `except:` clause leaves an empty block and a syntax error.
5. **A repo whose `src.include` hides the tree being migrated.** The four core repos
   scope ty to `<pkg>/**/*.py`, so `ty check tests` measures nothing. Any migration
   that observes ty's output must override `src.include` per tree or it will
   conclude "nothing to do" for every test file.

---

### Task 1: Build the reusable migration tool

**Files:**
- Create: `crackerjack/crackerjack/tools/ty_suppression_migrate.py`
- Test: `crackerjack/tests/unit/tools/test_ty_suppression_migrate.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `find_directives(text: str) -> list[Directive]` — every mypy-syntax directive in
    real COMMENT tokens, each with `line`, `col`, `kind` (`"bare"` | `"bracketed"`),
    and `codes`.
  - `strip_directives(text: str, targets: set[tuple[int, int]]) -> str` — removes the
    text of the directives at the given `(line, col)` positions.
  - `convert_blanket(text: str, rules_by_line: dict[int, list[str]]) -> str` —
    replaces a bare `# type: ignore` on a line with `# ty: ignore[r1, r2]`.
  - `main(argv) -> int` — CLI with `--mode {delete-bracketed,delete-dead,convert-blanket}`,
    `--repo PATH`, `--python PATH`, `--dry-run`.

- [x] **Step 1: Write the failing test for `find_directives`**

Assert it returns only real comments: a file containing `# type: ignore` inside a
docstring yields zero directives, while the same text in a comment yields one.

- [x] **Step 2: Run the test to verify it fails**

Run: `crackerjack/.venv/bin/pytest tests/unit/tools/test_ty_suppression_migrate.py -q --no-cov`
Expected: FAIL — module does not exist.

- [x] **Step 3: Implement `find_directives` and `strip_directives`**

Use `tokenize.tokenize` over the file bytes. For each `COMMENT` token, match
`#\s*type:\s*ignore(\[[^\]]*\])?`. Record `line = token.start[0]`,
`col = token.start[1] + match.start()`. To strip, group the spans by line, sort
descending, and slice with the absolute column. Never touch text outside a
COMMENT token.

- [x] **Step 4: Run the test to verify it passes**

Run: `crackerjack/.venv/bin/pytest tests/unit/tools/test_ty_suppression_migrate.py -q --no-cov`
Expected: PASS.

- [x] **Step 5: Write the failing test for `convert_blanket`**

A line `# type: ignore` with `rules_by_line = {7: ["invalid-argument-type"]}` becomes
`# ty: ignore[invalid-argument-type]`. A line with two rules becomes
`# ty: ignore[a, b]`.

- [x] **Step 6: Run the test to verify it fails**

Expected: FAIL — `convert_blanket` not defined.

- [x] **Step 7: Implement `convert_blanket` and `main`**

`convert_blanket` replaces the matched directive text in place, preserving the
surrounding line. `main` wires the three modes:
- `delete-bracketed` — remove every bracketed mypy directive.
- `delete-dead` — remove bare directives that ty reports as
  `unused-type-ignore-comment`.
- `convert-blanket` — for each bare directive, strip it, run ty over the affected
  tree with `src.include` overridden, read back the diagnostics that appear on that
  line, and write `# ty: ignore[<rules>]`.

- [x] **Step 8: Run the test to verify it passes**

Expected: PASS.

- [x] **Step 9: Verify the tool on a real repo in `--dry-run`**

Run: `crackerjack/.venv/bin/python -m crackerjack.tools.ty_suppression_migrate --mode delete-bracketed --repo /Users/les/Projects/oneiric --dry-run`
Expected: a count of bracketed directives, and **no file modified**.

- [x] **Step 10: Commit**

```bash
git commit --only crackerjack/tools/ty_suppression_migrate.py \
  tests/unit/tools/test_ty_suppression_migrate.py \
  -m "feat(tools): add a strip-and-observe tool for migrating ty suppressions"
```

---

### Task 2: Fix the vacuous default scan path in `ty_ignore_syntax`

**Files:**
- Modify: `crackerjack/crackerjack/tools/ty_ignore_syntax.py:190-195`
- Test: `crackerjack/tests/unit/tools/test_ty_ignore_syntax.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the tool's default `paths` argument becomes `[Path(".")]` instead of
  `[Path("crackerjack")]`.

**Why:** The hook registers this tool with no path argument, so it scans
`crackerjack/` — a directory that exists only in crackerjack itself. In every other
repo the hook scans **zero files and passes**. This is the same vacuous-gate shape
already fixed in `ty_ratchet`.

- [x] **Step 1: Write the failing test**

A default-path invocation against a temp repo containing `pkg/mod.py` and
`tests/test_mod.py`, each with a mypy-syntax directive, must report findings from
both files.

- [x] **Step 2: Run the test to verify it fails**

Expected: FAIL — the default scans only `crackerjack/`, which does not exist.

- [x] **Step 3: Change the default to the repo root**

`default=[Path(".")]` and update the help text to "Files or directories to scan
(default: the repository root)."

- [x] **Step 4: Run the test to verify it passes**

Run: `crackerjack/.venv/bin/pytest tests/unit/tools/test_ty_ignore_syntax.py -q --no-cov`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git commit --only crackerjack/tools/ty_ignore_syntax.py \
  tests/unit/tools/test_ty_ignore_syntax.py \
  -m "fix(tools): scan the repo root, not a crackerjack-only path"
```

---

### Task 3: Delete the bracketed mypy directives fleet-wide

**Files:** every `*.py` under the 16 repos carrying bracketed directives.

**Interfaces:**
- Consumes: `ty_suppression_migrate --mode delete-bracketed` from Task 1.
- Produces: 2,711 dead directives removed.

**Why this is safe:** ty does not read bracketed mypy codes (verified by probe — a
blanket `# type: ignore` suppresses in ty, `# type: ignore[code]` does not). mypy is
not invoked by CI in any repo in the fleet, and mypy already fails to parse 69 of
crackerjack's files. No gate depends on these.

- [x] **Step 1: Record the pre-change ty baseline for each repo**

For each repo, run ty over the package tree and the tests tree with `src.include`
overridden, and record both counts. The post-change counts must match exactly.

- [x] **Step 2: Delete the bracketed directives in one repo**

Run: `crackerjack/.venv/bin/python -m crackerjack.tools.ty_suppression_migrate --mode delete-bracketed --repo /Users/les/Projects/<repo>`

- [x] **Step 3: Verify the tree still parses**

Run `ast.parse` over every modified file. Expected: zero syntax errors. A file that
was left with an empty block must be repaired by hand, not by re-adding the comment.

- [x] **Step 4: Verify ty's counts are unchanged**

The package and tests counts must equal the Step 1 baseline exactly. The only
expected change is a drop in `unused-type-ignore-comment` warnings, if any existed.

- [x] **Step 5: Run the repo's test suite**

Run `<repo>/.venv/bin/pytest -q --no-cov -x`. Expected: PASS, or the same failures
as the pre-change baseline.

- [x] **Step 6: Commit that repo**

```bash
git commit --only <the modified paths> \
  -m "chore(<repo>): remove bracketed mypy ignore directives"
```

- [x] **Step 7: Repeat Steps 2-6 for each remaining repo**

One repo per commit. Never batch multiple repos into one commit.

---

### Task 4: Delete the dead blanket directives

**Files:** the 34 sites ty reports as `unused-type-ignore-comment`.

**Interfaces:**
- Consumes: `ty_suppression_migrate --mode delete-dead` from Task 1.
- Produces: 34 directives removed; ty's `unused-type-ignore-comment` count drops to 0.

- [x] **Step 1: Confirm the dead set**

For each repo, run ty with `rules.unused-type-ignore-comment` at warn level and
collect the reported sites. Expected: 34 sites fleet-wide.

- [x] **Step 2: Delete them and verify**

After deletion, the `unused-type-ignore-comment` count for that repo must be 0, and
the package/tests diagnostic counts must be unchanged.

- [x] **Step 3: Commit each repo**

```bash
git commit --only <the modified paths> \
  -m "chore(<repo>): remove dead blanket type-ignore directives"
```

---

### Task 5: Convert the live blanket directives to specific ty rules

**Files:** the ~105 live sites across 9 repos.

**Interfaces:**
- Consumes: `ty_suppression_migrate --mode convert-blanket` from Task 1.
- Produces: `# ty: ignore[<rule>]` in place of each live `# type: ignore`.

**Rules for the conversion:**
- A directive naming a rule ty does not recognise is a bug — stop and fix the code.
- A line with two different diagnostics gets `# ty: ignore[rule1, rule2]`.
- A line whose diagnostic ty attributes to a different line gets the directive on
  the line ty reports.
- A blanket that suppresses a *warning* (not an error) still converts, but the
  resulting directive must not draw `unused-ignore-comment`.

- [x] **Step 1: Convert one repo and verify**

Run the tool in `convert-blanket` mode against the repo. Then verify:
- ty's package and tests counts return to the Task 3 baseline **exactly**. Any
  difference means a directive was mis-placed or a rule list is incomplete.
- No `unused-ignore-comment` warnings appear anywhere in the repo.
- Every converted directive names a rule ty knows (`ty explain rule <name>` exits 0).

- [x] **Step 2: Commit that repo**

```bash
git commit --only <the modified paths> \
  -m "fix(<repo>): convert blanket type-ignores to specific ty rules"
```

- [x] **Step 3: Repeat for each repo with live blanket directives**

Repos: crackerjack, dhara, mcp-common, oneiric, mahavishnu, fastblocks,
session-buddy.

---

### Task 6: Fix the defects the conversion exposes

**Files:** the code sites behind the newly-specific diagnostics.

**Interfaces:**
- Consumes: the converted directives from Task 5.
- Produces: real fixes, with the corresponding directive removed.

**Already identified:**
- `crackerjack/crackerjack/services/memory_aware_scanner.py:137,140` — `random` is
  used but never imported. **Fix: add `import random`.** Remove the directive.
- `crackerjack/crackerjack/mahavishnu/mcp/tools/git_analytics.py:2406,2447` —
  `SecureSubprocessExecutor` is imported only inside a different function, so
  `_scan_large_files` raises `NameError`. **Fix: import it at module scope** (or
  inside `_scan_large_files`). Remove the directive.

- [x] **Step 1: Fix the two `NameError` defects**

Add the missing import / correct the scoping. Remove the corresponding
`# ty: ignore[unresolved-reference]`.

- [x] **Step 2: Verify ty's counts drop by exactly the number of fixed sites**

Each fix removes one diagnostic, so the count drops by one per fix.

- [x] **Step 3: Run the affected tests**

Run `<repo>/.venv/bin/pytest -q --no-cov`. Expected: PASS.

- [x] **Step 4: Commit**

```bash
git commit --only <the modified paths> \
  -m "fix(<repo>): fix undefined names hidden by blanket suppressions"
```

- [x] **Step 5: Triage the remaining `invalid-argument-type` and `missing-attribute` sites**

These are the largest buckets (19 and 11 in crackerjack alone). Per the decision
doc's rules, each is either a proven boundary (keep a specific directive) or a real
defect (fix the code). Record the decision in the commit message. Do not silently
convert-and-move-on for the ones that are genuine defects.

---

### Task 7: Drop mypy configuration

**Files:** `mypy.ini` (11 repos), `[tool.mypy]` sections (4 repos), mypy dev
dependencies (4 repos: akosha, opera-cloud-mcp, raindropio-mcp, mdinject).

**Interfaces:**
- Consumes: Tasks 3-6 complete — no mypy-syntax directive remains anywhere.
- Produces: no mypy configuration in the fleet.

- [x] **Step 1: Delete `mypy.ini` and the `[tool.mypy]` sections**

Delete the file; remove the section from `pyproject.toml`, including any
`mypy_args` key that belongs to it.

- [x] **Step 2: Remove mypy from dependency groups**

Remove the `mypy` entry from `[dependency-groups]` / `[project.optional-dependencies]`.
Re-lock with `uv lock`.

- [x] **Step 3: Verify nothing imports mypy**

Run: `grep -rn "import mypy\|from mypy" <repo> --include="*.py"`. Expected: only
`crackerjack/config/refurb_args.py`, which reads mypy *flags* for refurb, not mypy
itself.

- [x] **Step 4: Verify the test suite still passes**

Run `<repo>/.venv/bin/pytest -q --no-cov`. Expected: PASS.

- [x] **Step 5: Commit each repo**

```bash
git commit --only <the modified paths> \
  -m "chore(<repo>): drop mypy configuration in favour of ty"
```

---

### Task 8: Enable the `ty-ignore-syntax` hook

**Files:** each repo's crackerjack configuration.

**Interfaces:**
- Consumes: Task 2 (the default path now scans the repo root).
- Produces: the policy is machine-enforced.

- [x] **Step 1: Enable the hook in one repo**

Set `enable_ty_ignore_syntax = true` in the repo's crackerjack settings.

- [x] **Step 2: Verify the hook scans the repo and finds nothing**

Run the tool directly against the repo root:
`crackerjack/.venv/bin/python -m crackerjack.tools.ty_ignore_syntax .`
Expected: `0 findings across N file(s)` with **N > 0**. If N is 0, the default path
fix from Task 2 has not shipped — stop.

- [x] **Step 3: Verify the hook finds a planted violation**

Add `# type: ignore[assignment]` to a scratch file in the repo, re-run, confirm the
finding, then remove the scratch file.

- [x] **Step 4: Commit, then repeat per repo**

```bash
git commit --only <the config path> \
  -m "chore(<repo>): enable the ty-ignore-syntax hook"
```

---

### Task 9: Update the decision doc

**Files:**
- Modify: `mahavishnu/docs/decisions/ty-ignore-codes.md`
- Modify: `mahavishnu/docs/decisions/README.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: the policy doc states that ty is the only checker.

- [x] **Step 1: Rewrite the doc's "What enforces this" section**

State that ty is the sole checker in the fleet, that mypy configuration is removed,
and that bare `# type: ignore` is no longer accepted — a suppression must name a
rule.

- [x] **Step 2: Update the anti-patterns list**

Add "a bare `# type: ignore` with no rule" as an anti-pattern.

- [x] **Step 3: Update the decisions README index row**

Reflect the new enforcement mechanism.

- [x] **Step 4: Commit**

```bash
git commit --only docs/decisions/ty-ignore-codes.md docs/decisions/README.md \
  -m "docs(decisions): record the ty-only policy"
```

---

## Execution Notes

- **One repo per commit.** Never batch repos.
- **A repo with concurrent WIP** (crackerjack, and any repo another session is
  working in) must use `git commit --only <paths>`, and its pre-existing failures
  must be recorded as a baseline before changing anything.
- **The verification that matters is the ty count returning to baseline.** Every
  task states the expected count change. A count that does not return to baseline
  means a directive is misplaced — investigate rather than adjusting the budget.
- **Do not adjust the ratchet budgets to absorb a migration mistake.** The budgets
  are measured; if the count moves, the cause is in the change under review.

## Outcome

Executed 2026-11-14. The fleet now has one type checker.

**What landed**

- **2,711 bracketed mypy directives deleted** across 46 git repositories. Every
  one of them was inert: ty never read the bracketed form.
- **105 blanket `# type: ignore` directives** converted to specific
  `# ty: ignore[<rule>]` directives, or deleted where they were dead.
- **Two production `NameError` defects fixed** — `SecureSubprocessExecutor`
  imported into a function scope in `git_analytics.py`, and `random` never
  imported in `memory_aware_scanner.py`. Both were hidden by a suppression.
- **mypy's configuration removed fleet-wide**: no `mypy.ini`, no `[tool.mypy]`
  section, no mypy dependency in any dependency group. 33 repos carried mypy
  configuration; every one of them is gone.
- **`ty-ignore-syntax` on by default** (`hooks.enable_ty_ignore_syntax`). The
  gate reports **0 findings across every committed repo** in the fleet.
- **Ratchet budgets re-measured** in the five repos that carry them
  (oneiric 558, session-buddy 3279, akosha 1750, mahavishnu 3925,
  crackerjack 2475). Each count *fell* during the migration: a mypy-syntax
  directive is inert as a suppression but not as comment text, because ty
  parses the text of a comment for directives — so every one of them also
  drew an `invalid-ignore-comment` warning.

**Deviations from the plan**

- **Task 8 was done in one place, not 46.** The plan said to set
  `enable_ty_ignore_syntax = true` in each repo's crackerjack settings. The
  fleet shares one crackerjack, so flipping the default in
  `crackerjack/config/settings.py` turns the gate on everywhere at once — and
  a repo that needs an exception can still set it to `false`.
- **The repo count was 46, not the 16 the plan assumed.** The fleet turned out
  to be larger than the plan's survey found.
- **`ty_ratchet` gained two fixes** the plan did not anticipate: a per-gate
  `src.include` override (without it, `--test-dir tests` measured zero files
  in every repo that scopes ty to its package) and a gate-error state for "ty
  found no files" (without it, a vacuous measurement reported PASS).

**Verification, and its limits**

- Every migrated repo was checked for: ty's diagnostic count per tree
  **unchanged** across the migration, `ast.parse` clean on every changed file,
  and a per-line diff proving only the directive changed.
- **The full test suite was not run in every one of the 46 repos.** It was run
  in session-buddy (pass), crackerjack (the 88 tests covering the two fixed
  modules pass), and the repos whose own suites were exercised during the
  migration. A repo whose suite was not run has a verified-unchanged ty count
  and a verified-clean parse, and nothing more.

**One exception, deliberately left**

`sites/` contains two bare `# type: ignore` directives
(`sites/fastest/main.py:15`, `sites/dotorg/main.py:2`). That repo has **no
commits at all** — `main` is unborn — and the files belong to another
session's untracked work. Editing them would have meant touching another
session's WIP. The fix, when their owner applies it, is to drop the
directive: ty reports nothing at either line, so no suppression is needed.

