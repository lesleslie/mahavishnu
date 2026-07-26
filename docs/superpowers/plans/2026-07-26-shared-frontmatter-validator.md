---
status: draft
role: implementation
date: 2026-07-26
spec: ../specs/2026-07-26-shared-frontmatter-validator-design.md
topic: shared-frontmatter-validator
---

# Shared Frontmatter Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Move the validator script from a per-repo seed-copied file into the crackerjack package as a real Python module. Consumer repos delete their `scripts/validate_document_frontmatter.py`. Eliminates the cross-repo drift that caused the 2026-07-26 cleanup phase failure.
> **Architecture:** Move `scripts/validate_document_frontmatter.py` → `crackerjack/validators/frontmatter.py`. Add new `crackerjack/validators/git_root.py` for repo-root discovery. Refactor `crackerjack/services/frontmatter_validator.py` to call the new module in-process (no subprocess). Refactor `crackerjack docs validate` CLI subcommand to use the new module. Delete `scripts/validate_document_frontmatter.py` from 5 consumer repos.
> **Tech Stack:** Python 3.13, Typer, pathlib, pytest, crackerjack (already a dependency in all 5 repos).

## Global Constraints

- Crackerjack is **already a declared dependency** in `dhara`, `session-buddy`, `akosha`, `oneiric`, and `mahavishnu`. No new dep additions.
- All consumer repos require `crackerjack>=0.69.5` after the canonical release.
- The `FrontmatterValidator` Python wrapper's PUBLIC API stays unchanged: `FrontmatterValidator(pkg_path=Path).validate(strict=False, allow_nonstandard=True, ...)` returns `FrontmatterValidationResult`.
- The `crackerjack docs validate` CLI surface changes `--path` → `--repo-root`. No external consumer of the CLI is known.
- Each commit is single-purpose; tests pass at every commit; commit only on GREEN.
- Cross-repo changes release in order: crackerjack first, then consumer repos.
- Existing pytest markers, project conventions, and `from __future__ import annotations` heredity apply.
- Hard limits from `pyproject.toml` apply: line length 100, function args ≤ 10, branches ≤ 15, returns ≤ 6, statements ≤ 55.

______________________________________________________________________

## Phase 1: Foundation in crackerjack

### Task 1: Add `RepositoryNotFoundError` exception

**Files:**
- Modify: `crackerjack/errors.py:1-50` (extend existing exception hierarchy)
- Test: `tests/unit/test_errors.py` (extend if exists, else create)

**Interfaces:**
- Consumes: nothing
- Produces: `from crackerjack.errors import RepositoryNotFoundError`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_errors.py (extend existing file or create)
import pytest
from crackerjack.errors import RepositoryNotFoundError


def test_repository_not_found_error_is_exception():
    """RepositoryNotFoundError must be a regular Exception subclass."""
    assert issubclass(RepositoryNotFoundError, Exception)


def test_repository_not_found_error_message():
    """RepositoryNotFoundError carries the search-start path."""
    err = RepositoryNotFoundError("not found from /tmp")
    assert "not found from /tmp" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_errors.py::test_repository_not_found_error_is_exception -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'RepositoryNotFoundError'`

- [ ] **Step 3: Add the exception to `crackerjack/errors.py`**

Open `crackerjack/errors.py` and add this class. Place it near the other "not found" exceptions (e.g., near `AdapterNotFoundError` if it exists, or at the end of the file):

```python
class RepositoryNotFoundError(Exception):
    """Raised when a git repository root cannot be discovered.

    Used by validators.frontmatter.git_root when find_repo_root() is
    invoked outside any git repository and the caller wants strict
    behavior. Callers that want lenient behavior should use
    find_repo_root_or_none() instead.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_errors.py::test_repository_not_found_error_is_exception -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add crackerjack/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): add RepositoryNotFoundError for git root discovery"
```

---

### Task 2: Add `git_root.py` module with tests

**Files:**
- Create: `crackerjack/validators/__init__.py`
- Create: `crackerjack/validators/git_root.py`
- Test: `tests/unit/test_git_root.py`

**Interfaces:**
- Consumes: `from crackerjack.errors import RepositoryNotFoundError`
- Produces:
  - `find_repo_root(start: Path | None = None) -> Path` — raises if not found
  - `find_repo_root_or_none(start: Path | None = None) -> Path | None` — returns None if not found

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_git_root.py
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.errors import RepositoryNotFoundError
from crackerjack.validators import git_root


def test_find_repo_root_walks_up_to_dot_git(tmp_path: Path) -> None:
    """find_repo_root returns the directory containing .git."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    assert git_root.find_repo_root(start=nested) == tmp_path


