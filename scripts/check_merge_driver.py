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
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

CheckState = Literal["ok", "missing", "warning", "error"]


# Phase 4 deferred review (M6): mapping from file extension to the
# mergiraf grammar that should be loadable. The CLI flag ``--repo-path``
# walks the repo, dedupes by extension, and asserts the corresponding
# grammar was reported by ``mergiraf languages``. Operators see the
# grammars they actually need for their codebase, not just the Python
# default that ships with ``brew install mergiraf``.
_EXTENSION_GRAMMAR: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".rs": "Rust",
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".rb": "Ruby",
}


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


def check_python_grammar(repo_path: Path | None = None) -> CheckResult:
    """Verify the tree-sitter grammars this repo needs are loadable.

    When ``repo_path`` is provided (Phase 4 deferred review M6), walks
    the repo and asserts every grammar the codebase actually uses is
    in the ``mergiraf languages`` output. When ``repo_path`` is
    ``None``, falls back to the original Python-only check (the
    legacy default; CLI flag ``--repo-path`` is opt-in).

    Soft failure (warning): mergiraf without a required grammar can
    still parse heuristically, but every affected file in a settle
    run risks a tree-sitter parse error. Operators should install
    the missing grammars explicitly.
    """
    if repo_path is not None:
        required = _required_grammars_for_repo(repo_path)
        if not required:
            return CheckResult(
                name="python_grammar",
                state="ok",
                detail=(
                    f"--repo-path {repo_path}: no files matched the "
                    f"tracked extensions; nothing to verify"
                ),
            )
        binary = shutil.which("mergiraf")
        if binary is None:
            return CheckResult(
                name="python_grammar",
                state="missing",
                detail="skipped (binary not found)",
            )
        return _check_repo_grammars(binary, required)
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


def _required_grammars_for_repo(repo_path: Path) -> list[str]:
    """Walk ``repo_path`` and return the deduped list of grammars needed.

    Phase 4 deferred review (M6). Walks the repo with ``rglob`` over
    the file types :data:`_EXTENSION_GRAMMAR` covers, dedupes the
    grammar names preserving first-seen order, and returns the list.
    Files larger than 1MB are skipped — both are noise for the
    grammar-need detection (binary assets and vendored deps). The
    1MB threshold is generous: source files over 1MB are rare; binary
    blobs are the common case (``.pyc``, lockfiles, vendored deps).
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for ext in _EXTENSION_GRAMMAR:
        for candidate in repo_path.rglob(f"*{ext}"):
            try:
                if not candidate.is_file():
                    continue
                # Skip heavy/binary files quickly; the grammar detector
                # only needs presence of the extension.
                if candidate.stat().st_size > 1_000_000:
                    continue
            except OSError:
                # Permission denied, broken symlink, race with delete.
                continue
            grammar = _EXTENSION_GRAMMAR[ext]
            if grammar not in seen_set:
                seen.append(grammar)
                seen_set.add(grammar)
    return seen


def _check_repo_grammars(binary: str, required_grammars: list[str]) -> CheckResult:
    """Run ``mergiraf languages`` and check each required grammar is present.

    Phase 4 deferred review (M6). The Python-only check is the original
    behavior (and still the default when ``--repo-path`` is omitted);
    this variant asserts every grammar the repo actually uses is
    loadable. Soft failure so operators see which one is missing
    rather than a single aggregated warning.
    """
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
    if result.returncode != 0:
        return CheckResult(
            name="python_grammar",
            state="error",
            detail=f"mergiraf languages exited {result.returncode}",
        )
    languages_output = result.stdout or ""
    missing = [g for g in required_grammars if g not in languages_output]
    if missing:
        return CheckResult(
            name="python_grammar",
            state="warning",
            detail=(
                f"repo needs {len(missing)} missing grammar(s): "
                f"{', '.join(missing)}. Run 'mergiraf install-grammar "
                f"<lang>' for each (or use brew install mergiraf which "
                f"bundles the common ones)."
            ),
        )
    return CheckResult(
        name="python_grammar",
        state="ok",
        detail=(
            f"all {len(required_grammars)} required grammars loadable: "
            f"{', '.join(required_grammars)}"
        ),
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


def run_checks(
    strict: bool = False,
    repo_path: Path | None = None,
) -> list[CheckResult]:
    """Run all pre-flight checks and return their results in order.

    Phase 4 deferred review (M6): when ``repo_path`` is provided, the
    grammar check walks the repo and asserts every grammar the
    codebase uses is loadable. When ``None`` (the default), the
    original Python-only check runs.
    """
    results = [
        check_binary(),
        check_version(),
        check_python_grammar(repo_path),
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
    parser.add_argument(
        "--repo-path",
        type=str,
        default=None,
        help=(
            "Path to a source repo. When provided, the grammar check "
            "walks the repo and asserts every language the codebase "
            "actually uses is loadable (Python/Rust/Go/TypeScript/"
            "JavaScript/Java/C/C++/Ruby). When omitted, the check "
            "falls back to the original Python-only behavior. "
            "(Phase 4 deferred review M6)"
        ),
    )
    args = parser.parse_args(argv)

    # Phase 4 deferred review (M6): validate --repo-path early so a
    # bad path produces a clean error rather than a confusing empty
    # result or a partial-success hard failure.
    repo_path: Path | None
    try:
        repo_path = _resolve_repo_path(args.repo_path)
    except ValueError as exc:
        sys.stderr.write(f"{exc!s}\n")
        return 2

    try:
        results = run_checks(strict=args.strict, repo_path=repo_path)
    except Exception as exc:
        sys.stderr.write(f"internal error: {exc!s}\n")
        return 2

    output = _format_json(results) if args.json else _format_text(results)
    print(output)

    # Hard failures (binary missing, version unparsable, git too old)
    # return 1. Soft warnings return 0 unless --strict is set.
    hard_failures = [r for r in results if r.state in {"missing", "error"}]
    return 1 if hard_failures else 0


def _resolve_repo_path(repo_path_arg: str | None) -> Path | None:
    """Validate ``--repo-path`` and return a normalized :class:`Path`.

    Phase 4 deferred review (M6). Returns ``None`` when the flag was
    omitted (legacy Python-only behavior). When provided, the path
    must exist and be a directory — operator-friendly error rather
    than a confusing ``rglob`` empty-result surprise.
    """
    if repo_path_arg is None:
        return None
    candidate = Path(repo_path_arg).expanduser()
    if not candidate.exists():
        raise ValueError(f"--repo-path {candidate} does not exist")
    if not candidate.is_dir():
        raise ValueError(f"--repo-path {candidate} is not a directory")
    return candidate


if __name__ == "__main__":
    sys.exit(main())
