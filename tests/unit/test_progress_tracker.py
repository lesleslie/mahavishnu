"""Tests for ProgressTracker - Operation progress tracking."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any

from mahavishnu.core.progress_tracker import (
    ProgressTracker,
    ProgressState,
    ProgressTask,
    ProgressSpinner,
    ProgressBar,
)


@pytest.fixture
def mock_console() -> MagicMock:
    """Create a mock Rich console."""
    return MagicMock()


@pytest.fixture
def sample_task() -> ProgressTask:
    """Create a sample progress task."""
    return ProgressTask(
        task_id="prog-1",
        description="Processing files",
        total=100,
        completed=0,
    )


class TestProgressState:
    """Tests for ProgressState enum."""

    def test_progress_states(self) -> None:
        """Test available progress states."""
        assert ProgressState.PENDING.value == "pending"
        assert ProgressState.RUNNING.value == "running"
        assert ProgressState.COMPLETED.value == "completed"
        assert ProgressState.FAILED.value == "failed"
        assert ProgressState.CANCELLED.value == "cancelled"


class TestProgressTask:
    """Tests for ProgressTask dataclass."""

    def test_create_progress_task(self) -> None:
        """Create a progress task."""
        task = ProgressTask(
            task_id="prog-1",
            description="Processing",
            total=100,
            completed=0,
        )

        assert task.task_id == "prog-1"
        assert task.total == 100
        assert task.completed == 0
        assert task.state == ProgressState.PENDING

    def test_progress_task_percentage(self) -> None:
        """Calculate progress percentage."""
        task = ProgressTask(
            task_id="prog-2",
            description="Task",
            total=100,
            completed=50,
        )

        assert task.percentage == 50.0

    def test_progress_task_eta(self) -> None:
        """Calculate ETA."""
        from datetime import timedelta

        task = ProgressTask(
            task_id="prog-3",
            description="Task",
            total=100,
            completed=50,
            start_time=datetime.now(UTC) - timedelta(seconds=10),
        )

        eta = task.estimate_remaining()
        assert eta is not None
        assert eta > 0

    def test_progress_task_to_dict(self) -> None:
        """Convert task to dictionary."""
        task = ProgressTask(
            task_id="prog-4",
            description="Task",
            total=100,
            completed=25,
        )

        d = task.to_dict()
        assert d["task_id"] == "prog-4"
        assert d["percentage"] == 25.0


class TestProgressSpinner:
    """Tests for ProgressSpinner class."""

    def test_create_spinner(self) -> None:
        """Create a progress spinner."""
        spinner = ProgressSpinner("Loading...")

        assert spinner.message == "Loading..."
        assert spinner.active is False

    def test_spinner_frames(self) -> None:
        """Test spinner frame iteration."""
        spinner = ProgressSpinner("Processing")

        frame = spinner.next_frame()
        assert frame is not None
        assert len(frame) > 0

    def test_spinner_cycle(self) -> None:
        """Test spinner cycles through frames."""
        spinner = ProgressSpinner("Task", frames=["a", "b", "c"])

        frames = [spinner.next_frame() for _ in range(6)]
        assert frames[0] == frames[3]  # Should cycle
        assert frames[1] == frames[4]


class TestProgressBar:
    """Tests for ProgressBar class."""

    def test_create_progress_bar(self) -> None:
        """Create a progress bar."""
        bar = ProgressBar(total=100, width=50)

        assert bar.total == 100
        assert bar.width == 50

    def test_render_progress_bar(self) -> None:
        """Render progress bar."""
        bar = ProgressBar(total=100, width=20)

        rendered = bar.render(50)
        assert rendered is not None
        assert "50" in rendered or "█" in rendered

    def test_render_complete_bar(self) -> None:
        """Render complete progress bar."""
        bar = ProgressBar(total=100, width=20)

        rendered = bar.render(100)
        assert "100" in rendered or "█" in rendered

    def test_render_zero_progress(self) -> None:
        """Render zero progress."""
        bar = ProgressBar(total=100, width=20)

        rendered = bar.render(0)
        assert rendered is not None


class TestProgressTracker:
    """Tests for ProgressTracker class."""

    def test_create_tracker(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Create a progress tracker."""
        tracker = ProgressTracker(console=mock_console)

        assert tracker is not None
        assert len(tracker.tasks) == 0

    def test_add_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Add a progress task."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task(
            description="Processing files",
            total=100,
        )

        assert task_id is not None
        assert len(tracker.tasks) == 1

    def test_update_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Update progress task."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task("Task", total=100)
        tracker.update_task(task_id, advance=25)

        task = tracker.get_task(task_id)
        assert task is not None
        assert task.completed == 25

    def test_complete_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Complete a progress task."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task("Task", total=100)
        tracker.complete_task(task_id)

        task = tracker.get_task(task_id)
        assert task is not None
        assert task.state == ProgressState.COMPLETED

    def test_fail_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Fail a progress task."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task("Task", total=100)
        tracker.fail_task(task_id, "Error occurred")

        task = tracker.get_task(task_id)
        assert task is not None
        assert task.state == ProgressState.FAILED

    def test_cancel_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Cancel a progress task."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task("Task", total=100)
        tracker.cancel_task(task_id)

        task = tracker.get_task(task_id)
        assert task is not None
        assert task.state == ProgressState.CANCELLED

    def test_get_nonexistent_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Get task that doesn't exist."""
        tracker = ProgressTracker(console=mock_console)

        task = tracker.get_task("nonexistent")
        assert task is None

    def test_start_spinner(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Start a spinner for indeterminate progress."""
        tracker = ProgressTracker(console=mock_console)

        spinner_id = tracker.start_spinner("Loading...")
        assert spinner_id is not None

        tracker.stop_spinner(spinner_id)

    def test_multiple_tasks(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Track multiple progress tasks."""
        tracker = ProgressTracker(console=mock_console)

        task1 = tracker.add_task("Task 1", total=100)
        task2 = tracker.add_task("Task 2", total=200)

        tracker.update_task(task1, advance=50)
        tracker.update_task(task2, advance=100)

        assert tracker.get_task(task1).completed == 50
        assert tracker.get_task(task2).completed == 100

    def test_overall_progress(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Calculate overall progress across tasks."""
        tracker = ProgressTracker(console=mock_console)

        task1 = tracker.add_task("Task 1", total=100)
        task2 = tracker.add_task("Task 2", total=100)

        tracker.update_task(task1, completed=50)
        tracker.update_task(task2, completed=75)

        overall = tracker.get_overall_progress()
        assert overall == 62.5  # (50 + 75) / 200 * 100

    def test_get_statistics(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Get progress statistics."""
        tracker = ProgressTracker(console=mock_console)

        tracker.add_task("Task 1", total=100)
        tracker.add_task("Task 2", total=100)

        stats = tracker.get_statistics()

        assert stats["total_tasks"] == 2
        assert stats["pending_tasks"] == 2
        assert stats["running_tasks"] == 0

    @pytest.mark.asyncio
    async def test_track_operation(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Track an async operation with progress."""

        async def operation(update: Any) -> str:
            for i in range(5):
                update(advance=20)
            return "done"

        tracker = ProgressTracker(console=mock_console)

        result = await tracker.track_operation(
            description="Processing",
            operation=operation,
            total=100,
        )

        assert result == "done"

    def test_display_mode_quiet(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Quiet mode suppresses output."""
        tracker = ProgressTracker(
            console=mock_console,
            quiet=True,
        )

        tracker.add_task("Task", total=100)
        tracker.update_task("prog-1", advance=50)

        # Should not print in quiet mode
        mock_console.print.assert_not_called()

    def test_elapsed_time(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Track elapsed time."""
        from datetime import timedelta

        tracker = ProgressTracker(console=mock_console)
        task_id = tracker.add_task("Task", total=100)

        # Simulate some time passing
        task = tracker.get_task(task_id)
        task.start_time = datetime.now(UTC) - timedelta(seconds=30)

        elapsed = tracker.get_elapsed_time(task_id)
        assert elapsed is not None
        assert elapsed >= 30

    def test_format_time(self) -> None:
        """Test time formatting."""
        formatted = ProgressTracker.format_time(3661)
        assert "1h" in formatted or "60m" in formatted or "3661" in formatted

        formatted_short = ProgressTracker.format_time(45)
        assert "45" in formatted_short

    def test_task_with_metadata(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Create task with metadata."""
        tracker = ProgressTracker(console=mock_console)

        task_id = tracker.add_task(
            "Task",
            total=100,
            metadata={"file": "data.json", "size": "1MB"},
        )

        task = tracker.get_task(task_id)
        assert task is not None
        assert task.metadata["file"] == "data.json"

    def test_clear_completed(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Clear completed tasks."""
        tracker = ProgressTracker(console=mock_console)

        task1 = tracker.add_task("Task 1", total=100)
        task2 = tracker.add_task("Task 2", total=100)

        tracker.complete_task(task1)

        tracker.clear_completed()

        assert tracker.get_task(task1) is None
        assert tracker.get_task(task2) is not None

    def test_subtask_tracking(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Track subtasks within a main task."""
        tracker = ProgressTracker(console=mock_console)

        main_task = tracker.add_task("Main", total=100)
        subtask1 = tracker.add_task("Sub 1", total=50, parent_id=main_task)
        subtask2 = tracker.add_task("Sub 2", total=50, parent_id=main_task)

        tracker.update_task(subtask1, completed=50)
        tracker.update_task(subtask2, completed=25)

        # Main task progress should reflect subtasks
        main = tracker.get_task(main_task)
        assert main is not None
