"""Dependency Manager Module for Mahavishnu.

Provides automatic blocking and unblocking based on dependencies:
- Automatic task blocking when dependencies are added
- Automatic unblocking when dependencies complete
- Dependency status tracking
- Event notifications for status changes
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

from mahavishnu.core.dependency_graph import (
    DependencyEdge,
    DependencyGraph,
    DependencyStatus,
    DependencyType,
)

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task completion status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DependencyEvent(str, Enum):
    """Types of dependency events."""

    TASK_BLOCKED = "task_blocked"
    TASK_UNBLOCKED = "task_unblocked"
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    DEPENDENCY_SATISFIED = "dependency_satisfied"
    DEPENDENCY_FAILED = "dependency_failed"
    ALL_DEPENDENCIES_SATISFIED = "all_dependencies_satisfied"
    BLOCKING_TASKS_CHANGED = "blocking_tasks_changed"


@dataclass
class DependencyEventData:
    """Data for dependency events."""

    event_type: DependencyEvent
    task_id: str
    related_task_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_type": self.event_type.value,
            "task_id": self.task_id,
            "related_task_id": self.related_task_id,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class DependencyEventEmitter:
    """Emits dependency events to registered handlers."""

    def __init__(self) -> None:
        """Initialize event emitter."""
        self._handlers: dict[DependencyEvent, list[Callable[[DependencyEventData], None]]] = defaultdict(list)

    def on(self, event: DependencyEvent, handler: Callable[[DependencyEventData], None]) -> None:
        """Register an event handler.

        Args:
            event: Event type to listen for
            handler: Function to call when event occurs
        """
        self._handlers[event].append(handler)

    def off(self, event: DependencyEvent, handler: Callable[[DependencyEventData], None]) -> None:
        """Unregister an event handler.

        Args:
            event: Event type
            handler: Handler to remove
        """
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    def emit(self, event_data: DependencyEventData) -> None:
        """Emit an event to all registered handlers.

        Args:
            event_data: Event data to emit
        """
        for handler in self._handlers[event_data.event_type]:
            try:
                handler(event_data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_data.event_type}: {e}")

    def clear_handlers(self) -> None:
        """Clear all registered handlers."""
        self._handlers.clear()


class DependencyManager:
    """Manages task dependencies with automatic blocking/unblocking."""

    def __init__(
        self,
        graph: DependencyGraph | None = None,
        task_statuses: dict[str, TaskStatus] | None = None,
    ) -> None:
        """Initialize dependency manager.

        Args:
            graph: Optional dependency graph to use
            task_statuses: Optional initial task statuses
        """
        self._graph = graph or DependencyGraph()
        self._task_statuses: dict[str, TaskStatus] = task_statuses or {}
        self._emitter = DependencyEventEmitter()

    @property
    def graph(self) -> DependencyGraph:
        """Get the dependency graph."""
        return self._graph

    @property
    def event_emitter(self) -> DependencyEventEmitter:
        """Get the event emitter for registering handlers."""
        return self._emitter

    def add_task(
        self,
        task_id: str,
        status: TaskStatus = TaskStatus.PENDING,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a task with status tracking.

        Args:
            task_id: Unique task identifier
            status: Initial task status
            metadata: Optional task metadata
        """
        self._graph.add_task(task_id, metadata)
        self._task_statuses[task_id] = status

    def remove_task(self, task_id: str) -> list[str]:
        """Remove a task and handle dependent unblocking.

        Args:
            task_id: Task to remove

        Returns:
            List of affected task IDs
        """
        # Get dependents before removal
        dependents = self._graph.get_dependents(task_id)

        # Remove from graph
        affected = self._graph.remove_task(task_id)

        # Remove status
        self._task_statuses.pop(task_id, None)

        # Check if any dependents are now unblocked
        for dep_id in dependents:
            if not self._graph.is_blocked(dep_id):
                self._emit_unblocked(dep_id, task_id)

        return affected

    def update_task_status(self, task_id: str, status: TaskStatus) -> list[str]:
        """Update task status and handle dependency satisfaction.

        Args:
            task_id: Task to update
            status: New status

        Returns:
            List of newly unblocked task IDs
        """
        old_status = self._task_statuses.get(task_id)
        self._task_statuses[task_id] = status

        newly_unblocked: list[str] = []

        if status == TaskStatus.COMPLETED:
            newly_unblocked = self._handle_task_completed(task_id)
        elif status == TaskStatus.FAILED:
            self._handle_task_failed(task_id)
        elif status == TaskStatus.CANCELLED:
            newly_unblocked = self._handle_task_cancelled(task_id)

        return newly_unblocked

    def add_dependency(
        self,
        dependency_id: str,
        dependent_id: str,
        dependency_type: DependencyType = DependencyType.BLOCKS,
        metadata: dict[str, Any] | None = None,
    ) -> DependencyEdge:
        """Add a dependency and handle automatic blocking.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends
            dependency_type: Type of dependency
            metadata: Optional edge metadata

        Returns:
            The created dependency edge

        Raises:
            CircularDependencyError: If adding would create a cycle
        """
        # Add to graph
        edge = self._graph.add_dependency(
            dependency_id,
            dependent_id,
            dependency_type,
            metadata,
            validate=True,
        )

        # Ensure tasks have statuses
        if dependency_id not in self._task_statuses:
            self._task_statuses[dependency_id] = TaskStatus.PENDING
        if dependent_id not in self._task_statuses:
            self._task_statuses[dependent_id] = TaskStatus.PENDING

        # Check if dependency is already satisfied
        dep_status = self._task_statuses.get(dependency_id)
        if dep_status == TaskStatus.COMPLETED:
            edge.status = DependencyStatus.SATISFIED
        elif dep_status == TaskStatus.FAILED:
            edge.status = DependencyStatus.FAILED

        # Emit event
        self._emitter.emit(DependencyEventData(
            event_type=DependencyEvent.DEPENDENCY_ADDED,
            task_id=dependent_id,
            related_task_id=dependency_id,
            details={"dependency_type": dependency_type.value},
        ))

        # Check if dependent is now blocked
        if self._graph.is_blocked(dependent_id):
            self._emitter.emit(DependencyEventData(
                event_type=DependencyEvent.TASK_BLOCKED,
                task_id=dependent_id,
                related_task_id=dependency_id,
                details={"blocking_tasks": self._graph.get_blocking_tasks(dependent_id)},
            ))

        return edge

    def remove_dependency(self, dependency_id: str, dependent_id: str) -> bool:
        """Remove a dependency and handle automatic unblocking.

        Args:
            dependency_id: Task that was depended on
            dependent_id: Task that depended

        Returns:
            True if dependency was removed
        """
        result = self._graph.remove_dependency(dependency_id, dependent_id)

        if result:
            # Emit event
            self._emitter.emit(DependencyEventData(
                event_type=DependencyEvent.DEPENDENCY_REMOVED,
                task_id=dependent_id,
                related_task_id=dependency_id,
            ))

            # Check if dependent is now unblocked
            if not self._graph.is_blocked(dependent_id):
                self._emit_unblocked(dependent_id, dependency_id)

        return result

    def is_ready(self, task_id: str) -> bool:
        """Check if a task is ready to be worked on.

        A task is ready if:
        - All dependencies are satisfied
        - Task is not already completed/failed/cancelled

        Args:
            task_id: Task to check

        Returns:
            True if task is ready
        """
        if self._graph.is_blocked(task_id):
            return False

        status = self._task_statuses.get(task_id)
        return status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)

    def get_ready_tasks(self) -> list[str]:
        """Get all tasks ready to be worked on.

        Returns:
            List of ready task IDs
        """
        return [
            task_id
            for task_id in self._graph
            if self.is_ready(task_id)
        ]

    def get_blocked_tasks(self) -> list[str]:
        """Get all blocked tasks.

        Returns:
            List of blocked task IDs
        """
        return self._graph.get_blocked_tasks()

    def get_blocking_tasks(self, task_id: str) -> list[str]:
        """Get tasks blocking a given task.

        Args:
            task_id: Task to query

        Returns:
            List of blocking task IDs
        """
        return self._graph.get_blocking_tasks(task_id)

    def get_dependent_tasks(self, task_id: str) -> list[str]:
        """Get tasks that depend on a given task.

        Args:
            task_id: Task to query

        Returns:
            List of dependent task IDs
        """
        return self._graph.get_dependents(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """Get the status of a task.

        Args:
            task_id: Task to query

        Returns:
            Task status or None if not found
        """
        return self._task_statuses.get(task_id)

    def get_dependency_status(self, dependency_id: str, dependent_id: str) -> DependencyStatus | None:
        """Get the status of a dependency edge.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends

        Returns:
            Dependency status or None if edge doesn't exist
        """
        edge = self._graph.get_edge(dependency_id, dependent_id)
        return edge.status if edge else None

    def get_next_available_tasks(self, limit: int = 10) -> list[str]:
        """Get the next tasks that can be worked on.

        Returns tasks ordered by dependency depth (shallow first).

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of available task IDs
        """
        ready = self.get_ready_tasks()

        # Sort by depth (tasks with fewer dependencies first)
        ready.sort(key=lambda tid: self._graph.get_dependency_depth(tid))

        return ready[:limit]

    def can_complete_task(self, task_id: str) -> bool:
        """Check if a task can be marked as completed.

        A task can be completed if:
        - It exists
        - It's not already completed

        Args:
            task_id: Task to check

        Returns:
            True if task can be completed
        """
        status = self._task_statuses.get(task_id)
        return status is not None and status != TaskStatus.COMPLETED

    def get_completion_candidates(self, task_id: str) -> list[str]:
        """Get tasks that could become available if this task completes.

        Args:
            task_id: Task to check

        Returns:
            List of task IDs that would become ready
        """
        if self._task_statuses.get(task_id) == TaskStatus.COMPLETED:
            return []  # Already completed

        dependents = self._graph.get_dependents(task_id)
        candidates: list[str] = []

        for dep_id in dependents:
            # Check if this task is the only blocker
            blockers = self._graph.get_blocking_tasks(dep_id)
            if blockers == [task_id]:
                candidates.append(dep_id)

        return candidates

    def _handle_task_completed(self, task_id: str) -> list[str]:
        """Handle task completion - satisfy dependencies.

        Args:
            task_id: Completed task

        Returns:
            List of newly unblocked tasks
        """
        newly_unblocked: list[str] = []
        dependents = self._graph.get_dependents(task_id)

        for dep_id in dependents:
            edge = self._graph.get_edge(task_id, dep_id)
            if edge and edge.status == DependencyStatus.PENDING:
                # Mark edge as satisfied
                edge.status = DependencyStatus.SATISFIED

                # Emit event
                self._emitter.emit(DependencyEventData(
                    event_type=DependencyEvent.DEPENDENCY_SATISFIED,
                    task_id=dep_id,
                    related_task_id=task_id,
                ))

                # Check if dependent is now unblocked
                if not self._graph.is_blocked(dep_id):
                    self._emit_unblocked(dep_id, task_id)
                    newly_unblocked.append(dep_id)

        return newly_unblocked

    def _handle_task_failed(self, task_id: str) -> list[str]:
        """Handle task failure - mark dependencies as failed.

        Args:
            task_id: Failed task

        Returns:
            List of affected task IDs
        """
        affected: list[str] = []
        dependents = self._graph.get_dependents(task_id)

        for dep_id in dependents:
            edge = self._graph.get_edge(task_id, dep_id)
            if edge:
                # Mark edge as failed
                edge.status = DependencyStatus.FAILED

                # Emit event
                self._emitter.emit(DependencyEventData(
                    event_type=DependencyEvent.DEPENDENCY_FAILED,
                    task_id=dep_id,
                    related_task_id=task_id,
                ))

                affected.append(dep_id)

        return affected

    def _handle_task_cancelled(self, task_id: str) -> list[str]:
        """Handle task cancellation - update dependencies.

        Args:
            task_id: Cancelled task

        Returns:
            List of newly unblocked tasks
        """
        newly_unblocked: list[str] = []
        dependents = self._graph.get_dependents(task_id)

        for dep_id in dependents:
            edge = self._graph.get_edge(task_id, dep_id)
            if edge:
                # Mark edge as cancelled
                edge.status = DependencyStatus.CANCELLED

                # Check if dependent is now unblocked
                # (cancelled dependencies don't block)
                if not self._graph.is_blocked(dep_id):
                    self._emit_unblocked(dep_id, task_id)
                    newly_unblocked.append(dep_id)

        return newly_unblocked

    def _emit_unblocked(self, task_id: str, by_task_id: str) -> None:
        """Emit task unblocked event.

        Args:
            task_id: Task that was unblocked
            by_task_id: Task that caused unblocking
        """
        self._emitter.emit(DependencyEventData(
            event_type=DependencyEvent.TASK_UNBLOCKED,
            task_id=task_id,
            related_task_id=by_task_id,
        ))

        # Also emit all dependencies satisfied if applicable
        if not self._graph.is_blocked(task_id):
            self._emitter.emit(DependencyEventData(
                event_type=DependencyEvent.ALL_DEPENDENCIES_SATISFIED,
                task_id=task_id,
            ))

    def to_dict(self) -> dict[str, Any]:
        """Serialize manager state to dictionary."""
        return {
            "graph": self._graph.to_dict(),
            "task_statuses": {
                tid: status.value for tid, status in self._task_statuses.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyManager:
        """Deserialize manager state from dictionary."""
        graph = DependencyGraph.from_dict(data.get("graph", {}))
        statuses = {
            tid: TaskStatus(status)
            for tid, status in data.get("task_statuses", {}).items()
        }
        return cls(graph=graph, task_statuses=statuses)

    def __len__(self) -> int:
        """Return number of tasks."""
        return len(self._graph)

    def __contains__(self, task_id: str) -> bool:
        """Check if task exists."""
        return task_id in self._graph


def create_dependency_manager() -> DependencyManager:
    """Create a new dependency manager.

    Returns:
        New DependencyManager instance
    """
    return DependencyManager()
