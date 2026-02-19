"""Tests for Dependency Manager Module.

Tests cover:
- Automatic blocking/unblocking
- Status tracking
- Event notifications
- Dependency satisfaction
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mahavishnu.core.dependency_graph import DependencyStatus, DependencyType
from mahavishnu.core.dependency_manager import (
    DependencyEvent,
    DependencyEventData,
    DependencyEventEmitter,
    DependencyManager,
    TaskStatus,
    create_dependency_manager,
)


class TestTaskStatus:
    """Test task status enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.CANCELLED.value == "cancelled"


class TestDependencyEvent:
    """Test dependency events."""

    def test_event_types(self) -> None:
        """Test event types."""
        assert DependencyEvent.TASK_BLOCKED.value == "task_blocked"
        assert DependencyEvent.TASK_UNBLOCKED.value == "task_unblocked"
        assert DependencyEvent.DEPENDENCY_ADDED.value == "dependency_added"


class TestDependencyEventData:
    """Test event data."""

    def test_event_data(self) -> None:
        """Test event data creation."""
        data = DependencyEventData(
            event_type=DependencyEvent.TASK_BLOCKED,
            task_id="task-1",
            related_task_id="task-2",
            details={"reason": "testing"},
        )

        assert data.event_type == DependencyEvent.TASK_BLOCKED
        assert data.task_id == "task-1"
        assert data.related_task_id == "task-2"
        assert data.details["reason"] == "testing"

    def test_event_data_to_dict(self) -> None:
        """Test event data serialization."""
        data = DependencyEventData(
            event_type=DependencyEvent.DEPENDENCY_ADDED,
            task_id="task-1",
        )

        d = data.to_dict()

        assert d["event_type"] == "dependency_added"
        assert d["task_id"] == "task-1"
        assert "timestamp" in d


class TestDependencyEventEmitter:
    """Test event emitter."""

    def test_on_emit(self) -> None:
        """Test registering and emitting events."""
        emitter = DependencyEventEmitter()
        handler = MagicMock()

        emitter.on(DependencyEvent.TASK_BLOCKED, handler)

        data = DependencyEventData(
            event_type=DependencyEvent.TASK_BLOCKED,
            task_id="task-1",
        )
        emitter.emit(data)

        handler.assert_called_once_with(data)

    def test_off(self) -> None:
        """Test unregistering handlers."""
        emitter = DependencyEventEmitter()
        handler = MagicMock()

        emitter.on(DependencyEvent.TASK_BLOCKED, handler)
        emitter.off(DependencyEvent.TASK_BLOCKED, handler)

        data = DependencyEventData(
            event_type=DependencyEvent.TASK_BLOCKED,
            task_id="task-1",
        )
        emitter.emit(data)

        handler.assert_not_called()

    def test_multiple_handlers(self) -> None:
        """Test multiple handlers for same event."""
        emitter = DependencyEventEmitter()
        handler1 = MagicMock()
        handler2 = MagicMock()

        emitter.on(DependencyEvent.TASK_UNBLOCKED, handler1)
        emitter.on(DependencyEvent.TASK_UNBLOCKED, handler2)

        data = DependencyEventData(
            event_type=DependencyEvent.TASK_UNBLOCKED,
            task_id="task-1",
        )
        emitter.emit(data)

        handler1.assert_called_once()
        handler2.assert_called_once()

    def test_handler_exception(self) -> None:
        """Test that handler exceptions don't break emission."""
        emitter = DependencyEventEmitter()

        def bad_handler(data: DependencyEventData) -> None:
            raise ValueError("Test error")

        good_handler = MagicMock()

        emitter.on(DependencyEvent.TASK_BLOCKED, bad_handler)
        emitter.on(DependencyEvent.TASK_BLOCKED, good_handler)

        data = DependencyEventData(
            event_type=DependencyEvent.TASK_BLOCKED,
            task_id="task-1",
        )
        emitter.emit(data)

        # Good handler should still be called
        good_handler.assert_called_once()

    def test_clear_handlers(self) -> None:
        """Test clearing all handlers."""
        emitter = DependencyEventEmitter()
        handler = MagicMock()

        emitter.on(DependencyEvent.TASK_BLOCKED, handler)
        emitter.clear_handlers()

        data = DependencyEventData(
            event_type=DependencyEvent.TASK_BLOCKED,
            task_id="task-1",
        )
        emitter.emit(data)

        handler.assert_not_called()


