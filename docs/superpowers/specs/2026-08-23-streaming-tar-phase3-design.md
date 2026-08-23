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

**Rollout note (2026-08-23 review):** because the storage_key suffix
changes from `.tar.gz` to `.tar.zst` and the read-side codec changes
from `r:gz` to `r|zst`, the rollout MUST drain Phase 2 writers
first, then upgrade readers, then upgrade writers. Mixed deployment
windows will see `MHV-212 BUNDLE_MALFORMED` for Phase 2 handles that
Phase 3 readers try to decode as tar.zst. Runbook
`docs/runbooks/worktree-streaming-phase3.md` documents the procedure
and a startup-time sweep that identifies any `.tar.gz` keys remaining
in the storage prefix.

**Cross-repo version coupling (BLOCKER R2-09):** Mahavishnu PR-D pins
`oneiric` to the **exact commit SHA** of Oneiric PR-A landing in main
until Oneiric cuts a release:

```toml
# mahavishnu/pyproject.toml — interim pin (BLOCKER R2-09)
dependencies = [
    "oneiric @ git+https://github.com/lesleslie/oneiric.git@<oneiric_pr_a_commit_sha>",
    ...
]
```

Once Oneiric cuts the next minor (e.g. `0.45.0` containing
`compression.stream`), a follow-up Mahavishnu PR bumps the dependency
to `oneiric>=0.45.0,<0.46.0`. This avoids the "two minors shipped
between PR-A and PR-D" problem (Mahavishnu would otherwise pull in
unrelated changes). Document the selection criterion in
`docs/decisions/oneiric-version-coupling.md` so future Phase 3-class
changes follow the same pattern.

**Streaming actually streams (BLOCKER R2-10):** the spec's "full
streaming path" via `chunks_buffer: list[bytes]` materializes the full
bundle in memory BEFORE `to_thread(deserialize_worktree_tar)` — peak
memory is `O(bundle_size)`, NOT `O(chunk_size)` as claimed. This
defeats the streaming benefit and creates an inconsistency with
`MAX_BUNDLE_BYTES_STOPGAP` (which is checked on the stopgap path but
not on the "full streaming" path). Fix: use a queue-based handoff
between the async-for-loop and the thread:

```python
import asyncio
import queue
from concurrent.futures import ThreadPoolExecutor

async def fetch(self, handle):
    # ...
    storage_key = f"worktrees/{handle.repo}/{handle.branch}/{handle.handle_id}.tar.zst"

    if supports_streaming(self._storage):
        # Phase 2 orphan magic-byte sniff (MHV-213) — see File 4 above.
        first_chunk = await anext(self._storage.read_stream(storage_key))
        if first_chunk[:2] == b"\x1f\x8b":
            raise WorktreeError(...)

        # Bridge: async-for-loop producer feeds a sync queue consumed by
        # the worker thread. Bounded queue enforces backpressure and
        # caps memory at chunk_size × queue_capacity.
        q: queue.Queue[bytes | None] = queue.Queue(maxsize=4)
        async def _produce() -> None:
            async for chunk in self._storage.read_stream(
                storage_key, offset=len(first_chunk), chunk_size=65_536,
            ):
                q.put(chunk)  # blocks if queue full → backpressure
            q.put(None)  # sentinel: end-of-stream
        produce_task = asyncio.create_task(_produce())

        def chunk_reader() -> Iterator[bytes]:
            while True:
                item = q.get()
                if item is None:
                    return
                yield item

        # _validate_stopgap_size applies to the streaming path too —
        # total bytes is unknown until drained, so we estimate via the
        # bundle_size metadata on the handle (Phase 2 stored this).
        estimated_size = handle.bytes_size  # Dhara-registered
        _validate_stopgap_size(estimated_size)  # raises MHV-221 if exceeded

        await asyncio.to_thread(
            deserialize_worktree_tar, chunk_reader, target,
            expected_sha256=handle.sha256, backend="local", principal_short=...,
        )
        await produce_task  # ensure producer finished cleanly
    else:
        # Stopgap: read whole blob into memory. Cap applies.
        blob = await self._storage.read(storage_key)
        _validate_stopgap_size(len(blob))
        # ... rest unchanged ...
```

The `queue.Queue(maxsize=4)` bounds memory at `4 × chunk_size ≈ 256KB`
regardless of bundle size. The `_validate_stopgap_size` applies to
both paths so an oversized bundle fails loudly rather than OOM-ing.
The memory-profile table in this spec is corrected:

| Phase | Before (Phase 2) | After (Phase 3) |
|---|---|---|
| Create (compression peak) | 2.5× bundle_size (~250MB for 100MB worktree) | ~0 (disk is the buffer) |
| Create (upload peak) | bundle_size | bundle_size (stopgap) → O(chunk_size × queue_capacity) ≈ 256KB (full streaming) |
| Fetch (blob load peak) | bundle_size | bundle_size (stopgap) → O(chunk_size × queue_capacity) ≈ 256KB (full streaming) |
| Fetch (extract peak) | 2.5× bundle_size (~250MB) | ~0 (disk is the buffer; staging subdir, then atomic rename) |

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

### Memory profile comparison (corrected after BLOCKER R2-10)

| Phase | Before (Phase 2) | After (Phase 3) |
|---|---|---|
| **Create (compression peak)** | 2.5× bundle_size (~250MB for 100MB worktree) | ~0 (disk is the buffer) |
| **Create (upload peak)** | bundle_size (already in-memory) | bundle_size (stopgap) → O(chunk_size × queue_capacity) ≈ 256KB (full streaming) |
| **Fetch (blob load peak)** | bundle_size | bundle_size (stopgap) → O(chunk_size × queue_capacity) ≈ 256KB (full streaming) |
| **Fetch (extract peak)** | 2.5× bundle_size (~250MB) | ~0 (disk is the buffer; staging subdir, then atomic rename) |

Net: the 250MB peak during compression and the 250MB peak during extract
are eliminated in all configurations. Upload/download peak depends on
whether `save_stream` / `read_stream` are wired (in scope for Phase 3) or
the stopgap `read_bytes` path is used. **BLOCKER R2-10 fix:** the full
streaming path uses a bounded `queue.Queue(maxsize=4)` to bridge the
async-for-loop producer and the worker thread consumer; memory is
bounded at `chunk_size × 4 ≈ 256KB` regardless of bundle size. The
`_validate_stopgap_size` cap applies to both stopgap and streaming paths
so an oversized bundle fails loudly (MHV-221) rather than OOM-ing.

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

Add `requires-python = ">=3.14"` (BLOCKER R2-08 — `tarfile.data_filter` is
only stable in 3.14; 3.11/3.10 install paths get cryptic `AttributeError`).

Add `zstandard>=0.23.0` (BLOCKER R2-13 — 0.21.0 has a known
`chunked_stream_decompress` bug yielding one extra empty chunk after
frame EOF on fragmented input; bumped to current stable for the
streaming-fetch path that fragments at chunk boundaries).

**Add PEP 735 optional dependency group** (BLOCKER R2-07 — CLAUDE.md
explicitly enumerates PEP 735 for large/narrow deps; `zstandard` is a
~500KB C extension requiring native compilation):

```toml
[dependency-groups]
compression-zstd = ["zstandard>=0.23.0"]
# existing groups preserved: ai, gpu, content-ingest, storage-pg
```

