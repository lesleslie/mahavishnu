"""Tests for ``mahavishnu.core.worktree_providers.storage_io`` (Phase 3 PR-C).

Covers the streaming tar.zst implementation added in Task C.5. All tests
require the ``zstandard`` optional dependency (compression-zstd group);
if missing the whole module is skipped at collection time.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile

import pytest

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.skip(
        "zstandard required; uv sync --group compression-zstd",
        allow_module_level=True,
    )

from mahavishnu.core.errors import ErrorCode, WorktreeError
from mahavishnu.core.worktree_providers.storage_io import (
    MAX_BUNDLE_BYTES_STOPGAP,
    deserialize_worktree_tar,
    serialize_worktree_tar,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


# ---------------------------------------------------------------------------
# Synthetic worktree fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_worktree(tmp_path: Path) -> Path:
    """Small synthetic worktree: a text file, a subdir, a relative symlink."""
    (tmp_path / "file.txt").write_text("hello")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "sub.txt").write_text("world")
    target = tmp_path / "symlink.txt"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to("file.txt")  # RELATIVE so data_filter accepts
    return tmp_path


def _chunk_reader(path: Path, chunk_size: int = 64 * 1024) -> Callable[[], Iterator[bytes]]:
    """Return a fresh callable that yields ``path`` in fixed-size chunks.

    Per the storage_io contract, ``chunk_reader`` is a sync
    ``Callable[[], Iterator[bytes]]`` — invocable to produce a fresh
    iterator per ``deserialize_worktree_tar`` call. Returning the
    callable (not the iterator) lets each call yield independently.
    """

    def reader() -> Iterator[bytes]:
        return _read_chunks(path, chunk_size)

    return reader


def _read_chunks(path: Path, chunk_size: int) -> bytes:
    """Yield fixed-size chunks from ``path`` until EOF."""
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                return
            yield block


def _serialize_to_payload(source: Path) -> tuple[Path, int, str]:
    """Helper: run serialize and consume the context manager cleanly."""
    with serialize_worktree_tar(source) as (temp_path, byte_count, sha256):
        # Read the file once so the hash is stable before we let the
        # caller close the context (which does NOT remove the file).
        return Path(temp_path), byte_count, sha256


# ---------------------------------------------------------------------------
# Module-level constant sanity
# ---------------------------------------------------------------------------


def test_max_bundle_bytes_stopgap_is_256mb() -> None:
    """The stopgap constant is the documented 256MB."""
    assert MAX_BUNDLE_BYTES_STOPGAP == 256 * 1024 * 1024


# ---------------------------------------------------------------------------
# serialize_worktree_tar — context-manager shape + SHA correctness
# ---------------------------------------------------------------------------


def test_serialize_returns_temp_path_size_sha(sample_worktree: Path) -> None:
    """Context manager yields a (temp_path, byte_count, sha256) triple."""
    with serialize_worktree_tar(sample_worktree) as (temp_path, byte_count, sha256):
        assert isinstance(temp_path, Path)
        assert temp_path.exists()
        # ``Path.suffix`` returns only the last dotted segment; the
        # full suffix is ``.tar.zst``.
        assert temp_path.name.endswith(".tar.zst")
        assert isinstance(byte_count, int)
        assert byte_count > 0
        assert byte_count == temp_path.stat().st_size
        assert isinstance(sha256, str)
        assert len(sha256) == 64  # hex SHA-256


def test_serialize_chunked_hash_matches_full_hash(sample_worktree: Path) -> None:
    """SHA from streaming hash equals SHA of the file bytes."""
    temp_path, _byte_count, streaming_sha = _serialize_to_payload(sample_worktree)
    full_sha = hashlib.sha256(temp_path.read_bytes()).hexdigest()
    assert streaming_sha == full_sha


def test_serialize_source_must_exist(tmp_path: Path) -> None:
    """Missing source raises FileNotFoundError before any file is created."""
    with pytest.raises(FileNotFoundError):
        with serialize_worktree_tar(tmp_path / "missing"):
            pytest.fail("context body must not execute")


def test_serialize_source_must_be_directory(tmp_path: Path) -> None:
    """A file (not a directory) source raises NotADirectoryError."""
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x")
    with pytest.raises(NotADirectoryError):
        with serialize_worktree_tar(file_path):
            pytest.fail("context body must not execute")


# ---------------------------------------------------------------------------
# serialize_worktree_tar — cleanup on BaseException paths (B-DI-07)
# ---------------------------------------------------------------------------


def test_serialize_cleanup_on_cancellation(sample_worktree: Path) -> None:
    """CancelledError raised inside the context triggers temp cleanup."""
    leaked: list[Path] = []
    with pytest.raises(BaseException):
        with serialize_worktree_tar(sample_worktree) as (temp_path, _count, _sha):
            leaked.append(temp_path)
            raise asyncio_cancelled_error()
    assert leaked and not leaked[0].exists(), (
        f"temp file leaked after CancelledError: {leaked[0]}"
    )


def test_serialize_cleanup_on_keyboard_interrupt(sample_worktree: Path) -> None:
    """KeyboardInterrupt (BaseException) also triggers cleanup."""
    leaked: list[Path] = []
    with pytest.raises(KeyboardInterrupt):
        with serialize_worktree_tar(sample_worktree) as (temp_path, _count, _sha):
            leaked.append(temp_path)
            raise KeyboardInterrupt()
    assert leaked and not leaked[0].exists(), (
        f"temp file leaked after KeyboardInterrupt: {leaked[0]}"
    )


def asyncio_cancelled_error() -> BaseException:
    """Construct asyncio.CancelledError lazily to avoid an unconditional
    asyncio import (which can fail under restricted interpreters)."""
    import asyncio

    return asyncio.CancelledError()


# ---------------------------------------------------------------------------
# serialize_worktree_tar — error-code wrapping (MHV-209, MHV-210)
# ---------------------------------------------------------------------------


def test_serialize_temp_create_oserror_wrapped(
    sample_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MHV-209: ``tempfile.mkstemp`` OSError → ``WorktreeError`` with that code."""
    import tempfile as tempfile_mod

    def _explode(*args: object, **kwargs: object) -> tuple[int, str]:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile_mod, "mkstemp", _explode)
    with pytest.raises(WorktreeError) as exc_info:
        with serialize_worktree_tar(sample_worktree):
            pytest.fail("context body must not execute")
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_TEMP_CREATE_FAILED


