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
  ``rename()`` the staging dir onto ``target`` (atomic-promote).
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
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

from mahavishnu.core.errors import ErrorCode, WorktreeError
from mahavishnu.observability.bundle_integrity import verify_sha256_streaming

_logger = logging.getLogger(__name__)


# Stopgap upper bound for the in-memory / temp-file path. Bundles
# larger than this MUST use streaming-aware storage adapters. Exposed
# at module scope so providers and tests can reference the same value.
MAX_BUNDLE_BYTES_STOPGAP: int = 256 * 1024 * 1024  # 256MB


@contextmanager
def serialize_worktree_tar(
    source: Path,
    *,
    compression_level: int = 3,
) -> Iterator[tuple[Path, int, str]]:
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
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"source path does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"source is not a directory: {source}")

    # Lazy import — zstandard is optional via the compression-zstd PEP
    # 735 group; raise a clear error rather than failing at import time.
    try:
        import zstandard
    except ImportError as exc:
        raise WorktreeError(
            "zstandard dependency required for streaming tar.zst; "
            "install with `uv sync --group compression-zstd`",
            error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
        ) from exc

    # Create the temp file BEFORE entering the try block so cleanup
    # is unconditional — any exception (including the OSError below)
    # results in the temp file being removed.
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

    temp_path = Path(temp_path_str)

    try:
        # Build the tar payload into memory. The tarfile module does
        # not expose a true streaming writer today; the streaming
        # surface in this module is the zstd chunker + the caller's
        # temp file path. Peak memory during serialize is ~2x the
        # uncompressed tar size, bounded by MAX_BUNDLE_BYTES_STOPGAP
        # for callers using the in-memory stopgap path.
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            tar.add(str(source), arcname=".", recursive=True)
        tar_data = tar_buffer.getvalue()

        # Stream the tar bytes through the zstd chunker and write the
        # compressed output to the temp file. ``chunker()`` returns a
        # stateful compressor that buffers across calls; we feed it
        # the full tar payload and iterate the yielded output bytes
        # so we can hash + count + write incrementally.
        sha = hashlib.sha256()
        byte_count = 0
        chunker = zstandard.ZstdCompressor(level=compression_level).chunker()
        try:
            with os.fdopen(fd, "wb") as raw_file:
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

        sha_hex = sha.hexdigest()
        yield temp_path, byte_count, sha_hex
    except BaseException:
        # CancelledError, KeyboardInterrupt, and any other
        # BaseException subclass must trigger cleanup. Re-raise
        # after removing the temp file so callers see the original
        # exception untouched.
        _cleanup_temp(temp_path)
        raise


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
        # Lazy import — same rationale as serialize_worktree_tar.
        try:
            import zstandard
        except ImportError as exc:
            raise WorktreeError(
                "zstandard dependency required for streaming tar.zst; "
                "install with `uv sync --group compression-zstd`",
                error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
            ) from exc

        try:
            fd, temp_path_str = tempfile.mkstemp(
                prefix=f"worktree-dl-{uuid.uuid4().hex[:8]}-",
                suffix=".tar",
            )
            temp_path = Path(temp_path_str)
        except OSError as exc:
            raise WorktreeError(
                f"Failed to create temp file for decompressed tar: {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_CREATE_FAILED,
            ) from exc

        # Stream the compressed chunks through the zstd decompressor
        # into a temp file. Hash the COMPRESSED bytes (this is the
        # value ``serialize_worktree_tar`` produced) so the caller
        # can verify integrity without re-hashing plaintext.
        sha = hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as raw_file:
                decompressor = zstandard.ZstdDecompressor().decompressobj()
                for compressed_chunk in chunk_reader():
                    sha.update(compressed_chunk)
                    plaintext = decompressor.decompress(compressed_chunk)
                    if plaintext:
                        raw_file.write(plaintext)
                tail = decompressor.flush()
                if tail:
                    raw_file.write(tail)
                raw_file.flush()
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

        actual_sha = sha.hexdigest()
        if expected_sha256 is not None:
            # verify_sha256_streaming raises WorktreeIntegrityError on
            # mismatch (MHV-208) after emitting the metric.
            verify_sha256_streaming(
                actual_sha,
                expected_sha256,
                backend=backend,
                principal_short=principal_short,
            )

        # Ensure target.parent exists, then create the sibling staging
        # directory. Using a sibling (not a child of target) is what
        # makes the atomic-promote work: we never materialize target
        # until the rename below.
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=False, exist_ok=False)

        try:
            with tarfile.open(temp_path, mode="r:") as tar:
                # ``tarfile.data_filter`` (Python 3.12+, stable without
                # DeprecationWarning in 3.14) rejects path-traversal,
                # absolute symlink targets, device files, and FIFOs.
                tar.extractall(staging, filter=tarfile.data_filter)
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
