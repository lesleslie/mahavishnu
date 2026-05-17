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
async def test_start_poller_noops_for_running_or_missing_poller() -> None:
    running_poller = SimpleNamespace(_running=True, start=AsyncMock())
    running_app = SimpleNamespace(session_buddy_poller=running_poller)
    missing_app = SimpleNamespace(session_buddy_poller=None)

    await start_poller(running_app)
    await start_poller(missing_app)

    running_poller.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_poller_clears_metrics_and_stops_running_poller() -> None:
    poller = SimpleNamespace(_running=True, stop=AsyncMock())
    app = SimpleNamespace(session_buddy_poller=poller, routing_metrics_server=object())

    await stop_poller(app)

    assert app.routing_metrics_server is None
    poller.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_poller_noops_when_nothing_to_stop() -> None:
    poller = SimpleNamespace(_running=False, stop=AsyncMock())
    app = SimpleNamespace(session_buddy_poller=poller, routing_metrics_server=None)

    await stop_poller(app)

    assert app.routing_metrics_server is None
    poller.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_learning_pipeline_lifecycle() -> None:
    pipeline = SimpleNamespace(is_running=False, start=AsyncMock(), stop=AsyncMock())
    app = SimpleNamespace(_learning_pipeline=pipeline)

    await start_learning_pipeline(app)
    await stop_learning_pipeline(app)

    pipeline.start.assert_awaited_once()
    pipeline.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_learning_pipeline_noops_for_running_or_missing_pipeline() -> None:
    running_pipeline = SimpleNamespace(is_running=True, start=AsyncMock(), stop=AsyncMock())
    running_app = SimpleNamespace(_learning_pipeline=running_pipeline)
    missing_app = SimpleNamespace(_learning_pipeline=None)

    await start_learning_pipeline(running_app)
    await stop_learning_pipeline(missing_app)

    running_pipeline.start.assert_not_awaited()
    running_pipeline.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_initialize_worktree_coordinator_exception_is_swallowed() -> None:
    """Exception during init is caught and logged — worktree_coordinator stays None (lines 57-58)."""
    repo_manager = SimpleNamespace(load=AsyncMock(side_effect=RuntimeError("load failed")))
    app = SimpleNamespace(
        worktree_coordinator=None,
        repository_manager=repo_manager,
        coordination_manager=None,
    )

    await initialize_worktree_coordinator(app)
    assert app.worktree_coordinator is None


@pytest.mark.asyncio
async def test_initialize_worktree_coordinator_noops_when_already_initialized() -> None:
    repo_manager = SimpleNamespace(load=AsyncMock())
    app = SimpleNamespace(
        worktree_coordinator=object(),
        repository_manager=repo_manager,
        coordination_manager=object(),
    )

    await initialize_worktree_coordinator(app)

    repo_manager.load.assert_not_awaited()
    assert app.worktree_coordinator is not None


@pytest.mark.asyncio
async def test_initialize_worktree_coordinator_noops_without_repository_manager() -> None:
    app = SimpleNamespace(worktree_coordinator=None, coordination_manager=object())

    await initialize_worktree_coordinator(app)

    assert app.worktree_coordinator is None


@pytest.mark.asyncio
async def test_initialize_worktree_coordinator_creates_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
