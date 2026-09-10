#!/usr/bin/env python3
"""Three-way consistency check: PLAN_INDEX.md <-> filesystem <-> Dhara.

Usage:
    python scripts/audit_plan_index.py [--repo-root PATH]
    python scripts/audit_plan_index.py --dhara-records records.json

Exits 0 if consistent; exits 1 if any of these fail:
  - Every entry in PLAN_INDEX.md corresponds to a .md file on disk.
  - Every .md file with valid frontmatter appears in PLAN_INDEX.md.
  - Every Dhara-stored record is also in PLAN_INDEX.md.

The Dhara leg is opt-in. The CLI reads records from a JSON file
(``--dhara-records``) so the audit stays runnable in CI without a live
Dhara instance; callers that already hold a ``PlanIndexStore`` can use
:func:`collect_dhara_paths` instead. Records not present in Dhara but
present in the rendered index are reported as warnings, not failures --
the rendered artifact is allowed to lag a TTL-expired record.

Two index renderers are supported so the audit keeps working across the
cut-over:
  - legacy ``scripts/regenerate_plan_index.py`` rows, whose first column
    is a markdown link with a backticked repo-relative path;
  - ``mahavishnu.plan_index.render`` rows, shaped ``| DATE | path | ...``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

# Rows emitted by mahavishnu.plan_index.render: "| YYYY-MM-DD | path | ..."
_RENDERED_ROW_RE = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|\s*([^|\s]+)\s*\|")
# Legacy rows emitted by scripts/regenerate_plan_index.py: "| [`path`](target) | ..."
_LEGACY_LINK_RE = re.compile(r"\[`([^`]+\.md)`\]\(")

#: Number of offending paths printed per failure category.
_MAX_REPORTED = 10


def extract_index_paths(index_text: str) -> set[str]:
    """Repo-relative paths referenced by a rendered PLAN_INDEX.md.

    Accepts both the legacy and the Dhara-canonical row shapes; a file
    mid-migration may contain either.
    """
    paths: set[str] = set()
    for line in index_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        rendered = _RENDERED_ROW_RE.match(stripped)
        if rendered is not None:
            paths.add(rendered.group(1))
            continue
        paths.update(_LEGACY_LINK_RE.findall(stripped))
    return paths


def scan_disk_paths(repo_root: Path, yaml_module: Any | None = None) -> set[str]:
    """Repo-relative paths of every frontmatter-bearing .md file on disk.

    Delegates store discovery to ``scripts.regenerate_plan_index`` so the
    audit and the renderer never disagree about what counts as a store.
    """
    from scripts.regenerate_plan_index import (
        _has_frontmatter,
        _load_yaml_module,
        discover_files,
        discover_stores,
    )

    yaml_module = yaml_module if yaml_module is not None else _load_yaml_module()
    stores = discover_stores(repo_root, yaml_module)
    store_set = set(stores)
    paths: set[str] = set()
    for store_rel in stores:
        # Only stores NESTED UNDER this one are skipped, mirroring
        # regenerate_plan_index.main(). Skipping every other store would
        # drop each nested store's own files (a parent prefix would match).
        skip = frozenset(s for s in store_set if s != store_rel and s.startswith(store_rel))
        for abs_path, rel in discover_files(repo_root, store_rel, skip_deeper_stores=skip):
            if _has_frontmatter(abs_path, yaml_module):
                paths.add(rel)
    return paths


def dhara_paths_from_records(records: Iterable[dict[str, Any]]) -> set[str]:
    """Repo-relative paths carried by a sequence of plan record dicts."""
    paths: set[str] = set()
    for record in records:
        path = record.get("path")
        if isinstance(path, str) and path:
            paths.add(path)
    return paths


async def collect_dhara_paths(store: Any, *, limit: int = 1000) -> set[str]:
    """Repo-relative paths for every record a ``PlanIndexStore`` holds.

    ``store`` is typed loosely on purpose: the audit consumes the public
    ``list_all`` contract only, so a real store and ``FakeDhara``-backed
    store are interchangeable here.
    """
    records = await store.list_all(limit=limit)
    return dhara_paths_from_records(records)


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Outcome of the three-way comparison.

    ``dhara_checked`` distinguishes "Dhara agreed" from "Dhara was not
    consulted" -- an unchecked leg must never read as a pass.
    """

    in_index_only: frozenset[str] = frozenset()
    in_disk_only: frozenset[str] = frozenset()
    in_dhara_only: frozenset[str] = frozenset()
    missing_from_dhara: frozenset[str] = frozenset()
    dhara_checked: bool = False
    index_count: int = 0

    @property
    def failures(self) -> int:
        return sum(
            1 for group in (self.in_index_only, self.in_disk_only, self.in_dhara_only) if group
        )

    @property
    def ok(self) -> bool:
        return self.failures == 0