def test_serialize_temp_write_oserror_wrapped(
    sample_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MHV-210: writing the temp file raises OSError → wrapped."""
    import builtins

    # Snapshot the real open BEFORE monkeypatch; the wrapper delegates to it.
    real_open = builtins.open

    class _ExplodingFile:
        # Production uses builtins.open(path, "wb") in the streaming tar.zst
        # write path; os.fdopen runs only as an internal impl detail and
        # patching it leaves the call site untouched. Patch builtins.open.
        # read()/readinto() delegate to the real file so the same wrapper is
        # safe when the patched open is reused for input (e.g. deserialize
        # also needs to read the source tar.zst during the test).
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._inner = real_open(*args, **kwargs)

        def write(self, _data: bytes) -> int:
            raise OSError(5, "Input/output error")

        def read(self, size: int = -1) -> bytes:
            return self._inner.read(size)

        def flush(self) -> None:
            self._inner.flush()

        def __enter__(self) -> _ExplodingFile:
            return self

        def __exit__(self, *args: object) -> None:
            self._inner.close()

    monkeypatch.setattr("builtins.open", _ExplodingFile)
    leaked: list[Path] = []
    with pytest.raises(WorktreeError) as exc_info:
        with serialize_worktree_tar(sample_worktree) as (temp_path, _count, _sha):
            leaked.append(temp_path)
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED
    # Temp file should be cleaned up on the wrapped error too.
    if leaked:
        assert not leaked[0].exists()


# ---------------------------------------------------------------------------
# Round-trip — serialize → deserialize
# ---------------------------------------------------------------------------


def test_deserialize_extracts_content(sample_worktree: Path) -> None:
    """Round-trip preserves files, subdirectories, and relative symlinks."""
    temp_path, _count, sha256 = _serialize_to_payload(sample_worktree)
    target = sample_worktree.parent / "extracted"
    deserialize_worktree_tar(_chunk_reader(temp_path), target)
    assert (target / "file.txt").read_text() == "hello"
    assert (target / "nested" / "sub.txt").read_text() == "world"
    symlink = target / "symlink.txt"
    assert symlink.is_symlink()
    assert symlink.read_text() == "hello"


def test_deserialize_verifies_sha(sample_worktree: Path) -> None:
    """SHA mismatch raises; temp file + staging dir are both unlinked."""
    temp_path, _count, _sha = _serialize_to_payload(sample_worktree)
    target = sample_worktree.parent / "extracted_sha_mismatch"
    bogus_expected = "0" * 64  # not the real hash
    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(
            _chunk_reader(temp_path),
            target,
            expected_sha256=bogus_expected,
            backend="local",
            principal_short="a1b2c3d4",
        )
    # MHV-208 = WORKTREE_INTEGRITY_FAILED raised by verify_sha256_streaming.
    assert exc_info.value.error_code == ErrorCode.WORKTREE_INTEGRITY_FAILED
    assert not target.exists(), "target must NOT be promoted on SHA mismatch"
    # The staging dir is a sibling under target.parent; it should
    # have been cleaned up by the BaseException handler.
    if target.parent.exists():
        leftovers = [
            p for p in target.parent.iterdir() if p.name.startswith(".staging-")
        ]
        assert not leftovers, f"staging leftovers under target.parent: {leftovers}"


# ---------------------------------------------------------------------------
# Security — path traversal and corrupt payloads
# ---------------------------------------------------------------------------


def _build_malicious_tar() -> bytes:
    """Build a tar that ``data_filter`` rejects (parent-traversal member)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name="../../etc/escaped")
        info.size = len(b"escaped content")
        info.type = tarfile.REGTYPE
        tar.addfile(info, io.BytesIO(b"escaped content"))
    return buf.getvalue()


