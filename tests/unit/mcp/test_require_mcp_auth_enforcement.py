"""Unit tests for :func:`mahavishnu.mcp.auth.require_mcp_auth` enforcement.

Task 11.7 — RBACManager-driven gate. The decorator previously accepted
``rbac_manager`` and ``required_permission`` parameters but never enforced
them. This module asserts the four post-fix invariants:

* Missing ``user_id`` → ``AUTH_REQUIRED`` envelope (audit emitted).
* ``rbac_manager is None`` → ``AUTH_NOT_CONFIGURED`` envelope (fail-closed).
* ``rbac_manager.check_permission`` returns True → wrapped function runs;
  audit emitted with ``result="allowed"``.
* ``rbac_manager.check_permission`` returns False → ``PERMISSION_DENIED``
  envelope; audit emitted with ``result="denied"``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp_common.auth.audit import (
    AuthAuditEvent,  # noqa: TC002  # annotation-only with __future__ annotations
)
import pytest

from mahavishnu.core.permissions import Permission
import mahavishnu.mcp.auth as mcp_auth
from mahavishnu.mcp.auth import require_mcp_auth


class _FakeRBAC:
    """Configurable fake RBAC manager.

    Records every ``check_permission`` call so tests can assert on the
    arguments the decorator passes (user_id, repo, permission).
    """

    def __init__(self, *, allow: bool = True, repo_value: str = "*") -> None:
        self.allow = allow
        self.repo_value = repo_value
        self.calls: list[tuple[str, str, Permission]] = []

    async def check_permission(
        self, user_id: str, repo: str, permission: Permission
    ) -> bool:
        self.calls.append((user_id, repo, permission))
        return self.allow


class _SpyAuditLogger:
    """Capture-only stand-in for ``mahavishnu.mcp.auth._audit_logger``.

    Replaces the module-level singleton for the duration of one test so
    we can inspect the audit event payload without polluting other tests.
    """

    def __init__(self) -> None:
        self.events: list[AuthAuditEvent] = []

    def emit(self, event: AuthAuditEvent) -> None:
        self.events.append(event)


class TestRequireMCPAuthEnforcement:
    @pytest.fixture(autouse=True)
    def _swap_audit_logger(self, monkeypatch: pytest.MonkeyPatch) -> _SpyAuditLogger:
        """Replace the module-level audit logger with an in-memory spy.

        Returning the spy lets tests introspect emitted events directly.
        """
        spy = _SpyAuditLogger()
        monkeypatch.setattr(mcp_auth, "_audit_logger", spy)
        return spy

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_auth_required(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """No user_id → AUTH_REQUIRED envelope + audit emitted with result=denied."""
        decorator = require_mcp_auth(
            rbac_manager=_FakeRBAC(allow=True),
            required_permission=Permission.READ_PLAN_INDEX,
        )

        @decorator
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x")  # type: ignore[call-arg]

        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        assert "user_id" in result["error"]
        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        assert event.result == "denied"
        assert event.permission == Permission.READ_PLAN_INDEX
        assert event.caller_id == "unknown"
        assert event.reason == "No user_id provided"

    @pytest.mark.asyncio
    async def test_rbac_manager_none_returns_auth_not_configured(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """rbac_manager is None → fail-closed AUTH_NOT_CONFIGURED, even with user_id."""
        decorator = require_mcp_auth(rbac_manager=None)

        @decorator
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", user_id="alice")

        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_NOT_CONFIGURED"
        assert "RBAC manager" in result["error"]
        # No audit event for AUTH_NOT_CONFIGURED — it's a config error,
        # not a denied request.
        assert _swap_audit_logger.events == []

    @pytest.mark.asyncio
    async def test_rbac_allows_invokes_wrapped_function(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """rbac.check_permission returns True → wrapped function runs + allowed audit."""
        fake = _FakeRBAC(allow=True)

        @require_mcp_auth(
            rbac_manager=fake, required_permission=Permission.READ_PLAN_INDEX
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", user_id="alice")

        assert result == {"status": "ok", "arg": "x"}
        # check_permission was called with user_id + repo + perm.
        assert fake.calls == [("alice", "*", Permission.READ_PLAN_INDEX)]
        # Single allowed audit event.
        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        assert event.result == "allowed"
        assert event.permission == Permission.READ_PLAN_INDEX
        assert event.caller_id == "alice"
        assert event.reason is None

    @pytest.mark.asyncio
    async def test_rbac_denies_returns_permission_denied(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """rbac.check_permission returns False → PERMISSION_DENIED + denied audit."""
        fake = _FakeRBAC(allow=False)

        @require_mcp_auth(
            rbac_manager=fake, required_permission=Permission.READ_PLAN_INDEX
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", user_id="intruder")

        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert Permission.READ_PLAN_INDEX.value in result["error"]
        # Audit emitted with result=denied and the repo recorded in the reason.
        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        assert event.result == "denied"
        assert event.permission == Permission.READ_PLAN_INDEX
        assert event.caller_id == "intruder"
        assert event.reason is not None
        assert "RBAC denied" in event.reason

    @pytest.mark.asyncio
    async def test_repo_kwarg_passed_to_check_permission(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """When the wrapped tool has a ``repo`` kwarg, it is forwarded to RBAC."""
        fake = _FakeRBAC(allow=True)

        @require_mcp_auth(
            rbac_manager=fake, required_permission=Permission.READ_REPO
        )
        async def sample_tool(
            repo: str, user_id: str | None = None
        ) -> dict[str, Any]:
            return {"status": "ok", "repo": repo}

        result = await sample_tool(repo="github.com/foo/bar", user_id="alice")

        assert result == {"status": "ok", "repo": "github.com/foo/bar"}
        # repo was forwarded verbatim to check_permission.
        assert fake.calls == [("alice", "github.com/foo/bar", Permission.READ_REPO)]

    @pytest.mark.asyncio
    async def test_explicit_permission_is_forwarded(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """The decorator forwards the supplied ``required_permission`` to RBAC."""
        fake = _FakeRBAC(allow=True)

        @require_mcp_auth(
            rbac_manager=fake, required_permission=Permission.READ_PLAN_INDEX
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok"}

        await sample_tool(arg="x", user_id="alice")

        assert fake.calls == [("alice", "*", Permission.READ_PLAN_INDEX)]
        # Audit event carries the explicit permission.
        assert _swap_audit_logger.events[0].permission == Permission.READ_PLAN_INDEX

    @pytest.mark.asyncio
    async def test_audit_event_shape_matches_contract(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """Audit event fields line up with the AuthAuditEvent signature."""
        fake = _FakeRBAC(allow=True)

        @require_mcp_auth(rbac_manager=fake, required_permission=Permission.READ_PLAN_INDEX)
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok"}

        before = datetime.now(UTC)
        await sample_tool(arg="x", user_id="alice")
        after = datetime.now(UTC)

        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        # Required fields per AuthAuditEvent:
        assert event.service == "mahavishnu"
        assert event.caller_service == "unknown"
        assert event.caller_id == "alice"
        assert event.action == "sample_tool"
        assert event.permission == Permission.READ_PLAN_INDEX
        assert event.result == "allowed"
        assert event.source_ip is None
        assert event.token_id is None
        # Timestamp is a datetime within the test window.
        assert isinstance(event.timestamp, datetime)
        assert before <= event.timestamp <= after
