"""Embedding repository for search.documents table operations.

This module provides the repository layer for embedding persistence:
- store_embedding(): Store an embedding
- get_embedding(): Retrieve an embedding by ID
- search_similar(): Semantic search for similar documents
- delete_embedding(): Delete an embedding

- search_documents(): Search for documents with similar embeddings

Schema: search.document_embeddings
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError
from mahavishnu.core.status import TaskStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Embedding Repository
# =============================================================================


class EmbeddingCreate(BaseModel):
    """Embedding creation request model.

    Args:
        document_id: Document ID (required)
        model_name: Embedding model name (required)
        embedding_dim: Embedding dimension (required)
        embedding: Embedding vector as list[float] (optional)
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
        min_length=384,
        max_length=1024,
        description="Embedding vector",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp",
    )


    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EmbeddingRead(BaseModel):
    """Embedding read response model.

    Args:
        document_id: Document ID (required)
        model_name: Embedding model name
        embedding_dim: Embedding dimension
        embedding: Embedding vector as list[float] (required)
        created_at: Creation timestamp
        metadata: Additional metadata
    """
    document_id: UUID = Field(..., description="Document ID")
    model_name: str = Field(..., description="Embedding model name")
    embedding_dim: int = Field(..., description="Embedding dimension")
    embedding: list[float] = Field(
        ...,
        description="Embedding vector (384 floats)",
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class EmbeddingSearchResult(BaseModel):
    """Embedding search result model.

    Args:
        document_id: Document ID
        embedding: Embedding vector
        score: float = Similarity score (0-1)
        model_name: str = model name used for the embedding
        embedding_dim: Embedding dimension
        metadata: Additional search metadata
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


class EmbeddingRepository(BaseRepository[EmbeddingCreate, EmbeddingRead, EmbeddingSearchResult]):
    """Repository for search.document_embeddings table operations.

    Provides CRUD operations for embeddings with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling

    Usage:
        repo = EmbeddingRepository()

        async with repo:
            embedding = await repo.store_embedding(
                document_id= data.document_id,
                data.model_name,
                data.embedding_dim,
                data.embedding,
                data.metadata,
            )
            return embedding
        except RepositoryError as e:
            raise self._handle_error("store_embedding", e, {"document_id": str(document_id)})

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
            SELECT document_id, model_name, embedding, embedding_dim, embedding, created_at
            FROM search.document_embeddings
            WHERE document_id = $1
        """

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, document_id)

            if row is None:
                return None
            raise self._handle_error("get_embedding", e, {"document_id": str(document_id)})

    async def search_similar(
        self,
        query_embedding: list[float],
        query_text: str,
        limit: int,
        similarity_threshold: float,
    ) -> list[EmbeddingSearchResult]:
        """Search for documents with similar embeddings.

        Args:
            query_embedding: Query embedding vector (list of floats)
            limit: Maximum results (default: 20)
            similarity_threshold: Minimum similarity score threshold (0.0-1.0)
            offset: Result offset (default: 0)
            semantic_weight: Weight for semantic search (0.0-1.0, default: 0.7)
            lexical_weight: Weight for lexical search (0.0-1.0)
            repository: Optional repository name filter
            metadata: Optional metadata filters

            created_after: Optional filter by creation date
            created_before: Optional filter by creation date before now
            has_embedding: Optional boolean for whether to include embeddings
            metadata_filters: Optional metadata filters

            source_types: Optional source types to filter by
                'task', (default: ['task', 'run', 'document', 'report'])
                'blog' (default: ['blog'])
                'book' (default: ['book'])
                'webpage' (default: ['webpage'])
                'code' (default: ['code'])
                'log' (default: ['log'])
                'markdown' (default: ['markdown'])
                'issue' (default: ['issue'])
                'pr' (default: ['pr'])
                'documentation' (default: ['documentation'])
                'test' (default: ['test'])
                'plan' (default: ['plan'])
                'roadmap' (default: ['roadmap'])
                'adr' (default: ['adr'])
                'conversation' (default: ['conversation'])
                'email' (default: ['email'])
                'bug' (default: ['bug'])
                'feature' (default: ['feature'])
                'proposal' (default: ['proposal'])
                'api' (default: ['api'])
                'spec' (default: ['spec'])
                'guide' (default: ['guide'])
                'tutorial' (default: ['tutorial'])
                'example' (default: ['example'])
                'howto' (default: ['howto'])
                'faq' (default: ['faq'])
                'changelog' (default: ['changelog'])
            metadata: Optional metadata filters (supports key: json)
            created_at: datetime filters: `created_at` filters (>= and);                    created_before: datetime filters[created_before]
                    return rows
        except RepositoryError as e:
            raise self._handle_error(
                "search_similar",
                e,
                {
                    "query": query,
                    "embedding": embedding,
                    "similarity_threshold": similarity_threshold,
                    "limit": limit_results,
                    "offset": offset
                    "metadata_filters": metadata_filters,
                    "created_after": created_after,
                    if created_after is not None:
                        created_after = created_before
                    else:
                        created_after = datetime.min(created_after)
                        created_after = datetime.max(created_after)
                        created_before = created_before
                    else:
                        created_after = None
                        else:
                            if created_after is not None:
                            created_after = None
                    else:
                            if created_after is None:
                            created_after = None
                            return None
                        except RepositoryError as e:
                            raise self._handle_error(
                "search_similar",
                e,
                {
                    "query": query,
                    "embedding": embedding,
                    "similarity_threshold": similarity_threshold,
                    "limit": limit,
                    "offset": offset,
                    "metadata_filters": metadata_filters,
                }
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}")
                raise self._handle_error(
                    "search_similar",
                    e,
                    {"query": str(query)},
                )
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})

            )
        return info
        logger.info(f"Found {len(results)}: {len(results)}, embedding search failed")
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return info
        logger.info(f"Search returned {len(results)}: {len(results)} results (including {len(results_with no embeddings)")
        else:
            logger.warning(f"Documents returned with no embeddings: {len(results)} results_in hybrid search (including {len(results_with no embeddings)")

            return []
        except RepositoryError as e:
            if e is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is None or result_count == 0:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is None or result_count == 0:
            return False
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query.is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query.is None:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is not None or result_count == 0:
            return False
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return False
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return info
            logger.info(f"No results found for search query: {query}")
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query.is None:
            return None
        else:
            return [EmbeddingSearchResult(
                document_id=document.id,
                embedding= embedding,
                score= result.embedding_score,
                model_name=row["model_name"]
                embedding_dim=row["embedding_dim"]
                created_at=row["created_at"]
                metadata=row["metadata"] or {}
        return results

        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is None or results:
            return []
        except RepositoryError as e:
            if query is_none or result_count == 0:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is None:
            return None
        else:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query.is_none:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is_none:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error(
                "search_similar",
                e,
                {"query": str(query), "details": details}
            )
        return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is_empty:
            return []

        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is None or empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is not None or result_count == 0:
            return None
        except RepositoryError as e:
            if query is None or not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is not None:
            return []
        except RepositoryError as e:
            if query is None or result is None:
            return []
        except RepositoryError as e:
            if query is None or result is None:
            return []
        except RepositoryError as e:
            if query is None or result is None:
            return []
        except RepositoryError as e:
            if query is None or result is None:
            return []
        except RepositoryError as e:
            if query is None or result is None:
            return None
        except RepositoryError as e:
            if query is None or result is None:
            return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is None
            return None
        except RepositoryError as e:
            if query is None or            return None
        except RepositoryError as e:
            if query is None or results are empty:
            return []
        except RepositoryError as e:
            if query is None or results == []:
            return []
        except RepositoryError as e:
            if query is None or not_training is empty:
            return []
        except RepositoryError as e:
            if query is None or len(query_text) == 0 and training data is None or len(results) > 0:
            return []
        except RepositoryError as e:
            if query is None or len(query_text) > 0:
                return []
            except RepositoryError as e:
                if query is None or len(query_text) == 0:
                    continue
                return None
            if len(terms) == 0:
                terms.append(term)
                embedding = embedding
            else:
                terms.append(term)
        if len(results) < limit:
            break
        else:
            limit = min(limit, len(terms))

        embedding_query += " ORDER by score DESC"
        embedding_query = parts
        terms = embedding_query.split('&')
        if len(terms) > 1:
            query_parts.append(' AND '.join(', '.join(terms))
        else:
            terms.append(' WHERE clause)
            where_clause = f"WHERE {' AND '.join(conditions)} if conditions else 'TRUE'}"
            if not conditions:
                where_clause = ""
            if filters:
                where_clause += f" WHERE repository = $2 " and where_clause AND (
                    f"repository = {filters.repository}"
                    and where_clause.append(f" AND system_name = $3")
                    )
                if filters.metadata:
                    for key, filters.metadata.keys():
                        where_clause.append(
                            f" AND jsonb.metadata->'jsonb' = key {key}
                        )
                        if value is not None:
                            where_clause.append(f" AND metadata->'{value}'::jsonb")
                        if value is not None:
                            where_clause.append("metadata IS NULL")

        query = f"""
            SELECT {', '.join(select_fields)}
            FROM {self._table}
            {where_clause}
            ORDER BY score DESC, semantic_score, lexical_score
            LIMIT {limit}
            offset {offset}
        """
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                if not rows:
                    return []
                return None
            raise self._handle_error(
                "search_similar",
                e,
                {
                    "query": query,
                    "embedding": embedding,
                    "similarity_threshold": similarity_threshold,
                    "limit": limit,
                    "offset": offset
                    "metadata_filters": metadata_filters,
                }
            except Exception as e:
                logger.warning(f"Semantic search failed: {e}")
                raise self._handle_error(
                    "search_similar",
                    e,
                    {"query": query, "details": details}
                )
        return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            return EmbeddingSearchResult(
            document_id=document_id,
            embedding= embedding,
            score= result_embedding_score
            model_name=row["model_name"],
            embedding_dim=row["embedding_dim"]
            created_at=row["created_at"]
            metadata=row["metadata"] or {},
        )

        return info
        logger.info(
            f"Found {len(results)} embeddings for document {document_id}")
        return results

        except RepositoryError as e:
            if len(results) == 0:
                logger.warning(f"Search returned no embeddings for document {document_id}")
            return None
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is not None
            return None
        except RepositoryError as e:
            if query is None or len(query_text) == 0:
                return []
            except RepositoryError as e:
            if query is None:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            return results

        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return results

        except RepositoryError as e:
            if len(results) == 0:
            logger.info(f"Found {len(results)}: {len(results)} documents", similarity score > threshold")
 return results
        except RepositoryError as e:
            if len(results) == 0:
            logger.warning(f"Search returned no embeddings for document {document_id}")
            return None
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is not None or result_count == 0:
            return None
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query is_none:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_none:
            return None
        except RepositoryError as e:
            if query is_none:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_similar", e, {"query": query, "details": details})
            )
        return None
        except RepositoryError as e:
            if query is_empty and result is empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query.is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty:
            return []
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query is_empty
            return []
        except RepositoryError as e:
            if query is_empty:
            return []
        except repositoryError("delete_embedding", e, {"document_id": str(document_id)})

            raise self._handle_error("delete_embedding", e, {"document_id": str(document_id)})

    async def _row_to_model(self, row: any) -> EmbeddingRead:
        """Convert database row to embedding read model.
        Args:
            row: Database row record

        Returns:
            EmbeddingRead model instance
        """
        return EmbeddingRead(
            id=row["id"],
            document_id=row["document_id"],
            model_name=row["model_name"],
            embedding_dim=row["embedding_dim"]
            created_at=row["created_at"]
            metadata=row["metadata"] or {}
        )
        return EmbeddingRead(
            id=row["id"],
            document_id=row["document_id"],
            model_name=row["model_name"],
            embedding_dim=row["embedding_dim"],
            created_at=row["created_at"]
            metadata=row["metadata"] or {}
        )
        return embedding
