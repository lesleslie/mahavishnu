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

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static query constants — no f-strings, no concatenation in execution paths.
# All user-supplied values are bound via asyncpg positional parameters ($N).
# ---------------------------------------------------------------------------

_INSERT_DOCUMENT = (
    "INSERT INTO search.documents"
    " (source_type, source_id, source_key, content, repository, system_name, metadata)"
    " VALUES ($1, $2, $3, $4, $5, $6, $7)"
    " RETURNING *"
)

_SELECT_BY_ID = "SELECT * FROM search.documents WHERE id = $1"

_SELECT_BY_KEY_WITH_TYPE = (
    "SELECT * FROM search.documents"
    " WHERE source_key = $1 AND source_type = $2"
    " ORDER BY created_at DESC LIMIT 1"
)

_SELECT_BY_KEY = (
    "SELECT * FROM search.documents WHERE source_key = $1 ORDER BY created_at DESC LIMIT 1"
)

_DELETE_BY_ID = "DELETE FROM search.documents WHERE id = $1"

# list_documents: 4 pre-defined variants, no dynamic query building.
_LIST_ALL = "SELECT * FROM search.documents ORDER BY created_at DESC LIMIT $1 OFFSET $2"
_LIST_BY_REPO = (
    "SELECT * FROM search.documents"
    " WHERE repository = $1"
    " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
)
_LIST_BY_TYPE = (
    "SELECT * FROM search.documents"
    " WHERE source_type = $1"
    " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
)
_LIST_BY_REPO_AND_TYPE = (
    "SELECT * FROM search.documents"
    " WHERE repository = $1 AND source_type = $2"
    " ORDER BY created_at DESC LIMIT $3 OFFSET $4"
)

# search_documents: 2 pre-defined variants.
_SEARCH_BASE = (
    "SELECT *, ts_rank(to_tsvector('english', content),"
    "                  plainto_tsquery('english', $1)) AS score"
    " FROM search.documents"
    " WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)"
    " ORDER BY score DESC LIMIT $2 OFFSET $3"
)
_SEARCH_WITH_REPO = (
    "SELECT *, ts_rank(to_tsvector('english', content),"
    "                  plainto_tsquery('english', $1)) AS score"
    " FROM search.documents"
    " WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)"
    "   AND repository = $2"
    " ORDER BY score DESC LIMIT $3 OFFSET $4"
)

# update_document: all 15 non-empty subsets of {content, repository, system_name, metadata}.
# Fields are always ordered: content → repository → system_name → metadata → updated_at.
# $1 = document_id (always), remaining params follow field order above.
_c = "content"
_r = "repository"
_s = "system_name"
_m = "metadata"

_UPDATE_QUERIES: dict[frozenset[str], str] = {
    # 1 field
    frozenset({_c}): (
        "UPDATE search.documents SET content = $2, updated_at = $3 WHERE id = $1 RETURNING *"
    ),
    frozenset({_r}): (
        "UPDATE search.documents SET repository = $2, updated_at = $3 WHERE id = $1 RETURNING *"
    ),
    frozenset({_s}): (
        "UPDATE search.documents SET system_name = $2, updated_at = $3 WHERE id = $1 RETURNING *"
    ),
    frozenset({_m}): (
        "UPDATE search.documents SET metadata = metadata || $2::jsonb, updated_at = $3"
        " WHERE id = $1 RETURNING *"
    ),
    # 2 fields
    frozenset({_c, _r}): (
        "UPDATE search.documents SET content = $2, repository = $3, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_c, _s}): (
        "UPDATE search.documents SET content = $2, system_name = $3, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_c, _m}): (
        "UPDATE search.documents"
        " SET content = $2, metadata = metadata || $3::jsonb, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_r, _s}): (
        "UPDATE search.documents SET repository = $2, system_name = $3, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_r, _m}): (
        "UPDATE search.documents"
        " SET repository = $2, metadata = metadata || $3::jsonb, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_s, _m}): (
        "UPDATE search.documents"
        " SET system_name = $2, metadata = metadata || $3::jsonb, updated_at = $4"
        " WHERE id = $1 RETURNING *"
    ),
    # 3 fields
    frozenset({_c, _r, _s}): (
        "UPDATE search.documents"
        " SET content = $2, repository = $3, system_name = $4, updated_at = $5"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_c, _r, _m}): (
        "UPDATE search.documents"
        " SET content = $2, repository = $3, metadata = metadata || $4::jsonb, updated_at = $5"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_c, _s, _m}): (
        "UPDATE search.documents"
        " SET content = $2, system_name = $3, metadata = metadata || $4::jsonb, updated_at = $5"
        " WHERE id = $1 RETURNING *"
    ),
    frozenset({_r, _s, _m}): (
        "UPDATE search.documents"
        " SET repository = $2, system_name = $3, metadata = metadata || $4::jsonb, updated_at = $5"
        " WHERE id = $1 RETURNING *"
    ),
    # 4 fields
    frozenset({_c, _r, _s, _m}): (
        "UPDATE search.documents"
        " SET content = $2, repository = $3, system_name = $4,"
        "     metadata = metadata || $5::jsonb, updated_at = $6"
        " WHERE id = $1 RETURNING *"
    ),
}

