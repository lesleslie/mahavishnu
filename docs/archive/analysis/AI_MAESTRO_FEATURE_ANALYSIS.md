# AI Maestro Feature Analysis for Mahavishnu

**Date:** 2025-01-24
**Analysis of:** [AI Maestro v0.19.0](https://github.com/23blocks-OS/ai-maestro)
**Purpose:** Identify features that would enhance Mahavishnu orchestration platform
**Related:** Session Buddy analysis at `../session-buddy/AI_MAESTRO_FEATURE_ANALYSIS.md`

---

## Executive Summary

AI Maestro and Mahavishnu serve different but complementary orchestration needs:

| Aspect | AI Maestro | Mahavishnu |
|--------|-----------|------------|
| **Architecture** | Multi-agent orchestrator (tmux + web dashboard) | Multi-engine orchestrator (MCP server) |
| **Scope** | Managing AI agents across machines | Orchestration engines across repositories |
| **Adapters** | Agent-specific configurations | Prefect, LlamaIndex, Agno, Oneiric |
| **Storage** | CozoDB (graph-relational) per agent | DuckDB (vector + relational) centralized |
| **Communication** | Agent-to-agent messaging | Multi-project coordination |
| **Integration** | Shell-based workflows | MCP-based tool calls |

**Key Insight:** AI Maestro's features for **agent communication**, **code graph analysis**, and **portable configuration** would significantly enhance Mahavishnu's multi-repository orchestration capabilities.

---

## 🎯 Top Recommended Features for Mahavishnu

### 1. Inter-Repository Messaging System ⭐⭐⭐⭐⭐
**Priority: HIGH** | **Effort: MEDIUM** | **Alignment: PERFECT**

AI Maestro's messaging system would dramatically enhance Mahavishnu's cross-repository coordination.

#### What AI Maestro Has

- **Persistent message queue** with inbox/outbox per agent
- **Priority levels:** urgent, high, normal, low
- **Message types:** request, response, notification, update
- **Message forwarding** with context preservation
- **Cross-host messaging** via mesh network (optional for Mahavishnu)

#### Why This Matters for Mahavishnu

Mahavishnu orchestrates workflows across multiple repositories. A messaging system enables:

1. **Backend → Frontend Notifications**
   - Backend repo notifies frontend when API is ready
   - Schema changes automatically alert dependent services
   - Version compatibility notifications

2. **QA → Development Alerts**
   - Test failures automatically notify relevant repo owners
   - Integration test results routed to correct teams
   - Performance regression alerts

3. **Cross-Adapter Coordination**
   - LlamaIndex adapter notifies Prefect when ingestion completes
   - Agno agent notifies LlamaIndex when new code is ready for indexing
   - Workflow status updates between engines

#### Proposed Mahavishnu Implementation

```python
# mahavishnu/messaging/repository_messenger.py

from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel
from mahavishnu.core.config import MahavishnuSettings
import structlog

logger = structlog.get_logger(__name__)

class Priority(str, Literal["low", "normal", "high", "urgent"]):
    """Message priority levels"""
    pass

class MessageType(str, Literal["request", "response", "notification", "update"]):
    """Message types"""
    pass

class RepositoryMessage(BaseModel):
    """Inter-repository message"""
    id: str
    from_repository: str
    from_adapter: str | None = None  # 'prefect', 'llamaindex', 'agno'
    to_repository: str
    timestamp: str
    subject: str
    priority: Priority
    status: Literal["unread", "read", "archived"]
    content_type: MessageType
    content_message: str
    content_context: dict[str, object] | None = None
    in_reply_to: str | None = None
    workflow_id: str | None = None

class RepositoryMessenger:
    """Handle messaging between repositories"""

    def __init__(self, settings: MahavishnuSettings):
        self.settings = settings
        # Use DuckDB or vector store for persistence

    async def send_message(
        self,
        from_repository: str,
        to_repository: str,
        subject: str,
        message: str,
        priority: Priority = Priority.NORMAL,
        message_type: MessageType = MessageType.NOTIFICATION,
        from_adapter: str | None = None,
        context: dict[str, object] | None = None,
        workflow_id: str | None = None
    ) -> RepositoryMessage:
        """
        Send a message from one repository to another.

        Example:
            # Backend API notifies frontend
            await messenger.send_message(
                from_repository="myapp-backend-api",
                to_repository="myapp-frontend-dashboard",
                subject="User stats API ready",
                message="GET /api/stats implemented. Returns {activeUsers, signups}.",
                priority=Priority.HIGH,
                context={
                    "endpoint": "/api/stats",
                    "cache_ttl": 300,
                    "rate_limit": "100/hour"
                }
            )
        """
        msg_id = f"msg-{int(datetime.now().timestamp())}-{from_repository[:8]}"

        message_obj = RepositoryMessage(
            id=msg_id,
            from_repository=from_repository,
            from_adapter=from_adapter,
            to_repository=to_repository,
            timestamp=datetime.now().isoformat(),
            subject=subject,
            priority=priority,
            status="unread",
            content_type=message_type,
            content_message=message,
            content_context=context,
            workflow_id=workflow_id
        )

        # Store in database
        await self._store_message(message_obj)

        logger.info(
            "Repository message sent",
            from_repo=from_repository,
            to_repo=to_repository,
            message_id=msg_id,
            priority=priority
        )

        return message_obj

    async def list_messages(
        self,
        repository: str,
        status: Literal["unread", "read", "archived"] | None = None,
        priority: Priority | None = None,
        from_adapter: str | None = None
    ) -> list[RepositoryMessage]:
        """List messages for a repository with optional filters"""
        return await self._list_messages(repository, status, priority, from_adapter)

    async def forward_message(
        self,
        original_message_id: str,
        from_repository: str,
        to_repository: str,
        forward_note: str | None = None
    ) -> RepositoryMessage:
        """
        Forward a message to another repository with additional context.

        Example:
            # QA forwards test failure to backend lead
            await messenger.forward_message(
                original_message_id="msg-1234567890-backend",
                from_repository="myapp-qa-tests",
                to_repository="myapp-backend-api",
                forward_note="Critical blocker, needs immediate attention"
            )
        """
        original = await self._get_message(original_message_id)

        forwarded_content = f"""--- Forwarded Message ---
From: {original.from_repository}
To: {original.to_repository}
Sent: {original.timestamp}
Subject: {original.subject}

{original.content_message}
--- End of Forwarded Message ---"""

        if forward_note:
            forwarded_content = f"{forward_note}\n\n{forwarded_content}"

        return await self.send_message(
            from_repository=from_repository,
            to_repository=to_repository,
            subject=f"Fwd: {original.subject}",
            message=forwarded_content,
            priority=original.priority,
            message_type=MessageType.NOTIFICATION
        )
```

#### MCP Tool Integration

```python
# mahavishnu/mcp/tools/messaging_tools.py

from fastmcp import FastMCP
from mahavishnu.messaging.repository_messenger import RepositoryMessenger, Priority, MessageType

mcp = FastMCP("mahavishnu-messaging")

@mcp.tool()
async def send_repository_message(
    from_repository: str,
    to_repository: str,
    subject: str,
    message: str,
    priority: Priority = Priority.NORMAL,
    message_type: MessageType = MessageType.NOTIFICATION,
    from_adapter: str | None = None,
    context: dict[str, object] | None = None
) -> dict[str, object]:
    """
    Send a structured message between repositories.

    Enables cross-repository coordination for:
    - API readiness notifications (backend → frontend)
    - Test failure alerts (QA → development)
    - Schema change notifications (database → services)
    - Workflow status updates (adapter → adapter)

    Args:
        from_repository: Source repository identifier (from repos.yaml)
        to_repository: Target repository identifier
        subject: Message subject line
        message: Message body
        priority: Message priority (low, normal, high, urgent)
        message_type: Type of message (request, response, notification, update)
        from_adapter: Optional adapter identifier (prefect, llamaindex, agno)
        context: Additional metadata/context

    Returns:
        Sent message with ID and metadata
    """
    messenger = RepositoryMessenger(app_settings)
    message_obj = await messenger.send_message(
        from_repository=from_repository,
        to_repository=to_repository,
        subject=subject,
        message=message,
        priority=priority,
        message_type=message_type,
        from_adapter=from_adapter,
        context=context
    )

    return {
        "success": True,
        "message_id": message_obj.id,
        "timestamp": message_obj.timestamp,
        "priority": message_obj.priority
    }

@mcp.tool()
async def list_repository_messages(
    repository: str,
    status: Literal["unread", "read", "archived"] | None = None,
    priority: Priority | None = None,
    from_adapter: str | None = None
) -> dict[str, object]:
    """
    List messages for a repository.

    Args:
        repository: Repository identifier (from repos.yaml)
        status: Filter by status (optional)
        priority: Filter by priority (optional)
        from_adapter: Filter by adapter (optional)

    Returns:
        List of messages with metadata
    """
    messenger = RepositoryMessenger(app_settings)
    messages = await messenger.list_messages(repository, status, priority, from_adapter)

    return {
        "success": True,
        "messages": [msg.model_dump() for msg in messages],
        "count": len(messages)
    }

@mcp.tool()
async def forward_repository_message(
    original_message_id: str,
    from_repository: str,
    to_repository: str,
    forward_note: str | None = None
) -> dict[str, object]:
    """
    Forward a message to another repository with additional context.

    Args:
        original_message_id: ID of message to forward
        from_repository: Repository doing the forwarding
        to_repository: Target repository
        forward_note: Optional note to add to forwarded message

    Returns:
        Forwarded message with ID
    """
    messenger = RepositoryMessenger(app_settings)
    forwarded_msg = await messenger.forward_message(
        original_message_id=original_message_id,
        from_repository=from_repository,
        to_repository=to_repository,
        forward_note=forward_note
    )

    return {
        "success": True,
        "message_id": forwarded_msg.id,
        "timestamp": forwarded_msg.timestamp
    }
```

#### Database Schema (DuckDB)

```sql
-- Add to mahavishnu database initialization

CREATE TABLE IF NOT EXISTS repository_messages (
    id TEXT PRIMARY KEY,
    from_repository TEXT NOT NULL,
    from_adapter TEXT,
    to_repository TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    subject TEXT NOT NULL,
    priority TEXT NOT NULL,  -- 'low' | 'normal' | 'high' | 'urgent'
    status TEXT NOT NULL,     -- 'unread' | 'read' | 'archived'
    content_type TEXT NOT NULL,
    content_message TEXT NOT NULL,
    content_context JSON,
    in_reply_to TEXT,
    workflow_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_to_repo
    ON repository_messages(to_repository, status, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_messages_from_repo
    ON repository_messages(from_repository, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_messages_workflow
    ON repository_messages(workflow_id, timestamp DESC);
```

#### Real-World Mahavishnu Use Cases

```python
# 1. Backend notifies frontend that API is ready
await send_repository_message(
    from_repository="myapp-backend-api",
    to_repository="myapp-frontend-dashboard",
    subject="User stats API ready for integration",
    message="GET /api/stats implemented and tested. "
            "Returns {activeUsers, signups, revenue}. "
            "Cached for 5min. Rate limited to 100/hour. "
            "OpenAPI spec at /api/docs.",
    priority=Priority.HIGH,
    from_adapter="prefect",
    context={
        "endpoint": "/api/stats",
        "openapi_spec": "https://api.example.com/api/docs",
        "cache_ttl": 300,
        "rate_limit": "100/hour",
        "workflow_id": "wf-stats-api-123"
    }
)

# 2. LlamaIndex notifies Prefect that ingestion is complete
await send_repository_message(
    from_repository="myapp-backend",
    to_repository="myapp-backend",  # Same repo, different concern
    subject="RAG ingestion complete",
    message="Successfully indexed 1,247 documents from 45 Python files. "
            "Vector store ready for queries.",
    priority=Priority.NORMAL,
    from_adapter="llamaindex",
    context={
        "documents_indexed": 1247,
        "files_processed": 45,
        "vector_store": "pgvector",
        "index_id": "backend-main-001"
    }
)

# 3. QA alerts developers of test failure
await send_repository_message(
    from_repository="myapp-qa-tests",
    to_repository="myapp-backend-api",
    subject="URGENT: Integration test failure",
    message="POST /api/users returning 500 error in 3 test cases. "
            "Regression detected after last commit. "
            "See test_report_20250124.html for details.",
    priority=Priority.URGENT,
    context={
        "test_file": "tests/api/test_users.py",
        "failing_tests": ["test_create_user", "test_update_user", "test_delete_user"],
        "commit": "abc123def",
        "report_url": "https://ci.example.com/reports/20250124.html"
    }
)

# 4. Cross-repository schema change notification
await send_repository_message(
    from_repository="myapp-database",
    to_repository="myapp-backend-api",
    subject="Breaking schema change: users table",
    message="Column 'email_verified' added to users table. "
            "Column 'is_active' default changed from TRUE to FALSE. "
            "Migration required before next deployment.",
    priority=Priority.HIGH,
    context={
        "migration_file": "migrations/20250124_add_email_verification.sql",
        "breaking_change": True,
        "required_action": "Run migration before deploying backend v2.3.0"
    }
)
```

#### Benefits for Mahavishnu

1. **Automated Cross-Repo Coordination**
   - No manual emails or Slack messages
   - Persistent message history
   - Priority-based routing

2. **Adapter-to-Adapter Communication**
   - LlamaIndex → Prefect: "Ingestion complete, start workflow"
   - Agno → LlamaIndex: "New code deployed, re-index needed"
   - Prefect → Agno: "Workflow failed, investigate"

3. **Workflow Integration**
   - Messages linked to workflow executions
   - Automatic notifications on workflow state changes
   - Context preserved across async operations

4. **Quality Control**
   - QA automatically alerts developers on test failures
   - Performance regression notifications
   - Security vulnerability alerts

---

### 2. Code Graph Visualization & Indexing ⭐⭐⭐⭐⭐
**Priority: HIGH** | **Effort: HIGH** | **Alignment: EXCELLENT**

AI Maestro's Code Graph provides deep codebase understanding that would dramatically improve Mahavishnu's RAG pipeline quality.

#### What AI Maestro Has

- **Multi-language AST parsing:** TypeScript, JavaScript, Ruby, Python
- **CozoDB storage:** Graph relationships (classes, functions, calls, imports)
- **Delta indexing:** ~100ms for changed files vs 1000ms+ full re-index
- **Interactive graph visualization:** Web-based explorer
- **Filter by type:** Files, Functions, Components

#### Why This Matters for Mahavishnu

Mahavishnu's LlamaIndex adapter currently ingests code as **flat documents**. Code graph awareness enables:

1. **Smarter Document Chunking**
   - Chunk along function/class boundaries (not arbitrary 1024 chars)
   - Keep related code together (class + methods)
   - Preserve import context for better embeddings

2. **Enhanced RAG Retrieval**
   - When retrieving a function, also retrieve related functions
   - Understand call chains for better context
   - Find callers/callees alongside search results

3. **Better Vector Embeddings**
   - Embed semantic meaning + code structure
   - Weight exported functions higher
   - Consider call frequency in relevance scoring

4. **Quality Metrics**
   - Analyze code complexity (cyclomatic complexity from AST)
   - Measure coupling (number of imports/calls)
   - Detect code smells (long functions, deep inheritance)

#### Proposed Mahavishnu Implementation

```python
# mahavishnu/code_graph/analyzer.py

import ast
from pathlib import Path
from typing import Literal
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)

@dataclass
class CodeNode:
    """Base class for code nodes"""
    id: str
    name: str
    file_id: str
    node_type: Literal["file", "function", "class", "import"]

@dataclass
class FunctionNode(CodeNode):
    """Function or method"""
    is_export: bool
    start_line: int
    end_line: int
    calls: list[str]  # List of function names called
    lang: str = "python"

@dataclass
class ClassNode(CodeNode):
    """Class definition"""
    class_type: Literal["class", "interface", "type"]
    start_line: int
    end_line: int
    extends: str | None = None
    methods: list[str]  # Function IDs

@dataclass
class ImportNode(CodeNode):
    """Import statement"""
    module: str
    import_type: Literal["import", "from_import"]
    names: list[str]

class CodeGraphAnalyzer:
    """Analyze and index codebase structure for better RAG"""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.nodes: dict[str, CodeNode] = {}
        self.edges: dict[str, set[str]] = {}

    async def analyze_repository(self, repo_path: str) -> dict[str, object]:
        """
        Analyze repository and build code graph.

        Returns:
            Statistics about indexed code
        """
        logger.info("Starting repository analysis", path=repo_path)

        python_files = list(Path(repo_path).rglob("*.py"))
        logger.info("Found Python files", count=len(python_files))

        stats = {
            "files_indexed": 0,
            "functions_indexed": 0,
            "classes_indexed": 0,
            "calls_indexed": 0,
            "imports_indexed": 0
        }

        for file_path in python_files:
            try:
                result = await self._analyze_file(file_path)
                if result:
                    stats["files_indexed"] += 1
                    stats["functions_indexed"] += result["functions"]
                    stats["classes_indexed"] += result["classes"]
                    stats["calls_indexed"] += result["calls"]
                    stats["imports_indexed"] += result["imports"]
            except Exception as e:
                logger.warning("Failed to analyze file", file=str(file_path), error=str(e))

        logger.info("Repository analysis complete", **stats)
        return stats

    async def _analyze_file(self, file_path: Path) -> dict[str, int] | None:
        """Analyze a single Python file"""
        try:
            source = file_path.read_text()
            tree = ast.parse(source, filename=str(file_path))

            file_id = self._generate_file_id(file_path)
            module = self._get_module_name(file_path)

            functions = []
            classes = []
            imports = []
            call_count = 0

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func = self._parse_function(node, file_id)
                    functions.append(func)
                    call_count += len(func.calls)

                elif isinstance(node, ast.ClassDef):
                    cls = self._parse_class(node, file_id)
                    classes.append(cls)

                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    imp = self._parse_import(node, file_id)
                    imports.append(imp)

            # Store nodes
            self.nodes[file_id] = CodeNode(
                id=file_id,
                name=file_path.name,
                file_id=file_id,
                node_type="file"
            )
            for func in functions:
                self.nodes[func.id] = func
            for cls in classes:
                self.nodes[cls.id] = cls
            for imp in imports:
                self.nodes[imp.id] = imp

            return {
                "functions": len(functions),
                "classes": len(classes),
                "calls": call_count,
                "imports": len(imports)
            }

        except SyntaxError as e:
            logger.warning("Syntax error in file", file=str(file_path), error=str(e))
            return None

    def _parse_function(self, node: ast.FunctionDef, file_id: str) -> FunctionNode:
        """Parse a function definition"""
        func_id = f"fn-{file_id}-{node.lineno}-{node.name}"

        # Find function calls
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)

        return FunctionNode(
            id=func_id,
            name=node.name,
            file_id=file_id,
            node_type="function",
            is_export=not node.name.startswith("_"),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            calls=calls
        )

    def _parse_class(self, node: ast.ClassDef, file_id: str) -> ClassNode:
        """Parse a class definition"""
        class_id = f"cls-{file_id}-{node.lineno}-{node.name}"

        # Get base classes
        extends = None
        if node.bases:
            if isinstance(node.bases[0], ast.Name):
                extends = node.bases[0].id

        methods = [
            f"fn-{file_id}-{m.lineno}-{m.name}"
            for m in node.body
            if isinstance(m, ast.FunctionDef)
        ]

        return ClassNode(
            id=class_id,
            name=node.name,
            file_id=file_id,
            node_type="class",
            class_type="class",
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            extends=extends,
            methods=methods
        )

    def _parse_import(self, node: ast.Import | ast.ImportFrom, file_id: str) -> ImportNode:
        """Parse an import statement"""
        import_id = f"imp-{file_id}-{node.lineno}"

        if isinstance(node, ast.Import):
            module = node.names[0].name.split('.')[0]
            names = [alias.name for alias in node.names]
            import_type = "import"
        else:  # ImportFrom
            module = node.module or ""
            names = [alias.name for alias in node.names]
            import_type = "from_import"

        return ImportNode(
            id=import_id,
            name=f"{import_type} {module}",
            file_id=file_id,
            node_type="import",
            module=module,
            import_type=import_type,
            names=names
        )

    async def get_function_context(
        self,
        function_name: str
    ) -> dict[str, object]:
        """
        Get comprehensive context for a function.

        Includes:
        - Function definition
        - Calling functions (who calls this)
        - Called functions (what this calls)
        - Related imports
        """
        context = {
            "function": None,
            "callers": [],
            "callees": [],
            "related_imports": []
        }

        # Find the function
        for node in self.nodes.values():
            if isinstance(node, FunctionNode) and node.name == function_name:
                context["function"] = {
                    "name": node.name,
                    "file": node.file_id,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "is_export": node.is_export
                }

                # Find callees (functions this calls)
                for called_func in node.calls:
                    for callee_node in self.nodes.values():
                        if isinstance(callee_node, FunctionNode) and callee_node.name == called_func:
                            context["callees"].append({
                                "name": callee_node.name,
                                "file": callee_node.file_id,
                                "line": callee_node.start_line
                            })

                break

        # Find callers (functions that call this)
        for node in self.nodes.values():
            if isinstance(node, FunctionNode):
                if function_name in node.calls:
                    context["callers"].append({
                        "name": node.name,
                        "file": node.file_id,
                        "line": node.start_line
                    })

        return context

    def _generate_file_id(self, file_path: Path) -> str:
        """Generate unique file ID"""
        rel_path = file_path.relative_to(self.project_path)
        return str(rel_path).replace("/", "_").replace(".", "_")

    def _get_module_name(self, file_path: Path) -> str:
        """Extract module name from file path"""
        parts = file_path.relative_to(self.project_path).parts
        if parts[-1] == "__init__.py":
            return ".".join(parts[:-1])
        return ".".join(parts[:-1] + (parts[-1].replace(".py", ""),))
```

#### Integration with LlamaIndex Adapter

```python
# mahavishnu/engines/llamaindex_adapter_enhanced.py

from llama_index.core import Document
from llama_index.core.node_parser import CodeSplitter
from mahavishnu.code_graph.analyzer import CodeGraphAnalyzer

class EnhancedLlamaIndexAdapter(LlamaIndexAdapter):
    """LlamaIndex adapter with code graph awareness"""

    def __init__(self, config):
        super().__init__(config)
        self.code_graphs: dict[str, CodeGraphAnalyzer] = {}

    async def _ingest_repository(self, repo_path: str, task_params: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest a repository with code graph analysis"""
        try:
            repo = Path(repo_path)

            # Build code graph first
            logger.info("Building code graph", repo=repo_path)
            graph_analyzer = CodeGraphAnalyzer(repo)
            graph_stats = await graph_analyzer.analyze_repository(repo_path)
            self.code_graphs[repo.name] = graph_analyzer

            # Use CodeSplitter for intelligent chunking
            code_splitter = CodeSplitter(
                language="python",
                chunk_lines=40,  # Split along function boundaries
                chunk_lines_overlap=5,
                max_chars=1500
            )

            # Load documents
            reader = SimpleDirectoryReader(
                input_dir=str(repo),
                recursive=True,
                required_exts=[".py"],
            )

            documents = reader.load_data()

            if not documents:
                return {
                    "repo": repo_path,
                    "status": "completed",
                    "result": {
                        "operation": "ingest",
                        "documents_ingested": 0,
                        "index_id": None
                    }
                }

            # Enhance documents with code graph context
            enhanced_documents = []
            for doc in documents:
                # Get function context from code graph
                file_path = Path(doc.metadata.get('file_path', ''))
                context = await self._get_document_context(graph_analyzer, file_path)

                # Add context to document metadata
                doc.metadata.update({
                    "code_graph": context,
                    "functions": context.get("functions", []),
                    "classes": context.get("classes", []),
                    "imports": context.get("imports", [])
                })

                enhanced_documents.append(doc)

            # Parse into nodes with code-aware chunking
            nodes = code_splitter.get_nodes_from_documents(enhanced_documents)

            # Create vector store index
            index = VectorStoreIndex(nodes)

            # Store index
            index_id = f"{repo.name}_{len(self.indices)}"
            self.indices[index_id] = index
            self.documents[index_id] = enhanced_documents

            return {
                "repo": repo_path,
                "status": "completed",
                "result": {
                    "operation": "ingest",
                    "documents_ingested": len(enhanced_documents),
                    "nodes_created": len(nodes),
                    "index_id": index_id,
                    "graph_stats": graph_stats
                }
            }

        except Exception as e:
            return {
                "repo": repo_path,
                "status": "failed",
                "error": f"Ingestion failed: {str(e)}"
            }

    async def _get_document_context(
        self,
        graph_analyzer: CodeGraphAnalyzer,
        file_path: Path
    ) -> dict[str, object]:
        """Get code graph context for a document"""
        # Get functions, classes, imports from graph
        functions = [
            {"name": n.name, "line": n.start_line, "exported": n.is_export}
            for n in graph_analyzer.nodes.values()
            if isinstance(n, FunctionNode) and n.file_id == graph_analyzer._generate_file_id(file_path)
        ]

        classes = [
            {"name": n.name, "line": n.start_line, "extends": n.extends}
            for n in graph_analyzer.nodes.values()
            if isinstance(n, ClassNode) and n.file_id == graph_analyzer._generate_file_id(file_path)
        ]

        imports = [
            {"module": n.module, "names": n.names}
            for n in graph_analyzer.nodes.values()
            if isinstance(n, ImportNode) and n.file_id == graph_analyzer._generate_file_id(file_path)
        ]

        return {
            "functions": functions,
            "classes": classes,
            "imports": imports
        }

    async def _query_index_enhanced(
        self,
        repo_path: str,
        task_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Query with code graph context"""
        result = await super()._query_index(repo_path, task_params)

        if result.get("status") == "completed":
            # Enhance results with function context
            graph_analyzer = self.code_graphs.get(Path(repo_path).name)
            if graph_analyzer:
                for source in result["result"].get("sources", []):
                    # Add caller/callee information
                    function_name = source.get("function_name")
                    if function_name:
                        context = await graph_analyzer.get_function_context(function_name)
                        source["callers"] = context.get("callers", [])
                        source["callees"] = context.get("callees", [])

        return result
```

#### MCP Tools

```python
# mahavishnu/mcp/tools/code_graph_tools.py

@mcp.tool()
async def index_code_graph(
    repository_path: str
) -> dict[str, object]:
    """
    Analyze and index codebase structure.

    Builds a graph of files, functions, classes, and their relationships.
    Enables intelligent RAG context and better search results.

    Args:
        repository_path: Path to repository directory

    Returns:
        Indexing statistics
    """
    try:
        analyzer = CodeGraphAnalyzer(Path(repository_path))
        stats = await analyzer.analyze_repository(repository_path)

        return {
            "success": True,
            "stats": stats,
            "message": f"Indexed {stats['files_indexed']} files with "
                      f"{stats['functions_indexed']} functions and "
                      f"{stats['classes_indexed']} classes"
        }

    except Exception as e:
        logger.error("Code graph indexing failed", error=str(e))
        return {"success": False, "error": str(e)}

@mcp.tool()
async def get_function_context(
    repository_path: str,
    function_name: str
) -> dict[str, object]:
    """
    Get comprehensive context for a function.

    Includes function definition, callers, callees, and related imports.

    Args:
        repository_path: Path to repository
        function_name: Function name

    Returns:
        Function context with callers and callees
    """
    try:
        # Get or create analyzer
        analyzer = CodeGraphAnalyzer(Path(repository_path))
        context = await analyzer.get_function_context(function_name)

        return {
            "success": True,
            "context": context
        }

    except Exception as e:
        logger.error("Failed to get function context", error=str(e))
        return {"success": False, "error": str(e)}
```

#### Benefits for Mahavishnu

1. **Smarter RAG Pipelines**
   - Code-aware chunking preserves semantic boundaries
   - Better embeddings with structural context
   - Related code retrieved together

2. **Enhanced Search Results**
   - Find functions + their callers/callees
   - Understand code relationships
   - Provide context about why code is relevant

3. **Quality Metrics**
   - Detect complex functions (high cyclomatic complexity)
   - Identify tight coupling
   - Find code smells

4. **Better Context Compaction**
   - Keep related code together
   - Prioritize exported functions
   - Preserve call chain context

---

### 3. Portable Workflow Configuration ⭐⭐⭐⭐
**Priority: MEDIUM-HIGH** | **Effort: LOW-MEDIUM** | **Alignment: GOOD**

AI Maestro's ability to export/import agent configurations would be valuable for Mahavishnu workflow sharing.

#### What AI Maestro Has

- **Export agents to .zip** with full configuration
- **Import with conflict detection**
- **Preview before importing**
- **Cross-host transfer**
- **Clone & backup agents**

#### Why This Matters for Mahavishnu

Mahavishnu orchestrates workflows across repositories. Portable configuration enables:

1. **Workflow Templates**
   - Export successful workflow configurations
   - Share across teams
   - Standardize orchestration patterns

2. **Cross-Environment Migration**
   - Dev → Staging → Production
   - Laptop → Desktop → CI/CD
   - Team member collaboration

3. **Backup & Version Control**
   - Save workflow states before refactoring
   - Rollback to previous configurations
   - Track workflow evolution

#### Proposed Implementation

```python
# mahavishnu/config/portable_workflows.py

import zipfile
import json
from pathlib import Path
from datetime import datetime
from mahavishnu.core.config import MahavishnuSettings
import structlog

logger = structlog.get_logger(__name__)

@mcp.tool()
async def export_workflow_config(
    workflow_id: str,
    include_reflections: bool = True,
    include_quality_history: bool = True,
    include_repos_config: bool = True
) -> dict[str, object]:
    """
    Export workflow configuration to a portable zip file.

    Creates a backup of workflow state, reflections, and configuration
    that can be imported into another Mahavishnu instance.

    Args:
        workflow_id: Workflow identifier
        include_reflections: Include stored reflections (if using Session Buddy)
        include_quality_history: Include quality score history
        include_repos_config: Include repos.yaml configuration

    Returns:
        Zip file path and metadata
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = f"mahavishnu_workflow_{workflow_id}_{timestamp}.zip"
        export_path = Path.home() / ".claude" / "exports" / zip_name
        export_path.parent.mkdir(parents=True, exist_ok=True)

        config_data = {
            "exported_at": datetime.now().isoformat(),
            "workflow_id": workflow_id,
            "version": "0.1.0",
            "includes": {
                "reflections": include_reflections,
                "quality_history": include_quality_history,
                "repos_config": include_repos_config
            }
        }

        with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Export configuration
            zipf.writestr("config.json", json.dumps(config_data, indent=2))

            # Export workflow definition
            workflow_def = await _get_workflow_definition(workflow_id)
            if workflow_def:
                zipf.writestr(
                    "workflow.json",
                    json.dumps(workflow_def, indent=2)
                )

            # Export repos.yaml if requested
            if include_repos_config:
                repos_file = Path.cwd() / "repos.yaml"
                if repos_file.exists():
                    zipf.write(repos_file, "repos.yaml")

            # Export quality history if requested
            if include_quality_history:
                quality_file = Path.home() / ".claude" / "data" / "quality_history.json"
                if quality_file.exists():
                    zipf.write(quality_file, "quality_history.json")

        logger.info(
            "Workflow configuration exported",
            workflow_id=workflow_id,
            path=str(export_path),
            size_bytes=export_path.stat().st_size
        )

        return {
            "success": True,
            "export_path": str(export_path),
            "size_bytes": export_path.stat().st_size,
            "config": config_data
        }

    except Exception as e:
        logger.error("Failed to export workflow config", error=str(e))
        return {"success": False, "error": str(e)}

@mcp.tool()
async def import_workflow_config(
    zip_path: str,
    merge_strategy: Literal["preview", "merge", "replace"] = "preview"
) -> dict[str, object]:
    """
    Import workflow configuration from zip file.

    Args:
        zip_path: Path to exported zip file
        merge_strategy:
            - preview: Show what would be imported without making changes
            - merge: Merge with existing configuration
            - replace: Replace existing configuration

    Returns:
        Import plan with conflicts and changes
    """
    try:
        zip_file = Path(zip_path)
        if not zip_file.exists():
            return {"success": False, "error": "Zip file not found"}

        import_plan = {
            "config": None,
            "workflow": None,
            "repos": None,
            "quality_history": None,
            "conflicts": [],
            "changes": []
        }

        with zipfile.ZipFile(zip_file, 'r') as zipf:
            # Read configuration
            if 'config.json' in zipf.namelist():
                config_data = json.loads(zipf.read('config.json'))
                import_plan["config"] = config_data

            # Preview workflow
            if 'workflow.json' in zipf.namelist():
                workflow_data = json.loads(zipf.read('workflow.json'))
                import_plan["workflow"] = workflow_data
                import_plan["changes"].append(
                    f"Would import workflow: {workflow_data.get('name', 'unknown')}"
                )

            # Check for conflicts
            existing_workflow = await _get_workflow_definition(
                import_plan["config"]["workflow_id"]
            )
            if existing_workflow:
                import_plan["conflicts"].append(
                    f"Workflow already exists: {import_plan['config']['workflow_id']}"
                )

        # Preview mode - just return the plan
        if merge_strategy == "preview":
            return {
                "success": True,
                "merge_strategy": "preview",
                "import_plan": import_plan,
                "message": "Preview mode - no changes made"
            }

        # Actually perform import
        if merge_strategy in ["merge", "replace"]:
            logger.info(
                "Importing workflow configuration",
                zip_path=zip_path,
                strategy=merge_strategy
            )
            # ... import logic here ...

        return {
            "success": True,
            "merge_strategy": merge_strategy,
            "import_plan": import_plan,
            "message": f"Configuration imported with {merge_strategy} strategy"
        }

    except Exception as e:
        logger.error("Failed to import workflow config", error=str(e))
        return {"success": False, "error": str(e)}
```

#### Use Cases

```python
# 1. Workflow template sharing
await export_workflow_config(
    workflow_id="backend-api-pipeline",
    include_repos_config=True
)

# Team members import with merge strategy
await import_workflow_config(
    "/path/to/export.zip",
    merge_strategy="merge"
)

# 2. Cross-environment migration (dev → prod)
await export_workflow_config("production-workflow")

# Transfer to production server
await import_workflow_config(
    "/path/to/export.zip",
    merge_strategy="replace"
)

# 3. Backup before refactoring
await export_workflow_config(
    "current-stable-workflow",
    include_quality_history=True
)
```

---

## ❌ Features That DON'T Fit Mahavishnu

### Peer Mesh Network
**Why not:** Mahavishnu is an MCP server (single instance), not a distributed multi-agent system. The mesh network is specific to AI Maestro's tmux-based architecture.

### tmux Session Management
**Why not:** Mahavishnu doesn't manage terminal sessions - it orchestrates workflows via MCP protocol through adapters.

### Web Dashboard
**Why not:** Mahavishnu is designed to work through MCP tool calls, not provide its own dashboard. Could be added as a separate frontend project.

### Agent Notes (localStorage)
**Why not:** Mahavishnu uses vector databases and reflection systems (via Session Buddy integration) for persistence - browser-based notes would be redundant.

---

## 📊 Implementation Priority

```
Phase 1 (High Impact, Medium Effort):
  ✅ Inter-Repository Messaging System
     - Build on existing Mahavishnu architecture
     - Add DuckDB schema for messages
     - Implement send/list/forward MCP tools
     - Integrate with adapter execution
     - Estimated effort: 3-4 days

Phase 2 (High Impact, High Effort):
  ⭐ Code Graph Visualization & Indexing
     - Add AST parsing for Python (expand to JS/TS later)
     - Create graph schema in DuckDB/vector store
     - Build code graph analyzer
     - Integrate with LlamaIndex adapter for smart chunking
     - Estimated effort: 5-7 days

Phase 3 (Medium Impact, Low-Medium Effort):
  🔧 Portable Workflow Configuration
     - Export/import workflow configs
     - Conflict detection and resolution
     - Zip file packaging
     - Cross-environment migration
     - Estimated effort: 2-3 days

Phase 4 (Future Enhancement):
  📋 Auto-Generated Documentation
     - Depends on Code Graph infrastructure
     - Extract docstrings during indexing
     - Integrate with LlamaIndex for documentation search
     - Estimated effort: 2-3 days
```

---

## 🎁 Integration Opportunities

### Mahavishnu + AI Maestro + Session Buddy

These three systems can work together:

```
┌─────────────────────┐
│   AI Maestro        │  ← Multi-agent orchestrator (tmux + dashboard)
│   (Agents)          │
└──────────┬──────────┘
           │ Messages via mesh network
           ↓
┌─────────────────────┐
│   Mahavishnu        │  ← Multi-engine orchestrator (MCP + adapters)
│   (Workflows)       │     - Receives agent notifications
└──────────┬──────────┘     - Orchestrates Prefect/Agno/LlamaIndex
           │ Workflow events
           ↓
┌─────────────────────┐
│   Session Buddy     │  ← Memory & context (MCP server)
│   (Memory)          │     - Stores reflections
└─────────────────────┘     - Provides context to all
```

**Example Workflow:**
```bash
# 1. AI Maestro backend agent completes API endpoint
# - Sends notification via AI Maestro mesh network

# 2. Mahavishnu receives notification
# - Triggers LlamaIndex adapter to re-index backend repo
# - Notifies frontend repo via inter-repository messaging
# - Triggers Prefect workflow for integration testing

# 3. Session Buddy provides context
# - Finds similar APIs built in the past
# - Provides quality metrics from previous workflows
# - Stores reflection for future reference
```

---

## 🚀 Recommended Next Steps

### Option 1: Inter-Repository Messaging System
I can design and implement the complete messaging system with:
- Full database schema (DuckDB)
- MCP tool implementations
- Integration with existing adapters
- Real-world use case examples
- Test suite
- Documentation

### Option 2: Code Graph Proof-of-Concept
I can create a working prototype with:
- Python AST parser
- DuckDB graph storage
- Integration with LlamaIndex adapter
- Smart document chunking
- Enhanced RAG retrieval
- Performance benchmarks

### Option 3: Portable Workflow System
I can build the export/import system with:
- Workflow configuration packaging
- Cross-environment migration
- Template sharing system
- Conflict resolution
- Version control integration

### Option 4: Integration Architecture
I can design the complete integration between:
- AI Maestro (agent notifications)
- Mahavishnu (workflow orchestration)
- Session Buddy (memory & context)
- Example workflows
- API specifications

Let me know which direction you'd like to pursue!

---

## 📚 References

- **AI Maestro GitHub:** https://github.com/23blocks-OS/ai-maestro
- **AI Maestro Documentation:** https://ai-maestro.23blocks.com/
- **Mahavishnu Repository:** https://github.com/lesleslie/mahavishnu
- **Session Buddy Analysis:** `../session-buddy/AI_MAESTRO_FEATURE_ANALYSIS.md`
- **LlamaIndex Documentation:** https://docs.llamaindex.ai/
- **CozoDB (Graph Database):** https://www.cozodb.org/

---

**Document Version:** 1.0
**Last Updated:** 2025-01-24
**Author:** Claude Code with analysis of AI Maestro v0.19.0 for Mahavishnu
