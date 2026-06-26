#!/usr/bin/env python3
"""CI guard for workflow quarantine (Plan 5 Phase A.0.4).

The runtime quarantine invariant (mahavishnu/distill/discovery.py) blocks
distilled/*.py files from being discovered. But it doesn't stop a human
(or a stale Claude Code session) from doing::

    cp mahavishnu/workflows/distilled/foo.py mahavishnu/workflows/foo.py
    git add mahavishnu/workflows/foo.py

That bypass file would land as a top-level workflow with NO row in
distilled_workflows, NO approved_by, NO audit trail. Runtime discovery
would happily find it. Defense-in-depth: this CI guard enforces the
metadata convention at the filesystem level.

Quarantine rules for any ``*.py`` file directly under
``mahavishnu/workflows/`` (i.e. NOT under ``distilled/``):

1. Filename MUST NOT match the pattern ``distilled_*.py``.
2. First 50 lines MUST contain BOTH header comments:
   - ``# Approved by: <reviewer-id>``
   - ``# Workflow-ID: <ulid>``

A file under ``workflows/distilled/`` is allowed (the quarantine dir) and
NOT subject to headers — it's not executable until ``mahavishnu workflow
publish <id>`` moves it.

Exit codes:
- 0: all checks pass
- 1: at least one violation was found

Usage::

    python scripts/ci/check_workflow_quarantine.py [<repo_root>]
    python scripts/ci/check_workflow_quarantine.py /path/to/repo
    python scripts/ci/check_workflow_quarantine.py --json
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Centralized path constants — keep in sync with mahavishnu.distill.discovery
# ---------------------------------------------------------------------------

WORKFLOWS_ROOT = Path("mahavishnu") / "workflows"
QUARANTINE_DIR_NAME = "distilled"
HEADER_SCAN_LINE_LIMIT = 50
PY_SUFFIX = ".py"

# Filename pattern that signals "this file was distilled and not promoted
# properly". A file named distilled_*.py directly under workflows/ is a
# failed-publish bypass.
DISTILLED_FILENAME_PATTERN = re.compile(r"^distilled_.*\.py$")

# Header lines we require in any non-quarantined workflow file. The order
# of regexes is preserved in error output.
REQUIRED_HEADER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Approved by",
        re.compile(r"^\s*#\s*Approved by:\s*\S+", re.MULTILINE),
    ),
    (
        "Workflow-ID",
        re.compile(r"^\s*#\s*Workflow-ID:\s*\S+", re.MULTILINE),
    ),
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single quarantine-bypass attempt detected by the guard."""

    file: Path
    code: str  # short stable identifier for machine consumption
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "file": str(self.file),
            "code": self.code,
            "message": self.message,
        }


@dataclass
class CheckResult:
    """Aggregate result of one CI check run."""

    repo_root: Path
    violations: list[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, object]:
        return {
            "repo_root": str(self.repo_root),
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
        }


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------


def iter_workflow_files(workflows_dir: Path) -> Iterator[Path]:
    """Yield top-level workflow ``*.py`` files.

    Excludes anything under ``distilled/`` and any non-``.py`` file. The
    guard operates ONLY on the published directory — distilled files
    don't need headers because they're not executable.
    """
    if not workflows_dir.is_dir():
        return
    for path in sorted(workflows_dir.glob("*.py")):
        if path.suffix != PY_SUFFIX:
            continue
        if path.stem == "__init__":
            continue
        yield path


def _read_header(path: Path, line_limit: int = HEADER_SCAN_LINE_LIMIT) -> str:
    """Read the first ``line_limit`` lines of ``path`` for header parsing."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        # On read failure, return empty so all required-header checks fail
        # with a deterministic message rather than crashing the CI run.
        return ""
    return "\n".join(text.splitlines()[:line_limit])


# ---------------------------------------------------------------------------
# Check logic
# ---------------------------------------------------------------------------


def _check_filename(path: Path) -> str | None:
    """Return a violation code if ``path`` filename violates naming rule.

    Files named ``distilled_*.py`` directly under workflows/ are a bypass
    indicator — the file was copied from the quarantine dir without going
    through ``mahavishnu workflow publish``.
    """
    if DISTILLED_FILENAME_PATTERN.match(path.name):
        return "distilled_filename_bypass"
    return None


def _check_headers(path: Path) -> list[tuple[str, str]]:
    """Return list of ``(header_name, code)`` for any missing required headers."""
    header = _read_header(path)
    missing: list[tuple[str, str]] = []
    for header_name, pattern in REQUIRED_HEADER_PATTERNS:
        if not pattern.search(header):
            missing.append(
                (
                    header_name,
                    f"missing_required_header:{header_name.lower().replace(' ', '_')}",
                )
            )
    return missing


def check_repo(repo_root: Path) -> CheckResult:
    """Run all quarantine checks against ``repo_root`` and return the result."""
    workflows_dir = repo_root / WORKFLOWS_ROOT
    result = CheckResult(repo_root=repo_root)

    for wf_file in iter_workflow_files(workflows_dir):
        # Rule 1: filename pattern
        filename_code = _check_filename(wf_file)
        if filename_code:
            result.violations.append(
                Violation(
                    file=wf_file,
                    code=filename_code,
                    message=(
                        f"File {wf_file.name} matches 'distilled_*.py' pattern but is "
                        f"directly under {WORKFLOWS_ROOT}/, not under "
                        f"{WORKFLOWS_ROOT}/{QUARANTINE_DIR_NAME}/. This is a "
                        f"publish-bypass attempt."
                    ),
                )
            )

        # Rule 2: required headers
        for header_name, code in _check_headers(wf_file):
            result.violations.append(
                Violation(
                    file=wf_file,
                    code=code,
                    message=(
                        f"File {wf_file.relative_to(repo_root)} is missing the required "
                        f"header '# {header_name}: <value>' in its first "
                        f"{HEADER_SCAN_LINE_LIMIT} lines."
                    ),
                )
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CI guard for the distilled-workflow quarantine invariant.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=".",
        help="Path to the repo root (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    result = check_repo(repo_root)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_human(result)

    return 0 if result.passed else 1


def _print_human(result: CheckResult) -> None:
    if result.passed:
        print(f"OK: workflow quarantine check passed ({result.repo_root})")
        return

    print(
        f"FAIL: workflow quarantine check found "
        f"{len(result.violations)} violation(s) in {result.repo_root}",
        file=sys.stderr,
    )
    for v in result.violations:
        print(f"  [{v.code}] {v.file}: {v.message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())