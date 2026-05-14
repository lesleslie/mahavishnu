"""Application lifecycle helpers for MahavishnuApp."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def start_poller(app: Any) -> None:
    """Start the Session-Buddy poller if configured."""
    if app.session_buddy_poller and not app.session_buddy_poller._running:
        await app.session_buddy_poller.start()
        logger.info("Session-Buddy poller started")


async def stop_poller(app: Any) -> None:
    """Stop the Session-Buddy poller and clear transitional metrics state."""
    if app.routing_metrics_server:
        logger.info("Routing metrics server reference cleared")
        app.routing_metrics_server = None

    if app.session_buddy_poller and app.session_buddy_poller._running:
        await app.session_buddy_poller.stop()
        logger.info("Session-Buddy poller stopped")


async def start_learning_pipeline(app: Any) -> None:
    """Start the learning pipeline if configured."""
    if app._learning_pipeline is not None and not app._learning_pipeline.is_running:
        await app._learning_pipeline.start()
        logger.info("Learning pipeline started")


async def stop_learning_pipeline(app: Any) -> None:
    """Stop the learning pipeline gracefully."""
    if app._learning_pipeline is not None:
        await app._learning_pipeline.stop()
        logger.info("Learning pipeline stopped")


async def initialize_worktree_coordinator(app: Any) -> None:
    """Initialize WorktreeCoordinator after the event loop is running."""
    if app.worktree_coordinator is None and hasattr(app, "repository_manager"):
        try:
            await app.repository_manager.load()

            from .worktree_coordination import WorktreeCoordinator

            app.worktree_coordinator = WorktreeCoordinator(
                repo_manager=app.repository_manager,
                coordination_manager=app.coordination_manager,
            )

            logger.info("WorktreeCoordinator initialized")
        except Exception as exc:
            logger.warning("Failed to initialize WorktreeCoordinator: %s", exc)
