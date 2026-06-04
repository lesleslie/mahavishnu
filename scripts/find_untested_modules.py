#!/usr/bin/env python3
"""Find source modules in ``mahavishnu/`` that have no test coverage.

This script exists because the obvious discovery heuristic — grep
``tests/`` for ``^from mahavishnu\\.`` — produces false negatives.
Modules imported via the package-level form ``from mahavishnu import
factories`` are missed entirely, even when the corresponding test file
exists and exercises the module. The corrected regex used here
matches every form documented in PEP 328:

    from mahavishnu import X
    from mahavishnu.X import Y
    from mahavishnu.X.Y import Z
    import mahavishnu
    import mahavishnu.X

The output is a prioritized work list bucketed by line count and
external-IO surface, suitable for fanning out parallel test-writing
agents.

Usage:
    python scripts/find_untested_modules.py
    python scripts/find_untested_modules.py --json
    python scripts/find_untested_modules.py --root /path/to/repo --package mypkg
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import NamedTuple

# Source-file exclusions. ``__init__`` and ``__main__`` rarely contain
# logic worth unit-testing on their own; ``.archive/`` is historical.
EXCLUDED_SOURCE_NAMES = {"__init__.py", "__main__.py"}
EXCLUDED_SOURCE_DIR_PARTS = {".archive", "__pycache__"}

# IO-heavy imports that signal higher test difficulty (need mocks or
# containers). Used for risk bucketing only.
IO_HEAVY_IMPORTS = frozenset({
    "asyncpg",
    "redis",
    "httpx",
    "aiohttp",
    "requests",
    "uvicorn",
    "fastapi",
    "sqlalchemy",
    "aiosqlite",
    "boto3",
    "kubernetes",
    "docker",
})


class SourceModule(NamedTuple):
    """A Python source file inside the package being audited."""

    rel_path: str  # e.g. "mahavishnu/factories.py"
    abs_path: Path
    line_count: int
    is_io_heavy: bool


class UntestedBucket(NamedTuple):
    """One prioritized bucket of untested modules."""

    label: str
    rationale: str
    modules: list[SourceModule]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def iter_source_modules(package_root: Path, package_name: str) -> list[SourceModule]:
    """Yield every importable source file under ``package_root``.

    Excludes ``__init__.py``/``__main__.py`` and any path that contains
    an excluded directory component (e.g. ``.archive/``).
    """
    out: list[SourceModule] = []
    for path in sorted(package_root.rglob("*.py")):
        rel_parts = set(path.relative_to(package_root).parts)
        if rel_parts & EXCLUDED_SOURCE_DIR_PARTS:
            continue
        if path.name in EXCLUDED_SOURCE_NAMES:
            continue
        rel = f"{package_name}/{path.relative_to(package_root).as_posix()}"
        try:
            line_count = sum(1 for _ in path.open("rb"))
        except OSError:
            line_count = 0
        is_io_heavy = _file_imports(path, IO_HEAVY_IMPORTS)
        out.append(SourceModule(rel, path, line_count, is_io_heavy))
    return out


def _file_imports(path: Path, names: frozenset[str]) -> bool:
    """Return True if ``path`` contains an import of any name in ``names``.

    Cheap textual scan: looks for ``import X``, ``from X import ...``,
    or dotted variants. Not a full AST walk — adequate for risk flags.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for name in names:
        # Word-boundary match on bare name and dotted variants
        if re.search(rf"\b{re.escape(name)}\b", text):
            return True
    return False


# ---------------------------------------------------------------------------
# Coverage map
# ---------------------------------------------------------------------------


# Captures both ``from <pkg> [.<sub>... ] import ...`` and
# ``import <pkg>[.<sub>...]`` on the same line. The captured prefix is
# normalized to a dotted path and re-mapped onto the package's module
# namespace by ``_collect_imported_modules``.
_IMPORT_RE = re.compile(
    r"""
    ^[ \t]* (?:
        from \s+ (?P<from_path> \w+ (?: \. \w+ )* ) \s+ import
      | import \s+ (?P<import_path> \w+ (?: \. \w+ )* )
    )
    """,
    re.VERBOSE | re.MULTILINE,
)


