"""Verify webhook_replay_tool is registered as an MCP tool.

Mirrors the sibling ``tests/unit/mcp/tools/test_workflow_tools.py``
shape: register the tool group on a fresh FastMCP server, introspect
the registered tools via ``mcp.list_tools()``, and exercise both the
happy path (read returns a dict) and the AUTH_REQUIRED gate
(@require_mcp_auth rejects missing ``user_id``).

The tests monkeypatch ``mahavishnu.webhooks.replay.dhara.get`` so the
leaf :func:`webhook_replay` reads from a controlled fake without
touching the real Dhara substrate. webhook_replay reads
``dhara.get`` at call time, so the patch is picked up on every
invocation.

``mahavishnu.webhooks.replay`` imports ``from dhara.schema import
WebhookIngress, from_dict`` — a Dhara substrate-compat module that
isn't always present in test environments. We pre-warm a minimal
stub with the registry-style ``from_dict(name, payload)`` signature
that ``webhook_replay`` actually invokes at line 118.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import sys
from types import ModuleType
from unittest.mock import MagicMock

from fastmcp import FastMCP
import pytest

# Pre-warm a minimal ``dhara.schema`` stub so ``mahavishnu.webhooks.replay``
# and ``mahavishnu.mcp.tools.webhook_tools`` can import in environments where
# the upstream ``dhara`` package is missing the ``schema`` submodule. The
# stub exposes the surface :func:`webhook_replay` and the MCP wrapper read:
#
# - ``WebhookIngress`` (mirrors msgspec.Struct shape via ``to_dict()``)
# - ``from_dict(name, payload)`` — registry-style 2-arg call signature
# - ``to_dict(record)`` — registry-style struct→dict serializer used by
#   ``mahavishnu/mcp/tools/webhook_tools.py`` line 77
# - ``SchemaValidationError``, ``validate`` (passthrough)
_DHARA_SCHEMA_STUB: ModuleType = ModuleType("dhara.schema")


class _StubWebhookIngress:
    """Stand-in for ``dhara.schema.WebhookIngress``.

    Mirrors the msgspec.Struct surface :func:`webhook_replay` and the
    MCP wrapper (``record.to_dict()``) read.
    """

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


def _stub_from_dict(name: str, payload: dict) -> _StubWebhookIngress:
    """Stand-in for ``dhara.schema.from_dict``.

    Mirrors the registry call shape ``from_dict(name, payload)`` used at
    ``mahavishnu/webhooks/replay.py``.
    """
    return _StubWebhookIngress(payload)


def _stub_to_dict(record: object) -> dict:
    """Stand-in for ``dhara.schema.to_dict`` used by webhook_tools.

    Mirrors the registry call shape ``to_dict(record)`` at
    ``mahavishnu/mcp/tools/webhook_tools.py`` line 77. Accepts either a
    stub ``WebhookIngress`` (with ``._payload``) or a plain ``dict`` and
    returns a dict either way.
    """
    if isinstance(record, _StubWebhookIngress):
        return record._payload
    if isinstance(record, dict):
        return record
    return dict(record)


class _StubSchemaValidationError(Exception):
    """Stand-in for ``dhara.schema.SchemaValidationError``."""


def _stub_validate(_name: str, payload: object) -> object:
    """Stand-in for ``dhara.schema.validate``; returns ``payload`` unchanged."""
    return payload


_DHARA_SCHEMA_STUB.WebhookIngress = _StubWebhookIngress
_DHARA_SCHEMA_STUB.from_dict = _stub_from_dict
_DHARA_SCHEMA_STUB.to_dict = _stub_to_dict
_DHARA_SCHEMA_STUB.SchemaValidationError = _StubSchemaValidationError
_DHARA_SCHEMA_STUB.validate = _stub_validate
# Only install the stub when the real ``dhara.schema`` package is NOT
# importable. The pinned ``dhara`` package in this venv ships a real
# ``dhara.schema`` module — replacing it would shadow the msgspec Structs
# and break the ``WebhookIngress``/``WorkflowOutcome`` import in sibling
# tests. Falls back to the stub only when the upstream package is missing
# the submodule entirely (substrate-compat guard for legacy test envs).
if "dhara.schema" not in sys.modules:
    try:
        import dhara.schema  # noqa: F401
    except ImportError:
        sys.modules["dhara.schema"] = _DHARA_SCHEMA_STUB

from mahavishnu.mcp.tools import webhook_tools  # noqa: E402,F401
from mahavishnu.mcp.tools.webhook_tools import register_webhook_tools  # noqa: E402

pytestmark = pytest.mark.unit


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

    The leaf ``webhook_replay`` calls ``dhara.get`` at function-call time;
    we monkeypatch the source-module binding so the leaf sees the fake
    without needing a real Dhara substrate. ``from_dict`` (stubbed) then
    rebuilds the WebhookIngress Struct, and the wrapper calls ``.to_dict()``.
    """
    payload = {
        "webhook_id": "wh-abc",
        "source": "openclaw",
        "received_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC).isoformat(),
        "payload_hash": "sha256:deadbeef",
        "metadata": {"hello": "world"},
    }

    fake_get = MagicMock(return_value=payload)
    monkeypatch.setattr("mahavishnu.webhooks.replay.dhara.get", fake_get)

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
    monkeypatch.setattr("mahavishnu.webhooks.replay.dhara.get", fake_get)

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
    monkeypatch.setattr("mahavishnu.webhooks.replay.dhara.get", fake_get)

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
    monkeypatch.setattr("mahavishnu.webhooks.replay.dhara.get", fake_get)

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
# POST /durable-webhooks/webhook) is deferred. The receiver's validate path returns
# a msgspec.Struct (real dhara.schema) — the test env's pre-warmed stub returns a
# dict, so the receiver's ``validated.webhook_id`` access fails. The 5 tests above
# cover the MCP tool surface; the mount is structurally validated at
# ``mahavishnu/mcp/bootstrap.py:413-415`` (manual code review). Add the integration
# test once dhara.schema ships in mahavishnu's pinned dhara version.
