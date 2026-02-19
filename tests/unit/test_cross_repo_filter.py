"""Tests for CrossRepoFilter - Multi-repository task filtering."""

import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.cross_repo_filter import (
    CrossRepoFilter,
    FilterCriteria,
    FilterResult,
    DateRangeFilter,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def mock_repo_manager() -> MagicMock:
    """Create a mock RepositoryManager."""
    manager = MagicMock()

    # Create proper mock repos with string names
    def make_mock_repo(name: str, tags: list[str], role: str):
        repo = MagicMock()
        repo.name = name  # Set as actual string, not MagicMock
        repo.tags = tags
        repo.role = role
        return repo

    manager.get_repos_by_tag = MagicMock(side_effect=lambda tag: [
        make_mock_repo("mahavishnu", ["orchestrator", "python"], "orchestrator"),
        make_mock_repo("crackerjack", ["qc", "testing", "python"], "inspector"),
    ] if tag in ["python", "orchestrator"] else [])

    manager.get_repos_by_role = MagicMock(side_effect=lambda role: [
        make_mock_repo("session-buddy", ["session", "memory"], "manager"),
        make_mock_repo("akosha", ["vector", "search"], "soothsayer"),
    ] if role in ["manager", "soothsayer"] else [])

    manager.list_repos = MagicMock(return_value=[
        make_mock_repo("mahavishnu", ["orchestrator", "python"], "orchestrator"),
        make_mock_repo("crackerjack", ["qc", "testing"], "inspector"),
        make_mock_repo("session-buddy", ["session", "memory"], "manager"),
    ])
    return manager


class TestFilterCriteria:
    """Tests for FilterCriteria model."""

    def test_create_empty_criteria(self) -> None:
        """Create criteria with defaults."""
        criteria = FilterCriteria()
        assert criteria.repo_names is None
        assert criteria.repo_tags is None
        assert criteria.repo_roles is None
        assert criteria.statuses is None
        assert criteria.priorities is None

    def test_create_criteria_with_values(self) -> None:
        """Create criteria with specific values."""
        criteria = FilterCriteria(
            repo_names=["mahavishnu", "crackerjack"],
            repo_roles=["orchestrator", "inspector"],
            repo_tags=["python"],
            statuses=[TaskStatus.IN_PROGRESS, TaskStatus.PENDING],
            priorities=[TaskPriority.HIGH, TaskPriority.CRITICAL],
            tags=["auth", "security"],
            date_range=DateRangeFilter(last_n_days=7),
        )
        assert criteria.repo_names == ["mahavishnu", "crackerjack"]
        assert criteria.repo_roles == ["orchestrator", "inspector"]
        assert criteria.statuses == [TaskStatus.IN_PROGRESS, TaskStatus.PENDING]

    def test_criteria_with_text_search(self) -> None:
        """Create criteria with text search."""
        criteria = FilterCriteria(
            text_search="authentication bug",
            search_fields=["title", "description"],
        )
        assert criteria.text_search == "authentication bug"
        assert criteria.search_fields == ["title", "description"]


class TestDateRangeFilter:
    """Tests for DateRangeFilter model."""

    def test_last_n_days(self) -> None:
        """Create filter for last N days."""
        filter = DateRangeFilter(last_n_days=7)
        assert filter.last_n_days == 7
        assert filter.start_date is None
        assert filter.end_date is None

    def test_explicit_date_range(self) -> None:
        """Create filter with explicit dates."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        filter = DateRangeFilter(start_date=start, end_date=end)
        assert filter.start_date == start
        assert filter.end_date == end
        assert filter.last_n_days is None

    def test_get_date_range_last_n_days(self) -> None:
        """Calculate date range from last_n_days."""
        filter = DateRangeFilter(last_n_days=7)
        start, end = filter.get_date_range()

        # Start should be approximately 7 days ago
        assert (end - start).days == 7

    def test_get_date_range_explicit(self) -> None:
        """Get explicit date range."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        filter = DateRangeFilter(start_date=start, end_date=end)
        result_start, result_end = filter.get_date_range()

        assert result_start == start
        assert result_end == end


class TestFilterResult:
    """Tests for FilterResult dataclass."""

    def test_create_filter_result(self) -> None:
        """Create FilterResult instance."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
        ]
        result = FilterResult(
            tasks=tasks,
            total_count=1,
            filtered_count=1,
            page=1,
            page_size=50,
            total_pages=1,
        )

        assert result.total_count == 1
        assert result.filtered_count == 1
        assert len(result.tasks) == 1
        assert result.has_more is False

    def test_filter_result_pagination(self) -> None:
        """Test pagination properties."""
        result = FilterResult(
            tasks=[],
            total_count=100,
            filtered_count=100,
            page=2,
            page_size=50,
            total_pages=2,
        )

        assert result.has_more is False
        assert result.page == 2

    def test_filter_result_has_more(self) -> None:
        """Test has_more property."""
        result = FilterResult(
            tasks=[],
            total_count=100,
            filtered_count=100,
            page=1,
            page_size=50,
            total_pages=2,
        )

        assert result.has_more is True

    def test_filter_result_to_dict(self) -> None:
        """Convert to dictionary."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
        ]
        result = FilterResult(
            tasks=tasks,
            total_count=1,
            filtered_count=1,
            page=1,
            page_size=50,
            total_pages=1,
        )

        d = result.to_dict()
        assert d["total_count"] == 1
        assert d["filtered_count"] == 1
        assert "tasks" in d
        assert "page" in d


