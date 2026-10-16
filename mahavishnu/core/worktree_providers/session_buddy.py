"""Session-Buddy MCP worktree provider (primary)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from .base import WorktreeProvider
from .errors import (
    WorktreeCreationError,
    WorktreeRemovalError,
    WorktreeToolNotAvailableError,
    WorktreeValidationError,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_tool_payload(result: Any) -> dict[str, Any]:
    """Parse the JSON-string payload returned by Session-Buddy's tools.

    FastMCP's ``client.call_tool()`` returns a ``CallToolResult`` whose
    ``.content`` is a list of ``TextContent`` objects. Session-Buddy's
    worktree tools serialize their response via ``json.dumps``, so the
    raw text is a JSON document we parse back to a dict.

    For dict inputs (un-mocked tests or alternative clients) the dict is
    returned as-is so callers can use the existing payload shape.

    Returns an empty dict when the response cannot be parsed — callers
    then see ``success=False`` and skip the provider gracefully.
    """
    if isinstance(result, dict):
        return result
    try:
        content = getattr(result, "content", None)
        if content is None and isinstance(result, list):
            # Some FastMCP versions return a list directly
            content = result
        if not content:
            return {}
        first = content[0]
        text = getattr(first, "text", None) or (first if isinstance(first, str) else None)
        if not text:
            return {}
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, AttributeError, IndexError, TypeError) as exc:
        logger.warning("Failed to extract Session-Buddy tool payload: %s", exc)
        return {}


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
        self._last_health: bool | None = None
        self._health_checked_at: float | None = None

        logger.debug(f"SessionBuddyWorktreeProvider initialized (url={session_buddy_url})")

    async def _get_mcp_client(self):
        """Get or create MCP client connection to Session-Buddy.

        Returns:
            MCP client instance
        """
        if self._mcp_client is None:
            # Import MCP client lazily (only when needed). Session-Buddy speaks
            # the FastMCP wire protocol, so the substrate is ``fastmcp.Client`` —
            # the local ``MCPClient`` alias preserves the call sites that follow.
            try:
                from fastmcp import Client as MCPClient

                self._mcp_client = MCPClient(self.session_buddy_url)
                await self._mcp_client.__aenter__()

                logger.info(f"Connected to Session-Buddy MCP: {self.session_buddy_url}")

            except ImportError as e:
                logger.error(f"MCP client not available: {e}")
                raise WorktreeCreationError(
                    message="MCP client not installed",
                    details={"error": str(e)},
                ) from e
            except Exception as e:  # translate any MCP/network error to typed WorktreeCreationError
                logger.exception("Failed to connect to Session-Buddy")
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
            payload = _extract_tool_payload(result)
            if payload.get("success") is False:
                return {
                    "success": False,
                    "error": payload.get("error", "unknown error"),
                    "error_code": payload.get("error_code"),
                    "provider": "session-buddy",
                }

            logger.info(f"Worktree created successfully: {worktree_path}")

            return {
                "success": True,
                "worktree_path": payload.get("worktree_path", str(worktree_path)),
                "head": payload.get("head"),
                "branch": payload.get("branch", branch),
                "repository_path": str(repository_path),
                "provider": "session-buddy",
            }

        except WorktreeCreationError:
            raise
        except Exception as e:  # translate any MCP error to typed WorktreeCreationError
            logger.exception("Session-Buddy create_worktree failed")
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
            payload = _extract_tool_payload(result)
            if payload.get("success") is False:
                return {
                    "success": False,
                    "error": payload.get("error", "unknown error"),
                    "error_code": payload.get("error_code"),
                    "force_required": payload.get("force_required", False),
                    "safety_check": payload.get("safety_check"),
                    "provider": "session-buddy",
                }

            logger.info(f"Worktree removed successfully: {worktree_path}")

            return {
                "success": True,
                "removed_path": payload.get("worktree_path", str(worktree_path)),
                "repository_path": str(repository_path),
                "provider": "session-buddy",
            }

        except WorktreeRemovalError:
            raise
        except Exception as e:  # translate any MCP error to typed WorktreeRemovalError
            # FastMCP returns "Unknown tool: '<name>'" when the MCP server
            # does not advertise the requested tool. That's a configuration
            # gap, not a real failure — surface the sentinel so the
            # coordinator can fall back to the next provider instead of
            # misleadingly bubbling up a green-out-of-tree exception. Match
            # the FastMCP error envelope verbatim (any case) plus the
            # underlying MCP "tool not found" code path.
            error_msg = str(e)
            if "Unknown tool" in error_msg or "tool not found" in error_msg.lower():
                logger.warning(
                    "Session-Buddy MCP does not expose remove_worktree; "
                    "coordinator will fall back to the next provider"
                )
                raise WorktreeToolNotAvailableError(
                    message=(f"Session-Buddy MCP does not expose remove_worktree: {e}"),
                    details={
                        "repository_path": str(repository_path),
                        "worktree_path": str(worktree_path),
                        "missing_tool": "remove_worktree",
                    },
                ) from e
            logger.exception("Session-Buddy remove_worktree failed")
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
            payload = _extract_tool_payload(result)

            worktrees = payload.get("worktrees", []) if payload else []
            logger.debug(f"Found {len(worktrees)} worktrees")

            # Default to True when the payload is present; only treat as failure
            # when the upstream explicitly reports success=False.
            if not payload:
                success = False
                error = "Session-Buddy did not respond"
            else:
                success = payload.get("success", True)
                error = payload.get("error")

            return {
                "success": success,
                "worktrees": worktrees,
                "repository_path": str(repository_path),
                "error": error,
                "provider": "session-buddy",
            }

        except WorktreeValidationError:
            raise
        except Exception as e:  # translate any MCP error to typed WorktreeValidationError
            logger.exception("Session-Buddy list_worktrees failed")
            raise WorktreeValidationError(
                message=f"Session-Buddy worktree listing failed: {e}",
                details={"repository_path": str(repository_path)},
            ) from e

    # Workaround for session-buddy's race between /health and tool
    # registration: the wrapper marks the server healthy once
    # /health returns 200, but tools/list is still in flight.
    # Until the upstream fix lands (sync profile dispatch at
    # startup), this short cache lets the registry see the
    # server as 'unhealthy' for a moment so the LocalWorktree
    # Provider transparently takes over. See
    # docs/decisions/session-buddy-worktree-registration-race.md
    # (to be written) for the full diagnosis.
    _HEALTH_CACHE_TTL_S = 10.0

    def health_check(self) -> bool:
        """Check if Session-Buddy MCP is available AND the worktree
        tools are actually registered.

        Returns:
            True only if the server is reachable AND
            ``list_worktrees`` is in the registered tools list.
            Mere TCP reachability is not enough -- the server can
            respond on its port while still mid-startup (the
            wrapper's 60s health-check timeout fires before the
            FULL profile dispatch finishes registering tools).
        """
        import time as _time

        # Short-circuit on cached result
        now = _time.monotonic()
        if (
            self._health_checked_at is not None
            and (now - self._health_checked_at) < self._HEALTH_CACHE_TTL_S
        ):
            return self._last_health

        try:
            import socket
            from urllib.parse import urlparse

            parsed = urlparse(self.session_buddy_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8678

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()

            if result != 0:
                logger.warning(f"Session-Buddy MCP server unreachable: {host}:{port}")
                self._last_health = False
                self._health_checked_at = now
                return False

            # Port is open. Now verify the tool is actually
            # registered -- bare TCP reachability is not enough
            # (see docstring). Single-shot tools/list probe via
            # stdlib urllib; parse the SSE-wrapped response.
            is_healthy = self._probe_list_worktrees_registered(host, port)

            if not is_healthy:
                logger.warning(
                    "Session-Buddy MCP is up but 'list_worktrees' is "
                    "not registered yet; reporting unhealthy so the "
                    "registry picks the local provider"
                )

            self._last_health = is_healthy
            self._health_checked_at = now
            return is_healthy

        except Exception as e:  # health probe — exception means unreachable, return False  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Session-Buddy health check failed: {e}")
            self._last_health = False
            self._health_checked_at = now
            return False

    def _probe_list_worktrees_registered(self, host: str, port: int) -> bool:
        """One-shot MCP initialize + tools/list probe to verify
        ``list_worktrees`` is in the registered tools. Returns
        False on any error (timeout, parse failure, missing tool).
        """
        import json
        import urllib.request

        base = f"http://{host}:{port}/mcp"
        # 1. initialize (gets us a session id)
        init_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mahavishnu-healthcheck", "version": "0"},
                },
            }
        ).encode()
        req = urllib.request.Request(
            base,
            data=init_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310 — stdlib HTTP for health probe to localhost
            session_id = resp.headers.get("mcp-session-id", "")
            resp.read().decode("utf-8", errors="replace")

        if not session_id:
            return False

        # 2. tools/list with the session id
        list_body = json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        ).encode()
        req2 = urllib.request.Request(
            base,
            data=list_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-session-id": session_id,
            },
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=2) as resp2:  # nosec B310 — localhost health probe
            raw2 = resp2.read().decode("utf-8", errors="replace")

        # The server returns SSE; the JSON payload is on a 'data: '
        # line. Find it and parse.
        for line in raw2.splitlines():
            stripped = line.removeprefix("data: ").strip()
            if not stripped or not stripped.startswith("{"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            tools = payload.get("result", {}).get("tools", [])
            return bool(any(t.get("name") == "list_worktrees" for t in tools))
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
            except Exception:  # close is best-effort teardown; never fatal
                logger.exception("Error closing Session-Buddy connection")
            finally:
                self._mcp_client = None