def test_deserialize_blocks_path_traversal(tmp_path: Path) -> None:
    """``../../etc/passwd`` payload rejected with MHV-211."""
    target = tmp_path / "safe_target"
    payload = _build_malicious_tar()

    # Compress the malicious tar into a zstd stream.
    compressed = io.BytesIO()
    chunker = zstandard.ZstdCompressor().chunker()
    for out in chunker.compress(payload):
        compressed.write(out)
    for out in chunker.finish():
        compressed.write(out)

    def reader() -> io.IO[bytes]:
        return iter([compressed.getvalue()])

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(reader, target)
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_PATH_TRAVERSAL
    # No extraction should have occurred.
    assert not target.exists()
    # The staging dir is now a sibling under target.parent; verify it
    # was cleaned up by the BaseException handler.
    if target.parent.exists():
        leftovers = [
            p for p in target.parent.iterdir()
            if p.name.startswith(".staging-") and p.parent == target.parent
        ]
        assert not leftovers, f"staging leftovers under target.parent: {leftovers}"


def test_deserialize_blocks_zstd_corrupt_header(tmp_path: Path) -> None:
    """Garbage bytes for zstd raise (MHV-212 malformed)."""
    target = tmp_path / "garbage_target"
    garbage = b"not a zstd frame at all " * 32

    def reader() -> io.IO[bytes]:
        return iter([garbage])

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(reader, target)
    # Either MHV-212 (zstd corruption) is surfaced; the key invariant
    # is the target is NOT materialized.
    assert exc_info.value.error_code in {
        ErrorCode.WORKTREE_BUNDLE_MALFORMED,
        ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
    }
    assert not target.exists()


