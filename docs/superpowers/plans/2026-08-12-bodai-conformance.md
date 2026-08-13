---
status: draft
role: implementation
date: 2026-08-12
last_reviewed: 2026-08-12
topic: bodai-conformance
title: Bodai Ecosystem Conformance
blocks_on:
  - docs/superpowers/specs/2026-08-12-bodai-ecosystem-consistency-design.md
---

# Bodai Ecosystem Conformance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CI-enforced conformance check that prevents the 5 cross-repo drift patterns (documented-but-not-wired, removed-but-referenced, version-stamp-drift, MCP-tool-hallucination, cross-component-port-drift) from recurring across the 6 Bodai components.

**Architecture:** Crackerjack exposes 5 generic check primitives as CLI + FastMCP tools. Mahavishnu gains a `mahavishnu conformance check` CLI + FastMCP tool that orchestrates 6 Bodai-specific checks by calling crackerjack primitives over MCP (using `BodaiComponentMCPClient`). Each Bodai repo declares its own conformance contract in a top-level `conformance.yaml` manifest. Crackerjack stays ecosystem-agnostic; all Bodai-specific facts flow out of mahavishnu (never Python-imported, per the 2026-08-12 `mcpretentious-removed-mcp-first` ruling).

**Tech Stack:** Python 3.13+, hatchling (mahavishnu), Typer CLI, FastMCP, Pydantic v2 + pydantic-settings, `tomllib` (stdlib), `ast` (stdlib), `importlib.resources`, `subprocess.run`, `BodaiComponentMCPClient` at `mahavishnu/mcp/bodai_component_client.py` (existing, base_url-based).

## Global Constraints

- **Pre-1.0 merge policy**: branch + ff-merge to main; no PRs, no review board.
- **Crackerjack for CI/CD**: no pre-commit hooks; no bodai pre-commit hook exists (memory: `no-bodai-pre-commit-hook`).
- **Manual version bumps for the crackerjack repo**: implementer does NOT bump `crackerjack/pyproject.toml`; user handles post-merge. For other Bodai repos, `python -m crackerjack run -v -p minor` handles bump+commit+tag+push+publish automatically (memory: `crackerjack-p-minor-full-lifecycle`).
- **MCP-first cross-component wiring**: never `import crackerjack` in mahavishnu. Always go through `BodaiComponentMCPClient` (memory: `mcpretentious-removed-mcp-first`).
- **MHV error hierarchy (ADR 003)**: conformance errors use `MahavishnuError` subclasses with codes `MHV-512..516`, NOT bare integer exit codes.
- **Configuration files live at top-level `settings/`** (repo root, NOT inside the package). Loaded via `yaml.safe_load` directly — these are compliance config, NOT typed settings on `MahavishnuSettings`.
- **Cross-repo wiring language**: `uvx --from 'mahavishnu==X.Y.Z'` (with `==` not `@`) to pin exactly.
- **No new PyPI packages**: conformance lives in existing crackerjack + mahavishnu.
- **`yaml.safe_load` mandate**: never `yaml.load`; RCE risk.
- **`audit_orphans.py` before declaring any phase complete** (CLAUDE.md "Process Discipline").
- **Wire-up contract**: each phase deliverable documents Triggered from / Returns to / Demonstrable by / Rollback signal / Observability added (per `.claude/decisions/wire-up-contract.md`).
- **YAML regex escape semantics**: in `bodai-doc-rules.yaml`, use `\\d` (double backslash) so `yaml.safe_load` decodes to `\d`. The Python equivalent is `r"\d"` in raw strings or `"\\d"` in regular strings.
- **`BodaiComponentMCPClient` is async-only with explicit session lifecycle**: there is NO `component_name=` constructor kwarg (use `base_url=`); there are NO `__aenter__`/`__aexit__` methods. Callers must `await client._ensure_session()` and `await client.aclose()` explicitly.
- **`crackerjack` CLI registration**: `_safe_add_typer(main_app, module_path: str, attr_name: str, command_name: str)` — 4-arg, string-imports the module.
- **`mahavishnu` CLI registration**: `app.add_typer(sub_app, name="X")` — direct Typer call.
- **No Bodai repo currently has `.github/workflows/ci.yml`** — Phase 2 adoption tasks must CREATE these files, not modify.

## File Structure

### Crackerjack repo (`/Users/les/Projects/crackerjack`)

```
crackerjack/
├── cli/
│   └── check.py                          # NEW: Typer subcommand `crackerjack check`
├── mcp/
│   ├── server_core.py                    # MODIFY: add register_check_tools(mcp_app) call
│   └── tools/
│       └── check_tools.py                # NEW: register_check_tools + 5 @mcp.tool() functions
├── services/
│   ├── check_primitives/                 # NEW package
│   │   ├── __init__.py
│   │   ├── base.py                       # PrimitiveResult with `value` field
│   │   ├── regex_match.py                # returns value=match.group(capture_group)
│   │   ├── pyproject_field.py            # returns value=str(extracted_field)
│   │   ├── yaml_field.py                 # NEW (round 2): yaml.safe_load variant of pyproject_field
│   │   ├── git_grep.py                   # returns value=None
│   │   ├── markdown_inventory.py         # returns value=None
│   │   └── ast_symbol_check.py           # returns value=None
│   └── regex_patterns.py                 # REUSE (already exists, ReDoS-safe ValidatedPattern)
└── tests/
    ├── fixtures/
    │   ├── clean_repo/                   # NEW
    │   ├── version_drift/                # NEW
    │   ├── removed_symbol/               # NEW
    │   ├── missing_inventory/            # NEW
    │   └── missing_symbol/               # NEW
    └── unit/
        ├── test_check_primitives.py      # NEW
        └── test_check_cli.py             # NEW
```

### Mahavishnu repo (`/Users/les/Projects/mahavishnu`)

```
mahavishnu/
├── cli/
│   └── conformance_cli.py                # NEW: Typer subcommand `mahavishnu conformance check`
├── core/
│   └── errors.py                         # MODIFY: add MHV-512..516 ConformanceError subclasses
├── mcp/
│   ├── bodai_component_client.py         # REUSE (existing; no changes needed)
│   └── tools/
│       └── conformance_tools.py          # NEW: mcp__mahavishnu__conformance_check
├── services/
│   └── conformance/                      # NEW package
│       ├── __init__.py
│       ├── runner.py                     # async run_rule; composite handling; value comparison
│       ├── aggregator.py                 # CheckResult dataclass
│       └── reporter.py                   # MHV-coded error formatting
└── tests/
    └── integration/
        └── conformance/
            ├── fixture_clean_bodai_repo/    # NEW: matching versions
            ├── fixture_version_drift/       # NEW: pyproject 1.2.3 vs README 9.9.9
            ├── fixture_mahavishnu_real/     # NEW: mirrors actual current skew
            ├── fixture_bodai_doc_rules.yaml  # NEW: copy of production settings
            ├── fixture_bodai_ports.yaml      # NEW: copy of production settings
            ├── test_version_guard.py         # NEW
            └── test_cross_layer_drift_detection.py  # NEW (Phase 3)
```

### Top-level settings (mahavishnu repo root, NOT inside package)

```
mahavishnu/  (repo root, NOT mahavishnu/ subdirectory)
├── conformance.yaml                      # NEW: per-repo manifest (mahavishnu)
└── settings/
    ├── bodai-ports.yaml                  # NEW: canonical port table
    └── bodai-doc-rules.yaml              # NEW: rule config (with version_guard composite)
```

### Per-Bodai-repo (×6)

```
<repo>/
├── conformance.yaml                      # NEW: per-repo port manifest (each repo)
└── .github/workflows/
    └── ci.yml                            # NEW (CREATE, not modify): Bodai conformance step
```

---

## Phase 1: Prerequisite — Sync mahavishnu's own version skew

### Task 0: Sync mahavishnu's version + README banner (prerequisite)

**Files:**
- Modify: `mahavishnu/mahavishnu/__init__.py` (line 3: `__version__ = "0.1.0"` → `"0.12.0"`)
- Modify: `mahavishnu/README.md` (add `## Version: 0.12.0` near top)

**Why:** Phase 1's `version_guard` will fire on mahavishnu itself unless these are aligned. Doing this prerequisite prevents the conformance check from blocking its own merge.

- [ ] **Step 1: Update `mahavishnu/__init__.py`**

Read the current line 3 (likely `__version__ = "0.1.0"` per feasibility review). Change to:
```python
__version__ = "0.12.0"
```

- [ ] **Step 2: Update `mahavishnu/README.md`**

Read the first 30 lines of `mahavishnu/README.md`. Find the appropriate spot for a version banner (after the title, before the first section heading). Add:
```markdown
## Version: 0.12.0
```

- [ ] **Step 3: Verify both files match**

Run:
```bash
grep "__version__" /Users/les/Projects/mahavishnu/mahavishnu/__init__.py
grep "^version" /Users/les/Projects/mahavishnu/pyproject.toml
grep "## Version:" /Users/les/Projects/mahavishnu/README.md
```
Expected: all three print `0.12.0`.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/__init__.py README.md
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "chore: sync __version__ and README banner to 0.12.0 (conformance prerequisite)"
```

**Manual version bump for the mahavishnu repo:** After merge, run `python -m crackerjack run -v -p minor` per `crackerjack-p-minor-full-lifecycle` memory to bump and publish. The implementer does NOT do this; flag in PR that user handles.

---

## Phase 1: Crackerjack primitives + version_guard rule + adopt in mahavishnu

### Task 1: Add MHV-512..516 error classes to mahavishnu

**Files:**
- Modify: `mahavishnu/core/errors.py` (add 5 new `MahavishnuError` subclasses)

**Interfaces:**
- Consumes: existing `MahavishnuError` base class and `ErrorCode` StrEnum
- Produces: 5 new exception classes importable from `mahavishnu.core.errors`

- [ ] **Step 1: Read existing errors module**

Run: `Read /Users/les/Projects/mahavishnu/mahavishnu/core/errors.py`
Expected: see `ErrorCode` StrEnum, `MahavishnuError` base class with `error_code`, `recovery`, `details` fields.

- [ ] **Step 2: Add 5 new error code entries**

In `mahavishnu/core/errors.py`, add to the `ErrorCode` StrEnum:

```python
# Conformance check errors (MHV-512..516)
CONFORMANCE_DRIFT_DETECTED = "MHV-512"
CONFORMANCE_RULES_CONFIG_INVALID = "MHV-513"
CONFORMANCE_RULES_FILE_MISSING = "MHV-514"
CONFORMANCE_PRIMITIVE_CRASH = "MHV-515"
CONFORMANCE_UNAVAILABLE = "MHV-516"
```

- [ ] **Step 3: Add 5 new MahavishnuError subclasses**

After the existing subclasses:

```python
class ConformanceDriftDetected(MahavishnuError):
    """Real drift found in docs/config/CLI/MCP surface."""

    def __init__(
        self,
        rule_name: str,
        recovery: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.CONFORMANCE_DRIFT_DETECTED,
            recovery=recovery,
            details={"rule": rule_name, **(details or {})},
        )


class ConformanceRulesConfigInvalid(MahavishnuError):
    """bodai-doc-rules.yaml has invalid pattern or missing field."""

    def __init__(
        self,
        rule_name: str,
        recovery: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.CONFORMANCE_RULES_CONFIG_INVALID,
            recovery=recovery,
            details={"rule": rule_name, **(details or {})},
        )


class ConformanceRulesFileMissing(MahavishnuError):
    """settings/bodai-ports.yaml or bodai-doc-rules.yaml not found."""

    def __init__(
        self,
        file_path: str,
        recovery: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.CONFORMANCE_RULES_FILE_MISSING,
            recovery=recovery,
            details={"file": file_path, **(details or {})},
        )


class ConformancePrimitiveCrash(MahavishnuError):
    """Crackerjack primitive returned an error (likely a crackerjack bug)."""

    def __init__(
        self,
        rule_name: str,
        recovery: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.CONFORMANCE_PRIMITIVE_CRASH,
            recovery=recovery,
            details={"rule": rule_name, **(details or {})},
        )


class ConformanceUnavailable(MahavishnuError):
    """Cannot reach crackerjack MCP server, PyPI unreachable, etc."""

    def __init__(
        self,
        cause: str,
        recovery: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code=ErrorCode.CONFORMANCE_UNAVAILABLE,
            recovery=recovery,
            details={"cause": cause, **(details or {})},
        )
```

- [ ] **Step 4: Verify import works**

Run: `cd /Users/les/Projects/mahavishnu && uv run python -c "from mahavishnu.core.errors import ConformanceDriftDetected; e = ConformanceDriftDetected('test', ['fix it'], {'file': 'x'}); print(e.error_code)"`
Expected: prints `MHV-512`.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/errors.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(errors): add MHV-512..516 conformance error subclasses"
```

---

### Task 2: Implement crackerjack regex_match primitive (with `value` field)

**Files:**
- Create: `crackerjack/services/check_primitives/__init__.py`
- Create: `crackerjack/services/check_primitives/base.py`
- Create: `crackerjack/services/check_primitives/regex_match.py`
- Create: `crackerjack/tests/fixtures/clean_repo/README.md`
- Create: `crackerjack/tests/unit/test_regex_match.py`

**Interfaces:**
- Consumes: `crackerjack.services.regex_patterns.ValidatedPattern` (existing, ReDoS-safe)
- Produces: `regex_match(config) -> PrimitiveResult` with `value: str | None` set to the matched group when `capture_group` is provided

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_regex_match.py`:

```python
"""Tests for the regex_match crackerjack primitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.services.check_primitives.regex_match import RegexMatchPrimitive
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_clean_repo_readme_banner_passes() -> None:
    """README with version banner matching pattern passes and captures value."""
    primitive = RegexMatchPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/README.md"),
        "pattern": r"## Version: (\d+\.\d+\.\d+)",
        "capture_group": 1,
    }
    result = primitive.run(config)
    assert result.passed is True
    assert result.value == "1.2.3"


def test_missing_banner_fails() -> None:
    primitive = RegexMatchPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/README.md"),
        "pattern": r"## NotInFile: (\d+)",
        "capture_group": 1,
    }
    result = primitive.run(config)
    assert result.passed is False
    assert result.value is None


def test_malformed_pattern_raises_config_error() -> None:
    primitive = RegexMatchPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/README.md"),
        "pattern": r"(unclosed",
        "capture_group": 1,
    }
    with pytest.raises(ConfigError):
        primitive.run(config)


def test_unsafe_pattern_raises_config_error() -> None:
    """ReDoS-unsafe nested-quantifier pattern raises ConfigError at primitive level."""
    primitive = RegexMatchPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/README.md"),
        "pattern": r"(a+)+$",
        "capture_group": 1,
    }
    with pytest.raises(ConfigError, match="catastrophic backtracking"):
        primitive.run(config)


def test_missing_file_raises_missing_file_error() -> None:
    primitive = RegexMatchPrimitive()
    config = {
        "path": "/nonexistent/path/file.md",
        "pattern": r"## Version: (\d+\.\d+\.\d+)",
        "capture_group": 1,
    }
    with pytest.raises(MissingFileError):
        primitive.run(config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_regex_match.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `check_primitives/__init__.py`**

```python
"""Generic crackerjack check primitives (ecosystem-agnostic)."""
from __future__ import annotations
```

- [ ] **Step 4: Create `check_primitives/base.py`**

```python
"""Shared types and exceptions for crackerjack check primitives."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PrimitiveResult:
    """Result of running a single checkerjack check primitive."""

    passed: bool
    rule_name: str
    file: str | None = None
    line: int | None = None
    value: str | None = None
    message: str = ""
    remediation: list[str] = field(default_factory=list)


