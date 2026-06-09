"""Embedding repository for search.document_embeddings table operations.

This module provides the repository layer for embedding persistence:
- store_embedding(): Store an embedding vector
- get_embedding(): Retrieve an embedding by document ID
- search_similar(): Semantic search for similar documents
- delete_embedding(): Delete an embedding

Schema: search.document_embeddings
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static query constants — no f-strings, all user values via positional params.
# ---------------------------------------------------------------------------

_INSERT_EMBEDDING = (
    "INSERT INTO search.document_embeddings"
    " (document_id, model_name, embedding_dim, embedding, created_at, metadata)"
    " VALUES ($1, $2, $3, $4, $5, $6)"
    " ON CONFLICT (document_id) DO UPDATE SET"
    "   model_name = EXCLUDED.model_name,"
    "   embedding_dim = EXCLUDED.embedding_dim,"
    "   embedding = EXCLUDED.embedding,"
    "   metadata = EXCLUDED.metadata,"
    "   created_at = EXCLUDED.created_at"
    " RETURNING *"
)

_SELECT_BY_DOC = (
    "SELECT document_id, model_name, embedding_dim, embedding, created_at, metadata"
    " FROM search.document_embeddings"
    " WHERE document_id = $1"
)

_SEARCH_SIMILAR = (
    "SELECT document_id, model_name, embedding_dim, metadata,"
    "       1 - (embedding <=> $1::vector) AS score"
    " FROM search.document_embeddings"
    " WHERE 1 - (embedding <=> $1::vector) >= $2"
    " ORDER BY embedding <=> $1::vector"
    " LIMIT $3"
)

_DELETE_EMBEDDING = "DELETE FROM search.document_embeddings WHERE document_id = $1"

_LIST_ALL = "SELECT * FROM search.document_embeddings ORDER BY created_at DESC LIMIT $1 OFFSET $2"

_LIST_BY_MODEL = (
    "SELECT * FROM search.document_embeddings"
    " WHERE model_name = $1"
    " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
)


# =============================================================================
# Pydantic Models for Embedding Repository
# =============================================================================


class EmbeddingCreate(BaseModel):
    """Embedding creation request model."""

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(default=384, ge=128, le=1024, description="Embedding dimension")
    embedding: list[float] = Field(
        ..., min_length=128, max_length=1024, description="Embedding vector"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class EmbeddingRead(BaseModel):
    """Embedding read response model."""

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(..., description="Embedding dimension")
    embedding: list[float] = Field(..., description="Embedding vector")
    created_at: datetime = Field(..., description="Creation timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class EmbeddingSearchResult(BaseModel):
    """Embedding search result with similarity score."""

    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(..., description="Embedding dimension")
    score: float = Field(..., ge=0.0, le=1.0, description="Similarity score")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class EmbeddingUpdate(BaseModel):
    """Embedding update request model (all fields optional)."""

    embedding: list[float] | None = Field(None, description="Updated embedding vector")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates")


# =============================================================================
# Embedding Repository Implementation
# =============================================================================


class EmbeddingRepository(
    BaseRepository[EmbeddingCreate, EmbeddingRead, EmbeddingUpdate],
):
    """Repository for search.document_embeddings table operations."""

    async def create(self, data: EmbeddingCreate) -> EmbeddingRead:
        """Not used directly — use store_embedding() instead."""
        raise NotImplementedError("Use store_embedding() instead")

    async def store_embedding(self, data: EmbeddingCreate) -> EmbeddingRead:
        """Store an embedding vector."""
        now = datetime.now(UTC)
        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    _INSERT_EMBEDDING,
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
            raise self._handle_error("store_embedding", e, {"document_id": str(data.document_id)})

    async def get_embedding(self, document_id: UUID) -> EmbeddingRead | None:
        """Get an embedding by document ID."""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(_SELECT_BY_DOC, document_id)
                return self._row_to_model(row) if row is not None else None
        except Exception as e:
            raise self._handle_error("get_embedding", e, {"document_id": str(document_id)})

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 20,
        similarity_threshold: float = 0.5,
    ) -> list[EmbeddingSearchResult]:
        """Search for documents with similar embeddings using cosine similarity."""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(
                    _SEARCH_SIMILAR, str(query_embedding), similarity_threshold, limit
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
                "search_similar", e, {"limit": limit, "threshold": similarity_threshold}
            )

    async def delete_embedding(self, document_id: UUID) -> bool:
        """Delete an embedding by document ID."""
        try:
            async with self.transaction() as conn:
                result = await conn.execute(_DELETE_EMBEDDING, document_id)
                return result == "DELETE 1"  # type: ignore[no-any-return]
        except Exception as e:
            raise self._handle_error("delete_embedding", e, {"document_id": str(document_id)})

    async def list_embeddings(
        self,
        model_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EmbeddingRead]:
        """List embeddings with optional model filter."""
        try:
            async with self.connection() as conn:
                if model_name:
                    rows = await conn.fetch(_LIST_BY_MODEL, model_name, limit, offset)
                else:
                    rows = await conn.fetch(_LIST_ALL, limit, offset)
                return [self._row_to_model(row) for row in rows]
        except Exception as e:
            raise self._handle_error("list_embeddings", e, {"model_name": model_name})

    def _row_to_model(self, row: Any) -> EmbeddingRead:
        """Convert database row to EmbeddingRead model."""
        embedding = row["embedding"]
        if isinstance(embedding, str):
            embedding = [float(x) for x in embedding.strip("[]").split(",") if x.strip()]
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
