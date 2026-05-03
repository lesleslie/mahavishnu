"""Tests for webhook Pydantic models and validation.

Covers:
- WebhookStatus enum values
- OpenClawSweepRequest: valid creation, defaults, tag validation, priority,
  metadata size limits
- OpenClawWorkflowRequest: valid creation, repo list bounds, path traversal
  prevention, absolute path rejection, timeout bounds, metadata size limits
- WebhookResponse: defaults and custom values
- WebhookErrorResponse: required fields and defaults
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from mahavishnu.core.metrics_schema import AdapterType
from mahavishnu.webhooks.models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookErrorResponse,
    WebhookResponse,
    WebhookStatus,
)

# =============================================================================
# WebhookStatus Tests
# =============================================================================


class TestWebhookStatus:
    """Test WebhookStatus enum values and string behaviour."""

    def test_enum_values(self):
        assert WebhookStatus.SUCCESS == "success"
        assert WebhookStatus.ERROR == "error"
        assert WebhookStatus.PENDING == "pending"
        assert WebhookStatus.ACCEPTED == "accepted"

    def test_all_members_present(self):
        expected = {"SUCCESS", "ERROR", "PENDING", "ACCEPTED"}
        actual = {m.name for m in WebhookStatus}
        assert actual == expected

    def test_is_str_subclass(self):
        assert isinstance(WebhookStatus.SUCCESS, str)


# =============================================================================
# OpenClawSweepRequest Tests
# =============================================================================


class TestOpenClawSweepRequest:
    """Test OpenClawSweepRequest model creation and validation."""

    # -- Valid creation -------------------------------------------------------

    def test_valid_minimal(self):
        req = OpenClawSweepRequest(tag="backend")
        assert req.tag == "backend"
        assert req.adapter == AdapterType.AGNO
        assert req.task_description is None
        assert req.priority == "normal"
        assert req.dry_run is False
        assert req.metadata == {}

    def test_valid_all_fields(self):
        req = OpenClawSweepRequest(
            tag="python",
            adapter="prefect",
            task_description="Run quality sweep",
            priority="high",
            dry_run=True,
            metadata={"source": "ci"},
        )
        assert req.tag == "python"
        assert req.adapter == AdapterType.PREFECT
        assert req.task_description == "Run quality sweep"
        assert req.priority == "high"
        assert req.dry_run is True
        assert req.metadata == {"source": "ci"}

    def test_adapter_accepts_enum_value(self):
        req = OpenClawSweepRequest(tag="test", adapter=AdapterType.LLAMAINDEX)
        assert req.adapter == AdapterType.LLAMAINDEX

    def test_tag_with_underscores_and_hyphens(self):
        req = OpenClawSweepRequest(tag="frontend-react_v2")
        assert req.tag == "frontend-react_v2"

    # -- Tag validation -------------------------------------------------------

    def test_tag_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="path traversal"):
            OpenClawSweepRequest(tag="../../../etc/passwd")

    def test_tag_with_slashes_rejected(self):
        with pytest.raises(ValidationError, match="Invalid tag"):
            OpenClawSweepRequest(tag="back/end")

    def test_tag_with_spaces_rejected(self):
        with pytest.raises(ValidationError, match="Invalid tag"):
            OpenClawSweepRequest(tag="back end")

    def test_tag_with_special_chars_rejected(self):
        with pytest.raises(ValidationError, match="Invalid tag"):
            OpenClawSweepRequest(tag="back@end")

    def test_empty_tag_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="")

    def test_tag_too_long_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="a" * 65)

    def test_tag_at_max_length_accepted(self):
        req = OpenClawSweepRequest(tag="a" * 64)
        assert len(req.tag) == 64

    def test_tag_single_char_accepted(self):
        req = OpenClawSweepRequest(tag="x")
        assert req.tag == "x"

    # -- Priority validation --------------------------------------------------

    def test_valid_priorities(self):
        for prio in ("low", "normal", "high", "critical"):
            req = OpenClawSweepRequest(tag="test", priority=prio)
            assert req.priority == prio

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="test", priority="urgent")

    def test_empty_priority_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="test", priority="")

    # -- Metadata validation --------------------------------------------------

    def test_metadata_within_limit(self):
        req = OpenClawSweepRequest(
            tag="test",
            metadata={"key": "a" * 4000},
        )
        assert "key" in req.metadata

    def test_metadata_exceeds_4kb_rejected(self):
        large_value = "x" * 4097
        with pytest.raises(ValidationError, match="4KB"):
            OpenClawSweepRequest(tag="test", metadata={"payload": large_value})

    # -- Task description validation ------------------------------------------

    def test_task_description_too_long_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="test", task_description="d" * 1001)

    def test_task_description_at_max_length(self):
        req = OpenClawSweepRequest(tag="test", task_description="d" * 1000)
        assert len(req.task_description) == 1000


# =============================================================================
# OpenClawWorkflowRequest Tests
# =============================================================================


class TestOpenClawWorkflowRequest:
    """Test OpenClawWorkflowRequest model creation and validation."""

    # -- Valid creation -------------------------------------------------------

    def test_valid_minimal(self):
        req = OpenClawWorkflowRequest(repos=["mahavishnu/mahavishnu"])
        assert req.repos == ["mahavishnu/mahavishnu"]
        assert req.adapter == AdapterType.PREFECT
        assert req.workflow_type == "code_sweep"
        assert req.task_description is None
        assert req.parallel is True
        assert req.fail_fast is False
        assert req.timeout_seconds == 300
        assert req.metadata == {}

    def test_valid_all_fields(self):
        req = OpenClawWorkflowRequest(
            repos=["org/repo-a", "org/repo-b"],
            adapter="agno",
            workflow_type="security_scan",
            task_description="Run security scan across repos",
            parallel=False,
            fail_fast=True,
            timeout_seconds=600,
            metadata={"trigger": "schedule"},
        )
        assert len(req.repos) == 2
        assert req.adapter == AdapterType.AGNO
        assert req.workflow_type == "security_scan"
        assert req.parallel is False
        assert req.fail_fast is True
        assert req.timeout_seconds == 600

    # -- Repo list bounds -----------------------------------------------------

    def test_empty_repos_list_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=[])

    def test_too_many_repos_rejected(self):
        repos = [f"org/repo-{i}" for i in range(101)]
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=repos)

    def test_max_repos_accepted(self):
        repos = [f"org/repo-{i}" for i in range(100)]
        req = OpenClawWorkflowRequest(repos=repos)
        assert len(req.repos) == 100

    # -- Path traversal prevention --------------------------------------------

    def test_repo_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="path traversal"):
            OpenClawWorkflowRequest(repos=["../../../etc/passwd"])

    def test_repo_double_dot_rejected(self):
        with pytest.raises(ValidationError, match="path traversal"):
            OpenClawWorkflowRequest(repos=["org/.."])

    def test_repo_with_spaces_rejected(self):
        with pytest.raises(ValidationError, match="Invalid repository path"):
            OpenClawWorkflowRequest(repos=["org/my repo"])

    def test_repo_with_special_chars_rejected(self):
        with pytest.raises(ValidationError, match="Invalid repository path"):
            OpenClawWorkflowRequest(repos=["org/repo;rm -rf"])

    # -- Absolute path prevention ---------------------------------------------

    def test_absolute_path_slash_rejected(self):
        with pytest.raises(ValidationError, match="Absolute paths not allowed"):
            OpenClawWorkflowRequest(repos=["/etc/passwd"])

    def test_absolute_path_tilde_rejected(self):
        """Tilde paths fail the REPO_PATH_PATTERN regex since ~ is not an
        allowed character, so the error message references the pattern check
        rather than the explicit absolute-path guard."""
        with pytest.raises(ValidationError, match="Invalid repository path"):
            OpenClawWorkflowRequest(repos=["~/secret"])

    # -- Timeout bounds -------------------------------------------------------

    def test_timeout_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["org/repo"], timeout_seconds=59)

    def test_timeout_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["org/repo"], timeout_seconds=3601)

    def test_timeout_at_minimum(self):
        req = OpenClawWorkflowRequest(repos=["org/repo"], timeout_seconds=60)
        assert req.timeout_seconds == 60

    def test_timeout_at_maximum(self):
        req = OpenClawWorkflowRequest(repos=["org/repo"], timeout_seconds=3600)
        assert req.timeout_seconds == 3600

    # -- Metadata validation --------------------------------------------------

    def test_metadata_exceeds_4kb_rejected(self):
        large_value = "y" * 4097
        with pytest.raises(ValidationError, match="4KB"):
            OpenClawWorkflowRequest(repos=["org/repo"], metadata={"payload": large_value})

    # -- Workflow type validation ---------------------------------------------

    def test_workflow_type_too_long_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["org/repo"], workflow_type="w" * 65)

    def test_workflow_type_at_max_length(self):
        req = OpenClawWorkflowRequest(repos=["org/repo"], workflow_type="w" * 64)
        assert len(req.workflow_type) == 64


# =============================================================================
# WebhookResponse Tests
# =============================================================================


class TestWebhookResponse:
    """Test WebhookResponse model defaults and custom values."""

    def test_defaults(self):
        resp = WebhookResponse()
        assert resp.status == WebhookStatus.SUCCESS
        assert resp.message == "Webhook processed successfully"
        assert resp.workflow_id is None
        assert isinstance(resp.accepted_at, datetime)
        assert resp.details == {}

    def test_custom_values(self):
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        resp = WebhookResponse(
            status=WebhookStatus.ACCEPTED,
            message="Sweep initiated",
            workflow_id="wf-abc123",
            accepted_at=ts,
            details={"repos_count": 5, "adapter": "agno"},
        )
        assert resp.status == WebhookStatus.ACCEPTED
        assert resp.message == "Sweep initiated"
        assert resp.workflow_id == "wf-abc123"
        assert resp.accepted_at == ts
        assert resp.details["repos_count"] == 5

    def test_accepted_at_is_utc(self):
        resp = WebhookResponse()
        assert resp.accepted_at.tzinfo == UTC

    def test_message_max_length(self):
        resp = WebhookResponse(message="m" * 500)
        assert len(resp.message) == 500

    def test_message_exceeds_max_rejected(self):
        with pytest.raises(ValidationError):
            WebhookResponse(message="m" * 501)


# =============================================================================
# WebhookErrorResponse Tests
# =============================================================================


class TestWebhookErrorResponse:
    """Test WebhookErrorResponse model required fields and defaults."""

    def test_required_fields(self):
        err = WebhookErrorResponse(message="Something went wrong")
        assert err.status == WebhookStatus.ERROR
        assert err.error_code == "VALIDATION_ERROR"
        assert err.message == "Something went wrong"
        assert err.recovery == []
        assert err.details == {}
        assert err.documentation_url is None

    def test_custom_values(self):
        err = WebhookErrorResponse(
            status=WebhookStatus.ERROR,
            error_code="PATH_TRAVERSAL",
            message="Invalid tag format",
            recovery=["Use alphanumeric characters only"],
            details={"field": "tag", "value": "../../../etc/passwd"},
            documentation_url="https://docs.mahavishnu.org/errors/validation",
        )
        assert err.error_code == "PATH_TRAVERSAL"
        assert err.message == "Invalid tag format"
        assert len(err.recovery) == 1
        assert err.details["field"] == "tag"
        assert err.documentation_url == ("https://docs.mahavishnu.org/errors/validation")

    def test_status_always_defaults_to_error(self):
        err = WebhookErrorResponse(message="fail")
        assert err.status == WebhookStatus.ERROR

    def test_error_code_max_length(self):
        err = WebhookErrorResponse(message="fail", error_code="E" * 64)
        assert len(err.error_code) == 64

    def test_error_code_exceeds_max_rejected(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse(message="fail", error_code="E" * 65)

    def test_message_max_length(self):
        err = WebhookErrorResponse(message="e" * 500)
        assert len(err.message) == 500

    def test_message_exceeds_max_rejected(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse(message="e" * 501)

    def test_message_is_required(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse()