class TestCrossRepoFilter:
    """Tests for CrossRepoFilter class."""

    @pytest.mark.asyncio
    async def test_filter_by_repo_names(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by repository names."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(repo_names=["mahavishnu"])
        result = await filter.filter(criteria)

        # Should return only 1 task (mahavishnu)
        assert result.total_count == 1
        assert all(t.repository == "mahavishnu" for t in result.tasks)

    @pytest.mark.asyncio
    async def test_filter_by_status(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by status."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(statuses=[TaskStatus.IN_PROGRESS])
        result = await filter.filter(criteria)

        # Should return only 1 task (in_progress)
        assert result.total_count == 1
        assert all(t.status == TaskStatus.IN_PROGRESS for t in result.tasks)

    @pytest.mark.asyncio
    async def test_filter_by_priority(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by priority."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(priorities=[TaskPriority.HIGH])
        result = await filter.filter(criteria)

        # Should return only 1 task (high priority)
        assert result.total_count == 1
        assert all(t.priority == TaskPriority.HIGH for t in result.tasks)

    @pytest.mark.asyncio
    async def test_filter_by_tags(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by tags."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                tags=["python", "backend"],
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                tags=["testing", "qc"],
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(tags=["python"])
        result = await filter.filter(criteria)

        assert any("python" in t.tags for t in result.tasks)

    @pytest.mark.asyncio
    async def test_filter_by_repo_tags(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by repository tags."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        # Create proper mock with .name as string
        mock_repo = MagicMock()
        mock_repo.name = "mahavishnu"
        mock_repo_manager.get_repos_by_tag.return_value = [mock_repo]

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(repo_tags=["orchestrator"])
        result = await filter.filter(criteria)

        mock_repo_manager.get_repos_by_tag.assert_called_with("orchestrator")

    @pytest.mark.asyncio
    async def test_filter_by_repo_roles(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter tasks by repository roles."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="session-buddy",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="akosha",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        # Create proper mocks with .name as strings
        mock_repo1 = MagicMock()
        mock_repo1.name = "session-buddy"
        mock_repo2 = MagicMock()
        mock_repo2.name = "akosha"
        mock_repo_manager.get_repos_by_role.return_value = [mock_repo1, mock_repo2]

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(repo_roles=["manager", "soothsayer"])
        result = await filter.filter(criteria)

        # Verify the filter was applied
        assert result.total_count == 2

    @pytest.mark.asyncio
    async def test_filter_with_pagination(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter with pagination."""
        tasks = [
            Task(
                id=f"task-{i}",
                title=f"Task {i}",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            )
            for i in range(100)
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(page=2, page_size=10)
        result = await filter.filter(criteria)

        assert result.page == 2
        assert result.page_size == 10

    @pytest.mark.asyncio
    async def test_filter_with_date_range(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter with date range."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=10),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=2),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(
            date_range=DateRangeFilter(last_n_days=7)
        )
        result = await filter.filter(criteria)

        # Should filter to only recent tasks (task-2 is within 7 days)
        assert result.total_count == 1

    @pytest.mark.asyncio
    async def test_filter_combined_criteria(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter with combined criteria."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                tags=["python"],
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="crackerjack",
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                tags=["testing"],
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.HIGH,
                tags=["python"],
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(
            repo_names=["mahavishnu"],
            statuses=[TaskStatus.IN_PROGRESS],
            priorities=[TaskPriority.HIGH],
        )
        result = await filter.filter(criteria)

        # Should only return task-1 (mahavishnu + in_progress + high)
        assert all(
            t.repository == "mahavishnu"
            and t.status == TaskStatus.IN_PROGRESS
            and t.priority == TaskPriority.HIGH
            for t in result.tasks
        )

    @pytest.mark.asyncio
    async def test_filter_text_search(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter with text search."""
        tasks = [
            Task(
                id="task-1",
                title="Fix authentication bug",
                description="Users cannot login",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Update documentation",
                description="Add API examples",
                repository="crackerjack",
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(text_search="authentication")
        result = await filter.filter(criteria)

        # Should filter to only matching tasks (task-1 has "authentication")
        assert result.total_count == 1
        assert result.tasks[0].id == "task-1"

    @pytest.mark.asyncio
    async def test_filter_exclude_completed(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter excluding completed tasks."""
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(exclude_completed=True)
        result = await filter.filter(criteria)

        assert all(t.status != TaskStatus.COMPLETED for t in result.tasks)

    @pytest.mark.asyncio
    async def test_filter_sorting(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Filter with sorting."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id="task-1",
                title="Task 1",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.LOW,
                created_at=now - timedelta(days=2),
            ),
            Task(
                id="task-2",
                title="Task 2",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                created_at=now,
            ),
        ]
        mock_task_store.list.return_value = tasks

        filter = CrossRepoFilter(mock_task_store, mock_repo_manager)
        criteria = FilterCriteria(sort_by="priority", sort_order="desc")
        result = await filter.filter(criteria)

        assert result.total_count == 2
