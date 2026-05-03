#!/usr/bin/env python3
"""Create missing docs entrypoints across active Bodai ecosystem repositories.

The script is intentionally conservative:

- it never overwrites existing files
- it never deletes or moves documentation
- it only creates missing docs README, archive README, and plan index files
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from os.path import relpath
from pathlib import Path
from typing import Any

import yaml

PLAN_MARKERS = ("PLAN", "ROADMAP", "STRATEGY")


@dataclass(frozen=True)
class PendingWrite:
    """A file creation planned by the standardization pass."""

    path: Path
    content: str


def load_active_repos(ecosystem_path: Path) -> list[dict[str, Any]]:
    """Load active repository entries from ecosystem.yaml."""
    data = yaml.safe_load(ecosystem_path.read_text()) or {}
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        raise ValueError(f"Invalid repos list in {ecosystem_path}")
    return [repo for repo in repos if repo.get("status", "active") == "active"]


def repo_display_name(repo: dict[str, Any]) -> str:
    """Return a human-readable repo name."""
    return str(repo["name"]).replace("-", " ").title()


def markdown_link(path: Path, base_path: Path) -> str:
    """Return a relative markdown link from one docs file directory to another file."""
    return relpath(path, start=base_path)


def discover_plan_files(docs_path: Path) -> list[Path]:
    """Find root/plans markdown files that look like plans or roadmaps."""
    candidates: list[Path] = []
    search_roots = [docs_path]
    plans_dir = docs_path / "plans"
    if plans_dir.exists():
        search_roots.append(plans_dir)

    for root in search_roots:
        for path in root.glob("*.md"):
            if path.name in {"README.md", "PLAN_INDEX.md"}:
                continue
            stem = path.stem.upper()
            if any(marker in stem for marker in PLAN_MARKERS):
                candidates.append(path)

    return sorted(set(candidates))


def render_docs_readme(
    repo: dict[str, Any],
    docs_path: Path,
    *,
    has_or_will_have_plan_index: bool,
) -> str:
    """Render a standard docs entrypoint for a repo."""
    title = repo_display_name(repo)
    description = str(repo.get("description", "Bodai ecosystem repository."))
    role = str(repo.get("role", "unspecified"))
    archive_exists = (docs_path / "archive").exists()

    lines = [
        f"# {title} Docs",
        "",
        description,
        "",
        f"- Role: `{role}`",
        "- Status: active ecosystem repository",
        "",
        "## Start Here",
        "",
        "- Use current root docs for maintained operator and developer guidance.",
    ]
    if has_or_will_have_plan_index:
        lines.append(
            "- Use [plans/PLAN_INDEX.md](plans/PLAN_INDEX.md) for active and historical plans."
        )
    if archive_exists:
        lines.append(
            "- Use [archive/README.md](archive/README.md) for historical, non-authoritative material."
        )

    lines.extend(
        [
            "",
            "## Maintenance Rules",
            "",
            "- Keep active docs in the smallest accurate set possible.",
            "- Move completed reports, stale implementation plans, and superseded notes into `archive/`.",
            "- Do not commit generated coverage, backup archives, or temporary audit artifacts under `docs/`.",
            "- When a document becomes the implementation source of truth, add or update an index entry here.",
            "",
        ]
    )
    return "\n".join(lines)


def render_archive_readme(repo: dict[str, Any]) -> str:
    """Render a standard archive entrypoint for a repo."""
    title = repo_display_name(repo)
    return "\n".join(
        [
            f"# {title} Docs Archive",
            "",
            "This directory contains historical documentation.",
            "",
            "Archived docs are retained for provenance, audits, migration history, and context recovery. They are not current authority unless a current plan or root `docs/README.md` explicitly points here.",
            "",
            "## Archive Policy",
            "",
            "- Do not implement directly from archive docs without checking current code and active plans.",
            "- Do not add new active plans here.",
            "- Prefer moving stale root reports here over leaving them in the active docs path.",
            "- Generated files, coverage reports, tarballs, and temporary artifacts should not live here long-term.",
            "",
        ]
    )


def render_plan_index(repo: dict[str, Any], docs_path: Path, plan_files: list[Path]) -> str:
    """Render a standard plan index for a repo."""
    title = repo_display_name(repo)
    lines = [
        f"# {title} Plan Index",
        "",
        "This index makes implementation plans easier to find during review and cleanup.",
        "",
        "## Indexed Plans",
        "",
    ]
    if plan_files:
        index_dir = docs_path / "plans"
        for path in plan_files:
            lines.append(f"- [{path.stem}]({markdown_link(path, index_dir)})")
    else:
        lines.append("- No plan-like markdown files were discovered during standardization.")

    lines.extend(
        [
            "",
            "## Maintenance Rules",
            "",
            "- Keep current implementation plans visible from this index.",
            "- Move completed or superseded plans to `docs/archive/` after review.",
            "- Update this index whenever plans are added, retired, or consolidated.",
            "",
        ]
    )
    return "\n".join(lines)


def has_marker(path: Path, marker: str) -> bool:
    """Return whether an existing file contains a known generated marker."""
    return path.exists() and marker in path.read_text()


def collect_writes(
    repos: list[dict[str, Any]],
    *,
    refresh_generated: bool = False,
) -> list[PendingWrite]:
    """Collect missing docs structure writes without touching disk."""
    writes: list[PendingWrite] = []
    for repo in repos:
        docs_path = Path(str(repo["path"])) / "docs"
        plan_files = discover_plan_files(docs_path)
        plan_index = docs_path / "plans" / "PLAN_INDEX.md"
        will_have_plan_index = plan_index.exists() or len(plan_files) > 3

        docs_readme = docs_path / "README.md"
        docs_readme_content = render_docs_readme(
            repo,
            docs_path,
            has_or_will_have_plan_index=will_have_plan_index,
        )
        if not docs_readme.exists() or (
            refresh_generated and has_marker(docs_readme, "- Status: active ecosystem repository")
        ):
            writes.append(
                PendingWrite(
                    docs_readme,
                    docs_readme_content,
                )
            )

        archive_path = docs_path / "archive"
        archive_readme = archive_path / "README.md"
        if archive_path.exists() and (
            not archive_readme.exists()
            or (
                refresh_generated
                and has_marker(archive_readme, "This directory contains historical documentation.")
            )
        ):
            writes.append(PendingWrite(archive_readme, render_archive_readme(repo)))

        should_write_plan_index = len(plan_files) > 3 and (
            not plan_index.exists()
            or (
                refresh_generated
                and has_marker(
                    plan_index,
                    "This index makes implementation plans easier to find during review and cleanup.",
                )
            )
        )
        if should_write_plan_index:
            writes.append(PendingWrite(plan_index, render_plan_index(repo, docs_path, plan_files)))

    return writes


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
        "--apply",
        action="store_true",
        help="Create the missing files. Without this flag, only print planned writes.",
    )
    parser.add_argument(
        "--refresh-generated",
        action="store_true",
        help="Refresh files previously generated by this script.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the docs structure standardization pass."""
    args = parse_args()
    repos = load_active_repos(args.ecosystem)
    writes = collect_writes(repos, refresh_generated=args.refresh_generated)

    if not writes:
        print("No missing docs structure files detected.")
        return 0

    for write in writes:
        print(write.path)
        if args.apply:
            write.path.parent.mkdir(parents=True, exist_ok=True)
            write.path.write_text(write.content)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
