"""Mahavishnu admin shell with workflow-specific formatters and helpers.

This module extends the Oneiric AdminShell with Mahavishnu-specific functionality
for workflow orchestration, repository management, and log viewing.

Example:
    >>> from mahavishnu.shell import MahavishnuShell
    >>> from mahavishnu.core.app import MahavishnuApp
    >>> app = MahavishnuApp()
    >>> shell = MahavishnuShell(app)
    >>> shell.start()
"""

from .adapter import MahavishnuShell
from .formatters import WorkflowFormatter, LogFormatter, RepoFormatter

__all__ = ["MahavishnuShell", "WorkflowFormatter", "LogFormatter", "RepoFormatter"]