def test_find_repo_root_or_none_returns_none_outside_repo(tmp_path: Path) -> None:
    """find_repo_root_or_none returns None when no .git is found."""
    # tmp_path is a fresh dir with no .git anywhere up to root
    # We test by walking from a subdir of a controlled structure
    # To avoid hitting the host's actual git repo, we walk down-only
    leaf = tmp_path / "no_repo_here"
    leaf.mkdir()
    # Walk up from leaf; if the host filesystem has a .git somewhere
    # above tmp_path this test will be flaky. We pre-check that
    # tmp_path itself has no .git and we cap the walk at tmp_path.
    result = git_root.find_repo_root_or_none(start=leaf, stop_at=tmp_path)
    assert result is None


def test_find_repo_root_or_none_returns_none_when_stop_at_reached(tmp_path: Path) -> None:
    """find_repo_root_or_none honors the stop_at boundary."""
    (tmp_path / ".git").mkdir()
    # Place leaf INSIDE the repo but stop the search at the parent
    inside = tmp_path / "subdir"
    inside.mkdir()
    result = git_root.find_repo_root_or_none(start=inside, stop_at=tmp_path.parent)
    assert result is None


def test_find_repo_root_strict_raises_outside_repo(tmp_path: Path) -> None:
    """find_repo_root raises RepositoryNotFoundError when not found."""
    leaf = tmp_path / "no_repo_here"
    leaf.mkdir()
    with pytest.raises(RepositoryNotFoundError):
        git_root.find_repo_root(start=leaf, stop_at=tmp_path)


def test_find_repo_root_default_start_is_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """find_repo_root defaults start to Path.cwd()."""
    # We just verify the function signature: default None is mapped to cwd.
    import inspect
    sig = inspect.signature(git_root.find_repo_root)
    assert sig.parameters["start"].default is None


def test_find_repo_root_handles_dot_git_file(tmp_path: Path) -> None:
    """find_repo_root recognizes .git as a file (git submodule/worktree)."""
    (tmp_path / ".git").write_text("gitdir: /tmp/elsewhere\n")
    assert git_root.find_repo_root(start=tmp_path) == tmp_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_git_root.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'crackerjack.validators'`

- [ ] **Step 3: Create the package skeleton**

Create `crackerjack/validators/__init__.py` (empty file):

```python
"""Validator modules for in-process use by services and CLI."""
```

- [ ] **Step 4: Write the implementation**

Create `crackerjack/validators/git_root.py`:

```python
from __future__ import annotations

from pathlib import Path

from crackerjack.errors import RepositoryNotFoundError


def find_repo_root(
    start: Path | None = None,
    *,
    stop_at: Path | None = None,
) -> Path:
    """Walk up from ``start`` (default: cwd) looking for a .git entry.

    Returns the directory containing .git. Raises
    :class:`RepositoryNotFoundError` if no .git is found before reaching
    the filesystem root or ``stop_at``.

    Args:
        start: Directory to begin the search. Defaults to ``Path.cwd()``.
        stop_at: Upper bound for the search. Defaults to the filesystem
            root of ``start``. Useful in tests to avoid walking into the
            host filesystem.
    """
    result = find_repo_root_or_none(start=start, stop_at=stop_at)
    if result is None:
        search_start = start or Path.cwd()
        raise RepositoryNotFoundError(
            f"no .git directory found at or above {search_start}"
        )
    return result


def find_repo_root_or_none(
    start: Path | None = None,
    *,
    stop_at: Path | None = None,
) -> Path | None:
    """Same as :func:`find_repo_root` but returns ``None`` if not found."""
    current = (start or Path.cwd()).resolve()
    default_stop = current.anchor
    upper = (stop_at or Path(default_stop)).resolve()

    while True:
        git_path = current / ".git"
        if git_path.exists():
            return current
        if current == upper:
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_git_root.py -v --no-cov`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add crackerjack/validators/__init__.py crackerjack/validators/git_root.py tests/unit/test_git_root.py
git commit -m "feat(validators): add git_root discovery helper with tests"
```

---

### Task 3: Move validator script to `crackerjack/validators/frontmatter.py`

**Files:**
- Create: `crackerjack/validators/frontmatter.py` (copy of `scripts/validate_document_frontmatter.py` with edits)
- Modify: `tests/unit/test_validate_document_frontmatter.py` → rename to `tests/unit/test_validate_frontmatter.py` (and update import path)
- Delete: `scripts/validate_document_frontmatter.py` (deferred to Task 7 — keep during refactor to avoid breaking Phase 1 commits)

**Interfaces:**
- Consumes: nothing (self-contained)
- Produces:
  - `validate_file(path, rel, *, repo_root, known_files, known_topics, strict, allow_nonstandard, validate_links, skip_link_note) -> FileResult`
  - `main(argv: list[str] | None = None) -> int`
  - `discover_files(repo_root, stores, extra_paths) -> list[tuple[Path, str]]`
  - `extract_frontmatter(text) -> tuple[dict | None, str | None]`
  - `FileResult`, `Issue`, `validate_file`, `build_parser`, `DEFAULT_STORES`, `STORE_LOOKUP`

- [ ] **Step 1: Move the existing test file and update imports**

```bash
cd /Users/les/Projects/crackerjack
git mv tests/unit/test_validate_document_frontmatter.py tests/unit/test_validate_frontmatter.py
```