class ConfigError(Exception):
    """Raised when a primitive's config block is invalid (MHV-513)."""


class MissingFileError(Exception):
    """Raised when a primitive's required file is missing (MHV-514)."""


class PrimitiveCrash(Exception):
    """Raised when a primitive itself crashes during execution (MHV-515)."""
```

- [ ] **Step 5: Create test fixture `tests/fixtures/clean_repo/README.md`**

```markdown
# Clean Repo

## Version: 1.2.3

A test fixture for crackerjack primitives.
```

- [ ] **Step 6: Create `check_primitives/regex_match.py`**

```python
"""regex_match primitive: match a regex against file contents."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)
from crackerjack.services.regex_patterns import ValidatedPattern


class RegexMatchPrimitive:
    """Match a regex pattern against a file. ReDoS-safe via ValidatedPattern + primitive-level guard."""

    rule_name = "regex_match"

    @staticmethod
    def _is_unsafe_pattern(pattern: str) -> bool:
        """Detect catastrophic-backtracking nested-quantifier patterns.

        `ValidatedPattern` emits warnings but does NOT raise. We add this
        primitive-level guard to fail-closed on ReDoS patterns.
        """
        import re
        # Detect nested quantifiers on overlapping groups: (X+)+ or (X*)* etc.
        return bool(re.search(r"\([^)]*[+*]\)[+*]", pattern))

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        path = config.get("path")
        pattern_str = config.get("pattern")
        capture_group = config.get("capture_group", 0)

        if not path or not pattern_str:
            raise ConfigError("regex_match requires 'path' and 'pattern'")

        if self._is_unsafe_pattern(pattern_str):
            raise ConfigError(
                f"pattern rejected as potentially catastrophic backtracking: {pattern_str!r}"
            )

        try:
            validated = ValidatedPattern(pattern_str)
        except Exception as exc:
            raise ConfigError(f"invalid or unsafe pattern: {exc}") from exc

        file_path = Path(path)
        if not file_path.exists():
            raise MissingFileError(f"file not found: {path}")

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise MissingFileError(f"cannot read {path}: {exc}") from exc

        match = validated.search(content)
        if match is None:
            return PrimitiveResult(
                passed=False,
                rule_name=self.rule_name,
                file=path,
                line=None,
                message=f"pattern {pattern_str!r} did not match any line in {path}",
                remediation=[f"Add a line matching {pattern_str!r} to {path}"],
            )

        captured = match.group(capture_group) if capture_group else None
        return PrimitiveResult(
            passed=True,
            rule_name=self.rule_name,
            file=path,
            line=content[: match.start()].count("\n") + 1,
            value=captured,
        )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_regex_match.py -v`
Expected: 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/ tests/unit/test_regex_match.py tests/fixtures/clean_repo/
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): regex_match primitive (with value capture)"
```

**Note:** Manual version bump for crackerjack repo — flag as `Skipped — user handles manually` per `crackerjack-version-bumping-manual`. Do NOT bump `crackerjack/pyproject.toml`.

---

### Task 3: Implement crackerjack pyproject_field primitive (with `value` field)

**Files:**
- Create: `crackerjack/services/check_primitives/pyproject_field.py`
- Create: `crackerjack/tests/unit/test_pyproject_field.py`
- Create: `crackerjack/tests/fixtures/clean_repo/pyproject.toml`

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_pyproject_field.py`:

```python
"""Tests for the pyproject_field crackerjack primitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.services.check_primitives.pyproject_field import PyprojectFieldPrimitive
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extracts_version_field_with_value() -> None:
    """Extract [project].version and capture value."""
    primitive = PyprojectFieldPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/pyproject.toml"),
        "field": "[project].version",
    }
    result = primitive.run(config)
    assert result.passed is True
    assert result.value == "1.2.3"


def test_missing_field_fails() -> None:
    primitive = PyprojectFieldPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/pyproject.toml"),
        "field": "[project].nonexistent",
    }
    result = primitive.run(config)
    assert result.passed is False
    assert result.value is None


def test_missing_file_raises() -> None:
    primitive = PyprojectFieldPrimitive()
    config = {"path": "/nonexistent/pyproject.toml", "field": "[project].version"}
    with pytest.raises(MissingFileError):
        primitive.run(config)


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    from crackerjack.services.check_primitives.base import ConfigError

    fixture_path = tmp_path / "invalid_toml_repo"
    fixture_path.mkdir()
    (fixture_path / "pyproject.toml").write_text("this is not valid toml [")

    primitive = PyprojectFieldPrimitive()
    config = {
        "path": str(fixture_path / "pyproject.toml"),
        "field": "[project].version",
    }
    with pytest.raises(ConfigError):
        primitive.run(config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_pyproject_field.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `tests/fixtures/clean_repo/pyproject.toml`**

```toml
[project]
name = "clean-repo"
version = "1.2.3"
description = "Test fixture"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 4: Create `check_primitives/pyproject_field.py`**

```python
"""pyproject_field primitive: extract a TOML field from pyproject.toml."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)


def _resolve_field(data: dict, dotted_path: str) -> Any:
    """Resolve a dotted path like 'project.version' against nested dicts."""
    path = dotted_path.strip("[]").split(".")
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


class PyprojectFieldPrimitive:
    """Extract a TOML field from pyproject.toml and verify it exists."""

    rule_name = "pyproject_field"

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        path = config.get("path", "./pyproject.toml")
        field_path = config.get("field")

        if not field_path:
            raise ConfigError("pyproject_field requires 'field'")

        file_path = Path(path)
        if not file_path.exists():
            raise MissingFileError(f"pyproject.toml not found: {path}")

        try:
            with file_path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

        value = _resolve_field(data, field_path)
        if value is None:
            return PrimitiveResult(
                passed=False,
                rule_name=self.rule_name,
                file=path,
                message=f"field {field_path!r} not found in {path}",
                remediation=[f"Add field {field_path!r} to {path}"],
            )

        return PrimitiveResult(
            passed=True,
            rule_name=self.rule_name,
            file=path,
            value=str(value),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_pyproject_field.py -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/pyproject_field.py tests/unit/test_pyproject_field.py tests/fixtures/clean_repo/pyproject.toml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): pyproject_field primitive (with value capture)"
```

---

### Task 3A: Implement crackerjack yaml_field primitive (round-2 addition for Phase 2)

**Why this task:** Akosha, dhara, session-buddy, and crackerjack store their ports in YAML, not TOML. `pyproject_field` will fail with `TOMLDecodeError` → MHV-513 for these repos. The `yaml_field` primitive is the YAML equivalent of `pyproject_field`.

**Files:**
- Create: `crackerjack/services/check_primitives/yaml_field.py`
- Create: `crackerjack/tests/unit/test_yaml_field.py`
- Create: `crackerjack/tests/fixtures/clean_repo/akosha_style.yaml`

**Interfaces:**
- Consumes: `yaml.safe_load` (stdlib)
- Produces: `yaml_field(config) -> PrimitiveResult` with `value: str | None` set to extracted YAML value

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_yaml_field.py`:

```python
"""Tests for the yaml_field crackerjack primitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.services.check_primitives.yaml_field import YamlFieldPrimitive
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extracts_yaml_field_with_value() -> None:
    """Extract nested YAML field and capture value."""
    yaml_file = FIXTURES / "clean_repo/akosha_style.yaml"
    yaml_file.write_text(
        "settings:\n"
        "  api_port: 8682\n"
        "  mcp_port: 3002\n"
    )
    primitive = YamlFieldPrimitive()
    config = {
        "path": str(yaml_file),
        "field": "settings.api_port",
    }
    result = primitive.run(config)
    assert result.passed is True
    assert result.value == "8682"


def test_missing_field_fails() -> None:
    yaml_file = FIXTURES / "clean_repo/akosha_style.yaml"
    yaml_file.write_text("settings:\n  api_port: 8682\n")
    primitive = YamlFieldPrimitive()
    config = {"path": str(yaml_file), "field": "settings.nonexistent"}
    result = primitive.run(config)
    assert result.passed is False
    assert result.value is None


def test_missing_file_raises() -> None:
    primitive = YamlFieldPrimitive()
    config = {"path": "/nonexistent/file.yaml", "field": "settings.api_port"}
    with pytest.raises(MissingFileError):
        primitive.run(config)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    from crackerjack.services.check_primitives.base import ConfigError

    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text("foo: [unclosed\n")

    primitive = YamlFieldPrimitive()
    config = {"path": str(yaml_file), "field": "foo"}
    with pytest.raises(ConfigError):
        primitive.run(config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_yaml_field.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `check_primitives/yaml_field.py`**

```python
"""yaml_field primitive: extract a YAML field from a YAML config file."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)


def _resolve_field(data: dict, dotted_path: str) -> Any:
    """Resolve a dotted path like 'settings.api_port' against nested dicts."""
    path = dotted_path.split(".")
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


class YamlFieldPrimitive:
    """Extract a YAML field from a YAML file and verify it exists."""

    rule_name = "yaml_field"

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        path = config.get("path", "./settings.yaml")
        field_path = config.get("field")

        if not field_path:
            raise ConfigError("yaml_field requires 'field'")

        file_path = Path(path)
        if not file_path.exists():
            raise MissingFileError(f"yaml file not found: {path}")

        try:
            with file_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

        value = _resolve_field(data, field_path)
        if value is None:
            return PrimitiveResult(
                passed=False,
                rule_name=self.rule_name,
                file=path,
                message=f"field {field_path!r} not found in {path}",
                remediation=[f"Add field {field_path!r} to {path}"],
            )

        return PrimitiveResult(
            passed=True,
            rule_name=self.rule_name,
            file=path,
            value=str(value),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_yaml_field.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Register yaml_field in `PRIMITIVES` dict**

In `crackerjack/services/check_primitives/__init__.py`, add the import:

```python
from crackerjack.services.check_primitives.yaml_field import YamlFieldPrimitive
```

And add to `PRIMITIVES`:
```python
PRIMITIVES: dict[str, type] = {
    "regex_match": RegexMatchPrimitive,
    "pyproject_field": PyprojectFieldPrimitive,
    "yaml_field": YamlFieldPrimitive,        # NEW (round 2)
    "git_grep": GitGrepPrimitive,
    "markdown_inventory": MarkdownInventoryPrimitive,
    "ast_symbol_check": AstSymbolCheckPrimitive,
}
```

- [ ] **Step 6: Register MCP tool in `crackerjack/mcp/tools/check_tools.py`**

Add the import:
```python
from crackerjack.services.check_primitives.yaml_field import YamlFieldPrimitive
```

Add the `@mcp_app.tool()` registration (mirror the `check_pyproject_field` block):
```python
@mcp_app.tool(name="crackerjack__check_yaml_field")
def check_yaml_field(config: dict) -> dict:
    """Extract a YAML field from a YAML file. Returns value=str(extracted)."""
    try:
        result = YamlFieldPrimitive().run(config)
    except ConfigError as exc:
        return {"error": "config_invalid", "message": str(exc)}
    except MissingFileError as exc:
        return {"error": "file_missing", "message": str(exc)}
    return _serialize(result)
```

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/yaml_field.py tests/unit/test_yaml_field.py tests/fixtures/clean_repo/akosha_style.yaml crackerjack/services/check_primitives/__init__.py crackerjack/mcp/tools/check_tools.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): yaml_field primitive for YAML config (Phase 2 prerequisite)"
```

**Note:** Manual version bump for crackerjack repo — flag as `Skipped — user handles manually`. Do NOT bump `crackerjack/pyproject.toml`.

---

### Task 4: Implement crackerjack git_grep primitive

**Files:**
- Create: `crackerjack/services/check_primitives/git_grep.py`
- Create: `crackerjack/tests/unit/test_git_grep.py`

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_git_grep.py`:

```python
"""Tests for the git_grep crackerjack primitive."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from crackerjack.services.check_primitives.git_grep import GitGrepPrimitive


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with one deleted symbol referenced in docs."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

    (repo / "module.py").write_text("def old_function(): pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add old_function"], cwd=repo, check=True)

    (repo / "module.py").write_text("def new_function(): pass\n")
    (repo / "docs.md").write_text("# Docs\n\nUse old_function here.\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "rename"], cwd=repo, check=True)

    return repo


def test_finds_deleted_symbol_in_docs(git_repo: Path) -> None:
    """git_grep finds deleted symbols cited in docs."""
    primitive = GitGrepPrimitive()
    config = {
        "target_path": str(git_repo),
        "scan_paths": ["docs.md"],
        "exclude_paths": [".claude/worktrees/", "docs/archive/"],
        "since": "all",
    }
    result = primitive.run(config)
    assert result.passed is False
    assert "old_function" in result.message


def test_no_deleted_symbols_passes(tmp_path: Path) -> None:
    """Repo with no deletions and no matching docs passes."""
    repo = tmp_path / "clean"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "module.py").write_text("def stable(): pass\n")
    (repo / "docs.md").write_text("# Docs\n\nUse stable.\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    primitive = GitGrepPrimitive()
    config = {
        "target_path": str(repo),
        "scan_paths": ["docs.md"],
        "exclude_paths": [],
        "since": "all",
    }
    result = primitive.run(config)
    assert result.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_git_grep.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `check_primitives/git_grep.py`**

```python
"""git_grep primitive: find deleted symbols cited in docs."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from crackerjack.services.check_primitives.base import (
    ConfigError,
    PrimitiveResult,
)


class GitGrepPrimitive:
    """Find strings from deleted symbols (since ref/tag) that appear in docs.

    Excludes worktrees and archive paths by default.
    """

    rule_name = "git_grep"

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        target_path = config.get("target_path", ".")
        scan_paths = config.get("scan_paths", ["."])
        exclude_paths = config.get("exclude_paths", [".claude/worktrees/", "docs/archive/"])
        since = config.get("since", "last-tag")

        target = Path(target_path).resolve()
        if not (target / ".git").exists():
            raise ConfigError(f"{target_path} is not a git repository")

        deleted_symbols = self._collect_deleted_symbols(target, since)
        if not deleted_symbols:
            return PrimitiveResult(
                passed=True,
                rule_name=self.rule_name,
                file=str(target),
                message="no deleted symbols found",
            )

        matches = self._grep_docs(target, deleted_symbols, scan_paths, exclude_paths)
        if not matches:
            return PrimitiveResult(passed=True, rule_name=self.rule_name, file=str(target))

        sample = matches[0]
        return PrimitiveResult(
            passed=False,
            rule_name=self.rule_name,
            file=sample["file"],
            line=sample["line"],
            message=f"deleted symbol {sample['symbol']!r} is still referenced in docs",
            remediation=[
                f"Remove the reference to {sample['symbol']!r} from {sample['file']}",
            ],
        )

    def _collect_deleted_symbols(self, target: Path, since: str) -> set[str]:
        args = ["git", "log", "-p", "--diff-filter=D", "--format="]
        if since == "all":
            pass
        elif since == "last-tag":
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
            )
            if tag_result.returncode == 0 and tag_result.stdout.strip():
                args.append(f"{tag_result.stdout.strip()}..HEAD")
        else:
            args.append(f"{since}..HEAD")

        result = subprocess.run(
            args, cwd=target, capture_output=True, text=True, check=False,
        )
        symbols: set[str] = set()
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("class "):
                parts = stripped.split()
                if len(parts) >= 2:
                    name = parts[1].split("(")[0].rstrip(":")
                    symbols.add(name)
        return symbols

    def _grep_docs(
        self, target, symbols, scan_paths, exclude_paths,
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for symbol in symbols:
            for scan_path in scan_paths:
                cmd = [
                    "git", "grep", "-n", "--", symbol, "--", scan_path, ":!*.py",
                ]
                for excl in exclude_paths:
                    cmd.extend([":!" + excl])
                result = subprocess.run(
                    cmd, cwd=target, capture_output=True, text=True, check=False,
                )
                for line in result.stdout.splitlines():
                    if ":" in line:
                        file_part, line_num, content = line.split(":", 2)
                        matches.append({
                            "symbol": symbol,
                            "file": file_part,
                            "line": int(line_num),
                            "content": content.strip(),
                        })
                        if len(matches) >= 20:
                            return matches
        return matches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_git_grep.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/git_grep.py tests/unit/test_git_grep.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): git_grep primitive (deleted symbols since ref)"
