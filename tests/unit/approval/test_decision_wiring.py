"""Verify ApprovalManager.respond() wires record_approval_decision into the
existing decision flow (replaces the legacy delete-on-resolve branch).

Per M-APPROVAL-LOG Task 3: every approval resolution must persist an
ApprovalLog via the producer from Task 1, with the legacy delete-on-resolve
branch gated behind the APPROVAL_LOG_V1_ENABLED feature flag.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.approval_manager import (
    ApprovalManager,
    ApprovalOption,
    ApprovalRequest,
)


@pytest.fixture
def manager_with_pending_request() -> tuple[ApprovalManager, MagicMock, ApprovalRequest]:
    """ApprovalManager wired to a mock Dhara backend with one pending request."""
    mock_dhara = MagicMock()
    mock_dhara.schedule_put = MagicMock()
    mock_dhara.schedule_delete = MagicMock()
    manager = ApprovalManager(dhara_state=mock_dhara)
    request = manager.create_request(approval_type="publish", context={})
    mock_dhara.schedule_put.reset_mock()
    return manager, mock_dhara, request


def test_respond_calls_record_approval_decision_with_mapped_args(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approved path: respond() must invoke record_approval_decision with
    decision="approved" and the request id as approval_id."""
    manager, _mock_dhara, request = manager_with_pending_request

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "true")

    with patch(
        "mahavishnu.core.approval_manager.record_approval_decision",
    ) as mock_writer:
        manager.respond(request.id, approved=True, selected_option=1)

    mock_writer.assert_called_once()
    call_kwargs = mock_writer.call_args.kwargs
    assert call_kwargs["approval_id"] == request.id
    assert call_kwargs["decision"] == "approved"
    # rationale falls back to "" when no rejection_reason provided
    assert call_kwargs["rationale"] == ""
    assert call_kwargs["decided_by"] == "system"
    metadata = call_kwargs["metadata"]
    assert metadata["selected_option"] == 1


def test_respond_calls_record_approval_decision_with_denied_on_rejection(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Denied path: decision="denied", rationale carries rejection_reason."""
    manager, _mock_dhara, request = manager_with_pending_request

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "true")

    with patch(
        "mahavishnu.core.approval_manager.record_approval_decision",
    ) as mock_writer:
        manager.respond(
            request.id,
            approved=False,
            rejection_reason="Coverage below threshold",
        )

    mock_writer.assert_called_once()
    call_kwargs = mock_writer.call_args.kwargs
    assert call_kwargs["decision"] == "denied"
    assert call_kwargs["rationale"] == "Coverage below threshold"


def test_respond_uses_actor_from_request_context(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the request context carries a 'decided_by' actor, it propagates."""
    manager, mock_dhara, _ = manager_with_pending_request
    request = manager.create_request(
        approval_type="version_bump",
        context={"decided_by": "alice@example.com"},
    )
    mock_dhara.schedule_put.reset_mock()

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "true")

    with patch(
        "mahavishnu.core.approval_manager.record_approval_decision",
    ) as mock_writer:
        manager.respond(request.id, approved=True)

    mock_writer.assert_called_once()
    assert mock_writer.call_args.kwargs["decided_by"] == "alice@example.com"


def test_respond_does_not_schedule_dhara_delete_when_flag_enabled(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When APPROVAL_LOG_V1_ENABLED=true, the legacy delete-on-resolve branch
    must NOT fire — history is now persisted by the producer, not deleted."""
    manager, mock_dhara, request = manager_with_pending_request

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "true")

    with patch("mahavishnu.core.approval_manager.record_approval_decision"):
        manager.respond(request.id, approved=True)

    mock_dhara.schedule_delete.assert_not_called()


def test_respond_still_deletes_when_flag_disabled(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback path: APPROVAL_LOG_V1_ENABLED=false restores the legacy
    delete-on-resolve behavior; the producer is NOT invoked."""
    manager, mock_dhara, request = manager_with_pending_request

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "false")

    with patch("mahavishnu.core.approval_manager.record_approval_decision") as mock_writer:
        manager.respond(request.id, approved=True)

    mock_dhara.schedule_delete.assert_called_once_with(f"approval/v1/{request.id}")
    mock_writer.assert_not_called()


def test_respond_on_expired_request_still_deletes_when_flag_disabled(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired path also honors the feature flag."""
    manager, mock_dhara, _ = manager_with_pending_request
    expired = ApprovalRequest(
        id="exp-wired",
        approval_type="version_bump",
        context={},
        created_at=datetime.now(UTC) - timedelta(hours=25),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        options=[ApprovalOption(label="Approve", description="ok")],
    )
    manager._pending_requests[expired.id] = expired

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "false")

    with patch("mahavishnu.core.approval_manager.record_approval_decision") as mock_writer:
        with pytest.raises(ValueError, match="expired"):
            manager.respond(expired.id, approved=True)

    mock_dhara.schedule_delete.assert_called_once_with(f"approval/v1/{expired.id}")
    mock_writer.assert_not_called()


def test_cleanup_expired_still_deletes_when_flag_disabled(
    manager_with_pending_request: tuple[ApprovalManager, MagicMock, ApprovalRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cleanup_expired is an admin op — must keep deleting regardless of flag
    (it does not persist a structured ApprovalLog; only live resolutions do)."""
    manager, mock_dhara, _ = manager_with_pending_request
    expired = ApprovalRequest(
        id="cleanup-expired",
        approval_type="version_bump",
        context={},
        created_at=datetime.now(UTC) - timedelta(hours=25),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        options=[],
    )
    manager._pending_requests[expired.id] = expired

    monkeypatch.setenv("APPROVAL_LOG_V1_ENABLED", "false")

    manager.cleanup_expired()

    mock_dhara.schedule_delete.assert_called_once_with("approval/v1/cleanup-expired")