`dev` includes `compression-zstd` (matching the existing 4-group pattern
documented in CLAUDE.md). Production deployments that do not use
streaming compression omit the group; the runtime code raises a clear
`LifecycleError("zstandard not installed. Install with: uv sync --group compression-zstd")`
matching the existing wrapper convention in `content_ingester.py`.

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
            try:
                import zstandard
            except ImportError as exc:
                # BLOCKER R2-15: tarfile uses its own lazy-import path that
                # surfaces as tarfile.CompressionError. This action-kit path
                # uses an explicit import — wrap ImportError as LifecycleError
                # so callers get a consistent error envelope.
                raise LifecycleError(
                    "zstandard dependency required for zstd algorithm; "
                    "install with `uv sync --group compression-zstd`"
                ) from exc
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
            try:
                import zstandard
            except ImportError as exc:
                raise LifecycleError(
                    "zstandard dependency required for zstd algorithm; "
                    "install with `uv sync --group compression-zstd`"
                ) from exc
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

**File 4: `docs/action-kits.md`** — append a new entry. **Note (BLOCKER R2-14):**
the Oneiric resolver selects candidates by `priority` then `stack_level`,
NOT by entry order in `builtin_action_metadata()`. The alphabetical
ordering note is a docs-file hint for human readers, not a resolver
mechanism. Spec writers must NOT try to control resolution by editing
return order.

**Priority selection rationale (BLOCKER R2-14):** existing
`CompressionAction` has `priority=450`, `HashAction` has `priority=445`.
Phase 3's `StreamingCompressionAction` is `priority=448`. Order in
resolver: `CompressionAction` (450) > `StreamingCompressionAction` (448) >
`HashAction` (445). Callers requesting `mode=compress` on a generic
action-kit dispatch get `CompressionAction` (higher priority), preserving
existing Phase 1+2 callers. Callers explicitly requesting
`compression.stream` get the new streaming action. This is the intent;
a future maintainer bumping `StreamingCompressionAction.priority` above
450 would silently route Phase 1+2 callers to the streaming action
(which has different semantics — bytes-in/bytes-out vs iterator-in),
breaking them. Document this as a constant in the spec.

**File 5: `oneiric/adapters/storage/{local,s3,gcs,azure}.py`** — add two
methods to each adapter. The existing `save` and `read` stay (backward
compat for all current callers).

**Async consistency (all four adapters, `async def`, `AsyncIterator[bytes]`):**
S3 / GCS / Azure are natively async (their existing `save`/`read` are
`async def` with `asyncio.to_thread` for blocking I/O). LocalStorageAdapter's
existing `save`/`read` are also `async def`. To avoid `hasattr` checks having
to also distinguish sync-vs-async method shapes, the new streaming methods
are uniformly `async def` accepting `AsyncIterator[bytes]`. LocalStorageAdapter
internally wraps the async iterator via `async for chunk in chunks:` over an
async generator. The stream-consumer side in `mahavishnu/core/worktree_providers/local.py`
runs in `asyncio.to_thread` and consumes via a small async-to-sync drain.

```python
# All four adapters (uniform async signature)
async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> int:
    """Stream chunks to storage. Returns total bytes written.
    On partial failure, aborts the in-flight multipart upload (S3) to
    prevent orphan parts (see S3 abort note in File 5b)."""

async def read_stream(
    self, key: str, *, offset: int = 0, chunk_size: int = 65_536
) -> AsyncIterator[bytes]:
    """Yield storage object body chunks via range-aware read."""

# LocalStorageAdapter implementation (sync IO behind async wrapper):
async def save_stream(self, key, chunks):
    path = self._base_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(path, "wb") as f:
        async for chunk in chunks:
            f.write(chunk)
            written += len(chunk)
    return written

async def read_stream(self, key, *, offset=0, chunk_size=65_536):
    path = self._base_path / key
    if not path.exists():
        return
    with open(path, "rb") as f:
        if offset:
            f.seek(offset)
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
```

**File 5b: S3 multipart abort on failure (BLOCKER fix):**
S3 multipart upload lifecycle MUST be aborted on partial failure to
prevent orphan parts (default 7-day retention, S3 cost accrual).
`S3StorageAdapter.save_stream` wraps the upload in:

```python
try:
    upload_id = await self._client.create_multipart_upload(...)
    parts = []
    async for chunk in chunks:
        part = await self._client.upload_part(...)
        parts.append(part)
    await self._client.complete_multipart_upload(upload_id, parts)
except BaseException:  # includes CancelledError
    await self._client.abort_multipart_upload(upload_id)
    raise
```

`abort_multipart_upload` is added as a new method on `S3StorageAdapter`.
Operator defense-in-depth: S3 bucket lifecycle rule should auto-abort
multipart uploads older than 24h (standard practice).

**File 6: `oneiric/tests/actions/test_stream_compression_action.py`** (new).

**File 7: `oneiric/tests/adapters/storage/test_local_stream.py`** (new).

**File 8: `oneiric/tests/adapters/storage/test_s3_stream.py`** (new, uses
`moto.mock_aws`).

**File 8b: `oneiric/tests/adapters/storage/test_gcs_stream.py`** + `test_azure_blob_stream.py`
(new, mirror S3 streaming tests — required to meet the ≥90% coverage target
on `oneiric/adapters/storage/{local,s3,gcs,azure}.py`). Uses `gcp-storage-emulator`
Docker container + `pytest-gcs-emulator` plugin (GCS) and Azurite Docker +
`pytest-azurite` plugin (Azure) — see R2-12 emulator strategy below.
**Do NOT** use `@mock_gcs` or `@mock_azure` decorators — neither exists
in the standard SDKs; community mock packages (`google-cloud-test-utils`,
`azure-storage-blob-mock`) are unreliable and not in the project's dev
deps. The emulator-Docker approach is reproducible across CI runs.

### Mahavishnu

**File 1: `pyproject.toml`** — add `requires-python = ">=3.14"` (BLOCKER R2-08).

Add `zstandard>=0.23.0` via the `compression-zstd` PEP 735 group
(inherited from Oneiric — BLOCKER R2-07). The group is declared in
Oneiric's `pyproject.toml` and pulled transitively into Mahavishnu via
the `dev` include group. A clean install that omits `compression-zstd`
hits `tarfile.CompressionError("Unable to locate decompressor for 'zst' format")`
on first worktree create — wrapped as MHV-223 WORKTREE_BUNDLE_CODEC_UNAVAILABLE
with install hint (added below).

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
from contextlib import contextmanager
from pathlib import Path
import tarfile
import tempfile
from typing import Callable, Iterator


@contextmanager
def serialize_worktree_tar(path: Path) -> Iterator[tuple[Path, int, str]]:
    """Tar + zstd-compress ``path`` into a temp file as a context manager.

    Yields ``(temp_path, byte_size, sha256)``. The temp file is
    auto-unlinked on context exit (success or exception), including on
    ``asyncio.CancelledError`` (which is a ``BaseException`` in Python
    3.8+, not caught by ``except Exception``).

    The temp file outlives the context — callers can stream it to a
    storage adapter AFTER exiting the context IF they have copied the
    bytes. For Phase 3's streaming flow, callers enter the context,
    read the yielded temp file in chunks, then exit (which unlinks).
    This eliminates the manual-unlink footgun of the Phase 2 tuple
    return signature.

    Memory peak during compression: ~0 (disk is the buffer).
    Memory peak during hash: O(chunk_size) where chunk_size = 65_536.
    """
    fd, name = tempfile.mkstemp(suffix=".tar.zst", prefix="worktree-")
    os.close(fd)
    temp_path = Path(name)
    try:
        with tarfile.open(temp_path, mode="w|zst") as tar:
            tar.add(str(path), arcname=".", recursive=True)
        hasher = hashlib.sha256()
        bytes_written = 0
        with open(temp_path, "rb") as f:
            while chunk := f.read(65_536):
                hasher.update(chunk)
                bytes_written += len(chunk)
        yield temp_path, bytes_written, hasher.hexdigest()
    except BaseException:
        # Catches asyncio.CancelledError + KeyboardInterrupt + SystemExit.
        # Phase 2's `except Exception` silently skipped CancelledError,
        # leaking the temp file until /tmp cleanup. Use BaseException here.
        temp_path.unlink(missing_ok=True)
        raise


