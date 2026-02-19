"""Multi-Repository Coordinator for Mahavishnu.

Coordinates task completion across multiple repositories:
- Dependency-aware execution ordering
- Cross-repository synchronization
- Rollback on failure
- Progress tracking

Usage:
    from mahavishnu.core.multi_repo_coordinator import MultiRepoCoordinator

    coordinator = MultiRepoCoordinator(task_store, dependency_linker)

    # Create a coordination plan
    plan = await coordinator.create_plan(
        goal="Complete feature across repos",
        task_ids=["task-1", "task-2", "task-3"],
    )

    # Execute the plan
    results = await coordinator.execute_plan(plan)
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.cross_repo_dependency import (
    CrossRepoDependencyLinker,
    CrossRepoDependency,
    DependencyType,
    DependencyStatus,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskStore

logger = logging.getLogger(__name__)


class CoordinationStatus(str, Enum):
    """Status of a coordination step or plan."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class CoordinationStep:
    """A single step in a coordination plan.

    Attributes:
        step_id: Unique identifier for this step
        task_id: Task to be acted upon
        repository: Repository containing the task
        action: Action to perform (complete, start, etc.)
        dependencies: Task IDs that must complete first
        status: Current status of this step
        started_at: When execution started
        completed_at: When execution completed
        error: Error message if failed
    """

    step_id: str
    task_id: str
    repository: str
    action: str
    dependencies: list[str] = field(default_factory=list)
    status: CoordinationStatus = CoordinationStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "task_id": self.task_id,
            "repository": self.repository,
            "action": self.action,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }


@dataclass
class CoordinationPlan:
    """A plan for coordinating tasks across repositories.

    Attributes:
        plan_id: Unique identifier for this plan
        goal: Description of what this plan achieves
        steps: Ordered list of coordination steps
        repositories_involved: List of repositories involved
        status: Overall plan status
        created_at: When the plan was created
    """

    plan_id: str
    goal: str
    steps: list[CoordinationStep] = field(default_factory=list)
    repositories_involved: list[str] = field(default_factory=list)
    status: CoordinationStatus = CoordinationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def get_progress(self) -> dict[str, Any]:
        """Calculate progress metrics.

        Returns:
            Dictionary with progress statistics
        """
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == CoordinationStatus.COMPLETED)
        in_progress = sum(1 for s in self.steps if s.status == CoordinationStatus.IN_PROGRESS)
        pending = sum(1 for s in self.steps if s.status == CoordinationStatus.PENDING)
        failed = sum(1 for s in self.steps if s.status == CoordinationStatus.FAILED)

        percentage = (completed / total * 100) if total > 0 else 0

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "failed": failed,
            "percentage": round(percentage, 2),
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "repositories_involved": self.repositories_involved,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "progress": self.get_progress(),
        }


@dataclass
class RepoSyncState:
    """Synchronization state for a repository.

    Attributes:
        repository: Repository name
        last_sync: Last synchronization time
        pending_tasks: Number of pending tasks
        completed_tasks: Number of completed tasks
        sync_status: Current sync status
        error: Error message if sync failed
    """

    repository: str
    last_sync: datetime
    pending_tasks: int = 0
    completed_tasks: int = 0
    sync_status: str = "pending"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "repository": self.repository,
            "last_sync": self.last_sync.isoformat(),
            "pending_tasks": self.pending_tasks,
            "completed_tasks": self.completed_tasks,
            "sync_status": self.sync_status,
            "error": self.error,
        }


