# Crackerjack scripts/examples coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/` and `examples/` to Crackerjack's fast-hook ruff-check, ruff-format, codespell, and tc-refs coverage, with universal compatibility across all 14 Bodai repos via CLI-injected per-file-ignores. Also rewrite `audit_type_checking_runtime_refs.py` to be ruff-clean.

**Architecture:** Modify `crackerjack/config/tool_commands.py` to add `./scripts ./examples` to ruff-check, ruff-format, codespell, and tc-refs target paths. Inject a hardcoded universal 9-rule starter pack via ruff's `--per-file-ignores=<path>` CLI flag. The starter pack file is written lazily to `.crackerjack_cache/scripts_examples_per_file_ignores.toml` in the consumer repo. Rewrite `crackerjack/audit_type_checking_runtime_refs.py` to silence 12 violations through surgical rule-by-rule fixes.

**Tech Stack:** Python 3.14, ruff (with `--per-file-ignores` CLI flag), pytest, mypy.

**Spec:** `docs/superpowers/specs/2026-09-05-crackerjack-scripts-examples-coverage-design.md`

## Global Constraints

- **Bodai pre-1.0 merge policy**: NO PRs. Commit directly to local main (5 commits total).
- **Python 3.14 syntax**: `X | None`, `list[str]`, `pathlib.Path`. Target version is `py314`.
- **`from __future__ import annotations`** as first line of every source file (after module docstring).
- **Type annotations** on all function args with default `None` (mypy `no_implicit_optional = true`).
- **No `Any`** in tool inputs; escape via `TYPE_CHECKING` and typed protocols.
- **`crackerjack` runs from consumer repo cwd**: `Path.cwd()` returns the consumer repo root. Use this for repo-relative paths.
- **TDD discipline**: write failing test first, verify it fails, implement minimal code, verify pass, commit.
- **No per-repo `pyproject.toml` edits** — the universal starter pack travels with crackerjack via CLI flag.
- **All commits land on local main of `/Users/les/Projects/crackerjack`**, not mahavishnu.

---

## File Structure

**New files (in `/Users/les/Projects/crackerjack`):**

| File | Responsibility |
|---|---|
| `crackerjack/config/per_file_ignores.py` | Universal starter pack constants + idempotent file-creation helper |
| `tests/unit/config/test_per_file_ignores.py` | 11 tests covering starter pack contents, file lifecycle, ruff acceptance |

**Modified files (in `/Users/les/Projects/crackerjack`):**

| File | Responsibility |
|---|---|
| `crackerjack/config/tool_commands.py` | Add `./scripts ./examples` to 4 tool commands; inject `--per-file-ignores` for ruff-check; extract shared target-list helper |
| `crackerjack/audit_type_checking_runtime_refs.py` | Rewrite to silence 12 violations via surgical fixes; `chmod +x` for EXE001 |
| `tests/config/test_tool_commands.py` | Update `test_target_directories_specified`; add 2 new tests for codespell + tc-refs |
| `tests/unit/test_audit_type_checking_runtime_refs.py` (or extend existing) | 4 regression tests for behavior preservation + ruff-clean verification |

---

### Task 1: Add per_file_ignores module (Commit 1)

**Files:**
- Create: `crackerjack/config/per_file_ignores.py`
- Create: `tests/unit/config/test_per_file_ignores.py`

**Interfaces (consumed by Task 2, 3):**
- `UNIVERSAL_PER_FILE_IGNORES: dict[str, list[str]]` — the 4-pattern starter pack
- `ensure_per_file_ignores_file(repo_root: Path) -> Path` — writes the TOML file, returns its path

**Step 1.1: Write failing tests for the starter pack contents**

Create `tests/unit/config/test_per_file_ignores.py`:

