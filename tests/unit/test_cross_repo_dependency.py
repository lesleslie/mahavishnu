"""Tests for CrossRepoDependencyLinker - Cross-repository task dependencies."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.cross_repo_dependency import (
    CrossRepoDependencyLinker,
    CrossRepoDependency,
    DependencyType,
    DependencyStatus,
    CrossRepoDependencyError,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def sample_mahavishnu_task() -> Task:
    """Create a sample task from mahavishnu repo."""
    return Task(
        id="task-mah-1",
        title="Implement API endpoint",
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
        title="Add quality check",
        repository="crackerjack",
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
        created_at=datetime.now(UTC),
    )


class TestDependencyType:
    """Tests for DependencyType enum."""

    def test_dependency_types(self) -> None:
        """Test available dependency types."""
        assert DependencyType.BLOCKS.value == "blocks"
        assert DependencyType.REQUIRES.value == "requires"
        assert DependencyType.RELATED.value == "related"

    def test_dependency_direction(self) -> None:
        """Test dependency direction semantics."""
        # BLOCKS: task_a blocks task_b (task_b cannot complete until task_a is done)
        # REQUIRES: task_a requires task_b (task_a needs task_b to be done first)
        assert DependencyType.BLOCKS.value == "blocks"
        assert DependencyType.REQUIRES.value == "requires"


class TestDependencyStatus:
    """Tests for DependencyStatus enum."""

    def test_statuses(self) -> None:
        """Test available dependency statuses."""
        assert DependencyStatus.PENDING.value == "pending"
        assert DependencyStatus.SATISFIED.value == "satisfied"
        assert DependencyStatus.FAILED.value == "failed"
        assert DependencyStatus.BLOCKED.value == "blocked"


class TestCrossRepoDependency:
    """Tests for CrossRepoDependency dataclass."""

    def test_create_dependency(self) -> None:
        """Create a cross-repo dependency."""
        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-mah-1",
            source_repo="mahavishnu",
            target_task_id="task-jack-1",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )

        assert dep.source_task_id == "task-mah-1"
        assert dep.source_repo == "mahavishnu"
        assert dep.target_task_id == "task-jack-1"
        assert dep.target_repo == "crackerjack"
        assert dep.dependency_type == DependencyType.BLOCKS

    def test_dependency_to_dict(self) -> None:
        """Convert dependency to dictionary."""
        dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.REQUIRES,
            status=DependencyStatus.PENDING,
        )

        d = dep.to_dict()
        assert d["source_task_id"] == "task-1"
        assert d["source_repo"] == "mahavishnu"
        assert d["dependency_type"] == "requires"

    def test_cross_repo_flag(self) -> None:
        """Test is_cross_repo property."""
        cross_repo_dep = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )

        same_repo_dep = CrossRepoDependency(
            id="dep-2",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-3",
            target_repo="mahavishnu",
            dependency_type=DependencyType.BLOCKS,
        )

        assert cross_repo_dep.is_cross_repo is True
        assert same_repo_dep.is_cross_repo is False


class TestCrossRepoDependencyLinker:
    """Tests for CrossRepoDependencyLinker class."""

    @pytest.mark.asyncio
    async def test_create_dependency(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Create a cross-repo dependency."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)
        dep = await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        assert dep is not None
        assert dep.source_task_id == "task-mah-1"
        assert dep.target_task_id == "task-jack-1"

    @pytest.mark.asyncio
    async def test_prevent_self_dependency(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
    ) -> None:
        """Prevent a task from depending on itself."""
        mock_task_store.get.return_value = sample_mahavishnu_task

        linker = CrossRepoDependencyLinker(mock_task_store)

        with pytest.raises(CrossRepoDependencyError, match="cannot depend on itself"):
            await linker.create_dependency(
                source_task_id="task-mah-1",
                target_task_id="task-mah-1",
                dependency_type=DependencyType.BLOCKS,
            )

    @pytest.mark.asyncio
    async def test_prevent_cycle(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Prevent circular dependencies."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)

        # Create first dependency: mah-1 blocks jack-1
        await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        # Try to create cycle: jack-1 blocks mah-1
        with pytest.raises(CrossRepoDependencyError, match="cycle"):
            await linker.create_dependency(
                source_task_id="task-jack-1",
                target_task_id="task-mah-1",
                dependency_type=DependencyType.BLOCKS,
            )

    @pytest.mark.asyncio
    async def test_get_dependencies_for_task(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Get all dependencies for a task."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)

        # Create dependency
        await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        # Get dependencies for task-mah-1
        deps = linker.get_dependencies_for_task("task-mah-1")
        assert len(deps) == 1
        assert deps[0].target_task_id == "task-jack-1"

    @pytest.mark.asyncio
    async def test_get_dependent_tasks(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Get all tasks that depend on a task."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)

        # Create dependency: mah-1 blocks jack-1
        await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        # Get tasks that depend on task-jack-1 (what blocks jack-1)
        dependents = linker.get_dependents_of_task("task-jack-1")
        assert len(dependents) == 1  # mah-1 blocks jack-1
        assert dependents[0].source_task_id == "task-mah-1"

        # Get tasks blocked BY task-mah-1
        blocked = linker.get_blocked_tasks("task-mah-1")
        assert len(blocked) == 1  # jack-1 is blocked by mah-1
        assert blocked[0].target_task_id == "task-jack-1"

    @pytest.mark.asyncio
    async def test_remove_dependency(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Remove a cross-repo dependency."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)

        # Create dependency
        dep = await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        # Remove it
        result = linker.remove_dependency(dep.id)
        assert result is True

        # Verify it's removed
        deps = linker.get_dependencies_for_task("task-mah-1")
        assert len(deps) == 0

    @pytest.mark.asyncio
    async def test_get_cross_repo_dependencies(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get all cross-repo dependencies."""
        linker = CrossRepoDependencyLinker(mock_task_store)

        # Helper to add dependency with indexes
        def add_dep(dep: CrossRepoDependency) -> None:
            linker._dependencies[dep.id] = dep
            linker._task_dependencies[dep.source_task_id].append(dep.id)
            linker._task_dependents[dep.target_task_id].append(dep.id)

        add_dep(CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        ))
        add_dep(CrossRepoDependency(
            id="dep-2",
            source_task_id="task-3",
            source_repo="mahavishnu",
            target_task_id="task-4",
            target_repo="session-buddy",
            dependency_type=DependencyType.REQUIRES,
        ))
        add_dep(CrossRepoDependency(
            id="dep-3",
            source_task_id="task-5",
            source_repo="mahavishnu",
            target_task_id="task-6",
            target_repo="mahavishnu",  # Same repo
            dependency_type=DependencyType.RELATED,
        ))

        cross_repo = linker.get_cross_repo_dependencies()
        assert len(cross_repo) == 2  # Only cross-repo deps

    @pytest.mark.asyncio
    async def test_dependency_status_update(
        self,
        mock_task_store: AsyncMock,
        sample_mahavishnu_task: Task,
        sample_crackerjack_task: Task,
    ) -> None:
        """Update dependency status based on task status."""
        mock_task_store.get.side_effect = lambda tid: {
            "task-mah-1": sample_mahavishnu_task,
            "task-jack-1": sample_crackerjack_task,
        }.get(tid)

        linker = CrossRepoDependencyLinker(mock_task_store)

        dep = await linker.create_dependency(
            source_task_id="task-mah-1",
            target_task_id="task-jack-1",
            dependency_type=DependencyType.BLOCKS,
        )

        # Initially pending
        assert dep.status == DependencyStatus.PENDING

        # Update when source task completes
        sample_mahavishnu_task.status = TaskStatus.COMPLETED
        updated = await linker.update_dependency_status(dep.id)
        assert updated.status == DependencyStatus.SATISFIED

    @pytest.mark.asyncio
    async def test_get_blocking_chain(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get the full blocking chain for a task."""
        linker = CrossRepoDependencyLinker(mock_task_store)

        # Helper to add dependency with indexes
        def add_dep(dep: CrossRepoDependency) -> None:
            linker._dependencies[dep.id] = dep
            linker._task_dependencies[dep.source_task_id].append(dep.id)
            linker._task_dependents[dep.target_task_id].append(dep.id)

        # Create a chain: task-1 blocks task-2 blocks task-3
        add_dep(CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        ))
        add_dep(CrossRepoDependency(
            id="dep-2",
            source_task_id="task-2",
            source_repo="crackerjack",
            target_task_id="task-3",
            target_repo="session-buddy",
            dependency_type=DependencyType.BLOCKS,
        ))

        chain = linker.get_blocking_chain("task-3")
        assert len(chain) == 2
        # Should be in order: task-2 blocks task-3, task-1 blocks task-2
        assert chain[0].source_task_id == "task-2"
        assert chain[1].source_task_id == "task-1"

    @pytest.mark.asyncio
    async def test_get_dependencies_by_repo(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get dependencies involving a specific repository."""
        linker = CrossRepoDependencyLinker(mock_task_store)

        # Helper to add dependency with indexes
        def add_dep(dep: CrossRepoDependency) -> None:
            linker._dependencies[dep.id] = dep
            linker._task_dependencies[dep.source_task_id].append(dep.id)
            linker._task_dependents[dep.target_task_id].append(dep.id)

        add_dep(CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        ))
        add_dep(CrossRepoDependency(
            id="dep-2",
            source_task_id="task-3",
            source_repo="session-buddy",
            target_task_id="task-4",
            target_repo="akosha",
            dependency_type=DependencyType.REQUIRES,
        ))

        mahavishnu_deps = linker.get_dependencies_by_repo("mahavishnu")
        assert len(mahavishnu_deps) == 1
        assert mahavishnu_deps[0].source_repo == "mahavishnu"


class TestCrossRepoDependencyError:
    """Tests for CrossRepoDependencyError exception."""

    def test_error_message(self) -> None:
        """Create error with message."""
        error = CrossRepoDependencyError("Task not found")
        assert str(error) == "Task not found"

    def test_error_with_details(self) -> None:
        """Create error with details."""
        error = CrossRepoDependencyError(
            "Cycle detected",
            details={"path": ["task-1", "task-2", "task-1"]},
        )
        assert error.details is not None
        assert error.details["path"] == ["task-1", "task-2", "task-1"]
