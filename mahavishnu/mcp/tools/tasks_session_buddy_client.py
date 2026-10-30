"""A narrow session-buddy MCP client for the task system's back-link.

Two components need to talk to session-buddy over MCP for the task
system, and neither needs the rest of its 200+ tools:

* ``tasks_handoff_to_workflow`` reads the task (``tasks_get``) and binds
  the workflow to it (``tasks_link_workflow``).
* ``task_orphan_sweeper`` reads the task and re-links it after a failed
  binding.

``BodaiComponentMCPClient`` already speaks streamable HTTP MCP against
any Bodai component. This module adapts it to the duck-type the task
tools expect, and unwraps FastMCP's ``CallToolResult`` envelope into
the plain dict the callers want.

The envelope matters: FastMCP returns a ``CallToolResult`` whose
payload lives under ``structuredContent["result"]`` (and, for older
clients, in ``content[0].text`` as a JSON string). The task tools
index the payload directly (``task.get("content", "")``), so an
unwrapped dict is required — handing them the raw envelope would make
every task look empty.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mahavishnu.mcp.bodai_component_client import BodaiComponentMCPClient

logger = logging.getLogger(__name__)


def _unwrap_tool_result(raw: Any) -> dict[str, Any]:
    """Return the payload dict from a FastMCP tool result.

    Handles the three shapes seen in the fleet: a plain dict, a
    ``CallToolResult`` with ``structuredContent``, and a
    ``CallToolResult`` with only ``content`` (JSON in the first text
    block). Anything unrecognised is returned as ``{}`` rather than
    raised, so a malformed response surfaces as an empty task — which
    the caller's validation rejects — instead of an opaque crash.
    """
    if isinstance(raw, dict):
        return raw

    structured = getattr(raw, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        if isinstance(inner, dict):
            return inner
        return structured

    content = getattr(raw, "content", None)
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("session-buddy tool result was not JSON")
                return {}
            if isinstance(parsed, dict):
                return parsed

    return {}


class SessionBuddyTaskClient:
    """The task system's narrow view of session-buddy over MCP.

    Args:
        base_url: The session-buddy MCP endpoint (e.g.
            ``http://localhost:8678/mcp``).
        timeout: Per-call timeout in seconds.
        token: Optional bearer token, forwarded when session-buddy's
            auth gate is on.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        token: str | None = None,
    ) -> None:
        self._client = BodaiComponentMCPClient(base_url, timeout=timeout, token=token)

    @property
    def base_url(self) -> str:
        """The session-buddy MCP endpoint this client talks to."""
        return self._client.base_url

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        """Fetch a task by id. Returns the task envelope as a dict.

        A missing or invisible task comes back as the server's
        ``not_found`` error envelope — the caller decides what that
        means. This method does not raise for that case.
        """
        return await self._call("tasks_get", {"task_id": task_id})

    async def tasks_link_workflow(self, task_id: str, workflow_id: str) -> dict[str, Any]:
        """Bind a workflow to a task through the typed link channel.

        This is the only channel that writes ``Task.workflow_id``. The
        generic ``tasks_update`` metadata bag cannot reach the field.

        Implements: REQ-008, REQ-001
        """
        return await self._call(
            "tasks_link_workflow",
            {"task_id": task_id, "workflow_id": workflow_id},
        )

    async def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = await self._client.call_tool(tool, arguments)
        return _unwrap_tool_result(raw)

    async def aclose(self) -> None:
        """Close the underlying MCP session.

        The client holds a persistent session; without this the
        connection outlives the server that opened it.
        """
        await self._client.aclose()


__all__ = [
    "SessionBuddyTaskClient",
    "_unwrap_tool_result",
    "get_session_buddy_task_client",
]


#: The process-wide client. ``SessionBuddyTaskClient`` holds a persistent
#: MCP session, so one per process is the right cardinality — creating
#: one per call would open a connection per call.
_TASK_CLIENT: SessionBuddyTaskClient | None = None


def get_session_buddy_task_client() -> SessionBuddyTaskClient:
    """Return the process-wide session-buddy task client.

    The endpoint comes from ``pools.session_buddy_url`` in
    ``MahavishnuSettings`` — the same setting the delegated pools use, so
    the task system and the pool router cannot drift onto different
    session-buddy instances.
    """
    global _TASK_CLIENT
    if _TASK_CLIENT is None:
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        _TASK_CLIENT = SessionBuddyTaskClient(settings.pools.session_buddy_url)
    return _TASK_CLIENT
