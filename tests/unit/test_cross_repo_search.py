"""Tests for CrossRepoSearch - Cross-repository task search."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from mahavishnu.core.cross_repo_search import (
    CrossRepoSearch,
    SearchCriteria,
    SearchResult,
    SearchMatch,
    SearchType,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def mock_vector_search() -> AsyncMock:
    """Create a mock VectorSearch."""
    search = AsyncMock()
    return search


@pytest.fixture
def sample_tasks() -> list[Task]:
    """Create sample tasks for testing."""
    now = datetime.now(UTC)
    return [
        Task(
            id="task-1",
            title="Fix authentication bug in login",
            description="Users cannot login due to OAuth2 issue",
            repository="mahavishnu",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            tags=["auth", "security", "oauth"],
            created_at=now,
        ),
        Task(
            id="task-2",
            title="Add unit tests for API",
            description="Increase coverage for REST endpoints",
            repository="crackerjack",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            tags=["testing", "api"],
            created_at=now,
        ),
        Task(
            id="task-3",
            title="Implement semantic search",
            description="Add vector-based search capabilities",
            repository="akosha",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            tags=["search", "vector", "ai"],
            created_at=now,
        ),
    ]


class TestSearchCriteria:
    """Tests for SearchCriteria model."""

    def test_create_text_search(self) -> None:
        """Create text-only search criteria."""
        criteria = SearchCriteria(query="authentication")
        assert criteria.query == "authentication"
        assert criteria.search_type == SearchType.TEXT
        assert criteria.repo_names is None

    def test_create_semantic_search(self) -> None:
        """Create semantic search criteria."""
        criteria = SearchCriteria(
            query="login issues",
            search_type=SearchType.SEMANTIC,
        )
        assert criteria.query == "login issues"
        assert criteria.search_type == SearchType.SEMANTIC

    def test_create_hybrid_search(self) -> None:
        """Create hybrid search criteria."""
        criteria = SearchCriteria(
            query="bug fix",
            search_type=SearchType.HYBRID,
            repo_names=["mahavishnu", "crackerjack"],
        )
        assert criteria.search_type == SearchType.HYBRID
        assert criteria.repo_names == ["mahavishnu", "crackerjack"]

    def test_search_with_filters(self) -> None:
        """Create search with status/priority filters."""
        criteria = SearchCriteria(
            query="api",
            statuses=[TaskStatus.IN_PROGRESS, TaskStatus.PENDING],
            priorities=[TaskPriority.HIGH],
        )
        assert criteria.statuses == [TaskStatus.IN_PROGRESS, TaskStatus.PENDING]
        assert criteria.priorities == [TaskPriority.HIGH]


class TestSearchMatch:
    """Tests for SearchMatch dataclass."""

    def test_create_search_match(self) -> None:
        """Create SearchMatch instance."""
        match = SearchMatch(
            field="title",
            snippet="Fix **authentication** bug",
            score=0.95,
        )
        assert match.field == "title"
        assert match.score == 0.95
        assert "authentication" in match.snippet

    def test_match_to_dict(self) -> None:
        """Convert match to dictionary."""
        match = SearchMatch(
            field="description",
            snippet="OAuth2 **issue**",
            score=0.8,
        )
        d = match.to_dict()

        assert d["field"] == "description"
        assert d["score"] == 0.8


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_create_search_result(self) -> None:
        """Create SearchResult instance."""
        task = Task(
            id="task-1",
            title="Test",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            created_at=datetime.now(UTC),
        )
        result = SearchResult(
            task=task,
            matches=[SearchMatch(field="title", snippet="**Test**", score=1.0)],
            overall_score=0.9,
            search_type=SearchType.TEXT,
        )

        assert result.task.id == "task-1"
        assert result.overall_score == 0.9
        assert len(result.matches) == 1

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        task = Task(
            id="task-1",
            title="Test",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            created_at=datetime.now(UTC),
        )
        result = SearchResult(
            task=task,
            matches=[],
            overall_score=0.5,
            search_type=SearchType.SEMANTIC,
        )

        d = result.to_dict()
        assert d["overall_score"] == 0.5
        assert d["search_type"] == "semantic"
        assert "task" in d


class TestCrossRepoSearch:
    """Tests for CrossRepoSearch class."""

    @pytest.mark.asyncio
    async def test_text_search(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test basic text search."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="authentication")
        results = await search.search(criteria)

        assert len(results) >= 1
        # Task-1 should match "authentication"
        assert any(r.task.id == "task-1" for r in results)

    @pytest.mark.asyncio
    async def test_text_search_in_description(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test text search in description field."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="OAuth2")
        results = await search.search(criteria)

        # Task-1 has OAuth2 in description
        assert any(r.task.id == "task-1" for r in results)

    @pytest.mark.asyncio
    async def test_search_with_repo_filter(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with repository filter."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(
            query="search",
            repo_names=["akosha"],
        )
        results = await search.search(criteria)

        # All results should be from akosha
        assert all(r.task.repository == "akosha" for r in results)

    @pytest.mark.asyncio
    async def test_search_with_status_filter(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with status filter."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(
            query="api",
            statuses=[TaskStatus.PENDING],
        )
        results = await search.search(criteria)

        # All results should be PENDING
        assert all(r.task.status == TaskStatus.PENDING for r in results)

    @pytest.mark.asyncio
    async def test_search_with_tag_filter(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with tag filter."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(
            query="implement",
            tags=["search"],
        )
        results = await search.search(criteria)

        # Results should have "search" tag
        assert all("search" in r.task.tags for r in results)

    @pytest.mark.asyncio
    async def test_search_limit(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with result limit."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="", limit=2)
        results = await search.search(criteria)

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_search_scoring(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test that results are scored and ranked."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="authentication bug")
        results = await search.search(criteria)

        # Results should be sorted by score (descending)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].overall_score >= results[i + 1].overall_score

    @pytest.mark.asyncio
    async def test_search_no_results(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with no matching results."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="xyznonexistent123")
        results = await search.search(criteria)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_empty_query(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with empty query returns all tasks."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="")
        results = await search.search(criteria)

        # Should return all tasks (up to limit)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_case_insensitive(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test case-insensitive search."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="AUTHENTICATION")
        results = await search.search(criteria)

        # Should find task-1 regardless of case
        assert any(r.task.id == "task-1" for r in results)

    @pytest.mark.asyncio
    async def test_search_highlight_matches(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test that matching terms are highlighted."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="authentication")
        results = await search.search(criteria)

        # At least one result should have a match snippet
        if results:
            assert any(len(r.matches) > 0 for r in results)

    @pytest.mark.asyncio
    async def test_search_multiple_terms(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test search with multiple search terms."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="api test")
        results = await search.search(criteria)

        # Should find tasks with either "api" or "test"
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_result_contains_repository(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Test that results include repository information."""
        mock_task_store.list.return_value = sample_tasks

        search = CrossRepoSearch(mock_task_store)
        criteria = SearchCriteria(query="search")
        results = await search.search(criteria)

        for result in results:
            assert result.task.repository is not None
            assert result.to_dict()["task"]["repository"] == result.task.repository


class TestSearchType:
    """Tests for SearchType enum."""

    def test_search_types(self) -> None:
        """Test available search types."""
        assert SearchType.TEXT.value == "text"
        assert SearchType.SEMANTIC.value == "semantic"
        assert SearchType.HYBRID.value == "hybrid"


class TestSearchCriteriaValidation:
    """Tests for SearchCriteria validation."""

    def test_default_search_type(self) -> None:
        """Default search type should be TEXT."""
        criteria = SearchCriteria(query="test")
        assert criteria.search_type == SearchType.TEXT

    def test_default_limit(self) -> None:
        """Default limit should be 50."""
        criteria = SearchCriteria(query="test")
        assert criteria.limit == 50

    def test_custom_limit(self) -> None:
        """Can set custom limit."""
        criteria = SearchCriteria(query="test", limit=10)
        assert criteria.limit == 10
