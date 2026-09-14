"""String-shape Dhara KV adapter — fits PlanIndexStore's _DharaClient Protocol.

Why this exists: ``DharaStateBackend.get()`` returns the wire envelope dict
(``{"ok": True, "key": ..., "value": ...}``) on purpose — the workflow /
pool / approval ``recover_*`` helpers consume the dict shape directly.

``PlanIndexStore`` (plan_index/store.py:109-115) declares a different
contract on its ``_DharaClient`` Protocol::

    async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
    async def delete(self, key: str) -> None: ...

That is the canonical Mahavishnu KV surface — JSON-encoded strings on the
wire — and is what ``cron_core.run_rebuild_cycle`` consumes directly (it
does ``int(await dhara.get(KEY))``, ``json.loads(recent_raw)``, etc.).

Routing ``PlanIndexStore`` through ``DharaStateBackend`` crashes every cycle
with ``int() argument must be ... not 'dict'`` because the wire envelope is
a dict, not the raw string the cycle expects.

This adapter sits at the seam and unwraps Dhara's wire envelope so both
contracts can coexist on the same Dhara instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mahavishnu.core.dhara_adapter import DharaClient


@dataclass
class DharaKvConfig:
    """Configuration for the string-shape KV adapter."""

    enabled: bool = True


class DharaKvClient:
    """Thin adapter exposing Dhara's KV store under the string-shape Protocol.

    Wraps ``DharaClient`` (the raw MCP HTTP tool-call client). Each method
    unwraps Dhara's wire envelope:
      - ``dhara_get`` returns ``{"ok": True, "key": K, "value": V}`` →
        ``self.get`` returns ``V`` (as ``str``) or ``None``.
      - ``dhara_put`` returns ``{"ok": True, "key": K}`` → ``self.put``
        surfaces the ack by returning ``None`` (protocol: ``put → None``).
      - ``dhara_list_prefix`` returns
        ``{"ok": True, "count": N, "items": [{"key", "value"}, ...]}`` →
        ``self.list_prefix`` flattens to ``[(key, str_value), ...]``.
      - ``dhara_delete`` returns ``{"ok": True}`` → ``self.delete`` returns
        ``None``.

    Failures are swallowed with a no-op (mirrors ``DharaStateBackend``).
    The KV layer is non-authoritative; ``/health`` reports degradation
    rather than crashing the server on a Dhara outage.
    """

    def __init__(self, base_url: str, config: DharaKvConfig | None = None) -> None:
        self._client = DharaClient(base_url=base_url)
        self._config = config or DharaKvConfig()

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
