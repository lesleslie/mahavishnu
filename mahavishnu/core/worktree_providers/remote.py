"""Remote (cloud-backed) worktree provider (ADR 015 v4 §13).

Wraps any of Oneiric's cloud storage adapters (S3, GCS, Azure Blob)
to provide a WorktreeHandle-based interface for non-local worktrees.

This is the v4-era primary cloud provider. The legacy sync ABC
methods are preserved (raising ``NotImplementedError``) so callers
on the v1 dict-based API keep their existing failure mode.

Renamed from ``S3WorktreeProvider`` in Phase 1 (ADR 015 v4 §13) to
reflect that the provider is backend-agnostic (it dispatches through
whichever Oneiric storage adapter the deployment configures).

Backend dispatch is keyed off the handle's ``storage_ref.backend_kind``
*and* the ``backend`` label passed at construction (so OTel metrics
carry an unambiguous backend identity even before the handle exists,
e.g. for create-time metrics).

Phase 3 (ADR 015 v4): ``RemoteWorktreeProvider.create_worktree_handle``
and ``fetch`` are rewritten to use the streaming tar.zst storage_io
contract (Task C.7 — mirror of LocalWorktreeProvider's C.6 rewrite).
Bundle create persists via ``storage.save_stream``; fetch drains
``storage.load_stream`` through a bounded ``queue.Queue(maxsize=4)``
producer-consumer handoff to keep peak memory bounded under
streaming. Legacy gzip (.tar.gz) bundles are rejected with
``WORKTREE_BUNDLE_LEGACY_PHASE2`` (MHV-213).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256 as _sha256_hash
import logging
from pathlib import Path
import queue
import threading
import time
from typing import TYPE_CHECKING, Any, Literal
import uuid

if TYPE_CHECKING:
    from mahavishnu.auth import Principal
    from mahavishnu.core.worktree_providers.cache import WorktreeCache

from mahavishnu.core.paths import (
    get_worktree_base_path,
    get_worktree_path,
)
from mahavishnu.core.worktree_providers.dhara_registry import (
    register_handles,
)
from mahavishnu.core.worktree_providers.dhara_registry import (
    remove_handle as dhara_remove_handle,
)
from mahavishnu.core.worktree_providers.local import (
    _create_worktree_via_git,
    _remove_worktree_via_git,
    _validate_path_component,
)
from mahavishnu.core.worktree_providers.storage_io import (
    MAX_BUNDLE_BYTES_STOPGAP,
    deserialize_worktree_tar,
    serialize_worktree_tar,
)
from mahavishnu.observability.metrics import (
    record_cache_invalidation,
    record_worktree_op,
)

from .base import WorktreeProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from oneiric.adapters.storage.azure import AzureBlobStorageAdapter
    from oneiric.adapters.storage.gcs import GCSStorageAdapter
    from oneiric.adapters.storage.s3 import S3StorageAdapter

    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.worktree_providers.types import WorktreeHandle, WorktreeRef

# ``collections.abc`` is in the stdlib so a runtime import is safe
# even when the type-checker narrows the alias to a TYPE_CHECKING
# import — both names resolve to ``collections.abc.Callable`` at
# runtime.
from collections.abc import Callable, Iterator  # noqa: E402,F401

# ``.types`` is a leaf module (no outbound runtime deps on the
# provider packages) so importing it eagerly here is safe and lets
# helper methods declare ``handle: WorktreeHandle`` parameters
# without ``TYPE_CHECKING``-string-quote workarounds.
from .types import (  # noqa: E402  (runtime import after TYPE_CHECKING)
    WorktreeHandle,  # noqa: F401
    WorktreeRef,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants + helpers (Phase 3 Task C.7 — mirror of local.py)
# ---------------------------------------------------------------------------

# Default bucket name when the storage adapter doesn't carry one. The
# adapter's ``settings.bucket`` is the canonical source where available
# (S3/GCS), so this fallback is mostly relevant for unusual deployments.
_DEFAULT_BUCKET = "mahavishnu-worktrees"

# Storage-key cap (S3 1024 bytes; we use 256 as a conservative Phase 3
# cap matching the plan spec so a misconfigured key fails fast).
_STORAGE_KEY_MAX_BYTES: int = 256

# Maximum number of concurrent streaming fetches (Phase 3 PR-C B-DI-09).
# Bounded so a single client cannot exhaust the worker's memory by
# opening many streaming fetches in parallel. 8 is the documented
# value from the plan; tests assert the constant shape.
MAX_CONCURRENT_WORKTREE_STREAMS: int = 8

# Module-level asyncio semaphore used by ``RemoteWorktreeProvider.fetch``
# to enforce the concurrency cap. The semaphore is process-global so
# sibling fetch coroutines cooperate across awaits.
_fetch_stream_semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKTREE_STREAMS)


def supports_streaming(storage: Any) -> bool:
    """Return True iff ``storage`` advertises AND implements stream APIs.

    B-DI-04: capability + method check (both). An adapter that
    advertises ``"stream"`` in ``metadata.capabilities`` but does NOT
    implement ``save_stream`` / ``load_stream`` should return False
    so the stopgap path is used (per the storage_io contract; the
    oneiric S3/GCS/Azure adapters always implement both per
    oneiric PR-A).
    """
    if storage is None:
        return False
    capabilities = getattr(getattr(storage, "metadata", None), "capabilities", [])
    has_methods = hasattr(storage, "save_stream") and hasattr(storage, "load_stream")
    return "stream" in capabilities and has_methods


def _principal_short(principal: Any) -> str:
    """Hash a principal to the 8-char OTel label suffix.

    Mirrors ``mahavishnu.observability.metrics._short_principal`` so the
    fetch path can pass the pre-computed label into
    ``verify_sha256_streaming`` without re-hashing.
    """
    name = getattr(principal, "name", None) or (
        principal if isinstance(principal, str) else "unknown"
    )
    if not name:
        return "anon"
    return _sha256_hash(str(name).encode("utf-8")).hexdigest()[:8]


@dataclass
class HealthReport:
    """Lightweight health probe result for ``RemoteWorktreeProvider``.

    Mirrors the :class:`LocalWorktreeProvider.HealthReport` shape so
    callers can treat both providers uniformly. ``__bool__`` returns
    ``True`` when no warnings are present and no probe failed;
    warnings (e.g. ``streaming_capability_missing``) flip it to
    ``False``.
    """

    healthy: bool = True
    warnings: list[dict[str, str]] = field(default_factory=list)

    def add_warning(self, *, kind: str, message: str) -> None:
        self.warnings.append({"kind": kind, "message": message})

    def __bool__(self) -> bool:
        return self.healthy and not self.warnings


# Unique sentinel used by the bounded-queue producer to signal
# end-of-stream without colliding with valid empty-bytes payloads.
_STREAM_SENTINEL: object = object()


def _producer_thread_target(
    thread: threading.Thread,
    stream_iter: Any,
    q: queue.Queue[bytes | object],
) -> None:
    """Drain ``stream_iter`` into ``q``; enqueue ``_STREAM_SENTINEL`` on exit.

    Designed to be run on a daemon thread so the consumer (which runs
    on the event-loop thread) can pull chunks with bounded back-pressure
    (the queue is ``maxsize=4``). On any exception inside the iterator,
    the ``finally`` block guarantees ``_STREAM_SENTINEL`` lands in the
    queue so the consumer can always make progress.

    The exception (if any) is stashed on the ``thread`` object via
    ``thread._producer_error`` so the consumer's
    ``producer.join(timeout=...)`` can re-raise — without this handoff
    the consumer would silently treat a truncated stream as end-of-data
    and validate the SHA over partial bytes (silent data corruption).
    """
    error: BaseException | None = None
    try:
        try:
            for chunk in stream_iter:
                q.put(chunk)
        except BaseException as exc:
            error = exc
            raise
    finally:
        q.put(_STREAM_SENTINEL)
        # Attach the captured error AFTER the sentinel so the consumer
        # is guaranteed to see end-of-stream before raising. The
        # attribute is ``_producer_error`` so external callers cannot
        # accidentally trip it; it is read inside ``fetch``.
        thread._producer_error = error  # type: ignore[attr-defined]


class RemoteWorktreeProvider(WorktreeProvider):
    """v4-era cloud-backed worktree provider.

    Wraps a Oneiric storage adapter (S3, GCS, Azure Blob) and the
    Dhara-backed worktree registry. The ``backend`` label passed at
    construction is the canonical OTel/audit label (also baked into
    ``RemoteWorktreeRef.backend_kind`` for downstream code).

    Storage dispatch is keyed off the handle's ``storage_ref.backend_kind``
    — there is no provider-level "kind" attribute on the handle. One
    provider instance can serve multiple buckets / backends if each
    handle carries its own storage_ref (multi-tenant deployments).
    """

    def __init__(
        self,
        *,
        storage: S3StorageAdapter | GCSStorageAdapter | AzureBlobStorageAdapter,
        cache: WorktreeCache,
        backend: Literal["local", "s3", "gcs", "azure", "bundle"] = "s3",
        dhara_client: Any | None = None,
        settings: MahavishnuSettings | None = None,
        local_provider: Any | None = None,
    ) -> None:
        if storage is None:
            raise ValueError("RemoteWorktreeProvider requires a storage adapter")
        if cache is None:
            raise ValueError("RemoteWorktreeProvider requires a WorktreeCache")
        self._storage = storage
        self._cache = cache
        self._backend = backend
        self._dhara_client = dhara_client
        self._settings = settings
        self._local_provider = local_provider

    # ------------------------------------------------------------------
    # v1 ABC surface — preserved as Phase-5-deprecation stubs.
    # ------------------------------------------------------------------

    def provider_name(self) -> str:
        return "RemoteWorktreeProvider"

    def health_check(self) -> bool:
        # Synchronous ``health_check`` is the v1 ABC surface; we don't
        # have an async bridge here so we surface the last-known
        # storage health, defaulting to False (matches the v1
        # contract). Callers should prefer ``health()`` (async, v4)
        # which actually probes the storage adapter.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return False

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 provider; use "
            "LocalWorktreeProvider or SessionBuddyWorktreeProvider "
            "for legacy sync worktree operations."
        )

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError("RemoteWorktreeProvider is a v4 provider.")

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError("RemoteWorktreeProvider is a v4 provider.")

    # ------------------------------------------------------------------
    # v4 WorktreeHandle-based interface (async) — Phase 3 streaming
    # ------------------------------------------------------------------

    async def create_worktree_handle(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal: Principal,
    ) -> WorktreeHandle:
        """Create a WorktreeHandle backed by streaming tar.zst upload.

        Phase 3 (Task C.7) implementation — mirrors
        ``LocalWorktreeProvider.create_worktree_handle`` (Task C.6):

        1. Materialize a transient worktree directory via
           ``git worktree add`` so the serializer has something to read.
        2. Build the canonical storage key from
           ``repo / branch / handle_id``.
        3. Validate storage-key length (MHV-220) — must happen BEFORE
           any heavy IO.
        4. ``serialize_worktree_tar`` context manager yields
           ``(temp_path, byte_count, sha256)``.
        5. Validate the bundle size against
           ``MAX_BUNDLE_BYTES_STOPGAP`` (MHV-221).
        6. ``storage.save_stream`` streams the compressed bytes to the
           cloud backend with ``sha256``, ``size``, ``principal``
           metadata.
        7. Register the WorktreeHandle in Dhara via
           ``dhara_registry.register_handles``.
        8. Emit ``streaming_op`` (SERIALIZE) + ``worktree_op`` (create)
           metrics with ``success=True`` on success, ``success=False``
           on any exception.
        """
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        # Imports inside the function body mirror LocalWorktreeProvider
        # so tests can ``monkeypatch.setattr`` the source module without
        # fighting captured references (``from ... import`` at module
        # level would capture the original function object).
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_bundle_bytes,
            record_streaming_op,
            record_worktree_op,
        )

        from .types import RemoteWorktreeRef, WorktreeHandle

        handle_id = uuid.uuid4().hex
        bucket = self._resolve_bucket()
        storage_key = self._build_key(repo, branch, handle_id)
        backend_kind = self._backend

        # Storage-key validation (MHV-220) — must happen BEFORE any
        # heavy IO so a misconfigured key fails fast.
        if len(storage_key) > _STORAGE_KEY_MAX_BYTES:
            raise WorktreeError(
                f"Storage key too long ({len(storage_key)} > "
                f"{_STORAGE_KEY_MAX_BYTES}): {storage_key!r}",
                error_code=ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG,
            )

        # Materialize the transient worktree dir on disk first so the
        # serializer has source files. The branch is created if it
        # doesn't exist (matches LocalWorktreeProvider's create_branch=True).
        # ``repo`` and ``branch`` are joined into a filesystem path;
        # reject values containing ``/``, ``\``, ``..`` or starting
        # with ``-`` so a malicious caller cannot escape the worktree
        # base (security review finding).
        _validate_path_component(repo, kind="repo")
        _validate_path_component(branch, kind="branch")
        wt_path = get_worktree_path(repo, branch)
        wt_path.mkdir(parents=True, exist_ok=True)
        await _create_worktree_via_git(
            "git",
            Path(repo),
            branch,
            wt_path,
            create_branch=True,
        )

        start = time.monotonic()
        try:
            # Serialize the worktree to a tar.zst temp file (Phase 3
            # context-manager contract). The context manager cleans up
            # the temp file on any exception (including BaseException).
            with serialize_worktree_tar(wt_path) as (temp_path, size, sha256):
                # Stopgap size guard (MHV-221) — bundles above
                # MAX_BUNDLE_BYTES_STOPGAP must use a streaming-only
                # storage backend; we surface this as a clear error
                # rather than silently OOM.
                if size > MAX_BUNDLE_BYTES_STOPGAP:
                    raise WorktreeError(
                        f"Bundle size {size} exceeds stopgap cap {MAX_BUNDLE_BYTES_STOPGAP}",
                        error_code=ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE,
                    )

                record_bundle_bytes(repo=repo, byte_size=size)

                save_stream = getattr(self._storage, "save_stream", None)
                if save_stream is None:
                    raise WorktreeError(
                        f"Storage adapter {type(self._storage).__name__} "
                        f"does not implement save_stream; cannot persist "
                        f"Phase 3 tar.zst bundle",
                        error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
                    )

                # Save_stream is async on S3/GCS/Azure adapters per
                # oneiric PR-A. ``chunk_reader()`` returns the (single)
                # compressed bytes chunk for the stopgap path; for
                # true streaming uploads the chunk_reader would yield
                # multiple chunks and ``save_stream`` would issue
                # multipart uploads.
                result = save_stream(
                    storage_key,
                    lambda: iter([temp_path.read_bytes()]),
                    metadata={
                        "sha256": sha256,
                        "size": str(size),
                        "principal": principal.name,
                    },
                )
                if asyncio.iscoroutine(result):
                    await result

                record_streaming_op(
                    StreamingOp.SERIALIZE,
                    backend_kind,
                    duration_ms=(time.monotonic() - start) * 1000.0,
                    bytes_processed=size,
                    success=True,
                )

            handle = WorktreeHandle(
                handle_id=handle_id,
                principal=principal,
                repo=repo,
                branch=branch,
                base_ref=base_ref,
                created_at=datetime.now(UTC),
                storage_ref=RemoteWorktreeRef(
                    bucket=bucket,
                    key=storage_key,
                    worktree_id=handle_id,
                    backend_kind=backend_kind,  # type: ignore[arg-type]
                ),
                sha256=sha256,
                bytes_size=size,
                cleanup_policy=None,
                provenance="v4",
            )

            if self._dhara_client is not None:
                await register_handles(self._dhara_client, [handle], caller=principal)

            record_worktree_op(
                backend=backend_kind,
                op="create",
                duration_seconds=time.monotonic() - start,
                success=True,
                principal=principal.name,
            )
            return handle
        except Exception:
            record_worktree_op(
                backend=backend_kind,
                op="create",
                duration_seconds=time.monotonic() - start,
                success=False,
                principal=principal.name,
            )
            raise

    async def fetch(self, handle: WorktreeHandle) -> WorktreeRef:
        """Cache-aside read with SHA-256 verification (§3, §6).

        Phase 3 (Task C.7) implementation — true bounded-queue
        producer/consumer handoff:

        1. Try cache for the materialized path.
        2. On miss: drain ``storage.load_stream`` through a bounded
           ``queue.Queue(maxsize=4)`` producer (daemon thread) and a
           consumer (``deserialize_worktree_tar`` running on the
           event-loop thread). The bounded queue keeps peak memory at
           ``chunk_size * 4`` even when network bandwidth vastly
           exceeds disk throughput.
        3. Gzip magic sniff (MHV-213) on the first chunk.
        4. Codec unavailability (MHV-223) surfaces as a clear
           ``WorktreeError`` rather than a generic ImportError.
        5. MHV-222 (NOT_FOUND) when ``storage.load_stream`` raises a
           storage-side "missing key" error.
        """
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_streaming_op,
        )

        from .types import LocalWorktreeRef, RemoteWorktreeRef

        self._validate_remote_handle(handle)
        ref: RemoteWorktreeRef = handle.storage_ref
        backend_kind = ref.backend_kind

        start = time.monotonic()
        cache_key = f"materialized:{handle.handle_id}"

        # 1. Cache hit path
        cached = await self._try_remote_cache_hit(cache_key, handle, start, backend_kind)
        if cached is not None:
            return cached

        # 2. Cache miss path: streaming download + verify + extract + cache.
        try:
            self._ensure_codec_available()
            self._ensure_storage_supports_load_stream()

            chunk_reader_callable = self._open_storage_chunk_reader(ref.key)
            stream_iter = self._invoke_chunk_reader(chunk_reader_callable, ref.key)

            # Bounded semaphore — cap concurrent streaming fetches to
            # MAX_CONCURRENT_WORKTREE_STREAMS so a single client cannot
            # exhaust worker memory.
            async with _fetch_stream_semaphore:
                q, producer = self._start_stream_producer(stream_iter)
                first_chunk = self._consume_first_chunk(q, ref.key)
                self._reject_legacy_gzip_magic(first_chunk, producer)

                target = self._resolve_materialized_path_for_handle(handle)
                target.parent.mkdir(parents=True, exist_ok=True)
                from .storage_io import deserialize_worktree_tar

                compressed_bytes_total = self._drain_queue_into_target(
                    deserialize_worktree_tar,
                    q,
                    first_chunk,
                    target,
                    handle,
                    backend_kind,
                )
                producer.join(timeout=30.0)
                # Surface any mid-stream failure the producer thread
                # stashed on itself (security review finding). Without
                # this re-raise, a truncated stream would be treated
                # as a successful EOF and the SHA would validate over
                # fewer bytes than ``handle.bytes_size`` (silent
                # corruption).
                producer_error = getattr(producer, "_producer_error", None)
                if producer_error is not None:
                    raise producer_error
                # Validate the compressed byte count against the
                # recorded handle size. A mismatch means the iterator
                # returned fewer chunks than expected (silent
                # truncation) — even if SHA matched, the bytes would
                # not be the full payload.
                if compressed_bytes_total != handle.bytes_size:
                    raise WorktreeError(
                        f"Compressed bundle size mismatch: got "
                        f"{compressed_bytes_total}, expected "
                        f"{handle.bytes_size}",
                        error_code=ErrorCode.WORKTREE_BUNDLE_MALFORMED,
                    )

            self._record_successful_deserialize(start, backend_kind, handle.bytes_size)
            await self._cache.set(cache_key, str(target))
            self._record_fetch_outcome(
                start, backend_kind, success=True, handle=handle
            )
            return LocalWorktreeRef(
                path=target,
                worktree_id=handle.handle_id,
            )
        except Exception:
            self._record_fetch_outcome(
                start, backend_kind, success=False, handle=handle
            )
            raise

    @staticmethod
    def _validate_remote_handle(handle: WorktreeHandle) -> None:
        """Reject handles whose ``storage_ref`` is not a ``RemoteWorktreeRef``."""
        from .types import RemoteWorktreeRef

        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            raise NotImplementedError(
                "RemoteWorktreeProvider.fetch expects a RemoteWorktreeRef; "
                f"got {type(handle.storage_ref).__name__}"
            )

    async def _try_remote_cache_hit(
        self,
        cache_key: str,
        handle: WorktreeHandle,
        start: float,
        backend_kind: str,
    ):
        """Return cached ``LocalWorktreeRef`` on cache hit, else ``None``."""
        from mahavishnu.observability.metrics import record_worktree_op

        from .types import LocalWorktreeRef

        cached_path_str = await self._cache.get(cache_key)
        if not cached_path_str:
            return None
        materialized = Path(str(cached_path_str))
        if not materialized.exists():
            return None
        record_worktree_op(
            backend=backend_kind,
            op="fetch",
            duration_seconds=time.monotonic() - start,
            success=True,
            principal=handle.principal.name,
        )
        return LocalWorktreeRef(
            path=materialized,
            worktree_id=handle.handle_id,
        )

    @staticmethod
    def _ensure_codec_available() -> None:
        """MHV-223: surface a structured error when zstandard is missing."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        try:
            import zstandard  # noqa: F401
        except ImportError as exc:
            raise WorktreeError(
                "zstandard dependency required for streaming tar.zst; "
                "install with `uv sync --group compression-zstd`",
                error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
            ) from exc

    def _ensure_storage_supports_load_stream(self) -> None:
        """Reject storage adapters missing the streaming surface."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        if getattr(self._storage, "load_stream", None) is None:
            raise WorktreeError(
                f"Storage adapter {type(self._storage).__name__} "
                f"does not implement load_stream; cannot fetch Phase 3 "
                f"tar.zst bundle",
                error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
            )

    def _open_storage_chunk_reader(
        self, storage_key: str
    ) -> Callable[[], Iterator[bytes]]:
        """MHV-222 first half: map load_stream acquisition to NOT_FOUND.

        ``load_stream`` returns a ``Callable[[], Iterator[bytes]]``
        per oneiric PR-A (S3/GCS/Azure). The next step
        (``_invoke_chunk_reader``) calls that callable.
        """
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        try:
            return self._storage.load_stream(storage_key)  # type: ignore[union-attr, return-value]
        except Exception as exc:
            raise WorktreeError(
                f"Storage key not found: {storage_key}",
                error_code=ErrorCode.WORKTREE_BUNDLE_NOT_FOUND,
            ) from exc

    @staticmethod
    def _invoke_chunk_reader(
        chunk_reader_callable: Callable[[], Iterator[bytes]],
        storage_key: str,
    ) -> Iterator[bytes]:
        """MHV-222 second half: map callable invocation to NOT_FOUND."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        try:
            return chunk_reader_callable()
        except Exception as exc:
            raise WorktreeError(
                f"Storage key not found: {storage_key}",
                error_code=ErrorCode.WORKTREE_BUNDLE_NOT_FOUND,
            ) from exc

    @staticmethod
    def _start_stream_producer(
        stream_iter: Iterator[bytes],
    ) -> tuple[queue.Queue[bytes | object], threading.Thread]:
        """Start a daemon producer thread draining ``stream_iter`` into ``q``.

        Returns ``(queue, Thread)``. The bounded queue (maxsize=4)
        keeps producer/consumer memory at ``chunk_size * 4`` (B-DI-10).

        The closure binds ``producer`` into the target so the
        producer can stash any captured exception on
        ``producer._producer_error``; the consumer reads this
        attribute after ``producer.join()`` to surface mid-stream
        failures (security review finding).
        """
        q: queue.Queue[bytes | object] = queue.Queue(maxsize=4)

        def _run() -> None:
            # Bind the thread reference first so the target can stash
            # any captured exception on it. ``threading.current_thread()``
            # returns the calling Thread for us.
            _producer_thread_target(threading.current_thread(), stream_iter, q)

        producer = threading.Thread(
            target=_run,
            daemon=True,
        )
        producer.start()
        return q, producer

    @staticmethod
    def _consume_first_chunk(
        q: queue.Queue[bytes | object], storage_key: str
    ) -> bytes:
        """Pull the first chunk from ``q``; raise NOT_FOUND on empty."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        first_chunk_any = q.get()
        if first_chunk_any is _STREAM_SENTINEL:
            raise WorktreeError(
                f"Storage key not found: {storage_key}",
                error_code=ErrorCode.WORKTREE_BUNDLE_NOT_FOUND,
            )
        return first_chunk_any  # type: ignore[return-value]

    @staticmethod
    def _reject_legacy_gzip_magic(
        first_chunk: bytes, producer: threading.Thread
    ) -> None:
        """MHV-213: reject legacy ``.tar.gz`` bundles."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        if first_chunk[:2] == b"\x1f\x8b":
            producer.join(timeout=1.0)
            raise WorktreeError(
                "Legacy .tar.gz bundle (gzip magic) is not "
                "supported in the Phase 3 streaming path; "
                "re-create the worktree with create_worktree_handle",
                error_code=ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2,
            )

    @staticmethod
    def _drain_queue_into_target(
        deserialize_worktree_tar: Callable[..., None],
        q: queue.Queue[bytes | object],
        first_chunk: bytes,
        target: Path,
        handle: WorktreeHandle,
        backend_kind: str,
    ) -> int:
        """Drain the bounded queue into ``deserialize_worktree_tar``.

        Yields the (peeked) ``first_chunk`` first, then continues
        draining the queue until the producer's sentinel arrives.

        Returns the total compressed bytes observed (used by the
        caller to verify against ``handle.bytes_size`` — a missing
        chunk would otherwise validate SHA over a truncated payload).
        """
        byte_count = 0

        def _chunk_reader_from_queue() -> Any:
            nonlocal byte_count
            yield first_chunk
            byte_count += len(first_chunk)
            while True:
                item = q.get()
                if item is _STREAM_SENTINEL:
                    return
                # Sentinel already returned; remaining items are bytes.
                assert isinstance(item, (bytes, bytearray))  # nosemgrep
                byte_count += len(item)
                yield item

        deserialize_worktree_tar(
            _chunk_reader_from_queue,
            target,
            expected_sha256=handle.sha256,
            backend=backend_kind,
            principal_short=_principal_short(handle.principal),
        )
        return byte_count

    @staticmethod
    def _resolve_materialized_path_for_handle(handle: WorktreeHandle) -> Path:
        """Per-handle target under ``get_worktree_base_path() / remote-materialized``."""
        target = get_worktree_base_path() / "remote-materialized" / handle.handle_id
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _record_successful_deserialize(
        start: float, backend_kind: str, byte_size: int
    ) -> None:
        """Emit the ``DESERIALIZE`` histogram for the streaming success path."""
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_streaming_op,
        )

        record_streaming_op(
            StreamingOp.DESERIALIZE,
            backend_kind,
            duration_ms=(time.monotonic() - start) * 1000.0,
            bytes_processed=byte_size,
            success=True,
        )

    @staticmethod
    def _record_fetch_outcome(
        start: float,
        backend_kind: str,
        *,
        success: bool,
        handle: WorktreeHandle,
    ) -> None:
        """Emit the ``fetch`` histogram with success/failure flag."""
        from mahavishnu.observability.metrics import record_worktree_op

        record_worktree_op(
            backend=backend_kind,
            op="fetch",
            duration_seconds=time.monotonic() - start,
            success=success,
            principal=handle.principal.name,
        )

    async def remove_handle(
        self,
        handle: WorktreeHandle,
        *,
        caller: Principal,
    ) -> bool:
        """Remove a handle from storage + cache + Dhara registry.

        ``caller`` is the authenticated session principal — NOT
        ``handle.principal``. Threading it through Dhara's ownership
        + scope check prevents a session from impersonating the
        handle owner (the auth-fabrication risk documented in the
        PR-D security review). WorktreeCoordinator forwards caller.

        Phase 3 (Task C.7) notes:

        - Storage delete is best-effort — a missing object is normal
          (the handle may already have been cleaned up by a previous
          remove).
        - Cache invalidation removes any cached materialized path
          for this handle; ``record_cache_invalidation`` is emitted
          with ``reason="remove_handle"`` per the cache-metric shape
          shared with LocalWorktreeProvider.
        - Dhara registry remove is the source of truth for
          "does this handle still exist"; returns ``True`` when the
          primary row was deleted, ``False`` when it was not found.
        """
        from .types import RemoteWorktreeRef

        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            raise NotImplementedError(
                "RemoteWorktreeProvider.remove_handle expects a RemoteWorktreeRef; "
                f"got {type(handle.storage_ref).__name__}"
            )
        if caller is None:
            raise PermissionError(
                "RemoteWorktreeProvider.remove_handle requires a caller "
                "(no anonymous handle removal)"
            )
        ref: RemoteWorktreeRef = handle.storage_ref
        backend_kind = ref.backend_kind

        # 0. Best-effort cleanup of the transient worktree dir on disk.
        # The dir is owned by ``get_worktree_path(repo, branch)`` and
        # only exists when ``create_worktree_handle`` ran to
        # completion — missing path is a no-op.
        try:
            # Validate the components the same way create_worktree_handle
            # does — a handle whose recorded repo/branch contain ``/``
            # or ``..`` must not be allowed to escape the base.
            _validate_path_component(handle.repo, kind="repo")
            _validate_path_component(handle.branch, kind="branch")
            wt_path = get_worktree_path(handle.repo, handle.branch)
            if wt_path.exists():
                await _remove_worktree_via_git("git", Path(handle.repo), wt_path, force=True)
        except Exception as exc:  # noqa: BLE001 — best-effort on-disk cleanup; logged + falls through to storage delete
            logger.debug(
                "worktree-remove-handle-on-disk-cleanup-skipped",
                extra={"handle_id": handle.handle_id, "error": str(exc)},
            )

        # 1. Delete from object storage (best-effort — missing object is OK).
        try:
            delete = getattr(self._storage, "delete", None)
            if delete is None:
                # Pre-PR-A adapter — fall back to upload with empty
                # bytes (not ideal, but matches the legacy contract).
                logger.debug(
                    "remote-storage-delete-skipped",
                    extra={"key": ref.key, "backend": backend_kind},
                )
            else:
                result = delete(ref.key)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as exc:  # noqa: BLE001 — boundary; surface + continue
            logger.warning(
                "remote-storage-delete-failed",
                extra={
                    "key": ref.key,
                    "backend": backend_kind,
                    "error": str(exc),
                },
            )

        # 2. Invalidate cache entries for this handle.
        try:
            count = await self._cache.invalidate_handle(handle.handle_id)
        except Exception as exc:  # noqa: BLE001 — boundary; surface + continue
            logger.warning(
                "remote-cache-invalidate-failed",
                extra={"handle_id": handle.handle_id, "error": str(exc)},
            )
            count = 0
        record_cache_invalidation(backend_kind, "remove_handle", count)

        # 3. Remove from the Dhara registry (caller = authenticated session).
        if self._dhara_client is None:
            return False
        return await dhara_remove_handle(
            self._dhara_client,
            handle.handle_id,
            caller=caller,
        )

    async def list_handles(
        self,
        principal: str | None = None,
        repo: str | None = None,
        caller: Principal | None = None,
        all_tenants: bool = False,
    ) -> list:
        """List handles via the Dhara registry.

        Permission model is delegated to ``dhara_registry.list_handles``:
        ``all_tenants=True`` requires ``worktree:list-all``; ``repo``
        scoping requires ``worktree:read``; otherwise results are
        filtered to the caller's own handles.
        """
        from mahavishnu.core.worktree_providers.dhara_registry import (
            list_handles as dhara_list_handles,
        )

        if caller is None:
            raise PermissionError("RemoteWorktreeProvider.list_handles requires a caller")
        if self._dhara_client is None:
            return []
        return await dhara_list_handles(
            self._dhara_client,
            principal=principal,
            repo=repo,
            caller=caller,
            all_tenants=all_tenants,
        )

    async def exists(self, handle: WorktreeHandle) -> bool:
        """Return True iff the underlying object exists in remote storage.

        Uses ``storage.exists`` when the adapter supports it (post-Oneiric
        PR-A); otherwise falls back to a ``load_stream`` + empty-stream
        check. Never raises — a missing object is a normal "exists=False".
        """
        from .types import RemoteWorktreeRef

        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            return False
        ref: RemoteWorktreeRef = handle.storage_ref
        storage_exists = getattr(self._storage, "exists", None)
        if storage_exists is not None:
            try:
                result = storage_exists(ref.key)
                if asyncio.iscoroutine(result):
                    return bool(await result)
                return bool(result)
            except Exception as exc:  # noqa: BLE001 — boundary; return False
                logger.warning(
                    "remote-exists-check-failed",
                    extra={"key": ref.key, "error": str(exc)},
                )
                return False
        # Fallback: head-conditional via load_stream.
        try:
            load_stream = getattr(self._storage, "load_stream", None)
            if load_stream is None:
                return False
            callable_iter = load_stream(ref.key)
            if callable(callable_iter):
                iterator = callable_iter()
            else:
                iterator = callable_iter
            try:
                first = next(iter(iterator), b"")
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
            return bool(first)
        except Exception:  # noqa: BLE001 — boundary; return False
            return False

    async def lock(
        self,
        repo: str,
        branch: str,
        *,
        acquire_timeout: float = 10.0,
        lease_ttl: float = 30.0,
        redis_client: object | None = None,
    ):
        """Acquire a distributed lock by delegating to ``local_provider``.

        The lock semantics (Redis SETNX with fencing token) live in
        :class:`LocalWorktreeProvider`; the remote provider reuses the
        same backend so a single Mahavishnu deployment has one
        distributed lock domain across both local and cloud worktrees.

        Raises ``NotImplementedError`` when no ``local_provider`` was
        supplied at construction (decentralized deployments that prefer
        a direct Redis client should construct ``LocalWorktreeProvider``
        themselves and pass it in).
        """
        if self._local_provider is None:
            raise NotImplementedError(
                "RemoteWorktreeProvider.lock requires a LocalWorktreeProvider "
                "passed at construction (for the Redis-backed distributed lock). "
                "Construct one and pass it via local_provider=..."
            )
        return await self._local_provider.lock(
            repo,
            branch,
            acquire_timeout=acquire_timeout,
            lease_ttl=lease_ttl,
            redis_client=redis_client,
        )

    async def health(self) -> HealthReport:
        """Probe storage, cache, and streaming capability (B-DI-03).

        Returns a :class:`HealthReport` instead of a raw ``bool`` so
        the warning can be carried alongside the probe result. The
        ``HealthReport`` is ``__bool__``-compatible so legacy
        ``if await provider.health()`` callers keep working.

        A ``streaming_capability_missing`` warning is added when the
        storage adapter lacks ``save_stream`` / ``load_stream`` — in
        that case the stopgap path (max bundle size
        ``MAX_BUNDLE_BYTES_STOPGAP``) is used and the warning lets
        dashboards flag misconfigured adapters.
        """
        from mahavishnu.observability.metrics import record_backend_health_check_failed

        report = HealthReport(healthy=True)

        try:
            storage_health = self._storage.health()
            if asyncio.iscoroutine(storage_health):
                storage_ok = await storage_health
            else:
                storage_ok = bool(storage_health)
        except Exception:  # noqa: BLE001 — boundary
            storage_ok = False
        if not storage_ok:
            report.healthy = False
            record_backend_health_check_failed(backend=self._backend)

        try:
            cache_ok = await self._cache.health()
        except Exception:  # noqa: BLE001 — boundary
            cache_ok = False
        if not cache_ok:
            report.healthy = False
            record_backend_health_check_failed(backend=self._backend)

        if not supports_streaming(self._storage):
            report.add_warning(
                kind="streaming_capability_missing",
                message=(
                    f"Storage adapter {type(self._storage).__name__} "
                    f"lacks save_stream/load_stream; "
                    f"stopgap path will be used (max bundle size "
                    f"{MAX_BUNDLE_BYTES_STOPGAP // (1024 * 1024)}MB)"
                ),
            )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_bucket(self) -> str:
        """Read the adapter's bucket/container name (best-effort)."""
        settings = getattr(self._storage, "_settings", None)
        for attr in ("bucket", "container"):
            value = getattr(settings, attr, None)
            if value:
                return str(value)
        return _DEFAULT_BUCKET

    def _build_key(self, repo: str, branch: str, handle_id: str) -> str:
        """Build the canonical object key for a worktree bundle.

        Format: ``worktrees/<repo>/<branch>/<handle_id>.tar.zst``. Repo
        slashes are flattened to ``_`` so a key never contains a ``/``
        mid-component that could be misinterpreted by prefix-listing.
        """
        safe_repo = repo.strip("/").replace("/", "_")
        safe_branch = branch.strip("/").replace("/", "_").replace(" ", "_")
        return f"worktrees/{safe_repo}/{safe_branch}/{handle_id}.tar.zst"


__all__ = [
    "MAX_CONCURRENT_WORKTREE_STREAMS",
    "HealthReport",
    "RemoteWorktreeProvider",
    "supports_streaming",
]
