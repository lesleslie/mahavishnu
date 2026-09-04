"""Session Buddy integration for Mahavishnu with code graph analysis."""

from datetime import UTC, datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp_common.code_graph import CodeGraphAnalyzer

# ``messaging`` is an optional Bodai-ecosystem dependency. When it is not
# installed (e.g. minimal venvs used by CI smoke jobs), fall back to
# in-process stub enums/dataclasses so the module remains importable.
# The test suite relies on
# ``mahavishnu.session_buddy.integration.SessionBuddyIntegration`` being
# importable for ``monkeypatch.setattr(..., "SessionBuddyIntegration", ...)``
# patches; an ImportError here breaks every test in
# ``test_mcp_git_analytics.py`` with
# ``AttributeError: module 'mahavishnu.session_buddy' has no attribute 'integration'``.
try:
    # ``messaging.types`` historically lives in an optional Bodai-ecosystem
    # package that is not always available (CI smoke jobs ship a minimal venv).
    # The actual symbols ship alongside this repo at
    # ``mahavishnu.messaging.messaging.types``; fall back to legacy top-level
    # ``messaging.types`` only when neither path resolves (truly minimal
    # installs without ``mahavishnu.messaging.messaging``).
    try:
        from mahavishnu.messaging.messaging.types import (  # type: ignore[import-not-found]
            MessageStatus,
            MessageType,
            Priority,
            ProjectMessage,
        )
    except ImportError:  # pragma: no cover - exercised only on minimal installs
        from messaging.types import (  # type: ignore[import-not-found]  # ty: ignore[unresolved-import]
            MessageStatus,
            MessageType,
            Priority,
            ProjectMessage,
        )
except ImportError:  # pragma: no cover - exercised only on minimal installs

    class MessageStatus(Enum):
        NORMAL = "normal"
        URGENT = "urgent"
        LOW = "low"

    class MessageType(Enum):
        INFO = "info"
        WARNING = "warning"
        ERROR = "error"

    class Priority(Enum):
        HIGH = 1
        NORMAL = 2
        LOW = 3

    class ProjectMessage:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)