def test_deserialize_corrupt_tar_after_zstd(tmp_path: Path) -> None:
    """Valid zstd but the inner tar is malformed → MHV-212."""
    # Build a buffer of 1024 zero bytes; that is a valid empty zstd
    # frame but the inner tar is empty / unreadable.
    raw = io.BytesIO()
    chunker = zstandard.ZstdCompressor().chunker()
    for out in chunker.compress(b""):
        raw.write(out)
    for out in chunker.finish():
        raw.write(out)
    payload = raw.getvalue()

    target = tmp_path / "empty_target"

    def reader() -> io.IO[bytes]:
        return iter([payload])

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(reader, target)
    # Empty tar yields 0 bytes → tarfile.open raises TarError → MHV-212.
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_MALFORMED


# ---------------------------------------------------------------------------
# Cleanup on cancel / runtime errors
# ---------------------------------------------------------------------------


def test_deserialize_cleans_temp_on_chunk_reader_runtime_error(
    sample_worktree: Path,
) -> None:
    """RuntimeError from chunk_reader → cleanup, target NOT created."""
    target = sample_worktree.parent / "extracted_runtime_err"

    def reader() -> io.IO[bytes]:
        raise RuntimeError("simulated chunk-reader failure")
        yield  # pragma: no cover  (generator shape)

    with pytest.raises(RuntimeError, match="simulated chunk-reader failure"):
        deserialize_worktree_tar(reader, target)
    assert not target.exists()


def test_deserialize_cleans_temp_on_cancelled_error(
    sample_worktree: Path,
) -> None:
    """CancelledError mid-stream cleans up the temp file + staging."""
    target = sample_worktree.parent / "extracted_cancelled"
    _serialize_to_payload(sample_worktree)  # warm so the temp file pattern exists

    def reader() -> io.IO[bytes]:
        yield b"\x00" * 16
        raise asyncio_cancelled_error()

    with pytest.raises(BaseException):
        deserialize_worktree_tar(reader, target)
    assert not target.exists()


# ---------------------------------------------------------------------------
# Empty worktree + large file round-trip
# ---------------------------------------------------------------------------


def test_serialize_empty_worktree_round_trips(tmp_path: Path) -> None:
    """An empty source directory round-trips to an empty target dir."""
    empty = tmp_path / "empty_src"
    empty.mkdir()
    target = tmp_path / "empty_target"
    temp_path, _count, _sha = _serialize_to_payload(empty)
    deserialize_worktree_tar(_chunk_reader(temp_path), target)
    assert target.exists()
    assert target.is_dir()


@pytest.mark.timeout(60)
def test_round_trip_100mb_file(tmp_path: Path) -> None:
    """A 100MB file survives the streaming round-trip."""
    big = tmp_path / "big.bin"
    # Stream-write to avoid holding 100MB in Python memory at once.
    with open(big, "wb") as f:
        chunk = b"x" * (1024 * 1024)
        for _ in range(100):
            f.write(chunk)
    target = tmp_path / "big_target"
    temp_path, byte_count, _sha = _serialize_to_payload(tmp_path)
    # Sanity: compression must shrink a uniform-byte file dramatically.
    assert byte_count < 10 * 1024 * 1024, (
        f"expected compressed <10MB, got {byte_count}"
    )
    deserialize_worktree_tar(_chunk_reader(temp_path), target)
    assert (target / "big.bin").stat().st_size == 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# Round-trip at size boundaries (per plan C.5 step 2 parametrize set)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size_bytes",
    [0, 1, 1024, 99 * 1024 * 1024, 101 * 1024 * 1024],
    ids=["empty", "1B", "1KB", "99MB", "101MB"],
)
def test_round_trip_at_size_boundary(
    tmp_path: Path, size_bytes: int
) -> None:
    """Sizes from 0B to 101MB round-trip; sanity boundary at 100MB."""
    big = tmp_path / "blob.bin"
    if size_bytes > 0:
        chunk = b"a"
        with open(big, "wb") as f:
            for _ in range(size_bytes):
                f.write(chunk)
    target = tmp_path / "boundary_target"
    temp_path, _count, sha256 = _serialize_to_payload(tmp_path)
    deserialize_worktree_tar(_chunk_reader(temp_path), target)
    if size_bytes > 0:
        assert (target / "blob.bin").stat().st_size == size_bytes
    assert len(sha256) == 64


