from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mahavishnu.mcp.lifecycle import register_worktree_tools, start_server, stop_server


@pytest.mark.asyncio
async def test_start_server_uses_profile_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyProfile:
        value = "full"

    profile = DummyProfile()
    run_http_async = AsyncMock()
    server = SimpleNamespace(
        _active_profile=None,
        _update_registered_tool_metrics=Mock(),
        server=SimpleNamespace(run_http_async=run_http_async),
    )
    monkeypatch.setattr(
        "mahavishnu.mcp.lifecycle._register_profile_tools_helper",
        AsyncMock(),
        raising=True,
    )
    monkeypatch.setattr(
        "mahavishnu.mcp.lifecycle.get_active_profile",
        Mock(return_value=profile),
    )
    monkeypatch.setattr(
        "mahavishnu.mcp.lifecycle.PROFILE_REGISTRATIONS",
        {profile: ["alpha"]},
    )

    await start_server(server, host="127.0.0.1", port=3000)

    server._update_registered_tool_metrics.assert_called_once()
    run_http_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_server_handles_client_stop() -> None:
    client = SimpleNamespace(_client=SimpleNamespace(stop=AsyncMock()))
    server = SimpleNamespace(mcp_client=client)

    await stop_server(server)

    client._client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_worktree_tools_skips_without_coordinator() -> None:
    server = SimpleNamespace(app=SimpleNamespace(worktree_coordinator=None))

    await register_worktree_tools(server)
