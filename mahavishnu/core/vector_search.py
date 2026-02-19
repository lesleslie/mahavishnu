"""Vector Search Module for Mahavishnu.

Provides vector similarity search using PostgreSQL + pgvector:
- HNSW indexing for fast approximate nearest neighbor search
- Hybrid search combining vector similarity + full-text search
- Embedding storage and retrieval
- Task similarity search
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict

from mahavishnu.core.database import Database
from mahavishnu.core.embeddings import EmbeddingService, cosine_similarity
from mahavishnu.core.errors import MahavishnuError, ErrorCode

logger = logging.getLogger(__name__)


class SearchType(Enum):
    """Types of search available."""

    VECTOR = "vector"
    FTS = "fts"  # Full-text search
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    """Result from vector search."""

    task_id: str
    title: str
    repository: str
    similarity: float
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    highlights: list[str] = field(default_factory=list)


class SearchQuery(BaseModel):
    """Search query parameters."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Search query text")
    repository: str | None = Field(default=None, description="Filter by repository")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results")
    threshold: float = Field(default=0.7, ge=0.0, le=1.0, description="Minimum similarity")
    search_type: SearchType = Field(default=SearchType.HYBRID, description="Search type")
    include_content: bool = Field(default=False, description="Include full content")


class VectorSearchError(MahavishnuError):
    """Error during vector search."""

    def __init__(self, message: str, query: str | None = None, details: dict | None = None):
        super().__init__(message, ErrorCode.EMBEDDING_SERVICE_ERROR, details=details)
        self.query = query


class VectorIndex:
    """Manages pgvector index operations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_hnsw_index(
        self,
        table: str = "task_embeddings",
        column: str = "embedding",
        m: int = 16,
        ef_construction: int = 64,
    ) -> None:
        """Create HNSW index for fast approximate nearest neighbor search.

        Args:
            table: Table name containing embeddings
            column: Column name for vector data
            m: Number of bi-directional links (default 16)
            ef_construction: Size of dynamic candidate list (default 64)
        """
        index_name = f"{table}_{column}_hnsw_idx"

        await self.db.execute(f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {table}
            USING hnsw ({column} vector_cosine_ops)
            WITH (m = {m}, ef_construction = {ef_construction});
        """)

        logger.info(f"Created HNSW index {index_name} on {table}.{column}")

    async def create_ivfflat_index(
        self,
        table: str = "task_embeddings",
        column: str = "embedding",
        lists: int = 100,
    ) -> None:
        """Create IVFFlat index for exact nearest neighbor search.

        Args:
            table: Table name containing embeddings
            column: Column name for vector data
            lists: Number of clusters (default 100, should be rows/1000)
        """
        index_name = f"{table}_{column}_ivf_idx"

        await self.db.execute(f"""
            CREATE INDEX IF NOT EXISTS {index_name}
            ON {table}
            USING ivfflat ({column} vector_cosine_ops)
            WITH (lists = {lists});
        """)

        logger.info(f"Created IVFFlat index {index_name} on {table}.{column}")

    async def drop_index(self, table: str, column: str, index_type: str = "hnsw") -> None:
        """Drop an existing vector index."""
        index_name = f"{table}_{column}_{index_type}_idx"
        await self.db.execute(f"DROP INDEX IF EXISTS {index_name};")
        logger.info(f"Dropped index {index_name}")


