"""Onboarding Flow for Mahavishnu.

Provides an interactive tutorial for new users:
- Step-by-step guidance
- Progress tracking
- Skip option
- Task creation walkthrough
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


class OnboardingStep(str, Enum):
    """Onboarding steps in order."""

    WELCOME = "welcome"
    CREATE_FIRST_TASK = "create_first_task"
    LIST_TASKS = "list_tasks"
    UPDATE_TASK = "update_task"
    SEARCH_TASKS = "search_tasks"
    COMPLETE = "complete"


class OnboardingStatus(str, Enum):
    """Status of onboarding process."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SKIPPED = "skipped"
    COMPLETED = "completed"


@dataclass
class TutorialStep:
    """A single step in the tutorial."""

    id: OnboardingStep
    title: str
    description: str
    instructions: list[str]
    tips: list[str] = field(default_factory=list)
    action_required: bool = False
    action_label: str = ""
    action_callback: Callable[[], Any] | None = None


# Define tutorial steps
TUTORIAL_STEPS: list[TutorialStep] = [
    TutorialStep(
        id=OnboardingStep.WELCOME,
        title="Welcome to Mahavishnu!",
        description="Mahavishnu is a multi-engine orchestration platform for managing tasks across multiple repositories.",
        instructions=[
            "Mahavishnu helps you create, track, and manage tasks",
            "You can search tasks semantically to find related work",
            "All tasks are stored in PostgreSQL with full history tracking",
        ],
        tips=[
            "Use 'mhv' as a shorthand for 'mahavishnu'",
            "Press Ctrl+K to open the command palette",
        ],
    ),
    TutorialStep(
        id=OnboardingStep.CREATE_FIRST_TASK,
        title="Create Your First Task",
        description="Let's create a simple task to get started.",
        instructions=[
            "Run: mahavishnu task create \"My First Task\" -r mahavishnu",
            "The -r flag specifies the repository",
            "You can also add priority with -p high",
        ],
        tips=[
            "Shorthand: mhv tc \"Task title\" -r repo",
            "Tasks need at least a title and repository",
        ],
        action_required=True,
        action_label="Create Task",
    ),
    TutorialStep(
        id=OnboardingStep.LIST_TASKS,
        title="List Your Tasks",
        description="View all your tasks with filters.",
        instructions=[
            "Run: mahavishnu task list",
            "Filter by repository: mahavishnu task list -r mahavishnu",
            "Filter by status: mahavishnu task list -s in_progress",
        ],
        tips=[
            "Shorthand: mhv tl",
            "Use --json for machine-readable output",
        ],
        action_required=True,
        action_label="List Tasks",
    ),
    TutorialStep(
        id=OnboardingStep.UPDATE_TASK,
        title="Update a Task",
        description="Change task status, priority, or other properties.",
        instructions=[
            "Get task ID from list command",
            "Run: mahavishnu task update <task-id> -s completed",
            "Or use shorthand: mhv tu <task-id> -s completed",
        ],
        tips=[
            "Quick status update: mhv ts <task-id> completed",
            "You can update multiple fields at once",
        ],
        action_required=True,
        action_label="Update Task",
    ),
    TutorialStep(
        id=OnboardingStep.SEARCH_TASKS,
        title="Search Tasks Semantically",
        description="Find related tasks using semantic search.",
        instructions=[
            "Run: mahavishnu search tasks \"bug fix\"",
            "Results are ranked by semantic similarity",
            "Combine with filters for precision",
        ],
        tips=[
            "Search understands context, not just keywords",
            "Use quotes for exact phrase matching",
        ],
        action_required=True,
        action_label="Search Tasks",
    ),
    TutorialStep(
        id=OnboardingStep.COMPLETE,
        title="You're All Set!",
        description="Congratulations! You've completed the onboarding.",
        instructions=[
            "You now know the basics of Mahavishnu",
            "Explore the command palette with Ctrl+K",
            "Check the documentation for advanced features",
        ],
        tips=[
            "Run 'mahavishnu --help' for all commands",
            "Visit docs.mahavishnu.org for more",
        ],
    ),
]


