#!/usr/bin/env python3
"""Audit script for traceable spec IDs (D2).

Walks plan/spec files for declared ``requirement_id`` entries and code for
references (inline comments, docstrings, pytest markers). Reports orphans
(declared but never referenced) and phantoms (referenced but never declared).

Exit codes:
    0 = clean
    1 = orphans or phantoms found
    2 = --root not found
    3 = internal error (uncaught exception)

Inspired by ``scripts/audit_orphans.py`` (the symbol-discovery audit). Keeps
the same flag surface and exit code semantics.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


REQUIREMENT_ID_RE = re.compile(r"\bREQ-[A-Z0-9-]*\d{2,}[A-Z0-9-]*\b")

# Inline reference marker: `# req: REQ-001` (or comma-separated list).
# Allows optional prefix between REQ and the numeric portion (e.g. REQ-ORC-001).
INLINE_REFERENCE_RE = re.compile(
    r"#\s*req:\s*((?:REQ-[A-Z0-9-]*\d{2,}[A-Z0-9-]*\s*,\s*)*REQ-[A-Z0-9-]*\d{2,}[A-Z0-9-]*)",
    re.IGNORECASE,
)

DOCSTRING_REFERENCE_RE = re.compile(
    r"#\s*implements:\s*((?:REQ-[A-Z0-9-]*\d{2,}[A-Z0-9-]*\s*,\s*)*REQ-[A-Z0-9-]*\d{2,}[A-Z0-9-]*)",
    re.IGNORECASE,
)

PYTEST_MARKER_REFERENCE_RE = re.compile(
    r"@pytest\.marker\.req\(\s*\[(?P<ids>[^\]]*)\]\s*\)",
    re.IGNORECASE,
)


@dataclass
class RequirementDecl:
    requirement_id: str
    source_path: Path
    line: int
    title: str
    description: str


@dataclass
class RequirementRef:
    requirement_id: str
    referencing_path: Path
    line: int
    reference_kind: str  # "comment" | "docstring" | "pytest_marker"


@dataclass
class AuditReport:
    declared: list[RequirementDecl] = field(default_factory=list)
    referenced: list[RequirementRef] = field(default_factory=list)
    orphans: list[RequirementDecl] = field(default_factory=list)
    phantoms: list[RequirementRef] = field(default_factory=list)


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter between leading ``---`` fences.

    Returns ``None`` if no frontmatter block is present. Uses PyYAML's
    safe loader to avoid executing arbitrary tags.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    block = text[3:end].lstrip("\n")
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return None


def extract_declarations(plan_paths: list[Path]) -> list[RequirementDecl]:
    """Find declared requirements from each plan file's frontmatter."""
    decls: list[RequirementDecl] = []
    for path in plan_paths:
        fm = parse_frontmatter(path)
        if not fm:
            continue
        requirements = fm.get("requirements") or []
        if not isinstance(requirements, list):
            continue
        for idx, item in enumerate(requirements, start=1):
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if not isinstance(rid, str) or not rid.startswith("REQ-"):
                continue
            decls.append(
                RequirementDecl(
                    requirement_id=rid,
                    source_path=path,
                    line=idx,  # 1-indexed position within the requirements list
                    title=str(item.get("title", "")),
                    description=str(item.get("description", "")),
                )
            )
    return decls


def extract_references(source_paths: list[Path]) -> list[RequirementRef]:
    """Find code/test references via inline comments, docstrings, pytest markers."""
    refs: list[RequirementRef] = []
    for path in source_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for kind, regex in (
            ("pytest_marker", PYTEST_MARKER_REFERENCE_RE),
            ("docstring", DOCSTRING_REFERENCE_RE),
            ("comment", INLINE_REFERENCE_RE),
        ):
            for match in regex.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                ids = _extract_ids_from_match(match)
                for rid in ids:
                    refs.append(
                        RequirementRef(
                            requirement_id=rid,
                            referencing_path=path,
                            line=line,
                            reference_kind=kind,
                        )
                    )
    return refs


def _extract_ids_from_match(match: re.Match[str]) -> list[str]:
    """Pull requirement IDs out of a regex match group.

    For pytest_marker, the IDs are inside ``[...]`` (group ``ids``) and may be
    quoted with ``"`` or ``'`` (Python list-literal syntax). For inline /
    docstring, they're comma-separated in group 1.

    Strips surrounding whitespace AND surrounding quote characters so
    ``@pytest.mark.req(["REQ-001", "REQ-002"])`` resolves to ``REQ-001`` and
    ``REQ-002`` rather than ``"REQ-001"`` / ``"REQ-002"``.
    """
    if "ids" in match.groupdict():
        raw = match.group("ids")
    else:
        raw = match.group(1)
    return [token.strip().strip("\"'") for token in raw.split(",") if token.strip().strip("\"'")]


def compute_diff(
    declared: list[RequirementDecl],
    referenced: list[RequirementRef],
) -> tuple[list[RequirementDecl], list[RequirementRef]]:
    """Compute orphans (declared but not referenced) and phantoms."""
    declared_ids = {d.requirement_id for d in declared}
    referenced_ids = {r.requirement_id for r in referenced}
    orphans = [d for d in declared if d.requirement_id not in referenced_ids]
    phantoms = [r for r in referenced if r.requirement_id not in declared_ids]
    return orphans, phantoms


