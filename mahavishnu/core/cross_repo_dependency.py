"""Cross-Repository Task Dependency Linker for Mahavishnu.

Links tasks across repositories with:
- Cross-repo dependency creation and tracking
- Cycle detection and prevention
- Dependency status management
- Blocking chain analysis

Usage:
    from mahavishnu.core.cross_repo_dependency import CrossRepoDependencyLinker

    linker = CrossRepoDependencyLinker(task_store)

    # Create a cross-repo dependency
    dep = await linker.create_dependency(
        source_task_id="task-1",
        target_task_id="task-2",
        dependency_type=DependencyType.BLOCKS,
    )

    # Get blocking chain
    chain = linker.get_blocking_chain("task-3")
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskStore

logger = logging.getLogger(__name__)


class DependencyType(str, Enum):
    """Type of dependency between tasks."""

    BLOCKS = "blocks"  # Source task blocks target (target waits for source)
    REQUIRES = "requires"  # Source requires target (source waits for target)
    RELATED = "related"  # Tasks are related but no blocking


class DependencyStatus(str, Enum):
    """Status of a dependency relationship."""

    PENDING = "pending"  # Dependency not yet satisfied
    SATISFIED = "satisfied"  # Dependency satisfied (dependency task completed)
    FAILED = "failed"  # Dependency cannot be satisfied
    BLOCKED = "blocked"  # Dependency is blocked by another dependency


class CrossRepoDependencyError(Exception):
    """Error in cross-repository dependency operations.

    Attributes:
        message: Error message
        details: Additional context about the error
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass
class CrossRepoDependency:
    """A dependency relationship between tasks in different repositories.

    Attributes:
        id: Unique identifier for this dependency
        source_task_id: ID of the source (dependent) task
        source_repo: Repository of the source task
        target_task_id: ID of the target (dependency) task
        target_repo: Repository of the target task
        dependency_type: Type of dependency relationship
        status: Current status of the dependency
        created_at: When the dependency was created
        metadata: Additional metadata
    """

    id: str
    source_task_id: str
    source_repo: str
    target_task_id: str
    target_repo: str
    dependency_type: DependencyType
    status: DependencyStatus = DependencyStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_cross_repo(self) -> bool:
        """Check if this is a cross-repository dependency."""
        return self.source_repo != self.target_repo

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "source_task_id": self.source_task_id,
            "source_repo": self.source_repo,
            "target_task_id": self.target_task_id,
            "target_repo": self.target_repo,
            "dependency_type": self.dependency_type.value,
            "status": self.status.value,
            "is_cross_repo": self.is_cross_repo,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class CrossRepoDependencyLinker:
    """Links tasks across repositories with dependency relationships.

    Features:
    - Create and track cross-repo dependencies
    - Detect and prevent circular dependencies
    - Update dependency status based on task completion
    - Analyze blocking chains

    Example:
        linker = CrossRepoDependencyLinker(task_store)

        # Create dependency: task-1 blocks task-2
        dep = await linker.create_dependency(
            source_task_id="task-1",
            target_task_id="task-2",
            dependency_type=DependencyType.BLOCKS,
        )

        # Get all dependencies for a task
        deps = linker.get_dependencies_for_task("task-1")

        # Get blocking chain
        chain = linker.get_blocking_chain("task-3")
    """

    def __init__(self, task_store: TaskStore) -> None:
        """Initialize the linker.

        Args:
            task_store: TaskStore for fetching task information
        """
        self.task_store = task_store
        self._dependencies: dict[str, CrossRepoDependency] = {}
        self._task_dependencies: dict[str, list[str]] = defaultdict(list)  # task_id -> dep_ids where task is source
        self._task_dependents: dict[str, list[str]] = defaultdict(list)  # task_id -> dep_ids where task is target

    async def create_dependency(
        self,
        source_task_id: str,
        target_task_id: str,
        dependency_type: DependencyType,
        metadata: dict[str, Any] | None = None,
    ) -> CrossRepoDependency:
        """Create a dependency relationship between two tasks.

        Args:
            source_task_id: ID of the source (dependent) task
            target_task_id: ID of the target (dependency) task
            dependency_type: Type of dependency
            metadata: Optional metadata

        Returns:
            Created CrossRepoDependency

        Raises:
            CrossRepoDependencyError: If dependency is invalid or creates a cycle
        """
        # Prevent self-dependency
        if source_task_id == target_task_id:
            raise CrossRepoDependencyError(
                "Task cannot depend on itself",
                details={"task_id": source_task_id},
            )

        # Fetch tasks to get repository info
        source_task = await self._get_task(source_task_id)
        target_task = await self._get_task(target_task_id)

        if not source_task:
            raise CrossRepoDependencyError(
                f"Source task not found: {source_task_id}",
                details={"source_task_id": source_task_id},
            )

        if not target_task:
            raise CrossRepoDependencyError(
                f"Target task not found: {target_task_id}",
                details={"target_task_id": target_task_id},
            )

        # Check for existing dependency
        for dep_id in self._task_dependencies.get(source_task_id, []):
            existing = self._dependencies.get(dep_id)
            if existing and existing.target_task_id == target_task_id:
                raise CrossRepoDependencyError(
                    "Dependency already exists",
                    details={
                        "source_task_id": source_task_id,
                        "target_task_id": target_task_id,
                        "existing_dep_id": dep_id,
                    },
                )

        # Check for cycles
        if self._would_create_cycle(source_task_id, target_task_id, dependency_type):
            raise CrossRepoDependencyError(
                "Dependency would create a cycle",
                details={
                    "source_task_id": source_task_id,
                    "target_task_id": target_task_id,
                },
            )

        # Create the dependency
        dep_id = str(uuid.uuid4())
        dependency = CrossRepoDependency(
            id=dep_id,
            source_task_id=source_task_id,
            source_repo=source_task.repository,
            target_task_id=target_task_id,
            target_repo=target_task.repository,
            dependency_type=dependency_type,
            status=DependencyStatus.PENDING,
            metadata=metadata or {},
        )

        # Store the dependency
        self._dependencies[dep_id] = dependency
        self._task_dependencies[source_task_id].append(dep_id)
        self._task_dependents[target_task_id].append(dep_id)

        logger.info(
            f"Created cross-repo dependency: {source_task_id} -> {target_task_id} "
            f"({source_task.repository} -> {target_task.repository})"
        )

        return dependency

    def remove_dependency(self, dep_id: str) -> bool:
        """Remove a dependency.

        Args:
            dep_id: ID of dependency to remove

        Returns:
            True if removed, False if not found
        """
        dep = self._dependencies.get(dep_id)
        if not dep:
            return False

        # Remove from indexes
        if dep_id in self._task_dependencies.get(dep.source_task_id, []):
            self._task_dependencies[dep.source_task_id].remove(dep_id)

        if dep_id in self._task_dependents.get(dep.target_task_id, []):
            self._task_dependents[dep.target_task_id].remove(dep_id)

        # Remove dependency
        del self._dependencies[dep_id]

        logger.info(f"Removed dependency: {dep_id}")
        return True

    def get_dependencies_for_task(self, task_id: str) -> list[CrossRepoDependency]:
        """Get all dependencies where the task is the source.

        Args:
            task_id: Task ID to get dependencies for

        Returns:
            List of dependencies
        """
        dep_ids = self._task_dependencies.get(task_id, [])
        return [self._dependencies[did] for did in dep_ids if did in self._dependencies]

    def get_dependents_of_task(self, task_id: str) -> list[CrossRepoDependency]:
        """Get all dependencies where the task is the target (tasks that block this task).

        For BLOCKS relationships: if A blocks B, calling this on B returns the
        dependency showing that A blocks B.

        Args:
            task_id: Task ID to get dependents for

        Returns:
            List of dependencies where this task is the target
        """
        dep_ids = self._task_dependents.get(task_id, [])
        return [self._dependencies[did] for did in dep_ids if did in self._dependencies]

    def get_blocked_tasks(self, task_id: str) -> list[CrossRepoDependency]:
        """Get all dependencies where this task is the blocker (tasks blocked by this task).

        For BLOCKS relationships: if A blocks B, calling this on A returns the
        dependency showing that A blocks B.

        Args:
            task_id: Task ID to get blocked tasks for

        Returns:
            List of dependencies where this task is the source (blocks others)
        """
        dep_ids = self._task_dependencies.get(task_id, [])
        return [self._dependencies[did] for did in dep_ids if did in self._dependencies]

    def get_cross_repo_dependencies(self) -> list[CrossRepoDependency]:
        """Get all cross-repository dependencies.

        Returns:
            List of cross-repo dependencies
        """
        return [dep for dep in self._dependencies.values() if dep.is_cross_repo]

    def get_dependencies_by_repo(self, repo_name: str) -> list[CrossRepoDependency]:
        """Get dependencies involving a specific repository.

        Args:
            repo_name: Repository name

        Returns:
            List of dependencies involving the repo
        """
        return [
            dep for dep in self._dependencies.values()
            if dep.source_repo == repo_name or dep.target_repo == repo_name
        ]

    def get_blocking_chain(self, task_id: str) -> list[CrossRepoDependency]:
        """Get the full blocking chain for a task.

        Follows the chain of dependencies to find all upstream blockers.

        Args:
            task_id: Task ID to analyze

        Returns:
            List of dependencies in blocking order (immediate blockers first)
        """
        chain: list[CrossRepoDependency] = []
        visited: set[str] = set()
        queue = [task_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            # Get dependencies where current task is the target
            for dep in self.get_dependents_of_task(current_id):
                if dep.dependency_type == DependencyType.BLOCKS:
                    chain.append(dep)
                    queue.append(dep.source_task_id)

        return chain

    async def update_dependency_status(self, dep_id: str) -> CrossRepoDependency:
        """Update the status of a dependency based on task states.

        Args:
            dep_id: Dependency ID to update

        Returns:
            Updated dependency
        """
        dep = self._dependencies.get(dep_id)
        if not dep:
            raise CrossRepoDependencyError(f"Dependency not found: {dep_id}")

        # Fetch tasks to get current status
        source_task = await self._get_task(dep.source_task_id)
        target_task = await self._get_task(dep.target_task_id)

        # For BLOCKS: satisfied when source completes
        # For REQUIRES: satisfied when target completes
        if dep.dependency_type == DependencyType.BLOCKS:
            if source_task:
                if source_task.status == TaskStatus.COMPLETED:
                    dep.status = DependencyStatus.SATISFIED
                elif source_task.status == TaskStatus.FAILED:
                    dep.status = DependencyStatus.FAILED
                elif source_task.status == TaskStatus.BLOCKED:
                    dep.status = DependencyStatus.BLOCKED
        elif dep.dependency_type == DependencyType.REQUIRES:
            if target_task:
                if target_task.status == TaskStatus.COMPLETED:
                    dep.status = DependencyStatus.SATISFIED
                elif target_task.status == TaskStatus.FAILED:
                    dep.status = DependencyStatus.FAILED

        return dep

    def update_all_statuses(self, task_statuses: dict[str, TaskStatus]) -> int:
        """Update all dependency statuses based on provided task statuses.

        Args:
            task_statuses: Map of task ID to status

        Returns:
            Number of dependencies updated
        """
        updated = 0

        for dep in self._dependencies.values():
            old_status = dep.status

            if dep.dependency_type == DependencyType.BLOCKS:
                # Source task blocks target
                source_status = task_statuses.get(dep.source_task_id)
                if source_status == TaskStatus.COMPLETED:
                    dep.status = DependencyStatus.SATISFIED
                elif source_status == TaskStatus.FAILED:
                    dep.status = DependencyStatus.FAILED
                elif source_status == TaskStatus.BLOCKED:
                    dep.status = DependencyStatus.BLOCKED

            elif dep.dependency_type == DependencyType.REQUIRES:
                # Source requires target to complete first
                target_status = task_statuses.get(dep.target_task_id)
                if target_status == TaskStatus.COMPLETED:
                    dep.status = DependencyStatus.SATISFIED
                elif target_status == TaskStatus.FAILED:
                    dep.status = DependencyStatus.FAILED

            if dep.status != old_status:
                updated += 1

        return updated

    async def _get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        try:
            return await self.task_store.get(task_id)
        except Exception:
            return None

    def _would_create_cycle(
        self,
        source_task_id: str,
        target_task_id: str,
        dependency_type: DependencyType,
    ) -> bool:
        """Check if creating this dependency would create a cycle.

        Uses BFS to check if there's already a path from target to source.
        """
        # For BLOCKS: source -> target (target waits for source)
        # A cycle would be if target already (directly or indirectly) blocks source

        visited: set[str] = set()
        queue = [target_task_id]

        while queue:
            current = queue.pop(0)
            if current == source_task_id:
                return True  # Found a path back to source

            if current in visited:
                continue
            visited.add(current)

            # Get tasks that current task blocks (where current is source of BLOCKS)
            for dep in self.get_dependencies_for_task(current):
                if dep.dependency_type == DependencyType.BLOCKS:
                    queue.append(dep.target_task_id)

            # Get tasks that current requires (where current is source of REQUIRES)
            for dep in self.get_dependencies_for_task(current):
                if dep.dependency_type == DependencyType.REQUIRES:
                    queue.append(dep.target_task_id)

        return False

    def get_all_dependencies(self) -> list[CrossRepoDependency]:
        """Get all dependencies.

        Returns:
            List of all dependencies
        """
        return list(self._dependencies.values())

    def get_dependency_count(self) -> dict[str, int]:
        """Get counts of dependencies by type.

        Returns:
            Dictionary with counts
        """
        counts: dict[str, int] = {
            "total": len(self._dependencies),
            "cross_repo": 0,
            "same_repo": 0,
            "by_type": {t.value: 0 for t in DependencyType},
            "by_status": {s.value: 0 for s in DependencyStatus},
        }

        for dep in self._dependencies.values():
            if dep.is_cross_repo:
                counts["cross_repo"] += 1
            else:
                counts["same_repo"] += 1

            counts["by_type"][dep.dependency_type.value] += 1
            counts["by_status"][dep.status.value] += 1

        return counts


__all__ = [
    "CrossRepoDependencyLinker",
    "CrossRepoDependency",
    "DependencyType",
    "DependencyStatus",
    "CrossRepoDependencyError",
]