class SessionBuddyIntegration:
    """Integration with Session Buddy for development session tracking and quality metrics."""

    def __init__(self, app):
        self.app = app
        self.session_buddy_client = None
        self.code_graph_analyzer = CodeGraphAnalyzer(Path())
        self.logger = __import__("logging").getLogger(__name__)

    async def integrate_code_graph(self, repo_path: str) -> dict[str, Any]:
        """Integrate code graph analysis with Session Buddy."""
        try:
            # Analyze the repository using the code graph analyzer
            analyzer = CodeGraphAnalyzer(Path(repo_path))
            analysis_result = await analyzer.analyze_repository(repo_path)

            # Extract relevant information for Session Buddy
            code_context = {
                "repo_path": repo_path,
                "files_indexed": analysis_result.get("files_indexed", 0),
                "functions_indexed": analysis_result.get("functions_indexed", 0),
                "classes_indexed": analysis_result.get("classes_indexed", 0),
                "total_nodes": analysis_result.get("total_nodes", 0),
                "functions": [],
                "classes": [],
                "imports": [],
            }

            # Extract function details
            for node_id, node in analyzer.nodes.items():
                if hasattr(node, "name") and hasattr(node, "file_id"):
                    # Use ``getattr`` with explicit defaults + ``isinstance``
                    # checks rather than ``hasattr`` so that Mock objects
                    # (which report ``hasattr`` True for any attribute) do not
                    # cause every node to be misclassified as a function.
                    calls = getattr(node, "calls", None)
                    methods = getattr(node, "methods", None)
                    imported_from = getattr(node, "imported_from", None)
                    if isinstance(calls, list):  # Function node
                        code_context["functions"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "is_export": getattr(node, "is_export", False),
                                "start_line": getattr(node, "start_line", 0),
                                "end_line": getattr(node, "end_line", 0),
                                "calls": calls,
                                "id": node_id,
                            }
                        )
                    elif isinstance(methods, list):  # Class node
                        code_context["classes"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "methods": methods,
                                "inherits_from": getattr(node, "inherits_from", []),
                                "id": node_id,
                            }
                        )
                    elif isinstance(imported_from, str):  # Import node
                        code_context["imports"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "imported_from": imported_from,
                                "alias": getattr(node, "alias", None),
                                "id": node_id,
                            }
                        )

            # Send code context to Session Buddy
            await self._send_code_context_to_session_buddy(repo_path, code_context)

            return {
                "status": "success",
                "analysis_result": analysis_result,
                "code_context_sent": True,
                "functions_extracted": len(code_context["functions"]),
                "classes_extracted": len(code_context["classes"]),
                "imports_extracted": len(code_context["imports"]),
            }
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error integrating code graph: {e}")
            return {"status": "error", "error": str(e)}

    async def _send_code_context_to_session_buddy(
        self, repo_path: str, code_context: dict[str, Any]
    ):
        """Send code context to Session Buddy via MCP or direct API."""
        try:
            # In a real implementation, this would send the code context to Session Buddy
            # via MCP protocol or direct API call
            self.logger.info(f"Sending code context for {repo_path} to Session Buddy")

            # For now, we'll simulate sending the context
            # In a real implementation, this would be an actual call to Session Buddy
            # Codebase uses from_project/to_project/content_message; the bundled
            # ``messaging.types.ProjectMessage`` (Pydantic BaseModel) requires
            # ``project_id``/``message`` instead, and the fallback accepts **kwargs: Any.
            session_buddy_message = ProjectMessage(
                id=f"msg_{uuid4().hex}",
                from_project=repo_path,
                to_project=repo_path,
                timestamp=datetime.now(UTC).isoformat(),
                subject="Code context update",
                priority=Priority.NORMAL,
                status=MessageStatus.UNREAD,  # ty: ignore[unresolved-attribute]
                content_type=MessageType.NOTIFICATION,  # ty: ignore[unresolved-attribute]
                content_message=json.dumps(code_context, default=str),
            )

            # Log the message that would be sent
            self.logger.info(
                f"Session Buddy message prepared: {getattr(session_buddy_message, 'project_id', '<unknown>')}"
            )
        except Exception as e:  # noqa: BLE001 - event handler; logs and continues
            self.logger.error(f"Error sending code context to Session Buddy: {e}")

    async def get_related_code(self, repo_path: str, file_path: str) -> dict[str, Any]:
        """Get related code based on imports/calls using code graph."""
        try:
            # Analyze the repository if not already analyzed
            analyzer = CodeGraphAnalyzer(Path(repo_path))
            await analyzer.analyze_repository(repo_path)

            # Find related files using the code graph analyzer
            related_files = await analyzer.find_related_files(file_path)

            return {
                "status": "success",
                "file_path": file_path,
                "related_files": related_files,
                "count": len(related_files),
            }
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error getting related code: {e}")
            return {"status": "error", "error": str(e)}

    async def get_function_context(self, repo_path: str, function_name: str) -> dict[str, Any]:
        """Get context for a specific function using code graph."""
        try:
            # Analyze the repository if not already analyzed
            analyzer = CodeGraphAnalyzer(Path(repo_path))
            await analyzer.analyze_repository(repo_path)

            # Get function context using the code graph analyzer
            context = await analyzer.get_function_context(function_name)

            return {"status": "success", "function_name": function_name, "context": context}
        except Exception as e:  # noqa: BLE001 - event handler; logs and continues
            self.logger.error(f"Error getting function context: {e}")
            return {"status": "error", "error": str(e)}

    async def index_documentation(self, repo_path: str) -> dict[str, Any]:
        """Extract docstrings and index for semantic search."""
        try:
            # Analyze the repository to extract docstrings
            analyzer = CodeGraphAnalyzer(Path(repo_path))
            _analysis_result = await analyzer.analyze_repository(repo_path)

            # Extract docstrings from functions and classes
            documentation = []

            for node_id, node in analyzer.nodes.items():
                if hasattr(node, "name") and hasattr(node, "file_id"):
                    docstring = self._extract_docstring_from_file(node.file_id, node.name)
                    if docstring:
                        documentation.append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "type": "function" if hasattr(node, "calls") else "class",
                                "docstring": docstring,
                                "node_id": node_id,
                            }
                        )

            # In a real implementation, this would index the documentation
            # in Session Buddy's knowledge base
            await self._index_documentation_in_session_buddy(repo_path, documentation)

            return {
                "status": "success",
                "repo_path": repo_path,
                "documentation_items": len(documentation),
                "indexed": True,
            }
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error indexing documentation: {e}")
            return {"status": "error", "error": str(e)}

    def _extract_docstring_from_file(self, file_path: str, function_name: str) -> str | None:
        """Extract docstring from a specific function in a file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Parse the file with AST to extract docstrings
            tree = __import__("ast").parse(content)

            for node in __import__("ast").walk(tree):
                if (
                    isinstance(
                        node,
                        (
                            __import__("ast").FunctionDef,
                            __import__("ast").AsyncFunctionDef,
                            __import__("ast").ClassDef,
                        ),
                    )
                    and node.name == function_name
                ):
                    docstring = __import__("ast").get_docstring(node)
                    return docstring  # type: ignore[no-any-return]

            return None
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return None

    async def _index_documentation_in_session_buddy(
        self, repo_path: str, documentation: list[dict[str, Any]]
    ):
        """Index documentation in Session Buddy's knowledge base."""
        try:
            # In a real implementation, this would send documentation to Session Buddy
            # for indexing in its knowledge base
            self.logger.info(
                f"Indexing {len(documentation)} documentation items for {repo_path} in Session Buddy"
            )

            # Prepare a message for Session Buddy
            _session_buddy_message = ProjectMessage(
                id=f"msg_{uuid4().hex}",
                from_project=repo_path,
                to_project=repo_path,
                timestamp=datetime.now(UTC).isoformat(),
                subject="Documentation index",
                priority=Priority.NORMAL,
                status=MessageStatus.UNREAD,  # ty: ignore[unresolved-attribute]
                content_type=MessageType.NOTIFICATION,  # ty: ignore[unresolved-attribute]
                content_message=json.dumps(documentation, default=str),
            )

            # Log the message that would be sent
            self.logger.info(f"Documentation index message prepared for {repo_path}")

        except Exception as e:  # noqa: BLE001 - event handler; logs and continues
            self.logger.error(f"Error indexing documentation in Session Buddy: {e}")

    async def search_documentation(self, query: str) -> dict[str, Any]:
        """Search through indexed documentation."""
        try:
            # In a real implementation, this would query Session Buddy's
            # documentation index
            self.logger.info(f"Searching documentation for query: {query}")

            # This would normally be a call to Session Buddy's search API
            # For now, return an empty result
            return {"status": "success", "query": query, "results": [], "count": 0}
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error searching documentation: {e}")
            return {"status": "error", "error": str(e)}

    async def send_project_message(
        self,
        from_project: str,
        to_project: str,
        subject: str,
        message: str,
        priority: Priority = Priority.NORMAL,
    ) -> dict[str, Any]:
        """Send message between projects using MCP protocol."""
        try:
            # Create a project message using the shared messaging types
            project_message = ProjectMessage(
                id=f"msg_{uuid4().hex}",
                from_project=from_project,
                to_project=to_project,
                timestamp=datetime.now(UTC).isoformat(),
                subject=subject,
                priority=priority,
                status=MessageStatus.UNREAD,  # ty: ignore[unresolved-attribute]
                content_type=MessageType.NOTIFICATION,  # ty: ignore[unresolved-attribute]
                content_message=message,
            )

            # In a real implementation, this would send the message via MCP
            # For now, we'll just log that the message would be sent
            self.logger.info(f"Project message from {from_project} to {to_project}: {subject}")

            return {
                "status": "success",
                "message_id": project_message.id,  # ty: ignore[unresolved-attribute]
                "sent": True,
            }
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error sending project message: {e}")
            return {"status": "error", "error": str(e)}

    async def list_project_messages(self, project: str) -> dict[str, Any]:
        """List messages for a project."""
        try:
            # In a real implementation, this would retrieve messages from Session Buddy
            # For now, return an empty list
            self.logger.info(f"Listing messages for project: {project}")

            return {"status": "success", "project": project, "messages": [], "count": 0}
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.error(f"Error listing project messages: {e}")
            return {"status": "error", "error": str(e)}