class TestDependencyManager:
    """Test dependency manager."""

    @pytest.fixture
    def manager(self) -> DependencyManager:
        """Create fresh dependency manager."""
        return DependencyManager()

    def test_add_task(self, manager: DependencyManager) -> None:
        """Test adding tasks."""
        manager.add_task("task-1", TaskStatus.PENDING)

        assert "task-1" in manager
        assert manager.get_task_status("task-1") == TaskStatus.PENDING

    def test_remove_task(self, manager: DependencyManager) -> None:
        """Test removing tasks."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        affected = manager.remove_task("task-1")

        assert "task-1" not in manager
        assert "task-2" in affected

    def test_add_dependency(self, manager: DependencyManager) -> None:
        """Test adding dependencies."""
        manager.add_task("task-1")
        manager.add_task("task-2")

        edge = manager.add_dependency("task-1", "task-2")

        assert edge.dependency_id == "task-1"
        assert manager.is_ready("task-1")  # Has no deps
        assert not manager.is_ready("task-2")  # Blocked

    def test_remove_dependency(self, manager: DependencyManager) -> None:
        """Test removing dependencies."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        result = manager.remove_dependency("task-1", "task-2")

        assert result is True
        assert manager.is_ready("task-2")  # Now unblocked

    def test_update_status_completed(self, manager: DependencyManager) -> None:
        """Test completing a task unblocks dependents."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        newly_unblocked = manager.update_task_status("task-1", TaskStatus.COMPLETED)

        assert "task-2" in newly_unblocked
        assert manager.is_ready("task-2")
        assert manager.get_dependency_status("task-1", "task-2") == DependencyStatus.SATISFIED

    def test_update_status_failed(self, manager: DependencyManager) -> None:
        """Test failing a task marks dependencies as failed."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        manager.update_task_status("task-1", TaskStatus.FAILED)

        # Task-2 should still be blocked (failed dependency)
        assert not manager.is_ready("task-2")
        assert manager.get_dependency_status("task-1", "task-2") == DependencyStatus.FAILED

    def test_update_status_cancelled(self, manager: DependencyManager) -> None:
        """Test cancelling a task unblocks dependents."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        manager.update_task_status("task-1", TaskStatus.CANCELLED)

        # Cancelled dependencies don't block
        assert manager.get_dependency_status("task-1", "task-2") == DependencyStatus.CANCELLED
        assert manager.is_ready("task-2")

    def test_get_ready_tasks(self, manager: DependencyManager) -> None:
        """Test getting ready tasks."""
        manager.add_task("task-1", TaskStatus.COMPLETED)
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_dependency("task-1", "task-3")

        ready = manager.get_ready_tasks()

        assert "task-2" in ready
        assert "task-3" in ready  # dependency already completed

    def test_get_blocked_tasks(self, manager: DependencyManager) -> None:
        """Test getting blocked tasks."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        blocked = manager.get_blocked_tasks()

        assert "task-2" in blocked
        assert "task-1" not in blocked

    def test_get_next_available_tasks(self, manager: DependencyManager) -> None:
        """Test getting next available tasks."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_dependency("task-1", "task-2")

        available = manager.get_next_available_tasks(limit=2)

        assert len(available) <= 2
        assert "task-1" in available or "task-3" in available

    def test_can_complete_task(self, manager: DependencyManager) -> None:
        """Test checking if task can be completed."""
        manager.add_task("task-1")

        assert manager.can_complete_task("task-1") is True

        manager.update_task_status("task-1", TaskStatus.COMPLETED)
        assert manager.can_complete_task("task-1") is False

    def test_get_completion_candidates(self, manager: DependencyManager) -> None:
        """Test getting tasks that would become available."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_dependency("task-1", "task-2")

        candidates = manager.get_completion_candidates("task-1")

        assert "task-2" in candidates

    def test_multiple_dependencies(self, manager: DependencyManager) -> None:
        """Test task with multiple dependencies."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_dependency("task-1", "task-3")
        manager.add_dependency("task-2", "task-3")

        # Task-3 blocked by both
        assert not manager.is_ready("task-3")

        # Complete task-1
        manager.update_task_status("task-1", TaskStatus.COMPLETED)

        # Still blocked by task-2
        assert not manager.is_ready("task-3")

        # Complete task-2
        newly_unblocked = manager.update_task_status("task-2", TaskStatus.COMPLETED)

        # Now ready
        assert "task-3" in newly_unblocked
        assert manager.is_ready("task-3")


class TestEventIntegration:
    """Test event integration with manager."""

    @pytest.fixture
    def manager(self) -> DependencyManager:
        """Create manager."""
        return DependencyManager()

    def test_blocked_event(self, manager: DependencyManager) -> None:
        """Test blocked event is emitted."""
        handler = MagicMock()
        manager.event_emitter.on(DependencyEvent.TASK_BLOCKED, handler)

        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        handler.assert_called()
        call_data = handler.call_args[0][0]
        assert call_data.task_id == "task-2"

    def test_unblocked_event(self, manager: DependencyManager) -> None:
        """Test unblocked event is emitted."""
        handler = MagicMock()
        manager.event_emitter.on(DependencyEvent.TASK_UNBLOCKED, handler)

        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        manager.update_task_status("task-1", TaskStatus.COMPLETED)

        handler.assert_called()
        call_data = handler.call_args[0][0]
        assert call_data.task_id == "task-2"

    def test_dependency_satisfied_event(self, manager: DependencyManager) -> None:
        """Test dependency satisfied event."""
        handler = MagicMock()
        manager.event_emitter.on(DependencyEvent.DEPENDENCY_SATISFIED, handler)

        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_dependency("task-1", "task-2")

        manager.update_task_status("task-1", TaskStatus.COMPLETED)

        handler.assert_called()


class TestSerialization:
    """Test serialization."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        manager = DependencyManager()
        manager.add_task("task-1", TaskStatus.COMPLETED)
        manager.add_task("task-2", TaskStatus.PENDING)
        manager.add_dependency("task-1", "task-2")

        data = manager.to_dict()

        assert "graph" in data
        assert "task_statuses" in data
        assert data["task_statuses"]["task-1"] == "completed"
        assert data["task_statuses"]["task-2"] == "pending"

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "graph": {
                "tasks": [
                    {"id": "task-1"},
                    {"id": "task-2"},
                ],
                "edges": [
                    {
                        "dependency_id": "task-1",
                        "dependent_id": "task-2",
                        "dependency_type": "blocks",
                    }
                ],
            },
            "task_statuses": {
                "task-1": "completed",
                "task-2": "pending",
            },
        }

        manager = DependencyManager.from_dict(data)

        assert len(manager) == 2
        assert manager.get_task_status("task-1") == TaskStatus.COMPLETED

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = DependencyManager()
        original.add_task("task-1", TaskStatus.COMPLETED)
        original.add_task("task-2", TaskStatus.PENDING)
        original.add_dependency("task-1", "task-2")

        data = original.to_dict()
        restored = DependencyManager.from_dict(data)

        assert len(restored) == len(original)
        assert restored.get_task_status("task-1") == TaskStatus.COMPLETED
        assert restored.get_task_status("task-2") == TaskStatus.PENDING