class OnboardingProgress(BaseModel):
    """Tracks onboarding progress for a user."""

    model_config = ConfigDict(extra="forbid")

    status: OnboardingStatus = Field(default=OnboardingStatus.NOT_STARTED)
    current_step: int = Field(default=0, ge=0)
    completed_steps: list[str] = Field(default_factory=list)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    skipped_at: datetime | None = Field(default=None)
    skipped_from_step: int | None = Field(default=None)

    def start(self) -> None:
        """Start the onboarding process."""
        if self.status == OnboardingStatus.NOT_STARTED:
            self.status = OnboardingStatus.IN_PROGRESS
            self.started_at = datetime.now(UTC)
            self.current_step = 0

    def advance(self) -> bool:
        """Advance to the next step.

        Returns:
            True if advanced, False if already at last step
        """
        if self.status != OnboardingStatus.IN_PROGRESS:
            return False

        current_step_id = TUTORIAL_STEPS[self.current_step].id.value
        if current_step_id not in self.completed_steps:
            self.completed_steps.append(current_step_id)

        if self.current_step < len(TUTORIAL_STEPS) - 1:
            self.current_step += 1
            return True
        else:
            # Completed all steps
            self.status = OnboardingStatus.COMPLETED
            self.completed_at = datetime.now(UTC)
            return False

    def skip(self) -> None:
        """Skip the onboarding process."""
        self.status = OnboardingStatus.SKIPPED
        self.skipped_at = datetime.now(UTC)
        self.skipped_from_step = self.current_step

    def go_to_step(self, step_index: int) -> bool:
        """Go to a specific step.

        Args:
            step_index: Index of the step to go to

        Returns:
            True if step was valid, False otherwise
        """
        if 0 <= step_index < len(TUTORIAL_STEPS):
            self.current_step = step_index
            return True
        return False

    def get_completion_percentage(self) -> float:
        """Get the percentage of onboarding completed."""
        total_steps = len(TUTORIAL_STEPS)
        if self.status == OnboardingStatus.COMPLETED:
            return 100.0
        if self.status == OnboardingStatus.SKIPPED:
            completed = len(self.completed_steps)
            return (completed / total_steps) * 100
        return (len(self.completed_steps) / total_steps) * 100


class OnboardingManager:
    """Manages the onboarding flow."""

    def __init__(self) -> None:
        self._progress: OnboardingProgress = OnboardingProgress()

    @property
    def progress(self) -> OnboardingProgress:
        """Get current progress."""
        return self._progress

    @property
    def current_step(self) -> TutorialStep | None:
        """Get the current tutorial step."""
        if self._progress.status not in (
            OnboardingStatus.NOT_STARTED,
            OnboardingStatus.IN_PROGRESS,
        ):
            return None
        if self._progress.current_step >= len(TUTORIAL_STEPS):
            return None
        return TUTORIAL_STEPS[self._progress.current_step]

    def start(self) -> TutorialStep:
        """Start the onboarding process.

        Returns:
            The first tutorial step
        """
        self._progress.start()
        return TUTORIAL_STEPS[0]

    def advance(self) -> TutorialStep | None:
        """Advance to the next step.

        Returns:
            The next tutorial step, or None if completed
        """
        has_more = self._progress.advance()
        if has_more:
            return TUTORIAL_STEPS[self._progress.current_step]
        return None

    def skip(self) -> None:
        """Skip the onboarding."""
        self._progress.skip()
        logger.info("Onboarding skipped by user")

    def get_step(self, step_id: OnboardingStep) -> TutorialStep | None:
        """Get a specific step by ID."""
        for step in TUTORIAL_STEPS:
            if step.id == step_id:
                return step
        return None

    def should_show_onboarding(self) -> bool:
        """Check if onboarding should be shown."""
        return self._progress.status == OnboardingStatus.NOT_STARTED

    def is_completed(self) -> bool:
        """Check if onboarding is completed."""
        return self._progress.status == OnboardingStatus.COMPLETED

    def is_skipped(self) -> bool:
        """Check if onboarding was skipped."""
        return self._progress.status == OnboardingStatus.SKIPPED

    def reset(self) -> None:
        """Reset onboarding progress."""
        self._progress = OnboardingProgress()
        logger.info("Onboarding progress reset")


# Singleton instance
_onboarding_manager: OnboardingManager | None = None


def get_onboarding_manager() -> OnboardingManager:
    """Get the singleton onboarding manager."""
    global _onboarding_manager
    if _onboarding_manager is None:
        _onboarding_manager = OnboardingManager()
    return _onboarding_manager


def format_step_output(step: TutorialStep, step_number: int, total_steps: int) -> str:
    """Format a step for display in the terminal.

    Args:
        step: The tutorial step
        step_number: Current step number (1-indexed)
        total_steps: Total number of steps

    Returns:
        Formatted string for terminal display
    """
    lines = [
        f"\n{'=' * 60}",
        f"Step {step_number}/{total_steps}: {step.title}",
        f"{'=' * 60}",
        f"\n{step.description}",
        "\nInstructions:",
    ]

    for i, instruction in enumerate(step.instructions, 1):
        lines.append(f"  {i}. {instruction}")

    if step.tips:
        lines.append("\nTips:")
        for tip in step.tips:
            lines.append(f"  • {tip}")

    if step.action_required:
        lines.append(f"\n[Action Required: {step.action_label}]")

    lines.append("\nPress Enter to continue, 's' to skip, 'q' to quit")
    lines.append("")

    return "\n".join(lines)


def format_welcome_message() -> str:
    """Format the welcome message for onboarding."""
    return """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║     Welcome to Mahavishnu!                                   ║
║     ─────────────────────                                    ║
║                                                              ║
║     Mahavishnu is a multi-engine orchestration platform      ║
║     for managing tasks across multiple repositories.         ║
║                                                              ║
║     Would you like to take a quick tutorial?                 ║
║     (You can skip it and run it later with 'mhv tutorial')   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

[Y]es, show me around    [S]kip for now    [N]ever ask again
"""
