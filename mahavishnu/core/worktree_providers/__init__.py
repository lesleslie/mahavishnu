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

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "WorktreeProvider": (".base", "WorktreeProvider"),
    "DirectGitWorktreeProvider": (".direct_git", "DirectGitWorktreeProvider"),
    "MockWorktreeProvider": (".mock", "MockWorktreeProvider"),
    "WorktreeProviderRegistry": (".registry", "WorktreeProviderRegistry"),
    "SessionBuddyWorktreeProvider": (".session_buddy", "SessionBuddyWorktreeProvider"),
    "ProviderUnavailableError": (".errors", "ProviderUnavailableError"),
    "WorktreeCreationError": (".errors", "WorktreeCreationError"),
    "WorktreeOperationError": (".errors", "WorktreeOperationError"),
    "WorktreeRemovalError": (".errors", "WorktreeRemovalError"),
    "WorktreeValidationError": (".errors", "WorktreeValidationError"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