class TestConvenienceFunction:
    """Test convenience function."""

    def test_create_dependency_manager(self) -> None:
        """Test creating manager via convenience function."""
        manager = create_dependency_manager()

        assert isinstance(manager, DependencyManager)
        assert len(manager) == 0


class TestComplexScenarios:
    """Test complex dependency scenarios."""

    @pytest.fixture
    def manager(self) -> DependencyManager:
        """Create manager."""
        return DependencyManager()

    def test_diamond_dependencies(self, manager: DependencyManager) -> None:
        """Test diamond dependency pattern."""
        # task-1 -> task-2 -> task-4
        # task-1 -> task-3 -> task-4
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_task("task-4")

        manager.add_dependency("task-1", "task-2")
        manager.add_dependency("task-1", "task-3")
        manager.add_dependency("task-2", "task-4")
        manager.add_dependency("task-3", "task-4")

        # All except task-1 should be blocked
        assert manager.is_ready("task-1")
        assert not manager.is_ready("task-2")
        assert not manager.is_ready("task-3")
        assert not manager.is_ready("task-4")

        # Complete task-1
        manager.update_task_status("task-1", TaskStatus.COMPLETED)

        # task-2 and task-3 should now be ready
        assert manager.is_ready("task-2")
        assert manager.is_ready("task-3")
        assert not manager.is_ready("task-4")

        # Complete task-2
        manager.update_task_status("task-2", TaskStatus.COMPLETED)

        # task-4 still blocked by task-3
        assert not manager.is_ready("task-4")

        # Complete task-3
        manager.update_task_status("task-3", TaskStatus.COMPLETED)

        # Now task-4 should be ready
        assert manager.is_ready("task-4")

    def test_chain_completion(self, manager: DependencyManager) -> None:
        """Test completing a chain of tasks."""
        # task-1 -> task-2 -> task-3 -> task-4
        for i in range(1, 5):
            manager.add_task(f"task-{i}")
            if i > 1:
                manager.add_dependency(f"task-{i-1}", f"task-{i}")

        # Complete in order
        for i in range(1, 5):
            assert manager.is_ready(f"task-{i}")
            manager.update_task_status(f"task-{i}", TaskStatus.COMPLETED)

    def test_partial_failure(self, manager: DependencyManager) -> None:
        """Test handling partial failures."""
        manager.add_task("task-1")
        manager.add_task("task-2")
        manager.add_task("task-3")
        manager.add_dependency("task-1", "task-3")
        manager.add_dependency("task-2", "task-3")

        # Fail one dependency
        manager.update_task_status("task-1", TaskStatus.FAILED)

        # task-3 should still be blocked
        assert not manager.is_ready("task-3")

        # Complete the other dependency
        manager.update_task_status("task-2", TaskStatus.COMPLETED)

        # task-3 still blocked by failed task-1
        assert not manager.is_ready("task-3")
