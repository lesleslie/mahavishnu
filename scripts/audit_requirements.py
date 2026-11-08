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
    r"@pytest\.mark\.req\(\s*\[(?P<ids>[^\]]*)\]\s\)",
    re.IGNORECASE,
)

# A requirement ID with no namespace (``REQ-001``). The namespaced grammar is
# ``REQ-<PLAN>-<NNN>``; bare IDs predate it and collide across unrelated
# plans, so they are reported but never treated as failures.
BARE_ID_RE = re.compile(r"^REQ-\d+$")

# Plan lifecycle values that mean the plan's work is over. Their
# unimplemented requirements are history, not drift.
CLOSED_PLAN_STATUSES = frozenset({"complete", "shipped", "superseded"})

# Paths excluded from reference scanning by default.
_DEFAULT_EXCLUDES: list[str] = [
    "**/conftest.py",
    "**/secrets.py",
    "**/.env.py",
    "**/fixtures/**",
    "**/snapshots/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/.claude/worktrees/**",
    # Self-exclude: the regex patterns themselves contain "REQ-001"
    # as examples, which would otherwise produce a phantom. The test file
    # writes the same marker strings into synthetic trees, so it has to be
    # excluded for the same reason.
    "**/audit_requirements.py",
    "**/test_audit_requirements.py",
]


def _is_namespaced(requirement_id: str) -> bool:
    """True when the ID carries a namespace (``REQ-ORC-001``), not ``REQ-001``."""
    return not BARE_ID_RE.match(requirement_id)


def _repo_names(decl: RequirementDecl) -> list[str]:
    """The sibling repositories a requirement is implemented in.

    ``implementation_repo`` may name several repositories, comma-separated:
    a requirement implemented across the fleet is not owned by one of them.
    """
    if not decl.implementation_repo:
        return []
    return [part.strip() for part in decl.implementation_repo.split(",") if part.strip()]


@dataclass
class RequirementDecl:
    requirement_id: str
    source_path: Path
    line: int
    title: str
    description: str
    implementation_repo: str | None = None
    plan_status: str = ""
    plan_role: str = ""


@dataclass
class RequirementRef:
    requirement_id: str
    referencing_path: Path
    line: int
    reference_kind: str  # "comment" | "docstring" | "pytest_marker"
    external_repo: str | None = None


