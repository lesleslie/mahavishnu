"""CLI subpackage for Mahavishnu.

This package contains modular CLI components:
- help_cli: Comprehensive help system with command reference
- backup_cli: Backup and recovery commands
- monitoring_cli: Monitoring and health check commands
- production_cli: Production readiness commands
- team_cli: Goal-driven team management commands

Note: The main CLI app is defined in mahavishnu/_main_cli.py (separate module).
"""

from .help_cli import help_group, show_general_help, show_command_help, show_all_help
from .team_cli import (
    app as team_app,
    add_team_commands,
    create_team,
    parse_goal_cmd,
    list_skills,
    list_teams,
)

__all__ = [
    "help_group",
    "show_general_help",
    "show_command_help",
    "show_all_help",
    # Team CLI
    "team_app",
    "add_team_commands",
    "create_team",
    "parse_goal_cmd",
    "list_skills",
    "list_teams",
]
