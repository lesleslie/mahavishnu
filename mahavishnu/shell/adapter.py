"""Mahavishnu admin shell adapter."""

import asyncio
import logging

from oneiric.shell import AdminShell, ShellConfig

from ..core.app import MahavishnuApp
from ..core.workflow_state import WorkflowStatus
from .formatters import LogFormatter, RepoFormatter, WorkflowFormatter
from .magics import MahavishnuMagics
from .shell_commands import errors, ps, sync, top

logger = logging.getLogger(__name__)


class MahavishnuShell(AdminShell):
    """Mahavishnu-specific admin shell.

    Extends the base AdminShell with Mahavishnu-specific namespace,
    formatters, helpers, and magic commands for workflow orchestration.

    Features:
    - ps(): Show all workflows
    - top(): Show active workflows with progress
    - errors(n=10): Show recent errors
    - sync(): Sync workflow state from backend
    - %repos: List repositories
    - %workflow <id>: Show workflow details
    """

    def __init__(self, app: MahavishnuApp, config: ShellConfig | None = None) -> None:
        """Initialize Mahavishnu shell.

        Args:
            app: MahavishnuApp instance
            config: Optional shell configuration
        """
        super().__init__(app, config)
        self._add_mahavishnu_namespace()
        self.workflow_formatter = WorkflowFormatter()
        self.log_formatter = LogFormatter()
        self.repo_formatter = RepoFormatter()

    def _add_mahavishnu_namespace(self) -> None:
        """Add Mahavishnu-specific objects to shell namespace."""
        self.namespace.update(
            {
                # Workflow status enum
                "WorkflowStatus": WorkflowStatus,
                # App class for introspection
                "MahavishnuApp": MahavishnuApp,
                # Convenience helper functions (wrapped for async execution)
                "ps": lambda: asyncio.run(ps(self.app)),
                "top": lambda: asyncio.run(top(self.app)),
                "errors": lambda limit=10: asyncio.run(errors(self.app, limit)),
                "sync": lambda: asyncio.run(sync(self.app)),
            }
        )

    def _register_magics(self) -> None:
        """Register Mahavishnu-specific magic commands."""
        super()._register_magics()
        magics = MahavishnuMagics(self.shell)
        magics.set_app(self.app)
        self.shell.register_magics(magics)

    def _get_banner(self) -> str:
        """Get Mahavishnu-specific banner."""
        adapters = ", ".join(self.app.adapters.keys())
        return f"""
Mahavishnu Admin Shell
{"=" * 60}
Active Adapters: {adapters}

Convenience Functions:
  ps()          - Show all workflows
  top()         - Show active workflows with progress
  errors(n=10)  - Show recent errors
  sync()        - Sync workflow state from backend

Magic Commands:
  %repos        - List repositories
  %workflow <id> - Show workflow details

Type 'help()' for Python help or %help_shell for shell commands
{"=" * 60}
"""
