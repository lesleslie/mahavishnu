# `mahavishnu.core.worktree_providers`

Worktree bundle storage, retrieval, and provider orchestration. This
package owns the Phase 3 streaming `tar.zst` pipeline that replaced
the Phase 2 in-memory `tar.gz` path, plus the provider hierarchy that
plugs the pipeline into the rest of the control plane.

## Table of Contents

1. [Module Structure](#module-structure)
1. [Public API](#public-api)
1. [Internal Architecture](#internal-architecture)
1. [Extension Pattern](#extension-pattern)
1. [Testing Notes](#testing-notes)
1. [Related Modules](#related-modules)

______________________________________________________________________

## Module Structure

| File | Responsibility |
|---|---|
| `base.py` | `WorktreeProvider` abstract base class plus the shared `BackendKind` literal type |
| `types.py` | `WorktreeHandle`, `WorktreeRef`, `WorktreeSpec`, `LocalWorktreeRef`, `S3WorktreeRef` dataclasses |
| `errors.py` | Worktree-domain exceptions (`WorktreeError`, `WorktreeLocked`, `WorktreeIntegrityError`) |
| `storage_io.py` | Streaming `tar.zst` serialize/deserialize — the Phase 3 serde layer |
| `local.py` | `LocalWorktreeProvider` — direct local-filesystem streaming provider |
| `remote.py` | `RemoteWorktreeProvider` — S3/GCS/Azure remote provider with bounded queue handoff |
| `mock.py` | In-process `MockWorktreeProvider` for unit tests |
| `session_buddy.py` | `SessionBuddyWorktreeProvider` — delegates to a Session-Buddy instance |
| `dhara_registry.py` | Dhara-backed registry of worktree handles |
| `registry.py` | Provider factory + capability-based resolver |
| `cache.py` | Worktree cache layer (L1 memory + L2 storage) |
| `lock.py` | Distributed locking on `(repo, branch)` |
| `pre_migrate.py` | Pre-v2 migration discovery helper |

## Public API

### Streaming tar.zst I/O

```python
from contextlib import contextmanager
from pathlib import Path
from mahavishnu.core.worktree_providers.storage_io import (
    serialize_worktree_tar,
    deserialize_worktree_tar,
    MAX_BUNDLE_BYTES_STOPGAP,
)


@contextmanager
def serialize(source: Path) -> Iterator[tuple[Path, int, str]]:
    """Stream `source` directory to a temp ``.tar.zst`` file.

    Yields ``(temp_path, byte_count, sha256)``. The caller is
    responsible for promoting ``temp_path`` to its final location
    once the context exits successfully. Cleanup is unconditional
    on any exception (``BaseException`` covers ``CancelledError``
    and ``KeyboardInterrupt``).
    """


async def deserialize(
    chunk_reader: Callable[[], Iterator[bytes]],
    target: Path,
    *,
    expected_sha256: str | None = None,
    backend: str = "unknown",
    principal_short: str = "unknown",
) -> None:
    """Stream a ``.tar.zst`` payload into ``target``.

    Writes the decompressed bytes to a temp file, verifies the
    SHA-256 against ``expected_sha256`` if provided, extracts the
    tar into a sibling staging directory, then atomically
    ``rename``s the staging directory onto ``target``.
    """
```

### Provider hierarchy

```python
from mahavishnu.core.worktree_providers import WorktreeProvider, WorktreeHandle


class WorktreeProvider(ABC):
    """Abstract worktree provider.

    Concrete providers extend this ABC. They MUST route every
    serialize/deserialize call through ``storage_io`` so the
    bounded queue, integrity verification, and metric emission are
    uniformly applied.
    """

    @abstractmethod
    async def create(self, spec: WorktreeSpec) -> WorktreeHandle: ...

    @abstractmethod
    async def fetch(self, handle: WorktreeRef) -> WorktreeHandle: ...

    @abstractmethod
    async def remove(self, handle: WorktreeRef) -> None: ...
```

### Bounded queue handoff

`RemoteWorktreeProvider.fetch` decouples the slow disk side from the
fast network side via a Python `queue.Queue(maxsize=4)`. The producer
fills chunks from the storage adapter; the consumer drains chunks to
the local staging directory. Memory stays bounded at
`chunk_size × 4` regardless of bundle size.

```python
queue: queue.Queue[bytes | Sentinel] = queue.Queue(maxsize=4)


async def producer() -> None:
    async for chunk in remote_stream:
        queue.put(chunk)  # blocks when queue is full
    queue.put(_SENTINEL)


async def consumer() -> None:
    while True:
        chunk = await loop.run_in_executor(None, queue.get)
        if chunk is _SENTINEL:
            return
        await staging_writer.write(chunk)
```

### `MAX_BUNDLE_BYTES_STOPGAP`

`MAX_BUNDLE_BYTES_STOPGAP = 256 * 1024 * 1024` (256 MiB) defines the
in-memory / temp-file path boundary. Bundles larger than this MUST
route through streaming-aware adapters and the bounded queue. The
constant is exported from `storage_io` so providers, tests, and the
migration script share one source of truth.

## Internal Architecture

The Phase 3 streaming pipeline is composed of three layers:

1. **Provider** (`local.py`, `remote.py`) — owns the orchestration:
   pick a storage adapter, build a streaming reader/writer, call into
   `storage_io` for serde, emit OTel metrics around each op.
1. **Storage I/O** (`storage_io.py`) — pure serde. No awareness of
   which adapter fed it bytes; receives a `chunk_reader` callable
   and yields a streaming file path on serialize. Cleanup is
   unconditional.
1. **Storage adapter** (oneiric `LocalStorageAdapter`,
   `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`)
   — exposes `save_stream` / `load_stream` so the storage I/O layer
   never needs a full blob in memory.

Error propagation: `storage_io` raises `WorktreeError` with one of
the `WORKTREE_BUNDLE_*` `ErrorCode` values (MHV-209..213 + 220..223).
The provider catches, emits the appropriate OTel counter, and either
propagates (programmer / deployment error) or swallow-and-logs
(transient I/O).

## Extension Pattern

To add a new storage backend (for example, an `R2StorageAdapter` over
Cloudflare R2):

1. **Implement the Oneiric adapter.** Add `save_stream` /
   `load_stream` to the adapter class following the Phase 3 contract
   in `oneiric/oneiric/adapters/storage/base.py`. The adapter is
   expected to chunk the payload, call the cloud SDK's multipart
   upload, and abort on any chunk-level failure.
1. **Register the adapter kind.** Add the new kind to
   `BackendKind` (`base.py`). Add the matching label to
   `_ALLOWED_BACKEND_KINDS` in `mahavishnu/observability/bundle_integrity.py`.
1. **Wire it into `registry.py`.** Add a resolver case mapping
   the capability name to the new provider class. The capability
   name follows the `worktree-provider/<kind>` convention.
1. **Cover the metric labels.** Every code path that emits
   `streaming_op_total` must use the new backend kind label.
   CI guard test `tests/unit/test_observability_metrics.py::test_cardinality_budget`
   will reject unknown keys.
1. **Add tests.** Provide both unit tests (mocked adapter) and an
   integration test against the real cloud SDK. Use the
   `emulator` pattern from Phase B.6 if the cloud provider ships a
   local emulator; otherwise use `pytest-httpserver` or
   `moto3`-style mocks.

## Error Codes

| Code | Name | Raised by | Operational signal |
|---|---|---|---|
| MHV-208 | `WORKTREE_INTEGRITY_FAILED` | `verify_sha256_streaming` | Bundle SHA-256 mismatch (corrupt or tampered) |
| MHV-209 | `WORKTREE_BUNDLE_TEMP_CREATE_FAILED` | `storage_io` | `tempfile.mkstemp` OSError |
| MHV-210 | `WORKTREE_BUNDLE_TEMP_WRITE_FAILED` | `storage_io` | Write OSError or CancelledError |
| MHV-211 | `WORKTREE_BUNDLE_PATH_TRAVERSAL` | `storage_io` | `tarfile.data_filter` rejected a member |
| MHV-212 | `WORKTREE_BUNDLE_MALFORMED` | `storage_io` | Corrupt/truncated tar.zst |
| MHV-213 | `WORKTREE_BUNDLE_LEGACY_PHASE2` | provider | Fetch hit a `.tar.gz` Phase 2 handle |
| MHV-220 | `WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG` | provider | S3 1024-byte limit exceeded |
| MHV-221 | `WORKTREE_BUNDLE_STOPGAP_TOO_LARGE` | provider | In-memory path OOM guard tripped |
| MHV-222 | `WORKTREE_BUNDLE_NOT_FOUND` | provider | Storage adapter returned None |
| MHV-223 | `WORKTREE_BUNDLE_CODEC_UNAVAILABLE` | `storage_io` | `zstandard` not installed |

Severity routing for these codes lives in
`docs/runbooks/coordinator-error-severity.md`.

## Testing Notes

- The streaming pipeline is covered by the `tests/integration/`
  suite under the `streaming` marker. CI runs these on every
  release; pre-merge the `mhv-storage-stream` lightweight variant
  is sufficient.
- `MAX_BUNDLE_BYTES_STOPGAP` is referenced from tests so a single
  test sweep catches any change to the 256 MiB cap.
- `LocalStorageAdapter` mock (oneiric side) is sufficient for unit
  tests of `storage_io`. The producer/consumer bounded queue is
  exercised by `tests/unit/test_worktree_providers_remote.py`.
- `data_filter` rejection coverage lives in
  `tests/unit/test_worktree_providers_storage_io.py::test_data_filter_rejection`
  — Phase 2 had no such filter, so the new tests are net-new.

## Related Modules

- `mahavishnu.observability.metrics` — OTel instruments
  (`streaming_op_total`, `bundle_bytes`, `bundle_integrity_failure_total`)
- `mahavishnu.observability.bundle_integrity` — SHA-256 helpers
  (`verify_sha256_streaming`, `compute_sha256`)
- `mahavishnu.core.errors` — `ErrorCode` enum (MHV-200..223)
- `oneiric.adapters.storage.local` / `oneiric.adapters.storage.s3` /
  `oneiric.adapters.storage.gcs` / `oneiric.adapters.storage.azure`
  — backend adapters with `save_stream` / `load_stream`
- `docs/runbooks/streaming-tar-rollout.md` — operator runbook
- `docs/runbooks/coordinator-error-severity.md` — error severity table
- `docs/adr/015-worktree-and-cache-storage-v4.md` — architecture
  decision record
