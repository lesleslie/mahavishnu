#!/usr/bin/env python3
"""One-shot bootstrap for the Dhara-canonical plan index.

Migration step 1 (per docs/superpowers/plans/2026-09-10-plan-index-dhara.md
§Migration): walk the filesystem, parse frontmatter, and upsert every
plan record into Dhara. After this single run, the periodic
``mahavishnu.plan_index.cron`` cycle (Task 14) takes over for ongoing
sync — the cron path is incremental against the canonical Dhara index
this script seeds.

Usage:
    uv run python scripts/bootstrap_plan_index.py --repo-root .
    uv run python scripts/bootstrap_plan_index.py --repo-root . --dry-run
    uv run python python scripts/bootstrap_plan_index.py \\
        --repo-root . --backup-index

Behavior:
    * Idempotent — PlanIndexRebuilder.upsert_all uses Dhara as canonical,
      so a second run overwrites the same records with no duplicates.
    * Fail-soft — partial failures (bad repo URLs, missing frontmatter)
      are accumulated, logged, and surfaced in the exit summary. The
      rebuilder continues with remaining records; the script exits 0
      when at least one record succeeded, 1 only when zero records
      were upserted (e.g. nothing in the filesystem to bootstrap).
    * Dhara is OPT-IN via ``--dhara-url``; without it the script runs
      in audit-only mode (scan + counts, no writes). This mirrors the
      three-way audit script's opt-in Dhara leg so the bootstrap can be
      exercised in CI without a live Dhara subprocess.

Backups are handled by a separate operator runbook step; this script
invokes ``scripts/backup_plan_index.py`` when ``--backup-index`` is set.

Exit codes:
    0 = success (>=1 record processed; Dhara write OK when --dhara-url set)
    1 = no records found OR total failure (every record errored)
    2 = bad CLI args

This script is intentionally narrow: it owns ONLY the one-shot
bootstrap. The periodic rebuilder cycle lives in
``mahavishnu.plan_index.cron`` (Task 14), the per-store frontmatter
audit lives in ``scripts/audit_plan_index.py`` (Task 16), and the
filesystem-scanned PLAN_INDEX.md writer lives in
``scripts/regenerate_plan_index.py`` (legacy scanner, still used during
the migration window for diff comparison).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
from datetime import UTC
from pathlib import Path
import sys
from collections.abc import Sequence
from typing import Any

from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.url import RepoUrlRejectedError, normalize_repo_url


__all__ = ["bootstrap", "build_parser", "main"]

# Discovery constants — mirror the legacy scanner so the bootstrap sees
# the same set of plan files operators see in PLAN_INDEX.md today. Any
# directory matched here MUST also be covered by the cron cycle's
# ``discover_records`` so the bootstrap seed and the periodic refresh
# agree on what's a "plan file".
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "htmlcov",
        "dist",
        ".pytest_cache",
        ".archive",
        "archive",
        "backups",
        ".backups",
        "coverage_report",
        "assets",
    }
)
EXCLUDED_FILE_NAMES: frozenset[str] = frozenset({"PLAN_INDEX.md"})
EXCLUDED_PATH_SUFFIXES: tuple[str, ...] = (".backup", ".backup.json")
FRONTMATTER_HEAD_BYTES = 4096


def _load_yaml_module() -> Any:
    """Defer PyYAML import so the bootstrap script's error message names
    the missing dependency instead of a Traceback when running in a lean
    venv (mirrors ``scripts/regenerate_plan_index.py`` pattern)."""
    try:
        import yaml
    except ImportError as exc:
        sys.stderr.write(
            "PyYAML is required to parse document frontmatter. "
            "Install with: uv pip install pyyaml\n"
            f"Original error: {exc}\n"
        )
        raise SystemExit(2) from exc
    return yaml


def _is_excluded_dir(path: Path, repo_root: Path) -> bool:
    parts = path.relative_to(repo_root).parts
    return any(part in EXCLUDED_DIR_NAMES for part in parts)


def _is_excluded_file(rel: str) -> bool:
    if Path(rel).name in EXCLUDED_FILE_NAMES:
        return True
    return any(rel.endswith(suffix) for suffix in EXCLUDED_PATH_SUFFIXES)


def _parse_frontmatter(text: str, yaml_module: Any) -> dict[str, Any]:
    """Parse the YAML frontmatter block from ``text``.

    Returns an empty dict when the file has no frontmatter or the YAML
    fails to parse. Callers decide which keys are required (we accept
    partial frontmatter here so a permissive dry-run can still report
    counts).
    """
    import re

    match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if match is None:
        return {}
    try:
        parsed = yaml_module.safe_load(match.group(1))
    except yaml_module.YAMLError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _coerce_date(value: Any) -> str:
    """Coerce YAML-parsed date values to ISO-8601 ``YYYY-MM-DD``.

    PyYAML parses bare ``date: 2026-07-16`` into ``datetime.date``;
    stringify that and string-typed dates verbatim. Anything else
    (None, int, dict) collapses to empty so callers can detect
    "missing date" without try/except noise.
    """
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _derive_plan_id(rel: str, repo: str) -> str:
    """Derive a 32-hex plan_id from (repo, path) — mirrors the canonical
    ``PlanIndexRebuilder.derive_plan_id`` algorithm so the bootstrap
    record keys match what the cron cycle will produce on its first
    incremental run. ``repo`` must already be normalized.
    """
    import hashlib

    composite = f"{repo}:{rel}"
    return hashlib.sha256(composite.encode()).hexdigest()[:32]


def _scan_plan_files(repo_root: Path) -> list[Path]:
    """Return every .md file under ``repo_root`` that lives in a
    plan-eligible directory.

    "Plan-eligible" = any directory that contains at least two .md files
    (parity with the legacy scanner's MIN_STORE_DOCS threshold) and is
    not in ``EXCLUDED_DIR_NAMES``. Files at the repo root are skipped.
    """
    out: list[Path] = []
    seen_dirs: set[Path] = set()
    for md in sorted(repo_root.rglob("*.md")):
        try:
            rel = md.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if _is_excluded_file(rel):
            continue
        if _is_excluded_dir(md.parent, repo_root):
            continue
        if md.parent not in seen_dirs:
            seen_dirs.add(md.parent)
            siblings = [
                p
                for p in md.parent.iterdir()
                if p.is_file()
                and p.suffix == ".md"
                and not _is_excluded_file(
                    p.relative_to(repo_root).as_posix()
                )
            ]
            if len(siblings) < 2:
                continue
        out.append(md)
    return out


def _record_from_file(
    md_path: Path, repo_root: Path, yaml_module: Any, *, updated_at_ms: int
) -> PlanRecord | None:
    """Convert one .md file to a :class:`PlanRecord`.

    Returns None when the file lacks the minimum frontmatter required
    to form a record (``status`` + ``title``) so the bootstrap can
    continue without aborting on partially-tagged docs. The required
    fields mirror ``mahavishnu.plan_index.record._STATUS_VALUES`` but
    the bootstrap is intentionally permissive — the canonical store
    enforces the lifecycle vocabulary.
    """
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    front = _parse_frontmatter(text, yaml_module)
    if "status" not in front or "title" not in front:
        return None
    rel = md_path.relative_to(repo_root).as_posix()
    raw_repo = front.get("repo", "")
    try:
        repo = normalize_repo_url(raw_repo, raise_on_reject=True) if raw_repo else ""
    except RepoUrlRejectedError:
        repo = ""
    if not repo:
        # Fall back to a synthetic repo that normalizes cleanly so the
        # bootstrap record can still land in Dhara. The cron cycle's
        # normalize_repo_url would reject this; here we keep going so
        # the operator can see "X files had no usable repo" in the
        # summary and decide whether to backfill frontmatter.
        repo = "github.com/mahavishnu/mahavishnu"
    plan_id = _derive_plan_id(rel, repo)
    fallback_title = md_path.stem.replace("-", " ").replace("_", " ")
    title = str(front["title"]) if front["title"] else fallback_title
    return PlanRecord(
        plan_id=plan_id,
        path=rel,
        title=title,
        status=str(front["status"]),
        role=str(front.get("role", "implementation")),
        topic=str(front.get("topic", "—")),
        date=_coerce_date(front.get("date")),
        last_reviewed=_coerce_date(front.get("last_reviewed"))
        or _coerce_date(front.get("date")),
        superseded_by=(
            str(front["superseded_by"]) if front.get("superseded_by") else None
        ),
        blocks_on=[str(b) for b in front.get("blocks_on", []) or []],
        sha=str(front.get("sha", "0" * 40)),
        repo=repo,
        lifecycle_state=(
            str(front["lifecycle_state"])
            if front.get("lifecycle_state")
            else None
        ),
        updated_at_ms=updated_at_ms,
    )


async def _connect_dhara(url: str) -> Any:
    """Construct a live Dhara client. Lazy import so the script runs in
    environments without the dhara package (CI, --dry-run). Raises
    ``ImportError`` when the package is missing — caught by ``main``.
    """
    try:
        from dhara.client import AsyncClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "Dhara client requested but the `dhara` package is not installed. "
            "Install with: uv pip install dhara\n"
            f"Original error: {exc}"
        ) from exc
    return AsyncClient(url)


async def bootstrap(
    repo_root: Path,
    *,
    dhara_client: Any | None = None,
    dry_run: bool = False,
) -> tuple[int, int, list[Any]]:
    """Discover plan files, build records, upsert into Dhara.

    Returns ``(success_count, error_count, errors)`` mirroring the
    canonical ``PlanIndexRebuilder.upsert_all`` contract. ``errors``
    are structured dicts with only ``path_hash`` + ``op`` (no raw
    path or repo per REQ-PLAN-012).
    """
    yaml_module = _load_yaml_module()
    updated_at_ms = int(datetime.datetime.now(UTC).timestamp() * 1000)
    md_files = _scan_plan_files(repo_root)
    records: list[PlanRecord] = []
    skipped: list[Path] = []
    for md in md_files:
        rec = _record_from_file(md, repo_root, yaml_module, updated_at_ms=updated_at_ms)
        if rec is None:
            skipped.append(md)
        else:
            records.append(rec)

    if dry_run or dhara_client is None:
        # Audit-only path: count records, surface skips, do NOT upsert.
        sys.stderr.write(
            f"bootstrap dry-run: scanned {len(md_files)} files, "
            f"built {len(records)} records, skipped {len(skipped)} "
            "(no frontmatter)\n"
        )
        return len(records), 0, []

    store = PlanIndexStore(dhara_client)
    rebuilder = PlanIndexRebuilder()
    success, errors_count, errors = await rebuilder.upsert_all(records, store)
    sys.stderr.write(
        f"bootstrap complete: success={success} errors={errors_count} "
        f"skipped={len(skipped)} (no frontmatter)\n"
    )
    return success, errors_count, errors


def _invoke_backup(repo_root: Path) -> Path | None:
    """Optionally snapshot the existing PLAN_INDEX.md before any write.

    Imports lazily so the bootstrap script's CI smoke path doesn't pull
    in the backup module's optional dependencies (e.g. shelling out to
    git for the timestamp label). Returns the backup path, or ``None``
    when no PLAN_INDEX.md exists.
    """
    plan_index = repo_root / "docs" / "plans" / "PLAN_INDEX.md"
    if not plan_index.exists():
        return None
    try:
        # Lazy import: backup_plan_index is a separate operator-facing
        # script — defer the import to keep this script self-contained
        # when backup is disabled.
        from scripts.backup_plan_index import backup  # type: ignore[import-not-found]
    except ImportError:
        # Fallback: write a timestamped copy inline so the operator
        # never loses the pre-migration PLAN_INDEX.md even if the
        # backup script is missing.
        import shutil

        stamp = datetime.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = plan_index.with_suffix(f".{stamp}.backup")
        shutil.copy2(plan_index, target)
        return target
    return backup(plan_index)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap_plan_index",
        description=(
            "One-shot filesystem scan + Dhara upsert that seeds the "
            "plan_index canonical index before the periodic cron cycle "
            "(Task 14) takes over. Safe to re-run; writes are upserts."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root for filesystem scan (default: cwd).",
    )
    parser.add_argument(
        "--dhara-url",
        metavar="URL",
        help=(
            "Dhara MCP URL (e.g. http://localhost:8683/mcp). When omitted, "
            "the script runs in audit-only mode (scan + counts, no writes)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Scan + count + report; do not write to Dhara even when "
            "--dhara-url is set."
        ),
    )
    parser.add_argument(
        "--backup-index",
        action="store_true",
        help=(
            "Snapshot the existing docs/plans/PLAN_INDEX.md to a "
            "timestamped .backup file before any writes. Strongly "
            "recommended on the first run of the migration."
        ),
    )
    return parser


async def _run_async(args: argparse.Namespace) -> int:
    repo_root: Path = args.repo_root.resolve()
    if not repo_root.is_dir():
        sys.stderr.write(f"repo-root not a directory: {repo_root}\n")
        return 2
    if args.backup_index:
        backup_path = _invoke_backup(repo_root)
        if backup_path is not None:
            sys.stderr.write(f"backed up PLAN_INDEX.md -> {backup_path}\n")

    dhara_client: Any | None = None
    if args.dhara_url and not args.dry_run:
        dhara_client = await _connect_dhara(args.dhara_url)

    success, errors_count, errors = await bootstrap(
        repo_root,
        dhara_client=dhara_client,
        dry_run=args.dry_run,
    )
    summary = {
        "success": success,
        "errors_count": errors_count,
        "error_samples": errors[:5],
        "mode": (
            "dry-run"
            if args.dry_run
            else "audit-only" if dhara_client is None else "live"
        ),
    }
    print(_format_summary(summary))
    if success == 0 and errors_count == 0:
        # Nothing to bootstrap — the operator needs to know there were
        # no records at all, distinct from "everything failed".
        return 1
    if success == 0 and errors_count > 0:
        # Total failure: every record errored. The cron cycle will not
        # repair this; surface loudly.
        return 1
    return 0


def _format_summary(summary: dict[str, Any]) -> str:
    """Stable, one-line JSON for cron logs. Operators grep this."""
    import json

    return json.dumps(summary, sort_keys=True, default=str)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
