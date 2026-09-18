"""Auth-context middleware — extracts Bearer token, stores user_id in Context state.

Production callers (HTTP / STDIO / SSE) authenticate via the request's
``Authorization: Bearer <token>`` header. This middleware reads the
header, validates the token shape via
:func:`mahavishnu.mcp.auth.extract_auth_from_request`, and stores the
extracted ``user_id`` in FastMCP Context state under the namespaced key
``"mahavishnu.user_id"``.

The :func:`mahavishnu.mcp.auth.require_mcp_auth` decorator reads this
state at gate time (preferred over kwargs, kwargs is the fallback for
test paths). On extraction failure (no Bearer header, malformed token),
state is set to ``None`` and the decorator's AUTH_REQUIRED branch fires
when both Context state and kwargs are empty.

FastMCP 4.0.3 API (resolved through ``mcp_common.fastmcp`` — Plan 7
Phase 2 centralized FastMCP re-export surface):

* :class:`Middleware` lives at ``mcp_common.fastmcp.Middleware``
  (re-export of ``fastmcp.server.middleware.middleware.Middleware``).
* Override :meth:`Middleware.on_call_tool`; ``call_next`` is a coroutine
  taking the same ``MiddlewareContext`` object.
* The FastMCP ``Context`` (with ``set_state`` / ``get_state``) is
  exposed at ``context.fastmcp_context``, not ``context.context``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

# Centralized FastMCP re-export — Plan 7 Phase 2 contract. Direct upstream
# ``fastmcp.server.middleware.middleware`` imports break
# ``tests/unit/test_mcp_common_fastmcp_imports.py``; the ``mcp_common``
# re-export lets us swap the pinned FastMCP version in one place.
from mcp_common.fastmcp import Middleware

from mahavishnu.mcp.auth import extract_auth_from_request

if TYPE_CHECKING:
    # TYPE_CHECKING-only imports stay on the upstream path because they
    # never run at import time (no runtime attribute lookup happens for
    # them) and ``mcp_common.fastmcp`` only re-exports the runtime
    # symbols. The forward reference via ``"`` quotes still resolves
    # through :mod:`mcp_common.fastmcp` at type-check time.
    from fastmcp.server.context import Context
    from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext

logger = logging.getLogger(__name__)

USER_ID_STATE_KEY = "mahavishnu.user_id"
"""Namespaced Context-state key holding the extracted user_id (or None)."""


class AuthContextMiddleware(Middleware):
    """FastMCP middleware that extracts Bearer token -> user_id -> Context state.

    Runs in the ``on_call_tool`` hook (per FastMCP 4.0.3 docs) — fires
    AFTER tool dispatch but BEFORE the tool function executes. Sets
    the Context state under the namespaced key so the auth decorator
    picks it up.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        request = getattr(context.message, "arguments", None) or {}
        # ``arguments`` is the tool-call argument dict — what the caller
        # sent as the tool's input. Production callers may embed the
        # ``Authorization`` header here in some transports; falling back
        # to a top-level ``request`` attribute keeps us tolerant of any
        # future wire shape FastMCP might introduce.
        request_dict: dict[str, Any] = dict(request) if isinstance(request, dict) else {}
        if "request" in request_dict and isinstance(request_dict["request"], dict):
            request_dict = request_dict["request"]

        user_id: str | None = None
        try:
            extracted = await extract_auth_from_request(request_dict)
            user_id = extracted["user_id"]
        except Exception:  # noqa: BLE001 - auth failures are non-fatal here
            user_id = None

        fastmcp_ctx: Context | None = getattr(context, "fastmcp_context", None)
        if fastmcp_ctx is not None:
            try:
                await fastmcp_ctx.set_state(USER_ID_STATE_KEY, user_id)
            except Exception:
                logger.debug(
                    "AuthContextMiddleware: failed to persist user_id to Context state",
                    exc_info=True,
                )

        return await call_next(context)
