#!/usr/bin/env python3
"""Test Coverage Matrix Generator.

Deterministic generator (stdlib + ``defusedxml`` for safe ``coverage.xml`` parsing) for ``components x test_types`` coverage
matrices. Used by ``quality-validation.md`` and ``test-harness.md`` tool
consumers to give an LLM real, on-disk evidence about which components are
covered by which test suites — replacing the LLM's tendency to hallucinate
file lists.

Three stacks are supported. ``python`` is implemented in full; ``node`` and
``go`` are intentionally minimal (file presence only) per the spec.

CLI:
    test_matrix.py --project PATH --stack {python,node,go,mixed}
                   [--types unit,integration,e2e,property,chaos]
                   [--coverage-target PCT]
                   [--force-stack python,node,go]
                   [--out PATH] [--out-md PATH]

Defaults: --types=unit,integration, --coverage-target=80, --out=./test-matrix.json.
--out-md is omitted unless set.

Exit codes:
    0  success
    1  argument or filesystem error
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable  # noqa: TC003
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any

import defusedxml.ElementTree as ET  # noqa: N817 (ET is the conventional name)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

# Directories under mahavishnu/ that are not actual testable components.
# These are entry-point modules, ad-hoc scripts, or documentation that live
# alongside the package but should not appear as components in the matrix.
_NON_COMPONENT_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        "prototypes",  # throwaway experiments
        "shell",  # interactive REPL
        "tui",  # text UI, exercised manually
        "models",  # Pydantic schemas only; transitively covered
    }
)


@dataclass
class ComponentCoverage:
    """Per-cell record describing whether a component is covered by a test type.

    Value-like but not deeply immutable — ``files`` and ``gaps`` lists are
    mutable. If you need an immutable view, copy with ``dataclasses.replace()``.
    """

    covered: bool
    files: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"covered": self.covered, "files": self.files, "gaps": self.gaps}


# ---------------------------------------------------------------------------
# Component discovery
# ---------------------------------------------------------------------------


def detect_components(project: Path) -> list[str]:
    """Return the sorted list of testable component paths under ``mahavishnu/``.

    A component is a top-level subdirectory of the ``mahavishnu`` package that
    contains a real ``__init__.py`` (so it's a real Python package) and isn't
    in :data:`_NON_COMPONENT_DIRS`.
    """
    pkg_root = project / "mahavishnu"
    if not pkg_root.is_dir():
        return []
    components: list[str] = []
    for entry in sorted(pkg_root.iterdir()):
        if entry.name in _NON_COMPONENT_DIRS:
            continue
        if not entry.is_dir():
            continue
        if not (entry / "__init__.py").exists():
            continue
        components.append(f"mahavishnu/{entry.name}")
    return components


# ---------------------------------------------------------------------------
# Test type → on-disk location mapping (Python)
# ---------------------------------------------------------------------------


# Where to look for tests of a given type. Each entry maps a test type to a
# subdirectory name under ``tests/``. ``None`` means "no conventional
# subdirectory" — fall back to marker-based discovery.
_TEST_TYPE_DIRS: dict[str, str | None] = {
    "unit": "unit",
    "integration": "integration",
    "e2e": "e2e",
    "property": "property",
    "chaos": "chaos",
}


# Subdirectories of ``tests/`` that hold top-level test files (not a
# "category" bucket). Files placed directly in ``tests/`` count toward
# whatever test_type the user requested.
_UNCATEGORIZED_TEST_SUBDIRS: frozenset[str] = frozenset(
    {"examples", "fixtures", "archived", "__pycache__"}
)


# ---------------------------------------------------------------------------
# Import → component mapping
# ---------------------------------------------------------------------------

# Matches ``from mahavishnu.X... import ...`` and ``import mahavishnu.X...``
# at the top-of-file. Anchored to the line start to avoid matching the word
# "mahavishnu" inside a docstring or comment that happens to mention imports.
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+mahavishnu(?:\s*\.\s*|\s+)([a-zA-Z_][\w.]*)|import\s+mahavishnu(?:\s*\.\s*|\s+)([a-zA-Z_][\w.]*))",
    re.MULTILINE,
)


def infer_component_from_imports(test_file: Path) -> str | None:
    """Guess the component under test by scanning the file's imports.

    Returns the first ``mahavishnu.<sub>`` sub-package referenced, or ``None``
    if nothing is found. The first match is used because most test files
    focus on a single component.
    """
    try:
        text = test_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for match in _IMPORT_RE.finditer(text):
        target = match.group(1) or match.group(2)
        if not target:
            continue
        head = target.split(".", 1)[0]
        # ``from mahavishnu import X`` (no submodule) makes the regex
        # greedily capture the literal token ``import`` as the head.
        # That isn't a real component — fall through to the caller's
        # filename-based heuristic and catch-all bucket.
        if head == "import":
            return None
        candidate = f"mahavishnu/{head}"
        return candidate
    return None


def infer_component_from_filename(test_file: Path, tests_root: Path) -> str | None:
    """Heuristic fallback: pull the component from the test file name.

    e.g. ``test_websocket_integration.py`` -> ``mahavishnu/websocket``.
    Strips the ``test_`` prefix and common suffix tokens like
    ``_integration``, ``_impl``, ``_contract``.
    """
    rel = test_file.relative_to(tests_root)
    # If the file lives in tests/<bucket>/test_X.py, treat the first path
    # segment as the bucket and use the file stem's subject.
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "unit":
        subject = parts[-1]
    elif len(parts) >= 3:
        # e.g. unit/core/test_health.py -> core
        subject = parts[-2]
    else:
        subject = parts[-1]
    stem = subject.removeprefix("test_").removesuffix(".py")
    for suffix in ("_integration", "_impl", "_contract", "_properties", "_property"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if not stem:
        return None
    return f"mahavishnu/{stem}"


def map_test_files_to_components(
    test_files: Iterable[Path],
    tests_root: Path,
    valid_components: set[str] | None = None,
) -> dict[str, list[str]]:
    """Group test files by the component they exercise.

    Strategy: scan imports first (most accurate), fall back to filename
    heuristic, fall back to "mahavishnu" (catch-all bucket) so uncovered
    test files are still visible.

    If ``valid_components`` is provided, any inferred component that isn't
    in the set is treated as a phantom (the stem didn't match a real
    subpackage) and the test file is bucketed into the catch-all
    ``mahavishnu`` component instead. Pass ``None`` to disable the check.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for tf in test_files:
        rel = tf.relative_to(tests_root).as_posix()
        component = infer_component_from_imports(tf) or infer_component_from_filename(
            tf, tests_root
        )
        if component is None:
            component = "mahavishnu"  # catch-all for no-signal files
        elif valid_components is not None and component not in valid_components:
            # Filename or import heuristic produced a phantom — fall back
            # to the catch-all rather than marking a non-existent
            # component as "covered".
            component = "mahavishnu"
        grouped[component].append(rel)
    return dict(grouped)


# ---------------------------------------------------------------------------
# Stack-specific discovery
# ---------------------------------------------------------------------------


def discover_python_tests(project: Path, test_type: str) -> list[Path]:
    """Collect all test files for ``test_type`` in a Python project.

    Looks in the canonical ``tests/<test_type>/`` directory for files
    matching ``test_*.py``. Top-level ``tests/test_*.py`` files are NOT
    auto-bucketed into the requested test type — that would misclassify
    them (e.g. ``tests/test_*.py`` would falsely appear as e2e tests).
    Callers that want top-level tests should use a custom test type via
    ``--types``. There is no marker-based fallback: this function
    performs a deterministic, directory-based scan only.
    """
    tests_root = project / "tests"
    if not tests_root.is_dir():
        return []
    found: set[Path] = set()
    canonical_dir = _TEST_TYPE_DIRS.get(test_type)
    if canonical_dir is not None:
        candidate = tests_root / canonical_dir
        if candidate.is_dir():
            found.update(candidate.rglob("test_*.py"))
    # Filter out the buckets we never want to count
    return sorted(
        tf for tf in found if not any(part in _UNCATEGORIZED_TEST_SUBDIRS for part in tf.parts)
    )


# Markers we look for on individual tests. Read from pyproject.toml's
# ``[tool.pytest] markers`` table at module import time.
#
# Module-level cache keyed by the *resolved* file path. Each entry stores
# ``(mtime_ns, file_size, markers)`` so we re-read the file when either
# the on-disk mtime or the size changes (i.e. the file was edited
# between script invocations when this module is imported as a library).
#
# Resolving the path before keying means the same logical file reached
# via different path strings (relative vs. absolute, symlink vs. real
# path) shares a single cache entry. Including ``file_size`` guards
# against second-precision filesystems (HFS+, FAT) where a same-second
# rewrite would otherwise hit the cache and miss the new markers.
_MARKER_FILE_CACHE: dict[str, tuple[int, int, set[str]]] = {}


def _has_marker(test_file: Path, marker: str) -> bool:
    """Cheap textual check for ``@pytest.mark.<marker>`` in a test file."""
    key = str(test_file.resolve())
    try:
        st = test_file.stat()
    except OSError:
        # File disappeared — treat as empty and clear any stale cache.
        _MARKER_FILE_CACHE.pop(key, None)
        return False
    mtime_ns = st.st_mtime_ns
    file_size = st.st_size
    cached = _MARKER_FILE_CACHE.get(key)
    if cached is None or cached[0] != mtime_ns or cached[1] != file_size:
        try:
            text = test_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        markers = set(re.findall(r"@pytest\.mark\.(\w+)", text))
        _MARKER_FILE_CACHE[key] = (mtime_ns, file_size, markers)
        return marker in markers
    return marker in cached[2]


def discover_node_tests(project: Path, test_type: str) -> list[Path]:
    """Minimal Node test discovery: walk for ``*.test.{ts,js}`` and ``__tests__``."""
    del test_type  # Currently single-bucket; we treat all node tests the same.
    found: set[Path] = set()
    for ext in ("ts", "js", "tsx", "jsx"):
        found.update(project.rglob(f"*.test.{ext}"))
    for tests_dir in project.rglob("__tests__"):
        if tests_dir.is_dir():
            for ext in ("ts", "js", "tsx", "jsx"):
                found.update(tests_dir.rglob(f"*.{ext}"))
    # Drop noisy directories.
    return sorted(
        p
        for p in found
        if not any(part in {"node_modules", ".next", "dist", "build"} for part in p.parts)
    )


def discover_go_tests(project: Path, test_type: str) -> list[Path]:
    """Minimal Go test discovery: walk for ``*_test.go``."""
    del test_type
    return sorted(
        p
        for p in project.rglob("*_test.go")
        if not any(part in {"vendor", ".git"} for part in p.parts)
    )


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------


def parse_coverage_xml(project: Path) -> dict[str, float] | None:
    """Parse ``coverage.xml`` (Cobertura format produced by coverage.py).

    Returns ``{relative_path_from_project: line_rate}`` — paths are verbatim
    Cobertura paths (relative to the project root, NOT stripped of
    extension) — or ``None`` if ``coverage.xml`` is absent or unparsable.

    Callers that need to cross-reference these paths with matrix component
    keys (``mahavishnu/core``) must derive the directory themselves, e.g.
    ``Path(p).parent.as_posix()``. We only use the dict to set a
    confidence flag on the matrix; cell-level line coverage per test type
    isn't feasible without mapping tests back to files.
    """
    cov = project / "coverage.xml"
    if not cov.is_file():
        return None
    try:
        tree = ET.parse(cov)
    except ET.ParseError:
        return None
    out: dict[str, float] = {}
    for cls in tree.getroot().iter("class"):
        filename = cls.get("filename")
        rate = cls.get("line-rate")
        if filename and rate is not None:
            try:
                out[filename] = float(rate)
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# Matrix assembly
# ---------------------------------------------------------------------------


def assemble_python_matrix(
    project: Path,
    components: list[str],
    test_types: list[str],
) -> dict[str, dict[str, ComponentCoverage]]:
    """Build the component x test_type matrix for the Python stack.

    Discovery is hoisted out of the (component x test_type) loop: a project
    with 20 components and 5 test types runs filesystem discovery 5 times
    (once per test type) instead of 100 times.
    """
    tests_root = project / "tests"
    valid_components: set[str] = set(components)

    # Cache: per test_type, the {component -> [rel_test_files]} mapping.
    per_type_mappings: dict[str, dict[str, list[str]]] = {}
    for test_type in test_types:
        test_files = discover_python_tests(project, test_type)
        per_type_mappings[test_type] = map_test_files_to_components(
            test_files, tests_root, valid_components
        )

    cells: dict[str, dict[str, ComponentCoverage]] = {}
    for component in components:
        cells[component] = {}
        for test_type in test_types:
            matched = per_type_mappings[test_type].get(component, [])
            gaps: list[str] = []
            if not matched:
                gaps.append(f"no {test_type} tests for module {component}")
            cells[component][test_type] = ComponentCoverage(
                covered=bool(matched),
                files=sorted(matched),
                gaps=gaps,
            )
    return cells


def assemble_node_matrix(
    project: Path,
    components: list[str],
    test_types: list[str],
) -> dict[str, dict[str, ComponentCoverage]]:
    """Node matrix: per-component coverage is approximated by directory."""
    test_files = discover_node_tests(project, test_types[0] if test_types else "unit")
    cells: dict[str, dict[str, ComponentCoverage]] = {}
    for component in components:
        comp_name = component.split("/", 1)[-1]
        matched = [p.relative_to(project).as_posix() for p in test_files if comp_name in p.parts]
        cells[component] = {}
        # Replicate the same `files` list across all test types so
        # downstream consumers don't see empty lists for non-first types.
        files = list(matched)
        for t in test_types:
            cells[component][t] = ComponentCoverage(
                covered=bool(matched),
                files=files,
                gaps=[] if matched else [f"no {t} tests in {component} tree"],
            )
    return cells


def assemble_go_matrix(
    project: Path,
    components: list[str],
    test_types: list[str],
) -> dict[str, dict[str, ComponentCoverage]]:
    """Go matrix: group tests by package directory."""
    test_files = discover_go_tests(project, test_types[0] if test_types else "unit")
    cells: dict[str, dict[str, ComponentCoverage]] = {}
    for component in components:
        comp_name = component.split("/", 1)[-1]
        matched = [p.relative_to(project).as_posix() for p in test_files if comp_name in p.parts]
        cells[component] = {}
        # Replicate the same `files` list across all test types so
        # downstream consumers don't see empty lists for non-first types.
        files = list(matched)
        for t in test_types:
            cells[component][t] = ComponentCoverage(
                covered=bool(matched),
                files=files,
                gaps=[] if matched else [f"no {t} tests in {component}"],
            )
    return cells


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def build_summary(
    cells: dict[str, dict[str, ComponentCoverage]],
    components: list[str],
    test_types: list[str],
    coverage_target: int,
    coverage_data: dict[str, float] | None,
) -> dict[str, Any]:
    """Compute the summary block of the JSON output."""
    total_components = len(components)
    total_cells = total_components * len(test_types)
    covered_cells = sum(1 for comp in components for t in test_types if cells[comp][t].covered)
    coverage_pct = round((covered_cells / total_cells) * 100, 1) if total_cells else 0.0
    below_target = [
        comp for comp in components if not all(cells[comp][t].covered for t in test_types)
    ]
    # Components with NO tests of ANY requested type. This is a subset of
    # ``below_target``; the two should not be conflated. Computed here
    # from the cells dict (same source of truth as ``below_target``) so
    # we don't have to thread a second value through every assembler.
    components_with_no_tests = [
        {
            "component": comp,
            "missing_test_types": [t for t in test_types if not cells[comp][t].covered],
        }
        for comp in components
        if not any(cells[comp][t].covered for t in test_types)
    ]
    summary: dict[str, Any] = {
        "total_components": total_components,
        "total_cells": total_cells,
        "covered_cells": covered_cells,
        "coverage_pct": coverage_pct,
        "below_target": below_target,
        "components_with_no_tests": components_with_no_tests,
    }
    if coverage_data:
        # Aggregate line coverage to a project-wide average.
        rates = [r for r in coverage_data.values() if 0.0 <= r <= 1.0]
        if rates:
            avg = sum(rates) / len(rates)
            summary["coverage_xml_present"] = True
            summary["avg_line_coverage_pct"] = round(avg * 100, 1)
            summary["coverage_target_pct"] = coverage_target
            summary["meets_line_coverage_target"] = (
                summary["avg_line_coverage_pct"] >= coverage_target
            )
        else:
            summary["coverage_xml_present"] = True
            summary["avg_line_coverage_pct"] = None
    else:
        summary["coverage_xml_present"] = False
    return summary


def render_markdown(
    project: str,
    stack: str,
    components: list[str],
    test_types: list[str],
    cells: dict[str, dict[str, ComponentCoverage]],
    summary: dict[str, Any],
    coverage_target: int,
) -> str:
    """Render the human-readable Markdown variant of the matrix."""
    lines: list[str] = []
    lines.append(f"# Test Coverage Matrix — `{project}`")
    lines.append("")
    lines.append(f"- **Stack**: `{stack}`")
    lines.append(f"- **Test types**: {', '.join(test_types)}")
    lines.append(f"- **Coverage target**: {coverage_target}%")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Components detected**: {summary['total_components']}")
    lines.append(f"- **Total cells**: {summary['total_cells']}")
    lines.append(f"- **Covered cells**: {summary['covered_cells']}")
    lines.append(f"- **Coverage %**: {summary['coverage_pct']}%")
    if summary.get("coverage_xml_present"):
        avg = summary.get("avg_line_coverage_pct")
        if avg is not None:
            meets = "yes" if summary.get("meets_line_coverage_target") else "no"
            lines.append(f"- **Line coverage (from coverage.xml)**: {avg}% (target met: {meets})")
    if summary["below_target"]:
        lines.append("- **Components below target**:")
        for comp in summary["below_target"]:
            lines.append(f"  - `{comp}`")
    lines.append("")
    lines.append("## Component × Test Type Matrix")
    lines.append("")
    # Header row
    header = ["Component"] + test_types
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for comp in components:
        row: list[str] = [f"`{comp}`"]
        for t in test_types:
            cell = cells[comp][t]
            if cell.covered and cell.files:
                # Show file count to keep the table compact.
                row.append(f"covered ({len(cell.files)} files)")
            else:
                row.append("missing")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    # Gaps section — explicit "what's missing"
    lines.append("## Gaps")
    lines.append("")
    any_gap = False
    for comp in components:
        for t in test_types:
            for gap in cells[comp][t].gaps:
                lines.append(f"- `{comp}` ({t}): {gap}")
                any_gap = True
    if not any_gap:
        lines.append("- No gaps detected for the selected test types.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_VALID_STACKS = ("python", "node", "go", "mixed")
_VALID_TYPES = ("unit", "integration", "e2e", "property", "chaos")


def _validate_output_path(label: str, candidate: Path, project_root: Path) -> Path | None:
    """Resolve ``candidate`` and confirm it lives strictly inside ``project_root``.

    Two guards enforced:
      1. The resolved path must be :py:meth:`Path.is_relative_to` the
         project root (rejects ``/tmp/../../etc/passwd`` style escapes).
      2. The resolved path must NOT equal the project root itself — a
         confused-deputy case where someone passes ``--out project_root``
         instead of ``--out project_root/matrix.json`` and we'd otherwise
         be willing to ``mkdir``/overwrite the project directory.

    Returns the resolved :class:`Path` on success, or ``None`` on failure
    (with a clear error already printed to stderr).
    """
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        print(
            f"error: {label} {candidate} could not be resolved: {exc}",
            file=sys.stderr,
        )
        return None
    if not resolved.is_relative_to(project_root):
        print(
            f"error: {label} {resolved} is outside the project root {project_root}",
            file=sys.stderr,
        )
        return None
    if resolved == project_root:
        print(
            f"error: {label} {resolved} resolves to the project root itself; "
            f"refusing to overwrite the project directory "
            f"(pass an explicit filename, e.g. {project_root}/test-matrix.json)",
            file=sys.stderr,
        )
        return None
    return resolved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="test_matrix.py",
        description=(
            "Generate a deterministic test coverage matrix for a project. "
            "Used by the quality-validation and test-harness tools."
        ),
    )
    parser.add_argument(
        "--project",
        required=True,
        type=Path,
        help="Path to the project root.",
    )
    parser.add_argument(
        "--stack",
        required=True,
        choices=_VALID_STACKS,
        help="Which test runner / stack the project uses.",
    )
    parser.add_argument(
        "--types",
        default="unit,integration",
        help=(
            "Comma-separated list of test types to include in the matrix. "
            f"Choices: {', '.join(_VALID_TYPES)}."
        ),
    )
    parser.add_argument(
        "--coverage-target",
        type=int,
        default=80,
        help="Coverage target percentage (used for the gap analysis only).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("./test-matrix.json"),
        help="Output path for the JSON matrix (default: ./test-matrix.json).",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Optional path for a human-readable Markdown summary.",
    )
    parser.add_argument(
        "--force-stack",
        default="",
        help=(
            "Comma-separated list of stacks to include even when the "
            "project-root marker file is missing. Useful for polyglot "
            "monorepos that have Go files in ``cmd/*.go`` but no top-level "
            "``go.mod``, or Node workspaces without a top-level "
            "``package.json``. Skips the marker check for the named "
            f"stacks. Choices: {', '.join(s for s in _VALID_STACKS if s != 'mixed')}."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a shell exit code."""
    args = parse_args(argv)

    # Normalize the comma-separated --types list, drop whitespace, dedupe,
    # preserve caller order. Reject unknown values up front.
    requested: list[str] = []
    for token in args.types.split(","):
        token = token.strip()
        if not token or token in requested:
            continue
        if token not in _VALID_TYPES:
            print(f"error: unknown test type '{token}'", file=sys.stderr)
            return 1
        requested.append(token)
    if not requested:
        print("error: --types resolved to an empty list", file=sys.stderr)
        return 1

    project: Path = args.project.resolve()
    if not project.is_dir():
        print(f"error: --project {project} is not a directory", file=sys.stderr)
        return 1

    if not (0 <= args.coverage_target <= 100):
        print(
            f"error: --coverage-target must be between 0 and 100 (got {args.coverage_target})",
            file=sys.stderr,
        )
        return 1

    # Validate that --out and --out-md resolve to a path inside the
    # project root. Prevents a user from accidentally writing the
    # matrix to ``/etc/...`` or ``/tmp/../../etc/passwd``. The same
    # check is re-applied after ``mkdir`` (see below) to close the
    # TOCTOU window where a parent directory could be symlink-swapped
    # between resolution and write.
    project_root = project  # already resolved above
    for label, candidate in (("--out", args.out), ("--out-md", args.out_md)):
        if candidate is None:
            continue
        if _validate_output_path(label, candidate, project_root) is None:
            return 1

    # Normalize --force-stack: drop empties, dedupe, reject unknowns.
    # This is the escape hatch for polyglot monorepos that have, e.g.,
    # Go files in ``cmd/*.go`` but no top-level ``go.mod`` (so the
    # M2 marker check would silently skip Go detection).
    forced_stacks: set[str] = set()
    for token in args.force_stack.split(","):
        token = token.strip()
        if not token or token in forced_stacks:
            continue
        if token not in _VALID_STACKS or token == "mixed":
            print(
                f"error: --force-stack got unknown stack '{token}' "
                f"(allowed: {', '.join(s for s in _VALID_STACKS if s != 'mixed')})",
                file=sys.stderr,
            )
            return 1
        forced_stacks.add(token)

    # Components: only the Python stack uses the package-based detection.
    # Node/Go callers get a basic "top-level dirs of <stack_root>" union.
    # We gate each non-Python detection on its project-root marker
    # (``package.json`` / ``go.mod``) so a Python-only project doesn't
    # get every top-level dir reported as a phantom Node or Go component.
    # ``--force-stack <stack>`` skips the marker check for the named
    # stack — see the polyglot-monorepo rationale above.
    components: list[str] = []
    if args.stack in ("python", "mixed"):
        components.extend(detect_components(project))
    if args.stack in ("node", "mixed") and (
        "node" in forced_stacks or (project / "package.json").is_file()
    ):
        for entry in sorted((project / "src").iterdir()) if (project / "src").is_dir() else []:
            if entry.is_dir():
                components.append(f"src/{entry.name}")
        for entry in sorted(project.iterdir()):
            if entry.is_dir() and entry.name.startswith("packages"):
                components.append(entry.name)
    if args.stack in ("go", "mixed") and ("go" in forced_stacks or (project / "go.mod").is_file()):
        for entry in sorted(project.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                # Cheap: top-level dirs that aren't obviously meta
                if entry.name not in {"docs", "scripts", "test", "tests", ".git", ".github"}:
                    components.append(entry.name)
    components = sorted(set(components))
    if not components:
        print(
            f"error: no components detected for stack '{args.stack}' in {project}",
            file=sys.stderr,
        )
        return 1

    # Build per-stack matrices, then union them.
    cells: dict[str, dict[str, ComponentCoverage]] = {}
    if args.stack == "python":
        cells = assemble_python_matrix(project, components, requested)
    elif args.stack == "node":
        cells = assemble_node_matrix(project, components, requested)
    elif args.stack == "go":
        cells = assemble_go_matrix(project, components, requested)
    else:  # mixed
        py_cells = assemble_python_matrix(
            project,
            [c for c in components if c.startswith("mahavishnu/")],
            requested,
        )
        cells.update(py_cells)
        non_py = [c for c in components if not c.startswith("mahavishnu/")]
        if non_py:
            other_cells = assemble_node_matrix(project, non_py, requested)
            cells.update(other_cells)

    # Optional coverage.xml cross-check (only meaningful for Python).
    coverage_data: dict[str, float] | None = None
    if args.stack in ("python", "mixed"):
        coverage_data = parse_coverage_xml(project)

    summary = build_summary(cells, components, requested, args.coverage_target, coverage_data)

    output: dict[str, Any] = {
        "project": str(project),
        "stack": args.stack,
        "types": requested,
        "coverage_target": args.coverage_target,
        "components": components,
        "cells": {comp: {t: cells[comp][t].to_dict() for t in requested} for comp in components},
        "summary": summary,
    }

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Second-pass TOCTOU check: re-resolve and re-validate after mkdir
    # in case the parent directory was symlink-swapped during the gap
    # (or the caller pointed at a not-yet-existing path that resolves
    # differently now that an ancestor exists).
    if _validate_output_path("--out", out_path, project_root) is None:
        return 1
    out_path.write_text(json.dumps(output, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    if args.out_md is not None:
        md = render_markdown(
            project=str(project),
            stack=args.stack,
            components=components,
            test_types=requested,
            cells=cells,
            summary=summary,
            coverage_target=args.coverage_target,
        )
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        # Same second-pass TOCTOU check for --out-md.
        if _validate_output_path("--out-md", args.out_md, project_root) is None:
            return 1
        args.out_md.write_text(md, encoding="utf-8")

    # Friendly one-line summary on stdout so callers can grep for it.
    print(
        f"test-matrix: stack={args.stack} components={summary['total_components']} "
        f"coverage={summary['coverage_pct']}% -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
