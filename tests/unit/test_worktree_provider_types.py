"""Tests for the v4 WorktreeHandle + provider types (ADR 015 v4 §13)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.local import (
    DirectGitWorktreeProvider,
    LocalWorktreeProvider,
)
from mahavishnu.core.worktree_providers.types import (
    BackendKind,
    BundleRef,
    LocalWorktreeRef,
    RemoteWorktreeRef,
    WorktreeHandle,
    WorktreeLock,
    WorktreeRef,
)

# ----- Principal / cleanup policy -----------------------------------------


def test_principal_from_uid_and_anonymous() -> None:
    p_uid = Principal.from_uid(1000)
    assert p_uid.uid == 1000
    assert p_uid.name == "uid:1000"
    assert not p_uid.is_anonymous

    p_anon = Principal.anonymous()
    assert p_anon.uid is None
    assert p_anon.is_anonymous


# ----- WorktreeRef discriminator -------------------------------------------


def test_local_worktree_ref_backend_kind() -> None:
    ref = LocalWorktreeRef(path=Path("/tmp/wt"), worktree_id="wt-1")
    assert ref.backend_kind == "local"
    assert isinstance(ref, WorktreeRef)


def test_remote_worktree_ref_backend_kind() -> None:
    """Renamed from S3WorktreeRef in Phase 1 (ADR 015 v4 §13).

    ``backend_kind`` is required at construction (no default) — the
    previous hardcoded default of ``"s3"`` silently downgraded gcs/
    azure handles (security review #3). Tests must declare the
    backend explicitly.
    """
    ref = RemoteWorktreeRef(bucket="b", key="k", worktree_id="wt-1", backend_kind="s3")
    assert ref.backend_kind == "s3"
    assert isinstance(ref, WorktreeRef)


# ----- WorktreeHandle roundtrip -------------------------------------------


def test_worktree_handle_construction() -> None:
    p = Principal.from_uid(1000)
    ref = LocalWorktreeRef(path=Path("/tmp/wt"), worktree_id="wt-1")
    h = WorktreeHandle(
        handle_id="h-1",
        principal=p,
        repo="mahavishnu",
        branch="feature/auth",
        base_ref="main",
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        storage_ref=ref,
        sha256="abc123",
        bytes_size=4096,
        cleanup_policy="keep",
        provenance="v4",
    )
    assert h.handle_id == "h-1"
    assert h.principal == p
    assert h.storage_ref is ref
    assert h.cleanup_policy == "keep"
    assert h.provenance == "v4"


# ----- BackendKind literal ------------------------------------------------


def test_backend_kind_literal_includes_core_backends() -> None:
    # MyPy Literal["local", "s3", "gcs", "azure", "bundle"] — verify the
    # canonical set
    assert "local" in BackendKind.__args__
    assert "s3" in BackendKind.__args__
    assert "gcs" in BackendKind.__args__
    assert "azure" in BackendKind.__args__
    assert "bundle" in BackendKind.__args__


# ----- LocalWorktreeProvider class shape ------------------------------------


def test_local_worktree_provider_class_shape() -> None:
    p = LocalWorktreeProvider()
    assert p.provider_name() == "LocalWorktreeProvider"

    # Legacy ABC methods exist
    assert callable(p.health_check)
    assert callable(p.create_worktree)
    assert callable(p.remove_worktree)
    assert callable(p.list_worktrees)

    # v4 methods exist (some are stubs in Phase 1)
    assert callable(p.create_worktree_handle)
    assert callable(p.fetch)
    assert callable(p.remove_handle)
    assert callable(p.list_handles)
    assert callable(p.exists)
    assert callable(p.lock)
    assert callable(p.health)


def test_direct_git_worktree_provider_preserved_as_alias() -> None:
    """DirectGitWorktreeProvider is preserved as a 1-release alias (v4 §1)."""
    p = DirectGitWorktreeProvider()
    assert p.provider_name() == "DirectGitWorktreeProvider"


# ----- Errors (the new exception hierarchy) -------------------------------


def test_worktree_error_hierarchy() -> None:
    from mahavishnu.core.errors import (
        MahavishnuError,
        WorktreeError,
        WorktreeIntegrityError,
        WorktreeLockError,
    )

    assert issubclass(WorktreeError, MahavishnuError)
    assert issubclass(WorktreeLockError, WorktreeError)
    assert issubclass(WorktreeIntegrityError, WorktreeError)


# ----- WorktreeLock dataclass --------------------------------------------


def test_worktree_lock_dataclass() -> None:
    p = Principal.from_uid(1000)
    now = datetime(2026, 8, 23, tzinfo=UTC)
    lock = WorktreeLock(
        acquire_at=now,
        expires_at=now.replace(hour=now.hour + 1),
        owner_principal=p,
        fencing_token=42,
        repo="mahavishnu",
        branch="feature/auth",
    )
    assert lock.fencing_token == 42
    assert lock.owner_principal == p


# ----- BundleRef ----------------------------------------------------------


def test_bundle_ref_construction() -> None:
    b = BundleRef(
        bundle_key="worktrees/mahavishnu/feature.bundle",
        sha256="deadbeef",
        signature=None,
        created_at=datetime(2026, 8, 23, tzinfo=UTC),
        bytes_size=2048,
    )
    assert b.signature is None
    assert b.bytes_size == 2048
