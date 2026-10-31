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

The store itself lives in :mod:`mahavishnu.core.kv_store` so the
server's own producers — which write through
:mod:`mahavishnu.core.substrate` — and these public tools share one
instance. A sibling component reading ``ecosystem-services/…`` through
``mahavishnu_kv_get`` therefore sees what the server wrote.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

from mahavishnu.core.kv_store import kv_store  # req: REQ-SUBSTR-002
from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.auth import require_mcp_auth, resolved_user_id

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = get_logger(__name__)

#: Namespace → the permission that owns **reading** it.
#:
#: The store is shared by the substrate facade (the server's own
#: producers) and these public tools, so a key under one of these
#: namespaces holds records whose owning domain has its own permission.
#: The base permission the decorator requires is *not* sufficient to
#: reach them: a principal that may read the ecosystem registry must not
#: thereby be able to read every approval decision, every webhook
#: receipt and every workflow outcome.
#:
#: Keys outside these namespaces (the ``plan_index/`` lock keys, the
#: budget records, the envelope addresses) are governed by the base
#: permission alone.
_NAMESPACE_READ_PERMISSIONS: tuple[tuple[str, Permission], ...] = (
    ("approval-history/", Permission.READ_APPROVAL),
    ("webhook-ingress/", Permission.READ_WEBHOOK),
    ("workflow-results/", Permission.VIEW_WORKFLOW_STATUS),
)


def _owning_permission(key: str) -> Permission | None:
    """Return the permission that owns the namespace ``key`` lives in.

    Forward direction only: ``key`` is an exact key, so it either sits
    inside a namespace or it does not.
    """
    for namespace, permission in _NAMESPACE_READ_PERMISSIONS:
        if key.startswith(namespace):
            return permission
    return None


def _implicated_read_permissions(prefix: str) -> set[Permission]:
    """Every read permission a listing prefix can reach into.

    The store matches keys by prefix, so a prefix reaches a protected
    namespace in **two** directions, and checking only one of them
    leaks the namespace:

    * ``prefix.startswith(namespace)`` — the prefix is inside the
      namespace (``"approval-history/apr-1/"``).
    * ``namespace.startswith(prefix)`` — the prefix *truncates* the
      namespace, so the listing still returns its records. The empty
      prefix truncates every namespace, and so does ``"a"`` for the
      approval namespace, and ``"approval-history"`` without its
      trailing separator.

    A listing may implicate several namespaces at once (the empty
    prefix reaches all of them), and the caller must hold **every**
    implicated permission.
    """
    permissions: set[Permission] = set()
    for namespace, permission in _NAMESPACE_READ_PERMISSIONS:
        if namespace.startswith(prefix) or prefix.startswith(namespace):
            permissions.add(permission)
    return permissions


def _is_write_protected(key: str) -> bool:
    """Return ``True`` when ``key`` lands inside a domain-owned namespace.

    The domain-owned namespaces are written by the server's **own**
    producers, in process, through :mod:`mahavishnu.core.substrate`.
    They are never written through the public KV surface, so a
    mutation there is denied outright: there is no write permission
    for those namespaces, and a *read* permission must never authorise
    a mutation.
    """
    return any(key.startswith(namespace) for namespace, _ in _NAMESPACE_READ_PERMISSIONS)


async def _authorize_namespaces(
    rbac_manager: Any | None,
    user_id: str | None,
    subject: str,
    permissions: set[Permission],
) -> dict[str, Any] | None:
    """Require **every** permission in ``permissions``; return a denial or ``None``.

    ``None`` means "allowed" (or "no check possible", which cannot
    happen in production: the decorator already fails closed when no
    RBAC manager is configured).
    """
    if rbac_manager is None or not permissions:
        return None
    principal = await resolved_user_id(user_id)
    if not principal:
        return {
            "ok": False,
            "error": "Authentication required: user_id parameter missing",
            "error_code": "AUTH_REQUIRED",
        }
    for permission in sorted(permissions, key=lambda item: item.value):
        allowed = await rbac_manager.check_permission(principal, "*", permission)
        if allowed:
            continue
        logger.warning(
            "kv_namespace_permission_denied",
            extra={
                "subject": subject,
                "permission": permission.value,
                "user_id": principal,
            },
        )
        return {
            "ok": False,
            "error": f"Permission denied for namespace of {subject!r}",
            "error_code": "PERMISSION_DENIED",
        }
    return None


