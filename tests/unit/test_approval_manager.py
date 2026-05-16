"""Tests for the approval manager."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

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


class TestApprovalManagerDharaPersistence:
    """Tests for Dhara-backed durable persistence."""

    def _make_mock_dhara(self) -> MagicMock:
        mock = MagicMock()
        mock.schedule_put = MagicMock()
        mock.schedule_delete = MagicMock()
        return mock

    def test_create_request_schedules_dhara_persist(self) -> None:
        mock_dhara = self._make_mock_dhara()
        manager = ApprovalManager(dhara_state=mock_dhara)
        request = manager.create_request(approval_type="version_bump", context={})
        mock_dhara.schedule_put.assert_called_once()
        args = mock_dhara.schedule_put.call_args[0]
        assert args[0] == f"approval/v1/{request.id}"
        assert args[1]["id"] == request.id

    def test_create_request_without_dhara_does_not_raise(self) -> None:
        manager = ApprovalManager()
        request = manager.create_request(approval_type="publish", context={})
        assert request.id.startswith("approval-")

    def test_respond_schedules_dhara_delete(self) -> None:
        mock_dhara = self._make_mock_dhara()
        manager = ApprovalManager(dhara_state=mock_dhara)
        request = manager.create_request(approval_type="publish", context={})
        mock_dhara.schedule_put.reset_mock()
        manager.respond(request.id, approved=True)
        mock_dhara.schedule_delete.assert_called_once_with(f"approval/v1/{request.id}")

    def test_cleanup_expired_schedules_dhara_delete(self) -> None:
        mock_dhara = self._make_mock_dhara()
        manager = ApprovalManager(dhara_state=mock_dhara)
        expired = ApprovalRequest(
            id="exp-001",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=25),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            options=[],
        )
        manager._pending_requests[expired.id] = expired
        mock_dhara.schedule_put.reset_mock()
        manager.cleanup_expired()
        mock_dhara.schedule_delete.assert_called_once_with("approval/v1/exp-001")

    def test_restore_skips_expired_entries(self) -> None:
        manager = ApprovalManager()
        expired_request = ApprovalRequest(
            id="expired-001",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=25),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            options=[],
        )
        entries = [("approval/v1/expired-001", expired_request.to_dict())]
        restored = manager.restore_from_dhara_entries(entries)
        assert restored == 0
        assert len(manager.pending_requests) == 0

    def test_restore_registers_valid_approvals(self) -> None:
        manager = ApprovalManager()
        valid_request = ApprovalRequest(
            id="valid-001",
            approval_type="publish",
            context={"version": "1.0.0"},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=23),
            options=[ApprovalOption(label="Publish", description="Do it", is_recommended=True)],
        )
        entries = [("approval/v1/valid-001", valid_request.to_dict())]
        restored = manager.restore_from_dhara_entries(entries)
        assert restored == 1
        recovered = manager.get_request("valid-001")
        assert recovered is not None
        assert recovered.approval_type == "publish"
        assert len(recovered.options) == 1

    def test_restore_skips_duplicate_ids(self) -> None:
        manager = ApprovalManager()
        existing = manager.create_request(approval_type="version_bump", context={})
        entry_data = {
            "id": existing.id,
            "approval_type": "publish",
            "context": {},
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "options": [],
        }
        restored = manager.restore_from_dhara_entries([(f"approval/v1/{existing.id}", entry_data)])
        assert restored == 0

    def test_restore_ignores_malformed_entries(self) -> None:
        manager = ApprovalManager()
        entries = [
            ("approval/v1/bad", {"missing": "required fields"}),
            ("approval/v1/also-bad", {}),
        ]
        restored = manager.restore_from_dhara_entries(entries)
        assert restored == 0

    def test_default_timeout_is_24h(self) -> None:
        manager = ApprovalManager()
        request = manager.create_request(approval_type="publish", context={})
        delta = request.expires_at - request.created_at
        assert delta >= timedelta(hours=23, minutes=59)

    def test_respond_nonexistent_request_raises(self) -> None:
        """respond() raises ValueError when request_id is not found (line 225)."""
        manager = ApprovalManager()
        with pytest.raises(ValueError, match="not found"):
            manager.respond("no-such-id", approved=True)

    def test_get_default_options_unknown_type_returns_empty(self) -> None:
        """_get_default_options falls back to [] for unrecognized types (line 196)."""
        manager = ApprovalManager()
        request = manager.create_request(approval_type="unknown_custom_type", context={})
        assert request.options == []
