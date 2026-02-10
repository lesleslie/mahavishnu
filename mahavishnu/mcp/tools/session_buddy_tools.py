"""MCP tools for Session Buddy integration with authorization."""

from typing import Any

from ...messaging import MessagePriority

from ..auth import require_mcp_auth
from ...core.permissions import Permission, RBACManager


def register_session_buddy_tools(server, session_manager, mcp_client, rbac_manager: RBACManager | None = None):
    """Register Session Buddy integration tools with the MCP server."""

    @server.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )
    async def index_code_graph(project_path: str, include_docs: bool = True, user_id: str | None = None) -> dict[str, Any]:
        """Index codebase structure for better context in Session Buddy.

        Args:
            project_path: Path to the project to analyze
            include_docs: Whether to include documentation indexing
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Analysis results with indexed elements
        """
        try:
            from ..session_buddy.integration import SessionBuddyManager

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
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )
    async def get_function_context(project_path: str, function_name: str, user_id: str | None = None) -> dict[str, Any]:
        """Get caller/callee context for a function for Session Buddy.

        Args:
            project_path: Path to the project
            function_name: Name of the function to analyze
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Context information for the function
        """
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

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
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )
    async def find_related_code(project_path: str, file_path: str, user_id: str | None = None) -> dict[str, Any]:
        """Find code related by imports/calls for Session Buddy.

        Args:
            project_path: Path to the project
            file_path: Path to the file to analyze
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Related code elements
        """
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
        required_permission=Permission.READ_REPO,
        require_repo_param="project_path",
    )
    async def index_documentation(project_path: str, user_id: str | None = None) -> dict[str, Any]:
        """Extract docstrings and index for semantic search in Session Buddy.

        Args:
            project_path: Path to the project to analyze
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Indexing results
        """
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
        """Search through indexed documentation in Session Buddy.

        Args:
            query: Search query
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Search results
        """
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
        """Send message between projects for Session Buddy.

        Args:
            from_project: Source project identifier
            to_project: Destination project identifier
            subject: Message subject
            message: Message content
            priority: Message priority (NORMAL, HIGH, CRITICAL)
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            Send status
        """
        try:
            from ..session_buddy.integration import SessionBuddyIntegration

            app = getattr(server, "app", None)
            if not app:
                return {"status": "error", "error": "App instance not available in server context"}

            # Convert priority string to enum
            try:
                priority_enum = MessagePriority(priority.upper())
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
        """List messages for a project in Session Buddy.

        Args:
            project: Project identifier to list messages for
            user_id: Authenticated user ID (injected by @require_mcp_auth)

        Returns:
            List of messages
        """
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

    print("✅ Registered 7 Session Buddy integration tools with MCP server (with authorization)")

