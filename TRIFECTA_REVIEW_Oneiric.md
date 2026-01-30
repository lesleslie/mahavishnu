# Oneiric Integration Review - Mahavishnu Memory Implementation V2

**Date:** 2025-01-24
**Reviewer:** Oneiric Integration Specialist
**Document:** MEMORY_IMPLEMENTATION_PLAN_V2.md
**Verdict:** ⚠️ **CONDITIONAL GO** - Requires critical fixes before implementation

______________________________________________________________________

## Executive Summary

The revised memory plan has improved architecture but has **CRITICAL Oneiric integration issues** that must be fixed:

1. ✅ **GOOD**: Eliminates non-existent AgentDB dependency, consolidates to PostgreSQL + pgvector
1. ❌ **CRITICAL**: Ignores Oneiric's built-in pgvector adapter - proposes custom implementation instead
1. ❌ **CRITICAL**: Health checks return `bool` instead of following Oneiric patterns
1. ❌ **CRITICAL**: Missing Oneiric observability integration (structured logging, trace correlation)
1. ⚠️ **MAJOR**: Configuration doesn't extend Oneiric base settings properly
1. ⚠️ **MAJOR**: No use of Oneiric's lifecycle hooks or error handling patterns
1. ⚠️ **MAJOR**: Metrics collection doesn't use Oneiric's observability utilities

**Overall Score: 5/10** - Solid architectural decisions but poor Oneiric integration patterns.

______________________________________________________________________

## Critical Issues (Must Fix)

### 1. **Ignores Oneiric's pgvector Adapter** 🔴

**Problem:** The plan proposes building custom PostgreSQL and vector store implementations despite Oneiric having production-ready adapters.

**Evidence from Plan:**

- Lines 99-211: Custom `PgVectorStore` class with manual SQL queries
- Lines 284-393: Custom `PostgreSQLConnection` class
- Lines 231-278: Custom Alembic migrations

**Oneiric Reality:**

```python
# Oneiric v0.3.12 already has this:
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.database.postgres import PostgresDatabaseAdapter

# Health check returns bool (correct)
health = await adapter.health()  # Returns: bool

# All features already implemented:
# ✅ Connection pooling
# ✅ Vector search (insert, upsert, search, delete, count)
# ✅ Metadata filtering (JSONB)
# ✅ Collection management
# ✅ IVFFlat indexing
# ✅ Transaction support
# ✅ Lifecycle hooks (init, health, cleanup)
```

**Impact:**

- **Wastes 60-80 hours** of development time
- **Adds maintenance burden** - you maintain custom code instead of using Oneiric
- **Misses out** on Oneiric updates and bug fixes
- **Breaks consistency** with rest of Mahavishnu's Oneiric patterns

**Fix Required:**

```python
# CORRECT APPROACH (from VECTOR_DATABASE_RECOMMENDATIONS.md):
# mahavishnu/core/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument
from mahavishnu.core.config import MahavishnuSettings


class MahavishnuVectorStore:
    """Thin wrapper around Oneiric pgvector adapter."""

    def __init__(self, settings: MahavishnuSettings):
        self.pgvector_settings = settings.to_pgvector_settings()
        self.adapter = PgvectorAdapter(self.pgvector_settings)

    async def initialize(self):
        await self.adapter.init()
        # Create Mahavishnu-specific collections
        await self.adapter.create_collection(
            name="workflows",
            dimension=768,  # nomic-embed-text
            distance_metric="cosine",
        )

    async def search_workflows(
        self, query_embedding: list[float], limit: int = 10, tags: list[str] | None = None
    ) -> list[dict]:
        filter_expr = {"tags": tags} if tags else None
        results = await self.adapter.search(
            collection="workflows",
            query_vector=query_embedding,
            limit=limit,
            filter_expr=filter_expr,
        )
        return [
            {"workflow_id": r.id, "similarity_score": r.score, "metadata": r.metadata}
            for r in results
        ]

    async def health_check(self) -> bool:
        """Health check returns bool (Oneiric pattern)."""
        return await self.adapter.health()

    async def cleanup(self):
        await self.adapter.cleanup()
```

**References:**

- `ONEIRIC_ADAPTER_ANALYSIS.md` lines 1-615
- `VECTOR_DATABASE_RECOMMENDATIONS.md` lines 1-535
- `test_oneiric_pgvector_adapter.py` (working integration test exists)