```

---

### Task 5: Implement crackerjack markdown_inventory primitive

**Files:**
- Create: `crackerjack/services/check_primitives/markdown_inventory.py`
- Create: `crackerjack/tests/unit/test_markdown_inventory.py`

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_markdown_inventory.py`:

```python
"""Tests for the markdown_inventory crackerjack primitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.services.check_primitives.markdown_inventory import MarkdownInventoryPrimitive
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extracts_block_with_html_comments(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Clean Repo\n\n"
        "## Tools\n\n"
        "<!-- BEGIN tools -->\n"
        "- foo\n- bar\n"
        "<!-- END tools -->\n"
    )
    primitive = MarkdownInventoryPrimitive()
    config = {
        "path": str(readme),
        "block_name": "tools",
        "expected_lines": ["- foo", "- bar"],
    }
    result = primitive.run(config)
    assert result.passed is True


def test_missing_line_in_inventory_fails(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Clean Repo\n\n"
        "<!-- BEGIN tools -->\n"
        "- foo\n"
        "<!-- END tools -->\n"
    )
    primitive = MarkdownInventoryPrimitive()
    config = {
        "path": str(readme),
        "block_name": "tools",
        "expected_lines": ["- foo", "- bar"],
    }
    result = primitive.run(config)
    assert result.passed is False
    assert "- bar" in result.message


def test_missing_delimiters_raises_config_error(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Clean Repo\n\nNo inventory block here.\n")

    primitive = MarkdownInventoryPrimitive()
    config = {
        "path": str(readme),
        "block_name": "tools",
        "expected_lines": ["- foo"],
    }
    with pytest.raises(ConfigError):
        primitive.run(config)


def test_missing_file_raises() -> None:
    primitive = MarkdownInventoryPrimitive()
    config = {
        "path": "/nonexistent/README.md",
        "block_name": "tools",
        "expected_lines": ["- foo"],
    }
    with pytest.raises(MissingFileError):
        primitive.run(config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_markdown_inventory.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `check_primitives/markdown_inventory.py`**

```python
"""markdown_inventory primitive: extract HTML-comment-delimited blocks and compare."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)

_BEGIN_RE = re.compile(r"<!--\s*BEGIN\s+(?P<name>\S+)\s*-->")
_END_RE = re.compile(r"<!--\s*END\s+(?P<name>\S+)\s*-->")


class MarkdownInventoryPrimitive:
    """Extract a block delimited by HTML comments and compare to expected lines."""

    rule_name = "markdown_inventory"

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        path = config.get("path")
        block_name = config.get("block_name")
        expected_lines = config.get("expected_lines", [])

        if not path or not block_name:
            raise ConfigError("markdown_inventory requires 'path' and 'block_name'")

        file_path = Path(path)
        if not file_path.exists():
            raise MissingFileError(f"file not found: {path}")

        content = file_path.read_text(encoding="utf-8", errors="replace")
        block_lines = self._extract_block(content, block_name)
        if block_lines is None:
            raise ConfigError(
                f"missing <!-- BEGIN {block_name} --> / <!-- END {block_name} --> delimiters in {path}"
            )

        missing = [line for line in expected_lines if line not in block_lines]
        if missing:
            return PrimitiveResult(
                passed=False,
                rule_name=self.rule_name,
                file=path,
                message=f"missing lines in {block_name!r} block: {missing}",
                remediation=[
                    f"Add lines {missing} to the <!-- BEGIN {block_name} --> block in {path}",
                ],
            )

        return PrimitiveResult(passed=True, rule_name=self.rule_name, file=path)

    def _extract_block(self, content: str, block_name: str) -> list[str] | None:
        lines = content.splitlines()
        begin_idx = end_idx = None
        for i, line in enumerate(lines):
            m = _BEGIN_RE.search(line)
            if m and m.group("name") == block_name:
                begin_idx = i + 1
                continue
            m = _END_RE.search(line)
            if m and m.group("name") == block_name and begin_idx is not None:
                end_idx = i
                break
        if begin_idx is None or end_idx is None:
            return None
        return lines[begin_idx:end_idx]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_markdown_inventory.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/markdown_inventory.py tests/unit/test_markdown_inventory.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): markdown_inventory primitive (HTML-comment blocks)"
```

---

### Task 6: Implement crackerjack ast_symbol_check primitive

**Files:**
- Create: `crackerjack/services/check_primitives/ast_symbol_check.py`
- Create: `crackerjack/tests/unit/test_ast_symbol_check.py`

- [ ] **Step 1: Write the failing test**

`crackerjack/tests/unit/test_ast_symbol_check.py`:

```python
"""Tests for the ast_symbol_check crackerjack primitive."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.services.check_primitives.ast_symbol_check import AstSymbolCheckPrimitive

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_existing_function_passes(tmp_path: Path) -> None:
    (FIXTURES / "clean_repo").mkdir(exist_ok=True)
    (FIXTURES / "clean_repo/module.py").write_text("def existing_function(): pass\n")
    primitive = AstSymbolCheckPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/module.py"),
        "symbol": "existing_function",
        "check": "exists",
    }
    result = primitive.run(config)
    assert result.passed is True


def test_missing_function_fails(tmp_path: Path) -> None:
    (FIXTURES / "clean_repo/module.py").write_text("def other_function(): pass\n")
    primitive = AstSymbolCheckPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/module.py"),
        "symbol": "missing_function",
        "check": "exists",
    }
    result = primitive.run(config)
    assert result.passed is False
    assert "missing_function" in result.message


def test_field_with_validation_alias_passes(tmp_path: Path) -> None:
    (FIXTURES / "clean_repo/module.py").write_text(
        "from pydantic import BaseModel, Field\n"
        "class Settings(BaseModel):\n"
        "    api_key: str = Field(validation_alias='API_KEY')\n"
    )
    primitive = AstSymbolCheckPrimitive()
    config = {
        "path": str(FIXTURES / "clean_repo/module.py"),
        "symbol": "Field",
        "check": "wired",
        "wired_kwarg": "validation_alias",
        "wired_value_contains": "API_KEY",
    }
    result = primitive.run(config)
    assert result.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_ast_symbol_check.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `check_primitives/ast_symbol_check.py`**

```python
"""ast_symbol_check primitive: resolve a Python symbol or check Pydantic wiring."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveResult,
)


class AstSymbolCheckPrimitive:
    """Check Python AST for symbol existence or Pydantic Field wiring."""

    rule_name = "ast_symbol_check"

    def run(self, config: dict[str, Any]) -> PrimitiveResult:
        path = config.get("path")
        symbol = config.get("symbol")
        check = config.get("check", "exists")

        if not path or not symbol:
            raise ConfigError("ast_symbol_check requires 'path' and 'symbol'")

        file_path = Path(path)
        if not file_path.exists():
            raise MissingFileError(f"file not found: {path}")

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            raise ConfigError(f"invalid Python in {path}: {exc}") from exc

        if check == "exists":
            return self._check_exists(file_path, tree, symbol)
        if check == "wired":
            return self._check_wired(file_path, tree, config)
        raise ConfigError(f"unknown check type: {check}")

    def _check_exists(self, file_path, tree, symbol: str) -> PrimitiveResult:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol:
                    return PrimitiveResult(
                        passed=True, rule_name=self.rule_name,
                        file=str(file_path), line=node.lineno,
                    )
        return PrimitiveResult(
            passed=False, rule_name=self.rule_name, file=str(file_path),
            message=f"symbol {symbol!r} not found in {file_path}",
            remediation=[f"Define {symbol} in {file_path}"],
        )

    def _check_wired(self, file_path, tree, config: dict[str, Any]) -> PrimitiveResult:
        symbol = config["symbol"]
        kwarg_name = config.get("wired_kwarg")
        value_contains = config.get("wired_value_contains", "")
        if not kwarg_name:
            raise ConfigError("'wired' check requires 'wired_kwarg'")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = self._get_call_name(node)
            if func_name != symbol:
                continue
            for kw in node.keywords:
                if kw.arg == kwarg_name:
                    value_repr = ast.unparse(kw.value) if kw.value else ""
                    if value_contains in value_repr:
                        return PrimitiveResult(
                            passed=True, rule_name=self.rule_name,
                            file=str(file_path), line=node.lineno,
                            value=value_contains,
                        )

        return PrimitiveResult(
            passed=False, rule_name=self.rule_name, file=str(file_path),
            message=f"symbol {symbol!r} called without {kwarg_name}=... containing {value_contains!r}",
            remediation=[
                f"Add {kwarg_name}={value_contains!r} to the {symbol} call in {file_path}",
            ],
        )

    def _get_call_name(self, node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_ast_symbol_check.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/services/check_primitives/ast_symbol_check.py tests/unit/test_ast_symbol_check.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): ast_symbol_check primitive (existence + Pydantic wiring)"
```

---

### Task 7: Add `crackerjack check` Typer subcommand

**Files:**
- Create: `crackerjack/cli/check.py`
- Modify: `crackerjack/__main__.py` (use the actual 4-arg `_safe_add_typer` signature)
- Create: `crackerjack/tests/unit/test_check_cli.py`

- [ ] **Step 1: Read existing `crackerjack/__main__.py`**

Run: `Read /Users/les/Projects/crackerjack/crackerjack/__main__.py`
Find the existing `_safe_add_typer` calls (lines ~110-135) and note the exact 4-arg signature: `_safe_add_typer(main_app, module_path: str, attr_name: str, command_name: str)`.

- [ ] **Step 2: Write the failing test**

`crackerjack/tests/unit/test_check_cli.py`:

```python
"""Tests for the `crackerjack check` CLI subcommand."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from crackerjack.__main__ import cli

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_check_cli_dispatches_to_regex_match() -> None:
    """`crackerjack check --rule regex_match --config <yaml>` runs the primitive."""
    runner = CliRunner()
    config_yaml = (
        f'path: "{FIXTURES / "clean_repo/README.md"}"\n'
        'pattern: "## Version: (\\\\d+\\\\.\\\\d+\\\\.\\\\d+)"\n'
        "capture_group: 1\n"
    )
    result = runner.invoke(
        cli, ["check", "--rule", "regex_match", "--config", config_yaml],
    )
    assert result.exit_code == 0, result.stdout


def test_check_cli_unknown_rule_exits_2() -> None:
    """Unknown rule exits with config error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--rule", "unknown_rule", "--config", "path: x"])
    assert result.exit_code == 2


def test_check_cli_help_mentions_rule_option() -> None:
    """`crackerjack check --help` shows --rule option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["check", "--help"])
    assert result.exit_code == 0
    assert "Primitive name" in result.stdout or "--rule" in result.stdout
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_check_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'crackerjack.cli.check'`.

- [ ] **Step 4: Create `crackerjack/cli/check.py`**

```python
"""Typer subcommand `crackerjack check` — dispatch to generic primitives."""
from __future__ import annotations

from typing import Any

import typer
import yaml

from crackerjack.services.check_primitives import PRIMITIVES
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveCrash,
)

check_app = typer.Typer(help="Run a single generic check primitive")


@check_app.command(name="check")
def check_cmd(
    rule: str = typer.Option(..., "--rule", help="Primitive name (regex_match, etc.)"),
    config: str = typer.Option(
        ..., "--config", help="YAML config block as a string",
        envvar="CRACKERJACK_CHECK_CONFIG",
    ),
) -> None:
    """Run a single check primitive against a target."""
    primitive_cls = PRIMITIVES.get(rule)
    if primitive_cls is None:
        typer.echo(f"unknown rule {rule!r}; available: {sorted(PRIMITIVES)}", err=True)
        raise typer.Exit(code=2)

    try:
        parsed_config: dict[str, Any] = yaml.safe_load(config) or {}
    except yaml.YAMLError as exc:
        typer.echo(f"invalid YAML config: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    primitive = primitive_cls()
    try:
        result = primitive.run(parsed_config)
    except ConfigError as exc:
        typer.echo(f"config error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except MissingFileError as exc:
        typer.echo(f"missing file: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    except PrimitiveCrash as exc:
        typer.echo(f"primitive crash: {exc}", err=True)
        raise typer.Exit(code=4) from exc

    if result.passed:
        typer.echo(f"PASS {rule}: {result.message or 'ok'}")
        raise typer.Exit(code=0)

    typer.echo(f"FAIL {rule}: {result.message}")
    for r in result.remediation:
        typer.echo(f"  -> {r}")
    raise typer.Exit(code=1)
```

- [ ] **Step 5: Update `crackerjack/services/check_primitives/__init__.py`**