```python
"""Tests for the universal per-file-ignores starter pack mechanism."""
from __future__ import annotations

from pathlib import Path

import pytest

from crackerjack.config.per_file_ignores import (
    UNIVERSAL_PER_FILE_IGNORES,
    ensure_per_file_ignores_file,
)


class TestUniversalPerFileIgnores:
    """The starter pack should contain exactly the rules we agreed on."""

    def test_scripts_starter_pack_has_universal_rules(self) -> None:
        scripts_rules = UNIVERSAL_PER_FILE_IGNORES["scripts/**/*.py"]
        expected = {
            "EXE001", "BLE001", "F541", "C901",
            "SIM102", "SIM103", "SIM114", "S110", "PLW1510",
        }
        assert set(scripts_rules) == expected

    def test_examples_starter_pack_inherits_and_extends(self) -> None:
        examples_rules = UNIVERSAL_PER_FILE_IGNORES["examples/**/*.py"]
        scripts_rules = UNIVERSAL_PER_FILE_IGNORES["scripts/**/*.py"]
        for rule in scripts_rules:
            assert rule in examples_rules, f"missing {rule} in examples"
        assert "N999" in examples_rules
        assert "RUF100" in examples_rules
        assert "FURB162" in examples_rules

    def test_no_tc003_in_starter_pack(self) -> None:
        """TC003 catches real runtime bugs. Must NOT be silenced."""
        for rules in UNIVERSAL_PER_FILE_IGNORES.values():
            assert "TC003" not in rules

    def test_underscore_prefixed_scripts_get_n999(self) -> None:
        assert UNIVERSAL_PER_FILE_IGNORES["scripts/_*.py"] == ["N999"]

    def test_backup_files_get_all_silenced(self) -> None:
        assert UNIVERSAL_PER_FILE_IGNORES["**/*.bak[0-9]"] == ["ALL"]```

**Step 1.2: Run the test to verify it fails**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/config/test_per_file_ignores.py -v
```

Expected: `ImportError: cannot import name 'UNIVERSAL_PER_FILE_IGNORES' from 'crackerjack.config.per_file_ignores'` (or `ModuleNotFoundError` if file doesn't exist).

**Step 1.3: Implement the starter pack constants**

Create `crackerjack/config/per_file_ignores.py`:

```python
"""Universal per-file-ignores injected via ruff's --per-file-ignores flag.

The starter pack silences ecosystem-wide patterns that fire too noisilyin admin/demo code to be worth enforcing repo-by-repo. Per-repo rules(intentionally) stay OUT of this module — they're addressed per-repo.

Format: a TOML file that ruff accepts via --per-file-ignores=<path>.
Ruff merges these ignores with whatever's in the consumer's pyproject.toml
(additive, not overriding).
"""
from __future__ import annotations

from pathlib import Path

# TOML keys are glob patterns; values are lists of ruff rule IDs.
# Use "ALL" to silence every rule for a pattern (e.g., stale .bak files).
UNIVERSAL_PER_FILE_IGNORES: dict[str, list[str]] = {
    "scripts/**/*.py": [
        "EXE001",   # shebang-not-executable (78 fires, 6 repos)
        "BLE001",   # blind-except (56 fires, 7 repos)
        "F541",     # f-string-missing-placeholders (32 fires, 6 repos)
        "C901",     # complex-structure (12 fires, 6 repos)
        "SIM102",   # collapsible-if (11 fires, 6 repos)
        "SIM103",   # needless-bool (7 fires, 6 repos)
        "SIM114",   # if-with-same-arms (8 fires, 7 repos)
        "S110",     # try-except-pass (10 fires, 2 repos)
        "PLW1510",  # subprocess-run-without-check (9 fires, 3 repos)
    ],
    "examples/**/*.py": [
        # Same as scripts/** + 3 examples-specific additions:
        "EXE001",
        "BLE001",
        "F541",
        "C901",
        "SIM102",
        "SIM103",
        "SIM114",
        "S110",
        "PLW1510",
        # Examples-only additions:
        "N999",     # invalid-module-name (underscored demo filenames)
        "RUF100",   # unused-noqa in example files
        "FURB162",  # fromisoformat-replace-z
 ],
    "scripts/_*.py": ["N999"],  # underscore-prefixed one-shot scripts
    "**/*.bak[0-9]": ["ALL"],  # stale backup files (crackerjack has 2)
}

# Cached file path (deterministic — concurrent runs race-safely overwrite).
_PER_FILE_IGNORES_FILENAME = ".crackerjack_cache/scripts_examples_per_file_ignores.toml"


