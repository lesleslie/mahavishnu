from __future__ import annotations

from mahavishnu.core.worktree_providers.errors import (
    ProviderUnavailableError,
    WorktreeCreationError,
    WorktreeOperationError,
    WorktreeRemovalError,
    WorktreeValidationError,
)


def test_worktree_operation_error_serialization() -> None:
    error = WorktreeOperationError(
        "failed",
        details={"operation": "create"},
        providers=["direct_git", "session_buddy"],
    )

    assert error.message == "failed"
    assert error.details == {"operation": "create"}
    assert error.providers == ["direct_git", "session_buddy"]
    assert error.to_dict() == {
        "error": "failed",
        "error_type": "WorktreeOperationError",
        "details": {"operation": "create"},
        "providers": ["direct_git", "session_buddy"],
    }


def test_worktree_error_subclasses_inherit_base_behavior() -> None:
    creation = WorktreeCreationError("create failed")
    removal = WorktreeRemovalError("remove failed", details={"path": "/tmp/wt"})
    validation = WorktreeValidationError("invalid worktree")
    unavailable = ProviderUnavailableError("no providers")

    assert isinstance(creation, WorktreeOperationError)
    assert isinstance(removal, WorktreeOperationError)
    assert isinstance(validation, WorktreeOperationError)
    assert isinstance(unavailable, WorktreeOperationError)
    assert removal.to_dict()["details"] == {"path": "/tmp/wt"}
