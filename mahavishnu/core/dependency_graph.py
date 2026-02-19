"""Dependency Graph Module for Mahavishnu.

Provides dependency graph data structures and operations including:
- DAG (Directed Acyclic Graph) for task dependencies
- Cycle detection algorithms
- Dependency CRUD operations
- Dependency queries and traversals
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DependencyType(str, Enum):
    """Type of dependency relationship."""

    BLOCKS = "blocks"  # This task blocks the dependent
    REQUIRES = "requires"  # This task requires the dependency
    RELATED = "related"  # Related but not blocking
    SUBTASK = "subtask"  # Is a subtask of


class DependencyStatus(str, Enum):
    """Status of a dependency relationship."""

    PENDING = "pending"  # Dependency not yet satisfied
    SATISFIED = "satisfied"  # Dependency completed
    FAILED = "failed"  # Dependency failed, blocks dependent
    CANCELLED = "cancelled"  # Dependency was cancelled


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected."""

    def __init__(self, cycle: list[str]):
        """Initialize with the detected cycle.

        Args:
            cycle: List of task IDs forming the cycle
        """
        self.cycle = cycle
        cycle_str = " -> ".join(cycle)
        super().__init__(f"Circular dependency detected: {cycle_str}")


class DependencyError(Exception):
    """Base exception for dependency errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """Initialize with message and optional details."""
        self.message = message
        self.details = details or {}
        super().__init__(message)


@dataclass
class DependencyEdge:
    """Represents an edge in the dependency graph."""

    dependency_id: str  # ID of the task being depended on
    dependent_id: str  # ID of the task that depends
    dependency_type: DependencyType = DependencyType.BLOCKS
    status: DependencyStatus = DependencyStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "dependency_id": self.dependency_id,
            "dependent_id": self.dependent_id,
            "dependency_type": self.dependency_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class Dependency(BaseModel):
    """Pydantic model for dependency relationship."""

    id: str = Field(default_factory=lambda: "")
    dependency_id: str
    dependent_id: str
    dependency_type: DependencyType = DependencyType.BLOCKS
    status: DependencyStatus = DependencyStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "dependency_id": self.dependency_id,
            "dependent_id": self.dependent_id,
            "dependency_type": self.dependency_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }


class DependencyGraph:
    """Manages task dependencies as a directed acyclic graph."""

    def __init__(self) -> None:
        """Initialize empty dependency graph."""
        # Adjacency lists
        self._dependents: dict[str, set[str]] = defaultdict(set)  # task -> tasks that depend on it
        self._dependencies: dict[str, set[str]] = defaultdict(set)  # task -> tasks it depends on
        self._edges: dict[tuple[str, str], DependencyEdge] = {}
        self._task_metadata: dict[str, dict[str, Any]] = {}

    def add_task(self, task_id: str, metadata: dict[str, Any] | None = None) -> None:
        """Add a task to the graph.

        Args:
            task_id: Unique task identifier
            metadata: Optional task metadata
        """
        self._task_metadata[task_id] = metadata or {}

    def remove_task(self, task_id: str) -> list[str]:
        """Remove a task and all its dependencies.

        Args:
            task_id: Task to remove

        Returns:
            List of affected task IDs
        """
        affected = set()

        # Remove all edges involving this task
        dependents = list(self._dependents[task_id])
        dependencies = list(self._dependencies[task_id])

        for dep_id in dependents:
            self.remove_dependency(task_id, dep_id)
            affected.add(dep_id)

        for dep_id in dependencies:
            self.remove_dependency(dep_id, task_id)
            affected.add(dep_id)

        # Clean up task data
        self._dependents.pop(task_id, None)
        self._dependencies.pop(task_id, None)
        self._task_metadata.pop(task_id, None)

        return list(affected)

    def add_dependency(
        self,
        dependency_id: str,
        dependent_id: str,
        dependency_type: DependencyType = DependencyType.BLOCKS,
        metadata: dict[str, Any] | None = None,
        validate: bool = True,
    ) -> DependencyEdge:
        """Add a dependency relationship.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends on the other
            dependency_type: Type of dependency relationship
            metadata: Optional metadata for the edge
            validate: Whether to validate for cycles (default True)

        Returns:
            The created DependencyEdge

        Raises:
            CircularDependencyError: If adding would create a cycle
            DependencyError: If dependency already exists
        """
        # Check for existing edge
        edge_key = (dependency_id, dependent_id)
        if edge_key in self._edges:
            raise DependencyError(
                f"Dependency already exists: {dependency_id} -> {dependent_id}",
                {"dependency_id": dependency_id, "dependent_id": dependent_id},
            )

        # Add to adjacency lists first for cycle detection
        self._dependents[dependency_id].add(dependent_id)
        self._dependencies[dependent_id].add(dependency_id)

        # Validate for cycles
        if validate and self._would_create_cycle(dependency_id, dependent_id):
            # Remove the edge we just added
            self._dependents[dependency_id].discard(dependent_id)
            self._dependencies[dependent_id].discard(dependency_id)

            # Find the cycle for error message
            cycle = self._find_cycle_path(dependency_id, dependent_id)
            raise CircularDependencyError(cycle)

        # Create edge
        edge = DependencyEdge(
            dependency_id=dependency_id,
            dependent_id=dependent_id,
            dependency_type=dependency_type,
            metadata=metadata or {},
        )
        self._edges[edge_key] = edge

        # Ensure both tasks exist in metadata
        if dependency_id not in self._task_metadata:
            self._task_metadata[dependency_id] = {}
        if dependent_id not in self._task_metadata:
            self._task_metadata[dependent_id] = {}

        logger.debug(
            f"Added dependency: {dependency_id} -> {dependent_id} ({dependency_type.value})"
        )

        return edge

    def remove_dependency(self, dependency_id: str, dependent_id: str) -> bool:
        """Remove a dependency relationship.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends

        Returns:
            True if dependency was removed, False if it didn't exist
        """
        edge_key = (dependency_id, dependent_id)
        if edge_key not in self._edges:
            return False

        del self._edges[edge_key]
        self._dependents[dependency_id].discard(dependent_id)
        self._dependencies[dependent_id].discard(dependency_id)

        logger.debug(f"Removed dependency: {dependency_id} -> {dependent_id}")
        return True

    def get_dependencies(self, task_id: str) -> list[str]:
        """Get all tasks a given task depends on.

        Args:
            task_id: Task to query

        Returns:
            List of task IDs this task depends on
        """
        return list(self._dependencies.get(task_id, set()))

    def get_dependents(self, task_id: str) -> list[str]:
        """Get all tasks that depend on a given task.

        Args:
            task_id: Task to query

        Returns:
            List of task IDs that depend on this task
        """
        return list(self._dependents.get(task_id, set()))

    def get_edge(
        self, dependency_id: str, dependent_id: str
    ) -> DependencyEdge | None:
        """Get the edge between two tasks.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends

        Returns:
            DependencyEdge if exists, None otherwise
        """
        return self._edges.get((dependency_id, dependent_id))

    def update_edge_status(
        self,
        dependency_id: str,
        dependent_id: str,
        status: DependencyStatus,
    ) -> bool:
        """Update the status of a dependency edge.

        Args:
            dependency_id: Task that is depended on
            dependent_id: Task that depends
            status: New status

        Returns:
            True if updated, False if edge doesn't exist
        """
        edge = self._edges.get((dependency_id, dependent_id))
        if edge:
            edge.status = status
            logger.debug(
                f"Updated edge status: {dependency_id} -> {dependent_id} = {status.value}"
            )
            return True
        return False

    def is_blocked(self, task_id: str) -> bool:
        """Check if a task is blocked by unsatisfied dependencies.

        A task is blocked if any dependency is PENDING or FAILED.
        SATISFIED and CANCELLED dependencies don't block.

        Args:
            task_id: Task to check

        Returns:
            True if task has blocking dependencies
        """
        for dep_id in self._dependencies.get(task_id, set()):
            edge = self._edges.get((dep_id, task_id))
            if edge and edge.status in (DependencyStatus.PENDING, DependencyStatus.FAILED):
                return True
        return False

    def get_blocking_tasks(self, task_id: str) -> list[str]:
        """Get tasks blocking a given task.

        Includes tasks with PENDING or FAILED status.

        Args:
            task_id: Task to query

        Returns:
            List of task IDs blocking this task
        """
        blocking = []
        for dep_id in self._dependencies.get(task_id, set()):
            edge = self._edges.get((dep_id, task_id))
            if edge and edge.status in (DependencyStatus.PENDING, DependencyStatus.FAILED):
                blocking.append(dep_id)
        return blocking

    def get_ready_tasks(self) -> list[str]:
        """Get all tasks with no pending dependencies.

        Returns:
            List of task IDs ready to work on
        """
        ready = []
        for task_id in self._task_metadata:
            if not self.is_blocked(task_id):
                ready.append(task_id)
        return ready

    def get_blocked_tasks(self) -> list[str]:
        """Get all tasks that are blocked.

        Returns:
            List of blocked task IDs
        """
        blocked = []
        for task_id in self._task_metadata:
            if self.is_blocked(task_id):
                blocked.append(task_id)
        return blocked

    def topological_sort(self) -> list[str]:
        """Get tasks in topological order.

        Returns:
            List of task IDs in dependency order

        Raises:
            CircularDependencyError: If graph has cycles
        """
        # Check for cycles first
        cycles = self.detect_cycles()
        if cycles:
            raise CircularDependencyError(cycles[0])

        # Kahn's algorithm
        in_degree: dict[str, int] = defaultdict(int)

        # Initialize in-degrees
        for task_id in self._task_metadata:
            in_degree[task_id] = len(self._dependencies.get(task_id, set()))

        # Queue of tasks with no dependencies
        queue = deque(
            [task_id for task_id, degree in in_degree.items() if degree == 0]
        )
        result: list[str] = []

        while queue:
            task_id = queue.popleft()
            result.append(task_id)

            # Reduce in-degree for dependents
            for dependent_id in self._dependents.get(task_id, set()):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        return result

    def detect_cycles(self) -> list[list[str]]:
        """Detect all cycles in the graph.

        Returns:
            List of cycles, each cycle is a list of task IDs
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(task_id: str) -> None:
            visited.add(task_id)
            rec_stack.add(task_id)
            path.append(task_id)

            for dep_id in self._dependents.get(task_id, set()):
                if dep_id not in visited:
                    dfs(dep_id)
                elif dep_id in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(dep_id)
                    cycle = path[cycle_start:] + [dep_id]
                    cycles.append(cycle)

            path.pop()
            rec_stack.remove(task_id)

        for task_id in list(self._task_metadata.keys()):
            if task_id not in visited:
                dfs(task_id)

        return cycles

    def has_cycle(self) -> bool:
        """Check if graph has any cycles.

        Returns:
            True if cycles exist
        """
        return len(self.detect_cycles()) > 0

    def _would_create_cycle(self, from_id: str, to_id: str) -> bool:
        """Check if adding edge would create a cycle.

        Uses DFS to check if there's a path from to_id back to from_id.
        """
        visited: set[str] = set()
        stack = [to_id]

        while stack:
            current = stack.pop()
            if current == from_id:
                return True
            if current in visited:
                continue
            visited.add(current)

            for dep_id in self._dependents.get(current, set()):
                if dep_id not in visited:
                    stack.append(dep_id)

        return False

    def _find_cycle_path(self, from_id: str, to_id: str) -> list[str]:
        """Find the path that creates a cycle."""
        visited: set[str] = set()
        path: list[str] = []

        def dfs(current: str) -> bool:
            visited.add(current)
            path.append(current)

            if current == from_id:
                return True

            for dep_id in self._dependents.get(current, set()):
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True

            path.pop()
            return False

        if dfs(to_id):
            return path + [from_id]
        return [from_id, to_id]

    def get_dependency_depth(self, task_id: str) -> int:
        """Get the depth of dependencies for a task.

        Args:
            task_id: Task to analyze

        Returns:
            Maximum depth of dependency chain
        """
        visited: set[str] = set()

        def depth(tid: str) -> int:
            if tid in visited:
                return 0
            visited.add(tid)

            deps = self._dependencies.get(tid, set())
            if not deps:
                return 0

            return 1 + max(depth(dep_id) for dep_id in deps)

        return depth(task_id)

    def get_dependency_tree(self, task_id: str) -> dict[str, Any]:
        """Get the dependency tree for a task.

        Args:
            task_id: Task to analyze

        Returns:
            Nested dictionary representing the tree
        """
        visited: set[str] = set()

        def build_tree(tid: str) -> dict[str, Any]:
            if tid in visited:
                return {"id": tid, "circular": True}
            visited.add(tid)

            deps = self._dependencies.get(tid, set())
            edge = None
            if deps:
                # Get first edge for metadata
                first_dep = next(iter(deps))
                edge = self._edges.get((first_dep, tid))

            return {
                "id": tid,
                "metadata": self._task_metadata.get(tid, {}),
                "status": edge.status.value if edge else None,
                "dependencies": [
                    build_tree(dep_id) for dep_id in deps
                ],
            }

        visited.clear()
        return build_tree(task_id)

    def get_transitive_dependencies(self, task_id: str) -> set[str]:
        """Get all transitive dependencies of a task.

        Args:
            task_id: Task to analyze

        Returns:
            Set of all task IDs this task depends on (directly or indirectly)
        """
        result: set[str] = set()
        stack = list(self._dependencies.get(task_id, set()))

        while stack:
            current = stack.pop()
            if current not in result:
                result.add(current)
                stack.extend(self._dependencies.get(current, set()))

        return result

    def get_transitive_dependents(self, task_id: str) -> set[str]:
        """Get all transitive dependents of a task.

        Args:
            task_id: Task to analyze

        Returns:
            Set of all task IDs that depend on this task (directly or indirectly)
        """
        result: set[str] = set()
        stack = list(self._dependents.get(task_id, set()))

        while stack:
            current = stack.pop()
            if current not in result:
                result.add(current)
                stack.extend(self._dependents.get(current, set()))

        return result

    def get_all_tasks(self) -> list[str]:
        """Get all task IDs in the graph.

        Returns:
            List of all task IDs
        """
        return list(self._task_metadata.keys())

    def get_all_edges(self) -> list[DependencyEdge]:
        """Get all dependency edges.

        Returns:
            List of all edges
        """
        return list(self._edges.values())

    def get_edge_count(self) -> int:
        """Get total number of edges."""
        return len(self._edges)

    def get_task_count(self) -> int:
        """Get total number of tasks."""
        return len(self._task_metadata)

    def clear(self) -> None:
        """Clear the entire graph."""
        self._dependents.clear()
        self._dependencies.clear()
        self._edges.clear()
        self._task_metadata.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dictionary."""
        return {
            "tasks": [
                {"id": tid, **metadata}
                for tid, metadata in self._task_metadata.items()
            ],
            "edges": [edge.to_dict() for edge in self._edges.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyGraph:
        """Deserialize graph from dictionary."""
        graph = cls()

        # Add tasks
        for task in data.get("tasks", []):
            task_id = task.pop("id")
            graph.add_task(task_id, task)

        # Add edges
        for edge_data in data.get("edges", []):
            graph.add_dependency(
                dependency_id=edge_data["dependency_id"],
                dependent_id=edge_data["dependent_id"],
                dependency_type=DependencyType(edge_data.get("dependency_type", "blocks")),
                metadata=edge_data.get("metadata"),
                validate=False,  # Skip validation for deserialization
            )

        return graph

    def __len__(self) -> int:
        """Return number of tasks."""
        return len(self._task_metadata)

    def __contains__(self, task_id: str) -> bool:
        """Check if task exists in graph."""
        return task_id in self._task_metadata

    def __iter__(self) -> Iterator[str]:
        """Iterate over task IDs."""
        return iter(self._task_metadata)


def create_dependency_graph() -> DependencyGraph:
    """Create a new empty dependency graph.

    Returns:
        New DependencyGraph instance
    """
    return DependencyGraph()