class VectorStore:
    """Vector storage for task embeddings."""

    def __init__(self, db: Database, embedding_service: EmbeddingService | None = None) -> None:
        self.db = db
        self.embedding_service = embedding_service
        self.index = VectorIndex(db)

    async def store_embedding(
        self,
        task_id: str,
        text: str,
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an embedding for a task.

        Args:
            task_id: Task ID
            text: Text that was embedded
            embedding: Pre-computed embedding (or generate if None)
            metadata: Additional metadata

        Returns:
            Embedding ID
        """
        # Generate embedding if not provided
        if embedding is None:
            if not self.embedding_service:
                raise VectorSearchError(
                    "No embedding service configured",
                    query=text,
                )
            result = await self.embedding_service.embed(text)
            embedding = result.embeddings[0]

        # Upsert embedding
        row = await self.db.fetchrow(
            """
            INSERT INTO task_embeddings (task_id, content, embedding, metadata, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (task_id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            task_id,
            text,
            embedding,
            metadata or {},
        )

        return row["id"]

    async def get_embedding(self, task_id: str) -> list[float] | None:
        """Get embedding for a task."""
        row = await self.db.fetchrow(
            "SELECT embedding FROM task_embeddings WHERE task_id = $1",
            task_id,
        )
        if row:
            return list(row["embedding"])
        return None

    async def delete_embedding(self, task_id: str) -> bool:
        """Delete embedding for a task."""
        result = await self.db.execute(
            "DELETE FROM task_embeddings WHERE task_id = $1",
            task_id,
        )
        return result.split()[-1] != "0"

    async def batch_store(
        self,
        items: list[dict[str, Any]],
        batch_size: int = 100,
    ) -> int:
        """Store multiple embeddings in batch.

        Args:
            items: List of dicts with task_id, text, embedding (optional), metadata (optional)
            batch_size: Number of items per batch

        Returns:
            Number of embeddings stored
        """
        if not items:
            return 0

        stored = 0

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]

            # Generate embeddings for items without them
            if self.embedding_service:
                texts_to_embed = [
                    (j, item["text"])
                    for j, item in enumerate(batch)
                    if "embedding" not in item or item["embedding"] is None
                ]

                if texts_to_embed:
                    indices, texts = zip(*texts_to_embed)
                    result = await self.embedding_service.embed(list(texts))
                    for idx, embedding in zip(indices, result.embeddings):
                        batch[idx]["embedding"] = embedding

            # Insert batch
            for item in batch:
                await self.store_embedding(
                    task_id=item["task_id"],
                    text=item["text"],
                    embedding=item.get("embedding"),
                    metadata=item.get("metadata"),
                )
                stored += 1

        return stored


class VectorSearch:
    """Vector similarity search with hybrid support."""

    def __init__(
        self,
        db: Database,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.db = db
        self.embedding_service = embedding_service
        self.store = VectorStore(db, embedding_service)

    async def search(
        self,
        query: SearchQuery,
    ) -> list[SearchResult]:
        """Execute search based on query parameters.

        Args:
            query: Search query parameters

        Returns:
            List of search results
        """
        if query.search_type == SearchType.VECTOR:
            return await self._vector_search(query)
        elif query.search_type == SearchType.FTS:
            return await self._fts_search(query)
        else:
            return await self._hybrid_search(query)

    async def _vector_search(self, query: SearchQuery) -> list[SearchResult]:
        """Pure vector similarity search."""
        if not self.embedding_service:
            raise VectorSearchError(
                "Embedding service required for vector search",
                query=query.query,
            )

        # Generate query embedding
        embedding_result = await self.embedding_service.embed([query.query])
        query_embedding = embedding_result.embeddings[0]

        # Build SQL
        sql = """
            SELECT
                e.task_id,
                t.title,
                t.repository,
                1 - (e.embedding <=> $1::vector) as similarity,
                e.content,
                e.metadata
            FROM task_embeddings e
            JOIN tasks t ON t.id = e.task_id
            WHERE 1 - (e.embedding <=> $1::vector) >= $2
        """
        params: list[Any] = [query_embedding, query.threshold]
        param_idx = 3

        if query.repository:
            sql += f" AND t.repository = ${param_idx}"
            params.append(query.repository)
            param_idx += 1

        sql += f" ORDER BY similarity DESC LIMIT ${param_idx}"
        params.append(query.limit)

        rows = await self.db.fetch(sql, *params)

        return [
            SearchResult(
                task_id=row["task_id"],
                title=row["title"],
                repository=row["repository"],
                similarity=float(row["similarity"]),
                content=row["content"] if query.include_content else None,
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]

    async def _fts_search(self, query: SearchQuery) -> list[SearchResult]:
        """Full-text search using PostgreSQL tsvector."""
        # Build SQL
        sql = """
            SELECT
                e.task_id,
                t.title,
                t.repository,
                ts_rank(e.search_vector, plainto_tsquery('english', $1)) as similarity,
                e.content,
                e.metadata,
                ts_headline(
                    'english',
                    e.content,
                    plainto_tsquery('english', $1),
                    'MaxWords=50, MinWords=10'
                ) as highlight
            FROM task_embeddings e
            JOIN tasks t ON t.id = e.task_id
            WHERE e.search_vector @@ plainto_tsquery('english', $1)
        """
        params: list[Any] = [query.query]
        param_idx = 2

        if query.repository:
            sql += f" AND t.repository = ${param_idx}"
            params.append(query.repository)
            param_idx += 1

        sql += f" ORDER BY similarity DESC LIMIT ${param_idx}"
        params.append(query.limit)

        rows = await self.db.fetch(sql, *params)

        return [
            SearchResult(
                task_id=row["task_id"],
                title=row["title"],
                repository=row["repository"],
                similarity=float(row["similarity"]),
                content=row["content"] if query.include_content else None,
                metadata=row["metadata"] or {},
                highlights=[row["highlight"]] if row["highlight"] else [],
            )
            for row in rows
        ]

    async def _hybrid_search(self, query: SearchQuery) -> list[SearchResult]:
        """Hybrid search combining vector + FTS with reciprocal rank fusion."""
        if not self.embedding_service:
            # Fallback to FTS only
            return await self._fts_search(query)

        # Generate query embedding
        embedding_result = await self.embedding_service.embed([query.query])
        query_embedding = embedding_result.embeddings[0]

        # Hybrid search using weighted combination
        sql = """
            WITH vector_results AS (
                SELECT
                    e.task_id,
                    t.title,
                    t.repository,
                    1 - (e.embedding <=> $1::vector) as vector_score,
                    e.content,
                    e.metadata
                FROM task_embeddings e
                JOIN tasks t ON t.id = e.task_id
                WHERE 1 - (e.embedding <=> $1::vector) >= $2
            ),
            fts_results AS (
                SELECT
                    e.task_id,
                    t.title,
                    t.repository,
                    ts_rank(e.search_vector, plainto_tsquery('english', $3)) as fts_score,
                    e.content,
                    e.metadata
                FROM task_embeddings e
                JOIN tasks t ON t.id = e.task_id
                WHERE e.search_vector @@ plainto_tsquery('english', $3)
            ),
            combined AS (
                SELECT
                    COALESCE(v.task_id, f.task_id) as task_id,
                    COALESCE(v.title, f.title) as title,
                    COALESCE(v.repository, f.repository) as repository,
                    COALESCE(v.vector_score, 0) * 0.7 + COALESCE(f.fts_score, 0) * 0.3 as hybrid_score,
                    COALESCE(v.content, f.content) as content,
                    COALESCE(v.metadata, f.metadata) as metadata
                FROM vector_results v
                FULL OUTER JOIN fts_results f ON v.task_id = f.task_id
            )
            SELECT * FROM combined
        """
        params: list[Any] = [query_embedding, query.threshold, query.query]
        param_idx = 4

        if query.repository:
            sql += f" WHERE repository = ${param_idx}"
            params.append(query.repository)
            param_idx += 1

        sql += f" ORDER BY hybrid_score DESC LIMIT ${param_idx}"
        params.append(query.limit)

        rows = await self.db.fetch(sql, *params)

        return [
            SearchResult(
                task_id=row["task_id"],
                title=row["title"],
                repository=row["repository"],
                similarity=float(row["hybrid_score"]),
                content=row["content"] if query.include_content else None,
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]

    async def find_similar(
        self,
        task_id: str,
        limit: int = 10,
        threshold: float = 0.7,
        repository: str | None = None,
    ) -> list[SearchResult]:
        """Find tasks similar to a given task.

        Args:
            task_id: Task to find similar items for
            limit: Maximum results
            threshold: Minimum similarity
            repository: Optional repository filter

        Returns:
            List of similar tasks
        """
        # Get embedding for the task
        embedding = await self.store.get_embedding(task_id)
        if not embedding:
            return []

        # Search for similar embeddings
        sql = """
            SELECT
                e.task_id,
                t.title,
                t.repository,
                1 - (e.embedding <=> $1::vector) as similarity,
                e.content,
                e.metadata
            FROM task_embeddings e
            JOIN tasks t ON t.id = e.task_id
            WHERE e.task_id != $2
            AND 1 - (e.embedding <=> $1::vector) >= $3
        """
        params: list[Any] = [embedding, task_id, threshold]
        param_idx = 4

        if repository:
            sql += f" AND t.repository = ${param_idx}"
            params.append(repository)
            param_idx += 1

        sql += f" ORDER BY similarity DESC LIMIT ${param_idx}"
        params.append(limit)

        rows = await self.db.fetch(sql, *params)

        return [
            SearchResult(
                task_id=row["task_id"],
                title=row["title"],
                repository=row["repository"],
                similarity=float(row["similarity"]),
                metadata=row["metadata"] or {},
            )
            for row in rows
        ]


class TaskSimilarity:
    """Task similarity utilities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def compute_similarity_matrix(
        self,
        task_ids: list[str],
    ) -> dict[tuple[str, str], float]:
        """Compute similarity matrix for a set of tasks.

        Args:
            task_ids: List of task IDs

        Returns:
            Dict mapping (task_id1, task_id2) to similarity score
        """
        if len(task_ids) < 2:
            return {}

        # Fetch all embeddings
        rows = await self.db.fetch(
            "SELECT task_id, embedding FROM task_embeddings WHERE task_id = ANY($1)",
            task_ids,
        )

        embeddings = {row["task_id"]: list(row["embedding"]) for row in rows}

        # Compute pairwise similarities
        matrix: dict[tuple[str, str], float] = {}
        for i, id1 in enumerate(task_ids):
            if id1 not in embeddings:
                continue
            for id2 in task_ids[i + 1 :]:
                if id2 not in embeddings:
                    continue
                sim = cosine_similarity(embeddings[id1], embeddings[id2])
                matrix[(id1, id2)] = sim
                matrix[(id2, id1)] = sim

        return matrix

    async def find_duplicates(
        self,
        threshold: float = 0.95,
        repository: str | None = None,
    ) -> list[tuple[str, str, float]]:
        """Find potential duplicate tasks.

        Args:
            threshold: Similarity threshold for duplicates
            repository: Optional repository filter

        Returns:
            List of (task_id1, task_id2, similarity) tuples
        """
        sql = """
            SELECT
                e1.task_id as task_id1,
                e2.task_id as task_id2,
                1 - (e1.embedding <=> e2.embedding) as similarity
            FROM task_embeddings e1
            JOIN task_embeddings e2 ON e1.task_id < e2.task_id
            JOIN tasks t1 ON t1.id = e1.task_id
            JOIN tasks t2 ON t2.id = e2.task_id
            WHERE 1 - (e1.embedding <=> e2.embedding) >= $1
        """
        params: list[Any] = [threshold]

        if repository:
            sql += " AND t1.repository = $2 AND t2.repository = $2"
            params.append(repository)

        sql += " ORDER BY similarity DESC"

        rows = await self.db.fetch(sql, *params)

        return [(row["task_id1"], row["task_id2"], float(row["similarity"])) for row in rows]