def ensure_per_file_ignores_file(repo_root: Path) -> Path:
    """Write the starter pack TOML to .crackerjack_cache/ if not present.

    Returns the file path for use with `ruff --per-file-ignores=<path>`.
    Idempotent — re-running is a no-op if file exists.
    """
    target = repo_root / _PER_FILE_IGNORES_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        lines: list[str] = []
        for pattern, rules in UNIVERSAL_PER_FILE_IGNORES.items():
            rule_str = ", ".join(f'"{r}"' for r in rules)
            lines.append(f'"{pattern}" = [{rule_str}]')
        target.write_text("\n".join(lines) + "\n")
    return target
```

**Step 1.4: Run the starter pack tests to verify they pass**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/config/test_per_file_ignores.py::TestUniversalPerFileIgnores -v
```

Expected: 5 passed.

**Step 1.5: Write failing tests for `ensure_per_file_ignores_file`**

Append to `tests/unit/config/test_per_file_ignores.py`:

```python
class TestEnsurePerFileIgnoresFile:
    """The file lifecycle: create, idempotent, valid TOML."""

    def test_creates_file_with_correct_path(self, tmp_path: Path) -> None:
        result = ensure_per_file_ignores_file(tmp_path)
        assert result == tmp_path / ".crackerjack_cache" / "scripts_examples_per_file_ignores.toml"
        assert result.exists()

    def test_creates_cache_dir_if_missing(self, tmp_path: Path) -> None:
        assert not (tmp_path / ".crackerjack_cache").exists()
        ensure_per_file_ignores_file(tmp_path)
        assert (tmp_path / ".crackerjack_cache").exists()

    def test_idempotent_on_repeat_calls(self, tmp_path: Path) -> None:
        first = ensure_per_file_ignores_file(tmp_path)
        first_mtime = first.stat().st_mtime_ns
        second = ensure_per_file_ignores_file(tmp_path)
        assert first == second
        assert second.stat().st_mtime_ns == first_mtime

    def test_generated_toml_parses_with_tomllib(self, tmp_path: Path) -> None:
        import tomllib
        result = ensure_per_file_ignores_file(tmp_path)
        content = result.read_text()
        parsed = tomllib.loads(content)
        assert "scripts/**/*.py" in parsed
        assert "examples/**/*.py" in parsed
        assert "scripts/_*.py" in parsed
        assert "**/*.bak[0-9]" in parsed

    def test_generated_toml_has_ruff_compatible_format(self, tmp_path: Path) -> None:
        """Ruff parses --per-file-ignores files with double-quoted keys."""
        result = ensure_per_file_ignores_file(tmp_path)
        content = result.read_text()
        for line in content.splitlines():
            assert line.startswith('"'), f"Bad line: {line!r}"
            assert "=" in line, f"Bad line: {line!r}"


@pytest.mark.integration
class TestRuffAcceptsGeneratedFile:
    """Verify ruff actually parses our generated file correctly."""

    def test_ruff_check_with_generated_ignores_does_not_error(
        self, tmp_path: Path
    ) -> None:
        """If ruff rejects our generated TOML, the hook would fail loudly."""
        import subprocess
        per_file_ignores = ensure_per_file_ignores_file(tmp_path)
        sample_dir = tmp_path / "scripts"
        sample_dir.mkdir()
        sample = sample_dir / "sample.py"
        sample.write_text("#!/usr/bin/env python3\nprint('hello')\n")
        result = subprocess.run(
            ["ruff", "check",
 "--per-file-ignores", str(per_file_ignores),
             "--no-fix", str(sample_dir)],
            capture_output=True, text=True,
 cwd=tmp_path,
        )
        assert result.returncode == 0, (
            f"ruff rejected our per-file-ignores file:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
```

**Step 1.6: Run tests to verify they pass**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/config/test_per_file_ignores.py -v
```

Expected: All 11 tests pass (5 + 5 + 1 integration).

**Step 1.7: Verify full test suite still passes**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/ tests/config/ -x
```

Expected: All tests pass (no regressions).

**Step 1.8: Verify ruff + mypy pass on the new file**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/ruff check crackerjack/config/per_file_ignores.py tests/unit/config/test_per_file_ignores.py
.venv/bin/ruff format --check crackerjack/config/per_file_ignores.py tests/unit/config/test_per_file_ignores.py
.venv/bin/mypy crackerjack/config/per_file_ignores.py
```

Expected: clean.

**Step 1.9: Commit**

Run:
```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/config/per_file_ignores.py tests/unit/config/test_per_file_ignores.py
git commit -m "$(cat <<'EOF'
feat(hooks): add universal per-file-ignores starter pack for scripts/examples

