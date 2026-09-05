"""Coverage tests for the inline MCP tool bodies in ``mahavishnu.mcp.server_core``.

``FastMCPServer._register_tools`` defines ~27 tools inline so FastMCP can
introspect their signatures. Those bodies are therefore unreachable as
module-level functions; this suite drives them through the public FastMCP
introspection API (``await server.get_tool(name)`` -> ``FunctionTool.fn``),
which returns the instrumented handler and runs the real body.

Complements ``tests/unit/test_mcp_server_core.py`` (init / middleware /
lifecycle / registration metrics) by exercising the per-tool success and
error branches plus the sync/cancel/timeout arms of
``_wrap_tool_handler``.

Deliberately avoids stubbing modules in ``sys.modules``; every patch uses
``monkeypatch.setattr`` against a real, already-imported module object.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.server_core import FastMCPServer

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit


# =============================================================================
# Local helpers / fixtures (kept in this file — no shared conftest additions)
# =============================================================================


def _make_settings(**overrides: Any) -> MahavishnuSettings:
    """Build MahavishnuSettings with heavy subsystems disabled."""
    defaults: dict[str, Any] = {
        "server_name": "Tool Body Test Server",
        "observability_enabled": False,
        "terminal_enabled": False,
        "pools": {"enabled": False},
        "workers": {"enabled": False},
        "otel_storage": {"enabled": False},
    }
    defaults.update(overrides)
    return MahavishnuSettings(**defaults)


class _Boom:
    """Callable that always raises — used to drive ``except`` arms."""

    def __init__(self, message: str = "boom", exc: type[BaseException] = RuntimeError) -> None:
        self.message = message
        self.exc = exc

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        raise self.exc(self.message)


@pytest.fixture
def mock_app() -> MagicMock:
    """A MahavishnuApp double with every attribute the tool bodies touch."""
    app = MagicMock(spec=MahavishnuApp)
    app.config = _make_settings()
    app.get_repos = MagicMock(return_value=[])
    app.adapters = {}
    app.pool_manager = None
    app.worktree_coordinator = None

    app.workflow_state_manager = MagicMock()
    app.rbac_manager = MagicMock()
    app.observability = MagicMock()
    app.opensearch_integration = MagicMock()
    app.error_recovery_manager = MagicMock()
    app.monitoring_service = MagicMock()
    return app


@pytest.fixture
def server(mock_app: MagicMock) -> FastMCPServer:
    """FastMCPServer bound to the mocked app, with auth resolution stubbed."""
    with patch("mahavishnu.mcp.server_core.get_auth_from_config"):
        return FastMCPServer(app=mock_app)


@pytest.fixture
def tool(server: FastMCPServer) -> Callable[[str], Any]:
    """Return an async lookup that resolves a registered tool's callable.

    ``FunctionTool.fn`` is the instrumented wrapper produced by
    ``_wrap_tool_handler``, so calling it exercises both the tool body and
    the metrics instrumentation.
    """

    async def _lookup(name: str) -> Any:
        found = await server.server.get_tool(name)
        return found.fn

    return _lookup


# =============================================================================
# list_repos
# =============================================================================


class TestListRepos:
    """Pagination arithmetic and the error envelope for ``list_repos``."""

    async def test_returns_all_repos_by_default(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Without pagination every repo is projected with exists=True."""
        mock_app.get_repos = MagicMock(return_value=["/a", "/b", "/c"])

        fn = await tool("list_repos")
        result = await fn()

        assert result["total_count"] == 3
        assert result["filtered_count"] == 3
        assert result["repos"] == [
            {"path": "/a", "exists": True},
            {"path": "/b", "exists": True},
            {"path": "/c", "exists": True},
        ]

    async def test_applies_offset_then_limit(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Offset is applied before limit, and total_count stays unfiltered."""
        mock_app.get_repos = MagicMock(return_value=["/a", "/b", "/c", "/d"])

        fn = await tool("list_repos")
        result = await fn(offset=1, limit=2)

        assert [r["path"] for r in result["repos"]] == ["/b", "/c"]
        assert result["filtered_count"] == 2
        assert result["total_count"] == 4

    async def test_echoes_tag_filter(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """The requested tag is echoed back in the response."""
        mock_app.get_repos = MagicMock(return_value=["/a"])

        fn = await tool("list_repos")
        result = await fn(tag="backend")

        assert result["tag"] == "backend"

    async def test_wraps_repo_lookup_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A repo-catalog failure returns an empty, zeroed envelope."""
        mock_app.get_repos = MagicMock(side_effect=RuntimeError("repos.yaml missing"))

        fn = await tool("list_repos")
        result = await fn()

        assert result["status"] == "error"
        assert "repos.yaml missing" in result["error"]
        assert result["repos"] == []
        assert result["total_count"] == 0
        assert result["filtered_count"] == 0


# =============================================================================
# trigger_workflow — default/tag arms plus timeout & error recovery
# =============================================================================


class TestTriggerWorkflow:
    """Cover the ``params is None`` default and the ``tag`` repo-resolution arm."""

    async def test_explicit_repos_bypass_catalog_lookup(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An explicit repo list is used verbatim, never re-resolved."""
        mock_app.execute_workflow_parallel = AsyncMock(
            return_value={
                "workflow_id": "wf-explicit",
                "status": "completed",
                "repos_processed": 2,
                "successful_repos": 2,
                "failed_repos": 0,
                "execution_time_seconds": 1.5,
                "errors": [],
            }
        )

        fn = await tool("trigger_workflow")
        result = await fn(adapter="prefect", task_type="review", repos=["/x", "/y"])

        assert result["status"] == "completed"
        assert result["execution_time"] == 1.5
        assert result["successful_repos"] == 2
        mock_app.get_repos.assert_not_called()
        assert mock_app.execute_workflow_parallel.await_args.args[2] == ["/x", "/y"]

    async def test_timeout_wraps_execution_in_wait_for(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A supplied timeout routes the call through ``asyncio.wait_for``."""
        mock_app.get_repos = MagicMock(return_value=["/a"])
        mock_app.execute_workflow_parallel = AsyncMock(
            return_value={"workflow_id": "wf-timed", "status": "completed"}
        )

        fn = await tool("trigger_workflow")
        result = await fn(adapter="prefect", task_type="review", timeout=30)

        assert result["workflow_id"] == "wf-timed"

    async def test_timeout_records_failed_workflow_state(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A timeout synthesizes a workflow id and persists a failed state."""
        mock_app.get_repos = MagicMock(return_value=["/a", "/b"])
        mock_app.execute_workflow_parallel = _Boom("too slow", exc=TimeoutError)
        mock_app.workflow_state_manager.create = AsyncMock()
        mock_app.workflow_state_manager.update = AsyncMock()

        fn = await tool("trigger_workflow")
        result = await fn(adapter="prefect", task_type="review", timeout=5)

        assert result["status"] == "failed"
        assert result["workflow_id"].startswith("wf_timeout_")
        assert result["workflow_id"].endswith("_review")
        assert result["failed_repos"] == 2
        assert result["execution_time"] == 5
        assert result["errors"][0]["type"] == "TimeoutError"

        mock_app.workflow_state_manager.create.assert_awaited_once()
        assert mock_app.workflow_state_manager.create.await_args.kwargs["repos"] == ["/a", "/b"]
        assert mock_app.workflow_state_manager.update.await_args.kwargs["status"] == "failed"

    async def test_generic_failure_records_error_workflow_state(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A generic failure synthesizes an error workflow id and persists it."""
        mock_app.get_repos = MagicMock(return_value=["/a"])
        mock_app.execute_workflow_parallel = _Boom("adapter exploded")
        mock_app.workflow_state_manager.create = AsyncMock()
        mock_app.workflow_state_manager.update = AsyncMock()

        fn = await tool("trigger_workflow")
        result = await fn(adapter="agno", task_type="ingest")

        assert result["status"] == "failed"
        assert result["workflow_id"].startswith("wf_error_")
        assert result["result"]["error"] == "adapter exploded"
        assert result["failed_repos"] == 1
        assert result["errors"][0]["type"] == "RuntimeError"
        mock_app.workflow_state_manager.update.assert_awaited_once()

    async def test_generic_failure_survives_state_persistence_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """If state persistence also fails, the error envelope still returns.

        The handler wraps the bookkeeping in ``contextlib.suppress`` precisely
        so a dead state store cannot mask the original adapter error.
        """
        mock_app.get_repos = MagicMock(return_value=["/a"])
        mock_app.execute_workflow_parallel = _Boom("adapter exploded")
        mock_app.workflow_state_manager.create = _Boom("state store dead")

        fn = await tool("trigger_workflow")
        result = await fn(adapter="agno", task_type="ingest")

        assert result["status"] == "failed"
        assert result["result"]["error"] == "adapter exploded"

    async def test_defaults_params_to_empty_dict(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Omitting ``params`` must normalize to ``{}`` before dispatch."""
        mock_app.execute_workflow_parallel = AsyncMock(
            return_value={"workflow_id": "wf-1", "status": "queued"}
        )

        fn = await tool("trigger_workflow")
        result = await fn(adapter="prefect", task_type="code_review")

        assert result["workflow_id"] == "wf-1"
        task_arg = mock_app.execute_workflow_parallel.await_args.args[0]
        assert task_arg["params"] == {}

    async def test_tag_resolves_repos_via_get_repos(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """When ``repos`` is absent but ``tag`` is set, repos come from the tag."""
        mock_app.get_repos = MagicMock(return_value=["/repo/a", "/repo/b"])
        mock_app.execute_workflow_parallel = AsyncMock(
            return_value={"workflow_id": "wf-tag", "status": "queued", "repos_processed": 2}
        )

        fn = await tool("trigger_workflow")
        result = await fn(adapter="agno", task_type="ingest", tag="backend")

        assert result["repos_processed"] == 2
        mock_app.get_repos.assert_called_once_with(tag="backend", user_id=None)


# =============================================================================
# RBAC-gated tools — permission-denied + exception arms
# =============================================================================


class TestPermissionGatedTools:
    """Every RBAC-gated tool must return a structured denial, never raise."""

    async def test_get_workflow_status_forbidden(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A user without VIEW_WORKFLOW_STATUS gets status='forbidden'."""
        mock_app.workflow_state_manager.get = AsyncMock(return_value={"status": "running"})
        mock_app.rbac_manager.check_permission = AsyncMock(return_value=False)

        fn = await tool("get_workflow_status")
        result = await fn(workflow_id="wf-9", user_id="alice")

        assert result["status"] == "forbidden"
        assert "does not have permission" in result["error"]

    async def test_get_workflow_status_allowed_returns_state(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """With permission granted the full state projection is returned."""
        mock_app.workflow_state_manager.get = AsyncMock(
            return_value={
                "status": "completed",
                "progress": 100,
                "repos": ["/a"],
                "task": {"type": "review"},
                "results": [1, 2],
                "errors": [],
            }
        )
        mock_app.rbac_manager.check_permission = AsyncMock(return_value=True)

        fn = await tool("get_workflow_status")
        result = await fn(workflow_id="wf-ok", user_id="bob")

        assert result["status"] == "completed"
        assert result["task_type"] == "review"
        assert result["results_count"] == 2

    async def test_get_workflow_status_not_found(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An unknown workflow id yields status='not_found' before RBAC runs."""
        mock_app.workflow_state_manager.get = AsyncMock(return_value=None)
        mock_app.rbac_manager.check_permission = AsyncMock()

        fn = await tool("get_workflow_status")
        result = await fn(workflow_id="wf-missing", user_id="alice")

        assert result["status"] == "not_found"
        assert "wf-missing" in result["error"]
        mock_app.rbac_manager.check_permission.assert_not_awaited()

    async def test_get_workflow_status_wraps_backend_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A state-store failure returns status='error' with a timestamp."""
        mock_app.workflow_state_manager.get = _Boom("state store dead")

        fn = await tool("get_workflow_status")
        result = await fn(workflow_id="wf-1")

        assert result["status"] == "error"
        assert "state store dead" in result["error"]
        assert "timestamp" in result

    async def test_list_workflows_success_applies_offset(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """The limit goes to the backend; the offset is applied locally."""
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[{"id": "1"}, {"id": "2"}, {"id": "3"}]
        )

        fn = await tool("list_workflows")
        result = await fn(limit=5, offset=1)

        assert result["status"] == "success"
        assert [w["id"] for w in result["workflows"]] == ["2", "3"]
        assert result["limit"] == 5
        assert result["offset"] == 1

    async def test_list_workflows_accepts_valid_status_filter(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A valid status string is coerced to the WorkflowStatus enum."""
        from mahavishnu.core.workflow_state import WorkflowStatus

        mock_app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        fn = await tool("list_workflows")
        result = await fn(status="completed")

        assert result["status"] == "success"
        assert result["status_filter"] == "completed"
        kwargs = mock_app.workflow_state_manager.list_workflows.await_args.kwargs
        assert kwargs["status"] is WorkflowStatus.COMPLETED

    async def test_list_workflows_rejects_invalid_status(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An unknown status is rejected and the valid set is listed."""
        mock_app.workflow_state_manager.list_workflows = AsyncMock()

        fn = await tool("list_workflows")
        result = await fn(status="quantum_superposition")

        assert result["status"] == "error"
        assert "Invalid status" in result["error"]
        assert "completed" in result["error"]
        mock_app.workflow_state_manager.list_workflows.assert_not_awaited()

    async def test_list_workflows_forbidden(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """LIST_WORKFLOWS denial returns an error envelope with empty list."""
        mock_app.rbac_manager.check_permission = AsyncMock(return_value=False)

        fn = await tool("list_workflows")
        result = await fn(user_id="carol")

        assert result["status"] == "error"
        assert result["workflows"] == []
        assert result["total_count"] == 0

    async def test_list_workflows_wraps_backend_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A state-manager explosion is converted to an error envelope."""
        mock_app.workflow_state_manager.list_workflows = _Boom("state down")

        fn = await tool("list_workflows")
        result = await fn()

        assert result["status"] == "error"
        assert "state down" in result["error"]

    async def test_cancel_workflow_forbidden(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """CANCEL_WORKFLOW denial short-circuits before touching state."""
        mock_app.rbac_manager.check_permission = AsyncMock(return_value=False)
        mock_app.workflow_state_manager.update = AsyncMock()

        fn = await tool("cancel_workflow")
        result = await fn(workflow_id="wf-x", user_id="dave")

        assert result["status"] == "forbidden"
        mock_app.workflow_state_manager.update.assert_not_awaited()

    async def test_cancel_workflow_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A successful cancel records the cancelled state and confirms."""
        mock_app.workflow_state_manager.update = AsyncMock()

        fn = await tool("cancel_workflow")
        result = await fn(workflow_id="wf-cancel")

        assert result["status"] == "cancelled"
        assert "wf-cancel" in result["message"]
        kwargs = mock_app.workflow_state_manager.update.await_args.kwargs
        assert kwargs["status"] == "cancelled"
        assert "cancelled_at" in kwargs

    async def test_cancel_workflow_wraps_backend_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An update failure surfaces as status='error', not a raise."""
        mock_app.workflow_state_manager.update = _Boom("cannot update")

        fn = await tool("cancel_workflow")
        result = await fn(workflow_id="wf-x")

        assert result["status"] == "error"
        assert "cannot update" in result["error"]

    async def test_create_user_forbidden(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A caller lacking admin rights cannot create users."""
        mock_app.rbac_manager.check_permission = AsyncMock(return_value=False)
        mock_app.rbac_manager.create_user = AsyncMock()

        fn = await tool("create_user")
        result = await fn(user_id="new", roles=["viewer"], user_id_caller="not-admin")

        assert result["status"] == "forbidden"
        mock_app.rbac_manager.create_user.assert_not_awaited()

    async def test_create_user_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A successful create returns the role names off the user object."""
        role = MagicMock()
        role.name = "viewer"
        created = MagicMock(user_id="new", roles=[role])
        mock_app.rbac_manager.create_user = AsyncMock(return_value=created)

        fn = await tool("create_user")
        result = await fn(user_id="new", roles=["viewer"], allowed_repos=["/r"])

        assert result["status"] == "success"
        assert result["roles"] == ["viewer"]
        assert result["allowed_repos"] == ["/r"]

    async def test_create_user_wraps_backend_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An RBAC create failure returns status='error' with a message."""
        mock_app.rbac_manager.create_user = _Boom("duplicate user")

        fn = await tool("create_user")
        result = await fn(user_id="dupe", roles=["viewer"])

        assert result["status"] == "error"
        assert "duplicate user" in result["error"]
        assert result["message"] == "Failed to create user"


class TestCheckPermissionTool:
    """``check_permission`` validates the enum then delegates to RBAC."""

    async def test_valid_permission_delegates_to_rbac(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A known permission string is converted to the enum and checked."""
        from mahavishnu.core.permissions import Permission

        mock_app.rbac_manager.check_permission = AsyncMock(return_value=True)

        fn = await tool("check_permission")
        result = await fn(user_id="alice", repo="/r", permission="read_repo")

        assert result["has_permission"] is True
        assert result["permission"] == "read_repo"
        mock_app.rbac_manager.check_permission.assert_awaited_once_with(
            "alice", "/r", Permission.READ_REPO
        )

    async def test_invalid_permission_lists_valid_values(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """An unknown permission returns the valid set instead of raising."""
        fn = await tool("check_permission")
        result = await fn(user_id="alice", repo="/r", permission="not_a_perm")

        assert result["status"] == "error"
        assert result["has_permission"] is False
        assert "read_repo" in result["valid_permissions"]

    async def test_rbac_failure_is_wrapped(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An RBAC backend error yields has_permission=False, not a raise."""
        mock_app.rbac_manager.check_permission = _Boom("rbac offline")

        fn = await tool("check_permission")
        result = await fn(user_id="alice", repo="/r", permission="read_repo")

        assert result["status"] == "error"
        assert result["has_permission"] is False


# =============================================================================
# Observability / OpenSearch-backed tools
# =============================================================================


class TestObservabilityTools:
    """Observability and log/workflow search tools and their error arms."""

    async def test_observability_metrics_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """The handler projects perf metrics plus a bounded log preview."""
        log = MagicMock(
            timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            message="hello",
            attributes={"k": "v"},
        )
        log.level = MagicMock(value="info")
        mock_app.observability.get_performance_metrics = MagicMock(return_value={"cpu": 1})
        mock_app.observability.get_logs = MagicMock(return_value=[log] * 3)

        fn = await tool("get_observability_metrics")
        result = await fn()

        assert result["status"] == "success"
        assert result["performance_metrics"] == {"cpu": 1}
        assert result["recent_logs_count"] == 3
        assert result["recent_logs_preview"][0]["message"] == "hello"

    async def test_observability_metrics_not_initialized(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A missing observability subsystem returns an error, not a raise."""
        mock_app.observability = None

        fn = await tool("get_observability_metrics")
        result = await fn()

        assert "not initialized" in result["error"]
        assert result["metrics"] == {}

    async def test_observability_metrics_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An exception inside metric collection is caught and reported."""
        mock_app.observability.get_performance_metrics = MagicMock(
            side_effect=RuntimeError("metrics dead")
        )

        fn = await tool("get_observability_metrics")
        result = await fn()

        assert "metrics dead" in result["error"]

    async def test_search_logs_success_echoes_query_params(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Results and the original filter set are both returned."""
        mock_app.opensearch_integration.search_logs = AsyncMock(return_value=[{"m": "1"}])

        fn = await tool("search_logs")
        result = await fn(query="error", level="ERROR", size=5)

        assert result["status"] == "success"
        assert result["total_found"] == 1
        assert result["query_params"]["level"] == "ERROR"
        assert result["query_params"]["size"] == 5

    async def test_search_logs_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An OpenSearch error yields an empty log list with status='error'."""
        mock_app.opensearch_integration.search_logs = _Boom("opensearch down")

        fn = await tool("search_logs")
        result = await fn(query="x")

        assert result["status"] == "error"
        assert result["logs"] == []

    async def test_search_workflows_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Workflow search mirrors the log-search envelope shape."""
        mock_app.opensearch_integration.search_workflows = AsyncMock(
            return_value=[{"workflow_id": "wf-1"}, {"workflow_id": "wf-2"}]
        )

        fn = await tool("search_workflows")
        result = await fn(adapter="prefect", status="completed")

        assert result["total_found"] == 2
        assert result["query_params"]["adapter"] == "prefect"

    async def test_search_workflows_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A search failure returns an empty workflow list."""
        mock_app.opensearch_integration.search_workflows = _Boom("query failed")

        fn = await tool("search_workflows")
        result = await fn()

        assert result["status"] == "error"
        assert result["workflows"] == []

    @pytest.mark.parametrize(
        ("tool_name", "backend_attr", "payload_key"),
        [
            ("get_workflow_statistics", "get_workflow_stats", "statistics"),
            ("get_log_statistics", "get_log_stats", "statistics"),
        ],
    )
    async def test_statistics_tools_success(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        mock_app: MagicMock,
        tool_name: str,
        backend_attr: str,
        payload_key: str,
    ) -> None:
        """Both statistics tools pass the backend payload straight through."""
        setattr(
            mock_app.opensearch_integration,
            backend_attr,
            AsyncMock(return_value={"count": 7}),
        )

        fn = await tool(tool_name)
        result = await fn()

        assert result["status"] == "success"
        assert result[payload_key] == {"count": 7}

    @pytest.mark.parametrize(
        ("tool_name", "backend_attr"),
        [
            ("get_workflow_statistics", "get_workflow_stats"),
            ("get_log_statistics", "get_log_stats"),
        ],
    )
    async def test_statistics_tools_wrap_failure(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        mock_app: MagicMock,
        tool_name: str,
        backend_attr: str,
    ) -> None:
        """A stats backend failure degrades to an empty statistics dict."""
        setattr(mock_app.opensearch_integration, backend_attr, _Boom("stats down"))

        fn = await tool(tool_name)
        result = await fn()

        assert result["status"] == "error"
        assert result["statistics"] == {}

    async def test_recovery_metrics_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Recovery metrics are forwarded verbatim."""
        mock_app.error_recovery_manager.get_recovery_metrics = AsyncMock(
            return_value={"retries": 3}
        )

        fn = await tool("get_recovery_metrics")
        result = await fn()

        assert result["metrics"] == {"retries": 3}

    async def test_recovery_metrics_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A recovery-manager failure degrades to an empty metrics dict."""
        mock_app.error_recovery_manager.get_recovery_metrics = _Boom("no recovery")

        fn = await tool("get_recovery_metrics")
        result = await fn()

        assert result["status"] == "error"
        assert result["metrics"] == {}

    async def test_heal_workflows_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Healing kicks off the monitor loop and reports success."""
        mock_app.error_recovery_manager.monitor_and_heal_workflows = AsyncMock()

        fn = await tool("heal_workflows")
        result = await fn()

        assert result["status"] == "success"
        mock_app.error_recovery_manager.monitor_and_heal_workflows.assert_awaited_once()

    async def test_heal_workflows_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A healing failure is reported rather than propagated."""
        mock_app.error_recovery_manager.monitor_and_heal_workflows = _Boom("heal failed")

        fn = await tool("heal_workflows")
        result = await fn()

        assert result["status"] == "error"
        assert "heal failed" in result["error"]

    async def test_flush_metrics_warns_when_observability_missing(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """No observability subsystem is a warning, not an error."""
        mock_app.observability = None

        fn = await tool("flush_metrics")
        result = await fn()

        assert result["status"] == "warning"

    async def test_flush_metrics_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A healthy observability subsystem is flushed."""
        mock_app.observability.flush_metrics = AsyncMock()

        fn = await tool("flush_metrics")
        result = await fn()

        assert result["status"] == "success"
        mock_app.observability.flush_metrics.assert_awaited_once()

    async def test_flush_metrics_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A flush failure is caught at the MCP boundary."""
        mock_app.observability.flush_metrics = _Boom("flush failed")

        fn = await tool("flush_metrics")
        result = await fn()

        assert result["status"] == "error"


# =============================================================================
# Backup / disaster-recovery tools (inline BackupManager import)
# =============================================================================


class _FakeBackupInfo:
    def __init__(self, backup_id: str = "bk-1", status: str = "complete") -> None:
        self.backup_id = backup_id
        self.location = f"/backups/{backup_id}"
        self.size_bytes = 2048
        self.timestamp = dt.datetime(2026, 2, 2, tzinfo=dt.UTC)
        self.status = status


class TestBackupTools:
    """``create_backup`` / ``list_backups`` / ``restore_backup`` / DR check."""

    @pytest.fixture
    def backup_module(self) -> Any:
        """The real module whose ``BackupManager`` the tool imports inline."""
        from mahavishnu.core import backup_recovery

        return backup_recovery

    async def test_create_backup_success(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A created backup surfaces its id, location, and ISO timestamp."""
        manager = MagicMock()
        manager.create_backup = AsyncMock(return_value=_FakeBackupInfo("bk-42"))
        monkeypatch.setattr(backup_module, "BackupManager", MagicMock(return_value=manager))

        fn = await tool("create_backup")
        result = await fn(backup_type="full")

        assert result["status"] == "success"
        assert result["backup_id"] == "bk-42"
        assert result["size_bytes"] == 2048
        assert result["timestamp"].startswith("2026-02-02")

    async def test_create_backup_wraps_failure(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A backup failure returns status='error'."""
        monkeypatch.setattr(
            backup_module, "BackupManager", MagicMock(side_effect=RuntimeError("disk full"))
        )

        fn = await tool("create_backup")
        result = await fn()

        assert result["status"] == "error"
        assert "disk full" in result["error"]

    async def test_list_backups_success(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each backup is projected into a serializable dict."""
        manager = MagicMock()
        manager.list_backups = AsyncMock(
            return_value=[_FakeBackupInfo("bk-1"), _FakeBackupInfo("bk-2")]
        )
        monkeypatch.setattr(backup_module, "BackupManager", MagicMock(return_value=manager))

        fn = await tool("list_backups")
        result = await fn()

        assert result["total_count"] == 2
        assert {b["backup_id"] for b in result["backups"]} == {"bk-1", "bk-2"}

    async def test_list_backups_wraps_failure(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A listing failure returns an empty backups list."""
        manager = MagicMock()
        manager.list_backups = _Boom("cannot enumerate")
        monkeypatch.setattr(backup_module, "BackupManager", MagicMock(return_value=manager))

        fn = await tool("list_backups")
        result = await fn()

        assert result["status"] == "error"
        assert result["backups"] == []

    @pytest.mark.parametrize(
        ("restore_ok", "expected_status", "expected_word"),
        [(True, "success", "completed"), (False, "error", "failed")],
    )
    async def test_restore_backup_reports_outcome(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
        restore_ok: bool,
        expected_status: str,
        expected_word: str,
    ) -> None:
        """The boolean restore result drives both status and message text."""
        manager = MagicMock()
        manager.restore_backup = AsyncMock(return_value=restore_ok)
        monkeypatch.setattr(backup_module, "BackupManager", MagicMock(return_value=manager))

        fn = await tool("restore_backup")
        result = await fn(backup_id="bk-7")

        assert result["status"] == expected_status
        assert expected_word in result["message"]

    async def test_restore_backup_wraps_failure(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A restore exception is converted to an error envelope."""
        manager = MagicMock()
        manager.restore_backup = _Boom("corrupt archive")
        monkeypatch.setattr(backup_module, "BackupManager", MagicMock(return_value=manager))

        fn = await tool("restore_backup")
        result = await fn(backup_id="bk-7")

        assert result["status"] == "error"
        assert "corrupt archive" in result["error"]

    async def test_disaster_recovery_check_success(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DR results are forwarded verbatim."""
        manager = MagicMock()
        manager.run_disaster_recovery_check = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr(
            backup_module, "DisasterRecoveryManager", MagicMock(return_value=manager)
        )

        fn = await tool("run_disaster_recovery_check")
        result = await fn()

        assert result["status"] == "success"
        assert result["results"] == {"ok": True}

    async def test_disaster_recovery_check_wraps_failure(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        backup_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A DR failure returns status='error'."""
        manager = MagicMock()
        manager.run_disaster_recovery_check = _Boom("dr unreachable")
        monkeypatch.setattr(
            backup_module, "DisasterRecoveryManager", MagicMock(return_value=manager)
        )

        fn = await tool("run_disaster_recovery_check")
        result = await fn()

        assert result["status"] == "error"


# =============================================================================
# Monitoring / alerting tools
# =============================================================================


def _fake_alert(alert_id: str = "al-1") -> MagicMock:
    """Build an alert double with the attribute surface the tool projects."""
    alert = MagicMock(
        id=alert_id,
        timestamp=dt.datetime(2026, 3, 3, tzinfo=dt.UTC),
        title="Disk pressure",
        description="Above threshold",
        details={"pct": 91},
    )
    alert.severity = MagicMock(value="high")
    alert.type = MagicMock(value="system_health")
    return alert


class TestMonitoringTools:
    """Dashboard + alert tools including uninitialized-service guards."""

    async def test_monitoring_dashboard_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dashboard wraps the canonical ecosystem report as JSON."""
        from mahavishnu.core import ecosystem_status

        report = MagicMock()
        report.model_dump = MagicMock(return_value={"overall": "healthy"})
        service = MagicMock()
        service.generate_report = AsyncMock(return_value=report)
        monkeypatch.setattr(
            ecosystem_status, "EcosystemStatusService", MagicMock(return_value=service)
        )

        fn = await tool("get_monitoring_dashboard")
        result = await fn()

        assert result["status"] == "success"
        assert result["ecosystem_status"] == {"overall": "healthy"}
        report.model_dump.assert_called_once_with(mode="json")

    async def test_monitoring_dashboard_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A report-generation failure returns status='error'."""
        from mahavishnu.core import ecosystem_status

        monkeypatch.setattr(
            ecosystem_status,
            "EcosystemStatusService",
            MagicMock(side_effect=RuntimeError("status svc down")),
        )

        fn = await tool("get_monitoring_dashboard")
        result = await fn()

        assert result["status"] == "error"
        assert "status svc down" in result["error"]

    async def test_active_alerts_requires_monitoring_service(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A missing monitoring service is reported, not raised."""
        mock_app.monitoring_service = None

        fn = await tool("get_active_alerts")
        result = await fn()

        assert result["status"] == "error"
        assert "not initialized" in result["error"]

    async def test_active_alerts_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Alerts are projected into JSON-safe dicts with an ISO timestamp."""
        mock_app.monitoring_service.alert_manager.get_active_alerts = AsyncMock(
            return_value=[_fake_alert("al-1"), _fake_alert("al-2")]
        )

        fn = await tool("get_active_alerts")
        result = await fn()

        assert result["count"] == 2
        assert result["alerts"][0]["severity"] == "high"
        assert result["alerts"][0]["timestamp"].startswith("2026-03-03")

    async def test_active_alerts_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An alert-manager failure returns status='error'."""
        mock_app.monitoring_service.alert_manager.get_active_alerts = _Boom("alert svc down")

        fn = await tool("get_active_alerts")
        result = await fn()

        assert result["status"] == "error"

    async def test_acknowledge_alert_requires_monitoring_service(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Acknowledging without a monitoring service is an error envelope."""
        mock_app.monitoring_service = None

        fn = await tool("acknowledge_alert")
        result = await fn(alert_id="al-1", user="alice")

        assert result["status"] == "error"

    @pytest.mark.parametrize(("ack_ok", "expected_status"), [(True, "success"), (False, "error")])
    async def test_acknowledge_alert_reports_outcome(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        mock_app: MagicMock,
        ack_ok: bool,
        expected_status: str,
    ) -> None:
        """The boolean ack result drives the response status."""
        mock_app.monitoring_service.acknowledge_alert = AsyncMock(return_value=ack_ok)

        fn = await tool("acknowledge_alert")
        result = await fn(alert_id="al-1", user="alice")

        assert result["status"] == expected_status

    async def test_acknowledge_alert_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An ack exception is converted to an error envelope."""
        mock_app.monitoring_service.acknowledge_alert = _Boom("ack failed")

        fn = await tool("acknowledge_alert")
        result = await fn(alert_id="al-1", user="alice")

        assert result["status"] == "error"

    async def test_trigger_test_alert_requires_monitoring_service(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """No monitoring service means no test alert."""
        mock_app.monitoring_service = None

        fn = await tool("trigger_test_alert")
        result = await fn()

        assert result["status"] == "error"

    async def test_trigger_test_alert_rejects_bad_severity(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An unparseable severity is rejected before the alert is created."""
        mock_app.monitoring_service.alert_manager.trigger_alert = AsyncMock()

        fn = await tool("trigger_test_alert")
        result = await fn(severity="apocalyptic")

        assert result["status"] == "error"
        assert "Invalid severity" in result["error"]
        mock_app.monitoring_service.alert_manager.trigger_alert.assert_not_awaited()

    async def test_trigger_test_alert_success(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A valid severity produces an alert and returns its id."""
        from mahavishnu.core.monitoring import AlertSeverity, AlertType

        mock_app.monitoring_service.alert_manager.trigger_alert = AsyncMock(
            return_value=_fake_alert("al-test")
        )

        fn = await tool("trigger_test_alert")
        result = await fn(severity="HIGH", title="T", description="D")

        assert result["status"] == "success"
        assert result["alert_id"] == "al-test"
        kwargs = mock_app.monitoring_service.alert_manager.trigger_alert.await_args.kwargs
        assert kwargs["severity"] is AlertSeverity.HIGH
        assert kwargs["alert_type"] is AlertType.SYSTEM_HEALTH
        assert kwargs["details"] == {"test_alert": True}

    async def test_trigger_test_alert_wraps_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A trigger failure is caught at the MCP boundary."""
        mock_app.monitoring_service.alert_manager.trigger_alert = _Boom("cannot trigger")

        fn = await tool("trigger_test_alert")
        result = await fn(severity="low")

        assert result["status"] == "error"


# =============================================================================
# list_adapters / get_health
# =============================================================================


class _BoomRoles:
    """RBAC double whose ``roles`` property raises on access."""

    @property
    def roles(self) -> dict[str, Any]:
        raise RuntimeError("rbac registry corrupt")


class TestAdapterAndHealthTools:
    """``list_adapters`` feature tagging and ``get_health`` aggregation."""

    @pytest.mark.parametrize(
        ("adapter_name", "expected_feature"),
        [
            ("llamaindex", "RAG"),
            ("prefect", "Workflow Orchestration"),
            ("agno", "AI Agents"),
        ],
    )
    async def test_list_adapters_tags_known_adapters(
        self,
        server: FastMCPServer,
        tool: Callable[[str], Any],
        mock_app: MagicMock,
        adapter_name: str,
        expected_feature: str,
    ) -> None:
        """Each known adapter name gets its documented feature list."""
        adapter = MagicMock()
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})
        mock_app.adapters = {adapter_name: adapter}

        fn = await tool("list_adapters")
        result = await fn()

        assert result["count"] == 1
        assert expected_feature in result["adapters"][adapter_name]["features"]

    async def test_list_adapters_records_unhealthy_on_probe_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A failing health probe is recorded as unhealthy, not fatal."""
        adapter = MagicMock()
        adapter.get_health = _Boom("adapter offline")
        mock_app.adapters = {"prefect": adapter}

        fn = await tool("list_adapters")
        result = await fn()

        info = result["adapters"]["prefect"]
        assert info["health"]["status"] == "unhealthy"
        assert "adapter offline" in info["health"]["error"]
        assert info["features"] == []

    @staticmethod
    def _make_healthy_app(mock_app: MagicMock) -> None:
        """Wire the app so every ``get_health`` sub-probe reports healthy."""
        mock_app.is_healthy = AsyncMock(return_value=True)
        mock_app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        mock_app.rbac_manager.roles = {"admin": MagicMock()}
        mock_app.opensearch_integration.health_check = AsyncMock(return_value={"status": "healthy"})

    async def test_get_health_all_healthy(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """With every sub-probe healthy the aggregate status is healthy."""
        self._make_healthy_app(mock_app)

        fn = await tool("get_health")
        result = await fn()

        assert result["status"] == "healthy"
        assert result["rbac_healthy"] is True
        assert result["opensearch_healthy"] is True

    async def test_get_health_degraded_when_adapter_degraded(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A degraded adapter downgrades the aggregate to 'degraded'."""
        self._make_healthy_app(mock_app)
        adapter = MagicMock()
        adapter.get_health = AsyncMock(return_value={"status": "degraded"})
        mock_app.adapters = {"agno": adapter}

        fn = await tool("get_health")
        result = await fn()

        assert result["status"] == "degraded"

    async def test_get_health_unhealthy_when_adapter_probe_raises(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """An adapter probe exception marks that adapter — and the whole — unhealthy."""
        self._make_healthy_app(mock_app)
        adapter = MagicMock()
        adapter.get_health = _Boom("adapter exploded")
        mock_app.adapters = {"prefect": adapter}

        fn = await tool("get_health")
        result = await fn()

        assert result["status"] == "unhealthy"
        assert result["adapter_health"]["prefect"]["status"] == "unhealthy"

    async def test_get_health_reports_unhealthy_subsystems(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """Each sub-probe failure is captured independently in the response."""
        mock_app.is_healthy = AsyncMock(return_value=True)
        mock_app.workflow_state_manager.list_workflows = _Boom("wf store down")
        mock_app.rbac_manager = _BoomRoles()
        mock_app.opensearch_integration.health_check = _Boom("os down")

        fn = await tool("get_health")
        result = await fn()

        assert result["status"] == "unhealthy"
        assert result["workflow_state_healthy"] is False
        assert result["rbac_healthy"] is False
        assert result["opensearch_healthy"] is False
        assert "wf store down" in result["workflow_state_info"]["error"]
        assert "rbac registry corrupt" in result["rbac_info"]["error"]
        assert "os down" in result["opensearch_info"]["error"]

    async def test_get_health_wraps_top_level_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], mock_app: MagicMock
    ) -> None:
        """A failure in ``is_healthy`` short-circuits to an unhealthy envelope."""
        mock_app.is_healthy = _Boom("app probe exploded")

        fn = await tool("get_health")
        result = await fn()

        assert result["status"] == "unhealthy"
        assert "app probe exploded" in result["error"]


# =============================================================================
# Introspection tools: get_tool_versions / discover_tools
# =============================================================================


class TestIntrospectionTools:
    """Version registry lookups and profile-aware tool discovery."""

    async def test_tool_versions_returns_full_registry(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """Called without a name, every known tool version is returned."""
        from mahavishnu.mcp.tool_versions import TOOL_VERSIONS

        fn = await tool("get_tool_versions")
        result = await fn()

        assert result["status"] == "success"
        assert result["total_tools"] == len(TOOL_VERSIONS)
        assert result["versions"] == dict(TOOL_VERSIONS)

    async def test_tool_versions_single_known_tool(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """A registered tool name resolves to its version string."""
        from mahavishnu.mcp.tool_versions import TOOL_VERSIONS

        known = next(iter(TOOL_VERSIONS))

        fn = await tool("get_tool_versions")
        result = await fn(tool_name=known)

        assert result["status"] == "success"
        assert result["tool_name"] == known
        assert result["version"] == TOOL_VERSIONS[known]

    async def test_tool_versions_unknown_tool(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """An unregistered tool name yields status='not_found'."""
        fn = await tool("get_tool_versions")
        result = await fn(tool_name="definitely_not_a_registered_tool")

        assert result["status"] == "not_found"
        assert "not in version registry" in result["error"]

    async def test_discover_tools_partitions_loaded_and_not_loaded(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """Discovery splits the version registry against the live registry."""
        fn = await tool("discover_tools")
        result = await fn()

        assert result["status"] == "success"
        assert result["loaded_count"] == len(result["loaded_tools"])
        assert result["not_loaded_count"] == len(result["not_loaded_tools"])
        assert result["total_known"] == result["loaded_count"] + result["not_loaded_count"]
        # Core inline tools registered in __init__ must appear as loaded.
        assert "get_health" in result["loaded_tools"]
        assert not set(result["loaded_tools"]) & set(result["not_loaded_tools"])

    async def test_discover_tools_applies_query_filter(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """A query filters both partitions case-insensitively by substring."""
        fn = await tool("discover_tools")
        result = await fn(query="WORKFLOW")

        assert result["query"] == "WORKFLOW"
        every = result["loaded_tools"] + result["not_loaded_tools"]
        assert every, "expected at least one workflow tool"
        assert all("workflow" in name.lower() for name in every)

    async def test_discover_tools_survives_list_tools_failure(
        self, server: FastMCPServer, tool: Callable[[str], Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If FastMCP introspection fails, everything reports as not-loaded."""

        async def _explode() -> list[Any]:
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr(server.server, "list_tools", _explode)

        fn = await tool("discover_tools")
        result = await fn()

        assert result["status"] == "success"
        assert result["loaded_tools"] == []
        assert result["not_loaded_count"] == result["total_known"]

    async def test_discover_tools_capability_ready_adds_routable_workers(
        self, server: FastMCPServer, tool: Callable[[str], Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``capability='ready'`` attaches the router's worker snapshot."""
        from mahavishnu.core import config as config_module
        from mahavishnu.workers import capabilities

        monkeypatch.setattr(config_module, "MahavishnuSettings", MagicMock())
        monkeypatch.setattr(
            capabilities,
            "select_routable_workers",
            MagicMock(return_value=["worker-a", "worker-b"]),
        )

        fn = await tool("discover_tools")
        result = await fn(capability="ready")

        assert result["capability"] == "ready"
        assert result["routable_workers"] == ["worker-a", "worker-b"]

    async def test_discover_tools_omits_workers_without_capability(
        self, server: FastMCPServer, tool: Callable[[str], Any]
    ) -> None:
        """Without the capability gate the worker snapshot is not computed."""
        fn = await tool("discover_tools")
        result = await fn()

        assert "routable_workers" not in result


# =============================================================================
# _wrap_tool_handler — sync path and cancellation/timeout classification
# =============================================================================


class TestWrapToolHandlerBranches:
    """Cover the sync wrapper plus the cancelled/timeout status labels."""

    async def test_async_wrapper_propagates_cancellation(self, server: FastMCPServer) -> None:
        """CancelledError must propagate (never be swallowed as an error)."""

        async def cancelled_tool() -> None:
            raise asyncio.CancelledError

        wrapped = server._wrap_tool_handler(cancelled_tool)

        with pytest.raises(asyncio.CancelledError):
            await wrapped()

    async def test_async_wrapper_propagates_timeout(self, server: FastMCPServer) -> None:
        """TimeoutError is labelled 'timeout' and re-raised."""
        from monitoring.metrics import mcp_tool_calls_total

        async def timing_out_tool() -> None:
            raise TimeoutError

        wrapped = server._wrap_tool_handler(timing_out_tool)

        with pytest.raises(TimeoutError):
            await wrapped()

        counter = mcp_tool_calls_total.labels(tool_name="timing_out_tool", status="timeout")
        assert counter._value.get() >= 1

    def test_sync_wrapper_records_success(self, server: FastMCPServer) -> None:
        """A sync tool returns its value and is labelled 'success'."""
        from monitoring.metrics import mcp_tool_calls_total

        def sync_ok() -> dict[str, str]:
            return {"ok": "yes"}

        wrapped = server._wrap_tool_handler(sync_ok)

        assert wrapped() == {"ok": "yes"}
        counter = mcp_tool_calls_total.labels(tool_name="sync_ok", status="success")
        assert counter._value.get() >= 1

    def test_sync_wrapper_classifies_error_payload(self, server: FastMCPServer) -> None:
        """A sync tool returning an error dict is labelled 'error'."""
        from monitoring.metrics import mcp_tool_calls_total

        def sync_error_payload() -> dict[str, str]:
            return {"status": "error", "error": "nope"}

        wrapped = server._wrap_tool_handler(sync_error_payload)

        assert wrapped()["status"] == "error"
        counter = mcp_tool_calls_total.labels(tool_name="sync_error_payload", status="error")
        assert counter._value.get() >= 1

    def test_sync_wrapper_propagates_timeout(self, server: FastMCPServer) -> None:
        """A sync TimeoutError is labelled 'timeout' and re-raised."""
        from monitoring.metrics import mcp_tool_calls_total

        def sync_timeout() -> None:
            raise TimeoutError

        wrapped = server._wrap_tool_handler(sync_timeout)

        with pytest.raises(TimeoutError):
            wrapped()

        counter = mcp_tool_calls_total.labels(tool_name="sync_timeout", status="timeout")
        assert counter._value.get() >= 1

    def test_sync_wrapper_propagates_generic_error(self, server: FastMCPServer) -> None:
        """A sync exception is labelled 'error' and re-raised."""
        from monitoring.metrics import mcp_tool_calls_total

        def sync_raiser() -> None:
            raise ValueError("bad input")

        wrapped = server._wrap_tool_handler(sync_raiser)

        with pytest.raises(ValueError, match="bad input"):
            wrapped()

        counter = mcp_tool_calls_total.labels(tool_name="sync_raiser", status="error")
        assert counter._value.get() >= 1
