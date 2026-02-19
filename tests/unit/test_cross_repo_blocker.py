"""Tests for CrossRepoBlockerTracker - Cross-repository blocking tracking."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.cross_repo_blocker import (
    CrossRepoBlockerTracker,
    BlockingChain,
    BlockerImpact,
    BlockingStatus,
)
from mahavishnu.core.cross_repo_dependency import (
    CrossRepoDependencyLinker,
    CrossRepoDependency,
    DependencyType,
    DependencyStatus,
)
from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority


@pytest.fixture
def mock_dependency_linker() -> MagicMock:
    """Create a mock CrossRepoDependencyLinker."""
    linker = MagicMock(spec=CrossRepoDependencyLinker)
    return linker


@pytest.fixture
def sample_tasks() -> dict[str, Task]:
    """Create sample tasks for blocking scenarios."""
    now = datetime.now(UTC)
    return {
        "task-1": Task(
            id="task-1",
            title="Foundation task",
            repository="mahavishnu",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            created_at=now - timedelta(days=5),
        ),
        "task-2": Task(
            id="task-2",
            title="Intermediate task",
            repository="crackerjack",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.MEDIUM,
            created_at=now - timedelta(days=3),
        ),
        "task-3": Task(
            id="task-3",
            title="Final task",
            repository="session-buddy",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.HIGH,
            created_at=now - timedelta(days=1),
        ),
        "task-4": Task(
            id="task-4",
            title="Independent task",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,
            created_at=now,
        ),
        "task-5": Task(
            id="task-5",
            title="Another blocked task",
            repository="akosha",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.CRITICAL,
            created_at=now - timedelta(days=2),
        ),
    }


class TestBlockingStatus:
    """Tests for BlockingStatus enum."""

    def test_blocking_statuses(self) -> None:
        """Test available blocking statuses."""
        assert BlockingStatus.ACTIVE.value == "active"
        assert BlockingStatus.RESOLVED.value == "resolved"
        assert BlockingStatus.ESCALATED.value == "escalated"


class TestBlockingChain:
    """Tests for BlockingChain dataclass."""

    def test_create_blocking_chain(self) -> None:
        """Create a blocking chain."""
        chain = BlockingChain(
            blocked_task_id="task-3",
            chain_depth=2,
            chain_path=["task-1", "task-2", "task-3"],
            repositories_involved=["mahavishnu", "crackerjack", "session-buddy"],
            status=BlockingStatus.ACTIVE,
        )

        assert chain.blocked_task_id == "task-3"
        assert chain.chain_depth == 2
        assert len(chain.chain_path) == 3
        assert chain.status == BlockingStatus.ACTIVE

    def test_blocking_chain_to_dict(self) -> None:
        """Convert blocking chain to dictionary."""
        chain = BlockingChain(
            blocked_task_id="task-3",
            chain_depth=2,
            chain_path=["task-1", "task-2", "task-3"],
            repositories_involved=["mahavishnu", "crackerjack"],
            status=BlockingStatus.ACTIVE,
        )

        d = chain.to_dict()
        assert d["blocked_task_id"] == "task-3"
        assert d["chain_depth"] == 2
        assert d["status"] == "active"
        assert d["is_cross_repo"] is True

    def test_blocking_chain_same_repo(self) -> None:
        """Test is_cross_repo for same-repo chain."""
        chain = BlockingChain(
            blocked_task_id="task-2",
            chain_depth=1,
            chain_path=["task-1", "task-2"],
            repositories_involved=["mahavishnu"],
            status=BlockingStatus.ACTIVE,
        )

        assert chain.is_cross_repo is False


class TestBlockerImpact:
    """Tests for BlockerImpact dataclass."""

    def test_create_blocker_impact(self) -> None:
        """Create a blocker impact assessment."""
        impact = BlockerImpact(
            blocker_task_id="task-1",
            directly_blocked_count=2,
            indirectly_blocked_count=3,
            total_impact=5,
            affected_repositories=["crackerjack", "session-buddy", "akosha"],
            critical_blocked_count=1,
        )

        assert impact.blocker_task_id == "task-1"
        assert impact.directly_blocked_count == 2
        assert impact.total_impact == 5
        assert len(impact.affected_repositories) == 3

    def test_blocker_impact_to_dict(self) -> None:
        """Convert blocker impact to dictionary."""
        impact = BlockerImpact(
            blocker_task_id="task-1",
            directly_blocked_count=2,
            indirectly_blocked_count=1,
            total_impact=3,
            affected_repositories=["crackerjack"],
            critical_blocked_count=0,
        )

        d = impact.to_dict()
        assert d["blocker_task_id"] == "task-1"
        assert d["total_impact"] == 3


class TestCrossRepoBlockerTracker:
    """Tests for CrossRepoBlockerTracker class."""

    @pytest.mark.asyncio
    async def test_get_blocking_chain(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get the blocking chain for a task."""
        # Set up dependency chain: task-1 blocks task-2 blocks task-3
        dep1 = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        dep2 = CrossRepoDependency(
            id="dep-2",
            source_task_id="task-2",
            source_repo="crackerjack",
            target_task_id="task-3",
            target_repo="session-buddy",
            dependency_type=DependencyType.BLOCKS,
        )

        mock_dependency_linker.get_blocking_chain.return_value = [dep2, dep1]

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        chain = tracker.get_blocking_chain("task-3")

        assert chain is not None
        assert chain.blocked_task_id == "task-3"
        assert chain.chain_depth == 2
        assert len(chain.repositories_involved) == 3

    @pytest.mark.asyncio
    async def test_get_blocker_impact(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get the impact of a blocker task."""
        # task-1 blocks task-2 and task-5 directly
        dep1 = CrossRepoDependency(
            id="dep-1",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-2",
            target_repo="crackerjack",
            dependency_type=DependencyType.BLOCKS,
        )
        dep2 = CrossRepoDependency(
            id="dep-2",
            source_task_id="task-1",
            source_repo="mahavishnu",
            target_task_id="task-5",
            target_repo="akosha",
            dependency_type=DependencyType.BLOCKS,
        )
        # task-2 blocks task-3 (indirect from task-1)
        dep3 = CrossRepoDependency(
            id="dep-3",
            source_task_id="task-2",
            source_repo="crackerjack",
            target_task_id="task-3",
            target_repo="session-buddy",
            dependency_type=DependencyType.BLOCKS,
        )

        mock_dependency_linker.get_blocked_tasks.return_value = [dep1, dep2]
        mock_dependency_linker.get_blocking_chain.side_effect = lambda tid: {
            "task-2": [dep1],
            "task-5": [dep2],
            "task-3": [dep3, dep1],
        }.get(tid, [])

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        impact = tracker.get_blocker_impact("task-1")

        assert impact.blocker_task_id == "task-1"
        assert impact.directly_blocked_count == 2
        assert impact.total_impact >= 2

    @pytest.mark.asyncio
    async def test_get_all_blockers(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get all active blockers across repositories."""
        deps = [
            CrossRepoDependency(
                id="dep-1",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-2",
                target_repo="crackerjack",
                dependency_type=DependencyType.BLOCKS,
                status=DependencyStatus.PENDING,
            ),
            CrossRepoDependency(
                id="dep-2",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-5",
                target_repo="akosha",
                dependency_type=DependencyType.BLOCKS,
                status=DependencyStatus.PENDING,
            ),
        ]

        mock_dependency_linker.get_all_dependencies.return_value = deps

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        blockers = tracker.get_all_blockers()

        # task-1 should be identified as a blocker
        assert "task-1" in blockers

    @pytest.mark.asyncio
    async def test_get_critical_blockers(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get blockers that are blocking critical priority tasks."""
        deps = [
            CrossRepoDependency(
                id="dep-1",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-2",
                target_repo="crackerjack",
                dependency_type=DependencyType.BLOCKS,
            ),
        ]

        mock_dependency_linker.get_all_dependencies.return_value = deps
        mock_dependency_linker.get_blocked_tasks.return_value = deps

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        # Without task data, this should still work
        critical = tracker.get_critical_blockers(min_impact=1)

        assert isinstance(critical, list)

    @pytest.mark.asyncio
    async def test_resolve_blocker(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Mark a blocker as resolved."""
        mock_dependency_linker.update_all_statuses.return_value = 2

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        result = tracker.resolve_blocker("task-1")

        assert result is True

    @pytest.mark.asyncio
    async def test_get_blocking_summary(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get a summary of blocking across all repositories."""
        deps = [
            CrossRepoDependency(
                id="dep-1",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-2",
                target_repo="crackerjack",
                dependency_type=DependencyType.BLOCKS,
                status=DependencyStatus.PENDING,
            ),
            CrossRepoDependency(
                id="dep-2",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-3",
                target_repo="session-buddy",
                dependency_type=DependencyType.BLOCKS,
                status=DependencyStatus.PENDING,
            ),
            CrossRepoDependency(
                id="dep-3",
                source_task_id="task-4",
                source_repo="mahavishnu",
                target_task_id="task-5",
                target_repo="akosha",
                dependency_type=DependencyType.REQUIRES,
                status=DependencyStatus.SATISFIED,
            ),
        ]

        mock_dependency_linker.get_all_dependencies.return_value = deps

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        summary = tracker.get_blocking_summary()

        assert summary["total_blockers"] >= 1
        assert summary["total_blocked"] >= 2
        assert "mahavishnu" in summary["blocking_by_repo"]

    @pytest.mark.asyncio
    async def test_get_escalation_candidates(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get blockers that should be escalated (blocking many tasks for long time)."""
        deps = [
            CrossRepoDependency(
                id="dep-1",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-2",
                target_repo="crackerjack",
                dependency_type=DependencyType.BLOCKS,
            ),
        ]

        mock_dependency_linker.get_all_dependencies.return_value = deps
        mock_dependency_linker.get_blocked_tasks.return_value = deps

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        candidates = tracker.get_escalation_candidates(min_blocked=1)

        assert isinstance(candidates, list)

    @pytest.mark.asyncio
    async def test_empty_blocking_chain(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Get blocking chain for unblocked task returns None."""
        mock_dependency_linker.get_blocking_chain.return_value = []

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        chain = tracker.get_blocking_chain("task-4")

        assert chain is None

    @pytest.mark.asyncio
    async def test_cross_repo_blocking_detection(
        self,
        mock_dependency_linker: MagicMock,
    ) -> None:
        """Detect when blocking spans multiple repositories."""
        deps = [
            CrossRepoDependency(
                id="dep-1",
                source_task_id="task-1",
                source_repo="mahavishnu",
                target_task_id="task-2",
                target_repo="crackerjack",
                dependency_type=DependencyType.BLOCKS,
            ),
        ]

        mock_dependency_linker.get_all_dependencies.return_value = deps

        tracker = CrossRepoBlockerTracker(mock_dependency_linker)
        cross_repo_blockers = tracker.get_cross_repo_blockers()

        assert len(cross_repo_blockers) >= 1
        assert all(b.is_cross_repo for b in cross_repo_blockers)


# Import timedelta for fixtures
from datetime import timedelta
