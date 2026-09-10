#!/usr/bin/env python3
"""Pre-flight check for the mergiraf merge driver.

# Implements: REQ-SM-008

Operator-facing probe that verifies the mergiraf merge driver is wired
correctly before settling workloads. Exits 0 when all checks pass; exits
1 with a remediation hint when any check fails.

Checks (in order):
    1. ``mergiraf`` is on ``$PATH`` (``shutil.which("mergiraf")``).
    2. ``mergiraf --version`` parses a semver-like string (e.g. "0.19.1").
    3. The ``tree-sitter-python`` grammar is loadable
       (``mergiraf languages | grep -q Python``). R4 #C: tree-sitter
       grammars are NOT packaged with the ``cargo binstall`` binary and
       most CI container images — only the Homebrew formula bundles them.
    4. ``git --version`` reports >= 2.38 (R4 unstated dependency for the
       Phase 6 ``git merge-tree --write-tree`` candidate; cheap to verify
       now).

Output format: one ``check=NAME state=ok|missing|error detail=...`` line
per check, followed by a summary line ``checks_passed=<N>/<M>``.

CLI flags:
    --json    emit machine-readable JSON
    --strict  exit non-zero on any warning (currently: tree-sitter grammar
              absent is a warning; binary missing or version unparsable
              is a hard failure)

Remediation hints:
    * Binary missing:
      - macOS / Linux: ``brew install mergiraf`` (Homebrew bundles grammars)
      - Linux alt: ``cargo binstall mergiraf`` ships only the binary —
        run ``mergiraf install-grammar python`` for required grammars
    * Tree-sitter grammar absent:
      - ``mergiraf install-grammar python`` (and others your repo needs)
    * Git too old:
      - Upgrade to >= 2.38 (``brew install git`` on macOS)

Exit codes:
    0 = all checks passed
    1 = at least one hard check failed (binary / version / git)
    2 = internal error (subprocess failure, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

CheckState = Literal["ok", "missing", "warning", "error"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single pre-flight check."""

    name: str
    state: CheckState
    detail: str

    @property
    def passed(self) -> bool:
        """True when this check is OK or a soft warning (under --strict)."""
        return self.state == "ok"


def check_binary() -> CheckResult:
    """Probe ``mergiraf`` on ``$PATH``.

    Hard failure: without the binary, the SEMANTIC strategy cannot run
    and the startup guard refuses to boot when
    ``merge_driver_required=True``.
    """
    binary = shutil.which("mergiraf")
    if binary is None:
        return CheckResult(
            name="binary",
            state="missing",
            detail=(
                "mergiraf not found on $PATH. Install via "
                "'brew install mergiraf' (Homebrew bundles tree-sitter "
                "grammars) or 'cargo binstall mergiraf' (ships binary only)."
            ),
        )
    return CheckResult(name="binary", state="ok", detail=binary)


def check_version() -> CheckResult:
    """Parse ``mergiraf --version`` output.

    Hard failure: a malformed version string means the CLI shape has
    drifted from what ``_merge_via_mergiraf`` expects. Operators should
    update Mahavishnu's pin or migrate to a supported mergiraf release.
    """
    binary = shutil.which("mergiraf")
    if binary is None:
        return CheckResult(
            name="version",
            state="missing",
            detail="skipped (binary not found)",
        )
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="version",
            state="error",
            detail="mergiraf --version timed out after 5s",
        )
    except OSError as exc:
        return CheckResult(
            name="version",
            state="error",
            detail=f"subprocess failure: {exc!s}",
        )
    output = (result.stdout or result.stderr or "").strip()
    match = re.search(r"mergiraf\s+(\d+\.\d+\.\d+)", output)
    if match is None:
        return CheckResult(
            name="version",
            state="error",
            detail=f"could not parse version from: {output!r}",
        )
    return CheckResult(name="version", state="ok", detail=match.group(1))


