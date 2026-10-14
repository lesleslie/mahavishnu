---
title: Shared Frontmatter Validator (crackerjack docs validate)
date: 2026-07-26
last_reviewed: 2026-07-27
status: complete
role: canonical
topic: shared-frontmatter-validator
spec-for: crackerjack v0.69.5+
---

# Shared Frontmatter Validator

## Problem

The script `scripts/validate_document_frontmatter.py` is seed-copied into 5
Bodai ecosystem repos (crackerjack, dhara, session-buddy, akosha, oneiric,
mahavishnu). Today the 5 copies have **5 different MD5 hashes** — they have
already drifted. The drift caused the
[`documentation_cleanup` phase failure on 2026-07-26](#regression-source):
each consumer's script unconditionally emitted `MISSING_FRONTMATTER` as an
ERROR, even when `--allow-nonstandard` was set, blocking the cleanup phase
from running on legacy docs.

The crackerjack `services/frontmatter_validator.py` wrapper, the
`crackerjack docs validate` CLI subcommand, and the `phase_coordinator.py`
cleanup phase all reach the validator via subprocess invocation of the
seed-copied script. With 5 copies diverging, fixing a bug in one place
doesn't fix it everywhere.

## Goal

Move the validator into the crackerjack package as a real Python module.
Consumer repos delete their `scripts/validate_document_frontmatter.py`. All
three call sites (CLI subcommand, Python wrapper, cleanup phase) call the
same in-process Python module. **One source of truth.**

## Non-Goals

- Consolidating `docs/schemas/document-frontmatter-v1.md` or
  `topic-vocabulary-v1.md` (still seed-copied; tracked separately).
- Consolidating `scripts/regenerate_plan_index.py` (still seed-copied;
  tracked separately).
- Adding a new docs-group command. The existing `crackerjack docs validate`
  is the surface; this design refactors its internals.
- Changing the JSON output shape (preserves backward compat for any
  downstream JSON consumers — none exist today, but the contract is
  documented).

## Architecture

```
crackerjack/                                # canonical source
├── validators/
│   ├── __init__.py
│   ├── frontmatter.py        # MOVED from scripts/validate_document_frontmatter.py
│   └── git_root.py           # NEW: walks up to find .git
├── services/
│   └── frontmatter_validator.py    # MODIFIED: in-process call (no subprocess)
├── cli/
│   └── docs_cli.py           # MODIFIED: `validate` calls new module directly
└── __main__.py               # unchanged (docs group already registered at line 132)

# In each consumer repo:
scripts/validate_document_frontmatter.py   # DELETED
```

### Module placement

`crackerjack/validators/` is a new package. It holds validator modules
that are consumed in-process by the wrapper and CLI. Mirrors the existing
`crackerjack/services/` package (which holds adapters/business logic).

`crackerjack/validators/frontmatter.py` is the file formerly at
`scripts/validate_document_frontmatter.py`. It contains the entire
validator: `extract_frontmatter`, `validate_file`, `discover_files`,
`build_parser`, `main`, dataclasses `Issue`, `FileResult`. The module
public API becomes `main(argv: list[str] | None = None) -> int` and
`validate_file(...)`. The `if __name__ == "__main__":` block is removed.

### Repo-root discovery

`crackerjack/validators/git_root.py` provides two functions:

```python
def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) looking for .git.
    Raises RepositoryNotFoundError if not found."""

def find_repo_root_or_none(start: Path | None = None) -> Path | None:
    """Same, but returns None instead of raising."""
```

Both walk `start` (or `Path.cwd()`) and its parents, returning the
directory containing a `.git` file/directory. No `subprocess` calls
(no `git rev-parse --show-toplevel` shell-out). Cheap and pure Python.

`RepositoryNotFoundError` is a new exception in `crackerjack.errors`
alongside the existing exception hierarchy.

## Components

### `crackerjack/validators/frontmatter.py`

Source: `scripts/validate_document_frontmatter.py` (line-for-line copy of
the crackerjack version).

Changes from the original script:

- `repo_root` is no longer computed from `__file__`; callers pass it
  explicitly via `validate_file()` or `main()`.
- `validate_file` signature is unchanged.
- `main(argv: list[str] | None = None) -> int` is unchanged.
- The `if __name__ == "__main__":` block is removed.
- The `--allow-nonstandard` flag's behavior (already fixed in the prior
  bug-fix commit) is preserved as-is.

### `crackerjack/validators/git_root.py`

