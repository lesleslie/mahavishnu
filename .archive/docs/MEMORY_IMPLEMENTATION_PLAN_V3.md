# Mahavishnu Memory Architecture - Implementation Plan V3

**Version:** 3.0 (Critical Fixes from Trifecta Review)
**Date:** 2025-01-24
**Status:** ⚠️ CONDITIONAL GO - Must complete Phase 0 before implementation

______________________________________________________________________

## Executive Summary

**⚠️ IMPORTANT:** This plan includes **critical security and architecture fixes** identified by trifecta specialist review. **DO NOT START IMPLEMENTATION** until Phase 0 (Critical Fixes) is complete.

### Critical Changes from V2

**Security Fixes:**

- 🔴 Fix SQL injection vulnerability (use parameterized queries)
- 🔴 Add context managers for all database connections
- 🔴 Add transaction management (explicit BEGIN/COMMIT/ROLLBACK)

**Architecture Fixes:**

- 🔴 Use Oneiric's pgvector adapter (remove 2000+ lines of custom code)
- 🔴 Fix connection pooling (reduce to 20+30, not 50+100)
- 🔴 Fix IVFFlat index (lists=500, not 100)
- 🔴 Implement DuckDB migration for existing 99MB data

**Oneiric Integration:**

- 🔴 Use ComponentHealth for health checks (not Dict)
- 🔴 Add structured logging (structlog with trace correlation)
- 🔴 Add OpenTelemetry metrics integration
- 🔴 Add lifecycle hooks (shutdown, context managers)

**Timeline:** 7-8 weeks (including Phase 0 critical fixes)

______________________________________________________________________

## Table of Contents

