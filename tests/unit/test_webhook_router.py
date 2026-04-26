"""Comprehensive unit tests for mahavishnu/webhooks/router.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mahavishnu.core.errors import AuthenticationError
from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.webhooks.models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookStatus,
)
from mahavishnu.webhooks.router import (
    webhook_router,
    validate_auth,
    sweep_endpoint,
    workflow_endpoint,
    webhook_health,
)


def _make_request(scope_type="http"):
    scope = {
        "type": scope_type,
        "method": "POST",
        "headers": [],
        "query_string": b"",
        "path": "/openclaw/sweep",
    }
    return Request(scope=scope)


class TestWebhookRouterModuleAttributes:
    """Verify module-level exports and router configuration."""

    def test_webhook_router_is_api_router(self):
        assert webhook_router.prefix == "/openclaw"
        assert "webhooks" in webhook_router.tags
        assert "openclaw" in webhook_router.tags

    def test_router_has_expected_routes(self):
        paths = {route.path for route in webhook_router.routes}
        assert "/openclaw/sweep" in paths
        assert "/openclaw/workflow" in paths
        assert "/openclaw/health" in paths

    def test_router_response_models_configured(self):
        paths = {route.path: route for route in webhook_router.routes}
        sweep = paths["/openclaw/sweep"]
        assert "POST" in sweep.methods
        workflow = paths["/openclaw/workflow"]
        assert "POST" in workflow.methods
        health = paths["/openclaw/health"]
        assert "GET" in health.methods


class TestValidateAuth:
    """Tests for the validate_auth dependency."""

    @pytest.mark.asyncio
    async def test_valid_authentication_returns_result(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": True,
            "user": "testuser",
            "method": "subscription",
        }

        with patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler):
            result = await validate_auth("Bearer valid-token")
            assert result["authenticated"] is True
            assert result["user"] == "testuser"

    @pytest.mark.asyncio
    async def test_unauthenticated_result_raises_401(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": False,
        }

        with (
            patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler),
            pytest.raises(HTTPException) as exc_info,
        ):
            await validate_auth("Bearer bad-token")

        assert exc_info.value.status_code == 401
        detail = exc_info.value.detail
        assert detail["error_code"] == "AUTHENTICATION_ERROR"

    @pytest.mark.asyncio
    async def test_authentication_error_raises_401_with_details(self):
        auth_error = AuthenticationError(
            message="Token expired",
            details={"reason": "exp claim exceeded"},
        )
        mock_handler = MagicMock()
        mock_handler.authenticate_request.side_effect = auth_error

        with (
            patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler),
            pytest.raises(HTTPException) as exc_info,
        ):
            await validate_auth("Bearer expired-token")

        assert exc_info.value.status_code == 401
        detail = exc_info.value.detail
        assert detail["error_code"] == "AUTHENTICATION_ERROR"
        assert "expired" in detail["message"].lower()
        assert "recovery" in detail

    @pytest.mark.asyncio
    async def test_auth_error_detail_contains_recovery_steps(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": False,
        }

        with (
            patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler),
            pytest.raises(HTTPException) as exc_info,
        ):
            await validate_auth("Bearer bad-token")

        detail = exc_info.value.detail
        assert isinstance(detail["recovery"], list)
        assert len(detail["recovery"]) > 0

    @pytest.mark.asyncio
    async def test_auth_error_from_exception_contains_details(self):
        auth_error = AuthenticationError(
            message="Invalid signature",
            details={"token_type": "subscription"},
        )
        mock_handler = MagicMock()
        mock_handler.authenticate_request.side_effect = auth_error

        with (
            patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler),
            pytest.raises(HTTPException) as exc_info,
        ):
            await validate_auth("Bearer invalid-token")

        detail = exc_info.value.detail
        assert "details" in detail
        assert detail["details"]["token_type"] == "subscription"

    @pytest.mark.asyncio
    async def test_auth_handler_is_called(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": True,
            "user": "caller",
        }

        with (
            patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler) as mock_get_handler,
        ):
            await validate_auth("Bearer some-token")
            mock_get_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_request_called_with_correct_token(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": True,
            "user": "u1",
        }

        with patch("mahavishnu.webhooks.router.get_auth_handler", return_value=mock_handler):
            await validate_auth("Bearer my-secret-token")
            mock_handler.authenticate_request.assert_called_once_with("Bearer my-secret-token")


class TestSweepEndpoint:
    """Tests for the /openclaw/sweep POST endpoint."""

    def _make_sweep_request(self, **kwargs):
        defaults = {
            "tag": "backend",
            "adapter": AdapterType.AGNO,
        }
        defaults.update(kwargs)
        return OpenClawSweepRequest(**defaults)

    @pytest.mark.asyncio
    async def test_sweep_returns_accepted_status(self):
        sweep_req = self._make_sweep_request()
        request = _make_request()
        auth_result = {"authenticated": True, "user": "testuser"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.AGNO,
            AdapterType.PREFECT,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            unwrapped = sweep_endpoint.__wrapped__ if hasattr(sweep_endpoint, "__wrapped__") else sweep_endpoint
            try:
                response = await unwrapped(request, sweep_req, auth_result)
            except TypeError:
                response = await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        assert response.status == WebhookStatus.ACCEPTED
        assert "sweep" in response.message.lower()
        assert "backend" in response.message

    @pytest.mark.asyncio
    async def test_sweep_generates_workflow_id(self):
        sweep_req = self._make_sweep_request(tag="python")
        request = _make_request()
        auth_result = {"authenticated": True, "user": "devuser"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.BATCH_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        assert response.workflow_id is not None
        assert "wf-sweep-" in response.workflow_id
        assert "python" in response.workflow_id

    @pytest.mark.asyncio
    async def test_sweep_classifies_intent_with_task_description(self):
        task_desc = "Run security scan across backend repositories"
        sweep_req = self._make_sweep_request(task_description=task_desc)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user1"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.CRITICAL_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        mock_task_router.classify_intent.assert_called_once_with(task_desc)

    @pytest.mark.asyncio
    async def test_sweep_classifies_intent_without_task_description(self):
        sweep_req = self._make_sweep_request(tag="frontend", task_description=None)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user2"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.AGNO]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        mock_task_router.classify_intent.assert_called_once_with("sweep frontend repositories")

    @pytest.mark.asyncio
    async def test_sweep_generates_fallback_chain_with_preferred_adapter(self):
        sweep_req = self._make_sweep_request(adapter=AdapterType.PREFECT)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user3"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.PREFECT,
            AdapterType.AGNO,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        mock_task_router.generate_fallback_chain.assert_called_once_with(
            TaskType.WORKFLOW,
            preferred_adapter=AdapterType.PREFECT,
        )

    @pytest.mark.asyncio
    async def test_sweep_response_contains_expected_details(self):
        sweep_req = self._make_sweep_request(
            tag="devops",
            adapter=AdapterType.LLAMAINDEX,
            dry_run=True,
        )
        request = _make_request()
        auth_result = {"authenticated": True, "user": "ops-user"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.BATCH_TASK
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.LLAMAINDEX,
            AdapterType.AGNO,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        details = response.details
        assert details["tag"] == "devops"
        assert details["adapter"] == "llamaindex"
        assert details["dry_run"] is True
        assert details["user"] == "ops-user"
        assert "task_type" in details
        assert "fallback_chain" in details

    @pytest.mark.asyncio
    async def test_sweep_calls_get_pool_manager(self):
        sweep_req = self._make_sweep_request()
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user4"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.AGNO]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager") as mock_pool_fn,
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)
            mock_pool_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_sweep_with_unknown_user(self):
        sweep_req = self._make_sweep_request()
        request = _make_request()
        auth_result = {"authenticated": True}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.AGNO]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        assert "unknown" in response.workflow_id

    @pytest.mark.asyncio
    async def test_sweep_fallback_chain_in_response_details(self):
        sweep_req = self._make_sweep_request(adapter=AdapterType.AGNO)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user5"}
        expected_chain = [AdapterType.AGNO, AdapterType.LLAMAINDEX]
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = expected_chain

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await sweep_endpoint.__wrapped__(request, sweep_req, auth_result)

        assert response.details["fallback_chain"] == ["agno", "llamaindex"]


class TestWorkflowEndpoint:
    """Tests for the /openclaw/workflow POST endpoint."""

    def _make_workflow_request(self, **kwargs):
        defaults = {
            "repos": ["repo-a", "repo-b"],
            "adapter": AdapterType.PREFECT,
        }
        defaults.update(kwargs)
        return OpenClawWorkflowRequest(**defaults)

    @pytest.mark.asyncio
    async def test_workflow_returns_accepted_status(self):
        wf_req = self._make_workflow_request()
        request = _make_request()
        auth_result = {"authenticated": True, "user": "testuser"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        assert response.status == WebhookStatus.ACCEPTED
        assert "workflow" in response.message.lower()

    @pytest.mark.asyncio
    async def test_workflow_generates_workflow_id(self):
        wf_req = self._make_workflow_request()
        request = _make_request()
        auth_result = {"authenticated": True, "user": "wfuser"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        assert response.workflow_id is not None
        assert "wf-workflow-" in response.workflow_id

    @pytest.mark.asyncio
    async def test_workflow_classifies_intent_with_description(self):
        task_desc = "Run full integration test suite"
        wf_req = self._make_workflow_request(task_description=task_desc)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user1"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.BATCH_TASK
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        mock_task_router.classify_intent.assert_called_once_with(task_desc)

    @pytest.mark.asyncio
    async def test_workflow_classifies_intent_without_description(self):
        wf_req = self._make_workflow_request(repos=["repo-x"], task_description=None)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user2"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        mock_task_router.classify_intent.assert_called_once_with("workflow for 1 repos")

    @pytest.mark.asyncio
    async def test_workflow_response_contains_expected_details(self):
        wf_req = self._make_workflow_request(
            repos=["alpha", "beta", "gamma"],
            adapter=AdapterType.AGNO,
            parallel=False,
            timeout_seconds=600,
        )
        request = _make_request()
        auth_result = {"authenticated": True, "user": "devuser"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.AGNO,
            AdapterType.LLAMAINDEX,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        details = response.details
        assert details["repos"] == ["alpha", "beta", "gamma"]
        assert details["repos_count"] == 3
        assert details["adapter"] == "agno"
        assert details["parallel"] is False
        assert details["timeout_seconds"] == 600
        assert details["user"] == "devuser"

    @pytest.mark.asyncio
    async def test_workflow_generates_fallback_chain(self):
        wf_req = self._make_workflow_request(adapter=AdapterType.LLAMAINDEX)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user3"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.RAG_QUERY
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.LLAMAINDEX,
            AdapterType.AGNO,
            AdapterType.PREFECT,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        assert response.details["fallback_chain"] == [
            "llamaindex",
            "agno",
            "prefect",
        ]

    @pytest.mark.asyncio
    async def test_workflow_calls_get_pool_manager(self):
        wf_req = self._make_workflow_request()
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user4"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager") as mock_pool_fn,
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await workflow_endpoint.__wrapped__(request, wf_req, auth_result)
            mock_pool_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_workflow_with_single_repo(self):
        wf_req = self._make_workflow_request(repos=["solo-repo"])
        request = _make_request()
        auth_result = {"authenticated": True, "user": "solo-user"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.WORKFLOW
        mock_task_router.generate_fallback_chain.return_value = [AdapterType.PREFECT]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            response = await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        assert response.details["repos_count"] == 1
        assert "1 repositories" in response.message

    @pytest.mark.asyncio
    async def test_workflow_generates_fallback_with_preferred_adapter(self):
        wf_req = self._make_workflow_request(adapter=AdapterType.AGNO)
        request = _make_request()
        auth_result = {"authenticated": True, "user": "user5"}
        mock_task_router = MagicMock()
        mock_task_router.classify_intent.return_value = TaskType.AI_TASK
        mock_task_router.generate_fallback_chain.return_value = [
            AdapterType.AGNO,
            AdapterType.PREFECT,
        ]

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=mock_task_router),
            patch("mahavishnu.webhooks.router.rate_limit", lambda x: lambda f: f),
        ):
            await workflow_endpoint.__wrapped__(request, wf_req, auth_result)

        mock_task_router.generate_fallback_chain.assert_called_once_with(
            TaskType.AI_TASK,
            preferred_adapter=AdapterType.AGNO,
        )


class TestWebhookHealthEndpoint:
    """Tests for the /openclaw/health GET endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_healthy_status(self):
        result = await webhook_health()
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_returns_service_name(self):
        result = await webhook_health()
        assert result["service"] == "mahavishnu-webhooks"

    @pytest.mark.asyncio
    async def test_health_lists_endpoints(self):
        result = await webhook_health()
        assert "/openclaw/sweep" in result["endpoints"]
        assert "/openclaw/workflow" in result["endpoints"]

    @pytest.mark.asyncio
    async def test_health_returns_dict_with_correct_keys(self):
        result = await webhook_health()
        assert set(result.keys()) == {"status", "service", "endpoints"}


