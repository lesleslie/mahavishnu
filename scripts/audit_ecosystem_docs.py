#!/usr/bin/env python3
"""Audit docs directories across active Bodai ecosystem repositories.

This script is intentionally read-only. It inventories docs trees, applies
simple classification heuristics, and emits a text, JSON, or markdown report.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

import yaml

BACKUP_SUFFIXES = (".backup", ".backup.json", ".bak")
GENERATED_NAMES = {"coverage.json"}
GENERATED_SUFFIXES = (".tar.gz",)
STALE_ROOT_MARKERS = (
    "_SUMMARY",
    "_COMPLETE",
    "_COMPLETION",
    "_REPORT",
    "_PROGRESS",
    "_ACTION_PLAN",
)
PLAN_MARKERS = ("PLAN", "ROADMAP", "STRATEGY")
COUNT_CLAIM_PATTERNS: dict[str, re.Pattern[str]] = {
    "repo_count": re.compile(r"^-\s+\*\*(\d+)\s+git repositories\*\*", re.MULTILINE),
    "mcp_server_count": re.compile(r"^-\s+\*\*(\d+)\s+MCP servers\*\*", re.MULTILINE),
    "agent_count": re.compile(r"^-\s+\*\*(\d+)\s+Claude agents\*\*", re.MULTILINE),
    "workflow_count": re.compile(r"^-\s+\*\*(\d+)\s+workflows\*\*", re.MULTILINE),
    "skill_count": re.compile(r"^-\s+\*\*(\d+)\s+skills\*\*", re.MULTILINE),
    "tool_count": re.compile(r"^-\s+\*\*(\d+)\s+tools\*\*", re.MULTILINE),
    "role_count": re.compile(r"^-\s+\*\*(\d+)\s+role definitions\*\*", re.MULTILINE),
}


@dataclass(frozen=True)
class RepoDocsSummary:
    """Summary for one repository docs tree."""

    name: str
    path: str
    docs_path: str
    docs_exists: bool
    total_files: int
    markdown_files: int
    archive_files: int
    backup_like_files: int
    generated_files: int
    root_markdown_files: int
    stale_root_candidates: int
    has_docs_readme: bool
    has_archive_readme: bool
    has_plan_index: bool
    top_level_dirs: list[str]
    backup_like_paths: list[str]
    generated_paths: list[str]
    stale_root_paths: list[str]
    recommendations: list[str]


@dataclass(frozen=True)
class CatalogSnapshot:
    """Summary of the current ecosystem catalog."""

    ecosystem_path: str
    last_updated: str
    repo_count: int
    active_repo_count: int
    mcp_server_count: int
    agent_count: int
    workflow_count: int
    skill_count: int
    tool_count: int
    role_count: int


def load_ecosystem_data(ecosystem_path: Path) -> dict[str, Any]:
    """Load the raw ecosystem configuration payload."""
    data = yaml.safe_load(ecosystem_path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid ecosystem data in {ecosystem_path}")
    return data


def load_catalog_snapshot(ecosystem_path: Path) -> CatalogSnapshot:
    """Summarize the active catalog counts from ecosystem.yaml."""
    data = load_ecosystem_data(ecosystem_path)
    repos = data.get("repos", [])
    return CatalogSnapshot(
        ecosystem_path=str(ecosystem_path),
        last_updated=str(data.get("last_updated", "")),
        repo_count=len(repos) if isinstance(repos, list) else 0,
        active_repo_count=sum(
            1
            for repo in repos
            if isinstance(repo, dict) and repo.get("status", "active") == "active"
        )
        if isinstance(repos, list)
        else 0,
        mcp_server_count=len(data.get("mcp_servers", []))
        if isinstance(data.get("mcp_servers", []), list)
        else 0,
        agent_count=len(data.get("claude_agents", {}))
        if isinstance(data.get("claude_agents", {}), dict)
        else 0,
        workflow_count=len(data.get("workflows", {}))
        if isinstance(data.get("workflows", {}), dict)
        else 0,
        skill_count=len(data.get("skills", {})) if isinstance(data.get("skills", {}), dict) else 0,
        tool_count=len(data.get("tools", {})) if isinstance(data.get("tools", {}), dict) else 0,
        role_count=len(data.get("roles", [])) if isinstance(data.get("roles", []), list) else 0,
    )


def extract_catalog_claims(docs_path: Path) -> dict[str, int]:
    """Extract catalog count claims from docs/ECOSYSTEM.md."""
    if not docs_path.exists():
        return {}

    text = docs_path.read_text()
    claims: dict[str, int] = {}
    for field, pattern in COUNT_CLAIM_PATTERNS.items():
        match = pattern.search(text)
        if match:
            claims[field] = int(match.group(1))
    return claims


def audit_catalog_snapshot(snapshot: CatalogSnapshot, docs_path: Path) -> list[str]:
    """Compare the catalog snapshot to docs claims and freshness metadata."""
    issues: list[str] = []
    docs_claims = extract_catalog_claims(docs_path)
    labels = {
        "repo_count": "git repositories",
        "mcp_server_count": "MCP servers",
        "agent_count": "Claude agents",
        "workflow_count": "workflows",
        "skill_count": "skills",
        "tool_count": "tools",
        "role_count": "role definitions",
    }

    for field, label in labels.items():
        claimed = docs_claims.get(field)
        actual = getattr(snapshot, field)
        if claimed is not None and claimed != actual:
            issues.append(
                f"docs/ECOSYSTEM.md claims {claimed} {label} but {snapshot.ecosystem_path} has {actual}"
            )

    if snapshot.last_updated:
        try:
            updated = date.fromisoformat(snapshot.last_updated)
        except ValueError:
            issues.append(
                f"{snapshot.ecosystem_path} has invalid last_updated metadata: {snapshot.last_updated!r}"
            )
        else:
            age_days = (date.today() - updated).days
            if age_days > 30:
                issues.append(
                    f"{snapshot.ecosystem_path} last_updated is {age_days} days old; refresh catalog metadata"
                )
    else:
        issues.append(f"{snapshot.ecosystem_path} is missing last_updated metadata")

    return issues


def audit_health_probe_metadata(ecosystem_data: dict[str, Any]) -> list[str]:
    """Check enabled HTTP MCP servers for health metadata."""
    issues: list[str] = []
    for server in ecosystem_data.get("mcp_servers", []):
        if not isinstance(server, dict):
            continue
        if server.get("status", "enabled") != "enabled":
            continue
        if server.get("type") == "http" and not server.get("health_check"):
            issues.append(
                f"{server.get('name', '<unknown>')}: enabled HTTP server is missing health_check"
            )
    return issues


def build_audit_report(
    ecosystem_path: Path,
) -> tuple[CatalogSnapshot, list[str], list[RepoDocsSummary]]:
    """Build the catalog snapshot, drift issues, and per-repo summaries."""
    ecosystem_data = load_ecosystem_data(ecosystem_path)
    snapshot = load_catalog_snapshot(ecosystem_path)
    docs_path = ecosystem_path.parent.parent / "docs" / "ECOSYSTEM.md"
    issues = audit_catalog_snapshot(snapshot, docs_path)
    issues.extend(audit_health_probe_metadata(ecosystem_data))
    repos = [
        repo for repo in ecosystem_data.get("repos", []) if repo.get("status", "active") == "active"
    ]
    summaries = [summarize_repo(repo) for repo in repos]
    return snapshot, issues, summaries


def load_active_repos(ecosystem_path: Path) -> list[dict[str, Any]]:
    """Load active repository entries from ecosystem.yaml."""
    data = load_ecosystem_data(ecosystem_path)
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"Invalid repos list in {ecosystem_path}")
    return [repo for repo in repos if repo.get("status", "active") == "active"]


def is_backup_like(path: Path) -> bool:
    """Return whether a file looks like a backup artifact."""
    name = path.name
    return (
        ".backups" in path.parts
        or ("backups" in path.parts and "archive" not in path.parts)
        or name.endswith(BACKUP_SUFFIXES)
        or name.endswith(GENERATED_SUFFIXES)
    )


def is_generated(path: Path) -> bool:
    """Return whether a file looks generated rather than authored."""
    return path.name in GENERATED_NAMES or path.name.endswith(GENERATED_SUFFIXES)


def is_stale_root_candidate(path: Path, docs_path: Path) -> bool:
    """Return whether a root markdown file looks like a stale report/summary."""
    if path.parent != docs_path or path.suffix.lower() != ".md":
        return False
    stem = path.stem.upper()
    return any(marker in stem for marker in STALE_ROOT_MARKERS)


def has_plan_index(docs_path: Path) -> bool:
    """Return whether docs has a plan index."""
    return (docs_path / "plans" / "PLAN_INDEX.md").exists() or (
        docs_path / "plans" / "README.md"
    ).exists()


def repo_relative(path: Path, repo_path: Path) -> str:
    """Return a path relative to the repo root."""
    return str(path.relative_to(repo_path))


def _categorize_docs_files(docs_path: Path) -> dict[str, list[Path]]:
    """Categorize files within a docs directory.

    Returns a dict with keys: all_files, markdown, archive, backup_like,
    generated, root_markdown, stale_root_candidates.
    """
    files = [path for path in docs_path.rglob("*") if path.is_file()]
    markdown_files = [path for path in files if path.suffix.lower() == ".md"]
    archive_files = [path for path in files if "archive" in path.parts]
    backup_like_files = [path for path in files if is_backup_like(path)]
    generated_files = [path for path in files if is_generated(path)]
    root_markdown_files = [path for path in markdown_files if path.parent == docs_path]
    stale_root_candidates = [
        path for path in markdown_files if is_stale_root_candidate(path, docs_path)
    ]
    return {
        "all_files": files,
        "markdown": markdown_files,
        "archive": archive_files,
        "backup_like": backup_like_files,
        "generated": generated_files,
        "root_markdown": root_markdown_files,
        "stale_root_candidates": stale_root_candidates,
    }


def _build_repo_recommendations(
    docs_path: Path,
    docs_exists: bool,
    categories: dict[str, list[Path]],
) -> list[str]:
    """Build recommendation strings for a repo's docs directory."""
    recommendations: list[str] = []
    if not docs_exists:
        recommendations.append("create docs/ or confirm repo intentionally has no docs")
        return recommendations

    if not (docs_path / "README.md").exists():
        recommendations.append("add docs/README.md")
    if categories["archive"] and not (docs_path / "archive" / "README.md").exists():
        recommendations.append("add docs/archive/README.md")

    root_plan_like_files = [
        path
        for path in categories["root_markdown"]
        if any(marker in path.stem.upper() for marker in PLAN_MARKERS)
    ]
    if len(root_plan_like_files) > 3 and not has_plan_index(docs_path):
        recommendations.append("add docs/plans/PLAN_INDEX.md")
    if categories["backup_like"]:
        recommendations.append("review/remove backup-like artifacts under docs")
    if categories["generated"]:
        recommendations.append("move generated artifacts out of docs")
    if categories["stale_root_candidates"]:
        recommendations.append("move stale root reports/summaries into archive")
    return recommendations


