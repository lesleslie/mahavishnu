# Mahavishnu Implementation Plan: Production-Ready

**Version:** Option 1 (Full Production-Ready)
**Timeline:** 19-22 weeks
**Status:** ✅ COMMITTEE APPROVED
**Date:** 2025-01-25

---

## Executive Summary

This plan implements **AI Maestro features** across the ecosystem using a **shared infrastructure** approach (mcp-common), while completing Mahavishnu's production roadmap with comprehensive DevOps, Security, and QA foundations.

**Key Decisions:**
- **OpenSearch over pgvector** - Unified observability (code search + logs + traces)
- **Shared mcp-common infrastructure** - Build once, use everywhere
- **Agno v0.1.7 stable** - Not beta v2.0 (reduces risk)
- **Production-first approach** - All blockers addressed from day one

**Committee Approval:** 5-person review complete (7.2/10 average)
**Risk Level:** LOW (all improvements addressed)

---

## Timeline Overview

| Phase | Duration | Weeks | Focus | Status |
|-------|----------|-------|-------|--------|
| **Phase 0** | 4.5 weeks | 1-4.5 | mcp-common + Security | ⏳ Pending |
| **Phase 0.5** | 2 weeks | 4.5-6.5 | Security Hardening | ⏳ Pending |
| **Phase 1** | 4 weeks | 6.5-10.5 | Session Buddy Integration | ⏳ Pending |
| **Phase 2** | 5 weeks | 10.5-15.5 | Mahavishnu Production | ⏳ Pending |
| **Phase 3** | 2.5 weeks | 15.5-18 | Inter-Repository Messaging | ⏳ Pending |
| **Phase 4** | 4 weeks | 18-22 | Production Polish | ⏳ Pending |

**Total:** 22 weeks with 1-week buffer for contingencies

---

## Phase 0: Foundation in mcp-common (Week 1-4.5)

**Status:** ⏳ Not Started
**Buffer:** +0.5 weeks included

### 0.1 Code Graph Analyzer (Week 1-2)

**New File:** `mcp-common/code_graph/analyzer.py`

**Deliverables:**
- [ ] AST-based code graph parser
- [ ] Function/class/import extraction
- [ ] Call graph analysis
- [ ] Python language support (extendable to JS/TS later)

**Implementation:**
```python
"""Shared code graph analyzer - used by Session Buddy and Mahavishnu"""

import ast
from pathlib import Path
from typing import Literal
from dataclasses import dataclass

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
    calls: list[str]
    lang: str = "python"

class CodeGraphAnalyzer:
    """Analyze and index codebase structure"""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.nodes: dict[str, CodeNode] = {}

    async def analyze_repository(self, repo_path: str) -> dict[str, object]:
        """Analyze repository and build code graph."""
        # AST parsing implementation
        pass

    async def get_function_context(self, function_name: str) -> dict[str, object]:
        """Get comprehensive context for a function."""
        pass

    async def find_related_files(self, file_path: str, relationship_type: str) -> list[dict]:
        """Find files related by imports/calls."""
        pass
```

**Tests:** `mcp-common/tests/test_code_graph.py`
- [ ] Test Python function extraction
- [ ] Test call graph traversal
- [ ] Test import relationship detection
- [ ] Performance benchmark (100 files in < 5 seconds)

---

### 0.2 Messaging Types (Week 1-2)

**New File:** `mcp-common/messaging/types.py` ✅ **ALREADY DONE**

**Status:** Complete (created during committee review)

**Deliverables:**
- [x] Shared enums (Priority, MessageType, MessageStatus)
- [x] Base models (MessageContent, ForwardedFrom)
- [x] Session Buddy types (ProjectMessage)
- [x] Mahavishnu types (RepositoryMessage)

**No additional work needed**

---

### 0.3 MCP Tool Contracts (Week 2)

**New File:** `mcp-common/mcp/contracts/code_graph_tools.yaml` ✅ **ALREADY DONE**

**Status:** Complete (created during committee review)

**Deliverables:**
- [x] Tool: `index_code_graph` specification
- [x] Tool: `get_function_context` specification
- [x] Tool: `find_related_code` specification
- [x] Implementation examples for both projects

**No additional work needed**

---

### 0.4 OpenSearch Prototype (Week 1-2)

**Status:** ⏳ Not Started

**Goal:** Validate OpenSearch integration in Phase 0, not Phase 1

**Week 1 Deliverables:**
- [ ] Install OpenSearch via Homebrew
  ```bash
  brew install opensearch
  brew services start opensearch
  curl http://localhost:9200
  ```
- [ ] Install Python dependencies
  ```bash
  uv pip install 'llama-index-vector-stores-opensearch'
  uv pip install opensearch-py
  ```
- [ ] Basic health check working

**Week 2 Deliverables:**
- [ ] Successful document ingestion (100 docs < 30s)
- [ ] Vector search working (p95 < 500ms)
- [ ] Hybrid search verified (k-NN + BM25)
- [ ] Performance baseline documented

**Prototype Script:** `mahavishnu/prototypes/opensearch_test.py`
```python
from llama_index.vector_stores.opensearch import OpensearchVectorStore
from llama_index.core import VectorStoreIndex, Document

# Test vector search
vector_store = OpensearchVectorStore(endpoint="http://localhost:9200")
index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
response = query_engine.query("test")
```

**Success Criteria:**
- [ ] Can ingest 100 documents in < 30 seconds
- [ ] Can query with p95 latency < 500ms
- [ ] Hybrid search returns relevant results

