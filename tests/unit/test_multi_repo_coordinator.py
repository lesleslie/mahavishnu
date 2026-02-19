"""Tests for MultiRepoCoordinator - Coordinating task completion across repos."""

import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.multi_repo_coordinator import (
    MultiRepoCoordinator,
    CoordinationPlan,
    CoordinationStep,
    CoordinationStatus,
    RepoSyncState,
)
from mahavishnu.core.cross_repo_dependency import (
    CrossRepoDependencyLinker,
    CrossRepoDependency,
    DependencyType,
    DependencyStatus,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock(spec=TaskStore)
    return store


@pytest.fixture
def mock_dependency_linker() -> MagicMock:
    """Create a mock CrossRepoDependencyLinker."""
    linker = MagicMock(spec=CrossRepoDependencyLinker)
    return linker


@pytest.fixture
def sample_mahavishnu_task() -> Task:
    """Create a sample task from mahavishnu repo."""
    return Task(
        id="task-mah-1",
        title="Foundation task",
        repository="mahavishnu",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_crackerjack_task() -> Task:
    """Create a sample task from crackerjack repo."""
    return Task(
        id="task-jack-1",
        title="Dependent task",
        repository="crackerjack",
        status=TaskStatus.BLOCKED,
        priority=TaskPriority.MEDIUM,
        created_at=datetime.now(UTC),
    )


class TestCoordinationStatus:
    """Tests for CoordinationStatus enum."""

    def test_coordination_statuses(self) -> None:
        """Test available coordination statuses."""
        assert CoordinationStatus.PENDING.value == "pending"
        assert CoordinationStatus.IN_PROGRESS.value == "in_progress"
        assert CoordinationStatus.COMPLETED.value == "completed"
        assert CoordinationStatus.FAILED.value == "failed"


class TestCoordinationStep:
    """Tests for CoordinationStep dataclass."""

    def test_create_coordination_step(self) -> None:
        """Create a coordination step."""
        step = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
        )

        assert step.step_id == "step-1"
        assert step.task_id == "task-1"
        assert step.repository == "mahavishnu"
        assert step.status == CoordinationStatus.PENDING

    def test_coordination_step_to_dict(self) -> None:
        """Convert coordination step to dictionary."""
        step = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=["task-0"],
            status=CoordinationStatus.COMPLETED,
        )

        d = step.to_dict()
        assert d["step_id"] == "step-1"
        assert d["task_id"] == "task-1"
        assert d["status"] == "completed"
        assert d["dependencies"] == ["task-0"]


class TestCoordinationPlan:
    """Tests for CoordinationPlan dataclass."""

    def test_create_coordination_plan(self) -> None:
        """Create a coordination plan."""
        step1 = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
        )
        step2 = CoordinationStep(
            step_id="step-2",
            task_id="task-2",
            repository="crackerjack",
            action="complete",
            dependencies=["task-1"],
        )

        plan = CoordinationPlan(
            plan_id="plan-1",
            goal="Complete feature across repos",
            steps=[step1, step2],
            repositories_involved=["mahavishnu", "crackerjack"],
        )

        assert plan.plan_id == "plan-1"
        assert len(plan.steps) == 2
        assert len(plan.repositories_involved) == 2

    def test_coordination_plan_to_dict(self) -> None:
        """Convert coordination plan to dictionary."""
        step = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
        )

        plan = CoordinationPlan(
            plan_id="plan-1",
            goal="Complete feature",
            steps=[step],
            repositories_involved=["mahavishnu"],
        )

        d = plan.to_dict()
        assert d["plan_id"] == "plan-1"
        assert d["goal"] == "Complete feature"
        assert len(d["steps"]) == 1

    def test_coordination_plan_progress(self) -> None:
        """Calculate coordination plan progress."""
        step1 = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
            status=CoordinationStatus.COMPLETED,
        )
        step2 = CoordinationStep(
            step_id="step-2",
            task_id="task-2",
            repository="crackerjack",
            action="complete",
            dependencies=["task-1"],
            status=CoordinationStatus.IN_PROGRESS,
        )
        step3 = CoordinationStep(
            step_id="step-3",
            task_id="task-3",
            repository="session-buddy",
            action="complete",
            dependencies=["task-2"],
            status=CoordinationStatus.PENDING,
        )

        plan = CoordinationPlan(
            plan_id="plan-1",
            goal="Complete feature",
            steps=[step1, step2, step3],
            repositories_involved=["mahavishnu", "crackerjack", "session-buddy"],
        )

        progress = plan.get_progress()
        assert progress["completed"] == 1
        assert progress["in_progress"] == 1
        assert progress["pending"] == 1
        assert progress["percentage"] == pytest.approx(33.33, rel=0.1)


class TestRepoSyncState:
    """Tests for RepoSyncState dataclass."""

    def test_create_sync_state(self) -> None:
        """Create a repo sync state."""
        state = RepoSyncState(
            repository="mahavishnu",
            last_sync=datetime.now(UTC),
            pending_tasks=5,
            completed_tasks=10,
            sync_status="in_sync",
        )

        assert state.repository == "mahavishnu"
        assert state.pending_tasks == 5
        assert state.sync_status == "in_sync"

    def test_sync_state_to_dict(self) -> None:
        """Convert sync state to dictionary."""
        state = RepoSyncState(
            repository="crackerjack",
            last_sync=datetime.now(UTC),
            pending_tasks=3,
            completed_tasks=7,
            sync_status="syncing",
        )

        d = state.to_dict()
        assert d["repository"] == "crackerjack"
        assert d["pending_tasks"] == 3
        assert d["sync_status"] == "syncing"


