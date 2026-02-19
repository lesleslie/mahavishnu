"""Cross-Repository Task Aggregator for Mahavishnu.

Aggregates tasks across multiple repositories for unified views:
- Aggregate tasks by repository, status, priority, tags
- Get statistics per repository
- Filter tasks across repositories
- Provide cross-repo summaries

Usage:
    from mahavishnu.core.cross_repo_aggregator import CrossRepoAggregator

    aggregator = CrossRepoAggregator(task_store, repo_manager)

    # Aggregate all tasks
    all_tasks = await aggregator.aggregate_all()

    # Get tasks by status across repos
    by_status = await aggregator.aggregate_by_status()

    # Get repo statistics
    stats = await aggregator.get_repo_stats("mahavishnu")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore, TaskListFilter

logger = logging.getLogger(__name__)


@dataclass
class AggregationFilter:
    """Filter for cross-repository task aggregation.

    Attributes:
        repo_names: Filter to specific repositories (AND logic if multiple)
        roles: Filter to repositories with these roles
        tags: Filter to tasks with ALL these tags
        tags_any: Filter to tasks with ANY of these tags
        status: Filter to specific task status
        priority: Filter to specific task priority
        exclude_completed: Exclude completed tasks from results
        limit: Maximum number of tasks to return
        offset: Offset for pagination
    """

    repo_names: list[str] | None = None
    roles: list[str] | None = None
    tags: list[str] | None = None
    tags_any: list[str] | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    exclude_completed: bool = False
    limit: int = 100
    offset: int = 0

    def to_task_filter(self) -> TaskListFilter:
        """Convert to TaskListFilter for TaskStore queries."""
        return TaskListFilter(
            status=self.status,
            priority=self.priority,
            tags=self.tags,
            limit=self.limit,
            offset=self.offset,
        )


@dataclass
class RepoTaskStats:
    """Statistics for tasks in a single repository.

    Attributes:
        repo_name: Name of the repository
        total_tasks: Total number of tasks
        status_counts: Count of tasks per status
        priority_counts: Count of tasks per priority
        tag_counts: Count of tasks per tag
        blocked_tasks: List of blocked task IDs
        oldest_pending: Date of oldest pending task (None if no pending)
        newest_task: Date of most recently created task
    """

    repo_name: str
    total_tasks: int
    status_counts: dict[TaskStatus, int] = field(default_factory=dict)
    priority_counts: dict[TaskPriority, int] = field(default_factory=dict)
    tag_counts: dict[str, int] = field(default_factory=dict)
    blocked_tasks: list[str] = field(default_factory=list)
    oldest_pending: datetime | None = None
    newest_task: datetime | None = None

    @property
    def completion_rate(self) -> float:
        """Calculate task completion rate (0.0 to 1.0)."""
        if self.total_tasks == 0:
            return 0.0
        completed = self.status_counts.get(TaskStatus.COMPLETED, 0)
        return completed / self.total_tasks

    @property
    def blocked_rate(self) -> float:
        """Calculate task blocked rate (0.0 to 1.0)."""
        if self.total_tasks == 0:
            return 0.0
        blocked = self.status_counts.get(TaskStatus.BLOCKED, 0)
        return blocked / self.total_tasks

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "repo_name": self.repo_name,
            "total_tasks": self.total_tasks,
            "status_counts": {
                s.value: c for s, c in self.status_counts.items()
            },
            "priority_counts": {
                p.value: c for p, c in self.priority_counts.items()
            },
            "tag_counts": self.tag_counts,
            "blocked_tasks": self.blocked_tasks,
            "completion_rate": self.completion_rate,
            "blocked_rate": self.blocked_rate,
            "oldest_pending": self.oldest_pending.isoformat() if self.oldest_pending else None,
            "newest_task": self.newest_task.isoformat() if self.newest_task else None,
        }


@dataclass
class AggregatedTasks:
    """Container for aggregated tasks across repositories.

    Attributes:
        tasks: List of all tasks
        total_count: Total number of tasks
        repo_counts: Count of tasks per repository
        status_counts: Count of tasks per status
        priority_counts: Count of tasks per priority
        tag_counts: Count of tasks per tag
    """

    tasks: list[Task] = field(default_factory=list)
    total_count: int = 0
    repo_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[TaskStatus, int] = field(default_factory=dict)
    priority_counts: dict[TaskPriority, int] = field(default_factory=dict)
    tag_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "total_count": self.total_count,
            "repo_counts": self.repo_counts,
            "status_counts": {
                s.value: c for s, c in self.status_counts.items()
            },
            "priority_counts": {
                p.value: c for p, c in self.priority_counts.items()
            },
            "tag_counts": self.tag_counts,
        }


@dataclass
class CrossRepoSummary:
    """Summary of tasks across all repositories.

    Attributes:
        total_tasks: Total tasks across all repos
        total_repos: Number of repositories with tasks
        pending_count: Tasks in pending status
        in_progress_count: Tasks in progress
        completed_count: Completed tasks
        blocked_count: Blocked tasks
        cancelled_count: Cancelled tasks
        failed_count: Failed tasks
        repo_stats: Per-repository statistics
        critical_count: High priority tasks needing attention
    """

    total_tasks: int = 0
    total_repos: int = 0
    pending_count: int = 0
    in_progress_count: int = 0
    completed_count: int = 0
    blocked_count: int = 0
    cancelled_count: int = 0
    failed_count: int = 0
    repo_stats: dict[str, RepoTaskStats] = field(default_factory=dict)
    critical_count: int = 0  # High priority + blocked/in_progress

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_tasks": self.total_tasks,
            "total_repos": self.total_repos,
            "pending_count": self.pending_count,
            "in_progress_count": self.in_progress_count,
            "completed_count": self.completed_count,
            "blocked_count": self.blocked_count,
            "cancelled_count": self.cancelled_count,
            "failed_count": self.failed_count,
            "critical_count": self.critical_count,
            "repo_stats": {
                name: stats.to_dict() for name, stats in self.repo_stats.items()
            },
        }


class CrossRepoAggregator:
    """Aggregates tasks across multiple repositories.

    Provides unified views of tasks across the entire ecosystem:
    - Aggregate all tasks with counts by repo, status, priority
    - Group tasks by various dimensions
    - Calculate per-repository statistics
    - Filter tasks across repositories

    Example:
        aggregator = CrossRepoAggregator(task_store, repo_manager)

        # Get all tasks
        all_tasks = await aggregator.aggregate_all()

        # Get tasks by repository
        by_repo = await aggregator.aggregate_by_repository()

        # Get statistics for a repo
        stats = await aggregator.get_repo_stats("mahavishnu")

        # Get cross-repo summary
        summary = await aggregator.get_summary()
    """

    def __init__(
        self,
        task_store: TaskStore,
        repo_manager: Any,  # RepositoryManager type
    ) -> None:
        """Initialize the aggregator.

        Args:
            task_store: TaskStore instance for task queries
            repo_manager: RepositoryManager for repo metadata
        """
        self.task_store = task_store
        self.repo_manager = repo_manager

    async def aggregate_all(self) -> AggregatedTasks:
        """Aggregate all tasks across all repositories.

        Returns:
            AggregatedTasks with all tasks and counts
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))
        return self._build_aggregated_tasks(tasks)

    async def aggregate_with_filter(self, filter: AggregationFilter) -> AggregatedTasks:
        """Aggregate tasks with a filter applied.

        Args:
            filter: AggregationFilter to apply

        Returns:
            AggregatedTasks with filtered tasks and counts
        """
        task_filter = filter.to_task_filter()

        # If filtering by repo names, we need to query each repo separately
        if filter.repo_names:
            all_tasks: list[Task] = []
            for repo in filter.repo_names:
                repo_filter = TaskListFilter(
                    repository=repo,
                    status=filter.status,
                    priority=filter.priority,
                    tags=filter.tags,
                    limit=filter.limit,
                    offset=filter.offset,
                )
                tasks = await self.task_store.list(repo_filter)
                all_tasks.extend(tasks)

            # Apply exclude_completed if needed
            if filter.exclude_completed:
                all_tasks = [
                    t for t in all_tasks
                    if t.status != TaskStatus.COMPLETED
                ]

            return self._build_aggregated_tasks(all_tasks[:filter.limit])

        tasks = await self.task_store.list(task_filter)

        # Apply exclude_completed if needed
        if filter.exclude_completed:
            tasks = [t for t in tasks if t.status != TaskStatus.COMPLETED]

        return self._build_aggregated_tasks(tasks)

    async def aggregate_by_repository(self) -> dict[str, RepoTaskStats]:
        """Aggregate tasks grouped by repository.

        Returns:
            Dictionary mapping repository name to RepoTaskStats
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))
        return self._group_by_repository(tasks)

    async def aggregate_by_status(self) -> dict[TaskStatus, list[Task]]:
        """Aggregate tasks grouped by status across repositories.

        Returns:
            Dictionary mapping status to list of tasks
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))

        result: dict[TaskStatus, list[Task]] = defaultdict(list)
        for task in tasks:
            result[task.status].append(task)

        return dict(result)

    async def aggregate_by_priority(self) -> dict[TaskPriority, list[Task]]:
        """Aggregate tasks grouped by priority across repositories.

        Returns:
            Dictionary mapping priority to list of tasks
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))

        result: dict[TaskPriority, list[Task]] = defaultdict(list)
        for task in tasks:
            result[task.priority].append(task)

        return dict(result)

    async def aggregate_by_tag(self) -> dict[str, list[Task]]:
        """Aggregate tasks grouped by tag across repositories.

        Returns:
            Dictionary mapping tag to list of tasks
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))

        result: dict[str, list[Task]] = defaultdict(list)
        for task in tasks:
            for tag in task.tags:
                result[tag].append(task)

        return dict(result)

    async def aggregate_by_role(self) -> dict[str, list[Task]]:
        """Aggregate tasks grouped by repository role.

        Returns:
            Dictionary mapping role to list of tasks
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))

        # Build repo name -> role mapping
        repo_to_role: dict[str, str] = {}
        try:
            repos = self.repo_manager.list_repos()
            for repo in repos:
                repo_to_role[repo.name] = getattr(repo, "role", "unknown")
        except Exception as e:
            logger.warning(f"Could not get repo roles: {e}")

        result: dict[str, list[Task]] = defaultdict(list)
        for task in tasks:
            role = repo_to_role.get(task.repository, "unknown")
            result[role].append(task)

        return dict(result)

    async def get_repo_stats(self, repo_name: str) -> RepoTaskStats:
        """Get statistics for a specific repository.

        Args:
            repo_name: Name of the repository

        Returns:
            RepoTaskStats with detailed statistics
        """
        tasks = await self.task_store.list(
            TaskListFilter(repository=repo_name, limit=10000)
        )
        return self._build_repo_stats(repo_name, tasks)

    async def get_summary(self) -> CrossRepoSummary:
        """Get a summary of tasks across all repositories.

        Returns:
            CrossRepoSummary with overall statistics
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))
        repo_stats = self._group_by_repository(tasks)

        # Count by status
        status_counts: dict[TaskStatus, int] = defaultdict(int)
        priority_counts: dict[TaskPriority, int] = defaultdict(int)
        critical_count = 0

        for task in tasks:
            status_counts[task.status] += 1
            priority_counts[task.priority] += 1

            # Critical = high priority + (blocked or in_progress)
            if task.priority == TaskPriority.HIGH or task.priority == TaskPriority.CRITICAL:
                if task.status in (TaskStatus.BLOCKED, TaskStatus.IN_PROGRESS):
                    critical_count += 1

        return CrossRepoSummary(
            total_tasks=len(tasks),
            total_repos=len(repo_stats),
            pending_count=status_counts.get(TaskStatus.PENDING, 0),
            in_progress_count=status_counts.get(TaskStatus.IN_PROGRESS, 0),
            completed_count=status_counts.get(TaskStatus.COMPLETED, 0),
            blocked_count=status_counts.get(TaskStatus.BLOCKED, 0),
            cancelled_count=status_counts.get(TaskStatus.CANCELLED, 0),
            failed_count=status_counts.get(TaskStatus.FAILED, 0),
            repo_stats=repo_stats,
            critical_count=critical_count,
        )

    async def get_repos_needing_attention(self, limit: int = 5) -> list[RepoTaskStats]:
        """Get repositories that need attention (blocked tasks, high blocked rate).

        Args:
            limit: Maximum number of repos to return

        Returns:
            List of RepoTaskStats sorted by need for attention
        """
        all_stats = await self.aggregate_by_repository()

        # Score repos by need for attention
        def attention_score(stats: RepoTaskStats) -> float:
            score = 0.0
            # Blocked tasks are critical
            score += stats.blocked_rate * 50
            # High priority tasks matter
            high_count = stats.priority_counts.get(TaskPriority.HIGH, 0)
            critical_count = stats.priority_counts.get(TaskPriority.CRITICAL, 0)
            score += (high_count + critical_count * 2) * 5
            # Low completion rate
            score += (1 - stats.completion_rate) * 20
            return score

        sorted_stats = sorted(
            all_stats.values(),
            key=attention_score,
            reverse=True,
        )

        return sorted_stats[:limit]

    def _build_aggregated_tasks(self, tasks: list[Task]) -> AggregatedTasks:
        """Build AggregatedTasks from a list of tasks."""
        repo_counts: dict[str, int] = defaultdict(int)
        status_counts: dict[TaskStatus, int] = defaultdict(int)
        priority_counts: dict[TaskPriority, int] = defaultdict(int)
        tag_counts: dict[str, int] = defaultdict(int)

        for task in tasks:
            repo_counts[task.repository] += 1
            status_counts[task.status] += 1
            priority_counts[task.priority] += 1
            for tag in task.tags:
                tag_counts[tag] += 1

        return AggregatedTasks(
            tasks=tasks,
            total_count=len(tasks),
            repo_counts=dict(repo_counts),
            status_counts=dict(status_counts),
            priority_counts=dict(priority_counts),
            tag_counts=dict(tag_counts),
        )

    def _group_by_repository(self, tasks: list[Task]) -> dict[str, RepoTaskStats]:
        """Group tasks by repository and build stats."""
        repo_tasks: dict[str, list[Task]] = defaultdict(list)

        for task in tasks:
            repo_tasks[task.repository].append(task)

        return {
            repo: self._build_repo_stats(repo, tasks)
            for repo, tasks in repo_tasks.items()
        }

    def _build_repo_stats(self, repo_name: str, tasks: list[Task]) -> RepoTaskStats:
        """Build RepoTaskStats from a list of tasks for a repository."""
        status_counts: dict[TaskStatus, int] = defaultdict(int)
        priority_counts: dict[TaskPriority, int] = defaultdict(int)
        tag_counts: dict[str, int] = defaultdict(int)
        blocked_tasks: list[str] = []
        oldest_pending: datetime | None = None
        newest_task: datetime | None = None

        for task in tasks:
            status_counts[task.status] += 1
            priority_counts[task.priority] += 1
            for tag in task.tags:
                tag_counts[tag] += 1

            if task.status == TaskStatus.BLOCKED:
                blocked_tasks.append(task.id)

            if task.status == TaskStatus.PENDING and task.created_at:
                if oldest_pending is None or task.created_at < oldest_pending:
                    oldest_pending = task.created_at

            if task.created_at:
                if newest_task is None or task.created_at > newest_task:
                    newest_task = task.created_at

        return RepoTaskStats(
            repo_name=repo_name,
            total_tasks=len(tasks),
            status_counts=dict(status_counts),
            priority_counts=dict(priority_counts),
            tag_counts=dict(tag_counts),
            blocked_tasks=blocked_tasks,
            oldest_pending=oldest_pending,
            newest_task=newest_task,
        )


__all__ = [
    "CrossRepoAggregator",
    "AggregatedTasks",
    "AggregationFilter",
    "RepoTaskStats",
    "CrossRepoSummary",
]
