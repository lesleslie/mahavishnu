"""Document repository for search.documents table operations.

This module provides the repository layer for document persistence:
- create_document(): Create a new document
- get_document(): Retrieve a document by ID
- update_document(): Update document fields
- delete_document(): Delete a document
- search_documents(): Full-text and semantic search across documents

Schema: search.documents
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
# Pydantic Models for Document Repository
# =============================================================================


class DocumentCreate(BaseModel):
    """Document creation request model.

    Args:
        source_type: Source type (e.g., 'task', 'run', 'document', 'webpage')
        source_id: Optional source reference ID
        source_key: Source key for deduplication and lookup
        content: Document content text
        repository: Repository name
        system_name: System name (optional)
        metadata: Additional metadata
    """

    source_type: str = Field(..., description="Source type")
    source_id: UUID | None = Field(None, description="Source reference ID")
    source_key: str = Field(..., description="Source key for lookup")
    content: str = Field(..., description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class DocumentRead(BaseModel):
    """Document read response model.

    All fields from DocumentCreate plus:
    - id: UUID (primary key)
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    """

    id: UUID = Field(..., description="Document unique identifier")
    source_type: str = Field(..., description="Source type")
    source_id: UUID | None = Field(None, description="Source reference ID")
    source_key: str = Field(..., description="Source key for lookup")
    content: str = Field(..., description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class DocumentUpdate(BaseModel):
    """Document update request model.

    All fields are optional for partial updates.

    Args:
        content: New content (optional)
        repository: New repository name (optional)
        system_name: New system name (optional)
        metadata: Metadata updates (merged with existing, optional)
    """

    content: str | None = Field(None, description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    metadata: dict[str, Any] | None = Field(
        None, description="Metadata updates (merged)",
    )


class DocumentSearchResult(BaseModel):
    """Document search result with relevance scoring.

    Args:
        document: The matched document
        score: Relevance score (0.0-1.0)
        match_type: How the document was matched (semantic, lexical, hybrid)
    """

    document: DocumentRead = Field(..., description="Matched document")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score")
    match_type: str = Field(
        default="hybrid",
        description="Match type (semantic, lexical, hybrid)",
    )


# =============================================================================
# Document Repository Implementation
# =============================================================================


class DocumentRepository(
    BaseRepository[DocumentCreate, DocumentRead, DocumentUpdate],
):
    """Repository for search.documents table operations.

    Provides CRUD operations for documents with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling
    - Full-text search support

    Usage:
        repo = DocumentRepository()

        async with repo:
            doc = await repo.create_document(
                DocumentCreate(
                    source_type="task",
                    source_key="task-123-output",
                    content="Analysis results...",
                )
            )
            results = await repo.search_documents("error handling patterns")
    """

    def __init__(self) -> None:
        """Initialize document repository."""
        super().__init__()
        self._table = "search.documents"

    async def create_document(self, data: DocumentCreate) -> DocumentRead:
        """Create a new document.

        Args:
            data: Document creation data

        Returns:
            Created document with generated ID and timestamps

        Raises:
            RepositoryError: If creation fails
        """
        query = f"""
            INSERT INTO {self._table} (
                source_type, source_id, source_key, content,
                repository, system_name, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    data.source_type,
                    data.source_id,
                    data.source_key,
                    data.content,
                    data.repository,
                    data.system_name,
                    data.metadata,
                )

                if row is None:
                    raise RepositoryError(
                        "Failed to create document",
                        operation="create_document",
                        details={"source_key": data.source_key},
                    )

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "create_document",
                e,
                {"source_key": data.source_key},
            )

    async def get_document(self, document_id: UUID) -> DocumentRead | None:
        """Get a document by ID.

        Args:
            document_id: Document unique identifier

        Returns:
            Document if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"SELECT * FROM {self._table} WHERE id = $1"

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, document_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "get_document",
                e,
                {"document_id": str(document_id)},
            )

    async def get_document_by_key(
        self,
        source_key: str,
        source_type: str | None = None,
    ) -> DocumentRead | None:
        """Get a document by source key.

        Args:
            source_key: Source key to look up
            source_type: Optional source type filter

        Returns:
            Document if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        if source_type:
            query = f"""
                SELECT * FROM {self._table}
                WHERE source_key = $1 AND source_type = $2
                ORDER BY created_at DESC LIMIT 1
            """
            params = [source_key, source_type]
        else:
            query = f"""
                SELECT * FROM {self._table}
                WHERE source_key = $1
                ORDER BY created_at DESC LIMIT 1
            """
            params = [source_key]

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, *params)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "get_document_by_key",
                e,
                {"source_key": source_key},
            )

    async def update_document(
        self,
        document_id: UUID,
        data: DocumentUpdate,
    ) -> DocumentRead | None:
        """Update document fields.

        Args:
            document_id: Document unique identifier
            data: Update data (partial updates supported)

        Returns:
            Updated document if found, None otherwise

        Raises:
            RepositoryError: If update fails
        """
        updates = []
        params = [document_id]
        param_idx = 2

        field_mapping = {
            "content": "content",
            "repository": "repository",
            "system_name": "system_name",
        }

        for field, column in field_mapping.items():
            value = getattr(data, field, None)
            if value is not None:
                updates.append(f"{column} = ${param_idx}")
                params.append(value)
                param_idx += 1

        # Handle metadata merge
        if data.metadata is not None:
            updates.append(f"metadata = metadata || ${param_idx}::jsonb")
            params.append(data.metadata)
            param_idx += 1

        if not updates:
            return await self.get_document(document_id)

        now = datetime.now(timezone.utc)
        updates.append(f"updated_at = ${param_idx}")
        params.append(now)

        query = f"""
            UPDATE {self._table}
            SET {', '.join(updates)}
            WHERE id = $1
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(query, *params)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "update_document",
                e,
                {"document_id": str(document_id)},
            )

    async def delete_document(self, document_id: UUID) -> bool:
        """Delete a document.

        Args:
            document_id: Document ID to delete

        Returns:
            True if deleted, False if not found

        Raises:
            RepositoryError: If deletion fails
        """
        query = f"DELETE FROM {self._table} WHERE id = $1"

        try:
            async with self.transaction() as conn:
                result = await conn.execute(query, document_id)
                return result == "DELETE 1"

        except Exception as e:
            raise self._handle_error(
                "delete_document",
                e,
                {"document_id": str(document_id)},
            )

    async def search_documents(
        self,
        query_text: str,
        repository: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DocumentSearchResult]:
        """Search documents using full-text search.

        Args:
            query_text: Search query string
            repository: Optional repository filter
            limit: Maximum results (default: 20)
            offset: Result offset (default: 0)

        Returns:
            List of search results with relevance scores

        Raises:
            RepositoryError: If search fails
        """
        conditions = []
        params: list[Any] = []
        param_idx = 1

        # Full-text search condition
        conditions.append(
            f"to_tsvector('english', content) @@ plainto_tsquery('english', ${param_idx})",
        )
        params.append(query_text)
        param_idx += 1

        if repository:
            conditions.append(f"repository = ${param_idx}")
            params.append(repository)
            param_idx += 1

        params.extend([limit, offset])

        query = f"""
            SELECT *,
                   ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', ${1})
                   ) as score
            FROM {self._table}
            WHERE {' AND '.join(conditions)}
            ORDER BY score DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                results = []
                for row in rows:
                    doc = self._row_to_model(row)
                    score = float(row.get("score", 0.0))
                    # Normalize score to 0-1 range
                    normalized_score = min(max(score / 10.0, 0.0), 1.0)
                    results.append(
                        DocumentSearchResult(
                            document=doc,
                            score=normalized_score,
                            match_type="lexical",
                        ),
                    )
                return results

        except Exception as e:
            raise self._handle_error(
                "search_documents",
                e,
                {"query": query_text},
            )

    async def list_documents(
        self,
        repository: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentRead]:
        """List documents with optional filters.

        Args:
            repository: Filter by repository (optional)
            source_type: Filter by source type (optional)
            limit: Maximum results (default: 50)
            offset: Result offset (default: 0)

        Returns:
            List of documents matching filters

        Raises:
            RepositoryError: If query fails
        """
        conditions = []
        params: list[Any] = []
        param_idx = 1

        if repository:
            conditions.append(f"repository = ${param_idx}")
            params.append(repository)
            param_idx += 1

        if source_type:
            conditions.append(f"source_type = ${param_idx}")
            params.append(source_type)
            param_idx += 1

        where_clause = (
            f"WHERE {' AND '.join(conditions)}" if conditions else ""
        )
        params.extend([limit, offset])

        query = f"""
            SELECT * FROM {self._table}
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "list_documents",
                e,
                {"repository": repository, "source_type": source_type},
            )

    def _row_to_model(self, row: Any) -> DocumentRead:
        """Convert database row to DocumentRead model.

        Args:
            row: Database row record

        Returns:
            DocumentRead model instance
        """
        return DocumentRead(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_key=row["source_key"],
            content=row["content"],
            repository=row["repository"],
            system_name=row["system_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=row["metadata"] or {},
        )


__all__ = [
    "DocumentCreate",
    "DocumentRead",
    "DocumentUpdate",
    "DocumentSearchResult",
    "DocumentRepository",
]
