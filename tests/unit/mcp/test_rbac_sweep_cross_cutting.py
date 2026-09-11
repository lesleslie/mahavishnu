"""Cross-cutting RBAC sweep — Task 11.8.

The Task 11.7 fix made ``require_mcp_auth`` fail-closed when its
``rbac_manager`` argument is ``None``. Five additional tool files have
the same latent defect — they call ``@require_mcp_auth(...)`` without
threading ``rbac_manager`` through from the bootstrap wiring.

This module asserts the post-fix invariant for one representative tool
from each of the five files:

* ``webhook_tools.webhook_replay_tool`` → ``Permission.READ_WEBHOOK``
* ``workflow_tools.workflow_get_outcome_tool`` → ``Permission.VIEW_WORKFLOW_STATUS``
* ``capability_tools.resolve_capabilities`` → ``MCPPermissionCommon.READ``
* ``session_buddy_tools.index_code_graph`` → ``MCPPermissionCommon.READ``
* ``git_analytics.get_cross_project_patterns`` → ``MCPPermissionCommon.READ``

For each tool we verify three envelopes:

1. ``rbac_manager=None`` → ``AUTH_NOT_CONFIGURED``
2. ``rbac_manager=fake_rbac`` + missing ``user_id`` → ``AUTH_REQUIRED``
3. ``rbac_manager=fake_rbac`` (deny) + ``user_id`` → ``PERMISSION_DENIED``

The fourth code path (``rbac_manager=fake_rbac`` allow + ``user_id``)
is covered exhaustively by ``tests/unit/mcp/test_require_mcp_auth_enforcement.py``
and is not re-tested here — this module's purpose is to lock the wiring
contract for the cross-cutting sweep.

Mirrors the test structure established by Task 11.7's
``tests/unit/mcp/test_require_mcp_auth_enforcement.py`` (same FakeRBAC
shape, same envelope assertions).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from fastmcp import FastMCP
from mcp_common.auth.permissions import Permission as MCPPermissionCommon
import pytest

from mahavishnu.core.config import EnginesConfig, WorkerRegistryConfig
from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.tools import (
    capability_tools,
    git_analytics,
    session_buddy_tools,
    webhook_tools,
    workflow_tools,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeRBAC:
    """Configurable fake RBAC manager — mirrors the Task 11.7 shape."""

    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str, Any]] = []

    async def check_permission(
        self, user_id: str, repo: str, permission: Any
    ) -> bool:
        self.calls.append((user_id, repo, permission))
        return self.allow


class _StubMCP:
    """Minimal FastMCP stand-in that captures decorated functions.

    The session_buddy and git_analytics tool bodies do
    ``getattr(server, "app", None)`` and (git_analytics) read
    ``app.dhara_url``, so we expose an ``app`` MagicMock with that
    attribute so the tools reach the auth-gate short-circuit instead
    of blowing up on a missing attribute.
    """

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}
        self.app = MagicMock(name="app")
        self.app.dhara_url = "http://dhara:8683"

    def tool(self, *args: Any, **kwargs: Any):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _capability_settings() -> Any:
    """Build a settings object that satisfies capability_tools interface."""
    settings = MagicMock()
    settings.capability_enabled = True
    settings.capability_scopes = []
    settings.worker_registry = WorkerRegistryConfig(entries=[])
    settings.engines = EnginesConfig(disabled=[])
    return settings


# ---------------------------------------------------------------------------
# Per-file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def webhook_mcp() -> _StubMCP:
    mcp = _StubMCP()
    webhook_tools.register_webhook_tools(mcp)  # rbac_manager=None (default)
    return mcp


@pytest.fixture
def workflow_mcp() -> _StubMCP:
    mcp = _StubMCP()
    workflow_tools.register_workflow_tools(mcp)
    return mcp


@pytest.fixture
def capability_mcp() -> _StubMCP:
    mcp = _StubMCP()
    capability_tools.register_capability_tools(mcp, _capability_settings())
    return mcp


@pytest.fixture
def session_buddy_mcp() -> _StubMCP:
    mcp = _StubMCP()
    session_buddy_tools.register_session_buddy_tools(
        mcp,
        session_manager=MagicMock(),
        mcp_client=MagicMock(),
        rbac_manager=None,
    )
    return mcp


@pytest.fixture
def git_analytics_mcp() -> _StubMCP:
    mcp = _StubMCP()
    git_analytics.register_git_analytics_tools(
        mcp, MagicMock(name="mcp_client"), rbac_manager=None
    )
    return mcp


# ---------------------------------------------------------------------------
# Tests — one per tool file. Each asserts the three required envelopes.
# ---------------------------------------------------------------------------


class TestWebhookToolsRBAC:
    """webhook_tools: register_webhook_tools must thread rbac_manager through."""

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, webhook_mcp: _StubMCP
    ) -> None:
        """rbac_manager omitted → fail-closed AUTH_NOT_CONFIGURED even with user_id."""
        tool = webhook_mcp.tools["webhook_replay_tool"]
        result = await tool(webhook_id="wh-1", user_id="alice", token="a.b.c")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, webhook_mcp: _StubMCP
    ) -> None:
        """Fake RBAC + no user_id → AUTH_REQUIRED envelope."""
        fake = _FakeRBAC(allow=True)
        mcp = _StubMCP()
        webhook_tools.register_webhook_tools(mcp, rbac_manager=fake)
        tool = mcp.tools["webhook_replay_tool"]

        result = await tool(webhook_id="wh-1", token="a.b.c")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        # check_permission was NOT called — the gate short-circuits before RBAC.
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_intruder_returns_permission_denied(
        self, webhook_mcp: _StubMCP
    ) -> None:
        """Fake RBAC (deny) + user_id → PERMISSION_DENIED envelope."""
        fake = _FakeRBAC(allow=False)
        mcp = _StubMCP()
        webhook_tools.register_webhook_tools(mcp, rbac_manager=fake)
        tool = mcp.tools["webhook_replay_tool"]

        result = await tool(webhook_id="wh-1", user_id="intruder", token="a.b.c")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        # RBAC was consulted; perm READ_WEBHOOK was forwarded.
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "intruder"
        assert fake.calls[0][2] == Permission.READ_WEBHOOK


class TestWorkflowToolsRBAC:
    """workflow_tools: register_workflow_tools must thread rbac_manager through."""

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, workflow_mcp: _StubMCP
    ) -> None:
        tool = workflow_mcp.tools["workflow_get_outcome_tool"]
        result = await tool(workflow_id="wf-abc", user_id="alice")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, workflow_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=True)
        mcp = _StubMCP()
        workflow_tools.register_workflow_tools(mcp, rbac_manager=fake)
        tool = mcp.tools["workflow_get_outcome_tool"]

        result = await tool(workflow_id="wf-abc")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_intruder_returns_permission_denied(
        self, workflow_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=False)
        mcp = _StubMCP()
        workflow_tools.register_workflow_tools(mcp, rbac_manager=fake)
        tool = mcp.tools["workflow_get_outcome_tool"]

        result = await tool(workflow_id="wf-abc", user_id="intruder")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "intruder"
        assert fake.calls[0][2] == Permission.VIEW_WORKFLOW_STATUS


class TestCapabilityToolsRBAC:
    """capability_tools: register_capability_tools must thread rbac_manager through.

    ``resolve_capabilities`` is the canonical READ-gated tool; the
    WRITE-gated siblings (``plan_capability``, ``execute_capability``)
    share the same decorator wiring and are covered transitively.
    """

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, capability_mcp: _StubMCP
    ) -> None:
        tool = capability_mcp.tools["resolve_capabilities"]
        result = await tool(
            requires=["worker:bash"], prompt="echo hello", user_id="alice"
        )
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, capability_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=True)
        mcp = _StubMCP()
        capability_tools.register_capability_tools(
            mcp, _capability_settings(), rbac_manager=fake
        )
        tool = mcp.tools["resolve_capabilities"]

        result = await tool(requires=["worker:bash"], prompt="echo hello")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_intruder_returns_permission_denied(
        self, capability_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=False)
        mcp = _StubMCP()
        capability_tools.register_capability_tools(
            mcp, _capability_settings(), rbac_manager=fake
        )
        tool = mcp.tools["resolve_capabilities"]

        result = await tool(
            requires=["worker:bash"], prompt="echo hello", user_id="intruder"
        )

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "intruder"
        # capability_tools uses MCPPermissionCommon.READ (per brief, do not change).
        assert fake.calls[0][2] == MCPPermissionCommon.READ


class TestSessionBuddyToolsRBAC:
    """session_buddy_tools: index_code_graph is the canonical READ tool.

    Note: 5 of the 9 ``@require_mcp_auth(...)`` decorators in
    ``session_buddy_tools.py`` (lines 155, 174, 210, 228, 293) currently
    lack an explicit ``required_permission=`` argument and fail-fast at
    decorator-application time (Task 11.10's strict removal of the
    ``Permission.READ`` fallback). Those tools are out of scope for Task
    11.8 (which is concerned with ``rbac_manager`` wiring). We test
    ``index_code_graph`` here because it has both ``rbac_manager=`` AND
    ``required_permission=`` in its decorator and so exercises the
    complete gate.
    """

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, session_buddy_mcp: _StubMCP
    ) -> None:
        tool = session_buddy_mcp.tools["index_code_graph"]
        result = await tool(project_path="/tmp/proj", user_id="alice")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, session_buddy_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=True)
        mcp = _StubMCP()
        session_buddy_tools.register_session_buddy_tools(
            mcp,
            session_manager=MagicMock(),
            mcp_client=MagicMock(),
            rbac_manager=fake,
        )
        tool = mcp.tools["index_code_graph"]

        result = await tool(project_path="/tmp/proj")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_intruder_returns_permission_denied(
        self, session_buddy_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=False)
        mcp = _StubMCP()
        session_buddy_tools.register_session_buddy_tools(
            mcp,
            session_manager=MagicMock(),
            mcp_client=MagicMock(),
            rbac_manager=fake,
        )
        tool = mcp.tools["index_code_graph"]

        result = await tool(project_path="/tmp/proj", user_id="intruder")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "intruder"
        # session_buddy_tools uses MCPPermissionCommon.READ.
        assert fake.calls[0][2] == MCPPermissionCommon.READ


class TestGitAnalyticsToolsRBAC:
    """git_analytics: get_cross_project_patterns is the canonical READ tool."""

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, git_analytics_mcp: _StubMCP
    ) -> None:
        tool = git_analytics_mcp.tools["get_cross_project_patterns"]
        result = await tool(days_back=7, user_id="alice")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, git_analytics_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=True)
        mcp = _StubMCP()
        git_analytics.register_git_analytics_tools(
            mcp, MagicMock(name="mcp_client"), rbac_manager=fake
        )
        tool = mcp.tools["get_cross_project_patterns"]

        result = await tool(days_back=7)

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        assert fake.calls == []

    @pytest.mark.asyncio
    async def test_intruder_returns_permission_denied(
        self, git_analytics_mcp: _StubMCP
    ) -> None:
        fake = _FakeRBAC(allow=False)
        mcp = _StubMCP()
        git_analytics.register_git_analytics_tools(
            mcp, MagicMock(name="mcp_client"), rbac_manager=fake
        )
        tool = mcp.tools["get_cross_project_patterns"]

        result = await tool(days_back=7, user_id="intruder")

        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert len(fake.calls) == 1
        assert fake.calls[0][0] == "intruder"
        assert fake.calls[0][2] == MCPPermissionCommon.READ


# ---------------------------------------------------------------------------
# Source-inspection guard
# ---------------------------------------------------------------------------


class TestBootstrapWiring:
    """bootstrap.py must thread rbac_manager at all 5 brief-specified callsites.

    The brief lists exactly 5 callsites: capability_tools, workflow_tools,
    webhook_tools, session_buddy_tools, git_analytics_tools. The
    register_profile_tools() wrapper at ``bootstrap.py:824-843`` and the
    ``_register_core_integration_tools()`` block at lines 320-346 also call
    these functions but are out of scope for Task 11.8 — they remain
    ``rbac_manager=None`` callsites until Task 11.8.x widens the sweep.
    """

    @pytest.mark.parametrize(
        "call_line",
        [
            "_register_capability_block",  # line 658
            "_register_workflow_tools",  # line 873
            "_register_webhook_tools",  # line 882
            "_register_session_buddy_tools",  # line 902
            "_register_git_analytics_tools",  # line 910
        ],
    )
    def test_bootstrap_callsite_threads_rbac_manager(
        self, call_line: str
    ) -> None:
        """Each callsite must include ``rbac_manager=getattr(server.app, ...)``."""
        import inspect

        from mahavishnu.mcp import bootstrap

        source = inspect.getsource(bootstrap)
        # The function definition + the next ~6 lines is enough to capture
        # the register_*_tools(...) call.
        func_idx = source.find(f"def {call_line}")
        assert func_idx != -1, f"{call_line} not found in bootstrap.py"
        snippet = source[func_idx : func_idx + 1500]
        assert "rbac_manager" in snippet, (
            f"{call_line} does not thread rbac_manager into the register_*_tools call"
        )
        assert "getattr(server.app" in snippet, (
            f"{call_line} does not use the canonical getattr(server.app, 'rbac_manager', None) pattern"
        )