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
    "BundleRef",
    "DirectGitWorktreeProvider",
    "LocalWorktreeRef",
    "LocalWorktreeProvider",
    "MockWorktreeProvider",
    "ProviderUnavailableError",
    # Concrete providers
    "S3WorktreeRef",
    "SessionBuddyWorktreeProvider",
    "WorktreeCreationError",
    # Exceptions
    "WorktreeOperationError",
    # Abstract interface
    "WorktreeHandle",
    "WorktreeProvider",
    # Registry
    "WorktreeProviderRegistry",
    "WorktreeLock",
    "WorktreeRef",
    "WorktreeRemovalError",
    "WorktreeValidationError",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "WorktreeProvider": (".base", "WorktreeProvider"),
    "WorktreeProviderRegistry": (".registry", "WorktreeProviderRegistry"),
    "WorktreeHandle": (".types", "WorktreeHandle"),
    "WorktreeRef": (".types", "WorktreeRef"),
    "LocalWorktreeRef": (".types", "LocalWorktreeRef"),
    "S3WorktreeRef": (".types", "S3WorktreeRef"),
    "BundleRef": (".types", "BundleRef"),
    "WorktreeLock": (".types", "WorktreeLock"),
    "DirectGitWorktreeProvider": (".local", "DirectGitWorktreeProvider"),
    "LocalWorktreeProvider": (".local", "LocalWorktreeProvider"),
    "MockWorktreeProvider": (".mock", "MockWorktreeProvider"),
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