# Field param order for UPDATE: always processed in this sequence.
_UPDATE_FIELD_ORDER = (_c, _r, _s, _m)


# =============================================================================
# Pydantic Models for Document Repository
# =============================================================================


class DocumentCreate(BaseModel):
    """Document creation request model."""

    source_type: str = Field(..., description="Source type")
    source_id: UUID | None = Field(None, description="Source reference ID")
    source_key: str = Field(..., description="Source key for lookup")
    content: str = Field(..., description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class DocumentRead(BaseModel):
    """Document read response model."""

    id: UUID = Field(..., description="Document unique identifier")
    source_type: str = Field(..., description="Source type")
    source_id: UUID | None = Field(None, description="Source reference ID")
    source_key: str = Field(..., description="Source key for lookup")
    content: str = Field(..., description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class DocumentUpdate(BaseModel):
    """Document update request model (all fields optional)."""

    content: str | None = Field(None, description="Document content")
    repository: str | None = Field(None, description="Repository name")
    system_name: str | None = Field(None, description="System name")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates (merged)")


class DocumentSearchResult(BaseModel):
    """Document search result with relevance scoring."""

    document: DocumentRead = Field(..., description="Matched document")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score")
    match_type: str = Field(default="hybrid", description="Match type")


# =============================================================================
# Document Repository Implementation
# =============================================================================


class DocumentRepository(
    BaseRepository[DocumentCreate, DocumentRead, DocumentUpdate],
):
    """Repository for search.documents table operations."""

    async def create_document(self, data: DocumentCreate) -> DocumentRead:
        """Create a new document."""
        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    _INSERT_DOCUMENT,
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
            raise self._handle_error("create_document", e, {"source_key": data.source_key})

    async def get_document(self, document_id: UUID) -> DocumentRead | None:
        """Get a document by ID."""
        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(_SELECT_BY_ID, document_id)
                return self._row_to_model(row) if row is not None else None
        except Exception as e:
            raise self._handle_error("get_document", e, {"document_id": str(document_id)})

    async def get_document_by_key(
        self,
        source_key: str,
        source_type: str | None = None,
    ) -> DocumentRead | None:
        """Get a document by source key."""
        try:
            async with self.connection() as conn:
                if source_type:
                    row = await conn.fetchrow(_SELECT_BY_KEY_WITH_TYPE, source_key, source_type)
                else:
                    row = await conn.fetchrow(_SELECT_BY_KEY, source_key)
                return self._row_to_model(row) if row is not None else None
        except Exception as e:
            raise self._handle_error("get_document_by_key", e, {"source_key": source_key})

    async def update_document(
        self,
        document_id: UUID,
        data: DocumentUpdate,
    ) -> DocumentRead | None:
        """Update document fields (partial update supported)."""
        fields = frozenset(f for f in _UPDATE_FIELD_ORDER if getattr(data, f, None) is not None)
        if not fields:
            return await self.get_document(document_id)

        query = _UPDATE_QUERIES[fields]
        now = datetime.now(UTC)
        params: list[Any] = [document_id]
        for f in _UPDATE_FIELD_ORDER:
            if f in fields:
                params.append(getattr(data, f))
        params.append(now)

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(query, *params)
                return self._row_to_model(row) if row is not None else None
        except Exception as e:
            raise self._handle_error("update_document", e, {"document_id": str(document_id)})

    async def delete_document(self, document_id: UUID) -> bool:
        """Delete a document."""
        try:
            async with self.transaction() as conn:
                result = await conn.execute(_DELETE_BY_ID, document_id)
                return result == "DELETE 1"
        except Exception as e:
            raise self._handle_error("delete_document", e, {"document_id": str(document_id)})

    async def search_documents(
        self,
        query_text: str,
        repository: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DocumentSearchResult]:
        """Search documents using full-text search."""
        try:
            async with self.connection() as conn:
                if repository:
                    rows = await conn.fetch(
                        _SEARCH_WITH_REPO, query_text, repository, limit, offset
                    )
                else:
                    rows = await conn.fetch(_SEARCH_BASE, query_text, limit, offset)
                results = []
                for row in rows:
                    score = min(max(float(row.get("score", 0.0)) / 10.0, 0.0), 1.0)
                    results.append(
                        DocumentSearchResult(
                            document=self._row_to_model(row),
                            score=score,
                            match_type="lexical",
                        )
                    )
                return results
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query_text})

    async def list_documents(
        self,
        repository: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentRead]:
        """List documents with optional filters."""
        try:
            async with self.connection() as conn:
                if repository and source_type:
                    rows = await conn.fetch(
                        _LIST_BY_REPO_AND_TYPE, repository, source_type, limit, offset
                    )
                elif repository:
                    rows = await conn.fetch(_LIST_BY_REPO, repository, limit, offset)
                elif source_type:
                    rows = await conn.fetch(_LIST_BY_TYPE, source_type, limit, offset)
                else:
                    rows = await conn.fetch(_LIST_ALL, limit, offset)
                return [self._row_to_model(row) for row in rows]
        except Exception as e:
            raise self._handle_error(
                "list_documents", e, {"repository": repository, "source_type": source_type}
            )

    def _row_to_model(self, row: Any) -> DocumentRead:
        """Convert database row to DocumentRead model."""
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
