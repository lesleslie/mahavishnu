# tests/unit/test_websocket_tools.py
"""Unit tests for websocket_tools MCP module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp import websocket_tools as ws_module


# ---------------------------------------------------------------------------
# Fake WebSocket server
# ---------------------------------------------------------------------------


class _FakeWebSocketServer:
    """Minimal fake matching MahavishnuWebSocketServer interface."""

    def __init__(self) -> None:
        self.is_running = True
        self.host = "127.0.0.1"
        self.port = 8690
        self.max_connections = 100
        self.message_rate_limit = 1000
        self.connections: dict[str, Any] = {"conn-1": MagicMock(), "conn-2": MagicMock()}
        self.connection_rooms: dict[str, set[str]] = {
            "room-alpha": {"conn-1"},
            "room-beta": {"conn-1", "conn-2"},
        }

    def _get_timestamp(self) -> str:
        return "2026-01-01T00:00:00Z"

    async def broadcast_to_room(self, room: str, event: Any) -> None:
        pass  # no-op in fake


# ---------------------------------------------------------------------------
# Fake FastMCP (server)
# ---------------------------------------------------------------------------


class _FakeServer:
    """Fake FastMCP server that records @server.tool() decorated callables."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


# ---------------------------------------------------------------------------
# Helper: build a fake MCP + register with given websocket_server
# ---------------------------------------------------------------------------


def _register(ws_server=None) -> dict[str, Any]:
    fake_server = _FakeServer()
    ws_module.register_websocket_tools(fake_server, ws_server)
    return fake_server.tools


async def _call_tool(tools: dict[str, Any], name: str, *args, **kwargs) -> Any:
    """Call a tool by name, awaiting the result if it is a coroutine."""
    result = tools[name](*args, **kwargs)
    if hasattr(result, "__await__"):
        return await result
    return result


# ---------------------------------------------------------------------------
# websocket_health_check
# ---------------------------------------------------------------------------

def test_health_check_not_initialized() -> None:
    """When websocket_server is None, should return 'not_initialized'."""
    tools = _register(ws_server=None)
    result = asyncio.run(_call_tool(tools, "websocket_health_check"))
    assert result["status"] == "not_initialized"
    assert result["port"] == 8690


def test_health_check_not_running() -> None:
    """When server exists but is not running, should return 'stopped'."""
    fake_ws = _FakeWebSocketServer()
    fake_ws.is_running = False
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_health_check"))
    assert result["status"] == "stopped"
    assert result["connections"] == 0
    assert result["rooms"] == 0


def test_health_check_healthy() -> None:
    """When server is running, should return healthy status with counts."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_health_check"))
    assert result["status"] == "healthy"
    assert result["connections"] == 2
    assert result["rooms"] == 2
    assert result["port"] == 8690
    assert result["max_connections"] == 100


def test_health_check_exception() -> None:
    """Exceptions should be caught and returned as error status."""
    class _BrokenServer:
        is_running = True
        host = "127.0.0.1"
        port = 8690

        @property
        def connections(self):
            raise RuntimeError("connections broken")

    tools = _register(ws_server=_BrokenServer())
    result = asyncio.run(_call_tool(tools, "websocket_health_check"))
    assert result["status"] == "error"
    assert "connections broken" in result["error"]


# ---------------------------------------------------------------------------
# websocket_get_status
# ---------------------------------------------------------------------------

def test_get_status_not_initialized() -> None:
    """None server should return not_running server status."""
    tools = _register(ws_server=None)
    result = asyncio.run(_call_tool(tools, "websocket_get_status"))
    assert result["server"]["status"] == "not_running"
    assert result["connections"] == []
    assert result["rooms"] == []


def test_get_status_not_running() -> None:
    """Stopped server should return not_running."""
    fake_ws = _FakeWebSocketServer()
    fake_ws.is_running = False
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_get_status"))
    assert result["server"]["status"] == "not_running"


def test_get_status_running() -> None:
    """Running server should return connection and room details."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_get_status"))

    assert result["server"]["status"] == "running"
    assert result["server"]["host"] == "127.0.0.1"
    assert result["server"]["port"] == 8690
    assert "conn-1" in result["connections"]
    assert "conn-2" in result["connections"]
    assert result["total_connections"] == 2
    assert "room-alpha" in result["rooms"]
    assert "room-beta" in result["rooms"]
    assert result["total_rooms"] == 2


def test_get_status_exception() -> None:
    """Exceptions should be caught and returned as error."""
    class _BrokenServer:
        is_running = True

        @property
        def connections(self):
            raise RuntimeError("get status broken")

    tools = _register(ws_server=_BrokenServer())
    result = asyncio.run(_call_tool(tools, "websocket_get_status"))
    assert result["server"]["status"] == "error"
    assert "get status broken" in result["error"]


# ---------------------------------------------------------------------------
# websocket_list_rooms
# ---------------------------------------------------------------------------

def test_list_rooms_not_initialized() -> None:
    """None server should return empty rooms."""
    tools = _register(ws_server=None)
    result = asyncio.run(_call_tool(tools, "websocket_list_rooms"))
    assert result["rooms"] == {}
    assert result["total_rooms"] == 0


def test_list_rooms_not_running() -> None:
    """Stopped server should return empty rooms."""
    fake_ws = _FakeWebSocketServer()
    fake_ws.is_running = False
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_list_rooms"))
    assert result["rooms"] == {}
    assert result["total_rooms"] == 0