class TestMultiRepoCoordinator:
    """Tests for MultiRepoCoordinator class."""

    @pytest.mark.asyncio
    async def test_create_coordination_plan(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Create a coordination plan for tasks."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        mock_dependency_linker.get_all_dependencies.return_value = [dep]

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)
        plan = await coordinator.create_plan(
            goal="Complete cross-repo feature",
            task_ids=["task-mah-1", "task-jack-1"],
        )

        assert plan is not None
        assert plan.goal == "Complete cross-repo feature"
        assert len(plan.steps) == 2

    @pytest.mark.asyncio
    async def test_coordination_plan_respects_dependencies(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Plan orders tasks respecting dependencies."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        mock_dependency_linker.get_all_dependencies.return_value = [dep]

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)
        plan = await coordinator.create_plan(
            goal="Complete feature",
            task_ids=["task-jack-1", "task-mah-1"],  # Note: jack first in input
        )

        # mah-1 should come before jack-1 in the plan (dependency order)
        assert plan.steps[0].task_id == "task-mah-1"
        assert plan.steps[1].task_id == "task-jack-1"

    @pytest.mark.asyncio
    async def test_execute_coordination_step(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_mahavishnu_task: Task,
    ) -> None:
        """Execute a step in the coordination plan."""
        mock_task_store.get.return_value = sample_mahavishnu_task
        mock_task_store.update.return_value = sample_mahavishnu_task

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)

        step = CoordinationStep(
            step_id="step-1",
            task_id="task-mah-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
        )

        result = await coordinator.execute_step(step)

        assert result is True
        mock_task_store.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_step_blocked_by_dependency(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_crackerjack_task: Task,
    ) -> None:
        """Cannot execute step if dependencies not met."""
        mock_task_store.get.return_value = sample_crackerjack_task

        # Dependency not satisfied
        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
            status=DependencyStatus.PENDING,
        )
        mock_dependency_linker.get_dependents_of_task.return_value = [dep]

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)

        step = CoordinationStep(
            step_id="step-1",
            task_id="task-jack-1",
            repository="crackerjack",
            action="complete",
            dependencies=["task-mah-1"],
        )

        result = await coordinator.execute_step(step)

        assert result is False

    @pytest.mark.asyncio
    async def test_get_repo_sync_states(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get sync states for all involved repositories."""
        from mahavishnu.core.task_store import TaskListFilter

        mah_tasks = [
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
        jack_tasks = [
            Task(
                id="task-3",
                title="Task 3",
                repository="crackerjack",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                created_at=datetime.now(UTC),
            ),
        ]

        mock_task_store.list.side_effect = lambda f: (
            mah_tasks if f.repository == "mahavishnu" else jack_tasks
        )

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)
        states = await coordinator.get_sync_states(["mahavishnu", "crackerjack"])

        assert len(states) == 2
        assert states[0].repository == "mahavishnu"
        assert states[1].repository == "crackerjack"

    @pytest.mark.asyncio
    async def test_coordinate_completion(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Coordinate completion of all tasks in a plan."""
        sample_mahavishnu_task.status = TaskStatus.IN_PROGRESS
        sample_crackerjack_task.status = TaskStatus.BLOCKED

        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)
        mock_task_store.update.return_value = sample_mahavishnu_task

        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        mock_dependency_linker.get_all_dependencies.return_value = [dep]
        mock_dependency_linker.get_dependents_of_task.return_value = []
        mock_dependency_linker.update_all_statuses.return_value = 1

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)

        plan = await coordinator.create_plan(
            goal="Complete feature",
            task_ids=["task-mah-1", "task-jack-1"],
        )

        # Execute the plan
        results = await coordinator.execute_plan(plan)

        assert len(results) == 2
        # First step (mah-1) should succeed
        assert results[0] is True

    @pytest.mark.asyncio
    async def test_rollback_on_failure(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Rollback completed steps on failure."""
        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)

        step1 = CoordinationStep(
            step_id="step-1",
            task_id="task-1",
            repository="mahavishnu",
            action="complete",
            dependencies=[],
            status=CoordinationStatus.COMPLETED,
        )
        step2 = CoordinationStep(
            step_id="step-2",
            task_id="task-2",
            repository="crackerjack",
            action="complete",
            dependencies=["task-1"],
            status=CoordinationStatus.FAILED,
        )

        plan = CoordinationPlan(
            plan_id="plan-1",
            goal="Test plan",
            steps=[step1, step2],
            repositories_involved=["mahavishnu", "crackerjack"],
        )

        # Rollback should be called
        rollback_count = await coordinator.rollback_plan(plan)

        assert rollback_count == 1  # Only step1 should be rolled back

    @pytest.mark.asyncio
    async def test_get_completion_order(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Get optimal completion order for tasks."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        mock_dependency_linker.get_all_dependencies.return_value = [dep]

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)
        order = coordinator.get_completion_order(["task-jack-1", "task-mah-1"])

        # mah-1 must come before jack-1
        assert order.index("task-mah-1") < order.index("task-jack-1")

    @pytest.mark.asyncio
    async def test_coordination_with_no_dependencies(
        self,
        mock_task_store: AsyncMock,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Tasks with no dependencies can be completed in any order."""
        task1 = Task(
            id="task-1",
            title="Independent task 1",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            created_at=datetime.now(UTC),
        )
        task2 = Task(
            id="task-2",
            title="Independent task 2",
            repository="crackerjack",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
            created_at=datetime.now(UTC),
        )

        mock_task_store.get.side_effect = lambda tid: {
            "task-1": task1,
            "task-2": task2,
        }.get(tid)
        mock_dependency_linker.get_all_dependencies.return_value = []

        coordinator = MultiRepoCoordinator(mock_task_store, mock_dependency_linker)
        order = coordinator.get_completion_order(["task-1", "task-2"])

        assert len(order) == 2
        assert "task-1" in order
        assert "task-2" in order
