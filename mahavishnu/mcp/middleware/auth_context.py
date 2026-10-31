"""Auth-context middleware — resolves the caller identity into Context state.

Two identity sources, in priority order:

1. **The internal self-call credential.** The substrate client runs in
   this same process and presents a per-process token in the
   ``Authorization`` header. When that token verifies, the request
   carries the internal service principal, and the middleware records
   the verification in Context state under
   ``"mahavishnu.internal_principal"``.
2. **The tool-call arguments.** Otherwise the middleware falls back to
   :func:`mahavishnu.mcp.auth.extract_auth_from_request`, which reads the
   ``user_id`` / ``Authorization`` / ``api_key`` field the caller sent as
   the tool's input. This is a *claim*, not a proof — it is why the
   internal principal additionally requires source 1.

The resolved ``user_id`` is stored in FastMCP Context state under the
namespaced key ``"mahavishnu.user_id"``. The
:func:`mahavishnu.mcp.auth.require_mcp_auth` decorator reads this state
at gate time (preferred over kwargs, kwargs is the fallback for test
paths). On extraction failure (no identity in the arguments), state is
set to ``None`` and the decorator's AUTH_REQUIRED branch fires when both
Context state and kwargs are empty.

FastMCP 4.0.3 API (resolved through ``mcp_common.fastmcp`` — Plan 7
Phase 2 centralized FastMCP re-export surface):

* :class:`Middleware` lives at ``mcp_common.fastmcp.Middleware``
  (re-export of ``fastmcp.server.middleware.middleware.Middleware``).
* Override :meth:`Middleware.on_call_tool`; ``call_next`` is a coroutine
  taking the same ``MiddlewareContext`` object.
* The FastMCP ``Context`` (with ``set_state`` / ``get_state``) is
  exposed at ``context.fastmcp_context``, not ``context.context``.
* The active HTTP request (and therefore its headers) comes from
  ``fastmcp.server.dependencies.get_http_request``.
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
from mahavishnu.mcp.internal_auth import (
    INTERNAL_PRINCIPAL_STATE_KEY,
    INTERNAL_SERVICE_USER_ID,
    bearer_token_from_headers,
    request_headers,
    verify_internal_token,
)

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
    """FastMCP middleware that resolves the caller identity into Context state.

    Runs in the ``on_call_tool`` hook (per FastMCP 4.0.3 docs) — fires
    AFTER tool dispatch but BEFORE the tool function executes. Sets
    the Context state under the namespaced key so the auth decorator
    picks it up.

    The internal self-call credential is checked first; only a request
    that presents it is recorded as carrying the internal principal.
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
        internal_verified = False

        # Internal self-call credential check — runs FIRST, and outranks
        # the argument-derived identity below.
        #
        # The substrate client lives in this same process and presents a
        # per-process token in the ``Authorization`` header. Verifying it
        # here is what makes the internal principal unforgeable: the
        # argument-derived path treats ``user_id`` as the caller's claim,
        # so a caller that supplies the principal's *name* reaches the
        # branch below but never this one.
        token = bearer_token_from_headers(request_headers())
        if verify_internal_token(token):
            user_id = INTERNAL_SERVICE_USER_ID
            internal_verified = True
        else:
            try:
                extracted = await extract_auth_from_request(request_dict)
                user_id = extracted["user_id"]
            except Exception:  # MCP tool error handler — broad catch is the documented contract  # noqa: BLE001, RUF100
                user_id = None

        fastmcp_ctx: Context | None = getattr(context, "fastmcp_context", None)
        if fastmcp_ctx is not None:
            try:
                await fastmcp_ctx.set_state(USER_ID_STATE_KEY, user_id)
                await fastmcp_ctx.set_state(INTERNAL_PRINCIPAL_STATE_KEY, internal_verified)
            except Exception:  # MCP tool error handler — broad catch is the documented contract
                logger.debug(
                    "AuthContextMiddleware: failed to persist user_id to Context state",
                    exc_info=True,
                )

        return await call_next(context)
