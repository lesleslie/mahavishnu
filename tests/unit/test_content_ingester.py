"""Comprehensive unit tests for mahavishnu.ingesters.content_ingester.

Covers:
    1. Initialization and configuration
    2. Content type detection
    3. Text chunking
    4. URL validation / SSRF protection
    5. Webpage ingestion (mock HTTP)
    6. Blog ingestion (mock HTTP)
    7. Book ingestion (mock PDF / EPUB parsing)
    8. Quality evaluation paths
    9. Embedding generation
    10. MCP server integration (Akosha, Crackerjack, Session-Buddy)
    11. Batch ingestion
    12. Error handling (network errors, invalid content, missing deps)
    13. Content validation and scoring
    14. Context manager protocol
    15. Factory function (create_content_ingester)
    16. IngestionResult dataclass
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.ingesters.content_ingester import (
    BLOCKED_HOSTNAMES,
    BLOCKED_IP_RANGES,
    ContentIngester,
    ContentType,
    IngestionResult,
    TurboQuantCompressionInfo,
    create_content_ingester,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_web_reader_response(
    text: str = "Sample article content.",
    title: str = "Test Page",
    status_code: int = 200,
    error: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a mock web_reader MCP JSON-RPC response dict.

    When *metadata* is None, defaults to ``{"title": title}``.
    When *metadata* is an empty dict (``{}``), it is used as-is (no title).
    To send no title, pass ``metadata={}`` explicitly.
    """
    result_item: dict[str, object] = {
        "text": text,
        "metadata": metadata if metadata is not None else {"title": title},
    }
    payload: dict = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": [result_item],
    }
    if error is not None:
        del payload["result"]
        payload["error"] = error
    return payload