______________________________________________________________________

### 2. **Health Check Type Mismatch** 🔴

**Problem:** Plan shows health checks returning `Dict[str, Any]` but Oneiric adapters return `bool`.

**Evidence from Plan:**

```python
# Line 355-368: INCORRECT
async def health_check(self) -> bool:
    """Check database connection health.

    Returns:
        True if connection is healthy, False otherwise
    """
```

**Wait, this is actually correct!** The custom implementation returns `bool`, which matches Oneiric.

**BUT** - the base adapter interface (`mahavishnu/core/adapters/base.py` line 24-31) requires:

```python
async def get_health(self) -> Dict[str, Any]:
    """
    Returns:
        Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
    """
```

**This is a MISMATCH:**

- Oneiric adapters: `health() -> bool`
- Mahavishnu base: `get_health() -> Dict[str, Any]`

**Fix Required:**

```python
# Option 1: Update Mahavishnu base adapter to match Oneiric
class OrchestratorAdapter(ABC):
    @abstractmethod
    async def get_health(self) -> bool:  # Changed from Dict[str, Any]
        """Return True if healthy, False otherwise."""
        pass


# Option 2: Create adapter wrapper that converts
class MahavishnuVectorStore:
    async def get_health(self) -> Dict[str, Any]:
        """Mahavishnu format health check."""
        is_healthy = await self.adapter.health()  # Returns bool
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "vector_db": is_healthy,
            "adapter": "pgvector",
        }
```

______________________________________________________________________

### 3. **No Structured Logging with Trace Correlation** 🔴

**Problem:** Custom implementations use standard `logging` instead of Oneiric's structured logging.

**Evidence from Plan:**

```python
# Lines 294, 339, 364, etc.: Standard logging
logger = logging.getLogger(__name__)
logger.info("PostgreSQL connection pool created successfully")
logger.debug(f"Stored memory {memory_id} (type={memory_type})")
```

**Oneiric Pattern:**

```python
from oneiric.core.observability import get_logger, scoped_log_context, trace

logger = get_logger(__name__)


# With trace correlation
async def store_memory(self, content: str, embedding: list[float]):
    with scoped_log_context(
        memory_id=memory_id, memory_type=memory_type, source_system=source_system
    ):
        logger.info("storing-memory", content_length=len(content))

        with trace("vector-store.store", component="memory"):
            result = await self.adapter.insert("memories", [doc])

        logger.info("memory-stored", memory_id=memory_id)
```

**Why This Matters:**

- Oneiric uses **structlog** for structured logging
- Trace correlation connects logs across async operations
- Observability systems (Jaeger, Tempo) can trace request flows
- Critical for debugging async memory operations

**Fix Required:**

```python
# Use Oneiric observability
from oneiric.core.observability import get_logger, scoped_log_context, trace

logger = get_logger(__name__)


class MahavishnuVectorStore:
    async def store_memory(self, content: str, embedding: list[float]):
        with scoped_log_context(memory_type="agent", source_system="agno"):
            with trace("memory.store", component="vector_store"):
                logger.info("storing-memory", content_length=len(content))

                doc = VectorDocument(
                    id=str(uuid.uuid4()), vector=embedding, metadata={"content": content}
                )

                await self.adapter.insert("memories", [doc])

                logger.info("memory-stored", doc_id=doc.id)
```

______________________________________________________________________

### 4. **Missing Oneiric Metrics Integration** 🔴

**Problem:** Performance monitoring plan doesn't use Oneiric's observability features.

**Evidence from Plan:**

```python
# Lines 1446-1494: Custom metrics storage
class PerformanceMonitor:
    async def collect_adapter_health(self, adapter_name: str, health_data: dict):
        # Stores in PostgreSQL instead of using Oneiric metrics
        await self.memory.store_performance_metrics(...)
```

**Oneiric Pattern:**