def _matches_excluded(path: Path, exclude_globs: list[str]) -> bool:
    """Return True if any exclude pattern matches the path (suffix glob)."""
    p_str = str(path)
    return any(Path(p_str).match(pattern) or p_str.endswith(pattern) for pattern in exclude_globs)


def _collect_source_paths(root: Path, exclude_globs: list[str]) -> list[Path]:
    """Walk ``root`` for ``*.py`` files, honoring exclusions."""
    if not root.exists():
        return []
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root) if p.is_relative_to(root) else p
        rel_str = str(rel)
        if any(rel_str.endswith(pattern.lstrip("*")) for pattern in exclude_globs):
            continue
        paths.append(p)
    return paths


def _collect_plan_paths(plans_root: Path) -> list[Path]:
    if not plans_root.exists():
        return []
    return sorted(plans_root.rglob("*.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit traceable requirement IDs across plan files and code."
    )
    parser.add_argument(
        "--plans",
        default="docs/plans/",
        help="Glob or directory for plan files (default: docs/plans/).",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Source tree root (default: current directory).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/ when scanning for code references.",
    )
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[
            "**/conftest.py",
            "**/secrets.py",
            "**/.env.py",
            "**/fixtures/**",
            "**/snapshots/**",
            "**/__pycache__/**",
            "**/.venv/**",
            # Self-exclude: the regex patterns themselves contain "REQ-001"
            # as examples, which would otherwise produce a phantom.
            "**/audit_requirements.py",
        ],
        help="Glob (repeatable) for paths to exclude. Defaults to a safe baseline.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write a markdown report to this path.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout (machine-readable).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be reported without exiting non-zero.",
    )
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).resolve()
        if not root.exists():
            print(f"--root {root} does not exist", file=sys.stderr)
            return 2
        plans_root = (
            (root / args.plans).resolve()
            if not Path(args.plans).is_absolute()
            else Path(args.plans)
        )
        plan_paths = _collect_plan_paths(plans_root)
        source_paths = _collect_source_paths(root, args.exclude_glob)
        if args.include_tests:
            tests_root = root / "tests"
            if tests_root.exists():
                source_paths.extend(_collect_source_paths(tests_root, args.exclude_glob))

        declared = extract_declarations(plan_paths)
        referenced = extract_references(source_paths)
        orphans, phantoms = compute_diff(declared, referenced)

        report = AuditReport(
            declared=declared,
            referenced=referenced,
            orphans=orphans,
            phantoms=phantoms,
        )

        if args.json:
            print(json.dumps(_report_to_dict(report), indent=2, default=str))
        else:
            _print_human_report(report)

        if args.out:
            _write_markdown_report(report, Path(args.out))

        if (orphans or phantoms) and not args.dry_run:
            return 1
        return 0
    except Exception as exc:
        print(f"audit_requirements.py: internal error: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 3


def _report_to_dict(report: AuditReport) -> dict[str, Any]:
    """Serialize AuditReport to a JSON-safe dict."""
    return {
        "declared": [asdict(d) for d in report.declared],
        "referenced": [asdict(r) for r in report.referenced],
        "orphans": [asdict(d) for d in report.orphans],
        "phantoms": [asdict(r) for r in report.phantoms],
        "summary": {
            "declared_count": len(report.declared),
            "referenced_count": len(report.referenced),
            "orphan_count": len(report.orphans),
            "phantom_count": len(report.phantoms),
        },
    }


def _print_human_report(report: AuditReport) -> None:
    print(f"Declared:   {len(report.declared)}")
    print(f"Referenced: {len(report.referenced)}")
    print(f"Orphans:    {len(report.orphans)}")
    print(f"Phantoms:   {len(report.phantoms)}")
    if report.orphans:
        print("\n## Orphan Requirements (declared, never referenced)")
        for d in report.orphans:
            print(f"  - {d.requirement_id}  ({d.source_path}:{d.line})  {d.title}")
    if report.phantoms:
        print("\n## Phantom Requirements (referenced, never declared)")
        for r in report.phantoms:
            print(f"  - {r.requirement_id}  ({r.referencing_path}:{r.line}  {r.reference_kind})")


def _write_markdown_report(report: AuditReport, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Traceable Requirements Audit",
        "",
        f"- Declared: {len(report.declared)}",
        f"- Referenced: {len(report.referenced)}",
        f"- Orphans: {len(report.orphans)}",
        f"- Phantoms: {len(report.phantoms)}",
        "",
        "## Orphan Requirements",
        "",
    ]
    for d in report.orphans:
        lines.append(f"- `{d.requirement_id}` — {d.title} ({d.source_path}:{d.line})")
    if not report.orphans:
        lines.append("_(none)_")
    lines.extend(["", "## Phantom Requirements", ""])
    for r in report.phantoms:
        lines.append(f"- `{r.requirement_id}` — {r.reference_kind} ({r.referencing_path}:{r.line})")
    if not report.phantoms:
        lines.append("_(none)_")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