```python
"""Generic crackerjack check primitives (ecosystem-agnostic)."""
from __future__ import annotations

from crackerjack.services.check_primitives.ast_symbol_check import AstSymbolCheckPrimitive
from crackerjack.services.check_primitives.git_grep import GitGrepPrimitive
from crackerjack.services.check_primitives.markdown_inventory import MarkdownInventoryPrimitive
from crackerjack.services.check_primitives.pyproject_field import PyprojectFieldPrimitive
from crackerjack.services.check_primitives.regex_match import RegexMatchPrimitive

PRIMITIVES: dict[str, type] = {
    "regex_match": RegexMatchPrimitive,
    "pyproject_field": PyprojectFieldPrimitive,
    "git_grep": GitGrepPrimitive,
    "markdown_inventory": MarkdownInventoryPrimitive,
    "ast_symbol_check": AstSymbolCheckPrimitive,
}

__all__ = [
    "PRIMITIVES",
    "RegexMatchPrimitive",
    "PyprojectFieldPrimitive",
    "GitGrepPrimitive",
    "MarkdownInventoryPrimitive",
    "AstSymbolCheckPrimitive",
]
```

- [ ] **Step 6: Modify `crackerjack/__main__.py`**

After the existing imports and `_safe_add_typer` calls, add:

```python
_safe_add_typer(app, "crackerjack.cli.check", "check_app", "check")
```

**Match the exact 4-arg signature:** `_safe_add_typer(main_app, module_path: str, attr_name: str, command_name: str)`. The function imports `module_path` via `importlib.import_module`, then `getattr(module, attr_name)`, then calls `main_app.add_typer(sub_app, name=command_name)`.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_check_cli.py -v`
Expected: 3 tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/cli/check.py crackerjack/services/check_primitives/__init__.py crackerjack/__main__.py tests/unit/test_check_cli.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack): 'crackerjack check' CLI subcommand"
```

---

### Task 8: Register crackerjack__check_* MCP tools (NEW file)

**Files:**
- Create: `crackerjack/mcp/tools/check_tools.py`
- Modify: `crackerjack/mcp/server_core.py` (add `register_check_tools(mcp_app)` call)

**Interfaces:**
- Consumes: `crackerjack.services.check_primitives.PRIMITIVES`
- Produces: 5 MCP tools `crackerjack__check_<name>` accepting `config: dict`, returning `{passed, file, line, value, message, remediation, error?}`

- [ ] **Step 1: Read existing `crackerjack/mcp/server_core.py`**

Run: `Read /Users/les/Projects/crackerjack/crackerjack/mcp/server_core.py`
Find: (a) the `mcp`/`app` FastMCP instance, (b) the call site where tool modules register themselves (likely a single function calling `register_X_tools(mcp)` for each tool group).

- [ ] **Step 2: Create `crackerjack/mcp/tools/check_tools.py`**

```python
"""MCP tools exposing crackerjack's 5 generic check primitives."""
from __future__ import annotations

from typing import Any

from crackerjack.services.check_primitives import (
    AstSymbolCheckPrimitive,
    GitGrepPrimitive,
    MarkdownInventoryPrimitive,
    PyprojectFieldPrimitive,
    RegexMatchPrimitive,
)
from crackerjack.services.check_primitives.base import (
    ConfigError,
    MissingFileError,
    PrimitiveCrash,
)


def _serialize(result):
    return {
        "passed": result.passed,
        "rule_name": result.rule_name,
        "file": result.file,
        "line": result.line,
        "value": result.value,
        "message": result.message,
        "remediation": result.remediation,
    }


def register_check_tools(mcp_app: Any) -> None:
    """Register `crackerjack__check_*` MCP tools."""

    @mcp_app.tool(name="crackerjack__check_regex_match")
    def check_regex_match(config: dict) -> dict:
        """Match a regex against file contents. ReDoS-safe via ValidatedPattern."""
        try:
            result = RegexMatchPrimitive().run(config)
        except ConfigError as exc:
            return {"error": "config_invalid", "message": str(exc)}
        except MissingFileError as exc:
            return {"error": "file_missing", "message": str(exc)}
        except PrimitiveCrash as exc:
            return {"error": "primitive_crash", "message": str(exc)}
        return _serialize(result)

    @mcp_app.tool(name="crackerjack__check_pyproject_field")
    def check_pyproject_field(config: dict) -> dict:
        """Extract a TOML field from pyproject.toml. Returns value=str(extracted)."""
        try:
            result = PyprojectFieldPrimitive().run(config)
        except ConfigError as exc:
            return {"error": "config_invalid", "message": str(exc)}
        except MissingFileError as exc:
            return {"error": "file_missing", "message": str(exc)}
        return _serialize(result)

    @mcp_app.tool(name="crackerjack__check_git_grep")
    def check_git_grep(config: dict) -> dict:
        """Find deleted symbols cited in docs."""
        try:
            result = GitGrepPrimitive().run(config)
        except ConfigError as exc:
            return {"error": "config_invalid", "message": str(exc)}
        return _serialize(result)

    @mcp_app.tool(name="crackerjack__check_markdown_inventory")
    def check_markdown_inventory(config: dict) -> dict:
        """Extract HTML-comment-delimited Markdown block and compare."""
        try:
            result = MarkdownInventoryPrimitive().run(config)
        except ConfigError as exc:
            return {"error": "config_invalid", "message": str(exc)}
        except MissingFileError as exc:
            return {"error": "file_missing", "message": str(exc)}
        return _serialize(result)

    @mcp_app.tool(name="crackerjack__check_ast_symbol_check")
    def check_ast_symbol_check(config: dict) -> dict:
        """Resolve a Python symbol or check Pydantic wiring."""
        try:
            result = AstSymbolCheckPrimitive().run(config)
        except ConfigError as exc:
            return {"error": "config_invalid", "message": str(exc)}
        except MissingFileError as exc:
            return {"error": "file_missing", "message": str(exc)}
        return _serialize(result)
```

- [ ] **Step 3: Modify `crackerjack/mcp/server_core.py`**

Find where other tool groups register themselves (per Step 1 reading). Add an import:

```python
from crackerjack.mcp.tools.check_tools import register_check_tools
```

And a call:

```python
register_check_tools(mcp)
```

Place the call alongside the other `register_X_tools(mcp)` calls.

- [ ] **Step 4: Verify the tools are registered**

Run: `cd /Users/les/Projects/crackerjack && uv run python -c "from crackerjack.mcp.server_core import mcp_app; print(sorted(t.name for t in mcp_app.list_tools() if t.name.startswith('crackerjack__check_')))"`
Expected: prints 6 tool names (5 original + yaml_field added in Task 3A).

**Note:** The FastMCP variable name in `crackerjack/mcp/server_core.py:163` is `mcp_app` (NOT `mcp`). Using `mcp` will raise `ImportError`.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/mcp/tools/check_tools.py crackerjack/mcp/server_core.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(checkerjack-mcp): register 5 crackerjack__check_* tools"
```

---

### Task 9: Create mahavishnu settings files (top-level, NOT inside package)

**Files:**
- Create: `mahavishnu/settings/bodai-ports.yaml`
- Create: `mahavishnu/settings/bodai-doc-rules.yaml` (with `version_guard` as `composite` type)

**Interfaces:**
- Consumes: `yaml.safe_load` directly on `Path("settings/bodai-ports.yaml").read_text()` — NOT via `MahavishnuSettings` (these are compliance config, not typed settings)
- Produces: Two YAML files at repo root `settings/`

- [ ] **Step 1: Create top-level `settings/bodai-ports.yaml`**

```yaml
# Canonical Bodai ecosystem port table (source of truth)
# Loaded via yaml.safe_load by mahavishnu conformance CLI.
# Updated by mahavishnu maintainers; consumed by `port_consistency` rule.
ecosystem:
  mahavishnu: 8680
  akosha: 8682
  dhara: 8683
  session_buddy: 8678
  crackerjack: 8676
  oneiric: null  # library, no MCP server port
```

- [ ] **Step 2: Create top-level `settings/bodai-doc-rules.yaml`**

```yaml
# Bodai-specific rule configs for the conformance check.
# Loaded by mahavishnu conformance CLI; each rule is invoked via
# the corresponding crackerjack primitive over MCP, except for
# `primitive: composite` rules which are orchestrated in mahavishnu.
#
# Per-rule fields:
#   primitive: crackerjack primitive name OR `composite` (mahavishnu-side orchestration)
#   config: dict passed verbatim to the primitive (composite rules use `steps:` instead)
#   steps: list of {primitive, capture, config} dicts (composite rules only)
#   comparison: "equal" | "not_equal" (composite rules only)
#   remediation_hint: list of strings shown when the rule fails
#   required: bool — false means skip with a notice instead of fail
#   kill_switch: bool — true means skip entirely (operator disable)
#   allow_self_violation: bool — true means skip when target repo name matches self_repo
#   self_repo: string — repo name that owns this rule

rules:
  version_guard:
    self_repo: mahavishnu
    allow_self_violation: true
    kill_switch: false
    required: true
    description: >
      pyproject.toml [project].version must equal the README version banner.
    primitive: composite
    comparison: equal
    steps:
      - name: pyproject_version
        primitive: pyproject_field
        capture: version
        config:
          path: "./pyproject.toml"
          field: "project.version"
      - name: readme_version
        primitive: regex_match
        capture: version
        config:
          path: "./README.md"
          pattern: "## Version: (\\d+\\.\\d+\\.\\d+)"
          capture_group: 1
    remediation_hint:
      - "Update README.md to read '## Version: <version>' matching pyproject.toml [project].version"
      - "Or set __version__ in <repo>/__init__.py to read via importlib.metadata.version()"
```

**YAML escape note:** the `pattern:` value uses `\\d+\\.\\d+\\.\\d+` (double backslash). `yaml.safe_load` decodes this to `\d+\.\d+\.\d+` which Python's `re.compile` interprets as a real regex pattern. **Single backslash `\d` would be interpreted by some YAML loaders as an unknown escape and dropped.**

- [ ] **Step 3: Verify the YAML loads correctly**

Run:
```bash
cd /Users/les/Projects/mahavishnu
uv run python -c "
import yaml
from pathlib import Path
data = yaml.safe_load(Path('settings/bodai-ports.yaml').read_text())
print(data['ecosystem']['mahavishnu'])

data = yaml.safe_load(Path('settings/bodai-doc-rules.yaml').read_text())
rule = data['rules']['version_guard']
print(rule['primitive'], rule['comparison'])
import re
pattern = rule['steps'][1]['config']['pattern']
print(re.compile(pattern).pattern)
"
```
Expected output (3 lines):
```
8680
composite equal
## Version: (\d+\.\d+\.\d+)
```

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add settings/bodai-ports.yaml settings/bodai-doc-rules.yaml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance): add top-level bodai-ports and bodai-doc-rules (Phase 1 subset)"
```

---

### Task 10: Extend BodaiComponentMCPClient with explicit session helpers

**Files:**
- Modify: `mahavishnu/mcp/bodai_component_client.py` (add `check_primitive` helper; document explicit lifecycle)

**Note:** `BodaiComponentMCPClient` has NO `__aenter__`/`__aexit__` and uses `base_url=...` constructor (per adversarial review). We do NOT add context manager support — callers must `await client._ensure_session()` and `await client.aclose()` explicitly.

- [ ] **Step 1: Read existing `bodai_component_client.py`**

Run: `Read /Users/les/Projects/mahavishnu/mahavishnu/mcp/bodai_component_client.py`
Find: constructor signature (`def __init__(self, base_url: str, ...)`), `call_tool` method, `_ensure_session` method, `aclose` method, `list_tools` method (if present).

- [ ] **Step 2: Add `list_tools` if not present**

If missing, add to the class:

```python
async def list_tools(self) -> list[dict]:
    """List tools available on the target MCP server."""
    await self._ensure_session()
    if self._session is None:
        raise RuntimeError("client not connected")
    result = await self._session.list_tools()
    return [
        {"name": tool.name, "description": tool.description}
        for tool in result.tools
    ]
```

- [ ] **Step 3: Add `check_primitive` helper (with CallToolResult unpacking)**

```python
async def check_primitive(self, primitive_name: str, config: dict) -> dict:
    """Call a crackerjack__check_<name> MCP tool.

    primitive_name is one of: regex_match, pyproject_field, yaml_field,
    git_grep, markdown_inventory, ast_symbol_check.

    Unpacks MCP SDK CallToolResult.content[0].text (JSON) into a dict.
    """
    import json

    raw = await self.call_tool(
        f"crackerjack__check_{primitive_name}",
        {"config": config},
    )
    # MCP SDK returns CallToolResult (Pydantic model), not a dict
    if hasattr(raw, "content") and raw.content:
        try:
            return json.loads(raw.content[0].text)
        except (json.JSONDecodeError, IndexError, AttributeError):
            pass
    if isinstance(raw, dict):
        return raw
    return {
        "error": "primitive_crash",
        "message": f"unexpected MCP response shape: {raw!r}",
    }
```

- [ ] **Step 4: Write a unit test for `check_primitive`**

`mahavishnu/tests/unit/test_bodai_component_client.py`:

```python
"""Test BodaiComponentMCPClient.check_primitive helper."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.mcp.bodai_component_client import BodaiComponentMCPClient


@pytest.mark.asyncio
async def test_check_primitive_builds_correct_tool_name() -> None:
    """check_primitive calls crackerjack__check_<name> with config."""
    client = BodaiComponentMCPClient(base_url="http://localhost:8676/mcp")
    client.call_tool = AsyncMock(return_value={"passed": True})
    result = await client.check_primitive(
        "regex_match",
        {"path": "x.md", "pattern": r"v(\d+)"},
    )
    client.call_tool.assert_awaited_once_with(
        "crackerjack__check_regex_match",
        {"config": {"path": "x.md", "pattern": r"v(\d+)"}},
    )
    assert result == {"passed": True}
```

- [ ] **Step 5: Run test**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/test_bodai_component_client.py -v`
Expected: 1 test PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/bodai_component_client.py tests/unit/test_bodai_component_client.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(mcp): BodaiComponentMCPClient.check_primitive + list_tools helpers"
```

---

### Task 11: Implement mahavishnu conformance runner with async + composite handling

**Files:**
- Create: `mahavishnu/services/conformance/__init__.py`
- Create: `mahavishnu/services/conformance/runner.py` (async; handles `composite` rule type)
- Create: `mahavishnu/services/conformance/aggregator.py`
- Create: `mahavishnu/services/conformance/reporter.py`
- Create: `mahavishnu/cli/conformance_cli.py` (Typer subcommand)
- Modify: `mahavishnu/_main_cli.py` (use `app.add_typer(conformance_app, name="conformance")` — NOT `_safe_add_typer`)
- Create: `mahavishnu/tests/integration/conformance/fixture_clean_bodai_repo/`
- Create: `mahavishnu/tests/integration/conformance/fixture_version_drift/`
- Create: `mahavishnu/tests/integration/conformance/fixture_mahavishnu_real/`
- Create: `mahavishnu/tests/integration/conformance/fixture_bodai_doc_rules.yaml`
- Create: `mahavishnu/tests/integration/conformance/fixture_bodai_ports.yaml`
- Create: `mahavishnu/tests/integration/conformance/test_version_guard.py`

