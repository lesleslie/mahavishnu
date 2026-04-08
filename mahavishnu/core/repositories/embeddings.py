"""Embedding repository for search.document_embeddings table operations.

This module provides the repository layer for embedding persistence:
- store_embedding(): Store an embedding vector
- get_embedding(): Retrieve an embedding by document ID
- search_similar(): Semantic search for similar documents
- delete_embedding(): Delete an embedding

Schema: search.document_embeddings
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Embedding Repository
# =============================================================================


class EmbeddingCreate(BaseModel):
    """Embedding creation request model.

    Args:
        document_id: Document ID this embedding belongs to
        model_name: Embedding model name (e.g., 'all-MiniLM-L6-v2')
        embedding_dim: Embedding dimension (e.g., 384)
        embedding: Embedding vector as list of floats
        metadata: Additional metadata
    """

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(
        default=384,
        ge=128,
        le=1024,
        description="Embedding dimension",
    )
    embedding: list[float] = Field(
        ...,
        min_length=128,
        max_length=1024,
        description="Embedding vector",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EmbeddingRead(BaseModel):
    """Embedding read response model.

    Args:
        document_id: Document ID
        model_name: Embedding model name
        embedding_dim: Embedding dimension
        embedding: Embedding vector
        created_at: Creation timestamp
        metadata: Additional metadata
    """

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(..., description="Embedding dimension")
    embedding: list[float] = Field(
        ...,
        description="Embedding vector",
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EmbeddingSearchResult(BaseModel):
    """Embedding search result with similarity score.

    Args:
        document_id: Document ID of the match
        model_name: Embedding model name
        embedding_dim: Embedding dimension
        score: Cosine similarity score (0.0-1.0)
        metadata: Additional metadata
    """

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(..., description="Embedding dimension")
    score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EmbeddingUpdate(BaseModel):
    """Embedding update request model.

    All fields are optional for partial updates.

    Args:
        embedding: New embedding vector (optional)
        metadata: Metadata updates (merged with existing, optional)
    """

    embedding: list[float] | None = Field(
        None, description="Updated embedding vector",
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Metadata updates",
    )


# =============================================================================
# Embedding Repository Implementation
# =============================================================================


class EmbeddingRepository(
    BaseRepository[EmbeddingCreate, EmbeddingRead, EmbeddingUpdate],
):
    """Repository for search.document_embeddings table operations.

    Provides CRUD operations for embeddings with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling
    - Vector similarity search support

    Usage:
        repo = EmbeddingRepository()

        async with repo:
            embedding = await repo.store_embedding(
                EmbeddingCreate(
                    document_id=doc_id,
                    model_name="all-MiniLM-L6-v2",
                    embedding=[0.1, 0.2, ...],
                )
            )
            results = await repo.search_similar(query_embedding, limit=10)
    """

    def __init__(self) -> None:
        """Initialize embedding repository."""
        super().__init__()
        self._table = "search.document_embeddings"

    async def store_embedding(self, data: EmbeddingCreate) -> EmbeddingRead:
        """Store an embedding vector.

        Args:
            data: Embedding creation data

        Returns:
            Stored embedding with generated timestamp

        Raises:
            RepositoryError: If storage fails
        """
        now = datetime.now(timezone.utc)

        query = f"""
            INSERT INTO {self._table} (
                document_id, model_name, embedding_dim, embedding, created_at, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (document_id) DO UPDATE SET
                model_name = EXCLUDED.model_name,
                embedding_dim = EXCLUDED.embedding_dim,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                created_at = EXCLUDED.created_at
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    data.document_id,
                    data.model_name,
                    data.embedding_dim,
                    str(data.embedding),
                    now,
                    data.metadata,
                )

                if row is None:
                    raise RepositoryError(
                        "Failed to store embedding",
                        operation="store_embedding",
                        details={"document_id": str(data.document_id)},
                    )

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "store_embedding",
                e,
                {"document_id": str(data.document_id)},
            )

    async def get_embedding(self, document_id: UUID) -> EmbeddingRead | None:
        """Get an embedding by document ID.

        Args:
            document_id: Document ID

        Returns:
            EmbeddingRead if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT document_id, model_name, embedding_dim, embedding, created_at, metadata
            FROM {self._table}
            WHERE document_id = $1
        """

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, document_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "get_embedding",
                e,
                {"document_id": str(document_id)},
            )

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 20,
        similarity_threshold: float = 0.5,
    ) -> list[EmbeddingSearchResult]:
        """Search for documents with similar embeddings.

        Uses cosine similarity to find the closest matching documents.

        Args:
            query_embedding: Query embedding vector
            limit: Maximum results (default: 20)
            similarity_threshold: Minimum similarity score (default: 0.5)

        Returns:
            List of search results sorted by similarity

        Raises:
            RepositoryError: If search fails
        """
        query = f"""
            SELECT document_id, model_name, embedding_dim, metadata,
                   1 - (embedding <=> $1::vector) as score
            FROM {self._table}
            WHERE 1 - (embedding <=> $1::vector) >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    query,
                    str(query_embedding),
                    similarity_threshold,
                    limit,
                )

                return [
                    EmbeddingSearchResult(
                        document_id=row["document_id"],
                        model_name=row["model_name"],
                        embedding_dim=row["embedding_dim"],
                        score=float(row["score"]),
                        metadata=row["metadata"] or {},
                    )
                    for row in rows
                ]

        except Exception as e:
            raise self._handle_error(
                "search_similar",
                e,
                {"limit": limit, "threshold": similarity_threshold},
            )

    async def delete_embedding(self, document_id: UUID) -> bool:
        """Delete an embedding by document ID.

        Args:
            document_id: Document ID

        Returns:
            True if deleted, False if not found

        Raises:
            RepositoryError: If deletion fails
        """
        query = f"DELETE FROM {self._table} WHERE document_id = $1"

        try:
            async with self.transaction() as conn:
                result = await conn.execute(query, document_id)
                return result == "DELETE 1"

        except Exception as e:
            raise self._handle_error(
                "delete_embedding",
                e,
                {"document_id": str(document_id)},
            )

    async def list_embeddings(
        self,
        model_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmbeddingRead]:
        """List embeddings with optional model filter.

        Args:
            model_name: Filter by model name (optional)
            limit: Maximum results (default: 50)
            offset: Result offset (default: 0)

        Returns:
            List of embeddings

        Raises:
            RepositoryError: If query fails
        """
        if model_name:
            query = f"""
                SELECT * FROM {self._table}
                WHERE model_name = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            params: list[Any] = [model_name, limit, offset]
        else:
            query = f"""
                SELECT * FROM {self._table}
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            params = [limit, offset]

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "list_embeddings",
                e,
                {"model_name": model_name},
            )

    def _row_to_model(self, row: Any) -> EmbeddingRead:
        """Convert database row to EmbeddingRead model.

        Args:
            row: Database row record

        Returns:
            EmbeddingRead model instance
        """
        embedding = row["embedding"]
        if isinstance(embedding, str):
            # Parse vector string representation
            embedding = [
                float(x) for x in embedding.strip("[]").split(",") if x.strip()
            ]

        return EmbeddingRead(
            document_id=row["document_id"],
            model_name=row["model_name"],
            embedding_dim=row["embedding_dim"],
            embedding=embedding,
            created_at=row["created_at"],
            metadata=row["metadata"] or {},
        )


__all__ = [
    "EmbeddingCreate",
    "EmbeddingRead",
    "EmbeddingUpdate",
    "EmbeddingSearchResult",
    "EmbeddingRepository",
]