```python
from oneiric.core.observability import configure_observability, get_tracer
from opentelemetry import metrics


class MahavishnuVectorStore:
    def __init__(self, settings):
        # Configure Oneiric observability
        configure_observability(settings.observability)

        # Get OpenTelemetry meter
        self.meter = metrics.get_meter(__name__)

        # Create metrics
        self.memory_store_counter = self.meter.create_counter(
            "memory.stored", description="Number of memories stored"
        )
        self.search_latency = self.meter.create_histogram(
            "search.latency", description="Vector search latency in seconds"
        )

    async def store_memory(self, content: str, embedding: list[float]):
        with self.search_latency.record_time():
            result = await self.adapter.insert("memories", [doc])

        self.memory_store_counter.add(1, {"memory_type": "agent", "source_system": "agno"})
```

**Why This Matters:**

- Metrics automatically exported to OTLP endpoint (if configured)
- Consistent with Oneiric ecosystem
- Works with Prometheus, Grafana, etc.
- No custom PostgreSQL storage needed

______________________________________________________________________

## Major Concerns (Should Fix)

### 5. **Configuration Doesn't Extend Oneiric Base Settings** ⚠️

**Problem:** Plan adds fields to `MahavishnuSettings` without following Oneiric patterns.

**Evidence from Plan:**

```python
# Lines 558-616: Custom PostgreSQLSettings
class PostgreSQLSettings(BaseModel):  # Should extend Oneiric settings
    enabled: bool = Field(default=False)
    host: str = Field(default="localhost")
    # ...
```

**Oneiric Pattern:**

```python
from oneiric.adapters.vector.pgvector import PgvectorSettings
from pydantic import Field


class MahavishnuSettings(MCPServerSettings):
    # ... existing fields ...

    # Vector database configuration (Oneiric-compatible)
    vector_db_enabled: bool = Field(default=True)
    vector_db_host: str = Field(default="localhost")
    vector_db_port: int = Field(default=5432)
    vector_db_user: str = Field(default="postgres")
    vector_db_password: SecretStr | None = Field(default=None)
    vector_db_name: str = Field(default="mahavishnu")
    vector_db_schema: str = Field(default="public")
    vector_db_dimension: int = Field(default=768)  # nomic-embed-text

    def to_pgvector_settings(self) -> PgvectorSettings:
        """Convert Mahavishnu settings to Oneiric PgvectorSettings."""
        return PgvectorSettings(
            host=self.vector_db_host,
            port=self.vector_db_port,
            user=self.vector_db_user,
            password=self.vector_db_password,
            database=self.vector_db_name,
            db_schema=self.vector_db_schema,
            default_dimension=self.vector_db_dimension,
            default_distance_metric="cosine",
            collection_prefix="mahavishnu_",
            ensure_extension=True,
        )
```

**Missing:**

- No `SecretStr` for passwords (security risk)
- No field validators for port ranges
- No environment variable overrides
- No Oneiric layered loading integration

______________________________________________________________________

### 6. **No Use of Oneiric Lifecycle Hooks** ⚠️

**Problem:** Custom implementations don't use Oneiric's lifecycle management.

**Oneiric Lifecycle Pattern:**

```python
from oneiric.core.lifecycle import LifecycleManager, LifecycleError


class MahavishnuVectorStore:
    def __init__(self, settings):
        self.settings = settings
        self.adapter = PgvectorAdapter(settings.to_pgvector_settings())

    async def initialize(self):
        """Initialize with Oneiric lifecycle hooks."""
        try:
            await self.adapter.init()

            # Pre-initialization hook
            await self._validate_schema()

            # Create collections
            await self._create_collections()

            # Post-initialization hook
            await self._warm_cache()

        except Exception as e:
            raise LifecycleError(
                f"Failed to initialize vector store: {e}",
                component="vector_store",
                details={"settings": self.settings.dict()},
            )

    async def health_check(self) -> bool:
        """Health check with circuit breaker awareness."""
        try:
            return await self.adapter.health()
        except Exception as e:
            logger.error("health-check-failed", error=str(e))
            return False

    async def cleanup(self):
        """Cleanup with Oneiric lifecycle hooks."""
        try:
            await self.adapter.cleanup()
        except Exception as e:
            logger.error("cleanup-failed", error=str(e))
```

**Missing from Plan:**

- No `LifecycleError` usage
- No pre/post hooks
- No circuit breaker integration
- No graceful degradation

______________________________________________________________________

### 7. **No Circuit Breaker Integration** ⚠️

**Problem:** Memory operations don't use circuit breakers despite Mahavishnu having them.