def deserialize_worktree_tar(
    chunk_reader: Callable[[], Iterator[bytes]],
    target: Path,
    *,
    expected_sha256: str,
    backend: str,
    principal_short: str,
) -> None:
    """Stream chunks from ``chunk_reader`` → temp file + hash → verify SHA → extract.

    Args:
        chunk_reader: ``() -> Iterator[bytes]`` — sync chunk iterator that yields
            the full bundle bytes. The previous spec signature took
            ``(offset, chunk_size)`` parameters; these were vestigial (only
            ever called with ``(0, 65_536)``) and have been removed in this
            revision. The chunk_size for the storage adapter is configured on
            the adapter side (default 65_536), not negotiated per-call.
            Caller provides an adapter or a closure over an in-memory blob.
        target: Destination directory. Created (parents included) if missing.
        expected_sha256: SHA-256 expected after streaming-hash. Raises
            ``WorktreeIntegrityError`` on mismatch (which emits the
            ``bundle_integrity_failure_total{backend, principal_short}`` OTel
            counter via the shared observability helper — NOT inlined).
        backend: Storage backend identifier (``"local"`` / ``"s3"`` / ``"gcs"``
            / ``"azure"``). Forwarded to ``bundle_integrity.verify_sha256_streaming``.
        principal_short: 8-char truncated principal hash. Full uid only in Dhara
            audit log (cardinality protection per Phase 2 §17).

    Memory peak: O(chunk_size) during read+hash; ~0 during extract.

    On any failure (CancelledError, OSError, SHA mismatch, tarfile read error,
    extract error, path-traversal rejection) the temp file is unlinked via
    finally and the partial target directory (if this function created it
    fresh) is removed via shutil.rmtree.

    CancelledError handling: ``asyncio.CancelledError`` is a ``BaseException``
    subclass in Python 3.8+, NOT caught by ``except Exception``. The temp
    file MUST be cleaned before re-raising. The implementation uses
    ``except (OSError, ValueError, asyncio.CancelledError)`` so cancellation
    surfaces with a wrapped MHV-210 error_code (for log dispatchers that key
    on error_code) BEFORE the cancellation propagates.
    """
    import asyncio
    import shutil
    from mahavishnu.core.errors import (
        ErrorCode,
        WorktreeError,
    )
    from mahavishnu.observability.bundle_integrity import verify_sha256_streaming

    target.mkdir(parents=True, exist_ok=True)
    target_was_created = not any(target.iterdir()) if target.exists() else True
    fd, name = tempfile.mkstemp(suffix=".tar.zst", prefix="worktree-")
    os.close(fd)
    temp_path = Path(name)
    try:
        hasher = hashlib.sha256()
        try:
            with open(temp_path, "wb") as f:
                for chunk in chunk_reader():
                    f.write(chunk)
                    hasher.update(chunk)
        except (OSError, ValueError, asyncio.CancelledError) as exc:
            raise WorktreeError(
                f"Failed to stream bundle into temp file: {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_TEMP_WRITE_FAILED,
            ) from exc
        actual_sha = hasher.hexdigest()
        # Shared observability helper — emits bundle_integrity_failure_total
        # counter on mismatch (preserves Phase 2 SLO dashboard) and uses
        # 8-char principal_short truncation (cardinality protection).
        verify_sha256_streaming(
            actual_sha, expected_sha256, backend=backend, principal_short=principal_short
        )
        # Extract to staging subdir then atomic-rename for failure-isolation.
        staging = target / f".extract-staging-{os.getpid()}"
        try:
            with tarfile.open(temp_path, mode="r|zst") as tar:
                tar.extractall(staging, filter=tarfile.data_filter)
        except tarfile.OutsideDestinationError as exc:
            raise WorktreeError(
                f"Bundle contains path-traversal member (rejected by data_filter): {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_PATH_TRAVERSAL,
            ) from exc
        except (tarfile.TarError, OSError) as exc:
            # OSError catches ENOSPC / EACCES / EMFILE / EPERM mid-extract.
            # Roll back partial staging dir BEFORE raising.
            shutil.rmtree(staging, ignore_errors=True)
            raise WorktreeError(
                f"Bundle extract failed: {exc}",
                error_code=ErrorCode.WORKTREE_BUNDLE_MALFORMED,
            ) from exc
        # Atomic promote: rename staging → target. If target had pre-existing
        # content (rare, defensive), staging contents win; target old content
        # is preserved under target / ".extract-staging-{pid}.superseded"
        # for operator inspection (NOT auto-deleted).
        if target.exists() and any(target.iterdir()):
            backup = target / f".extract-staging-{os.getpid()}.superseded"
            target.rename(backup)
        staging.rename(target)
    except BaseException:
        # Catches asyncio.CancelledError AND any non-Exception BaseException
        # (KeyboardInterrupt, SystemExit). Temp + staging must be cleaned.
        if "staging" in locals() and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def compute_sha256(blob: bytes) -> str:
    """Return hex SHA-256 digest of ``blob``. Kept for backward compat with
    callers that have small in-memory bundles; large bundles should use the
    streaming-hash pattern in ``serialize_worktree_tar``.
    """
    return hashlib.sha256(blob).hexdigest()
```

**File 3: `mahavishnu/core/errors.py`** — add five new error codes:

```python
WORKTREE_BUNDLE_TEMP_CREATE_FAILED = "MHV-209"  # mkstemp OSError
WORKTREE_BUNDLE_TEMP_WRITE_FAILED = "MHV-210"   # write OSError or CancelledError
WORKTREE_BUNDLE_PATH_TRAVERSAL = "MHV-211"      # data_filter rejects member
WORKTREE_BUNDLE_MALFORMED = "MHV-212"           # corrupt/truncated tar.zst
WORKTREE_BUNDLE_LEGACY_PHASE2 = "MHV-213"       # fetch hit a .tar.gz Phase 2 handle
WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG = "MHV-220"  # S3 1024-byte limit
WORKTREE_BUNDLE_STOPGAP_TOO_LARGE = "MHV-221"     # in-memory path OOM guard
WORKTREE_BUNDLE_NOT_FOUND = "MHV-222"             # storage adapter returned None
WORKTREE_BUNDLE_CODEC_UNAVAILABLE = "MHV-223"     # zstandard not installed; tarfile CompressionError
```

**Code table (full, with gaps reserved):**
- `MHV-200`–`MHV-207` — Phase 1 + Phase 2 (cache, lock, registry)
- `MHV-208` — Phase 2 (`WORKTREE_INTEGRITY_FAILED` — SHA mismatch)
- `MHV-209`–`MHV-213` — Phase 3 (streaming bundle lifecycle)
- `MHV-220`–`MHV-223` — Phase 3 (storage-key validation, stopgap OOM guard, not-found, codec unavailable)
- `MHV-214`–`MHV-219`, `MHV-224`+ — reserved for Phase 4 (encryption-at-rest, multipart abort, etc.)

**File 3b: `mahavishnu/observability/bundle_integrity.py`** — add
`verify_sha256_streaming` (sibling to existing `verify_sha256`):

```python
def verify_sha256_streaming(
    actual_sha: str,
    expected_sha: str,
    *,
    backend: str,
    principal_short: str,
) -> None:
    """Compare streamed-hash to expected, raise WorktreeIntegrityError on mismatch.

    Same observability contract as ``verify_sha256`` — emits the
    ``bundle_integrity_failure_total{backend, principal_short}`` OTel counter
    on mismatch and uses 8-char principal_short truncation (Phase 2 §17
    cardinality protection). Full principal uid stays in Dhara audit log.

    Phase 3's ``deserialize_worktree_tar`` calls this with the streamed-hash
    result, eliminating the parallel verify_sha256 implementation and the
    risk of observability drift between Phase 2's blob API and Phase 3's
    stream API.
    """