def audit(
    index_paths: set[str],
    disk_paths: set[str],
    dhara_paths: set[str] | None = None,
) -> AuditReport:
    """Compare the three views. Pure function -- no I/O."""
    return AuditReport(
        in_index_only=frozenset(index_paths - disk_paths),
        in_disk_only=frozenset(disk_paths - index_paths),
        in_dhara_only=frozenset(dhara_paths - index_paths)
        if dhara_paths is not None
        else frozenset(),
        missing_from_dhara=frozenset(index_paths - dhara_paths)
        if dhara_paths is not None
        else frozenset(),
        dhara_checked=dhara_paths is not None,
        index_count=len(index_paths),
    )


@dataclass(slots=True)
class _Lines:
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)


def _report_group(lines: _Lines, paths: frozenset[str], header: str, marker: str) -> None:
    if not paths:
        return
    lines.err.append(f"FAIL: {len(paths)} {header}")
    for path in sorted(paths)[:_MAX_REPORTED]:
        lines.err.append(f"  {marker} {path}")
    if len(paths) > _MAX_REPORTED:
        lines.err.append(f"  ... and {len(paths) - _MAX_REPORTED} more")


def format_report(report: AuditReport) -> _Lines:
    """Render an :class:`AuditReport` into stdout/stderr line buffers."""
    lines = _Lines()
    _report_group(lines, report.in_index_only, "paths in PLAN_INDEX.md but not on disk:", "-")
    _report_group(
        lines, report.in_disk_only, "frontmatter'd files missing from PLAN_INDEX.md:", "+"
    )
    _report_group(lines, report.in_dhara_only, "Dhara records missing from PLAN_INDEX.md:", "~")
    if report.missing_from_dhara:
        lines.out.append(
            f"WARN: {len(report.missing_from_dhara)} indexed paths have no Dhara record "
            "(expected while records are TTL-expiring)"
        )
    if report.ok:
        suffix = "" if report.dhara_checked else " (Dhara leg not checked)"
        lines.out.append(
            f"OK: {report.index_count} paths consistent across PLAN_INDEX.md and filesystem{suffix}"
        )
    return lines


def _load_dhara_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    if not isinstance(payload, list):
        raise TypeError(f"{path}: expected a JSON list of records")
    return [item for item in payload if isinstance(item, dict)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--dhara-records",
        type=Path,
        default=None,
        help="JSON file holding plan records (list, or {'records': [...]})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root: Path = args.repo_root.resolve()
    index_path = repo_root / "docs" / "plans" / "PLAN_INDEX.md"
    if not index_path.exists():
        print(f"PLAN_INDEX.md not found at {index_path}", file=sys.stderr)
        return 1

    index_paths = extract_index_paths(index_path.read_text(errors="replace"))
    disk_paths = scan_disk_paths(repo_root)

    dhara_paths: set[str] | None = None
    if args.dhara_records is not None:
        dhara_paths = dhara_paths_from_records(_load_dhara_records(args.dhara_records))

    report = audit(index_paths, disk_paths, dhara_paths)
    lines = format_report(report)
    for line in lines.out:
        print(line)
    for line in lines.err:
        print(line, file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