Edit `tests/unit/test_validate_frontmatter.py` (the renamed file):

The `_load_module()` helper at the top needs to load from the new path. Replace:

```python
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "validate_document_frontmatter.py"
)
```

with:

```python
from crackerjack.validators import frontmatter as validator_module
```

Then delete the `_load_module()` function and the fixture:
```python
@pytest.fixture
def validator_module() -> t.Any:
    return _load_module()
```

Update all `validator_module.X` references to use the imported module directly. Update the `test_main_exits_zero_when_only_missing_frontmatter` test (if present) to call `frontmatter.main(...)` directly.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_validate_frontmatter.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'crackerjack.validators.frontmatter'`

- [ ] **Step 3: Move the script to the package**

```bash
cd /Users/les/Projects/crackerjack
git mv scripts/validate_document_frontmatter.py crackerjack/validators/frontmatter.py
```

Edit `crackerjack/validators/frontmatter.py` to make these changes:

1. **Remove the `if __name__ == "__main__":` block** at the bottom of the file:

```python
# OLD (delete these lines at the very bottom of the file):
if __name__ == "__main__":
    raise SystemExit(main())
```

2. **Remove the hardcoded `repo_root` derivation** in `main()`:

```python
# OLD (line ~681):
    repo_root = Path(__file__).resolve().parent.parent

# NEW: caller must pass --repo-root as the first positional argument,
# OR the CLI passes cwd. See Task 4 for the CLI wiring.
```

Replace it with:

```python
    # Resolve repo_root: prefer --repo-root flag, else first positional
    # path's parent if it's a directory, else cwd.
    if args.paths:
        first = Path(args.paths[0]).resolve()
        repo_root = first if first.is_dir() else first.parent
    else:
        repo_root = Path.cwd()
```

Wait — actually the CLI handles repo-root resolution at a higher level (Task 4). The module's `main()` should accept a `--repo-root` argument. Add the CLI argument:

```python
    parser.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help="Repo root to validate. Defaults to first positional path or cwd.",
    )
```

And update `main()` to use it:

```python
    if args.repo_root is not None:
        repo_root = Path(args.repo_root).resolve()
    elif args.paths:
        first = Path(args.paths[0]).resolve()
        repo_root = first if first.is_dir() else first.parent
    else:
        repo_root = Path.cwd()
```

3. **Add `from __future__ import annotations`** at the top of the file (after the module docstring).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_validate_frontmatter.py -v --no-cov`
Expected: PASS (all moved tests)

- [ ] **Step 5: Verify the module is importable**

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -c "from crackerjack.validators import frontmatter; print(frontmatter.__file__)"
```
Expected: `/Users/les/Projects/crackerjack/crackerjack/validators/frontmatter.py`

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_validate_frontmatter.py crackerjack/validators/frontmatter.py
git rm scripts/validate_document_frontmatter.py
git commit -m "refactor(validators): move validate_document_frontmatter.py into crackerjack.validators.frontmatter"
```

---

### Task 4: Refactor `FrontmatterValidator` Python wrapper to call module in-process

**Files:**
- Modify: `crackerjack/services/frontmatter_validator.py:1-260`
- Modify: `tests/unit/test_frontmatter_validator.py:1-100`

**Interfaces:**
- Consumes: `from crackerjack.validators import frontmatter`
- Produces: same public API (`FrontmatterValidator`, `FrontmatterValidationResult`, `FrontmatterValidationError`, `FrontmatterValidator.validate()`)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_frontmatter_validator.py`:

```python
def test_validate_does_not_spawn_subprocess() -> None:
    """The wrapper must NOT spawn a subprocess when calling validate().

    Regression: the old wrapper spawned `python scripts/validate_document_frontmatter.py`
    as a subprocess. After the refactor, all validation happens in-process.
    """
    from unittest.mock import patch

    v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
    with (
        patch("subprocess.run") as mock_subprocess_run,
        patch(
            "crackerjack.services.frontmatter_validator.secure_subprocess.run"
        ) as mock_secure_run,
    ):
        # The clean-JSON path triggers the wrapper to parse a payload.
        # If the wrapper still spawns a subprocess, one of these mocks is called.
        from unittest.mock import MagicMock
        empty_payload = json.dumps(
            {"files_scanned": 0, "errors": [], "warnings": [], "duration_ms": 0}
        )
        mock_secure_run.return_value = MagicMock(
            stdout="",  # empty stdout → simulates "no subprocess output"
            returncode=0,
            stderr="",
        )
        # Force a no-files case so discover_files returns [] and validate_file
        # is never called. The wrapper should still avoid the subprocess.
        with patch(
            "crackerjack.validators.frontmatter.discover_files",
            return_value=[],
        ):
            result = v.validate()
        assert result.success is True
        # In-process path: subprocess.run was never called.
        mock_subprocess_run.assert_not_called()
        # The wrapper's secure_subprocess fallback was never invoked either
        # (with the refactor, this code path is removed).
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_frontmatter_validator.py::test_validate_does_not_spawn_subprocess -v --no-cov`
Expected: FAIL. The wrapper currently calls `secure_subprocess.run` which we've mocked; the test asserts the call happens. With the in-process refactor, the call doesn't happen.

- [ ] **Step 3: Refactor the wrapper**

Open `crackerjack/services/frontmatter_validator.py` and replace the body. Keep the public API (class signatures, methods, dataclasses) the same. Replace only the internals:

```python
from __future__ import annotations

