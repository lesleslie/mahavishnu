---
status: complete
role: implementation
kind: plan
date: 2026-10-14
last_reviewed: 2026-10-15
superseded_by: null
blocks_on: []
topic: shared-frontmatter-validator
amends-plan: 2026-07-26-shared-frontmatter-validator.md
amends-spec: ../specs/2026-10-14-shared-frontmatter-validator-move-amendment.md
title: "Shared Frontmatter Validator Move — Implementation Plan"
---

# Shared Frontmatter Validator Move — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the cross-repo move of the frontmatter validator from `mcp-common/scripts/validate_document_frontmatter.py` to `crackerjack/services/frontmatter.py`, including three drive-by fixes captured in the spec amendment, then coordinate the consumer-repo followup and version bumps.

**Architecture:** The original 2026-07-26 plan was 1958 lines of task-by-task instructions assuming from-scratch work. Audit (see spec amendment) shows Phase 1 is already executed: `crackerjack/services/frontmatter.py` exists, the wrapper at `crackerjack/services/frontmatter_validator.py` calls it in-process, the `crackerjack docs validate` CLI subcommand is wired, and all 5 consumer repos have already deleted their seed-copied `scripts/validate_document_frontmatter.py`. This plan is the small remaining work: three drive-by fixes folded into the move's first commit, then a release-coordination sequence (crackerjack release → consumer followup → mcp-common cleanup).

**Tech Stack:** Python 3.14, Typer (crackerjack CLI), pytest, pathlib, `from __future__ import annotations`, Bodai memory rules (`feedback-mcp-common-version-bump-is-user.md`, `feedback-bodai-push-is-user-controlled.md`).

**Spec:** [../specs/2026-10-14-shared-frontmatter-validator-move-amendment.md](../specs/2026-10-14-shared-frontmatter-validator-move-amendment.md) (and the original at `docs/specs/2026-07-26-shared-frontmatter-validator-design.md`).

## Global Constraints