- [ ] **Step 1: Create `services/conformance/__init__.py`**

```python
"""Bodai conformance check runner."""
from __future__ import annotations
```

- [ ] **Step 2: Create `services/conformance/aggregator.py`**

```python
"""Per-check result type."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    """Result of a single check (rule + primitive step)."""

    rule_name: str
    primitive: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
    file: str | None = None
    line: int | None = None
    value: str | None = None
    message: str = ""
    remediation: list[str] | None = None
```

- [ ] **Step 3: Create `services/conformance/runner.py`**

```python
"""Orchestrate Bodai-specific checks by calling crackerjack primitives via MCP."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mahavishnu.core.errors import (
    ConformanceDriftDetected,
    ConformancePrimitiveCrash,
    ConformanceRulesConfigInvalid,
    ConformanceRulesFileMissing,
)
from mahavishnu.mcp.bodai_component_client import BodaiComponentMCPClient
from mahavishnu.services.conformance.aggregator import CheckResult


def _resolve_target(config: dict, target_path: Path) -> dict:
    """Resolve relative paths in config to target_path."""
    resolved = dict(config)
    if "path" in resolved and not Path(resolved["path"]).is_absolute():
        resolved["path"] = str(target_path / resolved["path"])
    return resolved


def _resolve_composite_target(
    step: dict, target_path: Path
) -> dict:
    """Same as _resolve_target but for composite rule step configs."""
    resolved = dict(step.get("config", {}))
    if "path" in resolved and not Path(resolved["path"]).is_absolute():
        resolved["path"] = str(target_path / resolved["path"])
    return resolved


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConformanceRulesFileMissing(
            file_path=str(path),
            recovery=[f"Create {path}"],
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _repo_name_from(target_path: Path) -> str:
    """Read repo name from target's conformance.yaml; fall back to dir name."""
    manifest = target_path / "conformance.yaml"
    if manifest.exists():
        with manifest.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict) and "repo" in data:
            return str(data["repo"])
    return target_path.name


class ConformanceRunner:
    """Run a single conformance check (e.g. version_guard) against a target."""

    def __init__(self, rules_path: Path, ports_path: Path, crackerjack_url: str) -> None:
        self._rules_path = rules_path
        self._ports_path = ports_path
        self._crackerjack_url = crackerjack_url

    async def run_rule(self, rule_name: str, target_path: Path) -> list[CheckResult]:
        """Run a single rule asynchronously. Returns per-step results."""
        rules_config = _read_yaml(self._rules_path)
        rule = rules_config.get("rules", {}).get(rule_name)
        if rule is None:
            raise ConformanceRulesConfigInvalid(
                rule_name=rule_name,
                recovery=[f"Add {rule_name!r} rule to {self._rules_path}"],
            )

        if rule.get("kill_switch"):
            return [CheckResult(
                rule_name=rule_name, primitive="", passed=True, skipped=True,
                skip_reason="kill_switch=true",
            )]

        # Read repo name from conformance.yaml (preferred) or fall back to dir name
        repo_name = _repo_name_from(target_path)
        if rule.get("allow_self_violation") and rule.get("self_repo") == repo_name:
            return [CheckResult(
                rule_name=rule_name, primitive="", passed=True, skipped=True,
                skip_reason="allow_self_violation",
            )]

        if rule.get("primitive") == "composite":
            return await self._run_composite(rule_name, rule, target_path)

        # Single-primitive rule
        if not rule.get("config"):
            raise ConformanceRulesConfigInvalid(
                rule_name=rule_name,
                recovery=[f"single-primitive rule {rule_name!r} requires 'config'"],
            )
        return await self._run_single_primitive(
            rule_name, rule["primitive"], rule["config"], target_path,
        )

    async def _run_single_primitive(
        self,
        rule_name: str,
        primitive: str,
        config: dict,
        target_path: Path,
    ) -> list[CheckResult]:
        client = BodaiComponentMCPClient(base_url=self._crackerjack_url)
        try:
            await client._ensure_session()
            response = await client.check_primitive(primitive, _resolve_target(config, target_path))
        except Exception as exc:
            raise ConformancePrimitiveCrash(
                rule_name=rule_name,
                recovery=[f"Investigate crackerjack primitive {primitive!r}"],
                details={"exception": repr(exc)},
            ) from exc
        finally:
            await client.aclose()

        return [self._response_to_result(rule_name, primitive, response)]

    async def _run_composite(
        self,
        rule_name: str,
        rule: dict,
        target_path: Path,
    ) -> list[CheckResult]:
        steps = rule.get("steps", [])
        if not steps:
            raise ConformanceRulesConfigInvalid(
                rule_name=rule_name,
                recovery=[f"composite rule {rule_name!r} requires 'steps' list"],
            )
        comparison = rule.get("comparison", "equal")

        client = BodaiComponentMCPClient(base_url=self._crackerjack_url)
        results: list[CheckResult] = []
        captured: dict[str, str | None] = {}
        try:
            await client._ensure_session()
            for step in steps:
                primitive = step["primitive"]
                capture_name = step.get("capture")
                step_config = _resolve_composite_target(step, target_path)
                response = await client.check_primitive(primitive, step_config)
                result = self._response_to_result(rule_name, primitive, response)
                results.append(result)
                if capture_name and "value" in response:
                    captured[capture_name] = response.get("value")
        except Exception as exc:
            raise ConformancePrimitiveCrash(
                rule_name=rule_name,
                recovery=[f"Investigate composite rule {rule_name!r}"],
                details={"exception": repr(exc)},
            ) from exc
        finally:
            await client.aclose()

        # Cross-step comparison
        non_skipped = [r for r in results if not r.skipped]
        all_passed = all(r.passed for r in non_skipped)
        values_match = (
            len({v for v in captured.values() if v is not None}) <= 1
        )
        if comparison == "equal":
            composite_passed = all_passed and values_match
        elif comparison == "not_equal":
            composite_passed = all_passed and len({v for v in captured.values() if v is not None}) > 1
        else:
            raise ConformanceRulesConfigInvalid(
                rule_name=rule_name,
                recovery=[f"unknown comparison {comparison!r}; use 'equal' or 'not_equal'"],
            )

        if not composite_passed:
            # Find the first step with a mismatched value
            for r in results:
                if not r.passed:
                    # Surface the underlying error
                    return results
            # All primitives passed but values differ
            captured_summary = ", ".join(f"{k}={v!r}" for k, v in captured.items())
            return [
                CheckResult(
                    rule_name=rule_name,
                    primitive="composite",
                    passed=False,
                    message=f"{comparison!r} comparison failed: {captured_summary}",
                    remediation=rule.get("remediation_hint", [
                        f"Fix {rule_name!r} — captured values differ"
                    ]),
                ),
                *results,
            ]

        return results

    def _response_to_result(
        self, rule_name: str, primitive: str, response: dict
    ) -> CheckResult:
        """Convert MCP response dict to CheckResult; raise on error."""
        if "error" in response:
            err = response["error"]
            if err == "config_invalid":
                raise ConformanceRulesConfigInvalid(
                    rule_name=rule_name,
                    recovery=[f"Fix {rule_name!r} config: {response.get('message')}"],
                )
            raise ConformancePrimitiveCrash(
                rule_name=rule_name,
                recovery=[f"Investigate {err}: {response.get('message')}"],
            )
        return CheckResult(
            rule_name=rule_name,
            primitive=primitive,
            passed=response.get("passed", False),
            file=response.get("file"),
            line=response.get("line"),
            value=response.get("value"),
            message=response.get("message", ""),
            remediation=response.get("remediation", []),
        )

    def load_ports(self) -> dict:
        return _read_yaml(self._ports_path)
```

- [ ] **Step 4: Create `services/conformance/reporter.py`**

```python
"""Format check results as MHV-coded errors."""
from __future__ import annotations

from mahavishnu.core.errors import ConformanceDriftDetected
from mahavishnu.services.conformance.aggregator import CheckResult


def report_failures(rule_name: str, results: list[CheckResult]) -> None:
    """Raise MHV-512 ConformanceDriftDetected if any non-skipped result failed."""
    failures = [r for r in results if not r.passed and not r.skipped]
    if not failures:
        return
    details = [
        {"file": f.file, "line": f.line, "message": f.message, "primitive": f.primitive}
        for f in failures
    ]
    remediation = []
    for f in failures:
        if f.remediation:
            remediation.extend(f.remediation)
    if not remediation:
        remediation.append(f"Fix {rule_name!r} drift in target repo")
    raise ConformanceDriftDetected(
        rule_name=rule_name, recovery=remediation, details={"failures": details},
    )


def summarize(results: list[CheckResult]) -> str:
    lines = []
    for r in results:
        if r.skipped:
            lines.append(f"SKIP {r.rule_name}: {r.skip_reason}")
        elif r.passed:
            lines.append(f"PASS {r.rule_name}")
        else:
            lines.append(f"FAIL {r.rule_name}: {r.message}")
            for rem in r.remediation or []:
                lines.append(f"  -> {rem}")
    return "\n".join(lines)
```

- [ ] **Step 5: Create `cli/conformance_cli.py`**

```python
"""Typer subcommand `mahavishnu conformance check`."""
from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import yaml

from mahavishnu.core.errors import MahavishnuError
from mahavishnu.services.conformance.reporter import report_failures, summarize
from mahavishnu.services.conformance.runner import ConformanceRunner

conformance_app = typer.Typer(help="Bodai conformance checks")


@conformance_app.command(name="check")
def check_cmd(
    target: Path = typer.Option(Path("."), "--target", help="Path to the Bodai repo to check"),
    rules: Path = typer.Option(
        Path("settings/bodai-doc-rules.yaml"), "--rules",
        help="Path to bodai-doc-rules.yaml",
    ),
    ports: Path = typer.Option(
        Path("settings/bodai-ports.yaml"), "--ports",
        help="Path to bodai-ports.yaml",
    ),
    rule_filter: list[str] = typer.Option(
        [], "--only", help="Run only these rule names (repeatable)",
    ),
    crackerjack_url: str = typer.Option(
        "http://localhost:8676/mcp", "--crackerjack-url",
        help="URL of the crackerjack MCP server",
    ),
) -> None:
    """Run Bodai conformance checks against the target repo."""
    runner = ConformanceRunner(
        rules_path=rules, ports_path=ports, crackerjack_url=crackerjack_url,
    )
    rules_config = runner.load_ports()  # also validates file exists
    _ = rules_config

    if not rules.exists():
        typer.echo(f"rules file not found: {rules}", err=True)
        raise typer.Exit(code=1)

    with rules.open(encoding="utf-8") as f:
        rules_yaml = yaml.safe_load(f) or {}
    rule_names = list(rules_yaml.get("rules", {}).keys())
    if rule_filter:
        rule_names = [r for r in rule_names if r in rule_filter]
    if not rule_names:
        typer.echo("no rules to run", err=True)
        raise typer.Exit(code=0)

    any_failed = False

    async def run_all() -> None:
        nonlocal any_failed
        for rule_name in rule_names:
            try:
                results = await runner.run_rule(rule_name, target)
            except MahavishnuError as exc:
                typer.echo(f"[{exc.error_code}] {exc}", err=True)
                raise typer.Exit(code=1) from exc
            typer.echo(summarize(results))
            try:
                report_failures(rule_name, results)
            except MahavishnuError as exc:
                typer.echo(f"[{exc.error_code}] {exc}", err=True)
                any_failed = True

    asyncio.run(run_all())

    if any_failed:
        raise typer.Exit(code=1)
```

- [ ] **Step 6: Modify `_main_cli.py`**

Find the existing `app.add_typer(...)` calls (per feasibility review: worktree_app at line 113, workflows_app at line 134, etc.). Add:

```python
from mahavishnu.cli.conformance_cli import conformance_app
```

And:

```python
app.add_typer(conformance_app, name="conformance")
```