New module (~30 lines). Uses `os.path.commonpath` for safe ancestor
checks. Walks up until `.git` is found or `Path.anchor` is reached
(`/.` on Linux, `C:\` on Windows). Returns the directory containing
`.git`, not the `.git` itself.

### `crackerjack/services/frontmatter_validator.py` (modified)

Old behavior: spawns `python scripts/validate_document_frontmatter.py
--json --allow-nonstandard` as a subprocess, parses stdout JSON, returns
`FrontmatterValidationResult`.

New behavior: calls `crackerjack.validators.frontmatter.discover_files`
and `validate_file` directly in-process. Returns the same
`FrontmatterValidationResult` dataclass. Same public API.

```python
class FrontmatterValidator:
    def validate(self, *, strict=False, allow_nonstandard=True, ...) -> FrontmatterValidationResult:
        results = [
            validators.frontmatter.validate_file(
                path, rel, repo_root=self.pkg_path,
                known_files=known_files, known_topics=known_topics,
                strict=strict, allow_nonstandard=allow_nonstandard,
                validate_links=validate_links, skip_link_note=skip_link_note,
            )
            for path, rel in validators.frontmatter.discover_files(
                self.pkg_path, default_stores, []
            )
        ]
        return FrontmatterValidationResult.from_payload(results, exit_success=True)
```

The wrapper's `FrontmatterValidationError` exception types and `reason`
enum (`"errors" | "timeout" | "crash"`) are preserved. The `timeout` and
`crash` reasons are still in the exception type but, since we no longer
spawn a subprocess, only `"errors"` is ever raised in practice.

### `crackerjack/cli/docs_cli.py:validate` (modified)

The existing `validate` subcommand already accepts a `--path` typer
option. Renaming it to `--repo-root` for clarity and aligning with the
new module's vocabulary. The auto-detect behavior is added: if
`--repo-root` is not provided, the CLI walks up from cwd to find the
git toplevel.

```python
@app.command()
def validate(
    *,
    strict: bool = typer.Option(False, "--strict"),
    store: str | None = typer.Option(None, "--store"),
    validate_links: bool = typer.Option(False, "--validate-links"),
    json_output: bool = typer.Option(False, "--json"),
    repo_root: Path | None = typer.Option(
        None, "--repo-root",
        help="Repo root to validate. Defaults to git toplevel of cwd.",
    ),
) -> None:
    if repo_root is None:
        detected = git_root.find_repo_root_or_none()
        if detected is None:
            raise typer.BadParameter(
                "not in a git repository; pass --repo-root"
            )
        repo_root = detected

    validator = FrontmatterValidator(pkg_path=repo_root)
    # ... rest unchanged
```

The CLI's `pkg_path` argument is renamed to `repo_root` for clarity, but
the wrapper's `pkg_path` attribute stays (matches existing test
fixtures). The previous `--path` CLI flag is replaced by `--repo-root`.
This is a breaking change to the CLI surface; no external consumer of
the CLI is known.

## Data flow

### CLI invocation

```
crackerjack entry point (crackerjack.__main__:cli)
  └─> Typer parses args → docs subcommand
      └─> docs_cli.py:validate(repo_root=...)
          └─> FrontmatterValidator(pkg_path=repo_root).validate(...)
              └─> validators.frontmatter.discover_files(...)
              └─> for each file: validators.frontmatter.validate_file(...)
              └─> FrontmatterValidationResult.from_payload(results, exit_success=True)
          └─> Format JSON or human-readable output
          └─> typer.Exit(0) if success, typer.Exit(1) if errors
```

### Cleanup phase invocation (in-process)

```
phase_coordinator.run_documentation_cleanup_phase(options)
  └─> FrontmatterValidator(pkg_path=self.pkg_path).validate(allow_nonstandard=True)
      └─> [same Python module calls as above, ALL in-process]
  └─> if not result.success: fail_task(...) and return False
  └─> DocumentationCleanup.cleanup_documentation(...)
  └─> return True
```

### Data shape (preserved)

- `Issue(severity, rule, message)` — per-issue dataclass.
- `FileResult(path, status, errors, warnings)` — per-file dataclass.
- `FrontmatterValidationResult(success, files_scanned, errors, warnings,
  duration_ms, error_count, warning_count)` — aggregate dataclass.
- JSON output: list of `{path, status, errors[], warnings[]}` objects.
- Exit codes: 0 = clean, 1 = errors, 2 = broken CLI args.

## Error handling

| Scenario | Exit code | Handling |
|---|---|---|
| `--repo-root` doesn't exist | 2 | `typer.BadParameter` |
| Not in git repo, no `--repo-root` | 2 | `typer.BadParameter` |
| Validation errors (non-empty) | 1 | Wrapper returns `success=False`; CLI exits 1 |
| Clean validation | 0 | Wrapper returns `success=True`; CLI exits 0 |
| Crash in validator code | 1 | Wrapper catches, raises `FrontmatterValidationError(reason="crash")`; CLI exits 1 |

The cleanup phase's existing error handling is preserved:

```python
# phase_coordinator.py:run_documentation_cleanup_phase
if not vresult.success:
    self.session.fail_task(
        "documentation_cleanup",
        f"frontmatter validation failed: {vresult.error_count} errors",
    )
    return False
```

`@handle_errors` decorator catches unhandled exceptions and routes to
`session.fail_task`.

## Testing

### Unit tests

| Test | Asserts | Lives in |
|---|---|---|
| `test_allow_nonstandard_tolerates_missing_frontmatter` | The bug we just fixed doesn't regress | `tests/unit/test_validate_frontmatter.py` (renamed) |
| `test_missing_frontmatter_is_error_by_default` | Strict mode unchanged | (same) |
| `test_validate_file_required_keys` | status/role/date/last_reviewed/topic required | (same) |
| `test_validate_file_date_format` | ISO-8601 only | (same) |
| `test_validate_file_topic_slug` | Matches `^[a-z][a-z0-9-]{2,40}$` | (same) |
| `test_validate_file_role_status_pair` | role=superseded requires superseded_by | (same) |
| `test_validate_file_inline_status` | Triggers NONSTANDARD_INLINE_STATUS warning | (same) |
| `test_validate_file_superseded_by` | List/scalar resolution | (same) |
| `test_validate_file_blocks_on` | List resolution | (same) |
| `test_discover_files_includes_stores` | Default stores covered | (same) |
| `test_discover_files_excludes_archive` | Archive subdirs skipped | (same) |
| `test_discover_files_excludes_drafts` | `docs/plans/drafts/` skipped | (same) |
| `test_find_repo_root_walks_up` | Walks to nearest `.git` | `tests/unit/test_git_root.py` (new) |
| `test_find_repo_root_not_found` | Returns None outside repo | (same) |
| `test_find_repo_root_at_root` | `/` is the upper bound | (same) |
| `test_frontmatter_validator_no_subprocess` | Wrapper does NOT spawn subprocess | `tests/unit/test_frontmatter_validator.py` (modified) |

### Integration tests

| Test | Asserts | Lives in |
|---|---|---|
| `test_docs_validate_cli_exit_zero` | Real CLI exits 0 with clean docs | `tests/integration/test_docs_validate_cli.py` (new) |
| `test_docs_validate_cli_exit_one_with_errors` | Real CLI exits 1 with bad docs | (same) |
| `test_docs_validate_cli_repo_root_auto_detect` | `git_root` discovery works in a real repo | (same) |
| `test_run_documentation_cleanup_phase_with_missing_frontmatter` | End-to-end cleanup succeeds with a missing-frontmatter file | `tests/test_phase_coordinator.py` (new test in existing class) |

### Existing tests that stay green

- `tests/unit/test_frontmatter_validator.py` (existing subprocess-mocking
  tests) — these continue to test the wrapper's public API. They mock
  `secure_subprocess.run`; the new code path doesn't use it, so the mocks
  are never invoked. Tests pass unchanged.
- `tests/test_phase_coordinator.py` (existing `MagicMock` tests) — these
  continue to validate the phase's contract. They keep working because
  the wrapper's public API is unchanged.
- `tests/test_documentation_cleanup.py` — unrelated to this change.

### Verification commands

```bash
# Run validator unit tests
pytest tests/unit/test_validate_frontmatter.py

# Run wrapper unit tests
pytest tests/unit/test_frontmatter_validator.py

# Run CLI integration tests
pytest tests/integration/test_docs_validate_cli.py

# Run cleanup phase tests
pytest tests/test_phase_coordinator.py::TestDocumentationCleanupPhase

# Run the full new test suite end-to-end
pytest tests/unit/test_validate_frontmatter.py \
       tests/unit/test_frontmatter_validator.py \
       tests/integration/test_docs_validate_cli.py \
       tests/test_phase_coordinator.py
```

## Migration plan

This is a coordinated change across 5 repos. Order matters:

1. **crackerjack** (canonical source)
   - Add `crackerjack/validators/__init__.py`, `frontmatter.py`, `git_root.py`.
   - Add `crackerjack/errors.py::RepositoryNotFoundError` (or extend existing).
   - Modify `crackerjack/services/frontmatter_validator.py` to call the new module.
   - Modify `crackerjack/cli/docs_cli.py:validate` to add `--repo-root` and use `git_root`.
   - Move existing tests `tests/unit/test_validate_document_frontmatter.py` → `tests/unit/test_validate_frontmatter.py` (and update import path).
   - Add `tests/unit/test_git_root.py`, `tests/integration/test_docs_validate_cli.py`.
   - Add new `test_run_documentation_cleanup_phase_with_missing_frontmatter` to `tests/test_phase_coordinator.py`.
   - Update `scripts/regenerate_plan_index.py` doc reference (line 379) to point to `crackerjack docs validate` instead of the script.
   - Bump version: 0.69.4 → 0.69.5.
   - Run `crackerjack run` (full quality gate).
   - Release and tag.

2. **dhara, session-buddy, akosha, oneiric, mahavishnu** (each)
   - Update `crackerjack` dependency to `>=0.69.5` in `pyproject.toml`.
   - Delete `scripts/validate_document_frontmatter.py`.
   - Run `pytest` to verify cleanup phase still passes.
   - If any other test reference to the script exists, update it.

3. **Verification after merge**
   - In each consumer repo, run `crackerjack docs validate --json --allow-nonstandard` and confirm exit 0 with 0 errors.
   - Run `crackerjack run` (full quality gate including the cleanup phase) and confirm documentation_cleanup passes.

## Risks

- **Phase coordinator regressions**: The cleanup phase is the highest-risk
  integration. The existing `tests/test_phase_coordinator.py` tests use
  `MagicMock` to fake the validator, so they don't exercise the new
  in-process path. The new integration test
  `test_run_documentation_cleanup_phase_with_missing_frontmatter` is
  essential.

- **Lost exit-code semantics**: The subprocess path's `timeout` and
  `crash` exit codes are not directly equivalent to in-process
  exceptions. We keep a `reason` enum on the exception so callers can
  still distinguish.

- **Unknown JSON consumers**: The JSON output format is preserved, but
  if anything **outside** the crackerjack repo parses
  `crackerjack docs validate --json` output, it should keep working.
  No downstream consumers known.

- **Cross-repo coordination**: 5 repos need to merge in lockstep. If
  the consumer repos bump `crackerjack>=0.69.5` before the canonical
  release, they'll fail. Order: release crackerjack first, then update
  consumers.

## Success criteria

- `crackerjack docs validate --json --allow-nonstandard` exits 0 in
  all 5 consumer repos with 0 errors.
- `crackerjack docs validate --json` (without `--allow-nonstandard`)
  exits 1 in any repo with non-empty `MISSING_FRONTMATTER` errors.
- `find . -name validate_document_frontmatter.py` returns 0 results
  in all 5 consumer repos.
- `phase_coordinator.run_documentation_cleanup_phase` succeeds with a
  missing-frontmatter file in the repo.
- The new tests pass.
- The bug we just fixed (2026-07-26) cannot recur because the validator
  logic lives in one place.

## Regression source

The 2026-07-26 incident: crackerjack v0.69.4 shipped fixed
`scripts/validate_document_frontmatter.py` (the `--allow-nonstandard`
flag was made to tolerate `MISSING_FRONTMATTER`). The 4 consumer repos
(dhara, session-buddy, akosha, oneiric) had **older copies** of the
script that did not have this fix. The cleanup phase in those repos
blocked on `workflow-task-failed: documentation_cleanup` because the
subprocess call into the stale script returned a non-zero exit code.
This design eliminates the possibility of drift by eliminating the
copies.

## Related work

- `docs/schemas/document-frontmatter-v1.md` — currently seed-copied.
  Could be packaged as `crackerjack.schemas.v1` in a follow-up.
- `scripts/regenerate_plan_index.py` — currently seed-copied. Could be
  `crackerjack docs regenerate-plan-index` in a follow-up.
- `FrontmatterValidationError` — already in
  `crackerjack/services/frontmatter_validator.py`; preserved.
- `FrontmatterValidator` Python wrapper — already in
  `crackerjack/services/frontmatter_validator.py`; this design moves
  its internals, not its API.
