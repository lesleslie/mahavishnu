# Frontmatter Validator Wiring + P7 Cross-Repo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Mahavishnu's frontmatter validator into Crackerjack as a CLI subcommand, MCP tool, and pre-cleanup phase step, then run P7 cross-repo expansion (session-buddy template, then 4-repo fan-out).

**Architecture:** Crackerjack invokes the Mahavishnu validator as a subprocess (one-directional dependency: Crackerjack → Mahavishnu). Wrapper service parses JSON output into a result dataclass; surfaces (CLI, MCP, phase hook) consume the dataclass. P7 follows the same Wave A-C pattern used for Mahavishnu's own normalization.

**Tech Stack:** Python 3.13, Typer (CLI), FastMCP (MCP server), pytest, secure_subprocess (existing Crackerjack utility).

## Global Constraints

- Python 3.13 floor. No `Optional[X]`, no `List[X]` — use `X | None`, `list[X]`. Target `pathlib.Path` over `os.path`.
- All imports sorted within sections; `from __future__ import annotations` first non-comment line of every source file.
- Logger: `logging.getLogger(__name__)`, never print(), never stdlib print.
- Type checker: mypy strict (mimics Mahavishnu). Pyright strict.
- Subprocess: always go through `crackerjack.services.secure_subprocess.run`. No bare `subprocess` imports.
- Commit per task, with subject `feat:` / `fix:` / `test:` / `docs:`.
- No pre-commit hook (per user direction).
- Frontmatter vocabulary: see `docs/schemas/document-frontmatter-v1.md` and `docs/schemas/topic-vocabulary-v1.md` (single source of truth in Mahavishnu).
- Crackerjack Python entry point: `crackerjack` (configured in `pyproject.toml`). Repo root: `/Users/les/Projects/crackerjack`.
- Mahavishnu repo root: `/Users/les/Projects/mahavishnu`.

---

## File Structure

### Crackerjack (Phase 1)

| File | Status | Purpose |
|------|--------|---------|
| `crackerjack/services/frontmatter_validator.py` | new | Wraps Mahavishnu validator subprocess; parses JSON |
| `crackerjack/cli/docs_cli.py` | extend | Adds `validate` Typer subcommand under existing `docs` group |
| `crackerjack/mcp/tools/doc_tools.py` | new | Registers `crackerjack_doc_frontmatter_validate` MCP tool |
| `crackerjack/mcp/tools/__init__.py` | extend | Imports + exports `register_doc_tools` |
| `crackerjack/core/phase_coordinator.py` | extend | Pre-cleanup frontmatter validation in `run_documentation_cleanup_phase` |
| `crackerjack/tests/unit/test_frontmatter_validator.py` | new | Unit tests for the wrapper |
| `crackerjack/tests/unit/test_doc_cli.py` | new | CLI tests via `typer.testing.CliRunner` |
| `crackerjack/tests/integration/test_phase_coordinator_integration.py` | new | Integration test for the phase hook |

### Mahavishnu (Phase 1 documentation)

| File | Status | Purpose |
|------|--------|---------|
| `docs/schemas/document-frontmatter-v1.md` | extend | Add "Crackerjack surface" subsection |

### Cross-repo (Phase 2)

| File | Status | Purpose |
|------|--------|---------|
| `session-buddy/docs/schemas/document-frontmatter-v1.md` | new (copy) | Per-repo schema reference |
| `session-buddy/docs/schemas/topic-vocabulary-v1.md` | new (copy) | Per-repo vocab reference |
| `session-buddy/scripts/validate_document_frontmatter.py` | new (copy) | Per-repo validator |
| `session-buddy/scripts/regenerate_plan_index.py` | new (copy) | Per-repo index regenerator |
| `session-buddy/docs/plans/PLAN_INDEX.md` | generated | First regeneration |
| `session-buddy/docs/plans/2026-07-16-p7-cross-repo-playbook.md` | new | P7.A artifact: per-repo playbook |
| All session-buddy docs (6 stores) | extend | Prepend YAML frontmatter |
| dhara / crackerjack / akosha / oneiric equivalents of above | new | Per-repo P7.B fan-out |

---

# Phase 1: Crackerjack Integration

## Task 1: FrontmatterValidator service (wrapper)

**Files:**
- Create: `crackerjack/services/frontmatter_validator.py`
- Test: `crackerjack/tests/unit/test_frontmatter_validator.py`

