"""MCP tools for the Mahavishnu-side EventBridge publisher.

Exposes a single ``publish_to_eventbridge`` MCP tool that wraps the
underlying ``publish_workflow_*`` async functions into a
sync-callable interface for Claude Code and other MCP clients.

Mirrors the dispatch_to_pool pattern from
``mahavishnu/mcp/tools/pool_tools.py``: optional ``async_callback`` flag
returns a workflow_id immediately and runs the publish in the background.

The tool is gated by an explicit ``enabled`` parameter -- calling
``register_eventbridge_tools(mcp_app, enabled=True)`` is required to
expose it. The MCP server wiring must pass
``enabled=cfg.eventbridge.enabled`` from the loaded MahavishnuSettings.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.events.mahavishnu_publisher import (
    publish_workflow_completed,
    publish_workflow_failed,
    publish_workflow_started,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


async def _dispatch_topic(topic: str, payload: dict[str, Any]) -> None:
    """Route a (topic, payload) pair to the matching ``publish_*`` function."""
    if topic == "workflow.started":
        await publish_workflow_started(
            workflow_id=payload["workflow_id"],
            metadata=payload.get("metadata", {}),
        )
    elif topic == "workflow.completed":
        await publish_workflow_completed(
            workflow_id=payload["workflow_id"],
            result=payload.get("result", {}),
        )
    elif topic == "workflow.failed":
        await publish_workflow_failed(
            workflow_id=payload["workflow_id"],
            error=payload.get("error", ""),
        )
    else:
        logger.warning("mahavishnu.eventbridge_tools: unknown topic=%s; ignoring", topic)


def register_eventbridge_tools(
    mcp_app: FastMCP,
    enabled: bool = False,
    enabled_fn: Callable[[], bool] | None = None,
) -> None:
    """Register the EventBridge publisher MCP tool.

    Args:
        mcp_app: FastMCP application instance.
        enabled: Legacy master toggle. When False (default), the tool
            returns ``{"status": "disabled"}`` for every call.
        enabled_fn: Callable returning the current ``enabled`` state,
            invoked on EVERY tool call. When provided, ``enabled`` is
            ignored. Operators can flip the toggle without restarting
            the MCP server by changing the source the callable reads.
    """
    if enabled_fn is None:

        def _resolved_enabled_fn() -> bool:
            return enabled
    else:
        _resolved_enabled_fn = enabled_fn

    @mcp_app.tool()
    async def publish_to_eventbridge(
        topic: str,
        payload: dict[str, Any],
        async_callback: bool = False,
    ) -> dict[str, Any]:
        """Publish a workflow event to the Mahavishnu EventBridge stream."""
        if not _resolved_enabled_fn():
            return {"status": "disabled"}

        # The publisher is set on the WebSocketServer via set_event_publisher()
        # at app startup. We don't have direct access to it here, but the
        # publish_workflow_* functions accept an injected publisher. The
        # ``publish_*`` module-level functions in mahavishnu_publisher
        # accept a publisher argument; the WebSocketServer's
        # get_event_publisher() returns the current one.
        publisher = _try_get_publisher()
        if publisher is None:
            return {
                "status": "no_publisher",
                "warning": (
                    "eventbridge enabled but publisher not wired; no envelope will be emitted"
                ),
            }

        async def _dispatch_with_publisher() -> None:
            if topic == "workflow.started":
                await publish_workflow_started(
                    workflow_id=payload["workflow_id"],
                    metadata=payload.get("metadata", {}),
                    publisher=publisher,
                )
            elif topic == "workflow.completed":
                await publish_workflow_completed(
                    workflow_id=payload["workflow_id"],
                    result=payload.get("result", {}),
                    publisher=publisher,
                )
            elif topic == "workflow.failed":
                await publish_workflow_failed(
                    workflow_id=payload["workflow_id"],
                    error=payload.get("error", ""),
                    publisher=publisher,
                )
            else:
                logger.warning("mahavishnu.eventbridge_tools: unknown topic=%s; ignoring", topic)

        if async_callback:
            workflow_id = f"pub_{uuid.uuid4().hex[:12]}"
            _dispatch_task = asyncio.create_task(_dispatch_with_publisher())  # noqa: RUF006
            return {"workflow_id": workflow_id, "status": "queued"}

        await _dispatch_with_publisher()
        return {"status": "published"}


def _has_factories() -> bool:
    """Check whether the factories module is importable (avoid hard dep at import time)."""
    try:
        import mahavishnu.factories  # noqa: F401

        return True
    except ImportError:
        return False


def _try_get_publisher() -> Any | None:
    """Best-effort lookup of the wired publisher.

    Returns the WebSocketServer's ``_event_publisher`` if available.
    Returns None when:
    - the factories module is not importable
    - get_websocket_server() fails or returns None
    - the server has no publisher wired

    Failure modes are caught and treated as "no publisher" -- callers
    see a clean no_publisher status instead of an exception.
    """
    if not _has_factories():
        return None
    try:
        from mahavishnu.factories import get_websocket_server

        server = get_websocket_server()
    except Exception:  # noqa: BLE001 -- best-effort lookup
        return None
    if server is None:
        return None
    return getattr(server, "_event_publisher", None)


__all__ = ["register_eventbridge_tools"]