def summarize_repo(repo: dict[str, Any]) -> RepoDocsSummary:
    """Summarize docs health for one repo."""
    repo_path = Path(str(repo["path"]))
    docs_path = repo_path / "docs"
    docs_exists = docs_path.exists()

    categories = _categorize_docs_files(docs_path) if docs_exists else {
        "all_files": [], "markdown": [], "archive": [], "backup_like": [],
        "generated": [], "root_markdown": [], "stale_root_candidates": [],
    }

    files = categories["all_files"]
    markdown_files = categories["markdown"]
    archive_files = categories["archive"]
    backup_like_files = categories["backup_like"]
    generated_files = categories["generated"]
    stale_root_candidates = categories["stale_root_candidates"]
    root_markdown_files = categories["root_markdown"]

    recommendations = _build_repo_recommendations(
        docs_path, docs_exists, categories
    )

    return RepoDocsSummary(
        name=str(repo["name"]),
        path=str(repo_path),
        docs_path=str(docs_path),
        docs_exists=docs_exists,
        total_files=len(files),
        markdown_files=len(markdown_files),
        archive_files=len(archive_files),
        backup_like_files=len(backup_like_files),
        generated_files=len(generated_files),
        root_markdown_files=len(root_markdown_files),
        stale_root_candidates=len(stale_root_candidates),
        has_docs_readme=(docs_path / "README.md").exists(),
        has_archive_readme=(docs_path / "archive" / "README.md").exists(),
        has_plan_index=has_plan_index(docs_path),
        top_level_dirs=(
            sorted(path.name for path in docs_path.iterdir() if path.is_dir())
            if docs_exists else []
        ),
        backup_like_paths=sorted(repo_relative(path, repo_path) for path in backup_like_files),
        generated_paths=sorted(repo_relative(path, repo_path) for path in generated_files),
        stale_root_paths=sorted(repo_relative(path, repo_path) for path in stale_root_candidates),
        recommendations=recommendations,
    )


