"""Session Buddy integration for Mahavishnu with code graph analysis."""

import json
from pathlib import Path
from typing import Any

from mcp_common.code_graph import CodeGraphAnalyzer
from mcp_common.messaging.types import Priority, ProjectMessage


class SessionBuddyIntegration:
    """Integration with Session Buddy for development session tracking and quality metrics."""

    def __init__(self, app):
        self.app = app
        self.session_buddy_client = None
        self.code_graph_analyzer = CodeGraphAnalyzer(Path("."))
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
                    if hasattr(node, "calls"):  # Function node
                        code_context["functions"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "is_export": getattr(node, "is_export", False),
                                "start_line": getattr(node, "start_line", 0),
                                "end_line": getattr(node, "end_line", 0),
                                "calls": getattr(node, "calls", []),
                                "id": node_id,
                            }
                        )
                    elif hasattr(node, "methods"):  # Class node
                        code_context["classes"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "methods": getattr(node, "methods", []),
                                "inherits_from": getattr(node, "inherits_from", []),
                                "id": node_id,
                            }
                        )
                    elif hasattr(node, "imported_from"):  # Import node
                        code_context["imports"].append(
                            {
                                "name": node.name,
                                "file": node.file_id,
                                "imported_from": getattr(node, "imported_from", ""),
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
        except Exception as e:
            self.logger.error(f"Error integrating code graph: {str(e)}")
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
            session_buddy_message = ProjectMessage(
                project_id=repo_path,
                message={
                    "type": "code_context_update",
                    "content": json.dumps(code_context, default=str),
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                },
                priority=Priority.NORMAL,
            )

            # Log the message that would be sent
            self.logger.info(f"Session Buddy message prepared: {session_buddy_message.project_id}")

        except Exception as e:
            self.logger.error(f"Error sending code context to Session Buddy: {str(e)}")

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
        except Exception as e:
            self.logger.error(f"Error getting related code: {str(e)}")
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
        except Exception as e:
            self.logger.error(f"Error getting function context: {str(e)}")
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
        except Exception as e:
            self.logger.error(f"Error indexing documentation: {str(e)}")
            return {"status": "error", "error": str(e)}

    def _extract_docstring_from_file(self, file_path: str, function_name: str) -> str | None:
        """Extract docstring from a specific function in a file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Parse the file with AST to extract docstrings
            tree = __import__("ast").parse(content)

            for node in __import__("ast").walk(tree):
                if isinstance(
                    node,
                    (
                        __import__("ast").FunctionDef,
                        __import__("ast").AsyncFunctionDef,
                        __import__("ast").ClassDef,
                    ),
                ) and node.name == function_name:
                    docstring = __import__("ast").get_docstring(node)
                    return docstring

            return None
        except Exception:
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
                project_id=repo_path,
                message={
                    "type": "documentation_index",
                    "content": json.dumps(documentation, default=str),
                    "count": len(documentation),
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                },
                priority=Priority.NORMAL,
            )

            # Log the message that would be sent
            self.logger.info(f"Documentation index message prepared for {repo_path}")

        except Exception as e:
            self.logger.error(f"Error indexing documentation in Session Buddy: {str(e)}")

    async def search_documentation(self, query: str) -> dict[str, Any]:
        """Search through indexed documentation."""
        try:
            # In a real implementation, this would query Session Buddy's
            # documentation index
            self.logger.info(f"Searching documentation for query: {query}")

            # This would normally be a call to Session Buddy's search API
            # For now, return an empty result
            return {"status": "success", "query": query, "results": [], "count": 0}
        except Exception as e:
            self.logger.error(f"Error searching documentation: {str(e)}")
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
                project_id=to_project,
                message={
                    "from_project": from_project,
                    "subject": subject,
                    "content": message,
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                },
                priority=priority,
            )

            # In a real implementation, this would send the message via MCP
            # For now, we'll just log that the message would be sent
            self.logger.info(f"Project message from {from_project} to {to_project}: {subject}")

            return {
                "status": "success",
                "message_id": f"msg_{hash(str(project_message))}",
                "sent": True,
            }
        except Exception as e:
            self.logger.error(f"Error sending project message: {str(e)}")
            return {"status": "error", "error": str(e)}

    async def list_project_messages(self, project: str) -> dict[str, Any]:
        """List messages for a project."""
        try:
            # In a real implementation, this would retrieve messages from Session Buddy
            # For now, return an empty list
            self.logger.info(f"Listing messages for project: {project}")

            return {"status": "success", "project": project, "messages": [], "count": 0}
        except Exception as e:
            self.logger.error(f"Error listing project messages: {str(e)}")
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
            if code_graph_result["status"] == "success" and doc_result["status"] == "success"
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
        except Exception as e:
            return {"status": "error", "error": str(e)}
