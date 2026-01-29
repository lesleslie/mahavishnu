"""MCP tools for Session Buddy integration."""

from typing import Any

from mcp_common.messaging.types import Priority


def register_session_buddy_tools(server, session_manager, mcp_client):
    """Register Session Buddy integration tools with the MCP server."""

    @server.tool()
    async def index_code_graph(project_path: str, include_docs: bool = True) -> dict[str, Any]:
        """Index codebase structure for better context in Session Buddy.

        Args:
            project_path: Path to the project to analyze
            include_docs: Whether to include documentation indexing

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
            return {"status": "error", "error": f"Failed to index code graph: {str(e)}"}

    @server.tool()
    async def get_function_context(project_path: str, function_name: str) -> dict[str, Any]:
        """Get caller/callee context for a function for Session Buddy.

        Args:
            project_path: Path to the project
            function_name: Name of the function to analyze

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
            return {"status": "error", "error": f"Failed to get function context: {str(e)}"}

    @server.tool()
    async def find_related_code(project_path: str, file_path: str) -> dict[str, Any]:
        """Find code related by imports/calls for Session Buddy.

        Args:
            project_path: Path to the project
            file_path: Path to the file to analyze

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
            return {"status": "error", "error": f"Failed to find related code: {str(e)}"}

    @server.tool()
    async def index_documentation(project_path: str) -> dict[str, Any]:
        """Extract docstrings and index for semantic search in Session Buddy.

        Args:
            project_path: Path to the project to analyze

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
            return {"status": "error", "error": f"Failed to index documentation: {str(e)}"}

    @server.tool()
    async def search_documentation(query: str) -> dict[str, Any]:
        """Search through indexed documentation in Session Buddy.

        Args:
            query: Search query

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
            return {"status": "error", "error": f"Failed to search documentation: {str(e)}"}

    @server.tool()
    async def send_project_message(
        from_project: str, to_project: str, subject: str, message: str, priority: str = "NORMAL"
    ) -> dict[str, Any]:
        """Send message between projects for Session Buddy.

        Args:
            from_project: Source project identifier
            to_project: Destination project identifier
            subject: Message subject
            message: Message content
            priority: Message priority (NORMAL, HIGH, CRITICAL)

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
                priority_enum = Priority(priority.upper())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid priority: {priority}. Valid values: {list(Priority)}",
                }

            integration = SessionBuddyIntegration(app)
            result = await integration.send_project_message(
                from_project, to_project, subject, message, priority_enum
            )

            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": f"Failed to send project message: {str(e)}"}

    @server.tool()
    async def list_project_messages(project: str) -> dict[str, Any]:
        """List messages for a project in Session Buddy.

        Args:
            project: Project identifier to list messages for

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
            return {"status": "error", "error": f"Failed to list project messages: {str(e)}"}

    print("✅ Registered 7 Session Buddy integration tools with MCP server")
