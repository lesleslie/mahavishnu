"""Minimal Dhara MCP client and analytics adapter.

This module provides a small async HTTP client for Dhara's MCP HTTP transport.
Mahavishnu uses it for health persistence and git analytics until a richer
service-specific SDK exists.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DharaClient:
    """Async client for Dhara's MCP HTTP tool endpoint."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def tools_url(self) -> str:
        """Return the tool invocation endpoint."""
        return f"{self.base_url}/tools/call"

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a Dhara MCP tool over HTTP."""
        response = await self._client.post(
            self.tools_url,
            json={
                "name": name,
                "arguments": arguments,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

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
        """Close the underlying HTTP client."""
        await self._client.aclose()


class DharaAdapter:
    """Thin analytics adapter used by MCP tools."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.client = DharaClient(base_url=base_url, timeout=timeout)

    async def query_time_series(
        self,
        metric_type: str,
        entity_id: str,
        start_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query time-series metrics from Dhara."""
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
        logger.debug("Unexpected Dhara time-series response shape: %r", result)
        return []

    async def aggregate_patterns(
        self,
        start_date: str,
        min_occurrences: int = 2,
    ) -> list[dict[str, Any]]:
        """Query aggregated patterns from Dhara."""
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
        logger.debug("Unexpected Dhara pattern response shape: %r", result)
        return []
