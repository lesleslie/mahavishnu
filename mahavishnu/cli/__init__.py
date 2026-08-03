"""CLI subpackage for Mahavishnu.

This package contains modular CLI components:
- help_cli: Comprehensive help system with command reference
- backup_cli: Backup and recovery commands
- monitoring_cli: Monitoring and health check commands
- production_cli: Production readiness commands
- team_cli: Goal-driven team management commands
- events: Event schema validation and export commands
- docs_cli: Ecosystem docs audit commands

Note: The main CLI app is defined in mahavishnu/_main_cli.py (separate module).
"""

from .docs_cli import add_docs_commands
from .events import add_events_commands
from .help_cli import help_group, show_all_help, show_command_help, show_general_help
from .team_cli import (
    add_team_commands,
    create_team,
    list_skills,
    list_teams,
    parse_goal_cmd,
)
from .team_cli import (
    app as team_app,
)

__all__ = [
    "MahavishnuApp",
    "MultiAuthHandler",
    # Docs audit CLI
    "add_docs_commands",
    # Events CLI
    "add_events_commands",
    "add_team_commands",
    "app",
    "create_team",
    "help_group",
    "list_skills",
    "list_teams",
    "parse_goal_cmd",
    "show_all_help",
    "show_command_help",
    "show_general_help",
    # Team CLI
    "team_app",
]


def __getattr__(name: str):
    """Lazily expose the main CLI app and related public objects."""
    if name == "app":
        from .._main_cli import app

        return app
    if name == "MahavishnuApp":
        from ..core.app import MahavishnuApp

        return MahavishnuApp
    if name == "MultiAuthHandler":
        from ..core.subscription_auth import MultiAuthHandler

        return MultiAuthHandler
    raise AttributeError(name)
