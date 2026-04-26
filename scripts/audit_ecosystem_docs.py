#!/usr/bin/env python3
"""Audit docs directories across active Bodai ecosystem repositories.

This script is intentionally read-only. It inventories docs trees, applies
simple classification heuristics, and emits a text, JSON, or markdown report.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
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


def load_active_repos(ecosystem_path: Path) -> list[dict[str, Any]]:
    """Load active repository entries from ecosystem.yaml."""
    data = yaml.safe_load(ecosystem_path.read_text()) or {}
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


def summarize_repo(repo: dict[str, Any]) -> RepoDocsSummary:
    """Summarize docs health for one repo."""
    repo_path = Path(str(repo["path"]))
    docs_path = repo_path / "docs"
    docs_exists = docs_path.exists()

    files = [path for path in docs_path.rglob("*") if path.is_file()] if docs_exists else []
    markdown_files = [path for path in files if path.suffix.lower() == ".md"]
    archive_files = [path for path in files if "archive" in path.parts]
    backup_like_files = [path for path in files if is_backup_like(path)]
    generated_files = [path for path in files if is_generated(path)]
    root_markdown_files = [
        path for path in markdown_files if path.parent == docs_path
    ]
    stale_root_candidates = [
        path for path in markdown_files if is_stale_root_candidate(path, docs_path)
    ]
    top_level_dirs = sorted(
        path.name for path in docs_path.iterdir() if docs_exists and path.is_dir()
    )

    recommendations: list[str] = []
    if not docs_exists:
        recommendations.append("create docs/ or confirm repo intentionally has no docs")
    else:
        if not (docs_path / "README.md").exists():
            recommendations.append("add docs/README.md")
        if archive_files and not (docs_path / "archive" / "README.md").exists():
            recommendations.append("add docs/archive/README.md")
        root_plan_like_files = [
            path
            for path in root_markdown_files
            if any(marker in path.stem.upper() for marker in PLAN_MARKERS)
        ]
        if len(root_plan_like_files) > 3 and not has_plan_index(docs_path):
            recommendations.append("add docs/plans/PLAN_INDEX.md")
        if backup_like_files:
            recommendations.append("review/remove backup-like artifacts under docs")
        if generated_files:
            recommendations.append("move generated artifacts out of docs")
        if stale_root_candidates:
            recommendations.append("move stale root reports/summaries into archive")

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
        top_level_dirs=top_level_dirs,
        backup_like_paths=sorted(repo_relative(path, repo_path) for path in backup_like_files),
        generated_paths=sorted(repo_relative(path, repo_path) for path in generated_files),
        stale_root_paths=sorted(repo_relative(path, repo_path) for path in stale_root_candidates),
        recommendations=recommendations,
    )


def render_text(summaries: list[RepoDocsSummary]) -> str:
    """Render a concise text report."""
    lines = []
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
    for summary in summaries:
        lines.append(f"### {summary.name}")
        lines.append("")
        if summary.recommendations:
            for recommendation in summary.recommendations:
                lines.append(f"- {recommendation}")
        else:
            lines.append("- no immediate structural recommendations")
        lines.append("")

    if include_files:
        lines.extend(["## Detailed Cleanup Candidates", ""])
        for summary in summaries:
            lines.append(f"### {summary.name}")
            lines.append("")
            if not (
                summary.backup_like_paths
                or summary.generated_paths
                or summary.stale_root_paths
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

    return "\n".join(lines).rstrip() + "\n"


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
    repos = load_active_repos(args.ecosystem)
    summaries = [summarize_repo(repo) for repo in repos]

    if args.output == "json":
        rendered = json.dumps([asdict(summary) for summary in summaries], indent=2)
    elif args.output == "markdown":
        rendered = render_markdown(summaries, include_files=args.include_files)
    else:
        rendered = render_text(summaries)

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(rendered)
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