def render_text(
    summaries: list[RepoDocsSummary],
    *,
    catalog: CatalogSnapshot | None = None,
    catalog_issues: list[str] | None = None,
) -> str:
    """Render a concise text report."""
    lines = []
    if catalog is not None:
        lines.extend(
            [
                "CATALOG SUMMARY",
                f"  ecosystem.yaml: {catalog.ecosystem_path}",
                f"  repos: {catalog.repo_count} total / {catalog.active_repo_count} active",
                f"  mcp_servers: {catalog.mcp_server_count}",
                f"  agents: {catalog.agent_count}",
                f"  workflows: {catalog.workflow_count}",
                f"  skills: {catalog.skill_count}",
                f"  tools: {catalog.tool_count}",
                f"  roles: {catalog.role_count}",
            ]
        )
        if catalog_issues:
            lines.append("CATALOG ISSUES")
            for issue in catalog_issues:
                lines.append(f"  - {issue}")
        lines.append("")
    for summary in summaries:
        status = "OK" if summary.has_docs_readme and not summary.backup_like_files else "CHECK"
        lines.append(
            f"{status:5} {summary.name:14} files={summary.total_files:<4} "
            f"md={summary.markdown_files:<4} archive={summary.archive_files:<4} "
            f"backup_like={summary.backup_like_files:<3} "
            f"stale_root={summary.stale_root_candidates:<3}"
        )
        for recommendation in summary.recommendations:
            lines.append(f"      - {recommendation}")
    return "\n".join(lines)


