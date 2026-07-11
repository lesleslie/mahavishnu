"""Thin async client for Dhara's SQL proxy MCP tools.

This module is the substrate for ``execute``/``query`` calls that go
through Dhara's MCP ``sql_proxy_execute`` and ``sql_proxy_query`` tools.
The proxy is implemented in ``dhara/mcp/tools/sql_proxy.py``; this file
is the Mahavishnu-side thin wrapper.

Design constraints (from 2026-06-27-dhara-substrate-implementation.md):

* Keep the existing ``dhara_adapter.py`` surface (``put``/``call_tool``/
  ``query_time_series``/``aggregate_patterns``) untouched. ``execute`` and
  ``query`` are additive.
* Connection pooling: if a ``DharaClient`` (or ``DharaAdapter``-shaped
  object exposing ``call_tool``) is supplied, reuse it. Otherwise this
  module opens its own ``httpx.AsyncClient`` (one per instance).
* All I/O is async (``httpx.AsyncClient``).
* Connection-level failures raise ``DharaSQLProxyError`` so callers can
  handle transport failures separately from semantic SQL errors.

Mahavishnu conventions honored:

* ``from __future__ import annotations`` first.
* Modern ``X | None`` and ``list[dict]`` typing (no ``Optional``/``List``).
* ``pathlib.Path`` not used here — this module only does HTTP.
* All async; no blocking calls.
* Uses ``oneiric.logging``-style structured logging via stdlib
  ``logging.getLogger`` (existing project pattern).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DharaSQLProxyError(Exception):
    """Raised when the Dhara SQL proxy transport fails.

    This wraps connection-level errors (timeouts, refused connections,
    unexpected 5xx). SQL semantic errors from the backend are passed
    through as-is via ``DharaSQLProxyError.__cause__`` so callers can
    introspect via ``raise ... from``.
    """


class DharaThinClient:
    """Thin async client for Dhara's ``sql_proxy`` MCP tools.

    Parameters
    ----------
    base_url:
        Root URL of the Dhara MCP server (e.g. ``http://localhost:8683``).
    timeout:
        Per-request timeout in seconds. Defaults to 30s.
    adapter:
        Optional pre-existing ``DharaClient``-shaped object exposing
        ``call_tool(name, arguments)``. When supplied, ``execute`` and
        ``query`` route through it (no extra HTTP client is opened).
    token:
        Optional bearer token forwarded in the ``Authorization`` header.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        adapter: Any | None = None,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._adapter = adapter
        self._owns_client = adapter is None
        if self._owns_client:
            headers = {"Authorization": f"Bearer {token}"} if token else None
            self._client: httpx.AsyncClient | None = httpx.AsyncClient(
                timeout=timeout,
                headers=headers,
            )
        else:
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a write statement (INSERT/UPDATE/DELETE).

        Returns the proxy's ``result`` payload — typically
        ``{"rowcount": int, "status": str}``.
        """
        payload = {"sql": sql, "params": params or {}}
        result = await self._invoke("sql_proxy_execute", payload)
        if not isinstance(result, dict):
            # The proxy contract is a dict. Surface unexpected shapes so
            # callers don't silently consume garbage.
            raise DharaSQLProxyError(
                f"sql_proxy_execute returned non-dict: {type(result).__name__}"
            )
        return result

    async def query(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a SELECT statement and return rows as ``dict``s."""
        payload = {"sql": sql, "params": params or {}}
        result = await self._invoke("sql_proxy_query", payload)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("rows"), list):
            return list(result["rows"])
        if isinstance(result, dict):
            # Fall back to common alternative response shapes.
            for key in ("result", "records", "items"):
                value = result.get(key)
                if isinstance(value, list):
                    return value
        raise DharaSQLProxyError(
            f"sql_proxy_query returned unexpected shape: {type(result).__name__}"
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it.

        Only the client opened by this instance is closed. When an
        adapter is supplied, the caller owns the transport lifecycle.
        """
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Route a tool call through the adapter or own HTTP client.

        Connection-level failures are wrapped in ``DharaSQLProxyError``;
        semantic SQL errors raised by the proxy are re-raised verbatim
        via ``raise ... from`` so callers can inspect the original.
        """
        if self._adapter is not None:
            return await self._invoke_via_adapter(tool_name, arguments)
        return await self._invoke_via_http(tool_name, arguments)

    async def _invoke_via_adapter(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call the tool through the registered adapter."""
        if self._adapter is None:
            raise DharaSQLProxyError(
                f"{tool_name} requested via adapter path but no adapter is registered"
            )
        try:
            return await self._adapter.call_tool(tool_name, arguments)
        except DharaSQLProxyError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface transport failures
            logger.warning(
                "dhara adapter call_tool failed for %s: %s",
                tool_name,
                exc,
            )
            raise DharaSQLProxyError(f"{tool_name} failed via adapter: {exc}") from exc

    async def _invoke_via_http(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call the tool through the direct HTTP client."""
        if self._client is None:
            # Defensive: someone called after aclose(). Re-open on demand.
            self._client = httpx.AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}/tools/call"
        body = {"name": tool_name, "arguments": arguments}
        try:
            response = await self._client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("dhara sql_proxy transport failure: %s", exc)
            raise DharaSQLProxyError(f"{tool_name} transport failure: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — surface anything unexpected
            logger.exception("dhara sql_proxy unexpected failure")
            raise DharaSQLProxyError(f"{tool_name} unexpected failure: {exc}") from exc

        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload


__all__ = ["DharaSQLProxyError", "DharaThinClient"]
