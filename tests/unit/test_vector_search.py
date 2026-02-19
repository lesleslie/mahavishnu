"""Tests for Vector Search Module.

Tests cover:
- Vector storage operations
- Search functionality (vector, FTS, hybrid)
- Similarity calculations
- Index management
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from mahavishnu.core.vector_search import (
    VectorStore,
    VectorSearch,
    VectorIndex,
    TaskSimilarity,
    SearchQuery,
    SearchResult,
    SearchType,
    VectorSearchError,
)


class TestSearchQuery:
    """Test search query model."""

    def test_valid_query(self) -> None:
        """Test creating valid query."""
        query = SearchQuery(query="test search")
        assert query.query == "test search"
        assert query.limit == 10
        assert query.threshold == 0.7
        assert query.search_type == SearchType.HYBRID

    def test_custom_params(self) -> None:
        """Test query with custom parameters."""
        query = SearchQuery(
            query="custom",
            repository="mahavishnu",
            limit=50,
            threshold=0.8,
            search_type=SearchType.VECTOR,
            include_content=True,
        )
        assert query.repository == "mahavishnu"
        assert query.limit == 50
        assert query.threshold == 0.8
        assert query.search_type == SearchType.VECTOR
        assert query.include_content is True

    def test_query_validation_min_length(self) -> None:
        """Test query validation rejects empty."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchQuery(query="")

    def test_query_validation_limit_range(self) -> None:
        """Test query validation rejects invalid limit."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=0)

        with pytest.raises(ValidationError):
            SearchQuery(query="test", limit=101)

    def test_query_validation_threshold_range(self) -> None:
        """Test query validation rejects invalid threshold."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SearchQuery(query="test", threshold=-0.1)

        with pytest.raises(ValidationError):
            SearchQuery(query="test", threshold=1.1)


class TestSearchResult:
    """Test search result dataclass."""

    def test_minimal_result(self) -> None:
        """Test minimal result creation."""
        result = SearchResult(
            task_id="task-123",
            title="Test Task",
            repository="mahavishnu",
            similarity=0.95,
        )
        assert result.task_id == "task-123"
        assert result.title == "Test Task"
        assert result.repository == "mahavishnu"
        assert result.similarity == 0.95
        assert result.content is None
        assert result.metadata == {}
        assert result.highlights == []

    def test_full_result(self) -> None:
        """Test result with all fields."""
        result = SearchResult(
            task_id="task-123",
            title="Test Task",
            repository="mahavishnu",
            similarity=0.95,
            content="Full content here",
            metadata={"key": "value"},
            highlights=["matched text"],
        )
        assert result.content == "Full content here"
        assert result.metadata == {"key": "value"}
        assert result.highlights == ["matched text"]