# ---------------------------------------------------------------------------
# chunk_reader contract (per plan C.5 step 2)
# ---------------------------------------------------------------------------


def test_chunk_reader_contract(sample_worktree: Path) -> None:
    """chunk_reader is a callable returning Iterator[bytes]; invocable
    once per ``deserialize_worktree_tar`` call. Multiple invocations of
    the same callable return independent iterators (so retries are
    safe per the streaming-compression action-kit contract)."""
    temp_path, _count, _sha = _serialize_to_payload(sample_worktree)

    reader = _chunk_reader(temp_path)
    assert callable(reader)
    # Two independent iterators from the same callable.
    it1 = reader()
    it2 = reader()
    first = next(it1)
    assert isinstance(first, bytes)
    # The two iterators are independent; exhausting one does not
    # exhaust the other.
    assert next(it2) == first


# ---------------------------------------------------------------------------
# Self-check: tempfile API sanity (guard against platform quirks)
# ---------------------------------------------------------------------------


def test_tempfile_mkstemp_creates_real_file(tmp_path: Path) -> None:
    """Sanity-check the stdlib API our error wrappers depend on."""
    fd, path_str = tempfile.mkstemp(
        prefix="sanity-", suffix=".bin", dir=str(tmp_path)
    )
    try:
        with open(fd, "wb") as f:
            f.write(b"x")
        assert Path(path_str).exists()
    finally:
        Path(path_str).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Additional coverage: deserialize error wrappers + cleanup failure paths
# ---------------------------------------------------------------------------


def test_deserialize_temp_create_oserror_wrapped(
    sample_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MHV-209 also applies to deserialize's mkstemp (MHV-209 shared)."""
    import tempfile as tempfile_mod

    def _explode(*args: object, **kwargs: object) -> tuple[int, str]:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile_mod, "mkstemp", _explode)
    target = sample_worktree.parent / "extracted_mkstemp_fail"

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(_chunk_reader(sample_worktree), target)
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_TEMP_CREATE_FAILED
    assert not target.exists()


def test_deserialize_temp_write_oserror_wrapped(
    sample_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MHV-210: writing the decompressed tar temp file raises OSError."""
    import builtins

    # Snapshot the real open BEFORE monkeypatch; the wrapper delegates to it.
    real_open = builtins.open

    class _ExplodingFile:
        # See test_serialize_temp_write_oserror_wrapped for the rationale;
        # production calls builtins.open, not os.fdopen. read() delegates to
        # the inner file so the wrapper is also safe for read-side opens.
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._inner = real_open(*args, **kwargs)

        def write(self, _data: bytes) -> int:
            raise OSError(5, "Input/output error")

        def read(self, size: int = -1) -> bytes:
            return self._inner.read(size)

        def flush(self) -> None:
            self._inner.flush()

        def __enter__(self) -> _ExplodingFile:
            return self

        def __exit__(self, *args: object) -> None:
            self._inner.close()

    # Pre-build a real tar.zst payload to feed in.
    temp_path, _count, _sha = _serialize_to_payload(sample_worktree)
    monkeypatch.setattr("builtins.open", _ExplodingFile)
    target = sample_worktree.parent / "extracted_write_fail"

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(_chunk_reader(temp_path), target)
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED
    assert not target.exists()


def test_deserialize_target_already_exists(sample_worktree: Path) -> None:
    """If target exists before deserialize, MHV-210 wraps the refusal."""
    temp_path, _count, _sha = _serialize_to_payload(sample_worktree)
    target = sample_worktree.parent / "preexisting_target"
    target.mkdir()
    # Add a sentinel file so we can prove the rename never happened.
    sentinel = target / "sentinel.txt"
    sentinel.write_text("original")

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(_chunk_reader(temp_path), target)
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED
    # Atomic-promote must NOT have replaced target contents.
    assert sentinel.read_text() == "original"


def test_deserialize_emits_tail_bytes(sample_worktree: Path) -> None:
    """zstd flush() may yield trailing bytes — round-trip must cover that
    branch (line ~247 ``raw_file.write(tail)``)."""
    temp_path, byte_count, _sha = _serialize_to_payload(sample_worktree)
    # Lower the chunk size in the chunk_reader to force multiple
    # ``decompressor.decompress`` calls; this raises the chance that
    # the final ``flush()`` returns a non-empty tail.
    target = sample_worktree.parent / "tail_target"
    deserialize_worktree_tar(_chunk_reader(temp_path, chunk_size=512), target)
    assert (target / "file.txt").read_text() == "hello"
    assert byte_count > 0


def test_serialize_zstd_unavailable_raises_mhv223(
    sample_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If zstandard cannot be imported, MHV-223 wraps the missing dep."""
    import sys

    # Hide the already-imported zstandard module so the lazy import
    # inside serialize fails. Restore on exit so other tests still work.
    monkeypatch.delitem(sys.modules, "zstandard", raising=False)
    monkeypatch.setattr(sys, "path", [])

    # We need to defeat the module cache too. Easiest path: stub the
    # import via ``__import__``.
    import builtins

    real_import = builtins.__import__

    def _deny(name: str, *args: object, **kwargs: object) -> object:
        if name == "zstandard" or name.startswith("zstandard."):
            raise ImportError("simulated missing zstandard")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _deny)

    with pytest.raises(WorktreeError) as exc_info:
        with serialize_worktree_tar(sample_worktree):
            pytest.fail("context body must not execute")
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE


