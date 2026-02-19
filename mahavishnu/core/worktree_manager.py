"""Worktree Manager for Mahavishnu.

Manages git worktree lifecycle for task isolation:
- Automatic worktree creation on task start
- Worktree lifecycle management (create, list, cleanup)
- Worktree-aware task completion
- Branch management and synchronization

Usage:
    from mahavishnu.core.worktree_manager import WorktreeManager

    manager = WorktreeManager(task_store, git_runner, base_path="/repos")

    # Create worktree for task
    worktree = await manager.create_worktree(
        task_id="task-1",
        repo_path="/repos/mahavishnu",
        branch_name="feature/task-1",
    )

    # Complete and cleanup
    await manager.complete_worktree(worktree.worktree_id, merge=True)
    await manager.cleanup_worktree(worktree.worktree_id)
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import TaskStore

logger = logging.getLogger(__name__)


class WorktreeState(str, Enum):
    """State of a worktree."""

    ACTIVE = "active"  # Currently being worked on
    COMPLETED = "completed"  # Work finished, not merged
    ABANDONED = "abandoned"  # Abandoned without merging
    MERGED = "merged"  # Merged into base branch


@dataclass
class WorktreeInfo:
    """Information about a git worktree.

    Attributes:
        worktree_id: Unique identifier for this worktree
        task_id: Associated task ID
        path: Filesystem path to worktree
        branch: Branch name in worktree
        base_branch: Base branch to merge into
        state: Current state of worktree
        created_at: When worktree was created
        completed_at: When worktree was completed/merged
        metadata: Additional metadata
    """

    worktree_id: str
    task_id: str
    path: str
    branch: str
    base_branch: str
    state: WorktreeState
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "worktree_id": self.worktree_id,
            "task_id": self.task_id,
            "path": self.path,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "state": self.state.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }


class WorktreeError(Exception):
    """Exception raised for worktree errors."""

    def __init__(self, message: str, worktree_id: str | None = None) -> None:
        super().__init__(message)
        self.worktree_id = worktree_id


class GitRunner:
    """Simple git command runner using asyncio subprocess."""

    def __init__(self) -> None:
        """Initialize git runner."""
        pass

    async def run(self, *args: str, cwd: str | None = None) -> str:
        """Run a git command safely using asyncio subprocess.

        Args:
            *args: Git command arguments
            cwd: Working directory for command

        Returns:
            Command output

        Raises:
            Exception: If command fails
        """
        cmd = ["git"] + list(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() or f"Git command failed: {' '.join(cmd)}"
            raise Exception(error_msg)

        return stdout.decode().strip()


class WorktreeManager:
    """Manages git worktrees for task isolation.

    Features:
    - Create worktrees for task work
    - Track worktree lifecycle
    - Sync with base branches
    - Cleanup completed worktrees
    - Integration with task completion

    Example:
        manager = WorktreeManager(
            task_store,
            git_runner,
            base_path="/repos/worktrees",
        )

        # Create worktree on task start
        worktree = await manager.create_worktree(
            task_id="task-42",
            repo_path="/repos/mahavishnu",
            branch_name="feature/add-auth",
            base_branch="main",
        )

        # Get status during work
        status = await manager.get_status(worktree.worktree_id)

        # Complete and cleanup
        await manager.complete_worktree(worktree.worktree_id, merge=True)
        await manager.cleanup_worktree(worktree.worktree_id)
    """

    def __init__(
        self,
        task_store: TaskStore,
        git_runner: Any = None,  # GitRunner or mock
        base_path: str = "",
    ) -> None:
        """Initialize the worktree manager.

        Args:
            task_store: TaskStore for task operations
            git_runner: Optional git command runner (creates default if None)
            base_path: Base path for worktrees (default: repo parent + worktrees)
        """
        self.task_store = task_store
        self._git = git_runner or GitRunner()
        self._base_path = base_path
        self._worktrees: dict[str, WorktreeInfo] = {}

    def _generate_worktree_id(self) -> str:
        """Generate a unique worktree ID."""
        return f"wt-{uuid.uuid4().hex[:8]}"

    def _get_worktree_path(self, repo_path: str, task_id: str) -> str:
        """Generate worktree path.

        Args:
            repo_path: Path to main repository
            task_id: Task ID for worktree

        Returns:
            Path for the worktree
        """
        if self._base_path:
            return os.path.join(self._base_path, f"worktree-{task_id}")
        else:
            repo_name = os.path.basename(repo_path)
            parent = os.path.dirname(repo_path)
            return os.path.join(parent, f"{repo_name}-worktree-{task_id}")

    async def create_worktree(
        self,
        task_id: str,
        repo_path: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> WorktreeInfo:
        """Create a new worktree for a task.

        Args:
            task_id: Task ID to associate with worktree
            repo_path: Path to main repository
            branch_name: Name for new branch
            base_branch: Base branch to create from

        Returns:
            WorktreeInfo for created worktree

        Raises:
            WorktreeError: If creation fails
        """
        worktree_id = self._generate_worktree_id()
        worktree_path = self._get_worktree_path(repo_path, task_id)

        try:
            # Create worktree with new branch
            await self._git.run(
                "worktree", "add", "-b", branch_name,
                worktree_path, base_branch,
                cwd=repo_path,
            )

            worktree = WorktreeInfo(
                worktree_id=worktree_id,
                task_id=task_id,
                path=worktree_path,
                branch=branch_name,
                base_branch=base_branch,
                state=WorktreeState.ACTIVE,
                created_at=datetime.now(UTC),
            )

            self._worktrees[worktree_id] = worktree
            logger.info(f"Created worktree {worktree_id} for task {task_id} at {worktree_path}")

            return worktree

        except Exception as e:
            logger.error(f"Failed to create worktree for task {task_id}: {e}")
            raise WorktreeError(f"Failed to create worktree: {e}", worktree_id)

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all tracked worktrees.

        Returns:
            List of WorktreeInfo for all worktrees
        """
        return list(self._worktrees.values())

    def get_worktree_for_task(self, task_id: str) -> WorktreeInfo | None:
        """Get worktree for a specific task.

        Args:
            task_id: Task ID to find worktree for

        Returns:
            WorktreeInfo if found, None otherwise
        """
        for worktree in self._worktrees.values():
            if worktree.task_id == task_id:
                return worktree
        return None

    def get_active_worktrees(self) -> list[WorktreeInfo]:
        """Get all active worktrees.

        Returns:
            List of active WorktreeInfo
        """
        return [
            w for w in self._worktrees.values()
            if w.state == WorktreeState.ACTIVE
        ]

    def worktree_exists(self, worktree_id: str) -> bool:
        """Check if a worktree exists.

        Args:
            worktree_id: Worktree ID to check

        Returns:
            True if worktree exists
        """
        return worktree_id in self._worktrees

    async def complete_worktree(
        self,
        worktree_id: str,
        merge: bool = False,
        repo_path: str | None = None,
    ) -> bool:
        """Mark worktree as completed.

        Args:
            worktree_id: Worktree to complete
            merge: Whether to merge into base branch
            repo_path: Path to main repository (required if merge=True)

        Returns:
            True if successful

        Raises:
            WorktreeError: If completion fails
        """
        worktree = self._worktrees.get(worktree_id)
        if not worktree:
            raise WorktreeError(f"Worktree not found: {worktree_id}", worktree_id)

        try:
            if merge and repo_path:
                # Merge branch into base
                await self._git.run(
                    "checkout", worktree.base_branch,
                    cwd=repo_path,
                )
                await self._git.run(
                    "merge", worktree.branch, "--no-ff", "-m",
                    f"Merge {worktree.branch} into {worktree.base_branch}",
                    cwd=repo_path,
                )
                worktree.state = WorktreeState.MERGED
            else:
                worktree.state = WorktreeState.COMPLETED

            worktree.completed_at = datetime.now(UTC)
            logger.info(f"Completed worktree {worktree_id} (state: {worktree.state.value})")
            return True

        except Exception as e:
            logger.error(f"Failed to complete worktree {worktree_id}: {e}")
            raise WorktreeError(f"Failed to complete worktree: {e}", worktree_id)

    async def abandon_worktree(self, worktree_id: str) -> bool:
        """Abandon a worktree without merging.

        Args:
            worktree_id: Worktree to abandon

        Returns:
            True if successful
        """
        worktree = self._worktrees.get(worktree_id)
        if not worktree:
            return False

        worktree.state = WorktreeState.ABANDONED
        worktree.completed_at = datetime.now(UTC)
        logger.info(f"Abandoned worktree {worktree_id}")
        return True

    async def cleanup_worktree(self, worktree_id: str) -> bool:
        """Remove a worktree.

        Args:
            worktree_id: Worktree to remove

        Returns:
            True if successful
        """
        worktree = self._worktrees.get(worktree_id)
        if not worktree:
            return False

        try:
            # Remove worktree directory
            if os.path.exists(worktree.path):
                # Use git worktree remove
                parent_repo = os.path.dirname(os.path.dirname(worktree.path))
                await self._git.run(
                    "worktree", "remove", worktree.path, "--force",
                    cwd=parent_repo,
                )

            # Remove from tracking
            del self._worktrees[worktree_id]
            logger.info(f"Cleaned up worktree {worktree_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cleanup worktree {worktree_id}: {e}")
            # Still remove from tracking even if git command fails
            if worktree_id in self._worktrees:
                del self._worktrees[worktree_id]
            return False

    async def cleanup_completed(self) -> int:
        """Cleanup all completed/merged worktrees.

        Returns:
            Number of worktrees cleaned up
        """
        cleaned = 0
        to_cleanup = [
            wt_id for wt_id, wt in self._worktrees.items()
            if wt.state in (WorktreeState.COMPLETED, WorktreeState.MERGED, WorktreeState.ABANDONED)
        ]

        for worktree_id in to_cleanup:
            if await self.cleanup_worktree(worktree_id):
                cleaned += 1

        logger.info(f"Cleaned up {cleaned} completed worktrees")
        return cleaned

    async def sync_with_base(self, worktree_id: str) -> bool:
        """Sync worktree branch with base branch.

        Args:
            worktree_id: Worktree to sync

        Returns:
            True if successful
        """
        worktree = self._worktrees.get(worktree_id)
        if not worktree:
            return False

        try:
            # Fetch and merge base branch
            await self._git.run("fetch", "origin", cwd=worktree.path)
            await self._git.run(
                "merge", f"origin/{worktree.base_branch}",
                cwd=worktree.path,
            )
            logger.info(f"Synced worktree {worktree_id} with {worktree.base_branch}")
            return True

        except Exception as e:
            logger.error(f"Failed to sync worktree {worktree_id}: {e}")
            return False

    async def get_status(self, worktree_id: str) -> dict[str, Any] | None:
        """Get status of a worktree.

        Args:
            worktree_id: Worktree to get status for

        Returns:
            Dictionary with status info or None if not found
        """
        worktree = self._worktrees.get(worktree_id)
        if not worktree:
            return None

        try:
            # Get branch info
            branch_output = await self._git.run(
                "branch", "--show-current",
                cwd=worktree.path,
            )

            # Get status
            status_output = await self._git.run(
                "status", "--short",
                cwd=worktree.path,
            )

            # Get ahead/behind count
            ahead_behind = await self._git.run(
                "rev-list", "--left-right", "--count",
                f"{worktree.branch}...{worktree.base_branch}",
                cwd=worktree.path,
            )

            ahead, behind = ahead_behind.strip().split("\t")

            return {
                "worktree_id": worktree_id,
                "branch": branch_output.strip(),
                "base_branch": worktree.base_branch,
                "state": worktree.state.value,
                "modified_files": len(status_output.strip().split("\n")) if status_output.strip() else 0,
                "ahead": int(ahead),
                "behind": int(behind),
                "path": worktree.path,
            }

        except Exception as e:
            logger.error(f"Failed to get status for worktree {worktree_id}: {e}")
            return {
                "worktree_id": worktree_id,
                "error": str(e),
                "state": worktree.state.value,
            }

    async def prune_stale(self) -> int:
        """Prune stale worktree references.

        Returns:
            Number of pruned worktrees
        """
        pruned = 0

        for worktree_id, worktree in list(self._worktrees.items()):
            if not os.path.exists(worktree.path):
                # Directory no longer exists
                del self._worktrees[worktree_id]
                pruned += 1
                logger.info(f"Pruned stale worktree {worktree_id}")

        return pruned

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all worktrees.

        Returns:
            Dictionary with worktree statistics
        """
        total = len(self._worktrees)
        active = sum(1 for w in self._worktrees.values() if w.state == WorktreeState.ACTIVE)
        completed = sum(1 for w in self._worktrees.values() if w.state == WorktreeState.COMPLETED)
        merged = sum(1 for w in self._worktrees.values() if w.state == WorktreeState.MERGED)
        abandoned = sum(1 for w in self._worktrees.values() if w.state == WorktreeState.ABANDONED)

        return {
            "total_worktrees": total,
            "active_worktrees": active,
            "completed_worktrees": completed,
            "merged_worktrees": merged,
            "abandoned_worktrees": abandoned,
        }


__all__ = [
    "WorktreeManager",
    "WorktreeInfo",
    "WorktreeState",
    "WorktreeError",
    "GitRunner",
]