def test_list_rooms_running() -> None:
    """Running server should return room list with subscriber counts."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_list_rooms"))

    assert result["total_rooms"] == 2
    assert result["rooms"]["room-alpha"]["subscribers"] == 1
    assert result["rooms"]["room-beta"]["subscribers"] == 2


def test_list_rooms_exception() -> None:
    """Exceptions should be caught."""
    class _BrokenServer:
        is_running = True

        @property
        def connection_rooms(self):
            raise RuntimeError("rooms broken")

    tools = _register(ws_server=_BrokenServer())
    result = asyncio.run(_call_tool(tools, "websocket_list_rooms"))
    assert "error" in result
    assert result["total_rooms"] == 0


# ---------------------------------------------------------------------------
# websocket_broadcast_test_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_test_event_not_initialized() -> None:
    """None server should return error."""
    tools = _register(ws_server=None)
    result = await _call_tool(tools, "websocket_broadcast_test_event", "workflow.started", "room-alpha")
    assert result["status"] == "error"
    assert "not running" in result["error"]


@pytest.mark.asyncio
async def test_broadcast_test_event_not_running() -> None:
    """Stopped server should return error."""
    fake_ws = _FakeWebSocketServer()
    fake_ws.is_running = False
    tools = _register(ws_server=fake_ws)
    result = await _call_tool(tools, "websocket_broadcast_test_event", "workflow.started", "room-alpha")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_broadcast_test_event_success() -> None:
    """Successful broadcast should return broadcasted status with subscriber count."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)

    # room-alpha has 1 subscriber
    result = await _call_tool(
        tools, "websocket_broadcast_test_event", "workflow.started", "room-alpha", {"extra": "data"}
    )

    assert result["status"] == "broadcasted"
    assert result["event_type"] == "workflow.started"
    assert result["room"] == "room-alpha"
    assert result["subscribers"] == 1
    assert result["message"] == "Test event broadcast successfully"


@pytest.mark.asyncio
async def test_broadcast_test_event_custom_type() -> None:
    """Unknown event types should still work (passed through)."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)
    result = await _call_tool(tools, "websocket_broadcast_test_event", "arbitrary.event", "room-alpha")
    assert result["status"] == "broadcasted"
    assert result["event_type"] == "arbitrary.event"


@pytest.mark.asyncio
async def test_broadcast_test_event_empty_room() -> None:
    """Broadcasting to a room with 0 subscribers should still succeed."""
    fake_ws = _FakeWebSocketServer()
    # Add an empty room
    fake_ws.connection_rooms["empty-room"] = set()
    tools = _register(ws_server=fake_ws)

    result = await _call_tool(tools, "websocket_broadcast_test_event", "workflow.started", "empty-room")
    assert result["status"] == "broadcasted"
    assert result["subscribers"] == 0


@pytest.mark.asyncio
async def test_broadcast_test_event_exception() -> None:
    """Exceptions should be caught and returned as error."""
    class _BrokenServer(_FakeWebSocketServer):
        async def broadcast_to_room(self, room, event):
            raise RuntimeError("broadcast failed")

    tools = _register(ws_server=_BrokenServer())
    result = await _call_tool(tools, "websocket_broadcast_test_event", "workflow.started", "room-alpha")
    assert result["status"] == "error"
    assert "broadcast failed" in result["error"]


# ---------------------------------------------------------------------------
# websocket_get_metrics
# ---------------------------------------------------------------------------

def test_get_metrics_not_initialized() -> None:
    """None server should return not-running metrics."""
    tools = _register(ws_server=None)
    result = asyncio.run(_call_tool(tools, "websocket_get_metrics"))
    assert result["uptime_seconds"] == 0
    assert result["total_broadcasts"] == 0
    assert "not running" in result["message"]


def test_get_metrics_not_running() -> None:
    """Stopped server should return not-running metrics."""
    fake_ws = _FakeWebSocketServer()
    fake_ws.is_running = False
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_get_metrics"))
    assert result["uptime_seconds"] == 0
    assert "not running" in result["message"]


def test_get_metrics_running() -> None:
    """Running server should return current connection counts as metrics."""
    fake_ws = _FakeWebSocketServer()
    tools = _register(ws_server=fake_ws)
    result = asyncio.run(_call_tool(tools, "websocket_get_metrics"))

    # peak/current connections reflect current connection dict
    assert result["peak_connections"] == 2
    assert result["current_connections"] == 2
    assert "uptime_seconds" in result


def test_get_metrics_exception() -> None:
    """Exceptions should be caught."""
    class _BrokenServer:
        is_running = True

        @property
        def connections(self):
            raise RuntimeError("metrics broken")

    tools = _register(ws_server=_BrokenServer())
    result = asyncio.run(_call_tool(tools, "websocket_get_metrics"))
    assert "error" in result


# ---------------------------------------------------------------------------
# All 5 tools registered
# ---------------------------------------------------------------------------

def test_all_five_tools_registered() -> None:
    """All 5 tools should be registered: health_check, get_status, list_rooms, broadcast_test_event, get_metrics."""
    tools = _register(ws_server=_FakeWebSocketServer())
    assert set(tools.keys()) == {
        "websocket_health_check",
        "websocket_get_status",
        "websocket_list_rooms",
        "websocket_broadcast_test_event",
        "websocket_get_metrics",
    }