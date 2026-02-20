"""Progress Tracker for Mahavishnu.

Tracks progress of long-running operations:
- Progress bars for determinate operations
- Spinners for indeterminate operations
- Multi-task progress tracking
- Time estimation and ETA

Usage:
    from mahavishnu.core.progress_tracker import ProgressTracker

    tracker = ProgressTracker()

    # Add a task
    task_id = tracker.add_task("Processing files", total=100)

    # Update progress
    tracker.update_task(task_id, advance=10)

    # Complete
    tracker.complete_task(task_id)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class ProgressState(str, Enum):
    """State of a progress task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ProgressTask:
    """A trackable progress task.

    Attributes:
        task_id: Unique identifier
        description: Human-readable description
        total: Total units to complete
        completed: Units completed so far
        state: Current state
        start_time: When task started
        end_time: When task completed
        parent_id: Optional parent task ID
        metadata: Additional metadata
    """

    task_id: str
    description: str
    total: int | float
    completed: int | float = 0
    state: ProgressState = ProgressState.PENDING
    start_time: datetime | None = None
    end_time: datetime | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    @property
    def percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total == 0:
            return 100.0
        return (self.completed / self.total) * 100

    def estimate_remaining(self) -> float | None:
        """Estimate remaining time in seconds.

        Returns:
            Estimated seconds remaining, or None if cannot estimate
        """
        if not self.start_time or self.completed == 0:
            return None

        elapsed = (datetime.now(UTC) - self.start_time).total_seconds()
        rate = self.completed / elapsed

        if rate == 0:
            return None

        remaining = self.total - self.completed
        return remaining / rate

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "total": self.total,
            "completed": self.completed,
            "percentage": self.percentage,
            "state": self.state.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "parent_id": self.parent_id,
            "error_message": self.error_message,
        }


class ProgressSpinner:
    """A text-based spinner for indeterminate progress.

    Attributes:
        message: Message to display
        frames: Spinner frame characters
        active: Whether spinner is active
    """

    DEFAULT_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(
        self,
        message: str,
        frames: list[str] | None = None,
    ) -> None:
        """Initialize spinner.

        Args:
            message: Message to display
            frames: Optional custom frame characters
        """
        self.message = message
        self.frames = frames or self.DEFAULT_FRAMES
        self.active = False
        self._frame_index = 0

    def start(self) -> None:
        """Start the spinner."""
        self.active = True
        self._frame_index = 0

    def stop(self) -> None:
        """Stop the spinner."""
        self.active = False

    def next_frame(self) -> str:
        """Get the next frame.

        Returns:
            Current spinner frame character
        """
        frame = self.frames[self._frame_index]
        self._frame_index = (self._frame_index + 1) % len(self.frames)
        return frame

    def render(self) -> str:
        """Render current spinner state.

        Returns:
            Rendered spinner string
        """
        frame = self.next_frame()
        return f"{frame} {self.message}"


class ProgressBar:
    """A text-based progress bar.

    Attributes:
        total: Total units
        width: Bar width in characters
    """

    def __init__(
        self,
        total: int | float,
        width: int = 40,
        fill_char: str = "█",
        empty_char: str = "░",
    ) -> None:
        """Initialize progress bar.

        Args:
            total: Total units
            width: Bar width in characters
            fill_char: Character for filled portion
            empty_char: Character for empty portion
        """
        self.total = total
        self.width = width
        self.fill_char = fill_char
        self.empty_char = empty_char

    def render(self, completed: int | float) -> str:
        """Render progress bar.

        Args:
            completed: Units completed

        Returns:
            Rendered progress bar string
        """
        if self.total == 0:
            percentage = 100
        else:
            percentage = min(100, (completed / self.total) * 100)

        filled_width = int(self.width * percentage / 100)
        empty_width = self.width - filled_width

        bar = self.fill_char * filled_width + self.empty_char * empty_width
        return f"[{bar}] {percentage:.0f}%"


