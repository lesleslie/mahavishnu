"""Session-Buddy MCP worktree provider (primary)."""

import logging
from pathlib import Path
from typing import Any

from .base import WorktreeProvider
from .errors import WorktreeCreationError, WorktreeRemovalError, WorktreeValidationError

logger = logging.getLogger(__name__)


class SessionBuddyWorktreeProvider(WorktreeProvider):
    """Primary worktree provider using Session-Buddy MCP integration.

    This provider delegates worktree operations to Session-Buddy's existing
    WorktreeManager via MCP. It's the preferred provider when Session-Buddy is available.

    Example:
        >>> provider = SessionBuddyWorktreeProvider()
        >>> result = await provider.create_worktree(
        ...     Path("/repo"),
        ...     "main",
        ...     Path("/worktrees/repo-main")
        ... )
        >>> assert result["success"]
    """

    def __init__(
        self,
        session_buddy_url: str = "http://localhost:8678/mcp",
    ) -> None:
        """Initialize Session-Buddy provider.

        Args:
            session_buddy_url: URL of Session-Buddy MCP server
        """
        self.session_buddy_url = session_buddy_url
        self._mcp_client = None
        self._is_healthy: bool = True

        logger.debug(
            f"SessionBuddyWorktreeProvider initialized (url={session_buddy_url})"
        )

    async def _get_mcp_client(self):
        """Get or create MCP client connection to Session-Buddy.

        Returns:
            MCP client instance
        """
        if self._mcp_client is None:
            # Import MCP client lazily (only when needed)
            try:
                from mcp_client import MCPClient

                self._mcp_client = MCPClient(self.session_buddy_url)
                await self._mcp_client.__aenter__()

                logger.info(f"Connected to Session-Buddy MCP: {self.session_buddy_url}")

            except ImportError as e:
                logger.error(f"MCP client not available: {e}")
                raise WorktreeCreationError(
                    message="MCP client not installed",
                    details={"error": str(e)},
                ) from e
            except Exception as e:
                logger.error(f"Failed to connect to Session-Buddy: {e}", exc_info=True)
                raise WorktreeCreationError(
                    message=f"Failed to connect to Session-Buddy: {e}",
                    details={"session_buddy_url": self.session_buddy_url},
                ) from e

        return self._mcp_client

    async def create_worktree(
        self,
        repository_path: Path,
        branch: str,
        worktree_path: Path,
        create_branch: bool = False,
    ) -> dict[str, Any]:
        """Create a worktree via Session-Buddy MCP.

        Args:
            repository_path: Path to the git repository
            branch: Branch name for the worktree
            worktree_path: Path where worktree should be created
            create_branch: Whether to create the branch if it doesn't exist

        Returns:
            Dictionary with creation result
        """
        try:
            client = await self._get_mcp_client()

            logger.info(
                f"Creating worktree via Session-Buddy: "
                f"repo={repository_path}, branch={branch}, "
                f"worktree={worktree_path}"
            )

            # Call Session-Buddy's create_worktree tool
            result = await client.call_tool(
                "create_worktree",
                arguments={
                    "repository_path": str(repository_path),
                    "branch": branch,
                    "new_path": str(worktree_path),
                    "create_branch": create_branch,
                },
            )

            logger.info(f"Worktree created successfully: {worktree_path}")

            return {
                "success": True,
                "worktree_path": str(worktree_path),
                "branch": branch,
                "repository_path": str(repository_path),
                "provider": "session-buddy",
            }

        except WorktreeCreationError:
            raise
        except Exception as e:
            logger.error(f"Session-Buddy create_worktree failed: {e}", exc_info=True)
            raise WorktreeCreationError(
                message=f"Session-Buddy worktree creation failed: {e}",
                details={
                    "repository_path": str(repository_path),
                    "branch": branch,
                    "worktree_path": str(worktree_path),
                },
            ) from e

    async def remove_worktree(
        self,
        repository_path: Path,
        worktree_path: Path,
        force: bool = False,
    ) -> dict[str, Any]:
        """Remove a worktree via Session-Buddy MCP.

        Args:
            repository_path: Path to the git repository
            worktree_path: Path to worktree directory
            force: Force removal (skip safety checks)

        Returns:
            Dictionary with removal result
        """
        try:
            client = await self._get_mcp_client()

            logger.info(
                f"Removing worktree via Session-Buddy: "
                f"repo={repository_path}, worktree={worktree_path}, force={force}"
            )

            # Call Session-Buddy's remove_worktree tool
            result = await client.call_tool(
                "remove_worktree",
                arguments={
                    "repository_path": str(repository_path),
                    "worktree_path": str(worktree_path),
                    "force": force,
                },
            )

            logger.info(f"Worktree removed successfully: {worktree_path}")

            return {
                "success": True,
                "removed_path": str(worktree_path),
                "repository_path": str(repository_path),
                "provider": "session-buddy",
            }

        except WorktreeRemovalError:
            raise
        except Exception as e:
            logger.error(f"Session-Buddy remove_worktree failed: {e}", exc_info=True)
            raise WorktreeRemovalError(
                message=f"Session-Buddy worktree removal failed: {e}",
                details={
                    "repository_path": str(repository_path),
                    "worktree_path": str(worktree_path),
                },
            ) from e

    async def list_worktrees(
        self,
        repository_path: Path,
    ) -> dict[str, Any]:
        """List worktrees via Session-Buddy MCP.

        Args:
            repository_path: Path to the git repository

        Returns:
            Dictionary with list of worktrees
        """
        try:
            client = await self._get_mcp_client()

            logger.debug(f"Listing worktrees via Session-Buddy: repo={repository_path}")

            # Call Session-Buddy's list_worktrees tool
            result = await client.call_tool(
                "list_worktrees",
                arguments={"repository_path": str(repository_path)},
            )

            logger.debug(f"Found {len(result.get('worktrees', []))} worktrees")

            return {
                "success": True,
                "worktrees": result.get("worktrees", []),
                "repository_path": str(repository_path),
                "provider": "session-buddy",
            }

        except WorktreeValidationError:
            raise
        except Exception as e:
            logger.error(f"Session-Buddy list_worktrees failed: {e}", exc_info=True)
            raise WorktreeValidationError(
                message=f"Session-Buddy worktree listing failed: {e}",
                details={"repository_path": str(repository_path)},
            ) from e

    def health_check(self) -> bool:
        """Check if Session-Buddy MCP is available.

        Returns:
            True if Session-Buddy MCP server is reachable
        """
        try:
            import asyncio
            import socket

            # Parse URL to get host and port
            from urllib.parse import urlparse

            parsed = urlparse(self.session_buddy_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8678

            # Try to connect with timeout
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # 1 second timeout
            result = sock.connect_ex((host, port))
            sock.close()

            is_healthy = result == 0

            if not is_healthy:
                logger.warning(
                    f"Session-Buddy MCP server unreachable: {host}:{port}"
                )

            return is_healthy

        except Exception as e:
            logger.warning(f"Session-Buddy health check failed: {e}")
            return False

    def provider_name(self) -> str:
        """Get the name of this provider.

        Returns:
            Provider name
        """
        return "session-buddy"

    async def close(self) -> None:
        """Close MCP client connection."""
        if self._mcp_client is not None:
            try:
                await self._mcp_client.__aexit__(None, None, None)
                logger.info("Session-Buddy MCP connection closed")
            except Exception as e:
                logger.error(f"Error closing Session-Buddy connection: {e}", exc_info=True)
            finally:
                self._mcp_client = None
