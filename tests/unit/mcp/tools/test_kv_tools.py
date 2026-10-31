"""Verify the four self-hosted KV tools, including their namespace scoping.

The store is shared by the substrate facade (the server's own producers)
and these public tools, so a key under a namespace owned by another
domain — an approval history, a webhook receipt, a workflow outcome —
holds records that domain's permission governs.

Two regressions this file guards, both real bypasses of the first
version of the scoping:

1. **The prefix direction.** The store matches keys by prefix, so a
   listing prefix reaches a protected namespace in two directions: it
   can be *inside* the namespace, or it can *truncate* it. Checking
   only the first let ``""`` (every key), ``"a"`` and
   ``"approval-history"`` (no trailing separator) read the approval
   history without holding ``READ_APPROVAL``.
2. **Read authorising write.** The domain namespaces are written by the
   server's own producers, in process. A principal that may *read* the
   approval history must not be able to *write* or *delete* it, so the
   mutating tools deny those namespaces outright.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP
import pytest

from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.permissions import Permission
from mahavishnu.mcp.tools.kv_tools import (
    _authorize_namespaces,
    _implicated_read_permissions,
    _is_write_protected,
    _owning_permission,
    register_kv_tools,
)

pytestmark = pytest.mark.unit

#: The base permission the KV tools' own gate requires. The namespace
#: permission is the *extra* one under test.
_BASE: set[Permission] = {
    Permission.READ_ECOSYSTEM_STATE,
    Permission.WRITE_ECOSYSTEM_STATE,
}

#: Every domain-owned read permission.
_ALL_DOMAIN_READS: set[Permission] = {
    Permission.READ_APPROVAL,
    Permission.READ_WEBHOOK,
    Permission.VIEW_WORKFLOW_STATUS,
}


class _RecordingRBAC:
    """Fake RBAC manager that records the permissions it was asked about."""

    def __init__(self, granted: set[Permission]) -> None:
        self._granted = granted
        self.checked: list[Permission] = []

    async def check_permission(self, user_id: str, repo: str, permission: Permission) -> bool:
        self.checked.append(permission)
        return permission in self._granted


def _register(granted: set[Permission]) -> tuple[FastMCP, _RecordingRBAC]:
    """Register the KV tools with an RBAC manager granting ``granted``."""
    server = FastMCP(name="kv-test")
    rbac = _RecordingRBAC(granted)
    register_kv_tools(server, rbac)  # ty: ignore[invalid-argument-type]
    return server, rbac


async def _call(server: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a registered tool and return its result payload."""
    tool = next(t for t in await server.list_tools() if t.name == name)
    result = await tool.fn(**arguments)  # ty: ignore[unresolved-attribute]
    return result


# ---------------------------------------------------------------------------
# Namespace → permission mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("approval-history/apr-1/2026-x-deadbeef", Permission.READ_APPROVAL),
        ("webhook-ingress/evt-1/", Permission.READ_WEBHOOK),
        ("workflow-results/wf-1/", Permission.VIEW_WORKFLOW_STATUS),
        ("ecosystem-services/svc-1/", None),
        ("ecosystem-events/evt-1/", None),
        ("plan_index/meta/rebuild_lock/holder", None),
        ("verification/entries", None),
    ],
)
def test_owning_permission(key: str, expected: Permission | None) -> None:
    """An exact key is owned by a namespace only if it sits inside one."""
    assert _owning_permission(key) is expected


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        # Inside the namespace.
        ("approval-history/apr-1/", {Permission.READ_APPROVAL}),
        ("webhook-ingress/evt-1/", {Permission.READ_WEBHOOK}),
        ("workflow-results/wf-1/", {Permission.VIEW_WORKFLOW_STATUS}),
        # Truncating the namespace — the listing still returns its records.
        ("approval-history", {Permission.READ_APPROVAL}),
        ("a", {Permission.READ_APPROVAL}),
        ("w", {Permission.READ_WEBHOOK, Permission.VIEW_WORKFLOW_STATUS}),
        ("", _ALL_DOMAIN_READS),
        # Outside every namespace.
        ("plan_index/", set()),
        ("verification/", set()),
        ("envelopes/", set()),
    ],
)
def test_implicated_read_permissions(prefix: str, expected: set[Permission]) -> None:
    """A listing prefix implicates a namespace in either direction."""
    assert _implicated_read_permissions(prefix) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("approval-history/apr-1/x", True),
        ("webhook-ingress/evt-1/", True),
        ("workflow-results/wf-1/", True),
        ("plan_index/meta/x", False),
        ("approval-history", False),
        ("", False),
    ],
)
def test_is_write_protected(key: str, expected: bool) -> None:
    """Only a key *inside* a domain namespace is write-protected."""
    assert _is_write_protected(key) is expected


