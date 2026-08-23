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
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from .base import WorktreeProvider
from .errors import WorktreeCreationError, WorktreeOperationError

logger = logging.getLogger(__name__)


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
        settings: "MahavishnuSettings | None" = None,
        storage: "LocalStorageAdapter | None" = None,
        cache: "WorktreeCache | None" = None,
        dhara_client: "Any | None" = None,
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
    ) -> "WorktreeHandle":
        """Create worktree, persist tar.gz bundle, register in Dhara.

        Bundle SHA-256 is computed at create time (NOT lazy) per
        the new v4 contract; ``fetch`` verifies it on read.
        """
        from datetime import UTC, datetime
        import time
        import uuid

        from .dhara_registry import register_handles
        from .storage_io import compute_sha256, serialize_worktree_tar
        from .types import LocalWorktreeRef, WorktreeHandle
        from mahavishnu.core.paths import get_worktree_path
        from mahavishnu.observability.metrics import (
            record_bundle_bytes,
            record_worktree_op,
        )

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
            blob = serialize_worktree_tar(wt_path)
            sha = compute_sha256(blob)
            record_bundle_bytes(repo=repo, byte_size=len(blob))

            if self._storage is not None:
                storage_key = (
                    f"worktrees/{repo}/{branch}/{handle_id}.tar.gz"
                )
                await self._storage.save(storage_key, blob)

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
                sha256=sha,
                bytes_size=len(blob),
                cleanup_policy=None,
                provenance="v4",
            )

            if self._dhara_client is not None:
                await register_handles(
                    self._dhara_client, [handle], caller=principal
                )

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

    async def fetch(self, handle) -> "WorktreeRef":
        """Cache-aside read with SHA-256 verification (§3, §6).

        1. Try cache for materialized path
        2. On miss: read tar.gz from local storage, verify SHA-256,
           extract to ``worktree_base / handle_id``, cache the result
        """
        from .storage_io import deserialize_worktree_tar
        from .types import LocalWorktreeRef
        from mahavishnu.core.errors import WorktreeError
        from mahavishnu.core.paths import get_worktree_base_path
        from mahavishnu.observability.bundle_integrity import verify_sha256
        from mahavishnu.observability.metrics import record_worktree_op
        import time

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only fetch LocalWorktreeRef; got "
                f"{type(handle.storage_ref).__name__}"
            )

        start = time.monotonic()
        cache_key = f"materialized:{handle.handle_id}"
        # 1. Cache hit path
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                path = Path(cached)
                if path.exists():
                    record_worktree_op(
                        backend="local",
                        op="fetch",
                        duration_seconds=time.monotonic() - start,
                        success=True,
                        principal=handle.principal.name,
                    )
                    return LocalWorktreeRef(path=path, worktree_id=handle.handle_id)

        # 2. Cache miss path: read + verify + extract + cache
        try:
            if self._storage is None:
                # No storage adapter — fall back to existing path
                if not handle.storage_ref.path.exists():
                    raise WorktreeError(
                        f"Worktree path does not exist: {handle.storage_ref.path}"
                    )
                record_worktree_op(
                    backend="local",
                    op="fetch",
                    duration_seconds=time.monotonic() - start,
                    success=True,
                    principal=handle.principal.name,
                )
                return handle.storage_ref

            storage_key = (
                f"worktrees/{handle.repo}/{handle.branch}/{handle.handle_id}.tar.gz"
            )
            blob = await self._storage.read(storage_key)
            if blob is None:
                raise WorktreeError(
                    f"No storage blob for handle {handle.handle_id}"
                )
            verify_sha256(
                blob,
                handle.sha256,
                backend="local",
                principal=handle.principal.name,
            )
            target = get_worktree_base_path() / handle.handle_id
            deserialize_worktree_tar(blob, target)
            if self._cache is not None:
                await self._cache.set(cache_key, str(target))
            record_worktree_op(
                backend="local",
                op="fetch",
                duration_seconds=time.monotonic() - start,
                success=True,
                principal=handle.principal.name,
            )
            return LocalWorktreeRef(path=target, worktree_id=handle.handle_id)
        except Exception:
            record_worktree_op(
                backend="local",
                op="fetch",
                duration_seconds=time.monotonic() - start,
                success=False,
                principal=handle.principal.name,
            )
            raise

    async def remove_handle(
        self,
        handle,
        *,
        caller: "Principal",
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
        from .dhara_registry import remove_handle as dhara_remove
        from .types import LocalWorktreeRef
        from mahavishnu.observability.metrics import record_cache_invalidation

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only remove LocalWorktreeRef; got "
                f"{type(handle.storage_ref).__name__}"
            )

        # 1. git worktree remove (idempotent: missing path is fine)
        try:
            await _remove_worktree_via_git(
                self._git_executable,
                Path(handle.repo),
                handle.storage_ref.path,
                force=True,
            )
        except Exception:
            pass

        # 2. Cache invalidate (per-handle prefix)
        if self._cache is not None:
            count = await self._cache.invalidate_handle(handle.handle_id)
            record_cache_invalidation(
                backend="local", reason="remove_handle", count=count
            )

        # 3. Dhara registry remove (best-effort; auth errors propagate)
        if self._dhara_client is not None:
            try:
                await dhara_remove(
                    self._dhara_client,
                    handle.handle_id,
                    caller=caller,
                )
            except PermissionError:
                raise  # auth errors propagate; data errors swallowed

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

            redis_url = os.environ.get(
                "MAHAVISHNU_REDIS_URL", "redis://localhost:6379/0"
            )
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

    async def health(self) -> bool:
        """git + storage + cache probes (combined per §17)."""
        from mahavishnu.observability.metrics import record_backend_health_check_failed

        ok = self.health_check()
        if not ok:
            record_backend_health_check_failed(backend="local")
        if self._storage is not None:
            storage_ok = await self._storage.health()
            if not storage_ok:
                record_backend_health_check_failed(backend="local")
            ok = ok and storage_ok
        if self._cache is not None:
            cache_ok = await self._cache.health()
            if not cache_ok:
                record_backend_health_check_failed(backend="local")
            ok = ok and cache_ok
        return ok


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
            raise WorktreeCreationError(
                f"Failed to create worktree: {error_msg}"
            )
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
            raise WorktreeOperationError(
                f"Failed to remove worktree: {error_msg}"
            )
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
            raise WorktreeOperationError(
                f"Failed to list worktrees: {error_msg}"
            )
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