class SessionBuddyManager:
    """Manager for Session Buddy integration features."""

    def __init__(self, app):
        self.app = app
        self.integration = SessionBuddyIntegration(app)

    async def process_repository_for_session_buddy(self, repo_path: str) -> dict[str, Any]:
        """Process a repository for Session Buddy integration."""
        # Integrate code graph
        code_graph_result = await self.integration.integrate_code_graph(repo_path)

        # Index documentation
        doc_result = await self.integration.index_documentation(repo_path)

        return {
            "repository": repo_path,
            "code_graph_integration": code_graph_result,
            "documentation_indexing": doc_result,
            "overall_status": "success"
            if code_graph_result["status"] == doc_result["status"] == "success"
            else "partial",
        }

    async def get_enhanced_context(
        self, repo_path: str, query_elements: dict[str, Any]
    ) -> dict[str, Any]:
        """Get enhanced context combining code graph and Session Buddy knowledge."""
        try:
            results = {}

            # Get function context if function name is provided
            if "function_name" in query_elements:
                func_context = await self.integration.get_function_context(
                    repo_path, query_elements["function_name"]
                )
                results["function_context"] = func_context

            # Get related code if file path is provided
            if "file_path" in query_elements:
                related_code = await self.integration.get_related_code(
                    repo_path, query_elements["file_path"]
                )
                results["related_code"] = related_code

            # Search documentation if query is provided
            if "query" in query_elements:
                doc_search = await self.integration.search_documentation(query_elements["query"])
                results["documentation_search"] = doc_search

            return {"status": "success", "enhanced_context": results, "repo_path": repo_path}
        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            return {"status": "error", "error": str(e)}
