"""MCP tools for content ingestion.

This module provides FastMCP tools for ingesting web content and documents
into the Mahavishnu knowledge ecosystem.

Example:
    >>> from fastmcp import FastMCP
    >>> from mahavishnu.mcp.tools.content_ingestion_tools import register_content_tools
    >>>
    >>> mcp = FastMCP("mahavishnu")
    >>> register_content_tools(mcp)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ...ingesters.content_ingester import (
    ContentIngester,
    ContentType,
    IngestionResult,
    create_content_ingester,
)


# Global ingester instance (lazy initialized)
_ingester: ContentIngester | None = None


def _get_ingester() -> ContentIngester:
    """Get or create global content ingester instance."""
    global _ingester
    if _ingester is None:
        _ingester = create_content_ingester()
    return _ingester


def register_content_tools(mcp: FastMCP) -> None:
    """Register content ingestion tools with FastMCP server.

    Args:
        mcp: FastMCP server instance

    Example:
        >>> mcp = FastMCP("mahavishnu")
        >>> register_content_tools(mcp)
    """

    @mcp.tool()
    async def ingest_url(url: str) -> dict[str, Any]:
        """Ingest content from a URL into the knowledge ecosystem.

        This tool fetches content from the given URL and stores it in:
        - Akosha knowledge graph with embeddings
        - Crackerjack semantic file index
        - Session-Buddy tracking

        The content is automatically chunked and processed for semantic search.

        Args:
            url: URL to ingest (webpage, blog post, etc.)

        Returns:
            Dictionary with ingestion result including:
                - success: Whether ingestion succeeded
                - content_type: Type of content detected
                - title: Extracted title
                - chunk_count: Number of chunks created
                - stored_in_akosha: Whether stored in knowledge graph
                - indexed_in_crackerjack: Whether indexed for search
                - error: Error message if failed

        Example:
            >>> result = await ingest_url("https://blog.example.com/post")
            >>> print(result["success"], result["title"])
        """
        ingester = _get_ingester()

        if not ingester._initialized:
            await ingester.initialize()

        result = await ingester.ingest_url(url)
        return result.to_dict()

    @mcp.tool()
    async def ingest_file(file_path: str) -> dict[str, Any]:
        """Ingest content from a local file into the knowledge ecosystem.

        Supports:
        - PDF files (.pdf)
        - EPUB files (.epub)
        - Markdown files (.md, .markdown)
        - Text files (.txt, .text)

        The content is processed and stored in:
        - Akosha knowledge graph with embeddings
        - Crackerjack semantic file index
        - Session-Buddy tracking

        Args:
            file_path: Path to file to ingest

        Returns:
            Dictionary with ingestion result including:
                - success: Whether ingestion succeeded
                - content_type: Type of content detected
                - title: Extracted title (from filename)
                - chunk_count: Number of chunks created
                - stored_in_akosha: Whether stored in knowledge graph
                - indexed_in_crackerjack: Whether indexed for search
                - error: Error message if failed

        Example:
            >>> result = await ingest_file("documents/report.pdf")
            >>> print(result["success"], result["chunk_count"])
        """
        ingester = _get_ingester()

        if not ingester._initialized:
            await ingester.initialize()

        result = await ingester.ingest_file(file_path)
        return result.to_dict()

    @mcp.tool()
    async def batch_ingest_urls(urls: list[str]) -> list[dict[str, Any]]:
        """Ingest multiple URLs in parallel.

        Processes all URLs concurrently and returns results for each.
        Failed ingestions are reported without stopping the batch.

        Args:
            urls: List of URLs to ingest

        Returns:
            List of dictionaries, one per URL, with ingestion results

        Example:
            >>> urls = [
            ...     "https://blog1.example.com/post1",
            ...     "https://blog2.example.com/post2",
            ... ]
            >>> results = await batch_ingest_urls(urls)
            >>> successes = [r for r in results if r["success"]]
        """
        ingester = _get_ingester()

        if not ingester._initialized:
            await ingester.initialize()

        results = await ingester.batch_ingest_urls(urls)
        return [r.to_dict() for r in results]

    @mcp.tool()
    async def detect_content_type(source: str) -> str:
        """Detect the type of content from a URL or file path.

        Analyzes the source and returns the content type:
        - webpage: General web content
        - blog: Blog posts (detected by URL patterns)
        - pdf: PDF documents
        - epub: EPUB ebooks
        - markdown: Markdown files
        - text: Plain text files
        - unknown: Unable to determine

        Args:
            source: URL or file path to analyze

        Returns:
            Content type string

        Example:
            >>> ctype = await detect_content_type("https://blog.example.com/post")
            >>> print(ctype)  # "blog"
        """
        ingester = _get_ingester()
        content_type = ingester._detect_content_type(source)
        return content_type.value

    @mcp.tool()
    async def get_ingestion_stats() -> dict[str, Any]:
        """Get statistics about the content ingestion system.

        Returns:
            Dictionary with:
                - initialized: Whether ingester is initialized
                - output_dir: Directory where content is saved
                - chunk_size: Maximum characters per chunk
                - chunk_overlap: Character overlap between chunks
                - available_embeddings: Available embedding providers

        Example:
            >>> stats = await get_ingestion_stats()
            >>> print(stats["output_dir"], stats["chunk_size"])
        """
        ingester = _get_ingester()

        from ...core.embeddings import EmbeddingService

        embedding_service = EmbeddingService()
        available_providers = [p.value for p in embedding_service.get_available_providers()]

        return {
            "initialized": ingester._initialized,
            "output_dir": str(ingester._output_dir),
            "chunk_size": ingester._chunk_size,
            "chunk_overlap": ingester._chunk_overlap,
            "available_embeddings": available_providers,
        }