**Evidence from Code:**

```python
# mahavishnu/core/app.py lines 116-119
self.circuit_breaker = CircuitBreaker(
    threshold=self.config.circuit_breaker_threshold, timeout=self.config.retry_base_delay * 10
)
```

**But Memory Implementation Ignores This:**

```python
# Plan lines 745-778: No circuit breaker usage
async def store_agent_conversation(self, agent_id: str, role: str, content: str):
    # No circuit breaker protection
    # No retry logic
    # No fallback
    embedding = await self.embed_model.aget_text_embedding(content)
    await self.vector_store.store_memory(...)
```

**Fix Required:**

```python
class MahavishnuMemoryIntegration:
    def __init__(self, config, circuit_breaker):
        self.config = config
        self.circuit_breaker = circuit_breaker

    async def store_agent_conversation(self, agent_id: str, role: str, content: str):
        """Store with circuit breaker protection."""
        # Check circuit breaker
        if self.circuit_breaker.is_open():
            logger.warning("circuit-breaker-open", component="memory")
            # Fallback to local cache
            await self._store_locally(agent_id, role, content)
            return

        try:
            embedding = await self.embed_model.aget_text_embedding(content)
            await self.vector_store.store_memory(...)

            # Reset circuit breaker on success
            self.circuit_breaker.reset()

        except Exception as e:
            # Record failure
            self.circuit_breaker.record_failure()
            logger.error("memory-store-failed", error=str(e))
            raise
```

______________________________________________________________________

## Minor Issues (Nice to Have)

### 8. **No Transaction Context Usage**

Oneiric's pgvector adapter supports transactions:

```python
async with adapter.transaction() as client:
    await adapter.insert("coll1", docs1)
    await adapter.insert("coll2", docs2)
    # Commits on success, rolls back on error
```

Plan doesn't use this for multi-table operations.

______________________________________________________________________

### 9. **No Retry Logic**

Oneiric doesn't have built-in retry, but Mahavishnu has retry configuration:

```python
# config.py lines 109-120
retry_max_attempts: int = Field(default=3)
retry_base_delay: float = Field(default=1.0)
```

Memory implementation should use this for transient failures.

______________________________________________________________________

### 10. **No Use of Oneiric Error Types**

Oneiric has structured error types:

```python
from oneiric.core.errors import LifecycleError, ConfigurationError
```

Plan uses generic exceptions.

______________________________________________________________________

## What's Done Well

✅ **Single PostgreSQL Database** - Good architectural decision
✅ **Single Embedding Model** - Avoids dimension mismatch issues
✅ **Session-Buddy for Insights Only** - Smart separation of concerns
✅ **Async/Await Throughout** - Matches Oneiric patterns
✅ **Pydantic Models** - Type safety is good
✅ **Environment Variable Support** - Correct Oneiric pattern
✅ **Connection Pooling** - Performance consideration present
✅ **Alembic Migrations** - Database version control is smart

______________________________________________________________________

## Specific Recommendations

### Recommendation 1: Use Oneiric pgvector Adapter (Critical)

**Remove from plan:**

