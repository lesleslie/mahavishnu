"""webhook_replay MCP tool — read-back of stored WebhookIngress records.

Wraps :func:`mahavishnu.webhooks.replay.webhook_replay` with the
FastMCP ``@mcp.tool()`` + ``@require_mcp_auth()`` decorator contract so
callers can fetch a previously-ingested durable webhook by ``webhook_id``
via the MCP tool surface. The underlying leaf function still owns its
own RBAC gate (JWT-shape token check) and path-traversal guard; the
MCP wrapper only adds the surface-level ``READ_WEBHOOK`` permission
check that the FastMCP middleware enforces.

Mirrors the sibling :mod:`mahavishnu.mcp.tools.workflow_tools` shape:
the module-level leaf is ``webhook_replay`` (sync); the FastMCP-registered
tool is an inline ``async`` wrapper so FastMCP's coroutine contract holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dhara.schema import to_dict
from oneiric.core.logging import get_logger

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.webhooks.replay import webhook_replay

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)


def register_webhook_tools(mcp: FastMCP) -> None:
    """Register webhook MCP tools with the FastMCP server.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    The inner tool function delegates to the module-level
    :func:`webhook_replay` so the implementation stays testable in
    isolation without spinning up a FastMCP server.
    """

    @mcp.tool()
    @require_mcp_auth(required_permission=Permission.READ_WEBHOOK)
    async def webhook_replay_tool(
        webhook_id: str,
        user_id: str | None = None,
        token: str | None = None,
    ) -> dict[str, Any] | None:
        """Read back a stored ``WebhookIngress`` for ``webhook_id``.

        Returns the serialized ``WebhookIngress`` as a dict via
        ``record.to_dict()`` (mirrors the
        ``mahavishnu.core.adapter_persistence`` pattern), or ``None``
        when no record exists, the substrate is unbound, the
        ``webhook_id`` fails the path-traversal guard, or ``token``
        is missing or not JWT-shaped.

        Auth: requires ``user_id`` with ``READ_WEBHOOK`` permission
        (mirror of the ``@require_mcp_auth`` contract). Without
        ``user_id`` the tool returns
        ``{"status": "error", "error_code": "AUTH_REQUIRED", ...}``
        before any substrate access. The ``token`` parameter is
        passed through to :func:`webhook_replay` which performs a
        JWT-shape presence gate as the leaf-level RBAC contract.
        """
        record = webhook_replay(webhook_id, token=token)
        if record is None:
            return None
        # msgspec.Struct → dict via the standard ``to_dict`` helper,
        # matching the convention used at
        # ``mahavishnu/core/adapter_persistence.py``.
        return to_dict(record)
