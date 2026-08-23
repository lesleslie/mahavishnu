"""Tests for ``mahavishnu.core.worktree_providers.storage_io`` (PR-C)."""

from __future__ import annotations

import io
from pathlib import Path
import tarfile

import pytest

from mahavishnu.core.worktree_providers.storage_io import (
    compute_sha256,
    deserialize_worktree_tar,
    serialize_worktree_tar,
)


# ---------------------------------------------------------------------------
# serialize_worktree_tar / deserialize_worktree_tar round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_worktree(tmp_path: Path) -> Path:
    """Build a small directory tree: file.txt, nested/sub.txt, symlink.txt.

    Uses a *relative* symlink so the tar data_filter (which rejects
    absolute link targets per the tarfile security model) accepts the
    round-trip.
    """
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "sub.txt").write_text("world")
    target = tmp_path / "symlink.txt"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to("file.txt")  # RELATIVE link target
    return tmp_path


def test_serialize_then_deserialize_preserves_content(sample_worktree: Path) -> None:
    blob = serialize_worktree_tar(sample_worktree)
    extract_dir = sample_worktree.parent / "extracted"
    deserialize_worktree_tar(blob, extract_dir)
    assert (extract_dir / "file.txt").read_text() == "hello"
    assert (extract_dir / "nested" / "sub.txt").read_text() == "world"


def test_serialize_then_deserialize_preserves_symlinks(sample_worktree: Path) -> None:
    blob = serialize_worktree_tar(sample_worktree)
    extract_dir = sample_worktree.parent / "extracted_symlink"
    deserialize_worktree_tar(blob, extract_dir)
    link = extract_dir / "symlink.txt"
    assert link.is_symlink()
    assert link.read_text() == "hello"  # follows the symlink


def test_serialize_then_deserialize_sha256_matches_input(sample_worktree: Path) -> None:
    blob = serialize_worktree_tar(sample_worktree)
    # SHA-256 of the tar.gz bytes is stable for the same input. Two
    # serializations of the same tree must produce the same digest
    # (deterministic order, not just same content).
    blob2 = serialize_worktree_tar(sample_worktree)
    assert compute_sha256(blob) == compute_sha256(blob2)


def test_round_trip_10mb_file(tmp_path: Path) -> None:
    """Round-trip a >100KB file (smaller than the §16 100MB ceiling)."""
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (10 * 1024 * 1024))
    blob = serialize_worktree_tar(tmp_path)
    extract_dir = tmp_path.parent / "extracted_big"
    deserialize_worktree_tar(blob, extract_dir)
    assert (extract_dir / "big.bin").stat().st_size == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Security — malicious tarballs must NOT escape target directory
# ---------------------------------------------------------------------------


def _make_path_traversal_tarball(tmp_path: Path) -> bytes:
    """Build a malicious tarball that contains ``../../etc/passwd``."""
    src_dir = tmp_path / "evil_source"
    src_dir.mkdir()
    # We add a file with a name containing '..' that, if not filtered,
    # would extract outside target. The data filter rejects it.
    evil_path = src_dir / "evil.txt"
    evil_path.write_text("evil content")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(evil_path), arcname="subdir/evil.txt")
        # Manually add a member with a parent-traversal name
        info = tarfile.TarInfo(name="../../etc/escaped")
        info.size = len(b"escaped content")
        tar.addfile(info, io.BytesIO(b"escaped content"))
    return buf.getvalue()


def test_deserialize_blocks_path_traversal_via_data_filter(tmp_path: Path) -> None:
    """``data_filter`` must reject TarInfo members whose name escapes
    the target directory (e.g. ``../../etc/escaped``)."""
    blob = _make_path_traversal_tarball(tmp_path)
    target = tmp_path / "safe_target"
    with pytest.raises((tarfile.OutsideDestinationError, KeyError, ValueError)):
        deserialize_worktree_tar(blob, target)
    # The escaped file MUST NOT exist anywhere on the filesystem.
    assert not (tmp_path.parent / "etc" / "escaped").exists()
    assert not (tmp_path.parent / "escaped").exists()
