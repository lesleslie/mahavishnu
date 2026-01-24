# Mahavishnu Memory Architecture Plan

**Version:** 1.0
**Date:** 2025-01-24
**Status:** Proposed Architecture

## Executive Summary

This document outlines the comprehensive memory architecture for Mahavishnu that integrates:
- **Session-Buddy**: Project memory, global insights, and cross-project intelligence
- **AgentDB + PostgreSQL**: High-volume agent-specific memory storage
- **LlamaIndex + AgentDB**: RAG pipelines with persistent vector stores

**Key Benefits:**
- ✅ Unified search across all memory systems
- ✅ Bidirectional memory sharing with Session-Buddy
- ✅ Leverages Session-Buddy's cross-project intelligence
- ✅ AgentDB scales for high-frequency agent operations
- ✅ LlamaIndex optimized for large-scale vector operations
- ✅ Privacy-first (100% local processing)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Descriptions](#component-descriptions)
3. [Integration Strategy](#integration-strategy)
4. [Implementation Plan](#implementation-plan)
5. [Configuration](#configuration)
6. [API Design](#api-design)
7. [Cross-Project Integration](#cross-project-integration)
8. [Testing Strategy](#testing-strategy)
9. [Migration Path](#migration-path)

---

## Architecture Overview

### High-Level Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│          Mahavishnu Memory Interface Service                      │
├───────────────────────────────────────────────────────────────────┤
│  • Unified search across all memory systems                      │
│  • Bidirectional memory sharing with Session-Buddy               │
│  • Memory deduplication and intelligent merging                  │
│  • Cross-system memory sharing protocols                         │
└───────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ↓                    ↓                    ↓
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│  AgentDB + PostgreSQL│  │  LlamaIndex RAG     │  │  Session-Buddy   │
│  (Agent Memory)      │  │  (Knowledge Base)    │  │  Reflection DB   │
├──────────────────────┤  ├──────────────────────┤  ├──────────────────┤
│ • Agent conversations│  │ • Vector embeddings │  │ • Project memory │
│ • Tool usage         │  │ • Document chunks   │  │ • Global memory  │
│ • Reasoning traces   │  │ • Semantic search    │  │ • Insights       │
│ • Persistent storage │  │ • AgentDB backend    │  │ • Cross-project  │
└──────────────────────┘  └──────────────────────┘  └──────────────────┘
            ↑                    ↑                    ↑
            └────────────────────┴────────────────────┘
                           PostgreSQL
                    (Persistent storage layer)
```

### Memory Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       Memory Flow                               │
└─────────────────────────────────────────────────────────────────┘

Workflow Execution:
  Mahavishny Orchestrator
       ↓
  Store in Session-Buddy project memory
       ↓
  Available for cross-project search


Agent Conversation (Agno):
  Agent generates response
       ↓
  Store in AgentDB + PostgreSQL
       ↓
  Available for agent-specific search


RAG Query (LlamaIndex):
  Query knowledge base
       ↓
  Search LlamaIndex vector store (AgentDB-backed)
       ↓
  Return relevant documents


Unified Search:
  User query
       ↓
  Search all systems in parallel
       ↓
  Merge and deduplicate results
       ↓
  Return ranked results
```

---

## Component Descriptions

### 1. Session-Buddy Integration

**Purpose:** Project memory, global insights, and cross-project intelligence

**What Session-Buddy Provides:**
- **Reflection Database**: DuckDB-based at `~/.claude/data/reflection.duckdb`
- **Collection-based isolation**: Multiple "databases" in one DuckDB file
- **ONNX embeddings**: all-MiniLM-L6-v2 (384 dimensions)
- **Semantic search**: Cosine similarity with time decay
- **SHA-256 deduplication**: Automatic duplicate prevention
- **Cross-project intelligence**: Share knowledge across related projects
- **Automatic insights capture**: Extract insights from `★ Insight ─────` patterns

**Mahavishnu Collections:**
```python
# Project-specific memory
collection_name="mahavishnu_project"
  - Workflow executions
  - Orchestration patterns
  - Adapter health metrics

# Global/cross-project memory
collection_name="mahavishnu_global"
  - Orchestration insights
  - Cross-project patterns
  - Best practices
```

**Key Features We'll Use:**
1. **Project Memory**: Store Mahavishnu workflow executions
2. **Global Memory**: Share orchestration insights across projects
3. **Cross-Project Search**: Dependency-aware result ranking
4. **Insights Capture**: Automatic knowledge capture from workflows

---

### 2. AgentDB + PostgreSQL Integration

**Purpose:** High-volume agent-specific memory storage

**What AgentDB Provides:**
- **PostgreSQL backend**: Persistent, scalable storage
- **Vector similarity search**: AgentDB's vector operations
- **Agent conversation tracking**: Chat history and context
- **Tool usage history**: What tools agents used and results
- **Reasoning traces**: Agent thought processes and decisions

**Mahavishnu Uses:**
```python
# Agent-specific collections
agent_id="agno_agent_1"
  memory_types:
    - conversation: Chat history
    - tool_use: Tool invocations
    - reasoning: Decision traces
```

**Why AgentDB + PostgreSQL:**
- ✅ **Scalability**: Handles high-frequency agent operations
- ✅ **Persistence**: PostgreSQL provides durable storage
- ✅ **Performance**: Optimized for agent workloads
- ✅ **Vector operations**: Built-in similarity search
- ✅ **Replication**: PostgreSQL supports replication/backup

---

### 3. LlamaIndex + AgentDB Integration

**Purpose:** RAG pipelines with persistent vector stores

**What LlamaIndex Provides:**
- **Vector embeddings**: Ollama integration (nomic-embed-text)
- **Document chunking**: SentenceSplitter with configurable overlap
- **Vector stores**: Multiple backends (we'll use AgentDB)
- **Semantic search**: High-quality retrieval for RAG
- **Knowledge base integration**: Connects to Agno agents

**Mahavishnu Uses:**
```python
# RAG knowledge base
collection_name="mahavishnu_rag_knowledge"
  - Repository documents
  - Code chunks with embeddings
  - Semantic search for retrieval
```

**Why LlamaIndex + AgentDB:**
- ✅ **Purpose-built**: LlamaIndex optimized for RAG
- ✅ **Ollama integration**: Local embeddings, no external APIs
- ✅ **AgentDB backend**: Persistent vector storage in PostgreSQL
- ✅ **Large-scale**: Handles millions of documents
- ✅ **Advanced retrieval**: Hybrid search, re-ranking, filters

---

## Integration Strategy

### Memory System Responsibilities

**Session-Buddy (Project Memory + Global Intelligence):**
- Workflow execution logs
- Orchestration patterns and insights
- Cross-project knowledge sharing
- Automatic insights capture
- Dependency-aware search

**AgentDB + PostgreSQL (Agent Memory):**
- Agent conversations (high-volume)
- Tool usage history
- Reasoning traces
- Agent-specific context

**LlamaIndex + AgentDB (RAG Knowledge Base):**
- Repository/document embeddings
- Large-scale vector search
- Knowledge retrieval for agents
- Semantic search across codebases

### Unified Memory Interface

The `MahavishnuMemoryIntegration` class provides:

```python
# Store operations
await memory.store_workflow_execution(...)
await memory.store_agent_insight(...)
await memory.bridge_memory_to_session_buddy(...)

# Search operations
results = await memory.unified_search(UnifiedMemoryQuery(
    query="orchestration patterns",
    sources=["session_buddy_project", "agentdb", "llamaindex_rag"],
    limit=10
))

# Cross-system operations
await memory.learn_from_session_buddy(...)
await memory.share_workflow_insights(...)
```

---

## Implementation Plan

### Phase 1: Core Memory Integration (Foundation)

**Duration:** 2-3 days

**Tasks:**
1. Create `mahavishnu/core/memory_integration.py`
   - `MahavishnuMemoryIntegration` class
   - Session-Buddy collections setup
   - Basic unified search

2. Create `mahavishnu/core/agentdb_integration.py`
   - `AgentDBMemoryStore` class
   - PostgreSQL connection management
   - Agent memory operations

3. Update configuration
   - `AgentDBSettings` in `config.py`
   - `MemoryServiceSettings` in `config.py`
   - Add memory settings to `settings/mahavishnu.yaml.example`

**Deliverables:**
- ✅ Core memory integration classes
- ✅ Configuration updates
- ✅ Basic unified search working

**Acceptance Criteria:**
- Can store workflow executions in Session-Buddy
- Can store agent memory in AgentDB
- Can search across both systems
- Unit tests pass with >80% coverage

---

### Phase 2: LlamaIndex + AgentDB Backend

**Duration:** 2-3 days

**Tasks:**
1. Update `mahavishnu/engines/llamaindex_adapter.py`
   - Add AgentDB vector store backend
   - Implement RAG ingestion with AgentDB
   - Unified search across RAG + agent memory

2. Create `mahavishnu/core/llamaindex_agentdb_adapter.py`
   - `LlamaIndexAgentDBAdapter` class
   - Repository ingestion workflows
   - Knowledge retrieval API

**Deliverables:**
- ✅ LlamaIndex using AgentDB backend
- ✅ RAG knowledge base in PostgreSQL
- ✅ Unified search includes RAG results

**Acceptance Criteria:**
- Can ingest repositories into LlamaIndex + AgentDB
- Can search RAG knowledge base
- Results include both RAG and agent memory
- Integration tests pass

---

### Phase 3: Cross-Project Integration

**Duration:** 1-2 days

**Tasks:**
1. Create `mahavishnu/core/cross_project_integration.py`
   - `MahavishnuCrossProjectIntegration` class
   - Project group registration
   - Dependency tracking
   - Cross-project memory sharing

2. Update orchestrator initialization
   - Auto-register with Session-Buddy
   - Create project groups from repos.yaml
   - Define dependencies

**Deliverables:**
- ✅ Mahavishnu registered in Session-Buddy project groups
- ✅ Dependencies tracked
- ✅ Cross-project search working

**Acceptance Criteria:**
- Mahavishnu appears in Session-Buddy project groups
- Dependencies visible in cross-project search
- Workflow insights shared with related projects

---

### Phase 4: Advanced Features

**Duration:** 2-3 days

**Tasks:**
1. Create `mahavishnu/core/memory_sharing.py`
   - `MemorySharingProtocol` class
   - Bidirectional memory sharing
   - Memory synchronization service

2. Create `mahavishnu/core/memory_graph.py`
   - `UnifiedMemoryGraph` class
   - Knowledge graph construction
   - Cluster detection
   - Graph visualization

3. Create `mahavishnu/core/memory_sync.py`
   - `MemorySynchronizationService` class
   - Periodic sync between systems
   - Conflict resolution
   - Deduplication

**Deliverables:**
- ✅ Memory sharing protocols
- ✅ Knowledge graph visualization
- ✅ Automatic memory synchronization

**Acceptance Criteria:**
- Memory flows bidirectionally between systems
- Knowledge graphs can be generated
- Sync service runs without errors

---

### Phase 5: Testing & Documentation

**Duration:** 2-3 days

**Tasks:**
1. Create comprehensive test suite
   - Unit tests for all memory operations
   - Integration tests with real databases
   - Performance benchmarks
   - Cross-system tests

2. Update documentation
   - Memory architecture overview
   - API documentation
   - Usage examples
   - Troubleshooting guide

**Deliverables:**
- ✅ Test suite with >80% coverage
- ✅ Complete documentation
- ✅ Performance benchmarks
- ✅ Usage examples

**Acceptance Criteria:**
- All tests pass
- Documentation is comprehensive
- Benchmarks meet performance targets

---

## Configuration

### Mahavishnu Settings

```yaml
# settings/mahavishnu.yaml

# Memory Integration Settings
memory_service:
  enabled: true
  enable_rag_search: true
  enable_agent_memory: true
  enable_reflection_search: true
  enable_cross_system_sharing: true
  sync_interval_minutes: 5

# Session-Buddy Integration
session_buddy:
  project_collection: "mahavishnu_project"
  global_collection: "mahavishnu_global"
  enable_insights_capture: true
  insight_confidence_threshold: 0.5
  max_insights_per_checkpoint: 10

# AgentDB Integration
agentdb:
  enabled: true
  postgres_url: "postgresql://localhost:5432/agentdb"
  embedding_dimension: 1536
  connection_pool_size: 10
  connection_max_overflow: 20

# LlamaIndex Integration
llamaindex:
  enabled: true
  ollama_base_url: "http://localhost:11434"
  llm_model: "nomic-embed-text"
  chunk_size: 1024
  chunk_overlap: 20
  vector_store_backend: "agentdb"  # Use AgentDB for persistence

# Cross-Project Integration
cross_project:
  enabled: true
  auto_register_with_session_buddy: true
  create_project_groups: true
  track_dependencies: true
```

### Environment Variables

```bash
# AgentDB PostgreSQL
export AGENTDB_POSTGRES_URL="postgresql://user:pass@localhost:5432/agentdb"

# Session-Buddy
export SESSION_BUDDY_ENABLED="true"
export SESSION_BUDDY_DB_PATH="~/.claude/data/reflection.duckdb"

# Ollama (for LlamaIndex embeddings)
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"

# Memory Service
export MAHAVISHNU_MEMORY_SYNC_INTERVAL="300"  # 5 minutes
export MAHAVISHNU_MEMORY_ENABLE_CROSS_SYSTEM="true"
```

---

## API Design

### Unified Memory Query

```python
from mahavishnu.core.memory_integration import (
    UnifiedMemoryQuery,
    UnifiedMemoryResult,
    MemorySourceType
)

# Search across all memory systems
query = UnifiedMemoryQuery(
    query="orchestration patterns for microservices",
    sources=[
        MemorySourceType.SESSION_BUDDY_PROJECT,
        MemorySourceType.SESSION_BUDDY_GLOBAL,
        MemorySourceType.AGENTDB,
        MemorySourceType.LLAMAINDEX_RAG
    ],
    project_filter="auth-service",  # Optional
    agent_id="agno_agent_1",  # Optional
    limit=20
)

results = await memory.unified_search(query)

for result in results:
    print(f"[{result.source.value}] {result.content[:100]}...")
    print(f"  Score: {result.score:.3f}")
    print(f"  Collection: {result.collection}")
```

### Store Workflow Execution

```python
from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

await memory.store_workflow_execution(
    workflow_id="workflow_abc123",
    adapter="prefect",
    execution_data={
        "status": "completed",
        "duration_seconds": 45.2,
        "repos_processed": ["auth-service", "user-service"],
        "tasks_completed": 12
    },
    metadata={
        "triggered_by": "user",
        "environment": "production"
    }
)
```

### Share Agent Insight

```python
# Store insight in Session-Buddy global memory
# This will be available across all projects
await memory.store_agent_insight(
    insight="Always use circuit breakers when calling external services "
           "to prevent cascading failures",
    context={
        "workflow_id": "workflow_abc123",
        "adapter": "prefect",
        "category": "best_practice",
        "confidence": 0.9
    }
)
```

### Cross-Project Learning

```python
from mahavishnu.core.cross_project_integration import MahavishnuCrossProjectIntegration

# Learn from Session-Buddy
learned = await memory.learn_from_session_buddy(
    agent_id="agno_agent_1",
    session_id="session_buddy_session_456"
)

print(f"Learned {learned['learned_count']} new insights from Session-Buddy")

# Share workflow insights with related repos
await memory.share_workflow_insights(
    workflow_id="workflow_abc123",
    insight="Implemented retry logic with exponential backoff",
    target_repos=["auth-service", "user-service"]
)
```

---

## Cross-Project Integration

### Project Group Registration

```python
from session_buddy.multi_project_coordinator import ProjectGroup, ProjectDependency

# Automatically created from repos.yaml
group = ProjectGroup(
    name="mahavishnu_orchestrated",
    projects=[
        "mahavishnu",
        "auth-service",
        "user-service",
        "api-gateway"
    ],
    description="Projects orchestrated by Mahavishnu"
)

# Define dependencies
dependencies = [
    ProjectDependency(
        source_project="auth-service",
        target_project="mahavishnu",
        dependency_type="uses",
        description="Auth service orchestrated by Mahavishnu workflows"
    ),
    ProjectDependency(
        source_project="user-service",
        target_project="mahavishnu",
        dependency_type="uses",
        description="User service orchestrated by Mahavishnu workflows"
    ),
    ProjectDependency(
        source_project="user-service",
        target_project="auth-service",
        dependency_type="uses",
        description="User service depends on auth service"
    )
]
```

### Cross-Project Search

When a developer works on `auth-service` and searches for "circuit breaker patterns":

1. Session-Buddy searches `auth-service` project memory
2. Session-Buddy searches related projects (dependencies)
3. **Mahavishnu insights surface** because:
   - `auth-service` → uses → `mahavishnu`
   - Mahavishnu stored circuit breaker pattern in global memory
4. Result: Developer discovers Mahavishnu's orchestration patterns

### Dependency Graph Visualization

```mermaid
graph TD
    AS[auth-service] -->|uses| MV[Mahavishnu]
    US[user-service] -->|uses| MV[Mahavishnu]
    GW[api-gateway] -->|uses| MV[Mahavishnu]
    US -->|uses| AS

    MV -->|shares insights| AS
    MV -->|shares insights| US
    MV -->|shares insights| GW

    style MV fill:#c8e6c9
    style AS fill:#fff9c4
    style US fill:#fff9c4
    style GW fill:#fff9c4
```

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_memory_integration.py
import pytest
from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

@pytest.mark.asyncio
async def test_store_workflow_execution():
    """Test storing workflow execution in Session-Buddy."""
    memory = MahavishnuMemoryIntegration(config)

    await memory.store_workflow_execution(
        workflow_id="test_workflow",
        adapter="prefect",
        execution_data={"status": "completed"},
        metadata={"test": True}
    )

    # Verify stored in Session-Buddy
    results = await memory.session_buddy_project.semantic_search(
        query="test_workflow",
        limit=1
    )

    assert len(results) == 1
    assert results[0]["metadata"]["workflow_id"] == "test_workflow"

@pytest.mark.asyncio
async def test_unified_search():
    """Test unified search across all memory systems."""
    memory = MahavishnuMemoryIntegration(config)

    # Store in multiple systems
    await memory.store_workflow_execution(...)
    await memory.agentdb.store_agent_memory(...)

    # Search all
    query = UnifiedMemoryQuery(
        query="test query",
        sources=list(MemorySourceType),
        limit=10
    )

    results = await memory.unified_search(query)

    # Verify results from all sources
    source_types = {r.source for r in results}
    assert MemorySourceType.SESSION_BUDDY_PROJECT in source_types
    assert MemorySourceType.AGENTDB in source_types

@pytest.mark.asyncio
async def test_deduplication():
    """Test memory deduplication across sources."""
    memory = MahavishnuMemoryIntegration(config)

    # Store same content in multiple systems
    content = "Test content for deduplication"

    await memory.session_buddy_project.add_memory(content, {...})
    await memory.agentdb.store_agent_memory(
        agent_id="test",
        memory_type="test",
        content=content,
        metadata={}
    )

    # Search and deduplicate
    query = UnifiedMemoryQuery(query="Test content", limit=10)
    results = await memory.unified_search(query)

    # Should only return one result (deduplicated)
    assert len(results) == 1
```

### Integration Tests

```python
# tests/integration/test_memory_systems.py
import pytest
from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

@pytest.mark.integration
@pytest.mark.slow
async def test_end_to_end_workflow():
    """Test complete workflow with all memory systems."""
    memory = MahavishnuMemoryIntegration(config)

    # 1. Execute workflow
    await memory.store_workflow_execution(
        workflow_id="integration_test",
        adapter="prefect",
        execution_data={"status": "completed"},
        metadata={}
    )

    # 2. Store agent insight
    await memory.store_agent_insight(
        insight="Test insight from integration test",
        context={"workflow_id": "integration_test"}
    )

    # 3. Search across all systems
    query = UnifiedMemoryQuery(
        query="integration test",
        sources=list(MemorySourceType),
        limit=10
    )

    results = await memory.unified_search(query)

    # Verify results from all sources
    assert len(results) > 0
    assert any(r.source == MemorySourceType.SESSION_BUDDY_PROJECT for r in results)
    assert any(r.source == MemorySourceType.SESSION_BUDDY_GLOBAL for r in results)

@pytest.mark.integration
async def test_cross_project_sharing():
    """Test cross-project memory sharing."""
    from mahavishnu.core.cross_project_integration import MahavishnuCrossProjectIntegration

    integration = MahavishnuCrossProjectIntegration(config)

    # Register Mahavishnu with Session-Buddy
    await integration.register_with_session_buddy(
        repos=["auth-service", "user-service"],
        config=config
    )

    # Share insight with repos
    await integration.share_workflow_insights(
        workflow_id="cross_project_test",
        insight="Test cross-project insight",
        target_repos=["auth-service", "user-service"]
    )

    # Verify insight is discoverable by repos
    # (would require Session-Buddy integration test)
```

### Performance Benchmarks

```python
# tests/performance/test_memory_performance.py
import pytest
import time

@pytest.mark.performance
async def test_unified_search_latency():
    """Test unified search latency."""
    memory = MahavishnuMemoryIntegration(config)

    # Warm-up
    await memory.unified_search(UnifiedMemoryQuery(query="warmup"))

    # Measure search latency
    start = time.time()
    results = await memory.unified_search(
        UnifiedMemoryQuery(
            query="performance test query",
            sources=list(MemorySourceType),
            limit=20
        )
    )
    latency = time.time() - start

    # Should complete in <500ms for 20 results
    assert latency < 0.5
    assert len(results) <= 20

@pytest.mark.performance
async def test_concurrent_memory_operations():
    """Test concurrent memory operations."""
    memory = MahavishnuMemoryIntegration(config)

    # Concurrent stores
    tasks = [
        memory.store_workflow_execution(
            workflow_id=f"concurrent_{i}",
            adapter="prefect",
            execution_data={},
            metadata={}
        )
        for i in range(100)
    ]

    start = time.time()
    await asyncio.gather(*tasks)
    duration = time.time() - start

    # Should complete 100 stores in <5 seconds
    assert duration < 5.0
```

---

## Migration Path

### From Current State

**Current:**
- Basic session checkpoint integration
- No agent-specific memory
- No unified search
- No cross-project sharing

**To New State:**
1. Enable Session-Buddy memory integration
2. Add AgentDB + PostgreSQL
3. Integrate LlamaIndex with AgentDB backend
4. Implement unified memory service
5. Enable cross-project features

### Migration Steps

#### Step 1: Update Dependencies

```bash
# Add new dependencies
uv add agentdb psycopg2-binary asyncpg

# Verify Session-Buddy is latest
uv sync --group session-buddy
```

#### Step 2: Set Up PostgreSQL

```bash
# Using Docker
docker run -d \
  --name agentdb-postgres \
  -e POSTGRES_PASSWORD=agentdb \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  postgres:16

# Or use local PostgreSQL
createdb agentdb
```

#### Step 3: Update Configuration

```yaml
# settings/mahavishnu.yaml
memory_service:
  enabled: true

agentdb:
  enabled: true
  postgres_url: "postgresql://localhost:5432/agentdb"
```

#### Step 4: Initialize Memory Systems

```python
# Run initialization
python -m mahavishnu.scripts.init_memory_systems

# This will:
# - Create Session-Buddy collections
# - Initialize AgentDB schema
# - Set up LlamaIndex with AgentDB backend
# - Register with Session-Buddy project groups
```

#### Step 5: Verify Installation

```bash
# Run health checks
mahavishnu mcp health

# Should show:
# ✓ Session-Buddy integration: healthy
# ✓ AgentDB connection: healthy
# ✓ LlamaIndex RAG: healthy
# ✓ Unified memory service: healthy
```

---

## Benefits Summary

### For Developers

**Unified Knowledge Access:**
- Search once, get results from all memory systems
- No need to know where information is stored
- Automatic deduplication prevents redundancy

**Cross-Project Learning:**
- Solutions found in one project automatically help in related projects
- Orchestration patterns shared across codebase
- Dependencies tracked automatically

**Automatic Insights:**
- Knowledge base builds itself while you work
- `★ Insight ─────` pattern captures learnings
- No manual documentation required

### For Operations

**Scalability:**
- AgentDB handles high-volume agent operations
- PostgreSQL provides durable, scalable storage
- LlamaIndex optimized for large-scale vector search

**Reliability:**
- All systems have persistent storage
- PostgreSQL replication support
- Automatic memory synchronization

**Privacy:**
- 100% local processing
- No external API calls
- Your data stays yours

### For Architecture

**Separation of Concerns:**
- Each system does what it's best at
- Clear boundaries between components
- Easy to swap/upgrade individual systems

**Future-Proof:**
- Modular design allows easy additions
- Standard APIs for integration
- Supports multiple backends

---

## Success Metrics

### Performance Targets

- **Unified Search Latency**: <500ms for 20 results
- **Memory Store Latency**: <100ms per operation
- **Concurrent Operations**: Support 100+ concurrent stores
- **Cross-Project Search**: <1s for dependency-aware results

### Quality Targets

- **Test Coverage**: >80% across all memory modules
- **Deduplication Accuracy**: >99% duplicate detection
- **Search Relevance**: >0.8 average relevance score
- **Uptime**: >99.9% for all memory systems

### Adoption Targets

- **Developer Usage**: 100% of workflows use memory features
- **Insight Capture**: >50 insights captured per week
- **Cross-Project Sharing**: All projects registered in groups
- **Search Frequency**: >100 searches per day

---

## Open Questions

1. **AgentDB Version**: What version of AgentDB should we use? (Need to verify availability)
2. **PostgreSQL Version**: Should we require PostgreSQL 15+ or support 14+?
3. **Migration**: Should we migrate existing Reflection DB data to AgentDB?
4. **Backup Strategy**: How do we back up AgentDB? (PostgreSQL dumps vs. replication)
5. **Monitoring**: What metrics should we track for memory system health?

---

## Next Steps

1. **Review and approve** this architecture plan
2. **Verify AgentDB availability** (check session-buddy for existing integration)
3. **Set up PostgreSQL** for AgentDB backend
4. **Begin Phase 1 implementation** (core memory integration)
5. **Iterate based on testing** and feedback

---

## References

- **Session-Buddy Documentation**: `/Users/les/Projects/session-buddy/README.md`
- **Session-Buddy Intelligence Features**: `/Users/les/Projects/session-buddy/docs/features/INTELLIGENCE_QUICK_START.md`
- **LlamaIndex Documentation**: https://docs.llamaindex.ai
- **AgentDB Documentation**: TBD (verify availability)
- **PostgreSQL Vector Search**: https://www.postgresql.org/docs/current/textsearch-controls.html

---

**Document Version**: 1.0
**Last Updated**: 2025-01-24
**Status**: Ready for Review
