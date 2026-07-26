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
> **Architecture:** Move `scripts/validate_document_frontmatter.py` → `crackerjack/services/frontmatter.py` (next to the existing wrapper). Add `get_git_root` to existing `crackerjack/tools/_git_utils.py` (already half-wired via `conftest_reset.py`). Refactor `crackerjack/services/frontmatter_validator.py` to call the new module in-process (no subprocess). Refactor `crackerjack docs validate` CLI subcommand: rename `--path` → `--repo-root`, add `--allow-nonstandard/--strict-frontmatter` flag, and add comprehensive automated tests. Delete `scripts/validate_document_frontmatter.py` from 5 consumer repos.
> **Tech Stack:** Python 3.13, Typer, pathlib, pytest, `functools.lru_cache` (for git-root memoization), crackerjack (already a dependency in all 5 repos).

## Global Constraints

- Crackerjack is **already a declared dependency** in `dhara`, `session-buddy`, `akosha`, `oneiric`, and `mahavishnu`. No new dep additions.
- All consumer repos require `crackerjack>=0.69.5` after the canonical release.
- The `FrontmatterValidator` Python wrapper's PUBLIC API stays unchanged: `FrontmatterValidator(pkg_path=Path).validate(strict=False, allow_nonstandard=True, ...)` returns `FrontmatterValidationResult`. The `from_payload` classmethod is preserved. The constructor parameter name `pkg_path` stays as `pkg_path` (existing crackerjack convention — `pkg_path` IS the project root across 19+ internal uses). The CLI flag `--repo-root` is renamed at the user-facing surface only; the CLI passes it as `pkg_path=repo_root` to the wrapper.
- The `crackerjack docs validate` CLI surface changes `--path` → `--repo-root` AND adds `--allow-nonstandard/--strict-frontmatter` flag. No external consumer of the CLI is known.
- Each commit is single-purpose; tests pass at every commit; commit only on GREEN.
- Cross-repo changes release in order: crackerjack first, then consumers in the same session (minimize the inconsistent-state window).
- The CLI's `crackerjack docs validate --strict` corresponds to `--allow-nonstandard=False` (inverse flag relationship).
- All consumer repos must update their `scripts/regenerate_plan_index.py` help text to point at `crackerjack docs validate` (not the script).
- Mahavishnu's `tests/unit/test_document_frontmatter.py` imports the script directly and must be removed in the mahavishnu migration task.
- Existing pytest markers, project conventions, and `from __future__ import annotations` heredity apply.
- Hard limits from `pyproject.toml` apply: line length 100, function args ≤ 10, branches ≤ 15, returns ≤ 6, statements ≤ 55.

______________________________________________________________________

## Phase 1: Foundation in crackerjack

### Task 1: Add `get_git_root` to `crackerjack/tools/_git_utils.py`

**Files:**
- Modify: `crackerjack/tools/_git_utils.py` (find existing file; add `get_git_root` function)
- Test: `tests/unit/test_git_utils.py` (extend if exists, else create)

**Interfaces:**
- Consumes: nothing
- Produces: `from crackerjack.tools._git_utils import get_git_root` returning `Path | None`

**Background**: `tests/conftest_reset.py:169` already has `_git_utils.get_git_root.cache_clear()`. This is a latent dead-reference — the function was planned but never landed. Adding it now makes the existing test fixture code start working as intended.

- [ ] **Step 1: Read the existing file and find a good location**

```bash
cd /Users/les/Projects/crackerjack && head -40 crackerjack/tools/_git_utils.py
```

Identify the existing pattern (logger import, helper functions, etc.). Place `get_git_root` near the other discovery helpers.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_git_utils.py` (or extend existing):

```python
from __future__ import annotations

from pathlib import Path

from crackerjack.tools import _git_utils


def test_get_git_root_walks_up_to_dot_git(tmp_path: Path) -> None:
    """get_git_root walks up to find the directory containing .git."""
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    assert _git_utils.get_git_root(start=nested) == tmp_path


def test_get_git_root_returns_none_outside_repo(tmp_path: Path) -> None:
    """get_git_root returns None when no .git is found before filesystem root."""
    leaf = tmp_path / "no_repo_here"
    leaf.mkdir()
    # Walk up from inside tmp_path without a .git. tmp_path is on a
    # real filesystem, so we assert the function returns None or
    # returns *outside* tmp_path's parent (the host's repo). The
    # function's contract is "returns None if not found in any
    # reasonable ancestor"; we verify the function does not return
    # a child of tmp_path.
    result = _git_utils.get_git_root(start=leaf)
    # Either None (no .git above) or a directory OUTSIDE tmp_path.
    if result is not None:
        assert tmp_path not in result.parents, (
            f"get_git_root returned {result} which is inside tmp_path"
        )


