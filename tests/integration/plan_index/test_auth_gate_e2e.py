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
"""

from __future__ import annotations

from typing import Any

import pytest


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