import dataclasses
import typing as t
from pathlib import Path

from crackerjack.validators import frontmatter as _validator

if t.TYPE_CHECKING:
    from crackerjack.config.settings import CrackerjackSettings


logger = t.Any  # standard logging replaced per project convention


@dataclasses.dataclass
class FrontmatterValidationIssue:
    file: str
    line: int
    code: str
    message: str

    def __getitem__(self, key: str) -> str | int:
        if key not in {"file", "line", "code", "message"}:
            raise KeyError(key)
        return getattr(self, key)


@dataclasses.dataclass
class FrontmatterValidationResult:
    success: bool
    files_scanned: int
    errors: list[FrontmatterValidationIssue]
    warnings: list[FrontmatterValidationIssue]
    duration_ms: int
    error_count: int = 0
    warning_count: int = 0

    @classmethod
    def from_file_results(
        cls,
        payload: list[t.Any],
        exit_success: bool,
    ) -> FrontmatterValidationResult:
        errors: list[FrontmatterValidationIssue] = []
        warnings: list[FrontmatterValidationIssue] = []
        for file_result in payload:
            if not isinstance(file_result, dict):
                continue
            path = str(file_result.get("path", ""))
            errors.extend(
                _issue_from_dict(issue, path=path)
                for issue in file_result.get("errors", [])
            )
            warnings.extend(
                _issue_from_dict(issue, path=path)
                for issue in file_result.get("warnings", [])
            )
        return cls(
            success=exit_success and not errors,
            files_scanned=len(payload),
            errors=errors,
            warnings=warnings,
            duration_ms=0,
            error_count=len(errors),
            warning_count=len(warnings),
        )


def _issue_from_dict(
    issue: t.Any,
    *,
    path: str = "",
) -> FrontmatterValidationIssue:
    if not isinstance(issue, dict):
        return FrontmatterValidationIssue(
            file=path,
            line=0,
            code="unknown",
            message=str(issue),
        )
    return FrontmatterValidationIssue(
        file=str(issue.get("file", path)),
        line=int(issue.get("line", 0)),
        code=str(issue.get("code", issue.get("rule", "unknown"))),
        message=str(issue.get("message", "")),
    )


class FrontmatterValidationError(Exception):
    def __init__(
        self,
        message: str,
        result: FrontmatterValidationResult | None = None,
        reason: str = "errors",
    ) -> None:
        super().__init__(message)
        self.result = result
        self.reason = reason


