"""Content ingestion pipeline for blogs, webpages, and books.

This module provides a unified interface for ingesting web content and documents
into Mahavishnu's knowledge ecosystem (Akosha, Crackerjack, Session-Buddy).

Architecture:
    1. Fetch content from URLs (webpages, blogs) or local files (PDFs, EPUBs)
    2. Extract and clean text content
    3. Generate embeddings using Mahavishnu's embedding service
    4. Store in Akosha knowledge graph with metadata
    5. Index in Crackerjack for semantic search
    6. Track ingestion history in Session-Buddy

Example:
    >>> from mahavishnu.ingesters import ContentIngester
    >>> ingester = ContentIngester()
    >>> await ingester.initialize()
    >>> result = await ingester.ingest_url("https://blog.example.com/post")
    >>> await ingester.close()
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any
import urllib.parse

import httpx
import structlog

from ..core.embeddings import EmbeddingProvider, EmbeddingService, get_embedding_service
from ..core.observability import observe, span


# SSRF protection: blocked IP ranges
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('10.0.0.0/8'),        # Private Class A
    ipaddress.ip_network('172.16.0.0/12'),     # Private Class B
    ipaddress.ip_network('192.168.0.0/16'),    # Private Class C
    ipaddress.ip_network('127.0.0.0/8'),       # Loopback
    ipaddress.ip_network('169.254.0.0/16'),    # Link-local (cloud metadata)
    ipaddress.ip_network('0.0.0.0/8'),         # Current network
    ipaddress.ip_network('224.0.0.0/4'),       # Multicast
    ipaddress.ip_network('240.0.0.0/4'),       # Reserved
    ipaddress.ip_network('::1/128'),           # IPv6 loopback
    ipaddress.ip_network('fe80::/10'),         # IPv6 link-local
    ipaddress.ip_network('fc00::/7'),          # IPv6 private
]

# Blocked hostnames for SSRF protection
BLOCKED_HOSTNAMES = [
    'localhost',
    'localhost.localdomain',
    'ip6-localhost',
    'ip6-loopback',
    'metadata.google.internal',    # GCP metadata
    'metadata',                     # Azure metadata
    'kubernetes.default',           # K8s internal
    'kubernetes.default.svc',       # K8s internal
]


__all__ = [
    "ContentIngester",
    "ContentType",
    "IngestionResult",
    "create_content_ingester",
]


logger = structlog.get_logger()


class ContentType(Enum):
    """Types of content that can be ingested."""

    WEBPAGE = "webpage"
    BLOG = "blog"
    PDF = "pdf"
    EPUB = "epub"
    MARKDOWN = "markdown"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class IngestionResult:
    """Result of content ingestion.

    Attributes:
        success: Whether ingestion succeeded
        content_type: Type of content ingested
        source: Source URL or file path
        title: Extracted title
        chunk_count: Number of chunks created
        embedding_dimension: Dimension of embeddings generated
        stored_in_akosha: Whether stored in Akosha knowledge graph
        indexed_in_crackerjack: Whether indexed in Crackerjack
        error: Error message if failed
        metadata: Additional metadata
    """

    success: bool
    content_type: ContentType
    source: str
    title: str | None = None
    chunk_count: int = 0
    embedding_dimension: int = 0
    stored_in_akosha: bool = False
    indexed_in_crackerjack: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "success": self.success,
            "content_type": self.content_type.value,
            "source": self.source,
            "title": self.title,
            "chunk_count": self.chunk_count,
            "embedding_dimension": self.embedding_dimension,
            "stored_in_akosha": self.stored_in_akosha,
            "indexed_in_crackerjack": self.indexed_in_crackerjack,
            "error": self.error,
            "metadata": self.metadata,
        }


class ContentIngester:
    """Unified content ingestion pipeline.

    Integrates with:
    - web_reader MCP server for fetching web content
    - Akosha for embeddings and knowledge graph storage
    - Crackerjack for semantic file indexing
    - Session-Buddy for tracking ingestion history

    Example:
        >>> ingester = ContentIngester()
        >>> await ingester.initialize()
        >>> result = await ingester.ingest_url("https://example.com/blog")
        >>> print(result.to_dict())
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        output_dir: str | Path = "ingested",
        akosha_url: str = "http://localhost:8682/mcp",
        crackerjack_url: str = "http://localhost:8676/mcp",
        session_buddy_url: str = "http://localhost:8678/mcp",
        web_reader_url: str = "http://localhost:8699/mcp",  # web_reader MCP port
    ):
        """Initialize content ingester.

        Args:
            embedding_provider: Preferred embedding provider (None for auto-selection)
            chunk_size: Maximum characters per chunk
            chunk_overlap: Character overlap between chunks
            output_dir: Directory to save ingested content
            akosha_url: Akosha MCP server URL
            crackerjack_url: Crackerjack MCP server URL
            session_buddy_url: Session-Buddy MCP server URL
            web_reader_url: web_reader MCP server URL
        """
        self._embedding_provider = embedding_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # MCP server URLs
        self._akosha_url = akosha_url
        self._crackerjack_url = crackerjack_url
        self._session_buddy_url = session_buddy_url
        self._web_reader_url = web_reader_url

        # Embedding service (lazy initialized)
        self._embedding_service: EmbeddingService | None = None

        # HTTP clients for MCP servers
        self._akosha_client: httpx.AsyncClient | None = None
        self._crackerjack_client: httpx.AsyncClient | None = None
        self._session_buddy_client: httpx.AsyncClient | None = None
        self._web_reader_client: httpx.AsyncClient | None = None

        self._initialized = False
        self._log = logger.bind(component="content_ingester")

    async def initialize(self) -> None:
        """Initialize the ingester and connect to MCP servers.

        Raises:
            RuntimeError: If initialization fails
        """
        if self._initialized:
            return

        self._log.info(
            "initializing_content_ingester",
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
            output_dir=str(self._output_dir),
        )

        try:
            # Initialize embedding service
            self._embedding_service = get_embedding_service(self._embedding_provider)

            # Create HTTP clients for MCP servers
            timeout = httpx.Timeout(30.0, connect=10.0)
            self._akosha_client = httpx.AsyncClient(
                base_url=self._akosha_url, timeout=timeout
            )
            self._crackerjack_client = httpx.AsyncClient(
                base_url=self._crackerjack_url, timeout=timeout
            )
            self._session_buddy_client = httpx.AsyncClient(
                base_url=self._session_buddy_url, timeout=timeout
            )
            self._web_reader_client = httpx.AsyncClient(
                base_url=self._web_reader_url, timeout=timeout
            )

            self._initialized = True
            self._log.info("content_ingester_initialized")

        except Exception as e:
            self._log.error("initialization_failed", error=str(e))
            raise RuntimeError(f"Failed to initialize ContentIngester: {e}") from e

    async def close(self) -> None:
        """Close all connections."""
        if self._akosha_client:
            await self._akosha_client.aclose()
        if self._crackerjack_client:
            await self._crackerjack_client.aclose()
        if self._session_buddy_client:
            await self._session_buddy_client.aclose()
        if self._web_reader_client:
            await self._web_reader_client.aclose()

        self._initialized = False
        self._log.info("content_ingester_closed")

    async def __aenter__(self) -> ContentIngester:
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    @observe(span_name="content_ingester.detect_content_type")
    def _detect_content_type(self, source: str) -> ContentType:
        """Detect content type from source URL or file path.

        Args:
            source: URL or file path

        Returns:
            Detected content type
        """
        # Check if URL
        if source.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(source)

            # Blog detection patterns
            blog_patterns = ["/blog/", "/post/", "/article/", "/news/", "/posts/"]
            if any(pattern in parsed.path.lower() for pattern in blog_patterns):
                return ContentType.BLOG

            return ContentType.WEBPAGE

        # File detection
        path = Path(source).lower()
        if path.suffix == ".pdf":
            return ContentType.PDF
        if path.suffix == ".epub":
            return ContentType.EPUB
        if path.suffix in [".md", ".markdown"]:
            return ContentType.MARKDOWN
        if path.suffix in [".txt", ".text"]:
            return ContentType.TEXT

        return ContentType.UNKNOWN

    @observe(span_name="content_ingester.chunk_text")
    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks.

        Args:
            text: Text to chunk

        Returns:
            List of text chunks
        """
        if not text:
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + self._chunk_size

            # Try to break at word boundary
            if end < text_len:
                # Find last space in chunk
                last_space = text.rfind(" ", start, end)
                if last_space != -1:
                    end = last_space + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start with overlap
            start = end - self._chunk_overlap

            # Ensure progress
            if start <= 0:
                start = end

        return chunks

    def _validate_url(self, url: str) -> None:
        """Validate URL for SSRF protection.

        Args:
            url: URL to validate

        Raises:
            ValueError: If URL is blocked or invalid
        """
        parsed = urllib.parse.urlparse(url)

        # Only allow http and https schemes
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Blocked scheme: {parsed.scheme}. Only http and https are allowed.")

        # Block file:// protocol explicitly
        if parsed.scheme == 'file':
            raise ValueError("file:// protocol is not allowed.")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Invalid URL: no hostname")

        # Check blocked hostnames
        hostname_lower = hostname.lower()
        for blocked in BLOCKED_HOSTNAMES:
            if hostname_lower == blocked or hostname_lower.endswith(f'.{blocked}'):
                raise ValueError(f"Blocked hostname: {hostname}")

        # Resolve hostname and check IP ranges
        try:
            # Get all IP addresses for the hostname
            addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    for blocked_range in BLOCKED_IP_RANGES:
                        if ip in blocked_range:
                            raise ValueError(f"Blocked IP range: {ip} is in {blocked_range}")
                except ValueError:
                    # Not a valid IP, skip
                    pass
        except socket.gaierror as e:
            # DNS resolution failed - could be intentional for SSRF
            raise ValueError(f"DNS resolution failed for {hostname}: {e}") from e

    @observe(span_name="content_ingester.fetch_url")
    async def _fetch_url(self, url: str) -> dict[str, Any]:
        """Fetch content from URL using web_reader MCP server.

        Args:
            url: URL to fetch

        Returns:
            Dictionary with content and metadata

        Raises:
            RuntimeError: If fetch fails
            ValueError: If URL is blocked (SSRF protection)
        """
        # SSRF protection: validate URL before fetching
        self._validate_url(url)

        if not self._web_reader_client:
            raise RuntimeError("Ingester not initialized")

        try:
            response = await self._web_reader_client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "mcp__web_reader__webReader",
                        "arguments": {
                            "url": url,
                            "return_format": "markdown",
                            "retain_images": False,
                            "with_links_summary": True,
                        },
                    },
                },
            )

            if response.status_code != 200:
                raise RuntimeError(f"web_reader error: {response.status_code}")

            data = response.json()

            if "error" in data:
                raise RuntimeError(f"web_reader error: {data['error']}")

            # Extract content from response
            result = data.get("result", {})
            content_list = result if isinstance(result, list) else [result]

            if not content_list:
                raise RuntimeError("No content returned from web_reader")

            # Get first result
            first_result = content_list[0]

            # Extract text content
            text = first_result.get("text", "")
            metadata = first_result.get("metadata", {})

            # Extract title
            title = metadata.get("title") or metadata.get("og:title") or metadata.get("twitter:title")

            return {
                "text": text,
                "title": title,
                "url": url,
                "metadata": metadata,
            }

        except Exception as e:
            self._log.error("fetch_failed", url=url, error=str(e))
            raise RuntimeError(f"Failed to fetch URL {url}: {e}") from e

    @observe(span_name="content_ingester.generate_embeddings")
    async def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts.

        Args:
            texts: List of text strings

        Returns:
            List of embedding vectors
        """
        if not self._embedding_service:
            raise RuntimeError("Ingester not initialized")

        result = await self._embedding_service.embed(texts)
        return result.embeddings

    @observe(span_name="content_ingester.store_in_akosha")
    async def _store_in_akosha(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> bool:
        """Store content in Akosha knowledge graph.

        Args:
            content: Text content to store
            metadata: Metadata dictionary

        Returns:
            True if successful
        """
        if not self._akosha_client:
            return False

        try:
            # Generate embedding
            embeddings = await self._generate_embeddings([content])
            embedding = embeddings[0] if embeddings else []

            # Store memory with embedding
            response = await self._akosha_client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "mcp__akosha__store_memory",
                        "arguments": {
                            "content": content,
                            "metadata": {**metadata, "embedding": embedding},
                        },
                    },
                },
            )

            return response.status_code == 200

        except Exception as e:
            self._log.warning("akosha_store_failed", error=str(e))
            return False

    @observe(span_name="content_ingester.index_in_crackerjack")
    async def _index_in_crackerjack(self, file_path: str) -> bool:
        """Index file in Crackerjack for semantic search.

        Args:
            file_path: Path to file to index

        Returns:
            True if successful
        """
        if not self._crackerjack_client:
            return False

        try:
            response = await self._crackerjack_client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "mcp__crackerjack__index_file_semantic",
                        "arguments": {"file_path": file_path},
                    },
                },
            )

            result = response.json()

            if "error" in result:
                self._log.warning("crackerjack_index_error", error=result["error"])
                return False

            return response.status_code == 200

        except Exception as e:
            self._log.warning("crackerjack_index_failed", error=str(e))
            return False

    @observe(span_name="content_ingester.track_in_session_buddy")
    async def _track_in_session_buddy(
        self,
        source: str,
        content_type: ContentType,
        title: str | None = None,
    ) -> bool:
        """Track ingestion in Session-Buddy.

        Args:
            source: Source URL or file path
            content_type: Type of content
            title: Content title

        Returns:
            True if successful
        """
        if not self._session_buddy_client:
            return False

        try:
            response = await self._session_buddy_client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "mcp__session-buddy__store_reflection",
                        "arguments": {
                            "content": f"Ingested {content_type.value}: {title or source}",
                            "category": "content-ingestion",
                            "tags": [content_type.value, "ingested"],
                        },
                    },
                },
            )

            return response.status_code == 200

        except Exception as e:
            self._log.warning("session_buddy_track_failed", error=str(e))
            return False

    @observe(span_name="content_ingester.ingest_url")
    async def ingest_url(self, url: str) -> IngestionResult:
        """Ingest content from a URL.

        Args:
            url: URL to ingest

        Returns:
            IngestionResult with details

        Example:
            >>> result = await ingester.ingest_url("https://blog.example.com/post")
            >>> print(result.success)
        """
        if not self._initialized:
            await self.initialize()

        content_type = self._detect_content_type(url)

        self._log.info(
            "ingesting_url",
            url=url,
            content_type=content_type.value,
        )

        try:
            # Fetch content
            fetched = await self._fetch_url(url)
            text = fetched["text"]
            title = fetched.get("title")
            metadata = fetched.get("metadata", {})

            if not text:
                return IngestionResult(
                    success=False,
                    content_type=content_type,
                    source=url,
                    error="No content extracted",
                )

            # Chunk content
            chunks = self._chunk_text(text)

            # Generate embeddings for chunks
            embeddings = await self._generate_embeddings(chunks)

            # Save to file
            safe_title = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in (title or "untitled"))
            output_path = self._output_dir / f"{safe_title[:100]}.md"
            output_path.write_text(text, encoding="utf-8")

            # Store in Akosha (full content)
            stored_in_akosha = await self._store_in_akosha(
                content=text,
                metadata={
                    "source": url,
                    "title": title,
                    "content_type": content_type.value,
                    "chunk_count": len(chunks),
                    "ingested_at": datetime.now(UTC).isoformat(),
                },
            )

            # Index in Crackerjack
            indexed_in_crackerjack = await self._index_in_crackerjack(str(output_path))

            # Track in Session-Buddy
            await self._track_in_session_buddy(url, content_type, title)

            result = IngestionResult(
                success=True,
                content_type=content_type,
                source=url,
                title=title,
                chunk_count=len(chunks),
                embedding_dimension=len(embeddings[0]) if embeddings else 0,
                stored_in_akosha=stored_in_akosha,
                indexed_in_crackerjack=indexed_in_crackerjack,
                metadata={
                    "output_path": str(output_path),
                    "word_count": len(text.split()),
                    "char_count": len(text),
                    **metadata,
                },
            )

            self._log.info(
                "ingestion_complete",
                url=url,
                title=title,
                chunk_count=len(chunks),
                akosha=stored_in_akosha,
                crackerjack=indexed_in_crackerjack,
            )

            return result

        except Exception as e:
            self._log.error("ingestion_failed", url=url, error=str(e))
            return IngestionResult(
                success=False,
                content_type=content_type,
                source=url,
                error=str(e),
            )

    @observe(span_name="content_ingester.ingest_file")
    async def ingest_file(self, file_path: str | Path) -> IngestionResult:
        """Ingest content from a local file.

        Args:
            file_path: Path to file

        Returns:
            IngestionResult with details

        Example:
            >>> result = await ingester.ingest_file("document.pdf")
        """
        if not self._initialized:
            await self.initialize()

        file_path = Path(file_path)
        content_type = self._detect_content_type(str(file_path))

        self._log.info(
            "ingesting_file",
            file_path=str(file_path),
            content_type=content_type.value,
        )

        try:
            # Read file based on type
            if content_type == ContentType.PDF:
                text = await self._read_pdf(file_path)
            elif content_type == ContentType.EPUB:
                text = await self._read_epub(file_path)
            elif content_type in (ContentType.MARKDOWN, ContentType.TEXT):
                text = file_path.read_text(encoding="utf-8")
            else:
                # Try reading as text
                text = file_path.read_text(encoding="utf-8")

            if not text:
                return IngestionResult(
                    success=False,
                    content_type=content_type,
                    source=str(file_path),
                    error="No content extracted",
                )

            # Extract title from filename
            title = file_path.stem

            # Chunk content
            chunks = self._chunk_text(text)

            # Generate embeddings
            embeddings = await self._generate_embeddings(chunks)

            # Store in Akosha
            stored_in_akosha = await self._store_in_akosha(
                content=text,
                metadata={
                    "source": str(file_path),
                    "title": title,
                    "content_type": content_type.value,
                    "chunk_count": len(chunks),
                    "ingested_at": datetime.now(UTC).isoformat(),
                },
            )

            # Index in Crackerjack
            indexed_in_crackerjack = await self._index_in_crackerjack(str(file_path))

            # Track in Session-Buddy
            await self._track_in_session_buddy(str(file_path), content_type, title)

            result = IngestionResult(
                success=True,
                content_type=content_type,
                source=str(file_path),
                title=title,
                chunk_count=len(chunks),
                embedding_dimension=len(embeddings[0]) if embeddings else 0,
                stored_in_akosha=stored_in_akosha,
                indexed_in_crackerjack=indexed_in_crackerjack,
                metadata={
                    "word_count": len(text.split()),
                    "char_count": len(text),
                },
            )

            self._log.info(
                "file_ingestion_complete",
                file_path=str(file_path),
                chunk_count=len(chunks),
                akosha=stored_in_akosha,
                crackerjack=indexed_in_crackerjack,
            )

            return result

        except Exception as e:
            self._log.error("file_ingestion_failed", file_path=str(file_path), error=str(e))
            return IngestionResult(
                success=False,
                content_type=content_type,
                source=str(file_path),
                error=str(e),
            )

    async def _read_pdf(self, file_path: Path) -> str:
        """Extract text from PDF file.

        Args:
            file_path: Path to PDF file

        Returns:
            Extracted text
        """
        try:
            import pypdf

            reader = pypdf.PdfReader(file_path)
            text = "\n".join([page.extract_text() for page in reader.pages])
            return text

        except ImportError:
            raise RuntimeError(
                "pypdf not installed. Install with: uv pip install pypdf"
            ) from None

    async def _read_epub(self, file_path: Path) -> str:
        """Extract text from EPUB file.

        Args:
            file_path: Path to EPUB file

        Returns:
            Extracted text
        """
        try:
            from ebooklib import epub

            book = epub.read_epub(str(file_path))
            chapters = []

            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    content = item.get_content()
                    # Extract text from HTML (simplified)
                    import re

                    text = re.sub(r"<[^>]+>", "", content.decode("utf-8"))
                    chapters.append(text)

            return "\n\n".join(chapters)

        except ImportError:
            raise RuntimeError(
                "ebooklib not installed. Install with: uv pip install ebooklib"
            ) from None

    @observe(span_name="content_ingester.batch_ingest")
    async def batch_ingest_urls(self, urls: list[str]) -> list[IngestionResult]:
        """Ingest multiple URLs in parallel.

        Args:
            urls: List of URLs to ingest

        Returns:
            List of IngestionResults

        Example:
            >>> urls = ["https://blog1.com", "https://blog2.com"]
            >>> results = await ingester.batch_ingest_urls(urls)
            >>> print([r.success for r in results])
        """
        if not self._initialized:
            await self.initialize()

        self._log.info("batch_ingest_start", count=len(urls))

        tasks = [self.ingest_url(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        final_results = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                final_results.append(
                    IngestionResult(
                        success=False,
                        content_type=ContentType.UNKNOWN,
                        source=url,
                        error=str(result),
                    )
                )
            else:
                final_results.append(result)

        success_count = sum(1 for r in final_results if r.success)
        self._log.info("batch_ingest_complete", success=success_count, total=len(urls))

        return final_results


@lru_cache
def create_content_ingester(
    embedding_provider: EmbeddingProvider | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> ContentIngester:
    """Create or get cached content ingester instance.

    Args:
        embedding_provider: Preferred embedding provider
        chunk_size: Maximum characters per chunk
        chunk_overlap: Character overlap between chunks

    Returns:
        ContentIngester instance (cached)

    Example:
        >>> ingester = create_content_ingester()
        >>> await ingester.initialize()
        >>> result = await ingester.ingest_url("https://example.com")
    """
    return ContentIngester(
        embedding_provider=embedding_provider,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
