"""Mahavishnu integrations with external services.

This package contains integration modules for connecting Mahavishnu
with external services like Session-Buddy, Akosha, and other MCP servers.
"""

from mahavishnu.integrations.session_buddy_poller import SessionBuddyPoller

__all__ = ["SessionBuddyPoller"]
