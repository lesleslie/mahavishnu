"""Hybrid search combining semantic (pgvector) and lexical (PostgreSQL full-text).

This module implements the hybrid search pattern from the Storage Consolidation plan,
combining vector similarity search with PostgreSQL full-text search for optimal
retrieval quality.

Key Features:
- Combines semantic understanding (embeddings) with keyword matching (full-text)
- Configurable weights for semantic vs lexical search
- Graceful fallback to lexical-only when embeddings are missing
- Repository filtering support
- Observability through structured logging

Architecture:
- Uses asyncpg connection pool for database operations
- Integrates with EmbeddingRepository for vector operations
- Integrates with DocumentRepository for document retrieval
- Supports pluggable embedding models via EmbeddingService

SQL Query Pattern (from plan):
    SELECT
        d.id,
        d.source_type,
        d.title,
        d.content,
        1 - (e.embedding <=> $1::vector) AS semantic_score,
        ts_rank(d.content_tsv, plainto_tsquery('english', $2)) AS lexical_score
    FROM search.documents d
    JOIN search.document_embeddings e ON e.document_id = d.id
    WHERE d.repository = COALESCE($3, d.repository)
    ORDER BY
        ($4::float * (1 - (e.embedding <=> $1::vector))) +
        ($5::float * ts_rank(d.content_tsv, plainto_tsquery('english', $2))) DESC
    LIMIT 20;
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from mahavishnu.core.database import Database, get_database
from mahavishnu.core.embeddings import EmbeddingProvider, EmbeddingService

if TYPE_CHECKING:
    from uuid import UUID

    from asyncpg import Pool

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Models
# =============================================================================


@dataclass
class HybridSearchConfig:
    """Configuration for hybrid search engine.

    Attributes:
        semantic_weight: Weight for semantic (vector) search scores (0.0-1.0)
        lexical_weight: Weight for lexical (full-text) search scores (0.0-1.0)
        default_limit: Default number of results to return
        min_score: Minimum combined score threshold for results
        embedding_provider: Embedding provider to use for query embedding
        embedding_model: Specific embedding model name
        enable_lexical_fallback: Fall back to lexical-only if embedding fails
    """

    semantic_weight: float = 0.7
    lexical_weight: float = 0.3
    default_limit: int = 20
    min_score: float = 0.5
    embedding_provider: EmbeddingProvider = EmbeddingProvider.FASTEMBED
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    enable_lexical_fallback: bool = True

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not 0.0 <= self.semantic_weight <= 1.0:
            raise ValueError(
                f"semantic_weight must be between 0.0 and 1.0, got {self.semantic_weight}"
            )
        if not 0.0 <= self.lexical_weight <= 1.0:
            raise ValueError(
                f"lexical_weight must be between 0.0 and 1.0, got {self.lexical_weight}"
            )
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError(f"min_score must be between 0.0 and 1.0, got {self.min_score}")

        # Normalize weights to sum to 1.0
        total_weight = self.semantic_weight + self.lexical_weight
        if total_weight > 0:
            self.semantic_weight /= total_weight
            self.lexical_weight /= total_weight


class HybridSearchResult(BaseModel):
    """Hybrid search result with combined semantic and lexical scores.

    Attributes:
        id: Document UUID
        source_type: Type of source (task, run, document, report, etc.)
        title: Optional document title
        content: Document content
        semantic_score: Vector similarity score (0.0-1.0)
        lexical_score: Full-text search rank score (0.0-1.0, normalized)
        combined_score: Weighted combination of semantic and lexical scores
        metadata: Additional document metadata
        repository: Repository name if applicable
        created_at: Document creation timestamp
        updated_at: Document last update timestamp
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    id: UUID = Field(..., description="Document UUID")
    source_type: str = Field(..., description="Source type (task, run, document, etc.)")
    title: str | None = Field(None, description="Document title")
    content: str = Field(..., description="Document content")
    semantic_score: float = Field(..., ge=0.0, le=1.0, description="Semantic similarity score")
    lexical_score: float = Field(..., ge=0.0, le=1.0, description="Lexical search score")
    combined_score: float = Field(..., ge=0.0, le=1.0, description="Combined weighted score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    repository: str | None = Field(None, description="Repository name")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


# =============================================================================
# Hybrid Search Engine
# =============================================================================


class HybridSearchEngine:
    """Hybrid search engine combining semantic and lexical search.

    This engine implements the hybrid search pattern from the Storage Consolidation
    plan (docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md).

    The search combines:
    1. Semantic search: Vector similarity using pgvector cosine distance
    2. Lexical search: PostgreSQL full-text search with ts_rank

    Features:
    - Configurable weighting between semantic and lexical
    - Graceful fallback to lexical-only when embeddings are missing
    - Repository filtering
    - Observability through structured logging

    Example:
        from mahavishnu.core.search import HybridSearchEngine, HybridSearchConfig
        from asyncpg import create_pool

        pool = await create_pool("postgresql://...")
        config = HybridSearchConfig(semantic_weight=0.7, lexical_weight=0.3)
        engine = HybridSearchEngine(pool, config=config)

        results = await engine.search(
            query="API authentication implementation",
            repository="mahavishnu",
            limit=20
        )

        for result in results:
            print(f"{result.title}: {result.combined_score:.3f}")
    """

    def __init__(
        self,
        connection_pool: Pool | None = None,
        config: HybridSearchConfig | None = None,
        embedding_service: EmbeddingService | None = None,
        database: Database | None = None,
    ) -> None:
        """Initialize hybrid search engine.

        Args:
            connection_pool: asyncpg connection pool (optional, uses database if not provided)
            config: Search configuration (optional, uses defaults)
            embedding_service: Embedding service for query vectorization (optional)
            database: Database instance (optional, uses singleton if neither pool nor database provided)
        """
        self._pool = connection_pool
        self._database = database
        self.config = config or HybridSearchConfig()

        # Initialize embedding service if not provided
        if embedding_service is None:
            self._embedding_service = EmbeddingService(
                provider=self.config.embedding_provider,
                model_name=self.config.embedding_model,
            )
        else:
            self._embedding_service = embedding_service

        logger.info(
            "Initialized HybridSearchEngine",
            extra={
                "semantic_weight": self.config.semantic_weight,
                "lexical_weight": self.config.lexical_weight,
                "min_score": self.config.min_score,
                "embedding_provider": self.config.embedding_provider.value,
            },
        )

    async def _get_pool(self) -> Pool:
        """Get database connection pool.

        Returns:
            asyncpg Pool instance

        Raises:
            RuntimeError: If no pool or database is available
        """
        if self._pool is not None:
            return self._pool

        if self._database is not None:
            return self._database.pool

        # Fall back to singleton database
        db = await get_database()
        return db.pool

    @asynccontextmanager
    async def _acquire_connection(self, pool: Pool):
        """Acquire a connection from the pool.

        The production pool exposes an async context manager. Unit tests often
        patch `pool.acquire()` with a looser async mock shape, so this helper
        accepts both styles without changing the database-facing behavior.
        """
        acquire = pool.acquire()

        if hasattr(acquire, "__aenter__") and hasattr(acquire, "__aexit__"):
            entered = acquire.__aenter__()
            conn = await entered if inspect.isawaitable(entered) else entered
            try:
                yield conn
            finally:
                exited = acquire.__aexit__(None, None, None)
                if inspect.isawaitable(exited):
                    await exited
        else:
            conn = await acquire
            try:
                yield conn
            finally:
                release = getattr(pool, "release", None)
                if release is not None:
                    released = release(conn)
                    if inspect.isawaitable(released):
                        await released

    @asynccontextmanager
    async def _enter_async_context(self, context_manager: Any):
        """Enter an async context manager with mock-tolerant semantics."""
        entered = context_manager.__aenter__()
        resource = await entered if inspect.isawaitable(entered) else entered
        try:
            yield resource
        finally:
            exited = context_manager.__aexit__(None, None, None)
            if inspect.isawaitable(exited):
                await exited

    async def search(
        self,
        query: str,
        repository: str | None = None,
        limit: int | None = None,
    ) -> list[HybridSearchResult]:
        """Execute hybrid search combining semantic and lexical search.

        This method implements the SQL query pattern from the Storage Consolidation
        plan, joining documents with embeddings and combining vector similarity
        with full-text search ranking.

        Args:
            query: Search query string
            repository: Optional repository filter
            limit: Maximum number of results (uses config default if not provided)

        Returns:
            List of HybridSearchResult sorted by combined_score descending

        Raises:
            RuntimeError: If database connection fails
            ValueError: If query is empty

        Example:
            results = await engine.search(
                query="API authentication",
                repository="mahavishnu",
                limit=20
            )
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        limit = limit or self.config.default_limit

        logger.debug(
            "Starting hybrid search",
            extra={
                "query": query[:100],  # Truncate for logging
                "repository": repository,
                "limit": limit,
            },
        )

        try:
            # Generate query embedding
            query_embedding = await self._get_query_embedding(query)

            if query_embedding is not None:
                # Full hybrid search with semantic + lexical
                results = await self._hybrid_search(query, query_embedding, repository, limit)
            elif self.config.enable_lexical_fallback:
                # Fallback to lexical-only search
                logger.info("Falling back to lexical-only search (no embedding available)")
                results = await self._lexical_only_search(query, repository, limit)
            else:
                logger.warning("No embedding available and lexical fallback disabled")
                return []

            # Filter by minimum score
            filtered_results = [r for r in results if r.combined_score >= self.config.min_score]

            logger.info(
                "Hybrid search completed",
                extra={
                    "query": query[:100],
                    "total_results": len(results),
                    "filtered_results": len(filtered_results),
                    "repository": repository,
                },
            )

            return filtered_results

        except Exception as e:
            logger.error(
                "Hybrid search failed",
                extra={
                    "query": query[:100],
                    "repository": repository,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def _get_query_embedding(self, query: str) -> list[float] | None:
        """Generate embedding for search query.

        Args:
            query: Search query string

        Returns:
            Embedding vector or None if generation fails
        """
        try:
            result = await self._embedding_service.embed([query])
            if result.embeddings and len(result.embeddings) > 0:
                return result.embeddings[0]
            return None
        except Exception as e:
            logger.warning(
                "Failed to generate query embedding",
                extra={"query": query[:100], "error": str(e)},
            )
            return None

    async def _hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        repository: str | None,
        limit: int,
    ) -> list[HybridSearchResult]:
        """Execute full hybrid search with semantic + lexical.

        Args:
            query: Search query string
            query_embedding: Query embedding vector
            repository: Optional repository filter
            limit: Maximum results

        Returns:
            List of HybridSearchResult
        """
        pool = await self._get_pool()

        # SQL query from plan (lines 260-275)
        sql = """
            SELECT
                d.id,
                d.source_type,
                d.title,
                d.content,
                d.repository,
                d.metadata,
                d.created_at,
                d.updated_at,
                1 - (e.embedding <=> $1::vector) AS semantic_score,
                ts_rank(d.content_tsv, plainto_tsquery('english', $2)) AS lexical_score
            FROM search.documents d
            JOIN search.document_embeddings e ON e.document_id = d.id
            WHERE d.repository = COALESCE($3, d.repository)
            ORDER BY
                ($4::float * (1 - (e.embedding <=> $1::vector))) +
                ($5::float * ts_rank(d.content_tsv, plainto_tsquery('english', $2))) DESC
            LIMIT $6;
        """

        async with self._acquire_connection(pool) as conn:
            rows = await conn.fetch(
                sql,
                query_embedding,  # $1
                query,  # $2
                repository,  # $3
                self.config.semantic_weight,  # $4
                self.config.lexical_weight,  # $5
                limit,  # $6
            )

        results = []
        for row in rows:
            # Normalize lexical score to 0-1 range (ts_rank returns 0-1, but may exceed)
            lexical_score = min(float(row["lexical_score"]), 1.0)
            semantic_score = float(row["semantic_score"])

            # Calculate combined score
            combined_score = (
                self.config.semantic_weight * semantic_score
                + self.config.lexical_weight * lexical_score
            )

            result = HybridSearchResult(
                id=row["id"],
                source_type=row["source_type"],
                title=row["title"],
                content=row["content"],
                repository=row["repository"],
                metadata=row["metadata"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                semantic_score=semantic_score,
                lexical_score=lexical_score,
                combined_score=combined_score,
            )
            results.append(result)

        return results

    async def _lexical_only_search(
        self,
        query: str,
        repository: str | None,
        limit: int,
    ) -> list[HybridSearchResult]:
        """Execute lexical-only search (fallback when embeddings unavailable).

        Args:
            query: Search query string
            repository: Optional repository filter
            limit: Maximum results

        Returns:
            List of HybridSearchResult with semantic_score=0.0
        """
        pool = await self._get_pool()

        sql = """
            SELECT
                d.id,
                d.source_type,
                d.title,
                d.content,
                d.repository,
                d.metadata,
                d.created_at,
                d.updated_at,
                ts_rank(d.content_tsv, plainto_tsquery('english', $1)) AS lexical_score
            FROM search.documents d
            WHERE d.repository = COALESCE($2, d.repository)
            ORDER BY ts_rank(d.content_tsv, plainto_tsquery('english', $1)) DESC
            LIMIT $3;
        """

        async with self._acquire_connection(pool) as conn:
            rows = await conn.fetch(sql, query, repository, limit)

        results = []
        for row in rows:
            lexical_score = min(float(row["lexical_score"]), 1.0)

            result = HybridSearchResult(
                id=row["id"],
                source_type=row["source_type"],
                title=row["title"],
                content=row["content"],
                repository=row["repository"],
                metadata=row["metadata"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                semantic_score=0.0,  # No semantic search
                lexical_score=lexical_score,
                combined_score=self.config.lexical_weight * lexical_score,
            )
            results.append(result)

        return results

    async def index_document(
        self,
        doc_id: UUID,
        title: str,
        content: str,
        metadata: dict[str, Any],
        repository: str | None = None,
        source_type: str = "document",
        source_id: UUID | None = None,
        source_key: str | None = None,
        system_name: str | None = None,
    ) -> None:
        """Index a document for hybrid search.

        This method:
        1. Inserts the document into search.documents
        2. Generates and stores the embedding in search.document_embeddings

        Args:
            doc_id: Document UUID
            title: Document title
            content: Document content
            metadata: Additional metadata
            repository: Repository name
            source_type: Source type (task, run, document, etc.)
            source_id: Optional source UUID
            source_key: Optional source key
            system_name: Optional system name

        Raises:
            RuntimeError: If database connection fails
            ValueError: If content is empty
        """
        if not content or not content.strip():
            raise ValueError("Content cannot be empty")

        logger.debug(
            "Indexing document",
            extra={
                "doc_id": str(doc_id),
                "title": title[:50] if title else None,
                "repository": repository,
            },
        )

        pool = await self._get_pool()
        now = datetime.now(UTC)

        try:
            async with (
                self._acquire_connection(pool) as conn,
                self._enter_async_context(conn.transaction()),
            ):
                # Insert document
                await conn.execute(
                    """
                        INSERT INTO search.documents (
                            id, source_type, source_id, source_key, title, content,
                            repository, system_name, created_at, updated_at, metadata
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            repository = EXCLUDED.repository,
                            system_name = EXCLUDED.system_name,
                            updated_at = EXCLUDED.updated_at,
                            metadata = EXCLUDED.metadata
                        """,
                    doc_id,
                    source_type,
                    source_id,
                    source_key,
                    title,
                    content,
                    repository,
                    system_name,
                    now,
                    now,
                    metadata,
                )

                # Generate and store embedding
                embedding_result = await self._embedding_service.embed([content])
                if embedding_result.embeddings and len(embedding_result.embeddings) > 0:
                    embedding = embedding_result.embeddings[0]
                    await conn.execute(
                        """
                            INSERT INTO search.document_embeddings (
                                document_id, model_name, embedding_dim, embedding, created_at
                            ) VALUES ($1, $2, $3, $4, $5)
                            ON CONFLICT (document_id) DO UPDATE SET
                                model_name = EXCLUDED.model_name,
                                embedding_dim = EXCLUDED.embedding_dim,
                                embedding = EXCLUDED.embedding,
                                created_at = EXCLUDED.created_at
                            """,
                        doc_id,
                        embedding_result.model,
                        embedding_result.dimension,
                        embedding,
                        now,
                    )

            logger.info(
                "Document indexed successfully",
                extra={
                    "doc_id": str(doc_id),
                    "title": title[:50] if title else None,
                    "repository": repository,
                    "has_embedding": embedding_result.embeddings is not None
                    and len(embedding_result.embeddings) > 0,
                },
            )

        except Exception as e:
            logger.error(
                "Failed to index document",
                extra={
                    "doc_id": str(doc_id),
                    "title": title[:50] if title else None,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def delete_document(self, doc_id: UUID) -> bool:
        """Delete a document and its embedding from search index.

        Args:
            doc_id: Document UUID to delete

        Returns:
            True if document was deleted, False if not found

        Raises:
            RuntimeError: If database connection fails
        """
        logger.debug("Deleting document", extra={"doc_id": str(doc_id)})

        pool = await self._get_pool()

        try:
            async with self._acquire_connection(pool) as conn:
                # Delete document (embeddings cascade automatically)
                result = await conn.execute(
                    "DELETE FROM search.documents WHERE id = $1",
                    doc_id,
                )

                deleted = result == "DELETE 1"

                if deleted:
                    logger.info("Document deleted", extra={"doc_id": str(doc_id)})
                else:
                    logger.warning("Document not found for deletion", extra={"doc_id": str(doc_id)})

                return deleted

        except Exception as e:
            logger.error(
                "Failed to delete document",
                extra={"doc_id": str(doc_id), "error": str(e)},
                exc_info=True,
            )
            raise