class MultiRepoCoordinator:
    """Coordinates task completion across multiple repositories.

    Features:
    - Dependency-aware execution ordering
    - Cross-repository synchronization
    - Automatic rollback on failure
    - Progress tracking and reporting

    Example:
        coordinator = MultiRepoCoordinator(task_store, dependency_linker)

        # Create and execute a plan
        plan = await coordinator.create_plan(
            goal="Deploy feature",
            task_ids=["task-1", "task-2"],
        )
        results = await coordinator.execute_plan(plan)

        # Get optimal completion order
        order = coordinator.get_completion_order(["task-1", "task-2"])
    """

    def __init__(
        self,
        task_store: TaskStore,
        dependency_linker: CrossRepoDependencyLinker,
    ) -> None:
        """Initialize the coordinator.

        Args:
            task_store: TaskStore for task operations
            dependency_linker: CrossRepoDependencyLinker for dependencies
        """
        self.task_store = task_store
        self.dependency_linker = dependency_linker
        self._plans: dict[str, CoordinationPlan] = {}

    async def create_plan(
        self,
        goal: str,
        task_ids: list[str],
    ) -> CoordinationPlan:
        """Create a coordination plan for the given tasks.

        Args:
            goal: Description of what this plan achieves
            task_ids: List of task IDs to coordinate

        Returns:
            CoordinationPlan with ordered steps
        """
        # Get optimal completion order
        ordered_tasks = self.get_completion_order(task_ids)

        # Get dependencies for all tasks
        all_deps = self.dependency_linker.get_all_dependencies()
        dep_map: dict[str, list[str]] = defaultdict(list)

        for dep in all_deps:
            if dep.dependency_type == DependencyType.BLOCKS:
                # task-1 blocks task-2 means task-2 depends on task-1
                dep_map[dep.target_task_id].append(dep.source_task_id)

        # Create steps in order
        steps: list[CoordinationStep] = []
        repositories: set[str] = set()

        for idx, task_id in enumerate(ordered_tasks):
            task = await self.task_store.get(task_id)
            if task:
                repositories.add(task.repository)
                steps.append(CoordinationStep(
                    step_id=f"step-{idx + 1}",
                    task_id=task_id,
                    repository=task.repository,
                    action="complete",
                    dependencies=dep_map.get(task_id, []),
                ))

        plan = CoordinationPlan(
            plan_id=str(uuid.uuid4()),
            goal=goal,
            steps=steps,
            repositories_involved=list(repositories),
        )

        # Store the plan
        self._plans[plan.plan_id] = plan

        logger.info(
            f"Created coordination plan {plan.plan_id} with {len(steps)} steps "
            f"across {len(repositories)} repositories"
        )

        return plan

    def get_completion_order(self, task_ids: list[str]) -> list[str]:
        """Get optimal completion order respecting dependencies.

        Uses topological sort to determine order.

        Args:
            task_ids: List of task IDs to order

        Returns:
            Ordered list of task IDs
        """
        # Build dependency graph
        all_deps = self.dependency_linker.get_all_dependencies()
        dep_map: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {tid: 0 for tid in task_ids}

        for dep in all_deps:
            if dep.dependency_type == DependencyType.BLOCKS:
                if dep.target_task_id in task_ids and dep.source_task_id in task_ids:
                    dep_map[dep.source_task_id].append(dep.target_task_id)
                    in_degree[dep.target_task_id] += 1

        # Kahn's algorithm for topological sort
        queue = [tid for tid in task_ids if in_degree[tid] == 0]
        result: list[str] = []

        while queue:
            # Sort queue for deterministic ordering
            queue.sort()
            current = queue.pop(0)
            result.append(current)

            for dependent in dep_map.get(current, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # Add any remaining tasks (no dependencies or circular)
        remaining = [tid for tid in task_ids if tid not in result]
        result.extend(sorted(remaining))

        return result

    async def execute_step(self, step: CoordinationStep) -> bool:
        """Execute a single coordination step.

        Args:
            step: The step to execute

        Returns:
            True if successful, False otherwise
        """
        # Check if dependencies are met
        if step.dependencies:
            blocking_deps = self.dependency_linker.get_dependents_of_task(step.task_id)
            for dep in blocking_deps:
                if dep.status == DependencyStatus.PENDING:
                    logger.warning(
                        f"Cannot execute step {step.step_id}: "
                        f"dependency {dep.source_task_id} not satisfied"
                    )
                    return False

        step.status = CoordinationStatus.IN_PROGRESS
        step.started_at = datetime.now(UTC)

        try:
            # Get the task
            task = await self.task_store.get(step.task_id)
            if not task:
                step.status = CoordinationStatus.FAILED
                step.error = f"Task {step.task_id} not found"
                return False

            # Update task status to completed
            task.status = TaskStatus.COMPLETED
            await self.task_store.update(task)

            # Update dependency status
            self.dependency_linker.update_all_statuses({
                step.task_id: TaskStatus.COMPLETED,
            })

            step.status = CoordinationStatus.COMPLETED
            step.completed_at = datetime.now(UTC)

            logger.info(f"Completed coordination step {step.step_id} for task {step.task_id}")
            return True

        except Exception as e:
            step.status = CoordinationStatus.FAILED
            step.error = str(e)
            logger.error(f"Failed to execute step {step.step_id}: {e}")
            return False

    async def execute_plan(self, plan: CoordinationPlan) -> list[bool]:
        """Execute all steps in a coordination plan.

        Args:
            plan: The plan to execute

        Returns:
            List of results for each step
        """
        plan.status = CoordinationStatus.IN_PROGRESS
        results: list[bool] = []

        for step in plan.steps:
            result = await self.execute_step(step)
            results.append(result)

            if not result:
                # Stop execution on failure
                plan.status = CoordinationStatus.FAILED
                logger.error(f"Plan {plan.plan_id} failed at step {step.step_id}")
                break

        if all(results):
            plan.status = CoordinationStatus.COMPLETED
            logger.info(f"Plan {plan.plan_id} completed successfully")

        return results

    async def rollback_plan(self, plan: CoordinationPlan) -> int:
        """Rollback completed steps in a plan.

        Args:
            plan: The plan to rollback

        Returns:
            Number of steps rolled back
        """
        rollback_count = 0

        # Rollback in reverse order
        for step in reversed(plan.steps):
            if step.status == CoordinationStatus.COMPLETED:
                try:
                    task = await self.task_store.get(step.task_id)
                    if task:
                        task.status = TaskStatus.PENDING
                        await self.task_store.update(task)
                        step.status = CoordinationStatus.ROLLED_BACK
                        rollback_count += 1
                        logger.info(f"Rolled back step {step.step_id}")
                except Exception as e:
                    logger.error(f"Failed to rollback step {step.step_id}: {e}")

        plan.status = CoordinationStatus.ROLLED_BACK
        return rollback_count

    async def get_sync_states(
        self,
        repositories: list[str],
    ) -> list[RepoSyncState]:
        """Get synchronization states for repositories.

        Args:
            repositories: List of repository names

        Returns:
            List of RepoSyncState for each repository
        """
        from mahavishnu.core.task_store import TaskListFilter

        states: list[RepoSyncState] = []

        for repo in repositories:
            try:
                tasks = await self.task_store.list(
                    TaskListFilter(repository=repo, limit=10000)
                )

                pending = sum(1 for t in tasks if t.status in (
                    TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED
                ))
                completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)

                states.append(RepoSyncState(
                    repository=repo,
                    last_sync=datetime.now(UTC),
                    pending_tasks=pending,
                    completed_tasks=completed,
                    sync_status="in_sync",
                ))
            except Exception as e:
                states.append(RepoSyncState(
                    repository=repo,
                    last_sync=datetime.now(UTC),
                    sync_status="error",
                    error=str(e),
                ))

        return states

    def get_plan(self, plan_id: str) -> CoordinationPlan | None:
        """Get a coordination plan by ID.

        Args:
            plan_id: Plan ID to retrieve

        Returns:
            CoordinationPlan if found, None otherwise
        """
        return self._plans.get(plan_id)

    def get_all_plans(self) -> list[CoordinationPlan]:
        """Get all coordination plans.

        Returns:
            List of all CoordinationPlans
        """
        return list(self._plans.values())


__all__ = [
    "MultiRepoCoordinator",
    "CoordinationPlan",
    "CoordinationStep",
    "CoordinationStatus",
    "RepoSyncState",
]
