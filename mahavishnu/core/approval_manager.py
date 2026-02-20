"""Manual approval management for version bumps and publishing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
import uuid


@dataclass
class ApprovalOption:
    """An option the user can select in an approval request."""

    label: str
    description: str
    is_recommended: bool = False


@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""

    id: str
    approval_type: Literal["version_bump", "publish"]
    context: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    options: list[ApprovalOption]

    @property
    def is_expired(self) -> bool:
        """Check if this request has expired."""
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "approval_type": self.approval_type,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "is_expired": self.is_expired,
            "options": [
                {
                    "label": opt.label,
                    "description": opt.description,
                    "is_recommended": opt.is_recommended,
                }
                for opt in self.options
            ],
        }


@dataclass
class ApprovalResult:
    """Result of an approval decision."""

    approved: bool
    selected_option: int | None = None
    rejection_reason: str | None = None


class ApprovalManager:
    """Manages manual approval workflows for version bumps and publishing."""

    def __init__(self, default_timeout_minutes: int = 30) -> None:
        """Initialize the approval manager.

        Args:
            default_timeout_minutes: Default time before requests expire.
        """
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._default_timeout = timedelta(minutes=default_timeout_minutes)

    @property
    def pending_requests(self) -> list[ApprovalRequest]:
        """Get all pending requests."""
        return list(self._pending_requests.values())

    def create_request(
        self,
        approval_type: Literal["version_bump", "publish"],
        context: dict[str, Any],
        options: list[ApprovalOption] | None = None,
        timeout_minutes: int | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request.

        Args:
            approval_type: Type of approval needed.
            context: Context data for the approval.
            options: Available options for the user.
            timeout_minutes: Custom timeout (uses default if None).

        Returns:
            The created approval request.
        """
        request_id = f"approval-{uuid.uuid4().hex[:8]}"
        timeout = timedelta(minutes=timeout_minutes) if timeout_minutes else self._default_timeout

        # Generate default options if not provided
        if options is None:
            options = self._generate_default_options(approval_type, context)

        request = ApprovalRequest(
            id=request_id,
            approval_type=approval_type,
            context=context,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timeout,
            options=options,
        )

        self._pending_requests[request.id] = request
        return request

    def _generate_default_options(
        self,
        approval_type: Literal["version_bump", "publish"],
        context: dict[str, Any],
    ) -> list[ApprovalOption]:
        """Generate default options for an approval type."""
        if approval_type == "version_bump":
            current = context.get("current_version", "0.0.0")
            suggested = context.get("suggested_version", "")
            return [
                ApprovalOption(
                    label="Approve patch",
                    description=f"Bump {current} -> {suggested}",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="Minor bump",
                    description="Request minor version bump instead",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not bump version",
                    is_recommended=False,
                ),
            ]
        elif approval_type == "publish":
            return [
                ApprovalOption(
                    label="Publish to PyPI",
                    description="Publish the new version to PyPI",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="GitHub Release",
                    description="Create a GitHub release only",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not publish",
                    is_recommended=False,
                ),
            ]
        return []

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get a pending request by ID."""
        return self._pending_requests.get(request_id)

    def respond(
        self,
        request_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> ApprovalResult:
        """Respond to an approval request.

        Args:
            request_id: ID of the request to respond to.
            approved: Whether the request is approved.
            selected_option: Index of the selected option (if approved).
            rejection_reason: Reason for rejection (if not approved).

        Returns:
            The approval result.

        Raises:
            ValueError: If request not found or expired.
        """
        request = self._pending_requests.get(request_id)
        if request is None:
            raise ValueError(f"Request {request_id} not found")

        if request.is_expired:
            del self._pending_requests[request_id]
            raise ValueError(f"Request {request_id} has expired")

        # Remove from pending
        del self._pending_requests[request_id]

        return ApprovalResult(
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

    def cleanup_expired(self) -> int:
        """Remove all expired requests.

        Returns:
            Number of requests removed.
        """
        expired_ids = [req.id for req in self._pending_requests.values() if req.is_expired]
        for req_id in expired_ids:
            del self._pending_requests[req_id]
        return len(expired_ids)
