# Streaming tar.zst bundles for worktree providers — Phase 3 design

**Status:** approved (brainstorming complete; ready for writing-plans)
**Date:** 2026-08-23
**Author:** Claude (collaborative design with les)
**ADR reference:** ADR 015 v4 §6 (bundle format), §16 (size SLOs), §18 Phase 3
**Replaces:** ADR 015 v4 Phase 2 §6 — gzipped tar bundles held in memory

## Context

Phase 2 of ADR 015 v4 ships the cache + observability wiring but uses
`io.BytesIO` to hold the entire gzipped tar bundle in memory during
serialize/deserialize:

```python
def serialize_worktree_tar(path: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(path), arcname=".", recursive=True)
    return buf.getvalue()  # entire bundle in memory
```

Per ADR §16, worktree bundles are capped at 100MB; observed memory
peak during CPython's tarfile compression is ~2.5× the source size
(~250MB peak for a 100MB worktree). Phase 2 was acceptable at the
100MB cap. Phase 3 removes the cap by streaming.

This phase also switches compression from gzip to zstd. Zstd is
~3× faster at compress/decompress and uses ~50% less memory at
comparable compression ratios. Both algorithms are already supported
by Python's `tarfile` module via the `zstandard` library.

**Scope confirmed (2026-08-23):**

- No backward compat with existing Phase 2 tar.gz bundles. Old handles
  are orphaned; new handles are tar.zst only. This eliminates the
  `WorktreeHandle.bundle_format` field, the `bundle_format` literal
  type, and the dual-code-path complexity.
- zstd streaming primitives land in Oneiric's `compression` action kit
  for cross-Bodai reuse. Mahavishnu consumes them via the kit.
- Oneiric storage adapters grow streaming `save_stream` /
  `read_stream` methods. Existing `save` / `read` (bytes-in /
  bytes-out) stay for all current callers.

**Two repos affected:** Oneiric (action kit + storage adapter streaming)
+ Mahavishnu (storage_io rewrite + provider updates).

## Architecture

### Two repos, three components (down from initial four when backward compat was in scope)

| Component | Repo | Role |
|---|---|---|
| `StreamingCompressionAction` (new kit, key `compression.stream`) | oneiric | Streaming gzip + zstd compress/decompress. Sync `stream_compress` / `stream_decompress` generator methods; async `execute` wrapper for action-kit dispatchers. |
| `LocalStorageAdapter` / `S3StorageAdapter` / `GCSStorageAdapter` / `AzureBlobStorageAdapter` — `save_stream` + `read_stream` (additive) | oneiric | Chunked write/read of storage blobs. Mahavishnu's providers consume these for streaming upload/download. |
| `mahavishnu/core/worktree_providers/storage_io.py` (rewrite) | mahavishnu | `serialize_worktree_tar` returns `(temp_path, byte_size, sha256)` using `tar.zst` only. `deserialize_worktree_tar` reads from a chunked source, verifies SHA, extracts. |

### Data flow on create (`LocalWorktreeProvider.create_worktree_handle`)

```
1. git worktree add (existing, unchanged) → worktree dir
2. serialize_worktree_tar(worktree_path)
   ├─ tempfile.mkstemp(suffix=".tar.zst", prefix="worktree-")
   ├─ tarfile.open(temp_path, mode="w|zst")
   ├─ tar.add(str(worktree_path), arcname=".", recursive=True)
   ├─ stream-hash temp file in 64KB chunks → sha256
   ├─ return (temp_path, byte_size, sha256)
   └─ cleanup: except handler unlinks temp_path
3. record_bundle_bytes(repo, byte_size)
4. async for chunk in read_chunks(temp_path, 65_536):
       await storage.save_chunk(storage_key, chunk, is_final=...)
   ── OR (Phase 3 stopgap): blob = temp_path.read_bytes(); await storage.save(key, blob)
5. Build WorktreeHandle(sha256=sha, bytes_size=byte_size, ...)
6. dhara.register_handles(client, [handle], caller=principal)
7. temp_path.unlink(missing_ok=True)
8. record_worktree_op(backend="local", op="create", success=True)
```