- Lines 99-211: `PgVectorStore` custom implementation
- Lines 284-393: `PostgreSQLConnection` custom implementation
- Lines 231-278: Custom schema SQL (use Oneiric's collection management)

**Add to plan:**

```python
# mahavishnu/core/vector_store.py (NEW FILE)
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument
from oneiric.core.observability import get_logger, scoped_log_context, trace
from mahavishnu.core.config import MahavishnuSettings

logger = get_logger(__name__)


class MahavishnuVectorStore:
    """Mahavishnu vector store using Oneiric pgvector adapter."""

    # Collection constants
    COLLECTION_MEMORIES = "memories"
    COLLECTION_WORKFLOWS = "workflows"
    COLLECTION_REPOSITORIES = "repositories"

    def __init__(self, settings: MahavishnuSettings):
        self.settings = settings
        self.pgvector_settings = settings.to_pgvector_settings()
        self.adapter = PgvectorAdapter(self.pgvector_settings)

    async def initialize(self):
        """Initialize vector store with Oneiric lifecycle."""
        with trace("vector-store.initialize", component="memory"):
            await self.adapter.init()

            # Create Mahavishnu-specific collections
            for collection in [
                self.COLLECTION_MEMORIES,
                self.COLLECTION_WORKFLOWS,
                self.COLLECTION_REPOSITORIES,
            ]:
                await self.adapter.create_collection(
                    name=collection,
                    dimension=768,  # nomic-embed-text
                    distance_metric="cosine",
                )

            logger.info(
                "vector-store-initialized",
                collections=[
                    self.COLLECTION_MEMORIES,
                    self.COLLECTION_WORKFLOWS,
                    self.COLLECTION_REPOSITORIES,
                ],
            )

    async def store_memory(
        self,
        content: str,
        embedding: list[float],
        memory_type: str,
        source_system: str,
        metadata: dict,
    ) -> str:
        """Store memory with Oneiric observability."""
        with scoped_log_context(memory_type=memory_type, source_system=source_system):
            with trace("vector-store.store", component="memory"):
                doc = VectorDocument(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    metadata={
                        **metadata,
                        "content": content,
                        "memory_type": memory_type,
                        "source_system": source_system,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

                await self.adapter.insert(self.COLLECTION_MEMORIES, [doc])

                logger.info("memory-stored", doc_id=doc.id, content_length=len(content))
                return doc.id

    async def search_memories(
        self,
        query_embedding: list[float],
        memory_types: list[str] | None = None,
        limit: int = 10,
        threshold: float = 0.7,
    ) -> list[dict]:
        """Search memories with Oneiric observability."""
        with trace("vector-store.search", component="memory"):
            filter_expr = {"memory_type": memory_types} if memory_types else None

            results = await self.adapter.search(
                collection=self.COLLECTION_MEMORIES,
                query_vector=query_embedding,
                limit=limit,
                filter_expr=filter_expr,
            )

            # Apply threshold
            filtered = [
                {
                    "id": r.id,
                    "content": r.metadata.get("content"),
                    "memory_type": r.metadata.get("memory_type"),
                    "source_system": r.metadata.get("source_system"),
                    "similarity": r.score,
                    "metadata": r.metadata,
                }
                for r in results
                if r.score >= threshold
            ]

            logger.info("memory-search-completed", results=len(filtered))
            return filtered

    async def health_check(self) -> bool:
        """Health check matching Oneiric pattern."""
        try:
            return await self.adapter.health()
        except Exception as e:
            logger.error("health-check-failed", error=str(e))
            return False

    async def cleanup(self):
        """Cleanup with Oneiric lifecycle."""
        with trace("vector-store.cleanup", component="memory"):
            await self.adapter.cleanup()
```

______________________________________________________________________

### Recommendation 2: Update MahavishnuSettings (Critical)

**Add to `mahavishnu/core/config.py`:**

```python
from pydantic import Field, SecretStr, field_validator
from oneiric.adapters.vector.pgvector import PgvectorSettings


class MahavishnuSettings(MCPServerSettings):
    # ... existing fields ...

    # Vector database configuration (Oneiric-compatible)
    vector_db_enabled: bool = Field(
        default=True, description="Enable vector database for memory storage"
    )
    vector_db_host: str = Field(
        default="localhost", description="PostgreSQL host for vector database"
    )
    vector_db_port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL port")
    vector_db_user: str = Field(default="postgres", description="PostgreSQL user")
    vector_db_password: SecretStr | None = Field(
        default=None, description="PostgreSQL password (use env var MAHAVISHNU_VECTOR_DB_PASSWORD)"
    )
    vector_db_name: str = Field(default="mahavishnu", description="PostgreSQL database name")
    vector_db_schema: str = Field(default="public", description="PostgreSQL schema")
    vector_db_dimension: int = Field(
        default=768,  # nomic-embed-text
        ge=1,
        description="Embedding vector dimension",
    )
    vector_db_distance_metric: str = Field(
        default="cosine", description="Distance metric (cosine, euclidean, dot_product)"
    )

    @field_validator("vector_db_password")
    @classmethod
    def validate_vector_db_password(cls, v: SecretStr | None) -> SecretStr | None:
        """Validate password is set if vector DB is enabled."""
        # This would need access to config to check if enabled
        # For now, just return it
        return v

    def to_pgvector_settings(self) -> PgvectorSettings:
        """Convert Mahavishnu settings to Oneiric PgvectorSettings."""
        return PgvectorSettings(
            host=self.vector_db_host,
            port=self.vector_db_port,
            user=self.vector_db_user,
            password=self.vector_db_password,
            database=self.vector_db_name,
            db_schema=self.vector_db_schema,
            default_dimension=self.vector_db_dimension,
            default_distance_metric=self.vector_db_distance_metric,
            collection_prefix="mahavishnu_",
            ensure_extension=True,
            ivfflat_lists=100,
            max_connections=10,
        )
```

**Configuration file (`settings/mahavishnu.yaml`):**

```yaml
# ... existing config ...

# Vector database (Oneiric pgvector adapter)
vector_db_enabled: true
vector_db_host: localhost
vector_db_port: 5432
vector_db_user: postgres
vector_db_password: ${MAHAVISHNU_VECTOR_DB_PASSWORD}
vector_db_name: mahavishnu
vector_db_schema: public
vector_db_dimension: 768  # nomic-embed-text
vector_db_distance_metric: cosine
```

______________________________________________________________________

### Recommendation 3: Update Memory Integration (Critical)

**Replace `MahavishnuMemoryIntegration` with Oneiric patterns:**

```python
# mahavishnu/core/memory_integration.py (REWRITE)
from typing import Optional, List, Dict, Any
import uuid
from datetime import datetime
import logging

from oneiric.core.observability import get_logger, scoped_log_context, trace
from oneiric.core.errors import LifecycleError

from .config import MahavishnuSettings
from .vector_store import MahavishnuVectorStore

logger = get_logger(__name__)


class MahavishnuMemoryIntegration:
    """Integrated memory system using Oneiric pgvector + Session-Buddy."""

    def __init__(
        self, config: MahavishnuSettings, circuit_breaker, vector_store: MahavishnuVectorStore
    ):
        self.config = config
        self.circuit_breaker = circuit_breaker
        self.vector_store = vector_store

        # Ollama embeddings
        self.embed_model = None
        if config.memory_service_enabled:
            self._init_embeddings()

        # Session-Buddy integration
        self.session_buddy_project = None
        self.session_buddy_global = None
        self._init_session_buddy()

    def _init_embeddings(self):
        """Initialize Ollama embedding model."""
        try:
            from llama_index.embeddings.ollama import OllamaEmbedding

            self.embed_model = OllamaEmbedding(
                model_name=self.config.llm_model, base_url=self.config.ollama_base_url
            )

            logger.info("embeddings-initialized", model=self.config.llm_model)

        except ImportError as e:
            logger.warning("ollama-not-available", error=str(e))

    def _init_session_buddy(self):
        """Initialize Session-Buddy (for insights only)."""
        try:
            from session_buddy.adapters.reflection_adapter_oneiric import (
                ReflectionDatabaseAdapterOneiric,
            )

            # Project-specific memory
            self.session_buddy_project = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_project"
            )

            # Global/cross-project memory
            self.session_buddy_global = ReflectionDatabaseAdapterOneiric(
                collection_name="mahavishnu_global"
            )

            logger.info("session-buddy-initialized")

        except ImportError as e:
            logger.warning("session-buddy-not-available", error=str(e))

    async def store_agent_conversation(
        self, agent_id: str, role: str, content: str, metadata: Dict[str, Any]
    ) -> None:
        """Store agent conversation with Oneiric observability."""
        with scoped_log_context(agent_id=agent_id, role=role):
            # Check circuit breaker
            if self.circuit_breaker.is_open():
                logger.warning("circuit-breaker-open", component="memory")
                await self._store_locally(content, metadata)
                return

            try:
                with trace("memory.store.conversation", component="memory"):
                    # Generate embedding
                    embedding = await self.embed_model.aget_text_embedding(content)

                    # Store in vector DB
                    memory_id = await self.vector_store.store_memory(
                        content=content,
                        embedding=embedding,
                        memory_type="agent",
                        source_system="agno",
                        metadata={**metadata, "agent_id": agent_id, "role": role},
                    )

                    # Extract insights to Session-Buddy
                    await self._extract_and_store_insights(content, metadata)

                    # Reset circuit breaker on success
                    self.circuit_breaker.reset()

                    logger.info("conversation-stored", memory_id=memory_id)

            except Exception as e:
                self.circuit_breaker.record_failure()
                logger.error("conversation-store-failed", error=str(e))
                raise LifecycleError(
                    f"Failed to store conversation: {e}",
                    component="memory",
                    details={"agent_id": agent_id, "role": role},
                )

    async def search_memories(
        self, query: str, memory_types: Optional[List[str]] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Unified search with Oneiric observability."""
        with trace("memory.search", component="memory"):
            # Generate query embedding
            query_embedding = await self.embed_model.aget_text_embedding(query)

            # Search vector DB
            vector_results = await self.vector_store.search_memories(
                query_embedding=query_embedding, memory_types=memory_types, limit=limit
            )

            # Search Session-Buddy (insights only)
            session_results = []
            if self.session_buddy_project:
                try:
                    session_results = await self.session_buddy_project.semantic_search(
                        query=query, limit=limit // 2
                    )
                except Exception as e:
                    logger.error("session-buddy-search-failed", error=str(e))

            # Combine and rank results
            all_results = [{**r, "source": "vector_db"} for r in vector_results] + [
                {
                    "content": r.get("content"),
                    "metadata": r.get("metadata"),
                    "score": r.get("score", 0.0),
                    "source": "session_buddy",
                }
                for r in session_results
            ]

            all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

            logger.info(
                "memory-search-completed",
                total_results=len(all_results),
                vector_db_results=len(vector_results),
                session_buddy_results=len(session_results),
            )

            return all_results[:limit]

    async def _extract_and_store_insights(self, content: str, metadata: Dict[str, Any]) -> None:
        """Extract insights and store in Session-Buddy."""
        if not self.session_buddy_global:
            return

        # Check for insight delimiter
        if "★ Insight ─────" not in content:
            return

        try:
            with trace("memory.extract-insight", component="memory"):
                await self.session_buddy_global.add_memory(
                    content=content,
                    metadata={
                        **metadata,
                        "source_system": "mahavishnu",
                        "doc_type": "agent_insight",
                        "extracted_at": datetime.now().isoformat(),
                    },
                )

                logger.debug("insight-extracted")

        except Exception as e:
            logger.error("insight-extraction-failed", error=str(e))

    async def _store_locally(self, content: str, metadata: Dict[str, Any]):
        """Fallback storage when circuit breaker is open."""
        logger.warning("storing-locally", content_length=len(content))
        # Store in local cache or file system
        # Implementation depends on requirements

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check."""
        vector_health = await self.vector_store.health_check()

        return {
            "status": "healthy" if vector_health else "degraded",
            "vector_store": vector_health,
            "embeddings": self.embed_model is not None,
            "session_buddy": self.session_buddy_project is not None,
        }

    async def close(self) -> None:
        """Cleanup resources."""
        await self.vector_store.cleanup()
```

______________________________________________________________________

### Recommendation 4: Update MahavishnuApp Initialization

**Add to `mahavishnu/core/app.py`:**

```python
from .vector_store import MahavishnuVectorStore
from .memory_integration import MahavishnuMemoryIntegration


class MahavishnuApp:
    def __init__(self, config: MahavishnuSettings | None = None) -> None:
        self.config = config or self._load_config()
        self.adapters: dict[str, OrchestratorAdapter] = {}
        self._load_repos()

        # Initialize vector store first (needed by memory integration)
        self.vector_store = None
        if self.config.vector_db_enabled:
            self.vector_store = MahavishnuVectorStore(self.config)

        # Initialize memory integration
        self.memory_integration = None
        if self.vector_store:
            self.memory_integration = MahavishnuMemoryIntegration(
                config=self.config,
                circuit_breaker=self.circuit_breaker,
                vector_store=self.vector_store,
            )

        # ... rest of initialization ...

    async def initialize(self):
        """Initialize async components."""
        # Initialize vector store
        if self.vector_store:
            await self.vector_store.initialize()

        # Initialize memory integration
        if self.memory_integration:
            # Embeddings initialized in __init__
            pass

        # Initialize adapters
        self._initialize_adapters()

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check."""
        health = {"status": "healthy", "components": {}}

        # Vector store health
        if self.vector_store:
            health["components"]["vector_store"] = await self.vector_store.health_check()

        # Memory integration health
        if self.memory_integration:
            health["components"][
                "memory_integration"
            ] = await self.memory_integration.health_check()

        # Adapter health
        for name, adapter in self.adapters.items():
            try:
                adapter_health = await adapter.get_health()
                health["components"][name] = adapter_health
            except Exception as e:
                health["components"][name] = {"status": "unhealthy", "error": str(e)}

        # Overall status
        if any(c.get("status") == "unhealthy" for c in health["components"].values()):
            health["status"] = "unhealthy"
        elif any(c.get("status") == "degraded" for c in health["components"].values()):
            health["status"] = "degraded"

        return health

    async def cleanup(self):
        """Cleanup resources."""
        if self.memory_integration:
            await self.memory_integration.close()

        if self.vector_store:
            await self.vector_store.cleanup()
```

______________________________________________________________________

## Overall Assessment

### Score Breakdown

| Category | Score | Notes |
|----------|-------|-------|
| **Architecture** | 8/10 | Good decisions on single DB, single embedding model |
| **Oneiric Integration** | 2/10 | Ignores built-in adapters, custom implementation |
| **Configuration** | 5/10 | Partially correct, missing SecretStr and validators |
| **Observability** | 3/10 | No structured logging, no trace correlation |
| **Error Handling** | 4/10 | Generic exceptions, no LifecycleError usage |
| **Lifecycle Management** | 4/10 | No pre/post hooks, no circuit breaker integration |
| **Health Checks** | 6/10 | Returns bool but doesn't use Oneiric patterns |
| **Metrics** | 2/10 | Custom storage instead of OpenTelemetry |
| **Documentation** | 7/10 | Clear plan but based on wrong assumptions |
| **Test Coverage** | 8/10 | Test file exists for Oneiric adapter |

**Overall Score: 5/10** - Good architecture, poor Oneiric integration

______________________________________________________________________

## Go/No-Go Decision

### ⚠️ **CONDITIONAL GO** - Fix critical issues before implementation

**Required Changes Before Implementation:**

1. ✅ **MUST:** Replace custom PostgreSQL/pgvector with Oneiric adapters
1. ✅ **MUST:** Add structured logging with trace correlation
1. ✅ **MUST:** Use Oneiric observability for metrics
1. ✅ **MUST:** Fix health check type consistency
1. ✅ **SHOULD:** Integrate circuit breakers with memory operations
1. ✅ **SHOULD:** Add Oneiric lifecycle hooks
1. ✅ **SHOULD:** Update configuration to use `SecretStr`

**Implementation Sequence:**

1. **Phase 0 (NEW):** Oneiric Integration Foundation (3-4 days)

   - Update `MahavishnuSettings` with vector_db fields
   - Create `MahavishnuVectorStore` using Oneiric pgvector adapter
   - Add structured logging throughout
   - Update base adapter health check signature

1. **Phase 1 (Revised):** Vector Store Setup (2-3 days)

   - Remove custom schema/migrations (use Oneiric collections)
   - Initialize vector store in `MahavishnuApp`
   - Add health checks with Oneiric patterns
   - Add circuit breaker integration

1. **Phase 2 (Revised):** Memory Integration (4-5 days)

   - Implement `MahavishnuMemoryIntegration` with Oneiric observability
   - Add Session-Buddy integration for insights
   - Add retry logic and circuit breaker protection
   - Add comprehensive logging

1. **Phase 3-5:** Continue as planned with Oneiric patterns

**Revised Timeline:** 4-5 weeks (same as original plan, but better architecture)

______________________________________________________________________

## Conclusion

The memory implementation plan V2 has **solid architectural decisions** but **critical Oneiric integration failures**. The plan proposes building custom adapters that Oneiric already provides, wasting development time and creating maintenance burden.

**Key Takeaway:** Use Oneiric's production-ready adapters. Focus on business logic, not infrastructure.

**Next Steps:**

1. Address all "Critical Issues" in this review
1. Update MEMORY_IMPLEMENTATION_PLAN_V2.md with corrected code
1. Run existing integration test (`test_oneiric_pgvector_adapter.py`)
1. Create new implementation tasks based on recommendations
1. Begin implementation with Oneiric-first approach

______________________________________________________________________

**Reviewer Signature:** Oneiric Integration Specialist
**Date:** 2025-01-24
**Status:** Awaiting Critical Fixes
**Next Review:** After plan updates