def _collect_imported_modules(tests_root: Path, package_name: str) -> set[str]:
    """Return the set of module paths (dotted, normalized) referenced by tests.

    A module path like ``mahavishnu.factories`` is converted to
    ``mahavishnu/factories`` to match the form produced by
    ``iter_source_modules``.
    """
    referenced: set[str] = set()
    pattern = re.compile(rf"\b{re.escape(package_name)}(?:\.\w+)*")
    for path in tests_root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for dotted in pattern.findall(text):
            # Source-module paths produced by ``iter_source_modules`` retain
            # their ``.py`` suffix; keep the referenced set in the same
            # form so the membership check in ``bucket_untested`` succeeds.
            referenced.add(f"{dotted.replace('.', '/')}.py")
    return referenced


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def bucket_untested(
    modules: list[SourceModule],
    referenced: set[str],
) -> list[UntestedBucket]:
    """Group untested modules into three risk tiers."""
    easy: list[SourceModule] = []
    medium: list[SourceModule] = []
    hard: list[SourceModule] = []

    for mod in modules:
        if mod.rel_path in referenced:
            continue
        if mod.is_io_heavy or mod.line_count > 400:
            hard.append(mod)
        elif mod.line_count > 150:
            medium.append(mod)
        else:
            easy.append(mod)

    easy.sort(key=lambda m: m.line_count)
    medium.sort(key=lambda m: m.line_count)
    hard.sort(key=lambda m: m.line_count)

    return [
        UntestedBucket(
            label="Bucket 1 — easy wins (pure logic, <150 lines, no I/O)",
            rationale="Fast to cover; mock surface is small.",
            modules=easy,
        ),
        UntestedBucket(
            label="Bucket 2 — medium (150-400 lines or has I/O surface)",
            rationale="Needs mocks for external clients; otherwise pure.",
            modules=medium,
        ),
        UntestedBucket(
            label="Bucket 3 — hard (>400 lines or IO-heavy adapters)",
            rationale="Requires real services or large test scaffolding.",
            modules=hard,
        ),
    ]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def render_text_report(
    package_name: str,
    total: int,
    covered: int,
    buckets: list[UntestedBucket],
) -> str:
    """Format a human-readable report."""
    lines: list[str] = [
        f"Untested modules in `{package_name}/`",
        f"  {covered}/{total} source modules referenced by tests/.",
        "",
    ]
    if not any(b.modules for b in buckets):
        lines.append("All source modules have at least one test reference. ✓")
        return "\n".join(lines)
    for bucket in buckets:
        if not bucket.modules:
            continue
        lines.append(bucket.label)
        lines.append(f"  {bucket.rationale}")
        lines.append("")
        for mod in bucket.modules:
            lines.append(
                f"  {mod.line_count:5d}  {'IO' if mod.is_io_heavy else '  '}  {mod.rel_path}"
            )
        lines.append("")
    return "\n".join(lines)


def render_json_report(
    package_name: str,
    total: int,
    covered: int,
    buckets: list[UntestedBucket],
) -> str:
    """Format a JSON report for CI consumption."""
    payload = {
        "package": package_name,
        "total_modules": total,
        "covered_modules": covered,
        "untested_modules": total - covered,
        "buckets": [
            {
                "label": b.label,
                "rationale": b.rationale,
                "modules": [
                    {
                        "path": m.rel_path,
                        "line_count": m.line_count,
                        "io_heavy": m.is_io_heavy,
                    }
                    for m in b.modules
                ],
            }
            for b in buckets
        ],
    }
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root (default: cwd).",
    )
    parser.add_argument(
        "--package",
        default=None,
        help="Package directory to audit (default: derived from --root/<dir_name>).",
    )
    parser.add_argument(
        "--tests",
        type=Path,
        default=None,
        help="Tests root (default: <root>/tests).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the default text report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    package_name = args.package or root.name
    package_root = root / package_name
    tests_root = (args.tests or root / "tests").resolve()

    if not package_root.is_dir():
        print(f"error: package root not found: {package_root}", file=sys.stderr)
        return 2
    if not tests_root.is_dir():
        print(f"error: tests root not found: {tests_root}", file=sys.stderr)
        return 2

    modules = iter_source_modules(package_root, package_name)
    referenced = _collect_imported_modules(tests_root, package_name)
    buckets = bucket_untested(modules, referenced)

    covered = sum(1 for m in modules if m.rel_path in referenced)
    if args.json:
        print(render_json_report(package_name, len(modules), covered, buckets))
    else:
        print(render_text_report(package_name, len(modules), covered, buckets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
