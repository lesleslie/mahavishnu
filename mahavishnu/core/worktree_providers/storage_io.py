"""Worktree bytes serialization helpers (ADR 015 v4 §6).

Oneiric storage adapters store single blobs (per
``LocalStorageAdapter.save`` / ``S3StorageAdapter.upload``). Worktrees
are directories, so we tar.gz them into a single blob keyed at
``worktrees/<repo>/<branch>/<handle_id>.tar.gz``.

Pure functions, no class. The provider holds the storage adapter;
this module is the thin serde layer.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile


def serialize_worktree_tar(path: Path) -> bytes:
    """Serialize a worktree directory to a gzipped tar byte string.

    Symlinks are preserved (tar records link type explicitly). File
    modes are preserved via default ``tar.add(recursive=True)`` which
    captures stat info.

    Memory: peak RSS during compression is ~2.5x the source size
    (CPython's ``tarfile`` builds the archive in-memory via
    ``io.BytesIO``). Per ADR §16, ``S3WorktreeProvider`` is restricted
    to <100MB; ``mahavishnu/worktree-max-size-bytes`` guard lives in
    PR-D's provider.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(path), arcname=".", recursive=True)
    return buf.getvalue()


def deserialize_worktree_tar(blob: bytes, target: Path) -> None:
    """Extract a gzipped tar byte string into ``target``.

    ``target`` is created (parents included) if missing. Uses
    ``tarfile.data_filter`` (Python 3.12+) to block path-traversal
    attacks (e.g. a malicious tarball containing ``../../etc/passwd``
    members).
    """
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        # ``tarfile.data_filter`` (Python 3.12+) replaces the
        # deprecated extractall() default of "fully trusted" which
        # allowed path traversal. Use the explicit constant, not the
        # string alias "data", so semgrep and static analyzers
        # recognize the filter.
        tar.extractall(target, filter=tarfile.data_filter)


def compute_sha256(blob: bytes) -> str:
    """Return the hex SHA-256 digest of ``blob``.

    Thin wrapper around ``hashlib.sha256`` for symmetry with
    ``mahavishnu.observability.bundle_integrity.compute_sha256`` (same
    algorithm; providers may import either).
    """
    return hashlib.sha256(blob).hexdigest()