class TestVectorIndex:
    """Test vector index management."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def index(self, mock_db: MagicMock) -> VectorIndex:
        """Create vector index."""
        return VectorIndex(mock_db)

    @pytest.mark.asyncio
    async def test_create_hnsw_index(self, index: VectorIndex, mock_db: MagicMock) -> None:
        """Test creating HNSW index."""
        await index.create_hnsw_index(table="test_table", column="embedding")

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0][0]
        assert "CREATE INDEX" in call_args
        assert "USING hnsw" in call_args
        assert "test_table" in call_args
        assert "embedding" in call_args

    @pytest.mark.asyncio
    async def test_create_hnsw_index_custom_params(self, index: VectorIndex, mock_db: MagicMock) -> None:
        """Test creating HNSW index with custom params."""
        await index.create_hnsw_index(m=32, ef_construction=128)

        call_args = mock_db.execute.call_args[0][0]
        assert "m = 32" in call_args
        assert "ef_construction = 128" in call_args

    @pytest.mark.asyncio
    async def test_create_ivfflat_index(self, index: VectorIndex, mock_db: MagicMock) -> None:
        """Test creating IVFFlat index."""
        await index.create_ivfflat_index(lists=200)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0][0]
        assert "USING ivfflat" in call_args
        assert "lists = 200" in call_args

    @pytest.mark.asyncio
    async def test_drop_index(self, index: VectorIndex, mock_db: MagicMock) -> None:
        """Test dropping index."""
        await index.drop_index(table="test_table", column="embedding", index_type="hnsw")

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0][0]
        assert "DROP INDEX" in call_args


class TestVectorStore:
    """Test vector store operations."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.execute = AsyncMock()
        db.fetchrow = AsyncMock()
        db.fetch = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def mock_embedding_service(self) -> MagicMock:
        """Create mock embedding service."""
        service = MagicMock()
        result = MagicMock()
        result.embeddings = [[0.1, 0.2, 0.3]]
        service.embed = AsyncMock(return_value=result)
        return service

    @pytest.fixture
    def store(self, mock_db: MagicMock) -> VectorStore:
        """Create vector store."""
        return VectorStore(mock_db)

    @pytest.mark.asyncio
    async def test_store_embedding_with_precomputed(
        self, store: VectorStore, mock_db: MagicMock
    ) -> None:
        """Test storing pre-computed embedding."""
        mock_db.fetchrow = AsyncMock(return_value={"id": "emb-123"})

        result = await store.store_embedding(
            task_id="task-123",
            text="Test text",
            embedding=[0.1, 0.2, 0.3],
        )

        assert result == "emb-123"
        mock_db.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_embedding_generate(
        self, mock_db: MagicMock, mock_embedding_service: MagicMock
    ) -> None:
        """Test storing embedding with generation."""
        mock_db.fetchrow = AsyncMock(return_value={"id": "emb-123"})
        store = VectorStore(mock_db, mock_embedding_service)

        result = await store.store_embedding(
            task_id="task-123",
            text="Test text",
        )

        assert result == "emb-123"
        mock_embedding_service.embed.assert_called_once_with("Test text")

    @pytest.mark.asyncio
    async def test_store_embedding_no_service(self, store: VectorStore) -> None:
        """Test storing embedding fails without service."""
        with pytest.raises(VectorSearchError) as exc_info:
            await store.store_embedding(task_id="task-123", text="Test text")

        assert "No embedding service" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_embedding(self, store: VectorStore, mock_db: MagicMock) -> None:
        """Test getting embedding."""
        mock_db.fetchrow = AsyncMock(return_value={"embedding": [0.1, 0.2, 0.3]})

        result = await store.get_embedding("task-123")

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_get_embedding_not_found(self, store: VectorStore, mock_db: MagicMock) -> None:
        """Test getting embedding not found."""
        mock_db.fetchrow = AsyncMock(return_value=None)

        result = await store.get_embedding("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_embedding(self, store: VectorStore, mock_db: MagicMock) -> None:
        """Test deleting embedding."""
        mock_db.execute = AsyncMock(return_value="DELETE 1")

        result = await store.delete_embedding("task-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_embedding_not_found(self, store: VectorStore, mock_db: MagicMock) -> None:
        """Test deleting embedding not found."""
        mock_db.execute = AsyncMock(return_value="DELETE 0")

        result = await store.delete_embedding("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_batch_store(
        self, mock_db: MagicMock, mock_embedding_service: MagicMock
    ) -> None:
        """Test batch storing embeddings."""
        mock_db.fetchrow = AsyncMock(return_value={"id": "emb-123"})
        store = VectorStore(mock_db, mock_embedding_service)

        items = [
            {"task_id": "task-1", "text": "Text 1"},
            {"task_id": "task-2", "text": "Text 2"},
            {"task_id": "task-3", "text": "Text 3"},
        ]

        result = await store.batch_store(items)

        assert result == 3

    @pytest.mark.asyncio
    async def test_batch_store_empty(self, store: VectorStore) -> None:
        """Test batch storing empty list."""
        result = await store.batch_store([])
        assert result == 0


class TestVectorSearch:
    """Test vector search functionality."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.execute = AsyncMock()
        db.fetchrow = AsyncMock()
        db.fetch = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def mock_embedding_service(self) -> MagicMock:
        """Create mock embedding service."""
        service = MagicMock()
        result = MagicMock()
        result.embeddings = [[0.1, 0.2, 0.3]]
        service.embed = AsyncMock(return_value=result)
        return service

    @pytest.fixture
    def search(self, mock_db: MagicMock) -> VectorSearch:
        """Create vector search."""
        return VectorSearch(mock_db)

    @pytest.mark.asyncio
    async def test_vector_search(
        self, mock_db: MagicMock, mock_embedding_service: MagicMock
    ) -> None:
        """Test vector search."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-1",
                    "title": "Test Task",
                    "repository": "mahavishnu",
                    "similarity": 0.95,
                    "content": "Content",
                    "metadata": {},
                }
            ]
        )
        search = VectorSearch(mock_db, mock_embedding_service)

        query = SearchQuery(query="test", search_type=SearchType.VECTOR)
        results = await search.search(query)

        assert len(results) == 1
        assert results[0].task_id == "task-1"
        assert results[0].similarity == 0.95

    @pytest.mark.asyncio
    async def test_vector_search_no_service(self, search: VectorSearch) -> None:
        """Test vector search fails without embedding service."""
        query = SearchQuery(query="test", search_type=SearchType.VECTOR)

        with pytest.raises(VectorSearchError) as exc_info:
            await search.search(query)

        assert "Embedding service required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fts_search(self, search: VectorSearch, mock_db: MagicMock) -> None:
        """Test full-text search."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-1",
                    "title": "Test Task",
                    "repository": "mahavishnu",
                    "similarity": 0.8,
                    "content": "Content",
                    "metadata": {},
                    "highlight": "<b>test</b>",
                }
            ]
        )

        query = SearchQuery(query="test", search_type=SearchType.FTS)
        results = await search.search(query)

        assert len(results) == 1
        assert results[0].highlights == ["<b>test</b>"]

    @pytest.mark.asyncio
    async def test_hybrid_search(
        self, mock_db: MagicMock, mock_embedding_service: MagicMock
    ) -> None:
        """Test hybrid search."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-1",
                    "title": "Test Task",
                    "repository": "mahavishnu",
                    "hybrid_score": 0.9,
                    "content": "Content",
                    "metadata": {},
                }
            ]
        )
        search = VectorSearch(mock_db, mock_embedding_service)

        query = SearchQuery(query="test", search_type=SearchType.HYBRID)
        results = await search.search(query)

        assert len(results) == 1
        assert results[0].similarity == 0.9

    @pytest.mark.asyncio
    async def test_hybrid_search_fallback_fts(self, search: VectorSearch, mock_db: MagicMock) -> None:
        """Test hybrid search falls back to FTS without embedding service."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-1",
                    "title": "Test Task",
                    "repository": "mahavishnu",
                    "similarity": 0.8,
                    "content": "Content",
                    "metadata": {},
                    "highlight": None,
                }
            ]
        )

        query = SearchQuery(query="test", search_type=SearchType.HYBRID)
        results = await search.search(query)

        # Should have executed FTS search
        assert mock_db.fetch.called

    @pytest.mark.asyncio
    async def test_find_similar(
        self, mock_db: MagicMock, mock_embedding_service: MagicMock
    ) -> None:
        """Test finding similar tasks."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-2",
                    "title": "Similar Task",
                    "repository": "mahavishnu",
                    "similarity": 0.85,
                    "content": "Content",
                    "metadata": {},
                }
            ]
        )
        # Mock get_embedding
        mock_db.fetchrow = AsyncMock(return_value={"embedding": [0.1, 0.2, 0.3]})

        search = VectorSearch(mock_db, mock_embedding_service)
        results = await search.find_similar("task-1")

        assert len(results) == 1
        assert results[0].task_id == "task-2"

    @pytest.mark.asyncio
    async def test_find_similar_no_embedding(self, search: VectorSearch, mock_db: MagicMock) -> None:
        """Test finding similar when task has no embedding."""
        mock_db.fetchrow = AsyncMock(return_value=None)

        results = await search.find_similar("task-1")

        assert results == []