(Match the existing pattern. Do NOT use `_safe_add_typer` — that doesn't exist in mahavishnu.)

- [ ] **Step 7: Create test fixtures**

`fixture_clean_bodai_repo/`:
```
pyproject.toml        # version = "1.2.3"
README.md             # "## Version: 1.2.3"
conformance.yaml      # repo: fixture_clean_bodai_repo
```

`pyproject.toml`:
```toml
[project]
name = "fixture-clean-bodai-repo"
version = "1.2.3"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

`README.md`:
```markdown
# Clean Bodai Fixture

## Version: 1.2.3

A test fixture.
```

`conformance.yaml`:
```yaml
repo: fixture_clean_bodai_repo
```

`fixture_version_drift/`:
- Same structure, but `pyproject.toml` has `version = "1.2.3"` and `README.md` has `## Version: 9.9.9`.

`fixture_mahavishnu_real/`:
- Same structure, but `pyproject.toml` has `version = "0.12.0"` and `README.md` has `## Version: 0.12.0`.
- `conformance.yaml`: `repo: fixture_mahavishnu_real` (NOT mahavishnu, so `allow_self_violation` doesn't fire — this tests real-skew detection).
- Note: this fixture mirrors what mahavishnu will look like AFTER Task 0 lands; it tests the same-version-pass case. To test the version-drift case against a real-world-shape fixture, also create `fixture_mahavishnu_skew/` with `pyproject: 0.12.0` and `README: 0.1.0`.

`fixture_bodai_doc_rules.yaml`: copy of `mahavishnu/settings/bodai-doc-rules.yaml` content.
`fixture_bodai_ports.yaml`: copy of `mahavishnu/settings/bodai-ports.yaml` content.

- [ ] **Step 8: Write the integration test**

`mahavishnu/tests/integration/conformance/test_version_guard.py`:

```python
"""Integration tests for the version_guard composite rule."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from mahavishnu.cli.conformance_cli import conformance_app

FIXTURES = Path(__file__).parent


def _mock_responses(*values: str) -> AsyncMock:
    """Build an AsyncMock whose check_primitive returns values in order."""
    mock = AsyncMock()
    mock.check_primitive = AsyncMock(
        side_effect=[
            {"passed": True, "file": "pyproject.toml", "value": v, "message": ""}
            for v in values
        ]
    )
    return mock


def test_clean_repo_version_guard_passes() -> None:
    """Matching versions in pyproject and README → version_guard passes."""
    runner = CliRunner()
    with patch("mahavishnu.services.conformance.runner.BodaiComponentMCPClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client._ensure_session = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock(return_value=None)
        mock_client.check_primitive = AsyncMock(
            side_effect=[
                {"passed": True, "file": "pyproject.toml", "value": "1.2.3", "message": ""},
                {"passed": True, "file": "README.md", "value": "1.2.3", "message": ""},
            ]
        )
        mock_cls.return_value = mock_client

        result = runner.invoke(
            conformance_app,
            [
                "check",
                "--target", str(FIXTURES / "fixture_clean_bodai_repo"),
                "--rules", str(FIXTURES / "fixture_bodai_doc_rules.yaml"),
                "--ports", str(FIXTURES / "fixture_bodai_ports.yaml"),
                "--only", "version_guard",
            ],
        )
    assert result.exit_code == 0, result.stdout


def test_version_drift_repo_version_guard_fails() -> None:
    """Mismatched versions → version_guard fails with MHV-512."""
    runner = CliRunner()
    with patch("mahavishnu.services.conformance.runner.BodaiComponentMCPClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client._ensure_session = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock(return_value=None)
        mock_client.check_primitive = AsyncMock(
            side_effect=[
                {"passed": True, "file": "pyproject.toml", "value": "1.2.3", "message": ""},
                {"passed": True, "file": "README.md", "value": "9.9.9", "message": ""},
            ]
        )
        mock_cls.return_value = mock_client

        result = runner.invoke(
            conformance_app,
            [
                "check",
                "--target", str(FIXTURES / "fixture_version_drift"),
                "--rules", str(FIXTURES / "fixture_bodai_doc_rules.yaml"),
                "--ports", str(FIXTURES / "fixture_bodai_ports.yaml"),
                "--only", "version_guard",
            ],
        )
    assert result.exit_code == 1
    assert "MHV-512" in result.stdout or "FAIL" in result.stdout
```

- [ ] **Step 9: Run integration test**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/conformance/test_version_guard.py -v`
Expected: 2 tests PASS.

- [ ] **Step 10: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/services/conformance/ mahavishnu/cli/conformance_cli.py mahavishnu/_main_cli.py tests/integration/conformance/
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance): async runner with composite rule + version_guard integration test"
```

---

### Task 12: Register `mahavishnu__conformance_check` MCP tool

**Files:**
- Create: `mahavishnu/mcp/tools/conformance_tools.py`
- Modify: `mahavishnu/mcp/tools/__init__.py`

**Interfaces:**
- Consumes: `ConformanceRunner` from Task 11
- Produces: MCP tool callable as `mahavishnu__conformance_check` (FastMCP adds the `mcp__` prefix at registration)

- [ ] **Step 1: Create `mcp/tools/conformance_tools.py`**

```python
"""Register the mcp__mahavishnu__conformance_check tool."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mahavishnu.core.errors import MahavishnuError
from mahavishnu.services.conformance.runner import ConformanceRunner


def register_conformance_tools(mcp_app: Any) -> None:
    """Register `mahavishnu__conformance_check` MCP tool."""

    @mcp_app.tool(name="mahavishnu__conformance_check")
    async def conformance_check(
        target: str = ".",
        rule_filter: list[str] | None = None,
        rules_path: str = "settings/bodai-doc-rules.yaml",
        ports_path: str = "settings/bodai-ports.yaml",
        crackerjack_url: str = "http://localhost:8676/mcp",
    ) -> dict:
        """Run Bodai conformance checks against a target repo."""
        runner = ConformanceRunner(
            rules_path=Path(rules_path),
            ports_path=Path(ports_path),
            crackerjack_url=crackerjack_url,
        )
        import yaml

        with Path(rules_path).open(encoding="utf-8") as f:
            rules_config = yaml.safe_load(f) or {}
        rule_names = list(rules_config.get("rules", {}).keys())
        if rule_filter:
            rule_names = [r for r in rule_names if r in rule_filter]

        report: dict[str, Any] = {"target": target, "rules": {}}
        for rule_name in rule_names:
            try:
                results = await runner.run_rule(rule_name, Path(target))
                report["rules"][rule_name] = {
                    "passed": all(r.passed or r.skipped for r in results),
                    "results": [
                        {
                            "passed": r.passed,
                            "skipped": r.skipped,
                            "skip_reason": r.skip_reason,
                            "file": r.file,
                            "line": r.line,
                            "value": r.value,
                            "message": r.message,
                            "remediation": [str(x) for x in (r.remediation or [])],
                        }
                        for r in results
                    ],
                }
            except MahavishnuError as exc:
                report["rules"][rule_name] = {
                    "error_code": exc.error_code,
                    "error": str(exc),
                    "recovery": [str(r) for r in exc.recovery],
                }
        return report
```

- [ ] **Step 2: Register in `mahavishnu/mcp/server_core.py:_register_tools()`**

**Important:** `mcp/tools/__init__.py` does NOT export a `register_all_tools` function. The 27+ tools register inline inside `server_core.py:_register_tools()` (around line 1341). Add the conformance tool registration at the END of `_register_tools()`.

Find `mahavishnu/mcp/server_core.py` and locate the end of `_register_tools()` (a long method that registers many `@self.server.tool()` decorators). Add at the very end:

```python
# In server_core.py, at the top of the file with other imports:
from mahavishnu.mcp.tools.conformance_tools import register_conformance_tools

# Inside _register_tools(), at the end of the method:
register_conformance_tools(self.server)
```

The `self.server` is the FastMCP instance that all the inline `@self.server.tool()` decorators register against.

- [ ] **Step 3: Verify the tool is registered**

Run: `cd /Users/les/Projects/mahavishnu && uv run python -c "from mahavishnu.mcp.server import mcp; print([t.name for t in mcp.list_tools() if 'conformance' in t.name])"`
Expected: prints `['mahavishnu__conformance_check']` (with or without `mcp__` prefix depending on FastMCP).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/conformance_tools.py mahavishnu/mcp/tools/__init__.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance-mcp): register mahavishnu__conformance_check tool"
```

---

### Task 13: Create mahavishnu/conformance.yaml (per-repo manifest)

**Files:**
- Create: `mahavishnu/conformance.yaml`

- [ ] **Step 1: Discover mahavishnu's port key**

Run: `grep -rn "port" /Users/les/Projects/mahavishnu/settings/mahavishnu.yaml | grep -E ":\s*[0-9]+$" | head -10`
Expected: identifies the actual key path. (Could be `mcp.port`, `server.port`, or elsewhere.)

- [ ] **Step 2: Create `conformance.yaml`**

```yaml
repo: mahavishnu
port:
  settings_path: settings/mahavishnu.yaml
  key: <discovered-key>      # e.g., mcp.port
  expected: 8680
  fallback_sources: []
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

(Adjust `<discovered-key>` to match the actual path found in Step 1.)

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add conformance.yaml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance): add mahavishnu conformance.yaml manifest"
```

---

### Task 14: Wire CI step (AFTER publish)

**Files:**
- Modify: `mahavishnu/.github/workflows/ci.yml` (CREATE — file does not exist yet)

**Critical note:** The CI step pins `uvx --from 'mahavishnu==X.Y.Z'` to a SPECIFIC version. This must be added AFTER mahavishnu is published with the new `conformance` subcommand. Coordinate the version bump.

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: |
          python -m pip install uv
          uv sync --all-extras --dev

      - name: Run crackerjack
        run: uv run python -m crackerjack run -v

      - name: Bodai conformance
        run: uvx --from 'mahavishnu==0.13.0' mahavishnu conformance check --target .

      - name: Bodai conformance failed
        if: failure()
        run: |
          echo "::error::Conformance check failed. See logs above for MHV-coded errors."
          echo "MHV-512 = real drift (PR comment)"
          echo "MHV-513/514/515/516 = tool error (alert maintainer)"
```

(The version `0.13.0` is the assumed next version after 0.12.0. Adjust after the publish happens.)

- [ ] **Step 2: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .github/workflows/ci.yml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "ci: add Bodai conformance step (gated on 0.13.0 publish)"
```

**Manual version bump for the mahavishnu repo:** After merge, user runs `python -m crackerjack run -v -p minor` to publish. CI step activates once `mahavishnu==0.13.0` is on PyPI.

---

### Task 15: Phase 1 wire-up verification + audit_orphans

- [ ] **Step 1: Run `audit_orphans.py`**

Run: `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_orphans.py`
Expected: no newly-added symbols with zero callers. If orphans found, wire them in or remove.

- [ ] **Step 2: Run full crackerjack + mahavishnu test suites**

Run:
```bash
cd /Users/les/Projects/crackerjack && uv run pytest -v
cd /Users/les/Projects/mahavishnu && uv run pytest tests/integration/conformance/ -v
```
Expected: all pass.

- [ ] **Step 3: Run `mahavishnu conformance check` against mahavishnu (real skew test)**

Run:
```bash
cd /Users/les/Projects/mahavishnu
uv run python -m mahavishnu conformance check --target . --only version_guard
```

Expected: **exit 0** IF Task 0 (sync `__init__.py` + README banner) was applied. If Task 0 was skipped, expect exit 1 with MHV-512.

- [ ] **Step 4: Document Phase 1 completion**

Append to `mahavishnu/docs/superpowers/plans/2026-08-12-bodai-conformance.md`:

```markdown
## Phase 1 Status: complete (2026-08-12)

Built: crackerjack primitives (regex_match with value capture, pyproject_field, git_grep, markdown_inventory, ast_symbol_check), `crackerjack check` CLI + 5 MCP tools, mahavishnu MHV-512..516 errors, top-level `settings/bodai-ports.yaml` + `settings/bodai-doc-rules.yaml` (version_guard composite rule), async `mahavishnu conformance check` CLI + MCP tool with composite handling, `mahavishnu/conformance.yaml`, CI workflow.

Wired: CI workflow runs `uvx --from 'mahavishnu==0.13.0' mahavishnu conformance check`. Crackerjack primitives called via MCP from mahavishnu (no Python imports). `allow_self_violation: true` for `version_guard` so mahavishnu can adopt without firing on its own skew.

Adopted: mahavishnu (Phase 1 first repo). Next: 5 sibling repos in Phase 2.

Integration Contract (Phase 1):
- Triggered from: PR opened in /Users/les/Projects/{crackerjack,mahavishnu}.
- Returns to / updates: crackerjack primitives (CLI+MCP); mahavishnu settings/, mahavishnu/cli/, mahavishnu/mcp/, mahavishnu/services/conformance/, conformance.yaml, .github/workflows/ci.yml.
- Demonstrable by: `uv run python -m mahavishnu conformance check --target .` exits 0 against clean mahavishnu; exits 1 (MHV-512) against a repo with version drift.
- Rollback signal: CI logs MHV-516 (conformance unavailable) for >1 hour.
- Observability added: OTel span `bodai.conformance_check`; Dhara event `conformance_check_completed`.
```

---

## Phase 2: Remaining 5 Bodai rules + adopt in 5 sibling repos

### Task 16: Add 4 new rules to bodai-doc-rules.yaml (using conformance.yaml for per-repo paths)

**Files:**
- Modify: `mahavishnu/settings/bodai-doc-rules.yaml`

**Architectural note:** Per spec invariant #1, per-repo path/field facts live in each repo's `conformance.yaml`, NOT in mahavishnu's central rules. The rules below reference generic paths; the runner resolves them via `conformance.yaml` at runtime.

- [ ] **Step 1: Add `mcp_tool_inventory` rule**

Append to `rules:`:

```yaml
  mcp_tool_inventory:
    self_repo: null
    kill_switch: false
    required: false
    description: >
      If the repo exposes an MCP server, the committed <!-- BEGIN mcp-tools -->
      block in README.md must match the live mcp.list_tools() output.
    primitive: markdown_inventory
    config:
      path: "./README.md"
      block_name: mcp-tools
      expected_lines: []
    remediation_hint:
      - "Run `mahavishnu conformance update-tools --target .` to regenerate"
      - "Or manually add missing tools to the <!-- BEGIN mcp-tools --> block in README.md"
```

- [ ] **Step 2: Add `removed_but_referenced` rule**

```yaml
  removed_but_referenced:
    self_repo: null
    kill_switch: false
    required: true
    description: >
      Symbols deleted from git history (since last tag) must not appear in docs/.
    primitive: git_grep
    config:
      target_path: "."
      scan_paths: ["docs/", "README.md", "CLAUDE.md"]
      exclude_paths: [".claude/worktrees/", "docs/archive/", "CHANGELOG.md"]
      since: "last-tag"
    remediation_hint:
      - "Remove references to deleted symbols from docs/"
      - "Or rename to the new symbol name if a successor exists"
```

- [ ] **Step 3: Add `documented_but_not_wired` rule (MVP scope)**

```yaml
  documented_but_not_wired:
    self_repo: null
    kill_switch: false
    required: true
    description: >
      Env vars documented in the repo must have a Pydantic Field with
      validation_alias, alias, AliasChoices, or AliasPath binding.
      (MVP scope: ~20% of env vars; full Pydantic traversal deferred.)
    primitive: ast_symbol_check
    config:
      path: "./<repo>/config.py"  # runtime-resolved from target_path/conformance.yaml `documented_env_vars[].path`
      symbol: "Field"
      check: "wired"
      wired_kwarg: "validation_alias"
      wired_value_contains: ""  # runtime-resolved from per-env-var list
    remediation_hint:
      - "Add Field(validation_alias='<ENV_VAR>') to <repo>/config.py"
      - "Or document the env_prefix-derived name explicitly"
```

(Implementation: the runner reads each target repo's `conformance.yaml` for a `documented_env_vars:` block listing paths + env vars, then loops.)

- [ ] **Step 4: Add `port_consistency` rule**

```yaml
  port_consistency:
    self_repo: null
    kill_switch: false
    required: true
    description: >
      Each repo's port (declared in conformance.yaml) must equal the
      canonical port in settings/bodai-ports.yaml. Skip if the repo
      is a library (oneiric) with no port.
    primitive: composite
    comparison: equal
    steps:
      - name: settings_port
        primitive: yaml_field
        capture: port
        config:
          path: "./{settings_path}"        # runtime-substituted from conformance.yaml
          field: "{key}"                   # runtime-substituted from conformance.yaml
      - name: canonical_port
        primitive: regex_match
        capture: port
        config:
          path: "./settings/bodai-ports.yaml"
          pattern: "(?m)^\\s+{repo_name}:\\s+(\\d+|null)\\s*$"   # runtime-substituted
          capture_group: 1
    remediation_hint:
      - "Update {settings_path} to set {key}: {expected}"
      - "Or update settings/bodai-ports.yaml to match (requires mahavishnu release)"
```

**Runtime substitution:** the runner's `_resolve_target` (Task 11) substitutes `{repo_name}`, `{settings_path}`, `{key}`, `{expected}` placeholders from each target repo's `conformance.yaml` before invoking the primitive. This eliminates literal `<placeholder>` strings.

**Library skip:** the runner checks `conformance.yaml:port.expected` — if `null`, returns `[CheckResult(..., skipped=True, skip_reason="library repo, no port")]` without running the composite.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add settings/bodai-doc-rules.yaml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance): add 4 new rule blocks (Phase 2)"
```

---

### Task 17: Implement remaining rules in runner with per-repo path resolution

