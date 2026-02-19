"""Cross-Repository Task Filter for Mahavishnu.

Provides advanced filtering capabilities across repositories:
- Filter by repository names, roles, tags
- Filter by task status, priority, tags
- Date range filtering
- Text search across tasks
- Pagination and sorting support

Usage:
    from mahavishnu.core.cross_repo_filter import CrossRepoFilter, FilterCriteria

    filter = CrossRepoFilter(task_store, repo_manager)

    # Filter by status and priority
    criteria = FilterCriteria(
        statuses=[TaskStatus.IN_PROGRESS],
        priorities=[TaskPriority.HIGH],
    )
    result = await filter.filter(criteria)

    # Filter by repository role
    criteria = FilterCriteria(repo_roles=["orchestrator"])
    result = await filter.filter(criteria)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore, TaskListFilter

logger = logging.getLogger(__name__)


class SortOrder(str, Enum):
    """Sort order for results."""

    ASC = "asc"
    DESC = "desc"


@dataclass
class DateRangeFilter:
    """Date range filter for task creation dates.

    Attributes:
        last_n_days: Filter to last N days (mutually exclusive with start/end)
        start_date: Explicit start date
        end_date: Explicit end date
    """

    last_n_days: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None

    def get_date_range(self) -> tuple[datetime, datetime]:
        """Get the date range as (start, end) tuple."""
        end = datetime.now(UTC)

        if self.last_n_days is not None:
            start = end - timedelta(days=self.last_n_days)
            return start, end

        start = self.start_date or (end - timedelta(days=30))
        end = self.end_date or end

        return start, end


@dataclass
class FilterCriteria:
    """Criteria for filtering tasks across repositories.

    Attributes:
        repo_names: Filter to specific repository names
        repo_tags: Filter to repositories with these tags
        repo_roles: Filter to repositories with these roles
        statuses: Filter to specific task statuses
        priorities: Filter to specific task priorities
        tags: Filter to tasks with these tags (ANY match)
        tags_all: Filter to tasks with ALL these tags
        date_range: Filter by creation date range
        text_search: Text search in task fields
        search_fields: Fields to search in (default: title, description)
        exclude_completed: Exclude completed tasks
        sort_by: Field to sort by (priority, created_at, status)
        sort_order: Sort order (asc, desc)
        page: Page number (1-indexed)
        page_size: Number of results per page
    """

    repo_names: list[str] | None = None
    repo_tags: list[str] | None = None
    repo_roles: list[str] | None = None
    statuses: list[TaskStatus] | None = None
    priorities: list[TaskPriority] | None = None
    tags: list[str] | None = None
    tags_all: list[str] | None = None
    date_range: DateRangeFilter | None = None
    text_search: str | None = None
    search_fields: list[str] | None = None
    exclude_completed: bool = False
    sort_by: str = "created_at"
    sort_order: SortOrder | str = SortOrder.DESC
    page: int = 1
    page_size: int = 50


@dataclass
class FilterResult:
    """Result of a filter operation.

    Attributes:
        tasks: List of matching tasks
        total_count: Total number of matching tasks (before pagination)
        filtered_count: Number of tasks after all filters applied
        page: Current page number
        page_size: Number of results per page
        total_pages: Total number of pages
        applied_filters: Summary of filters that were applied
    """

    tasks: list[Task] = field(default_factory=list)
    total_count: int = 0
    filtered_count: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    applied_filters: dict[str, Any] = field(default_factory=dict)

    @property
    def has_more(self) -> bool:
        """Check if there are more pages."""
        return self.page < self.total_pages

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "total_count": self.total_count,
            "filtered_count": self.filtered_count,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_more": self.has_more,
            "applied_filters": self.applied_filters,
        }


class CrossRepoFilter:
    """Filters tasks across multiple repositories.

    Provides flexible filtering with:
    - Repository-level filters (name, role, tags)
    - Task-level filters (status, priority, tags)
    - Date range filtering
    - Text search
    - Pagination and sorting

    Example:
        filter = CrossRepoFilter(task_store, repo_manager)

        # Filter high priority in-progress tasks
        criteria = FilterCriteria(
            statuses=[TaskStatus.IN_PROGRESS],
            priorities=[TaskPriority.HIGH, TaskPriority.CRITICAL],
        )
        result = await filter.filter(criteria)

        # Filter by repository role with date range
        criteria = FilterCriteria(
            repo_roles=["orchestrator"],
            date_range=DateRangeFilter(last_n_days=7),
        )
        result = await filter.filter(criteria)
    """

    def __init__(
        self,
        task_store: TaskStore,
        repo_manager: Any,  # RepositoryManager type
    ) -> None:
        """Initialize the filter.

        Args:
            task_store: TaskStore instance for task queries
            repo_manager: RepositoryManager for repo metadata
        """
        self.task_store = task_store
        self.repo_manager = repo_manager

    async def filter(self, criteria: FilterCriteria) -> FilterResult:
        """Filter tasks based on criteria.

        Args:
            criteria: Filter criteria to apply

        Returns:
            FilterResult with matching tasks
        """
        # Build the base query
        applied_filters: dict[str, Any] = {}

        # Resolve repo names from roles/tags if needed
        effective_repo_names = list(criteria.repo_names) if criteria.repo_names else None

        if criteria.repo_roles:
            resolved = await self._resolve_repos_by_roles(criteria.repo_roles)
            if effective_repo_names is None:
                effective_repo_names = resolved
            else:
                effective_repo_names = list(set(effective_repo_names) & set(resolved))
            applied_filters["repo_roles"] = criteria.repo_roles

        if criteria.repo_tags:
            resolved = await self._resolve_repos_by_tags(criteria.repo_tags)
            if effective_repo_names is None:
                effective_repo_names = resolved
            else:
                effective_repo_names = list(set(effective_repo_names) & set(resolved))
            applied_filters["repo_tags"] = criteria.repo_tags

        if effective_repo_names:
            applied_filters["repo_names"] = effective_repo_names

        # Fetch tasks
        if criteria.statuses and len(criteria.statuses) == 1:
            status_filter = criteria.statuses[0]
        else:
            status_filter = None

        if criteria.priorities and len(criteria.priorities) == 1:
            priority_filter = criteria.priorities[0]
        else:
            priority_filter = None

        # Build task list filter
        task_filter = TaskListFilter(
            status=status_filter,
            priority=priority_filter,
            tags=criteria.tags_all,  # Use AND logic for tags_all
            limit=10000,  # High limit, we'll paginate after
        )

        all_tasks = await self.task_store.list(task_filter)

        # Apply in-memory filters
        filtered_tasks = self._apply_filters(all_tasks, criteria, effective_repo_names)

        # Record applied filters
        if criteria.statuses:
            applied_filters["statuses"] = [s.value for s in criteria.statuses]
        if criteria.priorities:
            applied_filters["priorities"] = [p.value for p in criteria.priorities]
        if criteria.tags:
            applied_filters["tags"] = criteria.tags
        if criteria.tags_all:
            applied_filters["tags_all"] = criteria.tags_all
        if criteria.date_range:
            applied_filters["date_range"] = {
                "last_n_days": criteria.date_range.last_n_days,
                "start": criteria.date_range.start_date.isoformat() if criteria.date_range.start_date else None,
                "end": criteria.date_range.end_date.isoformat() if criteria.date_range.end_date else None,
            }
        if criteria.text_search:
            applied_filters["text_search"] = criteria.text_search
        if criteria.exclude_completed:
            applied_filters["exclude_completed"] = True

        # Sort
        sorted_tasks = self._sort_tasks(filtered_tasks, criteria.sort_by, criteria.sort_order)

        # Calculate pagination
        total_count = len(sorted_tasks)
        total_pages = max(1, (total_count + criteria.page_size - 1) // criteria.page_size)

        # Apply pagination
        start_idx = (criteria.page - 1) * criteria.page_size
        end_idx = start_idx + criteria.page_size
        paginated_tasks = sorted_tasks[start_idx:end_idx]

        return FilterResult(
            tasks=paginated_tasks,
            total_count=total_count,
            filtered_count=total_count,
            page=criteria.page,
            page_size=criteria.page_size,
            total_pages=total_pages,
            applied_filters=applied_filters,
        )

    async def _resolve_repos_by_roles(self, roles: list[str]) -> list[str]:
        """Resolve repository names from roles."""
        repo_names: list[str] = []

        try:
            for role in roles:
                repos = self.repo_manager.get_repos_by_role(role)
                for repo in repos:
                    repo_names.append(repo.name)
        except Exception as e:
            logger.warning(f"Failed to resolve repos by roles: {e}")

        return repo_names

    async def _resolve_repos_by_tags(self, tags: list[str]) -> list[str]:
        """Resolve repository names from tags."""
        repo_names: list[str] = []

        try:
            for tag in tags:
                repos = self.repo_manager.get_repos_by_tag(tag)
                for repo in repos:
                    repo_names.append(repo.name)
        except Exception as e:
            logger.warning(f"Failed to resolve repos by tags: {e}")

        return repo_names

    def _apply_filters(
        self,
        tasks: list[Task],
        criteria: FilterCriteria,
        effective_repo_names: list[str] | None,
    ) -> list[Task]:
        """Apply all filters to the task list."""
        result = tasks

        # Filter by repository names
        if effective_repo_names:
            result = [t for t in result if t.repository in effective_repo_names]

        # Filter by statuses (always if specified, as store may not filter)
        if criteria.statuses:
            result = [t for t in result if t.status in criteria.statuses]

        # Filter by priorities (always if specified, as store may not filter)
        if criteria.priorities:
            result = [t for t in result if t.priority in criteria.priorities]

        # Filter by tags (ANY match)
        if criteria.tags:
            result = [
                t for t in result
                if any(tag in t.tags for tag in criteria.tags)
            ]

        # Filter by date range
        if criteria.date_range:
            start, end = criteria.date_range.get_date_range()
            result = [
                t for t in result
                if t.created_at and start <= t.created_at <= end
            ]

        # Text search
        if criteria.text_search:
            search_fields = criteria.search_fields or ["title", "description"]
            search_pattern = re.compile(re.escape(criteria.text_search), re.IGNORECASE)

            def matches_search(task: Task) -> bool:
                for field in search_fields:
                    value = getattr(task, field, None)
                    if value and search_pattern.search(str(value)):
                        return True
                return False

            result = [t for t in result if matches_search(t)]

        # Exclude completed
        if criteria.exclude_completed:
            result = [t for t in result if t.status != TaskStatus.COMPLETED]

        return result

    def _sort_tasks(
        self,
        tasks: list[Task],
        sort_by: str,
        sort_order: SortOrder | str,
    ) -> list[Task]:
        """Sort tasks by the specified field."""
        reverse = sort_order == SortOrder.DESC or sort_order == "desc"

        def sort_key(task: Task) -> Any:
            if sort_by == "priority":
                # Custom priority order: critical > high > medium > low
                priority_order = {
                    TaskPriority.CRITICAL: 0,
                    TaskPriority.HIGH: 1,
                    TaskPriority.MEDIUM: 2,
                    TaskPriority.LOW: 3,
                }
                return priority_order.get(task.priority, 99)
            elif sort_by == "status":
                # Custom status order
                status_order = {
                    TaskStatus.BLOCKED: 0,
                    TaskStatus.IN_PROGRESS: 1,
                    TaskStatus.PENDING: 2,
                    TaskStatus.COMPLETED: 3,
                    TaskStatus.CANCELLED: 4,
                    TaskStatus.FAILED: 5,
                }
                return status_order.get(task.status, 99)
            elif sort_by == "created_at":
                return task.created_at or datetime.min.replace(tzinfo=UTC)
            elif sort_by == "updated_at":
                return task.updated_at or datetime.min.replace(tzinfo=UTC)
            elif sort_by == "title":
                return task.title.lower()
            elif sort_by == "repository":
                return task.repository.lower()
            else:
                # Default to created_at
                return task.created_at or datetime.min.replace(tzinfo=UTC)

        return sorted(tasks, key=sort_key, reverse=reverse)

    async def get_available_filters(self) -> dict[str, Any]:
        """Get available filter options based on current data.

        Returns:
            Dictionary with available values for each filter type
        """
        tasks = await self.task_store.list(TaskListFilter(limit=10000))

        statuses = set()
        priorities = set()
        tags = set()
        repos = set()

        for task in tasks:
            statuses.add(task.status.value)
            priorities.add(task.priority.value)
            repos.add(task.repository)
            for tag in task.tags:
                tags.add(tag)

        # Get available repo roles and tags
        repo_roles = set()
        repo_tags = set()

        try:
            all_repos = self.repo_manager.list_repos()
            for repo in all_repos:
                if hasattr(repo, "role"):
                    repo_roles.add(repo.role)
                if hasattr(repo, "tags"):
                    repo_tags.update(repo.tags)
        except Exception as e:
            logger.warning(f"Could not get repo metadata: {e}")

        return {
            "statuses": sorted(statuses),
            "priorities": sorted(priorities),
            "tags": sorted(tags),
            "repositories": sorted(repos),
            "repo_roles": sorted(repo_roles),
            "repo_tags": sorted(repo_tags),
            "sort_options": ["priority", "status", "created_at", "updated_at", "title", "repository"],
            "sort_orders": ["asc", "desc"],
        }


__all__ = [
    "CrossRepoFilter",
    "FilterCriteria",
    "FilterResult",
    "DateRangeFilter",
    "SortOrder",
]
