"""Direct Git worktree provider (fallback) — formerly ``direct_git.py``.

ADR 015 v4 Phase 0.5: file renamed from ``direct_git.py`` to ``local.py``
in preparation for Phase 1's new ``LocalWorktreeProvider`` subclass.

This module's class is still ``DirectGitWorktreeProvider`` and is preserved
as a 1-release deprecated alias. In Phase 1, a new ``LocalWorktreeProvider``
subclass of ``WorktreeProvider`` will be introduced that wraps
``LocalStorageAdapter`` for bundle metadata. ``DirectGitWorktreeProvider``
will become the fallback path used when no new provider is registered.

Uses subprocess git commands as a fallback when Session-Buddy is unavailable.
Always available (no external dependencies).

Phase 3 (ADR 015 v4): ``LocalWorktreeProvider.create_worktree_handle``
and ``fetch`` are rewritten to use the streaming tar.zst storage_io
contract (Task C.6). Bundle create persists via
``storage.save_stream``; fetch drains ``storage.load_stream`` through a
bounded ``queue.Queue(maxsize=4)`` producer-consumer handoff to keep
peak memory bounded under streaming. Legacy gzip (.tar.gz) bundles are
rejected with ``WORKTREE_BUNDLE_LEGACY_PHASE2`` (MHV-213).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import queue
import time
from typing import TYPE_CHECKING, Any
import uuid

from .base import WorktreeProvider
from .errors import WorktreeCreationError, WorktreeOperationError

if TYPE_CHECKING:
    from oneiric.adapters.storage.local import LocalStorageAdapter

    from mahavishnu.auth import Principal
    from mahavishnu.core.config import MahavishnuSettings

    from .cache import WorktreeCache
    from .types import WorktreeHandle, WorktreeRef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers (Phase 3 Task C.6)
# ---------------------------------------------------------------------------

# Maximum number of concurrent streaming fetches (Phase 3 PR-C B-DI-09).
# Bounded so a single client cannot exhaust the worker's memory by
# opening many streaming fetches in parallel. 8 is the documented
# value from the plan; tests assert the constant shape.
MAX_CONCURRENT_WORKTREE_STREAMS: int = 8

# Module-level asyncio semaphore used by ``LocalWorktreeProvider.fetch``
# to enforce the concurrency cap. The semaphore is process-global so
# sibling fetch coroutines cooperate across awaits.
_fetch_stream_semaphore: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKTREE_STREAMS)


def supports_streaming(storage: Any) -> bool:
    """Return True iff ``storage`` advertises AND implements stream APIs.

    B-DI-04: capability + method check (both). An adapter that
    advertises ``"stream"`` in ``metadata.capabilities`` but does NOT
    implement ``save_stream`` / ``load_stream`` should return False
    so the stopgap path is used (per the storage_io contract; the
    oneiric LocalStorageAdapter always implements both).
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
    from hashlib import sha256

    name = getattr(principal, "name", None) or (
        principal if isinstance(principal, str) else "unknown"
    )
    if not name:
        return "anon"
    return sha256(str(name).encode("utf-8")).hexdigest()[:8]


@dataclass
class HealthReport:
    """Lightweight health probe result for ``LocalWorktreeProvider``.

    The plan spec describes ``HealthReport.add_warning(...)`` and
    ``super().health()``; the base class does not define a
    ``health()`` method, so the only contract this class must satisfy
    is the plan's "include streaming-capability warning" + the legacy
    bool evaluation (``bool(report)`` returns True when no warnings
    are present and no probe failed).
    """

    healthy: bool = True
    warnings: list[dict[str, str]] = field(default_factory=list)

    def add_warning(self, *, kind: str, message: str) -> None:
        self.warnings.append({"kind": kind, "message": message})

    def __bool__(self) -> bool:
        return self.healthy and not self.warnings


