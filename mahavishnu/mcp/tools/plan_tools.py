"""``mcp__mahavishnu__plan_*`` tools — the MCP surface over the plan index.

REQ-PLAN-010: all five tools are gated by
``@require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)``.
The decorator is applied here; ``tests/unit/mcp/test_plan_tools_auth_gate.py``
enforces that it stays applied.

The store is injected via ``store_provider`` so tests can supply a
``FakeDhara``-backed store. Production wires a real Dhara-backed store at
``MahavishnuApp`` startup (Task 12); there is deliberately no production
default here.

Each tool accepts a trailing ``user_id`` parameter because
:func:`mahavishnu.mcp.auth.require_mcp_auth` reads ``user_id`` from the call
kwargs and then forwards **all** kwargs to the wrapped function. Without the
parameter an authenticated call would raise ``TypeError``. This mirrors the
established shape in :mod:`mahavishnu.mcp.tools.webhook_tools`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from oneiric.core.logging import get_logger

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth
from mahavishnu.plan_index.errors import PlanNotFoundError
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp_common.fastmcp import FastMCP

    #: Zero-arg factory returning the store a tool invocation should read from.
    StoreProvider = Callable[[], PlanIndexStore]

__all__ = ["plan_tools_default_store_provider", "register_plan_tools"]

logger = get_logger(__name__)


def plan_tools_default_store_provider() -> PlanIndexStore:
    """Dev/test store provider backed by the in-memory :class:`FakeDhara`.

    Production callers MUST inject a real Dhara-backed provider instead;
    this exists so tests (and local smoke runs) can register the tools
    without standing up Dhara.
    """
    return PlanIndexStore(FakeDhara())


def register_plan_tools(mcp: FastMCP, *, store_provider: StoreProvider) -> None:
    """Register the five ``plan_*`` tools with the FastMCP server.

    ``store_provider`` is keyword-only and required: ``MahavishnuApp`` injects
    the real Dhara-backed store at startup. Tests pass
    :func:`plan_tools_default_store_provider`.

    Structural note: FastMCP's ``@mcp.tool()`` decorator introspects each
    function's name and signature to build the MCP tool schema, so the tool
    bodies must be defined inline. The per-tool logic delegates straight to
    :class:`~mahavishnu.plan_index.store.PlanIndexStore`, which stays testable
    in isolation.
    """
    provider = store_provider

    @mcp.tool(name="plan_list")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_list(
        status: str | None = None,
        topic: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """List plans, optionally filtered by status, topic, or date range.

        Filters are mutually exclusive and evaluated in priority order:
        ``status`` > ``topic`` > ``date_from``/``date_to`` > unfiltered.
        """
        store = provider()
        if status:
            records = await store.list_by_status(status, limit=limit)
        elif topic:
            records = await store.list_by_topic(topic, limit=limit)
        elif date_from and date_to:
            records = await store.list_by_date_range(date_from, date_to)
        else:
            records = await store.list_all(limit=limit)
        return {
            "plans": records,
            "total": len(records),
            "status": "ok",
        }

    @mcp.tool(name="plan_show")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_show(plan_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Show one plan by ``plan_id``. Raises ``PlanNotFoundError`` if absent."""
        store = provider()
        record = await store.get(plan_id)
        if record is None:
            raise PlanNotFoundError(plan_id)
        return cast("dict[str, Any]", record)

    @mcp.tool(name="plan_search")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_search(
        query: str,
        limit: int = 20,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lexical search over plan titles and topics. Empty query returns ``[]``."""
        if not query:
            return []
        store = provider()
        return cast("list[dict[str, Any]]", await store.search(query, limit=limit))

    @mcp.tool(name="plan_vitals")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_vitals(user_id: str | None = None) -> dict[str, Any]:
        """Aggregate counters, per-status/role/topic breakdowns, and tripwire state."""
        store = provider()
        return cast("dict[str, Any]", await store.vitals())

    @mcp.tool(name="plan_rebuild_status")
    @require_mcp_auth(required_permission=Permission.READ_PLAN_INDEX)
    async def plan_rebuild_status(user_id: str | None = None) -> dict[str, Any]:
        """Rebuild cycle counters, staleness flag, and (redacted) lock holder."""
        store = provider()
        return cast("dict[str, Any]", await store.rebuild_status())

    logger.debug("plan_index: registered 5 plan_* MCP tools")
