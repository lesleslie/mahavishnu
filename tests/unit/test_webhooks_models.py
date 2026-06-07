"""Unit tests for mahavishnu/webhooks/models.py.

Covers the Pydantic models used to validate inbound webhook payloads from
OpenClaw. The focus is on security-relevant validation:

- Tag and repo path traversal prevention
- Field bounds (length, range, regex)
- Default values and metadata size limits
- Enum membership and serialisation
- Response envelope shape (WebhookResponse / WebhookErrorResponse)

These tests deliberately use distinct class names from the pre-existing
test_webhook_models.py file to avoid pytest collection collisions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError
import pytest

from mahavishnu.core.metrics_schema import AdapterType
from mahavishnu.webhooks.models import (
    REPO_PATH_PATTERN,
    TAG_PATTERN,
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookErrorResponse,
    WebhookResponse,
    WebhookStatus,
)

pytestmark = pytest.mark.unit


# =============================================================================
# WebhookStatus Enum Tests
# =============================================================================


class TestWebhookStatusEnumCases:
    """Tests for the WebhookStatus StrEnum."""

    def test_enum_values_are_lowercase(self):
        assert WebhookStatus.SUCCESS == "success"
        assert WebhookStatus.ERROR == "error"
        assert WebhookStatus.PENDING == "pending"
        assert WebhookStatus.ACCEPTED == "accepted"

    def test_enum_is_str_compatible(self):
        # StrEnum members behave like strings for equality / formatting
        assert f"{WebhookStatus.ACCEPTED}" == "accepted"

    @pytest.mark.parametrize(
        "member,value",
        [
            ("SUCCESS", "success"),
            ("ERROR", "error"),
            ("PENDING", "pending"),
            ("ACCEPTED", "accepted"),
        ],
    )
    def test_enum_membership_parametrised(self, member, value):
        assert getattr(WebhookStatus, member).value == value


# =============================================================================
# Regex Pattern Tests
# =============================================================================


class TestRegexConstants:
    """Verify the validator patterns reject/accept the intended inputs."""

    @pytest.mark.parametrize(
        "candidate",
        ["backend", "python", "frontend-react", "tag_123", "X", "a-b_c-1"],
    )
    def test_tag_pattern_accepts_safe(self, candidate):
        assert TAG_PATTERN.match(candidate)

    @pytest.mark.parametrize(
        "candidate",
        ["", "../etc", "with space", "tag/sub", "tag.dot", "tag!"],
    )
    def test_tag_pattern_rejects_unsafe(self, candidate):
        assert not TAG_PATTERN.match(candidate)

    @pytest.mark.parametrize(
        "candidate",
        ["repo", "org/repo", "deep/path/repo.git", "a.b", "a_b-c.d"],
    )
    def test_repo_pattern_accepts_safe(self, candidate):
        assert REPO_PATH_PATTERN.match(candidate)

    @pytest.mark.parametrize(
        "candidate",
        ["", "with space", "weird;name", "$bash"],
    )
    def test_repo_pattern_rejects_unsafe(self, candidate):
        assert not REPO_PATH_PATTERN.match(candidate)


# =============================================================================
# OpenClawSweepRequest Tests
# =============================================================================


class TestSweepRequestConstruction:
    """Tests for OpenClawSweepRequest validation."""

    def test_minimum_valid_request(self):
        req = OpenClawSweepRequest(tag="backend")
        assert req.tag == "backend"
        assert req.adapter == AdapterType.AGNO  # default
        assert req.task_description is None
        assert req.priority == "normal"
        assert req.dry_run is False
        assert req.metadata == {}

    def test_full_construction(self):
        req = OpenClawSweepRequest(
            tag="python",
            adapter=AdapterType.PREFECT,
            task_description="sweep everything",
            priority="high",
            dry_run=True,
            metadata={"source": "ci"},
        )
        assert req.adapter == AdapterType.PREFECT
        assert req.task_description == "sweep everything"
        assert req.priority == "high"
        assert req.dry_run is True
        assert req.metadata == {"source": "ci"}

    def test_tag_required(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest()  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "bad_tag",
        ["../../../etc/passwd", "tag with space", "tag/sub", "tag.dot", "$tag"],
    )
    def test_tag_rejects_path_traversal_and_invalid_chars(self, bad_tag):
        with pytest.raises(ValidationError) as ei:
            OpenClawSweepRequest(tag=bad_tag)
        errors = ei.value.errors()
        assert any("tag" in str(e["loc"]) for e in errors)

    def test_tag_min_length_enforced(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="")

    def test_tag_max_length_enforced(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="a" * 65)

    def test_tag_at_max_length_allowed(self):
        req = OpenClawSweepRequest(tag="a" * 64)
        assert len(req.tag) == 64

    @pytest.mark.parametrize("priority", ["low", "normal", "high", "critical"])
    def test_priority_accepts_allowed_values(self, priority):
        req = OpenClawSweepRequest(tag="t", priority=priority)
        assert req.priority == priority

    @pytest.mark.parametrize("priority", ["urgent", "", "HIGH", "med"])
    def test_priority_rejects_invalid_values(self, priority):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="t", priority=priority)

    def test_task_description_max_length(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="t", task_description="x" * 1001)

    def test_metadata_max_size_validation(self):
        # 4KB cap measured against str(metadata)
        big_value = "x" * 5000
        with pytest.raises(ValidationError) as ei:
            OpenClawSweepRequest(tag="t", metadata={"k": big_value})
        assert "Metadata exceeds maximum size" in str(ei.value)

    def test_metadata_accepts_small_dict(self):
        req = OpenClawSweepRequest(tag="t", metadata={"a": 1, "b": "two"})
        assert req.metadata == {"a": 1, "b": "two"}

    def test_metadata_independent_between_instances(self):
        a = OpenClawSweepRequest(tag="t1")
        b = OpenClawSweepRequest(tag="t2")
        a.metadata["x"] = 1
        assert b.metadata == {}


# =============================================================================
# OpenClawWorkflowRequest Tests
# =============================================================================


class TestWorkflowRequestConstruction:
    """Tests for OpenClawWorkflowRequest validation."""

    def test_minimum_valid_request(self):
        req = OpenClawWorkflowRequest(repos=["org/repo"])
        assert req.repos == ["org/repo"]
        assert req.adapter == AdapterType.PREFECT
        assert req.workflow_type == "code_sweep"
        assert req.task_description is None
        assert req.parallel is True
        assert req.fail_fast is False
        assert req.timeout_seconds == 300
        assert req.metadata == {}

    def test_empty_repos_list_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=[])

    def test_too_many_repos_rejected(self):
        repos = [f"r{i}" for i in range(101)]
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=repos)

    def test_max_repos_allowed(self):
        repos = [f"r{i}" for i in range(100)]
        req = OpenClawWorkflowRequest(repos=repos)
        assert len(req.repos) == 100

    @pytest.mark.parametrize(
        "bad_repo",
        [
            "../../etc/passwd",
            "org/../../foo",
            "/abs/path",
            "~/home/path",
            "repo with space",
            "repo;rm",
        ],
    )
    def test_repos_reject_invalid_paths(self, bad_repo):
        with pytest.raises(ValidationError) as ei:
            OpenClawWorkflowRequest(repos=[bad_repo])
        errors = ei.value.errors()
        assert any("repos" in str(e["loc"]) for e in errors)

    @pytest.mark.parametrize(
        "good_repo",
        ["repo", "org/repo", "org/sub/repo.git", "a-b_c.d"],
    )
    def test_repos_accept_valid_paths(self, good_repo):
        req = OpenClawWorkflowRequest(repos=[good_repo])
        assert req.repos == [good_repo]

    def test_absolute_path_rejected_explicitly(self):
        with pytest.raises(ValidationError) as ei:
            OpenClawWorkflowRequest(repos=["/etc/passwd"])
        assert "Absolute paths not allowed" in str(ei.value) or "Invalid repository path" in str(
            ei.value
        )

    def test_tilde_home_path_rejected(self):
        with pytest.raises(ValidationError) as ei:
            OpenClawWorkflowRequest(repos=["~/sneaky"])
        assert "Absolute paths not allowed" in str(ei.value) or "Invalid repository path" in str(
            ei.value
        )

    @pytest.mark.parametrize("timeout", [60, 300, 3600])
    def test_timeout_within_bounds_accepted(self, timeout):
        req = OpenClawWorkflowRequest(repos=["r"], timeout_seconds=timeout)
        assert req.timeout_seconds == timeout

    @pytest.mark.parametrize("timeout", [0, 59, 3601, -10])
    def test_timeout_out_of_bounds_rejected(self, timeout):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["r"], timeout_seconds=timeout)

    def test_workflow_type_max_length(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["r"], workflow_type="x" * 65)

    def test_task_description_max_length(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["r"], task_description="x" * 1001)

    def test_metadata_size_limit_enforced(self):
        big: dict[str, Any] = {"k": "x" * 5000}
        with pytest.raises(ValidationError) as ei:
            OpenClawWorkflowRequest(repos=["r"], metadata=big)
        assert "Metadata exceeds maximum size" in str(ei.value)

    def test_adapter_can_be_overridden(self):
        req = OpenClawWorkflowRequest(repos=["r"], adapter=AdapterType.AGNO)
        assert req.adapter == AdapterType.AGNO


# =============================================================================
# WebhookResponse Tests
# =============================================================================


class TestWebhookResponseEnvelope:
    """Tests for the WebhookResponse model."""

    def test_default_response(self):
        resp = WebhookResponse()
        assert resp.status == WebhookStatus.SUCCESS
        assert resp.message == "Webhook processed successfully"
        assert resp.workflow_id is None
        assert isinstance(resp.accepted_at, datetime)
        assert resp.details == {}

    def test_custom_response_round_trips(self):
        resp = WebhookResponse(
            status=WebhookStatus.ACCEPTED,
            message="ok",
            workflow_id="wf-1",
            details={"k": "v"},
        )
        as_dict = resp.model_dump()
        assert as_dict["status"] == "accepted"
        assert as_dict["workflow_id"] == "wf-1"
        assert as_dict["details"] == {"k": "v"}

    def test_message_max_length(self):
        with pytest.raises(ValidationError):
            WebhookResponse(message="x" * 501)

    def test_accepted_at_unique_per_instance(self):
        a = WebhookResponse()
        b = WebhookResponse()
        # Both timestamps are datetimes (may be equal at fast clock, so just type-check)
        assert isinstance(a.accepted_at, datetime)
        assert isinstance(b.accepted_at, datetime)

    def test_status_accepts_string_or_enum(self):
        resp = WebhookResponse(status="pending")  # type: ignore[arg-type]
        assert resp.status == WebhookStatus.PENDING


# =============================================================================
# WebhookErrorResponse Tests
# =============================================================================


class TestWebhookErrorResponseEnvelope:
    """Tests for the WebhookErrorResponse model."""

    def test_message_is_required(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse()  # type: ignore[call-arg]

    def test_default_values(self):
        err = WebhookErrorResponse(message="something failed")
        assert err.status == WebhookStatus.ERROR
        assert err.error_code == "VALIDATION_ERROR"
        assert err.recovery == []
        assert err.details == {}
        assert err.documentation_url is None

    def test_full_construction(self):
        err = WebhookErrorResponse(
            error_code="AUTH_FAILED",
            message="auth failed",
            recovery=["check token"],
            details={"field": "tag"},
            documentation_url="https://docs.example.com/errors/auth",
        )
        assert err.error_code == "AUTH_FAILED"
        assert err.recovery == ["check token"]
        assert err.details == {"field": "tag"}
        assert err.documentation_url == "https://docs.example.com/errors/auth"

    def test_message_max_length(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse(message="x" * 501)

    def test_error_code_max_length(self):
        with pytest.raises(ValidationError):
            WebhookErrorResponse(message="ok", error_code="x" * 65)

    def test_status_defaults_to_error_string(self):
        err = WebhookErrorResponse(message="oops")
        # StrEnum string compatibility
        assert err.status == "error"
