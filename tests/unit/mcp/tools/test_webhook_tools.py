"""Verify webhook_replay_tool is registered as an MCP tool.

Mirrors the sibling ``tests/unit/mcp/tools/test_workflow_tools.py``
shape: register the tool group on a fresh FastMCP server, introspect
the registered tools via ``mcp.list_tools()``, and exercise both the
happy path (read returns a dict) and the AUTH_REQUIRED gate
(@require_mcp_auth rejects missing ``user_id``).

The tests patch ``mahavishnu.webhooks.replay.dhara_calltime`` so the
leaf :func:`webhook_replay` reads from a controlled fake without
touching the real Dhara substrate. webhook_replay reads
``dhara_calltime("get")`` at call time, so the patch is picked up on
every invocation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastmcp import FastMCP
import pytest

from mahavishnu.mcp.tools import webhook_tools  # noqa: F401  (intentional import for side effects)
from mahavishnu.mcp.tools.webhook_tools import register_webhook_tools
from mahavishnu.webhooks import replay as replay_module

pytestmark = pytest.mark.unit


def _patch_dhara_calltime(monkeypatch: pytest.MonkeyPatch, *, get: object | None) -> None:
    """Replace ``replay.dhara_calltime`` with a routing stub.

    Returns ``get`` when the leaf asks for ``"get"``; returns ``None``
    for everything else. Mirrors the pattern in
    ``tests/unit/channel/test_state_writer.py``.
    """
    def fake(name: str) -> object | None:
        return get if name == "get" else None

    monkeypatch.setattr(replay_module, "dhara_calltime", fake)


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
async def test_registered_tool_returns_dict_for_known_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: calling the registered MCP tool returns the persisted dict.

    The leaf ``webhook_replay`` calls ``dhara_calltime("get")`` at
    function-call time; we patch the source-module binding so the leaf
    sees the fake without needing a real Dhara substrate. The
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

    fake_get = MagicMock(return_value=payload)
    _patch_dhara_calltime(monkeypatch, get=fake_get)

    mcp = FastMCP(name="test-webhook-tools-roundtrip")
    register_webhook_tools(mcp)
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
async def test_registered_tool_returns_none_when_record_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: when the substrate returns ``None``, the tool returns ``None``."""
    fake_get = MagicMock(return_value=None)
    _patch_dhara_calltime(monkeypatch, get=fake_get)

    mcp = FastMCP(name="test-webhook-tools-missing")
    register_webhook_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(
        webhook_id="wh-missing",
        user_id="viewer-1",
        token="a.b.c",
    )

    assert result is None


@pytest.mark.asyncio
async def test_registered_tool_rejects_without_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """@require_mcp_auth wrapper rejects calls missing ``user_id``.

    Without ``user_id`` the wrapper returns the AUTH_REQUIRED error
    envelope before the underlying ``webhook_replay`` runs; the
    substrate is never touched. Mirrors the brief's
    "rejection without permission" contract.
    """
    fake_get = MagicMock()
    _patch_dhara_calltime(monkeypatch, get=fake_get)

    mcp = FastMCP(name="test-webhook-tools-auth")
    register_webhook_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(webhook_id="wh-1", token="a.b.c")

    assert isinstance(result, dict)
    assert result.get("status") == "error"
    assert result.get("error_code") == "AUTH_REQUIRED"
    fake_get.assert_not_called()


@pytest.mark.asyncio
async def test_registered_tool_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Path-traversal webhook_id is refused by the leaf guard before Dhara is touched."""
    fake_get = MagicMock()
    _patch_dhara_calltime(monkeypatch, get=fake_get)

    mcp = FastMCP(name="test-webhook-tools-traversal")
    register_webhook_tools(mcp)
    tool = next(t for t in await mcp.list_tools() if t.name == "webhook_replay_tool")

    result = await tool.fn(
        webhook_id="../../etc/passwd",
        user_id="viewer-1",
        token="a.b.c",
    )

    # The leaf returns None when the path-traversal guard rejects the id.
    assert result is None
    fake_get.assert_not_called()


# NOTE: A FastAPI mount integration test (``mount_durable_webhooks`` + TestClient +
# POST /durable-webhooks/webhook) is exercised by
# ``tests/unit/test_webhooks_mount.py`` (separate fixture using the same
# receiver.dhara_calltime patching pattern). The 5 tests above cover the
# MCP tool surface; the mount coverage lives in the sibling file.