Crackerjack's fast hooks now inject a 9-rule starter pack via ruff's
--per-file-ignores CLI flag, silencing ecosystem-wide patterns that fire
too noisily in admin/demo code (EXE001, BLE001, F541, C901, SIM*).
The starter pack travels with crackerjack; no per-repo config edits needed.

This is commit 1 of 5 for scripts/examples coverage in fast hooks.
Spec: docs/superpowers/specs/2026-09-05-crackerjack-scripts-examples-coverage-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Update ruff-check + ruff-format targets (Commit 2)

**Files:**
- Modify: `crackerjack/config/tool_commands.py` (ruff-check, ruff-format entries; extract `_build_targets` helper)
- Modify: `tests/config/test_tool_commands.py` (`test_target_directories_specified`)

**Interfaces:**
- Consumes: `ensure_per_file_ignores_file(repo_root: Path) -> Path` from Task 1

**Step 2.1: Write failing test for new ruff-check + ruff-format targets**

Modify `tests/config/test_tool_commands.py` — replace `test_target_directories_specified` and add new tests:

```python
    def test_target_directories_specified(self) -> None:
        """Test that tools include target directories where needed."""
        skylos_cmd = get_tool_command("skylos")
        assert any("crackerjack" in arg for arg in skylos_cmd)

        complexipy_cmd = get_tool_command("complexipy")
        assert any("crackerjack" in arg for arg in complexipy_cmd)

        refurb_cmd = get_tool_command("refurb")
        assert any("crackerjack" in arg for arg in refurb_cmd)

        # NEW: ruff-check and ruff-format include scripts/ and examples/
        ruff_check_cmd = get_tool_command("ruff-check")
        assert any("crackerjack" in arg for arg in ruff_check_cmd)
        assert any("scripts" in arg for arg in ruff_check_cmd)
        assert any("examples" in arg for arg in ruff_check_cmd)

        ruff_format_cmd = get_tool_command("ruff-format")
        assert any("crackerjack" in arg for arg in ruff_format_cmd)
        assert any("scripts" in arg for arg in ruff_format_cmd)
        assert any("examples" in arg for arg in ruff_format_cmd)

        # NEW: ruff-check uses --per-file-ignores pointing to the starter pack
        assert "--per-file-ignores" in ruff_check_cmd
        per_file_ignores_idx = ruff_check_cmd.index("--per-file-ignores")
        per_file_ignores_path = Path(ruff_check_cmd[per_file_ignores_idx + 1])
        assert per_file_ignores_path.exists()
        assert per_file_ignores_path.name == "scripts_examples_per_file_ignores.toml"

    def test_ruff_format_has_no_per_file_ignores_flag(self) -> None:
        """ruff-format has no per-file-ignores flag — only lint does."""
        ruff_format_cmd = get_tool_command("ruff-format")
        assert "--per-file-ignores" not in ruff_format_cmd
```

**Step 2.2: Run tests to verify they fail**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/config/test_tool_commands.py::TestCommandStructureValidation::test_target_directories_specified tests/config/test_tool_commands.py::TestCommandStructureValidation::test_ruff_format_has_no_per_file_ignores_flag -v
```

Expected: 2 failures (ruff-check doesn't include scripts/examples yet; --per-file-ignores not present).

**Step 2.3: Update tool_commands.py — extract `_build_targets` helper**

In `crackerjack/config/tool_commands.py`, add an import at the top:

```python
from pathlib import Path

from crackerjack.config.per_file_ignores import ensure_per_file_ignores_file
```

Add the shared helper (place near other helpers):

```python
def _build_targets(package_name: str) -> list[str]:
    """Canonical target list for tools that walk multiple directories.

    Used by ruff-check, ruff-format, codespell, tc-refs, and any future
    tool that should cover both the package and the scripts/examples dirs.
    """
    return [f"./{package_name}", "./scripts", "./examples"]
