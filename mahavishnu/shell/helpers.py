"""Convenience helper functions for Mahavishnu admin shell."""

import asyncio
import logging
from typing import Any, Dict, List

from ..core.app import MahavishnuApp
from ..core.workflow_state import WorkflowStatus
from .formatters import WorkflowFormatter, LogFormatter

logger = logging.getLogger(__name__)


async def ps(app: MahavishnuApp) -> None:
    """Show all workflows.

    Args:
        app: MahavishnuApp instance
    """
    workflows = await app.workflow_state_manager.list_workflows(limit=100)
    formatter = WorkflowFormatter()
    formatter.format_workflows(workflows, show_details=False)


async def top(app: MahavishnuApp) -> None:
    """Show active workflows with progress (single snapshot).

    Args:
        app: MahavishnuApp instance
    """
    workflows = await app.workflow_state_manager.list_workflows(
        status=WorkflowStatus.RUNNING, limit=20
    )
    if not workflows:
        print("No active workflows")
        return
    formatter = WorkflowFormatter()
    formatter.format_workflows(workflows, show_details=True)


async def errors(app: MahavishnuApp, limit: int = 10) -> None:
    """Show recent errors.

    Args:
        app: MahavishnuApp instance
        limit: Maximum number of errors to show
    """
    workflows = await app.workflow_state_manager.list_workflows(limit=100)
    error_entries = []
    for wf in workflows:
        for error in wf.get("errors", []):
            error_entries.append(
                {
                    "workflow_id": wf.get("id"),
                    "timestamp": error.get("timestamp"),
                    "level": "ERROR",
                    "message": error.get("message", "Unknown error"),
                }
            )
    error_entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    error_entries = error_entries[:limit]
    if not error_entries:
        print("No errors found")
        return
    formatter = LogFormatter()
    formatter.format_logs(error_entries, tail=limit)


async def sync(app: MahavishnuApp) -> None:
    """Sync workflow state from backend (OpenSearch).

    Args:
        app: MahavishnuApp instance
    """
    print("Syncing workflow state from OpenSearch...")
    health = await app.opensearch_integration.health_check()
    print(f"OpenSearch status: {health.get('status', 'unknown')}")
    stats = await app.opensearch_integration.get_workflow_stats()
    print(f"Total workflows: {stats.get('total_workflows', 0)}")
    print("Sync complete")