```

The existing `verify_sha256(blob, expected, *, backend, principal)` stays
for Phase 2 callers. A thin wrapper composes them:

```python
def verify_sha256(blob: bytes, expected: str, *, backend: str, principal) -> None:
    principal_short = principal.uid[:8] if hasattr(principal, 'uid') else principal[:8]
    verify_sha256_streaming(
        hashlib.sha256(blob).hexdigest(), expected,
        backend=backend, principal_short=principal_short,
    )
```

**File 4: `mahavishnu/core/worktree_providers/local.py`** — `create_worktree_handle`
+ `fetch` updated. Uses capability-aware dispatch (NOT `hasattr`):

```python
async def create_worktree_handle(self, repo, branch, base_ref, principal):
    # ... (steps 1-3 unchanged) ...
    handle_id = uuid.uuid4().hex  # Phase 2's handle_id was deterministic;
                                  # Phase 3 switches to UUID4 to eliminate
                                  # concurrent-create races on the same
                                  # storage key (see Risky handle_id below).
    storage_key = f"worktrees/{repo}/{branch}/{handle_id}.tar.zst"
    # Validate storage key length up front (S3 max 1024 bytes).
    if len(storage_key) > 1024:
        raise WorktreeError(
            f"storage_key exceeds S3 1024-byte limit: {len(storage_key)}",
            error_code=ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG,  # MHV-220
        )
    if supports_streaming(self._storage):
        # Full streaming path. Context manager auto-unlinks temp on exception.
        async with serialize_worktree_tar(wt_path) as (temp_path, byte_size, sha):
            # Drain the async chunk iterator to a sync iterator BEFORE entering
            # to_thread — to_thread cannot await. We pre-buffer via a generator
            # that reads the temp file synchronously, decoupling storage async
            # from the chunk_reader sync contract.
            def _chunks() -> Iterator[bytes]:
                with open(temp_path, "rb") as f:
                    while chunk := f.read(65_536):
                        yield chunk
            # Async adapter accepts AsyncIterator, so wrap the sync generator
            # in an async generator. NOTE: the sync generator is drained by
            # the consumer's `async for` loop, NOT inside to_thread.
            async def _async_chunks() -> AsyncIterator[bytes]:
                for chunk in _chunks():
                    yield chunk
            await self._storage.save_stream(storage_key, _async_chunks())
        # record_bundle_bytes happens AFTER successful upload so the metric
        # reflects what was actually persisted.
        record_bundle_bytes(repo=repo, byte_size=byte_size, sha256=sha)
    else:
        # Stopgap: bytes-in-memory upload. Explicit memory cap documented.
        async with serialize_worktree_tar(wt_path) as (temp_path, byte_size, sha):
            blob = temp_path.read_bytes()
            if sys.getsizeof(blob) > MAX_BUNDLE_BYTES_STOPGAP:
                # Stopgap is documented as "bundle_size ≤ available RAM".
                # Phase 3 raises if stopgap would OOM; full streaming path
                # is the only path that handles bundles > available RAM.
                raise WorktreeError(
                    f"Stopgap path cannot handle bundle of {byte_size} bytes "
                    f"(exceeds MAX_BUNDLE_BYTES_STOPGAP={MAX_BUNDLE_BYTES_STOPGAP}); "
                    f"storage adapter {type(self._storage).__name__} does not "
                    f"support streaming",
                    error_code=ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE,  # MHV-221
                )
            await self._storage.save(storage_key, blob)
        record_bundle_bytes(repo=repo, byte_size=byte_size, sha256=sha)
    # ... handle construction + dhara register + metric (unchanged) ...

async def fetch(self, handle):
    # ... cache check unchanged ...
    storage_key = f"worktrees/{handle.repo}/{handle.branch}/{handle.handle_id}.tar.zst"

    # Phase 2 → Phase 3 migration guard: detect orphan legacy bundle
    # before invoking the streaming path. The read_stream returns the
    # first chunk; we sniff the gzip magic bytes (1f 8b) and raise
    # MHV-213 instead of decoding garbage as tar.zst.
    if supports_streaming(self._storage):
        first_chunk = await anext(self._storage.read_stream(storage_key))
        if first_chunk[:2] == b"\x1f\x8b":
            raise WorktreeError(
                f"Storage key {storage_key} is a Phase 2 tar.gz bundle "
                f"(no backward compat per Phase 3 design). Handle "
                f"{handle.handle_id} is orphaned.",
                error_code=ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2,  # MHV-213
            )

        async def _read() -> AsyncIterator[bytes]:
            yield first_chunk  # include the chunk we already pulled
            async for chunk in self._storage.read_stream(
                storage_key, offset=len(first_chunk), chunk_size=65_536
            ):
                yield chunk

        # Pre-drain the async iterator to a sync iterator before to_thread.
        # Consumer side needs a sync chunk_reader because deserialize runs
        # in to_thread and cannot await.
        chunks_buffer: list[bytes] = []
        async for chunk in _read():
            chunks_buffer.append(chunk)

        def chunk_reader() -> Iterator[bytes]:
            yield from chunks_buffer  # single iteration — caller takes all chunks at once
    else:
        # Stopgap: read whole blob, yield once
        blob = await self._storage.read(storage_key)
        if blob is None:
            raise WorktreeError(
                f"No storage blob for handle {handle.handle_id}",
                error_code=ErrorCode.WORKTREE_BUNDLE_NOT_FOUND,  # MHV-222
            )
        if blob[:2] == b"\x1f\x8b":
            raise WorktreeError(
                f"Phase 2 tar.gz bundle orphan (handle {handle.handle_id})",
                error_code=ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2,
            )

        def chunk_reader() -> Iterator[bytes]:
            yield blob

    target = get_worktree_base_path() / handle.handle_id
    await asyncio.to_thread(
        deserialize_worktree_tar, chunk_reader, target,
        expected_sha256=handle.sha256,
        backend="local",
        principal_short=principal.uid[:8] if hasattr(principal, "uid") else principal[:8],
    )
    # ... cache set + metric unchanged ...
```

**`supports_streaming` helper (capability-aware dispatch, NOT hasattr):**

```python
def supports_streaming(storage) -> bool:
    """Return True iff the storage adapter advertises the 'stream' capability
    AND exposes ``save_stream`` / ``read_stream`` methods with the right shape.

    Oneiric's AdapterMetadata.capabilities is the source of truth — but we
    ALSO check for method presence (defensive: a custom adapter could
    declare the capability without implementing the methods).
    """
    capabilities = getattr(getattr(storage, "metadata", None), "capabilities", [])
    has_methods = hasattr(storage, "save_stream") and hasattr(storage, "read_stream")
    return "stream" in capabilities and has_methods
