"""Tests for the approval manager."""

from datetime import UTC, datetime, timedelta

import pytest

from mahavishnu.core.approval_manager import (
    ApprovalManager,
    ApprovalOption,
    ApprovalRequest,
)


class TestApprovalRequest:
    """Test ApprovalRequest model."""

    def test_create_version_bump_request(self) -> None:
        """Test creating a version bump approval request."""
        request = ApprovalRequest(
            id="approval-001",
            approval_type="version_bump",
            context={
                "current_version": "0.24.2",
                "suggested_version": "0.24.3",
                "bump_type": "patch",
            },
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            options=[
                ApprovalOption(
                    label="Approve patch",
                    description="Bump 0.24.2 -> 0.24.3",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="Minor bump",
                    description="Bump 0.24.2 -> 0.25.0",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not bump version",
                    is_recommended=False,
                ),
            ],
        )

        assert request.id == "approval-001"
        assert request.approval_type == "version_bump"
        assert len(request.options) == 3
        assert request.options[0].is_recommended is True

    def test_request_expired(self) -> None:
        """Test checking if request is expired."""
        request = ApprovalRequest(
            id="approval-002",
            approval_type="publish",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )

        assert request.is_expired is True

    def test_request_not_expired(self) -> None:
        """Test checking if request is not expired."""
        request = ApprovalRequest(
            id="approval-003",
            approval_type="publish",
            context={},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            options=[],
        )

        assert request.is_expired is False


class TestApprovalManager:
    """Test ApprovalManager class."""

    @pytest.fixture
    def manager(self) -> ApprovalManager:
        """Create approval manager instance."""
        return ApprovalManager()

    def test_create_approval_request(self, manager: ApprovalManager) -> None:
        """Test creating an approval request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={
                "current_version": "0.24.2",
                "suggested_version": "0.24.3",
            },
        )

        assert request.id.startswith("approval-")
        assert request.approval_type == "version_bump"
        assert request.is_expired is False
        assert request in manager.pending_requests

    def test_get_pending_request(self, manager: ApprovalManager) -> None:
        """Test retrieving a pending request."""
        request = manager.create_request(
            approval_type="publish",
            context={"version": "0.24.3"},
        )

        retrieved = manager.get_request(request.id)
        assert retrieved == request

    def test_get_nonexistent_request(self, manager: ApprovalManager) -> None:
        """Test retrieving a nonexistent request."""
        retrieved = manager.get_request("nonexistent-id")
        assert retrieved is None

    def test_respond_to_request_approve(self, manager: ApprovalManager) -> None:
        """Test approving a request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={"suggested_version": "0.24.3"},
            options=[
                ApprovalOption(label="Approve", description="Approve", is_recommended=True),
            ],
        )

        result = manager.respond(request.id, approved=True, selected_option=0)

        assert result.approved is True
        assert result.selected_option == 0
        assert request not in manager.pending_requests

    def test_respond_to_request_reject(self, manager: ApprovalManager) -> None:
        """Test rejecting a request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={},
        )

        result = manager.respond(request.id, approved=False)

        assert result.approved is False
        assert request not in manager.pending_requests

    def test_respond_to_expired_request(self, manager: ApprovalManager) -> None:
        """Test responding to an expired request raises error."""
        request = ApprovalRequest(
            id="expired-request",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )
        manager._pending_requests[request.id] = request

        with pytest.raises(ValueError, match="expired"):
            manager.respond(request.id, approved=True)

    def test_cleanup_expired_requests(self, manager: ApprovalManager) -> None:
        """Test cleaning up expired requests."""
        # Create an expired request directly
        expired = ApprovalRequest(
            id="expired",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )
        manager._pending_requests[expired.id] = expired

        # Create a valid request
        valid = manager.create_request(approval_type="publish", context={})

        manager.cleanup_expired()

        assert expired not in manager.pending_requests
        assert valid in manager.pending_requests
