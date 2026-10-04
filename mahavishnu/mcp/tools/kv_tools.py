"""Self-hosted generic KV tools — backfill for the plan_index lock store.

The plan_index periodic rebuild cycle uses a small string-shape KV
(``get`` / ``put`` / ``list_prefix`` / ``delete``) for its
distributed lock: the holder key, the acquired-at timestamp, and the
claim keys. Originally this lived on a separate MCP server
(``docs/plans/2026-09-16-mcp-mcp-retirement-plan.md`` retired that
server in 2026-09) and was reached via ``MCPStateBackend`` /
``MCPKvClient`` (which are self-calls — see the wire-envelope comment
in :mod:`mahavishnu.core.state_backends.mcp_kv`).

This module re-homes the four tools onto mahavishnu's own MCP server,
backed by a process-local thread-safe dict. The plan_index runs in the
same process as the server (lifespan refactor, commit f6f2976f), so
process-local is sufficient for the lock keys — they are short-lived
(per-cycle) and a fresh acquisition after a restart is the safe
default. The store intentionally has no TTL eviction because the
plan_index only writes short-lived lock keys; if future callers need
TTL, expose ``mahavishnu_kv_put``'s ``ttl`` parameter (it is accepted
but currently a no-op).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)


class _ProcessLocalKV:
    """Thread-safe string-shape KV for self-hosted MCP tools.

    The MCP server is single-process; multiple concurrent tool calls
    run in the same event loop. A plain ``dict`` is safe under CPython's
    GIL for individual operations, but a ``threading.Lock`` makes the
    read-modify-write patterns in ``list_prefix`` race-free. The lock
    is held only across the in-memory mutation, not across any await,
    so it never blocks the event loop.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        with self._lock:
            return [(k, v) for k, v in self._data.items() if k.startswith(prefix)]


#: Module-level singleton — one per process. The lifespan refactor
#: (commit f6f2976f) runs the plan_index init in the same process as
#: the MCP server, so this is the canonical store for that cycle's
#: lock keys.
_kv_store = _ProcessLocalKV()


def _now_ms() -> int:
    return int(time.time() * 1000)


def register_kv_tools(mcp: FastMCP, rbac_manager: Any | None = None) -> None:
    """Register the four self-hosted KV tools.

    Tool names match the ``MCPKvClient`` contract on the client side
    (so plan_index's existing call sites in
    :mod:`mahavishnu.plan_index.cron_core` work without renaming) and
    follow the same ``mahavishnu_*`` namespace convention as the other
    ecosystem-state tools. Auth mirrors the other KV-bearing tools:
    READ requires ``Permission.READ_ECOSYSTEM_STATE``; WRITE requires
    ``Permission.WRITE_ECOSYSTEM_STATE``.

    The ``ttl`` parameter on ``put`` is accepted for forward
    compatibility but is currently a no-op (no eviction loop).
    """

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_get(key: str, user_id: str | None = None) -> dict[str, Any]:
        """Fetch a string-shaped KV record by ``key``.

        Returns ``{"ok": True, "value": "..."}`` on hit, ``{"ok": True,
        "value": null}`` on miss. The ``value`` field is the raw
        string the caller stored (plan_index stores JSON-encoded
        strings and decodes them itself).
        """
        value = _kv_store.get(key)
        return {"ok": True, "value": value}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.WRITE_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_put(
        key: str,
        value: str,
        ttl: int | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a string-shape KV record.

        ``ttl`` is accepted for forward compatibility with the original
        :class:`MCPStateBackend` API but is currently a no-op; the
        store has no eviction loop. The plan_index's lock keys are
        short-lived (per-cycle) and don't need TTL.
        """
        _kv_store.put(key, value)
        return {"ok": True, "key": key, "stored_at_ms": _now_ms()}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_list(
        prefix: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """List (key, value) pairs whose key starts with ``prefix``.

        Returns ``{"ok": True, "items": [{"key", "value"}, ...]}``.
        Empty prefix matches all keys. The plan_index uses this to
        enumerate claim keys during lock takeover.
        """
        items = [
            {"key": k, "value": v}
            for k, v in _kv_store.list_prefix(prefix)
        ]
        return {"ok": True, "items": items, "count": len(items)}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.WRITE_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_delete(
        key: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """Delete a string-shape KV record by ``key`` (no-op if absent)."""
        _kv_store.delete(key)
        return {"ok": True, "key": key}
