"""CI guard test: worktree base path must resolve through ``paths.get_worktree_base_path()``.

ADR 015 v4 Phase 0.4: CI guard that scans mahavishnu source files and
fails the build if any reference to the worktree base path bypasses
the canonical helper in ``mahavishnu.core.paths``.

The audit (2026-08-23) found 5 call sites with different defaults
(``worktree_manager.py``, ``worktree_validation.py``,
``worktree_coordination.py``, ``.claude/hooks/worktree-session-isolation.py``,
``docs/CONFIGURATION.md``). Phase 0.3 unified them; this test prevents
the drift from recurring.

Allowed references:
  - ``mahavishnu/core/paths.py`` (defines the helper)
  - ``.claude/hooks/worktree-session-isolation.py`` (runs before
    ``MahavishnuApp.load()``; defines an inline mirror)
  - The CI guard test itself
  - Docs (excluding ``docs/CONFIGURATION.md``) and the AGENTS/CLAUDE.md files
  - Test files (by design, may reference the literal path)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories scanned for worktree-path references.
SCAN_DIRS = [
    REPO_ROOT / "mahavishnu",
    REPO_ROOT / ".claude" / "hooks",
    REPO_ROOT / "docs",
]

# Files exempt from the guard (by relative path from REPO_ROOT).
EXEMPT_PATHS = {
    # Defines the helper itself.
    "mahavishnu/core/paths.py",
    # Inline mirror in the SessionStart hook (per paths.py docstring).
    ".claude/hooks/worktree-session-isolation.py",
    # The guard test itself.
    "tests/unit/test_worktree_base_path_resolution.py",
    # Config doc; the env-var default IS the literal string.
    "docs/CONFIGURATION.md",
    # Decisions that document the historical drift; out of scope.
    ".claude/decisions/session-worktree-defaults.md",
    # Worktree-management guide uses literal `~/worktrees` paths
    # throughout CLI examples; rewriting the whole document is out of
    # scope for this fix (the canonical helper still owns resolution).
    "docs/WORKTREE_MANAGEMENT.md",
    # The historical multi-agent review ADR enumerates the exact
    # drift this test guards against — keeping the literal references
    # is the whole point of the doc.
    "docs/adr/015-multi-agent-review.md",
}

# Forbidden patterns. Each pattern is the (regex, description) tuple.
# The regex must be specific enough to avoid false positives (e.g., the
# word "worktree" alone is too broad).
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (
        r'["\']~/worktrees[/"\']',
        "literal '~/worktrees' path string — must go through get_worktree_base_path()",
    ),
    (
        r'os\.path\.expanduser\(\s*["\']~/worktrees',
        "os.path.expanduser on literal '~/worktrees' — must go through get_worktree_base_path()",
    ),
    (
        r'Path\.home\(\)\s*/\s*["\']?worktrees["\']?',
        "Path.home() / 'worktrees' — must go through get_worktree_base_path()",
    ),
    (
        r'os\.environ\.(?:get|setdefault)\(\s*["\']MAHAVISHNU_AUTO_WORKTREE_ROOT["\']',
        "direct MAHAVISHNU_AUTO_WORKTREE_ROOT read — must go through get_worktree_base_path() (or the inline _worktree_base_path() in the SessionStart hook)",
    ),
]


def _is_exempt(rel_path: str) -> bool:
    return rel_path in EXEMPT_PATHS


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return [(line_no, description, line_text)] for forbidden matches."""
    matches: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return matches
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, description in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                matches.append((line_no, description, line.strip()))
                break
    return matches


def test_no_direct_worktree_path_references() -> None:
    """Fail if any non-exempt source file references the worktree path directly.

    This is the Phase 0.4 CI guard. Adding a new worktree-path read
    site requires going through ``mahavishnu.core.paths.get_worktree_base_path()``
    (or the inline mirror in ``worktree-session-isolation.py``). Adding a
    legitimate direct reference requires updating the ``EXEMPT_PATHS``
    set above and the ADR's Resolution order table.
    """
    violations: list[tuple[str, int, str, str]] = []  # (file, line, desc, line_text)
    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*.py"):
            rel = str(path.relative_to(REPO_ROOT))
            if _is_exempt(rel):
                continue
            for line_no, desc, line_text in _scan_file(path):
                violations.append((rel, line_no, desc, line_text))
        # Non-Python files in docs/ also get scanned (markdown etc).
        if scan_dir.name == "docs":
            for path in scan_dir.rglob("*.md"):
                rel = str(path.relative_to(REPO_ROOT))
                if _is_exempt(rel):
                    continue
                for line_no, desc, line_text in _scan_file(path):
                    violations.append((rel, line_no, desc, line_text))

    if violations:
        formatted = "\n".join(
            f"  {rel}:{line_no}: {desc}\n    {line_text}"
            for rel, line_no, desc, line_text in violations
        )
        pytest.fail(
            "Direct worktree-path references found. Resolve via "
            "mahavishnu.core.paths.get_worktree_base_path() instead.\n"
            f"{formatted}\n"
            "If the reference is legitimate, add the path to EXEMPT_PATHS "
            "in this test and update the ADR's Resolution order table."
        )


def test_paths_helper_resolves_before_env_var_default() -> None:
    """Sanity check on the helper's resolution order.

    Independent of the file-scan guard above; verifies the helper
    itself follows the documented order:
      1. MAHAVISHNU_WORKTREE_BASE_PATH (canonical, v4+)
      2. MAHAVISHNU_AUTO_WORKTREE_ROOT (legacy alias)
      3. Path.home() / 'worktrees' (default)
    """
    from mahavishnu.core import paths

    # Save and clear all relevant env vars
    saved: dict[str, str | None] = {}
    for var in ("MAHAVISHNU_WORKTREE_BASE_PATH", "MAHAVISHNU_AUTO_WORKTREE_ROOT"):
        saved[var] = os.environ.pop(var, None)
    try:
        # 3. Default
        assert paths.get_worktree_base_path() == (Path.home() / "worktrees").resolve()
        # 2. Legacy env var
        os.environ["MAHAVISHNU_AUTO_WORKTREE_ROOT"] = "/tmp/legacy"
        assert paths.get_worktree_base_path() == Path("/tmp/legacy").resolve()
        # 1. Canonical env var wins
        os.environ["MAHAVISHNU_WORKTREE_BASE_PATH"] = "/tmp/canonical"
        assert paths.get_worktree_base_path() == Path("/tmp/canonical").resolve()
        # 1. Wins over 2
        os.environ["MAHAVISHNU_AUTO_WORKTREE_ROOT"] = "/tmp/legacy"
        assert paths.get_worktree_base_path() == Path("/tmp/canonical").resolve()
    finally:
        # Restore the prior env state. When the var was unset at entry,
        # ``pop`` it again so the leak ``os.environ[var] = "..."`` in the test
        # body doesn't survive past this test — that leak was the cause of a
        # cascade where ``test_worktree_validation::test_get_safe_worktree_path_default_base``
        # saw ``MAHAVISHNU_WORKTREE_BASE_PATH=/tmp/canonical`` even though no
        # env var was set in the worker.
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
