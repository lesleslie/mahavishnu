"""Minimal MCP MCP client and analytics adapter.

This module provides a small async MCP client for MCP's HTTP transport.
Mahavishnu uses it for the substrate (durable state + KV) and for
analytics.

**The substrate half** talks to mahavishnu's own MCP server and the
``mahavishnu_kv_*`` tools it registers. **The analytics half** has no
provider: the retired storage service's time-series API was the only
place the git-velocity, repository-health, fix-failure and
improvement-record series were ever written, nothing in the fleet writes
them now, and the matching reader (``analyze_changepoints``) was removed
from Akosha on 2026-09-26. :class:`NoAnalyticsWriterError` says so
explicitly rather than returning an empty series that would read as
"no data yet".

Phase 3 (REQ-004) of the common-mcp-client transport unification plan:
rewired to :class:`mcp_common.clients.common_mcp_client.CommonMCPClient`,
which manages its own session lifecycle over streamable-HTTP. The thin
wrapper preserves the prior public surface (``base_url``, ``timeout``,
``tools_url``, ``call_tool``, ``put``, ``aclose``) so callers don't change.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_common.clients.common_mcp_client import CommonMCPClient

logger = logging.getLogger(__name__)

# req: REQ-SUB-004
#: The substrate MCP server is mahavishnu's **own** MCP server: the KV and
#: durable-state tools it speaks (``mahavishnu_kv_get`` / ``_put`` /
#: ``_list`` / ``_delete``) are registered there by
#: :mod:`mahavishnu.mcp.tools.kv_tools`, backed by a process-local
#: thread-safe dict.
#:
#: The previous default pointed at a decommissioned service's port, whose
#: tool API (``put``, ``get``, ``query_time_series``) exists on no live
#: server in the fleet.
DEFAULT_SUBSTRATE_MCP_URL = "http://localhost:8680/mcp"

#: Identity the in-process substrate client presents on its self-call.
#:
#: The KV tools are gated by ``require_mcp_auth``, which denies any call
#: that carries no ``user_id`` (``error_code == "AUTH_REQUIRED"``). A
#: self-call has no inbound Authorization header, so it names this
#: principal explicitly; the RBAC manager registers it with the
#: ecosystem-state permissions during app bootstrap.
INTERNAL_SERVICE_USER_ID = "mahavishnu-internal"


class MCPClient:
    """Async MCP client for MCP's tool endpoint via CommonMCPClient."""

    def __init__(self, base_url: str, timeout: float = 30.0, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._mcp = CommonMCPClient(base_url=self.base_url, timeout=timeout, token=token)

    @property
    def tools_url(self) -> str:
        """Return the tool invocation endpoint (alias for ``base_url``).

        CommonMCPClient's streamable-HTTP transport serves both
        ``initialize`` and ``tools/call`` from the same URL, so this
        property now mirrors :attr:`base_url` (matches
        ``CommonMCPClient.tools_url``). Kept for API compatibility with
        callers that still read the property.
        """
        return self.base_url

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a MCP MCP tool over streamable-HTTP.

        Unwraps the FastMCP ``CallToolResult`` envelope so callers see
        the tool's actual return value (a dict, list, or scalar), not
        the SDK wrapper. The underlying ``CommonMCPClient`` returns
        ``CallToolResult`` (a Pydantic model with ``content``,
        ``structured_content``, ``is_error``). FastMCP tools annotated
        with ``-> dict[str, Any]`` populate ``structured_content``;
        string returns land in ``content[0].text``. PlanIndexStore and
        the workflow / approval ``recover_*`` helpers consume the
        unwrapped shape; the wire-envelope unwrap is the seam that
        lets both contracts coexist on the same MCP instance.
        """
        from mcp.types import TextContent  # type: ignore[import-not-found]

        result = await self._mcp.call_tool(name, arguments)
        if result.is_error:
            # Surface errors as a dict so callers can branch on
            # ``{"error": "..."}`` without needing to import
            # CallToolResult themselves. The original error text lives
            # in the first TextContent (FastMCP always uses text content
            # for errors, even when the tool is typed ``-> dict``).
            message = ""
            if result.content and isinstance(result.content[0], TextContent):
                message = result.content[0].text
            return {"error": message, "is_error": True}
        if result.structured_content is not None:
            return result.structured_content
        if result.content and isinstance(result.content[0], TextContent):
            import json

            try:
                return json.loads(result.content[0].text)
            except json.JSONDecodeError, TypeError:
                return result.content[0].text
        return None

    async def put(self, key: str, value: Any, ttl: int | None = None) -> Any:
        """Persist a key/value record via the self-hosted KV tool.

        ``mahavishnu_kv_put`` takes a **string** value, so structured
        payloads are JSON-encoded here and decoded on the read path by
        :func:`mahavishnu.core.state_backends.mcp._decode_payload`.
        """
        import json

        arguments: dict[str, Any] = {
            "key": key,
            "value": value if isinstance(value, str) else json.dumps(value, separators=(",", ":")),
            "user_id": INTERNAL_SERVICE_USER_ID,
        }
        if ttl is not None:
            arguments["ttl"] = ttl
        return await self.call_tool("mahavishnu_kv_put", arguments)

    async def aclose(self) -> None:
        """Close the underlying MCP session."""
        await self._mcp.aclose()


class NoAnalyticsWriterError(RuntimeError):
    """Raised when an analytics series has no writer anywhere in the fleet.

    Implements: REQ-SUB-005

    The retired storage service was the only writer and reader of the
    ``git_velocity``, ``repository_health``, ``fix-failures`` and
    ``improvement-records`` series, and of the aggregated pattern feed.
    Nothing writes them now — and Akosha's matching reader
    (``analyze_changepoints``) was removed on 2026-09-26 — so a query
    could only ever come back empty. Returning an empty list would read
    as "the series exists but has no data", which is a different (and
    wrong) statement. Callers surface this message to the operator.
    """


class MCPAdapter:
    """Analytics adapter for the metric series mahavishnu used to read.

    Retained as the seam the MCP tools call, but every query now raises
    :class:`NoAnalyticsWriterError`: the series have no writer in the
    fleet. When a component starts writing one of them again, this class
    is where the reader goes.
    """

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.client = MCPClient(base_url=base_url, timeout=timeout)

    async def query_time_series(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query time-series metrics.

        Raises:
            NoAnalyticsWriterError: no component in the fleet writes
                this metric series.
        """
        raise NoAnalyticsWriterError(
            f"No data source for the {metric_type!r} series: no component "
            "in the fleet writes it, and the retired storage service that "
            "used to is gone. The metric needs a writer before it can be "
            "read."
        )

    async def aggregate_patterns(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        """Query aggregated patterns.

        Raises:
            NoAnalyticsWriterError: no component in the fleet writes
                the aggregated pattern feed.
        """
        raise NoAnalyticsWriterError(
            "No data source for the aggregated pattern feed: no component "
            "in the fleet writes it, and the retired storage service that "
            "used to is gone. The feed needs a writer before it can be "
            "read."
        )


__all__ = ["MCPAdapter", "MCPClient"]
