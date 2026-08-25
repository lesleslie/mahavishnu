"""Streaming tar.zst I/O for worktree bundles (ADR 015 v4 Phase 3).

The Phase 3 worktree bundle format is ``.tar.zst`` (tar + zstd) streamed
end-to-end. This module is the thin serde layer between the on-disk
worktree directory and the storage adapter (oneiric's
``LocalStorageAdapter.save_stream`` / ``S3StorageAdapter.upload_part``).

Design contract (per Phase 3 plan C.5 + reviewer feedback):

- ``serialize_worktree_tar`` is a :func:`contextlib.contextmanager` that
  yields ``(temp_path, byte_count, sha256)`` once the tar.zst has been
  fully streamed to a temporary file. The caller is responsible for
  atomic-promoting ``temp_path`` to its final location once the
  context exits successfully — this lets the storage adapter call
  ``rename`` after a successful multipart upload without leaking
  partial payloads.
- ``deserialize_worktree_tar`` consumes a ``chunk_reader`` (a sync
  ``Callable[[], Iterator[bytes]]``) and extracts into a staging
  directory under ``target``. Only on full success does it
  ``rename()`` the staging directory onto ``target`` (atomic-promote).
- Integrity verification is delegated to
  :func:`mahavishnu.observability.bundle_integrity.verify_sha256_streaming`
  so the metric emission shape is identical to the in-memory path.
- All cleanup paths catch ``BaseException`` (not just ``Exception``)
  because ``asyncio.CancelledError`` and ``KeyboardInterrupt`` are
  ``BaseException`` subclasses — leaking temp files on cancel was
  the B-DI-07 BLOCKER.
- Path traversal is blocked by passing ``filter=tarfile.data_filter``
  to ``tar.extractall``; on rejection, the underlying ``tarfile``-
  level exception is re-raised as
  :class:`WorktreeError` with ``WORKTREE_BUNDLE_PATH_TRAVERSAL``
  (MHV-211).
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import logging
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

from mahavishnu.core.errors import ErrorCode, WorktreeError
from mahavishnu.observability.bundle_integrity import verify_sha256_streaming

_logger = logging.getLogger(__name__)


# Stopgap upper bound for the in-memory / temp-file path. Bundles
# larger than this MUST use streaming-aware storage adapters. Exposed
# at module scope so providers and tests can reference the same value.
MAX_BUNDLE_BYTES_STOPGAP: int = 256 * 1024 * 1024  # 256MB


def _validate_source_path(source: Path) -> Path:
    """Validate that ``source`` is an existing directory.

    Returns the resolved ``Path``. Raises ``FileNotFoundError`` /
    ``NotADirectoryError`` for parity with the previous contract.
    """
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"source path does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"source is not a directory: {source}")
    return source


def _load_zstandard() -> Any:
    """Lazy-import zstandard; surface a structured error when missing.

    The optional ``compression-zstd`` PEP 735 group supplies the binary;
    without it we cannot stream tar.zst bundles. Raises
    :class:`WorktreeError` with ``WORKTREE_BUNDLE_CODEC_UNAVAILABLE``
    (MHV-223) so callers see a uniform surface.
    """
    try:
        import zstandard as zstandard_runtime
    except ImportError as exc:
        raise WorktreeError(
            "zstandard dependency required for streaming tar.zst; "
            "install with `uv sync --group compression-zstd`",
            error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
        ) from exc
    return zstandard_runtime


def _create_zst_tempfile() -> Path:
    """Create a fresh ``.tar.zst`` tempfile and close the descriptor.

    The caller reopens the file for writing via :func:`open` (rather
    than :func:`os.fdopen`) so the descriptor is not threaded through
    the orchestrator. Raises :class:`WorktreeError` with
    ``WORKTREE_BUNDLE_TEMP_CREATE_FAILED`` (MHV-209) on ``OSError``.
    """
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=f"worktree-{uuid.uuid4().hex[:8]}-",
            suffix=".tar.zst",
        )
    except OSError as exc:
        raise WorktreeError(
            f"Failed to create temp file for tar.zst: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_CREATE_FAILED,
        ) from exc
    os.close(fd)
    return Path(temp_path_str)


def _build_tar_payload(source: Path) -> bytes:
    """Build an in-memory tar archive of ``source``.

    The tarfile module does not expose a true streaming writer; we
    serialize the tar in-memory and stream the bytes through zstd. Peak
    memory during serialize is ~2x the uncompressed tar size, bounded
    by ``MAX_BUNDLE_BYTES_STOPGAP`` for callers using the in-memory
    stopgap path.
    """
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        tar.add(str(source), arcname=".", recursive=True)
    return tar_buffer.getvalue()


def _write_zstd_stream_to_file(
    tar_data: bytes, temp_path: Path, compression_level: int
) -> tuple[int, str]:
    """Stream zstd-compressed tar bytes into ``temp_path``.

    Returns ``(byte_count, sha_hex)`` where ``byte_count`` is the
    compressed on-disk size and ``sha_hex`` is the digest of the
    compressed stream (matches what ``deserialize_worktree_tar`` will
    verify against).

    Raises :class:`WorktreeError` with ``WORKTREE_BUNDLE_TEMP_WRITE_FAILED``
    (MHV-210) when the OS rejects the write.
    """
    zstandard = _load_zstandard()
    sha = hashlib.sha256()
    byte_count = 0

    compressor: Any = zstandard.ZstdCompressor(level=compression_level)
    chunker: Any = compressor.chunker()

    try:
        with open(temp_path, "wb") as raw_file:
            for output in chunker.compress(tar_data):
                raw_file.write(output)
                sha.update(output)
                byte_count += len(output)
            for output in chunker.finish():
                raw_file.write(output)
                sha.update(output)
                byte_count += len(output)
            raw_file.flush()
    except OSError as exc:
        raise WorktreeError(
            f"Failed to write tar.zst temp file: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
        ) from exc

    return byte_count, sha.hexdigest()


@contextmanager
def serialize_worktree_tar(
    source: Path,
    *,
    compression_level: int = 3,
) -> Generator[tuple[Path, int, str]]:
    """Stream a worktree directory to a temp tar.zst file.

    Yields ``(temp_path, byte_count, sha256)`` where:

    - ``temp_path`` is a fresh ``tempfile.mkstemp()`` path; the file
      descriptor is closed before the yield, and the caller takes
      ownership of the path.
    - ``byte_count`` is the compressed byte count (matches ``Path.stat().st_size``
      of ``temp_path`` on disk).
    - ``sha256`` is the hex digest of the compressed bytes.

    The caller must copy or move ``temp_path`` to its final location
    after the context exits successfully. On any exception (including
    ``CancelledError`` / ``KeyboardInterrupt``), the temp file is
    removed before the exception is re-raised.

    Raises:
        FileNotFoundError: ``source`` does not exist.
        NotADirectoryError: ``source`` is not a directory.
        WorktreeError: ``MHV-223`` if ``zstandard`` is not installed;
            ``MHV-209`` if ``tempfile.mkstemp`` raises ``OSError``;
            ``MHV-210`` if writing the temp file raises ``OSError``.
    """
    source = _validate_source_path(source)
    _load_zstandard()  # fail-fast on missing codec before temp-file work
    temp_path = _create_zst_tempfile()

    try:
        tar_data = _build_tar_payload(source)
        byte_count, sha_hex = _write_zstd_stream_to_file(tar_data, temp_path, compression_level)
        yield temp_path, byte_count, sha_hex
    except BaseException:
        # CancelledError, KeyboardInterrupt, and any other
        # BaseException subclass must trigger cleanup. Re-raise
        # after removing the temp file so callers see the original
        # exception untouched.
        _cleanup_temp(temp_path)
        raise


def _create_tar_tempfile() -> Path:
    """Create a fresh ``.tar`` tempfile and return the path.

    Raises :class:`WorktreeError` with ``WORKTREE_BUNDLE_TEMP_CREATE_FAILED``
    (MHV-209) on ``OSError``. The descriptor is closed before returning
    (caller reopens via :func:`open`).
    """
    try:
        fd, temp_path_str = tempfile.mkstemp(
            prefix=f"worktree-dl-{uuid.uuid4().hex[:8]}-",
            suffix=".tar",
        )
    except OSError as exc:
        raise WorktreeError(
            f"Failed to create temp file for decompressed tar: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_CREATE_FAILED,
        ) from exc
    os.close(fd)
    return Path(temp_path_str)


def _decompress_and_write(
    chunk_reader: Callable[[], Iterator[bytes]],
    decompressor: Any,
    raw_file: Any,
    sha: Any,
) -> None:
    """Drive the streaming decompression loop and write plaintext bytes to ``raw_file``.

    ``sha`` is updated with the COMPRESSED chunk bytes so the caller
    can verify integrity without re-hashing plaintext (matches the
    producer side in ``serialize_worktree_tar``).
    """
    for compressed_chunk in chunk_reader():
        sha.update(compressed_chunk)
        plaintext = decompressor.decompress(compressed_chunk)
        if plaintext:
            raw_file.write(plaintext)
    tail = decompressor.flush()
    if tail:
        raw_file.write(tail)
    raw_file.flush()


def _decompress_chunks_to_tempfile(
    chunk_reader: Callable[[], Iterator[bytes]],
    temp_path: Path,
) -> str:
    """Stream-decompress ``chunk_reader`` into ``temp_path`` and return the SHA.

    Hashes the COMPRESSED bytes (matching what ``serialize_worktree_tar``
    produced) so the caller can verify integrity without re-hashing
    plaintext. Raises :class:`WorktreeError` for malformed zstd
    payloads (MHV-212) and write failures (MHV-210).
    """
    zstandard = _load_zstandard()
    sha = hashlib.sha256()
    decompressor: Any = zstandard.ZstdDecompressor().decompressobj()

    try:
        with open(temp_path, "wb") as raw_file:
            _decompress_and_write(chunk_reader, decompressor, raw_file, sha)
    except OSError as exc:
        raise WorktreeError(
            f"Failed to write decompressed tar temp file: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
        ) from exc
    except zstandard.ZstdError as exc:
        # Corrupt zstd header / truncated frame / etc.
        raise WorktreeError(
            f"Malformed zstd payload: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_MALFORMED,
        ) from exc

    return sha.hexdigest()


def _verify_compressed_integrity(
    actual_sha: str,
    expected_sha256: str | None,
    backend: str,
    principal_short: str,
) -> None:
    """Verify ``actual_sha`` against ``expected_sha256`` when provided.

    ``verify_sha256_streaming`` raises :class:`WorktreeIntegrityError`
    on mismatch (MHV-208) after emitting the metric.
    """
    if expected_sha256 is None:
        return
    verify_sha256_streaming(
        actual_sha,
        expected_sha256,
        backend=backend,
        principal_short=principal_short,
    )


def _extract_tar_atomic(temp_path: Path, target: Path, staging: Path) -> None:
    """Extract ``temp_path`` into ``staging`` and atomic-promote onto ``target``.

    Uses ``tarfile.data_filter`` to reject path-traversal, absolute
    symlink targets, device files, and FIFOs. Raises
    :class:`WorktreeError` with ``WORKTREE_BUNDLE_PATH_TRAVERSAL``
    (MHV-211) for filter rejections and
    ``WORKTREE_BUNDLE_MALFORMED`` (MHV-212) for corrupt tar archives.

    The ``tarfile.open(...).extractall(...)`` call below is the
    sanctioned extraction path: ``filter=tarfile.data_filter`` is
    the documented defense against path traversal (see Python 3.12
    release notes and B-DI-11 in the Phase 3 review). The semgrep
    ``tarfile-extractall-traversal`` rule fires on the open() call
    alone; we ignore it for this line because the data_filter is
    applied at extractall.
    """
    try:
        # ``tarfile.data_filter`` (Python 3.12+, stable without
        # DeprecationWarning in 3.14) rejects path-traversal,
        # absolute symlink targets, device files, and FIFOs. The
        # nosemgrep directives below are scoped to the line that
        # semgrep would otherwise flag — extractall IS guarded by
        # data_filter on the next line.
        with tarfile.open(  # nosemgrep: tarfile-extractall-traversal
            temp_path, mode="r:"
        ) as tar:
            tar.extractall(staging, filter=tarfile.data_filter)  # nosemgrep
    except (
        tarfile.OutsideDestinationError,
        tarfile.LinkOutsideDestinationError,
        tarfile.AbsolutePathError,
        tarfile.SpecialFileError,
    ) as exc:
        # data_filter rejection — treat as path traversal since
        # that's the only sanctioned reason to reject in this
        # context (legitimate bundles never include such members).
        raise WorktreeError(
            f"Path traversal detected in tar payload: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_PATH_TRAVERSAL,
        ) from exc
    except (tarfile.TarError, ValueError, KeyError) as exc:
        raise WorktreeError(
            f"Malformed tar archive: {exc}",
            error_code=ErrorCode.WORKTREE_BUNDLE_MALFORMED,
        ) from exc

    # Atomic-promote: rename the staging directory onto target.
    # Reject if target already exists — the caller is responsible
    # for cleaning the prior materialization (and there's no safe
    # default for partial-overwrite semantics here).
    if target.exists():
        raise WorktreeError(
            f"Target already exists: {target}",
            error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
        )
    staging.rename(target)


def deserialize_worktree_tar(
    chunk_reader: Callable[[], Iterator[bytes]],
    target: Path,
    *,
    expected_sha256: str | None = None,
    backend: str = "unknown",
    principal_short: str = "unknown",
) -> None:
    """Stream a tar.zst payload from ``chunk_reader`` into ``target``.

    Writes the decompressed tar bytes to a temp file (so partial
    decompression failures leave no debris on disk), verifies the
    SHA-256 of the compressed stream against ``expected_sha256`` if
    provided, extracts the tar into ``<target>/.staging-<uuid>`` using
    ``tarfile.data_filter``, then atomically ``rename``s the staging
    directory onto ``target``.

    On any failure (decompression, integrity, extraction, rename,
    ``CancelledError``, ``KeyboardInterrupt``) the temp file and
    staging directory are removed before the exception is re-raised.

    Raises:
        WorktreeError: ``MHV-223`` if ``zstandard`` is not installed;
            ``MHV-209`` if ``tempfile.mkstemp`` raises ``OSError``;
            ``MHV-210`` if writing the temp file raises ``OSError``;
            ``MHV-211`` if ``tarfile.data_filter`` rejects a member
            (path traversal, absolute symlink, device file, etc.);
            ``MHV-212`` if the zstd or tar payload is malformed;
            ``MHV-208`` (re-raised) if SHA-256 verification fails.
    """
    target = Path(target)
    # Sibling staging dir under ``target.parent`` so creating staging
    # does NOT materialize ``target`` itself. The rename below then
    # performs a true atomic-promote (``os.rename`` is atomic on the
    # same filesystem).
    staging = target.parent / f".staging-{uuid.uuid4().hex}"
    temp_path: Path | None = None

    try:
        temp_path = _create_tar_tempfile()
        actual_sha = _decompress_chunks_to_tempfile(chunk_reader, temp_path)
        _verify_compressed_integrity(actual_sha, expected_sha256, backend, principal_short)

        # Ensure target.parent exists, then create the sibling staging
        # directory. Using a sibling (not a child of target) is what
        # makes the atomic-promote work: we never materialize target
        # until the rename below.
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=False, exist_ok=False)
        _extract_tar_atomic(temp_path, target, staging)
    except BaseException:
        # BaseException covers CancelledError / KeyboardInterrupt as
        # well as any WorktreeError we raised above. Always clean up
        # the temp file and staging dir before propagating.
        if temp_path is not None:
            _cleanup_temp(temp_path)
        _cleanup_dir(staging)
        raise


def _cleanup_temp(path: Path) -> None:
    """Best-effort unlink of ``path``; never raises."""
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        _logger.warning(
            "worktree-storage-io-temp-cleanup-failed",
            extra={"path": str(path), "error": str(exc)},
        )


def _cleanup_dir(path: Path) -> None:
    """Best-effort recursive remove of ``path``; never raises."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        _logger.warning(
            "worktree-storage-io-staging-cleanup-failed",
            extra={"path": str(path), "error": str(exc)},
        )