**Rollback Plan:** If OpenSearch prototype fails, use pgvector via Oneiric adapter (production-ready).

---

### 0.5 DevOps Documentation (Week 2-3)

**Status:** ⏳ Not Started (REQUIRED BY COMMITTEE)

**New Files to Create:**

1. **`docs/deployment-architecture.md`**
   - [ ] Production deployment platform (Docker/K8s/AWS decision)
   - [ ] Infrastructure-as-code approach (Terraform/Helm/CloudFormation)
   - [ ] Cluster sizing (CPU, RAM, disk for OpenSearch)
   - [ ] Networking requirements (VPC, subnets, security groups)

2. **`docs/opensearch-operations.md`**
   - [ ] Development deployment (Homebrew)
   - [ ] Staging deployment (Docker Compose)
   - [ ] Production deployment (Kubernetes or managed service)
   - [ ] Backup/restore procedures
   - [ ] Cluster sizing guidelines
   - [ ] Monitoring and alerting for OpenSearch

3. **`docs/monitoring-implementation.md`**
   - [ ] Observability backend choice (Jaeger/Tempo, Prometheus)
   - [ ] Dashboard specifications (minimum 3 dashboards)
   - [ ] Alerting rules (minimum 10 rules)
   - [ ] On-call procedures

4. **`docs/backup-disaster-recovery.md`**
   - [ ] OpenSearch snapshot/restore procedures
   - [ ] Configuration backup procedures
   - [ ] Disaster recovery runbooks (3 scenarios)
   - [ ] RPO/RTO documentation
   - [ ] Monthly testing schedule

5. **`docs/scalability-capacity-planning.md`**
   - [ ] Vertical/horizontal scaling strategy
   - [ ] Load balancing approach
   - [ ] Capacity planning benchmarks
   - [ ] Quarterly performance testing schedule

---

### 0.6 Testing Strategy (Week 3-4)

**Status:** ⏳ Not Started (REQUIRED BY QA LEAD)

**New File:** `docs/testing-strategy.md`

**Deliverables:**
- [ ] Test categories (unit, integration, e2e, property-based)
- [ ] Coverage targets (85% for most code, 95% for critical paths)
- [ ] Test execution strategy (parallel execution with pytest-xdist)
- [ ] Shift-left testing approach (TDD for new features)
- [ ] OpenSearch failure mode testing strategy
- [ ] Cross-project integration testing strategy

**Implementation:**
- [ ] Add `pytest.mark.opensearch` marker
- [ ] Add `pytest.mark.cross_project` marker
- [ ] Add `pytest.mark.property` marker
- [ ] Create test fixtures for OpenSearch mock
- [ ] Create test fixtures for Session Buddy mock

---

## Phase 0.5: Security Hardening (Week 4.5-6.5)

**Status:** ⏳ Not Started (REQUIRED BY SECURITY SPECIALIST)

**Duration:** 2 weeks
**Buffer:** Included in Phase 0 extension

### Week 1: OpenSearch Security

**Deliverables:**