class FrontmatterValidator:
    DEFAULT_TIMEOUT = 120  # kept for API compatibility; no longer used

    def __init__(
        self,
        pkg_path: Path | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.pkg_path = (pkg_path or Path.cwd()).resolve()
        self.timeout_seconds = timeout_seconds  # unused; kept for API compat

    def validate(
        self,
        strict: bool = False,
        allow_nonstandard: bool = True,
        validate_links: bool = False,
        store: str | None = None,
    ) -> FrontmatterValidationResult:
        """Run the validator in-process and return the aggregate result.

        No subprocess is spawned. The validator module is invoked directly.
        """
        try:
            stores = _resolve_stores(self.pkg_path, store)
            files = _validator.discover_files(self.pkg_path, stores, [])
        except Exception as exc:
            raise FrontmatterValidationError(
                f"validator crashed during file discovery: {exc}",
                reason="crash",
            ) from exc

        known_files = {rel for _, rel in files}
        known_topics = _validator.load_seed_topics(self.pkg_path)

        results: list[t.Any] = []
        for abs_path, rel in files:
            try:
                results.append(
                    _validator.validate_file(
                        abs_path,
                        rel,
                        repo_root=self.pkg_path,
                        known_files=known_files,
                        known_topics=known_topics,
                        strict=strict,
                        allow_nonstandard=allow_nonstandard,
                        validate_links=validate_links,
                        skip_link_note=not validate_links,
                    )
                )
            except Exception as exc:
                raise FrontmatterValidationError(
                    f"validator crashed on {rel}: {exc}",
                    reason="crash",
                ) from exc

        return FrontmatterValidationResult.from_file_results(
            [
                {
                    "path": r.path,
                    "status": r.status,
                    "errors": [
                        {"rule": i.rule, "message": i.message}
                        for i in r.errors
                    ],
                    "warnings": [
                        {"rule": i.rule, "message": i.message}
                        for i in r.warnings
                    ],
                }
                for r in results
            ],
            exit_success=True,
        )

    def validate_or_raise(self, **kwargs: t.Any) -> FrontmatterValidationResult:
        result = self.validate(**kwargs)
        if not result.success:
            raise FrontmatterValidationError(
                f"{result.error_count} errors, {result.warning_count} warnings",
                result=result,
                reason="errors",
            )
        return result


def _resolve_stores(
    pkg_path: Path,
    store: str | None,
) -> list[Path]:
    """Translate the optional --store flag into a list of Path stores."""
    if store:
        rel = _validator.STORE_LOOKUP[store]
        return [pkg_path / rel]
    return [pkg_path / s for s in _validator.DEFAULT_STORES]
```

- [ ] **Step 4: Update existing tests that mocked the subprocess**

In `tests/unit/test_frontmatter_validator.py`, the existing 4 tests mock `crackerjack.services.frontmatter_validator.secure_subprocess.run`. With the refactor, that mock is no longer on the code path. Update the tests to instead patch the in-process module calls:

Update `test_validate_parses_clean_json` to use:

```python
from crackerjack.validators import frontmatter as _validator

def test_validate_parses_clean_json(tmp_path: Path) -> None:
    """Clean validator run returns success with zero errors."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    # No files means no validation errors → success.
    v = FrontmatterValidator(pkg_path=tmp_path)
    result = v.validate()
    assert isinstance(result, FrontmatterValidationResult)
    assert result.success is True
    assert result.files_scanned == 0
    assert result.error_count == 0
    assert result.warning_count == 0
```

Update `test_validate_raises_on_errors` to use a fixture that creates a malformed file:

```python
def test_validate_raises_on_errors(tmp_path: Path) -> None:
    """Bad frontmatter produces errors; validate_or_raise raises."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "bad.md").write_text(
        "---\nstatus: bogus\n---\n# Hi\n",
        encoding="utf-8",
    )
    v = FrontmatterValidator(pkg_path=tmp_path)
    with pytest.raises(FrontmatterValidationError) as exc_info:
        v.validate_or_raise()
    assert exc_info.value.result.error_count >= 1