class TestTaskSimilarity:
    """Test task similarity utilities."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.fetch = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def similarity(self, mock_db: MagicMock) -> TaskSimilarity:
        """Create task similarity."""
        return TaskSimilarity(mock_db)

    @pytest.mark.asyncio
    async def test_compute_similarity_matrix(self, similarity: TaskSimilarity, mock_db: MagicMock) -> None:
        """Test computing similarity matrix."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {"task_id": "task-1", "embedding": [0.1, 0.2, 0.3]},
                {"task_id": "task-2", "embedding": [0.15, 0.25, 0.35]},
                {"task_id": "task-3", "embedding": [0.2, 0.3, 0.4]},
            ]
        )

        matrix = await similarity.compute_similarity_matrix(["task-1", "task-2", "task-3"])

        # Should have 6 entries (3 pairs, each direction)
        assert len(matrix) == 6

    @pytest.mark.asyncio
    async def test_compute_similarity_matrix_single(self, similarity: TaskSimilarity) -> None:
        """Test computing similarity matrix with single task."""
        matrix = await similarity.compute_similarity_matrix(["task-1"])
        assert matrix == {}

    @pytest.mark.asyncio
    async def test_compute_similarity_matrix_empty(self, similarity: TaskSimilarity) -> None:
        """Test computing similarity matrix with empty list."""
        matrix = await similarity.compute_similarity_matrix([])
        assert matrix == {}

    @pytest.mark.asyncio
    async def test_find_duplicates(self, similarity: TaskSimilarity, mock_db: MagicMock) -> None:
        """Test finding duplicate tasks."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {"task_id1": "task-1", "task_id2": "task-2", "similarity": 0.98},
                {"task_id1": "task-3", "task_id2": "task-4", "similarity": 0.96},
            ]
        )

        duplicates = await similarity.find_duplicates(threshold=0.95)

        assert len(duplicates) == 2
        assert duplicates[0] == ("task-1", "task-2", 0.98)
        assert duplicates[1] == ("task-3", "task-4", 0.96)

    @pytest.mark.asyncio
    async def test_find_duplicates_with_repository(
        self, similarity: TaskSimilarity, mock_db: MagicMock
    ) -> None:
        """Test finding duplicates filtered by repository."""
        mock_db.fetch = AsyncMock(return_value=[])

        await similarity.find_duplicates(threshold=0.95, repository="mahavishnu")

        # Verify repository filter was included
        call_args = mock_db.fetch.call_args
        assert "mahavishnu" in call_args[0]
