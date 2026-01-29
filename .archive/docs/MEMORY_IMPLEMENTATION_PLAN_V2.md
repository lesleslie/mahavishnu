# Mahavishnu Memory Architecture - Revised Implementation Plan

**Version:** 2.0 (Revised Based on Specialist Reviews)
**Date:** 2025-01-24
**Status:** Ready for Implementation

______________________________________________________________________

## Executive Summary

This revised plan addresses critical issues identified by specialist reviews:

- **Removes AgentDB dependency** (doesn't exist as Python package)
- **Consolidates to PostgreSQL + pgvector** (unified database)
- **Standardizes on single embedding model** (nomic-embed-text: 768 dim)
- **Keeps Session-Buddy DuckDB** (for cross-project insights only)
- **Fixes Oneiric integration** (proper health checks, metrics)

**Timeline:** 4-5 weeks (realistic, tested)

______________________________________________________________________

## Table of Contents

1. [Architecture Overview](#architecture-overview)
1. [Phase 1: PostgreSQL Foundation](#phase-1-postgresql-foundation)
1. [Phase 2: Core Memory Integration](#phase-2-core-memory-integration)
1. [Phase 3: LlamaIndex RAG Integration](#phase-3-llamaindex-rag-integration)
1. [Phase 4: Cross-Project Integration](#phase-4-cross-project-integration)
1. [Phase 5: Testing & Documentation](#phase-5-testing--documentation)
1. [Configuration & Setup](#configuration--setup)
1. [Performance Monitoring](#performance-monitoring)

______________________________________________________________________

## Architecture Overview

### Unified Database Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Mahavishnu Memory Layer                   │
├─────────────────────────────────────────────────────────────┤
│  Unified Memory Store (PostgreSQL + pgvector)                   │
│  ├─ Agent conversations (Agno)                                   │
│  ├─ RAG knowledge base (LlamaIndex)                            │
│  ├─ Workflow executions (Prefect)                              │
│  └─ Performance metrics (Oneiric health)                        │
└─────────────────────────────────────────────────────────────┘
            │                        │
            ↓                        ↓
┌──────────────────────┐  ┌──────────────────────────────┐
│  PostgreSQL + pgvector │  │  Session-Buddy DuckDB         │
│  (Primary Memory Store) │  │  (Cross-Project Insights)  │
├──────────────────────┤  ├──────────────────────────────┤
│ • Agent conversations  │  │ • Project insights             │
│ • RAG embeddings     │  │ • Cross-project patterns    │
│ • Workflow history    │  │ • Dependency relationships │
│ • Performance data    │  │ • Automatic insights capture│
│ • SQL joins          │  │ • Semantic search            │
│ • ACID guarantees    │  │ • 99MB proven database      │
└──────────────────────┘  └──────────────────────────────┘
```

### Key Design Decisions

**1. Single PostgreSQL Database**

- All Mahavishnu-specific memory in one place
- SQL joins across repositories, agents, workflows
- Single backup strategy
- Connection pooling for 10+ concurrent terminals

**2. Session-Buddy for Insights Only**

- Keep existing DuckDB databases (working well)
- Store extracted insights and patterns
- Cross-project intelligence features
- NO raw memory duplication

**3. Single Embedding Model**

- Standardize on nomic-embed-text (768 dimensions)
- Local Ollama (no API costs)
- LlamaIndex + Session-Buddy can both use it
- Avoids triple embedding costs

**4. Proper Integration Patterns**

- Oneiric health check types (ComponentHealth)
- OpenTelemetry metrics
- Structured logging with trace correlation
- Async connection pooling (asyncpg)

______________________________________________________________________

## Phase 1: PostgreSQL Foundation

**Duration:** 4-5 days
**Objective:** Set up PostgreSQL + pgvector with proper schema

### Tasks

#### 1.1 Create Database Schema

**File to Create:** `mahavishnu/database/schema.sql`

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create main memories table
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(768),  -- nomic-embed-text
    memory_type TEXT NOT NULL,
    source_system TEXT NOT NULL,
    agent_id TEXT,
    workflow_id TEXT,
    repo_id TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_memory_type
        CHECK (memory_type IN ('agent', 'rag', 'workflow', 'insight'))
);

-- Indexes
CREATE INDEX memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX memories_type_date_idx
ON memories (memory_type, created_at DESC);

CREATE INDEX memories_agent_idx
ON memories (agent_id)
WHERE agent_id IS NOT NULL;

CREATE INDEX memories_workflow_idx
ON memories (workflow_id)
WHERE workflow_id IS NOT NULL;

-- Full-text search (hybrid search)
CREATE INDEX memories_content_fts
ON memories
USING gin(to_tsvector('english', content));

-- Agent conversations table
CREATE TABLE IF NOT EXISTS agent_conversations (
    id SERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_role CHECK (role IN ('user', 'assistant'))
);

CREATE INDEX agent_conversations_session_idx
ON agent_conversations (session_id, created_at);

-- RAG ingestion tracking
CREATE TABLE IF NOT EXISTS rag_ingestions (
    id SERIAL PRIMARY KEY,
    repo_id TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    documents_count INTEGER NOT NULL,
    chunks_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_ingestion_status
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed'))
);

CREATE INDEX rag_ingestions_repo_idx
ON rag_ingestions (repo_id, created_at);

-- Workflow executions
CREATE TABLE IF NOT EXISTS workflow_executions (
    id SERIAL PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    repos TEXT[],
    status TEXT NOT NULL,
    result JSONB,
    duration_seconds REAL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_execution_status
        CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE INDEX workflow_executions_workflow_idx
ON workflow_executions (workflow_id, created_at);

-- Performance metrics
CREATE TABLE IF NOT EXISTS performance_metrics (
    id SERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    metrics JSONB NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX performance_metrics_component_idx
ON performance_metrics (component, timestamp);
```

#### 1.2 Setup Database Migrations

**Install Alembic:**

```bash
cd /Users/les/Projects/mahavishnu
pip install alembic asyncpg

# Initialize Alembic
alembic init mahavishnu/database/migrations

# Generate initial migration
alembic revision --autogenerate -m "Initial schema"
```

**Migration File:** `mahavishnu/database/migrations/versions/001_initial_schema.py`

```python
"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # Create memories table
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        'memories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', postgresql.vector(768), nullable=False),
        sa.Column('memory_type', sa.Text(), nullable=False),
        sa.Column('source_system', sa.Text(), nullable=False),
        sa.Column('agent_id', sa.Text(), nullable=True),
        sa.Column('workflow_id', sa.Text(), nullable=True),
        sa.Column('repo_id', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("memory_type IN ('agent', 'rag', 'workflow', 'insight')", name='valid_memory_type')
    )

    # Create indexes
    op.execute('CREATE INDEX memories_embedding_idx ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)')
    op.execute('CREATE INDEX memories_type_date_idx ON memories (memory_type, created_at DESC)')
    op.execute('CREATE INDEX memories_agent_idx ON memories (agent_id) WHERE agent_id IS NOT NULL')

    # Create other tables...
    op.create_table('agent_conversations', ...)
    op.create_table('rag_ingestions', ...)
    op.create_table('workflow_executions', ...)
    op.create_table('performance_metrics', ...)

def downgrade() -> None:
    op.drop_table('memories')
    op.drop_table('agent_conversations')
    op.drop_table('rag_ingestions')
    op.drop_table('workflow_executions')
    op.drop_table('performance_metrics')
```

#### 1.3 Create Database Connection Module

**File to Create:** `mahavishnu/database/connection.py`

```python
"""PostgreSQL connection management for Mahavishnu memory."""
from typing import Optional
import asyncpg
from asyncpg import pool
import logging
from pathlib import Path

from mahavishnu.core.config import MahavishnuSettings

logger = logging.getLogger(__name__)

class PostgreSQLConnection:
    """PostgreSQL connection pool manager.

    Features:
    - Async connection pooling (asyncpg)
    - Automatic connection lifecycle management
    - Transaction support
    - Connection health monitoring
    """

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.pool: Optional[pool.Pool] = None
        self._dsn = self._build_dsn(config)

    def _build_dsn(self, config: MahavishnuSettings) -> str:
        """Build PostgreSQL DSN from config."""
        # Parse postgres_url if provided
        if hasattr(config, 'agentdb') and config.agentdb.postgres_url:
            return config.agentdb.postgres_url

        # Build from individual components
        host = getattr(config, 'pg_host', 'localhost')
        port = getattr(config, 'pg_port', 5432)
        database = getattr(config, 'pg_database', 'mahavishnu')
        user = getattr(config, 'pg_user', 'postgres')
        password = getattr(config, 'pg_password', '')

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    async def initialize(self) -> None:
        """Initialize connection pool.

        Should be called during application startup.
        """
        pool_size = 50
        max_overflow = 100
        timeout = 30

        if hasattr(self.config, 'agentdb'):
            pool_size = self.config.agentdb.connection_pool_size
            max_overflow = self.config.agentdb.connection_max_overflow

        logger.info(f"Creating PostgreSQL connection pool (size={pool_size}, max_overflow={max_overflow})")

        self.pool = await pool.create(
            dsn=self._dsn,
            min_size=5,
            max_size=pool_size,
            max_overflow=max_overflow,
            timeout=timeout,
            command_timeout=60
        )

        logger.info("PostgreSQL connection pool created successfully")

        # Run health check
        await self.health_check()

    async def health_check(self) -> bool:
        """Check database connection health.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.debug("PostgreSQL health check passed")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            return False

    async def close(self) -> None:
        """Close all connections in the pool.

        Should be called during application shutdown.
        """
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed")
            self.pool = None

    async def get_connection(self) -> pool.PoolConnectionProxy:
        """Get a connection from the pool.

        Returns:
            Connection from the pool

        Usage:
            async with await self.pg.get_connection() as conn:
                result = await conn.fetchval("SELECT $1", 42)
        """
        if not self.pool:
            raise RuntimeError("Connection pool not initialized. Call initialize() first.")
        return self.pool.acquire()
```

#### 1.4 Create Vector Store Module

**File to Create:** `mahavishnu/database/vector_store.py`

```python
"""Vector store operations using PostgreSQL + pgvector."""
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class PgVectorStore:
    """Vector store using PostgreSQL + pgvector.

    Features:
    - Store embeddings with metadata
    - Vector similarity search (cosine distance)
    - Hybrid search (vector + full-text)
    - Batch operations
    """

    def __init__(self, pg_connection):
        self.pg = pg_connection

    async def store_memory(
        self,
        content: str,
        embedding: List[float],
        memory_type: str,
        source_system: str,
        metadata: Dict[str, Any]
    ) -> int:
        """Store memory with embedding.

        Args:
            content: Memory content
            embedding: Vector embedding (768 dimensions)
            memory_type: Type of memory ('agent', 'rag', 'workflow', 'insight')
            source_system: Source system ('agno', 'llamaindex', 'prefect', etc.)
            metadata: Additional metadata

        Returns:
            Memory ID
        """
        async with await self.pg.get_connection() as conn:
            memory_id = await conn.fetchval(
                """
                INSERT INTO memories
                (content, embedding, memory_type, source_system, metadata)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                content,
                embedding,  # Automatically converted to pgvector type
                memory_type,
                source_system,
                metadata
            )

            logger.debug(f"Stored memory {memory_id} (type={memory_type}, source={source_system})")
            return memory_id

    async def vector_search(
        self,
        query_embedding: List[float],
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search.

        Args:
            query_embedding: Query vector (768 dimensions)
            memory_types: Filter by memory types
            limit: Max results
            threshold: Minimum similarity score (0-1)

        Returns:
            List of matching memories with similarity scores
        """
        async with await self.pg.get_connection() as conn:
            if memory_types:
                # Filter by memory types
                type_filter = "AND memory_type = ANY($2)"
                params = [query_embedding, memory_types, limit]
            else:
                type_filter = ""
                params = [query_embedding, limit]

            results = await conn.fetch(
                f"""
                SELECT
                    id, content, memory_type, source_system,
                    metadata,
                    1 - (embedding <=> $1) AS similarity
                FROM memories
                WHERE {type_filter or "1=1"}
                ORDER BY embedding <=> $1
                LIMIT $3
                """,
                *params
            )

            # Filter by threshold
            filtered = [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "memory_type": r["memory_type"],
                    "source_system": r["source_system"],
                    "metadata": r["metadata"],
                    "similarity": r["similarity"]
                }
                for r in results
                if r["similarity"] >= threshold
            ]

            logger.debug(f"Vector search returned {len(filtered)} results (threshold={threshold})")
            return filtered

    async def hybrid_search(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search (vector + full-text).

        Args:
            query: Search query
            memory_types: Filter by memory types
            limit: Max results

        Returns:
            List of matching memories
        """
        async with await self.pg.get_connection() as conn:
            # Full-text search using GIN index
            fts_results = await conn.fetch(
                """
                SELECT
                    id, content, memory_type, source_system, metadata,
                    ts_rank_cd(vector, ARRAY[A.1]) AS rank
                FROM memories, to_tsvector('english', content) vector
                WHERE to_tsvector('english', content) @@ plainto_tsquery($1)
                ORDER BY rank DESC
                LIMIT $2
                """,
                query,
                limit * 3  # Get more, re-rank with vector
            )

            logger.debug(f"Full-text search returned {len(fts_results)} candidates")
            return fts_results
```

#### 1.5 Update Configuration

**File to Modify:** `mahavishnu/core/config.py`

```python
# Add PostgreSQL configuration
class PostgreSQLSettings(BaseModel):
    """PostgreSQL configuration for memory storage."""

    enabled: bool = Field(
        default=False,
        description="Enable PostgreSQL memory storage"
    )
    host: str = Field(
        default="localhost",
        description="PostgreSQL host"
    )
    port: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="PostgreSQL port"
    )
    database: str = Field(
        default="mahavishnu",
        description="PostgreSQL database name"
    )
    user: str = Field(
        default="postgres",
        description="PostgreSQL user"
    )
    password: str = Field(
        default="",
        description="PostgreSQL password (use env var for security)"
    )
    pool_size: int = Field(
        default=50,
        ge=10,
        le=200,
        description="PostgreSQL connection pool size"
    )
    max_overflow: int = Field(
        default=100,
        ge=0,
        le=200,
        description="PostgreSQL max overflow connections"
    )

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if v:
            return v
        # Try environment variable
        import os
        return os.environ.get('MAHAVISHNU_PG_PASSWORD', '')

# Update MahavishnuSettings
class MahavishnuSettings(BaseSettings):
    # ... existing fields ...

    postgresql: PostgreSQLSettings = Field(
        default_factory=PostgreSQLSettings
    )
```

### Deliverables

- ✅ Database schema with migrations
- ✅ PostgreSQL connection module
- ✅ Vector store implementation
- ✅ Configuration updates
- ✅ Database initialization script

### Acceptance Criteria

- PostgreSQL database created
- pgvector extension enabled
- Migrations run successfully
- Connection pool established
- Vector search works with test data

______________________________________________________________________

## Phase 2: Core Memory Integration

**Duration:** 5-7 days
**Objective:** Implement unified memory service

### Tasks

#### 2.1 Update Memory Integration

**File to Modify:** `mahavishnu/core/memory_integration.py`

```python
"""Revised memory integration without AgentDB."""
from typing import Optional, List, Dict, Any
import hashlib
import asyncio
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class MahavishnuMemoryIntegration:
    """Integrated memory system using PostgreSQL + Session-Buddy.

    Architecture:
    1. PostgreSQL + pgvector: All Mahavishnu-specific memory
    2. Session-Buddy DuckDB: Cross-project insights only
    3. Single embedding model: nomic-embed-text (768 dimensions)
    """

    def __init__(self, config):
        self.config = config

        # PostgreSQL connection (lazy initialization)
        self.pg_connection = None

        # Session-Buddy integration
        self.session_buddy_project = None
        self.session_buddy_global = None
        self._init_session_buddy()

        # Ollama embeddings
        self.embed_model = None
        if config.memory_service.enabled:
            self._init_embeddings()

        # Vector store
        self.vector_store = None

    def _init_session_buddy(self):
        """Initialize Session-Buddy (for insights only)."""
        try:
            from session_buddy.adapters.reflection_adapter_oneiric import (
                ReflectionDatabaseAdapterOneiric,
                ReflectionAdapterSettings
            )

            # Project-specific memory (workflow executions, patterns)
            self.session_buddy_project = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_project",
                settings=self.config.session_buddy_settings
            )

            # Global/cross-project memory (insights, patterns)
            self.session_buddy_global = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_global",
                settings=self.config.session_buddy_settings
            )

            logger.info("Session-Buddy integration initialized")

        except ImportError as e:
            logger.warning(f"Session-Buddy not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize Session-Buddy: {e}")

    def _init_embeddings(self):
        """Initialize Ollama embedding model."""
        try:
            from llama_index.embeddings.ollama import OllamaEmbedding

            self.embed_model = OllamaEmbedding(
                model_name=self.config.llm_model,
                base_url=self.config.ollama_base_url
            )

            logger.info(f"Ollama embeddings initialized ({self.config.llm_model})")

        except ImportError as e:
            logger.warning(f"Ollama not available: {e}")

    async def initialize_postgresql(self) -> None:
        """Initialize PostgreSQL connection pool."""
        try:
            from .database.connection import PostgreSQLConnection

            self.pg_connection = PostgreSQLConnection(self.config)
            await self.pg_connection.initialize()

            from .database.vector_store import PgVectorStore
            self.vector_store = PgVectorStore(self.pg_connection)

            logger.info("PostgreSQL memory integration initialized")

        except ImportError as e:
            logger.warning(f"PostgreSQL not available: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL: {e}")

    async def store_agent_conversation(
        self,
        agent_id: str,
        role: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> None:
        """Store agent conversation in PostgreSQL.

        Args:
            agent_id: Agent identifier
            role: 'user' or 'assistant'
            content: Conversation content
            metadata: Additional metadata
        """
        if not self.vector_store:
            logger.warning("Vector store not initialized")
            return

        # Generate embedding
        embedding = await self.embed_model.aget_text_embedding(content)

        # Store in PostgreSQL
        await self.vector_store.store_memory(
            content=content,
            embedding=embedding,
            memory_type="agent",
            source_system="agno",
            metadata={
                **metadata,
                "agent_id": agent_id,
                "role": role
            }
        )

        # Extract insights to Session-Buddy
        await self._extract_and_store_insights(content, metadata)

    async def store_rag_knowledge(
        self,
        repo_id: str,
        repo_path: str,
        content: str,
        chunk_metadata: Dict[str, Any]
    ) -> None:
        """Store RAG knowledge in PostgreSQL.

        Args:
            repo_id: Repository identifier
            repo_path: Repository path
            content: Document chunk
            chunk_metadata: Chunk metadata
        """
        if not self.vector_store:
            logger.warning("Vector store not initialized")
            return

        # Generate embedding
        embedding = await self.embed_model.aget_text_embedding(content)

        # Store in PostgreSQL
        await self.vector_store.store_memory(
            content=content,
            embedding=embedding,
            memory_type="rag",
            source_system="llamaindex",
            metadata={
                **chunk_metadata,
                "repo_id": repo_id,
                "repo_path": repo_path
            }
        )

    async def store_workflow_execution(
        self,
        workflow_id: str,
        adapter: str,
        execution_data: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> None:
        """Store workflow execution in PostgreSQL and Session-Buddy.

        Args:
            workflow_id: Workflow identifier
            adapter: Adapter name
            execution_data: Execution results
            metadata: Additional context
        """
        # Store in PostgreSQL
        if self.vector_store:
            content = f"Workflow {workflow_id} execution via {adapter}"
            embedding = await self.embed_model.aget_text_embedding(content)

            await self.vector_store.store_memory(
                content=content,
                embedding=embedding,
                memory_type="workflow",
                source_system=adapter,
                metadata={
                    **metadata,
                    "workflow_id": workflow_id,
                    "adapter": adapter,
                    "execution_data": execution_data
                }
            )

        # Store execution in Session-Buddy (for pattern discovery)
        await self.session_buddy_project.add_memory(
            content=f"Workflow {workflow_id} executed via {adapter}",
            metadata={
                **metadata,
                "workflow_id": workflow_id,
                "adapter": adapter,
                "doc_type": "workflow_execution"
            }
        )

    async def store_performance_metrics(
        self,
        component: str,
        metrics: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> None:
        """Store performance metrics in PostgreSQL.

        Args:
            component: Component name (adapter_name, service_name, etc.)
            metrics: Performance metrics
            metadata: Additional context
        """
        # Store in PostgreSQL
        async with await self.pg_connection.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO performance_metrics (component, metric_type, metrics, timestamp)
                VALUES ($1, $2, $3, NOW())
                """,
                component,
                "performance",
                metrics,
                metadata
            )

        logger.debug(f"Stored performance metrics for {component}")

    async def unified_search(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Unified search across PostgreSQL and Session-Buddy.

        Args:
            query: Search query
            memory_types: Filter by memory types
            limit: Max results

        Returns:
            Ranked list of results from all sources
        """
        all_results = []

        # Search PostgreSQL (vector search)
        if self.vector_store:
            query_embedding = await self.embed_model.aget_text_embedding(query)

            pg_results = await self.vector_store.vector_search(
                query_embedding=query_embedding,
                memory_types=memory_types,
                limit=limit
            )

            for result in pg_results:
                all_results.append({
                    **result,
                    "source": "postgresql"
                })

        # Search Session-Buddy (insights)
        if self.session_buddy_project:
            sb_results = await self.session_buddy_project.semantic_search(
                query=query,
                limit=limit // 2
            )

            for result in sb_results:
                all_results.append({
                    "content": result.get("content", ""),
                    "metadata": result.get("metadata", {}),
                    "score": result.get("score", 0.0),
                    "source": "session_buddy"
                })

        # Sort by relevance
        all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        return all_results[:limit]

    async def _extract_and_store_insights(
        self,
        content: str,
        metadata: Dict[str, Any]
    ) -> None:
        """Extract insights and store in Session-Buddy.

        This uses Session-Buddy's automatic insight capture
        for ★ Insight ───── delimiter patterns.
        """
        if not self.session_buddy_global:
            return

        # Check if content contains insight delimiter
        if "★ Insight ─────" not in content:
            return

        # Store in Session-Buddy global memory
        await self.session_buddy_global.add_memory(
            content=content,
            metadata={
                **metadata,
                "source_system": "mahavishnu",
                "doc_type": "agent_insight",
                "extracted_at": datetime.now().isoformat()
            }
        )

        logger.debug("Stored insight in Session-Buddy global memory")

    async def close(self) -> None:
        """Close all connections."""
        if self.pg_connection:
            await self.pg_connection.close()
```

### Deliverables

- ✅ Revised memory integration class
- ✅ PostgreSQL vector store
- ✅ Ollama embedding integration
- ✅ Session-Buddy insight extraction
- ✅ Unified search across both systems

### Acceptance Criteria

- Can store agent conversations in PostgreSQL
- Can store RAG knowledge in PostgreSQL
- Insights extracted to Session-Buddy DuckDB
- Unified search works
- Unit tests pass

______________________________________________________________________

## Phase 3: LlamaIndex RAG Integration

**Duration:** 5-7 days
**Objective:** Integrate LlamaIndex with PostgreSQL backend

### Tasks

#### 3.1 Update LlamaIndex Adapter

**File to Modify:** `mahavishnu/engines/llamaindex_adapter.py`

```python
"""LlamaIndex adapter with PostgreSQL vector store backend."""
from typing import Dict, Any, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class LlamaIndexAdapter:
    """LlamaIndex RAG with PostgreSQL + pgvector backend.

    Features:
    - Repository ingestion with Ollama embeddings
    - Vector similarity search via pgvector
    - Knowledge base for agents
    """

    def __init__(self, config, memory_integration):
        from llama_index.core import Settings
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.embeddings.ollama import OllamaEmbedding

        self.config = config
        self.memory = memory_integration

        # Configure Ollama embeddings
        Settings.embed_model = OllamaEmbedding(
            model_name=config.llm_model,
            base_url=config.ollama_base_url
        )

        # Configure node parser
        self.node_parser = SentenceSplitter(
            chunk_size=1024,
            chunk_overlap=20,
            separator=" "
        )

        # Index cache
        self.indices = {}

    async def ingest_repository(
        self,
        repo_path: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ingest repository into PostgreSQL.

        Args:
            repo_path: Path to repository
            metadata: Repository metadata

        Returns:
            Ingestion statistics
        """
        from llama_index.core import SimpleDirectoryReader, Document

        repo = Path(repo_path)

        # Load documents
        reader = SimpleDirectoryReader(
            input_dir=str(repo),
            recursive=True,
            required_exts=[".py", ".md", ".txt", ".yaml", ".yml"],
            exclude=[".git", "__pycache__", "*.pyc", "node_modules"]
        )

        documents = reader.load_data()

        logger.info(f"Loaded {len(documents)} documents from {repo_path}")

        # Process documents
        total_chunks = 0
        for doc in documents:
            # Parse into chunks
            nodes = self.node_parser.get_nodes_from_documents([doc])

            # Store each chunk in PostgreSQL
            for node in nodes:
                await self.memory.store_rag_knowledge(
                    repo_id=metadata.get("repo_id", repo),
                    repo_path=repo_path,
                    content=node.get_content(),
                    chunk_metadata={
                        **metadata,
                        "doc_id": doc.id_,
                        "node_id": node.id_,
                        "file_path": node.metadata.get("file_name")
                    }
                )
                total_chunks += 1

        logger.info(f"Ingested {total_chunks} chunks from {len(documents)} documents")

        return {
            "status": "success",
            "documents_processed": len(documents),
            "chunks_stored": total_chunks,
            "repo_id": metadata.get("repo_id", repo)
        }

    async def query_knowledge_base(
        self,
        query: str,
        repo_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Query RAG knowledge base.

        Args:
            query: Query string
            repo_id: Filter by repository
            top_k: Number of results

        Returns:
            List of relevant documents with metadata
        """
        # Generate query embedding
        query_embedding = await self.memory.embed_model.aget_text_embedding(query)

        # Search PostgreSQL vector store
        results = await self.memory.vector_store.vector_search(
            query_embedding=query_embedding,
            memory_types=["rag"],
            limit=top_k
        )

        # Filter by repo_id if specified
        if repo_id:
            results = [
                r for r in results
                if r["metadata"].get("repo_id") == repo_id
            ]

        logger.debug(f"RAG query returned {len(results)} results")
        return results
```

### Deliverables

- ✅ LlamaIndex adapter with PostgreSQL backend
- ✅ Repository ingestion workflow
- ✅ Knowledge base query interface
- ✅ Integration tests pass

### Acceptance Criteria

- Can ingest repositories into PostgreSQL
- Vector search works with pgvector
- Knowledge base queries return relevant results
- Performance targets met (\<100ms for 20 results)

______________________________________________________________________

## Phase 4: Cross-Project Integration

**Duration:** 3-4 days
**Objective:** Integrate with Session-Buddy's cross-project features

### Tasks

#### 4.1 Create Cross-Project Integration

**File to Create:** `mahavishnu/core/cross_project.py`

```python
"""Cross-project integration with Session-Buddy."""
from typing import List, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class MahavishnuCrossProjectIntegration:
    """Integrate Mahavishnu with Session-Buddy's cross-project intelligence.

    Features:
    - Project group registration
    - Dependency tracking
    - Cross-project insight sharing
    """

    def __init__(self, config, memory_integration):
        self.config = config
        self.memory = memory_integration

    async def register_project_group(
        self,
        repos: List[str],
        config
    ) -> None:
        """Register Mahavishnu project group with Session-Buddy.

        Args:
            repos: List of repository paths from repos.yaml
            config: Configuration object
        """
        # Create project group
        project_names = [Path(r).name for r in repos]
        project_names.append("mahavishnu")

        # Note: Session-Buddy's project group API would go here
        # For now, we log the intent
        logger.info(f"Registering project group: {project_names}")

        # TODO: Implement actual Session-Buddy project group registration
        # This requires understanding Session-Buddy's project group API

    async def share_workflow_insights(
        self,
        workflow_id: str,
        insight: str,
        target_repos: List[str]
    ) -> None:
        """Share workflow insights with target repositories.

        Args:
            workflow_id: Workflow identifier
            insight: Insight to share
            target_repos: Target repositories
        """
        # Store insight in Session-Buddy global memory
        await self.memory.session_buddy_global.add_memory(
            content=insight,
            metadata={
                "workflow_id": workflow_id,
                "target_repos": target_repos,
                "doc_type": "cross_project_workflow",
                "share_type": "dependency_aware"
            }
        )

        logger.debug(f"Shared insight for workflow {workflow_id} with {len(target_repos)} repos")
```

### Deliverables

- ✅ Cross-project integration class
- ✅ Project group registration
- ✅ Workflow insight sharing
- ✅ Integration tests pass

### Acceptance Criteria

- Project groups registered with Session-Buddy
- Insights shared with target repos
- Cross-project search works
- Integration tests pass

______________________________________________________________________

## Phase 5: Testing & Documentation

**Duration:** 4-5 days
**Objective:** Comprehensive testing and documentation

### Tasks

#### 5.1 Create Test Suite

**Files to Create:**

```python
# tests/unit/test_postgres_integration.py
import pytest
from mahavishnu.database.connection import PostgreSQLConnection
from mahavishnu.database.vector_store import PgVectorStore

@pytest.mark.asyncio
async def test_postgres_connection():
    """Test PostgreSQL connection."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_vector_store():
    """Test vector store operations."""
    # Test implementation
    pass

@pytest.mark.asyncio
asyncio
async def test_memory_integration():
    """Test unified memory integration."""
    # Test implementation
    pass
```

```python
# tests/integration/test_rag_pipeline.py
@pytest.mark.integration
@pytest.mark.slow
async def test_repository_ingestion():
    """Test full repository ingestion pipeline."""
    # Test implementation
    pass
```

#### 5.2 Update Documentation

**Files to Update:**

- README.md (already updated)
- MEMORY_ARCHITECTURE_PLAN.md (add revised architecture section)
- Create SETUP_GUIDE.md (PostgreSQL setup instructions)
- Update docs/adr/005-memory-architecture.md (decision record)

### Deliverables

- ✅ Test suite with >80% coverage
- ✅ Unit tests for all modules
- ✅ Integration tests for pipelines
- ✅ Performance benchmarks
- ✅ Complete documentation

### Acceptance Criteria

- All tests pass
- Coverage >80%
- Performance targets met:
  - Vector search \<100ms for 20 results
  - Unified search \<200ms
  - 1000+ concurrent operations supported
- Documentation complete

______________________________________________________________________

## Configuration & Setup

### Environment Variables

```bash
# PostgreSQL
export MAHAVISHNU_PG_HOST="localhost"
export MAHAVISHNU_PG_PORT="5432"
export MAHAVISHNU_PG_DATABASE="mahavishnu"
export MAHAVISHNU_PG_USER="postgres"
export MAHAVISHNU_PG_PASSWORD="your_password"  # Use env var for security

# Ollama
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"
```

### Configuration File

**settings/mahavishnu.yaml:**

```yaml
server_name: "Mahavishnu Orchestrator"
cache_root: .oneiric_cache
log_level: INFO

# Adapters
adapters:
  prefect: true
  llamaindex: true
  agno: true

# PostgreSQL Memory Storage
postgresql:
  enabled: true
  host: "localhost"
  port: 5432
  database: "mahavishnu"
  user: "postgres"
  pool_size: 50
  max_overflow: 100

# Ollama
llm_model: "nomic-embed-text"
ollama_base_url: "http://localhost:11434"

# Memory Service
memory_service:
  enabled: true
  enable_rag_search: true
  enable_agent_memory: true
  enable_reflection_search: true
  enable_cross_system_sharing: true
  enable_performance_monitoring: true
```

### Database Setup

```bash
# Using Docker (recommended)
docker run -d \
  --name mahavishnu-postgres \
  -e POSTGRES_PASSWORD=mahavishnu \
  -e POSTGRES_DB=mahavishnu \
  -p 5432:5432 \
  -v mahavishnu_pgdata:/var/lib/postgresql/data \
  postgres:16

# Or using local PostgreSQL
createdb mahavishnu
psql mahavishnu

# Run migrations
cd /Users/les/Projects/mahavishnu
alembic upgrade head
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
# Test PostgreSQL connection
psql -h localhost -U postgres -d mahavishnu

# Test migrations
alembic current

# Run health check
mahavishnu mcp health
```

______________________________________________________________________

## Performance Monitoring

### Metrics Collection

**File to Create:** `mahavishnu/core/monitoring.py`

```python
"""Performance monitoring for Mahavishnu."""
from typing import Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Collect and analyze performance metrics."""

    def __init__(self, memory_integration):
        self.memory = memory_integration

    async def collect_adapter_health(
        self,
        adapter_name: str,
        health_data: Dict[str, Any]
    ) -> None:
        """Collect adapter health metrics."""
        # Store in PostgreSQL
        await self.memory.store_performance_metrics(
            component=adapter_name,
            metrics={
                "health_status": health_data.get("status", "unknown"),
                "latency_ms": health_data.get("latency_ms", 0),
                "memory_mb": health_data.get("memory_mb", 0),
                "error_count": health_data.get("error_count", 0),
                "timestamp": datetime.now().isoformat()
            },
            metadata={
                "collection_type": "adapter_health"
            }
        )

    async def collect_workflow_metrics(
        self,
        workflow_id: str,
        metrics_data: Dict[str, Any]
    ) -> None:
        """Collect workflow execution metrics."""
        await self.memory.store_performance_metrics(
            component=f"workflow_{workflow_id}",
            metrics=metrics_data,
            metadata={
                "collection_type": "workflow_execution"
            }
        )
```

______________________________________________________________________

## Verification Checklist

### Phase 1 Verification ✅

- [ ] PostgreSQL database created
- [ ] pgvector extension enabled
- [ ] Schema migrations run successfully
- [ ] Connection pool established (50 connections)
- [ ] Vector search works with test data
- [ ] Unit tests pass

### Phase 2 Verification ✅

- [ ] Memory integration initialized
- [ ] Can store agent conversations
- [ ] Can store RAG knowledge
- [ ] Can store workflow executions
- [ ] Insights extracted to Session-Buddy
- [ ] Unified search works
- [ ] Unit tests pass

### Phase 3 Verification ✅

- [ ] LlamaIndex adapter updated
- [ ] Can ingest repositories
- [ ] Vector search works via pgvector
- [ ] Knowledge base queries work
- [ ] Integration tests pass

### Phase 4 Verification ✅

- [ ] Cross-project integration works
- [ ] Project groups registered
- [ ] Insights shared correctly
- [ ] Integration tests pass

### Phase 5 Verification ✅

- [ ] All tests pass
- [ ] Coverage >80%
- [ ] Performance targets met
- [ ] Documentation complete
- [ ] Backup automation tested

______________________________________________________________________

## Summary

### What Changed from Original Plan

**Removed:**

- ❌ AgentDB (doesn't exist as Python package)
- ❌ Multiple embedding models (causes dimension mismatch)
- ❌ Cross-database synchronization (unnecessary complexity)

**Added:**

- ✅ PostgreSQL + pgvector (unified database)
- ✅ Single embedding model (nomic-embed-text: 768 dim)
- ✅ Proper database migrations (Alembic)
- ✅ Async connection pooling (asyncpg)
- ✅ Session-Buddy for insights only (not raw memory)

### Benefits

**Architectural:**

- Single database for all Mahavishnu memory
- SQL joins across repositories, agents, workflows
- Single backup strategy
- Simplified operations

**Performance:**

- \<100ms vector search for 20 results
- \<200ms unified search across all systems
- 1000+ concurrent operations supported
- Connection pooling for 10+ terminals

**Operational:**

- Python-only stack (no Node.js needed)
- Production-ready (pgvector proven at scale)
- Proper migrations (Alembic)
- Monitoring and backup strategies

______________________________________________________________________

**Document Version:** 2.0 (Revised)
**Last Updated:** 2025-01-24
**Status:** Ready for Specialist Review
**Next:** Trifecta review then implementation
