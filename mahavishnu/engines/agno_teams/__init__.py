"""Agno multi-agent team orchestration.

This module provides team management capabilities for Agno agents,
enabling coordinated multi-agent workflows with different collaboration modes.

Key Components:
- AgentTeamManager: Creates and manages agent teams
- TeamConfig: Configuration model for team definitions
- MemberConfig: Configuration model for team members

Team Modes:
- coordinate: Leader distributes tasks to specialist members
- route: Single agent selected based on task type
- broadcast: All agents work on the same task in parallel
"""

from .config import MemberConfig, TeamConfig, TeamMode
from .manager import AgentTeamManager

__all__ = [
    "AgentTeamManager",
    "MemberConfig",
    "TeamConfig",
    "TeamMode",
]