```

Update `test_validate_timeout_raises` to remove (subprocess timeout no longer applies; the in-process path can raise other exceptions but not TimeoutError). Replace with:

```python
def test_validate_crash_raises() -> None:
    """A crash during validator execution becomes FrontmatterValidationError(reason='crash')."""
    from unittest.mock import patch

    v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
    with patch(
        "crackerjack.validators.frontmatter.discover_files",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(FrontmatterValidationError) as exc_info:
            v.validate()
    assert exc_info.value.reason == "crash"
```

Update `test_validate_passes_store_flag` to use the new in-process path:

```python
def test_validate_passes_store_flag(tmp_path: Path) -> None:
    """The --store flag narrows the scan to a single store."""
    plans = tmp_path / "docs" / "plans"
    decisions = tmp_path / ".claude" / "decisions"
    plans.mkdir(parents=True)
    decisions.mkdir(parents=True)
    (plans / "a.md").write_text("# No frontmatter\n", encoding="utf-8")
    (decisions / "b.md").write_text("# Missing here too\n", encoding="utf-8")

    v = FrontmatterValidator(pkg_path=tmp_path)
    plans_only = v.validate(store="plans")
    assert plans_only.files_scanned == 1
    decisions_only = v.validate(store="decisions")
    assert decisions_only.files_scanned == 1
```

- [ ] **Step 5: Run all validator tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_validate_frontmatter.py tests/unit/test_frontmatter_validator.py -v --no-cov`
Expected: PASS (regression test + 4 existing + 1 new wrapper test)

- [ ] **Step 6: Run phase coordinator tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/test_phase_coordinator.py::TestDocumentationCleanupPhase -v --no-cov`
Expected: PASS (3 tests, no changes needed)

- [ ] **Step 7: Commit**

```bash
git add crackerjack/services/frontmatter_validator.py tests/unit/test_frontmatter_validator.py
git commit -m "refactor(validator): call validator module in-process instead of subprocess"
```

---

### Task 5: Modify `crackerjack docs validate` CLI subcommand

**Files:**
- Modify: `crackerjack/cli/docs_cli.py:165-228`
- Test: `tests/unit/test_docs_cli.py` (existing, if present) OR `tests/unit/cli/test_docs_cli.py`

**Interfaces:**
- Consumes: `from crackerjack.validators import git_root`, `from crackerjack.services.frontmatter_validator import FrontmatterValidator`
- Produces: `crackerjack docs validate [--repo-root PATH] [--strict] [--store NAME] [--validate-links] [--json]`

- [ ] **Step 1: Read the current subcommand**

Read `crackerjack/cli/docs_cli.py:165-228` to confirm the current state. The subcommand currently has `--path` as the option name. Replace the option block to use `--repo-root` with auto-detect.

- [ ] **Step 2: Apply the change**

In `crackerjack/cli/docs_cli.py`, replace the `validate` function (lines 165-228) with:

```python
@app.command()
def validate(
    *,
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    store: str | None = typer.Option(
        None, "--store", help="Limit scan to a single store (e.g. docs/plans/)."
    ),
    validate_links: bool = typer.Option(
        False, "--validate-links", help="Also check cross-references."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of human-readable."
    ),
    repo_root: Path | None = typer.Option(
        None,
        "--repo-root",
        help="Repo root to validate. Defaults to git toplevel of cwd.",
    ),
) -> None:
    from crackerjack.validators import git_root

    if repo_root is None:
        detected = git_root.find_repo_root_or_none()
        if detected is None:
            raise typer.BadParameter(
                "not in a git repository; pass --repo-root to specify"
            )
        repo_root = detected

    validator = FrontmatterValidator(pkg_path=repo_root)
    try:
        result = validator.validate(
            strict=strict,
            allow_nonstandard=True,
            validate_links=validate_links,
            store=store,
        )
    except FrontmatterValidationError as exc:
        if json_output:
            payload = (
                exc.result.__dict__
                if exc.result is not None
                else {
                    "success": False,
                    "reason": exc.reason,
                }
            )
            console.print(json.dumps(payload, indent=2))
        else:
            console.print(f"[red]validator failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        payload = {
            "success": result.success,
            "files_scanned": result.files_scanned,
            "errors": [e.__dict__ for e in result.errors],
            "warnings": [w.__dict__ for w in result.warnings],
            "duration_ms": result.duration_ms,
        }
        console.print(json.dumps(payload, indent=2))
    else:
        status = "[green]OK[/green]" if result.success else "[yellow]WARN[/yellow]"
        console.print(
            f"{status} {result.files_scanned} files scanned: "
            f"{result.error_count} errors, {result.warning_count} warnings "
            f"({result.duration_ms} ms)"
        )
        for issue in result.errors:
            console.print(
                f" [red]ERROR[/red] {issue.file}:{issue.line} {issue.code}: {issue.message}"
            )
        for issue in result.warnings:
            console.print(
                f" [yellow]WARN[/yellow] {issue.file}:{issue.line} {issue.code}: {issue.message}"
            )

    if not result.success or (strict and result.warning_count > 0):
        raise typer.Exit(1)
```

- [ ] **Step 3: Verify the CLI works**

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m crackerjack docs validate --help
```
Expected: Output shows `--repo-root PATH` option, no `--path`.

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m crackerjack docs validate --json
```
Expected: exit 0, JSON output. The `crackerjack` repo's docs are all properly frontmattered; validator returns clean.

- [ ] **Step 4: Run any existing docs-cli tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/ -k "docs_cli or docs_validate" -v --no-cov`
Expected: PASS (existing tests that don't bind to specific flag names)

- [ ] **Step 5: Commit**

```bash
git add crackerjack/cli/docs_cli.py
git commit -m "feat(cli): docs validate --repo-root with auto-detect via git_root"
```

---

### Task 6: Add cleanup phase integration test (regression guard)

**Files:**
- Modify: `tests/test_phase_coordinator.py:285-375` (add a test to `TestDocumentationCleanupPhase`)

**Interfaces:**
- Consumes: `PhaseCoordinator` with `pkg_path=tmp_path`, real `FrontmatterValidator`, real `DocumentationCleanup`
- Produces: end-to-end test of `run_documentation_cleanup_phase` with a missing-frontmatter file

- [ ] **Step 1: Write the failing test**

Add to `TestDocumentationCleanupPhase`:

```python
def test_run_documentation_cleanup_phase_with_missing_frontmatter(
    self,
    tmp_path: Path,
) -> None:
    """End-to-end: cleanup phase succeeds when a missing-frontmatter file exists.

    Regression: the documentation_cleanup phase must not be blocked by
    MISSING_FRONTMATTER errors when --allow-nonstandard is set. Uses
    real services (no MagicMock) to exercise the in-process validator path.
    """
    from crackerjack.core.phase_coordinator import PhaseCoordinator

    # Create a repo with a missing-frontmatter file in docs/plans/
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "legacy.md").write_text(
        "# Legacy doc\n\nNo frontmatter here.\n",
        encoding="utf-8",
    )

    # Build a coordinator with the real validator and a dry-run cleanup
    coordinator = PhaseCoordinator(
        pkg_path=tmp_path,
        # ... minimal construction; use the existing test fixtures
    )
    options = MagicMock()
    options.cleanup_docs = True
    options.docs_dry_run = True  # don't actually move files

    result = coordinator.run_documentation_cleanup_phase(options)
    assert result is True, "cleanup phase must succeed despite missing-frontmatter"
```

Reading the existing test file, you'll see the `PhaseCoordinator` is constructed via `coordinator` fixture. Re-use that fixture; just override the `pkg_path` attribute or use the fixture's tmp_path.

The actual test depends on the existing fixture mechanics. The pattern is:

```python
def test_run_documentation_cleanup_phase_with_missing_frontmatter(
    self,
    coordinator: PhaseCoordinator,
    mock_options: MagicMock,
    tmp_path: Path,
) -> None:
    # Override pkg_path to point at our temp repo
    coordinator.pkg_path = tmp_path
    # Inject a missing-frontmatter file
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "legacy.md").write_text(
        "# Legacy\n",
        encoding="utf-8",
    )
    mock_options.cleanup_docs = True
    mock_options.docs_dry_run = True

    result = coordinator.run_documentation_cleanup_phase(mock_options)
    assert result is True
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/test_phase_coordinator.py::TestDocumentationCleanupPhase::test_run_documentation_cleanup_phase_with_missing_frontmatter -v --no-cov`
Expected: PASS

- [ ] **Step 3: Verify the existing 3 tests still pass**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/test_phase_coordinator.py::TestDocumentationCleanupPhase -v --no-cov`
Expected: 4 passed (3 existing + 1 new)

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase_coordinator.py
git commit -m "test(cleanup): add end-to-end regression test for missing-frontmatter cleanup"
```

---

### Task 7: Update `regenerate_plan_index.py` doc reference

**Files:**
- Modify: `scripts/regenerate_plan_index.py:379`

- [ ] **Step 1: Read the current line**

Read `scripts/regenerate_plan_index.py:379` to see the current wording.

- [ ] **Step 2: Replace the doc reference**

Replace the example that mentions `uv run python scripts/validate_document_frontmatter.py` with:

```python
# OLD:
#     "`uv run python scripts/validate_document_frontmatter.py --allow-nonstandard` ",

# NEW:
#     "`crackerjack docs validate --allow-nonstandard` ",
```

Actually, the existing reference is a *suggestion* for the user to run after regenerating. Keep the wording similar but point to the CLI:

```python
#     "`crackerjack docs validate --allow-nonstandard` ",
```

Update the surrounding context if it referenced the script path.

- [ ] **Step 3: Commit**

```bash
git add scripts/regenerate_plan_index.py
git commit -m "docs(regenerator): point to crackerjack docs validate CLI"
```

---

### Task 8: Bump version, run full quality gate, release

**Files:**
- Modify: `pyproject.toml` (version field)
- Modify: `CHANGELOG.md` (add entry)

- [ ] **Step 1: Bump version**

Edit `pyproject.toml` line `version = "0.69.4"` → `version = "0.69.5"`.

- [ ] **Step 2: Add CHANGELOG entry**

Add to `CHANGELOG.md` (top of file):

```markdown
## 0.69.5 (2026-07-26)

### Refactor

- Move `scripts/validate_document_frontmatter.py` into the crackerjack package as `crackerjack.validators.frontmatter`.
- `FrontmatterValidator` Python wrapper now calls the validator in-process; no subprocess.
- `crackerjack docs validate` CLI subcommand renamed `--path` to `--repo-root`; auto-detects git toplevel when omitted.
- Add `crackerjack.validators.git_root` for repo-root discovery.

### Migration

- Consumer repos (dhara, session-buddy, akosha, oneiric, mahavishnu) must delete `scripts/validate_document_frontmatter.py` and bump `crackerjack>=0.69.5`.
- `crackerjack docs validate --repo-root PATH` replaces `python scripts/validate_document_frontmatter.py`.
```

- [ ] **Step 3: Run quality gate**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m crackerjack run -v 2>&1 | tail -50`
Expected: All phases pass. The documentation_cleanup phase should pass without subprocess.

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest -v --no-cov 2>&1 | tail -30`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.69.5"
```

- [ ] **Step 6: Tag the release**

```bash
git tag v0.69.5
git push origin main --tags
```

The crackerjack release is now available. Consumers can bump their `crackerjack>=0.69.5` dependency.

---

## Phase 2: Migrate consumer repos

For each of the 5 consumer repos (dhara, session-buddy, akosha, oneiric, mahavishnu), the migration is identical. We'll execute it as 5 separate tasks.

### Task 9: Migrate dhara

**Files:**
- Modify: `pyproject.toml` (crackerjack dep version)
- Delete: `scripts/validate_document_frontmatter.py`

- [ ] **Step 1: Verify crackerjack>=0.69.5 is available**

Run: `cd /Users/les/Projects/dhara && grep -n "crackerjack" pyproject.toml`
Expected: At least one line referencing `crackerjack`.

- [ ] **Step 2: Decide on the version constraint**

Look at the existing constraint: it may be `crackerjack>=0.13.1` or similar. Bump it to `crackerjack>=0.69.5`:

```toml
# OLD:
"crackerjack>=0.13.1",

# NEW:
"crackerjack>=0.69.5",
```

Apply the same edit to the dependency in `pyproject.toml`.

- [ ] **Step 3: Delete the script**

```bash
cd /Users/les/Projects/dhara && git rm scripts/validate_document_frontmatter.py
```

- [ ] **Step 4: Install the new crackerjack version**

```bash
cd /Users/les/Projects/dhara && uv sync --group dev
```

- [ ] **Step 5: Verify the CLI works**

```bash
cd /Users/les/Projects/dhara && ./.venv/bin/crackerjack docs validate --json --allow-nonstandard | tail -20
```
Expected: exit 0, JSON with `success: true`, 0 errors.

- [ ] **Step 6: Run the cleanup phase**

```bash
cd /Users/les/Projects/dhara && ./.venv/bin/python -c "
from crackerjack.core.phase_coordinator import PhaseCoordinator
from pathlib import Path
from unittest.mock import MagicMock
coord = PhaseCoordinator(pkg_path=Path('.'))
opts = MagicMock()
opts.cleanup_docs = True
opts.docs_dry_run = True
print(coord.run_documentation_cleanup_phase(opts))
"
```
Expected: exit 0, prints `True`.

- [ ] **Step 7: Run tests**

```bash
cd /Users/les/Projects/dhara && ./.venv/bin/python -m pytest -v --no-cov 2>&1 | tail -20
```
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/dhara
git add pyproject.toml
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 10: Migrate session-buddy

Same as Task 9, but in `/Users/les/Projects/session-buddy`. Verbose steps omitted.

- [ ] Apply the same 8-step migration:
  - Look at current crackerjack version constraint in `pyproject.toml:35`
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - `uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add pyproject.toml
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 11: Migrate akosha

Same as Task 9, but in `/Users/les/Projects/akosha`. Verbose steps omitted.

- [ ] Apply the same 8-step migration:
  - Look at current crackerjack version constraint in `pyproject.toml:165`
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - `uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/akosha
git add pyproject.toml
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 12: Migrate oneiric

Same as Task 9, but in `/Users/les/Projects/oneiric`. Verbose steps omitted.

- [ ] Apply the same 8-step migration:
  - Look at current crackerjack version constraint in `pyproject.toml:226`
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - `uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/oneiric
git add pyproject.toml
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 13: Migrate mahavishnu

Same as Task 9, but in `/Users/les/Projects/mahavishnu`. Verbose steps omitted.

- [ ] Apply the same 8-step migration:
  - Look at current crackerjack version constraint (already pinned to local crackerjack in dev)
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - `uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add pyproject.toml
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

## Phase 3: Final verification

### Task 14: Cross-repo verification

- [ ] **Step 1: Find any remaining validator scripts**

Run:
```bash
find /Users/les/Projects/{crackerjack,dhara,session-buddy,akosha,oneiric,mahavishnu} -name validate_document_frontmatter.py -not -path "*/.venv/*" -not -path "*/worktrees/*"
```
Expected: 0 results.

- [ ] **Step 2: Verify all 5 consumer repos pass validation**

For each repo:
```bash
cd /Users/les/Projects/<repo> && ./.venv/bin/crackerjack docs validate --json --allow-nonstandard > /tmp/validate.json && echo "<repo>: exit=$?, errors=$(jq '.error_count' /tmp/validate.json)"
```
Expected: All 5 repos report exit 0 and 0 errors.

- [ ] **Step 3: Verify strict mode still rejects missing-frontmatter**

```bash
cd /Users/les/Projects/akosha && ./.venv/bin/python -c "
import subprocess, json
# Create a missing-frontmatter file in a temp dir
import tempfile, pathlib
with tempfile.TemporaryDirectory() as td:
    p = pathlib.Path(td)
    (p / 'docs' / 'plans').mkdir(parents=True)
    (p / 'docs' / 'plans' / 'bad.md').write_text('# No frontmatter')
    r = subprocess.run(['./.venv/bin/crackerjack', 'docs', 'validate', '--repo-root', str(p)], capture_output=True, text=True)
    print(f'exit={r.returncode}, stderr={r.stderr.strip()[:200]}')
"
```
Expected: exit 1 (strict mode rejects missing-frontmatter).

- [ ] **Step 4: Run cleanup phase in each repo**

For each repo, run the cleanup phase smoke test from Task 9 step 6. Expected: `True` in all 5 repos.

- [ ] **Step 5: Commit verification summary (optional)**

If verification passes, write a comment in the crackerjack CHANGELOG:

```markdown
## 0.69.5 (2026-07-26) — verification

5 consumer repos migrated to `crackerjack>=0.69.5`; all `crackerjack docs validate` runs exit 0.
```

---

## Success criteria (from spec)

- [ ] `crackerjack docs validate --json --allow-nonstandard` exits 0 in all 5 consumer repos with 0 errors.
- [ ] `crackerjack docs validate --json` (without `--allow-nonstandard`) exits 1 in any repo with non-empty `MISSING_FRONTMATTER` errors.
- [ ] `find . -name validate_document_frontmatter.py` returns 0 results in all 5 consumer repos.
- [ ] `phase_coordinator.run_documentation_cleanup_phase` succeeds with a missing-frontmatter file in the repo.
- [ ] All new tests pass.
- [ ] The bug we just fixed (2026-07-26) cannot recur because the validator logic lives in one place.
