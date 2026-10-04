"""String-shape MCP KV adapter — fits PlanIndexStore's _MCPClient Protocol.

Why this exists: ``MCPStateBackend.get()`` returns the wire envelope dict
(``{"ok": True, "key": ..., "value": ...}``) on purpose — the workflow /
pool / approval ``recover_*`` helpers consume the dict shape directly.

``PlanIndexStore`` (plan_index/store.py:109-115) declares a different
contract on its ``_MCPClient`` Protocol::

    async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
    async def delete(self, key: str) -> None: ...

That is the canonical Mahavishnu KV surface — JSON-encoded strings on the
wire — and is what ``cron_core.run_rebuild_cycle`` consumes directly (it
does ``int(await mcp.get(KEY))``, ``json.loads(recent_raw)``, etc.).

The four tools (``mahavishnu_kv_get`` / ``put`` / ``list`` / ``delete``)
are registered on mahavishnu's own MCP server by
:mod:`mahavishnu.mcp.tools.kv_tools`, backed by a process-local
thread-safe dict (the previous MCP MCP server that hosted these tools
was retired per ``docs/plans/2026-09-16-mcp-mcp-retirement-plan.md``;
plan_index was left with no backend). Routing
``PlanIndexStore`` through the new tools works because the seam —
``MCPClient.call_tool`` returning the unwrapped tool return value
(see ``mahavishnu.core.mcp_adapter``) — finally matches the
``Protocol`` shape that ``PlanIndexStore`` declares.

The new tools wrap their return in ``{"ok": True, ...}`` envelopes
(matching the project-wide convention from the other ecosystem-state
tools). This adapter unwraps the envelope and surfaces just the
``value`` (or ``items`` list, or the ack) so ``PlanIndexStore`` sees
the canonical string-shape contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mahavishnu.core.mcp_adapter import MCPClient


@dataclass
class MCPKvConfig:
    """Configuration for the string-shape KV adapter."""

    enabled: bool = True


class MCPKvClient:
    """Thin adapter exposing the self-hosted KV under the string-shape Protocol.

    Routes through the ``mahavishnu_kv_get`` / ``_put`` / ``_list`` /
    ``_delete`` tools on the same mahavishnu MCP server. Each call's
    response is ``{"ok": True, "value": "..."}`` /
    ``{"ok": True, "key": "...", "stored_at_ms": N}`` /
    ``{"ok": True, "items": [{"key", "value"}, ...], "count": N}`` /
    ``{"ok": True, "key": "..."}`` — this adapter unwraps the
    ``{"ok": True, ...}`` envelope and surfaces the string-shape value
    so the ``PlanIndexStore`` Protocol contract holds.

    Failures are swallowed with a no-op (mirrors ``MCPStateBackend``).
    The KV layer is non-authoritative; ``/health`` reports degradation
    rather than crashing the server on a KV outage.
    """

    def __init__(self, base_url: str, config: MCPKvConfig | None = None) -> None:
        self._client = MCPClient(base_url=base_url)
        self._config = config or MCPKvConfig()

    async def get(self, key: str) -> str | None:
        if not self._config.enabled:
            return None
        try:
            envelope = await self._client.call_tool(
                "mahavishnu_kv_get", {"key": key}
            )
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return None
        if not isinstance(envelope, dict):
            return None
        if not envelope.get("ok"):
            return None
        value = envelope.get("value")
        if value is None:
            return None
        # PlanIndexStore only stores JSON-encoded strings; surfaces that
        # receive a non-string value (legacy mixed-type stores) get a
        # json-encoded form so callers always see a str | None contract.
        return value if isinstance(value, str) else _encode_non_string(value)

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        if not self._config.enabled:
            return
        try:
            await self._client.call_tool(
                "mahavishnu_kv_put", {"key": key, "value": value, "ttl": ttl}
            )
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        if not self._config.enabled:
            return []
        try:
            envelope = await self._client.call_tool(
                "mahavishnu_kv_list", {"prefix": prefix}
            )
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return []
        if not isinstance(envelope, dict):
            return []
        if not envelope.get("ok"):
            return []
        items = envelope.get("items")
        if not isinstance(items, list):
            return []
        out: list[tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if not isinstance(key, str):
                continue
            if value is None:
                # Surface as empty string so the (key, str) contract holds
                # and downstream ``json.loads`` produces ``None`` rather
                # than raising on missing values.
                out.append((key, ""))
            elif isinstance(value, str):
                out.append((key, value))
            else:
                out.append((key, _encode_non_string(value)))
        return out

    async def delete(self, key: str) -> None:
        if not self._config.enabled:
            return
        try:
            await self._client.call_tool(
                "mahavishnu_kv_delete", {"key": key}
            )
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return

    async def aclose(self) -> None:
        await self._client.aclose()


def _encode_non_string(value: Any) -> str:
    """JSON-encode a non-string value so the (key, str) contract holds."""
    import json

    return json.dumps(value, separators=(",", ":"))
