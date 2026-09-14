"""Unit tests for FastMCP session-context user_id extraction.

Task 11.9 — production callers authenticate via the request's
``Authorization: Bearer <jwt>`` header. The middleware extracts the
user_id and stores it under the namespaced Context-state key
``"mahavishnu.user_id"``; the ``@require_mcp_auth`` decorator prefers
that key over kwargs at gate time.

Three test invariants:

1. The decorator reads ``user_id`` from Context state when kwargs is
   empty (production path).
2. kwargs ``user_id`` works as the fallback when Context state is
   absent (test path) — defense-in-depth layering (Task 11.9 ruling).
3. ``AuthContextMiddleware.on_call_tool`` extracts the Bearer token
   from the ``arguments`` payload and persists ``user_id`` to Context
   state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.core.permissions import Permission
import mahavishnu.mcp.auth as mcp_auth
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.mcp.middleware.auth_context import (
    USER_ID_STATE_KEY,
    AuthContextMiddleware,
)

if TYPE_CHECKING:
    from fastmcp.server.middleware.middleware import MiddlewareContext
    from mcp_common.auth.audit import AuthAuditEvent


class _FakeRBAC:
    """Configurable fake RBAC manager.

    Records every ``check_permission`` call so tests can assert on the
    arguments the decorator passes (user_id, repo, permission).
    """

    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[str, str, Permission]] = []

    async def check_permission(
        self, user_id: str, repo: str, permission: Permission
    ) -> bool:
        self.calls.append((user_id, repo, permission))
        return self.allow


class _SpyAuditLogger:
    """In-memory spy for the module-level audit logger."""

    def __init__(self) -> None:
        self.events: list[AuthAuditEvent] = []

    def emit(self, event: AuthAuditEvent) -> None:
        self.events.append(event)


class _FakeContext:
    """Minimal stand-in for ``fastmcp.server.context.Context``.

    Implements only the ``set_state`` / ``get_state`` surface used by
    the middleware and decorator. Keeps an in-memory dict so reads see
    prior writes.
    """

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state: dict[str, Any] = dict(state or {})
        self.set_calls: list[tuple[str, Any]] = []

    async def set_state(self, key: str, value: Any) -> None:
        self.set_calls.append((key, value))
        self.state[key] = value

    async def get_state(self, key: str) -> Any:
        return self.state.get(key)


class _FakeCallToolMessage:
    """Minimal stand-in for ``mcp_types.CallToolRequestParams``.

    Carries the ``arguments`` attribute the middleware reads.
    """

    def __init__(self, arguments: dict[str, Any]) -> None:
        self.arguments = arguments


def _build_call_context(
    *,
    arguments: dict[str, Any] | None = None,
    fastmcp_context: _FakeContext | None = None,
) -> MiddlewareContext[Any]:
    """Build a real :class:`MiddlewareContext[Any]` for tests.

    Returns the actual FastMCP dataclass (frozen, ``kw_only=True``) so
    type-checkers see the right shape; only wires the fields the
    middleware reads (``message`` carrying the tool-call ``arguments``
    and ``fastmcp_context``).
    """
    from fastmcp.server.middleware.middleware import MiddlewareContext

    return MiddlewareContext(
        message=_FakeCallToolMessage(arguments or {}),
        fastmcp_context=fastmcp_context,  # type: ignore[arg-type]
    )


async def _next_call_returns(
    _context: MiddlewareContext[Any],
) -> Any:
    """No-op stand-in for the FastMCP middleware chain continuation."""
    return {"status": "next-ok"}


class TestRequireMCPAuthContextState:
    @pytest.fixture(autouse=True)
    def _swap_audit_logger(self, monkeypatch: pytest.MonkeyPatch) -> _SpyAuditLogger:
        """Replace the module-level audit logger with an in-memory spy."""
        spy = _SpyAuditLogger()
        monkeypatch.setattr(mcp_auth, "_audit_logger", spy)
        return spy

    @pytest.mark.asyncio
    async def test_decorator_reads_user_id_from_context_state(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """Context state supplies user_id when kwargs is empty (production path).

        Production callers pass no ``user_id`` kwarg — the middleware
        injects it via Context state from the ``Authorization`` header.
        The decorator must honor the Context-state value, not deny.
        """
        fake_rbac = _FakeRBAC(allow=True)
        fake_ctx = _FakeContext(
            state={USER_ID_STATE_KEY: "alice-from-context"},
        )

        @require_mcp_auth(
            rbac_manager=fake_rbac,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(
            arg: str,
            ctx: _FakeContext | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", ctx=fake_ctx)

        assert result == {"status": "ok", "arg": "x"}
        # check_permission received alice from Context state — NOT a
        # spurious kwarg value.
        assert fake_rbac.calls == [("alice-from-context", "*", Permission.READ_PLAN_INDEX)]
        # Single allowed audit event with alice as the caller.
        assert len(_swap_audit_logger.events) == 1
        event = _swap_audit_logger.events[0]
        assert event.result == "allowed"
        assert event.caller_id == "alice-from-context"

    @pytest.mark.asyncio
    async def test_kwargs_works_when_context_state_absent(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """kwargs user_id is the fallback when Context state has no user_id (test path).

        Defense-in-depth: tests that pass ``user_id`` via kwargs without
        a Context continue to work. The decorator's AUTH_REQUIRED branch
        only fires when BOTH Context state and kwargs are empty.
        """
        fake_rbac = _FakeRBAC(allow=True)
        fake_ctx = _FakeContext(state={})  # No user_id in state

        @require_mcp_auth(
            rbac_manager=fake_rbac,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(
            arg: str,
            ctx: _FakeContext | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", ctx=fake_ctx, user_id="bob-from-kwargs")

        assert result == {"status": "ok", "arg": "x"}
        # check_permission received bob from kwargs (Context state was empty).
        assert fake_rbac.calls == [("bob-from-kwargs", "*", Permission.READ_PLAN_INDEX)]
        assert _swap_audit_logger.events[0].caller_id == "bob-from-kwargs"

    @pytest.mark.asyncio
    async def test_context_state_takes_precedence_over_kwargs(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """When both are present, Context state wins (per defense-in-depth ruling).

        ``@require_mcp_auth`` order: (1) Context state, (2) kwargs.
        A spoofed kwargs ``user_id`` cannot bypass the trusted
        middleware-injected value.
        """
        fake_rbac = _FakeRBAC(allow=True)
        fake_ctx = _FakeContext(
            state={USER_ID_STATE_KEY: "alice-from-context"},
        )

        @require_mcp_auth(
            rbac_manager=fake_rbac,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(
            arg: str,
            ctx: _FakeContext | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        # kwargs says "intruder"; Context state says "alice".
        # alice has it, intruder doesn't — assert alice was used.
        result = await sample_tool(
            arg="x", ctx=fake_ctx, user_id="intruder"
        )

        assert result == {"status": "ok", "arg": "x"}
        assert fake_rbac.calls == [("alice-from-context", "*", Permission.READ_PLAN_INDEX)]
        assert _swap_audit_logger.events[0].caller_id == "alice-from-context"

    @pytest.mark.asyncio
    async def test_auth_required_when_both_context_and_kwargs_empty(
        self, _swap_audit_logger: _SpyAuditLogger
    ) -> None:
        """No user_id anywhere -> AUTH_REQUIRED envelope + denied audit."""
        fake_rbac = _FakeRBAC(allow=True)
        fake_ctx = _FakeContext(state={})  # No user_id anywhere

        @require_mcp_auth(
            rbac_manager=fake_rbac,
            required_permission=Permission.READ_PLAN_INDEX,
        )
        async def sample_tool(
            arg: str,
            ctx: _FakeContext | None = None,
            user_id: str | None = None,
        ) -> dict[str, Any]:
            return {"status": "ok", "arg": arg}

        result = await sample_tool(arg="x", ctx=fake_ctx)

        assert result["status"] == "error"
        assert result["error_code"] == "AUTH_REQUIRED"
        # RBAC was never called (gate closed before the check).
        assert fake_rbac.calls == []
        # Denied audit emitted with reason explaining the gap.
        assert len(_swap_audit_logger.events) == 1
        assert _swap_audit_logger.events[0].result == "denied"


class TestAuthContextMiddleware:
    @pytest.mark.asyncio
    async def test_middleware_extracts_bearer_token_to_context_state(self) -> None:
        """Bearer token in arguments -> Context state under the namespaced key."""
        fake_ctx = _FakeContext()
        call_context = _build_call_context(
            arguments={
                "headers": {"Authorization": "Bearer some-jwt-shaped-token"},
            },
            fastmcp_context=fake_ctx,
        )

        middleware = AuthContextMiddleware()
        result = await middleware.on_call_tool(call_context, call_next=_next_call_returns)  # type: ignore[arg-type]

        # The middleware passes through to call_next unchanged.
        assert result == {"status": "next-ok"}
        # And it persisted the user_id under the namespaced key.
        assert fake_ctx.set_calls == [(USER_ID_STATE_KEY, "some-jwt-shaped-token")]
        assert await fake_ctx.get_state(USER_ID_STATE_KEY) == "some-jwt-shaped-token"

    @pytest.mark.asyncio
    async def test_middleware_persists_none_when_no_bearer(self) -> None:
        """No Bearer header -> Context state stores ``None`` (decorator's AUTH_REQUIRED fires)."""
        fake_ctx = _FakeContext()
        call_context = _build_call_context(
            arguments={"some_other_arg": "value"},
            fastmcp_context=fake_ctx,
        )

        middleware = AuthContextMiddleware()
        result = await middleware.on_call_tool(call_context, call_next=_next_call_returns)  # type: ignore[arg-type]

        assert result == {"status": "next-ok"}
        # State was written (with None), not skipped — the decorator
        # then reads it and fires AUTH_REQUIRED.
        assert fake_ctx.set_calls == [(USER_ID_STATE_KEY, None)]
        assert await fake_ctx.get_state(USER_ID_STATE_KEY) is None

    @pytest.mark.asyncio
    async def test_middleware_swallows_state_write_errors(self) -> None:
        """A failing ``set_state`` is best-effort — the tool still runs."""
        class _BrokenContext(_FakeContext):
            async def set_state(self, key: str, value: Any) -> None:
                raise RuntimeError("state store down")

        call_context = _build_call_context(
            arguments={
                "headers": {"Authorization": "Bearer xyz"},
            },
            fastmcp_context=_BrokenContext(),
        )

        middleware = AuthContextMiddleware()
        result = await middleware.on_call_tool(call_context, call_next=_next_call_returns)  # type: ignore[arg-type]

        # The middleware must not propagate state-write failures; the
        # tool path runs, and the kwargs fallback in require_mcp_auth
        # still has a chance.
        assert result == {"status": "next-ok"}

    @pytest.mark.asyncio
    async def test_middleware_runs_when_no_fastmcp_context(self) -> None:
        """When the message has no FastMCP Context attached, middleware still passes through."""
        call_context = _build_call_context(
            arguments={
                "headers": {"Authorization": "Bearer xyz"},
            },
            fastmcp_context=None,
        )

        middleware = AuthContextMiddleware()
        result = await middleware.on_call_tool(call_context, call_next=_next_call_returns)  # type: ignore[arg-type]

        assert result == {"status": "next-ok"}

    def test_user_id_state_key_is_namespaced(self) -> None:
        """The Context-state key is namespaced to avoid collisions with other middleware."""
        assert USER_ID_STATE_KEY == "mahavishnu.user_id"
        assert USER_ID_STATE_KEY.startswith("mahavishnu.")
