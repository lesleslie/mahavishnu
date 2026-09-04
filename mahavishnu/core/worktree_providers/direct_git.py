"""Direct-git worktree provider (backward-compatible alias).

Historically this submodule lived at ``mahavishnu.core.worktree_providers.direct_git``.
The class was moved to ``mahavishnu.core.worktree_providers.local`` as part of the
worktree-provider refactor, but the legacy import path remains exercised by
the test suite and external callers. This shim re-exports
:class:`DirectGitWorktreeProvider` from its new home so both import paths
work without forcing a production-code rename.
"""

from __future__ import annotations

from mahavishnu.core.worktree_providers.local import (
    DirectGitWorktreeProvider as _LocalDirectGitWorktreeProvider,
)


class DirectGitWorktreeProvider(_LocalDirectGitWorktreeProvider):
    """Legacy import path; subclass exposes ``provider_name`` as a classmethod.

    The historical test contract calls ``DirectGitWorktreeProvider.provider_name()``
    on the class itself. The current instance-method signature accepts ``self``,
    so we override it here with a classmethod variant that delegates to the
    original string. Instantiation behavior is unchanged.
    """

    @classmethod
    def provider_name(cls) -> str:
        return "DirectGitWorktreeProvider"


__all__ = ["DirectGitWorktreeProvider"]
