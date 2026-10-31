"""Tests for the internal MCP self-call credential.

The substrate calls mahavishnu's own MCP server from inside the server
process, so they need an identity. The identity must be a *credential*,
not a name: the auth gate resolves ``user_id`` from the tool-call
arguments, which the caller controls, so a principal expressed as a name
would be claimable by any client that can reach the server.

These tests pin:

* the credential itself (issued once per process, verified in constant
  time);
* that the auth gate refuses a caller that only supplies the internal
  principal's *name*;
* that the gate allows the principal once the credential is verified;
* that the middleware maps a verified credential onto the principal;
* that the principal's role stays least-privilege.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.mcp.internal_auth import (
    INTERNAL_PRINCIPAL_STATE_KEY,
    INTERNAL_SERVICE_USER_ID,
    bearer_token_from_headers,
    get_internal_token,
    verify_internal_token,
)


class _AlwaysAllow:
    """Permissive RBAC stand-in — the credential check is what's under test."""

    async def check_permission(self, user_id: str, repo: str, permission: Permission) -> bool:
        return True


def _gated_tool(manager: Any = None) -> Any:
    decorator = require_mcp_auth(
        rbac_manager=manager or _AlwaysAllow(),
        required_permission=Permission.WRITE_ECOSYSTEM_STATE,
    )

    @decorator
    async def tool(key: str, user_id: str | None = None) -> dict:
        return {"status": "success", "key": key}

    return tool


# =============================================================================
# THE CREDENTIAL
# =============================================================================


class TestInternalToken:
    def test_token_is_stable_within_the_process(self) -> None:
        assert get_internal_token() == get_internal_token()

    def test_token_is_long_and_random(self) -> None:
        token = get_internal_token()
        assert len(token) >= 32

    def test_verify_accepts_the_current_token(self) -> None:
        assert verify_internal_token(get_internal_token()) is True

    def test_verify_rejects_a_wrong_token(self) -> None:
        assert verify_internal_token("not-the-token") is False

    def test_verify_rejects_none_and_empty(self) -> None:
        assert verify_internal_token(None) is False
        assert verify_internal_token("") is False


class TestBearerTokenExtraction:
    def test_reads_the_authorization_header(self) -> None:
        assert bearer_token_from_headers({"authorization": "Bearer abc123"}) == "abc123"

    def test_reads_the_capitalized_spelling(self) -> None:
        assert bearer_token_from_headers({"Authorization": "Bearer abc123"}) == "abc123"

    def test_ignores_a_non_bearer_scheme(self) -> None:
        assert bearer_token_from_headers({"authorization": "Basic abc123"}) is None

    def test_handles_missing_headers(self) -> None:
        assert bearer_token_from_headers(None) is None
        assert bearer_token_from_headers({}) is None


# =============================================================================
# THE GATE
# =============================================================================


class TestInternalPrincipalIsNotClaimable:
    """The name alone must not be enough."""

    @pytest.mark.asyncio
    async def test_claiming_the_name_is_denied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A caller that supplies the principal's name gets nothing.

        The RBAC check would happily resolve ``mahavishnu-internal``, so
        the gate must refuse on the credential, not on the permission.
        """
        monkeypatch.setattr(
            "mahavishnu.mcp.auth.internal_principal_verified", _async_false, raising=True
        )

        result = await _gated_tool()(key="k", user_id=INTERNAL_SERVICE_USER_ID)

        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_INVALID_IDENTITY"
        assert "verified credential" in result["error"]

    @pytest.mark.asyncio
    async def test_a_verified_credential_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "mahavishnu.mcp.auth.internal_principal_verified", _async_true, raising=True
        )

        result = await _gated_tool()(key="k", user_id=INTERNAL_SERVICE_USER_ID)

        assert result == {"status": "success", "key": "k"}

    @pytest.mark.asyncio
    async def test_other_users_are_unaffected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the internal principal needs the credential."""
        monkeypatch.setattr(
            "mahavishnu.mcp.auth.internal_principal_verified", _async_false, raising=True
        )

        result = await _gated_tool()(key="k", user_id="alice")

        assert result == {"status": "success", "key": "k"}


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


# =============================================================================
# THE MIDDLEWARE
# =============================================================================


class _FakeFastMCPContext:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}

    async def set_state(self, key: str, value: Any) -> None:
        self.state[key] = value

    async def get_state(self, key: str) -> Any:
        return self.state.get(key)


class _FakeMiddlewareContext:
    def __init__(self, arguments: dict[str, Any]) -> None:
        self.message = type("Msg", (), {"arguments": arguments})()
        self.fastmcp_context = _FakeFastMCPContext()


