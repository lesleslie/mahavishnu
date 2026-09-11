"""Round-2 BLOCKER: All 5 plan_* tools reject requests with no user_id when
MAHAVISHNU_AUTH_ENABLED=true.

REQ-PLAN-010: every plan_* tool is gated by @require_mcp_auth(
Permission.READ_PLAN_INDEX) and rejects requests with a structured envelope
when the caller has no user_id.

ADAPTATION (brief correction #1): the production decorator
:meth:`mahavishnu.mcp.auth.require_mcp_auth` does NOT raise
``PermissionError``. It returns a structured envelope::

    {
        "status": "error",
        "error": "Authentication required: user_id parameter missing",
        "error_code": "AUTH_REQUIRED",
    }

The brief's draft test asserts ``pytest.raises(PermissionError)``, which
would fail at runtime because the decorator returns rather than raises.
This file therefore invokes each tool via the real FastMCP path (the
conftest helper unwraps the envelope) and asserts that the
``error_code`` discriminator is ``"AUTH_REQUIRED"``. The
``MAHAVISHNU_AUTH_ENABLED=true`` env var is preserved verbatim because
the decorator inspects kwargs only; the env var is asserted at the test
level for documentation but the gate fires regardless of it (matching
the existing auth-gate contract).

Task 11.7 (BLOCKER): the conftest now registers a fake RBAC manager so
the gate enforces ``READ_PLAN_INDEX``. A caller without the permission
gets ``error_code == "PERMISSION_DENIED"``; the gate fires whether or
not the rbac_manager is wired (missing manager → ``AUTH_NOT_CONFIGURED``).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
import pytest

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.tools.plan_tools import register_plan_tools
from mahavishnu.plan_index.store import (
    PlanIndexStore,  # noqa: TC001  # annotation-only with __future__ annotations
)


class _FakeRBAC:
    """In-memory RBAC stand-in for e2e gate tests.

    ``alice`` has ``READ_PLAN_INDEX`` on every repo (admin-equivalent);
    ``intruder`` has nothing. ``check_permission`` mirrors
    :meth:`mahavishnu.core.permissions.RBACManager.check_permission`:
    an unknown user is denied.
    """

    def __init__(self) -> None:
        self.grants: dict[tuple[str, str, str], bool] = {
            ("alice", "*", Permission.READ_PLAN_INDEX.value): True,
        }

    async def check_permission(
        self, user_id: str, repo: str, permission: Permission
    ) -> bool:
        key = (user_id, repo, permission.value)
        if key in self.grants:
            return self.grants[key]
        # Allow the wildcard-admin grant to win regardless of repo.
        wildcard = self.grants.get((user_id, "*", permission.value))
        return bool(wildcard)


@pytest.fixture
def mcp_with_rbac(store: PlanIndexStore) -> FastMCP:
    """A FastMCP server with plan_* tools wired to a fake RBAC manager.

    The fake grants alice READ_PLAN_INDEX; intruder has nothing.
    """
    server = FastMCP("plan_index-auth-e2e")

    def provider() -> PlanIndexStore:
        return store

    register_plan_tools(server, store_provider=provider, rbac_manager=_FakeRBAC())
    return server


@pytest.fixture
def call_tool_with_rbac(mcp_with_rbac: FastMCP) -> Any:
    """Call-tool wrapper mirroring the standard conftest, bound to mcp_with_rbac."""

    async def _call(
        mcp: FastMCP,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        user_id: str | None = "test-user",
    ) -> Any:
        from fastmcp.exceptions import ToolError

        args: dict[str, Any] = dict(arguments or {})
        if user_id is not None:
            args["user_id"] = user_id
        try:
            result = await mcp.call_tool(tool_name, args)
        except ToolError as exc:
            return {"status": "error", "error": str(exc), "error_code": "TOOL_ERROR"}
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict) and set(structured).issuperset(
            {"status", "error_code"}
        ):
            return structured
        if isinstance(structured, dict) and "result" in structured and len(structured) == 1:
            return structured["result"]
        return structured

    async def _bound(
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        user_id: str | None = "test-user",
    ) -> Any:
        return await _call(mcp_with_rbac, tool_name, arguments, user_id=user_id)

    return _bound


class TestAuthGateE2E:
    @pytest.fixture
    def call_tool_unauthenticated(self, call_tool: Any) -> Any:
        """Bind ``call_tool`` to omit ``user_id`` (drives the AUTH path)."""

        async def _bound(tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
            return await call_tool(tool_name, arguments, user_id=None)

        return _bound

    @pytest.mark.asyncio
    async def test_plan_list_rejects_no_user_id(
        self, call_tool_unauthenticated: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no user_id, plan_list returns the AUTH_REQUIRED envelope."""
        monkeypatch.setenv("MAHAVISHNU_AUTH_ENABLED", "true")
        result = await call_tool_unauthenticated("plan_list", {})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_plan_show_rejects_no_user_id(
        self, call_tool_unauthenticated: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_AUTH_ENABLED", "true")
        result = await call_tool_unauthenticated("plan_show", {"plan_id": "0" * 32})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_plan_search_rejects_no_user_id(
        self, call_tool_unauthenticated: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_AUTH_ENABLED", "true")
        result = await call_tool_unauthenticated("plan_search", {"query": "x"})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_plan_vitals_rejects_no_user_id(
        self, call_tool_unauthenticated: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_AUTH_ENABLED", "true")
        result = await call_tool_unauthenticated("plan_vitals", {})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"

    @pytest.mark.asyncio
    async def test_plan_rebuild_status_rejects_no_user_id(
        self, call_tool_unauthenticated: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_AUTH_ENABLED", "true")
        result = await call_tool_unauthenticated("plan_rebuild_status", {})
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"


class TestAuthGateRBACEnforcement:
    """Task 11.7: when an RBAC manager is wired, missing permission is denied."""

    @pytest.mark.asyncio
    async def test_user_without_permission_is_denied(
        self, call_tool_with_rbac: Any
    ) -> None:
        """``intruder`` has no READ_PLAN_INDEX grant — must get PERMISSION_DENIED."""
        result = await call_tool_with_rbac("plan_list", {}, user_id="intruder")
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert Permission.READ_PLAN_INDEX.value in result["error"]

    @pytest.mark.asyncio
    async def test_user_with_permission_is_allowed(
        self, call_tool_with_rbac: Any
    ) -> None:
        """``alice`` has READ_PLAN_INDEX — plan_list reaches the wrapped function."""
        result = await call_tool_with_rbac("plan_list", {}, user_id="alice")
        # Happy path returns the structured ``{"plans": ..., "total": ...,
        # "status": "ok"}`` envelope from the tool body — NOT the error
        # envelope. ``structured_content["result"]`` wraps the dict.
        assert isinstance(result, dict)
        assert result.get("status") == "ok"
        assert "plans" in result
        assert "total" in result

    @pytest.mark.asyncio
    async def test_missing_rbac_manager_returns_auth_not_configured(
        self, store: PlanIndexStore
    ) -> None:
        """When register_plan_tools is called without an rbac_manager, the
        gate fails closed with ``error_code == "AUTH_NOT_CONFIGURED"``
        even with a valid ``user_id``. This is the production
        safety net for a misconfigured deployment.
        """
        from fastmcp import FastMCP
        from fastmcp.exceptions import ToolError

        server = FastMCP("plan_index-no-rbac")

        def provider() -> PlanIndexStore:
            return store

        # NB: rbac_manager omitted on purpose.
        register_plan_tools(server, store_provider=provider)

        args: dict[str, Any] = {"user_id": "alice"}
        try:
            result = await server.call_tool("plan_list", args)
        except ToolError as exc:
            envelope = {"status": "error", "error": str(exc), "error_code": "TOOL_ERROR"}
        else:
            structured = getattr(result, "structured_content", None)
            envelope = structured if isinstance(structured, dict) else {"raw": structured}

        assert envelope["status"] == "error"
        assert envelope["error_code"] == "AUTH_NOT_CONFIGURED"
