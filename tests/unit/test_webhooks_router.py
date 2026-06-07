"""Unit tests for mahavishnu/webhooks/router.py.

Covers the FastAPI router that handles inbound OpenClaw webhook requests.
We test pure-Python entry points (`validate_auth`, `sweep_endpoint`,
`workflow_endpoint`, `webhook_health`) directly with mocks - no real HTTP
client, no real auth, no real pool manager.

Distinct class names are used to avoid pytest collection collisions with
the pre-existing test_webhook_router.py file in the same directory.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import APIRouter, HTTPException, Request
import pytest

from mahavishnu.core.errors import AuthenticationError
from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.webhooks.models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookResponse,
    WebhookStatus,
)
from mahavishnu.webhooks.router import (
    AuthDep,
    get_auth_handler,
    sweep_endpoint,
    validate_auth,
    webhook_health,
    webhook_router,
    workflow_endpoint,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _build_mock_request() -> Request:
    """Return a real starlette/FastAPI Request for endpoint calls.

    slowapi's rate_limit decorator type-checks the request argument, so
    we need an actual Request instance even though endpoints don't use it.
    """
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [],
        "query_string": b"",
        "path": "/openclaw/sweep",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope=scope)


def _mock_task_router(task_type: TaskType, chain: list[AdapterType]) -> MagicMock:
    """Create a mock TaskRouter that returns the supplied classification."""
    tr = MagicMock()
    tr.classify_intent = MagicMock(return_value=task_type)
    tr.generate_fallback_chain = MagicMock(return_value=chain)
    return tr


# =============================================================================
# Module Surface Tests
# =============================================================================


class TestRouterModuleSurface:
    """Verify the router exports and its FastAPI configuration."""

    def test_router_is_api_router(self):
        assert isinstance(webhook_router, APIRouter)

    def test_router_prefix(self):
        assert webhook_router.prefix == "/openclaw"

    def test_router_tags_include_openclaw(self):
        assert "webhooks" in webhook_router.tags
        assert "openclaw" in webhook_router.tags

    def test_router_registers_expected_paths(self):
        paths = {route.path for route in webhook_router.routes}
        assert {
            "/openclaw/sweep",
            "/openclaw/workflow",
            "/openclaw/health",
        }.issubset(paths)

    def test_router_method_for_each_endpoint(self):
        by_path = {route.path: route for route in webhook_router.routes}
        assert "POST" in by_path["/openclaw/sweep"].methods
        assert "POST" in by_path["/openclaw/workflow"].methods
        assert "GET" in by_path["/openclaw/health"].methods

    def test_auth_dep_is_annotated_alias(self):
        # AuthDep is a typing Annotated alias for Depends(validate_auth);
        # we just confirm the symbol resolves and is non-None
        assert AuthDep is not None


# =============================================================================
# get_auth_handler Tests
# =============================================================================


class TestGetAuthHandler:
    """Tests for the lazy auth-handler factory."""

    async def test_returns_multi_auth_handler(self):
        fake_settings = MagicMock()
        # NOTE: get_settings is imported lazily inside get_auth_handler and
        # may not exist as a module attribute on import; use create=True so
        # the patch works regardless of whether the attribute is defined.
        with (
            patch(
                "mahavishnu.core.config.get_settings",
                return_value=fake_settings,
                create=True,
            ),
            patch("mahavishnu.core.subscription_auth.MultiAuthHandler") as mock_cls,
        ):
            mock_cls.return_value = MagicMock(name="handler")
            handler = await get_auth_handler()
            mock_cls.assert_called_once_with(fake_settings)
            assert handler is mock_cls.return_value


# =============================================================================
# validate_auth Tests
# =============================================================================


class TestValidateAuthDependency:
    """Tests for the validate_auth dependency."""

    async def test_authenticated_request_returns_payload(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {
            "authenticated": True,
            "user": "alice",
            "method": "subscription",
        }
        with patch(
            "mahavishnu.webhooks.router.get_auth_handler",
            new=AsyncMock(return_value=mock_handler),
        ):
            result = await validate_auth("Bearer good")
        assert result["authenticated"] is True
        assert result["user"] == "alice"
        mock_handler.authenticate_request.assert_called_once_with("Bearer good")

    async def test_unauthenticated_dict_raises_401(self):
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {"authenticated": False}
        with (
            patch(
                "mahavishnu.webhooks.router.get_auth_handler",
                new=AsyncMock(return_value=mock_handler),
            ),
            pytest.raises(HTTPException) as ei,
        ):
            await validate_auth("Bearer bad")
        assert ei.value.status_code == 401
        detail = ei.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "AUTHENTICATION_ERROR"
        assert "recovery" in detail

    async def test_authentication_error_propagates_as_401(self):
        mock_handler = MagicMock()
        err = AuthenticationError(
            message="bad token",
            details={"reason": "exp"},
        )
        mock_handler.authenticate_request.side_effect = err
        with (
            patch(
                "mahavishnu.webhooks.router.get_auth_handler",
                new=AsyncMock(return_value=mock_handler),
            ),
            pytest.raises(HTTPException) as ei,
        ):
            await validate_auth("Bearer expired")
        assert ei.value.status_code == 401
        detail = ei.value.detail
        assert detail["error_code"] == "AUTHENTICATION_ERROR"
        assert detail["message"] == "bad token"
        assert detail["details"] == {"reason": "exp"}

    async def test_missing_authenticated_key_treated_as_unauthenticated(self):
        # If the handler returns a dict without 'authenticated', falsy lookup
        # should raise 401 (covers the `.get("authenticated")` branch).
        mock_handler = MagicMock()
        mock_handler.authenticate_request.return_value = {"user": "bob"}
        with (
            patch(
                "mahavishnu.webhooks.router.get_auth_handler",
                new=AsyncMock(return_value=mock_handler),
            ),
            pytest.raises(HTTPException) as ei,
        ):
            await validate_auth("Bearer x")
        assert ei.value.status_code == 401


# =============================================================================
# sweep_endpoint Tests
# =============================================================================


class TestSweepEndpointBehavior:
    """Tests for the sweep_endpoint coroutine."""

    async def test_happy_path_returns_accepted_response(self):
        sweep_req = OpenClawSweepRequest(
            tag="backend",
            adapter=AdapterType.AGNO,
            task_description="sweep backend",
            dry_run=False,
        )
        auth_payload = {"user": "alice", "authenticated": True}
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.AGNO, AdapterType.PREFECT])

        with (
            patch("mahavishnu.webhooks.router.get_pool_manager") as mock_pool,
            patch(
                "mahavishnu.webhooks.router.TaskRouter",
                return_value=task_router,
            ),
        ):
            result = await sweep_endpoint(
                request=_build_mock_request(),
                sweep_request=sweep_req,
                auth=auth_payload,
            )

        assert isinstance(result, WebhookResponse)
        assert result.status == WebhookStatus.ACCEPTED
        assert "backend" in result.message
        assert result.workflow_id == "wf-sweep-backend-alice"
        assert result.details["tag"] == "backend"
        assert result.details["adapter"] == "agno"
        assert result.details["task_type"] == "workflow"
        assert result.details["fallback_chain"] == ["agno", "prefect"]
        assert result.details["dry_run"] is False
        assert result.details["user"] == "alice"
        mock_pool.assert_called_once()
        task_router.classify_intent.assert_called_once_with("sweep backend")
        task_router.generate_fallback_chain.assert_called_once_with(
            TaskType.WORKFLOW,
            preferred_adapter=AdapterType.AGNO,
        )

    async def test_falls_back_to_default_intent_when_description_missing(self):
        sweep_req = OpenClawSweepRequest(tag="python", adapter=AdapterType.AGNO)
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.AGNO])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            await sweep_endpoint(
                request=_build_mock_request(),
                sweep_request=sweep_req,
                auth={"user": "u"},
            )
        # The synthesised intent should mention the tag
        call_args = task_router.classify_intent.call_args
        assert "python" in call_args.args[0]

    async def test_workflow_id_uses_unknown_user_when_missing(self):
        sweep_req = OpenClawSweepRequest(tag="frontend")
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.AGNO])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            result = await sweep_endpoint(
                request=_build_mock_request(),
                sweep_request=sweep_req,
                auth={},
            )
        assert result.workflow_id == "wf-sweep-frontend-unknown"
        assert result.details["user"] is None

    async def test_dry_run_flag_passed_through_to_details(self):
        sweep_req = OpenClawSweepRequest(tag="t", dry_run=True)
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.AGNO])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            result = await sweep_endpoint(
                request=_build_mock_request(),
                sweep_request=sweep_req,
                auth={"user": "u"},
            )
        assert result.details["dry_run"] is True


# =============================================================================
# workflow_endpoint Tests
# =============================================================================


class TestWorkflowEndpointBehavior:
    """Tests for the workflow_endpoint coroutine."""

    async def test_happy_path_returns_accepted_response(self):
        wf_req = OpenClawWorkflowRequest(
            repos=["org/repo-a", "org/repo-b"],
            adapter=AdapterType.PREFECT,
            task_description="run code sweep",
        )
        auth_payload = {"user": "bob"}
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.PREFECT, AdapterType.AGNO])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager") as mock_pool,
            patch(
                "mahavishnu.webhooks.router.TaskRouter",
                return_value=task_router,
            ),
        ):
            result = await workflow_endpoint(
                request=_build_mock_request(),
                workflow_request=wf_req,
                auth=auth_payload,
            )

        assert isinstance(result, WebhookResponse)
        assert result.status == WebhookStatus.ACCEPTED
        assert "2 repositories" in result.message
        assert result.workflow_id == "wf-workflow-bob"
        assert result.details["repos"] == ["org/repo-a", "org/repo-b"]
        assert result.details["repos_count"] == 2
        assert result.details["adapter"] == "prefect"
        assert result.details["fallback_chain"] == ["prefect", "agno"]
        assert result.details["parallel"] is True
        assert result.details["timeout_seconds"] == 300
        assert result.details["user"] == "bob"
        mock_pool.assert_called_once()

    async def test_workflow_id_uses_unknown_user_when_missing(self):
        wf_req = OpenClawWorkflowRequest(repos=["org/repo"])
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.PREFECT])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            result = await workflow_endpoint(
                request=_build_mock_request(),
                workflow_request=wf_req,
                auth={},
            )
        assert result.workflow_id == "wf-workflow-unknown"

    async def test_synthesised_intent_when_no_task_description(self):
        wf_req = OpenClawWorkflowRequest(repos=["a", "b", "c"])
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.PREFECT])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            await workflow_endpoint(
                request=_build_mock_request(),
                workflow_request=wf_req,
                auth={"user": "u"},
            )
        call_args = task_router.classify_intent.call_args
        assert "3 repos" in call_args.args[0]

    async def test_timeout_and_parallel_propagate(self):
        wf_req = OpenClawWorkflowRequest(
            repos=["repo"],
            parallel=False,
            timeout_seconds=600,
        )
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.PREFECT])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            result = await workflow_endpoint(
                request=_build_mock_request(),
                workflow_request=wf_req,
                auth={"user": "u"},
            )
        assert result.details["parallel"] is False
        assert result.details["timeout_seconds"] == 600

    async def test_generate_fallback_chain_called_with_preferred_adapter(self):
        wf_req = OpenClawWorkflowRequest(repos=["r"], adapter=AdapterType.LLAMAINDEX)
        task_router = _mock_task_router(TaskType.WORKFLOW, [AdapterType.LLAMAINDEX])
        with (
            patch("mahavishnu.webhooks.router.get_pool_manager"),
            patch("mahavishnu.webhooks.router.TaskRouter", return_value=task_router),
        ):
            await workflow_endpoint(
                request=_build_mock_request(),
                workflow_request=wf_req,
                auth={"user": "u"},
            )
        task_router.generate_fallback_chain.assert_called_once_with(
            TaskType.WORKFLOW,
            preferred_adapter=AdapterType.LLAMAINDEX,
        )


# =============================================================================
# webhook_health Tests
# =============================================================================


class TestWebhookHealthEndpointBehavior:
    """Tests for the /openclaw/health endpoint."""

    async def test_health_returns_healthy_status(self):
        result = await webhook_health()
        assert isinstance(result, dict)
        assert result["status"] == "healthy"
        assert result["service"] == "mahavishnu-webhooks"
        endpoints = result["endpoints"]
        assert "/openclaw/sweep" in endpoints
        assert "/openclaw/workflow" in endpoints
