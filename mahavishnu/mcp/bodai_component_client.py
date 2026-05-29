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
        self._get_session_id: Any = None  # Stores the session ID callback

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

        result = await self._session.call_tool(name, arguments)
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

        Note: Calling _transport_context.__aexit__() directly causes:
        "RuntimeError: Attempted to exit cancel scope in a different task"
        because the transport's task group is tied to the task that created it.
        The MCP library has a known issue where async generator cleanup runs
        in the wrong task during asyncio.run() shutdown.

        For fire-and-forget use cases (like FitnessAnalyzer), we simply drop
        references and let garbage collection handle cleanup. The RuntimeError
        during shutdown is cosmetic and doesn't affect functionality since
        all work is complete before the event loop exits.

        For long-lived sessions that need explicit cleanup, a different
        transport implementation would be needed.
        """
        # Drop all references to trigger garbage collection cleanup
        # The RuntimeError during asyncio.shutdown is unavoidable with current MCP library
        self._session = None
        self._transport_context = None
        self._get_session_id = None