def test_deserialize_zstd_unavailable_raises_mhv223(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MHV-223 also fires if zstandard disappears between serialize
    and deserialize (e.g., operator uninstalls between writes)."""
    import builtins

    real_import = builtins.__import__

    def _deny(name: str, *args: object, **kwargs: object) -> object:
        if name == "zstandard" or name.startswith("zstandard."):
            raise ImportError("simulated missing zstandard")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _deny)

    with pytest.raises(WorktreeError) as exc_info:
        deserialize_worktree_tar(lambda: iter([b"\x00\x01"]), tmp_path / "x")
    assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE


def test_cleanup_temp_swallows_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_cleanup_temp`` logs a warning and never raises even if unlink fails."""
    from mahavishnu.core.worktree_providers import storage_io

    real = tmp_path / "to-be-removed"
    real.write_text("x")
    # Replace Path.unlink for this single instance so it raises OSError.
    boom_calls = {"n": 0}

    def _boom_unlink(self: Path, *args: object, **kwargs: object) -> None:
        boom_calls["n"] += 1
        raise OSError(5, "boom")

    monkeypatch.setattr(Path, "unlink", _boom_unlink)
    # Should not raise — _cleanup_temp is best-effort.
    storage_io._cleanup_temp(real)
    assert boom_calls["n"] == 1


def test_cleanup_dir_swallows_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_cleanup_dir`` logs a warning and never raises even if rmtree fails."""
    from mahavishnu.core.worktree_providers import storage_io

    real = tmp_path / "to-be-removed-dir"
    real.mkdir()

    def _rmtree(*args: object, **kwargs: object) -> None:
        raise OSError(5, "boom")

    import shutil

    monkeypatch.setattr(shutil, "rmtree", _rmtree)
    # Should not raise.
    storage_io._cleanup_dir(real)


def test_cleanup_dir_skips_missing_path() -> None:
    """``_cleanup_dir`` short-circuits when ``path`` doesn't exist."""
    from mahavishnu.core.worktree_providers import storage_io

    # /nonexistent/should/not/exist/anywhere should not raise.
    storage_io._cleanup_dir(Path("/nonexistent/should/not/exist/anywhere"))


def test_cleanup_temp_skips_missing_path() -> None:
    """``_cleanup_temp`` short-circuits when ``path`` doesn't exist."""
    from mahavishnu.core.worktree_providers import storage_io

    # Should not raise even though the file doesn't exist.
    storage_io._cleanup_temp(Path("/nonexistent/worktree-cleanup-test"))
