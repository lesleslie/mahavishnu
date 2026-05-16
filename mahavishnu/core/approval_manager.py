"""Manual approval management for version bumps and publishing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
import uuid

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.dhara import DharaStateBackend


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
    """Manages manual approval workflows for version bumps and publishing.

    Approvals are persisted to Dhara when a DharaStateBackend is provided,
    enabling survival across orchestrator restarts (lookback window).
    """

    def __init__(
        self,
        default_timeout_minutes: int = 1440,  # 24 hours
        dhara_state: DharaStateBackend | None = None,
    ) -> None:
        """Initialize the approval manager.

        Args:
            default_timeout_minutes: Default time before requests expire.
                Defaults to 1440 (24 hours) so approvals survive restarts.
            dhara_state: Optional Dhara backend for durable persistence.
                When provided, each pending approval is written to Dhara
                and deleted on resolution or expiry.
        """
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._default_timeout = timedelta(minutes=default_timeout_minutes)
        self._dhara_state = dhara_state

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
        self._schedule_dhara_persist(request)
        return request

    def _schedule_dhara_persist(self, request: ApprovalRequest) -> None:
        """Fire-and-forget: persist approval to Dhara with a TTL matching expires_at."""
        if self._dhara_state is None:
            return
        ttl = max(int((request.expires_at - datetime.now(UTC)).total_seconds()), 0)
        self._dhara_state.schedule_put(
            f"approval/v1/{request.id}",
            request.to_dict(),
            ttl=ttl if ttl > 0 else None,
        )

    def _schedule_dhara_delete(self, request_id: str) -> None:
        """Fire-and-forget: remove resolved/expired approval from Dhara."""
        if self._dhara_state is None:
            return
        self._dhara_state.schedule_delete(f"approval/v1/{request_id}")

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
            self._schedule_dhara_delete(request_id)
            raise ValueError(f"Request {request_id} has expired")

        del self._pending_requests[request_id]
        self._schedule_dhara_delete(request_id)

        return ApprovalResult(
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

    def cleanup_expired(self) -> int:
        """Remove all expired requests and schedule Dhara cleanup.

        Returns:
            Number of requests removed.
        """
        expired_ids = [req.id for req in self._pending_requests.values() if req.is_expired]
        for req_id in expired_ids:
            del self._pending_requests[req_id]
            self._schedule_dhara_delete(req_id)
        return len(expired_ids)

    def restore_from_dhara_entries(self, entries: list[tuple[str, dict[str, Any]]]) -> int:
        """Re-register non-expired approvals recovered from Dhara on restart.

        Args:
            entries: List of (key, value) pairs from DharaStateBackend.list_prefix.

        Returns:
            Number of approvals successfully restored.
        """
        restored = 0
        for _key, data in entries:
            try:
                request = self._dict_to_request(data)
                if not request.is_expired and request.id not in self._pending_requests:
                    self._pending_requests[request.id] = request
                    restored += 1
            except Exception:
                pass
        return restored

    @staticmethod
    def _dict_to_request(data: dict[str, Any]) -> ApprovalRequest:
        """Deserialize an ApprovalRequest from a Dhara-stored dict."""
        options = [
            ApprovalOption(
                label=opt["label"],
                description=opt["description"],
                is_recommended=opt.get("is_recommended", False),
            )
            for opt in data.get("options", [])
        ]
        return ApprovalRequest(
            id=data["id"],
            approval_type=data["approval_type"],
            context=data.get("context", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            options=options,
        )
