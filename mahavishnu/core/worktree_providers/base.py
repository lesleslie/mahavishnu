"""Abstract worktree provider interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .errors import (
    WorktreeCreationError,
    WorktreeOperationError,
    WorktreeRemovalError,
    WorktreeValidationError,
)


class WorktreeProvider(ABC):
    """Abstract interface for worktree operations.

    This interface defines the contract that all worktree providers must implement.
    It enables pluggable backends with automatic fallback for resilience.

    Implementations:
        SessionBuddyWorktreeProvider: Primary provider using Session-Buddy MCP
        DirectGitWorktreeProvider: Fallback provider using subprocess git commands
        MockWorktreeProvider: Testing provider with no real git operations
    """

    @abstractmethod
    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        """Create a worktree.

        Args:
            repository_path: Path to the git repository
            branch: Branch name for the worktree
            worktree_path: Path where worktree should be created
            create_branch: Whether to create the branch if it doesn't exist

        Returns:
            Dictionary with:
                - success (bool): Whether creation succeeded
                - worktree_path (str): Path to created worktree
                - branch (str): Branch name
                - error (str | None): Error message if failed

        Raises:
            WorktreeOperationError: If creation fails
        """
        pass

    @abstractmethod
    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        """Remove a worktree.

        Args:
            repository_path: Path to the git repository
            worktree_path: Path to worktree directory
            force: Force removal (skip safety checks)

        Returns:
            Dictionary with:
                - success (bool): Whether removal succeeded
                - removed_path (str): Path to removed worktree
                - error (str | None): Error message if failed

        Raises:
            WorktreeOperationError: If removal fails
        """
        pass

    @abstractmethod
    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        """List all worktrees for a repository.

        Args:
            repository_path: Path to the git repository

        Returns:
            Dictionary with:
                - success (bool): Whether list succeeded
                - worktrees (list): List of worktree dicts with 'path' and 'branch'
                - error (str | None): Error message if failed

        Raises:
            WorktreeOperationError: If listing fails
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if provider is available and healthy.

        Returns:
            True if provider is healthy and can be used, False otherwise
        """
        pass

    @abstractmethod
    def provider_name(self) -> str:
        """Get the name of this provider.

        Returns:
            Provider name (e.g., "session-buddy", "direct-git", "mock")
        """
        pass
