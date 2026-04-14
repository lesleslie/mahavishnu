"""MCP tools for hybrid search operations.

This module provides MCP tools that expose the hybrid search functionality:
- hybrid_search: Search across documents using semantic + lexical search
- index_document: Index a new document for search
- delete_document: Remove a document from the search index

These tools integrate with the HybridSearchEngine and follow the MCP tool
patterns established in the mahavishnu.mcp.tools module.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastmcp import FastMCP

from mahavishnu.core.search import HybridSearchEngine, HybridSearchConfig, HybridSearchResult
from mahavishnu.core.database import get_database

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Registration
# =============================================================================


def register_search_tools(mcp: FastMCP) -> None:
    """Register hybrid search tools with MCP server.

    Args:
        mcp: FastMCP server instance
    """
    # Global search engine instance (lazy initialization)
    _search_engine: HybridSearchEngine | None = None

    async def get_search_engine() -> HybridSearchEngine:
        """Get or create hybrid search engine instance."""
        nonlocal _search_engine
        if _search_engine is None:
            db = await get_database()
            config = HybridSearchConfig()  # Uses defaults
            _search_engine = HybridSearchEngine(database=db, config=config)
        return _search_engine

    @mcp.tool()
    async def hybrid_search(
        query: str,
        repository: str | None = None,
        limit: int = 20,
        semantic_weight: float = 0.7,
        lexical_weight: float = 0.3,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search across documents using hybrid semantic + lexical search."""
        try:
            # Create config with custom weights
            config = HybridSearchConfig(
                semantic_weight=semantic_weight,
                lexical_weight=lexical_weight,
                default_limit=limit,
                min_score=min_score,
            )

            # Get search engine with custom config
            engine = await get_search_engine()
            engine.config = config  # Update config for this search

            # Execute search
            results = await engine.search(
                query=query,
                repository=repository,
                limit=limit,
            )

            # Convert to dict for JSON serialization
            return [result.model_dump() for result in results]

        except Exception as e:
            logger.error(
                "hybrid_search tool failed",
                extra={
                    "query": query[:100],
                    "repository": repository,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    @mcp.tool()
    async def index_document(
        doc_id: str,
        title: str,
        content: str,
        repository: str | None = None,
        source_type: str = "document",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Index a document for hybrid search."""
        try:
            # Parse UUID
            doc_uuid = UUID(doc_id)

            # Get search engine
            engine = await get_search_engine()

            # Index document
            await engine.index_document(
                doc_id=doc_uuid,
                title=title,
                content=content,
                metadata=metadata or {},
                repository=repository,
                source_type=source_type,
            )

            return {
                "success": True,
                "doc_id": doc_id,
                "message": "Document indexed successfully",
            }

        except ValueError as e:
            logger.error(
                "index_document tool failed: invalid UUID",
                extra={"doc_id": doc_id, "error": str(e)},
            )
            raise ValueError(f"Invalid document UUID: {doc_id}") from e
        except Exception as e:
            logger.error(
                "index_document tool failed",
                extra={
                    "doc_id": doc_id,
                    "title": title[:50] if title else None,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    @mcp.tool()
    async def delete_document(doc_id: str) -> dict[str, Any]:
        """Delete a document from the search index."""
        try:
            # Parse UUID
            doc_uuid = UUID(doc_id)

            # Get search engine
            engine = await get_search_engine()

            # Delete document
            deleted = await engine.delete_document(doc_uuid)

            return {
                "success": True,
                "doc_id": doc_id,
                "deleted": deleted,
                "message": "Document deleted successfully" if deleted else "Document not found",
            }

        except ValueError as e:
            logger.error(
                "delete_document tool failed: invalid UUID",
                extra={"doc_id": doc_id, "error": str(e)},
            )
            raise ValueError(f"Invalid document UUID: {doc_id}") from e
        except Exception as e:
            logger.error(
                "delete_document tool failed",
                extra={"doc_id": doc_id, "error": str(e)},
                exc_info=True,
            )
            raise

    @mcp.tool()
    async def search_by_repository(
        repository: str,
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search documents within a specific repository."""
        try:
            engine = await get_search_engine()

            # If query is empty, do a broad search (effectively recent docs)
            search_query = query if query.strip() else "a"  # Minimal query to get results

            results = await engine.search(
                query=search_query,
                repository=repository,
                limit=limit,
            )

            return [result.model_dump() for result in results]

        except Exception as e:
            logger.error(
                "search_by_repository tool failed",
                extra={
                    "repository": repository,
                    "query": query[:100],
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    logger.info("Registered hybrid search MCP tools")


# =============================================================================
# Module-level registration for auto-discovery
# =============================================================================

__all__ = ["register_search_tools"]
