# Mahavishnu Memory Architecture Implementation Plan

**Version:** 1.0
**Date:** 2025-01-24
**Status:** Ready for Implementation
**Estimated Timeline:** 10-14 days

## Executive Summary

This implementation plan delivers Mahavishnu's unified memory architecture that integrates:
- **Session-Buddy**: Project memory, global insights, cross-project intelligence
- **AgentDB + PostgreSQL**: High-volume agent memory storage
- **LlamaIndex + AgentDB**: RAG pipelines with persistent vector stores
- **Performance Monitoring**: Collection and analysis of Oneiric health/metrics

**Total Implementation Time:** 10-14 days across 5 phases

---

## Table of Contents

1. [Phase 1: Core Memory Integration](#phase-1-core-memory-integration)
2. [Phase 2: LlamaIndex + AgentDB Backend](#phase-2-llamaindex--agentdb-backend)
3. [Phase 3: Cross-Project Integration](#phase-3-cross-project-integration)
4. [Phase 4: Advanced Features](#phase-4-advanced-features)
5. [Phase 5: Testing & Documentation](#phase-5-testing--documentation)
6. [Performance Monitoring Integration](#performance-monitoring-integration)
7. [Configuration & Setup](#configuration--setup)
8. [Verification Checklist](#verification-checklist)

---

## Phase 1: Core Memory Integration

**Duration:** 2-3 days
**Objective:** Establish foundation for unified memory service

### Tasks

#### 1.1 Create Core Memory Integration Classes

**Files to Create:**

```python
# mahavishnu/core/memory_integration.py
from typing import Optional, List, Dict, Any, Literal
from enum import Enum
from dataclasses import dataclass
import hashlib
import asyncio
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class MemorySourceType(str, Enum):
    """Memory source types for unified search."""
    SESSION_BUDDY_PROJECT = "session_buddy_project"
    SESSION_BUDDY_GLOBAL = "session_buddy_global"
    AGENTDB = "agentdb"
    LLAMAINDEX_RAG = "llamaindex_rag"
    PERFORMANCE = "performance"  # NEW: Performance metrics

@dataclass
class UnifiedMemoryQuery:
    """Unified memory query across all systems."""
    query: str
    sources: Optional[List[MemorySourceType]] = None
    project_filter: Optional[str] = None
    agent_id: Optional[str] = None
    limit: int = 10

@dataclass
class UnifiedMemoryResult:
    """Unified memory result from any source."""
    source: MemorySourceType
    content: str
    metadata: Dict[str, Any]
    score: float
    collection: Optional[str] = None

class MahavishnuMemoryIntegration:
    """Integrated memory system combining Session-Buddy + AgentDB + LlamaIndex.

    Architecture:
    1. Session-Buddy Reflection DB: Project memory, global insights
    2. AgentDB + PostgreSQL: Agent-specific memory
    3. LlamaIndex + AgentDB: RAG knowledge base
    4. Performance Monitoring: Oneiric health/metrics collection
    """

    def __init__(self, config):
        from mahavishnu.core.config import MahavishnuSettings

        self.config: MahavishnuSettings = config

        # Session-Buddy integration
        self.session_buddy_project = None
        self.session_buddy_global = None
        self._init_session_buddy()

        # AgentDB integration
        self.agentdb = None
        if config.memory_service.enable_agent_memory:
            self._init_agentdb()

        # LlamaIndex integration (Phase 2)
        self.llamaindex = None

        # Deduplication cache
        self._dedup_cache: Dict[str, set] = {}

    def _init_session_buddy(self):
        """Initialize Session-Buddy reflection database connections."""
        try:
            from session_buddy.adapters.reflection_adapter_oneiric import (
                ReflectionDatabaseAdapterOneiric,
                ReflectionAdapterSettings
            )

            # Project-specific memory
            self.session_buddy_project = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_project",
                settings=self.config.session_buddy_settings
            )

            # Global/cross-project memory
            self.session_buddy_global = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_global",
                settings=self.config.session_buddy_settings
            )

            logger.info("Session-Buddy memory integration initialized")

        except ImportError as e:
            logger.warning(f"Session-Buddy not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Session-Buddy: {e}")

    def _init_agentdb(self):
        """Initialize AgentDB + PostgreSQL connection."""
        try:
            from .agentdb_integration import AgentDBMemoryStore

            self.agentdb = AgentDBMemoryStore(self.config)
            logger.info("AgentDB memory integration initialized")

        except ImportError as e:
            logger.warning(f"AgentDB not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize AgentDB: {e}")

    async def store_workflow_execution(
        self,
        workflow_id: str,
        adapter: str,
        execution_data: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> None:
        """Store workflow execution in Session-Buddy project memory.

        Args:
            workflow_id: Unique workflow identifier
            adapter: Adapter name (prefect, llamaindex, agno)
            execution_data: Execution results and metrics
            metadata: Additional context
        """
        if not self.session_buddy_project:
            logger.warning("Session-Buddy project memory not available")
            return

        content = f"Workflow {workflow_id} execution via {adapter}"

        await self.session_buddy_project.add_memory(
            content=content,
            metadata={
                **metadata,
                "workflow_id": workflow_id,
                "adapter": adapter,
                "doc_type": "workflow_execution",
                "execution_data": execution_data
            }
        )

        logger.debug(f"Stored workflow execution: {workflow_id}")

    async def store_agent_insight(
        self,
        insight: str,
        context: Dict[str, Any]
    ) -> None:
        """Store agent insight in Session-Buddy global memory.

        Args:
            insight: Insight text (can include ★ Insight ───── delimiter)
            context: Additional context (workflow_id, adapter, etc.)
        """
        if not self.session_buddy_global:
            logger.warning("Session-Buddy global memory not available")
            return

        await self.session_buddy_global.add_memory(
            content=insight,
            metadata={
                **context,
                "source_system": "mahavishnu",
                "doc_type": "agent_insight",
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.debug(f"Stored agent insight: {insight[:50]}...")

    async def store_performance_metrics(
        self,
        component: str,
        metrics: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> None:
        """Store performance/health metrics from Oneiric components.

        Args:
            component: Component name (adapter_name, service_name, etc.)
            metrics: Performance metrics (execution_time, health_status, etc.)
            metadata: Additional context
        """
        if not self.session_buddy_project:
            logger.warning("Session-Buddy project memory not available")
            return

        content = (
            f"Performance metrics for {component}:\n"
            f"- Health: {metrics.get('health_status', 'unknown')}\n"
            f"- Execution time: {metrics.get('execution_time_ms', 0)}ms\n"
            f"- Memory: {metrics.get('memory_mb', 0)}MB"
        )

        await self.session_buddy_project.add_memory(
            content=content,
            metadata={
                **metadata,
                "component": component,
                "doc_type": "performance_metrics",
                "metrics": metrics,
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.debug(f"Stored performance metrics: {component}")

    async def unified_search(
        self,
        query: UnifiedMemoryQuery
    ) -> List[UnifiedMemoryResult]:
        """Search across all memory systems with intelligent merging.

        Args:
            query: Unified search query

        Returns:
            List of ranked results from all sources
        """
        # Default to all sources if not specified
        if query.sources is None:
            query.sources = list(MemorySourceType)

        all_results: List[UnifiedMemoryResult] = []
        search_tasks = []

        # Search Session-Buddy project memory
        if (MemorySourceType.SESSION_BUDDY_PROJECT in query.sources and
            self.session_buddy_project):
            search_tasks.append(
                self._search_session_buddy_project(query, all_results)
            )

        # Search Session-Buddy global memory
        if (MemorySourceType.SESSION_BUDDY_GLOBAL in query.sources and
            self.session_buddy_global):
            search_tasks.append(
                self._search_session_buddy_global(query, all_results)
            )

        # Search AgentDB
        if (MemorySourceType.AGENTDB in query.sources and
            self.agentdb):
            search_tasks.append(
                self._search_agentdb(query, all_results)
            )

        # Search LlamaIndex RAG (Phase 2)
        if (MemorySourceType.LLAMAINDEX_RAG in query.sources and
            self.llamaindex):
            search_tasks.append(
                self._search_llamaindex(query, all_results)
            )

        # Search performance metrics
        if (MemorySourceType.PERFORMANCE in query.sources and
            self.session_buddy_project):
            search_tasks.append(
                self._search_performance_metrics(query, all_results)
            )

        # Execute all searches concurrently
        await asyncio.gather(*search_tasks, return_exceptions=True)

        # Deduplicate results
        deduplicated = self._deduplicate_results(all_results)

        # Sort by relevance
        deduplicated.sort(key=lambda x: x.score, reverse=True)

        return deduplicated[:query.limit]

    async def _search_session_buddy_project(
        self,
        query: UnifiedMemoryQuery,
        results: List[UnifiedMemoryResult]
    ) -> None:
        """Search Session-Buddy project memory."""
        try:
            project_results = await self.session_buddy_project.semantic_search(
                query=query.query,
                limit=query.limit
            )

            for result in project_results:
                results.append(UnifiedMemoryResult(
                    source=MemorySourceType.SESSION_BUDDY_PROJECT,
                    content=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0),
                    collection="mahavishnu_project"
                ))

        except Exception as e:
            logger.error(f"Error searching Session-Buddy project memory: {e}")

    async def _search_session_buddy_global(
        self,
        query: UnifiedMemoryQuery,
        results: List[UnifiedMemoryResult]
    ) -> None:
        """Search Session-Buddy global memory."""
        try:
            global_results = await self.session_buddy_global.semantic_search(
                query=query.query,
                limit=query.limit
            )

            for result in global_results:
                results.append(UnifiedMemoryResult(
                    source=MemorySourceType.SESSION_BUDDY_GLOBAL,
                    content=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0),
                    collection="mahavishnu_global"
                ))

        except Exception as e:
            logger.error(f"Error searching Session-Buddy global memory: {e}")

    async def _search_agentdb(
        self,
        query: UnifiedMemoryQuery,
        results: List[UnifiedMemoryResult]
    ) -> None:
        """Search AgentDB agent memory."""
        try:
            agent_results = await self.agentdb.search_agent_memory(
                agent_id=query.agent_id or "*",
                query=query.query,
                limit=query.limit
            )

            for result in agent_results:
                results.append(UnifiedMemoryResult(
                    source=MemorySourceType.AGENTDB,
                    content=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0),
                    collection=result.get("memory_type", "unknown")
                ))

        except Exception as e:
            logger.error(f"Error searching AgentDB: {e}")

    async def _search_llamaindex(
        self,
        query: UnifiedMemoryQuery,
        results: List[UnifiedMemoryResult]
    ) -> None:
        """Search LlamaIndex RAG knowledge base."""
        try:
            rag_results = await self.llamaindex.unified_search(
                query=query.query,
                search_rag=True,
                search_agent_memory=False,
                top_k=query.limit
            )

            for result in rag_results.get("rag_results", []):
                results.append(UnifiedMemoryResult(
                    source=MemorySourceType.LLAMAINDEX_RAG,
                    content=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0),
                    collection="llamaindex_rag"
                ))

        except Exception as e:
            logger.error(f"Error searching LlamaIndex: {e}")

    async def _search_performance_metrics(
        self,
        query: UnifiedMemoryQuery,
        results: List[UnifiedMemoryResult]
    ) -> None:
        """Search performance metrics by filtering."""
        try:
            # Filter for performance metrics
            all_results = await self.session_buddy_project.semantic_search(
                query=query.query,
                limit=query.limit * 2  # Get more, then filter
            )

            for result in all_results:
                metadata = result.get("metadata", {})
                if metadata.get("doc_type") == "performance_metrics":
                    results.append(UnifiedMemoryResult(
                        source=MemorySourceType.PERFORMANCE,
                        content=result.get("content", ""),
                        metadata=metadata,
                        score=result.get("score", 0.0),
                        collection="mahavishnu_project"
                    ))

        except Exception as e:
            logger.error(f"Error searching performance metrics: {e}")

    def _deduplicate_results(
        self,
        results: List[UnifiedMemoryResult]
    ) -> List[UnifiedMemoryResult]:
        """Remove duplicate results across sources using SHA-256."""
        seen_hashes = set()
        deduplicated = []

        for result in results:
            content_hash = hashlib.sha256(
                result.content.encode('utf-8')
            ).hexdigest()

            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                deduplicated.append(result)

        return deduplicated

    async def bridge_memory_to_session_buddy(
        self,
        session_id: str,
        memory_type: Literal["rag_query", "agent_interaction", "workflow"],
        data: Dict[str, Any]
    ) -> None:
        """Bridge Mahavishnu memory to Session-Buddy.

        Args:
            session_id: Session-Buddy session ID
            memory_type: Type of memory to bridge
            data: Memory data
        """
        if not self.session_buddy_global:
            logger.warning("Session-Buddy global memory not available")
            return

        await self.session_buddy_global.add_memory(
            content=f"Session {session_id} context from Mahavishnu",
            metadata={
                **data,
                "source_system": "mahavishnu",
                "target_session": session_id,
                "doc_type": "context_bridge",
                "memory_type": memory_type,
                "timestamp": datetime.now().isoformat()
            }
        )

        logger.debug(f"Bridged memory to Session-Buddy session: {session_id}")

    async def get_session_buddy_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 10
    ) -> List[UnifiedMemoryResult]:
        """Retrieve memory from Session-Buddy for Mahavishnu.

        Args:
            session_id: Session-Buddy session ID
            query: Search query
            limit: Max results

        Returns:
            Memory results from Session-Buddy
        """
        if not self.session_buddy_global:
            logger.warning("Session-Buddy global memory not available")
            return []

        try:
            results = await self.session_buddy_global.semantic_search(
                query=query,
                limit=limit
            )

            return [
                UnifiedMemoryResult(
                    source=MemorySourceType.SESSION_BUDDY_GLOBAL,
                    content=result.get("content", ""),
                    metadata=result.get("metadata", {}),
                    score=result.get("score", 0.0),
                    collection="cross_project"
                )
                for result in results
            ]

        except Exception as e:
            logger.error(f"Error retrieving Session-Buddy memory: {e}")
            return []
```

#### 1.2 Create AgentDB Integration

**File to Create:**

```python
# mahavishnu/core/agentdb_integration.py
from typing import Dict, Any, List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

class AgentDBMemoryStore:
    """AgentDB integration with PostgreSQL backend.

    This is a placeholder implementation. The actual implementation depends on:
    1. Verifying AgentDB availability (check session-buddy for existing integration)
    2. Understanding AgentDB's API and schema requirements
    3. Implementing proper PostgreSQL async connection handling
    """

    def __init__(self, config):
        from mahavishnu.core.config import MahavishnuSettings

        self.config: MahavishnuSettings = config
        self._initialized = False

    async def initialize_schema(self) -> None:
        """Initialize AgentDB schema in PostgreSQL."""
        if self._initialized:
            return

        # TODO: Implement actual schema initialization
        # This depends on AgentDB's requirements
        self._initialized = True
        logger.info("AgentDB schema initialized (placeholder)")

    async def store_agent_memory(
        self,
        agent_id: str,
        memory_type: str,
        content: str,
        metadata: Dict[str, Any],
        embedding: Optional[List[float]] = None
    ) -> str:
        """Store agent memory in AgentDB.

        Args:
            agent_id: Agent identifier
            memory_type: Type of memory (conversation, tool_use, reasoning)
            content: Memory content
            metadata: Additional metadata
            embedding: Optional pre-computed embedding

        Returns:
            Memory ID
        """
        await self.initialize_schema()

        # TODO: Implement actual AgentDB storage
        # This requires:
        # 1. AgentDB client library
        # 2. PostgreSQL table schema
        # 3. Vector embedding storage

        memory_id = f"mem_{agent_id}_{len(content)}"  # Placeholder

        logger.debug(
            f"Stored agent memory: {memory_id} "
            f"(agent={agent_id}, type={memory_type}) [PLACEHOLDER]"
        )

        return memory_id

    async def search_agent_memory(
        self,
        agent_id: str,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search agent memory with semantic similarity.

        Args:
            agent_id: Agent to search
            query: Search query
            memory_types: Filter by memory types
            limit: Max results

        Returns:
            List of matching memories
        """
        await self.initialize_schema()

        # TODO: Implement actual AgentDB search
        # This requires:
        # 1. Vector similarity search in PostgreSQL
        # 2. Embedding generation for query
        # 3. Result ranking and filtering

        logger.debug(
            f"Searched agent memory: agent={agent_id}, "
            f"query={query[:50]}... [PLACEHOLDER]"
        )

        return []  # Placeholder

    async def get_conversation_history(
        self,
        agent_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve conversation history for agent.

        Args:
            agent_id: Agent identifier
            limit: Max conversations to retrieve

        Returns:
            Conversation history in chronological order
        """
        await self.initialize_schema()

        # TODO: Implement actual conversation history retrieval
        return []

    async def close(self) -> None:
        """Close database connections."""
        # TODO: Implement proper connection cleanup
        pass
```

#### 1.3 Update Configuration

**File to Modify:** `mahavishnu/core/config.py`

Add these settings to the existing `MahavishnuSettings` class:

```python
# Add to imports
from pydantic import Field
from typing import Optional

class AgentDBSettings(BaseModel):
    """AgentDB configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable AgentDB memory integration"
    )
    postgres_url: str = Field(
        default="postgresql://localhost:5432/agentdb",
        description="PostgreSQL connection URL for AgentDB"
    )
    embedding_dimension: int = Field(
        default=1536,
        description="Embedding vector dimension"
    )
    connection_pool_size: int = Field(
        default=10,
        description="PostgreSQL connection pool size"
    )
    connection_max_overflow: int = Field(
        default=20,
        description="PostgreSQL connection max overflow"
    )

class MemoryServiceSettings(BaseModel):
    """Memory service configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable unified memory service"
    )
    enable_rag_search: bool = Field(
        default=True,
        description="Enable RAG knowledge search"
    )
    enable_agent_memory: bool = Field(
        default=True,
        description="Enable AgentDB agent memory search"
    )
    enable_reflection_search: bool = Field(
        default=True,
        description="Enable reflection DB search"
    )
    enable_cross_system_sharing: bool = Field(
        default=True,
        description="Enable memory sharing with Session-Buddy"
    )
    enable_performance_monitoring: bool = Field(
        default=True,
        description="Enable performance metrics collection from Oneiric"
    )
    sync_interval_minutes: int = Field(
        default=5,
        description="Memory sync interval in minutes"
    )

# Add to MahavishnuSettings class
class MahavishnuSettings(BaseSettings):
    # ... existing fields ...

    agentdb: AgentDBSettings = Field(
        default_factory=AgentDBSettings
    )
    memory_service: MemoryServiceSettings = Field(
        default_factory=MemoryServiceSettings
    )

    # Session-Buddy settings (if not already present)
    session_buddy_settings: Optional[Any] = Field(
        default=None,
        description="Session-Buddy integration settings"
    )
```

#### 1.4 Update Configuration Example

**File to Update:** `settings/mahavishnu.yaml.example`

Add these sections:

```yaml
# Memory Integration Settings
memory_service:
  enabled: true
  enable_rag_search: true
  enable_agent_memory: true
  enable_reflection_search: true
  enable_cross_system_sharing: true
  enable_performance_monitoring: true
  sync_interval_minutes: 5

# AgentDB Integration
agentdb:
  enabled: true
  postgres_url: "postgresql://localhost:5432/agentdb"
  embedding_dimension: 1536
  connection_pool_size: 10
  connection_max_overflow: 20
```

### Deliverables

- ✅ `MahavishnuMemoryIntegration` class with unified search
- ✅ `AgentDBMemoryStore` class (placeholder for AgentDB API)
- ✅ Configuration updates for memory service
- ✅ Performance metrics storage method
- ✅ Unit tests for core integration

### Acceptance Criteria

- Can store workflow executions in Session-Buddy
- Can store performance metrics from Oneiric
- Can search across Session-Buddy project and global memory
- Configuration loading works correctly
- Unit tests pass with >80% coverage

---

## Phase 2: LlamaIndex + AgentDB Backend

**Duration:** 2-3 days
**Objective:** Integrate LlamaIndex with AgentDB vector store

### Tasks

#### 2.1 Update LlamaIndex Adapter

**File to Modify:** `mahavishnu/engines/llamaindex_adapter.py`

Update the existing adapter to support AgentDB backend:

```python
# Add to imports
from typing import Dict, Any
from pathlib import Path

class LlamaIndexAgentDBAdapter:
    """LlamaIndex RAG with AgentDB vector store backend.

    Architecture:
    - LlamaIndex: RAG pipelines and document processing
    - AgentDB: Persistent vector storage in PostgreSQL
    - Ollama: Local embeddings (nomic-embed-text)
    """

    def __init__(self, config, agentdb_store=None):
        from llama_index.core import Settings
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.core.node_parser import SentenceSplitter

        self.config = config
        self.agentdb = agentdb_store

        # Configure Ollama embeddings
        Settings.embed_model = OllamaEmbedding(
            model_name=config.llm_model,
            base_url=config.ollama_base_url
        )

        # Configure node parser for chunking
        self.node_parser = SentenceSplitter(
            chunk_size=1024,
            chunk_overlap=20,
            separator=" "
        )

        # Index cache
        self.indices: Dict[str, Any] = {}

    async def ingest_repository(
        self,
        repo_path: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ingest repository into LlamaIndex.

        Args:
            repo_path: Path to repository
            metadata: Repository metadata

        Returns:
            Ingestion statistics
        """
        from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, Document

        # Load documents
        repo = Path(repo_path)
        reader = SimpleDirectoryReader(
            input_dir=str(repo),
            recursive=True,
            required_exts=[".py", ".md", ".txt", ".yaml", ".yml"],
            exclude=[".git", "__pycache__", "*.pyc", "node_modules"]
        )

        documents = reader.load_data()

        # Parse documents into nodes
        nodes = self.node_parser.get_nodes_from_documents(documents)

        # Create vector store index
        # TODO: Replace with AgentDB vector store when available
        index = VectorStoreIndex(nodes)

        # Store index for querying
        index_id = f"{repo.name}_{len(self.indices)}"
        self.indices[index_id] = index

        logger.info(
            f"Ingested repository: {repo_path} "
            f"({len(documents)} docs, {len(nodes)} nodes)"
        )

        return {
            "status": "success",
            "documents_ingested": len(documents),
            "nodes_created": len(nodes),
            "index_id": index_id
        }

    async def query_knowledge_base(
        self,
        query: str,
        index_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Query RAG knowledge base.

        Args:
            query: Query string
            index_id: Specific index to query (default: most recent)
            top_k: Number of results

        Returns:
            List of relevant documents with metadata
        """
        if not self.indices:
            logger.warning("No indices available for querying")
            return []

        # Get index
        if index_id and index_id in self.indices:
            index = self.indices[index_id]
        else:
            index = list(self.indices.values())[-1]

        # Query
        query_engine = index.as_query_engine(
            similarity_top_k=top_k,
            streaming=False
        )

        response = query_engine.query(query)

        return [
            {
                "content": node.node.get_content(),
                "metadata": node.node.metadata,
                "score": node.score if hasattr(node, 'score') else 0.0
            }
            for node in response.source_nodes
        ]
```

#### 2.2 Integrate with Memory Service

**File to Modify:** `mahavishnu/core/memory_integration.py`

Add to `MahavishnuMemoryIntegration.__init__`:

```python
async def _init_llamaindex(self):
    """Initialize LlamaIndex with AgentDB backend."""
    if not self.config.memory_service.enable_rag_search:
        return

    try:
        from ..engines.llamaindex_adapter import LlamaIndexAgentDBAdapter

        self.llamaindex = LlamaIndexAgentDBAdapter(
            self.config,
            agentdb_store=self.agentdb
        )

        logger.info("LlamaIndex RAG integration initialized")

    except ImportError as e:
        logger.warning(f"LlamaIndex not available: {e}")
    except Exception as e:
        logger.error(f"Failed to initialize LlamaIndex: {e}")
```

### Deliverables

- ✅ LlamaIndex adapter updated
- ✅ RAG knowledge base functional
- ✅ Unified search includes RAG results
- ✅ Repository ingestion workflow
- ✅ Integration tests pass

### Acceptance Criteria

- Can ingest repositories into LlamaIndex
- Can search RAG knowledge base
- Results include both RAG and other memory
- Integration tests pass

---

## Phase 3: Cross-Project Integration

**Duration:** 1-2 days
**Objective:** Integrate with Session-Buddy's cross-project features

### Tasks

#### 3.1 Create Cross-Project Integration

**File to Create:** `mahavishnu/core/cross_project_integration.py`

```python
from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

@dataclass
class ProjectDependency:
    """Project dependency relationship."""
    source_project: str
    target_project: str
    dependency_type: Literal["uses", "extends", "references", "related"]
    description: Optional[str] = None

@dataclass
class ProjectGroup:
    """Group of related projects."""
    name: str
    projects: List[str]
    description: str

class MahavishnuCrossProjectIntegration:
    """Integrate Mahavishnu with Session-Buddy's cross-project intelligence.

    Features:
    - Project group registration
    - Dependency tracking
    - Cross-project memory sharing
    - Dependency-aware search
    """

    def __init__(self, config, memory_integration):
        from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

        self.config = config
        self.memory: MahavishnuMemoryIntegration = memory_integration

    async def register_with_session_buddy(
        self,
        repos: List[str],
        config
    ) -> None:
        """Register Mahavishnu with Session-Buddy project groups.

        Args:
            repos: List of repository paths from repos.yaml
            config: Configuration object
        """
        # Create project group
        group = ProjectGroup(
            name="mahavishnu_orchestrated",
            projects=[Path(r).name for r in repos] + ["mahavishnu"],
            description="Projects orchestrated by Mahavishnu"
        )

        # Define dependencies
        dependencies = []
        for repo in repos:
            repo_name = Path(repo).name
            dependencies.append(ProjectDependency(
                source_project=repo_name,
                target_project="mahavishnu",
                dependency_type="uses",
                description=f"{repo_name} orchestrated by Mahavishnu"
            ))

        # TODO: Register with Session-Buddy
        # This depends on Session-Buddy's project group API
        logger.info(
            f"Registered {len(repos)} repos with Mahavishnu project group "
            f"[PLACEHOLDER - requires Session-Buddy API]"
        )

    async def share_workflow_insights(
        self,
        workflow_id: str,
        insight: str,
        target_repos: List[str]
    ) -> None:
        """Share workflow insights with target repos.

        Args:
            workflow_id: Workflow identifier
            insight: Insight to share
            target_repos: Repositories that should discover this insight
        """
        await self.memory.store_agent_insight(
            insight=insight,
            context={
                "workflow_id": workflow_id,
                "target_repos": target_repos,
                "doc_type": "cross_project_workflow",
                "share_type": "dependency_aware"
            }
        )

        logger.debug(
            f"Shared workflow insight: {workflow_id} "
            f"with {len(target_repos)} repos"
        )

    async def learn_from_session_buddy(
        self,
        agent_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """Let Mahavishnu learn from Session-Buddy conversations.

        Args:
            agent_id: Agent identifier
            session_id: Session-Buddy session ID

        Returns:
            Learning statistics
        """
        # Get Session-Buddy memory
        results = await self.memory.get_session_buddy_memory(
            session_id=session_id,
            query="relevant context and learnings",
            limit=10
        )

        # Store in AgentDB for agent
        learned_count = 0
        for result in results:
            if self.memory.agentdb:
                await self.memory.agentdb.store_agent_memory(
                    agent_id=agent_id,
                    memory_type="cross_system_context",
                    content=result.content,
                    metadata=result.metadata
                )
                learned_count += 1

        logger.debug(
            f"Agent {agent_id} learned {learned_count} insights "
            f"from Session-Buddy session {session_id}"
        )

        return {"learned_count": learned_count}
```

#### 3.2 Update Orchestrator Initialization

**File to Modify:** `mahavishnu/core/app.py`

Update the `MahavishnuApp` class:

```python
class MahavishnuApp:
    def __init__(self, config: MahavishnuSettings | None = None):
        # ... existing init ...

        # Initialize memory integration
        self.memory = None
        if self.config.memory_service.enabled:
            self.memory = self._init_memory_integration()

        # Initialize cross-project integration
        self.cross_project = None
        if self.memory and self.config.memory_service.enable_cross_system_sharing:
            self.cross_project = self._init_cross_project()

        # Initialize performance monitor
        self.monitor = None
        if self.memory and self.config.memory_service.enable_performance_monitoring:
            self.monitor = self._init_performance_monitor()

    def _init_memory_integration(self):
        """Initialize unified memory service."""
        from .memory_integration import MahavishnuMemoryIntegration

        memory = MahavishnuMemoryIntegration(self.config)
        logger.info("Mahavishnu memory integration initialized")
        return memory

    def _init_cross_project(self):
        """Initialize cross-project integration."""
        from .cross_project_integration import MahavishnuCrossProjectIntegration

        integration = MahavishnuCrossProjectIntegration(
            self.config,
            self.memory
        )

        # Auto-register with Session-Buddy
        if self.config.repos_path:
            repos = self._load_repos()
            asyncio.run(integration.register_with_session_buddy(repos, self.config))

        logger.info("Cross-project integration initialized")
        return integration

    def _init_performance_monitor(self):
        """Initialize performance monitor."""
        from .monitoring import PerformanceMonitor

        monitor = PerformanceMonitor(self.memory)
        logger.info("Performance monitor initialized")
        return monitor
```

### Deliverables

- ✅ Cross-project integration class
- ✅ Project group registration (placeholder)
- ✅ Dependency tracking
- ✅ Cross-project memory sharing
- ✅ Integration tests pass

### Acceptance Criteria

- Mahavishnu can share workflow insights
- Dependencies can be tracked
- Can learn from Session-Buddy sessions
- Integration tests pass

---

## Phase 4: Advanced Features

**Duration:** 2-3 days
**Objective:** Implement advanced memory features

### Tasks

#### 4.1 Memory Sharing Protocols

**File to Create:** `mahavishnu/core/memory_sharing.py`

```python
class MemorySharingProtocol:
    """Protocol for sharing memory between Mahavishnu and Session-Buddy.

    Features:
    - Bi-directional memory access
    - Memory synchronization
    - Cross-system learning
    """

    def __init__(self, memory_integration):
        from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

        self.memory = memory_integration

    async def share_rag_knowledge(
        self,
        session_id: str,
        repo_path: str,
        query: str
    ) -> Dict[str, Any]:
        """Share RAG knowledge with Session-Buddy.

        Flow:
        1. Session-Buddy requests info about repo
        2. Mahavishnu queries RAG knowledge
        3. Results bridged to Session-Buddy
        4. Session-Buddy can now use this knowledge
        """
        # Query RAG knowledge
        results = await self.memory.unified_search(
            UnifiedMemoryQuery(
                query=query,
                sources=[MemorySourceType.LLAMAINDEX_RAG],
                limit=5
            )
        )

        # Bridge to Session-Buddy
        await self.memory.bridge_memory_to_session_buddy(
            session_id=session_id,
            memory_type="rag_query",
            data={
                "repo_path": repo_path,
                "query": query,
                "results": [r.metadata for r in results]
            }
        )

        return {"bridged_count": len(results)}
```

#### 4.2 Memory Synchronization Service

**File to Create:** `mahavishnu/core/memory_sync.py`

```python
class MemorySynchronizationService:
    """Synchronize memory across systems.

    Features:
    - Periodic sync between Mahavishnu and Session-Buddy
    - Conflict resolution
    - Memory deduplication
    """

    def __init__(self, memory_integration):
        from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

        self.memory = memory_integration
        self._sync_task = None

    async def start_sync_service(self) -> None:
        """Start periodic memory synchronization."""
        interval = self.memory.config.memory_service.sync_interval_minutes * 60

        self._sync_task = asyncio.create_task(self._sync_loop(interval))

    async def _sync_loop(self, interval: int) -> None:
        """Run sync loop periodically."""
        while True:
            try:
                await self.bidirectional_sync()
            except Exception as e:
                logger.error(f"Sync error: {e}")

            await asyncio.sleep(interval)

    async def bidirectional_sync(
        self,
        since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Perform bidirectional sync between systems."""
        # Sync Mahavishnu → Session-Buddy
        mahavishnu_sync = await self.sync_to_session_buddy(since=since)

        return {
            "mahavishnu_to_session_buddy": mahavishnu_sync,
            "synced_at": datetime.now().isoformat()
        }

    async def sync_to_session_buddy(
        self,
        since: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Sync new Mahavishnu memories to Session-Buddy."""
        # TODO: Implement actual sync logic
        return {"synced_count": 0}

    async def stop_sync_service(self) -> None:
        """Stop periodic memory synchronization."""
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
```

### Deliverables

- ✅ Memory sharing protocols
- ✅ Memory synchronization service
- ✅ Automatic background sync (placeholder)
- ✅ Integration tests pass

### Acceptance Criteria

- Memory can be shared between systems
- Sync service structure in place
- Integration tests pass

---

## Phase 5: Testing & Documentation

**Duration:** 2-3 days
**Objective:** Comprehensive testing and documentation

### Tasks

#### 5.1 Create Test Suite

**Files to Create:**

```python
# tests/unit/test_memory_integration.py
import pytest
from mahavishnu.core.memory_integration import (
    MahavishnuMemoryIntegration,
    UnifiedMemoryQuery,
    MemorySourceType
)

@pytest.mark.asyncio
async def test_store_workflow_execution():
    """Test storing workflow execution in Session-Buddy."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_store_performance_metrics():
    """Test storing performance metrics."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_unified_search():
    """Test unified search across all memory systems."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_deduplication():
    """Test memory deduplication across sources."""
    # Test implementation
    pass
```

```python
# tests/integration/test_memory_systems.py
import pytest

@pytest.mark.integration
@pytest.mark.slow
async def test_end_to_end_workflow():
    """Test complete workflow with all memory systems."""
    # Test implementation
    pass

@pytest.mark.integration
async def test_cross_project_sharing():
    """Test cross-project memory sharing."""
    # Test implementation
    pass
```

```python
# tests/performance/test_memory_performance.py
import pytest

@pytest.mark.performance
async def test_unified_search_latency():
    """Test unified search latency (<500ms target)."""
    # Test implementation
    pass

@pytest.mark.performance
async def test_concurrent_memory_operations():
    """Test concurrent memory operations (100+ operations)."""
    # Test implementation
    pass
```

#### 5.2 Update Documentation

**Files to Update:**

- **README.md**: Already updated ✅
- **MEMORY_ARCHITECTURE_PLAN.md**: Already created ✅
- **docs/adr/005-memory-architecture.md**: Already created ✅

### Deliverables

- ✅ Test suite with >80% coverage
- ✅ Unit tests for all memory operations
- ✅ Integration tests for cross-system workflows
- ✅ Performance benchmarks
- ✅ Complete documentation

### Acceptance Criteria

- All tests pass
- Test coverage >80%
- Performance targets met:
  - Unified search <500ms
  - Memory store <100ms
  - 100+ concurrent operations supported
- Documentation comprehensive

---

## Performance Monitoring Integration

### Overview

Mahavishnu can collect, analyze, and store health/performance data from Oneiric components and use it for:
- Trend analysis and anomaly detection
- Context-aware orchestration decisions
- Performance pattern discovery
- Predictive scaling recommendations

### Implementation

#### Collection Points

**1. Adapter Health Monitoring**

```python
# mahavishnu/core/monitoring.py
from typing import Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Collect and analyze performance metrics from Oneiric components."""

    def __init__(self, memory_integration):
        from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration

        self.memory = memory_integration
        self._collection_interval = 60  # seconds

    async def collect_adapter_health(
        self,
        adapter_name: str,
        health_data: Dict[str, Any]
    ) -> None:
        """Collect adapter health metrics.

        Args:
            adapter_name: Name of the adapter (prefect, llamaindex, agno)
            health_data: Health data from Oneiric health checks
        """
        metrics = {
            "adapter": adapter_name,
            "health_status": health_data.get("status", "unknown"),
            "execution_time_ms": health_data.get("execution_time_ms", 0),
            "memory_mb": health_data.get("memory_mb", 0),
            "error_count": health_data.get("error_count", 0),
            "last_check": datetime.now().isoformat()
        }

        await self.memory.store_performance_metrics(
            component=adapter_name,
            metrics=metrics,
            metadata={
                "collection_type": "adapter_health",
                "monitoring_version": "1.0"
            }
        )

        logger.debug(f"Collected health metrics for {adapter_name}")

    async def collect_workflow_metrics(
        self,
        workflow_id: str,
        metrics_data: Dict[str, Any]
    ) -> None:
        """Collect workflow execution metrics.

        Args:
            workflow_id: Workflow identifier
            metrics_data: Workflow execution metrics
        """
        metrics = {
            "workflow_id": workflow_id,
            "duration_seconds": metrics_data.get("duration_seconds", 0),
            "tasks_completed": metrics_data.get("tasks_completed", 0),
            "tasks_failed": metrics_data.get("tasks_failed", 0),
            "adapter": metrics_data.get("adapter", "unknown"),
            "timestamp": datetime.now().isoformat()
        }

        await self.memory.store_performance_metrics(
            component=f"workflow_{workflow_id}",
            metrics=metrics,
            metadata={
                "collection_type": "workflow_execution",
                "monitoring_version": "1.0"
            }
        )

        logger.debug(f"Collected metrics for workflow {workflow_id}")
```

**2. Context-Aware Queries**

```python
# Example: Query for slow workflows
async def find_slow_workflows(memory, threshold_seconds=5):
    """Find workflows that exceeded execution time threshold."""
    results = await memory.unified_search(
        UnifiedMemoryQuery(
            query=f"workflow execution with duration > {threshold_seconds}s",
            sources=[MemorySourceType.PERFORMANCE],
            limit=20
        )
    )

    return [
        r for r in results
        if r.metadata.get("metrics", {}).get("duration_seconds", 0) > threshold_seconds
    ]

# Example: Query for failing adapters
async def find_failing_adapters(memory):
    """Find adapters with high error rates."""
    results = await memory.unified_search(
        UnifiedMemoryQuery(
            query="adapter health check with errors",
            sources=[MemorySourceType.PERFORMANCE],
            limit=20
        )
    )

    return [
        r for r in results
        if r.metadata.get("metrics", {}).get("error_count", 0) > 0
    ]
```

**3. Integration with Adapters**

```python
# Example integration in Prefect adapter
class PrefectAdapter:
    async def execute(self, task: Dict[str, Any], repos: List[str]):
        """Execute Prefect workflow with performance monitoring."""
        import time

        start_time = time.time()

        try:
            # Execute workflow
            result = await self._execute_workflow(task, repos)

            # Collect metrics
            execution_time = time.time() - start_time

            if self.app.memory and self.app.config.memory_service.enable_performance_monitoring:
                await self.app.monitor.collect_workflow_metrics(
                    workflow_id=task.get("id", "unknown"),
                    metrics_data={
                        "duration_seconds": execution_time,
                        "tasks_completed": len(result.get("tasks", [])),
                        "tasks_failed": 0,
                        "adapter": "prefect"
                    }
                )

            return result

        except Exception as e:
            execution_time = time.time() - start_time

            if self.app.memory and self.app.config.memory_service.enable_performance_monitoring:
                await self.app.monitor.collect_workflow_metrics(
                    workflow_id=task.get("id", "unknown"),
                    metrics_data={
                        "duration_seconds": execution_time,
                        "tasks_completed": 0,
                        "tasks_failed": 1,
                        "adapter": "prefect",
                        "error": str(e)
                    }
                )

            raise
```

### Use Cases

**1. Trend Analysis**
```python
# Find performance trends over time
results = await memory.unified_search(
    UnifiedMemoryQuery(
        query="adapter performance metrics over last 7 days",
        sources=[MemorySourceType.PERFORMANCE],
        limit=100
    )
)

# Analyze trends
# - Execution time increasing?
# - Error rates spiking?
# - Memory usage growing?
```

**2. Anomaly Detection**
```python
# Find outliers
results = await memory.unified_search(
    UnifiedMemoryQuery(
        query="workflow execution with unusual patterns",
        sources=[MemorySourceType.PERFORMANCE],
        limit=50
    )
)

# Flag anomalies
# - Execution time >3x average
# - Error rate >10%
# - Memory usage >2x average
```

**3. Context-Aware Orchestration**
```python
# Make decisions based on performance data
async def orchestrate_with_context(task, memory):
    # Check adapter health
    health_results = await memory.unified_search(
        UnifiedMemoryQuery(
            query="current adapter health status",
            sources=[MemorySourceType.PERFORMANCE],
            limit=5
        )
    )

    # Choose adapter based on health
    for result in health_results:
        metrics = result.metadata.get("metrics", {})
        if metrics.get("health_status") == "healthy" and metrics.get("execution_time_ms", 0) < 1000:
            return metrics.get("adapter")

    # Fallback to default
    return "prefect"
```

### Benefits

- ✅ **Trend Analysis**: Track performance over time
- ✅ **Anomaly Detection**: Identify unusual patterns
- ✅ **Context-Aware Decisions**: Orchestrate based on actual performance
- ✅ **Predictive Scaling**: Anticipate resource needs
- ✅ **Debugging**: Historical performance data for troubleshooting

---

## Configuration & Setup

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
export MAHAVISHNU_MEMORY_ENABLE_PERFORMANCE_MONITORING="true"
```

### PostgreSQL Setup

```bash
# Using Docker
docker run -d \
  --name agentdb-postgres \
  -e POSTGRES_PASSWORD=agentdb \
  -e POSTGRES_DB=agentdb \
  -p 5432:5432 \
  -v agentdb-data:/var/lib/postgresql/data \
  postgres:16

# Or use local PostgreSQL
createdb agentdb
```

### Ollama Setup

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull embedding model
ollama pull nomic-embed-text

# Start Ollama server
ollama serve
```

### Verification

```bash
# Run health checks
mahavishnu mcp health

# Should show:
# ✓ Session-Buddy integration: healthy
# ✓ AgentDB connection: healthy
# ✓ LlamaIndex RAG: healthy
# ✓ Unified memory service: healthy
# ✓ Performance monitoring: enabled
```

---

## Verification Checklist

### Phase 1 Verification ✅

- [ ] Session-Buddy collections created
- [ ] AgentDB connection established (placeholder)
- [ ] Can store workflow executions
- [ ] Can store performance metrics
- [ ] Unified search works across sources
- [ ] Configuration loading correct
- [ ] Unit tests pass (>80% coverage)

### Phase 2 Verification ✅

- [ ] LlamaIndex adapter updated
- [ ] Can ingest repositories
- [ ] RAG knowledge base functional
- [ ] Unified search includes RAG results
- [ ] Integration tests pass

### Phase 3 Verification ✅

- [ ] Cross-project integration class created
- [ ] Can share workflow insights
- [ ] Can track dependencies (placeholder)
- [ ] Can learn from Session-Buddy
- [ ] Integration tests pass

### Phase 4 Verification ✅

- [ ] Memory sharing protocols work
- [ ] Sync service structure in place
- [ ] Bidirectional sync functional (placeholder)
- [ ] Integration tests pass

### Phase 5 Verification ✅

- [ ] All tests pass
- [ ] Coverage >80%
- [ ] Performance targets met:
  - [ ] Unified search <500ms
  - [ ] Memory store <100ms
  - [ ] 100+ concurrent operations
- [ ] Documentation complete

---

## Open Questions & TODOs

### Critical Items to Resolve

1. **AgentDB Verification**: Check session-buddy for existing AgentDB integration
   - Action: Search session-buddy codebase for AgentDB references
   - Action: Verify AgentDB availability and API
   - Action: If unavailable, implement alternative or placeholder

2. **Session-Buddy API**: Verify Session-Buddy's project group API
   - Action: Check session-buddy for project group/dependency APIs
   - Action: Understand required data structures
   - Action: Implement proper registration

3. **AgentDB Vector Store**: Verify LlamaIndex AgentDB integration
   - Action: Check if `llama-index-vector-stores-agentdb` exists
   - Action: If not, use alternative (e.g., PostgreSQL vector extension)
   - Action: Test vector storage and retrieval

### Database Architecture Review

**Need database-specialist review for:**
- PostgreSQL schema design for AgentDB
- Vector embedding storage strategy
- Index optimization for semantic search
- Connection pooling configuration
- Migration and backup strategies

### Oneiric Integration Review

**Need oneiric-integration-specialist review for:**
- Health check integration points
- Metrics collection strategies
- Performance data formats
- Adapter lifecycle hooks
- Error handling and retry patterns

---

## Summary

This implementation plan delivers a **production-ready unified memory architecture** for Mahavishnu with:

✅ **5 Phases** (10-14 days total)
✅ **3 Memory Backends** (Session-Buddy, AgentDB placeholder, LlamaIndex)
✅ **Performance Monitoring** (Oneiric health/metrics collection)
✅ **Cross-Project Intelligence** (Session-Buddy integration)
✅ **Comprehensive Testing** (>80% coverage)
✅ **Complete Documentation** (architecture, ADR, guides)

**Caveats:**
- AgentDB implementation is placeholder pending verification of availability
- Some Session-Buddy integrations need API verification
- Database architecture needs specialist review
- Oneiric integration needs specialist review

**Next Steps:**
1. ✅ Review this plan
2. 🔜 Have oneiric-integration-specialist review Oneiric integration points
3. 🔜 Have database-specialist review database architecture
4. 🔜 Verify AgentDB availability in session-buddy
5. 🔜 Set up PostgreSQL for testing
6. 🔜 Install Ollama and pull embedding model
7. 🔜 Begin Phase 1 implementation

---

**Document Version:** 1.0
**Last Updated:** 2025-01-24
**Status:** Ready for Specialist Review
**Pending:** Oneiric integration review, Database architecture review, AgentDB verification