class ProgressTracker:
    """Tracks progress of operations.

    Features:
    - Track multiple concurrent tasks
    - Progress bars and spinners
    - Time estimation and ETA
    - Subtask tracking
    - Quiet mode for non-interactive use

    Example:
        tracker = ProgressTracker()

        # Add task
        task_id = tracker.add_task("Processing", total=100)

        # Update progress
        for i in range(100):
            tracker.update_task(task_id, advance=1)

        # Complete
        tracker.complete_task(task_id)
    """

    def __init__(
        self,
        console: Any = None,  # Rich Console
        quiet: bool = False,
    ) -> None:
        """Initialize progress tracker.

        Args:
            console: Optional Rich Console
            quiet: If True, suppress output
        """
        self._console = console
        self._quiet = quiet
        self.tasks: dict[str, ProgressTask] = {}
        self._spinners: dict[str, ProgressSpinner] = {}

        # Try to get console if not provided
        if self._console is None and not quiet:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                pass

    def _generate_id(self) -> str:
        """Generate unique task ID."""
        return f"prog-{uuid.uuid4().hex[:8]}"

    def add_task(
        self,
        description: str,
        total: int | float,
        completed: int | float = 0,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a new progress task.

        Args:
            description: Task description
            total: Total units
            completed: Initial completed units
            parent_id: Optional parent task ID
            metadata: Optional metadata

        Returns:
            Task ID
        """
        task_id = self._generate_id()

        task = ProgressTask(
            task_id=task_id,
            description=description,
            total=total,
            completed=completed,
            parent_id=parent_id,
            metadata=metadata or {},
        )

        self.tasks[task_id] = task

        if not self._quiet and self._console:
            self._display_task(task)

        return task_id

    def get_task(self, task_id: str) -> ProgressTask | None:
        """Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            ProgressTask if found, None otherwise
        """
        return self.tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        completed: int | float | None = None,
        advance: int | float | None = None,
        description: str | None = None,
    ) -> bool:
        """Update task progress.

        Args:
            task_id: Task ID
            completed: Set completed to this value
            advance: Add this to completed
            description: Update description

        Returns:
            True if updated, False if not found
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        # Start task if first update
        if task.state == ProgressState.PENDING:
            task.state = ProgressState.RUNNING
            task.start_time = datetime.now(UTC)

        # Update completed
        if completed is not None:
            task.completed = completed
        elif advance is not None:
            task.completed += advance

        # Update description
        if description:
            task.description = description

        # Check for completion
        if task.completed >= task.total:
            task.completed = task.total

        if not self._quiet and self._console:
            self._display_task(task)

        # Update parent if exists
        if task.parent_id:
            self._update_parent_progress(task.parent_id)

        return True

    def _update_parent_progress(self, parent_id: str) -> None:
        """Update parent task progress from children."""
        parent = self.tasks.get(parent_id)
        if not parent:
            return

        # Get all children
        children = [
            t for t in self.tasks.values()
            if t.parent_id == parent_id
        ]

        if not children:
            return

        # Sum up child progress
        total_completed = sum(t.completed for t in children)
        parent.completed = total_completed

    def complete_task(self, task_id: str) -> bool:
        """Mark task as completed.

        Args:
            task_id: Task ID

        Returns:
            True if completed, False if not found
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        task.state = ProgressState.COMPLETED
        task.completed = task.total
        task.end_time = datetime.now(UTC)

        if not self._quiet and self._console:
            self._display_task(task)

        return True

    def fail_task(self, task_id: str, error_message: str = "") -> bool:
        """Mark task as failed.

        Args:
            task_id: Task ID
            error_message: Error description

        Returns:
            True if failed, False if not found
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        task.state = ProgressState.FAILED
        task.error_message = error_message
        task.end_time = datetime.now(UTC)

        if not self._quiet and self._console:
            self._display_task(task)

        return True

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task.

        Args:
            task_id: Task ID

        Returns:
            True if cancelled, False if not found
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        task.state = ProgressState.CANCELLED
        task.end_time = datetime.now(UTC)

        return True

    def start_spinner(self, message: str) -> str:
        """Start an indeterminate spinner.

        Args:
            message: Spinner message

        Returns:
            Spinner ID
        """
        spinner_id = self._generate_id()
        spinner = ProgressSpinner(message)
        spinner.start()
        self._spinners[spinner_id] = spinner
        return spinner_id

    def stop_spinner(self, spinner_id: str) -> bool:
        """Stop a spinner.

        Args:
            spinner_id: Spinner ID

        Returns:
            True if stopped, False if not found
        """
        spinner = self._spinners.get(spinner_id)
        if not spinner:
            return False

        spinner.stop()
        del self._spinners[spinner_id]
        return True

    def get_overall_progress(self) -> float:
        """Get overall progress across all tasks.

        Returns:
            Overall percentage (0-100)
        """
        if not self.tasks:
            return 0.0

        total = sum(t.total for t in self.tasks.values())
        completed = sum(t.completed for t in self.tasks.values())

        if total == 0:
            return 100.0

        return (completed / total) * 100

    def get_statistics(self) -> dict[str, Any]:
        """Get progress statistics.

        Returns:
            Dictionary with statistics
        """
        pending = sum(1 for t in self.tasks.values() if t.state == ProgressState.PENDING)
        running = sum(1 for t in self.tasks.values() if t.state == ProgressState.RUNNING)
        completed = sum(1 for t in self.tasks.values() if t.state == ProgressState.COMPLETED)
        failed = sum(1 for t in self.tasks.values() if t.state == ProgressState.FAILED)
        cancelled = sum(1 for t in self.tasks.values() if t.state == ProgressState.CANCELLED)

        return {
            "total_tasks": len(self.tasks),
            "pending_tasks": pending,
            "running_tasks": running,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "cancelled_tasks": cancelled,
            "overall_progress": self.get_overall_progress(),
        }

    def get_elapsed_time(self, task_id: str) -> float | None:
        """Get elapsed time for a task.

        Args:
            task_id: Task ID

        Returns:
            Elapsed seconds, or None if task not found or not started
        """
        task = self.tasks.get(task_id)
        if not task or not task.start_time:
            return None

        end = task.end_time or datetime.now(UTC)
        return (end - task.start_time).total_seconds()

    def clear_completed(self) -> int:
        """Remove completed, failed, and cancelled tasks.

        Returns:
            Number of tasks cleared
        """
        to_remove = [
            task_id for task_id, task in self.tasks.items()
            if task.state in (ProgressState.COMPLETED, ProgressState.FAILED, ProgressState.CANCELLED)
        ]

        for task_id in to_remove:
            del self.tasks[task_id]

        return len(to_remove)

    def _display_task(self, task: ProgressTask) -> None:
        """Display task progress."""
        if not self._console:
            return

        bar = ProgressBar(task.total)

        state_indicator = {
            ProgressState.PENDING: "○",
            ProgressState.RUNNING: "◐",
            ProgressState.COMPLETED: "●",
            ProgressState.FAILED: "✗",
            ProgressState.CANCELLED: "⊘",
        }.get(task.state, "○")

        eta_str = ""
        if task.state == ProgressState.RUNNING:
            eta = task.estimate_remaining()
            if eta:
                eta_str = f" ETA: {self.format_time(eta)}"

        message = f"{state_indicator} {task.description}: {bar.render(task.completed)}{eta_str}"

        if task.error_message:
            message += f" [{task.error_message}]"

        self._console.print(message)

    @staticmethod
    def format_time(seconds: float) -> str:
        """Format time in human-readable form.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    async def track_operation(
        self,
        description: str,
        operation: Callable[[Callable], Coroutine[Any, Any, Any]],
        total: int | float,
    ) -> Any:
        """Track an async operation with progress.

        Args:
            description: Task description
            operation: Async function to track
            total: Total units

        Returns:
            Operation result
        """
        task_id = self.add_task(description, total)

        def update(completed: int | float | None = None, advance: int | float | None = None) -> None:
            self.update_task(task_id, completed=completed, advance=advance)

        try:
            result = await operation(update)
            self.complete_task(task_id)
            return result
        except Exception as e:
            self.fail_task(task_id, str(e))
            raise


__all__ = [
    "ProgressTracker",
    "ProgressState",
    "ProgressTask",
    "ProgressSpinner",
    "ProgressBar",
]
