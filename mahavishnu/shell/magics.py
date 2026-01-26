"""Mahavishnu-specific IPython magic commands."""

import asyncio
import logging
from typing import Any

from IPython.core.magic import Magics, magics_class, line_magic

from ..core.app import MahavishnuApp
from .formatters import RepoFormatter, WorkflowFormatter

logger = logging.getLogger(__name__)


@magics_class
class MahavishnuMagics(Magics):
    """Mahavishnu-specific magic commands.

    Provides convenience commands for repository and workflow inspection.
    """

    def __init__(self, shell: Any):
        """Initialize magics.

        Args:
            shell: IPython shell instance
        """
        super().__init__(shell)
        self.app = None
        self.repo_formatter = RepoFormatter()
        self.workflow_formatter = WorkflowFormatter()

    def set_app(self, app: MahavishnuApp) -> None:
        """Set application reference.

        Args:
            app: MahavishnuApp instance
        """
        self.app = app

    @line_magic
    def repos(self, line: str) -> None:
        """List repositories. Usage: %repos [tag]

        Args:
            line: Command arguments (optional tag filter)
        """
        if not self.app:
            print("No application configured")
            return

        tag = line.strip() if line.strip() else None

        # Get repos from app
        repos = self.app.get_all_repos() if hasattr(self.app, "get_all_repos") else []

        # Filter by tag if specified
        if tag:
            repos = [r for r in repos if tag in r.get("tags", [])]

        self.repo_formatter.format_repos(repos, show_tags=True)

    @line_magic
    def workflow(self, line: str) -> None:
        """Show workflow details. Usage: %workflow <id>

        Args:
            line: Command arguments (workflow ID)
        """
        if not self.app:
            print("No application configured")
            return

        workflow_id = line.strip()
        if not workflow_id:
            print("Usage: %workflow <id>")
            return

        try:
            workflow = asyncio.run(self.app.workflow_state_manager.get(workflow_id))
            if not workflow:
                print(f"Workflow not found: {workflow_id}")
                return
            self.workflow_formatter.format_workflow_detail(workflow)
        except Exception as e:
            print(f"Error fetching workflow: {e}")
