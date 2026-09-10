#!/usr/bin/env python3
"""Restore docs/plans/PLAN_INDEX.md from a previous backup.

The migration runbook's rollback path: if the Dhara-only render produces
a broken PLAN_INDEX.md (missing rows, malformed table, drift from the
legacy file), the operator picks the most recent good backup and runs
this script. The script writes the backup back over PLAN_INDEX.md and
prints the path of the backup that was used so the operator can copy
the SHA into the post-mortem.

Usage:
    uv run python scripts/restore_plan_index_backup.py
    uv run python scripts/restore_plan_index_backup.py --from docs/plans/PLAN_INDEX.20260915T000000Z.backup
    uv run python scripts/restore_plan_index_backup.py --list

Exit codes:
    0 = restore succeeded (or --list printed)
    1 = no backup found OR restore failed
    2 = bad CLI args
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from collections.abc import Sequence


__all__ = ["build_parser", "list_backups", "main"]

BACKUP_PREFIX = "PLAN_INDEX."
BACKUP_SUFFIX = ".backup"
INDEX_REL = Path("docs") / "plans" / "PLAN_INDEX.md"


def list_backups(plan_index_dir: Path) -> list[Path]:
    """Return every ``PLAN_INDEX.*.backup`` under ``plan_index_dir``,
    newest first."""
    return sorted(
        plan_index_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _latest_backup(plan_index_dir: Path) -> Path | None:
    candidates = list_backups(plan_index_dir)
    return candidates[0] if candidates else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="restore_plan_index_backup",
        description=(
            "Roll back docs/plans/PLAN_INDEX.md to a previous backup. "
            "Use --list to inspect available backups first."
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
        help="Path to PLAN_INDEX.md relative to repo-root (default: docs/plans/PLAN_INDEX.md).",
    )
    parser.add_argument(
        "--from",
        dest="from_path",
        type=Path,
        default=None,
        help="Explicit backup to restore. Default: most recent backup.",
    )
    parser.add_argument(
        "--list",
        dest="list_only",
        action="store_true",
        help="Print available backups and exit (do not restore).",
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

    if args.list_only:
        for b in list_backups(plan_index.parent):
            print(b.name)
        return 0

    backup_path: Path | None
    if args.from_path is None:
        backup_path = _latest_backup(plan_index.parent)
        if backup_path is None:
            sys.stderr.write(f"no backups found in {plan_index.parent}\n")
            return 1
    else:
        from_arg: Path = args.from_path
        backup_path = from_arg if from_arg.is_absolute() else repo_root / from_arg
        if not backup_path.exists():
            sys.stderr.write(f"backup not found: {backup_path}\n")
            return 1

    try:
        shutil.copy2(backup_path, plan_index)
    except OSError as exc:
        sys.stderr.write(f"restore failed: {exc}\n")
        return 1
    print(str(plan_index))
    sys.stderr.write(f"restored from {backup_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


# Sequence import keeps mypy happy on the main() signature above.
_ = Sequence
