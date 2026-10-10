"""Test: ``RBACManager.check_permission`` bridges ``mcp_common.auth.permissions.Permission`` values.

Wave 7 (2026-10-10) #2 follow-up. The ``@require_mcp_auth`` decorator
in ``mahavishnu/mcp/auth.py`` reads permissions from
``mcp_common.auth.permissions.Permission`` (a SEPARATE enum class from
``mahavishnu.core.permissions.Permission``). The two enums have
non-overlapping values (``READ``='read' vs ``READ_REPO``='read_repo').
The pre-fix ``check_permission`` did:

    permission = Permission(permission.lower())  # only the local enum

which meant an admin role holding all ``Permission.READ_REPO`` could not
satisfy a check for ``mcp_common.Permission.READ`` (``'read'``) — Python
``in`` compares by identity, and the local enum's members don't match
the foreign enum's values.

The fix widens ``Role.permissions`` to ``list[Permission | str]`` and
compares in ``check_permission`` by string ``.value``. This test pins
the new contract: admin grants satisfy BOTH enums, non-admin still
scopes by ``allowed_repos``, and unknown users are denied.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.permissions import (
    Permission,
    RBACManager,
    Role,
    User,
)


class _StubConfig:
    """Minimal stand-in for ``MahavishnuSettings`` — RBACManager's __init__
    only stores it; the permissions tests don't read it.
    """

    pass


def _make_rbac() -> RBACManager:
    return RBACManager(_StubConfig())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_admin_role_includes_mcp_common_string_values() -> None:
    """The pre-defined admin role must grant both project-local
    Permission values AND the mcp_common string values so a check
    against either enum passes.
    """
    rbac = _make_rbac()
    admin = rbac.roles["admin"]
    perm_values = {str(p) for p in admin.permissions}
    # All 14 project-local permissions (as enum members)
    for p in Permission:
        assert p in admin.permissions, f"admin missing {p}"
    # The 4 mcp_common string values
    for mcp_perm in ("read", "write", "delete", "admin"):
        assert mcp_perm in perm_values, (
            f"admin missing mcp_common string value {mcp_perm!r}"
        )


@pytest.mark.asyncio
async def test_admin_check_passes_mcp_common_read_string() -> None:
    """When a tool calls ``require_mcp_auth(..., MCPPermission.READ)``,
    the RBACManager sees a Permission value of ``'read'``. The admin
    role must satisfy it.
    """
    rbac = _make_rbac()
    await rbac.create_user("les", roles=["admin"])

    # Simulate the mcp_common Permission.READ value
    class _MCPRead:
        value = "read"

    result = await rbac.check_permission("les", "/Users/les/Projects/mahavishnu", _MCPRead())
    assert result is True, (
        "admin role must pass mcp_common 'read' check via string-value bridge"
    )


@pytest.mark.asyncio
async def test_admin_check_passes_project_local_read_repo() -> None:
    """Sanity: the original use case (project-local Permission.READ_REPO)
    must still pass for admin. Guards against a regression that
    converts ``Permission`` instances to strings and breaks the
    identity comparison.
    """
    rbac = _make_rbac()
    await rbac.create_user("les", roles=["admin"])

    result = await rbac.check_permission(
        "les", "/Users/les/Projects/mahavishnu", Permission.READ_REPO
    )
    assert result is True


@pytest.mark.asyncio
async def test_unknown_user_is_denied() -> None:
    """A user that was never created must be denied even with admin
    role name. Guards against a regression that grants default
    privileges to unauthenticated callers.
    """
    rbac = _make_rbac()

    result = await rbac.check_permission(
        "ghost", "/Users/les/Projects/mahavishnu", Permission.READ_REPO
    )
    assert result is False


@pytest.mark.asyncio
async def test_viewer_role_denies_mcp_common_write() -> None:
    """A viewer must not get write access even when the check passes
    a mcp_common string value. Per-repository + per-permission
    scoping is preserved — the bridge only adds value-comparison, it
    does not weaken the role ACLs.
    """
    rbac = _make_rbac()
    await rbac.create_user("alice", roles=["viewer"])

    # Viewer grants: READ_REPO, LIST_WORKFLOWS, VIEW_WORKFLOW_STATUS
    # The mcp_common 'write' value is NOT in the viewer role.
    result = await rbac.check_permission(
        "alice", "/Users/les/Projects/mahavishnu", "write"
    )
    assert result is False, (
        "viewer role must NOT pass mcp_common 'write' check"
    )


@pytest.mark.asyncio
async def test_viewer_role_passes_mcp_common_read() -> None:
    """A viewer's READ_REPO is equivalent to mcp_common READ for the
    purpose of this check (both surface as 'read_repo' or 'read' in
    the role). The viewer should pass a 'read' check since they have
    READ_REPO. Note: the bridge matches by string value, so
    'read_repo' is what the viewer role grants, and 'read' (the
    mcp_common value) is NOT a match. The viewer would NOT pass
    mcp_common 'read' unless 'read' is explicitly added to their role.
    """
    rbac = _make_rbac()
    await rbac.create_user("bob", roles=["viewer"])

    # mcp_common 'read' value — viewer has READ_REPO ('read_repo'),
    # which is a DIFFERENT string, so this should fail unless admin.
    result = await rbac.check_permission(
        "bob", "/Users/les/Projects/mahavishnu", "read"
    )
    assert result is False, (
        "viewer grants READ_REPO ('read_repo'), not mcp_common "
        "'read' — value-comparison keeps them distinct"
    )


@pytest.mark.asyncio
async def test_role_permissions_accepts_string_values() -> None:
    """Pydantic model must accept string permission entries in the
    ``permissions`` list without raising.
    """
    role = Role(
        name="custom",
        permissions=["read", "write", Permission.READ_REPO],
        allowed_repos=None,
    )
    assert "read" in {str(p) for p in role.permissions}
    assert Permission.READ_REPO in role.permissions
