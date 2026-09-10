#!/usr/bin/env python3
"""Snapshot docs/plans/PLAN_INDEX.md before the first Dhara-only render.

Per the migration runbook (docs/runbooks/migrate-plan-index-dhara.md
step 0), the operator takes a backup of the legacy PLAN_INDEX.md BEFORE
the bootstrap script writes any Dhara records. This guards against
"the cron path produced a broken PLAN_INDEX.md" — the rollback path
is always one ``mv`` away.

Usage:
    uv run python scripts/backup_plan_index.py
    uv run python scripts/backup_plan_index.py --index-path docs/plans/PLAN_INDEX.md
    uv run python scripts/backup_plan_index.py --keep-last 5  # prune old backups

Behavior:
    * Writes ``docs/plans/PLAN_INDEX.{ISO8601_UTC}.backup`` (mode 0o644).
    * Idempotent — running twice in the same second produces two
      distinct files only when the timestamp string differs at
      sub-second resolution (rare; the bootstrap step is manual).
    * Optional prune keeps the most recent N backups and removes the
      rest (oldest first) so docs/plans/ does not accumulate.

Exit codes:
    0 = backup created (or index missing — nothing to do)
    1 = I/O error writing the backup
    2 = bad CLI args
"""

from __future__ import annotations

import argparse
import datetime
from datetime import UTC
from pathlib import Path
import shutil
import sys
from collections.abc import Sequence


__all__ = ["backup", "build_parser", "main"]


BACKUP_PREFIX = "PLAN_INDEX."
BACKUP_SUFFIX = ".backup"
INDEX_REL = Path("docs") / "plans" / "PLAN_INDEX.md"


def backup(
    plan_index_path: Path, *, now: datetime.datetime | None = None
) -> Path:
    """Copy ``plan_index_path`` to a timestamped sibling and return the new path.

    The timestamp uses ``%Y%m%dT%H%M%SZ`` (compact ISO 8601 with ``Z``
    suffix). Operators read these files by listing the directory and
    sorting; human-friendly formatting matters more than parseability.
    """
    if not plan_index_path.exists():
        return None  # type: ignore[return-value]
    stamp = (now or datetime.datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = plan_index_path.with_name(f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}")
    shutil.copy2(plan_index_path, target)
    return target


def prune_old_backups(plan_index_dir: Path, *, keep_last: int) -> list[Path]:
    """Delete oldest ``PLAN_INDEX.*.backup`` files beyond ``keep_last``.

    Returns the list of removed paths so the operator can confirm what
    was pruned. Files are sorted by mtime DESC; the newest ``keep_last``
    are kept, the rest deleted.
    """
    if keep_last < 1:
        return []
    candidates = sorted(
        plan_index_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for old in candidates[keep_last:]:
        old.unlink(missing_ok=True)
        removed.append(old)
    return removed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup_plan_index",
        description=(
            "Snapshot docs/plans/PLAN_INDEX.md before the first "
            "Dhara-only render. Keeps the legacy index recoverable."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd).",
    )
    parser.add_argument(
        "--index-path",
        type=Path,
        default=None,
        help=(
            "Path to PLAN_INDEX.md relative to repo-root "
            "(default: docs/plans/PLAN_INDEX.md)."
        ),
    )
    parser.add_argument(
        "--keep-last",
        type=int,
        default=10,
        help=(
            "After the new backup, prune older PLAN_INDEX.*.backup "
            "files so only this many recent snapshots remain "
            "(default: 10; set to 0 to disable pruning)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root: Path = args.repo_root.resolve()
    if not repo_root.is_dir():
        sys.stderr.write(f"repo-root not a directory: {repo_root}\n")
        return 2
    if args.index_path is None:
        plan_index = repo_root / INDEX_REL
    else:
        index_path: Path = args.index_path
        if not index_path.is_absolute():
            plan_index = repo_root / index_path
        else:
            plan_index = index_path
    if not plan_index.exists():
        sys.stderr.write(f"PLAN_INDEX.md not found at {plan_index}; nothing to back up\n")
        return 0
    try:
        target = backup(plan_index)
    except OSError as exc:
        sys.stderr.write(f"backup failed: {exc}\n")
        return 1
    if target is None:
        sys.stderr.write(f"PLAN_INDEX.md not found at {plan_index}; nothing to back up\n")
        return 0
    print(str(target))
    if args.keep_last > 0:
        removed = prune_old_backups(plan_index.parent, keep_last=args.keep_last)
        for r in removed:
            sys.stderr.write(f"pruned: {r}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