async def _readable_items(
    rbac_manager: Any | None,
    user_id: str | None,
    items: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Drop the items whose owning namespace the caller may not read.

    Defence in depth for the prefix check: even if the prefix logic were
    wrong, a record cannot leak through a mis-scoped prefix, because
    every returned key is checked against its own namespace.
    """
    if rbac_manager is None:
        return items
    principal = await resolved_user_id(user_id)
    if not principal:
        return []
    needed = {permission for key, _value in items if (permission := _owning_permission(key))}
    if not needed:
        return items
    granted = {
        permission
        for permission in needed
        if await rbac_manager.check_permission(principal, "*", permission)
    }
    return [
        (key, value)
        for key, value in items
        if (permission := _owning_permission(key)) is None or permission in granted
    ]


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

        A key under a namespace owned by another domain (an approval
        history, a webhook receipt, a workflow outcome) additionally
        requires that domain's read permission.
        """
        owning = _owning_permission(key)
        if owning is not None:
            denial = await _authorize_namespaces(rbac_manager, user_id, key, {owning})
            if denial is not None:
                return denial
        value = kv_store.get(key)
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

        The domain-owned namespaces (an approval history, a webhook
        receipt, a workflow outcome) are **write-protected**: they are
        written by the server's own producers, in process, and a read
        permission must never authorise a mutation of them.
        """
        if _is_write_protected(key):
            logger.warning(
                "kv_namespace_write_denied",
                extra={"key": key, "user_id": user_id},
            )
            return {
                "ok": False,
                "error": f"Key {key!r} is in a write-protected namespace",
                "error_code": "NAMESPACE_WRITE_PROTECTED",
            }
        kv_store.put(key, value)
        return {"ok": True, "key": key, "stored_at_ms": _now_ms()}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.READ_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_list(prefix: str, user_id: str | None = None) -> dict[str, Any]:
        """List (key, value) pairs whose key starts with ``prefix``.

        Returns ``{"ok": True, "items": [{"key", "value"}, ...]}``.
        Empty prefix matches all keys. The plan_index uses this to
        enumerate claim keys during lock takeover.

        A prefix that reaches a namespace owned by another domain (an
        approval history, a webhook receipt, a workflow outcome)
        additionally requires that domain's read permission — and a
        prefix that merely *truncates* a namespace reaches it too, so
        the empty prefix and ``"a"`` are both covered.
        """
        implicated = _implicated_read_permissions(prefix)
        if implicated:
            denial = await _authorize_namespaces(rbac_manager, user_id, prefix, implicated)
            if denial is not None:
                return denial
        pairs = await _readable_items(rbac_manager, user_id, kv_store.list_prefix(prefix))
        items = [{"key": k, "value": v} for k, v in pairs]
        return {"ok": True, "items": items, "count": len(items)}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager, required_permission=Permission.WRITE_ECOSYSTEM_STATE
    )
    async def mahavishnu_kv_delete(key: str, user_id: str | None = None) -> dict[str, Any]:
        """Delete a string-shape KV record by ``key`` (no-op if absent).

        The domain-owned namespaces (an approval history, a webhook
        receipt, a workflow outcome) are **write-protected**: they are
        written by the server's own producers, in process, and a read
        permission must never authorise a mutation of them.
        """
        if _is_write_protected(key):
            logger.warning(
                "kv_namespace_write_denied",
                extra={"key": key, "user_id": user_id},
            )
            return {
                "ok": False,
                "error": f"Key {key!r} is in a write-protected namespace",
                "error_code": "NAMESPACE_WRITE_PROTECTED",
            }
        kv_store.delete(key)
        return {"ok": True, "key": key}
