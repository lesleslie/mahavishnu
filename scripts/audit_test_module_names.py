#!/usr/bin/env python3
"""audit_test_module_names.py — find test files that collide on pytest module name.

pytest's default (``prepend``) import mode derives a test module's name from
its path: it walks up from the file's directory for as long as ``__init__.py``
exists, and uses the remainder as a dotted name. Two files that resolve to the
SAME name collide, and pytest then aborts the *entire* run with "import file
mismatch" — not just the colliding pair.

This is not hypothetical. ``tests/unit/test_config.py`` and
``tests/unit/test_core/test_config.py`` collided that way and took down the
whole suite collection (20,095 tests collected, 1 error, "Interrupted").

Two files sharing a *basename* is fine as long as at least one of their
directories is a package — the package path disambiguates the module name.
Only pairs that are BOTH in non-package directories collide. A repo-wide grep
for duplicate basenames therefore over-reports badly: this repo has 25
duplicate basenames and exactly one real collision.

The audit also flags a second hazard: a test directory whose name matches an
installed top-level package (``mcp``, ``mahavishnu``) would shadow that
package for the whole process once it carries an ``__init__.py``, because a
regular package beats a namespace portion regardless of path order.

Usage:
    python scripts/audit_test_module_names.py
    python scripts/audit_test_module_names.py --json
    python scripts/audit_test_module_names.py --repo-root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# Directory names that must never become regular packages under ``tests/``.
# A regular package beats a namespace portion, so ``tests/unit/mcp/__init__.py``
# would shadow the real ``mcp`` SDK for every import in the process.
SHADOW_DENY_LIST = frozenset({"mcp", "mahavishnu"})

_MAX_REPORTED = 20


def pytest_module_name(path: Path) -> str:
    """Return the module name pytest's ``prepend`` import mode gives ``path``.

    Mirrors pytest's own rule: walk up from the file's directory for as long as
    ``__init__.py`` exists, then use the remaining path as a dotted name.
    """
    directory = path.parent
    parts = [path.stem]
    while (directory / "__init__.py").exists():
        parts.insert(0, directory.name)
        directory = directory.parent
    return ".".join(parts)


def exposed_package_name(directory: Path) -> str:
    """Return the top-level import name a package directory would expose."""
    while (directory.parent / "__init__.py").exists():
        directory = directory.parent
    return directory.name


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Outcome of the test-module-name audit.

    ``collisions`` maps a duplicated pytest module name to the files claiming
    it. ``shadowed`` maps a deny-listed top-level name to the directories that
    would shadow the installed package.
    """

    collisions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shadowed: dict[str, tuple[str, ...]] = field(default_factory=dict)
    file_count: int = 0

    @property
    def failures(self) -> int:
        return len(self.collisions) + len(self.shadowed)

    @property
    def ok(self) -> bool:
        return self.failures == 0

    def to_json(self) -> dict[str, object]:
        """Render the report as a JSON-serialisable mapping."""
        return {
            "ok": self.ok,
            "file_count": self.file_count,
            "collisions": {name: list(paths) for name, paths in self.collisions.items()},
            "shadowed": {name: list(paths) for name, paths in self.shadowed.items()},
        }


@dataclass(slots=True)
class _Lines:
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)


def audit(tests_root: Path) -> AuditReport:
    """Audit ``tests_root`` for module-name collisions and shadowing dirs."""
    files = sorted(tests_root.rglob("test_*.py"))
    by_name: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        by_name[pytest_module_name(path)].append(path)

    collisions = {
        name: tuple(str(path) for path in paths)
        for name, paths in by_name.items()
        if len(paths) > 1
    }

    shadowed: dict[str, list[Path]] = defaultdict(list)
    for marker in sorted(tests_root.rglob("__init__.py")):
        directory = marker.parent
        name = exposed_package_name(directory)
        if name in SHADOW_DENY_LIST:
            shadowed[name].append(directory)

    return AuditReport(
        collisions=collisions,
        shadowed={name: tuple(str(path) for path in paths) for name, paths in shadowed.items()},
        file_count=len(files),
    )


def format_report(report: AuditReport) -> _Lines:
    """Render an :class:`AuditReport` into stdout/stderr line buffers."""
    lines = _Lines()
    for name, paths in sorted(report.collisions.items()):
        lines.err.append(f"FAIL: {len(paths)} test files share the pytest module name {name!r}")
        for path in paths[:_MAX_REPORTED]:
            lines.err.append(f"  - {path}")
        lines.err.append(
            "    fix: add an __init__.py to one of the directories (making it a "
            "package, which qualifies the module name), or rename one of the files"
        )
    for name, paths in sorted(report.shadowed.items()):
        lines.err.append(f"FAIL: {name!r} would shadow the installed package")
        for path in paths[:_MAX_REPORTED]:
            lines.err.append(f"  - {path}")
        lines.err.append(
            f"    fix: remove {name}/__init__.py — a namespace portion loses to the "
            "real package, a regular package does not"
        )
    if report.ok:
        lines.out.append(f"OK: {report.file_count} test files, no duplicate pytest module names")
    return lines


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the parent of scripts/)",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    tests_root = args.repo_root.resolve() / "tests"
    if not tests_root.is_dir():
        print(f"tests directory not found at {tests_root}", file=sys.stderr)
        return 1

    report = audit(tests_root)
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
        return 0 if report.ok else 1

    lines = format_report(report)
    for line in lines.out:
        print(line)
    for line in lines.err:
        print(line, file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