```

Note on stopgap memory claim: the spec table previously said
"bundle_size → ~0" for the full-streaming row. Corrected in this
revision to "bundle_size (stopgap) → O(chunk_size) ≈ 65KB (full streaming)".
The ~0 framing was the marketing claim, not the measured reality.

**Risky handle_id (BLOCKER fix):** Phase 2's `handle_id` was deterministic
on `(repo, branch, base_ref)`. Two concurrent creates for the same tuple
produced the same `handle_id`, racing on the storage upload and clobbering
each other. Phase 3 switches `handle_id` to `uuid.uuid4().hex` — no
collision risk. Cache keys (`materialized:{handle.handle_id}`) and storage
keys both pick up the new UUID.

Note: the streaming read path runs the synchronous tarfile read+extract in
`asyncio.to_thread` to avoid blocking the event loop. The 100MB extract
takes ~0.5-2s on modern hardware.

**`_sync_async_iter` is NOT needed** — the previous spec referenced an
undefined helper. The pre-drain-to-list pattern above replaces it. The
list lives in memory at peak (`O(bundle_size)` for the stopgap path, but
the streaming path uses fixed-size `read_stream` chunks; if a stopgap path
is taken, the in-memory peak is the bundle — explicit `MAX_BUNDLE_BYTES_STOPGAP`
cap raises MHV-221 if exceeded).

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

## Phase 2 caller migration (BLOCKER fixes)

The signature changes to `serialize_worktree_tar` (now a context manager)
and `deserialize_worktree_tar` (new kwargs + Callable shape) break every
existing Phase 2 call site. The spec enumerates them explicitly so the
implementer doesn't ship a runtime crash.

### Caller inventory

| File:line | Phase 2 call | Phase 3 replacement |
|---|---|---|
| `mahavishnu/core/worktree_providers/local.py:356` | `blob = serialize_worktree_tar(wt_path)` | `async with serialize_worktree_tar(wt_path) as (temp_path, byte_size, sha): ...` |
| `mahavishnu/core/worktree_providers/local.py:476` | `deserialize_worktree_tar(blob, target)` | `await asyncio.to_thread(deserialize_worktree_tar, chunk_reader, target, expected_sha256=handle.sha256, backend="local", principal_short=...)` (chunk_reader wraps `iter([blob])` for the legacy stopgap) |
| `mahavishnu/core/worktree_providers/remote.py:265` | `blob = serialize_worktree_tar(Path(repo))` | `async with serialize_worktree_tar(Path(repo)) as (temp_path, byte_size, sha): ...` |
| `mahavishnu/core/worktree_providers/remote.py:393` | `deserialize_worktree_tar(blob, target_dir)` | Same pattern as local.py:476 with `backend="s3"` |
| `mahavishnu/core/worktree_providers/remote.py:354` | `cache_key = f"{handle.handle_id}:materialized"` | `cache_key = f"materialized:{handle.handle_id}"` (unify with local.py shape — was inconsistent in Phase 2) |
| `tests/unit/test_core_worktree_providers_storage_io.py:41,49,58,67,100` | 5 Phase 2 tests assign `blob = serialize_worktree_tar(...)` | **DELETE** these 5 tests before/alongside the rewrite. New tests use the context-manager form. The spec's "Test files" section lists new test names; old names must NOT coexist. |

### `verify_sha256_streaming` full body (BLOCKER R2-19)

The Phase 2 `verify_sha256` enforces `backend in ALLOWED_BACKEND_KINDS` to
guard OTel label cardinality. Phase 3's streaming helper MUST mirror this:

```python
def verify_sha256_streaming(
    actual_sha: str,
    expected_sha: str,
    *,
    backend: str,
    principal_short: str,
) -> None:
    if backend not in ALLOWED_BACKEND_KINDS:  # frozenset({"local","s3","gcs","azure","bundle"})
        raise ValueError(f"backend {backend!r} not in ALLOWED_BACKEND_KINDS")
    # Principal_short is already 8 chars from the caller; do NOT re-hash.
    if actual_sha == expected_sha:
        return
    record_bundle_integrity_failure(backend=backend, principal_short=principal_short)
    _bundle_integrity_failure_logger.warning(
        "bundle integrity mismatch",
        extra={
            "error_code": "MHV-208",
            "backend": backend,
            "principal_short": principal_short,
            "expected_sha_prefix8": expected_sha[:8],
            "actual_sha_prefix8": actual_sha[:8],
        },
    )
    # Dhara audit row (forensic chain-of-custody; full uid via audit row).
    write_dhara_audit_row(
        kind="bundle_integrity_failure",
        backend=backend,
        principal_short=principal_short,
        expected_sha_prefix8=expected_sha[:8],
        actual_sha_prefix8=actual_sha[:8],
    )
    raise WorktreeIntegrityError(
        f"SHA-256 mismatch: expected={expected_sha!r}, actual={actual_sha!r}",
        error_code=ErrorCode.WORKTREE_INTEGRITY_FAILED,
    )
```

`record_bundle_integrity_failure` is the existing Phase 2 helper that
calls `_short_principal(name)` internally. Since the new helper receives
an already-8-char `principal_short`, callers MUST call the metric
recording path that **does not re-hash** (a new `record_bundle_integrity_failure_short`
helper or inline `_bundle_integrity_failure_counter.add(1, ...)`).
Phase 2's `verify_sha256(blob, expected, *, backend, principal)` becomes
a thin wrapper:

```python
def verify_sha256(blob: bytes, expected_sha: str, *, backend: str, principal) -> None:
    principal_short = _short_principal(principal.name if hasattr(principal, "name") else str(principal))
    verify_sha256_streaming(
        hashlib.sha256(blob).hexdigest(), expected_sha,
        backend=backend, principal_short=principal_short,
    )
```

`_short_principal` (existing in `observability/metrics.py`) returns
`sha256(name.encode("utf-8")).hexdigest()[:8]` — NOT `name[:8]`. The
literal-slice form would collapse distinct principals into the same
8-char bucket (e.g., `alice@acme.com` and `alice@acme2.com` both map
to `alice@ac`).

### `MAX_BUNDLE_BYTES_STOPGAP` definition (BLOCKER R2-21)

```python
# mahavishnu/core/worktree_providers/storage_io.py
MAX_BUNDLE_BYTES_STOPGAP: int = 256 * 1024 * 1024  # 256MB
```

Phase 2's cap was implicit (no explicit limit; OOM at bundle_size).
Phase 3 makes it explicit and raises MHV-221 STOPGAP_TOO_LARGE before
OOM. The `to_thread` chunk_reader path also applies this cap — without
it, the pre-drain `chunks_buffer: list[bytes]` materializes the full
bundle in memory, defeating the streaming benefit (BLOCKER R2-10).

```python
def _validate_stopgap_size(byte_size: int) -> None:
    if byte_size > MAX_BUNDLE_BYTES_STOPGAP:
        raise WorktreeError(
            f"Bundle of {byte_size} bytes exceeds MAX_BUNDLE_BYTES_STOPGAP "
            f"({MAX_BUNDLE_BYTES_STOPGAP}); storage adapter does not support streaming.",
            error_code=ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE,  # MHV-221
        )