**Phase 3 stopgap vs full streaming:** Step 4 has two implementations.
The stopgap reads the temp file into memory and calls the existing
`storage.save(key, bytes)` — eliminates compression peak (Phase 3's
primary goal) but still allocates bundle_size during upload. The full
streaming version calls `storage.save_stream(key, chunk_iterator)`
and never materializes the bundle. The full version requires Oneiric
storage adapters to expose `save_stream` (Phase 3 scope).

### Data flow on fetch (`LocalWorktreeProvider.fetch`)

```
1. Cache hit check (existing, unchanged):
   cache_key = f"materialized:{handle.handle_id}"
   if cache hit and path.exists(): return LocalWorktreeRef
2. async for chunk in storage.read_stream(storage_key, offset=0, chunk_size=65_536):
       write chunk to tempfile + update sha256 hasher incrementally
3. verify_sha256(actual, handle.sha256, backend="local", principal=...)
   ── mismatch: WorktreeIntegrityError (MHV-208), bundle_integrity_failure_total
                emitted, tempfile auto-unlinked via finally
4. tarfile.open(temp_path, mode="r|zst")
   tar.extractall(target, filter=tarfile.data_filter)
   ── data_filter rejects path-traversal members (../../etc/passwd)
5. temp_path.unlink(missing_ok=True) — in finally
6. cache.set(cache_key, str(target))
7. record_worktree_op(backend="local", op="fetch", success=True)
```

### Memory profile comparison

| Phase | Before (Phase 2) | After (Phase 3) |
|---|---|---|
| **Create (compression peak)** | 2.5× bundle_size (~250MB for 100MB worktree) | ~0 (disk is the buffer) |
| **Create (upload peak)** | bundle_size (already in-memory) | bundle_size (stopgap) → ~0 (full streaming) |
| **Fetch (blob load peak)** | bundle_size | bundle_size (stopgap) → O(chunk_size) (full streaming) |
| **Fetch (extract peak)** | 2.5× bundle_size (~250MB) | ~0 (disk is the buffer) |

Net: the 250MB peak during compression and the 250MB peak during extract
are eliminated in all configurations. Upload/download peak depends on
whether `save_stream` / `read_stream` are wired (in scope for Phase 3) or
the stopgap `read_bytes` path is used.

### Why temp file as intermediate buffer (not pure streaming)

`tarfile.extractall` needs random access to the archive (for member lookup).
`r|gz` and `r|zst` modes support sequential iteration but you can't seek
back. Pure streaming would require implementing our own tar parser with a
seekable index, which is far more complex than using a temp file as the
buffer. Disk I/O is cheap; the bundle is materialized on disk (not memory)
and auto-cleaned after extract. The temp file is bounded by bundle size
(no growth), and on POSIX the `mkstemp` prefix keeps it out of normal
directory listings.

## Component changes (detailed)

### Oneiric

**File 1: `oneiric/pyproject.toml`**

Add `zstandard>=0.21` to `dependencies`.

**File 2: `oneiric/actions/compression.py`** — append a new class:

```python
class StreamingCompressionAction:
    """Streaming compress/decompress for chunked sources too large for memory.

    Use when the source is an iterator of byte chunks (file chunks, network
    bytes) and you can't afford to materialize the whole blob in memory
    before compressing. For in-memory payloads, prefer CompressionAction
    (simpler API, base64 output, action-kit dispatch).

    Provides sync generator methods (stream_compress, stream_decompress)
    for direct use, and an async execute() wrapper for action-kit dispatchers
    that return metadata only.
    """

    metadata = ActionMetadata(
        key="compression.stream",
        provider="builtin-streaming-compression",
        factory="oneiric.actions.compression:StreamingCompressionAction",
        description="Streaming gzip/zstd compress/decompress for chunked input",
        domains=["task", "workflow"],
        capabilities=["compress", "decompress", "stream"],
        stack_level=25,
        priority=448,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
    )

    _SUPPORTED: ClassVar[set[str]] = {"gzip", "zstd"}

    def __init__(self, settings: CompressionActionSettings | None = None) -> None:
        self._settings = settings or CompressionActionSettings()
        self._logger = get_logger("action.compression.stream")

    def stream_compress(
        self,
        chunks: Iterator[bytes],
        *,
        algorithm: str | None = None,
        level: int | None = None,
    ) -> Iterator[bytes]:
        algo = (algorithm or self._settings.algorithm).lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            import zstandard
            lvl = level if level is not None else self._settings.level
            cctx = zstandard.ZstdCompressor(level=lvl)
            yield from cctx.chunked_stream_compress(chunks)
        elif algo == "gzip":
            yield from self._gzip_stream_compress(chunks, level or self._settings.level)

    def stream_decompress(
        self,
        chunks: Iterator[bytes],
        *,
        algorithm: str,
    ) -> Iterator[bytes]:
        algo = algorithm.lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            import zstandard
            dctx = zstandard.ZstdDecompressor()
            yield from dctx.chunked_stream_decompress(chunks)
        elif algo == "gzip":
            yield from self._gzip_stream_decompress(chunks)

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        # Returns metadata only. Callers wanting the streamed bytes must
        # invoke stream_compress/stream_decompress directly (the action-kit
        # async envelope is for dispatchers that don't handle iterators).
        mode = payload.get("mode", "compress")
        return {"status": "noop", "mode": mode, "note": "use stream_compress/stream_decompress directly"}

    @staticmethod
    def _gzip_stream_compress(chunks, level):
        # zlib for streaming gzip (Python's gzip module doesn't stream).
        cctx = zlib.compressobj(level)
        for chunk in chunks:
            data = cctx.compress(chunk)
            if data:
                yield data
        tail = cctx.flush()
        if tail:
            yield tail

    @staticmethod
    def _gzip_stream_decompress(chunks):
        dctx = zlib.decompressobj(zlib.MAX_WBITS | 16)  # gzip header
        for chunk in chunks:
            data = dctx.decompress(chunk)
            if data:
                yield data
        tail = dctx.flush()
        if tail:
            yield tail
```

**File 3: `oneiric/actions/__init__.py::builtin_action_metadata()`** — register
the new kit's `metadata`.

**File 4: `docs/action-kits.md`** — append a new entry alphabetically (before
`compression.encode` since `compression.stream` < `compression.encode` in
byte order).

**File 5: `oneiric/adapters/storage/{local,s3,gcs,azure}.py`** — add two
methods to each adapter. The existing `save` and `read` stay (backward
compat for all current callers).

```python
# LocalStorageAdapter (new methods, sync)
def save_stream(self, key: str, chunks: Iterator[bytes]) -> int:
    """Stream chunks to local file. Returns total bytes written."""
    path = self._base_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)
            written += len(chunk)
    return written

def read_stream(self, key: str, *, offset: int = 0, chunk_size: int = 65_536) -> Iterator[bytes]:
    """Yield chunks of the local file starting at offset."""
    path = self._base_path / key
    if not path.exists():
        return  # empty iterator — matches read()'s None convention
    with open(path, "rb") as f:
        if offset:
            f.seek(offset)
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk

# S3StorageAdapter (new methods, async)
async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> int:
    """Stream chunks to S3. Uses multipart upload automatically when
    total exceeds the part threshold (default 5MB)."""
    # Implementation: upload_part from AsyncIterator, complete_multipart_upload
    ...

async def read_stream(self, key: str, *, offset: int = 0, chunk_size: int = 65_536) -> AsyncIterator[bytes]:
    """Yield S3 object body chunks via get_object + range headers."""
    ...

# GCS / Azure: mirror the S3 async streaming shape (no separate spec needed).
```

**File 6: `oneiric/tests/actions/test_stream_compression_action.py`** (new).

**File 7: `oneiric/tests/adapters/storage/test_local_stream.py`** (new).

**File 8: `oneiric/tests/adapters/storage/test_s3_stream.py`** (new, uses
`moto.mock_aws`).