@dataclass
class AuditReport:
    declared: list[RequirementDecl] = field(default_factory=list)
    referenced: list[RequirementRef] = field(default_factory=list)
    orphans: list[RequirementDecl] = field(default_factory=list)
    phantoms: list[RequirementRef] = field(default_factory=list)
    # A requirement declared here but implemented in a sibling repo. Reported
    # separately: it is neither an orphan (it is implemented) nor a phantom
    # (it is declared).
    external: list[RequirementDecl] = field(default_factory=list)
    # An external requirement whose sibling repo is not available locally, so
    # the reference could not be confirmed. Non-fatal: the clone is missing,
    # not the implementation.
    unverified: list[RequirementDecl] = field(default_factory=list)
    # Declarations whose ID has no namespace (``REQ-001``). Fleet-wide these
    # collide across unrelated plans, so they cannot be traced to one owner.
    # Reported as a worklist, not as a failure.
    unnamespaced: list[RequirementDecl] = field(default_factory=list)
    # References to an ID that no declaration covers AND that carries no
    # namespace. The bare-ID convention predates the namespaced grammar and is
    # used informally across the tree; surfaced, but not fatal.
    informal: list[RequirementRef] = field(default_factory=list)


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
        plan_status = str(fm.get("status", "") or "")
        plan_role = str(fm.get("role", "") or "")
        for idx, item in enumerate(requirements, start=1):
            if not isinstance(item, dict):
                continue
            rid = item.get("id")
            if not isinstance(rid, str) or not rid.startswith("REQ-"):
                continue
            impl_repo = item.get("implementation_repo")
            decls.append(
                RequirementDecl(
                    requirement_id=rid,
                    source_path=path,
                    line=idx,  # 1-indexed position within the requirements list
                    title=str(item.get("title", "")),
                    description=str(item.get("description", "")),
                    implementation_repo=(
                        str(impl_repo) if isinstance(impl_repo, str) and impl_repo else None
                    ),
                    plan_status=plan_status,
                    plan_role=plan_role,
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


def scan_external_repos(
    declared: list[RequirementDecl],
    root: Path,
    overrides: dict[str, Path] | None = None,
) -> tuple[dict[str, set[str]], set[str], list[RequirementRef]]:
    """Look for requirement references in sibling repositories.

    A requirement may declare ``implementation_repo: <name>`` to say the
    implementation lives in another Bodai repository. That is the third
    category: the requirement is declared here and implemented there, so it is
    neither an orphan nor a phantom.

    ``<name>`` resolves to a sibling of ``root`` (``../<name>``) unless
    ``overrides`` maps it elsewhere. When the repo is not present locally the
    requirement is reported as *unverified* -- the clone is missing, not the
    implementation.

    Returns ``(found_ids, available_repo_names, external_refs)``.
    """
    overrides = overrides or {}
    wanted: dict[str, set[str]] = {}
    for d in declared:
        for repo_name in _repo_names(d):
            wanted.setdefault(repo_name, set()).add(d.requirement_id)

    found: dict[str, set[str]] = {}
    available: set[str] = set()
    refs: list[RequirementRef] = []

    for repo_name, ids in wanted.items():
        repo_path = overrides.get(repo_name, root.parent / repo_name)
        if not repo_path.is_dir():
            continue
        available.add(repo_name)
        repo_sources = _collect_source_paths(repo_path, _DEFAULT_EXCLUDES)
        repo_refs = extract_references(repo_sources)
        for ref in repo_refs:
            if ref.requirement_id not in ids:
                continue
            found.setdefault(ref.requirement_id, set()).add(repo_name)
            refs.append(
                RequirementRef(
                    requirement_id=ref.requirement_id,
                    referencing_path=ref.referencing_path,
                    line=ref.line,
                    reference_kind=ref.reference_kind,
                    external_repo=repo_name,
                )
            )

    return found, available, refs


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
    return [
        token.strip().strip("\"'")
        for token in raw.split(",")
        if token.strip().strip("\"'")
    ]


def compute_diff(
    declared: list[RequirementDecl],
    referenced: list[RequirementRef],
    external_referenced: dict[str, set[str]] | None = None,
    available_repos: set[str] | None = None,
) -> tuple[
    list[RequirementDecl],
    list[RequirementRef],
    list[RequirementDecl],
    list[RequirementDecl],
    list[RequirementDecl],
    list[RequirementRef],
]:
    """Split declarations and references into the categories the audit reports.

    Returns ``(orphans, phantoms, external, unverified, unnamespaced,
    informal)``.

    The ID grammar is what makes this more than a set difference:

    * A **namespaced** ID (``REQ-ORC-001``) names exactly one requirement.
      A namespaced declaration with no reference is an orphan; a namespaced
      reference with no declaration is a phantom. Both are failures.
    * A **bare** ID (``REQ-001``) is a repo-wide convention that predates the
      namespaced grammar. ``REQ-001`` means something different in the
      queueing plan, the worktree-settings tests and the producer-span plan,
      so a bare ID cannot be traced to one owner. Bare declarations and bare
      references are reported as worklists, never as failures.
    * An **external** requirement declares ``implementation_repo`` and is
      implemented in a sibling repository. It is satisfied by a reference
      there. If that repo is not cloned, the requirement is *unverified*
      rather than an orphan -- a missing clone is not a missing
      implementation.
    * A declaration in a **closed** plan (``complete`` / ``shipped`` /
      ``superseded``) describes work that is already over. Its unimplemented
      requirements are historical facts, not drift.
    """
    external_referenced = external_referenced or {}
    available_repos = available_repos or set()

    declared_ids = {d.requirement_id for d in declared}
    referenced_ids = {r.requirement_id for r in referenced}

    # A plan whose entire table is unreferenced is bookkeeping noise: it is
    # either a plan that has not started, or one whose implementation lives
    # elsewhere. Either way its own dead IDs say nothing about drift.
    referenced_per_plan: dict[Path, set[str]] = {}
    for d in declared:
        referenced_per_plan.setdefault(d.source_path, set())
        if d.requirement_id in referenced_ids:
            referenced_per_plan[d.source_path].add(d.requirement_id)
        elif d.requirement_id in external_referenced:
            referenced_per_plan[d.source_path].add(d.requirement_id)

    orphans: list[RequirementDecl] = []
    phantoms: list[RequirementRef] = []
    external: list[RequirementDecl] = []
    unverified: list[RequirementDecl] = []
    unnamespaced: list[RequirementDecl] = []
    informal: list[RequirementRef] = []

    for d in declared:
        if not _is_namespaced(d.requirement_id):
            unnamespaced.append(d)
            continue

        if d.requirement_id in referenced_ids:
            continue

        repo_names = _repo_names(d)
        if repo_names:
            if d.requirement_id in external_referenced:
                external.append(d)
            else:
                # ``implementation_repo`` is the operator's assertion that
                # the implementation lives in a sibling repo. The audit
                # confirms it when it finds a marker there; a missing
                # marker is a missing MARKER, not a missing implementation,
                # so this is reported rather than failed.
                unverified.append(d)
            continue

        if d.plan_status in CLOSED_PLAN_STATUSES:
            continue
        if not referenced_per_plan.get(d.source_path):
            continue
        orphans.append(d)

    for r in referenced:
        if r.requirement_id in declared_ids:
            continue
        if _is_namespaced(r.requirement_id):
            phantoms.append(r)
        else:
            informal.append(r)

    return orphans, phantoms, external, unverified, unnamespaced, informal


def _matches_excluded(path: Path, exclude_globs: list[str]) -> bool:
    """Return True if any exclude pattern matches the path.

    Uses ``Path.full_match`` (Python 3.13+) for proper ``**`` glob semantics.
    """
    return any(path.full_match(pattern) for pattern in exclude_globs)


def _collect_source_paths(root: Path, exclude_globs: list[str]) -> list[Path]:
    """Walk ``root`` for ``*.py`` files, honoring exclusions."""
    if not root.exists():
        return []
    paths: list[Path] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root) if p.is_relative_to(root) else p
        if _matches_excluded(rel, exclude_globs):
            continue
        paths.append(p)
    return paths


def _collect_plan_paths(plans_root: Path) -> list[Path]:
    """Plan files that carry requirement declarations.

    ``.archive/`` is skipped deliberately. The archive is git-ignored
    (``.gitignore``: ``.archive/``) and untracked, so it exists only on
    machines that happened to archive those plans locally. Scanning it makes
    the audit's verdict depend on the machine: on this Mac the archived
    declarations satisfy references that a fresh clone reports as phantoms.
    A requirement whose implementation is still live belongs in a tracked
    plan -- see ``docs/plans/2026-11-07-archived-requirements-registry.md``.
    """
    if not plans_root.exists():
        return []
    return sorted(p for p in plans_root.rglob("*.md") if ".archive" not in p.parts)


def _filter_dead_plans(
    declared: list[RequirementDecl],
    referenced_ids: set[str],
) -> list[RequirementDecl]:
    """Drop declarations from plans where every REQ is unreferenced.

    A plan whose whole table is dead is either not started yet or its
    implementation lives elsewhere; either way its dead IDs say nothing
    about drift, so they are not reported as orphans. The rule lives in
    ``compute_diff`` now, which also handles external implementations and
    closed plans; this helper is kept for callers that want the filtered
    declaration set on its own.
    """
    by_path: dict[Path, list[RequirementDecl]] = {}
    for d in declared:
        by_path.setdefault(d.source_path, []).append(d)
    kept: list[RequirementDecl] = []
    for path, decls in by_path.items():
        if any(d.requirement_id in referenced_ids for d in decls):
            kept.extend(decls)
    return kept


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
        default=list(_DEFAULT_EXCLUDES),
        help="Glob (repeatable) for paths to exclude. Defaults to a safe baseline.",
    )
    parser.add_argument(
        "--external-repo",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help=(
            "Location of a sibling repo that implements requirements declared "
            "here. Repeatable. Without it, a requirement's "
            "implementation_repo is resolved as a sibling of --root."
        ),
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
                source_paths.extend(
                    _collect_source_paths(tests_root, args.exclude_glob)
                )

        declared = extract_declarations(plan_paths)
        referenced = extract_references(source_paths)

        overrides: dict[str, Path] = {}
        for spec in args.external_repo:
            name, sep, path = spec.partition("=")
            if not sep or not path.strip():
                print(
                    f"audit_requirements.py: --external-repo needs NAME=PATH, got {spec!r}",
                    file=sys.stderr,
                )
                return 2
            overrides[name.strip()] = Path(path.strip()).expanduser()

        external_found, available_repos, external_refs = scan_external_repos(
            declared, root, overrides
        )

        orphans, phantoms, external, unverified, unnamespaced, informal = compute_diff(
            declared, referenced, external_found, available_repos
        )

        report = AuditReport(
            declared=declared,
            referenced=referenced + external_refs,
            orphans=orphans,
            phantoms=phantoms,
            external=external,
            unverified=unverified,
            unnamespaced=unnamespaced,
            informal=informal,
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
        "external": [asdict(d) for d in report.external],
        "unverified": [asdict(d) for d in report.unverified],
        "unnamespaced": [asdict(d) for d in report.unnamespaced],
        "informal": [asdict(r) for r in report.informal],
        "summary": {
            "declared_count": len(report.declared),
            "referenced_count": len(report.referenced),
            "orphan_count": len(report.orphans),
            "phantom_count": len(report.phantoms),
            "external_count": len(report.external),
            "unverified_count": len(report.unverified),
            "unnamespaced_count": len(report.unnamespaced),
            "informal_count": len(report.informal),
        },
    }


def _print_human_report(report: AuditReport) -> None:
    print(f"Declared:   {len(report.declared)}")
    print(f"Referenced: {len(report.referenced)}")
    print(f"Orphans:    {len(report.orphans)}")
    print(f"Phantoms:   {len(report.phantoms)}")
    print(f"External:   {len(report.external)}")
    print(f"Unverified: {len(report.unverified)}")
    print(f"Unnamespaced: {len(report.unnamespaced)}")
    print(f"Informal:   {len(report.informal)}")
    if report.orphans:
        print("\n## Orphan Requirements (declared, never referenced)")
        for d in report.orphans:
            print(f"  - {d.requirement_id}  ({d.source_path}:{d.line})  {d.title}")
    if report.phantoms:
        print("\n## Phantom Requirements (referenced, never declared)")
        for r in report.phantoms:
            print(
                f"  - {r.requirement_id}  ({r.referencing_path}:{r.line}  {r.reference_kind})"
            )
    if report.external:
        print("\n## External Requirements (declared here, implemented in a sibling repo)")
        for d in report.external:
            print(f"  - {d.requirement_id}  -> {d.implementation_repo}  {d.title}")
    if report.unverified:
        print("\n## Unverified External Requirements (sibling repo not available)")
        for d in report.unverified:
            print(f"  - {d.requirement_id}  -> {d.implementation_repo}  {d.title}")
    if report.unnamespaced:
        print("\n## Unnamespaced Declarations (bare REQ-NNN -- migration worklist)")
        for d in report.unnamespaced:
            print(f"  - {d.requirement_id}  ({d.source_path}:{d.line})  {d.title}")
    if report.informal:
        print("\n## Informal References (bare REQ-NNN with no declaration)")
        for r in report.informal:
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
        lines.append(
            f"- `{r.requirement_id}` — {r.reference_kind} ({r.referencing_path}:{r.line})"
        )
    if not report.phantoms:
        lines.append("_(none)_")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
