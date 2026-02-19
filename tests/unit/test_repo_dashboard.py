"""Tests for RepositoryDashboard - Repository-specific dashboard views."""

import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.repo_dashboard import (
    RepositoryDashboard,
    DashboardView,
    ActivityMetrics,
    HealthIndicator,
    TaskDistribution,
    RiskAssessment,
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
    return manager


@pytest.fixture
def sample_tasks() -> list[Task]:
    """Create sample tasks for a repository."""
    now = datetime.now(UTC)
    return [
        Task(
            id="task-1",
            title="Critical bug fix",
            repository="mahavishnu",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.CRITICAL,
            tags=["bug", "urgent"],
            created_at=now - timedelta(days=2),
        ),
        Task(
            id="task-2",
            title="Feature implementation",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            tags=["feature"],
            created_at=now - timedelta(days=5),
        ),
        Task(
            id="task-3",
            title="Documentation update",
            repository="mahavishnu",
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.LOW,
            tags=["docs"],
            created_at=now - timedelta(days=10),
            completed_at=now - timedelta(days=1),
        ),
        Task(
            id="task-4",
            title="Blocked dependency",
            repository="mahavishnu",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.HIGH,
            tags=["dependency"],
            created_at=now - timedelta(days=3),
        ),
        Task(
            id="task-5",
            title="Code review",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            tags=["review"],
            created_at=now - timedelta(hours=12),
        ),
    ]


class TestActivityMetrics:
    """Tests for ActivityMetrics dataclass."""

    def test_create_metrics(self) -> None:
        """Create ActivityMetrics instance."""
        metrics = ActivityMetrics(
            tasks_created_today=5,
            tasks_completed_today=3,
            tasks_created_week=20,
            tasks_completed_week=15,
            average_completion_time_hours=24.5,
            velocity_trend="increasing",
        )

        assert metrics.tasks_created_today == 5
        assert metrics.tasks_completed_today == 3
        assert metrics.velocity_trend == "increasing"

    def test_metrics_to_dict(self) -> None:
        """Convert metrics to dictionary."""
        metrics = ActivityMetrics(
            tasks_created_today=5,
            tasks_completed_today=3,
            tasks_created_week=20,
            tasks_completed_week=15,
            average_completion_time_hours=24.5,
            velocity_trend="stable",
        )

        d = metrics.to_dict()
        assert d["tasks_created_today"] == 5
        assert d["velocity_trend"] == "stable"


class TestHealthIndicator:
    """Tests for HealthIndicator enum."""

    def test_health_levels(self) -> None:
        """Test health indicator levels."""
        assert HealthIndicator.HEALTHY.value == "healthy"
        assert HealthIndicator.WARNING.value == "warning"
        assert HealthIndicator.CRITICAL.value == "critical"


class TestTaskDistribution:
    """Tests for TaskDistribution dataclass."""

    def test_create_distribution(self) -> None:
        """Create TaskDistribution instance."""
        dist = TaskDistribution(
            by_status={
                TaskStatus.PENDING: 10,
                TaskStatus.IN_PROGRESS: 5,
                TaskStatus.COMPLETED: 20,
            },
            by_priority={
                TaskPriority.HIGH: 3,
                TaskPriority.MEDIUM: 7,
                TaskPriority.LOW: 25,
            },
            by_tag={"bug": 5, "feature": 10, "docs": 20},
        )

        assert dist.by_status[TaskStatus.PENDING] == 10
        assert dist.by_priority[TaskPriority.HIGH] == 3

    def test_distribution_to_dict(self) -> None:
        """Convert distribution to dictionary."""
        dist = TaskDistribution(
            by_status={TaskStatus.PENDING: 10},
            by_priority={TaskPriority.HIGH: 3},
            by_tag={"bug": 5},
        )

        d = dist.to_dict()
        assert "by_status" in d
        assert "by_priority" in d


class TestRiskAssessment:
    """Tests for RiskAssessment dataclass."""

    def test_create_assessment(self) -> None:
        """Create RiskAssessment instance."""
        assessment = RiskAssessment(
            level="high",
            blocked_tasks=5,
            overdue_tasks=3,
            stale_tasks=2,
            risks=["High blocked task count", "Overdue deadlines"],
        )

        assert assessment.level == "high"
        assert assessment.blocked_tasks == 5
        assert len(assessment.risks) == 2

    def test_assessment_to_dict(self) -> None:
        """Convert assessment to dictionary."""
        assessment = RiskAssessment(
            level="low",
            blocked_tasks=0,
            overdue_tasks=0,
            stale_tasks=0,
            risks=[],
        )

        d = assessment.to_dict()
        assert d["level"] == "low"
        assert d["risks"] == []


class TestDashboardView:
    """Tests for DashboardView dataclass."""

    def test_create_dashboard_view(self) -> None:
        """Create DashboardView instance."""
        view = DashboardView(
            repo_name="mahavishnu",
            total_tasks=50,
            health=HealthIndicator.HEALTHY,
        )

        assert view.repo_name == "mahavishnu"
        assert view.total_tasks == 50
        assert view.health == HealthIndicator.HEALTHY

    def test_view_to_dict(self) -> None:
        """Convert view to dictionary."""
        view = DashboardView(
            repo_name="mahavishnu",
            total_tasks=50,
            health=HealthIndicator.WARNING,
        )

        d = view.to_dict()
        assert d["repo_name"] == "mahavishnu"
        assert d["health"] == "warning"


class TestRepositoryDashboard:
    """Tests for RepositoryDashboard class."""

    @pytest.mark.asyncio
    async def test_get_dashboard_view(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Get dashboard view for a repository."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.repo_name == "mahavishnu"
        assert view.total_tasks == 5

    @pytest.mark.asyncio
    async def test_dashboard_task_distribution(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Dashboard includes task distribution."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.distribution is not None
        assert view.distribution.by_status[TaskStatus.PENDING] == 2
        assert view.distribution.by_status[TaskStatus.IN_PROGRESS] == 1
        assert view.distribution.by_status[TaskStatus.COMPLETED] == 1
        assert view.distribution.by_status[TaskStatus.BLOCKED] == 1

    @pytest.mark.asyncio
    async def test_dashboard_health_healthy(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard shows healthy status when no issues."""
        # All completed tasks = healthy
        tasks = [
            Task(
                id=f"task-{i}",
                title=f"Task {i}",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.MEDIUM,
                created_at=datetime.now(UTC) - timedelta(days=i),
            )
            for i in range(10)
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.health == HealthIndicator.HEALTHY

    @pytest.mark.asyncio
    async def test_dashboard_health_warning(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard shows warning when some issues."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id="task-1",
                title="Blocked task",
                repository="mahavishnu",
                status=TaskStatus.BLOCKED,
                priority=TaskPriority.HIGH,
                created_at=now - timedelta(days=5),
            ),
            Task(
                id="task-2",
                title="Normal task",
                repository="mahavishnu",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.MEDIUM,
                created_at=now,
            ),
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        # Blocked tasks should trigger warning
        assert view.health in [HealthIndicator.WARNING, HealthIndicator.CRITICAL]

    @pytest.mark.asyncio
    async def test_dashboard_health_critical(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard shows critical when many issues."""
        now = datetime.now(UTC)
        # Many blocked and high priority tasks
        tasks = [
            Task(
                id=f"task-{i}",
                title=f"Blocked task {i}",
                repository="mahavishnu",
                status=TaskStatus.BLOCKED,
                priority=TaskPriority.CRITICAL,
                created_at=now - timedelta(days=10),
            )
            for i in range(10)
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.health == HealthIndicator.CRITICAL

    @pytest.mark.asyncio
    async def test_dashboard_activity_metrics(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Dashboard includes activity metrics."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.activity is not None
        assert view.activity.tasks_created_week >= 0
        assert view.activity.tasks_completed_week >= 0

    @pytest.mark.asyncio
    async def test_dashboard_risk_assessment(
        self, mock_task_store: AsyncMock, sample_tasks: list[Task]
    ) -> None:
        """Dashboard includes risk assessment."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.risk is not None
        assert view.risk.blocked_tasks == 1  # One blocked task in sample

    @pytest.mark.asyncio
    async def test_get_all_dashboards(
        self, mock_task_store: AsyncMock, mock_repo_manager: MagicMock
    ) -> None:
        """Get dashboards for all repositories."""
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

        # Mock repo manager
        mock_repo = MagicMock()
        mock_repo.name = "mahavishnu"
        mock_repo2 = MagicMock()
        mock_repo2.name = "crackerjack"
        mock_repo_manager.list_repos.return_value = [mock_repo, mock_repo2]

        dashboard = RepositoryDashboard(mock_task_store, mock_repo_manager)
        views = await dashboard.get_all_dashboards()

        assert len(views) >= 2

    @pytest.mark.asyncio
    async def test_dashboard_empty_repository(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard for repository with no tasks."""
        mock_task_store.list.return_value = []

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("empty-repo")

        assert view.total_tasks == 0
        assert view.health == HealthIndicator.HEALTHY

    @pytest.mark.asyncio
    async def test_dashboard_identifies_at_risk_tasks(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard identifies at-risk tasks."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id="task-1",
                title="Old pending task",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.HIGH,
                created_at=now - timedelta(days=30),  # Stale
            ),
            Task(
                id="task-2",
                title="Blocked high priority",
                repository="mahavishnu",
                status=TaskStatus.BLOCKED,
                priority=TaskPriority.CRITICAL,
                created_at=now - timedelta(days=5),
            ),
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        # Should identify risks
        assert view.risk is not None
        assert len(view.risk.risks) > 0

    @pytest.mark.asyncio
    async def test_dashboard_completion_rate(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard calculates completion rate."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id=f"task-{i}",
                title=f"Task {i}",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED if i < 5 else TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=i),
            )
            for i in range(10)
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        # 5 completed out of 10 = 50%
        assert view.completion_rate == pytest.approx(0.5, rel=0.1)

    @pytest.mark.asyncio
    async def test_dashboard_block_rate(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard calculates block rate."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id=f"task-{i}",
                title=f"Task {i}",
                repository="mahavishnu",
                status=TaskStatus.BLOCKED if i < 2 else TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=i),
            )
            for i in range(10)
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        # 2 blocked out of 10 = 20%
        assert view.blocked_rate == pytest.approx(0.2, rel=0.1)

    @pytest.mark.asyncio
    async def test_dashboard_recent_activity(
        self, mock_task_store: AsyncMock
    ) -> None:
        """Dashboard tracks recent activity."""
        now = datetime.now(UTC)
        tasks = [
            Task(
                id="task-today",
                title="Today task",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(hours=2),
            ),
            Task(
                id="task-week",
                title="Week task",
                repository="mahavishnu",
                status=TaskStatus.COMPLETED,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=3),
                completed_at=now - timedelta(days=2),
            ),
            Task(
                id="task-old",
                title="Old task",
                repository="mahavishnu",
                status=TaskStatus.PENDING,
                priority=TaskPriority.MEDIUM,
                created_at=now - timedelta(days=30),
            ),
        ]
        mock_task_store.list.return_value = tasks

        dashboard = RepositoryDashboard(mock_task_store)
        view = await dashboard.get_dashboard("mahavishnu")

        assert view.activity.tasks_created_today >= 1
        assert view.activity.tasks_created_week >= 2