### Mahavishnu

**File 1: `pyproject.toml`** — add `zstandard>=0.21` to dependencies (or rely
on transitive from oneiric; explicit add is safer).

**File 2: `mahavishnu/core/worktree_providers/storage_io.py`** — full rewrite
of the three functions:

```python
"""Worktree bytes serialization helpers (ADR 015 v4 §6, Phase 3 streaming).

Stream worktree directories to/from a single tar.zst blob. The bundle is
materialized on disk via a temp file as an intermediate buffer (between
tarfile's random-access needs and the storage adapter's chunked stream).
Memory peak is bounded by chunk size during read+hash, not by bundle size.

On-disk format: tar (ustar) wrapped in zstd compression. The tar archive
records symlinks as link type explicitly and preserves file modes via
``tar.add(recursive=True)``'s stat capture.

Backward compat note: Phase 2 used tar.gz with bytes-in-memory serialization.
Phase 3 is tar.zst only. Existing Dhara handles from Phase 2 are orphaned
by design (no backward compat per 2026-08-23 design review).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
from typing import Callable, Iterator


def serialize_worktree_tar(path: Path) -> tuple[Path, int, str]:
    """Tar + zstd-compress ``path`` into a temp file. Returns ``(temp_path, byte_size, sha256)``.

    The caller owns ``temp_path`` and MUST ``unlink`` it when done. This
    design lets the caller stream the temp file in chunks to a storage
    adapter without loading the full bundle into memory.

    Memory peak during compression: ~0 (disk is the buffer).
    Memory peak during hash: O(chunk_size) where chunk_size = 65_536.
    """
    fd, name = tempfile.mkstemp(suffix=".tar.zst", prefix="worktree-")
    os.close(fd)  # tarfile will reopen for writing
    temp_path = Path(name)
    try:
        with tarfile.open(temp_path, mode="w|zst") as tar:
            tar.add(str(path), arcname=".", recursive=True)
        # Stream-hash the temp file in 64KB chunks
        hasher = hashlib.sha256()
        bytes_written = 0
        with open(temp_path, "rb") as f:
            while chunk := f.read(65_536):  # type: ignore[assignment]
                hasher.update(chunk)
                bytes_written += len(chunk)
        return temp_path, bytes_written, hasher.hexdigest()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def deserialize_worktree_tar(
    chunk_reader: Callable[[int, int], Iterator[bytes]],
    target: Path,
    *,
    expected_sha256: str,
) -> None:
    """Stream chunks from ``chunk_reader`` → temp file + hash → verify SHA → extract.

    Args:
        chunk_reader: ``(offset, chunk_size) -> Iterator[bytes]`` — matches
            the Oneiric storage adapter ``read_stream`` signature. Caller
            provides an adapter or a closure over an in-memory blob.
        target: Destination directory. Created (parents included) if missing.
        expected_sha256: SHA-256 expected after streaming-hash. Raises
            ``WorktreeIntegrityError`` on mismatch.

    Memory peak: O(chunk_size) during read+hash; ~0 during extract.

    On any failure (SHA mismatch, tarfile read error, extract error,
    path-traversal rejection) the temp file is unlinked via finally.
    """
    from mahavishnu.core.errors import (
        ErrorCode,
        WorktreeError,
        WorktreeIntegrityError,
    )

    target.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=".tar.zst", prefix="worktree-")
    os.close(fd)
    temp_path = Path(name)
    try:
        hasher = hashlib.sha256()
        with open(temp_path, "wb") as f:
            try:
                for chunk in chunk_reader(0, 65_536):
                    f.write(chunk)
                    hasher.update(chunk)
            except (OSError, ValueError) as exc:
                raise WorktreeError(
                    f"Failed to stream bundle into temp file: {exc}",
                    error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
                ) from exc
        actual_sha = hasher.hexdigest()
        if actual_sha != expected_sha256:
            raise WorktreeIntegrityError(
                f"SHA-256 mismatch: expected={expected_sha256!r}, "
                f"actual={actual_sha!r}",
                error_code=ErrorCode.WORKTREE_INTEGRITY_FAILED,
            )
        try:
            with tarfile.open(temp_path, mode="r|zst") as tar:
                tar.extractall(target, filter=tarfile.data_filter)
        except tarfile.OutsideDestinationError as exc:
            raise WorktreeError(
                f"Bundle contains path-traversal member (rejected by data_filter): {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_PATH_TRAVERSAL,
            ) from exc
        except tarfile.TarError as exc:
            raise WorktreeError(
                f"Bundle is malformed or truncated: {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_MALFORMED,
            ) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def compute_sha256(blob: bytes) -> str:
    """Return hex SHA-256 digest of ``blob``. Kept for backward compat with
    callers that have small in-memory bundles; large bundles should use the
    streaming-hash pattern in ``serialize_worktree_tar``.
    """
    return hashlib.sha256(blob).hexdigest()
```