# ---------------------------------------------------------------------------
# The prefix-direction bypasses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_prefix_is_denied() -> None:
    """The empty prefix reaches every namespace, so it needs every permission."""
    server, rbac = _register(_BASE)
    kv_store.put("approval-history/apr-1/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_list",
        {"prefix": "", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "PERMISSION_DENIED"
    # The check is fail-fast: it stops at the first missing permission.
    assert Permission.READ_APPROVAL in rbac.checked


@pytest.mark.asyncio
async def test_prefix_truncating_a_namespace_is_denied() -> None:
    """``"a"`` truncates ``approval-history/`` and reaches its records."""
    server, rbac = _register(_BASE)
    kv_store.put("approval-history/apr-1/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_list",
        {"prefix": "a", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "PERMISSION_DENIED"
    assert Permission.READ_APPROVAL in rbac.checked


@pytest.mark.asyncio
async def test_prefix_without_the_trailing_separator_is_denied() -> None:
    """``"approval-history"`` (no slash) still returns the namespace's keys."""
    server, _rbac = _register(_BASE)
    kv_store.put("approval-history/apr-1/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_list",
        {"prefix": "approval-history", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_listing_everything_is_allowed_with_every_permission() -> None:
    """A principal holding all three domain read permissions may list all."""
    server, _rbac = _register(_BASE | _ALL_DOMAIN_READS)
    kv_store.put("approval-history/apr-1/x", "{}")
    kv_store.put("plan_index/meta/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_list",
        {"prefix": "", "user_id": "alice"},
    )

    assert result["ok"] is True
    assert result["count"] == 2


# ---------------------------------------------------------------------------
# Read authorising write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kv_put_cannot_write_a_domain_namespace() -> None:
    """READ_APPROVAL must not authorise writing the approval history."""
    server, _rbac = _register(_BASE | {Permission.READ_APPROVAL})

    result = await _call(
        server,
        "mahavishnu_kv_put",
        {"key": "approval-history/apr-1/x", "value": "{}", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "NAMESPACE_WRITE_PROTECTED"
    assert kv_store.get("approval-history/apr-1/x") is None


@pytest.mark.asyncio
async def test_kv_delete_cannot_delete_a_domain_namespace() -> None:
    """READ_APPROVAL must not authorise deleting the approval history."""
    server, _rbac = _register(_BASE | {Permission.READ_APPROVAL})
    kv_store.put("approval-history/apr-1/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_delete",
        {"key": "approval-history/apr-1/x", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "NAMESPACE_WRITE_PROTECTED"
    assert kv_store.get("approval-history/apr-1/x") is not None


@pytest.mark.asyncio
async def test_the_approval_cli_cannot_write_the_approval_history() -> None:
    """The approval reader is a reader: it must not be able to write."""
    server, _rbac = _register(_BASE | {Permission.READ_APPROVAL})

    put_result = await _call(
        server,
        "mahavishnu_kv_put",
        {"key": "approval-history/apr-1/x", "value": "{}", "user_id": "alice"},
    )
    assert put_result["ok"] is False
    assert put_result["error_code"] == "NAMESPACE_WRITE_PROTECTED"

    delete_result = await _call(
        server,
        "mahavishnu_kv_delete",
        {"key": "approval-history/apr-1/x", "user_id": "alice"},
    )
    assert delete_result["ok"] is False
    assert delete_result["error_code"] == "NAMESPACE_WRITE_PROTECTED"


# ---------------------------------------------------------------------------
# The read scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kv_get_denies_a_foreign_namespace() -> None:
    """A principal without READ_APPROVAL cannot read the approval history."""
    server, rbac = _register(_BASE)
    kv_store.put("approval-history/apr-1/x", '{"secret": true}')

    result = await _call(
        server,
        "mahavishnu_kv_get",
        {"key": "approval-history/apr-1/x", "user_id": "alice"},
    )

    assert result["ok"] is False
    assert result["error_code"] == "PERMISSION_DENIED"
    assert Permission.READ_APPROVAL in rbac.checked


@pytest.mark.asyncio
async def test_kv_get_allows_the_owning_namespace() -> None:
    """A principal with the owning permission can read the record."""
    server, rbac = _register(_BASE | {Permission.READ_APPROVAL})
    kv_store.put("approval-history/apr-1/x", '{"secret": true}')

    result = await _call(
        server,
        "mahavishnu_kv_get",
        {"key": "approval-history/apr-1/x", "user_id": "alice"},
    )

    assert result["ok"] is True
    assert result["value"] == '{"secret": true}'
    assert Permission.READ_APPROVAL in rbac.checked


@pytest.mark.asyncio
async def test_unowned_namespace_needs_no_extra_permission() -> None:
    """A key outside the domain namespaces is governed by the base gate only."""
    server, rbac = _register(_BASE)

    result = await _call(
        server,
        "mahavishnu_kv_put",
        {"key": "plan_index/meta/rebuild_lock/holder", "value": "x", "user_id": "alice"},
    )

    assert result["ok"] is True
    assert kv_store.get("plan_index/meta/rebuild_lock/holder") == "x"
    # No namespace permission was consulted.
    assert Permission.READ_APPROVAL not in rbac.checked


@pytest.mark.asyncio
async def test_internal_principal_name_alone_is_denied() -> None:
    """Naming the internal principal is not a credential.

    The auth gate requires the verified self-call credential for the
    internal principal; the name in the ``user_id`` argument is a claim
    and is refused before the namespace check is even reached.
    """
    server, _rbac = _register(_BASE)
    kv_store.put("approval-history/apr-1/x", "{}")

    result = await _call(
        server,
        "mahavishnu_kv_get",
        {"key": "approval-history/apr-1/x", "user_id": "mahavishnu-internal"},
    )

    assert result["status"] == "error"
    assert result["error_code"] == "AUTH_INVALID_IDENTITY"


@pytest.mark.asyncio
async def test_internal_role_is_denied_the_approval_namespace() -> None:
    """The internal service role holds ecosystem-state rights only.

    Even with its credential verified, the internal role must not reach
    the approval namespace: the approval history is read by a principal
    that holds ``READ_APPROVAL``.
    """
    rbac = _RecordingRBAC(_BASE)

    denial = await _authorize_namespaces(
        rbac,  # ty: ignore[invalid-argument-type]
        "mahavishnu-internal",
        "approval-history/apr-1/x",
        {Permission.READ_APPROVAL},
    )

    assert denial is not None
    assert denial["error_code"] == "PERMISSION_DENIED"
    assert Permission.READ_APPROVAL in rbac.checked


# ---------------------------------------------------------------------------
# The base gate still applies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_permission_is_still_required() -> None:
    """Without the base permission the decorator denies before the tool runs."""
    server = FastMCP(name="kv-test")
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=False)
    register_kv_tools(server, rbac)  # ty: ignore[invalid-argument-type]

    result = await _call(
        server,
        "mahavishnu_kv_get",
        {"key": "plan_index/meta/x", "user_id": "alice"},
    )

    assert result["status"] == "error"
    assert result["error_code"] == "PERMISSION_DENIED"