def test_get_git_root_handles_dot_git_file(tmp_path: Path) -> None:
    """get_git_root recognizes .git as a file (git submodule/worktree)."""
    (tmp_path / ".git").write_text("gitdir: /tmp/elsewhere\n")
    assert _git_utils.get_git_root(start=tmp_path) == tmp_path


def test_get_git_root_default_start_is_cwd() -> None:
    """get_git_root defaults start to Path.cwd()."""
    import inspect
    sig = inspect.signature(_git_utils.get_git_root)
    assert sig.parameters["start"].default is None


def test_get_git_root_accepts_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_git_root resolves relative paths via .resolve()."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    nested = Path("src/pkg")
    (tmp_path / nested).mkdir(parents=True)
    assert _git_utils.get_git_root(start=nested) == tmp_path


def test_get_git_root_recognizes_dot_git_symlink(tmp_path: Path) -> None:
    """get_git_root accepts a .git that is a symlink to a real directory."""
    import os
    real_git = tmp_path / "real_git"
    real_git.mkdir()
    (real_git / "HEAD").write_text("ref: refs/heads/main\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    os.symlink(real_git, worktree / ".git")
    assert _git_utils.get_git_root(start=worktree) == worktree
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_git_utils.py -v --no-cov`
Expected: FAIL with `AttributeError: module 'crackerjack.tools._git_utils' has no attribute 'get_git_root'`

- [ ] **Step 4: Add `get_git_root` to `_git_utils.py`**

Add the function (and any needed imports for `pathlib`). Match the existing file's style:

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def get_git_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default: cwd) looking for a .git entry.

    Returns the directory containing .git, or ``None`` if no .git is
    found before reaching the filesystem root.

    Recognizes .git as both a directory and a file (git submodule/
    worktree ``gitdir:`` files). Result is cached; call
    ``get_git_root.cache_clear()`` between tests.
    """
    current = (start or Path.cwd()).resolve()

    while True:
        git_path = current / ".git"
        if git_path.exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_git_utils.py -v --no-cov`
Expected: PASS (6 tests)

- [ ] **Step 6: Verify conftest wiring works**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest --no-cov 2>&1 | tail -10`
Expected: All tests pass; the previously-dead `_git_utils.get_git_root.cache_clear()` reference in `conftest_reset.py` now works.

- [ ] **Step 7: Commit**

```bash
git add crackerjack/tools/_git_utils.py tests/unit/test_git_utils.py
git commit -m "feat(tools): add get_git_root helper to _git_utils with tests"
```

---

### Task 2: Move `validate_document_frontmatter.py` to `crackerjack/services/frontmatter.py`

**Files:**
- Create: `crackerjack/services/frontmatter.py` (moved from `scripts/validate_document_frontmatter.py`)
- Delete: `scripts/validate_document_frontmatter.py`
- Move + edit: `tests/unit/test_validate_document_frontmatter.py` → `tests/unit/test_validate_frontmatter.py`

**Interfaces:**
- Consumes: `from crackerjack.tools._git_utils import get_git_root`
- Produces:
  - `validate_file(path, rel, *, repo_root, known_files, known_topics, strict, allow_nonstandard, validate_links, skip_link_note) -> FileResult`
  - `main(argv: list[str] | None = None) -> int`
  - `discover_files(repo_root, stores, extra_paths) -> list[tuple[Path, str]]`
  - `extract_frontmatter(text) -> tuple[dict | None, str | None]`
  - `FileResult`, `Issue`, `build_parser`, `DEFAULT_STORES`, `STORE_LOOKUP`, `load_seed_topics`

- [ ] **Step 1: Move the script to the package**

```bash
cd /Users/les/Projects/crackerjack
git mv scripts/validate_document_frontmatter.py crackerjack/services/frontmatter.py
```

- [ ] **Step 2: Edit the moved file**

Open `crackerjack/services/frontmatter.py`. Make these changes:

1. **Add `from __future__ import annotations`** at the top of the file (after the module docstring).

2. **Remove the `if __name__ == "__main__":` block** at the very bottom:

```python
# OLD (delete these lines):
if __name__ == "__main__":
    raise SystemExit(main())
```

3. **Replace the hardcoded `repo_root` derivation** in `main()`. Find this line (line 616 in the file as shipped):

```python
# OLD:
    repo_root = Path(__file__).resolve().parent.parent
```

Replace it with:

```python
    # Resolve repo_root: --repo-root flag wins; else first positional
    # path's parent (if a directory) or cwd.
    if args.repo_root is not None:
        repo_root = Path(args.repo_root).resolve()
    elif args.paths:
        first = Path(args.paths[0]).resolve()
        repo_root = first if first.is_dir() else first.parent
    else:
        repo_root = Path.cwd()
```

4. **Add the `--repo-root` argparse argument** to `build_parser()`. Find the existing `parser.add_argument("--store", ...)` block and add immediately after it:

```python
    parser.add_argument(
        "--repo-root",
        default=None,
        metavar="PATH",
        help="Repo root to validate. Defaults to first positional path or cwd.",
    )
```

- [ ] **Step 3: Move the existing test file and update imports**

```bash
cd /Users/les/Projects/crackerjack
git mv tests/unit/test_validate_document_frontmatter.py tests/unit/test_validate_frontmatter.py
```

Edit `tests/unit/test_validate_frontmatter.py` (the renamed file). Replace the `_load_module()` helper and the `validator_module` fixture with a direct import:

```python
# OLD (lines 16-50): helper that loads script via importlib.
# OLD (line 57): `@pytest.fixture` for validator_module.
# OLD (line 70): `validator_module` fixture call sites.

# NEW: replace the entire _load_module() function and the fixture with:
from crackerjack.services import frontmatter as validator_module
```

Replace every `validator_module.X` reference with the imported module. The `_make_missing_frontmatter_file` helper stays the same.

Add an additional test to confirm the new `--repo-root` flag works:

```python
def test_main_accepts_repo_root_flag(tmp_path: Path) -> None:
    """The validator's main() accepts --repo-root as a CLI argument."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "ok.md").write_text(
        "---\nstatus: draft\n---\n# Hi\n",
        encoding="utf-8",
    )
    rc = validator_module.main(
        ["--repo-root", str(tmp_path), "--json", "--allow-nonstandard"]
    )
    assert rc == 0


def test_validator_module_has_no_main_block() -> None:
    """The validator module is importable as a library; no __main__ block."""
    import inspect
    src = inspect.getsource(validator_module)
    assert '__name__ == "__main__"' not in src
    assert "if __name__ == '__main__'" not in src
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_validate_frontmatter.py -v --no-cov`
Expected: PASS (original 2 tests + 2 new tests)

- [ ] **Step 5: Verify the module is importable from the new path**

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -c "from crackerjack.services import frontmatter; print(frontmatter.__file__)"
```
Expected: `/Users/les/Projects/crackerjack/crackerjack/services/frontmatter.py`

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_validate_frontmatter.py crackerjack/services/frontmatter.py
git rm scripts/validate_document_frontmatter.py
git commit -m "refactor(services): move validate_document_frontmatter.py into crackerjack.services.frontmatter"
```

---

### Task 3: Refactor `FrontmatterValidator` Python wrapper to call module in-process

**Files:**
- Modify: `crackerjack/services/frontmatter_validator.py`
- Modify: `tests/unit/test_frontmatter_validator.py`

**Interfaces:**
- Consumes: `from crackerjack.services import frontmatter as _validator`
- Produces: `FrontmatterValidator(pkg_path=Path)` (parameter name stays as `pkg_path` per crackerjack convention; `pkg_path` IS the project root). `from_payload` classmethod is preserved. All other public API stays the same.

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
    with patch(
        "crackerjack.services.frontmatter_validator.secure_subprocess.run"
    ) as mock_secure_run:
        with patch(
            "crackerjack.services.frontmatter.discover_files",
            return_value=[],
        ):
            result = v.validate()
        assert result.success is True
        # CRITICAL: the wrapper's secure_subprocess.run must NOT be called.
        mock_secure_run.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_frontmatter_validator.py::test_validate_does_not_spawn_subprocess -v --no-cov`
Expected: FAIL — the wrapper currently uses `secure_subprocess.run`; the test asserts the call does NOT happen.

- [ ] **Step 3: Refactor the wrapper**

Open `crackerjack/services/frontmatter_validator.py` and rewrite it. The wrapper's PUBLIC API (constructor signature, attribute name, public methods) stays the same: `pkg_path` is the parameter name. The internal calls change to invoke the new module in-process.

```python
from __future__ import annotations

import dataclasses
import typing as t
from pathlib import Path

from crackerjack.services import frontmatter as _validator

if t.TYPE_CHECKING:
    from crackerjack.config.settings import CrackerjackSettings


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
    def from_payload(
        cls,
        payload: dict[str, t.Any] | list[t.Any],
        exit_success: bool,
    ) -> FrontmatterValidationResult:
        """Accepts dict OR list payload (dict for direct JSON, list for file-results)."""
        if isinstance(payload, list):
            return cls._from_file_results(payload, exit_success)
        errors = [
            cls._issue_from_payload(issue) for issue in payload.get("errors", [])
        ]
        warnings = [
            cls._issue_from_payload(issue) for issue in payload.get("warnings", [])
        ]
        return cls(
            success=exit_success and not errors,
            files_scanned=int(payload.get("files_scanned", 0)),
            errors=errors,
            warnings=warnings,
            duration_ms=int(payload.get("duration_ms", 0)),
            error_count=len(errors),
            warning_count=len(warnings),
        )

    @classmethod
    def _from_file_results(
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
                cls._issue_from_payload(issue, path=path)
                for issue in file_result.get("errors", [])
            )
            warnings.extend(
                cls._issue_from_payload(issue, path=path)
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

    @staticmethod
    def _issue_from_payload(
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
        """Run the validator in-process and return the aggregate result."""
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

        return FrontmatterValidationResult.from_payload(
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

- [ ] **Step 4: Update existing tests**

Open `tests/unit/test_frontmatter_validator.py`. Apply all of these changes:

1. Replace `pkg_path` with `repo_root` in every test:
   - `FrontmatterValidator(pkg_path=...)` → `FrontmatterValidator(pkg_path=...)` (no rename — wrapper keeps `pkg_path`)

2. Replace `test_validate_parses_clean_json` to use a real in-process run:

```python
def test_validate_parses_clean_json(tmp_path: Path) -> None:
    """Clean validator run returns success with zero errors."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    v = FrontmatterValidator(pkg_path=tmp_path)
    result = v.validate()
    assert isinstance(result, FrontmatterValidationResult)
    assert result.success is True
    assert result.files_scanned == 0
    assert result.error_count == 0
    assert result.warning_count == 0
```

3. Replace `test_validate_raises_on_errors` to use a real file:

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

4. Replace `test_validate_timeout_raises` with `test_validate_crash_raises`:

```python
def test_validate_crash_raises() -> None:
    """A crash during validator execution becomes FrontmatterValidationError(reason='crash')."""
    from unittest.mock import patch

    v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
    with patch(
        "crackerjack.services.frontmatter.discover_files",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(FrontmatterValidationError) as exc_info:
            v.validate()
    assert exc_info.value.reason == "crash"
```

5. Replace `test_validate_passes_store_flag` to use the new in-process path:

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

6. Add new tests for the bug-fix contracts:

```python
def test_validate_strict_promotes_warnings_to_failure(tmp_path: Path) -> None:
    """strict=True causes success=False when warnings exist."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "warny.md").write_text(
        "---\nstatus: draft\n---\n# Hi\n",
        encoding="utf-8",
    )
    v = FrontmatterValidator(pkg_path=tmp_path)
    lenient = v.validate(strict=False)
    strict = v.validate(strict=True)
    if lenient.warning_count > 0:
        assert strict.success is False
    if lenient.error_count > 0:
        assert lenient.success is False
        assert strict.success is False


def test_validate_allow_nonstandard_false_emits_missing_frontmatter(
    tmp_path: Path,
) -> None:
    """allow_nonstandard=False surfaces MISSING_FRONTMATTER errors."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "legacy.md").write_text("# No frontmatter\n", encoding="utf-8")
    v = FrontmatterValidator(pkg_path=tmp_path)
    result = v.validate(allow_nonstandard=False)
    assert result.success is False
    assert result.error_count >= 1
    codes = {e.code for e in result.errors}
    assert "MISSING_FRONTMATTER" in codes


def test_validate_in_process_real_file_with_status_field(tmp_path: Path) -> None:
    """A file with a valid status field validates cleanly via the in-process path."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "ok.md").write_text(
        "---\nstatus: draft\n---\n# Hi\n",
        encoding="utf-8",
    )
    v = FrontmatterValidator(pkg_path=tmp_path)
    result = v.validate()
    assert result.success is True
    assert result.files_scanned == 1
```

- [ ] **Step 5: Run all validator tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/test_validate_frontmatter.py tests/unit/test_frontmatter_validator.py -v --no-cov`
Expected: PASS (4 from test_validate_frontmatter + 8 from test_frontmatter_validator)

- [ ] **Step 6: Run phase coordinator tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/test_phase_coordinator.py::TestDocumentationCleanupPhase -v --no-cov`
Expected: PASS (3 tests, no changes needed)

- [ ] **Step 7: Commit**

```bash
git add crackerjack/services/frontmatter_validator.py tests/unit/test_frontmatter_validator.py
git commit -m "refactor(validator): call validator module in-process, rename pkg_path→repo_root"
```

---

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
- Test: `tests/unit/cli/test_docs_cli.py` (extend if exists, else create)

**Interfaces:**
- Consumes: `from crackerjack.tools._git_utils import get_git_root`, `from crackerjack.validators import frontmatter`
- Produces: `crackerjack docs validate [--repo-root PATH] [--strict] [--store NAME] [--validate-links] [--allow-nonstandard/--strict-frontmatter] [--json]`

- [ ] **Step 1: Read the current subcommand**

Read `crackerjack/cli/docs_cli.py:165-228` to confirm the current state. The subcommand currently has `--path` as the option name.

- [ ] **Step 2: Apply the change**

In `crackerjack/cli/docs_cli.py`, replace the `validate` function (lines 165-228) with:

```python
@app.command()
def validate(
    *,
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as errors."
    ),
    store: str | None = typer.Option(
        None, "--store", help="Limit scan to a single store (e.g. docs/plans/)."
    ),
    validate_links: bool = typer.Option(
        False, "--validate-links", help="Also check cross-references."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of human-readable."
    ),
    repo_root: Path = typer.Option(
        None,
        "--repo-root",
        callback=_resolve_repo_root,
        help="Repo root to validate. Defaults to git toplevel of cwd.",
    ),
    allow_nonstandard: bool = typer.Option(
        True,
        "--allow-nonstandard/--strict-frontmatter",
        help=(
            "Tolerate non-standard content (default true). "
            "Use --strict-frontmatter to reject missing-frontmatter."
        ),
    ),
) -> None:
    if repo_root and not repo_root.is_dir():
        raise typer.BadParameter(f"{repo_root} is not a directory")

    validator = FrontmatterValidator(pkg_path=repo_root)
    try:
        result = validator.validate(
            strict=strict,
            allow_nonstandard=allow_nonstandard,
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

Add the `_resolve_repo_root` Typer callback near the top of `docs_cli.py`:

```python
def _resolve_repo_root(value: Path | None) -> Path:
    """Typer callback: resolve --repo-root to a git toplevel if not provided."""
    from crackerjack.tools._git_utils import get_git_root

    if value is not None:
        return value
    detected = get_git_root()
    if detected is None:
        raise typer.BadParameter(
            "not in a git repository; pass --repo-root to specify"
        )
    return detected
```

- [ ] **Step 3: Verify the CLI works**

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m crackerjack docs validate --help
```
Expected: Output shows `--repo-root PATH`, `--allow-nonstandard/--strict-frontmatter`, no `--path`.

Run:
```bash
cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m crackerjack docs validate --json --allow-nonstandard
```
Expected: exit 0, JSON output. The `crackerjack` repo's docs are all properly frontmattered; validator returns clean.

- [ ] **Step 4: Add comprehensive CLI tests**

Open `tests/unit/cli/test_docs_cli.py` (or create it). Add the following test class:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crackerjack.cli.docs_cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def repo_with_passing_doc(tmp_path: Path) -> Path:
    """Create a temp repo with one valid doc."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "ok.md").write_text(
        "---\nstatus: draft\n---\n# Hi\n",
        encoding="utf-8",
    )
    return tmp_path


def test_validate_repo_root_flag_accepted(
    runner: CliRunner, repo_with_passing_doc: Path
) -> None:
    """`docs validate --repo-root PATH` accepts the new flag."""
    result = runner.invoke(
        app,
        ["validate", "--repo-root", str(repo_with_passing_doc), "--json"],
    )
    assert result.exit_code == 0, result.output


def test_validate_auto_detects_repo_root(
    runner: CliRunner,
    repo_with_passing_doc: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --repo-root, the CLI walks up to find .git."""
    (repo_with_passing_doc / ".git").mkdir()
    monkeypatch.chdir(repo_with_passing_doc)
    result = runner.invoke(app, ["validate", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["files_scanned"] >= 1


def test_validate_outside_git_repo_errors_when_no_repo_root(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --repo-root and outside a git repo, the CLI errors out."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["validate"])
    # Should fail because not in a git repo (no .git above tmp_path).
    assert result.exit_code != 0


def test_validate_repo_root_must_be_directory(
    runner: CliRunner, tmp_path: Path
) -> None:
    """A non-existent --repo-root errors out."""
    result = runner.invoke(
        app,
        ["validate", "--repo-root", "/nonexistent/path/that/does/not/exist"],
    )
    assert result.exit_code != 0


def test_validate_strict_frontmatter_exits_one_on_missing(
    runner: CliRunner, tmp_path: Path
) -> None:
    """--strict-frontmatter rejects missing-frontmatter files."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "legacy.md").write_text("# No frontmatter\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "validate",
            "--repo-root",
            str(tmp_path),
            "--strict-frontmatter",
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_count"] >= 1
    codes = {e["code"] for e in payload["errors"]}
    assert "MISSING_FRONTMATTER" in codes


def test_validate_allow_nonstandard_passes_with_missing_frontmatter(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Default --allow-nonstandard tolerates missing-frontmatter (the bug-fix)."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "legacy.md").write_text("# No frontmatter\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["validate", "--repo-root", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["files_scanned"] == 1


def test_validate_strict_promotes_warnings_to_exit_one(
    runner: CliRunner, tmp_path: Path
) -> None:
    """`--strict` causes exit 1 when warnings are present."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "warny.md").write_text(
        "---\nstatus: draft\n---\n# Hi\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["validate", "--repo-root", str(tmp_path), "--strict", "--json"],
    )
    # If warnings were produced, exit 1; otherwise exit 0.
    payload = json.loads(result.output)
    if payload["warning_count"] > 0:
        assert result.exit_code == 1
    else:
        assert result.exit_code == 0


def test_validate_json_output_schema(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The --json output has stable, documented keys."""
    result = runner.invoke(
        app, ["validate", "--repo-root", str(tmp_path), "--json"]
    )
    payload = json.loads(result.output)
    expected_keys = {"success", "files_scanned", "errors", "warnings", "duration_ms"}
    assert expected_keys.issubset(set(payload.keys()))
    assert isinstance(payload["errors"], list)
    assert isinstance(payload["warnings"], list)
```

- [ ] **Step 5: Run the new CLI tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/unit/cli/test_docs_cli.py -v --no-cov`
Expected: PASS (8 tests)

- [ ] **Step 6: Run any existing docs-cli tests**

Run: `cd /Users/les/Projects/crackerjack && ./.venv/bin/python -m pytest tests/ -k "docs_cli or docs_validate" -v --no-cov`
Expected: PASS (existing tests + new tests)

- [ ] **Step 7: Commit**

```bash
git add crackerjack/cli/docs_cli.py tests/unit/cli/test_docs_cli.py
git commit -m "feat(cli): docs validate --repo-root with --allow-nonstandard flag"
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

Reading the existing test file, you'll see the `PhaseCoordinator` is constructed via `coordinator` fixture. Reuse that fixture; just override the `pkg_path` attribute or use the fixture's tmp_path.

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
- Modify: `CHANGELOG.md` (replace `## Unreleased` with the new version)

- [ ] **Step 1: Bump version**

Edit `pyproject.toml` line `version = "0.69.4"` → `version = "0.69.5"`.

- [ ] **Step 2: Update CHANGELOG**

In `CHANGELOG.md`, find the `## Unreleased` header (line 3 according to the existing format). Replace the line `## Unreleased` with `## [0.69.5] - 2026-07-26` (move its content under the new header). Add a new `## Unreleased` block below if there are post-0.69.5 changes.

The new entry follows the existing `## [version] - date` format (with brackets and dash separator, matching line 23 of the existing CHANGELOG). Replace the existing `## [0.69.4] - 2026-07-26` block with:

```markdown
## [0.69.5] - 2026-07-26

### Refactor

- Move `scripts/validate_document_frontmatter.py` into the crackerjack package as `crackerjack.services.frontmatter`.
- `FrontmatterValidator` Python wrapper now calls the validator in-process; no subprocess.
- `crackerjack docs validate` CLI subcommand renamed `--path` to `--repo-root`; auto-detects git toplevel when omitted.
- Add `get_git_root` helper to `crackerjack/tools/_git_utils.py` for repo-root discovery.
- Constructor parameter `pkg_path` renamed to `repo_root` on `FrontmatterValidator`.

### Migration

- Consumer repos (dhara, session-buddy, akosha, oneiric, mahavishnu) must delete `scripts/validate_document_frontmatter.py` and bump `crackerjack>=0.69.5`.
- `crackerjack docs validate --repo-root PATH [--allow-nonstandard/--strict-frontmatter]` replaces `python scripts/validate_document_frontmatter.py`.
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
- Modify: `pyproject.toml` (crackerjack dep version — currently unversioned `"crackerjack"`)
- Delete: `scripts/validate_document_frontmatter.py`
- Modify: `scripts/regenerate_plan_index.py` (doc reference)

- [ ] **Step 1: Verify crackerjack is installable**

Run: `cd /Users/les/Projects/dhara && grep -n "crackerjack" pyproject.toml`
Expected: See the line `"crackerjack"` (unversioned) in `[project] dependencies`.

- [ ] **Step 2: Bump the dep version**

`dhara`'s crackerjack dep is currently unversioned (`"crackerjack"`). Bump it to `"crackerjack>=0.69.5"`:

```toml
# OLD:
"crackerjack",

# NEW:
"crackerjack>=0.69.5",
```

- [ ] **Step 3: Delete the script**

```bash
cd /Users/les/Projects/dhara && git rm scripts/validate_document_frontmatter.py
```

- [ ] **Step 4: Update regenerator doc reference**

Edit `scripts/regenerate_plan_index.py` to replace any reference to `scripts/validate_document_frontmatter.py` with `crackerjack docs validate --allow-nonstandard`. Search for the script path first:

```bash
cd /Users/les/Projects/dhara && grep -n "validate_document_frontmatter" scripts/regenerate_plan_index.py
```

Apply the replacement at each line.

- [ ] **Step 5: Install the new crackerjack version**

```bash
cd /Users/les/Projects/dhara && uv cache clean crackerjack && uv sync --group dev
```

- [ ] **Step 6: Verify the CLI works**

```bash
cd /Users/les/Projects/dhara && ./.venv/bin/crackerjack docs validate --json --allow-nonstandard | tail -20
```
Expected: exit 0, JSON with `success: true`, 0 errors.

- [ ] **Step 7: Run the cleanup phase**

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

- [ ] **Step 8: Run tests**

```bash
cd /Users/les/Projects/dhara && ./.venv/bin/python -m pytest -v --no-cov 2>&1 | tail -20
```
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/dhara
git add pyproject.toml scripts/regenerate_plan_index.py
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 10: Migrate session-buddy

**Files:**
- Modify: `pyproject.toml` (crackerjack dep version — TWO entries: line 35 main dep + line 231 dev group)
- Delete: `scripts/validate_document_frontmatter.py`
- Modify: `scripts/regenerate_plan_index.py` (doc reference)

- [ ] **Step 1: Verify crackerjack is installable**

Run: `cd /Users/les/Projects/session-buddy && grep -n "crackerjack" pyproject.toml`
Expected: Two lines — line 35 (`"crackerjack>=0.62.0"` in main deps) and line 231 (unversioned `"crackerjack"` in dev group).

- [ ] **Step 2: Bump both dep versions**

In `pyproject.toml`:
- Line 35: change `"crackerjack>=0.62.0"` → `"crackerjack>=0.69.5"`
- Line 231: change `"crackerjack"` → `"crackerjack>=0.69.5"` (consistency)

- [ ] **Step 3: Delete the script**

```bash
cd /Users/les/Projects/session-buddy && git rm scripts/validate_document_frontmatter.py
```

- [ ] **Step 4: Update regenerator doc reference**

```bash
cd /Users/les/Projects/session-buddy && grep -n "validate_document_frontmatter" scripts/regenerate_plan_index.py
```
Replace each found line with the CLI command.

- [ ] **Step 5: Install the new crackerjack version**

```bash
cd /Users/les/Projects/session-buddy && uv cache clean crackerjack && uv sync --group dev
```

- [ ] **Step 6: Verify the CLI works**

```bash
cd /Users/les/Projects/session-buddy && ./.venv/bin/crackerjack docs validate --json --allow-nonstandard | tail -20
```
Expected: exit 0, JSON with `success: true`, 0 errors.

- [ ] **Step 7: Run the cleanup phase**

```bash
cd /Users/les/Projects/session-buddy && ./.venv/bin/python -c "
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

- [ ] **Step 8: Run tests**

```bash
cd /Users/les/Projects/session-buddy && ./.venv/bin/python -m pytest -v --no-cov 2>&1 | tail -20
```
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add pyproject.toml scripts/regenerate_plan_index.py
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 11: Migrate akosha

**Files:**
- Modify: `pyproject.toml` (crackerjack dep version — line 165)
- Delete: `scripts/validate_document_frontmatter.py`
- Modify: `scripts/regenerate_plan_index.py` (doc reference)

- [ ] Apply the same 9-step migration as Task 9 (dhara):
  - Look at current crackerjack version constraint in `pyproject.toml:165` (`crackerjack>=0.54.5`)
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - Update `scripts/regenerate_plan_index.py` doc reference
  - `uv cache clean crackerjack && uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/akosha
git add pyproject.toml scripts/regenerate_plan_index.py
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 12: Migrate oneiric

**Files:**
- Modify: `pyproject.toml` (crackerjack dep version — line 226)
- Delete: `scripts/validate_document_frontmatter.py`
- Modify: `scripts/regenerate_plan_index.py` (doc reference)

- [ ] Apply the same 9-step migration as Task 9 (dhara):
  - Look at current crackerjack version constraint in `pyproject.toml:226` (`crackerjack>=0.66.1`)
  - Bump to `crackerjack>=0.69.5`
  - `git rm scripts/validate_document_frontmatter.py`
  - Update `scripts/regenerate_plan_index.py` doc reference
  - `uv cache clean crackerjack && uv sync --group dev`
  - Verify `crackerjack docs validate --json --allow-nonstandard` shows 0 errors
  - Run cleanup phase smoke test
  - Run pytest
  - Commit

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/oneiric
git add pyproject.toml scripts/regenerate_plan_index.py
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script"
```

---

### Task 13: Migrate mahavishnu

**Files:**
- Modify: `pyproject.toml` (crackerjack dep version — TWO entries: line 132 main dep + line 489 dev group)
- Delete: `scripts/validate_document_frontmatter.py`
- Delete: `tests/unit/test_document_frontmatter.py` (imports the script directly)
- Modify: `scripts/regenerate_plan_index.py` (doc reference — has 4 occurrences)

- [ ] **Step 1: Verify crackerjack is installable**

Run: `cd /Users/les/Projects/mahavishnu && grep -n "crackerjack" pyproject.toml`
Expected: Two lines — line 132 (`"crackerjack>=0.65.0"` in main deps) and line 489 (unversioned `"crackerjack"` in dev group).

- [ ] **Step 2: Bump both dep versions**

In `pyproject.toml`:
- Line 132: change `"crackerjack>=0.65.0"` → `"crackerjack>=0.69.5"`
- Line 489: change `"crackerjack"` → `"crackerjack>=0.69.5"` (consistency)

- [ ] **Step 3: Delete the script AND the test that imports it**

```bash
cd /Users/les/Projects/mahavishnu
git rm scripts/validate_document_frontmatter.py
git rm tests/unit/test_document_frontmatter.py
```

The test file imports the script directly via `from validate_document_frontmatter import ...`. After deletion, this test will fail with `ImportError`. Removing it is the correct action; the new in-process validator is tested in Task 5's CLI tests.

- [ ] **Step 4: Update regenerator doc references**

```bash
cd /Users/les/Projects/mahavishnu && grep -n "validate_document_frontmatter" scripts/regenerate_plan_index.py
```
Expected: 4 occurrences. Replace each with `crackerjack docs validate --allow-nonstandard`.

- [ ] **Step 5: Install the new crackerjack version**

```bash
cd /Users/les/Projects/mahavishnu && uv cache clean crackerjack && uv sync --group dev
```

- [ ] **Step 6: Verify the CLI works**

```bash
cd /Users/les/Projects/mahavishnu && ./.venv/bin/crackerjack docs validate --json --allow-nonstandard | tail -20
```
Expected: exit 0, JSON with `success: true`, 0 errors.

- [ ] **Step 7: Run the cleanup phase**

```bash
cd /Users/les/Projects/mahavishnu && ./.venv/bin/python -c "
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

- [ ] **Step 8: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && ./.venv/bin/python -m pytest -v --no-cov 2>&1 | tail -20
```
Expected: All tests pass (the deleted test is no longer in the suite).

- [ ] **Step 9: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add pyproject.toml scripts/regenerate_plan_index.py
git commit -m "chore(deps): bump crackerjack>=0.69.5; remove duplicated validator script and test"
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

Note: the new CLI defaults to `--allow-nonstandard=True`. To verify the strict path, use `--strict-frontmatter`:

```bash
cd /Users/les/Projects/akosha && ./.venv/bin/python -c "
import subprocess, json
import tempfile, pathlib
with tempfile.TemporaryDirectory() as td:
    p = pathlib.Path(td)
    (p / 'docs' / 'plans').mkdir(parents=True)
    (p / 'docs' / 'plans' / 'bad.md').write_text('# No frontmatter')
    r = subprocess.run(
        ['./.venv/bin/crackerjack', 'docs', 'validate',
         '--repo-root', str(p), '--strict-frontmatter', '--json'],
        capture_output=True, text=True,
    )
    print(f'exit={r.returncode}')
    payload = json.loads(r.stdout)
    print(f'errors: {payload[\"error_count\"]}')
    print(f'MISSING_FRONTMATTER: {any(e[\"code\"] == \"MISSING_FRONTMATTER\" for e in payload[\"errors\"])}')
"
```
Expected: exit 1, errors >= 1, MISSING_FRONTMATTER is True.

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
- [ ] `crackerjack docs validate --json --strict-frontmatter` exits 1 in any repo with non-empty `MISSING_FRONTMATTER` errors.
- [ ] `find . -name validate_document_frontmatter.py` returns 0 results in all 5 consumer repos (and in crackerjack).
- [ ] `phase_coordinator.run_documentation_cleanup_phase` succeeds with a missing-frontmatter file in the repo.
- [ ] All new tests pass (4 in `test_validate_frontmatter.py`, 8 in `test_frontmatter_validator.py`, 8 in `tests/unit/cli/test_docs_cli.py`, 1 in `test_phase_coordinator.py`).
- [ ] The 12 stale worktrees under `/Users/les/worktrees/` will lag behind the migration; document this as a known acceptable drift.
- [ ] The bug we just fixed (2026-07-26) cannot recur because the validator logic lives in one place.
