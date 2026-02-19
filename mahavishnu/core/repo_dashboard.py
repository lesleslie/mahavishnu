"""Repository Dashboard for Mahavishnu.

Provides repository-specific dashboard views:
- Task counts by status, priority, tags
- Activity metrics (created, completed, velocity)
- Health indicators (healthy, warning, critical)
- Risk assessment (blocked, overdue, stale)

Usage:
    from mahavishnu.core.repo_dashboard import RepositoryDashboard

    dashboard = RepositoryDashboard(task_store, repo_manager)

    # Get dashboard for a single repo
    view = await dashboard.get_dashboard("mahavishnu")

    # Get dashboards for all repos
    views = await dashboard.get_all_dashboards()
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore, TaskListFilter

logger = logging.getLogger(__name__)


class HealthIndicator(str, Enum):
    """Health status for a repository."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ActivityMetrics:
    """Activity metrics for a repository.

    Attributes:
        tasks_created_today: Tasks created in last 24 hours
        tasks_completed_today: Tasks completed in last 24 hours
        tasks_created_week: Tasks created in last 7 days
        tasks_completed_week: Tasks completed in last 7 days
        average_completion_time_hours: Average time to complete tasks
        velocity_trend: Trend direction (increasing, stable, decreasing)
    """

    tasks_created_today: int = 0
    tasks_completed_today: int = 0
    tasks_created_week: int = 0
    tasks_completed_week: int = 0
    average_completion_time_hours: float = 0.0
    velocity_trend: str = "stable"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tasks_created_today": self.tasks_created_today,
            "tasks_completed_today": self.tasks_completed_today,
            "tasks_created_week": self.tasks_created_week,
            "tasks_completed_week": self.tasks_completed_week,
            "average_completion_time_hours": self.average_completion_time_hours,
            "velocity_trend": self.velocity_trend,
        }


@dataclass
class TaskDistribution:
    """Distribution of tasks by various dimensions.

    Attributes:
        by_status: Count of tasks per status
        by_priority: Count of tasks per priority
        by_tag: Count of tasks per tag
    """

    by_status: dict[TaskStatus, int] = field(default_factory=dict)
    by_priority: dict[TaskPriority, int] = field(default_factory=dict)
    by_tag: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "by_status": {s.value: c for s, c in self.by_status.items()},
            "by_priority": {p.value: c for p, c in self.by_priority.items()},
            "by_tag": self.by_tag,
        }


@dataclass
class RiskAssessment:
    """Risk assessment for a repository.

    Attributes:
        level: Overall risk level (low, medium, high)
        blocked_tasks: Number of blocked tasks
        overdue_tasks: Number of overdue tasks
        stale_tasks: Number of stale tasks (pending > 14 days)
        risks: List of identified risks
    """

    level: str = "low"
    blocked_tasks: int = 0
    overdue_tasks: int = 0
    stale_tasks: int = 0
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "level": self.level,
            "blocked_tasks": self.blocked_tasks,
            "overdue_tasks": self.overdue_tasks,
            "stale_tasks": self.stale_tasks,
            "risks": self.risks,
        }


@dataclass
class DashboardView:
    """Complete dashboard view for a repository.

    Attributes:
        repo_name: Name of the repository
        total_tasks: Total number of tasks
        health: Health indicator
        distribution: Task distribution
        activity: Activity metrics
        risk: Risk assessment
        completion_rate: Percentage of completed tasks
        blocked_rate: Percentage of blocked tasks
        at_risk_task_ids: IDs of tasks needing attention
    """

    repo_name: str
    total_tasks: int
    health: HealthIndicator = HealthIndicator.HEALTHY
    distribution: TaskDistribution | None = None
    activity: ActivityMetrics | None = None
    risk: RiskAssessment | None = None
    completion_rate: float = 0.0
    blocked_rate: float = 0.0
    at_risk_task_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "repo_name": self.repo_name,
            "total_tasks": self.total_tasks,
            "health": self.health.value,
            "distribution": self.distribution.to_dict() if self.distribution else None,
            "activity": self.activity.to_dict() if self.activity else None,
            "risk": self.risk.to_dict() if self.risk else None,
            "completion_rate": self.completion_rate,
            "blocked_rate": self.blocked_rate,
            "at_risk_task_ids": self.at_risk_task_ids,
        }