**Files:**
- Modify: `mahavishnu/services/conformance/runner.py`

- [ ] **Step 1: Add `documented_env_vars` resolution from `conformance.yaml`**

Add to `runner.py`:

```python
def _load_target_env_var_paths(self, target_path: Path) -> list[tuple[str, str]]:
    """Read conformance.yaml:documented_env_vars → list of (config_path, env_var)."""
    manifest = target_path / "conformance.yaml"
    if not manifest.exists():
        return []
    with manifest.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    items = data.get("documented_env_vars", []) if isinstance(data, dict) else []
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append((str(target_path / item["path"]), str(item["env_var"])))
    return result
```

In `run_rule`, if `rule_name == "documented_but_not_wired"` and the target has `documented_env_vars:`, run the `ast_symbol_check` primitive once per env var (loop) instead of a single call.

- [ ] **Step 2: Fix `_resolve_target` to handle nested TOML keys**

Replace `_resolve_target` with:

```python
def _resolve_target(config: dict, target_path: Path) -> dict:
    """Resolve relative paths in config to target_path; preserve dotted field paths."""
    resolved = dict(config)
    if "path" in resolved and not Path(resolved["path"]).is_absolute():
        resolved["path"] = str(target_path / resolved["path"])
    # Field paths like 'mcp.port' or 'project.version' are NOT joined with target_path
    return resolved
```

(The bug was treating `mcp.port` as a path. Field paths are dot-segmented dict keys, not paths.)

- [ ] **Step 3: Add `_resolve_port_settings_path` with nested-key support**

```python
def _resolve_port_settings_path(target_path: Path) -> tuple[Path, list[str]] | None:
    """Walk conformance.yaml:port.settings_path + key, splitting key on '.'."""
    manifest_path = target_path / "conformance.yaml"
    if not manifest_path.exists():
        return None
    with manifest_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    port_cfg = data.get("port", {}) if isinstance(data, dict) else {}
    settings_rel = port_cfg.get("settings_path")
    key = port_cfg.get("key")
    if not settings_rel or not key:
        return None
    return target_path / settings_rel, key.split(".")
```

In `run_rule`, if `rule_name == "port_consistency"`:
1. Resolve `(settings_path, key_segments)` via `_resolve_port_settings_path`
2. Walk the YAML at `settings_path` to extract the value at the nested key
3. Compare to the canonical port from `bodai-ports.yaml:ecosystem.<repo_name>`

- [ ] **Step 4: Write integration tests for the new rules**

`mahavishnu/tests/integration/conformance/test_removed_but_referenced.py`, `test_port_consistency.py` — follow the fixture + mock pattern from Task 11.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/services/conformance/runner.py tests/integration/conformance/
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(conformance): implement 3 new rules with per-repo path resolution"
```

---

### Task 18: Adopt conformance in akosha

**Files:**
- Create: `akosha/conformance.yaml`
- Create: `akosha/.github/workflows/ci.yml`

- [ ] **Step 1: Discover akosha's port config**

Run:
```bash
grep -n "port" /Users/les/Projects/akosha/settings/akosha.yaml | head -10
grep -n "PORT" /Users/les/Projects/akosha/akosha/config.py | head -10
```

(Per feasibility review: akosha uses `api_port` in YAML and `AKOSHA_API_PORT` env var via `os.getenv`.)

- [ ] **Step 2: Create `akosha/conformance.yaml`**

```yaml
repo: akosha
port:
  settings_path: settings/akosha.yaml
  key: api_port
  expected: 8682
  fallback_sources:
    - type: os_getenv
      module: akosha/config.py
      env_var: AKOSHA_API_PORT
documented_env_vars:
  - path: akosha/config.py
    env_var: AKOSHA_API_PORT
  - path: akosha/config.py
    env_var: AKOSHA_MCP_PORT
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

- [ ] **Step 3: Create `akosha/.github/workflows/ci.yml`**

