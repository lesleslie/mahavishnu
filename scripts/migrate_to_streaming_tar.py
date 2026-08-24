#!/usr/bin/env python3
"""Migrate legacy .tar.gz worktree bundles to streaming .tar.zst.

Scans the worktree cache and re-uploads legacy ``.tar.gz`` bundles as
``.tar.zst`` so all readers see the new streaming format. Idempotent:
any key that already has a ``.tar.zst`` counterpart is skipped without
re-encoding the source.

Use ``--dry-run`` to preview without writing.

This script is intentionally read-mostly on the source bundle: it
streams the ``.tar.gz`` payload, recompresses to ``.tar.zst`` via
oneiric's ``compression-zstd`` action, and uploads the new key. The
legacy ``.tar.gz`` key is left in place so a rollback path remains
until the operator explicitly deletes it (outside this script's
scope).

Examples
--------
Preview the migration for a local cache::

    python scripts/migrate_to_streaming_tar.py --base-path /var/cache/mahavishnu/worktrees --dry-run

Run the migration on a remote S3 bucket::

    python scripts/migrate_to_streaming_tar.py --base-path mahavishnu-worktrees/worktrees

Limit by the ``--max-bytes`` stopgap (defaults to ``MAX_BUNDLE_BYTES_STOPGAP = 256 MiB``)::

    python scripts/migrate_to_streaming_tar.py --base-path . --max-bytes 134217728
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from oneiric.adapters.storage.local import LocalStorageAdapter, LocalStorageSettings
from mahavishnu.core.worktree_providers.storage_io import (
    MAX_BUNDLE_BYTES_STOPGAP,
    deserialize_worktree_tar,
    serialize_worktree_tar,
)

logger = logging.getLogger(__name__)


async def migrate_one(storage: LocalStorageAdapter, key: str, *, dry_run: bool) -> bool:
    """Migrate a single ``.tar.gz`` key to ``.tar.zst``.

    Returns ``True`` if a migration was performed, ``False`` if the
    key was skipped (already migrated, missing counterpart, or dry
    run with no source). The new key suffix is derived by replacing
    ``.tar.gz`` with ``.tar.zst`` — the only Phase 3 suffix in
    storage_io.py.
    """
    if not key.endswith(".tar.gz"):
        logger.debug("skip non-legacy key: %s", key)
        return False

    new_key = key[: -len(".tar.gz")] + ".tar.zst"
    existing = await storage.exists(new_key)
    if existing:
        logger.info("skip already-migrated: %s -> %s", key, new_key)
        return False

    if dry_run:
        logger.info("[dry-run] would migrate %s -> %s", key, new_key)
        return True

    # Stream the legacy payload, deserialize to a staging directory,
    # then re-serialize with the streaming tar.zst pipeline. The
    # deserialized staging directory is deleted once the new bundle
    # is uploaded.
    staging_root = Path(storage.settings.base_path) / ".migrate-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_dir = staging_root / Path(key).stem

    try:
        async with await storage.open_stream(key) as source_stream:
            chunk_reader = lambda: source_stream
            await deserialize_worktree_tar(
                chunk_reader,
                staging_dir,
                expected_sha256=None,  # legacy bundles may lack SHA
                backend="local",
                principal_short="migrate",
            )
        with serialize_worktree_tar(staging_dir) as (temp_path, _byte_count, _sha):
            data = await asyncio.to_thread(temp_path.read_bytes)
            await storage.save_stream(new_key, lambda: iter([data]))
        logger.info("migrated %s -> %s", key, new_key)
        return True
    finally:
        if staging_dir.exists():
            import shutil

            shutil.rmtree(staging_dir, ignore_errors=True)


async def migrate_all(base_path: Path, *, dry_run: bool, max_bytes: int) -> int:
    """Sweep ``base_path`` and migrate every eligible ``.tar.gz`` bundle.

    Returns the count of bundles actually migrated (or, under
    ``dry_run``, the count that *would* be migrated). Bundles larger
    than ``max_bytes`` are skipped and reported — operators must
    hand-migrate those because the streaming path is mandatory above
    that size.
    """
    if max_bytes > MAX_BUNDLE_BYTES_STOPGAP:
        logger.warning(
            "max_bytes=%d exceeds MAX_BUNDLE_BYTES_STOPGAP=%d; "
            "the streaming path is required above the stopgap",
            max_bytes,
            MAX_BUNDLE_BYTES_STOPGAP,
        )

    settings = LocalStorageSettings(base_path=str(base_path))
    storage = LocalStorageAdapter(settings)
    migrated = 0
    skipped_oversize = 0

    async for key in storage.list_keys():
        if not key.endswith(".tar.gz"):
            continue
        # Best-effort size check via the local adapter; remote adapters
        # expose ``stat`` differently so the LocalStorageAdapter path
        # is the only one this script supports today.
        size = await storage.get_size(key)
        if size > max_bytes:
            logger.warning(
                "skip oversize bundle: %s (%d > %d bytes)",
                key,
                size,
                max_bytes,
            )
            skipped_oversize += 1
            continue
        if await migrate_one(storage, key, dry_run=dry_run):
            migrated += 1

    if skipped_oversize:
        logger.warning(
            "oversize bundles skipped (manual migration required): %d",
            skipped_oversize,
        )
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy .tar.gz bundles to streaming .tar.zst",
    )
    parser.add_argument(
        "--base-path",
        type=Path,
        required=True,
        help="Local storage base path (the LocalStorageAdapter root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the migration without writing.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_BUNDLE_BYTES_STOPGAP,
        help="Skip bundles larger than this many bytes (default: MAX_BUNDLE_BYTES_STOPGAP).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    count = asyncio.run(
        migrate_all(
            args.base_path,
            dry_run=args.dry_run,
            max_bytes=args.max_bytes,
        )
    )
    suffix = " (dry run)" if args.dry_run else ""
    print(f"Migrated {count} bundles{suffix}")


if __name__ == "__main__":
    main()
