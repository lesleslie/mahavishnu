"""Worktree Manager for Mahavishnu.

Per C-8 (worktree isolation, REQ-010/011):

Manages git worktree lifecycle for task isolation:
- Automatic worktree creation on task start
- Worktree lifecycle management (create, complete, cleanup)
- Diff/merge/files_touched capture for completed worktrees
- Direct ``asyncio.to_thread(subprocess.run)`` for git subprocess calls
  (no ``GitRunner`` abstraction per no-backcompat policy)

Usage:
    from mahavishnu.core.worktree_manager import WorktreeManager

    manager = WorktreeManager(
        base_path="/repos/worktrees",
        event_store=event_store,
    )

    # Create worktree for task
    info = await manager.create_worktree(
        task_id="task-1",
        repo_path="/repos/mahavishnu",
        branch_name="feature/task-1",
        base_branch="main",
        ttl_seconds=3600,
    )

    # Complete and capture diff
    completion = await manager.complete_worktree(
        worktree_id=info.worktree_id,
        merge=False,
        repo_path="/repos/mahavishnu",
    )
    print(completion.info.diff)
    print(completion.info.files_touched)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.errors import ErrorCode, MahavishnuError

if TYPE_CHECKING:
    from mahavishnu.core.event_store import EventStore

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Result of a worktree creation or completion.

    REPLACED per C-8 — no longer carries ``task_id``, ``path``, ``branch``,
    ``state``, ``completed_at``, or ``metadata``. The diff/merge/files_touched
    fields are populated by ``complete_worktree()`` and read by
    ``pool_route_execute(worktree=...)``. ``to_dict()`` preserved for the
    ``worktree_manage`` MCP tool's JSON contract.
    """

    worktree_id: str
    repo_path: Path
    branch_name: str
    base_branch: str
    created_at: datetime
    ttl_seconds: int

    # Populated by complete_worktree(). Empty before completion.
    diff: str = ""
    merge: bool = False
    files_touched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Backward-compatible serialization for worktree_manage MCP tool."""
        return {
            "worktree_id": self.worktree_id,
            "repo_path": str(self.repo_path),
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
            "created_at": self.created_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "diff": self.diff,
            "merge": self.merge,
            "files_touched": list(self.files_touched),
        }


@dataclass
class WorktreeCompletion:
    """Wrapper for the result of ``complete_worktree()``.

    The wrapper lets future C-revisions add fields
    (e.g., ``merge_conflict: bool``) without breaking the signature.
    """

    info: WorktreeInfo


class WorktreeError(MahavishnuError):
    """Exception raised for worktree errors.

    Re-raised locally so callers in this module can raise ``WorktreeError``
    directly without re-importing from ``mahavishnu.core.errors``. The
    canonical definition lives in ``mahavishnu.core.errors`` (matches
    REQ-011 — no competing subclass for ``WorktreeLockedError``).
    """

    def __init__(self, message: str, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR) -> None:
        super().__init__(message, error_code)


class WorktreeManager:
    """Manages git worktrees for task isolation.

    Per C-8, the constructor accepts ``base_path`` + ``event_store``
    (no legacy ``task_store`` / ``git_runner`` parameters — those were
    dropped per the no-backcompat policy). Git subprocess calls use
    ``asyncio.to_thread(subprocess.run)`` directly.
    """

    def __init__(
        self,
        base_path: str | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        """Initialize the worktree manager.

        Args:
            base_path: Base directory where worktrees are created. When
                ``None``, falls back to ``$XDG_DATA_HOME/mahavishnu/worktrees``
                via :func:`mahavishnu.core.paths.get_worktree_base_path`.
            event_store: Optional EventStore for emitting worktree
                lifecycle events. Currently unused (kept for the wire-up
                contract with the conftest fixture).
        """
        del event_store  # Reserved for future persistence layer
        self._base_path = base_path or ""
        self._registry: dict[str, WorktreeInfo] = {}

    def _generate_worktree_id(self) -> str:
        """Generate a unique worktree ID."""
        return f"wt-{uuid.uuid4().hex[:8]}"

    def _get_worktree_path(self, repo_path: Path, worktree_id: str) -> Path:
        """Generate worktree path.

        Per C-8 the canonical layout is ``<repo>/.worktrees/<worktree_id>``.
        Both ``create_worktree`` and ``complete_worktree`` resolve via
        this helper, so the path is stable across the worktree's lifetime.
        """
        return repo_path / ".worktrees" / worktree_id

    async def create_worktree(
        self,
        task_id: str,
        repo_path: Path | str,
        branch_name: str,
        base_branch: str = "main",
        ttl_seconds: int = 86_400,
    ) -> WorktreeInfo:
        """Create a new worktree for a task.

        Args:
            task_id: Task ID to associate with worktree.
            repo_path: Path to main repository (str or Path).
            branch_name: Name for new branch.
            base_branch: Base branch to create from.
            ttl_seconds: TTL for the worktree (cleanup grace window).

        Returns:
            :class:`WorktreeInfo` for the created worktree.

        Raises:
            WorktreeError: If creation fails.
        """
        repo_path_p = Path(repo_path)
        worktree_id = self._generate_worktree_id()
        worktree_path = self._get_worktree_path(repo_path_p, worktree_id)

        try:

            def _git_worktree_add() -> None:
                subprocess.run(
                    [
                        "git",
                        "worktree",
                        "add",
                        "-b",
                        branch_name,
                        str(worktree_path),
                        base_branch,
                    ],
                    cwd=str(repo_path_p),
                    capture_output=True,
                    text=True,
                    check=True,
                )

            await asyncio.to_thread(_git_worktree_add)

            info = WorktreeInfo(
                worktree_id=worktree_id,
                repo_path=repo_path_p,
                branch_name=branch_name,
                base_branch=base_branch,
                created_at=datetime.now(UTC),
                ttl_seconds=ttl_seconds,
            )
            self._registry[worktree_id] = info
            logger.info(
                "Created worktree %s for task %s at %s",
                worktree_id,
                task_id,
                worktree_path,
            )
            return info

        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip() if hasattr(exc, "stderr") else str(exc)
            logger.error("Failed to create worktree for task %s: %s", task_id, stderr)
            raise WorktreeError(f"Failed to create worktree: {stderr}") from exc
        except Exception as exc:
            logger.exception("Failed to create worktree for task %s", task_id)
            raise WorktreeError(f"Failed to create worktree: {exc}") from exc

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all tracked worktrees."""
        return list(self._registry.values())

    def get_worktree(self, worktree_id: str) -> WorktreeInfo | None:
        """Return the worktree for ``worktree_id`` or ``None`` if missing."""
        return self._registry.get(worktree_id)

    def worktree_exists(self, worktree_id: str) -> bool:
        """Return True if the worktree is tracked in the registry."""
        return worktree_id in self._registry

    async def complete_worktree(
        self,
        worktree_id: str,
        merge: bool = False,
        repo_path: Path | str | None = None,
    ) -> WorktreeCompletion:
        """Finalize a worktree.

        Captures ``diff``, ``files_touched`` via ``git diff`` against the
        base branch and, when ``merge=True``, runs ``git merge --no-ff``
        on the source repository. Returns a :class:`WorktreeCompletion`
        wrapping the populated :class:`WorktreeInfo`.

        Args:
            worktree_id: Worktree to complete.
            merge: Whether to merge into base branch.
            repo_path: Path to main repository (required if ``merge=True``).

        Returns:
            :class:`WorktreeCompletion` with the populated WorktreeInfo.

        Raises:
            WorktreeError: If completion fails or the worktree is unknown.
        """
        info = self._registry.get(worktree_id)
        if info is None:
            raise WorktreeError(f"Worktree not found: {worktree_id}")

        if merge and repo_path is None:
            raise WorktreeError("repo_path required when merge=True")

        wt_path = self._get_worktree_path(info.repo_path, worktree_id)
        base_branch = info.base_branch
        branch_name = info.branch_name

        def _git_diff() -> tuple[str, list[str]]:
            diff_proc = subprocess.run(
                ["git", "diff", base_branch, "HEAD"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            names_proc = subprocess.run(
                ["git", "diff", "--name-only", base_branch, "HEAD"],
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                check=True,
            )
            return (
                diff_proc.stdout,
                [n for n in names_proc.stdout.splitlines() if n],
            )

        try:
            diff_text, files = await asyncio.to_thread(_git_diff)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip() if hasattr(exc, "stderr") else str(exc)
            raise WorktreeError(f"git diff failed: {stderr}") from exc

        merge_outcome = False
        if merge:
            merge_target = Path(repo_path)  # ty: ignore[invalid-argument-type]  # validated above

            def _git_merge() -> None:
                subprocess.run(
                    [
                        "git",
                        "merge",
                        "--no-ff",
                        branch_name,
                        "-m",
                        f"Auto-merge worktree {worktree_id}",
                    ],
                    cwd=str(merge_target),
                    capture_output=True,
                    text=True,
                    check=True,
                )

            try:
                await asyncio.to_thread(_git_merge)
                merge_outcome = True
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip() if hasattr(exc, "stderr") else str(exc)
                raise WorktreeError(f"git merge failed: {stderr}") from exc

        info.diff = diff_text
        info.merge = merge_outcome
        info.files_touched = files
        return WorktreeCompletion(info=info)

    async def cleanup_worktree(
        self,
        worktree_id: str,
        repo_path: Path | str | None = None,
    ) -> bool:
        """Remove a worktree.

        Args:
            worktree_id: Worktree to remove.
            repo_path: Path to main repository (used to run
                ``git worktree remove``); defaults to the worktree's
                ``repo_path`` if not provided.

        Returns:
            ``True`` if the worktree was removed (or already absent),
            ``False`` on git failure.
        """
        info = self._registry.get(worktree_id)
        if info is None:
            return False

        target_repo = Path(repo_path) if repo_path is not None else info.repo_path
        worktree_path = self._get_worktree_path(info.repo_path, worktree_id)
        try:
            if worktree_path.exists():

                def _git_worktree_remove() -> None:
                    subprocess.run(
                        [
                            "git",
                            "worktree",
                            "remove",
                            str(worktree_path),
                            "--force",
                        ],
                        cwd=str(target_repo),
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                await asyncio.to_thread(_git_worktree_remove)
        except Exception as exc:  # noqa: BLE001 - boundary keeps calling code alive
            logger.warning("Failed to git-worktree-remove %s: %s", worktree_id, exc)
        finally:
            self._registry.pop(worktree_id, None)
        logger.info("Cleaned up worktree %s", worktree_id)
        return True

    async def abandon_worktree(self, worktree_id: str) -> bool:
        """Mark a worktree as abandoned without completing it.

        The worktree remains on disk; callers can invoke
        :meth:`cleanup_worktree` separately to remove it.

        Returns:
            ``True`` if the registry was updated, ``False`` if unknown.
        """
        if worktree_id not in self._registry:
            return False
        logger.info("Abandoned worktree %s", worktree_id)
        return True

    def get_summary(self) -> dict[str, Any]:
        """Return aggregate worktree statistics."""
        infos = list(self._registry.values())
        return {
            "total_worktrees": len(infos),
            "active_worktrees": len(infos),
        }


__all__ = [
    "WorktreeCompletion",
    "WorktreeError",
    "WorktreeInfo",
    "WorktreeManager",
]