**File 3: `mahavishnu/core/errors.py`** — add four new error codes:

```python
WORKTREE_BUNDLE_TEMP_CREATE_FAILED = "MHV-209"
WORKTREE_BUNDLE_TEMP_WRITE_FAILED = "MHV-210"
WORKTREE_BUNDLE_PATH_TRAVERSAL = "MHV-211"
WORKTREE_BUNDLE_MALFORMED = "MHV-212"
```

**File 4: `mahavishnu/core/worktree_providers/local.py`** — `create_worktree_handle`
+ `fetch` updated:

```python
async def create_worktree_handle(self, repo, branch, base_ref, principal):
    # ... (steps 1-3 unchanged) ...
    temp_path, byte_size, sha = serialize_worktree_tar(wt_path)
    record_bundle_bytes(repo=repo, byte_size=byte_size)
    try:
        storage_key = f"worktrees/{repo}/{branch}/{handle_id}.tar.zst"
        if hasattr(self._storage, "save_stream"):
            # Full streaming path (Phase 3 preferred)
            def _chunks() -> Iterator[bytes]:
                with open(temp_path, "rb") as f:
                    while chunk := f.read(65_536):
                        yield chunk
            await self._storage.save_stream(storage_key, _chunks())
        else:
            # Stopgap: bytes-in-memory upload
            blob = temp_path.read_bytes()
            await self._storage.save(storage_key, blob)
    finally:
        temp_path.unlink(missing_ok=True)
    # ... handle construction + dhara register + metric (unchanged) ...

async def fetch(self, handle):
    # ... cache check unchanged ...
    storage_key = f"worktrees/{handle.repo}/{handle.branch}/{handle.handle_id}.tar.zst"
    if hasattr(self._storage, "read_stream"):
        async def _read() -> AsyncIterator[bytes]:
            async for chunk in self._storage.read_stream(storage_key, offset=0, chunk_size=65_536):
                yield chunk
        chunk_reader = lambda offset, size: self._sync_async_iter(_read())
    else:
        # Stopgap: read whole blob, yield once
        blob = await self._storage.read(storage_key)
        if blob is None:
            raise WorktreeError(f"No storage blob for handle {handle.handle_id}")
        chunk_reader = lambda offset, size: iter([blob])
    target = get_worktree_base_path() / handle.handle_id
    await asyncio.to_thread(
        deserialize_worktree_tar, chunk_reader, target,
        expected_sha256=handle.sha256,
    )
    # ... cache set + metric unchanged ...
```

Note: the streaming read path runs the synchronous tarfile read+extract in
`asyncio.to_thread` to avoid blocking the event loop. The 100MB extract
takes ~0.5-2s on modern hardware.

**File 5: `mahavishnu/core/worktree_providers/remote.py`** — mirror the
local.py changes for the remote (S3/GCS/Azure) path. Same API, different
backend strings for metrics.

**File 6: `tests/unit/test_core_worktree_providers_storage_io.py`** —
rewritten for streaming/zstd:

```python
# Key tests:
# - test_serialize_returns_temp_path_size_sha  (verify tuple shape)
# - test_serialize_temp_cleaned_on_tarfile_error  (cleanup contract)
# - test_serialize_chunked_hash_matches_full_hash  (deterministic)
# - test_deserialize_extracts_content  (round-trip)
# - test_deserialize_verifies_sha  (mismatch raises + temp cleaned)
# - test_deserialize_blocks_path_traversal  (../../etc/passwd rejected)
# - test_deserialize_blocks_truncated_archive  (corrupt byte)
# - test_round_trip_100mb_file  (peak memory < 5MB during extract)
# - test_serialize_cleanup_on_exception  (CancelledError mid-serialize)
```

**File 7: `tests/unit/test_core_worktree_providers_local.py`** — updated for
streaming API. Mirror tests for `tests/unit/test_core_worktree_providers_remote.py`.

**File 8: `docs/adr/015-worktree-and-cache-storage-v4.md`** — §18 status
updated to "Phase 3 shipped" with link to commits.

## Error handling

### Categories

**Tarfile errors:**
- `tarfile.OutsideDestinationError` → wrapped as `WorktreeError(MHV-211)`.
- `tarfile.ReadError` / `tarfile.CompressionError` / `tarfile.TarError`
  → wrapped as `WorktreeError(MHV-212)`.
- `tarfile.HeaderError` → wrapped as `WorktreeError(MHV-212)`.

**Bundle integrity:**
- `WorktreeIntegrityError(MHV-208)` — SHA-256 mismatch. Phase 3 detects
  this during the stream-to-temp write phase, BEFORE extract. Earlier
  detection than Phase 2 (which verified after load, before extract).
  Metric `bundle_integrity_failure_total{backend, principal_short}`
  emitted on detection. Same error code and metric as Phase 2.

**New Phase 3 errors:**
- `WORKTREE_BUNDLE_TEMP_CREATE_FAILED (MHV-209)` — `mkstemp` OSError
  (permission, disk full).
- `WORKTREE_BUNDLE_TEMP_WRITE_FAILED (MHV-210)` — OSError during write
  to temp file (disk full, IO error).
- `WORKTREE_BUNDLE_PATH_TRAVERSAL (MHV-211)` — `tarfile.data_filter`
  rejects a member with `..` in path. Phase 2 tests already cover
  this; Phase 3 verifies for tar.zst.
- `WORKTREE_BUNDLE_MALFORMED (MHV-212)` — corrupted/truncated tar.zst
  archive. Test: flip a byte in the middle of a real tar.zst bundle.

**Cleanup contracts:**
- `serialize_worktree_tar` returns the temp path; caller owns cleanup.
  Provider's `create_worktree_handle` MUST `try/finally` around the
  storage call to ensure unlink.
- `deserialize_worktree_tar` cleans up its own temp file in `finally`.
  Caller doesn't need to know about the temp file at all.
- On `CancelledError` mid-serialize: storage_io's except handler
  unlinks temp file before re-raising. Test: simulate cancellation.

### Open questions (resolved during brainstorming)

**Q1: Chunked storage save/read API.** Resolved: in scope for Phase 3.
Oneiric adapters gain `save_stream` / `read_stream`. Mahavishnu
consumes these. Both sync (local) and async (S3/GCS/Azure) variants.

**Q2: Concurrent serialize calls.** Resolved: `mkstemp`'s random suffix
guarantees unique temp paths per call. No collision risk. Document in
docstring.

