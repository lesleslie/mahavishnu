"""Mahavishnu-specific formatters for admin shell."""

import logging
from typing import Any

try:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from oneiric.shell.formatters import BaseLogFormatter, BaseTableFormatter

from ..core.workflow_state import WorkflowStatus

logger = logging.getLogger(__name__)


class WorkflowFormatter(BaseTableFormatter):
    """Format workflow state for display.

    Provides specialized formatting for workflow data including
    status indicators, progress bars, and detailed views.
    """

    def format_workflows(self, workflows: list[dict[str, Any]], show_details: bool = False) -> None:
        """Display workflows in a table.

        Args:
            workflows: List of workflow dictionaries
            show_details: Whether to show additional detail columns
        """
        if not workflows:
            print("No workflows to display")
            return

        if not RICH_AVAILABLE or not self.console:
            self._format_workflows_fallback(workflows, show_details)
            return

        table = Table(title="Workflows")
        table.add_column("ID", style="cyan", width=20)
        table.add_column("Status", width=12)
        table.add_column("Progress", width=10)
        table.add_column("Adapter", width=12)
        table.add_column("Created", width=20)

        if show_details:
            table.add_column("Details", width=40)

        for wf in workflows:
            status_key = wf.get("status")
            status_style = (
                {
                    WorkflowStatus.RUNNING: "yellow",
                    WorkflowStatus.COMPLETED: "green",
                    WorkflowStatus.FAILED: "red",
                    WorkflowStatus.PENDING: "blue",
                }.get(status_key, "")
                if status_key
                else ""
            )

            row = [
                wf.get("id", "")[:20],
                f"[{status_style}]{wf.get('status', 'unknown')}[/{status_style}]",
                f"{wf.get('progress', 0)}%",
                wf.get("adapter", "unknown"),
                wf.get("created_at", "")[:19],
            ]

            if show_details:
                details = f"Repos: {len(wf.get('repos', []))}"
                if wf.get("errors"):
                    details += f" | Errors: {len(wf['errors'])}"
                row.append(details)

            table.add_row(*row)

        self.console.print(table)

    def _format_workflows_fallback(
        self, workflows: list[dict[str, Any]], show_details: bool
    ) -> None:
        """Fallback workflow formatting without Rich.

        Args:
            workflows: List of workflow dictionaries
            show_details: Whether to show details
        """
        for wf in workflows:
            print(f"{wf.get('id')} - {wf.get('status')} - {wf.get('progress', 0)}%")
            if show_details:
                print(f"  Adapter: {wf.get('adapter')}")
                print(f"  Repos: {len(wf.get('repos', []))}")

    def format_workflow_detail(self, workflow: dict[str, Any]) -> None:
        """Display detailed workflow information.

        Args:
            workflow: Workflow dictionary with full details
        """
        if not RICH_AVAILABLE or not self.console:
            self._format_workflow_detail_fallback(workflow)
            return

        details = Text()
        details.append(f"ID: {workflow.get('id')}\n", style="cyan")
        details.append(f"Status: {workflow.get('status')}\n", style="magenta")
        details.append(f"Progress: {workflow.get('progress', 0)}%\n", style="yellow")
        details.append(f"Adapter: {workflow.get('adapter')}\n")

        if workflow.get("repos"):
            details.append(f"\nRepos ({len(workflow['repos'])}):\n", style="bold")
            for repo in workflow.get("repos", [])[:10]:
                details.append(f"  - {repo}\n")

        if workflow.get("errors"):
            details.append(f"\nErrors ({len(workflow['errors'])}):\n", style="bold red")
            for error in workflow.get("errors", [])[:5]:
                details.append(f"  - {error.get('message', 'Unknown error')}\n", style="red")

        panel = Panel(details, title="Workflow Details", border_style="blue")
        self.console.print(panel)

    def _format_workflow_detail_fallback(self, workflow: dict[str, Any]) -> None:
        """Fallback detail formatting without Rich.

        Args:
            workflow: Workflow dictionary
        """
        print(f"Workflow: {workflow.get('id')}")
        print(f"Status: {workflow.get('status')}")
        print(f"Progress: {workflow.get('progress', 0)}%")
        print(f"Adapter: {workflow.get('adapter')}")


class LogFormatter(BaseLogFormatter):
    """Format logs from OpenSearch for display.

    Extends base log formatter with workflow-specific filtering
    and enhanced display options.
    """

    def format_logs(
        self,
        logs: list[dict[str, Any]],
        level: str | None = None,
        workflow_id: str | None = None,
        tail: int = 50,
    ) -> None:
        """Display log entries with filtering.

        Args:
            logs: List of log entry dictionaries
            level: Optional log level filter
            workflow_id: Optional workflow ID filter
            tail: Number of most recent lines to display
        """
        if not logs:
            print("No logs to display")
            return

        # Filter by level
        if level:
            logs = [log for log in logs if log.get("level") == level.upper()]

        # Filter by workflow
        if workflow_id:
            logs = [log for log in logs if log.get("workflow_id") == workflow_id]

        # Get last N lines
        logs = logs[-tail:]

        if RICH_AVAILABLE and self.console:
            self._format_logs_rich(logs)
        else:
            self._format_logs_fallback(logs)

    def _format_logs_rich(self, logs: list[dict[str, Any]]) -> None:
        """Format logs with Rich colors.

        Args:
            logs: List of log entries
        """
        for log in logs:
            timestamp = log.get("timestamp", "")[:19]
            level_str = log.get("level", "INFO")
            message = log.get("message", "")
            style = {
                "ERROR": "bold red",
                "WARNING": "bold yellow",
                "INFO": "blue",
            }.get(level_str, "")

            self.console.print(f"[{timestamp}] [{level_str}] {message}", style=style)

    def _format_logs_fallback(self, logs: list[dict[str, Any]]) -> None:
        """Format logs without Rich.

        Args:
            logs: List of log entries
        """
        for log in logs:
            timestamp = log.get("timestamp", "")[:19]
            level_str = log.get("level", "INFO")
            message = log.get("message", "")
            print(f"{timestamp} [{level_str}] {message}")


class RepoFormatter(BaseTableFormatter):
    """Format repository information for display.

    Provides table-based repository listing with optional
    tag and metadata display.
    """

    def format_repos(self, repos: list[dict[str, Any]], show_tags: bool = False) -> None:
        """Display repositories in a table.

        Args:
            repos: List of repository dictionaries
            show_tags: Whether to show tags column
        """
        if not repos:
            print("No repositories to display")
            return

        if not RICH_AVAILABLE or not self.console:
            self._format_repos_fallback(repos, show_tags)
            return

        table = Table(title="Repositories")
        table.add_column("Path", style="cyan", width=50)
        table.add_column("Description", width=40)

        if show_tags:
            table.add_column("Tags", width=20)

        for repo in repos:
            row = [repo.get("path", ""), repo.get("description", "")[:40]]
            if show_tags:
                tags = ", ".join(repo.get("tags", []))
                row.append(tags[:20])
            table.add_row(*row)

        self.console.print(table)

    def _format_repos_fallback(self, repos: list[dict[str, Any]], show_tags: bool) -> None:
        """Fallback repo formatting without Rich.

        Args:
            repos: List of repository dictionaries
            show_tags: Whether to show tags
        """
        for repo in repos:
            path = repo.get("path", "")
            desc = repo.get("description", "")
            print(f"{path} - {desc}")
            if show_tags:
                tags = ", ".join(repo.get("tags", []))
                print(f"  Tags: {tags}")
