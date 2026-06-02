"""BodaiComponentMCPClient — MCP client for polling Bodai component endpoints.

Calls `query_local_traces` on each component's MCP HTTP endpoint using the official
MCP Python client library (streamable_http transport).

Session Management (FastMCP streamable-http):
    The streamable-http transport uses a session-based flow:
    1. POST with initialize request (no session ID) → server creates session
    2. Server returns session ID via mcp-session-id header in response
    3. Client sends 'initialized' notification to complete handshake
    4. Client opens GET SSE stream for server-to-client messages
    5. Subsequent POST requests include the session ID header

This client uses the official mcp.client.streamable_http_client() which handles
all session lifecycle correctly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)


class BodaiComponentMCPClient:
    """Async MCP client for calling tools on Bodai components.

    Uses the official MCP Python client's streamable_http transport which properly
    handles session establishment, initialized notification, and GET SSE stream
    management for server-to-client messaging.

    Parameters:
        base_url: Full MCP HTTP server URL (e.g. "http://localhost:8680/mcp")
        timeout: Request timeout in seconds
        token: Optional Bearer token for auth
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token
        self._session: ClientSession | None = None
        self._transport_context: Any = None
        self._get_session_id: Callable[[], str | None] | None = (
            None  # Stores the session ID callback
        )

    @property
    def tools_url(self) -> str:
        """Return the tool invocation endpoint."""
        return self.base_url

    @property
    def session_id(self) -> str | None:
        """Return the current MCP session ID, or None if not established."""
        if self._get_session_id is not None:
            return self._get_session_id()
        return None

    async def _ensure_session(self) -> None:
        """Establish MCP session using official client transport."""
        if self._session is not None:
            return

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        http_client: Any = None
        if self._token:
            import httpx

            http_client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self._token}"},
            )

        self._transport_context = streamable_http_client(
            self.base_url,
            http_client=http_client,
            terminate_on_close=True,
        )

        rs, ws, self._get_session_id = await self._transport_context.__aenter__()
        self._session = ClientSession(rs, ws)
        # Must enter session context BEFORE initialize - this starts the _receive_loop
        # task which is required for response routing (matching request IDs to responses)
        await self._session.__aenter__()
        await self._session.initialize()

        logger.debug("MCP session established: %s", self.session_id)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool over HTTP.

        Args:
            name: Tool name (e.g. "query_local_traces")
            arguments: Tool arguments dict

        Returns:
            Tool result from the MCP response
        """
        await self._ensure_session()

        result = await self._session.call_tool(name, arguments)  # type: ignore
        return result

    async def query_local_traces(
        self,
        task_class: str,
        time_range_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        """Query traces from a Bodai component's local OTel store.

        Args:
            task_class: Task classification to filter traces (e.g. "code_generation")
            time_range_minutes: How far back to query (default 60 minutes)

        Returns:
            List of trace summary dicts from the component's local store.
        """
        result = await self.call_tool(
            "query_local_traces",
            {
                "task_class": task_class,
                "time_range_minutes": time_range_minutes,
            },
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            items = result.get("traces") or result.get("items") or result.get("result")
            if isinstance(items, list):
                return items
        logger.debug("Unexpected query_local_traces response shape: %r", result)
        return []

    async def aclose(self) -> None:
        """Close the MCP session and transport.

        Explicitly exits the session and transport contexts, handling the known
        RuntimeError from MCP's async generator cleanup. The error occurs when
        async generator cleanup fires in a different task context than the one
        that created the transport (during asyncio.gather in _collect_traces).
        This is cosmetic — all work is complete before this is called.
        """
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except RuntimeError as exc:
                # MCP async generator cleanup runs in wrong task at shutdown.
                # All work is complete — this is cosmetic and safe to ignore.
                # Log at debug so we notice if the error message ever changes.
                if "cancel scope" in str(exc):
                    logger.debug("BodaiComponentMCPClient: suppressed cosmetic RuntimeError in session cleanup: %s", exc)
                else:
                    raise
            self._session = None

        if self._transport_context is not None:
            try:
                await self._transport_context.__aexit__(None, None, None)
            except RuntimeError as exc:
                if "cancel scope" in str(exc):
                    logger.debug("BodaiComponentMCPClient: suppressed cosmetic RuntimeError in transport cleanup: %s", exc)
                else:
                    raise
            self._transport_context = None

        self._get_session_id = None