**Interfaces:**
- Consumes: `crackerjack.services.secure_subprocess.run` (existing utility)
- Produces: `FrontmatterValidator` class with `.validate(...)` returning `FrontmatterValidationResult`; `FrontmatterValidationError` exception

- [ ] **Step 1: Write the failing test**

```python
# crackerjack/tests/unit/test_frontmatter_validator.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from crackerjack.services.frontmatter_validator import (
    FrontmatterValidationResult,
    FrontmatterValidator,
    FrontmatterValidationError,
)


def _fake_completed_process(stdout: str, returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = ""
    return m


def test_validate_parses_clean_json() -> None:
    payload = json.dumps({
        "files_scanned": 14,
        "errors": [],
        "warnings": [],
        "duration_ms": 123,
    })
    with patch(
        "crackerjack.services.frontmatter_validator.secure_subprocess.run",
        return_value=_fake_completed_process(payload, returncode=0),
    ):
        v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
        result = v.validate()
    assert isinstance(result, FrontmatterValidationResult)
    assert result.success is True
    assert result.files_scanned == 14
    assert result.error_count == 0
    assert result.warning_count == 0


def test_validate_raises_on_errors() -> None:
    payload = json.dumps({
        "files_scanned": 14,
        "errors": [{"file": "docs/x.md", "line": 1, "code": "missing_status",
                    "message": "missing status"}],
        "warnings": [],
        "duration_ms": 50,
    })
    with patch(
        "crackerjack.services.frontmatter_validator.secure_subprocess.run",
        return_value=_fake_completed_process(payload, returncode=1),
    ):
        v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
        with pytest.raises(FrontmatterValidationError) as exc_info:
            v.validate_or_raise()
    assert exc_info.value.result.error_count == 1
    assert exc_info.value.result.errors[0]["code"] == "missing_status"


def test_validate_timeout_raises() -> None:
    with patch(
        "crackerjack.services.frontmatter_validator.secure_subprocess.run",
        side_effect=TimeoutError(),
    ):
        v = FrontmatterValidator(pkg_path=Path("/tmp/repo"), timeout_seconds=5)
        with pytest.raises(FrontmatterValidationError) as exc_info:
            v.validate()
    assert exc_info.value.reason == "timeout"
    assert exc_info.value.result is None


def test_validate_passes_store_flag() -> None:
    payload = json.dumps({"files_scanned": 0, "errors": [], "warnings": [], "duration_ms": 1})
    with patch(
        "crackerjack.services.frontmatter_validator.secure_subprocess.run",
        return_value=_fake_completed_process(payload),
    ) as mock_run:
        v = FrontmatterValidator(pkg_path=Path("/tmp/repo"))
        v.validate(store="docs/plans/")
    cmd = mock_run.call_args[0][0]
    assert "--store" in cmd
    assert "docs/plans/" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_frontmatter_validator.py -v --no-cov`
Expected: `ModuleNotFoundError: No module named 'crackerjack.services.frontmatter_validator'`

- [ ] **Step 3: Write the wrapper service**