class TestRequestModelValidation:
    """Tests for request model validation through the router."""

    def test_sweep_request_with_path_traversal_tag_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="../../../etc/passwd", adapter=AdapterType.AGNO)

    def test_sweep_request_with_empty_tag_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="", adapter=AdapterType.AGNO)

    def test_sweep_request_with_invalid_priority_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="backend", priority="urgent")

    def test_sweep_request_with_valid_priority_accepted(self):
        req = OpenClawSweepRequest(tag="backend", priority="high")
        assert req.priority == "high"

    def test_sweep_request_with_special_characters_in_tag_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="back end!", adapter=AdapterType.AGNO)

    def test_sweep_request_with_valid_tag_accepted(self):
        req = OpenClawSweepRequest(tag="frontend-react", adapter=AdapterType.LLAMAINDEX)
        assert req.tag == "frontend-react"
        assert req.adapter == AdapterType.LLAMAINDEX

    def test_workflow_request_with_path_traversal_repo_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["../../etc/passwd"])

    def test_workflow_request_with_absolute_path_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["/etc/config"])

    def test_workflow_request_with_tilde_path_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["~/.ssh/id_rsa"])

    def test_workflow_request_with_empty_repos_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=[])

    def test_workflow_request_with_valid_repos_accepted(self):
        req = OpenClawWorkflowRequest(repos=["mahavishnu", "akosha/dhara"])
        assert len(req.repos) == 2

    def test_workflow_request_timeout_bounds(self):
        req = OpenClawWorkflowRequest(repos=["repo"], timeout_seconds=60)
        assert req.timeout_seconds == 60
        req2 = OpenClawWorkflowRequest(repos=["repo"], timeout_seconds=3600)
        assert req2.timeout_seconds == 3600

    def test_workflow_request_timeout_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["repo"], timeout_seconds=30)

    def test_workflow_request_timeout_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["repo"], timeout_seconds=5000)

    def test_sweep_metadata_size_limit(self):
        huge_metadata = {"key": "x" * 5000}
        with pytest.raises(ValidationError):
            OpenClawSweepRequest(tag="backend", metadata=huge_metadata)

    def test_sweep_metadata_valid_size_accepted(self):
        metadata = {"key": "value"}
        req = OpenClawSweepRequest(tag="backend", metadata=metadata)
        assert req.metadata == {"key": "value"}

    def test_workflow_metadata_size_limit(self):
        huge_metadata = {"key": "y" * 6000}
        with pytest.raises(ValidationError):
            OpenClawWorkflowRequest(repos=["repo"], metadata=huge_metadata)

    def test_sweep_default_values(self):
        req = OpenClawSweepRequest(tag="backend")
        assert req.adapter == AdapterType.AGNO
        assert req.priority == "normal"
        assert req.dry_run is False
        assert req.task_description is None
        assert req.metadata == {}

    def test_workflow_default_values(self):
        req = OpenClawWorkflowRequest(repos=["repo"])
        assert req.adapter == AdapterType.PREFECT
        assert req.workflow_type == "code_sweep"
        assert req.parallel is True
        assert req.fail_fast is False
        assert req.timeout_seconds == 300


class TestAllExportedNames:
    """Verify that __all__ lists the correct public names."""

    def test_all_contains_expected_names(self):
        from mahavishnu.webhooks.router import __all__
        expected = {"webhook_router", "validate_auth", "sweep_endpoint", "workflow_endpoint"}
        assert set(__all__) == expected
