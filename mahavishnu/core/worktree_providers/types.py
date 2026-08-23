"""Concrete types for the worktree storage abstraction (ADR 015 v4 §13).

Provides:
  - WorktreeHandle: backend-neutral identifier with provenance
  - WorktreeRef (ABC) + LocalWorktreeRef / S3WorktreeRef: backend-typed refs
  - BundleRef: bundle metadata (key, sha256, size)
  - WorktreeLock: distributed-lock record
  - BackendKind: Literal type for backend discrimination

These types are the v4 contract; they are imported by
``mahavishnu.core.worktree_providers`` and by external code that
needs to construct or pass worktree handles.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from mahavishnu.auth import CleanupPolicy, Principal

# Discriminator for WorktreeRef. Typed via Literal (not StrEnum) for
# compatibility with @dataclass(frozen=True, slots=True) inheritance
# from WorktreeRef(ABC).
BackendKind = Literal["local", "s3", "gcs", "azure", "bundle"]


@dataclass(frozen=True, slots=True)
class WorktreeHandle:
    """Backend-neutral worktree identifier.

    Carries enough metadata to resolve to a WorktreeRef via
    ``LocalWorktreeProvider.fetch`` / ``S3WorktreeProvider.fetch``.
    """

    handle_id: str
    principal: Principal
    repo: str
    branch: str
    base_ref: str
    created_at: datetime
    storage_ref: WorktreeRef
    sha256: str  # empty for pre-v4 worktrees; lazily computed
    bytes_size: int  # 0 for pre-v4; lazily computed
    cleanup_policy: CleanupPolicy | None = None
    provenance: str = "v4"


class WorktreeRef(ABC):
    """Backend-typed reference to a stored worktree.

    Subclasses MUST override ``backend_kind`` so callers can do
    discriminated-union narrowing via ``isinstance`` or
    ``runtime_checkable``.
    """

    @property
    @abstractmethod
    def backend_kind(self) -> str: ...


@dataclass(frozen=True, slots=True)
class LocalWorktreeRef(WorktreeRef):
    path: Path
    worktree_id: str

    @property
    def backend_kind(self) -> str:
        return "local"


@dataclass(frozen=True, slots=True)
class RemoteWorktreeRef(WorktreeRef):
    """Reference to a worktree stored on a remote (non-local) backend.

    Wraps any of Oneiric's storage adapters: S3, GCS, Azure Blob, or
    even a remote-mounted filesystem that exposes the same byte-store
    interface. The literal ``bucket`` and ``key`` fields map onto each
    adapter's underlying identifier (S3 bucket/key, GCS bucket/object,
    Azure container/blob, etc.).

    Renamed from ``S3WorktreeRef`` in Phase 1 (ADR 015 v4 §13) to
    reflect that the provider wraps *any* Oneiric storage adapter, not
    just S3. ``backend_kind`` carries the actual backend identity
    (``"s3"``, ``"gcs"``, ``"azure"``, ``"bundle"``) — round-trips
    through ``dhara_registry`` preserve this field exactly so a gcs
    handle never silently downgrades to ``"s3"``.

    The default of ``"s3"`` is retained for backward compatibility with
    callers that construct a ``RemoteWorktreeRef`` without specifying
    the backend (e.g. legacy code paths, tests). New code SHOULD pass
    the explicit backend kind at construction.
    """

    bucket: str
    key: str
    worktree_id: str
    backend_kind: BackendKind = "s3"


@dataclass(frozen=True, slots=True)
class BundleRef:
    """Bundle metadata for a single git-bundle.

    Stored alongside the bundle (S3 object metadata ``x-amz-meta-sha256``)
    or in Dhara for the worktree-registry record.
    """

    bundle_key: str
    sha256: str
    signature: str | None
    created_at: datetime
    bytes_size: int


@dataclass(frozen=True, slots=True)
class WorktreeLock:
    """Distributed-lock record returned by ``WorktreeProvider.lock()``."""

    acquire_at: datetime
    expires_at: datetime
    owner_principal: Principal
    fencing_token: int
    repo: str
    branch: str


__all__ = [
    "BackendKind",
    "BundleRef",
    "LocalWorktreeRef",
    "RemoteWorktreeRef",
    "WorktreeHandle",
    "WorktreeLock",
    "WorktreeRef",
]
