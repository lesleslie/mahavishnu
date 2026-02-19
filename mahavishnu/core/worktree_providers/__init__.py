"""
Worktree provider abstraction layer.

This module enables pluggable worktree backends with graceful degradation:
- SessionBuddyWorktreeProvider (primary, MCP-based)
- DirectGitWorktreeProvider (fallback, subprocess-based)
- MockWorktreeProvider (testing, isolated)

Example:
    >>> from mahavishnu.core.worktree_providers import (
    ...     WorktreeProvider,
    ...     SessionBuddyWorktreeProvider,
    ...     DirectGitWorktreeProvider,
    ...     MockWorktreeProvider,
    ...     WorktreeProviderRegistry,
    ... )
    >>> from pathlib import Path
    >>> providers = [
    ...     SessionBuddyWorktreeProvider(),
    ...     DirectGitWorktreeProvider(),
    ... ]
    >>> registry = WorktreeProviderRegistry(providers)
    >>> provider = await registry.get_available_provider()
"""

from .base import WorktreeProvider
from .direct_git import DirectGitWorktreeProvider
from .errors import (
    ProviderUnavailableError,
    WorktreeCreationError,
    WorktreeOperationError,
    WorktreeRemovalError,
    WorktreeValidationError,
)
from .mock import MockWorktreeProvider
from .registry import WorktreeProviderRegistry
from .session_buddy import SessionBuddyWorktreeProvider

__all__ = [
    # Abstract interface
    "WorktreeProvider",
    # Concrete providers
    "SessionBuddyWorktreeProvider",
    "DirectGitWorktreeProvider",
    "MockWorktreeProvider",
    # Registry
    "WorktreeProviderRegistry",
    # Exceptions
    "WorktreeOperationError",
    "WorktreeCreationError",
    "WorktreeRemovalError",
    "WorktreeValidationError",
    "ProviderUnavailableError",
]
