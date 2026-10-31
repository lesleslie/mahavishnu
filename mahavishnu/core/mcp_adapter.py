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

from mahavishnu.mcp.internal_auth import (
    INTERNAL_SERVICE_USER_ID,
    get_internal_token,
    is_loopback_url,
)

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
#: The KV tools are gated by ``require_mcp_auth``. A self-call has no
#: inbound Authorization header, so it presents this principal — but the
#: name alone is not sufficient: the client must also send the
#: per-process credential (see ``internal=True`` on :class:`MCPClient`),
#: and the auth middleware verifies it before the principal is granted.
#: The RBAC manager registers the principal with the least-privilege
#: ``internal_service`` role during app bootstrap.


class MCPClient:
    """Async MCP client for MCP's tool endpoint via CommonMCPClient."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        token: str | None = None,
        internal: bool = False,
    ) -> None:
        """Build a client for ``base_url``.

        Args:
            base_url: The MCP endpoint to call.
            timeout: Per-request timeout in seconds.
            token: Explicit bearer token. Use this for third-party servers.
            internal: When True, present this process's internal self-call
                credential instead of an anonymous request. Only set it for
                calls back into **mahavishnu's own** MCP server — the
                credential is a bearer secret and must never be sent to a
                third-party endpoint.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if internal and token is None:
            if is_loopback_url(self.base_url):
                token = get_internal_token()
            else:
                # The credential is a bearer secret: it must never travel
                # off this host. A non-loopback target means the caller
                # pointed the substrate somewhere else, so the call goes
                # out unauthenticated rather than leaking the secret.
                logger.warning(
                    "Refusing to send the internal self-call credential to a non-loopback URL: %s",
                    self.base_url,
                )
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

    async def kv_get(self, key: str) -> str | None:
        """Read a KV record as the raw string that was stored.

        The KV tools are string-shaped: ``mahavishnu_kv_get`` returns
        ``{"ok": True, "value": "<the stored string>"}``. This unwraps
        that envelope and returns the string, or ``None`` on a miss.
        """
        result = await self.call_tool(
            "mahavishnu_kv_get",
            {"key": key, "user_id": INTERNAL_SERVICE_USER_ID},
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return None
        value = result.get("value")
        return value if isinstance(value, str) else None

    async def kv_list(
        self,
        prefix: str,
        user_id: str = INTERNAL_SERVICE_USER_ID,
    ) -> list[tuple[str, str]]:
        """List the ``(key, value)`` pairs whose key starts with ``prefix``.

        ``mahavishnu_kv_list`` returns
        ``{"ok": True, "items": [{"key": ..., "value": ...}], "count": N}``;
        this unwraps the envelope into the plain list the callers want.

        ``user_id`` is the principal the read is performed as. It
        defaults to the internal self-call principal, which is correct
        for the in-process substrate client. A caller outside the server
        process must pass the user id it has *verified* — the server
        applies that principal's permissions, and the KV tools apply the
        owning namespace's permission on top.
        """
        result = await self.call_tool(
            "mahavishnu_kv_list",
            {"prefix": prefix, "user_id": user_id},
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return []
        items = result.get("items")
        if not isinstance(items, list):
            return []
        pairs: list[tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if isinstance(key, str):
                pairs.append((key, value if isinstance(value, str) else ""))
        return pairs

    async def aclose(self) -> None:
        """Close the underlying MCP session."""
        await self._mcp.aclose()


# req: REQ-SUB-005
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