```

**Step 2.4: Update ruff-check and ruff-format entries**

Modify the two entries (per spec section 4.4):

```python
"ruff-check": _python_module_command(
    "ruff", "check", "--output-format", "json", "--fix",
    "--per-file-ignores", str(ensure_per_file_ignores_file(Path.cwd())),
    *_build_targets(package_name),
),
"ruff-format": _python_module_command(
    "ruff", "format",
    *_build_targets(package_name),
),
```

**Step 2.5: Run tests to verify they pass**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/config/test_tool_commands.py::TestCommandStructureValidation::test_target_directories_specified tests/config/test_tool_commands.py::TestCommandStructureValidation::test_ruff_format_has_no_per_file_ignores_flag -v
```

Expected: 2 passed.

**Step 2.6: Verify full tool_commands tests still pass**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/config/ -x
```

Expected: All tests pass.

**Step 2.7: Verify ruff + mypy on modified files**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/ruff check crackerjack/config/tool_commands.py tests/config/test_tool_commands.py
.venv/bin/ruff format --check crackerjack/config/tool_commands.py tests/config/test_tool_commands.py
.venv/bin/mypy crackerjack/config/tool_commands.py
```

Expected: clean.

**Step 2.8: Smoke-test on crackerjack itself**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/python -m crackerjack run --select ruff-check,ruff-format
```

Expected: Passes. (Or surfaces only the `**/*.bak[0-9]` files, which are now silenced.)

**Step 2.9: Commit**

Run:
```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/config/tool_commands.py tests/config/test_tool_commands.py
git commit -m "$(cat <<'EOF'
feat(hooks): extend ruff-check + ruff-format to scripts/ and examples/

ruff-check now invokes with --per-file-ignores pointing to the universal
starter pack (added in previous commit). ruff-format gets the same target
expansion without the per-file-ignores flag (format doesn't need rule filtering).
Shared _build_targets() helper centralizes the canonical target list.

Verified: fast-hook smoke passes on crackerjack itself.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Extend codespell + tc-refs targets (Commit 3)

**Files:**
- Modify: `crackerjack/config/tool_commands.py` (codespell, tc-refs entries)
- Modify: `tests/config/test_tool_commands.py` (add 2 tests)

**Interfaces:**
- Consumes: `_build_targets(package_name: str) -> list[str]` from Task 2

**Step 3.1: Write failing tests for codespell + tc-refs targets**

Add to `tests/config/test_tool_commands.py`:

```python
    def test_codespell_targets_include_scripts_and_examples(self) -> None:
        """codespell extends coverage to admin/demo code for typo detection."""
        codespell_cmd = get_tool_command("codespell")
        assert any("scripts" in arg for arg in codespell_cmd)
        assert any("examples" in arg for arg in codespell_cmd)

    def test_tc_refs_targets_include_scripts_and_examples(self) -> None:
        """tc-refs (audit-type-checking-runtime-refs) covers TYPE_CHECKING
        runtime usage in scripts/examples too."""
        tc_refs_cmd = get_tool_command("tc-refs")
        assert any("scripts" in arg for arg in tc_refs_cmd)
        assert any("examples" in arg for arg in tc_refs_cmd)
```

**Step 3.2: Run tests to verify they fail**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/config/test_tool_commands.py::TestCommandStructureValidation::test_codespell_targets_include_scripts_and_examples tests/config/test_tool_commands.py::TestCommandStructureValidation::test_tc_refs_targets_include_scripts_and_examples -v
```

Expected: 2 failures.

**Step 3.3: Update codespell and tc-refs entries in tool_commands.py**

Identify the codespell and tc-refs entries (grep for these tool names). For each, replace any hardcoded target list with `_build_targets(package_name)`. Pattern:

```python
# Before:
"codespell": _python_module_command(
    "codespell", f"./{package_name}",  # or similar
),

# After:
"codespell": _python_module_command(
    "codespell", *_build_targets(package_name),
),
```

Same pattern for `tc-refs` (or `audit-type-checking-runtime-refs` — verify the exact key with `grep -n "tc-refs\|audit.type" crackerjack/config/tool_commands.py`).

**Step 3.4: Run tests to verify they pass**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/config/test_tool_commands.py::TestCommandStructureValidation::test_codespell_targets_include_scripts_and_examples tests/config/test_tool_commands.py::TestCommandStructureValidation::test_tc_refs_targets_include_scripts_and_examples -v
```

Expected: 2 passed.

**Step 3.5: Verify full test suite**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/ tests/config/ -x
```

Expected: All pass.

**Step 3.6: Verify lint + types**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/ruff check crackerjack/config/tool_commands.py tests/config/test_tool_commands.py
.venv/bin/mypy crackerjack/config/tool_commands.py
```

Expected: clean.

**Step 3.7: Commit**

Run:
```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/config/tool_commands.py tests/config/test_tool_commands.py
git commit -m "$(cat <<'EOF'
feat(hooks): extend codespell + tc-refs targets to scripts/ and examples/

Both tools now use the shared _build_targets() helper. codespell catches
typos in admin/demo code; tc-refs catches runtime usage of TYPE_CHECKING
imports in admin/demo code. No per-file-ignores needed for these tools.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Rewrite audit_type_checking_runtime_refs.py (Commit 4)

**Files:**
- Modify: `crackerjack/audit_type_checking_runtime_refs.py` (surgical fixes for 12 violations)
- Create: `tests/unit/test_audit_type_checking_runtime_refs.py` (4 regression tests)

**Step 4.1: Write regression tests for behavior preservation**

Create `tests/unit/test_audit_type_checking_runtime_refs.py`:

```python
"""Regression tests for the audit-type-checking-runtime-refs rewrite.

These tests verify behavior preservation after the rewrite that makes
the tool ruff-clean (was contributing 84 violations across 7 repos).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from crackerjack.audit_type_checking_runtime_refs import audit_file


class TestRewritePreservesDetectionSemantics:
    """The rewrite must NOT change what the tool detects."""

    def test_detects_runtime_use_of_typing_import(self, tmp_path: Path) -> None:
        src = tmp_path / "sample.py"
        src.write_text(textwrap.dedent('''
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import heavy_module  # type: ignore

            def f() -> None:
                obj = heavy_module.something()
                return obj
        '''))
        violations = audit_file(src)
        assert len(violations) > > = 1
        assert any("heavy_module" in str(v) for v in violations)

    def test_does_not_flag_legitimate_typing_usage(self, tmp_path: Path) -> None:
        src = tmp_path / "sample.py"
        src.write_text(textwrap.dedent('''
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import SomeType

            def f(x: "SomeType") -> "SomeType":
                return x
        '''))
        violations = audit_file(src)
        assert violations == []

    def test_handles_multiline_type_checking_blocks(self, tmp_path: Path) -> None:
        src = tmp_path / "sample.py"
        src.write_text(textwrap.dedent('''
            from __future__ import annotations
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import mod_a
                import mod_b
                import mod_c

            def f() -> None:
                return mod_a.something()
        '''))
        violations = audit_file(src)
        assert len(violations) >= 1


class TestRewriteIsRuffClean:
    """The rewrite must produce a file that ruff doesn't flag."""

    def test_audit_type_checking_runtime_refs_passes_ruff(self) -> None:
        import subprocess
        import tempfile

        from crackerjack.config.per_file_ignores import (
            ensure_per_file_ignores_file,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_tool = (
                Path(__file__).parent.parent.parent
                / "crackerjack/audit_type_checking_runtime_refs.py"
            )
            scripts_dir = tmp_path / "scripts"
            scripts_dir.mkdir()
            copy = scripts_dir / "audit_type_checking_runtime_refs.py"
            copy.write_text(audit_tool.read_text())
            ensure_per_file_ignores_file(tmp_path)
            result = subprocess.run(
                [
                    "ruff", "check", "--no-fix",
                    "--per-file-ignores",
                    str(
                        tmp_path / ".crackerjack_cache"
                        / "scripts_examples_per_file_ignores.toml"
                    ),
                    str(copy),
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, (
                f"Rewritten audit tool still has ruff violations:\n"
                f"{result.stdout}"
            )
```

**Step 4.2: Run tests to verify behavior is preserved (baseline)**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/test_audit_type_checking_runtime_refs.py -v
```

Expected: All 4 tests PASS (this is the baseline before making changes).

**Step 4.3: Capture pre-rewrite output for spot-check (later in step 4.10)**

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m crackerjack.tools.audit_type_checking_runtime_refs scripts/ > /tmp/audit_pre.txt
```

(Note: this assumes `crackerjack` is installed in mahavishnu's venv. If not, use `uv run --project /Users/les/Projects/crackerjack python -m crackerjack.tools.audit_type_checking_runtime_refs /Users/les/Projects/mahavishnu/scripts > /tmp/audit_pre.txt`)

**Step 4.4: Apply fix 1 — `chmod +x` for EXE001**

Run:
```bash
chmod +x /Users/les/Projects/crackerjack/crackerjack/audit_type_checking_runtime_refs.py
```

**Step 4.5: Apply fix 2 — F541 (f-string-without-placeholder)**

In `crackerjack/audit_type_checking_runtime_refs.py`, grep for `f"` and replace each instance that has no `{...}` placeholder with a plain string literal. Example:

```python
# Before:
print(f"audit: complete")# After:
print("audit: complete")
```

(Use grep to find all occurrences: `grep -n 'f"' /Users/les/Projects/crackerjack/crackerjack/audit_type_checking_runtime_refs.py`.)

**Step 4.6: Apply fix 3 — C901 (extract helper function)**

Identify the longest function in the file (likely `audit_file` or similar). Extract a helper (e.g., `_check_type_checking_block`) that handles one block at a time. Refactor the parent to iterate. Ensure cyclomatic complexity drops below the `max-branches=15` limit and below `25` for C901.

**Step 4.7: Apply fixes 4-7 — SIM102, SIM103, SIM114, BLE001**

For each:
- **SIM103**: Replace `return True/return False` patterns with direct returns.
- **SIM114**: Combine if-branches with identical bodies into one branch with `or` condition.
- **SIM102**: Inline nested `if` statements where the outer condition is the same.
- **BLE001**: Narrow `except Exception:` to `(OSError, UnicodeDecodeError)` (or whichever types the original code's intent indicates).

After each fix, run regression tests:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/test_audit_type_checking_runtime_refs.py -v
```

Expected: All 4 tests still pass after each fix. If any fails, revert that fix and try a different approach.

**Step 4.8: Apply fixes 8-10 — D301, PIE810, TRY004**

For each:
- **D301**: Use raw string `r"..."` for any string literal containing backslashes.
- **PIE810**: Fix `*args, **kwargs` unpacking patterns (e.g., `a, *b, c = something` → `a, b, c = something` if `b` is unused).
- **TRY004**: Replace `raise Exception(...)` with `raise TypeError(...)` or appropriate specific exception.

After each fix, run regression tests:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/test_audit_type_checking_runtime_refs.py -v
```

Expected: All 4 tests still pass.

**Step 4.9: Verify the rewritten file is ruff-clean**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/ruff check crackerjack/audit_type_checking_runtime_refs.py
```

Expected: 0 violations. (Some violations may remain for the audit tool file itself since it's at `crackerjack/`, not `scripts/` — those don't affect the consumer repos but should be cleaned up too if they're easy.)

**Step 4.10: Spot-check behavior preservation across real Bodai repos**

Run:
```bash
cd /Users/les/Projects/mahavishnu
uv run --project /Users/les/Projects/crackerjack python -m crackerjack.tools.audit_type_checking_runtime_refs /Users/les/Projects/mahavishnu/scripts > /tmp/audit_post.txt

# Compare with pre-rewrite output:
diff /tmp/audit_pre.txt /tmp/audit_post.txt
```

Expected: empty diff. If non-empty diff shows MISSED detections (tool no longer flags something it used to), revert the rewrite.

Repeat for session-buddy and oneiric:
```bash
diff /tmp/audit_pre_sb.txt /tmp/audit_post_sb.txt
diff /tmp/audit_pre_one.txt /tmp/audit_post_one.txt
```

(Capture pre-rewrite outputs at the start: `... > /tmp/audit_pre_sb.txt`, `... > /tmp/audit_pre_one.txt`.)

**Step 4.11: Verify full test suite + lint + types**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/pytest tests/unit/ tests/config/ -x
.venv/bin/ruff check crackerjack/audit_type_checking_runtime_refs.py tests/unit/test_audit_type_checking_runtime_refs.py
.venv/bin/mypy crackerjack/audit_type_checking_runtime_refs.py
```

Expected: All pass; no lint or type errors.

**Step 4.12: Commit**

Run:
```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/audit_type_checking_runtime_refs.py tests/unit/test_audit_type_checking_runtime_refs.py
git commit -m "$(cat <<'EOF'
feat(audit): make audit_type_checking_runtime_refs ruff-clean

Rewrite via surgical rule-by-rule fixes for the 12 violations that fire
in every copy across 7 consumer repos (84 total violations eliminated
on consumer-side fast-hook runs):
  - EXE001: chmod +x
  - F541: drop f prefix on literal-only f-strings
  - C901: extract _check_type_checking_block helper
  - SIM102/103/114: collapse redundant control flow
  - BLE001: narrow except Exception to OSError/UnicodeDecodeError
  - D301: raw strings for backslash literals
  - PIE810: fix star-unpacking patterns
  - TRY004: raise TypeError instead of Exception

Detection semantics preserved via regression tests + spot-check diff
against mahavishnu, session-buddy, oneiric (output identical to
pre-rewrite).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Verification report (Commit 5)

**Files:**
- No code changes — verification-only task.

**Step 5.1: Run full crackerjack fast-hook pipeline on crackerjack itself**

Run:
```bash
cd /Users/les/Projects/crackerjack
.venv/bin/python -m crackerjack run
```

Expected: Passes. Capture the output for the commit message.

**Step 5.2: Run post-deploy verification on heavy-offender repos**

Run:
```bash
for repo in mahavishnu session-buddy oneiric fastblocks mcp-common; do
    cd /Users/les/Projects/$repo
    echo "=== $repo ==="
    uv run ruff check scripts/ examples/ 2>&1 | tail -5
done
```

Capture output. Expected reductions:

| Repo | Pre-change | Expected post-change | Reduction |
|---|---|---|---|
| mahavishnu | 134 | ≤50 | ~60% |
| session-buddy | 117 | ≤60 | ~50% |
| oneiric | 30 | ≤10 | ~66% |
| fastblocks | 14 | ≤5 | ~64% |
| mcp-common | 14 | ≤5 | ~64% |

**Step 5.3: Run crackerjack fast-hook on mahavishnu (end-to-end check)**

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -m crackerjack run --select ruff-check,ruff-format,codespell,tc-refs
```

Expected: Passes (or surfaces only the per-repo remaining violations that the universal starter pack intentionally does NOT silence — UP034, DTZ005, RUF012, PLR1722, FURB162, etc.).

**Step 5.4: Capture verification report as a single text block**

Combine outputs from steps 5.1-5.3 into a verification report. This goes in the commit message.

**Step 5.5: Commit (verification report only)**

Run:
```bash
cd /Users/les/Projects/crackerjack
git commit --allow-empty -m "$(cat <<'EOF'
docs(verification): scripts/examples coverage rollout verification report

Post-deploy verification across 5 heavy-offender Bodai repos confirms
expected ruff violation reductions:

[Paste output from steps 5.1-5.3 here]

End-to-end crackerjack fast-hook run on mahavishnu passes. Remaining
violations are per-repo rules (UP034, DTZ005, RUF012, etc.) intentionally
NOT in the universal starter pack — these are signal for follow-up cleanup.

This is commit 5 of 5 for scripts/examples coverage in fast hooks.
Spec: docs/superpowers/specs/2026-09-05-crackerjack-scripts-examples-coverage-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Code <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist

Run these checks after the plan is complete (before handing to executor):

- [ ] **Spec coverage**: skim each spec section, confirm a task implements it
  - §4.1 Architecture → Tasks 1-4 cover all file changes
  - §4.2 Universal starter pack → Task 1 implements the constant
  - §4.3 Per-file-ignores injection → Task 1 implements helper
  - §4.4 tool_commands.py changes → Tasks 2-3 update tool commands
  - §4.5 Audit tool rewrite → Task 4 implements rewrite
  - §4.6 Test updates → Tasks 1, 2, 3, 4 add tests
  - §5 Verification & Rollout → Task 5 implements
- [ ] **No placeholders**: search for "TBD", "TODO", "implement later"
- [ ] **Type consistency**: `UNIVERSAL_PER_FILE_IGNORES` and `ensure_per_file_ignores_file` defined in Task 1, used in Tasks 2-3 with matching signatures
- [ ] **`_build_targets` defined in Task 2.3, used in Tasks 2.4, 3.3** with matching signature