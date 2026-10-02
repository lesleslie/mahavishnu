from __future__ import annotations

import asyncio
import logging
import sys
from types import ModuleType, SimpleNamespace
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
        app=SimpleNamespace(config=SimpleNamespace(pools_enabled=False)),
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
async def test_start_server_spawns_task_orphan_sweeper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 10 — start_server must construct a TaskOrphanSweeper, init it,
    and schedule its run_forever() loop on the event loop.

    The fake sweeper captures the kwargs it was constructed with so the
    test can assert (a) ``session_buddy_client=get_session_buddy_client()``
    was passed (per the inline stub) and (b) ``init()`` then
    ``run_forever()`` were each called once. The server-side attributes
    (``_task_orphan_sweeper`` and ``_task_orphan_sweeper_task``) are
    stashed on the server so ``stop_server`` can find them later.
    """
    class DummyProfile:
        value = "full"

    profile = DummyProfile()
    run_http_async = AsyncMock()
    fake_sweeper_instance = SimpleNamespace(
        init=AsyncMock(),
        cleanup=AsyncMock(),
        health=AsyncMock(return_value=True),
        run_forever=AsyncMock(side_effect=lambda: asyncio.sleep(0)),
    )
    created_kwargs: dict[str, object] = {}

    def fake_sweeper_factory(**kwargs: object) -> object:
        created_kwargs.update(kwargs)
        return fake_sweeper_instance

    server = SimpleNamespace(
        _active_profile=None,
        _update_registered_tool_metrics=Mock(),
        server=SimpleNamespace(run_http_async=run_http_async),
        app=SimpleNamespace(config=SimpleNamespace(pools_enabled=False)),
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
    monkeypatch.setattr(
        "mahavishnu.mcp.lifecycle.TaskOrphanSweeper",
        fake_sweeper_factory,
    )

    await start_server(server, host="127.0.0.1", port=3000)

    # The sweeper factory was called with the inline stub's None return.
    assert created_kwargs == {"session_buddy_client": None}
    # init() awaited once before the loop started; run_forever() is
    # the body of the scheduled background task (we can't directly
    # observe the call from here, but the task attribute below proves
    # the create_task path completed).
    fake_sweeper_instance.init.assert_awaited_once()
    assert server._task_orphan_sweeper is fake_sweeper_instance
    assert isinstance(server._task_orphan_sweeper_task, asyncio.Task)
    # Cancel the background task so it does not leak past the test.
    server._task_orphan_sweeper_task.cancel()
    try:
        await server._task_orphan_sweeper_task
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001 - cleanup
        # The task may have been mocked to raise (see
        # ``test_stop_server_handles_sweeper_task_failure``). Log so
        # the failure mode is observable but do not re-raise: the
        # test's signal is whether start_server wired the sweeper
        # attribute, not the task's own body.
        logging.getLogger(__name__).debug("sweeper task raised on cancel: %s", exc)


@pytest.mark.asyncio
async def test_stop_server_cancels_task_orphan_sweeper() -> None:
    """Task 10 — stop_server must cancel the sweeper background task
    (catching CancelledError) and await ``sweeper.cleanup()``.

    The test uses a real ``asyncio.Task`` so the cancellation path is
    exercised end-to-end. ``run_forever`` is patched to a sleep loop
    that respects cancellation.
    """

    async def run_forever_loop() -> None:
        while True:
            await asyncio.sleep(60)

    sweeper = SimpleNamespace(
        cleanup=AsyncMock(),
        health=AsyncMock(return_value=True),
    )
    sweeper_task = asyncio.create_task(run_forever_loop(), name="task_orphan_sweeper")
    server = SimpleNamespace(
        _task_orphan_sweeper=sweeper,
        _task_orphan_sweeper_task=sweeper_task,
    )

    await stop_server(server)

    assert sweeper_task.cancelled() is True
    sweeper.cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_server_noops_when_sweeper_absent() -> None:
    """When start_server never ran (or failed before the spawn point),
    stop_server must not blow up trying to cancel a non-existent task.
    """
    server = SimpleNamespace()  # no _task_orphan_sweeper / no _task_orphan_sweeper_task

    # Should not raise.
    await stop_server(server)


@pytest.mark.asyncio
async def test_stop_server_handles_sweeper_task_failure() -> None:
    """If awaiting the cancelled task raises something other than
    CancelledError, stop_server must log a warning and continue rather
    than aborting the rest of the teardown.
    """

    async def run_forever_loop() -> None:
        raise RuntimeError("simulated non-cancel error")

    sweeper = SimpleNamespace(
        cleanup=AsyncMock(),
        health=AsyncMock(return_value=True),
    )
    sweeper_task = asyncio.create_task(run_forever_loop(), name="task_orphan_sweeper")
    server = SimpleNamespace(
        _task_orphan_sweeper=sweeper,
        _task_orphan_sweeper_task=sweeper_task,
    )

    # Should not raise even though the task body raised.
    await stop_server(server)

    sweeper.cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_server_handles_client_stop() -> None:
    client = SimpleNamespace(_client=SimpleNamespace(stop=AsyncMock()))
    server = SimpleNamespace(mcp_client=client)

    await stop_server(server)

    client._client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_server_handles_client_stop_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _boom() -> None:
        raise RuntimeError("boom")

    client = SimpleNamespace(_client=SimpleNamespace(stop=_boom))
    server = SimpleNamespace(mcp_client=client)

    with caplog.at_level(logging.WARNING):
        await stop_server(server)

    assert "Error stopping embedded MCP client" in caplog.text


@pytest.mark.asyncio
async def test_register_worktree_tools_skips_without_coordinator() -> None:
    server = SimpleNamespace(app=SimpleNamespace(worktree_coordinator=None))

    await register_worktree_tools(server)


@pytest.mark.asyncio
async def test_register_worktree_tools_registers_with_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = ModuleType("mahavishnu.mcp.tools.worktree_tools")
    fake_register = Mock()
    fake_module.register_worktree_tools = fake_register
    monkeypatch.setitem(sys.modules, "mahavishnu.mcp.tools.worktree_tools", fake_module)

    server = SimpleNamespace(
        app=SimpleNamespace(worktree_coordinator=object()),
        server=SimpleNamespace(),
    )

    await register_worktree_tools(server)

    fake_register.assert_called_once_with(server.server, server.app)
