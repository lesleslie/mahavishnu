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

Routing ``PlanIndexStore`` through ``MCPStateBackend`` crashes every cycle
with ``int() argument must be ... not 'dict'`` because the wire envelope is
a dict, not the raw string the cycle expects.

This adapter sits at the seam and unwraps MCP's wire envelope so both
contracts can coexist on the same MCP instance.
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
    """Thin adapter exposing MCP's KV store under the string-shape Protocol.

    Wraps ``MCPClient`` (the raw MCP HTTP tool-call client). Each method
    unwraps MCP's wire envelope:
      - ``mcp_get`` returns ``{"ok": True, "key": K, "value": V}`` →
        ``self.get`` returns ``V`` (as ``str``) or ``None``.
      - ``mcp_put`` returns ``{"ok": True, "key": K}`` → ``self.put``
        surfaces the ack by returning ``None`` (protocol: ``put → None``).
      - ``mcp_list_prefix`` returns
        ``{"ok": True, "count": N, "items": [{"key", "value"}, ...]}`` →
        ``self.list_prefix`` flattens to ``[(key, str_value), ...]``.
      - ``mcp_delete`` returns ``{"ok": True}`` → ``self.delete`` returns
        ``None``.

    Failures are swallowed with a no-op (mirrors ``MCPStateBackend``).
    The KV layer is non-authoritative; ``/health`` reports degradation
    rather than crashing the server on a MCP outage.
    """

    def __init__(self, base_url: str, config: MCPKvConfig | None = None) -> None:
        self._client = MCPClient(base_url=base_url)
        self._config = config or MCPKvConfig()

    async def get(self, key: str) -> str | None:
        if not self._config.enabled:
            return None
        try:
            envelope = await self._client.call_tool("get", {"key": key})
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return None
        if not isinstance(envelope, dict):
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
            await self._client.put(key, value, ttl=ttl)
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        if not self._config.enabled:
            return []
        try:
            envelope = await self._client.call_tool("list_prefix", {"prefix": prefix})
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return []
        if not isinstance(envelope, dict):
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
            await self._client.call_tool("delete", {"key": key})
        except Exception:  # noqa: BLE001 - KV boundary never raises
            return

    async def aclose(self) -> None:
        await self._client.aclose()


def _encode_non_string(value: Any) -> str:
    """JSON-encode a non-string value so the (key, str) contract holds."""
    import json

    return json.dumps(value, separators=(",", ":"))
