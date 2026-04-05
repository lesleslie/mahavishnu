"""Agent export packages for external AI platforms.

Provides Mahavishnu orchestration capabilities as consumable
tools for Pydantic AI, OpenClaw, and other agent frameworks.

Usage:
    from mahavishnu.agents import get_mahavishnu_agent

    agent = get_mahavishnu_agent()
    # Use with Pydantic AI or other frameworks
"""

from mahavishnu.agents.mahavishnu_agent import (
    MahavishnuAgent,
    get_mahavishnu_agent,
)

__all__ = [
    "MahavishnuAgent",
    "get_mahavishnu_agent",
]