```

Use `len(blob)`, not `sys.getsizeof(blob)` — `getsizeof` includes
Python object overhead (~33 bytes for empty `bytes`) and is not the
canonical bundle byte count.

## Observability additions for Phase 3 (BLOCKER fixes)

### Phase 3 op enum (BLOCKER R2-06)

| Op value | Emitted by | When |
|---|---|---|
| `create` | local.py + remote.py | Successful streaming create |
| `create_stopgap` | local.py + remote.py | Stopgap in-memory path used (no `save_stream`) |
| `create_s3_multipart_aborted` | remote.py | S3 multipart upload aborted mid-flight |
| `create_codec_unavailable` | local.py + remote.py | zstandard missing at tarfile call |
| `fetch` | local.py + remote.py | Successful streaming fetch |
| `fetch_legacy_guard_hit` | local.py + remote.py | Migration guard detected Phase 2 tar.gz bundle (MHV-213) |
| `fetch_sha_mismatch` | local.py + remote.py | Streaming SHA mismatch (MHV-208) |
| `remove_handle` | local.py + remote.py | Successful handle removal |
| `invalidate_handle` | local.py + remote.py | Cache invalidation |

Existing Phase 2 op values (`lock`, `unlock`, `health`) remain. The
Phase 3 enum is **additive** — dashboards keyed on a fixed op set
should re-derive their filter list.

### New OTel counters (BLOCKER R2-01, R2-02)

| Counter | Labels | Emitted on |
|---|---|---|
| `s3_multipart_abort_total{backend, reason, principal_short}` | backend + reason (`cancelled\|exception\|timeout`) + 8-char principal | S3 multipart upload aborted (with byte-uploaded-before-abort as an explicit attribute on the span, not a label) |
| `s3_multipart_cost_events_total{principal_short}` | 8-char principal | One event per successful `complete_multipart_upload` (cost-attribution accounting) |
| `bundle_integrity_failure_total` (existing) | backend + 8-char principal | Preserved; emit from `verify_sha256_streaming` directly |
| `streaming_codec_unavailable_total{algorithm}` | algorithm (`zstd\|gzip`) | tarfile's lazy codec lookup fails (zstandard not installed) |

### `bundle_bytes` histogram bucket fix (BLOCKER R2-05)

Phase 2's histogram ended at `104857100` (≈99.99MB), pushing all ≥100MB
bundles into the `+Inf` bucket. Phase 3's purpose is supporting >100MB
bundles; the histogram must have dedicated percentiles for the
streaming-enabled size class:

```python
bundle_bytes_histogram = meter.create_histogram(
    name="mahavishnu_bundle_bytes",
    unit="By",
    explicit_bucket_boundaries=[
        1024,           # 1 KB
        10240,          # 10 KB
        102400,         # 100 KB
        1048576,        # 1 MB
        10485760,       # 10 MB
        52428800,       # 50 MB
        104857600,      # 100 MB
        209715200,      # 200 MB
        524288000,      # 500 MB
        1073741824,     # 1 GB
    ],
)
```

### Health probe for streaming capability (BLOCKER R2-03)

`LocalWorktreeProvider.health()` and `RemoteWorktreeProvider.health()` MUST
verify streaming capability, not just legacy `save`/`read`:

```python
async def health(self) -> HealthReport:
    report = await super().health()
    if not supports_streaming(self._storage):
        report.add_warning(
            kind="streaming_capability_missing",
            message=f"Storage adapter {type(self._storage).__name__} lacks save_stream/read_stream; "
                    f"stopgap path will be used (max bundle size {MAX_BUNDLE_BYTES_STOPGAP // (1024*1024)}MB)",
        )
    return report
```

A deployment missing streaming capability surfaces as a `HealthReport`
warning, not a silent degradation. The runbook includes "streaming
probe failed → fall back to stopgap + page primary on-call" as a
triage item.

### Trace context propagation across `to_thread` (NICE-TO-HAVE)

`asyncio.to_thread(deserialize_worktree_tar, ...)` does NOT propagate
the asyncio context by default. Without explicit propagation, the
worker thread's OTel spans are orphaned from the parent `fetch` span.

```python
import contextvars
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def fetch(self, handle):
    # ... cache check ...
    with tracer.start_as_current_span("fetch.deserialize_worktree_tar"):
        await asyncio.to_thread(
            deserialize_worktree_tar, chunk_reader, target,
            expected_sha256=handle.sha256,
            backend="local",
            principal_short=principal_short,
        )
```

The `start_as_current_span` wraps the thread call; the span context
propagates via `contextvars.copy_context()` (Python 3.12+).
Operators investigating fetch latency see the full trace tree.

### Structured logging contract per error path (NICE-TO-HAVE)

| Error code | Required fields | Log level |
|---|---|---|
| `MHV-209` | `error_code, handle_id, backend, principal_short, mkstemp_errno` | ERROR |
| `MHV-210` | `error_code, handle_id, backend, principal_short, byte_size, temp_path_pattern="worktree-*.tar.zst", exception_type` | ERROR |
| `MHV-211` | `error_code, handle_id, backend, principal_short, member_name` | ERROR |
| `MHV-212` | `error_code, handle_id, backend, principal_short, zstd_error_offset` (if zstandard) | ERROR |
| `MHV-213` | `error_code, handle_id, storage_key, first_2_bytes_hex="1f8b", detected_format="tar.gz"` | WARN |
| `MHV-220` | `error_code, handle_id, repo, branch, storage_key, key_length, s3_limit=1024` | ERROR |
| `MHV-221` | `error_code, handle_id, byte_size, max_stopgap_bytes, storage_adapter_class` | ERROR |
| `MHV-222` | `error_code, handle_id, storage_key` | ERROR |

The `record_worktree_error(error_code, **fields)` helper enforces this
shape across all error raise sites.

### Concurrent-create semaphore (NICE-TO-HAVE)

Phase 3's streaming path holds a temp file (up to bundle_size) per
in-flight create. No upper bound exists; a 100-burst of 100MB creates
= 10GB `/tmp` reservation. Pin a semaphore:

```python
# mahavishnu/core/worktree_providers/local.py
MAX_CONCURRENT_WORKTREE_STREAMS: int = 8

class LocalWorktreeProvider:
    def __init__(self, ...) -> None:
        ...
        self._stream_semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKTREE_STREAMS)

    async def create_worktree_handle(self, ...):
        async with self._stream_semaphore:
            ...