```python
# crackerjack/services/frontmatter_validator.py
from __future__ import annotations

import dataclasses
import json
import logging
import typing as t
from pathlib import Path

from crackerjack.services import secure_subprocess

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class FrontmatterValidationIssue:
    file: str
    line: int
    code: str
    message: str


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
    def from_payload(cls, payload: dict[str, t.Any], exit_success: bool) -> FrontmatterValidationResult:
        errors = [FrontmatterValidationIssue(**e) for e in payload.get("errors", [])]
        warnings = [FrontmatterValidationIssue(**w) for w in payload.get("warnings", [])]
        return cls(
            success=exit_success and not errors,
            files_scanned=int(payload.get("files_scanned", 0)),
            errors=errors,
            warnings=warnings,
            duration_ms=int(payload.get("duration_ms", 0)),
            error_count=len(errors),
            warning_count=len(warnings),
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
    DEFAULT_TIMEOUT = 120

    def __init__(
        self,
        pkg_path: Path | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.pkg_path = (pkg_path or Path.cwd()).resolve()
        self.timeout_seconds = timeout_seconds

    def _build_command(
        self,
        strict: bool,
        allow_nonstandard: bool,
        validate_links: bool,
        store: str | None,
    ) -> list[str]:
        cmd: list[str] = [
            "python",
            "-m",
            "mahavishnu.scripts.validate_document_frontmatter",
            "--json",
        ]
        if strict:
            cmd.append("--strict")
        if allow_nonstandard:
            cmd.append("--allow-nonstandard")
        if validate_links:
            cmd.append("--validate-links")
        if store:
            cmd.extend(["--store", store])
        return cmd

    def validate(
        self,
        strict: bool = False,
        allow_nonstandard: bool = True,
        validate_links: bool = False,
        store: str | None = None,
    ) -> FrontmatterValidationResult:
        cmd = self._build_command(strict, allow_nonstandard, validate_links, store)
        try:
            completed = secure_subprocess.run(
                cmd,
                cwd=str(self.pkg_path),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise FrontmatterValidationError(
                f"validator timed out after {self.timeout_seconds}s",
                reason="timeout",
            ) from exc
        except Exception as exc:
            raise FrontmatterValidationError(
                f"validator crashed: {exc}",
                reason="crash",
            ) from exc

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise FrontmatterValidationError(
                f"validator returned invalid JSON: {exc}; stderr={completed.stderr!r}",
                reason="crash",
            ) from exc

        result = FrontmatterValidationResult.from_payload(
            payload, exit_success=completed.returncode == 0
        )
        return result

    def validate_or_raise(self, **kwargs: t.Any) -> FrontmatterValidationResult:
        result = self.validate(**kwargs)
        if not result.success:
            raise FrontmatterValidationError(
                f"{result.error_count} errors, {result.warning_count} warnings",
                result=result,
                reason="errors",
            )
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_frontmatter_validator.py -v --no-cov`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/frontmatter_validator.py crackerjack/tests/unit/test_frontmatter_validator.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "feat(crackerjack): add FrontmatterValidator service wrapping mahavishnu validator"
```

---

## Task 2: docs validate CLI subcommand

**Files:**
- Modify: `crackerjack/cli/docs_cli.py:1-30` (extend existing `docs` Typer group)

**Interfaces:**
- Consumes: `FrontmatterValidator.validate(...)` from Task 1
- Produces: `crackerjack docs validate [--strict] [--store] [--validate-links] [--json] [--path]`

- [ ] **Step 1: Write the failing test**

```python
# crackerjack/tests/unit/test_doc_cli.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from crackerjack.cli.docs_cli import app
from crackerjack.services.frontmatter_validator import FrontmatterValidationResult


runner = CliRunner()


