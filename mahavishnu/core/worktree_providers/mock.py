"""Mock worktree provider for safe testing (TEST-001 fix)."""

import logging
from pathlib import Path
from typing import Any

from .base import WorktreeProvider
from .errors import WorktreeCreationError, WorktreeRemovalError

logger = logging.getLogger(__name__)


class MockWorktreeProvider(WorktreeProvider):
    """Mock provider for SAFE testing without real git operations.

    This provider simulates worktree operations without executing any real git commands.
    It's designed for use in tests to prevent data loss and ensure fast, reliable test execution.

    Example:
        >>> provider = MockWorktreeProvider()
        >>> result = await provider.create_worktree(
        ...     Path("/repo"),
        ...     "main",
        ...     Path("/worktrees/repo-main")
        ... )
        >>> assert result["success"]
        >>> assert len(provider.created_worktrees) == 1

    Attributes:
        created_worktrees: List of worktree creation records
        removed_worktrees: List of removed worktree paths
        should_fail: If True, all operations will raise exceptions
    """

    def __init__(self) -> None:
        """Initialize mock provider."""
        self.created_worktrees: list[dict[str, Any]] = []
        self.removed_worktrees: list[str] = []
        self.should_fail: bool = False
        self._is_healthy: bool = True

        logger.debug("MockWorktreeProvider initialized")

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        """Mock worktree creation (safe, no real git operations).

        Args:
            repository_path: Path to the git repository
            branch: Branch name for the worktree
            worktree_path: Path where worktree should be created
            create_branch: Whether to create the branch if it doesn't exist

        Returns:
            Dictionary with creation result

        Raises:
            WorktreeCreationError: If should_fail is True
        """
        if self.should_fail:
            raise WorktreeCreationError(
                message="Mock provider failure",
                details={
                    "repository_path": str(repository_path),
                    "branch": branch,
                    "worktree_path": str(worktree_path),
                },
            )

        # Record the creation (but don't actually create anything)
        self.created_worktrees.append(
            {
                "repository_path": str(repository_path),
                "branch": branch,
                "worktree_path": str(worktree_path),
                "create_branch": create_branch,
            }
        )

        logger.debug(
            f"[MOCK] Created worktree: {worktree_path} (branch={branch}, "
            f"create_branch={create_branch})"
        )

        return {
            "success": True,
            "worktree_path": str(worktree_path),
            "branch": branch,
            "repository_path": str(repository_path),
        }

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        """Mock worktree removal (safe, no real deletions).

        Args:
            repository_path: Path to the git repository
            worktree_path: Path to worktree directory
            force: Force removal (skip safety checks)

        Returns:
            Dictionary with removal result

        Raises:
            WorktreeRemovalError: If should_fail is True
        """
        if self.should_fail:
            raise WorktreeRemovalError(
                message="Mock provider failure",
                details={"worktree_path": str(worktree_path), "force": force},
            )

        # Record the removal (but don't actually delete anything)
        self.removed_worktrees.append(str(worktree_path))

        logger.debug(
            f"[MOCK] Removed worktree: {worktree_path} (force={force})"
        )

        return {
            "success": True,
            "removed_path": str(worktree_path),
            "repository_path": str(repository_path),
        }

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        """Mock worktree listing.

        Args:
            repository_path: Path to the git repository

        Returns:
            Dictionary with list of created worktrees
        """
        # Filter worktrees by repository
        repo_worktrees = [
            wt
            for wt in self.created_worktrees
            if wt["repository_path"] == str(repository_path)
        ]

        return {
            "success": True,
            "worktrees": [
                {"path": wt["worktree_path"], "branch": wt["branch"]}
                for wt in repo_worktrees
            ],
            "repository_path": str(repository_path),
        }

    def health_check(self) -> bool:
        """Mock provider health check.

        Returns:
            True if provider is healthy (not should_fail)
        """
        return self._is_healthy and not self.should_fail

    def provider_name(self) -> str:
        """Get the name of this provider.

        Returns:
            Provider name
        """
        return "mock"

    def set_healthy(self, healthy: bool) -> None:
        """Set health status for testing.

        Args:
            healthy: Whether provider should be healthy
        """
        self._is_healthy = healthy

    def reset(self) -> None:
        """Reset mock provider state.

        Clears all created/removed worktree records and resets failure state.
        """
        self.created_worktrees.clear()
        self.removed_worktrees.clear()
        self.should_fail = False
        self._is_healthy = True

        logger.debug("MockWorktreeProvider reset")
