"""Remote (cloud-backed) worktree provider (ADR 015 v4 §13).

Wraps any of Oneiric's storage adapters (S3, GCS, Azure Blob) to
provide a WorktreeHandle-based interface for non-local worktrees.

This is the v4-era primary cloud provider. The legacy sync ABC
methods are preserved (raising ``NotImplementedError``) so callers
on the v1 dict-based API keep their existing failure mode.

Renamed from ``S3WorktreeProvider`` in Phase 1 (ADR 015 v4 §13) to
reflect that the provider is backend-agnostic (it dispatches through
whichever Oneiric storage adapter the deployment configures).

Backend dispatch is a property of the handle's ``storage_ref.backend_kind``;
the provider picks that up at runtime via ``handle.storage_ref.key`` (the
storage backend does not need to know its own kind — the handle carries it).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import inspect
import logging
import subprocess
import time
from pathlib import Path
import uuid
from typing import TYPE_CHECKING, Any

from mahavishnu.auth import Principal
from mahavishnu.core.paths import get_worktree_base_path
from mahavishnu.core.worktree_providers.cache import WorktreeCache
from mahavishnu.core.worktree_providers.dhara_registry import (
    list_handles as dhara_list_handles,
)
from mahavishnu.core.worktree_providers.dhara_registry import (
    register_handles,
)
from mahavishnu.core.worktree_providers.dhara_registry import (
    remove_handle as dhara_remove_handle,
)
from mahavishnu.core.worktree_providers.storage_io import (
    compute_sha256,
    deserialize_worktree_tar,
    serialize_worktree_tar,
)
from mahavishnu.observability.bundle_integrity import verify_sha256
from mahavishnu.observability.metrics import (
    record_cache_invalidation,
    record_worktree_op,
)

from .base import WorktreeProvider

if TYPE_CHECKING:
    from oneiric.adapters.storage.azure import AzureBlobStorageAdapter
    from oneiric.adapters.storage.gcs import GCSStorageAdapter
    from oneiric.adapters.storage.s3 import S3StorageAdapter

    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.worktree_providers.local import LocalWorktreeProvider
    from mahavishnu.core.worktree_providers.types import WorktreeHandle, WorktreeRef

logger = logging.getLogger(__name__)


# Default bucket name when the storage adapter doesn't carry one. The
# adapter's ``settings.bucket`` is the canonical source where available
# (S3/GCS), so this fallback is mostly relevant for LocalStorageAdapter
# or unusual deployments.
_DEFAULT_BUCKET = "mahavishnu-worktrees"


def _upload_accepts_metadata(storage: Any) -> bool:
    """Return True iff ``storage.upload`` declares a ``metadata`` keyword.

    Oneiric PR-A added ``metadata=`` to the storage adapters; until that
    ships to the internal index, callers fall back to passing the kwargs
    through unconditionally and let ``TypeError`` surface. We use
    ``inspect.signature`` so a runtime TypeError never propagates out of
    a hot path.
    """
    upload = getattr(storage, "upload", None)
    if upload is None:
        return False
    try:
        sig = inspect.signature(upload)
    except (TypeError, ValueError):  # pragma: no cover - C-implemented callables
        return False
    return "metadata" in sig.parameters


def _storage_supports_exists(storage: Any) -> bool:
    """Return True iff ``storage.exists`` is implemented (post-PR-A).

    Pre-PR-A adapters expose ``download`` only — ``exists`` falls back to
    a try-download-and-catch pattern below.
    """
    return callable(getattr(storage, "exists", None))


async def _storage_exists(storage: Any, key: str) -> bool:
    """Dispatch to ``storage.exists`` if supported; else try-download fallback."""
    if _storage_supports_exists(storage):
        return await storage.exists(key)
    # Fallback: a successful head-conditional download returns bytes (or None
    # for ``404``). Treat None as "does not exist", everything else as
    # "exists" (we don't actually consume the bytes).
    blob = await storage.download(key)
    return blob is not None


async def _storage_upload_with_metadata(
    storage: Any,
    key: str,
    blob: bytes,
    metadata: dict[str, str],
) -> None:
    """Upload ``blob`` to ``key`` with object metadata if the adapter supports it.

    Falls back to a plain ``upload(key, blob)`` when ``metadata=`` is not
    declared on the adapter signature (pre-Oneiric PR-A); callers that
    need object metadata to round-trip should pin to a post-PR-A Oneiric.
    """
    if _upload_accepts_metadata(storage):
        await storage.upload(key, blob, metadata=metadata)
        return
    logger.debug(
        "storage-adapter-missing-metadata-kwarg",
        extra={"key": key},
    )
    await storage.upload(key, blob)


class RemoteWorktreeProvider(WorktreeProvider):
    """v4-era cloud-backed worktree provider.

    Wraps a Oneiric storage adapter (S3, GCS, Azure Blob, or Local) and
    the Dhara-backed worktree registry. ``lock`` delegates to an
    optional :class:`LocalWorktreeProvider` so the same distributed
    ``RedisLockBackend`` is shared between the local and remote paths.

    Storage dispatch is keyed off the handle's ``storage_ref.backend_kind``
    — there is no provider-level "kind" attribute. One provider instance
    can serve multiple buckets / backends if each handle carries its own
    storage_ref (multi-tenant deployments).
    """

    def __init__(
        self,
        *,
        storage: "S3StorageAdapter | GCSStorageAdapter | AzureBlobStorageAdapter",
        cache: WorktreeCache,
        dhara_client: Any | None = None,
        settings: "MahavishnuSettings | None" = None,
        local_provider: "LocalWorktreeProvider | None" = None,
    ) -> None:
        if storage is None:
            raise ValueError("RemoteWorktreeProvider requires a storage adapter")
        if cache is None:
            raise ValueError("RemoteWorktreeProvider requires a WorktreeCache")
        self._storage = storage
        self._cache = cache
        self._dhara_client = dhara_client
        self._settings = settings
        self._local_provider = local_provider
        # Tracks whether the underlying ``upload`` accepts ``metadata=``
        # so we only inspect once per provider instance.
        self._upload_supports_metadata: bool | None = None
        # Tracks whether ``storage.exists`` is implemented so we only
        # ``inspect`` once per provider instance.
        self._storage_has_exists: bool | None = None

    # ------------------------------------------------------------------
    # v1 ABC surface — preserved as Phase-5-deprecation stubs.
    # ------------------------------------------------------------------

    def provider_name(self) -> str:
        return "RemoteWorktreeProvider"

    def health_check(self) -> bool:
        # Synchronous ``health_check`` is the v1 ABC surface; we don't
        # have an async bridge here so we run the coroutine via ``asyncio``
        # only if there's a running loop. When called outside an event
        # loop we surface the last-known storage health, defaulting to
        # False (matches the v1 contract).
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return False  # callers should prefer ``health()`` (async, v4)

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
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 provider."
        )

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 provider."
        )

    # ------------------------------------------------------------------
    # v4 WorktreeHandle-based interface (async)
    # ------------------------------------------------------------------

    async def create_worktree_handle(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal: Principal,
    ) -> "WorktreeHandle":
        """Create a remote-backed WorktreeHandle.

        Validates ``base_ref`` via ``git bundle create`` (raises if the
        ref is unknown), then serializes the repository state via
        ``serialize_worktree_tar`` and uploads the blob with sha256 +
        principal metadata. The handle is registered in Dhara with the
        principal as caller; downstream consumers discover it via
        ``list_handles``.

        SHA-256 / bytes_size are computed eagerly here so the handle
        can be used as an integrity reference on subsequent fetches
        without re-uploading.
        """
        from .types import RemoteWorktreeRef, WorktreeHandle

        start = time.monotonic()
        handle_id = uuid.uuid4().hex
        bucket = self._resolve_bucket()
        key = self._build_key(repo, branch, handle_id)
        backend_kind = self._storage_backend_kind()

        # Step 1: validate base_ref via a throwaway git bundle. The bundle
        # file is a single-file artifact, but the brief calls for
        # ``serialize_worktree_tar`` for the actual upload body so the
        # fetch() path can hydrate a real worktree directory.
        await self._validate_base_ref(repo, base_ref, handle_id)

        # Step 2: serialize the working tree to a tar.gz blob.
        try:
            blob = serialize_worktree_tar(Path(repo))
        except Exception as exc:
            self._record_op("create", start, success=False, backend=backend_kind)
            raise

        sha = compute_sha256(blob)
        metadata = {
            "x-amz-meta-sha256": sha,
            "x-amz-meta-principal": principal.name,
        }

        # Step 3: upload with sha256/principal metadata.
        await _storage_upload_with_metadata(self._storage, key, blob, metadata)

        handle = WorktreeHandle(
            handle_id=handle_id,
            principal=principal,
            repo=repo,
            branch=branch,
            base_ref=base_ref,
            created_at=datetime.now(UTC),
            storage_ref=RemoteWorktreeRef(
                bucket=bucket,
                key=key,
                worktree_id=handle_id,
                backend_kind=backend_kind,  # type: ignore[arg-type]
            ),
            sha256=sha,
            bytes_size=len(blob),
            cleanup_policy=None,
            provenance="v4",
        )

        # Step 4: register the handle in Dhara. ``register_handles``
        # requires the caller to carry scope ``worktree:register`` (or
        # admin). The principal here IS the owner; we pass it as caller
        # so the auth check passes.
        if self._dhara_client is not None:
            try:
                await register_handles(
                    self._dhara_client,
                    [handle],
                    caller=principal,
                )
            except PermissionError:
                # Caller lacks the scope. The handle is still valid;
                # surface to caller for explicit handling.
                self._record_op("create", start, success=False, backend=backend_kind)
                raise

        self._record_op(
            "create",
            start,
            success=True,
            backend=backend_kind,
            principal=principal.name,
        )
        return handle

    async def fetch(self, handle: "WorktreeHandle") -> "WorktreeRef":
        """Materialize a remote handle into a local ``LocalWorktreeRef``.

        Honors a positive cache entry first (``{prefix}{handle_id}:materialized``)
        — when present, no download is performed and the cached path is
        returned. Otherwise downloads the bundle, verifies its SHA-256
        against ``handle.sha256``, materializes the tarball into a
        canonical per-handle directory under the worktree base, and
        populates the cache so subsequent fetches are free.

        Raises:
            NotImplementedError: When ``handle.storage_ref`` is not a
                ``RemoteWorktreeRef`` (e.g. a LocalWorktreeRef fed in by
                mistake).
            WorktreeIntegrityError: When the downloaded blob's SHA-256
                does not match ``handle.sha256``. The
                ``bundle_integrity_failure_total`` counter is incremented
                before the raise.
        """
        from .types import LocalWorktreeRef, RemoteWorktreeRef

        start = time.monotonic()
        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            raise NotImplementedError(
                "RemoteWorktreeProvider.fetch expects a RemoteWorktreeRef; "
                f"got {type(handle.storage_ref).__name__}"
            )
        ref: RemoteWorktreeRef = handle.storage_ref
        backend_kind = ref.backend_kind

        cache_key = f"{handle.handle_id}:materialized"
        cached_path_str = await self._cache.get(cache_key)
        if cached_path_str:
            materialized = Path(str(cached_path_str))
            if materialized.exists():
                self._record_op(
                    "fetch",
                    start,
                    success=True,
                    backend=backend_kind,
                    principal=handle.principal.name,
                )
                return LocalWorktreeRef(
                    path=materialized,
                    worktree_id=handle.handle_id,
                )

        # Cache miss: download + verify + materialize + populate cache.
        blob = await self._storage.download(ref.key)
        if blob is None:
            self._record_op(
                "fetch",
                start,
                success=False,
                backend=backend_kind,
                principal=handle.principal.name,
            )
            raise FileNotFoundError(
                f"Bundle missing in {backend_kind!r} storage at key={ref.key!r}"
            )

        verify_sha256(
            blob,
            handle.sha256,
            backend=backend_kind,
            principal=handle.principal.name,
        )

        target_dir = self._resolve_materialized_path(handle)
        deserialize_worktree_tar(blob, target_dir)

        await self._cache.set(cache_key, str(target_dir))
        self._record_op(
            "fetch",
            start,
            success=True,
            backend=backend_kind,
            principal=handle.principal.name,
        )
        return LocalWorktreeRef(
            path=target_dir,
            worktree_id=handle.handle_id,
        )

    async def remove_handle(self, handle: "WorktreeHandle") -> bool:
        """Remove a handle from storage + cache + Dhara registry.

        Returns ``True`` when the primary Dhara row was deleted, ``False``
        when it was not found (so callers can distinguish "no-op" from
        "deleted"). Best-effort: storage and cache invalidation errors
        are logged but do not abort the Dhara deletion — the registry is
        the source of truth for "is this handle alive?".
        """
        from .types import RemoteWorktreeRef

        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            raise NotImplementedError(
                "RemoteWorktreeProvider.remove_handle expects a RemoteWorktreeRef; "
                f"got {type(handle.storage_ref).__name__}"
            )
        ref: RemoteWorktreeRef = handle.storage_ref
        backend_kind = ref.backend_kind

        # 1. Delete from object storage (best-effort — missing object is OK).
        try:
            await self._storage.delete(ref.key)
        except Exception as exc:  # noqa: BLE001 — boundary; surface + continue
            logger.warning(
                "remote-storage-delete-failed",
                extra={"key": ref.key, "backend": backend_kind, "error": str(exc)},
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

        # 3. Remove from the Dhara registry. ``dhara_remove_handle``
        # returns True iff the primary row was deleted.
        if self._dhara_client is None:
            return False
        return await dhara_remove_handle(
            self._dhara_client,
            handle.handle_id,
            caller=handle.principal,
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
        if caller is None:
            raise PermissionError(
                "RemoteWorktreeProvider.list_handles requires a caller"
            )
        if self._dhara_client is None:
            return []
        return await dhara_list_handles(
            self._dhara_client,
            principal=principal,
            repo=repo,
            caller=caller,
            all_tenants=all_tenants,
        )

    async def exists(self, handle: "WorktreeHandle") -> bool:
        """Return True iff the underlying object exists in remote storage.

        Uses ``storage.exists`` when the adapter supports it (post-Oneiric
        PR-A); otherwise falls back to a ``download`` + ``None`` check.
        Never raises — a missing object is a normal "exists=False".
        """
        from .types import RemoteWorktreeRef

        if not isinstance(handle.storage_ref, RemoteWorktreeRef):
            return False
        ref: RemoteWorktreeRef = handle.storage_ref
        try:
            return await _storage_exists(self._storage, ref.key)
        except Exception as exc:  # noqa: BLE001 — boundary; return False
            logger.warning(
                "remote-exists-check-failed",
                extra={"key": ref.key, "error": str(exc)},
            )
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

    async def health(self) -> bool:
        """Return True iff both storage and cache are healthy."""
        try:
            storage_ok = await self._storage.health()
        except Exception as exc:  # noqa: BLE001 — boundary; report as unhealthy
            logger.warning("remote-storage-health-failed", extra={"error": str(exc)})
            storage_ok = False
        try:
            cache_ok = await self._cache.health()
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning("remote-cache-health-failed", extra={"error": str(exc)})
            cache_ok = False
        return bool(storage_ok and cache_ok)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _storage_backend_kind(self) -> str:
        """Derive the storage backend label for metrics / handle records.

        Prefers an explicit ``backend_kind`` attribute on the adapter
        (set by Oneiric PR-A and by test fakes) so the label is
        unambiguous. Falls back to inspecting the class name (oneiric's
        S3/GCS/Azure adapters embed the kind in their class name); falls
        back to ``"bundle"`` when the class can't be classified.
        """
        explicit = getattr(self._storage, "backend_kind", None)
        if explicit:
            return str(explicit)
        cls_name = type(self._storage).__name__.lower()
        for kind in ("s3", "gcs", "azure", "local"):
            if kind in cls_name:
                return kind
        return "bundle"

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

        Format: ``worktrees/<repo>/<branch>/<handle_id>.tar.gz``. Repo
        slashes are flattened to ``_`` so a key never contains a ``/``
        mid-component that could be misinterpreted by prefix-listing.
        """
        safe_repo = repo.strip("/").replace("/", "_")
        safe_branch = branch.strip("/").replace("/", "_").replace(" ", "_")
        return f"worktrees/{safe_repo}/{safe_branch}/{handle_id}.tar.gz"

    def _resolve_materialized_path(self, handle: "WorktreeHandle") -> Path:
        """Where to extract a fetched bundle on disk.

        Must be inside ``get_worktree_base_path()`` so the Dhara
        registry's path-validation guards (called on subsequent writes)
        accept it. The per-handle subdirectory keeps concurrent fetches
        of distinct handles from clobbering one another.
        """
        base = get_worktree_base_path().resolve()
        target = base / "remote-materialized" / handle.handle_id
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def _validate_base_ref(
        self,
        repo: str,
        base_ref: str,
        handle_id: str,
    ) -> None:
        """Validate ``base_ref`` is resolvable in ``repo`` via a throwaway
        git bundle.

        Best-effort: this step exists to surface "unknown ref" errors
        early so misconfigured callers don't pay for an upload that
        immediately fails downstream. If ``git bundle create`` cannot
        run (no git binary, not a git repo, etc.), we log and continue
        — the actual ``serialize_worktree_tar`` + ``upload`` flow is
        independent of git-bundle validity and will surface its own
        errors if the inputs are unusable.
        """
        from .errors import WorktreeCreationError

        bundle_path = Path("/tmp") / f"{handle_id}.bundle"
        cmd = [
            "git",
            "-C",
            repo,
            "bundle",
            "create",
            str(bundle_path),
            base_ref,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                   )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.debug(
                "git-bundle-skip-no-git-binary",
                extra={"error": str(exc), "base_ref": base_ref},
            )
            return
        _stdout, stderr = await process.communicate()
        try:
            if process.returncode != 0:
                err = stderr.decode() if stderr else "unknown git bundle failure"
                # "Need a repository" / "Not a git repository" are not
                # fatal for the create flow (the bundle step is just an
                # early validator); log and continue.
                if (
                    "not a git repository" in err.lower()
                    or "need a repository" in err.lower()
                ):
                    logger.debug(
                        "git-bundle-skip-non-git-repo",
                        extra={"base_ref": base_ref, "stderr": err.strip()},
                    )
                    return
                raise WorktreeCreationError(
                    f"git bundle create failed for base_ref={base_ref!r}: {err}"
                )
        finally:
            # The bundle is a throwaway — we only use it to validate the
            # ref exists. Clean up unconditionally; failures here are
            # best-effort.
            try:
                bundle_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - filesystem quirk
                pass

    def _record_op(
        self,
        op: str,
        start: float,
        *,
        success: bool,
        backend: str,
        principal: str | None = None,
    ) -> None:
        """Emit ``record_worktree_op`` for the create/fetch histograms."""
        record_worktree_op(
            backend,
            op,
            time.monotonic() - start,
            success=success,
            principal=principal,
        )


__all__ = ["RemoteWorktreeProvider"]
