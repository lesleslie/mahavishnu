"""Minimal MCP MCP client and analytics adapter.

This module provides a small async MCP client for MCP's HTTP transport.
Mahavishnu uses it for health persistence and git analytics until a richer
service-specific SDK exists.

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
        """Call a MCP MCP tool over streamable-HTTP."""
        return await self._mcp.call_tool(name, arguments)

    async def put(self, key: str, value: Any, ttl: int | None = None) -> Any:
        """Persist a key/value record if the server exposes a storage tool."""
        arguments: dict[str, Any] = {
            "key": key,
            "value": value,
        }
        if ttl is not None:
            arguments["ttl"] = ttl
        return await self.call_tool("put", arguments)

    async def aclose(self) -> None:
        """Close the underlying MCP session."""
        await self._mcp.aclose()


class MCPAdapter:
    """Thin analytics adapter used by MCP tools."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.client = MCPClient(base_url=base_url, timeout=timeout)

    async def query_time_series(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query time-series metrics from MCP."""
        arguments: dict[str, Any] = {
            "metric_type": metric_type,
            "entity_id": entity_id,
        }
        if start_date is not None:
            arguments["start_date"] = start_date
        if limit is not None:
            arguments["limit"] = limit
        result = await self.client.call_tool("query_time_series", arguments)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            records = result.get("records") or result.get("items") or result.get("result")
            if isinstance(records, list):
                return records
        logger.debug("Unexpected MCP time-series response shape: %r", result)
        return []

    async def aggregate_patterns(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        """Query aggregated patterns from MCP."""
        result = await self.client.call_tool(
            "aggregate_patterns",
            {
                "start_date": start_date,
                "min_occurrences": min_occurrences,
            },
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            patterns = result.get("patterns") or result.get("result")
            if isinstance(patterns, list):
                return patterns
        logger.debug("Unexpected MCP pattern response shape: %r", result)
        return []


__all__ = ["MCPAdapter", "MCPClient"]