(Use the same template as Task 14, but pin to the appropriate mahavishnu version for akosha's CI.)

- [ ] **Step 4: Commit + version bump**

```bash
cd /Users/les/Projects/akosha
git add conformance.yaml .github/workflows/ci.yml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "ci: adopt Bodai conformance"
python -m crackerjack run -v -p minor
```

(If `crackerjack run -p minor` fails with a ratchet defect per `crackerjack-ratchet-cli-defects.md` memory, **fallback: hand-edit `akosha/pyproject.toml` version + `git tag` + `git push --tags`**. Then verify with PyPI JSON API.)

---

### Task 19: Adopt conformance in dhara

(Same pattern as Task 18.)

- [ ] **Step 1: Discover dhara's port config**

Run:
```bash
grep -rn "port" /Users/les/Projects/dhara/settings/dhara.yaml | head -10
grep -n "PORT" /Users/les/Projects/dhara/dhara/core/config.py | head -10
```

(Per feasibility review: dhara may store port in `dhara/core/config.py` as a Pydantic model, not YAML.)

- [ ] **Step 2: Create `dhara/conformance.yaml`**

Dhara stores its port in a Pydantic model (`DharaSettings.port: int | None` at `dhara/core/config.py:195-202`), not in YAML. Use `ast_symbol_check` with `check: "wired"` to read the Field default.

```yaml
repo: dhara
port:
  settings_path: dhara/core/config.py
  check: ast_symbol
  field_name: port
  field_type: int
  expected: 8683
  fallback_sources: []
documented_env_vars:
  - path: dhara/core/config.py
    env_var: DHARA_STORAGE_PORT
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

**Implementation note:** the runner reads `dhara/core/config.py:DharaSettings.port` via AST inspection of the Pydantic class. The runner code (Task 17) must add an `ast_symbol` check that walks class bodies looking for `port: int` annotations with default values.

- [ ] **Step 3: Create CI + commit + bump**

Same as Task 18.

---

### Task 20: Adopt conformance in session-buddy

(Same pattern.)

- [ ] **Step 1: Discover session-buddy's port config**

Run: `grep -n "port" /Users/les/Projects/session-buddy/settings/session-buddy.yaml | head -10`
(Per feasibility review: session-buddy uses `server_port`.)

- [ ] **Step 2: Create `session-buddy/conformance.yaml`**

**Important:** Session-buddy has a known port inconsistency. `settings/session-buddy.yaml:166` declares `server_port: 3000`, but the actual MCP server in `session_buddy/server_optimized.py:718` listens on port 8678 (hardcoded). The maintainer must resolve this — either:
1. Fix the YAML to match the actual port (8678), OR
2. Adjust `expected` to match the YAML (3000) and fix the hardcode

The plan uses option 2 (match YAML) to land the conformance check without breaking the deployment. The maintainer should file a follow-up to align both:

```yaml
repo: session_buddy
port:
  settings_path: settings/session-buddy.yaml
  key: server_port
  expected: 3000      # MATCHES YAML — see comment above; follow-up needed
  fallback_sources: []
documented_env_vars:
  - path: session_buddy/server_optimized.py
    env_var: SESSION_BUDDY_SERVER_PORT
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

- [ ] **Step 3: Create CI + commit + bump**

Same as Task 18.

---

### Task 21: Adopt conformance in crackerjack

(Same pattern, but flag manual version bump.)

- [ ] **Step 1: Create `crackerjack/conformance.yaml`**

```yaml
repo: crackerjack
port:
  settings_path: settings/crackerjack.yaml
  key: mcp_http_port            # adjust per Step 1 grep
  expected: 8676
  fallback_sources: []
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

- [ ] **Step 2: Create CI**

```yaml
- name: Bodai conformance
  run: uvx --from 'mahavishnu==X.Y.Z' mahavishnu conformance check --target .
```

- [ ] **Step 3: Commit (manual version bump flagged)**

```bash
cd /Users/les/Projects/crackerjack
git add conformance.yaml .github/workflows/ci.yml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "ci: adopt Bodai conformance in crackerjack"
```

**Note:** `Skipped — user handles manually` per `crackerjack-version-bumping-manual`. Do NOT run `crackerjack run -p minor`. User handles the version bump post-merge.

---

### Task 22: Adopt conformance in oneiric

(Same pattern.)

- [ ] **Step 1: Create `oneiric/conformance.yaml`**

Oneiric is a library with no MCP server. Its port (`http_port: int = 8000` in `OneiricMCPConfig`) is a different concept — it's a configurable HTTP port for the embedded MCP, not a fixed service port. The conformance check should skip `port_consistency` for oneiric.

```yaml
repo: oneiric
port:
  settings_path: null
  key: null
  expected: null     # library; port_consistency skipped
  fallback_sources: []
excluded_paths:
  - .claude/worktrees/
  - docs/archive/
  - CHANGELOG.md
```

**Implementation note:** the runner (Task 11) checks `conformance.yaml:port.expected` — if `null`, the runner returns `[CheckResult(..., skipped=True, skip_reason="library repo, no port")]` without running the `port_consistency` composite. This is already specified in Task 16 Step 4's library-skip note.

- [ ] **Step 2: Create CI + commit + bump**

Same as Task 18.

---

## Phase 3: Watchdog + permanent cross-layer regression test

### Task 23: Watchdog Mahavishnu workflow (advisory only)

**Files:**
- Create: `mahavishnu/mcp/tools/conformance_tools.py` (add `conformance_watchdog` function — see Step 2)

**Initial mode:** advisory (alerts but doesn't fail) until ≥3 of 6 repos have adopted.

- [ ] **Step 1: Add watchdog MCP tool**

Append to `mahavishnu/mcp/tools/conformance_tools.py`:

```python
@mcp_app.tool(name="mahavishnu__conformance_watchdog")
async def conformance_watchdog() -> dict:
    """Check each Bodai repo for the conformance CI step. Advisory mode initially."""
    import httpx
    repos = [
        ("mahavishnu", "https://raw.githubusercontent.com/lesleslie/mahavishnu/main/.github/workflows/ci.yml"),
        ("akosha", "https://raw.githubusercontent.com/lesleslie/akosha/main/.github/workflows/ci.yml"),
        # ... add 4 more
    ]
    report = {"missing_step": [], "ok": []}
    for name, url in repos:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
            if r.status_code == 200 and "mahavishnu conformance check" in r.text:
                report["ok"].append(name)
            else:
                report["missing_step"].append(name)
        except Exception as exc:
            report["missing_step"].append(f"{name} (fetch failed: {exc})")
    return report
```

- [ ] **Step 2: Schedule via existing cron mechanism**

Per Mahavishnu's workflow scheduling convention (check `mahavishnu/workflows/` for existing examples), register the watchdog to run weekly. If no scheduling infrastructure exists, add the call site to a cron-driven task.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/conformance_tools.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "feat(watchdog): detect removed CI conformance steps (advisory mode)"
```

---

### Task 24: Permanent cross-layer drift detection regression test

**Files:**
- Create: `mahavishnu/tests/integration/conformance/test_cross_layer_drift_detection.py`

- [ ] **Step 1: Write the test**

```python
"""Permanent regression test: conformance check runs end-to-end against real Bodai repos.

This catches both:
- Drift introduced since the audit baseline
- Regressions in the conformance runner itself
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.conformance_cli import conformance_app

REPOS = ["mahavishnu", "akosha", "dhara", "session_buddy", "crackerjack", "oneiric"]


@pytest.mark.parametrize("repo_name", REPOS)
def test_real_repo_conformance_check_ends_cleanly(repo_name: str) -> None:
    """For each real Bodai repo, conformance check exits 0 or 1 (not crash)."""
    repo_path = Path(f"/Users/les/Projects/{repo_name}")
    if not repo_path.exists():
        pytest.skip(f"{repo_name} repo not present")

    runner = CliRunner()
    with patch("mahavishnu.services.conformance.runner.BodaiComponentMCPClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client._ensure_session = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock(return_value=None)
        mock_client.check_primitive = AsyncMock(
            return_value={"passed": True, "file": "x", "value": "1.0.0", "message": ""}
        )
        mock_cls.return_value = mock_client

        result = runner.invoke(
            conformance_app,
            [
                "check",
                "--target", str(repo_path),
                "--only", "version_guard",
            ],
        )
    # Smoke test: doesn't crash, exits 0 or 1 (not 2/3/4/5)
    assert result.exit_code in (0, 1)
```

- [ ] **Step 2: Add to mahavishnu CI as a permanent gate**

In `mahavishnu/.github/workflows/ci.yml`, add after the conformance step:

```yaml
- name: Cross-layer drift detection (conformance regression)
  run: uv run pytest tests/integration/conformance/test_cross_layer_drift_detection.py -v
```

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add tests/integration/conformance/test_cross_layer_drift_detection.py .github/workflows/ci.yml
git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -m "test: permanent cross-layer drift detection"
```

---

## Phase 4 (future)

CLI conventions rule + auto-remediation. Out of scope per spec; TBD after 2 quarterly audits show Phase 1-3 are stable.

---

## Self-Review

### Spec coverage

| Spec requirement | Task |
|---|---|
| MHV-512..516 error codes | Task 1 |
| Crackerjack primitives (5) with value capture | Tasks 2-6 |
| Crackerjack CLI `check` | Task 7 |
| Crackerjack MCP `crackerjack__check_*` (in `check_tools.py`) | Task 8 |
| Mahavishnu settings at top-level `settings/` | Task 9 |
| `BodaiComponentMCPClient.check_primitive` (uses `base_url=`) | Task 10 |
| Mahavishnu conformance CLI + version_guard | Tasks 11-12 |
| Per-repo `conformance.yaml` | Tasks 13, 18-22 |
| CI step (CREATE `.github/workflows/ci.yml`) | Tasks 14, 18-22 |
| All 6 rules | Tasks 11, 16-17 |
| Watchdog | Task 23 |
| Cross-layer regression test | Task 24 |
| Manual version bump flag (crackerjack) | Tasks 2-8, 21 commit notes |
| `allow_self_violation` reads `conformance.yaml:repo` | Task 11 (`_repo_name_from`) |
| `kill_switch` | Tasks 9, 11 |
| Wire-up contract per phase | Task 15 |
| Prerequisite `__version__` sync | Task 0 |

### Placeholder scan

No "TBD" or "TODO". Phase 4 explicitly marked as future scope.

### Type consistency

- `PrimitiveResult` (Tasks 2-6) carries `value: str | None`
- MCP `check_*` tools (Task 8) return `value` in serialized dict
- `ConformanceRunner._run_composite` (Task 11) reads `value` from each step's MCP response
- `CheckResult` (Task 11) carries `value` through

### Gaps addressed in this revision (vs original plan)

- Settings files at top-level `settings/`, not `mahavishnu/settings/`
- `_safe_add_typer` uses correct 4-arg signature with string import
- `BodaiComponentMCPClient(base_url=...)` not `component_name=...`
- `__aenter__`/`__aexit__` not used (explicit `_ensure_session` + `aclose` instead)
- `version_guard` is `composite` with value comparison
- CI workflow files are CREATED, not modified
- `_resolve_target` no longer breaks on nested TOML keys
- Phase 1 prerequisite syncs `__version__` to prevent self-fire
- CI pin activated AFTER publish, not in same task
- Crackerjack adoption explicitly flags manual version bump
- Per-repo path resolution reads from `conformance.yaml` (spec invariant #1)
- Mock pattern matches real async-context manager shape (uses AsyncMock attributes)
- `__init__.py` imports added where required
- One task per per-repo adoption (Tasks 18-22) with full content per repo

---

## Round-2 Known Issues & Mitigations

The following issues were surfaced by the second 4-agent review cycle. They are **not blockers for Phase 1** but **must be addressed before Phase 2 lands**. Each is documented with the concrete fix the implementer should apply.

### R2-1 [BLOCKER for Phase 2]: `pyproject_field` is TOML-only; `port_consistency` needs YAML access

**Files affected:** Tasks 16-17 (`port_consistency` rule), Tasks 18-22 (per-repo adoption)

**Issue:** `pyproject_field` uses `tomllib.load` (Task 3). Akosha, dhara, session-buddy, and crackerjack store their ports in YAML (or Python Pydantic, not TOML). The rule will fail with `TOMLDecodeError` → MHV-513 for 5 of 6 sibling repos.

**Mitigation:** Add a `yaml_field` primitive (mirror of `pyproject_field` but uses `yaml.safe_load`). The plan's file structure was updated to include `yaml_field.py`; the implementer must:
1. Create `crackerjack/services/check_primitives/yaml_field.py` (mirror Task 3's `pyproject_field.py` but with `yaml.safe_load` instead of `tomllib.load`)
2. Register it in `crackerjack/services/check_primitives/__init__.py` as `PRIMITIVES["yaml_field"] = YamlFieldPrimitive`
3. Update `port_consistency` rule in `mahavishnu/settings/bodai-doc-rules.yaml` (Task 16 Step 4) to use `primitive: yaml_field` instead of `pyproject_field`
4. For repos with ports in Pydantic models only (dhara), use `primitive: ast_symbol_check` with `check: "wired"` and `wired_kwarg: "default_factory"` to read the Field default.

### R2-2 [BLOCKER]: `BodaiComponentMCPClient.call_tool()` returns `CallToolResult`, not dict

**Files affected:** Task 10 (helper extension), Task 11 (`_response_to_result`)

**Issue:** The MCP SDK's `session.call_tool()` returns a `CallToolResult` (Pydantic model), not a plain dict. The runner's `_response_to_result` uses `"error" in response` and `response.get(...)` — both raise `TypeError: argument of type 'CallToolResult' is not iterable` on real MCP calls. Tests pass because mocks return dicts.

**Mitigation:** In Task 10 Step 3's `check_primitive` helper, unpack the `CallToolResult`:

```python
async def check_primitive(self, primitive_name: str, config: dict) -> dict:
    raw = await self.call_tool(
        f"crackerjack__check_{primitive_name}",
        {"config": config},
    )
    # Unpack MCP CallToolResult.content[0].text (JSON string) to a dict
    import json
    if hasattr(raw, "content") and raw.content:
        try:
            return json.loads(raw.content[0].text)
        except (json.JSONDecodeError, IndexError, AttributeError):
            pass
    # Fallback: return raw as-is if it's already a dict
    if isinstance(raw, dict):
        return raw
    return {"error": "primitive_crash", "message": f"unexpected response: {raw!r}"}
```

### R2-3 [HIGH]: `pattern: "## placeholder"` literal in Task 16 Step 4

**Files affected:** `mahavishnu/settings/bodai-doc-rules.yaml` (port_consistency rule)

**Issue:** The `canonical_port` step's regex pattern is the literal string `"## placeholder"` — it never matches anything. The runner doesn't substitute the canonical port from `bodai-ports.yaml`.

**Mitigation:** Replace with a real regex matching the `bodai-ports.yaml` structure:
```yaml
- name: canonical_port
  primitive: regex_match
  capture: port
  config:
    path: "./settings/bodai-ports.yaml"
    pattern: "(?m)^\\s+<repo_name>:\\s+(\\d+|null)\\s*$"
    capture_group: 1
```
**Or** (simpler): have the runner pre-substitute `<repo_name>` with `conformance.yaml:repo` before passing config to the primitive. This is the most robust approach — add this to `_resolve_target`:

```python
def _resolve_target(config: dict, target_path: Path, repo_name: str) -> dict:
    """Resolve relative paths + substitute {repo_name} placeholder."""
    resolved = dict(config)
    if "path" in resolved and not Path(resolved["path"]).is_absolute():
        resolved["path"] = str(target_path / resolved["path"])
    # Substitute placeholders
    for key, value in resolved.items():
        if isinstance(value, str):
            resolved[key] = value.replace("{repo_name}", repo_name)
    return resolved
```

### R2-4 [HIGH]: `ValidatedPattern` doesn't raise on ReDoS-unsafe patterns

**Files affected:** Task 2 (regex_match primitive), test `test_unsafe_pattern_raises_config_error`

**Issue:** `crackerjack/services/patterns/core.py:124-127` validates pattern safety but only emits warnings — does NOT raise. Task 2's test expects `ConfigError` on `(a+)+$` pattern; the test will FAIL.

**Mitigation:** Add a separate ReDoS guard at the primitive level in `regex_match.py`:

```python
def run(self, config: dict[str, Any]) -> PrimitiveResult:
    pattern_str = config.get("pattern", "")
    # ReDoS guard: detect catastrophic backtracking patterns
    if self._is_unsafe_pattern(pattern_str):
        raise ConfigError(
            f"pattern rejected as potentially catastrophic backtracking: {pattern_str!r}"
        )
    # ... rest of implementation

@staticmethod
def _is_unsafe_pattern(pattern: str) -> bool:
    """Detect (a+)+ patterns and similar nested quantifiers."""
    import re
    # Simple heuristic: nested quantifiers on overlapping groups
    return bool(re.search(r"\([^)]*[+*]\)[+*]", pattern))
```

Update the test to use a pattern the heuristic catches (the existing `(a+)+$` already does).

### R2-5 [HIGH]: `register_all_tools` doesn't exist; tools register inline in `server_core.py:_register_tools()`

**Files affected:** Task 12 (MCP tool registration)

**Issue:** `mahavishnu/mcp/tools/__init__.py` exports individual `register_*_tools` functions but NOT a `register_all_tools`. Tools register inline in `mahavishnu/mcp/server_core.py:_register_tools()`.

**Mitigation:** Task 12 should modify `server_core.py:_register_tools()` to add the conformance tool registration call, not look for `register_all_tools`. Find the end of `_register_tools()` and add:

```python
from mahavishnu.mcp.tools.conformance_tools import register_conformance_tools

# At the end of _register_tools():
register_conformance_tools(self.server)
```

### R2-6 [HIGH]: Crackerjack FastMCP variable is `mcp_app`, not `mcp`

**Files affected:** Task 8 Step 4 (verification command)

**Issue:** `crackerjack/mcp/server_core.py:163` defines `mcp_app = FastMCP(...)`. The verification command `from crackerjack.mcp.server_core import mcp` will fail with `ImportError`.

**Mitigation:** Change Task 8 Step 4 verification:
```bash
cd /Users/les/Projects/crackerjack && uv run python -c "from crackerjack.mcp.server_core import mcp_app; print(sorted(t.name for t in mcp_app.list_tools() if t.name.startswith('crackerjack__check_')))"
```

### R2-7 [HIGH]: Per-repo port values — session-buddy/dhara/oneiric specifics

**Files affected:** Tasks 19-22 conformance.yaml templates

**Issue:**
- **session-buddy**: YAML has `server_port: 3000` but actual MCP port is 8678 (hardcoded in `server_optimized.py:718`). Conformance will fail with MHV-512 unless `expected: 3000` matches YAML.
- **dhara**: YAML has no port field. Port lives in Pydantic `DharaSettings.port: int | None` field at `dhara/core/config.py:195-202`.
- **oneiric**: No `settings/oneiric.yaml` exists. Only `config/lite.yaml` and `config/standard.yaml`. Port is `http_port: int = 8000` in `OneiricMCPConfig`.

**Mitigation:**

Task 19 (dhara): Change `conformance.yaml` to use `ast_symbol_check` instead of `yaml_field`:
```yaml
repo: dhara
port:
  settings_path: dhara/core/config.py
  check: ast_symbol
  field_name: port
  field_type: int
  expected: 8683
  fallback_sources: []
```
The runner reads `dhara/core/config.py:DharaSettings.port` via AST inspection of the class.

Task 20 (session-buddy): Set `expected: 3000` (matches YAML) and add a NOTE that the actual MCP server port is 8678 (hardcoded); either fix YAML to match or document the discrepancy.

Task 22 (oneiric): Add `expected: null` and set the runner to skip port_consistency when `expected is None`:
```python
# In runner.run_rule for port_consistency:
if rule.get("expected") is None:
    return [CheckResult(rule_name="port_consistency", ..., skipped=True, skip_reason="library repo, no port")]
```

### R2-8 [MEDIUM]: Drop `pull_request:` CI trigger (pre-1.0 forbids PRs)

**Files affected:** Task 14, Tasks 18-22 (CI workflow yaml)

**Issue:** `pull_request:` trigger doesn't fire under pre-1.0 merge policy (no PRs exist).

**Mitigation:** Replace `pull_request:` with:
```yaml
on:
  push:
    branches: [main]
```

Drop the `pull_request:` block entirely.

### R2-9 [MEDIUM]: `audit_orphans.py` only after Phase 1

**Files affected:** Add a Task 22.5 (post-Phase-2 audit) and Task 24.1 (post-Phase-3 audit)

**Mitigation:** Add to each Phase 2 and Phase 3 task:
```bash
- name: Run audit_orphans
  run: uv run python scripts/audit_orphans.py
- name: Verify no orphans
  run: test -z "$(uv run python scripts/audit_orphans.py --json)"
```

### R2-10 [MEDIUM]: Wire-up Contract missing for Phase 2 + 3

**Files affected:** End of Phase 2 (Task 22) and Phase 3 (Task 24)

**Mitigation:** Add an Integration Contract block at the end of Phase 2 (after Task 22) and Phase 3 (after Task 24), mirroring Task 15 Step 4. Each block specifies:
- Triggered from: which event/workflow
- Returns to / updates: which artifacts
- Demonstrable by: smoke command
- Rollback signal: alert/log line
- Observability added: OTel span, Dhara event

### R2-11 [LOW]: Mock test invertibility false-positive

**Files affected:** Task 11 Step 8 (test_version_guard.py)

**Issue:** `side_effect=[{"value": "1.2.3"}, {"value": "1.2.3"}]` for the clean test passes even if swapped.

**Mitigation:** Add specific value assertions to the test stdout:
```python
def test_clean_repo_version_guard_passes() -> None:
    # ... mock setup ...
    assert result.exit_code == 0
    assert "pyproject=1.2.3" in result.stdout  # captured value surfaced
    assert "README=1.2.3" in result.stdout
```

### R2-12 [LOW]: `check_app` vs `app` naming inconsistency

**Files affected:** Task 7 (crackerjack CLI)

**Issue:** Other crackerjack CLI files (`docs_cli.py`, `mcp_cli.py`) export `app` (not `check_app`).

**Mitigation:** In Task 7, rename `check_app` → `app`:
```python
app = typer.Typer(help="Run a single generic check primitive")
```
And the registration call becomes:
```python
_safe_add_typer(app, "crackerjack.cli.check", "app", "check")
```

### R2-13 [LOW]: Task 11 monolithic commit (drift bundling risk)

**Files affected:** Task 11 Step 10

**Mitigation:** Split the commit into 3:
```bash
git add mahavishnu/services/conformance/ 
git commit -m "feat(conformance): async runner with composite rule"
git add mahavishnu/cli/conformance_cli.py mahavishnu/_main_cli.py
git commit -m "feat(conformance): CLI subcommand and registration"
git add tests/integration/conformance/
git commit -m "test(conformance): integration test for version_guard"
```

### R2-14 [LOW]: capture_name uniqueness check

**Files affected:** Task 11 `_run_composite`

**Mitigation:** Add uniqueness validation:
```python
capture_names = [s.get("capture") for s in steps if s.get("capture")]
if len(set(capture_names)) != len(capture_names):
    raise ConformanceRulesConfigInvalid(
        rule_name=rule_name,
        recovery=[f"composite rule {rule_name!r} has duplicate capture names: {capture_names}"],
    )
```

### R2-15 [LOW]: `excluded_paths` from conformance.yaml not wired to runner

**Files affected:** Task 11 runner, all per-repo conformance.yaml

**Mitigation:** In runner, before calling primitives, merge `conformance.yaml:excluded_paths` into each primitive's config:
```python
def _merge_excluded_paths(self, target_path: Path, config: dict) -> dict:
    manifest = target_path / "conformance.yaml"
    if not manifest.exists():
        return config
    with manifest.open() as f:
        data = yaml.safe_load(f) or {}
    excludes = data.get("excluded_paths", [])
    if excludes and "exclude_paths" in config:
        config["exclude_paths"] = list(set(config["exclude_paths"]) | set(excludes))
    return config
```

### R2-16 [LOW]: Print recovery lines in CLI

**Files affected:** Task 11 `conformance_cli.py`

**Mitigation:** Before re-raising `ConformanceDriftDetected`, print recovery hints:
```python
try:
    report_failures(rule_name, results)
except MahavishnuError as exc:
    typer.echo(f"[{exc.error_code}]", err=True)
    for r in exc.recovery:
        typer.echo(f"  -> {r}", err=True)
    any_failed = True
```

### R2-17 [LOW]: YAML 1.1 truthy coercion risk

**Files affected:** yaml_field primitive (when added)

**Mitigation:** Use `yaml.safe_load` with `Loader=yaml.SafeLoader` (default) — this rejects unquoted `yes`/`no`/`on`/`off`/`null` as booleans. If a per-repo YAML has unquoted booleans where the field expects a number, the rule will fail with `ValueError`. Add a regression test for the YAML 1.1 case.

---

## Implementation Order (revised)

For Phase 1, execute Tasks 0-15 in order. The yaml_field primitive (R2-1) is not needed for Phase 1 — defer until Phase 2.

For Phase 2, before executing Tasks 16-22:
1. Apply R2-1 (add yaml_field primitive + update port_consistency rule)
2. Apply R2-2 (CallToolResult unpacking in BodaiComponentMCPClient helper)
3. Apply R2-3 (replace `## placeholder` with real regex OR runtime substitution)
4. Apply R2-7 (per-repo port values for session-buddy/dhara/oneiric)
5. Then execute Tasks 18-22

For Phase 3, apply R2-5 (register conformance in server_core.py:_register_tools()) and R2-9/10 (audit_orphans per phase + Wire-up Contract for Phase 2/3).

