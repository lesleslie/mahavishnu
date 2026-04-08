"""Unit tests for hybrid search engine.

This module tests the HybridSearchEngine implementation:
- Configuration validation
- Search operations (hybrid and lexical-only)
- Document indexing and deletion
- Error handling and edge cases
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from mahavishnu.core.search import (
    HybridSearchConfig,
    HybridSearchEngine,
    HybridSearchResult,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_pool():
    """Mock asyncpg connection pool."""
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=AsyncMock())
    return pool


@pytest.fixture
def mock_embedding_service():
    """Mock embedding service."""
    service = AsyncMock()
    service.embed = AsyncMock()
    return service


@pytest.fixture
def search_config():
    """Default search configuration."""
    return HybridSearchConfig(
        semantic_weight=0.7,
        lexical_weight=0.3,
        default_limit=20,
        min_score=0.5,
    )


# =============================================================================
# Configuration Tests
# =============================================================================


class TestHybridSearchConfig:
    """Test HybridSearchConfig validation."""

    def test_default_values(self):
        """Test default configuration values."""
        config = HybridSearchConfig()

        assert config.semantic_weight == 0.7
        assert config.lexical_weight == 0.3
        assert config.default_limit == 20
        assert config.min_score == 0.5

    def test_weight_normalization(self):
        """Test that weights are normalized to sum to 1.0."""
        # Weights that don't sum to 1.0 should be normalized
        config = HybridSearchConfig(semantic_weight=0.8, lexical_weight=0.4)

        # After normalization: 0.8 / 1.2 = 0.667, 0.4 / 1.2 = 0.333
        assert abs(config.semantic_weight - 0.667) < 0.01
        assert abs(config.lexical_weight - 0.333) < 0.01

    def test_invalid_semantic_weight(self):
        """Test that invalid semantic weight raises error."""
        with pytest.raises(ValueError, match="semantic_weight must be between 0.0 and 1.0"):
            HybridSearchConfig(semantic_weight=1.5)

    def test_invalid_lexical_weight(self):
        """Test that invalid lexical weight raises error."""
        with pytest.raises(ValueError, match="lexical_weight must be between 0.0 and 1.0"):
            HybridSearchConfig(lexical_weight=-0.1)

    def test_invalid_min_score(self):
        """Test that invalid min_score raises error."""
        with pytest.raises(ValueError, match="min_score must be between 0.0 and 1.0"):
            HybridSearchConfig(min_score=1.5)


# =============================================================================
# HybridSearchResult Tests
# =============================================================================


class TestHybridSearchResult:
    """Test HybridSearchResult model."""

    def test_result_creation(self):
        """Test creating a search result."""
        doc_id = uuid4()
        result = HybridSearchResult(
            id=doc_id,
            source_type="document",
            title="Test Document",
            content="This is test content",
            semantic_score=0.85,
            lexical_score=0.72,
            combined_score=0.80,
            metadata={"category": "test"},
            repository="mahavishnu",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert result.id == doc_id
        assert result.source_type == "document"
        assert result.title == "Test Document"
        assert result.semantic_score == 0.85
        assert result.lexical_score == 0.72
        assert result.combined_score == 0.80

    def test_result_serialization(self):
        """Test result serialization to dict."""
        doc_id = uuid4()
        result = HybridSearchResult(
            id=doc_id,
            source_type="task",
            title=None,
            content="Task content",
            semantic_score=0.9,
            lexical_score=0.5,
            combined_score=0.78,
            metadata={},
            repository=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        result_dict = result.model_dump()
        assert "id" in result_dict
        assert result_dict["source_type"] == "task"
        assert result_dict["title"] is None


# =============================================================================
# HybridSearchEngine Tests
# =============================================================================


class TestHybridSearchEngine:
    """Test HybridSearchEngine functionality."""

    @pytest.mark.asyncio
    async def test_search_empty_query(self, mock_pool, search_config):
        """Test that empty query raises error."""
        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
        )

        with pytest.raises(ValueError, match="Query cannot be empty"):
            await engine.search("")

    @pytest.mark.asyncio
    async def test_search_with_embedding(
        self, mock_pool, mock_embedding_service, search_config
    ):
        """Test hybrid search with embedding."""
        # Mock embedding service
        mock_embedding_service.embed.return_value = MagicMock(
            embeddings=[[0.1] * 384],  # 384-dimensional embedding
            model="test-model",
            dimension=384,
        )

        # Mock database results
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.acquire.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = MagicMock(return_value=None)

        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
            embedding_service=mock_embedding_service,
        )

        results = await engine.search("test query", repository="mahavishnu", limit=10)

        assert isinstance(results, list)
        # Results should be empty since we mocked empty fetch
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_lexical_fallback(
        self, mock_pool, mock_embedding_service, search_config
    ):
        """Test lexical-only fallback when embedding fails."""
        # Mock embedding failure
        mock_embedding_service.embed.side_effect = Exception("Embedding failed")

        # Mock database results
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_pool.acquire.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = MagicMock(return_value=None)

        config = HybridSearchConfig(enable_lexical_fallback=True)
        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=config,
            embedding_service=mock_embedding_service,
        )

        # Should not raise error, should fall back to lexical search
        results = await engine.search("test query")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_index_document(self, mock_pool, mock_embedding_service, search_config):
        """Test document indexing."""
        doc_id = uuid4()

        # Mock embedding service
        mock_embedding_service.embed.return_value = MagicMock(
            embeddings=[[0.1] * 384],
            model="test-model",
            dimension=384,
        )

        # Mock database connection
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 1")
        mock_conn.transaction = MagicMock(return_value=AsyncMock())
        mock_conn.transaction.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_conn.transaction.return_value.__aexit__ = MagicMock(return_value=None)

        mock_pool.acquire.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = MagicMock(return_value=None)

        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
            embedding_service=mock_embedding_service,
        )

        # Should not raise error
        await engine.index_document(
            doc_id=doc_id,
            title="Test Document",
            content="This is test content for indexing",
            metadata={"category": "test"},
            repository="mahavishnu",
        )

        # Verify execute was called
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_index_document_empty_content(
        self, mock_pool, mock_embedding_service, search_config
    ):
        """Test that indexing with empty content raises error."""
        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
            embedding_service=mock_embedding_service,
        )

        with pytest.raises(ValueError, match="Content cannot be empty"):
            await engine.index_document(
                doc_id=uuid4(),
                title="Test",
                content="",
                metadata={},
            )

    @pytest.mark.asyncio
    async def test_delete_document(self, mock_pool, search_config):
        """Test document deletion."""
        doc_id = uuid4()

        # Mock database connection
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")
        mock_pool.acquire.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = MagicMock(return_value=None)

        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
        )

        deleted = await engine.delete_document(doc_id)

        assert deleted is True
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_delete_document_not_found(self, mock_pool, search_config):
        """Test deleting non-existent document."""
        doc_id = uuid4()

        # Mock database connection
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 0")
        mock_pool.acquire.return_value.__aenter__ = MagicMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = MagicMock(return_value=None)

        engine = HybridSearchEngine(
            connection_pool=mock_pool,
            config=search_config,
        )

        deleted = await engine.delete_document(doc_id)

        assert deleted is False


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestHybridSearchIntegration:
    """Integration tests for hybrid search (requires database)."""

    @pytest.mark.asyncio
    async def test_full_search_workflow(self):
        """Test complete search workflow with real database.

        This test requires:
        - PostgreSQL database with pgvector extension
        - search.documents and search.document_embeddings tables
        - Database connection configured via environment variables
        """
        # Skip if no database available
        pytest.skip("Requires PostgreSQL database with pgvector")

        # This would test the actual search workflow:
        # 1. Index a document
        # 2. Search for it
        # 3. Verify results
        # 4. Delete document
        # 5. Verify deletion
