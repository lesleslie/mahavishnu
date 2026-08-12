"""Tests for path-traversal guards in ``_workflow_id_guard``.

Covers ``validate_approval_id`` and ``validate_webhook_id`` — both
reuse the canonical ``WORKFLOW_ID_PATTERN`` from
:mod:`mahavishnu.mcp.tools._workflow_id_guard` so the rejection cases
mirror each other.
"""

from __future__ import annotations

from mahavishnu.mcp.tools._workflow_id_guard import (
    validate_approval_id,
    validate_webhook_id,
)


class TestValidateApprovalId:
    """Accept server-generated IDs; reject caller-supplied traversal."""

    def test_valid_uuid_hex_fragment_accepted(self) -> None:
        # Server-generated shape from
        # mahavishnu/core/approval_manager.py: ``f"approval-{uuid.uuid4().hex[:8]}"``
        assert validate_approval_id("approval-3f4a1c9b") is True

    def test_valid_dotted_segment_accepted(self) -> None:
        # Pattern allows '.' — useful if a future producer uses dotted IDs.
        assert validate_approval_id("approval.v1.abc") is True

    def test_traversal_double_dot_rejected(self) -> None:
        assert validate_approval_id("../etc/passwd") is False

    def test_forward_slash_rejected(self) -> None:
        assert validate_approval_id("approval/../other") is False

    def test_empty_string_rejected(self) -> None:
        assert validate_approval_id("") is False

    def test_oversized_id_rejected(self) -> None:
        assert validate_approval_id("a" * 129) is False


class TestValidateWebhookId:
    """Same allowlist semantics, mirrored for the webhook read path."""

    def test_valid_uuid_hex_fragment_accepted(self) -> None:
        # Server-generated webhook IDs are uuid hex fragments; the
        # pattern accepts the same shape as approval IDs.
        assert validate_webhook_id("3f4a1c9b8d2e4f1a") is True

    def test_valid_dashed_id_accepted(self) -> None:
        assert validate_webhook_id("webhook-3f4a-1c9b") is True

    def test_traversal_double_dot_rejected(self) -> None:
        assert validate_webhook_id("../../dhara") is False

    def test_forward_slash_rejected(self) -> None:
        assert validate_webhook_id("webhook/../other") is False

    def test_empty_string_rejected(self) -> None:
        assert validate_webhook_id("") is False

    def test_oversized_id_rejected(self) -> None:
        assert validate_webhook_id("a" * 129) is False