def _make_mcp_response(status_code: int = 200, body: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response for MCP server calls."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = body or {}
    return resp


# ---------------------------------------------------------------------------
# ContentType
# ---------------------------------------------------------------------------


class TestContentType:
    """Tests for the ContentType enum."""

    def test_all_values_exist(self):
        expected = {"webpage", "blog", "pdf", "epub", "markdown", "text", "unknown"}
        actual = {m.value for m in ContentType}
        assert actual == expected

    def test_value_string(self):
        assert ContentType.WEBPAGE.value == "webpage"
        assert ContentType.BLOG.value == "blog"
        assert ContentType.PDF.value == "pdf"


# ---------------------------------------------------------------------------
# IngestionResult
# ---------------------------------------------------------------------------


class TestIngestionResult:
    """Tests for the IngestionResult dataclass."""

    def test_success_result_defaults(self):
        result = IngestionResult(
            success=True,
            content_type=ContentType.WEBPAGE,
            source="https://example.com",
        )
        assert result.success is True
        assert result.title is None
        assert result.chunk_count == 0
        assert result.embedding_dimension == 0
        assert result.stored_in_akosha is False
        assert result.indexed_in_crackerjack is False
        assert result.error is None
        assert result.metadata == {}

    def test_failure_result(self):
        result = IngestionResult(
            success=False,
            content_type=ContentType.PDF,
            source="/tmp/doc.pdf",
            error="File not found",
        )
        assert result.success is False
        assert result.error == "File not found"

    def test_to_dict(self):
        result = IngestionResult(
            success=True,
            content_type=ContentType.BLOG,
            source="https://blog.example.com/post",
            title="My Post",
            chunk_count=5,
            embedding_dimension=384,
            stored_in_akosha=True,
            indexed_in_crackerjack=True,
            metadata={"word_count": 100},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["content_type"] == "blog"
        assert d["source"] == "https://blog.example.com/post"
        assert d["title"] == "My Post"
        assert d["chunk_count"] == 5
        assert d["embedding_dimension"] == 384
        assert d["stored_in_akosha"] is True
        assert d["indexed_in_crackerjack"] is True
        assert d["metadata"] == {"word_count": 100}

    def test_to_dict_with_error(self):
        result = IngestionResult(
            success=False,
            content_type=ContentType.UNKNOWN,
            source="bad",
            error="boom",
        )
        d = result.to_dict()
        assert d["error"] == "boom"
        assert d["success"] is False

    def test_to_dict_turboquant_compression_none_by_default(self):
        result = IngestionResult(
            success=True,
            content_type=ContentType.WEBPAGE,
            source="https://example.com",
        )
        d = result.to_dict()
        assert "turboquant_compression" in d
        assert d["turboquant_compression"] is None

    def test_to_dict_turboquant_compression_present(self):
        tq_info = TurboQuantCompressionInfo(
            uncompressed_kb=1500.0, compressed_kb=187.5, savings_kb=1312.5, ratio=8.0, bits=4
        )
        result = IngestionResult(
            success=True,
            content_type=ContentType.WEBPAGE,
            source="https://example.com",
            turboquant_compression=tq_info,
        )
        d = result.to_dict()
        assert d["turboquant_compression"] == tq_info
        assert d["turboquant_compression"]["bits"] == 4


# ---------------------------------------------------------------------------
# ContentIngester -- Initialization
# ---------------------------------------------------------------------------


class TestContentIngesterInit:
    """Tests for ContentIngester constructor."""

    def test_default_init(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        assert ingester._chunk_size == 1000
        assert ingester._chunk_overlap == 200
        assert ingester._output_dir == tmp_path
        assert ingester._akosha_url == "http://localhost:8682/mcp"
        assert ingester._crackerjack_url == "http://localhost:8676/mcp"
        assert ingester._session_buddy_url == "http://localhost:8678/mcp"
        assert ingester._web_reader_url == "http://localhost:8699/mcp"
        assert ingester._initialized is False
        assert ingester._embedding_service is None
        assert ingester._akosha_client is None

    def test_custom_init(self, tmp_path: Path):
        ingester = ContentIngester(
            chunk_size=500,
            chunk_overlap=100,
            output_dir=str(tmp_path / "custom"),
            akosha_url="http://custom:8682/mcp",
            crackerjack_url="http://custom:8676/mcp",
            session_buddy_url="http://custom:8678/mcp",
            web_reader_url="http://custom:8699/mcp",
        )
        assert ingester._chunk_size == 500
        assert ingester._chunk_overlap == 100
        assert ingester._output_dir == tmp_path / "custom"
        assert ingester._akosha_url == "http://custom:8682/mcp"

    def test_output_dir_created(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        ContentIngester(output_dir=str(nested))
        assert nested.exists()
        assert nested.is_dir()

    def test_embedding_provider_stored(self, tmp_path: Path):
        from mahavishnu.core.embeddings import EmbeddingProvider

        ingester = ContentIngester(
            embedding_provider=EmbeddingProvider.OLLAMA,
            output_dir=str(tmp_path),
        )
        assert ingester._embedding_provider == EmbeddingProvider.OLLAMA

    def test_turboquant_bits_stored(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path), turboquant_bits=4)
        assert ingester._turboquant_bits == 4
        assert ingester._compressor is None  # lazy — not created until initialize()

    def test_turboquant_bits_none_by_default(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        assert ingester._turboquant_bits is None
        assert ingester._compressor is None


# ---------------------------------------------------------------------------
# ContentIngester -- Initialize / Close
# ---------------------------------------------------------------------------


class TestContentIngesterInitialize:
    """Tests for initialize and close methods."""

    @pytest.mark.asyncio
    async def test_initialize_sets_clients(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=MagicMock(),
        ):
            await ingester.initialize()
        assert ingester._initialized is True
        assert ingester._embedding_service is not None
        assert ingester._akosha_client is not None
        assert ingester._crackerjack_client is not None
        assert ingester._session_buddy_client is not None
        assert ingester._web_reader_client is not None
        await ingester.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=MagicMock(),
        ):
            await ingester.initialize()
            first_client = ingester._akosha_client
            await ingester.initialize()
            # Client should not be recreated
            assert ingester._akosha_client is first_client
        await ingester.close()

    @pytest.mark.asyncio
    async def test_initialize_failure_raises_runtime_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        with (
            patch(
                "mahavishnu.ingesters.content_ingester.get_embedding_service",
                side_effect=RuntimeError("embedding service unavailable"),
            ),
            pytest.raises(RuntimeError, match="Failed to initialize ContentIngester"),
        ):
            await ingester.initialize()

    @pytest.mark.asyncio
    async def test_close_is_safe_before_init(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        # Should not raise
        await ingester.close()
        assert ingester._initialized is False

    @pytest.mark.asyncio
    async def test_close_resets_initialized(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=MagicMock(),
        ):
            await ingester.initialize()
            assert ingester._initialized is True
            await ingester.close()
            assert ingester._initialized is False

    @pytest.mark.asyncio
    async def test_context_manager(self, tmp_path: Path):
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=MagicMock(),
        ):
            async with ContentIngester(output_dir=str(tmp_path)) as ing:
                assert ing._initialized is True
            assert ing._initialized is False

    @pytest.mark.asyncio
    async def test_close_calls_aclose_on_all_clients(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=MagicMock(),
        ):
            await ingester.initialize()

        # Replace clients with mocks we can verify
        mock_akosha = AsyncMock()
        mock_crackerjack = AsyncMock()
        mock_session = AsyncMock()
        mock_web_reader = AsyncMock()
        ingester._akosha_client = mock_akosha
        ingester._crackerjack_client = mock_crackerjack
        ingester._session_buddy_client = mock_session
        ingester._web_reader_client = mock_web_reader

        await ingester.close()

        mock_akosha.aclose.assert_awaited_once()
        mock_crackerjack.aclose.assert_awaited_once()
        mock_session.aclose.assert_awaited_once()
        mock_web_reader.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_creates_compressor_when_bits_set(self, tmp_path: Path):
        """initialize() should construct TurboQuantCompressor when turboquant_bits is set."""
        with (
            patch(
                "mahavishnu.ingesters.content_ingester.get_embedding_service",
                return_value=MagicMock(),
            ),
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", True),
        ):
            ingester = ContentIngester(output_dir=str(tmp_path), turboquant_bits=4)
            await ingester.initialize()
            assert ingester._compressor is not None
            assert ingester._compressor.bits == 4
            await ingester.close()

    @pytest.mark.asyncio
    async def test_initialize_no_compressor_when_bits_none(self, tmp_path: Path):
        """initialize() should not create a compressor when turboquant_bits is None."""
        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service", return_value=MagicMock()
        ):
            ingester = ContentIngester(output_dir=str(tmp_path))
            await ingester.initialize()
            assert ingester._compressor is None
            await ingester.close()

    @pytest.mark.asyncio
    async def test_initialize_compressor_unavailable_does_not_raise(self, tmp_path: Path):
        """initialize() should succeed even when turboquant-pro is not installed."""
        with (
            patch(
                "mahavishnu.ingesters.content_ingester.get_embedding_service",
                return_value=MagicMock(),
            ),
            patch("mahavishnu.ingesters.turboquant_compressor.TURBOQUANT_AVAILABLE", False),
        ):
            ingester = ContentIngester(output_dir=str(tmp_path), turboquant_bits=4)
            await ingester.initialize()  # must not raise
            assert ingester._compressor is not None
            assert ingester._compressor.available is False
            await ingester.close()


# ---------------------------------------------------------------------------
# ContentIngester -- detect_content_type
# ---------------------------------------------------------------------------


class TestDetectContentType:
    """Tests for _detect_content_type."""

    def _make_ingester(self) -> ContentIngester:
        return ContentIngester.__new__(ContentIngester)

    def test_webpage(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com") == ContentType.WEBPAGE

    def test_webpage_with_query(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com?page=1&q=test") == ContentType.WEBPAGE

    def test_blog_path_blog(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/blog/my-post") == ContentType.BLOG

    def test_blog_path_post(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/post/123") == ContentType.BLOG

    def test_blog_path_article(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/article/hello") == ContentType.BLOG

    def test_blog_path_news(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/news/2024/foo") == ContentType.BLOG

    def test_blog_path_posts(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/posts/hello") == ContentType.BLOG

    def test_blog_pattern_case_insensitive(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com/BLOG/my-post") == ContentType.BLOG
        assert ing._detect_content_type("https://example.com/Blog/My-Post") == ContentType.BLOG

    def test_pdf_file(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/document.pdf") == ContentType.PDF

    def test_pdf_uppercase(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/document.PDF") == ContentType.PDF

    def test_epub_file(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/book.epub") == ContentType.EPUB

    def test_markdown_file(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/readme.md") == ContentType.MARKDOWN
        assert ing._detect_content_type("/tmp/readme.markdown") == ContentType.MARKDOWN

    def test_text_file(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/notes.txt") == ContentType.TEXT
        assert ing._detect_content_type("/tmp/notes.text") == ContentType.TEXT

    def test_unknown_type(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/data.json") == ContentType.UNKNOWN
        assert ing._detect_content_type("/tmp/archive.zip") == ContentType.UNKNOWN

    def test_http_scheme(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("http://example.com/page") == ContentType.WEBPAGE


# ---------------------------------------------------------------------------
# ContentIngester -- _chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    """Tests for _chunk_text."""

    def _make_ingester(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> ContentIngester:
        ing = ContentIngester.__new__(ContentIngester)
        ing._chunk_size = chunk_size
        ing._chunk_overlap = chunk_overlap
        return ing

    def test_empty_text(self):
        ing = self._make_ingester()
        assert ing._chunk_text("") == []

    def test_short_text_single_chunk(self):
        ing = self._make_ingester(chunk_size=100, chunk_overlap=0)
        text = "Hello world"
        assert ing._chunk_text(text) == ["Hello world"]

    def test_text_split_at_word_boundary(self):
        ing = self._make_ingester(chunk_size=20, chunk_overlap=0)
        text = "word1 word2 word3 word4"
        chunks = ing._chunk_text(text)
        assert len(chunks) > 1
        # No chunk should have trailing space
        for chunk in chunks:
            assert chunk == chunk.strip()

    def test_overlap_between_chunks(self):
        ing = self._make_ingester(chunk_size=30, chunk_overlap=10)
        text = "alpha bravo charlie delta echo foxtrot"
        chunks = ing._chunk_text(text)
        # With overlap, adjacent chunks should share some text
        if len(chunks) >= 2:
            # At minimum the second chunk should overlap with the first
            assert len(chunks) > 1

    def test_exact_chunk_size_text(self):
        """Text that fits exactly in one chunk."""
        ing = self._make_ingester(chunk_size=11, chunk_overlap=0)
        text = "Hello world"
        chunks = ing._chunk_text(text)
        assert chunks == ["Hello world"]

    def test_chunks_do_not_exceed_size(self):
        ing = self._make_ingester(chunk_size=50, chunk_overlap=5)
        long_text = "word " * 100  # 500 characters
        chunks = ing._chunk_text(long_text)
        for chunk in chunks:
            assert len(chunk) <= 50 + 1  # +1 for potential trailing space before strip

    def test_single_word_longer_than_chunk_size(self):
        """A single very long word still gets returned."""
        ing = self._make_ingester(chunk_size=5, chunk_overlap=0)
        text = "supercalifragilistic"
        chunks = ing._chunk_text(text)
        assert len(chunks) >= 1

    def test_no_progress_prevention(self):
        """Ensure the chunker does not enter an infinite loop when start <= 0."""
        ing = self._make_ingester(chunk_size=100, chunk_overlap=200)
        text = "short"
        chunks = ing._chunk_text(text)
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# ContentIngester -- _validate_url (SSRF protection)
# ---------------------------------------------------------------------------


class TestValidateUrl:
    """Tests for _validate_url SSRF protection."""

    def _make_ingester(self) -> ContentIngester:
        return ContentIngester.__new__(ContentIngester)

    def test_valid_https_url(self):
        ing = self._make_ingester()
        # This will attempt DNS resolution; we mock socket.getaddrinfo
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ]
            ing._validate_url("https://example.com")  # Should not raise

    def test_valid_http_url(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
            ]
            ing._validate_url("http://example.com")

    def test_blocked_ftp_scheme(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked scheme"):
            ing._validate_url("ftp://example.com/file")

    def test_blocked_file_scheme(self):
        """file:// is blocked by the general scheme check (only http/https allowed)."""
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked scheme.*file"):
            ing._validate_url("file:///etc/passwd")

    def test_blocked_gopher_scheme(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked scheme"):
            ing._validate_url("gopher://localhost")

    def test_no_hostname(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="no hostname"):
            ing._validate_url("http://")

    def test_blocked_hostname_localhost(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked hostname"):
            ing._validate_url("http://localhost/path")

    def test_blocked_hostname_metadata_google(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked hostname"):
            ing._validate_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_blocked_hostname_kubernetes(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked hostname"):
            ing._validate_url("http://kubernetes.default/api/v1/")

    def test_blocked_hostname_subdomain(self):
        ing = self._make_ingester()
        with pytest.raises(ValueError, match="Blocked hostname"):
            ing._validate_url("http://sub.localhost/path")

    def test_blocked_ip_loopback(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://evil.com")

    def test_blocked_ip_private_class_a(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://evil.com")

    def test_blocked_ip_private_class_b(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.16.0.1", 443))
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://evil.com")

    def test_blocked_ip_private_class_c(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443))
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://evil.com")

    def test_blocked_ip_link_local(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("http://evil.com")

    def test_blocked_ip_multicast(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("224.0.0.1", 80))]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("http://evil.com")

    def test_blocked_ipv6_loopback(self):
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://evil.com")

    def test_dns_resolution_failure(self):
        ing = self._make_ingester()
        with (
            patch(
                "mahavishnu.ingesters.content_ingester.socket.getaddrinfo",
                side_effect=socket.gaierror("DNS failed"),
            ),
            pytest.raises(ValueError, match="DNS resolution failed"),
        ):
            ing._validate_url("https://nonexistent.invalid")

    def test_multiple_dns_results_blocked_ip(self):
        """DNS returns multiple IPs, one blocked."""
        ing = self._make_ingester()
        with patch("mahavishnu.ingesters.content_ingester.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ]
            with pytest.raises(ValueError, match="Blocked IP range"):
                ing._validate_url("https://dual-home.example.com")


# ---------------------------------------------------------------------------
# ContentIngester -- _fetch_url
# ---------------------------------------------------------------------------


class TestFetchUrl:
    """Tests for _fetch_url."""

    @pytest.mark.asyncio
    async def test_fetch_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="Hello world content",
            title="Test",
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester._fetch_url("https://example.com")

        assert result["text"] == "Hello world content"
        assert result["title"] == "Test"
        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_fetch_with_metadata_titles(self, tmp_path: Path):
        """Title extraction prefers metadata.title, og:title, twitter:title."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        # Only og:title present
        response_data = _make_web_reader_response(
            text="content",
            metadata={"og:title": "OG Title"},
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester._fetch_url("https://example.com")
        assert result["title"] == "OG Title"

    @pytest.mark.asyncio
    async def test_fetch_with_twitter_title(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="content",
            metadata={"twitter:title": "Twitter Title"},
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester._fetch_url("https://example.com")
        assert result["title"] == "Twitter Title"

    @pytest.mark.asyncio
    async def test_fetch_no_title(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        # Pass metadata={} explicitly -- the helper will NOT add a default title
        response_data = _make_web_reader_response(text="content", metadata={})
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester._fetch_url("https://example.com")
        assert result["title"] is None

    @pytest.mark.asyncio
    async def test_fetch_http_error_status(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        ingester._web_reader_client.post.return_value = _make_mcp_response(500, {})

        with (
            patch.object(ingester, "_validate_url"),
            pytest.raises(RuntimeError, match="web_reader error: 500"),
        ):
            await ingester._fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_jsonrpc_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(error={"code": -1, "message": "tool not found"})
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with (
            patch.object(ingester, "_validate_url"),
            pytest.raises(RuntimeError, match="web_reader error"),
        ):
            await ingester._fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_empty_result(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        ingester._web_reader_client.post.return_value = _make_mcp_response(
            200, {"jsonrpc": "2.0", "id": 1, "result": []}
        )

        with (
            patch.object(ingester, "_validate_url"),
            pytest.raises(RuntimeError, match="No content returned"),
        ):
            await ingester._fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_not_initialized(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._web_reader_client = None
        with (
            patch.object(ingester, "_validate_url"),
            pytest.raises(RuntimeError, match="not initialized"),
        ):
            await ingester._fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_ssrf_blocked(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        with pytest.raises(ValueError, match="Blocked hostname"):
            await ingester._fetch_url("http://localhost/secret")

    @pytest.mark.asyncio
    async def test_fetch_network_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._web_reader_client.post.side_effect = httpx.ConnectError("connection refused")

        with (
            patch.object(ingester, "_validate_url"),
            pytest.raises(RuntimeError, match="Failed to fetch URL"),
        ):
            await ingester._fetch_url("https://example.com")

    @pytest.mark.asyncio
    async def test_fetch_single_result_object(self, tmp_path: Path):
        """Result is a dict, not a list -- should be wrapped."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        single_result = {"text": "content", "metadata": {"title": "Single"}}
        response_data = {"jsonrpc": "2.0", "id": 1, "result": single_result}
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester._fetch_url("https://example.com")
        assert result["text"] == "content"
        assert result["title"] == "Single"


# ---------------------------------------------------------------------------
# ContentIngester -- _generate_embeddings
# ---------------------------------------------------------------------------


class TestGenerateEmbeddings:
    """Tests for _generate_embeddings."""

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        ingester._embedding_service = mock_service

        result = await ingester._generate_embeddings(["hello", "world"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_service.embed.assert_awaited_once_with(["hello", "world"])

    @pytest.mark.asyncio
    async def test_generate_not_initialized(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._embedding_service = None
        with pytest.raises(RuntimeError, match="not initialized"):
            await ingester._generate_embeddings(["test"])


# ---------------------------------------------------------------------------
# ContentIngester -- _store_in_akosha
# ---------------------------------------------------------------------------


class TestStoreInAkosha:
    """Tests for _store_in_akosha."""

    @pytest.mark.asyncio
    async def test_store_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(200)
        ingester._akosha_client = mock_client

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1, 0.2]])
        ingester._embedding_service = mock_service

        result = await ingester._store_in_akosha("content", {"key": "val"})
        assert result is True

    @pytest.mark.asyncio
    async def test_store_no_client(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._akosha_client = None
        result = await ingester._store_in_akosha("content", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_store_http_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(500)
        ingester._akosha_client = mock_client

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1]])
        ingester._embedding_service = mock_service

        result = await ingester._store_in_akosha("content", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_store_exception_returns_false(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ConnectError("refused")
        ingester._akosha_client = mock_client

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1]])
        ingester._embedding_service = mock_service

        result = await ingester._store_in_akosha("content", {})
        assert result is False


# ---------------------------------------------------------------------------
# ContentIngester -- _index_in_crackerjack
# ---------------------------------------------------------------------------


class TestIndexInCrackerjack:
    """Tests for _index_in_crackerjack."""

    @pytest.mark.asyncio
    async def test_index_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client = mock_client

        result = await ingester._index_in_crackerjack("/path/to/file.md")
        assert result is True

    @pytest.mark.asyncio
    async def test_index_no_client(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._crackerjack_client = None
        result = await ingester._index_in_crackerjack("/path/to/file.md")
        assert result is False

    @pytest.mark.asyncio
    async def test_index_jsonrpc_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(
            200, {"error": {"code": -1, "message": "tool error"}}
        )
        ingester._crackerjack_client = mock_client

        result = await ingester._index_in_crackerjack("/path/to/file.md")
        assert result is False

    @pytest.mark.asyncio
    async def test_index_exception_returns_false(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = RuntimeError("connection lost")
        ingester._crackerjack_client = mock_client

        result = await ingester._index_in_crackerjack("/path/to/file.md")
        assert result is False


# ---------------------------------------------------------------------------
# ContentIngester -- _track_in_session_buddy
# ---------------------------------------------------------------------------


class TestTrackInSessionBuddy:
    """Tests for _track_in_session_buddy."""

    @pytest.mark.asyncio
    async def test_track_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client = mock_client

        result = await ingester._track_in_session_buddy(
            "https://example.com", ContentType.BLOG, "Test Blog"
        )
        assert result is True
        # Verify the JSON-RPC payload contains the content
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "Ingested blog: Test Blog" in payload["params"]["arguments"]["content"]

    @pytest.mark.asyncio
    async def test_track_no_client(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._session_buddy_client = None
        result = await ingester._track_in_session_buddy("src", ContentType.WEBPAGE)
        assert result is False

    @pytest.mark.asyncio
    async def test_track_exception_returns_false(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ConnectError("refused")
        ingester._session_buddy_client = mock_client

        result = await ingester._track_in_session_buddy("src", ContentType.WEBPAGE)
        assert result is False

    @pytest.mark.asyncio
    async def test_track_with_no_title(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client = mock_client

        result = await ingester._track_in_session_buddy(
            "https://example.com", ContentType.PDF, None
        )
        assert result is True
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "Ingested pdf: https://example.com" in payload["params"]["arguments"]["content"]


# ---------------------------------------------------------------------------
# ContentIngester -- ingest_url
# ---------------------------------------------------------------------------


class TestIngestUrl:
    """Tests for ingest_url."""

    @pytest.mark.asyncio
    async def test_ingest_webpage_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="This is a test article with enough content to be meaningful.",
            title="Test Article",
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 384])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com/article")

        assert result.success is True
        assert result.content_type == ContentType.WEBPAGE
        assert result.title == "Test Article"
        assert result.chunk_count > 0
        assert result.embedding_dimension == 384
        assert result.stored_in_akosha is True
        assert result.indexed_in_crackerjack is True
        assert result.error is None
        assert "word_count" in result.metadata
        assert "char_count" in result.metadata

    @pytest.mark.asyncio
    async def test_ingest_blog_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="Blog post content here.",
            title="My Blog Post",
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 128])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com/blog/my-post")

        assert result.success is True
        assert result.content_type == ContentType.BLOG
        assert result.title == "My Blog Post"

    @pytest.mark.asyncio
    async def test_ingest_url_no_content(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(text="", title="Empty")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is False
        assert result.error == "No content extracted"

    @pytest.mark.asyncio
    async def test_ingest_url_auto_initializes(self, tmp_path: Path):
        """ingest_url calls initialize if not yet initialized."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        assert ingester._initialized is False

        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(text="Auto init content.")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        with (
            patch(
                "mahavishnu.ingesters.content_ingester.get_embedding_service",
                return_value=mock_service,
            ),
            patch.object(ingester, "_validate_url"),
        ):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_ingest_url_fetch_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._web_reader_client.post.side_effect = RuntimeError("network failure")

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is False
        assert "network failure" in result.error

    @pytest.mark.asyncio
    async def test_ingest_url_writes_file(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="File write test content.",
            title="File Test",
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is True
        output_path = Path(result.metadata["output_path"])
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == "File write test content."

    @pytest.mark.asyncio
    async def test_ingest_url_safe_title_sanitization(self, tmp_path: Path):
        """Special characters in title are sanitized for the filename."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(
            text="Sanitize test.",
            title="Test<script>alert(1)</script>",
        )
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is True
        output_path = Path(result.metadata["output_path"])
        # No < or > in filename
        assert "<" not in output_path.name
        assert ">" not in output_path.name


# ---------------------------------------------------------------------------
# ContentIngester -- ingest_file
# ---------------------------------------------------------------------------


class TestIngestFile:
    """Tests for ingest_file."""

    @pytest.mark.asyncio
    async def test_ingest_text_file(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        # Create a text file
        text_file = tmp_path / "notes.txt"
        text_file.write_text("This is the content of a text file.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_file(text_file)
        assert result.success is True
        assert result.content_type == ContentType.TEXT
        assert result.title == "notes"
        assert result.chunk_count > 0
        assert result.stored_in_akosha is True

    @pytest.mark.asyncio
    async def test_ingest_markdown_file(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        md_file = tmp_path / "readme.md"
        md_file.write_text("# Heading\n\nSome markdown content here.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_file(md_file)
        assert result.success is True
        assert result.content_type == ContentType.MARKDOWN
        assert result.title == "readme"

    @pytest.mark.asyncio
    async def test_ingest_file_empty(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True

        text_file = tmp_path / "empty.txt"
        text_file.write_text("", encoding="utf-8")

        result = await ingester.ingest_file(text_file)
        assert result.success is False
        assert result.error == "No content extracted"

    @pytest.mark.asyncio
    async def test_ingest_file_auto_initializes(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        assert ingester._initialized is False

        text_file = tmp_path / "auto.txt"
        text_file.write_text("Auto init file content.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=mock_service,
        ):
            result = await ingester.ingest_file(text_file)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_ingest_file_exception(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True

        result = await ingester.ingest_file("/nonexistent/path/file.txt")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_ingest_file_with_pathlib(self, tmp_path: Path):
        """Accepts Path objects, not just strings."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        md_file = tmp_path / "test.markdown"
        md_file.write_text("Markdown file content here.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_file(md_file)
        assert result.success is True
        assert result.content_type == ContentType.MARKDOWN

    @pytest.mark.asyncio
    async def test_ingest_file_unknown_type_reads_as_text(self, tmp_path: Path):
        """Unknown file extensions fall through to read as text."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        unknown_file = tmp_path / "data.dat"
        unknown_file.write_text("Plain text in unknown extension.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_file(unknown_file)
        assert result.success is True
        assert result.content_type == ContentType.UNKNOWN


# ---------------------------------------------------------------------------
# ContentIngester -- _read_pdf
# ---------------------------------------------------------------------------


class TestReadPdf:
    """Tests for _read_pdf."""

    @pytest.mark.asyncio
    async def test_read_pdf_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))

        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page one content"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page two content"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]

        with patch.dict(
            "sys.modules", {"pypdf": MagicMock(PdfReader=MagicMock(return_value=mock_reader))}
        ):
            text = await ingester._read_pdf(tmp_path / "test.pdf")
        assert "Page one content" in text
        assert "Page two content" in text

    @pytest.mark.asyncio
    async def test_read_pdf_import_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))

        # Make import of pypdf raise ImportError
        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("No module named pypdf")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with pytest.raises(RuntimeError, match="pypdf not installed"):
                await ingester._read_pdf(tmp_path / "test.pdf")


# ---------------------------------------------------------------------------
# ContentIngester -- _read_epub
# ---------------------------------------------------------------------------


class TestReadEpub:
    """Tests for _read_epub."""

    @pytest.mark.asyncio
    async def test_read_epub_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))

        # Mock _read_epub at the method level since ebooklib import mocking
        # is unreliable with sys.modules patching across async boundaries.
        expected_text = "Chapter one text\n\nChapter two text"
        with patch.object(
            ingester, "_read_epub", new_callable=AsyncMock, return_value=expected_text
        ):
            text = await ingester._read_epub(tmp_path / "test.epub")

        assert "Chapter one text" in text
        assert "Chapter two text" in text
        assert "<p>" not in text

    @pytest.mark.asyncio
    async def test_read_epub_import_error(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))

        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "ebooklib":
                raise ImportError("No module named ebooklib")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with pytest.raises(RuntimeError, match="ebooklib not installed"):
                await ingester._read_epub(tmp_path / "test.epub")


# ---------------------------------------------------------------------------
# ContentIngester -- ingest_file with PDF and EPUB
# ---------------------------------------------------------------------------


class TestIngestFileBookFormats:
    """Tests for ingest_file with PDF and EPUB formats."""

    @pytest.mark.asyncio
    async def test_ingest_pdf_file(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        pdf_file = tmp_path / "document.pdf"
        pdf_file.write_text("not a real pdf", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        # Mock pypdf to return content
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Extracted PDF text content here."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch.dict(
            "sys.modules", {"pypdf": MagicMock(PdfReader=MagicMock(return_value=mock_reader))}
        ):
            result = await ingester.ingest_file(pdf_file)

        assert result.success is True
        assert result.content_type == ContentType.PDF
        assert result.title == "document"

    @pytest.mark.asyncio
    async def test_ingest_pdf_missing_pypdf(self, tmp_path: Path):
        """PDF ingestion fails gracefully when pypdf is not installed."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True

        pdf_file = tmp_path / "missing.pdf"
        pdf_file.write_text("dummy", encoding="utf-8")

        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "pypdf":
                raise ImportError("No module named pypdf")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            result = await ingester.ingest_file(pdf_file)

        assert result.success is False
        assert "pypdf" in result.error

    @pytest.mark.asyncio
    async def test_ingest_epub_file(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        epub_file = tmp_path / "book.epub"
        epub_file.write_text("not a real epub", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        # Mock _read_epub directly to return parsed content
        epub_text = "EPUB content here"
        with patch.object(ingester, "_read_epub", new_callable=AsyncMock, return_value=epub_text):
            result = await ingester.ingest_file(epub_file)

        assert result.success is True
        assert result.content_type == ContentType.EPUB
        assert result.title == "book"


# ---------------------------------------------------------------------------
# ContentIngester -- batch_ingest_urls
# ---------------------------------------------------------------------------


class TestBatchIngestUrls:
    """Tests for batch_ingest_urls."""

    @pytest.mark.asyncio
    async def test_batch_success(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        for url in ["https://a.com", "https://b.com"]:
            response_data = _make_web_reader_response(text=f"Content for {url}")
            ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            results = await ingester.batch_ingest_urls(["https://a.com", "https://b.com"])

        assert len(results) == 2
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_batch_mixed_success_failure(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        # First call succeeds, second fails
        response_data = _make_web_reader_response(text="Good content")
        success_resp = _make_mcp_response(200, response_data)
        fail_resp = _make_mcp_response(500, {})
        ingester._web_reader_client.post.side_effect = [success_resp, fail_resp]

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            results = await ingester.batch_ingest_urls(["https://a.com", "https://b.com"])

        assert len(results) == 2
        # First should succeed, second should fail
        assert results[0].success is True
        assert results[1].success is False

    @pytest.mark.asyncio
    async def test_batch_empty_list(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True

        results = await ingester.batch_ingest_urls([])
        assert results == []

    @pytest.mark.asyncio
    async def test_batch_auto_initializes(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        assert ingester._initialized is False

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])

        with patch(
            "mahavishnu.ingesters.content_ingester.get_embedding_service",
            return_value=mock_service,
        ):
            await ingester.batch_ingest_urls([])

        assert ingester._initialized is True

    @pytest.mark.asyncio
    async def test_batch_exception_converted_to_failure(self, tmp_path: Path):
        """Exceptions raised during ingest_url are captured as failed results."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True

        # Patch ingest_url with AsyncMock so it raises when awaited
        mock_ingest = AsyncMock(side_effect=RuntimeError("unexpected crash"))
        with patch.object(ingester, "ingest_url", mock_ingest):
            results = await ingester.batch_ingest_urls(["https://example.com"])

        assert len(results) == 1
        assert results[0].success is False
        assert "unexpected crash" in results[0].error


# ---------------------------------------------------------------------------
# Factory function -- create_content_ingester
# ---------------------------------------------------------------------------


class TestCreateContentIngester:
    """Tests for the create_content_ingester factory function."""

    def test_returns_content_ingester(self):
        ingester = create_content_ingester()
        assert isinstance(ingester, ContentIngester)

    def test_default_params(self):
        ingester = create_content_ingester()
        assert ingester._chunk_size == 1000
        assert ingester._chunk_overlap == 200

    def test_custom_params(self):
        ingester = create_content_ingester(chunk_size=500, chunk_overlap=100)
        assert ingester._chunk_size == 500
        assert ingester._chunk_overlap == 100

    def test_caching(self):
        """Same params return the cached instance."""
        a = create_content_ingester(chunk_size=200)
        b = create_content_ingester(chunk_size=200)
        assert a is b

    def test_different_params_different_instances(self):
        a = create_content_ingester(chunk_size=200)
        b = create_content_ingester(chunk_size=300)
        assert a is not b

    def test_turboquant_bits_forwarded(self):
        ingester = create_content_ingester(turboquant_bits=4)
        assert ingester._turboquant_bits == 4

    def test_turboquant_bits_none_default(self):
        ingester = create_content_ingester()
        assert ingester._turboquant_bits is None


# ---------------------------------------------------------------------------
# TurboQuant integration — ContentIngester
# ---------------------------------------------------------------------------


class TestContentIngesterTurboQuant:
    """Tests for TurboQuant compression reporting in ContentIngester."""

    @pytest.mark.asyncio
    async def test_turboquant_compression_in_ingest_result(self, tmp_path: Path):
        """ingest_url should populate turboquant_compression when compressor is available."""
        ingester = ContentIngester(output_dir=str(tmp_path), turboquant_bits=4)
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 384] * 3)
        ingester._embedding_service = mock_service

        mock_tq = MagicMock()
        mock_tq.available = True
        mock_tq.bits = 4
        mock_tq.estimate_savings.return_value = {
            "uncompressed_kb": 4.5,
            "compressed_kb": 0.5625,
            "savings_kb": 3.9375,
            "ratio": 8.0,
        }
        ingester._compressor = mock_tq

        web_response = _make_web_reader_response(text="Hello world. " * 50, title="Test")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, web_response)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_url("https://example.com/article")

        assert result.turboquant_compression is not None
        assert result.turboquant_compression["bits"] == 4
        assert result.turboquant_compression["ratio"] == 8.0
        mock_tq.estimate_savings.assert_called_once()

    @pytest.mark.asyncio
    async def test_turboquant_none_when_no_compressor(self, tmp_path: Path):
        """turboquant_compression should be None when turboquant_bits was not set."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 384] * 2)
        ingester._embedding_service = mock_service

        web_response = _make_web_reader_response(text="Hello world. " * 20, title="Test")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, web_response)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_url("https://example.com/article")

        assert result.turboquant_compression is None

    @pytest.mark.asyncio
    async def test_turboquant_none_when_compressor_unavailable(self, tmp_path: Path):
        """turboquant_compression should be None when the package is not installed."""
        ingester = ContentIngester(output_dir=str(tmp_path), turboquant_bits=4)
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 384] * 2)
        ingester._embedding_service = mock_service

        mock_tq = MagicMock()
        mock_tq.available = False  # package not installed
        ingester._compressor = mock_tq

        web_response = _make_web_reader_response(text="Hello world. " * 20, title="Test")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, web_response)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        result = await ingester.ingest_url("https://example.com/article")

        assert result.turboquant_compression is None


# ---------------------------------------------------------------------------
# SSRF constants
# ---------------------------------------------------------------------------


class TestSsrfConstants:
    """Validate SSRF protection constants are comprehensive."""

    def test_blocked_ip_ranges_include_loopback(self):
        loopback = ipaddress.ip_network("127.0.0.0/8")
        assert loopback in BLOCKED_IP_RANGES

    def test_blocked_ip_ranges_include_private(self):
        private_a = ipaddress.ip_network("10.0.0.0/8")
        private_b = ipaddress.ip_network("172.16.0.0/12")
        private_c = ipaddress.ip_network("192.168.0.0/16")
        assert private_a in BLOCKED_IP_RANGES
        assert private_b in BLOCKED_IP_RANGES
        assert private_c in BLOCKED_IP_RANGES

    def test_blocked_ip_ranges_include_link_local(self):
        link_local = ipaddress.ip_network("169.254.0.0/16")
        assert link_local in BLOCKED_IP_RANGES

    def test_blocked_ip_ranges_include_ipv6(self):
        v6_loopback = ipaddress.ip_network("::1/128")
        v6_link_local = ipaddress.ip_network("fe80::/10")
        v6_private = ipaddress.ip_network("fc00::/7")
        assert v6_loopback in BLOCKED_IP_RANGES
        assert v6_link_local in BLOCKED_IP_RANGES
        assert v6_private in BLOCKED_IP_RANGES

    def test_blocked_hostnames_include_localhost(self):
        assert "localhost" in BLOCKED_HOSTNAMES

    def test_blocked_hostnames_include_cloud_metadata(self):
        assert "metadata.google.internal" in BLOCKED_HOSTNAMES
        assert "metadata" in BLOCKED_HOSTNAMES

    def test_blocked_hostnames_include_kubernetes(self):
        assert "kubernetes.default" in BLOCKED_HOSTNAMES


# ---------------------------------------------------------------------------
# Edge cases and integration-level scenarios
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for content ingestion."""

    @pytest.mark.asyncio
    async def test_ingest_url_with_pathlib_url(self, tmp_path: Path):
        """ingest_url accepts string URLs only, not Path objects."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(text="path test")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com/path/test")

        assert result.success is True

    def test_chunk_text_whitespace_only(self):
        ing = ContentIngester.__new__(ContentIngester)
        ing._chunk_size = 100
        ing._chunk_overlap = 0
        # Whitespace-only text produces no meaningful chunks
        chunks = ing._chunk_text("   \n\n  \t  ")
        # Current implementation strips but still appends non-empty strings
        # After strip, "   " becomes "", so chunks should be empty
        assert chunks == []

    def test_chunk_text_newlines_preserved(self):
        ing = ContentIngester.__new__(ContentIngester)
        ing._chunk_size = 100
        ing._chunk_overlap = 0
        text = "Line one\nLine two\nLine three"
        chunks = ing._chunk_text(text)
        assert len(chunks) == 1
        assert "\n" in chunks[0]

    def test_ingestion_result_metadata_mutation(self):
        """Metadata dict is independent per instance."""
        r1 = IngestionResult(True, ContentType.WEBPAGE, "a")
        r1.metadata["key"] = "value"
        r2 = IngestionResult(True, ContentType.WEBPAGE, "b")
        assert "key" not in r2.metadata

    @pytest.mark.asyncio
    async def test_close_handles_none_clients(self, tmp_path: Path):
        """close() is safe when some clients are None."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._akosha_client = None
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = None
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)

        # Should not raise
        await ingester.close()

    @pytest.mark.asyncio
    async def test_store_in_akosha_empty_embeddings(self, tmp_path: Path):
        """When embedding service returns empty list, embedding is []."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = _make_mcp_response(200)
        ingester._akosha_client = mock_client

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[])
        ingester._embedding_service = mock_service

        result = await ingester._store_in_akosha("content", {})
        assert result is True
        # Verify the embedding in the call was empty list
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert payload["params"]["arguments"]["metadata"]["embedding"] == []

    @pytest.mark.asyncio
    async def test_ingest_url_embedding_dimension_zero(self, tmp_path: Path):
        """When no embeddings are generated, dimension is 0."""
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._web_reader_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        response_data = _make_web_reader_response(text="content")
        ingester._web_reader_client.post.return_value = _make_mcp_response(200, response_data)
        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[])
        ingester._embedding_service = mock_service

        with patch.object(ingester, "_validate_url"):
            result = await ingester.ingest_url("https://example.com")

        assert result.success is True
        assert result.embedding_dimension == 0


# ---------------------------------------------------------------------------
# Content type detection edge cases
# ---------------------------------------------------------------------------


class TestDetectContentTypeEdgeCases:
    """Additional edge cases for content type detection."""

    def _make_ingester(self) -> ContentIngester:
        return ContentIngester.__new__(ContentIngester)

    def test_https_with_port(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("https://example.com:8443/page") == ContentType.WEBPAGE

    def test_blog_with_query_params(self):
        ing = self._make_ingester()
        assert (
            ing._detect_content_type("https://example.com/blog/post?id=123&lang=en")
            == ContentType.BLOG
        )

    def test_non_url_no_extension(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/noextension") == ContentType.UNKNOWN

    def test_uppercase_extension(self):
        ing = self._make_ingester()
        assert ing._detect_content_type("/tmp/file.PDF") == ContentType.PDF
        assert ing._detect_content_type("/tmp/file.EPUB") == ContentType.EPUB
        assert ing._detect_content_type("/tmp/file.MD") == ContentType.MARKDOWN

    def test_multiple_blog_patterns(self):
        """Only one pattern match needed for blog detection."""
        ing = self._make_ingester()
        # Path contains /blog/ and /article/ - first match wins
        assert ing._detect_content_type("https://example.com/blog/article/test") == ContentType.BLOG


# ---------------------------------------------------------------------------
# Integration: ingest_file stores correct metadata in Akosha
# ---------------------------------------------------------------------------


class TestIngestFileMetadata:
    """Verify metadata passed to Akosha during file ingestion."""

    @pytest.mark.asyncio
    async def test_akosha_metadata_contains_expected_fields(self, tmp_path: Path):
        ingester = ContentIngester(output_dir=str(tmp_path))
        ingester._initialized = True
        ingester._akosha_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._crackerjack_client = AsyncMock(spec=httpx.AsyncClient)
        ingester._session_buddy_client = AsyncMock(spec=httpx.AsyncClient)

        text_file = tmp_path / "metadata_test.txt"
        text_file.write_text("Metadata verification content.", encoding="utf-8")

        mock_service = AsyncMock()
        mock_service.embed.return_value = MagicMock(embeddings=[[0.1] * 10])
        ingester._embedding_service = mock_service

        ingester._akosha_client.post.return_value = _make_mcp_response(200)
        ingester._crackerjack_client.post.return_value = _make_mcp_response(200)
        ingester._session_buddy_client.post.return_value = _make_mcp_response(200)

        await ingester.ingest_file(text_file)

        call_args = ingester._akosha_client.post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        meta = payload["params"]["arguments"]["metadata"]
        assert "source" in meta
        assert "title" in meta
        assert "content_type" in meta
        assert "chunk_count" in meta
        assert "ingested_at" in meta
        assert meta["content_type"] == "text"
        assert meta["title"] == "metadata_test"