def render_markdown(
    summaries: list[RepoDocsSummary],
    *,
    include_files: bool = False,
    catalog: CatalogSnapshot | None = None,
    catalog_issues: list[str] | None = None,
) -> str:
    """Render a markdown report."""
    totals = Counter()
    for summary in summaries:
        totals["files"] += summary.total_files
        totals["markdown"] += summary.markdown_files
        totals["archive"] += summary.archive_files
        totals["backup_like"] += summary.backup_like_files
        totals["generated"] += summary.generated_files

    lines = [
        "# Ecosystem Docs Audit",
        "",
        "Generated by `scripts/audit_ecosystem_docs.py`.",
        "",
    ]
    if catalog is not None:
        lines.extend(
            [
                "## Catalog Summary",
                "",
                f"- Ecosystem file: `{catalog.ecosystem_path}`",
                f"- Repos: {catalog.repo_count} total / {catalog.active_repo_count} active",
                f"- MCP servers: {catalog.mcp_server_count}",
                f"- Agents: {catalog.agent_count}",
                f"- Workflows: {catalog.workflow_count}",
                f"- Skills: {catalog.skill_count}",
                f"- Tools: {catalog.tool_count}",
                f"- Roles: {catalog.role_count}",
                "",
            ]
        )
        if catalog_issues:
            lines.extend(["## Catalog Issues", ""])
            for issue in catalog_issues:
                lines.append(f"- {issue}")
            lines.append("")
    lines.extend(
        [
            "## Totals",
            "",
            f"- Repos: {len(summaries)}",
            f"- Files: {totals['files']}",
            f"- Markdown files: {totals['markdown']}",
            f"- Archive files: {totals['archive']}",
            f"- Backup-like files: {totals['backup_like']}",
            f"- Generated files: {totals['generated']}",
            "",
            "## Repo Summary",
            "",
            "| Repo | Files | Markdown | Archive | Backup-like | Generated | Root stale candidates | docs README | Archive README | Plan index |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for summary in summaries:
        lines.append(
            f"| `{summary.name}` | {summary.total_files} | {summary.markdown_files} | "
            f"{summary.archive_files} | {summary.backup_like_files} | "
            f"{summary.generated_files} | {summary.stale_root_candidates} | "
            f"{'yes' if summary.has_docs_readme else 'no'} | "
            f"{'yes' if summary.has_archive_readme else 'no'} | "
            f"{'yes' if summary.has_plan_index else 'no'} |"
        )

    lines.extend(["", "## Recommendations", ""])
    lines.extend(_render_markdown_recommendations(summaries))

    if include_files:
        lines.extend(_render_markdown_cleanup_candidates(summaries))

    return "\n".join(lines).rstrip() + "\n"


def _render_markdown_recommendations(summaries: list[RepoDocsSummary]) -> list[str]:
    """Render the recommendations section of the markdown report."""
    lines: list[str] = []
    for summary in summaries:
        lines.append(f"### {summary.name}")
        lines.append("")
        if summary.recommendations:
            for recommendation in summary.recommendations:
                lines.append(f"- {recommendation}")
        else:
            lines.append("- no immediate structural recommendations")
        lines.append("")
    return lines


def _render_markdown_cleanup_candidates(summaries: list[RepoDocsSummary]) -> list[str]:
    """Render the detailed cleanup candidates section of the markdown report."""
    lines = ["## Detailed Cleanup Candidates", ""]
    for summary in summaries:
        lines.append(f"### {summary.name}")
        lines.append("")
        if not (
            summary.backup_like_paths or summary.generated_paths or summary.stale_root_paths
        ):
            lines.append("- no detailed candidates")
            lines.append("")
            continue

        if summary.backup_like_paths:
            lines.append("Backup-like files:")
            lines.append("")
            for path in summary.backup_like_paths:
                lines.append(f"- `{path}`")
            lines.append("")
        if summary.generated_paths:
            lines.append("Generated files:")
            lines.append("")
            for path in summary.generated_paths:
                lines.append(f"- `{path}`")
            lines.append("")
        if summary.stale_root_paths:
            lines.append("Root stale candidates:")
            lines.append("")
            for path in summary.stale_root_paths:
                lines.append(f"- `{path}`")
            lines.append("")
    return lines


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ecosystem",
        type=Path,
        default=Path("settings/ecosystem.yaml"),
        help="Path to Mahavishnu ecosystem.yaml.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json", "markdown"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--write",
        type=Path,
        default=None,
        help="Optional path to write the report instead of stdout.",
    )
    parser.add_argument(
        "--include-files",
        action="store_true",
        help="Include detailed file-level cleanup candidates in markdown output.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the docs audit."""
    args = parse_args()
    catalog, catalog_issues, summaries = build_audit_report(args.ecosystem)

    if args.output == "json":
        rendered = json.dumps([asdict(summary) for summary in summaries], indent=2)
    elif args.output == "markdown":
        rendered = render_markdown(
            summaries,
            include_files=args.include_files,
            catalog=catalog,
            catalog_issues=catalog_issues,
        )
    else:
        rendered = render_text(summaries, catalog=catalog, catalog_issues=catalog_issues)

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered)
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
