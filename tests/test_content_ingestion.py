"""Test content ingestion pipeline."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.ingesters import ContentIngester, ContentType


@pytest.mark.unit
async def test_content_ingester_initialization():
    """Test that ingester initializes correctly."""
    ingester = ContentIngester()
    await ingester.initialize()

    assert ingester._initialized is True
    assert ingester._embedding_service is not None
    assert ingester._akosha_client is not None

    await ingester.close()


@pytest.mark.unit
def test_content_type_detection():
    """Test content type detection from URLs and files."""
    ingester = ContentIngester()

    # Web content
    assert ingester._detect_content_type("https://example.com") == ContentType.WEBPAGE
    assert (
        ingester._detect_content_type("https://blog.example.com/post/how-to-build")
        == ContentType.BLOG
    )

    # Files
    assert ingester._detect_content_type("document.pdf") == ContentType.PDF
    assert ingester._detect_content_type("ebook.epub") == ContentType.EPUB
    assert ingester._detect_content_type("README.md") == ContentType.MARKDOWN
    assert ingester._detect_content_type("notes.txt") == ContentType.TEXT


@pytest.mark.unit
def test_text_chunking():
    """Test text chunking with overlap."""
    ingester = ContentIngester(
        chunk_size=100,
        chunk_overlap=20,
    )

    text = "a" * 200  # 200 characters
    chunks = ingester._chunk_text(text)

    # Should create multiple chunks with overlap
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert all(len(chunk) > 0 for chunk in chunks)


@pytest.mark.unit
async def test_ingestion_result_to_dict():
    """Test IngestionResult serialization."""
    from mahavishnu.ingesters.content_ingester import IngestionResult

    result = IngestionResult(
        success=True,
        content_type=ContentType.BLOG,
        source="https://example.com",
        title="Test Post",
        chunk_count=5,
        embedding_dimension=384,
        stored_in_akosha=True,
        indexed_in_crackerjack=True,
        metadata={"word_count": 1000},
    )

    data = result.to_dict()

    assert data["success"] is True
    assert data["content_type"] == "blog"
    assert data["title"] == "Test Post"
    assert data["chunk_count"] == 5
    assert data["metadata"]["word_count"] == 1000


@pytest.mark.integration
async def test_ingest_url_mocked():
    """Test URL ingestion with mocked MCP servers."""
    ingester = ContentIngester()

    # Mock HTTP clients
    ingester._web_reader_client = AsyncMock()
    ingester._akosha_client = AsyncMock()
    ingester._crackerjack_client = AsyncMock()
    ingester._session_buddy_client = AsyncMock()

    # Mock successful responses
    async def mock_post(*args, **kwargs):
        response = MagicMock()
        response.status_code = 200

        if "web_reader" in str(args[0]):
            response.json.return_value = {
                "result": [{
                    "text": "Test blog content",
                    "metadata": {"title": "Test Blog Post"},
                }]
            }
        else:
            response.json.return_value = {}

        return response

    ingester._web_reader_client.post = mock_post
    ingester._akosha_client.post = mock_post
    ingester._crackerjack_client.post = mock_post
    ingester._session_buddy_client.post = mock_post

    await ingester.initialize()

    result = await ingester.ingest_url("https://example.com/blog")

    assert result.success is True
    assert result.title == "Test Blog Post"

    await ingester.close()


@pytest.mark.property
@given(st.text(min_size=0, max_size=5000))
def test_chunking_property(text):
    """Property-based test for chunking correctness."""
    ingester = ContentIngester(
        chunk_size=500,
        chunk_overlap=50,
    )

    chunks = ingester._chunk_text(text)

    if text:
        # All chunks should be non-empty
        assert all(chunk.strip() for chunk in chunks)

        # Chunks shouldn't exceed max size (except possibly last one)
        assert all(len(chunk) <= 500 for chunk in chunks[:-1]) if len(chunks) > 1 else True

        # Total content should be preserved (minus overlap)
        total = "".join(chunks)
        # Account for overlap in chunks
        assert len(total) >= len(text) * 0.7  # At least 70% preserved
    else:
        assert chunks == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
