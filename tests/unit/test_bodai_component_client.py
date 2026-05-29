"""Tests for the BodaiComponentMCPClient transport wrapper."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.bodai_component_client import BodaiComponentMCPClient


class _FakeTransportContext:
    def __init__(self):
        self.entered = False
        self.exited = False
        self.http_client = None
        self.terminate_on_close = None

    async def __aenter__(self):
        self.entered = True
        return ("reader", "writer", None)

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True


class _FakeSession:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.initialized = False
        self.session_id = "session-123"
        self.call_tool = AsyncMock(return_value={"ok": True})

    async def initialize(self):
        self.initialized = True


def _install_fake_mcp_modules(monkeypatch, transport_context, session_cls):
    streamable_http_mod = ModuleType("mcp.client.streamable_http")

    def streamable_http_client(base_url, http_client=None, terminate_on_close=True):
        transport_context.http_client = http_client
        transport_context.terminate_on_close = terminate_on_close
        transport_context.base_url = base_url
        return transport_context

    streamable_http_mod.streamable_http_client = streamable_http_client

    session_mod = ModuleType("mcp.client.session")
    session_mod.ClientSession = session_cls

    client_mod = ModuleType("mcp.client")
    client_mod.streamable_http = streamable_http_mod
    client_mod.session = session_mod

    mcp_mod = ModuleType("mcp")
    mcp_mod.client = client_mod

    monkeypatch.setitem(sys.modules, "mcp", mcp_mod)
    monkeypatch.setitem(sys.modules, "mcp.client", client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.session", session_mod)


class TestBodaiComponentMCPClientInit:
    def test_init_strips_trailing_slash(self):
        client = BodaiComponentMCPClient("http://localhost:8680/mcp/")

        assert client.base_url == "http://localhost:8680/mcp"
        assert client.tools_url == "http://localhost:8680/mcp"
        assert client.timeout == 30.0


@pytest.mark.asyncio
class TestBodaiComponentMCPClientSession:
    async def test_ensure_session_is_noop_when_session_exists(self, monkeypatch):
        transport_context = _FakeTransportContext()
        _install_fake_mcp_modules(monkeypatch, transport_context, _FakeSession)
        client = BodaiComponentMCPClient("http://localhost:8680/mcp")
        sentinel = object()
        client._session = sentinel

        await client._ensure_session()

        assert client._session is sentinel
        assert transport_context.entered is False


@pytest.mark.asyncio
class TestBodaiComponentMCPClientCalls:
    async def test_call_tool_uses_session_call(self, monkeypatch):
        client = BodaiComponentMCPClient("http://localhost:8680/mcp")
        client._ensure_session = AsyncMock()
        client._session = MagicMock()
        client._session.call_tool = AsyncMock(return_value={"result": "ok"})

        result = await client.call_tool("query_local_traces", {"task_class": "code_generation"})

        assert result == {"result": "ok"}
        client._ensure_session.assert_awaited_once()
        client._session.call_tool.assert_awaited_once_with(
            "query_local_traces", {"task_class": "code_generation"}
        )

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ([{"id": 1}], [{"id": 1}]),
            ({"traces": [{"id": 2}]}, [{"id": 2}]),
            ({"items": [{"id": 3}]}, [{"id": 3}]),
            ({"result": [{"id": 4}]}, [{"id": 4}]),
        ],
    )
    async def test_query_local_traces_accepts_known_shapes(self, payload, expected, monkeypatch):
        client = BodaiComponentMCPClient("http://localhost:8680/mcp")
        client.call_tool = AsyncMock(return_value=payload)

        result = await client.query_local_traces("code_generation", time_range_minutes=15)

        assert result == expected
        client.call_tool.assert_awaited_once_with(
            "query_local_traces",
            {"task_class": "code_generation", "time_range_minutes": 15},
        )

    async def test_query_local_traces_returns_empty_for_unexpected_shape(self, monkeypatch):
        client = BodaiComponentMCPClient("http://localhost:8680/mcp")
        client.call_tool = AsyncMock(return_value="unexpected")

        assert await client.query_local_traces("code_generation") == []
        assert client._transport_context is None
        assert client._session is None