class TestMiddlewareMapsCredentialToPrincipal:
    @pytest.mark.asyncio
    async def test_verified_credential_yields_the_internal_principal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mahavishnu.mcp.middleware import auth_context as ac

        monkeypatch.setattr(
            ac,
            "request_headers",
            lambda: {"authorization": f"Bearer {get_internal_token()}"},
        )

        ctx = _FakeMiddlewareContext({"key": "k"})
        await ac.AuthContextMiddleware().on_call_tool(ctx, lambda _c: _noop())

        assert ctx.fastmcp_context.state["mahavishnu.user_id"] == INTERNAL_SERVICE_USER_ID
        assert ctx.fastmcp_context.state[INTERNAL_PRINCIPAL_STATE_KEY] is True

    @pytest.mark.asyncio
    async def test_a_claimed_name_is_not_marked_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The argument-derived identity never carries the verified flag."""
        from mahavishnu.mcp.middleware import auth_context as ac

        monkeypatch.setattr(ac, "request_headers", dict)

        ctx = _FakeMiddlewareContext({"key": "k", "user_id": INTERNAL_SERVICE_USER_ID})
        await ac.AuthContextMiddleware().on_call_tool(ctx, lambda _c: _noop())

        assert ctx.fastmcp_context.state["mahavishnu.user_id"] == INTERNAL_SERVICE_USER_ID
        assert ctx.fastmcp_context.state[INTERNAL_PRINCIPAL_STATE_KEY] is False

    @pytest.mark.asyncio
    async def test_a_wrong_token_is_not_the_principal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mahavishnu.mcp.middleware import auth_context as ac

        monkeypatch.setattr(
            ac, "request_headers", lambda: {"authorization": "Bearer definitely-not-the-token"}
        )

        ctx = _FakeMiddlewareContext({"key": "k"})
        await ac.AuthContextMiddleware().on_call_tool(ctx, lambda _c: _noop())

        assert ctx.fastmcp_context.state[INTERNAL_PRINCIPAL_STATE_KEY] is False
        assert ctx.fastmcp_context.state["mahavishnu.user_id"] != INTERNAL_SERVICE_USER_ID


async def _noop() -> Any:
    return None


# =============================================================================
# REGISTRATION
# =============================================================================


class TestKvToolsAreRegisteredAtEveryTier:
    """The KV tools must exist at every profile tier.

    The plan_index subsystem is started in the server lifespan at every
    profile and reaches its lock store over the MCP substrate, so a tier
    without the KV tools has a plan_index with no backend.
    """

    def test_kv_group_is_in_every_registration_list(self) -> None:
        from mahavishnu.mcp.tools.profiles import (
            FULL_REGISTRATIONS,
            MINIMAL_REGISTRATIONS,
            STANDARD_REGISTRATIONS,
        )

        for registrations in (
            MINIMAL_REGISTRATIONS,
            STANDARD_REGISTRATIONS,
            FULL_REGISTRATIONS,
        ):
            assert "_register_kv_tools" in registrations

    def test_kv_group_is_in_the_mandatory_set(self) -> None:
        """The W0 registration path consults the mandatory set."""
        from mahavishnu.mcp.tools.profiles import MAHAVISHNU_MANDATORY_GROUPS

        assert "_register_kv_tools" in MAHAVISHNU_MANDATORY_GROUPS

    def test_kv_group_is_in_the_registration_map(self) -> None:
        from mahavishnu.mcp.tools.profiles import REGISTRATION_MAP

        assert "_register_kv_tools" in REGISTRATION_MAP

    def test_kv_group_is_dispatched_by_the_live_registration_path(self) -> None:
        """The startup path dispatches through ``_OPTIONAL_TOOL_BLOCKS``.

        ``register_profile_tools`` (the path ``mahavishnu mcp start``
        actually takes) keeps its own table of profile groups. A group
        missing from that table is never installed, however it is
        listed in ``PROFILE_REGISTRATIONS`` — which is exactly how the
        KV tools stayed unregistered on the running server.
        """
        from mahavishnu.mcp.bootstrap import _OPTIONAL_TOOL_BLOCKS

        assert "_register_kv_tools" in {name for name, _ in _OPTIONAL_TOOL_BLOCKS}


# =============================================================================
# LEAST PRIVILEGE
# =============================================================================


class TestInternalServiceRole:
    def test_role_grants_exactly_the_two_ecosystem_permissions(self) -> None:
        from mahavishnu.core.permissions import RBACManager

        manager = RBACManager(SimpleNamespace())
        role = manager.roles["internal_service"]

        assert set(role.permissions) == {
            Permission.READ_ECOSYSTEM_STATE,
            Permission.WRITE_ECOSYSTEM_STATE,
        }

    def test_role_is_not_the_admin_role(self) -> None:
        from mahavishnu.core.permissions import RBACManager

        manager = RBACManager(SimpleNamespace())
        admin = manager.roles["admin"]

        assert set(manager.roles["internal_service"].permissions) != set(admin.permissions)
