"""MCP tools for Session Buddy integration with authorization."""

from datetime import UTC, datetime
from typing import Any
import uuid
import warnings

from ...core.permissions import Permission, RBACManager
from ...mcp.auth import require_mcp_auth
from ...messaging import MessagePriority

_CHANNEL_SESSION_TOOL = "mcp__session-buddy__track_channel_session"
_CHANNEL_QUERY_TOOL = "mcp__session-buddy__get_channel_sessions"

_DEPRECATED_CODE_INTEL_MESSAGE = (
    "This Session-Buddy code-intel tool is a compatibility shim. Prefer the "
    "canonical code-index or search surfaces for new work."
)

_VALID_EVENT_TYPES = frozenset(
    {"channel_session_start", "channel_session_end", "channel_heartbeat"}
)
_VALID_SCOPES = frozenset({"conversation", "thread", "day"})


def _coerce_priority(value: str) -> MessagePriority:
    return MessagePriority(value.lower())


def register_session_buddy_tools(  # noqa: C901
    server, session_manager, mcp_client, rbac_manager: RBACManager | None = None
):
    """Register Session Buddy integration tools with the MCP server.

    Structural C901 suppression: FastMCP's ``@server.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The 9 tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.
    """

    def _warn_code_intel_deprecation(tool_name: str, replacement: str) -> None:
        warnings.warn(
            f"{tool_name} is deprecated. Use {replacement} instead. {_DEPRECATED_CODE_INTEL_MESSAGE}",
            DeprecationWarning,
            stacklevel=2,
        )

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,  # type: ignore[arg-type]
        require_repo_param="project_path",
    )
    async def index_code_graph(
        project_path: str, include_docs: bool = True, user_id: str | None = None
    ) -> dict[str, Any]:
        """Index codebase structure for better context in Session Buddy."""
        _warn_code_intel_deprecation("index_code_graph", "code_index.index_repo")
        try:
            from ...session_buddy.integration import SessionBuddyManager

            # Assuming we have access to the main app through the server
            # In a real implementation, this would be properly injected
            app = getattr(server, "app", None)  # This would need to be set up properly
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            session_manager = SessionBuddyManager(app)
            result = await session_manager.process_repository_for_session_buddy(project_path)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to index code graph: {e}"}

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,  # type: ignore[arg-type]
        require_repo_param="project_path",
    )
    async def get_function_context(
        project_path: str, function_name: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """Get caller/callee context for a function for Session Buddy."""
        try:
            from ...session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            integration = SessionBuddyIntegration(app)
            result = await integration.get_function_context(project_path, function_name)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to get function context: {e}"}

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,  # type: ignore[arg-type]
        require_repo_param="project_path",
    )
    async def find_related_code(
        project_path: str, file_path: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """Find code related by imports/calls for Session Buddy."""
        _warn_code_intel_deprecation("find_related_code", "treesitter_tools")
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            integration = SessionBuddyIntegration(app)
            result = await integration.get_related_code(project_path, file_path)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to find related code: {e}"}

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,  # type: ignore[arg-type]
        require_repo_param="project_path",
    )
    async def index_documentation(project_path: str, user_id: str | None = None) -> dict[str, Any]:
        """Extract docstrings and index for semantic search in Session Buddy."""
        _warn_code_intel_deprecation("index_documentation", "code_index.index_repo")
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            integration = SessionBuddyIntegration(app)
            result = await integration.index_documentation(project_path)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to index documentation: {e}"}

    @server.tool()
    @require_mcp_auth(rbac_manager=rbac_manager)  # No repo permission needed for search
    async def search_documentation(query: str, user_id: str | None = None) -> dict[str, Any]:
        """Search through indexed documentation in Session Buddy."""
        _warn_code_intel_deprecation("search_documentation", "search_tools.hybrid_search")
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            integration = SessionBuddyIntegration(app)
            result = await integration.search_documentation(query)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to search documentation: {e}"}

    @server.tool()
    @require_mcp_auth(rbac_manager=rbac_manager)
    async def send_project_message(
        from_project: str,
        to_project: str,
        subject: str,
        message: str,
        priority: str = "NORMAL",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Send message between projects for Session Buddy."""
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            # Convert priority string to enum
            try:
                priority_enum = _coerce_priority(priority)
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid priority: {priority}. Valid values: {list(MessagePriority)}",
                }

            integration = SessionBuddyIntegration(app)
            result = await integration.send_project_message(
                from_project, to_project, subject, message, priority_enum
            )

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to send project message: {e}"}

    @server.tool()
    @require_mcp_auth(rbac_manager=rbac_manager)
    async def list_project_messages(project: str, user_id: str | None = None) -> dict[str, Any]:
        """List messages for a project in Session Buddy."""
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            integration = SessionBuddyIntegration(app)
            result = await integration.list_project_messages(project)

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to list project messages: {e}"}

    @server.tool()
    @require_mcp_auth(rbac_manager=rbac_manager)
    async def track_channel_session(
        event_type: str,
        channel_type: str,
        channel_id: str,
        sender_id: str,
        session_scope: str = "conversation",
        thread_id: str | None = None,
        component_name: str = "mahavishnu",
        workspace: str | None = None,
        platform: str | None = None,
        message_preview: str | None = None,
        message_count: int = 1,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Track a channel session event (start / end / heartbeat) in Session-Buddy.

        Delegates to Session-Buddy's track_channel_session MCP tool.
        See docs/plans/session-buddy-multi-channel-spec.md for the full event schema.
        """
        if event_type not in _VALID_EVENT_TYPES:
            return {
                "status": "error",
                "error": f"Invalid event_type {event_type!r}. Must be one of {sorted(_VALID_EVENT_TYPES)}",
            }
        if session_scope not in _VALID_SCOPES:
            return {
                "status": "error",
                "error": f"Invalid session_scope {session_scope!r}. Must be one of {sorted(_VALID_SCOPES)}",
            }

        payload: dict[str, Any] = {
            "event_version": "2.0",
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "channel_type": channel_type,
            "channel_id": channel_id,
            "sender_id": sender_id,
            "session_scope": session_scope,
            "component_name": component_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "message_count": message_count,
            "metadata": metadata or {},
        }
        if thread_id is not None:
            payload["thread_id"] = thread_id
        if workspace is not None:
            payload["workspace"] = workspace
        if platform is not None:
            payload["platform"] = platform
        if message_preview is not None:
            payload["message_preview"] = message_preview[:200]

        try:
            result = await mcp_client.call_tool(_CHANNEL_SESSION_TOOL, payload)
            return {"status": "success", "event_id": payload["event_id"], "result": result}
        except Exception as e:
            return {
                "status": "error",
                "error": f"Session-Buddy call failed: {e}",
                "event_id": payload["event_id"],
            }

    @server.tool()
    @require_mcp_auth(rbac_manager=rbac_manager)
    async def get_channel_sessions(
        channel_type: str | None = None,
        channel_id: str | None = None,
        sender_id: str | None = None,
        session_scope: str | None = None,
        limit: int = 20,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Query active or recent channel sessions tracked in Session-Buddy.

        All filter parameters are optional — omit to retrieve all sessions.
        """
        if limit < 1 or limit > 200:
            return {"status": "error", "error": "limit must be between 1 and 200"}

        query: dict[str, Any] = {"limit": limit}
        if channel_type is not None:
            query["channel_type"] = channel_type
        if channel_id is not None:
            query["channel_id"] = channel_id
        if sender_id is not None:
            query["sender_id"] = sender_id
        if session_scope is not None:
            if session_scope not in _VALID_SCOPES:
                return {
                    "status": "error",
                    "error": f"Invalid session_scope {session_scope!r}. Must be one of {sorted(_VALID_SCOPES)}",
                }
            query["session_scope"] = session_scope

        try:
            result = await mcp_client.call_tool(_CHANNEL_QUERY_TOOL, query)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Session-Buddy query failed: {e}"}

    print("✅ Registered 9 Session Buddy integration tools with MCP server (with authorization)")
