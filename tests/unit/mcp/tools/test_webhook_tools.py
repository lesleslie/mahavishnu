"""Verify webhook_replay_tool is registered as an MCP tool.

Mirrors the sibling ``tests/unit/mcp/tools/test_workflow_tools.py``
shape: register the tool group on a fresh FastMCP server, introspect
the registered tools via ``mcp.list_tools()``, and exercise both the
happy path (read returns a dict) and the AUTH_REQUIRED gate
(@require_mcp_auth rejects missing ``user_id``).

The tests use the REAL substrate facade: the store is process-local and
``tests/conftest.py`` clears it around every test, so the record written
here is the record the tool reads back.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastmcp import FastMCP
import pytest

from mahavishnu.core import substrate
from mahavishnu.core.kv_store import kv_store
from mahavishnu.mcp.tools.webhook_tools import register_webhook_tools

pytestmark = pytest.mark.unit


def _fake_rbac_manager() -> Any:
    """Return a fake RBAC manager that allows all checks.

    The ``@require_mcp_auth`` decorator calls
    ``rbac_manager.check_permission`` as an awaitable. ``AsyncMock``
    returning ``True`` satisfies the gate so tests can drive the
    AUTH_REQUIRED path (missing ``user_id``) without standing up a
    real RBAC.
    """
    rbac = MagicMock()
    rbac.check_permission = AsyncMock(return_value=True)
    return rbac


@pytest.mark.asyncio
async def test_register_webhook_tools_registers_tool() -> None:
    """register_webhook_tools registers webhook_replay_tool as an MCP tool."""
    mcp = FastMCP(name="test-webhook-tools")
    register_webhook_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    # FastMCP derives tool name from the inline function's __name__.
    assert "webhook_replay_tool" in tool_names

    # And: the registered coroutine is async, matching the FastMCP contract.
    tool = next(t for t in tools if t.name == "webhook_replay_tool")
    assert asyncio.iscoroutinefunction(tool.fn)


@pytest.mark.asyncio
async def test_registered_tool_returns_dict_for_known_webhook() -> None:
    """End-to-end: calling the registered MCP tool returns the persisted dict.

    The leaf ``webhook_replay`` reads through the substrate facade; the
    msgspec.Struct round-trip then rebuilds ``WebhookIngress`` from the
    payload, and the wrapper calls ``msgspec.to_builtins()``.
    """
    payload = {
        "webhook_id": "wh-abc",
        "source": "openclaw",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"hello": "world"},
    }
    substrate.put("webhook-ingress/wh-abc/", payload)

    mcp = FastMCP(name="test-webhook-tools-roundtrip")
    register_webhook_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    # The leaf requires a JWT-shaped token; pass one so the RBAC gate
    # inside webhook_replay falls through.
    result = await tool.fn(
        webhook_id="wh-abc",
        user_id="viewer-1",
        token="a.b.c",
    )

    assert isinstance(result, dict)
    assert result["webhook_id"] == "wh-abc"


@pytest.mark.asyncio
async def test_registered_tool_returns_none_when_record_missing() -> None:
    """End-to-end: when no record exists, the tool returns ``None``."""
    mcp = FastMCP(name="test-webhook-tools-missing")
    register_webhook_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(
        webhook_id="wh-missing",
        user_id="viewer-1",
        token="a.b.c",
    )

    assert result is None


@pytest.mark.asyncio
async def test_registered_tool_rejects_without_user_id() -> None:
    """@require_mcp_auth wrapper rejects calls missing ``user_id``.

    Without ``user_id`` the wrapper returns the AUTH_REQUIRED error
    envelope before the underlying ``webhook_replay`` runs; the
    substrate is never touched. Mirrors the brief's
    "rejection without permission" contract.
    """
    mcp = FastMCP(name="test-webhook-tools-auth")
    register_webhook_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(webhook_id="wh-1", token="a.b.c")

    assert isinstance(result, dict)
    assert result.get("status") == "error"
    assert result.get("error_code") == "AUTH_REQUIRED"
    assert not kv_store.list_prefix("")


@pytest.mark.asyncio
async def test_registered_tool_rejects_path_traversal() -> None:
    """Path-traversal webhook_id is refused by the leaf guard before the store is touched."""
    mcp = FastMCP(name="test-webhook-tools-traversal")
    register_webhook_tools(mcp, rbac_manager=_fake_rbac_manager())
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(
        webhook_id="../../etc/passwd",
        user_id="viewer-1",
        token="a.b.c",
    )

    # The leaf returns None when the path-traversal guard rejects the id.
    assert result is None
    assert not kv_store.list_prefix("")


# NOTE: A FastAPI mount integration test (``mount_durable_webhooks`` + TestClient +
# POST /durable-webhooks/webhook) is exercised by
# ``tests/unit/test_webhooks_mount.py`` (separate fixture using the same
# receiver substrate-patching pattern). The 5 tests above cover the
# MCP tool surface; the mount coverage lives in the sibling file.