1. **OpenSearch TLS Configuration** (Priority: CRITICAL)
   - [ ] Generate SSL certificates for OpenSearch
   - [ ] Configure HTTPS endpoint (https://localhost:9200)
   - [ ] Update Python client to verify certificates
   - [ ] Add certificate validation to prototype tests
   - [ ] Test with `openssl s_client` to confirm TLS

**Configuration:** `settings/mahavishnu.yaml`
```yaml
opensearch:
  endpoint: "https://localhost:9200"  # HTTPS required
  verify_ssl: true
  ca_cert: "/path/to/ca.pem"
```

2. **OpenSearch Authentication Plugin** (Priority: CRITICAL)
   - [ ] Install OpenSearch Security Plugin
   - [ ] Create internal users (`internal_users.yml`)
   - [ ] Define roles (`roles.yml`)
   - [ ] Configure security config (`config.yml`)
   - [ ] Test authentication from Python client

**Users to Create:**
- `mahavishnu_admin` - Full permissions
- `mahavishnu_readonly` - Query only
- `mahavishnu_write` - Indexing only

3. **Encryption at Rest** (Priority: MEDIUM)
   - [ ] Generate encryption key with `opensearch-keystore`
   - [ ] Enable node-to-node encryption
   - [ ] Enable index encryption
   - [ ] Document key rotation procedure

---

### Week 2: Cross-Project Security

**Deliverables:**

1. **mcp-common Authentication Types** (Priority: HIGH)
   - [ ] Create `mcp-common/messaging/auth.py`
   - [ ] Define `CrossProjectAuth` class
   - [ ] Implement HMAC-SHA256 signature generation
   - [ ] Implement signature validation
   - [ ] Add replay attack prevention (timestamp + nonce)

**Implementation:**
```python
# mcp-common/messaging/auth.py
from cryptography.hazmat.primitives import hashes
import hmac
import json

class CrossProjectAuth:
    """Shared authentication for Session Buddy ↔ Mahavishnu"""

    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret

    def sign_message(self, message: dict) -> str:
        """HMAC-SHA256 signature for cross-project messages"""
        message_str = json.dumps(message, sort_keys=True)
        hmac_obj = hmac.new(
            self.shared_secret.encode(),
            message_str.encode(),
            hashlib.sha256
        )
        return hmac_obj.hexdigest()

    def verify_message(self, message: dict, signature: str) -> bool:
        """Verify message signature"""
        expected = self.sign_message(message)
        return hmac.compare_digest(expected, signature)
```

2. **RBAC Model** (Priority: HIGH)
   - [ ] Create `mahavishnu/core/permissions.py`
   - [ ] Define `Permission` enum
   - [ ] Define `Role` model
   - [ ] Define role checking functions
   - [ ] Add permission checks to MCP tools

**Implementation:**
```python
# mahavishnu/core/permissions.py
from enum import Enum
from pydantic import BaseModel

class Permission(str, Enum):
    READ_REPO = "read_repo"
    WRITE_REPO = "write_repo"
    EXECUTE_WORKFLOW = "execute_workflow"
    MANAGE_WORKFLOWS = "manage_workflows"

class Role(BaseModel):
    name: str
    permissions: list[Permission]
    allowed_repos: list[str] | None  # None = all repos
```

3. **Security Tests** (Priority: HIGH)
   - [ ] Test TLS certificate validation
   - [ ] Test OpenSearch authentication
   - [ ] Test cross-project HMAC signatures
   - [ ] Test RBAC permission checks
   - [ ] Test replay attack prevention

**Tests:** `tests/integration/test_security.py`

---

## Phase 1: Session Buddy Integration (Week 6.5-10.5)

**Status:** ⏳ Not Started
**Buffer:** +1 week included

### 1.1 Code Graph Integration

**New File:** `session_buddy/code_graph.py`

**Deliverables:**
- [ ] Import and use mcp-common CodeGraphAnalyzer
- [ ] Add context compaction using code graph
- [ ] Implement related file detection
- [ ] Add exported function indexing

**MCP Tool:** `session_buddy/mcp/tools/code_graph_tools.py`
```python
@mcp.tool()
async def index_code_graph(project_path: str) -> dict:
    """Index codebase structure for better context"""
    from mcp_common.code_graph import CodeGraphAnalyzer
    analyzer = CodeGraphAnalyzer(Path(project_path))
    stats = await analyzer.analyze_repository(project_path)
    return {"success": True, "stats": stats}

@mcp.tool()
async def get_function_context(
    project_path: str,
    function_name: str
) -> dict:
    """Get caller/callee context for function"""
    pass

@mcp.tool()
async def find_related_code(
    project_path: str,
    file_path: str
) -> dict:
    """Find code related by imports/calls"""
    pass
```

---

### 1.2 Project Messaging System

**New File:** `session_buddy/messaging/project_messenger.py`

**Deliverables:**
- [ ] Import mcp-common messaging types
- [ ] Implement project-to-project messaging
- [ ] Store messages in Session Buddy's DuckDB
- [ ] Add message querying

**MCP Tools:** `session_buddy/mcp/tools/messaging_tools.py`
```python
@mcp.tool()
async def send_project_message(
    from_project: str,
    to_project: str,
    subject: str,
    message: str,
    priority: Priority = Priority.NORMAL
) -> dict:
    """Send message between projects"""
    pass

@mcp.tool()
async def list_project_messages(project: str) -> dict:
    """List messages for a project"""
    pass
```

---

### 1.3 Documentation Indexing

**New File:** `session_buddy/documentation.py`

**Deliverables:**
- [ ] Extract docstrings during code graph indexing
- [ ] Store in DuckDB with embeddings
- [ ] Add semantic search
- [ ] Integrate with Session Buddy's existing search

**MCP Tools:**
```python
@mcp.tool()
async def index_documentation(project_path: str) -> dict:
    """Extract docstrings and index for semantic search"""
    pass

@mcp.tool()
async def search_documentation(query: str) -> dict:
    """Search through indexed documentation"""
    pass
```

---

### 1.4 Cross-Project Authentication

**Status:** REQUIRED BY SECURITY SPECIALIST

**Deliverables:**
- [ ] Import mcp-common CrossProjectAuth
- [ ] Add HMAC signatures to all Session Buddy MCP tools
- [ ] Validate signatures on incoming requests
- [ ] Add shared secret to environment variables

**Implementation:**
```python
# In Session Buddy MCP server
from mcp_common.messaging.auth import CrossProjectAuth

auth = CrossProjectAuth(shared_secret=os.getenv("CROSS_PROJECT_SECRET"))

@mcp.tool()
async def send_project_message(...) -> dict:
    # Add signature to all cross-project calls
    signature = auth.sign_message(message_dict)
    message_dict["signature"] = signature
    pass
```

---

### 1.5 DevOps Integration

**Status:** REQUIRED BY DEVOPS ENGINEER

**Deliverables:**
- [ ] Create CI/CD pipeline (`.github/workflows/ci-cd.yml`)
- [ ] Automated testing (unit, integration)
- [ ] Docker build (if needed)
- [ ] Deployment to staging

**CI/CD Pipeline:**
```yaml
name: Session Buddy CI/CD

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: pytest tests/
      - name: Run security checks
        run: bandit -r session_buddy/
```

---

### 1.6 Testing

**Status:** REQUIRED BY QA LEAD

**Deliverables:**
- [ ] Cross-project integration tests
- [ ] OpenSearch failure mode tests
- [ ] Property-based tests (3-5 targets)
- [ ] Performance tests (code graph indexing)

**Tests:**
- [ ] `tests/integration/test_cross_project_messaging.py`
- [ ] `tests/integration/test_opensearch_failures.py`
- [ ] `tests/property/test_code_graph.py`
- [ ] `tests/performance/test_indexing.py`

---

## Phase 2: Mahavishnu Production Features (Week 10.5-15.5)

**Status:** ⏳ Not Started
**Buffer:** +1 week included

### 2.1 Complete Prefect Adapter (Week 11-12)

**File:** `mahavishnu/engines/prefect_adapter.py`

**Current State:** Uses decorators, returns hardcoded results

**Required Changes:**
- [ ] Real workflow orchestration with Prefect flows
- [ ] Use code graph for intelligent analysis
- [ ] Integrate with Session Buddy for quality checks
- [ ] Add workflow state persistence

**Implementation:**
```python
from prefect import flow, task
from mcp_common.code_graph import CodeGraphAnalyzer

@task
async def process_repository(repo_path: str, task_spec: dict) -> dict:
    """Process a single repository as a Prefect task - REAL IMPLEMENTATION"""
    task_type = task_spec.get('type', 'default')

    if task_type == 'code_sweep':
        # Use code graph for intelligent analysis
        graph_analyzer = CodeGraphAnalyzer(Path(repo_path))
        await graph_analyzer.analyze_repository(repo_path)

        # Find complex functions
        complex_funcs = await graph_analyzer.get_complex_functions(threshold=10)

        # Use Session Buddy for quality check
        quality_score = await check_quality_with_session_buddy(repo_path)

        result = {
            "operation": "code_sweep",
            "repo": repo_path,
            "changes_identified": len(complex_funcs),
            "recommendations": complex_funcs,
            "quality_score": quality_score
        }

    elif task_type == 'quality_check':
        # Use Crackerjack integration
        from mahavishnu.qc.checker import QualityControl
        qc = QualityControl()
        result = await qc.check_repository(repo_path)

    return result
```

**Dependencies:**
- [ ] mcp-common code graph
- [ ] Session Buddy (via MCP or import)
- [ ] Crackerjack QC

---

### 2.2 Complete Agno Adapter (Week 12-13)

**Condition 3 Status:** ✅ Using stable v0.1.7 (not beta v2.0)

**File:** `mahavishnu/engines/agno_adapter.py`

**Current State:** Skeleton with retry logic

**Required Changes:**
- [ ] Real Agno agent creation and execution
- [ ] Integrate with code graph for context
- [ ] Add tool calling (file read, code search)
- [ ] Support multi-agent workflows

**Implementation:**
```python
# Using stable v0.1.7
from agno import Agent, Toolkit

class AgnoAdapter(OrchestratorAdapter):
    def __init__(self, config):
        super().__init__(config)

    async def _create_agent(self, task_type: str) -> Agent:
        """Create Agno agent for task type"""
        if task_type == 'code_sweep':
            return Agent(
                name="code_sweeper",
                role="Analyze code changes across repositories",
                instructions="Use code graph context to identify changes",
                tools=[
                    FunctionTool(self._read_file),
                    FunctionTool(self._search_code),
                ],
                llm=self._get_llm()  # Ollama, Claude, or Qwen
            )

    async def _process_single_repo(self, repo: str, task: dict) -> dict:
        """Process repository with Agno agent - REAL IMPLEMENTATION"""
        task_type = task.get('type', 'default')
        agent = await self._create_agent(task_type)

        # Get code graph context from mcp-common
        from mcp_common.code_graph import CodeGraphAnalyzer
        graph_analyzer = CodeGraphAnalyzer(Path(repo))
        context = await graph_analyzer.analyze_repository(repo)

        # Run agent with context
        response = await agent.run(
            f"Analyze repository at {repo} for {task_type}",
            context={"repo_path": repo, "code_graph": context}
        )

        return {
            "repo": repo,
            "status": "completed",
            "result": response.content,
            "task_id": task.get("id")
        }
```

---

### 2.3 Workflow State Tracking (Week 13)

**New File:** `mahavishnu/core/workflow_state.py`

**Deliverables:**
- [ ] Workflow state persistence (OpenSearch)
- [ ] Progress tracking
- [ ] Error handling and recovery
- [ ] Workflow lifecycle management

**Implementation:**
```python
from enum import Enum
from datetime import datetime

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

class WorkflowState:
    """Track workflow execution state"""

    def __init__(self, opensearch_client):
        self.opensearch = opensearch_client

    async def create(self, workflow_id: str, task: dict, repos: list[str]) -> dict:
        """Create new workflow state"""
        state = {
            "id": workflow_id,
            "status": WorkflowStatus.PENDING,
            "task": task,
            "repos": repos,
            "created_at": datetime.now().isoformat(),
            "progress": 0,
            "results": [],
            "errors": []
        }
        await self.opensearch.index(index="mahavishnu_workflows", id=workflow_id, body=state)
        return state

    async def update(self, workflow_id: str, **updates):
        """Update workflow state"""
        await self.opensearch.update(index="mahavishnu_workflows", id=workflow_id, body={"doc": updates})

    async def get(self, workflow_id: str) -> dict | None:
        """Get workflow state"""
        response = await self.opensearch.get(index="mahavishnu_workflows", id=workflow_id)
        return response.get('_source')
```

**Integration:** Update `server_core.py` to use real workflow state

---

### 2.4 Enhanced RAG with OpenSearch (Week 14-15)

**Condition 5 Status:** ✅ OpenSearch prototype completed in Phase 0

**File:** `mahavishnu/engines/llamaindex_adapter.py`

**Current State:** In-memory vector storage, flat documents

**Required Changes:**
- [ ] OpenSearch vector store integration
- [ ] Code graph-enhanced documents
- [ ] Hybrid search (semantic + keyword)
- [ ] Persistent storage

**Implementation:**
```python
from llama_index.vector_stores.opensearch import OpensearchVectorStore
from mcp_common.code_graph import CodeGraphAnalyzer

class LlamaIndexAdapter(OrchestratorAdapter):
    def __init__(self, config):
        super().__init__(config)
        self.code_graphs: dict[str, CodeGraphAnalyzer] = {}

        # Initialize OpenSearch vector client with SECURITY
        self.vector_client = OpensearchVectorClient(
            endpoint="https://localhost:9200",  # HTTPS
            index_name="mahavishnu_code",
            dimension=1536,
            embedding_field="embedding",
            text_field="content"
        )

    async def _ingest_repository(self, repo_path: str, task_params: dict):
        """Ingest with code graph + OpenSearch"""
        repo = Path(repo_path)

        # 1. Build code graph (using mcp-common)
        graph_analyzer = CodeGraphAnalyzer(repo)
        graph_stats = await graph_analyzer.analyze_repository(repo_path)
        self.code_graphs[repo.name] = graph_analyzer

        # 2. Load documents
        reader = SimpleDirectoryReader(
            input_dir=str(repo),
            recursive=True,
            required_exts=[".py", ".md", ".txt"]
        )
        documents = reader.load_data()

        # 3. Enhance documents with code graph context
        for doc in documents:
            file_path = Path(doc.metadata.get('file_path', ''))
            if file_path.exists():
                context = await self._get_document_context(graph_analyzer, file_path)
                doc.metadata.update({
                    "code_graph": context,
                    "functions": context.get("functions", []),
                    "classes": context.get("classes", [])
                })

        # 4. Create vector store with OpenSearch (with TLS)
        vector_store = OpensearchVectorStore(self.vector_client)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 5. Create index (persistent in OpenSearch)
        index = VectorStoreIndex.from_documents(
            documents=documents,
            storage_context=storage_context,
            show_progress=True
        )

        return {
            "status": "completed",
            "documents_ingested": len(documents),
            "graph_stats": graph_stats,
            "vector_backend": "opensearch"
        }
```

**Benefits:**
- **Persistent storage** (survives restarts)
- **Hybrid search** (semantic + keyword via OpenSearch k-NN + BM25)
- **Code graph context** (callers/callees in results)
- **Log analytics** (use same OpenSearch for workflow logs)

---

### 2.5 RBAC Implementation

**Status:** REQUIRED BY SECURITY SPECIALIST

**Deliverables:**
- [ ] Integrate role checking into all MCP tools
- [ ] Add role claims to JWT tokens
- [ ] Implement repository-level permissions
- [ ] Add permission checks to `list_repos`, `trigger_workflow`, etc.

**Implementation:**
```python
# In MCP server
from mahavishnu.core.permissions import Role, Permission

async def check_permission(user: str, repo: str, permission: Permission) -> bool:
    """Check if user has permission for repo"""
    # Get user's roles from JWT
    user_roles = get_user_roles(user)

    # Check if any role has the required permission
    for role in user_roles:
        if permission in role.permissions:
            if role.allowed_repos is None or repo in role.allowed_repos:
                return True

    return False

@mcp.tool()
async def list_repos(user: str) -> dict:
    """List repositories user has access to"""
    # Filter repos by permissions
    repos = [repo for repo in ALL_REPOS if await check_permission(user, repo, Permission.READ_REPO)]
    return {"repos": repos}
```

**Tests:** `tests/integration/test_permissions.py`

---

### 2.6 DevOps: Monitoring Implementation

**Status:** REQUIRED BY DEVOPS ENGINEER

**Deliverables:**
- [ ] Deploy observability stack (Jaeger/Tempo, Prometheus, Grafana)
- [ ] Create dashboards (minimum 3)
- [ ] Configure alerting rules (minimum 10)
- [ ] Document on-call procedures

**Dashboards:**
- [ ] Mahavishnu Workflow Overview
- [ ] OpenSearch Cluster Health
- [ ] Adapter Performance

**Alerting Rules:**
- [ ] HighWorkflowFailureRate (error_rate > 5% for 5 minutes)
- [ ] OpenSearchClusterDown (cluster_status != 'green')
- [ ] SlowQueryPerformance (p95_query_latency > 1000ms)

---

## Phase 3: Inter-Repository Messaging (Week 15.5-18)

**Status:** ⏳ Not Started
**Buffer:** +0.5 weeks included

### 3.1 Repository Messenger

**New File:** `mahavishnu/messaging/repository_messenger.py`

**Deliverables:**
- [ ] Import mcp-common messaging types
- [ ] Implement inter-repository messaging
- [ ] Store in OpenSearch (with security)
- [ ] Add querying

**Implementation:**
```python
from mcp_common.messaging import RepositoryMessage, Priority, MessageType

class RepositoryMessenger:
    """Handle messaging between repositories"""

    def __init__(self, opensearch_client):
        self.opensearch = opensearch_client

    async def send_message(
        self,
        from_repository: str,
        to_repository: str,
        subject: str,
        message: str,
        priority: Priority = Priority.NORMAL,
        from_adapter: str | None = None,
        workflow_id: str | None = None
    ) -> RepositoryMessage:
        """Send message between repositories"""

        msg_id = f"msg-{int(datetime.now().timestamp())}-{from_repository[:8]}"

        message_obj = RepositoryMessage(
            id=msg_id,
            from_repository=from_repository,
            from_adapter=from_adapter,
            to_repository=to_repository,
            timestamp=datetime.now().isoformat(),
            subject=subject,
            priority=priority,
            content_type=MessageType.NOTIFICATION,
            content_message=message,
            workflow_id=workflow_id
        )

        # Store in OpenSearch (with TLS + auth)
        await self.opensearch.index(
            index="mahavishnu_messages",
            id=msg_id,
            body={
                "from_repository": from_repository,
                "to_repository": to_repository,
                "timestamp": message_obj.timestamp,
                "subject": subject,
                "priority": message_obj.priority,
                "message": message,
                "workflow_id": workflow_id
            }
        )

        return message_obj
```

---

### 3.2 Message Authentication

**Status:** REQUIRED BY SECURITY SPECIALIST

**Deliverables:**
- [ ] Add HMAC signatures to `RepositoryMessage`
- [ ] Validate signatures on receive
- [ ] Log all message traffic (for audit trail)

**Implementation:**
```python
from mcp_common.messaging.auth import CrossProjectAuth

auth = CrossProjectAuth(shared_secret=os.getenv("CROSS_PROJECT_SECRET"))

async def send_message(...) -> RepositoryMessage:
    # Add signature
    message_dict = message_obj.model_dump()
    signature = auth.sign_message(message_dict)
    message_dict["signature"] = signature

    # Store with signature
    await self.opensearch.index(index="mahavishnu_messages", body=message_dict)
```

---

### 3.3 MCP Tools

**New File:** `mahavishnu/mcp/tools/messaging_tools.py`

**Deliverables:**
- [ ] `send_repository_message` tool
- [ ] `list_repository_messages` tool
- [ ] Add permission checks (RBAC)
- [ ] Add security tests

**Implementation:**
```python
@mcp.tool()
async def send_repository_message(
    from_repository: str,
    to_repository: str,
    subject: str,
    message: str,
    priority: Priority = Priority.NORMAL,
    from_adapter: str | None = None
) -> dict:
    """Send message between repositories"""
    # Check permissions
    if not await check_permission(user, from_repository, Permission.WRITE_REPO):
        raise PermissionError("No write access to repository")

    messenger = RepositoryMessenger(app_settings.opensearch)
    message_obj = await messenger.send_message(
        from_repository=from_repository,
        to_repository=to_repository,
        subject=subject,
        message=message,
        priority=priority,
        from_adapter=from_adapter
    )

    return {
        "success": True,
        "message_id": message_obj.id,
        "timestamp": message_obj.timestamp
    }

@mcp.tool()
async def list_repository_messages(repository: str) -> dict:
    """List messages for a repository"""
    pass
```

---

## Phase 4: Production Polish (Week 18-22)

**Status:** ⏳ Not Started
**Buffer:** +1 week + 1 week contingency included

### 4.1 Observability (Week 18-19)

**File:** `mahavishnu/core/observability.py`

**Deliverables:**
- [ ] Implement OpenTelemetry tracing
- [ ] Structured logging with context
- [ ] Metrics collection
- [ ] Correlation IDs

**Implementation:**
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

tracer = trace.get_tracer(__name__)

async def execute_workflow(self, task, repos):
    with tracer.start_as_current_span("workflow_execution") as span:
        span.set_attribute("task_type", task.get("type"))
        span.set_attribute("repo_count", len(repos))

        # Execute workflow
        result = await process_repositories_flow(repos, task)

        span.set_attribute("success_count", result["success_count"])
        return result
```

---

### 4.2 OpenSearch Log Analytics (Week 19-20)

**Status:** REQUIRED BY DEVOPS ENGINEER

**Deliverables:**
- [ ] Data Prepper pipeline configuration
- [ ] ML Commons agent setup
- [ ] Log pattern detection alerts
- [ ] Correlation dashboards

**Implementation:**
```python
# Log to OpenSearch with correlation
async def execute_workflow(self, workflow_id, task, repos):
    logger = structlog.get_logger()
    logger.bind(workflow_id=workflow_id, task_type=task.get("type"))

    logger.info("Starting workflow")
    # Execute
    logger.info("Workflow completed", result=result)
```

**Benefits:** One platform for code search + logs + traces + metrics

---

### 4.3 Security Hardening (Week 20-21)

**Status:** REQUIRED BY SECURITY SPECIALIST

**Deliverables:**
- [ ] Audit logging for all security events
- [ ] Network security (firewall rules, rate limiting)
- [ ] Error message sanitization
- [ ] Security baseline documentation

**Audit Logging:**
```python
# Log all auth attempts
async def log_auth_event(user: str, success: bool, ip: str):
    await opensearch.index(index="mahavishnu_audit", body={
        "timestamp": datetime.now().isoformat(),
        "event_type": "auth_attempt",
        "user": user,
        "success": success,
        "ip_address": ip
    })
```

**Security Tests:**
- [ ] Test TLS certificate validation
- [ ] Test authentication enforcement
- [ ] Test permission checks
- [ ] Test audit logging

---

### 4.4 Testing & Quality (Week 20-21)

**Status:** REQUIRED BY QA LEAD

**Deliverables:**
- [ ] Complete test coverage (>85%)
- [ ] OpenSearch failure mode tests
- [ ] Cross-project integration tests
- [ ] Property-based tests (Hypothesis)
- [ ] Performance tests
- [ ] Security tests

**Test Categories:**
- [ ] Unit tests (>70% of tests)
- [ ] Integration tests (>20% of tests)
- [ ] E2E tests (>5% of tests)
- [ ] Property-based tests (>3% of tests)

**Property-Based Tests:**
```python
@pytest.mark.property
@given(st.lists(st.text(min_size=1), min_size=1, max_size=100))
def test_index_multiple_files(file_names):
    """Property: Indexing multiple files should complete successfully"""
    # Test with Hypothesis
    result = await index_files(file_names)
    assert result["success"] == True
    assert result["files_indexed"] == len(file_names)
```

---

### 4.5 Documentation (Week 21-22)

**Deliverables:**
- [ ] API documentation
- [ ] Deployment guide
- [ ] Operations guide
- [ ] Security guide
- [ ] Troubleshooting guide

**Documentation Files:**
- [ ] `docs/deployment-guide.md` - How to deploy
- [ ] `docs/operations-guide.md` - How to operate
- [ ] `docs/security-guide.md` - Security best practices
- [ ] `docs/troubleshooting.md` - Common issues and solutions
- [ ] `docs/api-reference.md` - MCP tool reference

---

### 4.6 Production Readiness Checklist (Week 22)

**Status:** REQUIRED BY DEVOPS ENGINEER

**Final Checklist:**

**Security:**
- [ ] TLS enabled for all external connections
- [ ] OpenSearch authentication configured
- [ ] RBAC implemented and tested
- [ ] Audit logging enabled
- [ ] Security scan passing (bandit, safety)

**DevOps:**
- [ ] Production deployment tested
- [ ] Backup/restore procedures tested
- [ ] Monitoring and alerting configured
- [ ] Disaster recovery drill completed
- [ ] Performance baselines documented

**QA:**
- [ ] Test coverage >85%
- [ ] All tests passing
- [ ] Integration tests passing
- [ ] E2E tests passing
- [ ] Property-based tests passing
- [ ] Performance tests passing

**Documentation:**
- [ ] API docs complete
- [ ] Deployment guide complete
- [ ] Operations guide complete
- [ ] Security guide complete
- [ ] Troubleshooting guide complete

---

## Success Criteria

**Phase 0 Complete When:**
- ✅ mcp-common code graph functional
- ✅ Shared messaging types defined
- ✅ Both projects can import from mcp-common
- ✅ OpenSearch prototype validated
- ✅ DevOps documentation complete
- ✅ Security hardening complete (TLS, auth, RBAC)

**Phase 0.5 Complete When:**
- ✅ OpenSearch TLS/HTTPS configured
- ✅ OpenSearch authentication working
- ✅ Cross-project authentication defined
- ✅ RBAC model implemented

**Phase 1 Complete When:**
- ✅ Session Buddy indexes code graphs
- ✅ Project messaging works
- ✅ Documentation searchable
- ✅ Cross-project authentication working
- ✅ CI/CD pipeline functional
- ✅ Integration tests passing

**Phase 2 Complete When:**
- ✅ Prefect executes real flows
- ✅ Agno creates and runs agents (stable v0.1.7)
- ✅ OpenSearch persists vectors + enables hybrid search
- ✅ Code graph enhances RAG quality
- ✅ Workflow state tracking working
- ✅ RBAC enforced on all MCP tools
- ✅ Monitoring dashboards live

**Phase 3 Complete When:**
- ✅ Repositories can message each other
- ✅ Backend notifies frontend automatically
- ✅ QA alerts developers on failures
- ✅ Message authentication working

**Phase 4 Complete When:**
- ✅ Observability instrumented
- ✅ Log analytics with OpenSearch
- ✅ 85%+ test coverage
- ✅ Production documentation complete
- ✅ Security hardening complete
- ✅ All readiness checks passing

---

## Risk Mitigation

### Critical Risks Identified

1. **OpenSearch Operational Complexity**
   - **Mitigation:** Phase 0 prototype validates assumptions early
   - **Rollback:** pgvector via Oneiric adapter (production-ready)
   - **Timeline Impact:** +0.5 weeks in Phase 0

2. **LlamaIndex httpx Conflict**
   - **Mitigation:** Document workaround in Phase 0
   - **Workaround:** Pin httpx version or use separate venv
   - **Timeline Impact:** 0 (documentation only)

3. **Security Implementation Complexity**
   - **Mitigation:** Dedicated Phase 0.5 for security hardening
   - **Support:** mcp-common provides shared auth types
   - **Timeline Impact:** +2 weeks (Phase 0.5)

4. **Testing Gap**
   - **Mitigation:** Shift-left testing approach, TDD for new features
   - **Support:** Property-based testing with Hypothesis
   - **Timeline Impact:** +1 week spread across all phases

### Contingency Plan

**If Phase 0 prototype fails:**
- Switch to pgvector via Oneiric adapter
- Adjust timeline by +1 week for pgvector integration
- OpenSearch deferred to post-MVP

**If Agno v0.1.7 has issues:**
- Consider Agno v2.0 beta (evaluate risk)
- Fallback to direct LLM API calls (Ollama)
- No timeline impact (local testing catches issues early)

**If Security hardening takes longer:**
- Defer nice-to-have items (full audit logging)
- Focus on must-have items (TLS, auth, RBAC)
- Maximum additional time: +1 week

---

## Dependencies

### External Packages

```bash
# Install with uv (preferred)
uv pip install 'llama-index-vector-stores-opensearch'
uv pip install opensearch-py

# Agno stable v0.1.7
uv pip install 'agno>=0.1.7'

# Existing
uv pip install 'oneiric~=0.3.0'
uv pip install 'session-buddy>=0.11.0'

# Ollama (already installed via Homebrew)
brew services list | grep ollama
```

### Infrastructure

```bash
# OpenSearch (local dev via Homebrew)
brew install opensearch
brew services start opensearch

# OpenSearch Dashboards (optional, for visualization)
brew install opensearch-dashboards
brew services start opensearch-dashboards

# Access Dashboards at http://localhost:5601
# Connect to OpenSearch at http://localhost:9200
```

---

## Files to Create/Modify

### mcp-common (Foundation)
- [ ] `mcp-common/code_graph/analyzer.py` - NEW
- [ ] `mcp-common/messaging/auth.py` - NEW (cross-project auth)
- [ ] `mcp-common/core/permissions.py` - NEW (RBAC types)
- [ ] `mcp-common/tests/test_code_graph.py` - NEW
- [ ] `mcp-common/messaging/types.py` - ✅ DONE
- [ ] `mcp-common/mcp/contracts/code_graph_tools.yaml` - ✅ DONE

### Session Buddy
- [ ] `session_buddy/code_graph.py` - NEW
- [ ] `session_buddy/messaging/project_messenger.py` - NEW
- [ ] `session_buddy/mcp/tools/code_graph_tools.py` - NEW
- [ ] `session_buddy/mcp/tools/messaging_tools.py` - NEW
- [ ] `session_buddy/documentation.py` - NEW
- [ ] `session_buddy/.github/workflows/ci-cd.yml` - NEW
- [ ] `tests/integration/test_cross_project.py` - NEW
- [ ] `tests/integration/test_opensearch_failures.py` - NEW

### Mahavishnu
- [ ] `mahavishnu/engines/prefect_adapter.py` - MODIFY (real logic)
- [ ] `mahavishnu/engines/agno_adapter.py` - MODIFY (Agno integration)
- [ ] `mahavishnu/engines/llamaindex_adapter.py` - MODIFY (OpenSearch + code graph)
- [ ] `mahavishnu/core/workflow_state.py` - NEW
- [ ] `mahavishnu/core/permissions.py` - NEW
- [ ] `mahavishnu/core/audit.py` - NEW
- [ ] `mahavishnu/messaging/repository_messenger.py` - NEW
- [ ] `mahavishnu/mcp/tools/messaging_tools.py` - NEW
- [ ] `mahavishnu/mcp/server_core.py` - MODIFY (workflow state, RBAC)
- [ ] `docs/deployment-architecture.md` - NEW
- [ ] `docs/opensearch-operations.md` - NEW
- [ ] `docs/monitoring-implementation.md` - NEW
- [ ] `docs/backup-disaster-recovery.md` - NEW
- [ ] `docs/scalability-capacity-planning.md` - NEW
- [ ] `docs/testing-strategy.md` - NEW
- [ ] `tests/integration/test_prefect_adapter.py` - NEW
- [ ] `tests/integration/test_agno_adapter.py` - NEW
- [ ] `tests/integration/test_workflow_state.py` - NEW
- [ ] `tests/integration/test_permissions.py` - NEW
- [ ] `tests/integration/test_security.py` - NEW
- [ ] `tests/property/test_code_graph.py` - NEW
- [ ] `tests/e2e/test_full_workflow.py` - NEW

---

## Progress Tracking

### Phase Status

- [ ] **Phase 0: mcp-common** (Week 1-4.5) - 0/20 tasks complete
- [ ] **Phase 0.5: Security** (Week 4.5-6.5) - 0/15 tasks complete
- [ ] **Phase 1: Session Buddy** (Week 6.5-10.5) - 0/18 tasks complete
- [ ] **Phase 2: Mahavishnu** (Week 10.5-15.5) - 0/25 tasks complete
- [ ] **Phase 3: Messaging** (Week 15.5-18) - 0/8 tasks complete
- [ ] **Phase 4: Polish** (Week 18-22) - 0/30 tasks complete

**Overall Progress:** 0/116 tasks complete (0%)

---

## Committee Sign-Off

**Reviewers:**
- ✅ QA Lead - REQUEST IMPROVEMENTS (5.5/10) - Improvements included
- ✅ Technical Architect - APPROVE WITH RECOMMENDATIONS (9/10) - Recommendations included
- ✅ Product Manager - APPROVE WITH MINOR RECOMMENDATIONS (7.5/10) - Recommendations included
- ✅ DevOps Engineer - REQUEST IMPROVEMENTS (6.5/10) - Improvements included
- ✅ Security Specialist - APPROVE WITH RECOMMENDATIONS (7.5/10) - Recommendations included

**Consensus:** All critical blockers addressed
**Risk Level:** LOW
**Confidence Level:** HIGH

**Date Approved:** 2025-01-25
**Plan Version:** Option 1 (Full Production-Ready)
**Timeline:** 19-22 weeks

---

## Next Steps

**Immediate (This Week):**
1. ✅ Begin Phase 0.1: Code Graph Analyzer implementation
2. ✅ Install OpenSearch via Homebrew
3. ✅ Create DevOps documentation templates
4. ✅ Set up testing strategy document

**Short-term (Week 2-4):**
1. Complete mcp-common foundation
2. Validate OpenSearch prototype
3. Begin security hardening
4. Set up CI/CD pipelines

**Phase 0 Review (Week 4.5):**
- Validate all deliverables
- Approve Phase 0.5 start
- Review security implementation

---

**Let's build this! 🚀**
