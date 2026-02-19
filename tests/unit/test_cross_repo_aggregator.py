"""Tests for CrossRepoAggregator - Multi-repository task aggregation."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from mahavishnu.core.cross_repo_aggregator import (
    CrossRepoAggregator,
    AggregatedTasks,
    RepoTaskStats,
    AggregationFilter,
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
    manager.get_repos_by_tag = MagicMock(return_value=[
        MagicMock(name="mahavishnu", tags=["orchestrator", "python"]),
        MagicMock(name="crackerjack", tags=["qc", "testing", "python"]),
    ])
    manager.get_repos_by_role = MagicMock(return_value=[
        MagicMock(name="session-buddy", role="manager"),
        MagicMock(name="akosha", role="soothsayer"),
    ])
    manager.list_repos = MagicMock(return_value=[
        MagicMock(name="mahavishnu", tags=["orchestrator", "python"], role="orchestrator"),
        MagicMock(name="crackerjack", tags=["qc", "testing"], role="inspector"),
        MagicMock(name="session-buddy", tags=["session", "memory"], role="manager"),
    ])
    return manager


@pytest.fixture
def sample_tasks() -> list[Task]:
    """Create sample tasks across repositories."""
    now = datetime.now(UTC)
    return [
        Task(
            id="task-1",
            title="Fix authentication bug",
            repository="mahavishnu",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            tags=["auth", "security"],
            created_at=now,
            updated_at=now,
        ),
        Task(
            id="task-2",
            title="Add unit tests",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            tags=["testing"],
            created_at=now,
            updated_at=now,
        ),
        Task(
            id="task-3",
            title="Implement quality check",
            repository="crackerjack",
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.HIGH,
            tags=["qc", "testing"],
            created_at=now,
            updated_at=now,
        ),
        Task(
            id="task-4",
            title="Track session state",
            repository="session-buddy",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.CRITICAL,
            tags=["session", "state"],
            created_at=now,
            updated_at=now,
        ),
        Task(
            id="task-5",
            title="Search optimization",
            repository="akosha",
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,
            tags=["search", "performance"],
            created_at=now,
            updated_at=now,
        ),
    ]


class TestAggregationFilter:
    """Tests for AggregationFilter model."""

    def test_create_empty_filter(self) -> None:
        """Create filter with defaults."""
        filter = AggregationFilter()
        assert filter.repo_names is None
        assert filter.repo_tags is None
        assert filter.repo_roles is None
        assert filter.status is None
        assert filter.priority is None

    def test_create_filter_with_values(self) -> None:
        """Create filter with specific values."""
        filter = AggregationFilter(
            repo_names=["mahavishnu", "crackerjack"],
            roles=["orchestrator", "inspector"],
            tags=["python"],
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
        )
        assert filter.repo_names == ["mahavishnu", "crackerjack"]
        assert filter.roles == ["orchestrator", "inspector"]
        assert filter.tags == ["python"]
        assert filter.status == TaskStatus.IN_PROGRESS


class TestCrossRepoAggregator:
    """Tests for CrossRepoAggregator class."""

    @pytest.mark.asyncio
    async def test_aggregate_all_tasks(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks from all repositories."""
        # Setup
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

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_all()

        assert result.total_count == 2
        assert len(result.tasks) == 2
        assert result.repo_counts["mahavishnu"] == 1
        assert result.repo_counts["crackerjack"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_by_repository(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks grouped by repository."""
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
                repository="mahavishnu",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="crackerjack",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_by_repository()

        assert "mahavishnu" in result
        assert "crackerjack" in result
        assert result["mahavishnu"].total_tasks == 2
        assert result["crackerjack"].total_tasks == 1

    @pytest.mark.asyncio
    async def test_aggregate_by_status(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks grouped by status across repositories."""
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
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="akosha",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_by_status()

        assert TaskStatus.PENDING in result
        assert TaskStatus.IN_PROGRESS in result
        assert len(result[TaskStatus.PENDING]) == 2
        assert len(result[TaskStatus.IN_PROGRESS]) == 1

    @pytest.mark.asyncio
    async def test_aggregate_by_priority(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks grouped by priority across repositories."""
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
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="akosha",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_by_priority()

        assert TaskPriority.HIGH in result
        assert TaskPriority.LOW in result
        assert len(result[TaskPriority.HIGH]) == 2
        assert len(result[TaskPriority.LOW]) == 1

    @pytest.mark.asyncio
    async def test_aggregate_by_tag(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks grouped by tag across repositories."""
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
                priority=TaskPriority.HIGH,
                tags=["python", "testing"],
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="akosha",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.LOW,
                tags=["vector", "search"],
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_by_tag()

        assert "python" in result
        assert len(result["python"]) == 2
        assert "backend" in result
        assert "testing" in result
        assert "vector" in result

    @pytest.mark.asyncio
    async def test_get_repo_stats(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Get statistics for a specific repository."""
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
                repository="mahavishnu",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        stats = await aggregator.get_repo_stats("mahavishnu")

        assert stats.repo_name == "mahavishnu"
        assert stats.total_tasks == 3
        assert stats.status_counts[TaskStatus.PENDING] == 1
        assert stats.status_counts[TaskStatus.IN_PROGRESS] == 1
        assert stats.status_counts[TaskStatus.COMPLETED] == 1

    @pytest.mark.asyncio
    async def test_aggregate_with_filter(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks with filter applied."""
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
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        filter = AggregationFilter(
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
        )
        result = await aggregator.aggregate_with_filter(filter)

        # Verify the filter was applied
        mock_task_store.list.assert_called()
        assert result.total_count == 2

    @pytest.mark.asyncio
    async def test_aggregate_by_role(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Aggregate tasks grouped by repository role."""
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
                repository="session-buddy",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        result = await aggregator.aggregate_by_role()

        # Should have roles as keys
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_get_cross_repo_summary(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Get a summary of tasks across all repositories."""
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
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC),
            ),
            Task(
                id="task-3",
                title="Task 3",
                repository="akosha",
                status=TaskStatus.BLOCKED,
                priority=TaskPriority.LOW,
                created_at=datetime.now(UTC),
            ),
        ]
        mock_task_store.list.return_value = tasks

        aggregator = CrossRepoAggregator(mock_task_store, mock_repo_manager)
        summary = await aggregator.get_summary()

        assert summary.total_tasks == 3
        assert summary.total_repos == 3
        assert summary.blocked_count == 1
        assert summary.in_progress_count == 1
        assert summary.pending_count == 1


class TestAggregatedTasks:
    """Tests for AggregatedTasks dataclass."""

    def test_create_aggregated_tasks(self) -> None:
        """Create AggregatedTasks instance."""
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
        aggregated = AggregatedTasks(
            tasks=tasks,
            total_count=1,
            repo_counts={"mahavishnu": 1},
            status_counts={TaskStatus.PENDING: 1},
            priority_counts={TaskPriority.MEDIUM: 1},
        )

        assert aggregated.total_count == 1
        assert len(aggregated.tasks) == 1
        assert aggregated.repo_counts["mahavishnu"] == 1

    def test_to_dict(self) -> None:
        """Convert AggregatedTasks to dictionary."""
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
        aggregated = AggregatedTasks(
            tasks=tasks,
            total_count=1,
            repo_counts={"mahavishnu": 1},
            status_counts={TaskStatus.PENDING: 1},
            priority_counts={TaskPriority.MEDIUM: 1},
        )

        result = aggregated.to_dict()

        assert result["total_count"] == 1
        assert "tasks" in result
        assert "repo_counts" in result


class TestRepoTaskStats:
    """Tests for RepoTaskStats dataclass."""

    def test_create_repo_stats(self) -> None:
        """Create RepoTaskStats instance."""
        stats = RepoTaskStats(
            repo_name="mahavishnu",
            total_tasks=10,
            status_counts={
                TaskStatus.PENDING: 3,
                TaskStatus.IN_PROGRESS: 2,
                TaskStatus.COMPLETED: 5,
            },
            priority_counts={
                TaskPriority.HIGH: 2,
                TaskPriority.MEDIUM: 5,
                TaskPriority.LOW: 3,
            },
        )

        assert stats.repo_name == "mahavishnu"
        assert stats.total_tasks == 10
        assert stats.status_counts[TaskStatus.PENDING] == 3

    def test_completion_rate(self) -> None:
        """Calculate completion rate."""
        stats = RepoTaskStats(
            repo_name="mahavishnu",
            total_tasks=10,
            status_counts={
                TaskStatus.PENDING: 3,
                TaskStatus.IN_PROGRESS: 2,
                TaskStatus.COMPLETED: 5,
            },
            priority_counts={},
        )

        assert stats.completion_rate == 0.5  # 5/10

    def test_completion_rate_zero_tasks(self) -> None:
        """Completion rate is 0 when no tasks exist."""
        stats = RepoTaskStats(
            repo_name="mahavishnu",
            total_tasks=0,
            status_counts={},
            priority_counts={},
        )

        assert stats.completion_rate == 0.0


class TestAggregationFilter:
    """Tests for AggregationFilter."""

    def test_empty_filter(self) -> None:
        """Create empty filter."""
        filter = AggregationFilter()
        assert filter.repo_names is None
        assert filter.roles is None
        assert filter.tags is None
        assert filter.status is None
        assert filter.priority is None

    def test_filter_with_all_fields(self) -> None:
        """Create filter with all fields."""
        filter = AggregationFilter(
            repo_names=["mahavishnu", "crackerjack"],
            roles=["orchestrator"],
            tags=["python"],
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            tags_any=["testing", "qc"],
            exclude_completed=True,
        )

        assert filter.repo_names == ["mahavishnu", "crackerjack"]
        assert filter.roles == ["orchestrator"]
        assert filter.tags == ["python"]
        assert filter.status == TaskStatus.IN_PROGRESS
        assert filter.priority == TaskPriority.HIGH
        assert filter.exclude_completed is True
