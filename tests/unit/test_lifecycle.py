from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.lifecycle import (
    initialize_worktree_coordinator,
    start_learning_pipeline,
    start_poller,
    stop_learning_pipeline,
    stop_poller,
)


@pytest.mark.asyncio
async def test_start_poller_starts_inactive_poller() -> None:
    poller = SimpleNamespace(_running=False, start=AsyncMock())
    app = SimpleNamespace(session_buddy_poller=poller)

    await start_poller(app)

    poller.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_poller_clears_metrics_and_stops_running_poller() -> None:
    poller = SimpleNamespace(_running=True, stop=AsyncMock())
    app = SimpleNamespace(session_buddy_poller=poller, routing_metrics_server=object())

    await stop_poller(app)

    assert app.routing_metrics_server is None
    poller.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_learning_pipeline_lifecycle() -> None:
    pipeline = SimpleNamespace(is_running=False, start=AsyncMock(), stop=AsyncMock())
    app = SimpleNamespace(_learning_pipeline=pipeline)

    await start_learning_pipeline(app)
    await stop_learning_pipeline(app)

    pipeline.start.assert_awaited_once()
    pipeline.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialize_worktree_coordinator_creates_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_manager = SimpleNamespace(load=AsyncMock())
    coordination_manager = object()

    class DummyCoordinator:
        def __init__(self, repo_manager: object, coordination_manager: object) -> None:
            self.repo_manager = repo_manager
            self.coordination_manager = coordination_manager

    monkeypatch.setattr(
        "mahavishnu.core.worktree_coordination.WorktreeCoordinator",
        DummyCoordinator,
        raising=True,
    )
    app = SimpleNamespace(
        worktree_coordinator=None,
        repository_manager=repo_manager,
        coordination_manager=coordination_manager,
    )

    await initialize_worktree_coordinator(app)

    repo_manager.load.assert_awaited_once()
    assert isinstance(app.worktree_coordinator, DummyCoordinator)
    assert app.worktree_coordinator.repo_manager is repo_manager
    assert app.worktree_coordinator.coordination_manager is coordination_manager