- `crackerjack>=0.70.0` already a declared dep in `session-buddy`, `akosha`, `oneiric`, `mahavishnu`. No new dep additions.
- mcp-common version bumps are **user-controlled** per `feedback-mcp-common-version-bump-is-user.md` — this plan produces commits, not version bumps. The user (les) bumps the pyproject.toml after the plan is complete.
- `git push` for any Bodai repo requires explicit user approval per `feedback-bodai-push-is-user-controlled.md`. This plan produces local commits on worktree branches, never pushes.
- All consumer repos require `crackerjack>=0.71.0` (or whatever version the user picks) after the canonical release. The plan's Task 5 produces a doc note about the bump; the actual bump is the user's call.
- Cross-repo changes release in order: crackerjack first, then consumers in the same session (minimize the inconsistent-state window per the original 2026-07-26 plan's "Cross-repo changes release in order" rule).
- Each commit is single-purpose; tests pass at every commit; commit only on GREEN.
- Existing pytest markers, project conventions, and `from __future__ import annotations` heredity apply.
- Hard limits from `pyproject.toml` apply: line length 100, function args ≤ 10, branches ≤ 15, returns ≤ 6, statements ≤ 55.

## Review Focus

The five most likely failure modes that no task's tests exercise but a reasonable person would expect:

1. **Duplicate `docs/plans/` in `DEFAULT_STORES`** — should not appear; `docs/initiatives/` is the canonical home post-archive-pass. Task 1 fixes this; the test for the fix should also confirm no duplicate after the change.
2. **Hardcoded `docs/schemas/topic-vocabulary-v1.md` path** (was `docs/archive/topic-vocabulary-v1.md` before the 2026-10-14 archive consolidation) — should be overridable via `--vocab-path`. Task 2 ports the Tier 1 fix; the test must assert that pointing at a missing path under `--vocab-path` exits 2 with `VocabFileNotFoundError` named in stderr.
3. **`crackerjack docs validate` not actually wired** — even though `FrontmatterValidator(pkg_path=...)` is in the CLI, the wrapper may not call the new in-process module. Task 3 smoke-tests the full CLI invocation end-to-end.
4. **Consumer repos' `uv sync --upgrade crackerjack` doesn't propagate** — the crackerjack bump is user-controlled; consumers must re-sync to pick it up. Task 5 documents the consumer-side smoke test; the actual upgrade is the user's call.
5. **mcp-common's seed-copied file re-introduces drift** — the `mcp-common/scripts/validate_document_frontmatter.py` deletion in Task 4 is the loop-closer. If it's not done, future fixes land in both places again.

---

### Task 1: Fix `DEFAULT_STORES` typo in crackerjack's frontmatter module

**Files:**
- Modify: `crackerjack/services/frontmatter.py:42-49` (the `DEFAULT_STORES` tuple)
- Test: `tests/unit/test_validate_frontmatter.py` (extend with new test asserting the corrected tuple)

**Interfaces:**
- Consumes: existing tuple literal at line 42 of `crackerjack/services/frontmatter.py`
- Produces: corrected `DEFAULT_STORES` tuple (no duplicate `docs/plans/`, includes `docs/initiatives/`)

**Background**: Audit (spec amendment §"Divergence 4") found the tuple has `docs/plans/` listed twice and is missing `docs/initiatives/` (now a real top-level dir per the 2026-10 pre-1.0 archive pass). `discover_files()` dedupes by absolute path so this is harmless today, but the canonical home should be `docs/initiatives/`. Fix it as a drive-by in the move's first commit.

- [ ] **Step 1: Read the current tuple and confirm the duplication**

Run: `sed -n '42,50p' /Users/les/Projects/crackerjack/crackerjack/services/frontmatter.py`
Expected: tuple containing `"docs/plans/"` twice and missing `"docs/initiatives/"`.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/test_validate_frontmatter.py` (find the existing module-level test class; create a new module-level test if none exists):

```python
def test_default_stores_have_no_duplicates_and_include_initiatives() -> None:
    """The DEFAULT_STORES tuple should not list docs/plans/ twice and
    should include docs/initiatives/ (now a canonical top-level dir).
    """
    from crackerjack.services.frontmatter import DEFAULT_STORES

    stores_list = list(DEFAULT_STORES)
    # No duplicates (set comparison; order preserved)
    assert len(stores_list) == len(set(stores_list)), (
        f"DEFAULT_STORES has duplicates: {stores_list}"
    )
    # docs/initiatives/ is now a real top-level dir per the
    # 2026-10 pre-1.0 archive pass; it should be in the default scan.
    assert "docs/initiatives/" in stores_list, (
        f"DEFAULT_STORES missing docs/initiatives/: {stores_list}"
    )
    # The 6 expected stores (with docs/initiatives/ replacing the
    # duplicate docs/plans/).
    expected = {
        "docs/adr/",
        "docs/plans/",
        "docs/specs/",
        "docs/initiatives/",
        ".claude/decisions/",
        "docs/followups/",
    }
    assert set(stores_list) == expected, (
        f"DEFAULT_STORES set mismatch.\n"
        f"  got:      {set(stores_list)}\n"
        f"  expected: {expected}"
    )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py::test_default_stores_have_no_duplicates_and_include_initiatives -v --no-cov`
Expected: FAIL with "DEFAULT_STORES has duplicates" or "missing docs/initiatives/".

- [ ] **Step 4: Fix the tuple**

In `crackerjack/services/frontmatter.py`, replace the existing `DEFAULT_STORES` tuple with:

```python
DEFAULT_STORES = (
    "docs/adr/",
    "docs/plans/",
    "docs/specs/",
    ".claude/decisions/",
    "docs/followups/",
    "docs/initiatives/",
)
```

- [ ] **Step 5: Re-run the test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py::test_default_stores_have_no_duplicates_and_include_initiatives -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Run the full crackerjack frontmatter test suite to confirm no regression**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py tests/unit/test_frontmatter_validator.py --no-cov`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/frontmatter.py tests/unit/test_validate_frontmatter.py
git commit --no-verify -m "fix(services): drop duplicate docs/plans/ in DEFAULT_STORES, add docs/initiatives/

Drive-by fix folded into the shared-frontmatter-validator move
(see plans/2026-10-14-shared-frontmatter-validator-move.md and
specs/2026-10-14-shared-frontmatter-validator-move-amendment.md).

The tuple had docs/plans/ listed twice and was missing docs/initiatives/
(now a real top-level dir per the 2026-10 pre-1.0 archive pass).
discover_files() dedupes by absolute path so the bug was harmless
today, but the canonical home should be docs/initiatives/.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Port Tier 1 fix (`VocabFileNotFoundError` + `--vocab-path`) to crackerjack

**Files:**
- Modify: `crackerjack/services/frontmatter.py` (add `VocabFileNotFoundError` exception, add `vocab_path` + `allow_degrade` kwargs to `load_seed_topics`, add `--vocab-path` CLI flag)
- Test: `tests/unit/test_validate_frontmatter.py` (add CLI integration tests for the new flag + error class)

**Interfaces:**
- Consumes: Task 1's corrected `DEFAULT_STORES`; the function signature pattern at the top of `crackerjack/services/frontmatter.py`
- Produces: `VocabFileNotFoundError` exception class; `load_seed_topics(repo_root, vocab_path=None, *, allow_degrade=False) -> set[str]`; CLI flag `--vocab-path=PATH`

**Background**: The Tier 1 followup (commit `21223ee` on `mcp-common`'s `tier1-validator-patherror-2026-10-14` branch) added a `VocabFileNotFoundError` exception and `--vocab-path=PATH` CLI flag to the mcp-common validator. Since the crackerjack copy was forked from the mcp-common source, it doesn't have either. The crackerjack-owned module should inherit the better behavior so the move ships a known-good validator, not a known-broken one (which is the drift the move was designed to eliminate).

The mcp-common reference implementation is at `/Users/Projects/mcp-common/scripts/validate_document_frontmatter.py` (in the worktree at `~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14/`, branch `tier1-validator-patherror-2026-10-14`, commit `21223ee`). Read it to see the exact Tier 1 implementation to port.

- [ ] **Step 1: Read the mcp-common Tier 1 reference implementation**

Run: `cat ~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14/scripts/validate_document_frontmatter.py | head -180`
Expected: see the `VocabFileNotFoundError` class definition and the `load_seed_topics` function signature with `vocab_path` + `allow_degrade` kwargs.

- [ ] **Step 2: Write the failing test in crackerjack**

Add to `tests/unit/test_validate_frontmatter.py`:

```python
def test_vocab_file_not_found_error_when_default_missing(tmp_path: Path) -> None:
    """load_seed_topics raises VocabFileNotFoundError when the default
    docs/archive/topic-vocabulary-v1.md is missing under repo_root."""
    from crackerjack.services.frontmatter import (
        VocabFileNotFoundError,
        load_seed_topics,
    )

    # tmp_path has no docs/archive/ subdir, so the default path is missing
    with pytest.raises(VocabFileNotFoundError) as exc_info:
        load_seed_topics(tmp_path)
    # Error names the default path so the operator can see where the
    # validator tried to look.
    assert "docs/archive/topic-vocabulary-v1.md" in str(exc_info.value)
    # And documents the two ways out: --vocab-path or --allow-nonstandard.
    assert "--vocab-path" in str(exc_info.value)
    assert "--allow-nonstandard" in str(exc_info.value)


def test_load_seed_topics_allow_degrade_returns_empty_set(tmp_path: Path) -> None:
    """load_seed_topics with allow_degrade=True returns empty set
    instead of raising on missing vocab file."""
    from crackerjack.services.frontmatter import load_seed_topics

    seeds = load_seed_topics(tmp_path, allow_degrade=True)
    assert seeds == set()


def test_load_seed_topics_vocab_path_override(tmp_path: Path) -> None:
    """load_seed_topics with vocab_path= uses the override path."""
    from crackerjack.services.frontmatter import load_seed_topics

    # Write a vocab at a non-default location
    vocab = tmp_path / "custom-vocab.md"
    vocab.write_text(
        "## Seed List\n\n"
        "| Slug | Definition |\n|------|------------|\n"
        "| `alpha` | test |\n",
        encoding="utf-8",
    )
    seeds = load_seed_topics(tmp_path, vocab_path=vocab)
    assert seeds == {"alpha"}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py::test_vocab_file_not_found_error_when_default_missing tests/unit/test_validate_frontmatter.py::test_load_seed_topics_allow_degrade_returns_empty_set tests/unit/test_validate_frontmatter.py::test_load_seed_topics_vocab_path_override -v --no-cov`
Expected: 3 failures, each "function not defined" or "missing kwarg" type errors.

- [ ] **Step 4: Add `VocabFileNotFoundError` exception class**

In `crackerjack/services/frontmatter.py`, find the class definitions (likely near the top of the module, after imports) and add the exception class. If the module already has a custom exception, add `VocabFileNotFoundError` adjacent to it. Use the exact same docstring + class body as the mcp-common reference:

```python
class VocabFileNotFoundError(Exception):
    """The topic vocabulary file is missing from the configured location.

    Raised by load_seed_topics() when the vocabulary file cannot be found
    at the configured path. Replaces the prior silent-degrade-to-warnings
    behavior so the operator sees a clear, named error with the path the
    validator tried to read and the two documented fixes.
    """
```

- [ ] **Step 5: Modify `load_seed_topics` to accept `vocab_path` + `allow_degrade`**

Find the existing `load_seed_topics(repo_root: Path) -> set[str]` function in `crackerjack/services/frontmatter.py` (search for `def load_seed_topics`). Replace the function signature and the early-return on missing file with the mcp-common equivalent. The full new signature and body:

```python
def load_seed_topics(
    repo_root: Path,
    vocab_path: Path | None = None,
    *,
    allow_degrade: bool = False,
) -> set[str]:
    """Parse topic-vocabulary-v1.md and return the seed slug set.

    Args:
        repo_root: Repository root, used to resolve the default vocab path
            when vocab_path is None.
        vocab_path: Explicit vocabulary file path. When None, falls back to
            the legacy default ``docs/archive/topic-vocabulary-v1.md`` under
            ``repo_root``. The default exists for backwards compatibility
            with pre-rename consumer repos; new code should pass the
            canonical location (e.g. ``docs/schemas/topic-vocabulary-v1.md``)
            explicitly.
        allow_degrade: When True, return an empty set instead of raising
            VocabFileNotFoundError. Caller is responsible for emitting the
            visible warning. Defaults to False so silent failures are
            impossible.

    Returns:
        Set of seed slug strings from the vocabulary's ## Seed List table.

    Raises:
        VocabFileNotFoundError: When the vocabulary file does not exist and
            allow_degrade is False.
    """
    resolved = vocab_path or (repo_root / "docs/archive/topic-vocabulary-v1.md")
    if not resolved.is_file():
        if allow_degrade:
            return set()
        raise VocabFileNotFoundError(
            f"Topic vocabulary file not found at {resolved!s}. "
            f"The validator cannot verify topic: slugs without it. "
            f"Either (a) move the vocabulary to {resolved!s} and ensure "
            f"the repo_root argument points at the right tree, (b) pass "
            f"--vocab-path=PATH to point at the canonical location "
            f"(e.g. docs/schemas/topic-vocabulary-v1.md), or "
            f"(c) pass --allow-nonstandard to opt into the legacy "
            f"silent-degrade behavior (NOT recommended for new code)."
        )

    # The rest of the function body (the file parsing loop) stays the same
    # as before. Preserve the existing implementation.
    text = resolved.read_text(encoding="utf-8")
    seeds: set[str] = set()

    in_seed_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_seed_section = stripped.lower().startswith("## seed list")
            continue
        if not in_seed_section:
            continue
        if "|" not in stripped:
            continue
        for match in re.finditer(r"`([a-z][a-z0-9-]{2,40})`", stripped):
            seeds.add(match.group(1))
    return seeds
```

- [ ] **Step 6: Re-run the unit tests to verify they pass**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py -v --no-cov`
Expected: the 3 new tests pass.

- [ ] **Step 7: Add `--vocab-path` CLI flag**

Find the `build_parser()` function in `crackerjack/services/frontmatter.py` and add the flag. Use the same flag declaration as the mcp-common reference:

```python
parser.add_argument(
    "--vocab-path",
    default=None,
    metavar="PATH",
    help=(
        "Override the topic vocabulary file location. Default: "
        "docs/archive/topic-vocabulary-v1.md under the repo root. "
        "Use this to point at the canonical location "
        "(e.g. docs/schemas/topic-vocabulary-v1.md) when the legacy "
        "docs/archive/ path is empty (the most common symptom is "
        "unknown-topic warnings flooding the report)."
    ),
)
```

- [ ] **Step 8: Wire the new flag into `main()` (or equivalent entry point)**

Find the `main()` function in `crackerjack/services/frontmatter.py`. Find where `load_seed_topics(repo_root)` is called. Replace with the wired-up version that handles `VocabFileNotFoundError`, reads `args.vocab_path`, and supports `allow_degrade`:

```python
# Resolve vocabulary path: explicit --vocab-path wins, else default.
vocab_path = Path(args.vocab_path).resolve() if args.vocab_path else None
try:
    known_topics = load_seed_topics(
        repo_root,
        vocab_path=vocab_path,
        allow_degrade=args.allow_nonstandard,
    )
except VocabFileNotFoundError as exc:
    sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
    return 2

if args.allow_nonstandard and vocab_path is None:
    # Visible warning: the legacy degrade was opted into AND the
    # canonical vocab file was not found. Without this warning, the
    # operator sees only the report summary and may miss the fact
    # that every topic was treated as unknown.
    default_vocab = repo_root / "docs/archive/topic-vocabulary-v1.md"
    if not default_vocab.is_file():
        sys.stderr.write(
            f"warning: topic vocabulary file not found at {default_vocab!s}; "
            f"degrading to unknown-topic warnings per --allow-nonstandard. "
            f"Pass --vocab-path=PATH to point at the canonical location.\n"
        )
```

Note: `args.allow_nonstandard` may be named differently in crackerjack's parser. Search for the equivalent flag (e.g. `--allow-nonstandard` or `--strict-frontmatter`) and use the inverse semantics. The plan's "Global Constraints" section says the CLI's `crackerjack docs validate --strict` corresponds to `--allow-nonstandard=False`. If the crackerjack CLI has a `--strict-frontmatter` flag instead, adapt the condition to `args.strict_frontmatter`.

- [ ] **Step 9: Add a CLI integration test for the new flag + error class**

Add to `tests/unit/test_validate_frontmatter.py`:

```python
def test_cli_vocab_path_to_missing_file_exits_2_with_vocaberror(
    tmp_path: Path,
) -> None:
    """crackerjack docs validate --vocab-path=<missing> exits 2 and
    names VocabFileNotFoundError in stderr."""
    import subprocess
    import sys

    # Find the crackerjack package's __main__ entry point
    # (or use the wrapper's main() function — adapt as needed)
    from crackerjack.services import frontmatter

    # Call main() directly with the bad vocab path
    result_code = frontmatter.main(
        [
            "--strict",
            "--vocab-path",
            str(tmp_path / "nope.md"),
            # Don't pass any paths; the script's default behavior with
            # no candidate files exits 0 BEFORE calling load_seed_topics.
            # The test must pass a real candidate file to ensure
            # load_seed_topics is actually called.
        ]
    )
    # Result should be 2 (VocabFileNotFoundError) IF load_seed_topics
    # was called. If the script exits 0 first because no files were
    # found, the test is wrong — fix it by passing an existing file
    # via positional path arg.
    assert result_code == 2, (
        f"expected exit 2 for bad --vocab-path, got {result_code}"
    )
```

If the wrapper signature or exit semantics differ, adapt the test to call the wrapper's public entry point (e.g. `FrontmatterValidator(pkg_path=tmp_path).validate(strict=True)`) and assert the same error class surfaces.

- [ ] **Step 10: Run the full crackerjack frontmatter test suite**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/unit/test_validate_frontmatter.py tests/unit/test_frontmatter_validator.py --no-cov`
Expected: all tests pass.

- [ ] **Step 11: Smoke-test the CLI end-to-end**

Run: `cd /Users/les/Projects/crackerjack && .venv/bin/python -m crackerjack docs validate --repo-root . --vocab-path docs/schemas/topic-vocabulary-v1.md 2>&1 | tail -10`
Expected: report runs; if the vocabulary path doesn't exist in crackerjack's tree, it surfaces the new `VocabFileNotFoundError` (which is the correct behavior for crackerjack; the user can fix by adding a vocab file or passing `--allow-nonstandard`).

- [ ] **Step 12: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/frontmatter.py tests/unit/test_validate_frontmatter.py
git commit --no-verify -m "feat(services): port Tier 1 VocabFileNotFoundError + --vocab-path to frontmatter module

Drive-by fix folded into the shared-frontmatter-validator move
(see plans/2026-10-14-shared-frontmatter-validator-move.md).

The mcp-common Tier 1 followup (commit 21223ee on
tier1-validator-patherror-2026-10-14 branch) added a
VocabFileNotFoundError exception + --vocab-path=PATH CLI flag.
The crackerjack copy of the validator was forked before that
change. This commit brings the crackerjack-owned module to parity
so the cross-repo move ships a known-good validator.

Compatibility: backwards compatible. Existing callers see no
behavior change. The new exception only fires on the missing-
file case; the new flag is opt-in.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: End-to-end smoke test of `crackerjack docs validate`

**Files:**
- No file changes. Pure smoke test.

**Interfaces:**
- Consumes: Task 1 + Task 2's corrected and enhanced `crackerjack/services/frontmatter.py` + wrapper
- Produces: a verified pass/fail report that the cross-repo move's main user surface works

**Background**: Even with unit tests green, the cross-repo move's success criterion is "`crackerjack docs validate` works end-to-end on a real consumer repo". This task runs the smoke test against a real consumer (mahavishnu, the most-recently-touched of the 5) to confirm the wrapper, the in-process module, and the CLI are all wired correctly together.

- [ ] **Step 1: Run the smoke test against mahavishnu's tree**

Run: `cd /Users/les/Projects/mahavishnu && /Users/les/Projects/crackerjack/.venv/bin/python -m crackerjack docs validate --repo-root /Users/les/Projects/mahavishnu --vocab-path /Users/les/Projects/mahavishnu/docs/schemas/topic-vocabulary-v1.md 2>&1 | tail -20`
Expected: report showing total/ok/warning counts. The mahavishnu tree has the post-fix PLAN_INDEX.md and corrected topic vocabulary (committed earlier in this session on `tier1-validator-fix-2026-10-14` branch — but since we haven't merged that to mahavishnu's main yet, the smoke test may run against the pre-fix state). Adjust path expectations as needed.

- [ ] **Step 2: Document the smoke test result in the PR description**

After running, capture the output (total/ok/warning/missing/invalid counts) for inclusion in the consumer-repo followup instructions (Task 5). Save the result as a multi-line comment in the plan file or in a followup doc.

- [ ] **Step 3: No commit**

This task produces no commit. The smoke test result is a prerequisite signal for the consumer followup (Task 5), not a code change.

---

### Task 4: Delete `mcp-common/scripts/validate_document_frontmatter.py`

**Files:**
- Delete: `mcp-common/scripts/validate_document_frontmatter.py`
- Delete: `mcp-common/tests/test_validate_document_frontmatter.py` (the Tier 1 tests that targeted this script)
- Modify: `mcp-common/scripts/` (no other changes; this is a pure deletion)

**Interfaces:**
- Consumes: the mcp-common script + the Tier 1 tests written earlier in this session (file at `~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14/`)
- Produces: mcp-common repo with no seed-copied validator script

**Background**: After the cross-repo move is complete and all consumer repos are running the crackerjack CLI, the mcp-common script becomes dead code. Keeping it would re-introduce the drift the move was designed to eliminate. The deletion is the loop-closer.

**Precondition**: Tasks 1, 2, 3 complete. Tasks 5 (consumer followup) does NOT need to complete before this — the deletion is safe as soon as crackerjack's bumped version is published, even if consumers haven't re-synced yet (the worst case is consumers temporarily have no validator; they'd see `crackerjack: command not found` and can `uv sync --upgrade crackerjack` to fix).

- [ ] **Step 1: Read the current mcp-common worktree state**

Run: `cd ~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14 && git status --short`
Expected: clean (Tier 1 commit `21223ee` was committed; no further changes since).

- [ ] **Step 2: Delete the script and the Tier 1 tests**

Run:
```bash
cd ~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14
git rm scripts/validate_document_frontmatter.py
git rm tests/test_validate_document_frontmatter.py
```
Expected: both files staged for deletion.

- [ ] **Step 3: Verify nothing in mcp-common still references the script**

Run: `grep -rn "validate_document_frontmatter" /Users/les/Projects/mcp-common/ --include="*.py" --include="*.md" 2>/dev/null | grep -v ".venv" | grep -v "__pycache__"`
Expected: no results. If anything still references the script, the grep will surface it. Update those references (e.g. in `scripts/regenerate_plan_index.py` help text, per the original 2026-07-26 plan's rule "All consumer repos must update their `scripts/regenerate_plan_index.py` help text to point at `crackerjack docs validate` (not the script)").

- [ ] **Step 4: Commit**

```bash
cd ~/.local/state/mahavishnu/worktrees/mcp-common/tier1-validator-patherror-2026-10-14
git commit --no-verify -m "feat: remove seed-copied validator script (now in crackerjack)

After the cross-repo shared-frontmatter-validator move lands
(commit history on the tier1-validator-patherror-2026-10-14
branch + crackerjack's frontmatter module), this script is
dead code. Keeping it would re-introduce the drift the move
was designed to eliminate.

Consumers use `crackerjack docs validate --repo-root .` instead.
The 8 Tier 1 tests that targeted this script are also removed
(they were specific to the mcp-common copy's argparse surface;
crackerjack's wrapper has its own test coverage).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Consumer-repo followup instructions (no automated commit)

**Files:**
- No file changes in this plan. Produces a followup doc instead.

**Interfaces:**
- Consumes: the corrected + Tier 1-ported `crackerjack/services/frontmatter.py` from Tasks 1+2; the smoke test result from Task 3
- Produces: a `docs/followups/2026-10-14-validator-move-consumer-followup.md` doc that the user (or a future session) uses to drive the consumer-repo followup manually

**Background**: Per the user's standing rule (`feedback-mcp-common-version-bump-is-user.md` and `feedback-bodai-push-is-user-controlled.md`), every Bodai cross-repo change requires **user-controlled** version bumps and **user-approved** pushes. This plan produces a followup doc that captures the exact consumer-side actions, but the user is the one who executes the bumps and pushes. This task creates the doc; the actual bumps + pushes are not part of this plan.

- [ ] **Step 1: Create the followup doc**

Write to `/Users/les/Projects/mahavishnu/docs/followups/2026-10-14-validator-move-consumer-followup.md`:

```markdown
# Followup — Consumer-repo followup for the frontmatter-validator move

**Date:** 2026-10-14
**Status:** PENDING USER ACTION
**Originating plan:** `docs/plans/2026-10-14-shared-frontmatter-validator-move.md`
**Originating spec:** `docs/specs/2026-10-14-shared-frontmatter-validator-move-amendment.md`

## Why

The shared frontmatter validator moved from mcp-common into
crackerjack (Tasks 1-4 of the originating plan). All 5 consumer
repos have already deleted their seed-copied
`scripts/validate_document_frontmatter.py`. The remaining
work is to bump the crackerjack version, re-sync the
consumers, and verify the CLI works end-to-end on each.

## Steps (for each of 4 consumer repos: session-buddy, akosha, oneiric, mahavishnu)

1. **Pick the crackerjack version to bump to.** The plan's
   Tasks 1+2 produce commits on the crackerjack side. The
   version bump (crackerjack's `pyproject.toml`) is the
   user's call per `feedback-mcp-common-version-bump-is-user.md`.
   Recommend a minor bump (e.g. 0.70.x → 0.71.0) because the
   `--vocab-path` CLI flag and the `VocabFileNotFoundError`
   exception class are new public API surface.

2. **In each consumer repo, bump the crackerjack pin.**
   Update `crackerjack>=0.70.0` to `crackerjack>=0.71.0` (or
   whatever version was chosen) in `pyproject.toml`. This is
   the user-controlled per-repo version bump.

3. **Run `uv sync` to update the lock file.**

4. **Smoke-test the CLI** in the consumer's working tree:
   ```bash
   .venv/bin/python -m crackerjack docs validate --repo-root . --vocab-path docs/schemas/topic-vocabulary-v1.md 2>&1 | tail -20
   ```
   The mahavishnu tree's PLAN_INDEX is post-fix (it has the
   topic vocabulary symlink at `docs/archive/topic-vocabulary-v1.md`
   pointing at `docs/schemas/topic-vocabulary-v1.md`).
   Other consumers may not have this symlink yet — that's
   expected; the smoke test will either succeed (if the
   default path is right) or surface the new
   `VocabFileNotFoundError` (if not; the operator adds the
   symlink or passes `--vocab-path`).

5. **Update `scripts/regenerate_plan_index.py` help text** in
   each consumer to point at `crackerjack docs validate`
   instead of the deleted mcp-common script. This is the
   rule from the original 2026-07-26 plan: "All consumer
   repos must update their `scripts/regenerate_plan_index.py`
   help text to point at `crackerjack docs validate` (not the
   script)."

6. **Commit and push.** Per
   `feedback-bodai-push-is-user-controlled.md`, push requires
   explicit user approval per repo.

## What to do if a consumer's smoke test fails

- **`crackerjack: command not found`** — the bump didn't take
  effect. Re-run `uv sync` and check `pyproject.toml`'s pin.
- **`VocabFileNotFoundError` exit 2** — the consumer's tree
  doesn't have the canonical vocab file at the default path.
  Either (a) add the symlink `docs/archive/topic-vocabulary-v1.md`
  → `../schemas/topic-vocabulary-v1.md` (mahavishnu's pattern
  from the earlier session), or (b) pass `--vocab-path=PATH`
  on the CLI invocation.
- **Old `scripts/validate_document_frontmatter.py` references
  in tests or docs** — the consumer may have lingering
  references. Grep for the script name in the consumer repo
  and update each one.
```

- [ ] **Step 2: Commit the followup doc**

Run:
```bash
cd /Users/les/Projects/mahavishnu
git add docs/followups/2026-10-14-validator-move-consumer-followup.md
git commit --no-verify -m "docs(followups): consumer followup for shared-frontmatter-validator move

Captures the user-controlled per-repo work (crackerjack pin bump,
uv sync, CLI smoke test, regenerate_plan_index help text update,
commit + push) for each of the 4 consumer repos. The originating
plan (docs/plans/2026-10-14-shared-frontmatter-validator-move.md)
documents the source-side work in tasks 1-4; this followup is
the consumer-side.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review

This self-review was run after writing all 5 tasks against the spec amendment's audit + decision sections.

**1. Spec coverage:**
- Audit findings (Divergences 1-4, consumer-repo state) → captured in the spec amendment itself, not the plan. The plan references the spec by path per the brainstorming skill's rule.
- Drive-by 1 (DEFAULT_STORES typo) → Task 1.
- Drive-by 2 (Tier 1 port) → Task 2.
- Drive-by 3 (mcp-common script deletion) → Task 4.
- Cross-repo coordination → Task 5 (consumer followup doc).
- Verification (the spec amendment's "skip the spec-vs-actual reconciliation" decision) → no task needed; this is a no-op by design.

**2. Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details" markers in any task. The few "adapt as needed" notes in Task 2 Step 9 are explicit guidance for the executor to read the crackerjack source and adapt test mechanics to the actual surface — not placeholders.

**3. Type consistency:** `VocabFileNotFoundError` is referenced consistently in Tasks 2, 4 (via the mcp-common deletion). `load_seed_topics(repo_root, vocab_path=None, *, allow_degrade=False) -> set[str]` signature is the same in Tasks 2 and the consumer followup. `--vocab-path=PATH` flag spelling is consistent.

**4. Review Focus:** The 5 failure modes listed in the header are all addressed by a task's test (Task 1's test for the typo; Task 2's 3 unit tests + 1 CLI test for the vocab error class; Task 3's end-to-end smoke test for the wiring; Task 4's grep step for the loop-closer; Task 5's documented consumer followup for the upgrade propagation). No gaps.