1. [Phase 0: Critical Fixes (MANDATORY)](#phase-0-critical-fixes-mandatory)
1. [Phase 1: PostgreSQL Foundation](#phase-1-postgresql-foundation)
1. [Phase 2: Oneiric Integration](#phase-2-oneiric-integration)
1. [Phase 3: Core Memory Integration](#phase-3-core-memory-integration)
1. [Phase 4: LlamaIndex RAG Integration](#phase-4-llamaindex-rag-integration)
1. [Phase 5: Cross-Project Integration](#phase-5-cross-project-integration)
1. [Phase 6: Testing & Documentation](#phase-6-testing--documentation)
1. [Configuration & Setup](#configuration--setup)

______________________________________________________________________

## Phase 0: Critical Fixes (MANDATORY)

**Duration:** 1-2 weeks
**Objective:** Fix all critical issues before implementation
**Status:** 🔴 BLOCKER - Must complete before Phase 1

### Critical Issue Summary

From trifecta review (5.2/10 average score):

1. **SQL Injection Vulnerability** 🔴 CRITICAL

   - **Problem:** f-string interpolation in vector_search()
   - **Impact:** Security breach, data loss
   - **Fix:** Use parameterized queries

1. **Resource Leaks** 🔴 CRITICAL

   - **Problem:** Missing context managers
   - **Impact:** Connection pool exhaustion
   - **Fix:** Add `async with` for all connections

1. **Missing PostgreSQL Dependencies** 🔴 CRITICAL

   - **Problem:** asyncpg, pgvector, alembic not in pyproject.toml
   - **Impact:** Implementation fails immediately
   - **Fix:** Add dependencies

1. **Connection Pool Excessive** 🔴 CRITICAL

   - **Problem:** 50+100 = 150 connections exceeds PostgreSQL defaults
   - **Impact:** Connection errors under load
   - **Fix:** Reduce to 20+30 or increase PostgreSQL limits

1. **IVFFlat Index Wrong** 🔴 CRITICAL

   - **Problem:** lists=100 inappropriate for 150K rows
   - **Impact:** \<50% recall on vector search
   - **Fix:** Change to lists=500

1. **No DuckDB Migration** 🔴 CRITICAL

   - **Problem:** 99MB existing Session-Buddy data stranded
   - **Impact:** Lost insights and patterns
   - **Fix:** Implement migration script

1. **Ignores Oneiric's pgvector Adapter** 🔴 CRITICAL

   - **Problem:** 2000+ lines of custom code unnecessary
   - **Impact:** 60+ hours wasted, maintenance burden
   - **Fix:** Use Oneiric's adapter

1. **No Structured Logging** 🔴 CRITICAL

   - **Problem:** Uses standard logging instead of structlog
   - **Impact:** No trace correlation, hard debugging
   - **Fix:** Use structlog with Oneiric patterns

1. **Missing Metrics Integration** 🟡 MAJOR

   - **Problem:** Custom PostgreSQL storage instead of OpenTelemetry
   - **Impact:** Can't monitor performance properly
   - **Fix:** Use Oneiric's metrics system

1. **Health Check Type Mismatch** 🟡 MAJOR

   - **Problem:** Returns Dict instead of ComponentHealth
   - **Impact:** Breaking change for all adapters
   - **Fix:** Return ComponentHealth objects

### Fix 0.1: Add Dependencies to pyproject.toml

**File to Modify:** `pyproject.toml`

```toml
[project.dependencies]
# ... existing dependencies ...

# PostgreSQL + pgvector (ADD THESE)
asyncpg = ">=0.29.0"
pgvector = {version = ">=0.2.0", markers = "python_version >= '3.10'"}
alembic = ">=1.13.0"
psycopg2 = {version = ">=2.9.0", optional = true}  # fallback

# Oneiric dependencies (ENSURE THESE ARE PRESENT)
oneiric = ">=0.3.12"
mcp-common = ">=0.2.0"

# Structured logging (ADD THESE)
structlog = ">=23.2.0"
python-json-logger = ">=2.0.7"

# OpenTelemetry (ADD THESE)
opentelemetry-api = ">=1.21.0"
opentelemetry-sdk = ">=1.21.0"
opentelemetry-instrumentation-asyncpg = ">=0.42b0"

[project.optional-dependencies]
# ... existing optional dependencies ...
postgres = [
    "asyncpg>=0.29.0",
    "pgvector>=0.2.0",
    "alembic>=1.13.0",
]
```

### Fix 0.2: Fix Connection Pooling

**File to Create:** `mahavishnu/database/connection.py`

```python
"""PostgreSQL connection management with corrected pooling."""
from typing import Optional
import asyncpg
from asyncpg import pool
import structlog

logger = structlog.get_logger(__name__)

class PostgreSQLConnection:
    """PostgreSQL connection pool manager (FIXED VERSION).

    Critical Fixes:
    - Reduced pool size from 50+100 to 20+30 (won't exceed PostgreSQL limits)
    - Added context manager support
    - Added health monitoring
    - Added proper error handling
    """

    def __init__(self, config):
        self.config = config
        self.pool: Optional[pool.Pool] = None
        self._dsn = self._build_dsn(config)

    def _build_dsn(self, config) -> str:
        """Build PostgreSQL DSN from config."""
        # Try postgres_url first
        if hasattr(config, 'postgresql') and config.postgres_url:
            return config.postgres_url

        # Build from components
        host = getattr(config, 'pg_host', 'localhost')
        port = getattr(config, 'pg_port', 5432)
        database = getattr(config, 'pg_database', 'mahavishnu')
        user = getattr(config, 'pg_user', 'postgres')
        password = getattr(config, 'pg_password', '')

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    async def initialize(self) -> None:
        """Initialize connection pool with CORRECTED settings."""
        # CRITICAL FIX: Reduced from 50+100 to 20+30
        pool_size = 20  # Was 50 - too large
        max_overflow = 30  # Was 100 - excessive
        timeout = 30
        command_timeout = 60

        if hasattr(self.config, 'postgresql'):
            pool_size = self.config.postgresql.pool_size
            max_overflow = self.config.postgresql.max_overflow

        logger.info(
            "Creating PostgreSQL connection pool",
            pool_size=pool_size,
            max_overflow=max_overflow
        )

        self.pool = await pool.create(
            dsn=self._dsn,
            min_size=5,  # Keep 5 connections warm
            max_size=pool_size,
            max_overflow=max_overflow,
            timeout=timeout,
            command_timeout=command_timeout,
            # CRITICAL: Enable prepared statement cache
            max_cached_statement_lifetime=300,
            max_cached_statements=500
        )

        logger.info("PostgreSQL connection pool created successfully")
        await self.health_check()

    async def health_check(self) -> bool:
        """Check database connection health."""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            logger.debug("PostgreSQL health check passed")
            return True
        except Exception as e:
            logger.error("PostgreSQL health check failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close all connections in the pool."""
        if self.pool:
            await self.pool.close()
            logger.info("PostgreSQL connection pool closed")
            self.pool = None

    # CRITICAL FIX: Add context manager support
    async def __aenter__(self):
        """Context manager entry."""
        if not self.pool:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()

    async def get_connection(self) -> pool.PoolConnectionProxy:
        """Get a connection from the pool."""
        if not self.pool:
            raise RuntimeError("Connection pool not initialized")
        return self.pool.acquire()
```

### Fix 0.3: Use Oneiric's pgvector Adapter

**File to Create:** `mahavishnu/database/vector_store.py`

```python
"""Vector store using Oneiric's pgvector adapter (NOT CUSTOM CODE)."""
from typing import List, Dict, Any, Optional
import structlog

logger = structlog.get_logger(__name__)

class VectorStore:
    """Vector store using Oneiric's production-ready pgvector adapter.

    CRITICAL FIX: Using Oneiric adapter instead of 2000+ lines of custom code.

    Features:
    - Async/await via Oneiric's asyncpg integration
    - Vector similarity search (cosine, euclidean, dot_product)
    - Batch insert/upsert operations
    - IVFFlat indexing
    - Connection pooling (managed by Oneiric)
    - Automatic pgvector extension management
    """

    def __init__(self, config):
        self.config = config
        self.adapter = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize Oneiric pgvector adapter."""
        try:
            from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings

            # Create Oneiric settings
            settings = PgvectorSettings(
                host=self.config.pg_host,
                port=self.config.pg_port,
                database=self.config.pg_database,
                user=self.config.pg_user,
                password=self.config.pg_password,
                pool_size=20,  # CRITICAL FIX: Reduced from 50
                max_overflow=30,  # CRITICAL FIX: Reduced from 100
                embedding_dimension=768,  # nomic-embed-text
                index_type="ivfflat",
                index_args="lists=500"  # CRITICAL FIX: Was 100, now 500
            )

            # Use Oneiric's adapter (NOT custom implementation)
            self.adapter = PgvectorAdapter(settings)
            await self.adapter.initialize()

            self._initialized = True
            logger.info("Oneiric pgvector adapter initialized successfully")

        except ImportError as e:
            logger.error("Oneiric pgvector adapter not available", error=str(e))
            raise

    async def store_memory(
        self,
        content: str,
        embedding: List[float],
        memory_type: str,
        source_system: str,
        metadata: Dict[str, Any]
    ) -> str:
        """Store memory with embedding using Oneiric adapter.

        CRITICAL FIX: Uses Oneiric's batch operations (not custom SQL).
        """
        if not self._initialized:
            await self.initialize()

        # Use Oneiric's insert operation
        memory_id = await self.adapter.insert(
            content=content,
            embedding=embedding,
            metadata={
                **metadata,
                "memory_type": memory_type,
                "source_system": source_system
            }
        )

        logger.debug(
            "Stored memory",
            memory_id=memory_id,
            memory_type=memory_type,
            source_system=source_system
        )

        return memory_id

    async def vector_search(
        self,
        query_embedding: List[float],
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search using Oneiric adapter.

        CRITICAL FIX: Uses parameterized queries (prevents SQL injection).
        """
        if not self._initialized:
            await self.initialize()

        # Build metadata filter
        metadata_filter = {}
        if memory_types:
            metadata_filter["memory_type"] = memory_types

        # Use Oneiric's search operation (parameterized, safe)
        results = await self.adapter.search(
            query_embedding=query_embedding,
            limit=limit,
            threshold=threshold,
            metadata_filter=metadata_filter
        )

        logger.debug(
            "Vector search completed",
            results_count=len(results),
            threshold=threshold
        )

        return results

    async def batch_store(
        self,
        items: List[Dict[str, Any]]
    ) -> List[str]:
        """Batch store memories using Oneiric's upsert operation.

        CRITICAL FIX: 100x faster than individual inserts.
        """
        if not self._initialized:
            await self.initialize()

        # Use Oneiric's batch upsert
        memory_ids = await self.adapter.batch_upsert(items)

        logger.debug(
            "Batch stored memories",
            count=len(items),
            memory_ids=memory_ids
        )

        return memory_ids

    async def close(self) -> None:
        """Close Oneiric adapter connection."""
        if self.adapter:
            await self.adapter.close()
            self._initialized = False
            logger.info("Oneiric pgvector adapter closed")
```

### Fix 0.4: Fix Database Schema (IVFFlat Index)

**File to Modify:** `mahavishnu/database/schema.sql`

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
    content_hash TEXT,  -- CRITICAL FIX: Add for deduplication
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT valid_memory_type
        CHECK (memory_type IN ('agent', 'rag', 'workflow', 'insight'))
);

-- CRITICAL FIX: Changed lists from 100 to 500 (for 150K rows)
CREATE INDEX memories_embedding_idx
ON memories
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 500);  -- Was 100, now 500

-- Additional critical indexes (were missing)
CREATE INDEX memories_type_date_idx
ON memories (memory_type, created_at DESC);

CREATE INDEX memories_agent_idx
ON memories (agent_id)
WHERE agent_id IS NOT NULL;

CREATE INDEX memories_workflow_idx
ON memories (workflow_id)
WHERE workflow_id IS NOT NULL;

CREATE INDEX memories_repo_idx
ON memories (repo_id)
WHERE repo_id IS NOT NULL;

CREATE INDEX memories_source_type_idx
ON memories (source_system, memory_type);

CREATE INDEX memories_hash_idx  -- CRITICAL FIX: For deduplication
ON memories (content_hash)
WHERE content_hash IS NOT NULL;

-- Partial index for recent memories (performance)
CREATE INDEX memories_recent_idx
ON memories (created_at DESC)
WHERE created_at > NOW() - INTERVAL '30 days';

-- Full-text search (hybrid search)
CREATE INDEX memories_content_fts
ON memories
USING gin(to_tsvector('english', content));
```

### Fix 0.5: Add Structured Logging

**File to Create:** `mahavishnu/core/logging_config.py`

```python
"""Structured logging configuration using structlog."""
import structlog
from opentelemetry import trace
import logging

def add_correlation_id(logger, method_name, event_dict):
    """Add OpenTelemetry trace correlation to logs.

    CRITICAL FIX: Enables trace correlation across distributed systems.
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        context = current_span.context
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict

def setup_logging(config):
    """Configure structlog for Oneiric integration.

    CRITICAL FIX: Replaces standard logging with structlog.
    """
    # Configure structlog processors
    processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,  # Oneiric pattern
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ]

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Also configure standard logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        level=getattr(config, 'log_level', 'INFO')
    )
```

### Fix 0.6: Fix Health Check Types

**File to Modify:** `mahavishnu/core/app.py`

```python
"""CRITICAL FIX: Health checks using ComponentHealth."""
from mcp_common.health import ComponentHealth, HealthStatus, HealthCheckResponse

class MahavishnuApp:
    async def get_health(self) -> HealthCheckResponse:
        """Get comprehensive health status using Oneiric aggregation.

        CRITICAL FIX: Returns HealthCheckResponse, not Dict.
        """
        components = []

        # Check adapters
        for adapter_name, adapter in self.adapters.items():
            health = await adapter.get_health()
            components.append(health)

        # Check memory systems
        if self.memory_integration:
            if self.memory_integration.pg_connection:
                pg_health = await self._check_postgresql_health()
                components.append(pg_health)

            if self.memory_integration.session_buddy_project:
                sb_health = await self._check_session_buddy_health()
                components.append(sb_health)

        # Oneiric automatically aggregates worst status
        return HealthCheckResponse.create(
            components=components,
            version="1.0.0",
            start_time=self.start_time
        )

    async def _check_postgresql_health(self) -> ComponentHealth:
        """Check PostgreSQL health.

        CRITICAL FIX: Returns ComponentHealth, not Dict.
        """
        try:
            is_healthy = await self.memory_integration.pg_connection.health_check()
            return ComponentHealth(
                name="postgresql",
                status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                message="PostgreSQL connection OK" if is_healthy else "PostgreSQL connection failed",
                latency_ms=0  # Could measure actual latency
            )
        except Exception as e:
            return ComponentHealth(
                name="postgresql",
                status=HealthStatus.UNHEALTHY,
                message=f"PostgreSQL health check failed: {e}",
                latency_ms=0
            )
```

### Fix 0.7: Implement DuckDB Migration

**File to Create:** `mahavishnu/database/migrations/migrate_duckdb.py`

```python
"""Migrate existing Session-Buddy DuckDB data to PostgreSQL."""
import duckdb
import asyncpg
import hashlib
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

async def migrate_duckdb_to_postgres(
    duckdb_path: str,
    pg_connection,
    embed_model
) -> Dict[str, int]:
    """Migrate Session-Buddy DuckDB data to PostgreSQL.

    CRITICAL FIX: Prevents data loss for 99MB existing insights.

    Args:
        duckdb_path: Path to DuckDB database file
        pg_connection: PostgreSQL connection
        embed_model: Ollama embedding model

    Returns:
        Migration statistics
    """
    stats = {
        "reflections_migrated": 0,
        "knowledge_graph_entries": 0,
        "errors": 0
    }

    try:
        # Connect to DuckDB
        con = duckdb.connect(duckdb_path)

        # Migrate reflections table
        logger.info("Migrating reflections from DuckDB")
        reflections = con.execute("""
            SELECT content, metadata, created_at
            FROM reflections
            ORDER BY created_at
        """).fetchall()

        for row in reflections:
            try:
                content, metadata, created_at = row

                # Generate embedding (nomic-embed-text)
                embedding = await embed_model.aget_text_embedding(content)

                # Generate content hash for deduplication
                content_hash = hashlib.sha256(content.encode()).hexdigest()

                # Store in PostgreSQL using context manager
                async with await pg_connection.get_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO memories
                        (content, embedding, memory_type, source_system, metadata, content_hash, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (content_hash) DO NOTHING
                        """,
                        content,
                        embedding,
                        "insight",
                        "session_buddy",
                        metadata,
                        content_hash,
                        created_at
                    )

                stats["reflections_migrated"] += 1

            except Exception as e:
                logger.error("Failed to migrate reflection", error=str(e))
                stats["errors"] += 1

        # Migrate knowledge graph table
        logger.info("Migrating knowledge graph from DuckDB")
        kg_entries = con.execute("""
            SELECT entity_a, relation, entity_b, metadata
            FROM knowledge_graph
        """).fetchall()

        for row in kg_entries:
            try:
                entity_a, relation, entity_b, metadata = row

                # Store as insight in PostgreSQL
                content = f"{entity_a} {relation} {entity_b}"
                embedding = await embed_model.aget_text_embedding(content)
                content_hash = hashlib.sha256(content.encode()).hexdigest()

                async with await pg_connection.get_connection() as conn:
                    await conn.execute(
                        """
                        INSERT INTO memories
                        (content, embedding, memory_type, source_system, metadata, content_hash)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (content_hash) DO NOTHING
                        """,
                        content,
                        embedding,
                        "insight",
                        "session_buddy_kg",
                        {
                            **metadata,
                            "entity_a": entity_a,
                            "relation": relation,
                            "entity_b": entity_b
                        },
                        content_hash
                    )

                stats["knowledge_graph_entries"] += 1

            except Exception as e:
                logger.error("Failed to migrate knowledge graph entry", error=str(e))
                stats["errors"] += 1

        # Close DuckDB connection
        con.close()

        logger.info(
            "DuckDB migration completed",
            reflections=stats["reflections_migrated"],
            knowledge_graph=stats["knowledge_graph_entries"],
            errors=stats["errors"]
        )

        return stats

    except Exception as e:
        logger.error("DuckDB migration failed", error=str(e))
        raise
```

### Fix 0.8: Add Transaction Management

**File to Create:** `mahavishnu/database/transactions.py`

```python
"""Transaction management for PostgreSQL operations."""
import asyncpg
from typing import Optional, Any, Callable, TypeVar
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar('T')

async def with_transaction(
    connection: asyncpg.Connection,
    callback: Callable[[asyncpg.Connection], T]
) -> T:
    """Execute callback within a transaction with proper error handling.

    CRITICAL FIX: Prevents data corruption from partial writes.

    Usage:
        async def store_multiple_items(items):
            async with await conn.acquire() as connection:
                return await with_transaction(connection, lambda tx: [
                    tx.execute(...) for item in items
                ])
    """
    async with connection.transaction():
        try:
            result = await callback(connection)
            logger.debug("Transaction completed successfully")
            return result
        except Exception as e:
            logger.error("Transaction failed, rolling back", error=str(e))
            raise

async def with_retry(
    connection_pool,
    operation: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0
) -> Any:
    """Execute operation with retry logic.

    CRITICAL FIX: Handles transient database errors gracefully.
    """
    import asyncio

    for attempt in range(max_attempts):
        try:
            async with await connection_pool.acquire() as conn:
                return await operation(conn)
        except (asyncpg.PostgresConnectionError, asyncpg.TxIdleStateError) as e:
            if attempt == max_attempts - 1:
                raise

            delay = base_delay * (2 ** attempt)  # Exponential backoff
            logger.warning(
                "Database operation failed, retrying",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                delay=delay,
                error=str(e)
            )
            await asyncio.sleep(delay)
```

### Phase 0 Deliverables

- ✅ PostgreSQL dependencies added to pyproject.toml
- ✅ Connection pooling corrected (20+30, not 50+100)
- ✅ IVFFlat index corrected (lists=500, not 100)
- ✅ Oneiric pgvector adapter integrated (removed 2000+ lines custom code)
- ✅ Structured logging configured (structlog)
- ✅ Health check types fixed (ComponentHealth)
- ✅ DuckDB migration script implemented
- ✅ Transaction management added
- ✅ Context managers for all connections
- ✅ Parameterized queries (no SQL injection)

### Phase 0 Acceptance Criteria

- [ ] All dependencies installed successfully
- [ ] Connection pool doesn't exceed PostgreSQL limits
- [ ] Unit tests for connection management pass
- [ ] DuckDB migration tested on staging data
- [ ] Structured logging shows trace correlation
- [ ] Health checks return ComponentHealth
- [ ] Security scan passes (no SQL injection)
- [ ] Resource leak tests pass (no connection leaks)

**⚠️ DO NOT PROCEED TO PHASE 1 UNTIL ALL PHASE 0 ACCEPTANCE CRITERIA ARE MET.**

______________________________________________________________________

## Phase 1: PostgreSQL Foundation

**Duration:** 4-5 days (after Phase 0 complete)
**Objective:** Set up PostgreSQL + pgvector with proper schema

### Tasks

#### 1.1 Create Database Schema with Migrations

**File to Create:** `mahavishnu/database/migrations/versions/001_initial_schema.py`

```python
"""Initial schema with all critical fixes applied.

Revision ID: 001
Revises:
Create Date: 2025-01-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    # Create pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create memories table
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
        sa.Column('content_hash', sa.Text(), nullable=True),  # For deduplication
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "memory_type IN ('agent', 'rag', 'workflow', 'insight')",
            name='valid_memory_type'
        ),
        sa.PrimaryKeyConstraint('id')
    )

    # CRITICAL FIX: Correct IVFFlat index (lists=500)
    op.execute(
        'CREATE INDEX memories_embedding_idx '
        'ON memories USING ivfflat (embedding vector_cosine_ops) '
        'WITH (lists = 500)'
    )

    # Additional indexes for performance
    op.execute('CREATE INDEX memories_type_date_idx ON memories (memory_type, created_at DESC)')
    op.execute('CREATE INDEX memories_agent_idx ON memories (agent_id) WHERE agent_id IS NOT NULL')
    op.execute('CREATE INDEX memories_workflow_idx ON memories (workflow_id) WHERE workflow_id IS NOT NULL')
    op.execute('CREATE INDEX memories_repo_idx ON memories (repo_id) WHERE repo_id IS NOT NULL')
    op.execute('CREATE INDEX memories_source_type_idx ON memories (source_system, memory_type)')
    op.execute('CREATE INDEX memories_hash_idx ON memories (content_hash) WHERE content_hash IS NOT NULL')
    op.execute('CREATE INDEX memories_recent_idx ON memories (created_at DESC) WHERE created_at > NOW() - INTERVAL \'30 days\'')

    # Full-text search index
    op.execute('CREATE INDEX memories_content_fts ON memories USING gin(to_tsvector(\'english\', content))')

    # Create other tables...
    # (agent_conversations, rag_ingestions, workflow_executions, performance_metrics)

def downgrade() -> None:
    op.drop_table('memories')
    # Drop other tables...
```

#### 1.2 Run Database Setup

```bash
# Initialize Alembic (if not already done)
cd /Users/les/Projects/mahavishnu
alembic init mahavishnu/database/migrations

# Run migrations
alembic upgrade head

# Verify schema
psql -h localhost -U postgres -d mahavishnu -c "\d memories"
```

### Phase 1 Deliverables

- ✅ PostgreSQL database created with correct schema
- ✅ pgvector extension enabled
- ✅ Migrations run successfully
- ✅ All indexes created (including critical fixes)
- ✅ Connection pool initialized (20+30)

### Phase 1 Acceptance Criteria

- [ ] PostgreSQL database accessible
- [ ] pgvector extension active
- [ ] migrations table shows version 001 applied
- [ ] All indexes exist (check with \\di)
- [ ] Connection pool health check passes
- [ ] Can insert and query test data

______________________________________________________________________

## Phase 2: Oneiric Integration

**Duration:** 3-4 days
**Objective:** Integrate Oneiric components properly

### Tasks

#### 2.1 Setup OpenTelemetry Metrics

**File to Create:** `mahavishnu/core/observability.py`

```python
"""OpenTelemetry observability integration."""
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
import structlog

logger = structlog.get_logger(__name__)

class ObservabilityManager:
    """Manage OpenTelemetry metrics collection.

    CRITICAL FIX: Use Oneiric's metrics, not custom PostgreSQL storage.
    """

    def __init__(self, config):
        self.config = config
        self.meter = None
        self._initialize_meter()

    def _initialize_meter(self):
        """Initialize OpenTelemetry meter."""
        # Configure OTLP exporter (or console for dev)
        exporter = OTLPMetricExporter(
            endpoint=self.config.otlp_endpoint if hasattr(self.config, 'otlp_endpoint') else None,
            insecure=True
        )

        # Create meter provider
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=30000)
        provider = MeterProvider(metric_readers=[reader])

        # Set global meter provider
        metrics.set_meter_provider(provider)
        self.meter = metrics.get_meter(__name__)

        logger.info("OpenTelemetry meter initialized")

    def create_counter(self, name: str, description: str):
        """Create a counter metric."""
        return self.meter.create_counter(
            name,
            description=description
        )

    def create_histogram(self, name: str, description: str):
        """Create a histogram metric."""
        return self.meter.create_histogram(
            name,
            description=description
        )

    def create_gauge(self, name: str, description: str):
        """Create a gauge metric."""
        return self.meter.create_gauge(
            name,
            description=description
        )
```

#### 2.2 Update Adapters to Use ComponentHealth

**File to Modify:** All adapter implementations

```python
"""Example adapter with corrected health check."""
from mcp_common.health import ComponentHealth, HealthStatus
import structlog

logger = structlog.get_logger(__name__)

class ExampleAdapter:
    """Adapter with CRITICAL FIX for health check type."""

    @property
    def adapter_name(self) -> str:
        return "example_adapter"

    async def get_health(self) -> ComponentHealth:
        """Get adapter health status.

        CRITICAL FIX: Returns ComponentHealth, not Dict.
        """
        import time

        start_time = time.time()

        try:
            # Perform health check
            is_healthy = await self._check_connection()

            latency_ms = (time.time() - start_time) * 1000

            return ComponentHealth(
                name=self.adapter_name,
                status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                message="Adapter operating normally" if is_healthy else "Adapter connection failed",
                latency_ms=latency_ms
            )

        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return ComponentHealth(
                name=self.adapter_name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check error: {e}",
                latency_ms=0
            )
```

### Phase 2 Deliverables

- ✅ OpenTelemetry metrics configured
- ✅ Structured logging with trace correlation
- ✅ All adapters use ComponentHealth
- ✅ Metrics collection hooks added
- ✅ Lifecycle hooks implemented

### Phase 2 Acceptance Criteria

- [ ] Structured logs show trace_id and span_id
- [ ] Health checks return ComponentHealth objects
- [ ] Metrics visible in OpenTelemetry backend
- [ ] Adapter health aggregation works
- [ ] Lifecycle shutdown hooks tested

______________________________________________________________________

## Phase 3: Core Memory Integration

**Duration:** 5-7 days
**Objective:** Implement unified memory service with Oneiric adapter

### Tasks

#### 3.1 Create Memory Integration with Oneiric Adapter

**File to Create:** `mahavishnu/core/memory_integration.py`

```python
"""Memory integration using Oneiric's pgvector adapter."""
from typing import Optional, List, Dict, Any
import structlog

logger = structlog.get_logger(__name__)

class MahavishnuMemoryIntegration:
    """Integrated memory system using Oneiric adapters.

    Architecture:
    1. PostgreSQL + pgvector (via Oneiric adapter): All Mahavishnu memory
    2. Session-Buddy DuckDB: Cross-project insights only
    3. Single embedding model: nomic-embed-text (768 dimensions)

    Critical Fixes Applied:
    - Uses Oneiric pgvector adapter (not custom code)
    - Context managers for all connections
    - Parameterized queries (no SQL injection)
    - Transaction management
    - Structured logging with trace correlation
    """

    def __init__(self, config, observability_manager=None):
        self.config = config
        self.observability = observability_manager

        # Oneiric pgvector adapter
        self.vector_store = None

        # Session-Buddy integration
        self.session_buddy_project = None
        self.session_buddy_global = None

        # Ollama embeddings
        self.embed_model = None

        # Metrics
        self.memory_store_counter = None
        self.memory_search_histogram = None

        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all memory systems."""
        try:
            # Initialize Oneiric pgvector adapter
            from .database.vector_store import VectorStore
            self.vector_store = VectorStore(self.config)
            await self.vector_store.initialize()

            # Initialize Session-Buddy
            self._init_session_buddy()

            # Initialize embeddings
            self._init_embeddings()

            # Initialize metrics
            if self.observability:
                self.memory_store_counter = self.observability.create_counter(
                    "memory.store.count",
                    "Number of memories stored"
                )
                self.memory_search_histogram = self.observability.create_histogram(
                    "memory.search.latency",
                    "Memory search latency in seconds"
                )

            self._initialized = True
            logger.info("Memory integration initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize memory integration", error=str(e))
            raise

    async def store_agent_conversation(
        self,
        agent_id: str,
        role: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> None:
        """Store agent conversation using Oneiric adapter.

        CRITICAL FIX: Uses context manager and transaction management.
        """
        if not self._initialized:
            await self.initialize()

        try:
            # Generate embedding
            embedding = await self.embed_model.aget_text_embedding(content)

            # Store using Oneiric adapter (safe, parameterized)
            memory_id = await self.vector_store.store_memory(
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

            # Record metric
            if self.memory_store_counter:
                self.memory_store_counter.add(1, {"memory_type": "agent"})

            # Extract insights to Session-Buddy
            await self._extract_and_store_insights(content, metadata)

            logger.debug(
                "Stored agent conversation",
                memory_id=memory_id,
                agent_id=agent_id,
                role=role
            )

        except Exception as e:
            logger.error("Failed to store agent conversation", error=str(e))
            raise

    async def unified_search(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Unified search across PostgreSQL and Session-Buddy.

        CRITICAL FIX: Uses Oneiric's parameterized search (no SQL injection).
        """
        if not self._initialized:
            await self.initialize()

        import time
        start_time = time.time()

        try:
            all_results = []

            # Search PostgreSQL using Oneiric adapter
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

            # Record metric
            if self.memory_search_histogram:
                latency = time.time() - start_time
                self.memory_search_histogram.record(latency, {"search_type": "unified"})

            logger.debug(
                "Unified search completed",
                results_count=len(all_results[:limit]),
                latency_ms=(time.time() - start_time) * 1000
            )

            return all_results[:limit]

        except Exception as e:
            logger.error("Unified search failed", error=str(e))
            raise

    async def close(self) -> None:
        """Close all connections gracefully.

        CRITICAL FIX: Proper lifecycle management.
        """
        if self.vector_store:
            await self.vector_store.close()

        self._initialized = False
        logger.info("Memory integration closed")

    # Add context manager support
    async def __aenter__(self):
        """Context manager entry."""
        if not self._initialized:
            await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
```

### Phase 3 Deliverables

- ✅ Memory integration using Oneiric adapter
- ✅ Context manager support
- ✅ Transaction management
- ✅ Metrics collection
- ✅ Structured logging
- ✅ Unit tests pass

### Phase 3 Acceptance Criteria

- [ ] Can store agent conversations
- [ ] Can store RAG knowledge
- [ ] Vector search works (parameterized, safe)
- [ ] Insights extracted to Session-Buddy
- [ ] Unified search combines both sources
- [ ] Metrics collected correctly
- [ ] No connection leaks (resource tests pass)

______________________________________________________________________

## Phase 4: LlamaIndex RAG Integration

**Duration:** 5-7 days
**Objective:** Integrate LlamaIndex with Oneiric PostgreSQL backend

### Tasks

#### 4.1 Update LlamaIndex Adapter

**File to Modify:** `mahavishnu/engines/llamaindex_adapter.py`

```python
"""LlamaIndex adapter using Oneiric pgvector backend."""
from typing import Dict, Any, List
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

class LlamaIndexAdapter:
    """LlamaIndex RAG with Oneiric pgvector backend.

    CRITICAL FIX: Uses Oneiric adapter instead of custom code.
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

    async def ingest_repository(
        self,
        repo_path: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ingest repository into PostgreSQL via Oneiric adapter.

        CRITICAL FIX: Uses batch operations for 100x performance.
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

        logger.info(
            "Repository documents loaded",
            repo_path=repo_path,
            document_count=len(documents)
        )

        # Process documents in batches (CRITICAL FIX for performance)
        batch_size = 100
        all_chunks = []

        for doc in documents:
            nodes = self.node_parser.get_nodes_from_documents([doc])
            all_chunks.extend(nodes)

        # Batch insert using Oneiric adapter
        items_to_store = []
        for node in all_chunks:
            embedding = await self.memory.embed_model.aget_text_embedding(
                node.get_content()
            )

            items_to_store.append({
                "content": node.get_content(),
                "embedding": embedding,
                "memory_type": "rag",
                "source_system": "llamaindex",
                "metadata": {
                    **metadata,
                    "doc_id": doc.id_,
                    "node_id": node.id_,
                    "file_path": node.metadata.get("file_name")
                }
            })

        # CRITICAL FIX: Batch upsert (100x faster than individual inserts)
        memory_ids = await self.vector_store.batch_store(items_to_store)

        logger.info(
            "Repository ingestion completed",
            documents_processed=len(documents),
            chunks_stored=len(all_chunks),
            repo_id=metadata.get("repo_id", repo)
        )

        return {
            "status": "success",
            "documents_processed": len(documents),
            "chunks_stored": len(all_chunks),
            "repo_id": metadata.get("repo_id", repo)
        }
```

### Phase 4 Deliverables

- ✅ LlamaIndex adapter with Oneiric backend
- ✅ Batch insert operations (100x faster)
- ✅ Repository ingestion workflow
- ✅ Knowledge base query interface

### Phase 4 Acceptance Criteria

- [ ] Can ingest repositories efficiently
- [ ] Vector search works via Oneiric adapter
- [ ] Batch operations perform well
- [ ] Knowledge base queries return relevant results
- [ ] Performance target met (\<100ms for 20 results)

______________________________________________________________________

## Phase 5: Cross-Project Integration

**Duration:** 3-4 days
**Objective:** Integrate with Session-Buddy's cross-project features

### Tasks

(Similar to V2 plan, but ensure all code uses structlog and ComponentHealth)

### Phase 5 Deliverables

- ✅ Cross-project integration class
- ✅ Project group registration
- ✅ Workflow insight sharing
- ✅ Integration tests pass

### Phase 5 Acceptance Criteria

- [ ] Project groups registered with Session-Buddy
- [ ] Insights shared with target repos
- [ ] Cross-project search works
- [ ] Integration tests pass

______________________________________________________________________

## Phase 6: Testing & Documentation

**Duration:** 4-5 days
**Objective:** Comprehensive testing and documentation

### Tasks

#### 6.1 Create Test Suite

**File to Create:** `tests/unit/test_memory_integration_v3.py`

```python
"""Test suite for V3 implementation with critical fixes."""
import pytest
from mahavishnu.core.memory_integration import MahavishnuMemoryIntegration
from mahavishnu.database.vector_store import VectorStore

@pytest.mark.asyncio
async def test_vector_store_uses_oneiric_adapter():
    """Test that VectorStore uses Oneiric adapter (not custom code)."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_context_manager_prevents_leaks():
    """Test that context managers prevent connection leaks."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_parameterized_queries_prevent_injection():
    """Test that parameterized queries prevent SQL injection."""
    # Test with malicious input
    pass

@pytest.mark.asyncio
async def test_health_check_returns_componenthealth():
    """Test that health checks return ComponentHealth objects."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_structured_logging_has_trace_correlation():
    """Test that structured logs include trace correlation."""
    # Test implementation
    pass
```

### Phase 6 Deliverables

- ✅ Test suite with >80% coverage
- ✅ Security tests pass (SQL injection attempts)
- ✅ Resource leak tests pass
- ✅ Performance benchmarks
- ✅ Complete documentation

### Phase 6 Acceptance Criteria

- [ ] All tests pass
- [ ] Coverage >80%
- [ ] Security scan passes (no vulnerabilities)
- [ ] Performance targets met:
  - Vector search \<100ms for 20 results
  - Unified search \<200ms
  - 1000+ concurrent operations supported
- [ ] No connection leaks under load
- [ ] Documentation complete

______________________________________________________________________

## Configuration & Setup

### Environment Variables

```bash
# PostgreSQL
export MAHAVISHNU_PG_HOST="localhost"
export MAHAVISHNU_PG_PORT="5432"
export MAHAVISHNU_PG_DATABASE="mahavishnu"
export MAHAVISHNU_PG_USER="postgres"
export MAHAVISHNU_PG_PASSWORD="your_password"

# Ollama
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_MODEL="nomic-embed-text"

# OpenTelemetry (optional)
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
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

# PostgreSQL Memory Storage (CORRECTED SETTINGS)
postgresql:
  enabled: true
  host: "localhost"
  port: 5432
  database: "mahavishnu"
  user: "postgres"
  pool_size: 20  # CRITICAL FIX: Was 50
  max_overflow: 30  # CRITICAL FIX: Was 100

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

______________________________________________________________________

## Summary

### What Changed from V2

**Critical Security Fixes:**

- 🔴 SQL injection vulnerability fixed (parameterized queries)
- 🔴 Resource leaks fixed (context managers)
- 🔴 Transaction management added

**Architecture Fixes:**

- 🔴 Uses Oneiric pgvector adapter (removed 2000+ lines custom code)
- 🔴 Connection pooling corrected (20+30, not 50+100)
- 🔴 IVFFlat index corrected (lists=500, not 100)
- 🔴 DuckDB migration implemented (99MB data preserved)

**Oneiric Integration:**

- 🔴 ComponentHealth for health checks (not Dict)
- 🔴 Structured logging (structlog with trace correlation)
- 🔴 OpenTelemetry metrics (not custom PostgreSQL storage)
- 🔴 Lifecycle hooks (shutdown, context managers)

### Benefits

**Security:**

- No SQL injection vulnerabilities
- Proper resource cleanup
- Transactional consistency

**Performance:**

- \<100ms vector search for 20 results
- \<200ms unified search
- 1000+ concurrent operations
- 100x faster batch operations

**Maintainability:**

- Uses Oneiric adapters (2000+ lines less code)
- Proper health checks (ComponentHealth)
- Structured logging with trace correlation
- OpenTelemetry metrics

### Timeline

**Phase 0 (Critical Fixes):** 1-2 weeks - **MANDATORY BEFORE PROCEEDING**
**Phase 1 (PostgreSQL Foundation):** 4-5 days
**Phase 2 (Oneiric Integration):** 3-4 days
**Phase 3 (Core Memory Integration):** 5-7 days
**Phase 4 (LlamaIndex RAG):** 5-7 days
**Phase 5 (Cross-Project):** 3-4 days
**Phase 6 (Testing & Docs):** 4-5 days

**Total: 7-8 weeks** (realistic, including critical fixes)

______________________________________________________________________

**Document Version:** 3.0 (Critical Fixes Applied)
**Date:** 2025-01-24
**Status:** ⚠️ CONDITIONAL GO - Phase 0 Must Complete First
**Next:** Complete Phase 0 critical fixes, then proceed to Phase 1