class RepositoryDashboard:
    """Generates dashboard views for repositories.

    Provides comprehensive dashboard with:
    - Task distribution by status, priority, tags
    - Activity metrics and velocity trends
    - Health indicators based on blocked/stale tasks
    - Risk assessment with actionable insights

    Example:
        dashboard = RepositoryDashboard(task_store, repo_manager)

        # Get dashboard for a single repo
        view = await dashboard.get_dashboard("mahavishnu")
        print(f"Health: {view.health.value}")
        print(f"Blocked: {view.risk.blocked_tasks}")

        # Get all dashboards
        for view in await dashboard.get_all_dashboards():
            print(f"{view.repo_name}: {view.total_tasks} tasks")
    """

    # Thresholds for health indicators
    BLOCKED_RATE_WARNING = 0.10  # 10% blocked triggers warning
    BLOCKED_RATE_CRITICAL = 0.25  # 25% blocked triggers critical
    STALE_TASK_WARNING_DAYS = 14  # Tasks pending > 14 days are stale

    def __init__(
        self,
        task_store: TaskStore,
        repo_manager: Any = None,  # RepositoryManager type
    ) -> None:
        """Initialize the dashboard.

        Args:
            task_store: TaskStore instance for task queries
            repo_manager: Optional RepositoryManager for repo list
        """
        self.task_store = task_store
        self.repo_manager = repo_manager

    async def get_dashboard(self, repo_name: str) -> DashboardView:
        """Get dashboard view for a specific repository.

        Args:
            repo_name: Name of the repository

        Returns:
            DashboardView with complete metrics
        """
        # Fetch all tasks for the repository
        tasks = await self.task_store.list(
            TaskListFilter(repository=repo_name, limit=10000)
        )

        # Calculate distribution
        distribution = self._calculate_distribution(tasks)

        # Calculate activity metrics
        activity = self._calculate_activity(tasks)

        # Assess risks
        risk = self._assess_risks(tasks)

        # Calculate rates
        completion_rate = self._calculate_completion_rate(tasks)
        blocked_rate = self._calculate_blocked_rate(tasks)

        # Determine health
        health = self._determine_health(tasks, blocked_rate, risk)

        # Identify at-risk tasks
        at_risk_ids = self._identify_at_risk_tasks(tasks)

        return DashboardView(
            repo_name=repo_name,
            total_tasks=len(tasks),
            health=health,
            distribution=distribution,
            activity=activity,
            risk=risk,
            completion_rate=completion_rate,
            blocked_rate=blocked_rate,
            at_risk_task_ids=at_risk_ids,
        )

    async def get_all_dashboards(self) -> list[DashboardView]:
        """Get dashboard views for all repositories.

        Returns:
            List of DashboardView for each repository with tasks
        """
        # Get all tasks
        all_tasks = await self.task_store.list(TaskListFilter(limit=10000))

        # Group by repository
        tasks_by_repo: dict[str, list[Task]] = defaultdict(list)
        for task in all_tasks:
            tasks_by_repo[task.repository].append(task)

        # Generate dashboard for each repo
        dashboards: list[DashboardView] = []
        for repo_name, tasks in tasks_by_repo.items():
            distribution = self._calculate_distribution(tasks)
            activity = self._calculate_activity(tasks)
            risk = self._assess_risks(tasks)
            completion_rate = self._calculate_completion_rate(tasks)
            blocked_rate = self._calculate_blocked_rate(tasks)
            health = self._determine_health(tasks, blocked_rate, risk)
            at_risk_ids = self._identify_at_risk_tasks(tasks)

            dashboards.append(DashboardView(
                repo_name=repo_name,
                total_tasks=len(tasks),
                health=health,
                distribution=distribution,
                activity=activity,
                risk=risk,
                completion_rate=completion_rate,
                blocked_rate=blocked_rate,
                at_risk_task_ids=at_risk_ids,
            ))

        return dashboards

    def _calculate_distribution(self, tasks: list[Task]) -> TaskDistribution:
        """Calculate task distribution by various dimensions."""
        by_status: dict[TaskStatus, int] = defaultdict(int)
        by_priority: dict[TaskPriority, int] = defaultdict(int)
        by_tag: dict[str, int] = defaultdict(int)

        for task in tasks:
            by_status[task.status] += 1
            by_priority[task.priority] += 1
            for tag in task.tags:
                by_tag[tag] += 1

        return TaskDistribution(
            by_status=dict(by_status),
            by_priority=dict(by_priority),
            by_tag=dict(by_tag),
        )

    def _calculate_activity(self, tasks: list[Task]) -> ActivityMetrics:
        """Calculate activity metrics."""
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        created_today = 0
        completed_today = 0
        created_week = 0
        completed_week = 0
        completion_times: list[float] = []

        for task in tasks:
            if task.created_at:
                if task.created_at >= day_ago:
                    created_today += 1
                if task.created_at >= week_ago:
                    created_week += 1

            if task.completed_at:
                if task.completed_at >= day_ago:
                    completed_today += 1
                if task.completed_at >= week_ago:
                    completed_week += 1

                # Calculate completion time
                if task.created_at:
                    delta = task.completed_at - task.created_at
                    completion_times.append(delta.total_seconds() / 3600)

        avg_completion_time = (
            sum(completion_times) / len(completion_times)
            if completion_times else 0.0
        )

        # Determine velocity trend (simplified)
        if created_week > 0:
            completion_ratio = completed_week / created_week
            if completion_ratio > 0.8:
                trend = "increasing"
            elif completion_ratio < 0.5:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return ActivityMetrics(
            tasks_created_today=created_today,
            tasks_completed_today=completed_today,
            tasks_created_week=created_week,
            tasks_completed_week=completed_week,
            average_completion_time_hours=round(avg_completion_time, 1),
            velocity_trend=trend,
        )

    def _assess_risks(self, tasks: list[Task]) -> RiskAssessment:
        """Assess risks for the repository."""
        now = datetime.now(UTC)
        stale_threshold = now - timedelta(days=self.STALE_TASK_WARNING_DAYS)

        blocked_count = 0
        stale_count = 0
        overdue_count = 0
        risks: list[str] = []

        for task in tasks:
            if task.status == TaskStatus.BLOCKED:
                blocked_count += 1

            # Check for stale tasks (pending too long)
            if task.status == TaskStatus.PENDING and task.created_at:
                if task.created_at < stale_threshold:
                    stale_count += 1

            # Check for overdue tasks (past deadline)
            if task.due_date and task.due_date < now:
                if task.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                    overdue_count += 1

        # Generate risk messages
        if blocked_count > 0:
            risks.append(f"{blocked_count} blocked task(s) need attention")

        if stale_count > 0:
            risks.append(f"{stale_count} stale task(s) pending > 14 days")

        if overdue_count > 0:
            risks.append(f"{overdue_count} overdue task(s) past deadline")

        # Determine overall risk level
        total = len(tasks)
        if total == 0:
            level = "low"
        elif blocked_count > total * 0.2 or stale_count > total * 0.3:
            level = "high"
        elif blocked_count > 0 or stale_count > 0 or overdue_count > 0:
            level = "medium"
        else:
            level = "low"

        return RiskAssessment(
            level=level,
            blocked_tasks=blocked_count,
            overdue_tasks=overdue_count,
            stale_tasks=stale_count,
            risks=risks,
        )

    def _calculate_completion_rate(self, tasks: list[Task]) -> float:
        """Calculate task completion rate."""
        if not tasks:
            return 0.0

        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        return round(completed / len(tasks), 2)

    def _calculate_blocked_rate(self, tasks: list[Task]) -> float:
        """Calculate task blocked rate."""
        if not tasks:
            return 0.0

        blocked = sum(1 for t in tasks if t.status == TaskStatus.BLOCKED)
        return round(blocked / len(tasks), 2)

    def _determine_health(
        self,
        tasks: list[Task],
        blocked_rate: float,
        risk: RiskAssessment,
    ) -> HealthIndicator:
        """Determine overall health indicator."""
        # No tasks = healthy
        if not tasks:
            return HealthIndicator.HEALTHY

        # Critical conditions
        if blocked_rate >= self.BLOCKED_RATE_CRITICAL:
            return HealthIndicator.CRITICAL

        if risk.level == "high":
            return HealthIndicator.CRITICAL

        # Warning conditions
        if blocked_rate >= self.BLOCKED_RATE_WARNING:
            return HealthIndicator.WARNING

        if risk.level == "medium":
            return HealthIndicator.WARNING

        # Check for high-priority blocked tasks
        high_priority_blocked = sum(
            1 for t in tasks
            if t.status == TaskStatus.BLOCKED
            and t.priority in (TaskPriority.HIGH, TaskPriority.CRITICAL)
        )
        if high_priority_blocked > 0:
            return HealthIndicator.WARNING

        return HealthIndicator.HEALTHY

    def _identify_at_risk_tasks(self, tasks: list[Task]) -> list[str]:
        """Identify tasks that need immediate attention."""
        now = datetime.now(UTC)
        stale_threshold = now - timedelta(days=self.STALE_TASK_WARNING_DAYS)
        at_risk: list[str] = []

        for task in tasks:
            is_at_risk = False

            # Blocked high/critical priority
            if task.status == TaskStatus.BLOCKED:
                if task.priority in (TaskPriority.HIGH, TaskPriority.CRITICAL):
                    is_at_risk = True

            # Stale pending tasks
            if task.status == TaskStatus.PENDING and task.created_at:
                if task.created_at < stale_threshold:
                    is_at_risk = True

            # Overdue tasks
            if task.due_date and task.due_date < now:
                if task.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                    is_at_risk = True

            if is_at_risk:
                at_risk.append(task.id)

        return at_risk


__all__ = [
    "RepositoryDashboard",
    "DashboardView",
    "ActivityMetrics",
    "HealthIndicator",
    "TaskDistribution",
    "RiskAssessment",
]
