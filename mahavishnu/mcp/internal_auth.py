"""Per-process credential for mahavishnu's internal MCP self-call.

Why this module exists
----------------------
The substrate clients run in the *same* process as the MCP server they
call, and the tools they reach (``mahavishnu_kv_get`` / ``_put`` /
``_list`` / ``_delete``) are gated by ``@require_mcp_auth``.

That gate resolves the caller's identity from the tool-call
**arguments** — the ``user_id`` field is caller-controlled. An identity
expressed as a plain *name* is therefore forgeable: any client that can
reach the server can claim any registered user id, including a
privileged service principal.

So the internal path must present a **credential**, not a name. This
module issues a random per-process token. The client sends it in the
``Authorization`` header; the auth middleware verifies it with a
constant-time comparison and only then records that the request carries
the internal principal. A caller that supplies the principal's *name*
without the credential is denied by the gate.

The token never leaves the process except as a header to the server's own
listener, and it is regenerated on every process start, so a token
captured from a previous run is worthless.

See ``docs/plans/2026-10-31-mcp-substrate-rewire.md`` §4.1 for the
defect this replaces.
"""

from __future__ import annotations

import hmac
import secrets
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = get_logger(__name__)

# req: REQ-SUB-006
INTERNAL_SERVICE_USER_ID = "mahavishnu-internal"
"""Identity the in-process substrate presents on its self-call.

Registered by :mod:`mahavishnu.core.bootstrap` with the least-privilege
``internal_service`` role — exactly ``READ_ECOSYSTEM_STATE`` and
``WRITE_ECOSYSTEM_STATE``.

It is **not** claimable by name. The name alone is not a credential:
:func:`verify_internal_token` must succeed for the gate to grant this
principal, and only the auth middleware can record that verification.
"""

INTERNAL_PRINCIPAL_STATE_KEY = "mahavishnu.internal_principal"
"""Context-state key the auth middleware sets when it verified the token.

``True`` means "this request presented the process credential". The gate
reads it to decide whether the internal principal may be used.
"""

_TOKEN: str | None = None


def get_internal_token() -> str:
    """Return this process's internal self-call credential.

    Generated once per process with :func:`secrets.token_urlsafe` and
    cached in module state, so every in-process caller presents the same
    value without a config file or a secret manager. Regenerated on every
    process start.
    """
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = secrets.token_urlsafe(32)
        logger.debug("Generated a new internal MCP self-call credential")
    return _TOKEN


def verify_internal_token(provided: str | None) -> bool:
    """Return ``True`` when ``provided`` matches this process's credential.

    Uses :func:`hmac.compare_digest` so the comparison does not leak the
    token's bytes through timing.
    """
    if not provided:
        return False
    return hmac.compare_digest(provided, get_internal_token())


def bearer_token_from_headers(headers: Mapping[str, str] | None) -> str | None:
    """Extract the bearer token from a request-headers mapping.

    Starlette's ``request.headers`` is case-insensitive, but the
    ``Mapping`` protocol is not, so both spellings are checked.
    """
    if not headers:
        return None
    raw = headers.get("authorization") or headers.get("Authorization")
    if raw and raw.startswith("Bearer "):
        return raw[len("Bearer ") :]
    return None


def is_loopback_url(url: str) -> bool:
    """Return ``True`` when ``url`` addresses this machine.

    The internal credential is a bearer secret. It must never be sent to
    a third-party endpoint, so the check is on the *host*: a loopback
    name or address keeps the credential on this host, and anything else
    would carry it off-machine.

    Used by :class:`mahavishnu.core.mcp_adapter.MCPClient` to refuse
    attaching the credential to a non-loopback URL.
    """
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    return host.lower() in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def request_headers() -> Any:
    """Return the current HTTP request headers, or ``None`` if unavailable.

    ``fastmcp.server.dependencies.get_http_request`` resolves the active
    Starlette request for the HTTP transport. It raises when there is no
    HTTP request in scope (STDIO transport, unit tests), which is why
    this helper swallows the error and returns ``None``.
    """
    try:
        from fastmcp.server.dependencies import get_http_request

        return get_http_request().headers
    # MCP tool error handler — no HTTP request in scope
    except Exception:  # noqa: BLE001, RUF100
        return None


async def internal_principal_verified() -> bool:
    """Return ``True`` when the current request presented the credential.

    Reads the Context state the auth middleware recorded after verifying
    the token.

    It uses ``fastmcp.server.dependencies.get_context`` rather than a
    ``ctx`` keyword argument because no tool declares a ``ctx``
    parameter — FastMCP injects one only when the signature asks for it.
    The contextvar is the channel that reaches the middleware's state
    from inside the auth gate.
    """
    try:
        from fastmcp.server.dependencies import get_context

        ctx = get_context()
    # MCP tool error handler — no active context
    except Exception:  # noqa: BLE001, RUF100
        return False
    try:
        return bool(await ctx.get_state(INTERNAL_PRINCIPAL_STATE_KEY))
    # MCP tool error handler — state read failed
    except Exception:  # noqa: BLE001, RUF100
        return False
