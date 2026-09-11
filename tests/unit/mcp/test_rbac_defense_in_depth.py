"""Defense-in-depth tests for :func:`mahavishnu.mcp.auth.require_mcp_auth`.

Task 11.10 — covers two latent defects in ``mahavishnu/mcp/auth.py``:

1. **Removed ``Permission.READ`` fallback.** The decorator previously
   fell back to ``Permission.READ`` (a generic "anything in the read
   namespace") when no ``required_permission`` was specified. The
   replacement contract is fail-fast: a missing ``required_permission``
   raises :class:`~mahavishnu.core.errors.ConfigurationError` at
   decorator-application time so the offender surfaces as a hard import
   error rather than silently granting a broad permission.

2. **Wrapped ``rbac_manager.check_permission``** in
   ``try / except Exception``. A buggy RBAC (Dhara network down,
   ``JSONDecodeError`` on stored user data, etc.) MUST deny with an audit
   event — it must never propagate out of the gate, where it would
   bypass the audit trail and either 500 to the caller or accidentally
   allow through whatever fallback the framework picks.

The pre-existing test module ``test_require_mcp_auth_enforcement.py``
covers the happy paths (allowed, denied, missing user_id, missing
rbac_manager, repo forwarding, audit shape). This module targets the
two NEW failure modes added in 11.10.
"""

from __future__ import annotations

from typing import Any

from mcp_common.auth.audit import (
    AuthAuditEvent,  # noqa: TC002  # annotation-only with __future__ annotations
)
import pytest

from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.permissions import Permission
import mahavishnu.mcp.auth as mcp_auth
from mahavishnu.mcp.auth import require_mcp_auth


class _FakeRBAC:
    """Allow-all RBAC stand-in. Keeps the constructor shape minimal so the
    decorator-application tests don't need a real manager.
    """

    async def check_permission(self, *args: Any, **kwargs: Any) -> bool:
        return True


class _ExplodingRBAC:
    """RBAC that always raises — used to assert defense-in-depth behavior.

    The exception class is :class:`RuntimeError` (a built-in, never
    caught by ``except`` accidentally at module level) and the message
    is a stable sentinel so the audit-reason assertion can match
    deterministically.
    """

    async def check_permission(self, *args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("Dhara network down")


class _SpyAuditLogger:
    """Capture-only stand-in for ``mahavishnu.mcp.auth._audit_logger``.

    Mirrors the spy pattern from ``test_require_mcp_auth_enforcement.py``
    so the two modules stay stylistically aligned.
    """

    def __init__(self) -> None:
        self.events: list[AuthAuditEvent] = []

    def emit(self, event: AuthAuditEvent) -> None:
        self.events.append(event)


class TestDecoratorFactoryFailFast:
    """The decorator factory must reject missing ``required_permission``.

    The check fires inside the decorator factory body — BEFORE the
    ``@wraps(func)`` wrapper closure — so it surfaces as a hard error
    at module import time rather than at first call.
    """

    def test_rejects_missing_required_permission_at_application_time(self) -> None:
        """``@require_mcp_auth()`` without ``required_permission=`` raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:

            @require_mcp_auth(rbac_manager=_FakeRBAC())
            async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
                return {"status": "ok"}

        # The error names the function so operators can locate the offender.
        message = str(exc_info.value)
        assert "sample_tool" in message
        assert "required_permission" in message
        # details dict surfaces the function name for structured loggers.
        assert exc_info.value.details == {"function": "sample_tool"}

    def test_rejects_missing_required_permission_with_none_explicit(self) -> None:
        """Passing ``required_permission=None`` explicitly is the same contract violation."""
        with pytest.raises(ConfigurationError):

            @require_mcp_auth(rbac_manager=_FakeRBAC(), required_permission=None)
            async def another_tool(user_id: str | None = None) -> dict[str, Any]:
                return {"status": "ok"}

    def test_accepts_explicit_required_permission(self) -> None:
        """``required_permission=Permission.X`` does NOT raise — sanity check that the
        contract still works when honored."""

        @require_mcp_auth(
            rbac_manager=_FakeRBAC(),
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def compliant_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok"}

        # The wrapper is applied; we just want to prove the factory ran
        # without raising — the actual call is covered by the existing
        # enforcement tests.
        assert callable(compliant_tool)


class TestRBACExceptionIsDefenseInDepth:
    """Defense-in-depth: a buggy RBAC must DENY with audit, never propagate
    or accidentally allow. The two assertions are:

    * The caller receives a ``PERMISSION_DENIED`` envelope (NOT a 500).
    * The audit event captures the exception class + message in the
      ``reason`` field, so operators can correlate the deny to the
      underlying RBAC failure.
    """

    @pytest.fixture(autouse=True)
    def _swap_audit_logger(self, monkeypatch: pytest.MonkeyPatch) -> _SpyAuditLogger:
        spy = _SpyAuditLogger()
        monkeypatch.setattr(mcp_auth, "_audit_logger", spy)
        return spy

    @pytest.mark.asyncio
    async def test_rbac_exception_returns_permission_denied(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """Exploding RBAC → PERMISSION_DENIED envelope (caller never sees 500)."""
        exploding = _ExplodingRBAC()

        @require_mcp_auth(
            rbac_manager=exploding,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok"}

        result = await sample_tool(arg="x", user_id="alice")

        assert result["status"] == "error"
        assert result["error_code"] == "PERMISSION_DENIED"
        assert Permission.READ_PLAN_INDEX.value in result["error"]

    @pytest.mark.asyncio
    async def test_rbac_exception_audit_captures_class_and_message(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """Denied audit reason embeds the exception class + message so
        operators can distinguish a real RBAC denial from a buggy RBAC
        that crashed mid-check."""
        exploding = _ExplodingRBAC()

        @require_mcp_auth(
            rbac_manager=exploding,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            return {"status": "ok"}

        await sample_tool(arg="x", user_id="alice")

        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        assert event.result == "denied"
        assert event.caller_id == "alice"
        assert event.permission == Permission.READ_PLAN_INDEX
        # The exception class + message must both be present so the deny
        # is distinguishable from a regular "RBAC denied for repo=*"
        # denial. Format is "RBAC raised: <ClassName>: <message>".
        assert event.reason is not None
        assert "RuntimeError" in event.reason
        assert "Dhara network down" in event.reason
        # Prefix is stable for grep / alerting.
        assert event.reason.startswith("RBAC raised: ")

    @pytest.mark.asyncio
    async def test_rbac_exception_does_not_invoke_wrapped_function(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """The wrapped function MUST NOT run when the RBAC raises — that
        would mean the gate was bypassed and the tool ran without an
        audit-allowed event."""
        call_count = 0

        @require_mcp_auth(
            rbac_manager=_ExplodingRBAC(),
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(arg: str, user_id: str | None = None) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"status": "ok"}

        await sample_tool(arg="x", user_id="alice")

        assert call_count == 0