def check_python_grammar() -> CheckResult:
    """Verify ``tree-sitter-python`` grammar is loadable.

    Soft failure (warning): mergiraf without the Python grammar can
    still parse Python files heuristically, but every Python file in
    a settle run risks a tree-sitter parse error. Operators using
    Python repos should install the grammar explicitly.
    """
    binary = shutil.which("mergiraf")
    if binary is None:
        return CheckResult(
            name="python_grammar",
            state="missing",
            detail="skipped (binary not found)",
        )
    try:
        result = subprocess.run(
            [binary, "languages"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="python_grammar",
            state="error",
            detail="mergiraf languages timed out after 10s",
        )
    except OSError as exc:
        return CheckResult(
            name="python_grammar",
            state="error",
            detail=f"subprocess failure: {exc!s}",
        )
    languages_output = result.stdout or ""
    if "Python" not in languages_output:
        return CheckResult(
            name="python_grammar",
            state="warning",
            detail=(
                "tree-sitter-python grammar not loadable. Run "
                "'mergiraf install-grammar python' (and others your "
                "repo needs). Without grammars, Python settles will "
                "fail with MergeFailureError(exit=2)."
            ),
        )
    return CheckResult(
        name="python_grammar",
        state="ok",
        detail="tree-sitter-python grammar loadable",
    )


def check_git_version(minimum: tuple[int, int] = (2, 38)) -> CheckResult:
    """Probe ``git --version`` and compare to the minimum supported.

    Hard failure: ``git merge-tree --write-tree`` (Phase 6 candidate)
    requires git >= 2.38. Even if Phase 5 stays deferred, the version
    is cheap to verify now and operators get a one-line migration hint.
    """
    binary = shutil.which("git")
    if binary is None:
        return CheckResult(
            name="git_version",
            state="missing",
            detail="git not found on $PATH",
        )
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult(
            name="git_version",
            state="error",
            detail=f"subprocess failure: {exc!s}",
        )
    output = (result.stdout or result.stderr or "").strip()
    match = re.search(r"git version\s+(\d+)\.(\d+)(?:\.\d+)?", output)
    if match is None:
        return CheckResult(
            name="git_version",
            state="error",
            detail=f"could not parse version from: {output!r}",
        )
    actual = (int(match.group(1)), int(match.group(2)))
    if actual < minimum:
        return CheckResult(
            name="git_version",
            state="missing",
            detail=(
                f"git {'.'.join(map(str, actual))} < "
                f"{'.'.join(map(str, minimum))}. "
                f"Upgrade git (brew install git on macOS)."
            ),
        )
    return CheckResult(
        name="git_version",
        state="ok",
        detail=f"git {'.'.join(map(str, actual))} >= {'.'.join(map(str, minimum))}",
    )


def run_checks(strict: bool = False) -> list[CheckResult]:
    """Run all pre-flight checks and return their results in order."""
    results = [
        check_binary(),
        check_version(),
        check_python_grammar(),
        check_git_version(),
    ]
    if strict:
        # Promote ``warning`` state to ``missing`` so --strict exits non-zero
        # on tree-sitter grammar absence too.
        return [
            CheckResult(
                name=r.name,
                state="missing" if r.state == "warning" else r.state,
                detail=r.detail,
            )
            for r in results
        ]
    return results


def _format_text(results: list[CheckResult]) -> str:
    lines = [f"check={r.name} state={r.state} detail={r.detail}" for r in results]
    passed = sum(1 for r in results if r.state == "ok")
    lines.append(f"checks_passed={passed}/{len(results)}")
    return "\n".join(lines)


def _format_json(results: list[CheckResult]) -> str:
    payload = {
        "checks": [{"name": r.name, "state": r.state, "detail": r.detail} for r in results],
        "passed": sum(1 for r in results if r.state == "ok"),
        "total": len(results),
    }
    return json.dumps(payload, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-flight check for the mergiraf merge driver.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of text.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when tree-sitter grammar is absent (warning → error).",
    )
    args = parser.parse_args(argv)

    try:
        results = run_checks(strict=args.strict)
    except Exception as exc:
        sys.stderr.write(f"internal error: {exc!s}\n")
        return 2

    output = _format_json(results) if args.json else _format_text(results)
    print(output)

    # Hard failures (binary missing, version unparsable, git too old)
    # return 1. Soft warnings return 0 unless --strict is set.
    hard_failures = [r for r in results if r.state in {"missing", "error"}]
    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