```

`health()` surfaces the semaphore's current value (`_stream_semaphore._value`)
as a metric so operators can see saturation.

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
  to temp file (disk full, IO error), OR `asyncio.CancelledError` mid-write.
- `WORKTREE_BUNDLE_PATH_TRAVERSAL (MHV-211)` — `tarfile.data_filter`
  rejects a member with `..` in path OR an absolute-path symlink OR a
  device file / FIFO. Phase 2 tests already cover the `..` case; Phase 3
  extends to absolute symlinks, BLKTYPE, CHRTYPE, FIFOTYPE.
- `WORKTREE_BUNDLE_MALFORMED (MHV-212)` — corrupted/truncated tar.zst
  archive (zstd decoder corruption OR mid-extract OSError). Tests:
  flip zstd magic bytes (header corruption), flip byte in compressed
  payload (decoder corruption), trigger ENOSPC mid-extract.
- `WORKTREE_BUNDLE_LEGACY_PHASE2 (MHV-213)` — fetch hit a `.tar.gz`
  bundle (Phase 2 orphan). Storage adapter returns gzip magic bytes
  (`1f 8b`); migration guard raises this instead of decoding garbage
  as tar.zst. Operator-facing message names the orphan handle.
- `WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG (MHV-220)` — composite storage key
  exceeds S3 1024-byte limit (raised at handle construction, before
  upload). Reused for "no storage blob" 404 cases.
- `WORKTREE_BUNDLE_STOPGAP_TOO_LARGE (MHV-221)` — stopgap upload path
  cannot handle a bundle that exceeds `MAX_BUNDLE_BYTES_STOPGAP`
  (default: 256MB). Indicates storage adapter is missing `stream`
  capability AND bundle is too large for in-memory stopgap.

**Cleanup contracts:**
- `serialize_worktree_tar` is a context manager — auto-unlinks temp on
  exit including on `asyncio.CancelledError` (which is `BaseException`,
  caught explicitly by `except BaseException:`).
- `deserialize_worktree_tar` cleans up its own temp file in `finally`,
  including on CancelledError. Partial-extract staging directory is
  removed via `shutil.rmtree` in the `except (TarError, OSError)`
  branch before raising.
- The atomic-promote pattern (extract to staging, then rename) ensures
  the target directory is never observed in a partial state. If a
  pre-existing target dir is encountered (rare, defensive), it is
  preserved as `.extract-staging-{pid}.superseded` for inspection.
- On `CancelledError` mid-`deserialize`: temp file unlinked via
  finally, partial staging dir unlinked via `except BaseException`,
  exception re-raised with original CancelledError chain.

**Behavior change vs Phase 2 (operator-facing):**
Phase 2's `tar.extractall(target)` used the default tar filter (no
filter), which preserved setuid/setgid bits and device nodes from the
source worktree. Phase 3 uses `tarfile.data_filter` (Python 3.12+),
which strips setuid/setgid bits and rejects device nodes / FIFOs. This
is a security improvement (defense against malicious bundles) but a
behavior change for legitimate worktrees containing setuid binaries
(uncommon in practice — most worktrees don't contain setuid git hooks).
If preservation is required, file a follow-up ADR for a custom filter.
Documented in the runbook.

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
| `mahavishnu/core/worktree_providers/storage_io.py` | 100% | Critical correctness (compression + integrity). MHV-209 + MHV-210 have explicit OSError-injection tests (see test list). |
| `mahavishnu/observability/bundle_integrity.py` (streaming helper) | 100% | `verify_sha256_streaming` emits the same metric + truncation contract as the existing `verify_sha256`. |
| `oneiric/actions/compression.py` (StreamingCompressionAction only) | 100% | Public action kit surface |
| `oneiric/adapters/storage/{local,s3,gcs,azure}.py` (streaming methods only) | ≥90% | New methods. **All four adapters have explicit streaming test files** (local + s3 + gcs + azure) so the target is reachable. |
| `mahavishnu/core/worktree_providers/local.py` (streaming paths in create/fetch) | ≥85% | Phase 2 already covers cache/storage paths |
| `mahavishnu/core/worktree_providers/remote.py` (streaming paths) | ≥85% | Same. **Test names listed explicitly** in the test-files section below — the target is enforceable, not aspirational. |

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
  - `test_s3_save_stream_aborts_multipart_on_partial_failure` — assert `abort_multipart_upload` called
  - `test_s3_save_stream_aborts_multipart_on_cancelled_error` — `asyncio.CancelledError` injection
  - `test_s3_read_stream_returns_chunks`
  - `test_s3_read_stream_offset_resume`
- `oneiric/tests/adapters/storage/test_gcs_stream.py` (uses `gcp-storage-emulator` Docker + `pytest-gcs-emulator` plugin — see Block R2-12 fix below)
  - `test_gcs_save_stream_chunked_upload`
  - `test_gcs_save_stream_cleans_up_on_failure`
  - `test_gcs_read_stream_yields_chunks`
- `oneiric/tests/adapters/storage/test_azure_blob_stream.py` (uses Azurite Docker + `pytest-azurite` plugin — R2-12 fix)
  - `test_azure_save_stream_chunked_upload`
  - `test_azure_save_stream_cleans_up_on_failure`
  - `test_azure_read_stream_yields_chunks`

**`zstandard` CI availability:** `zstandard>=0.23.0` is added to both Oneiric
and Mahavishnu via the `compression-zstd` PEP 735 group. The `[tool.pytest]`
test suite uses `pytest.fail(...)` (NOT `pytest.importorskip` — see
BLOCKER R2-11) at the top of `test_stream_compression_action.py` and
`test_core_worktree_providers_storage_io.py` to fail fast on missing
installs rather than producing cryptic tarfile errors OR silently
green-skipping the streaming tests. The dev group includes
`compression-zstd` so test runs pull the dep.

**BLOCKER R2-11 — `importorskip` does not match the spec's intent:**
`pytest.importorskip("zstandard")` SKIPS the test (returns as PASSED in
the suite) when the dep is missing. A missing `zstandard` would
silently turn the streaming tests into green skips, and `crackerjack`'s
coverage gate (`--cov-fail-under=89`) would still pass because skipped
tests don't count against coverage. The spec's intent ("fail fast on
missing installs") does NOT match the mechanism (silently pass when
missing).

```python
# tests/unit/test_core_worktree_providers_storage_io.py
try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.fail(
        "zstandard required for Phase 3 tar.zst streaming; "
        "install with `uv sync --group compression-zstd`",
        pytrace=False,
    )