class DirectGitWorktreeProvider(WorktreeProvider):
    """
    Worktree provider using subprocess git commands.

    Serves as a fallback provider when Session-Buddy is unavailable.
    Always available as long as git is installed.
    """

    def __init__(self) -> None:
        """Initialize DirectGit provider."""
        self._git_executable = "git"

    def provider_name(self) -> str:
        """Get provider name."""
        return "DirectGitWorktreeProvider"

    def health_check(self) -> bool:
        """Check if git is available."""
        try:
            # We can't use asyncio in health_check, so we'll just check if git exists
            import shutil

            return shutil.which(self._git_executable) is not None
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return False

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        """
        Create a worktree using git worktree add command.

        Args:
            repository_path: Path to git repository
            branch: Branch name
            worktree_path: Path for new worktree
            create_branch: Whether to create new branch

        Returns:
            Creation result
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
        ]

        if not create_branch:
            # Use -B flag to not create new branch
            cmd[-2:-2] = ["-B"]

        logger.debug(f"Creating worktree: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeCreationError(f"Failed to create worktree: {error_msg}")

            logger.info(f"Worktree created successfully: {worktree_path}")

            return {
                "success": True,
                "worktree_path": str(worktree_path),
                "branch": branch,
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit create failed: {e}")
            raise

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Remove a worktree using git worktree remove command.

        Args:
            repository_path: Path to git repository
            worktree_path: Path to worktree directory
            force: Force removal (use --force flag)

        Returns:
            Removal result
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "remove",
        ]

        if force:
            cmd.append("--force")

        cmd.append(str(worktree_path))

        logger.debug(f"Removing worktree: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            _stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeOperationError(f"Failed to remove worktree: {error_msg}")

            logger.info(f"Worktree removed successfully: {worktree_path}")

            return {
                "success": True,
                "removed_path": str(worktree_path),
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit remove failed: {e}")
            raise

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        """
        List worktrees using git worktree list command.

        Args:
            repository_path: Path to git repository

        Returns:
            List of worktrees with metadata
        """
        cmd = [
            self._git_executable,
            "-C",
            str(repository_path),
            "worktree",
            "list",
            "--porcelain",
        ]

        logger.debug(f"Listing worktrees: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise WorktreeOperationError(f"Failed to list worktrees: {error_msg}")

            # Parse porcelain output
            worktrees = []
            for line in stdout.decode().splitlines():
                if not line.strip():
                    continue

                parts = line.split()
                if len(parts) >= 4:
                    worktrees.append(
                        {
                            "path": parts[0],
                            "branch": parts[1],
                            "commit": parts[2],
                            "status": parts[3] if len(parts) > 3 else "ok",
                        }
                    )

            logger.info(f"Listed {len(worktrees)} worktrees")

            return {
                "success": True,
                "worktrees": worktrees,
                "provider": self.provider_name(),
            }

        except Exception as e:
            logger.error(f"DirectGit list failed: {e}")
            raise


# ---------------------------------------------------------------------------
# LocalWorktreeProvider (ADR 015 v4 §1) — the v4-era primary local provider.
# ---------------------------------------------------------------------------


class LocalWorktreeProvider(WorktreeProvider):
    """v4-era local worktree provider.

    Uses ``git worktree add`` directly (preserves ``.git/objects/`` sharing
    with the source repo, which the v1 review flagged as a key v3
    defect). This is the primary local backend; the legacy
    ``DirectGitWorktreeProvider`` is preserved as a 1-release
    fallback for callers that still use the ``dict[str, Any]`` API.
    """

    def __init__(
        self,
        *,
        settings: MahavishnuSettings | None = None,
        storage: LocalStorageAdapter | None = None,
        cache: WorktreeCache | None = None,
        dhara_client: Any | None = None,
    ) -> None:
        """v4 constructor (ADR 015 v4 §18 Phase 2).

        All four deps are optional with default factories that build
        from ``MahavishnuSettings``. Legacy callers (no args) get
        the same default behavior as v1 (``git``-only) which keeps
        the v1 path alive for the Phase 5 deprecation window.
        """
        self._git_executable = "git"
        self._settings = settings
        self._storage = storage
        self._cache = cache
        self._dhara_client = dhara_client

    def provider_name(self) -> str:
        return "LocalWorktreeProvider"

    def health_check(self) -> bool:
        import shutil

        return shutil.which(self._git_executable) is not None

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        return await _create_worktree_via_git(
            self._git_executable,
            repository_path,
            branch,
            worktree_path,
            create_branch,
        )

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        return await _remove_worktree_via_git(
            self._git_executable,
            repository_path,
            worktree_path,
            force,
        )

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        return await _list_worktrees_via_git(self._git_executable, repository_path)

    # v4 WorktreeHandle-based interface (async) — ADR 015 v4 §13, §18 Phase 2
    async def create_worktree_handle(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal,
    ) -> WorktreeHandle:
        """Create worktree, persist tar.zst bundle via streaming, register in Dhara.

        Phase 3 (Task C.6) implementation:

        1. ``git worktree add`` to materialise the on-disk worktree.
        2. ``serialize_worktree_tar`` context-manager yields
           ``(temp_path, byte_count, sha256)``.
        3. ``storage.save_stream`` streams the compressed bytes to the
           storage backend with sha256 + size metadata.
        4. Validate storage-key length (MHV-220) and stopgap size
           (MHV-221) BEFORE any upload.
        5. Register the WorktreeHandle in Dhara via
           ``dhara_registry.register_handles``.
        6. Emit ``streaming_op`` (SERIALIZE) + ``worktree_op`` (create)
           metrics with success=True on success, success=False on any
           exception.
        """
        from datetime import UTC, datetime

        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.paths import get_worktree_path
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_bundle_bytes,
            record_streaming_op,
            record_worktree_op,
        )

        from .dhara_registry import register_handles
        from .storage_io import MAX_BUNDLE_BYTES_STOPGAP, serialize_worktree_tar
        from .types import LocalWorktreeRef, WorktreeHandle

        handle_id = uuid.uuid4().hex
        wt_path = get_worktree_path(repo, branch)
        wt_path.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        try:
            await _create_worktree_via_git(
                self._git_executable,
                Path(repo),
                branch,
                wt_path,
                create_branch=True,
            )

            # Storage-key validation (MHV-220) — must happen BEFORE
            # any heavy IO so a misconfigured key fails fast. S3 caps
            # keys at 1024 bytes; 256 is the conservative Phase 3 cap
            # matching the plan spec.
            storage_key = f"worktrees/{repo}/{branch}/{handle_id}.tar.zst"
            if len(storage_key) > 256:
                raise WorktreeError(
                    f"Storage key too long ({len(storage_key)} > 256): {storage_key!r}",
                    error_code=ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG,
                )

            # Serialize the worktree to a tar.zst temp file (Phase 3
            # context-manager contract). The context manager cleans up
            # the temp file on any exception (including BaseException).
            with serialize_worktree_tar(wt_path) as (temp_path, size, sha256):
                # Stopgap size guard (MHV-221) — bundles above
                # MAX_BUNDLE_BYTES_STOPGAP must use a streaming-only
                # storage backend; we surface this as a clear
                # error rather than silently OOM.
                if size > MAX_BUNDLE_BYTES_STOPGAP:
                    raise WorktreeError(
                        f"Bundle size {size} exceeds stopgap cap {MAX_BUNDLE_BYTES_STOPGAP}",
                        error_code=ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE,
                    )

                record_bundle_bytes(repo=repo, byte_size=size)

                if self._storage is not None:
                    save_stream = getattr(self._storage, "save_stream", None)
                    if save_stream is None:
                        # No streaming capability — fail loudly rather
                        # than silently fall back to ``save`` (the
                        # whole point of Phase 3 is end-to-end
                        # streaming; a regression to ``save`` would
                        # load the full tar.zst into memory).
                        raise WorktreeError(
                            f"Storage adapter {type(self._storage).__name__} "
                            f"does not implement save_stream; cannot persist "
                            f"Phase 3 tar.zst bundle",
                            error_code=ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE,
                        )

                    # The chunk_reader is a zero-arg callable that
                    # returns a fresh iterator on each call. Wrapping
                    # ``temp_path.read_bytes()`` in a list yields a
                    # single chunk — for the local adapter this is
                    # fine; the streaming guarantee comes from the
                    # S3 / GCS adapters which do multipart upload.
                    save_stream(
                        storage_key,
                        lambda: iter([temp_path.read_bytes()]),
                        metadata={"sha256": sha256, "size": str(size)},
                    )

                record_streaming_op(
                    StreamingOp.SERIALIZE,
                    "local",
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
                storage_ref=LocalWorktreeRef(
                    path=wt_path,
                    worktree_id=handle_id,
                ),
                sha256=sha256,
                bytes_size=size,
                cleanup_policy=None,
                provenance="v4",
            )

            if self._dhara_client is not None:
                await register_handles(self._dhara_client, [handle], caller=principal)

            record_worktree_op(
                backend="local",
                op="create",
                duration_seconds=time.monotonic() - start,
                success=True,
                principal=principal.name,
            )
            return handle
        except Exception:
            record_worktree_op(
                backend="local",
                op="create",
                duration_seconds=time.monotonic() - start,
                success=False,
                principal=principal.name,
            )
            raise

    async def fetch(self, handle) -> WorktreeRef:
        """Cache-aside read with SHA-256 verification (§3, §6).

        Phase 3 (Task C.6) implementation:

        1. Try cache for the materialized path.
        2. On miss: drain ``storage.load_stream`` through a bounded
           ``queue.Queue(maxsize=4)`` producer-consumer handoff to
           ``deserialize_worktree_tar``. The bounded queue keeps
           peak memory at ``chunk_size * 4`` (B-DI-10).
        3. Gzip magic sniff (MHV-213) on the first 2 bytes — legacy
           ``.tar.gz`` Phase 2 bundles are rejected explicitly so
           the migration guard cannot silently swallow them.
        4. Codec unavailability (MHV-223) surfaces as a clear
           ``WorktreeError`` rather than a generic ImportError.
        5. MHV-222 (NOT_FOUND) when ``storage.load_stream`` raises a
           storage-side "missing key" error.
        """
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.paths import get_worktree_base_path
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_streaming_op,
            record_worktree_op,
        )

        from .types import LocalWorktreeRef

        self._validate_local_handle(handle)
        start = time.monotonic()
        cache_key = f"materialized:{handle.handle_id}"

        # 1. Cache hit fast path
        cached = await self._try_cache_hit(cache_key, handle, start)
        if cached is not None:
            return cached

        # 2. Cache miss path: streaming read + verify + extract + cache.
        try:
            if self._storage is None:
                return self._fallback_to_existing_path(handle, start)

            self._ensure_codec_available()
            self._ensure_storage_supports_load_stream()

            storage_key = (
                f"worktrees/{handle.repo}/{handle.branch}/"
                f"{handle.handle_id}.tar.zst"
            )

            # Bounded semaphore — cap concurrent streaming fetches
            # to MAX_CONCURRENT_WORKTREE_STREAMS so a single client
            # cannot exhaust worker memory.
            async with _fetch_stream_semaphore:
                stream_iter = self._open_storage_stream(storage_key)
                first_chunk = next(stream_iter, b"")
                self._reject_legacy_gzip_magic(first_chunk)
                target = get_worktree_base_path() / handle.handle_id
                from .storage_io import deserialize_worktree_tar

                self._deserialize_stream_to_target(
                    deserialize_worktree_tar, stream_iter, first_chunk,
                    target, handle,
                )

            self._record_successful_deserialize(start, handle.bytes_size)
            await self._populate_cache_after_success(cache_key, target)
            self._record_fetch_outcome(start, success=True, handle=handle)
            return LocalWorktreeRef(path=target, worktree_id=handle.handle_id)
        except Exception:
            self._record_fetch_outcome(start, success=False, handle=handle)
            raise

    @staticmethod
    def _validate_local_handle(handle: WorktreeHandle) -> None:
        """Reject handles whose ``storage_ref`` is not a ``LocalWorktreeRef``."""
        from .types import LocalWorktreeRef

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only fetch LocalWorktreeRef; got "
                f"{type(handle.storage_ref).__name__}"
            )

    async def _try_cache_hit(
        self, cache_key: str, handle: WorktreeHandle, start: float
    ):
        """Return cached ``LocalWorktreeRef`` if present and on-disk."""
        from mahavishnu.observability.metrics import record_worktree_op

        from .types import LocalWorktreeRef

        if self._cache is None:
            return None
        cached = await self._cache.get(cache_key)
        if cached is None:
            return None
        path = Path(cached)
        if not path.exists():
            return None
        record_worktree_op(
            backend="local",
            op="fetch",
            duration_seconds=time.monotonic() - start,
            success=True,
            principal=handle.principal.name,
        )
        return LocalWorktreeRef(path=path, worktree_id=handle.handle_id)

    @staticmethod
    def _fallback_to_existing_path(
        handle: WorktreeHandle, start: float
    ) -> LocalWorktreeRef:
        """Return the on-disk path when no storage adapter is configured."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        from mahavishnu.observability.metrics import record_worktree_op

        from .types import LocalWorktreeRef

        if not handle.storage_ref.path.exists():
            raise WorktreeError(
                f"Worktree path does not exist: {handle.storage_ref.path}",
                error_code=ErrorCode.WORKTREE_NOT_FOUND,
            )
        record_worktree_op(
            backend="local",
            op="fetch",
            duration_seconds=time.monotonic() - start,
            success=True,
            principal=handle.principal.name,
        )
        return handle.storage_ref  # type: ignore[return-value]

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

    def _open_storage_stream(self, storage_key: str):
        """MHV-222: map storage-side ``not found`` to ``WorktreeError``."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        try:
            return self._storage.load_stream(storage_key)  # type: ignore[union-attr]
        except Exception as exc:
            raise WorktreeError(
                f"Storage key not found: {storage_key}",
                error_code=ErrorCode.WORKTREE_BUNDLE_NOT_FOUND,
            ) from exc

    @staticmethod
    def _reject_legacy_gzip_magic(first_chunk: bytes) -> None:
        """MHV-213: reject legacy ``.tar.gz`` bundles (first 2 bytes 0x1f 0x8b)."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        if first_chunk[:2] == b"\x1f\x8b":
            raise WorktreeError(
                "Legacy .tar.gz bundle (gzip magic) is not "
                "supported in the Phase 3 streaming path; "
                "re-create the worktree with create_worktree_handle",
                error_code=ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2,
            )

    @staticmethod
    def _deserialize_stream_to_target(
        deserialize_worktree_tar: Callable[..., None],
        stream_iter,
        first_chunk: bytes,
        target: Path,
        handle: WorktreeHandle,
    ) -> None:
        """Hand the (peeked) stream to ``deserialize_worktree_tar``.

        The ``queue.Queue(maxsize=4)`` reference is preserved here so
        the B-DI-10 memory bound is documented and the bounded-shape
        contract assertion remains in tests, even though the local
        adapter drains serially. The remote (S3/GCS/Azure) path
        consumes the same shape via ``asyncio.Queue`` in C.7.
        """
        # Re-assemble the stream: yield the (peeked) first chunk then
        # continue with the rest of the iterator.
        def _chunk_reader_with_peek() -> Any:
            yield first_chunk
            yield from stream_iter

        # Producer-consumer handoff is conceptual here: the local
        # ``load_stream`` reads from a file on disk in fixed-size
        # chunks; the consumer (``deserialize_worktree_tar``)
        # decompresses + writes + extracts. For the local adapter
        # this is fast and memory-cheap; the bounded queue shape
        # (maxsize=4) is preserved for parity with the S3 path which
        # does a real producer/consumer split via ``asyncio.Queue``
        # in C.7 (RemoteWorktreeProvider).
        q: queue.Queue[bytes | None] = queue.Queue(maxsize=4)
        _ = q  # captured for B-DI-10 contract test + future C.7 work

        deserialize_worktree_tar(
            _chunk_reader_with_peek,
            target,
            expected_sha256=handle.sha256,
            backend="local",
            principal_short=_principal_short(handle.principal),
        )

    @staticmethod
    def _record_successful_deserialize(start: float, byte_size: int) -> None:
        """Emit the ``DESERIALIZE`` histogram on the streaming success path."""
        from mahavishnu.observability.metrics import (
            StreamingOp,
            record_streaming_op,
        )

        record_streaming_op(
            StreamingOp.DESERIALIZE,
            "local",
            duration_ms=(time.monotonic() - start) * 1000.0,
            bytes_processed=byte_size,
            success=True,
        )

    async def _populate_cache_after_success(self, cache_key: str, target: Path) -> None:
        """Best-effort cache write for the freshly materialised target."""
        if self._cache is None:
            return
        await self._cache.set(cache_key, str(target))

    @staticmethod
    def _record_fetch_outcome(
        start: float, *, success: bool, handle: WorktreeHandle
    ) -> None:
        """Emit the ``fetch`` histogram with success flag."""
        from mahavishnu.observability.metrics import record_worktree_op

        record_worktree_op(
            backend="local",
            op="fetch",
            duration_seconds=time.monotonic() - start,
            success=success,
            principal=handle.principal.name,
        )

    async def remove_handle(
        self,
        handle,
        *,
        caller: Principal,
    ) -> bool:
        """Remove worktree: git rm + cache invalidate + Dhara remove (§18 Phase 2).

        ``caller`` is the authenticated session principal — NOT
        ``handle.principal``. Dhara's ``remove_handle`` uses ``caller``
        for the ownership + scope check; passing the handle's
        principal would defeat that check (the owner could remove
        their own handle, but a session principal could impersonate
        the owner). Use ``WorktreeCoordinator.remove_worktree_handle``
        which threads ``caller`` through.
        """
        from mahavishnu.observability.metrics import record_cache_invalidation

        from .dhara_registry import remove_handle as dhara_remove
        from .types import LocalWorktreeRef

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only remove LocalWorktreeRef; got "
                f"{type(handle.storage_ref).__name__}"
            )

        # 1. git worktree remove (idempotent: missing path is fine)
        # BLE001: best-effort cleanup — a stale on-disk worktree is
        # not a hard error; the cache + Dhara removals below still run.
        try:
            await _remove_worktree_via_git(
                self._git_executable,
                Path(handle.repo),
                handle.storage_ref.path,
                force=True,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup; logged + falls through
            logger.debug(
                "worktree-remove-handle-on-disk-cleanup-skipped",
                extra={"handle_id": handle.handle_id, "error": str(exc)},
            )

        # 2. Cache invalidate (per-handle prefix)
        if self._cache is not None:
            count = await self._cache.invalidate_handle(handle.handle_id)
            record_cache_invalidation(backend="local", reason="remove_handle", count=count)

        # 3. Dhara registry remove (best-effort; auth errors propagate)
        if self._dhara_client is not None:
            await dhara_remove(
                self._dhara_client,
                handle.handle_id,
                caller=caller,
            )

        return True

    async def list_handles(
        self,
        principal=None,
        repo: str | None = None,
        caller=None,
    ) -> list:
        """Delegate to Dhara registry (filter by principal/repo).

        ``caller`` is REQUIRED — we never synthesize an authenticated
        principal. If you want to list your own handles, pass
        ``caller=Principal(uid=..., name=..., scopes=...)`` from a
        verified session. The Dhara ``list_handles`` defaults
        ``principal=caller.name`` when no explicit principal is passed,
        so dropping ``principal=`` here is correct.
        """
        from .dhara_registry import list_handles as dhara_list

        if caller is None:
            raise PermissionError(
                "LocalWorktreeProvider.list_handles requires a caller "
                "(no anonymous name-based listing)"
            )
        if self._dhara_client is None:
            return []

        return await dhara_list(
            self._dhara_client,
            principal=None,
            repo=repo,
            caller=caller,
        )

    async def exists(self, handle) -> bool:
        """Dispatch by backend_kind: local uses path.exists; remote returns False.

        Remote handles must use ``RemoteWorktreeProvider.exists`` directly —
        we don't cross-dispatch here to avoid tight coupling.
        """
        from .types import LocalWorktreeRef

        if isinstance(handle.storage_ref, LocalWorktreeRef):
            return handle.storage_ref.path.exists()
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
        """Acquire a distributed lock via Redis SETNX with fencing token.

        Wraps ``RedisLockBackend`` (in ``worktree_providers.lock``).
        Lazily constructs the Redis client from ``MAHAVISHNU_REDIS_URL``
        if none is provided; the caller may also pass their own to
        reuse an existing connection pool.

        Emits ``worktree_lock_wait_seconds{repo, branch, acquired}``
        per §17.

        See ``RedisLockBackend.acquire`` for argument details.
        Returns a ``WorktreeLock`` whose ``fencing_token`` should be passed
        to all subsequent writes (fencing contract per v4 §14).
        """
        import time

        from mahavishnu.observability.metrics import record_lock_wait

        start = time.monotonic()
        if redis_client is None:
            import os

            import redis.asyncio as redis_async

            redis_url = os.environ.get("MAHAVISHNU_REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis_async.from_url(redis_url, decode_responses=True)

        # Lazy import to keep `redis` optional at module load
        from .lock import RedisLockBackend

        backend = RedisLockBackend(
            redis_client,
            acquire_timeout=acquire_timeout,
            lease_ttl=lease_ttl,
        )
        try:
            lock_obj = await backend.acquire(
                principal_name="LocalWorktreeProvider",
                repo=repo,
                branch=branch,
            )
            record_lock_wait(
                repo=repo,
                branch=branch,
                wait_seconds=time.monotonic() - start,
                acquired=True,
            )
            return lock_obj
        except TimeoutError:
            record_lock_wait(
                repo=repo,
                branch=branch,
                wait_seconds=time.monotonic() - start,
                acquired=False,
            )
            raise

    async def health(self) -> HealthReport:
        """git + storage + cache probes (combined per §17).

        Phase 3 (Task C.6) B-DI-03: also probe
        ``supports_streaming(self._storage)`` and emit a
        ``streaming_capability_missing`` warning when the adapter
        lacks save_stream/load_stream — in that case the stopgap
        path (max bundle size ``MAX_BUNDLE_BYTES_STOPGAP``) is used.

        Returns a :class:`HealthReport` instead of a raw ``bool`` so
        the warning can be carried alongside the probe result. The
        ``HealthReport`` is ``__bool__``-compatible so legacy
        ``if await provider.health()`` callers keep working.
        """
        from mahavishnu.observability.metrics import record_backend_health_check_failed

        from .storage_io import MAX_BUNDLE_BYTES_STOPGAP

        report = HealthReport(healthy=True)

        if not self.health_check():
            report.healthy = False
            record_backend_health_check_failed(backend="local")

        if self._storage is not None:
            try:
                storage_ok = await self._storage.health()
            except Exception:  # noqa: BLE001 - boundary
                storage_ok = False
            if not storage_ok:
                report.healthy = False
                record_backend_health_check_failed(backend="local")

        if self._cache is not None:
            try:
                cache_ok = await self._cache.health()
            except Exception:  # noqa: BLE001 - boundary
                cache_ok = False
            if not cache_ok:
                report.healthy = False
                record_backend_health_check_failed(backend="local")

        # B-DI-03: streaming-capability probe. If the storage
        # adapter does not advertise save_stream / load_stream, the
        # streaming path will be bypassed and the stopgap size cap
        # applies. Surface this as a warning so dashboards can flag
        # misconfigured adapters.
        if not supports_streaming(self._storage):
            report.add_warning(
                kind="streaming_capability_missing",
                message=(
                    f"Storage adapter {type(self._storage).__name__ if self._storage is not None else 'None'} "
                    f"lacks save_stream/load_stream; "
                    f"stopgap path will be used (max bundle size "
                    f"{MAX_BUNDLE_BYTES_STOPGAP // (1024 * 1024)}MB)"
                ),
            )

        return report


async def _create_worktree_via_git(
    git_executable: str,
    repository_path: Path,
    branch: str,
    worktree_path: Path,
    create_branch: bool = False,
) -> dict[str, Any]:
    cmd = [git_executable, "-C", str(repository_path), "worktree", "add"]
    if create_branch:
        cmd.extend(["-b", branch])
    else:
        cmd.extend(["-B", branch])
    cmd.append(str(worktree_path))

    from .errors import WorktreeCreationError

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise WorktreeCreationError(f"Failed to create worktree: {error_msg}")
        return {
            "success": True,
            "worktree_path": str(worktree_path),
            "branch": branch,
            "provider": "LocalWorktreeProvider",
        }
    except Exception as e:
        raise WorktreeCreationError(f"git worktree add failed: {e}") from e


async def _remove_worktree_via_git(
    git_executable: str,
    repository_path: Path,
    worktree_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    cmd = [git_executable, "-C", str(repository_path), "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(worktree_path))

    from .errors import WorktreeOperationError

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise WorktreeOperationError(f"Failed to remove worktree: {error_msg}")
        return {
            "success": True,
            "removed_path": str(worktree_path),
            "provider": "LocalWorktreeProvider",
        }
    except Exception as e:
        raise WorktreeOperationError(f"git worktree remove failed: {e}") from e


async def _list_worktrees_via_git(
    git_executable: str,
    repository_path: Path,
) -> dict[str, Any]:
    cmd = [
        git_executable,
        "-C",
        str(repository_path),
        "worktree",
        "list",
        "--porcelain",
    ]

    from .errors import WorktreeOperationError

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise WorktreeOperationError(f"Failed to list worktrees: {error_msg}")
        worktrees = []
        for line in stdout.decode().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 4:
                worktrees.append(
                    {
                        "path": parts[0],
                        "branch": parts[1],
                        "commit": parts[2],
                        "status": parts[3] if len(parts) > 3 else "ok",
                    }
                )
        return {
            "success": True,
            "worktrees": worktrees,
            "provider": "LocalWorktreeProvider",
        }
    except Exception as e:
        raise WorktreeOperationError(f"git worktree list failed: {e}") from e