**Q3: zstd level tuning.** Resolved: default level 3 (zstd's default).
Tuning deferred until real workload data is collected (could become
a Phase 4 follow-up).

**Q4: SHA-256 cost.** Resolved: ~1-2s for 500MB bundles. Acceptable.

## Testing strategy

### Coverage targets

| Module | Target | Rationale |
|---|---|---|
| `mahavishnu/core/worktree_providers/storage_io.py` | 100% | Critical correctness (compression + integrity) |
| `oneiric/actions/compression.py` (StreamingCompressionAction only) | 100% | Public action kit surface |
| `oneiric/adapters/storage/{local,s3,gcs,azure}.py` (streaming methods only) | ≥90% | New methods |
| `mahavishnu/core/worktree_providers/local.py` (streaming paths in create/fetch) | ≥85% | Phase 2 already covers cache/storage paths |
| `mahavishnu/core/worktree_providers/remote.py` (streaming paths) | ≥85% | Same |

### Test files

**Oneiric (new):**
- `oneiric/tests/actions/test_stream_compression_action.py`
  - `test_stream_compress_zstd_roundtrip`
  - `test_stream_compress_gzip_roundtrip`
  - `test_stream_compress_zstd_large_chunk` (10MB source, 1KB chunks)
  - `test_stream_compress_zstd_small_chunk` (1KB source, 1-byte chunks)
  - `test_stream_compress_unknown_algorithm_raises` (LifecycleError)
  - `test_execute_wrapper_returns_metadata`
- `oneiric/tests/adapters/storage/test_local_stream.py`
  - `test_save_stream_writes_file`
  - `test_read_stream_yields_chunks`
  - `test_save_stream_overwrites_existing`
  - `test_read_stream_offset_beyond_eof_yields_nothing`
- `oneiric/tests/adapters/storage/test_s3_stream.py` (uses `moto.mock_aws`)
  - `test_s3_save_stream_multipart_upload`
  - `test_s3_read_stream_returns_chunks`
  - `test_s3_read_stream_offset_resume`

**Mahavishnu (rewritten):**
- `tests/unit/test_core_worktree_providers_storage_io.py`
  - `test_serialize_returns_temp_path_size_sha`
  - `test_serialize_temp_cleaned_on_tarfile_error`
  - `test_serialize_chunked_hash_matches_full_hash`
  - `test_deserialize_extracts_content`
  - `test_deserialize_verifies_sha`
  - `test_deserialize_extracts_symlinks`
  - `test_deserialize_blocks_path_traversal`
  - `test_deserialize_blocks_truncated_archive`
  - `test_round_trip_100mb_file`
  - `test_serialize_cleanup_on_cancellation`
- `tests/unit/test_core_worktree_providers_local.py` — updated for streaming API
- `tests/unit/test_core_worktree_providers_remote.py` — updated for streaming API

**Mahavishnu (new integration):**
- `tests/integration/test_worktree_round_trip_streaming.py`
  - `test_create_then_fetch_round_trip_100mb` — 100MB worktree, register, fetch on empty base, verify extract
  - `test_create_then_fetch_with_storage_chunked_upload` — verify save_stream actually streams (assert upload_part call count, not single put_object)
  - `test_sha_mismatch_during_streaming_raises_before_extract` — tampered bundle, error raised BEFORE any files extracted

### CI / quality gate

- `pytest --cov=mahavishnu --cov-fail-under=89` (per project pyproject.toml)
- `crackerjack run` clean — no new diagnostics, ty ratchet unchanged
- Pre-commit hook (crackerjack fast_hooks) checks ruff formatting + ty on new files

### What is NOT tested (intentional)

- zstd codec correctness — relies on `zstandard` library's tests
- `tarfile.open(mode="w|zst")` formatting — relies on Python tarfile + zstandard library; we test round-trip only
- Tarfile's `data_filter` itself — Phase 2 already tests this; Phase 3 verifies it still applies for tar.zst

## Definition of done

1. All tests green on the merged branch (pytest + crackerjack)
2. Coverage targets met
3. Crackerjack quality gate passes (no new ERROR/WARNING; ty ratchet unchanged)
4. Integration test `test_create_then_fetch_round_trip_100mb` passes
5. Documentation status updated in ADR §18
6. PRs merged to their target branches per Bodai pre-1.0 policy
7. Existing Phase 2 handles are orphaned (acceptable per design)

## Out of scope (deferred to follow-up ADRs)

- Phase 1.5 / Phase 4 pre-spike (independent)
- Cache TTL tuning after Phase 2 instrumentation
- `BundleTransport` decorator for local provider (ADR §13 Open Question #3)
- Dhara-side MCP tools for worktree handle operations (separate repo)
- zstd level tuning after real workload data is collected