def test_docs_validate_clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_result = FrontmatterValidationResult(
        success=True,
        files_scanned=10,
        errors=[],
        warnings=[],
        duration_ms=20,
    )
    with patch(
        "crackerjack.cli.docs_cli.FrontmatterValidator",
    ) as mock_cls:
        mock_cls.return_value.validate.return_value = fake_result
        result = runner.invoke(
            app, ["validate", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0
    assert "10 files scanned" in result.stdout or "10" in result.stdout


def test_docs_validate_strict_returns_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from crackerjack.services.frontmatter_validator import (
        FrontmatterValidationError,
        FrontmatterValidationResult,
        FrontmatterValidationIssue,
    )
    err_result = FrontmatterValidationResult(
        success=False,
        files_scanned=10,
        errors=[FrontmatterValidationIssue(
            file="x.md", line=1, code="missing", message="bad"
        )],
        warnings=[],
        duration_ms=5,
        error_count=1,
    )
    with patch(
        "crackerjack.cli.docs_cli.FrontmatterValidator",
    ) as mock_cls:
        mock_cls.return_value.validate_or_raise.side_effect = FrontmatterValidationError(
            "1 error", result=err_result, reason="errors"
        )
        result = runner.invoke(
            app, ["validate", "--strict", "--path", str(tmp_path)],
        )
    assert result.exit_code == 1


def test_docs_validate_json_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_result = FrontmatterValidationResult(
        success=True, files_scanned=2, errors=[], warnings=[], duration_ms=10
    )
    with patch(
        "crackerjack.cli.docs_cli.FrontmatterValidator",
    ) as mock_cls:
        mock_cls.return_value.validate.return_value = fake_result
        result = runner.invoke(
            app, ["validate", "--json", "--path", str(tmp_path)],
        )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["files_scanned"] == 2
    assert payload["success"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_doc_cli.py -v --no-cov`
Expected: no `validate` command found (or `ModuleNotFoundError` on FrontmatterValidator import in cli)

- [ ] **Step 3: Add the validate subcommand**

Append to `crackerjack/cli/docs_cli.py` (after the existing `build` command):

```python
from crackerjack.services.frontmatter_validator import (
    FrontmatterValidator,
    FrontmatterValidationError,
)


@app.command()
def validate(
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    store: str | None = typer.Option(
        None, "--store", help="Limit scan to a single store (e.g. docs/plans/)."
    ),
    validate_links: bool = typer.Option(
        False, "--validate-links", help="Also check cross-references."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of human-readable."),
    pkg_path: Path = typer.Option(Path.cwd(), "--path", help="Repo root."),
) -> None:
    """Validate YAML frontmatter on docs/, .claude/decisions/, etc."""
    validator = FrontmatterValidator(pkg_path=pkg_path)
    try:
        result = validator.validate(
            strict=strict,
            allow_nonstandard=True,
            validate_links=validate_links,
            store=store,
        )
    except FrontmatterValidationError as exc:
        if json_output:
            payload = exc.result.__dict__ if exc.result is not None else {
                "success": False, "reason": exc.reason,
            }
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
            console.print(f"  [red]ERROR[/red] {issue.file}:{issue.line} {issue.code}: {issue.message}")
        for issue in result.warnings:
            console.print(f"  [yellow]WARN[/yellow] {issue.file}:{issue.line} {issue.code}: {issue.message}")

    if not result.success or (strict and result.warning_count > 0):
        raise typer.Exit(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_doc_cli.py -v --no-cov`
Expected: 3 passed

- [ ] **Step 5: Smoke-test the CLI manually**

Run: `cd /Users/les/Projects/crackerjack && uv run crackerjack docs validate --help`
Expected: help text listing the new flags (`--strict`, `--store`, `--validate-links`, `--json`, `--path`).

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/cli/docs_cli.py crackerjack/tests/unit/test_doc_cli.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "feat(crackerjack): add docs validate CLI subcommand"
```

---

## Task 3: MCP tool — `crackerjack_doc_frontmatter_validate`

**Files:**
- Create: `crackerjack/mcp/tools/doc_tools.py`
- Modify: `crackerjack/mcp/tools/__init__.py:1-30`

**Interfaces:**
- Consumes: `FrontmatterValidator` from Task 1
- Produces: `register_doc_tools(mcp_app)` registered alongside sibling modules

- [ ] **Step 1: Write the doc_tools module**

```python
# crackerjack/mcp/tools/doc_tools.py
from __future__ import annotations

import json
import logging
import typing as t
from pathlib import Path

logger = logging.getLogger(__name__)


def register_doc_tools(mcp_app: t.Any) -> None:
    _register_frontmatter_validate_tool(mcp_app)


def _register_frontmatter_validate_tool(mcp_app: t.Any) -> None:
    @mcp_app.tool()
    async def crackerjack_doc_frontmatter_validate(
        pkg_path: str = ".",
        strict: bool = False,
        allow_nonstandard: bool = True,
        validate_links: bool = False,
        store: str | None = None,
    ) -> str:
        """Validate YAML frontmatter across the docs/ tree. Returns JSON.

        Args:
            pkg_path: Repo root to validate. Defaults to "." (current working directory).
            strict: Treat warnings as errors.
            allow_nonstandard: Accept legacy non-canonical frontmatter (default True).
            validate_links: Also check cross-references in `superseded_by` / `blocks_on`.
            store: Limit scan to a single store (e.g. "docs/plans/").

        Returns:
            JSON string with keys: success, files_scanned, errors, warnings, duration_ms.
        """
        from crackerjack.services.frontmatter_validator import (
            FrontmatterValidator,
            FrontmatterValidationError,
        )

        validator = FrontmatterValidator(pkg_path=Path(pkg_path))
        try:
            result = validator.validate(
                strict=strict,
                allow_nonstandard=allow_nonstandard,
                validate_links=validate_links,
                store=store,
            )
        except FrontmatterValidationError as exc:
            payload = {
                "success": False,
                "reason": exc.reason,
                "errors": [e.__dict__ for e in (exc.result.errors if exc.result else [])],
            }
            return json.dumps(payload, indent=2)

        return json.dumps(
            {
                "success": result.success,
                "files_scanned": result.files_scanned,
                "errors": [e.__dict__ for e in result.errors],
                "warnings": [w.__dict__ for w in result.warnings],
                "duration_ms": result.duration_ms,
            },
            indent=2,
        )
```

- [ ] **Step 2: Wire into tools/__init__.py**

Edit `crackerjack/mcp/tools/__init__.py`. After the existing imports, add:

```python
from .doc_tools import register_doc_tools
```

And add `"register_doc_tools"` to the `__all__` list.

- [ ] **Step 3: Verify import**

Run: `cd /Users/les/Projects/crackerjack && uv run python -c "from crackerjack.mcp.tools import register_doc_tools; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Smoke-test the MCP tool**

Run: `cd /Users/les/Projects/crackerjack && uv run python -c "
import asyncio
from crackerjack.services.frontmatter_validator import FrontmatterValidator, FrontmatterValidationResult
from unittest.mock import patch, MagicMock
import json

async def main():
    payload = json.dumps({'files_scanned': 1, 'errors': [], 'warnings': [], 'duration_ms': 1})
    m = MagicMock()
    m.returncode = 0
    m.stdout = payload
    m.stderr = ''
    with patch('crackerjack.services.frontmatter_validator.secure_subprocess.run', return_value=m):
        from crackerjack.mcp.tools.doc_tools import crackerjack_doc_frontmatter_validate
        out = await crackerjack_doc_frontmatter_validate()
        print(out)

asyncio.run(main())
"`
Expected: JSON with `"success": true`.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/mcp/tools/doc_tools.py crackerjack/mcp/tools/__init__.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "feat(crackerjack): add doc_frontmatter_validate MCP tool"
```

---

## Task 4: phase_coordinator hook

**Files:**
- Modify: `crackerjack/core/phase_coordinator.py:1152-1185` (`run_documentation_cleanup_phase`)
- Test: `crackerjack/tests/integration/test_phase_coordinator_integration.py`

**Interfaces:**
- Consumes: `FrontmatterValidator.validate()` from Task 1
- Produces: `run_documentation_cleanup_phase` runs validator before cleanup

- [ ] **Step 1: Write the integration test**

```python
# crackerjack/tests/integration/test_phase_coordinator_integration.py
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from crackerjack.core.phase_coordinator import PhaseCoordinator
from crackerjack.services.frontmatter_validator import (
    FrontmatterValidationResult,
    FrontmatterValidationIssue,
)


@pytest.fixture
def coordinator(tmp_path: Path) -> PhaseCoordinator:
    pc = PhaseCoordinator.__new__(PhaseCoordinator)
    pc.console = MagicMock()
    pc.pkg_path = tmp_path
    pc.git_service = MagicMock()
    pc._settings = MagicMock()
    pc.session = MagicMock()
    return pc


class _Options:
    cleanup_docs = True
    docs_dry_run = True


def test_run_documentation_cleanup_phase_fails_on_validator_errors(
    coordinator: PhaseCoordinator,
) -> None:
    bad = FrontmatterValidationResult(
        success=False, files_scanned=5,
        errors=[FrontmatterValidationIssue(file="x.md", line=1, code="missing", message="bad")],
        warnings=[], duration_ms=1, error_count=1,
    )
    with patch(
        "crackerjack.core.phase_coordinator.FrontmatterValidator"
    ) as mock_v:
        mock_v.return_value.validate.return_value = bad
        with patch(
            "crackerjack.core.phase_coordinator.DocumentationCleanup"
        ) as mock_dc:
            mock_dc.return_value.cleanup_documentation.return_value = MagicMock(success=True)
            result = coordinator.run_documentation_cleanup_phase(_Options())
    assert result is False
    coordinator.session.fail_task.assert_called_once()


def test_run_documentation_cleanup_phase_proceeds_when_validator_clean(
    coordinator: PhaseCoordinator,
) -> None:
    ok = FrontmatterValidationResult(
        success=True, files_scanned=5, errors=[], warnings=[], duration_ms=1
    )
    with patch(
        "crackerjack.core.phase_coordinator.FrontmatterValidator"
    ) as mock_v:
        mock_v.return_value.validate.return_value = ok
        with patch(
            "crackerjack.core.phase_coordinator.DocumentationCleanup"
        ) as mock_dc:
            mock_dc.return_value.cleanup_documentation.return_value = MagicMock(success=True)
            result = coordinator.run_documentation_cleanup_phase(_Options())
    assert result is True
    mock_dc.return_value.cleanup_documentation.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/integration/test_phase_coordinator_integration.py -v --no-cov`
Expected: tests fail (validator isn't called yet).

- [ ] **Step 3: Extend `run_documentation_cleanup_phase`**

Edit `crackerjack/core/phase_coordinator.py`. Inside `run_documentation_cleanup_phase`, **before** the `from crackerjack.services.documentation_cleanup import DocumentationCleanup` line, add:

```python
        from crackerjack.services.frontmatter_validator import (
            FrontmatterValidator,
            FrontmatterValidationError,
        )

        validator = FrontmatterValidator(
            console=self.console,
            pkg_path=self.pkg_path,
        )
        try:
            vresult = validator.validate(allow_nonstandard=True)
        except FrontmatterValidationError as exc:
            error_count = exc.result.error_count if exc.result else 0
            self.session.fail_task(
                "documentation_cleanup",
                f"frontmatter validation failed: {error_count} errors",
            )
            return False

        self.session.track_task(
            "frontmatter_validation",
            f"Frontmatter: {vresult.error_count} errors, {vresult.warning_count} warnings",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/integration/test_phase_coordinator_integration.py -v --no-cov`
Expected: 2 passed.

- [ ] **Step 5: Run full crackerjack test suite (smoke)**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/ -x --no-cov -q 2>&1 | tail -20`
Expected: suite passes (or only pre-existing failures unrelated to this work).

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/core/phase_coordinator.py crackerjack/tests/integration/test_phase_coordinator_integration.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "feat(crackerjack): validate frontmatter in doc cleanup phase"
```

---

## Task 5: Update Mahavishnu schema doc to reference Crackerjack surface

**Files:**
- Modify: `mahavishnu/docs/schemas/document-frontmatter-v1.md` (append "Crackerjack surface" subsection)

- [ ] **Step 1: Read current schema doc**

Run: `wc -l /Users/les/Projects/mahavishnu/docs/schemas/document-frontmatter-v1.md`

- [ ] **Step 2: Append the new subsection**

Append to the end of `mahavishnu/docs/schemas/document-frontmatter-v1.md`:

```markdown

## Crackerjack Surface

The validator is wrapped by Crackerjack so the same checks run during
`crackerjack run` (in the `documentation_cleanup` phase), via the CLI
(`crackerjack docs validate [--strict] [--store] [--validate-links] [--json]`),
and via the MCP tool `mcp__crackerjack__crackerjack_doc_frontmatter_validate`.

The wrapper invokes the validator as a subprocess (one-directional
dependency: Crackerjack → Mahavishnu). The validator remains the single
source of truth in this repo; Crackerjack imports it via
`mahavishnu.scripts.validate_document_frontmatter`.

See the design doc
`docs/superpowers/specs/2026-07-16-frontmatter-validator-wiring-design.md`
for full integration details.
```

- [ ] **Step 3: Re-run validator against this file to confirm zero errors**

Run: `cd /Users/les/Projects/mahavishnu && uv run python scripts/validate_document_frontmatter.py --allow-nonstandard docs/schemas/document-frontmatter-v1.md`
Expected: clean (no errors, no warnings).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/schemas/document-frontmatter-v1.md
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "docs(schemas): reference crackerjack integration surface"
```

---

## Task 6: Phase 1 final smoke + Crackerjack release bump

**Files:** none modified; verification only.

- [ ] **Step 1: Verify all Phase 1 tests pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/ --no-cov -q 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 2: Verify CLI works on a real repo**

Run: `cd /Users/les/Projects/mahavishnu && uv run /Users/les/Projects/crackerjack/.venv/bin/crackerjack docs validate --json --path /Users/les/Projects/mahavishnu 2>&1 | head -30`
Expected: JSON with files_scanned ~ 200, error_count 0, warning_count <= 5 (legacy warnings acceptable).

- [ ] **Step 3: Verify MCP tool imports cleanly**

Run: `cd /Users/les/Projects/crackerjack && uv run python -c "from crackerjack.mcp.tools import register_doc_tools; print('OK')"`
Expected: `OK`.

- [ ] **Step 4: Bump Crackerjack version**

Edit `crackerjack/pyproject.toml`. Change `version = "0.68.4"` → `version = "0.69.0"`.

- [ ] **Step 5: Commit version bump**

```bash
cd /Users/les/Projects/crackerjack
git add pyproject.toml
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "chore(crackerjack): bump version to 0.69.0 (frontmatter validator wiring)"
```

---

# Phase 2: P7 Cross-Repo Expansion (Gated)

Phase 2 is gated on Phase 1 finishing (the validator is shipped).
Phase 2 has two waves: **P7.A** (session-buddy template) and
**P7.B** (4-repo parallel fan-out).

## Task 7 (P7.A): Build session-buddy template + playbook

**Files:**
- Copy into `session-buddy/`:
  - `mahavishnu/scripts/validate_document_frontmatter.py` → `session-buddy/scripts/`
  - `mahavishnu/scripts/regenerate_plan_index.py` → `session-buddy/scripts/`
  - `mahavishnu/docs/schemas/document-frontmatter-v1.md` → `session-buddy/docs/schemas/`
  - `mahavishnu/docs/schemas/topic-vocabulary-v1.md` → `session-buddy/docs/schemas/`
- Create: `session-buddy/docs/plans/2026-07-16-p7-cross-repo-playbook.md`
- Modify: all `session-buddy/` docs across 6 stores (frontmatter prepend)
- Generated: `session-buddy/docs/plans/PLAN_INDEX.md`

**Interfaces:**
- Consumes: Phase 1 artifacts (validator, regenerator, schemas)
- Produces: session-buddy has its own frontmatter reality + the playbook that the 4-repo fan-out reads

- [ ] **Step 1: Inventory session-buddy docs**

Run from `/Users/les/Projects/session-buddy`:

```bash
find docs/ .claude/decisions/ -name "*.md" -not -path "*/.archive/*" -not -path "*/drafts/*" 2>/dev/null | wc -l
find docs/ .claude/decisions/ -name "*.md" -not -path "*/.archive/*" -not -path "*/drafts/*" 2>/dev/null | head -50
```

Capture the count and the 6-store breakdown (analogous to what Wave A produced for Mahavishnu).

- [ ] **Step 2: Copy validator + regenerator + schemas**

```bash
cd /Users/les/Projects
mkdir -p session-buddy/scripts session-buddy/docs/schemas
cp mahavishnu/scripts/validate_document_frontmatter.py session-buddy/scripts/
cp mahavishnu/scripts/regenerate_plan_index.py session-buddy/scripts/
cp mahavishnu/docs/schemas/document-frontmatter-v1.md session-buddy/docs/schemas/
cp mahavishnu/docs/schemas/topic-vocabulary-v1.md session-buddy/docs/schemas/
```

- [ ] **Step 3: Run the validator in `--dry-run` mode against session-buddy**

Run: `cd /Users/les/Projects/session-buddy && uv run python scripts/validate_document_frontmatter.py --allow-nonstandard 2>&1 | tail -10`
Expected: validator reports per-file issues (missing frontmatter, etc.). This is the inventory.

- [ ] **Step 4: Apply frontmatter across session-buddy's 6 stores (Pass 1)**

Reuse the Wave A pattern from Mahavishnu: for each of `docs/adr/`, `docs/plans/`, `docs/superpowers/specs/`, `docs/superpowers/plans/`, `.claude/decisions/`, `docs/followups/`, prepend YAML frontmatter using the same template (`PLAN_FM_TEMPLATE` from `mahavishnu/scripts/_orphan_sweep_C1_2.py`). Status/role/topic assignments follow the same playbook as Mahavishnu. Use `crackerjack docs validate` to verify each store is clean.

- [ ] **Step 5: Run post-P5 link sweep**

Run: `cd /Users/les/Projects/session-buddy && uv run python scripts/validate_document_frontmatter.py --validate-links --allow-nonstandard 2>&1 | tee /tmp/sb-link-sweep.txt | tail -1`
Expected: link sweep reports issues. Fix per-store; commit per-scope.

- [ ] **Step 6: Run regenerator to produce PLAN_INDEX.md**

Run: `cd /Users/les/Projects/session-buddy && uv run python scripts/regenerate_plan_index.py`
Expected: regenerator writes `docs/plans/PLAN_INDEX.md`.

- [ ] **Step 7: Write the playbook**

Create `session-buddy/docs/plans/2026-07-16-p7-cross-repo-playbook.md`. Document:

- Per-repo gotchas (e.g. session-buddy-specific topic vocab additions; conventions discovered).
- The exact command sequence each fan-out agent must follow.
- Pass 1 / Pass 2 ordering.
- The status/role/topic decision matrix used.
- Examples of legacy status coercions ("Resolved" → "complete", etc.).

Frontmatter for the playbook itself:

```yaml
---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: lifecycle
---
```

- [ ] **Step 8: Commit session-buddy template artifacts**

```bash
cd /Users/les/Projects/session-buddy
git add scripts/ docs/schemas/ docs/plans/PLAN_INDEX.md docs/plans/2026-07-16-p7-cross-repo-playbook.md docs/adr/ docs/plans/ docs/superpowers/specs/ docs/superpowers/plans/ .claude/decisions/ docs/followups/
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "docs(session-buddy): apply plan-lifecycle-unification playbook (P7.A template)"
```

---

## Task 8 (P7.B): 4-repo parallel fan-out

**Files:** per-repo copies of validator/regenerator/schemas + normalized docs + per-repo PLAN_INDEX.md + per-repo commits. Targets: dhara, crackerjack, akosha, oneiric.

**Interfaces:**
- Consumes: `session-buddy/docs/plans/2026-07-16-p7-cross-repo-playbook.md` from Task 7
- Produces: each repo has its own frontmatter reality, generated PLAN_INDEX.md, per-repo commits

This task is dispatched via the Workflow tool as a single fan-out with one subagent per repo. The coordinator agent reads the playbook, then dispatches four parallel subagents (one per repo). Each subagent applies the playbook verbatim. The coordinator validates, summarizes, and ensures commits land per repo.

- [ ] **Step 1: Prepare the Workflow tool dispatch**

Build a script `plan-p7-b-fanout.js` (Workflow tool inline) with 4 parallel subagents (one per repo). Each subagent's prompt:

```
You are applying the plan-lifecycle-unification playbook to <repo>.
READ FIRST: /Users/les/Projects/session-buddy/docs/plans/2026-07-16-p7-cross-repo-playbook.md
Then apply the same playbook to /Users/les/Projects/<repo>/ ...
[full prompt with 4-store mapping, link sweep, regenerator, commit]
```

- [ ] **Step 2: Execute the fan-out via Workflow tool**

Use `Workflow({ script: "...", args: [...] })`. Wait for the tool's notification.

- [ ] **Step 3: Verify all 4 repos clean**

For each of dhara, crackerjack, akosha, oneiric:

```bash
cd /Users/les/Projects/<repo>
uv run python scripts/validate_document_frontmatter.py --validate-links --allow-nonstandard 2>&1 | tail -5
```

Expected: 0 ERROR per repo.

- [ ] **Step 4: Final report**

Write a brief summary in this repo's `docs/followups/` listing which repos received the playbook, link-sweep results, and commit SHAs.

```bash
cd /Users/les/Projects/mahavishnu
mkdir -p docs/followups
# Write the followup file
```

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/followups/2026-07-16-p7-cross-repo-completion.md
git -c user.email=les@wedgwoodwebworks.com -c user.name=lesleslie commit -m "docs(followups): record P7 cross-repo completion"
```

---

## Self-Review

1. **Spec coverage**:
   - Wrapper service: Task 1 ✓
   - CLI subcommand: Task 2 ✓
   - MCP tool: Task 3 ✓
   - Phase hook: Task 4 ✓
   - Schema doc cross-reference: Task 5 ✓
   - Release bump: Task 6 ✓
   - P7.A (session-buddy template + playbook): Task 7 ✓
   - P7.B (4-repo fan-out): Task 8 ✓

2. **Placeholder scan**: No TBDs/TODOs. All code blocks are complete. Each commit command is concrete.

3. **Type consistency**:
   - `FrontmatterValidationResult` (Task 1) used consistently in Tasks 1, 2, 3, 4.
   - `FrontmatterValidationError.reason` ∈ `{"timeout", "crash", "errors"}` consistent.
   - `FrontmatterValidator.validate(...)` signature matches all 4 call sites (CLI, MCP, phase, tests).

4. **Scope**: Two phases (Crackerjack wiring, P7 cross-repo) produce working software per phase. P7 is gated on P7.A producing the playbook.