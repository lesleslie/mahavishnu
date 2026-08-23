"""Remote (cloud-backed) worktree provider (ADR 015 v4 §13).

Wraps any of Oneiric's storage adapters (S3, GCS, Azure Blob) to
provide a WorktreeHandle-based interface for non-local worktrees.

This module is a Phase 1 STUB. The real implementation requires:
  - boto3 / google-cloud-storage / azure-storage-blob client wiring
  - Bundle roundtrip via the selected storage adapter
  - SHA-256 integrity check on every fetch
  - Registry of bundle metadata in Dhara (per v4 §11)

The legacy sync ABC methods are not implemented here because
RemoteWorktreeProvider is a v4-era provider; pre-v4 callers should
keep using DirectGitWorktreeProvider / SessionBuddyWorktreeProvider.

Renamed from ``S3WorktreeProvider`` in Phase 1 (ADR 015 v4 §13) to
reflect that the provider is backend-agnostic (it dispatches through
whichever Oneiric storage adapter the deployment configures).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import WorktreeProvider


class RemoteWorktreeProvider(WorktreeProvider):
    """Phase 1 stub for the v4 remote (cloud) worktree provider.

    The async v4 methods (``create_worktree_handle``,
    ``remove_handle``, ``list_handles``, ``exists``, ``lock``,
    ``health``) all raise NotImplementedError until the storage
    integration is implemented in a follow-up.

    ``provider_name`` returns ``"RemoteWorktreeProvider"`` so the
    existing WorktreeProviderRegistry can include it in its fallback
    chain even though no async work is functional yet.
    """

    def __init__(self) -> None:
        self._git_executable = "git"
        # Future: self._storage = Oneiric.storage(...)

    def provider_name(self) -> str:
        return "RemoteWorktreeProvider"

    def health_check(self) -> bool:
        # No remote backend configured yet — health check returns
        # False until the storage adapter is wired up.
        return False

    # Legacy sync ABC methods are inherited (raise NotImplementedError
    # if called) — RemoteWorktreeProvider is a v4-only provider.

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 Phase 1 stub; use "
            "LocalWorktreeProvider or SessionBuddyWorktreeProvider "
            "for legacy sync worktree operations."
        )

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 Phase 1 stub."
        )

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "RemoteWorktreeProvider is a v4 Phase 1 stub."
        )

    # v4 WorktreeHandle-based interface (async)

    async def create_worktree_handle(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal,
    ):
        raise NotImplementedError(
            "RemoteWorktreeProvider.create_worktree_handle() requires "
            "Oneiric storage adapter integration (Phase 1.5 follow-up)."
        )

    async def fetch(self, handle):
        raise NotImplementedError(
            "RemoteWorktreeProvider.fetch() requires Oneiric storage "
            "adapter integration (Phase 1.5 follow-up)."
        )

    async def remove_handle(self, handle) -> None:
        raise NotImplementedError(
            "RemoteWorktreeProvider.remove_handle() requires Oneiric "
            "storage adapter integration (Phase 1.5 follow-up)."
        )

    async def list_handles(
        self,
        principal=None,
        repo: str | None = None,
    ) -> list:
        raise NotImplementedError(
            "RemoteWorktreeProvider.list_handles() requires Oneiric "
            "storage adapter integration (Phase 1.5 follow-up)."
        )

    async def exists(self, handle) -> bool:
        raise NotImplementedError(
            "RemoteWorktreeProvider.exists() requires Oneiric storage "
            "adapter integration (Phase 1.5 follow-up)."
        )

    async def lock(
        self,
        repo: str,
        branch: str,
        *,
        acquire_timeout: float = 10.0,
        lease_ttl: float = 30.0,
    ):
        raise NotImplementedError(
            "RemoteWorktreeProvider.lock() requires Redis; "
            "see ADR 015 v4 §14."
        )

    async def health(self) -> bool:
        return False
