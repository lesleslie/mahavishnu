"""Durable ecosystem state MCP tools — Phase 3 of the MCP retirement.

These five tools port ``mcp_upsert_service`` / ``mcp_get_service`` /
``mcp_list_services`` / ``mcp_record_event`` / ``mcp_list_events``
from MCP's MCP surface onto Mahavishnu's MCP server so sibling Bodai
components can resolve services and read events without depending on
MCP's MCP. See ``docs/plans/2026-09-16-mcp-mcp-retirement-plan.md``.

Mirrors the sibling :mod:`mahavishnu.mcp.tools.webhook_tools` shape:
each tool is an inline ``async`` function so FastMCP's ``@mcp.tool()``
decorator can introspect the function name + signature for the tool
schema. The leaf logic lives in
:mod:`mahavishnu.core.ecosystem_state.AsyncEcosystemStateStore` and
is decoupled from the FastMCP layer for testability.

Auth: each tool is gated by :func:`require_mcp_auth`. The READ tools
(``mahavishnu_get_service`` / ``mahavishnu_list_services`` /
``mahavishnu_list_events``) require ``Permission.READ_ECOSYSTEM_STATE``;
the WRITE tools (``mahavishnu_upsert_service`` /
``mahavishnu_record_event``) require
``Permission.WRITE_ECOSYSTEM_STATE``. The admin role inherits all
permissions via ``list(Permission)`` in ``RBACManager._init_default_roles``.

Substrate contract: the leaf store uses
:func:`mahavishnu.core._mcp_substrate_compat.mcp_calltime` so the
host's mcp binding is resolved lazily. When unbound, the writer logs
a structured ``ecosystem_state_*_skipped`` warning and returns the
validated record anyway; the readers return ``None`` / ``[]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

from mahavishnu.core.ecosystem_state import AsyncEcosystemStateStore
from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)


def register_ecosystem_state_tools(
    mcp: FastMCP,
    rbac_manager: Any | None = None,
) -> None:
    """Register the 5 ecosystem-state MCP tools with the FastMCP server.

    ``rbac_manager`` defaults to ``None``; production wiring at
    :func:`mahavishnu.mcp.bootstrap._register_ecosystem_state_tools`
    injects the real :class:`~mahavishnu.core.permissions.RBACManager`.
    Tests may omit it; the decorator denies with
    ``error_code == "AUTH_NOT_CONFIGURED"`` (fail-closed).

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be inline so it can introspect the
    function name + signature for the MCP tool schema. The five tools
    are intentionally inline; the per-tool complexity is the cost of
    the FastMCP API contract, not bad code.

    Each inline tool delegates to a module-level coroutine on
    :class:`AsyncEcosystemStateStore` so the implementation stays
    testable in isolation without spinning up a FastMCP server.
    """

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.WRITE_ECOSYSTEM_STATE
    )
    async def mahavishnu_upsert_service(
        service_id: str,
        service_type: str,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "unknown",
        lease_expires_at: str | None = None,
        heartbeat_at: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a durable ecosystem service record.

        Args:
            service_id: Stable primary key for the service.
            service_type: Logical type (e.g. ``"mcp"``, ``"worker_pool"``).
            capabilities: Free-form capability tags. Defaults to ``[]``.
            metadata: Free-form caller metadata. Defaults to ``{}``.
            status: Lifecycle status; free-form string. Defaults to ``"unknown"``.
            lease_expires_at: Optional ISO-8601 lease expiry.
            heartbeat_at: Optional ISO-8601 last-heartbeat timestamp.

        Returns:
            The serialized service record as a dict. Mirrors the MCP
            ``mcp_upsert_service`` response envelope (no extra
            wrapper) so call-site code can be ported verbatim.

        Auth: requires ``user_id`` with ``WRITE_ECOSYSTEM_STATE`` permission.
        """
        store = AsyncEcosystemStateStore()
        return await store.upsert_service_async(
            service_id=service_id,
            service_type=service_type,
            capabilities=capabilities,
            metadata=metadata,
            status=status,
            lease_expires_at=lease_expires_at,
            heartbeat_at=heartbeat_at,
        )

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_get_service(
        service_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a durable ecosystem service record by ``service_id``.

        Returns ``{"ok": True, "service": None}`` when no record exists
        OR the substrate is unbound. The ``service`` field is the
        serialized :class:`EcosystemService` payload or ``None``.

        Auth: requires ``user_id`` with ``READ_ECOSYSTEM_STATE`` permission.
        """
        store = AsyncEcosystemStateStore()
        service = await store.get_service_async(service_id)
        return {"ok": True, "service": service}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_list_services(
        service_type: str | None = None,
        capability: str | None = None,
        status: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """List durable ecosystem service records with optional filters.

        Filters match the MCP contract: exact ``service_type`` /
        ``status`` and single-tag ``capability`` membership check.

        Returns ``{"ok": True, "count": <n>, "services": [...]}``. An
        empty list (or unbound substrate) yields ``count == 0``.

        Auth: requires ``user_id`` with ``READ_ECOSYSTEM_STATE`` permission.
        """
        store = AsyncEcosystemStateStore()
        services = await store.list_services_async(
            service_type=service_type,
            capability=capability,
            status=status,
        )
        return {"ok": True, "count": len(services), "services": services}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.WRITE_ECOSYSTEM_STATE
    )
    async def mahavishnu_record_event(
        event_type: str,
        source_service: str,
        payload: dict[str, Any] | None = None,
        related_service: str | None = None,
        timestamp: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a durable ecosystem event.

        Args:
            event_type: Logical event type.
            source_service: Identifier of the service producing the event.
            payload: Free-form caller payload. Defaults to ``{}``.
            related_service: Optional related service identifier.
            timestamp: Optional ISO-8601 timestamp; defaults to ``now`` UTC.

        Returns:
            The serialized event record (includes the derived
            ``event_id`` and persisted ``timestamp``).

        Auth: requires ``user_id`` with ``WRITE_ECOSYSTEM_STATE`` permission.
        """
        store = AsyncEcosystemStateStore()
        return await store.record_event_async(
            event_type=event_type,
            source_service=source_service,
            payload=payload,
            related_service=related_service,
            timestamp=timestamp,
        )

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_list_events(
        event_type: str | None = None,
        source_service: str | None = None,
        related_service: str | None = None,
        limit: int | None = 100,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """List durable ecosystem events with optional filters.

        Returns up to ``limit`` most-recent matching events (default
        100). Filters match the MCP contract exactly.

        Auth: requires ``user_id`` with ``READ_ECOSYSTEM_STATE`` permission.
        """
        store = AsyncEcosystemStateStore()
        events = await store.list_events_async(
            event_type=event_type,
            source_service=source_service,
            related_service=related_service,
            limit=limit,
        )
        return {"ok": True, "count": len(events), "events": events}


__all__ = ["register_ecosystem_state_tools"]
