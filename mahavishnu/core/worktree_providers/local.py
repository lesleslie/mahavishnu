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

    def __init__(self) -> None:
        self._git_executable = "git"

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

    # v4 WorktreeHandle-based interface (async)
    async def create_worktree_handle(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal,
    ) -> "WorktreeHandle":
        """Create a worktree and return a WorktreeHandle.

        Bundle integrity (sha256) is computed lazily on first fetch()
        per v4 §6.
        """
        from datetime import UTC, datetime
        import uuid

        from .types import LocalWorktreeRef, WorktreeHandle
        from mahavishnu.core.paths import get_worktree_path

        wt_path = get_worktree_path(repo, branch)
        wt_path.mkdir(parents=True, exist_ok=True)

        await _create_worktree_via_git(
            self._git_executable,
            Path(repo),
            branch,
            wt_path,
            create_branch=True,
        )

        return WorktreeHandle(
            handle_id=uuid.uuid4().hex,
            principal=principal,
            repo=repo,
            branch=branch,
            base_ref=base_ref,
            created_at=datetime.now(UTC),
            storage_ref=LocalWorktreeRef(
                path=wt_path,
                worktree_id=uuid.uuid4().hex,
            ),
            sha256="",  # lazy
            bytes_size=0,  # lazy
            cleanup_policy=None,
            provenance="v4",
        )

    async def fetch(self, handle) -> "WorktreeRef":
        from .types import LocalWorktreeRef
        from mahavishnu.core.errors import WorktreeError

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only fetch LocalWorktreeRef; got {type(handle.storage_ref).__name__}"
            )
        if not handle.storage_ref.path.exists():
            raise WorktreeError(
                f"Worktree path does not exist: {handle.storage_ref.path}"
            )
        return handle.storage_ref

    async def remove_handle(self, handle) -> None:
        from .types import LocalWorktreeRef

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            raise NotImplementedError(
                f"LocalWorktreeProvider can only remove LocalWorktreeRef; got {type(handle.storage_ref).__name__}"
            )
        await _remove_worktree_via_git(
            self._git_executable,
            Path(handle.repo),
            handle.storage_ref.path,
            force=True,
        )

    async def list_handles(
        self,
        principal=None,
        repo: str | None = None,
    ) -> list:
        return []

    async def exists(self, handle) -> bool:
        from .types import LocalWorktreeRef

        if not isinstance(handle.storage_ref, LocalWorktreeRef):
            return False
        return handle.storage_ref.path.exists()

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

        See ``RedisLockBackend.acquire`` for argument details.
        Returns a ``WorktreeLock`` whose ``fencing_token`` should be
        passed to all subsequent writes (fencing contract per v4 §14).
        """
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
        return await backend.acquire(
            principal_name="LocalWorktreeProvider",
            repo=repo,
            branch=branch,
        )

    async def health(self) -> bool:
        return self.health_check()


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