```

**Mahavishnu (rewritten):**
- `tests/unit/test_core_worktree_providers_storage_io.py`
  - `test_serialize_returns_temp_path_size_sha`
  - `test_serialize_temp_cleaned_on_tarfile_error`
  - `test_serialize_chunked_hash_matches_full_hash`
  - `test_serialize_cleanup_on_cancellation` — uses `asyncio.CancelledError`
    injected at `tarfile.open`; asserts temp file no longer exists after
  - `test_serialize_cleanup_on_keyboard_interrupt` — also BaseException subclass
  - `test_deserialize_extracts_content`
  - `test_deserialize_verifies_sha` — also asserts temp file unlinked via finally
  - `test_deserialize_blocks_path_traversal` (`../../etc/passwd`)
  - `test_deserialize_blocks_absolute_symlink` (NEW — security regression coverage)
  - `test_deserialize_blocks_symlink_chain_outside_target` (NEW)
  - `test_deserialize_blocks_device_files` (NEW — `BLKTYPE`, `CHRTYPE` rejected)
  - `test_deserialize_blocks_fifo` (NEW — `FIFOTYPE` rejected)
  - `test_deserialize_blocks_truncated_archive` (flip mid-payload byte)
  - `test_deserialize_blocks_zstd_corrupt_header` (NEW — flip zstd magic bytes)
  - `test_deserialize_blocks_zstd_corrupt_payload` (NEW — flip byte in compressed payload)
  - `test_deserialize_cleans_temp_on_chunk_reader_runtime_error` (NEW — narrow except clause regression)
  - `test_deserialize_cleans_temp_on_cancelled_error` (NEW)
  - `test_serialize_temp_create_oserror_wrapped` (NEW — MHV-209)
  - `test_deserialize_temp_write_oserror_wrapped` (NEW — MHV-210)
  - `test_round_trip_100mb_file`
  - `test_round_trip_at_size_boundary` (NEW — parametrized 0, 1, 1024, 99MB, 101MB)
  - `test_serialize_empty_worktree_round_trips` (NEW — empty dir)
  - `test_serialize_round_trip_preserves_non_utf8_filename` (NEW)
  - `test_chunk_reader_contract` (NEW — assert (offset, chunk_size) honored,
    byte-for-byte equality, StopIteration clean, exhausted reader raises
    StopIteration not returns empty)
- `tests/unit/test_core_worktree_providers_local.py` — updated for streaming API
  - `test_create_uses_save_stream_when_available`
  - `test_create_falls_back_to_stopgap_when_no_stream_capability`
  - `test_create_stopgap_raises_mhv221_on_oversized_bundle`
  - `test_fetch_uses_read_stream_when_available`
  - `test_fetch_sha_mismatch_raises_before_extract` — asserts no files in `target`
  - `test_fetch_cache_hit_skips_streaming`
  - `test_fetch_phase2_targz_handle_raises_mhv213` (NEW — migration regression)
  - `test_fetch_migration_guard_does_not_swallow_gzip_magic` (NEW)
  - `test_supports_streaming_checks_capabilities_not_just_methods` (NEW)
  - `test_supports_streaming_advertises_but_does_not_implement_returns_false` (NEW — adapter claims `"stream"` in metadata.capabilities but does not implement `save_stream`/`read_stream`; helper MUST return False to avoid crashing call site — covers the Phase 2 `LocalStorageAdapter.metadata.capabilities` "advertised-but-staged" state)
- `tests/unit/test_core_worktree_providers_remote.py` — updated for streaming API
  - `test_remote_create_uses_save_stream_when_available` (NEW — named for coverage)
  - `test_remote_create_falls_back_to_stopgap_when_no_save_stream` (NEW)
  - `test_remote_create_uses_uuid4_handle_id_not_deterministic` (NEW)
  - `test_remote_create_storage_key_too_long_raises_mhv220` (NEW)
  - `test_remote_create_s3_multipart_aborted_on_partial_failure` (NEW — assert
    `abort_multipart_upload` called via moto call count)
  - `test_remote_fetch_uses_read_stream_when_available` (NEW)
  - `test_remote_fetch_sha_mismatch_raises_before_extract` (NEW)
  - `test_remote_fetch_cache_hit_skips_streaming` (NEW)
  - `test_remote_fetch_phase2_orphan_raises_mhv213` (NEW)
- `tests/unit/test_core_worktree_providers_storage_io.py::test_concurrent_create_same_handle_id_does_not_clobber` (NEW — asyncio.gather N tasks, assert all handle_ids unique, all S3 keys unique)
- `tests/unit/test_core_worktree_providers_storage_io.py::test_concurrent_fetch_and_remove_handle_is_safe` (NEW)
- `tests/unit/test_observability_bundle_integrity_streaming.py` (NEW — for `verify_sha256_streaming`)
  - `test_verify_sha256_streaming_emits_metric_on_mismatch` (asserts `bundle_integrity_failure_total` counter increments)
  - `test_verify_sha256_streaming_uses_principal_short_truncation` (asserts label value is 8 chars)
  - `test_verify_sha256_streaming_cardinality_allowlist_rejects_unknown_label_key` (asserts backend typo raises)
  - `test_verify_sha256_blob_wrapper_delegates_to_streaming` (Phase 2 ABI preserved)

**Mahavishnu (new integration):**
- `tests/integration/test_worktree_round_trip_streaming.py`
  - `@pytest.mark.integration @pytest.mark.slow` on all tests below
  - `test_create_then_fetch_round_trip_100mb` — 100MB worktree, register, fetch on empty base, verify extract
  - `test_create_then_fetch_with_storage_chunked_upload` — verify save_stream actually streams (assert `upload_part` call count > 1, not single `put_object`)
  - `test_sha_mismatch_during_streaming_raises_before_extract` — tampered bundle, error raised BEFORE any files extracted
  - Marker convention: skipped in CI without Redis via `pytest.skip("integration: requires Redis + moto")` at module load

### CI / quality gate

- `pytest --cov=mahavishnu --cov-fail-under=89` (per project pyproject.toml). Excludes integration tests via `-m "not integration"`.
- `pytest -m integration` — integration suite, run on demand or in dedicated CI lane.
- `crackerjack run` clean — no new diagnostics, ty ratchet unchanged
- Pre-commit hook (crackerjack fast_hooks) checks ruff formatting + ty on new files
- `pytest.fail(...)` (NOT `importorskip`) at top of storage_io + streaming-compression tests prevents cryptic failures if zstandard is missing — `importorskip` silently green-skips, defeating the coverage gate (BLOCKER R2-11)

### What is NOT tested (intentional)

- zstd codec correctness — relies on `zstandard` library's tests
- `tarfile.open(mode="w|zst")` formatting — relies on Python tarfile + zstandard library; we test round-trip only
- Tarfile's `data_filter` itself — Phase 2 already tests this; Phase 3 verifies it still applies for tar.zst (plus the additional absolute-symlink + device-file + FIFO cases via explicit tests)

## Definition of done

1. All tests green on the merged branch (pytest + crackerjack). New test files use `pytest.fail(...)` at module top to gate on `zstandard` presence (NOT `pytest.importorskip` — see BLOCKER R2-11). The PEP 735 `compression-zstd` group is included in `dev` so test runs pull the dep.
2. Coverage targets met per the table above; MHV-209 + MHV-210 have explicit tests (storage_io 100% is enforceable).
3. Crackerjack quality gate passes (no new ERROR/WARNING; ty ratchet unchanged).
4. Integration test `test_create_then_fetch_round_trip_100mb` passes against `moto.mock_aws` + `fakeredis`.
5. `docs/adr/015-worktree-and-cache-storage-v4.md` §18 status updated to "Phase 3 shipped" with link to commits.
6. **NEW:** `docs/runbooks/worktree-streaming-phase3.md` written — covers: (a) startup-time migration sweep to detect legacy `.tar.gz` keys; (b) MHV-209..MHV-213 + MHV-220..MHV-222 error code triage table; (c) rollback procedure (revert Phase 3 commits; no schema migration); (d) operator's S3 lifecycle rule verification (multipart upload auto-abort at 24h); (e) **SLO/SLI targets** with concrete numbers — `fetch` P99 < 5s for 100MB bundle, `bundle_integrity_failure_total` rate < 0.01% of fetches, `create_worktree_handle` P99 < 10s for 100MB bundle; (f) **PromQL alert queries** wired to PagerDuty — `mahavishnu_worktree_op_duration_seconds{op="fetch", quantile="0.99"} > 5`, `rate(mahavishnu_bundle_integrity_failure_total[5m]) / rate(mahavishnu_worktree_op_duration_seconds_count{op="fetch"}[5m]) > 0.0001`, `rate(mahavishnu_s3_multipart_abort_total[5m]) > 0`; (g) **capacity planning** — `/tmp` headroom = `bundle_size × concurrent_creates × 1.5 (safety_factor)`; (h) **on-call escalation matrix** with primary / secondary / manager; (i) **postmortem template** for streaming-path incidents.
7. **NEW:** `mahavishnu/core/worktree_providers/README.md` created — documents the new `serialize_worktree_tar` context-manager API, the chunk_reader contract, error codes, and the rollout guard (Phase 2 → Phase 3 migration).
8. **NEW:** Oneiric `CHANGELOG.md` entry — `compression.stream` kit + storage adapter `save_stream` / `read_stream` are additive public surface changes; bump Oneiric minor version per semver.
9. **NEW:** Mahavishnu `CHANGELOG.md` entry — cross-link from Oneiric's entry.
10. PRs merged to their target branches per Bodai pre-1.0 policy. Oneiric main first; Mahavishnu PR-D pins `oneiric` to the exact commit SHA of Oneiric PR-A (BLOCKER R2-09) via `oneiric @ git+https://...@<sha>` in `pyproject.toml`, then a follow-up PR bumps to `oneiric>=X.Y.Z` once Oneiric cuts the next minor.
11. Existing Phase 2 handles are orphaned; MHV-213 error path tested explicitly.

## Out of scope (deferred to follow-up ADRs)

- Phase 1.5 / Phase 4 pre-spike (independent)
- Cache TTL tuning after Phase 2 instrumentation
- `BundleTransport` decorator for local provider (ADR §13 Open Question #3)
- Dhara-side MCP tools for worktree handle operations (separate repo)
- zstd level tuning after real workload data is collected
- Encryption-at-rest for bundle blobs (would land in MHV-214+ range)
- `data_filter` permission-stripping behavior change vs Phase 2 (Phase 2 used
  default no-filter for production; Phase 3 silently applies `data_filter`
  which strips setuid/setgid bits. Documented as a behavior change in the
  runbook. If permission preservation is needed, file a follow-up ADR for
  a custom tar filter.)
