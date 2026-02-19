"""Tests for Onboarding Module.

Tests cover:
- Tutorial steps
- Progress tracking
- Onboarding flow
"""

from __future__ import annotations

import pytest
from datetime import datetime, UTC

from mahavishnu.core.onboarding import (
    OnboardingManager,
    OnboardingProgress,
    OnboardingStep,
    OnboardingStatus,
    TutorialStep,
    TUTORIAL_STEPS,
    format_step_output,
    format_welcome_message,
    get_onboarding_manager,
)


class TestOnboardingStep:
    """Test OnboardingStep enum."""

    def test_all_steps_defined(self) -> None:
        """Test all step values are defined."""
        steps = list(OnboardingStep)
        assert len(steps) == 6
        assert OnboardingStep.WELCOME in steps
        assert OnboardingStep.CREATE_FIRST_TASK in steps
        assert OnboardingStep.COMPLETE in steps


class TestTutorialStep:
    """Test TutorialStep dataclass."""

    def test_minimal_step(self) -> None:
        """Test minimal step creation."""
        step = TutorialStep(
            id=OnboardingStep.WELCOME,
            title="Welcome",
            description="Welcome message",
            instructions=["Do this"],
        )
        assert step.id == OnboardingStep.WELCOME
        assert step.title == "Welcome"
        assert step.instructions == ["Do this"]
        assert step.tips == []
        assert step.action_required is False

    def test_full_step(self) -> None:
        """Test step with all fields."""
        step = TutorialStep(
            id=OnboardingStep.CREATE_FIRST_TASK,
            title="Create Task",
            description="Create your first task",
            instructions=["Run command", "Check result"],
            tips=["Tip 1", "Tip 2"],
            action_required=True,
            action_label="Create",
        )
        assert len(step.instructions) == 2
        assert len(step.tips) == 2
        assert step.action_required is True
        assert step.action_label == "Create"


class TestTutorialSteps:
    """Test predefined tutorial steps."""

    def test_steps_exist(self) -> None:
        """Test tutorial steps are defined."""
        assert len(TUTORIAL_STEPS) == 6

    def test_steps_in_order(self) -> None:
        """Test steps are in correct order."""
        expected_order = [
            OnboardingStep.WELCOME,
            OnboardingStep.CREATE_FIRST_TASK,
            OnboardingStep.LIST_TASKS,
            OnboardingStep.UPDATE_TASK,
            OnboardingStep.SEARCH_TASKS,
            OnboardingStep.COMPLETE,
        ]
        for i, step in enumerate(TUTORIAL_STEPS):
            assert step.id == expected_order[i]

    def test_all_steps_have_content(self) -> None:
        """Test all steps have required content."""
        for step in TUTORIAL_STEPS:
            assert step.title, f"Step {step.id} missing title"
            assert step.description, f"Step {step.id} missing description"
            assert step.instructions, f"Step {step.id} missing instructions"


class TestOnboardingProgress:
    """Test OnboardingProgress model."""

    def test_default_values(self) -> None:
        """Test default values."""
        progress = OnboardingProgress()
        assert progress.status == OnboardingStatus.NOT_STARTED
        assert progress.current_step == 0
        assert progress.completed_steps == []
        assert progress.started_at is None
        assert progress.completed_at is None

    def test_start(self) -> None:
        """Test starting onboarding."""
        progress = OnboardingProgress()
        progress.start()

        assert progress.status == OnboardingStatus.IN_PROGRESS
        assert progress.started_at is not None

    def test_start_twice(self) -> None:
        """Test starting twice doesn't reset."""
        progress = OnboardingProgress()
        progress.start()
        first_start = progress.started_at

        progress.start()  # Second call
        assert progress.started_at == first_start  # Should not change

    def test_advance(self) -> None:
        """Test advancing steps."""
        progress = OnboardingProgress()
        progress.start()

        assert progress.current_step == 0
        result = progress.advance()
        assert result is True
        assert progress.current_step == 1
        assert "welcome" in progress.completed_steps

    def test_advance_to_completion(self) -> None:
        """Test advancing to completion."""
        progress = OnboardingProgress()
        progress.start()

        # Advance through all steps
        for _ in range(5):
            result = progress.advance()
            assert result is True

        # Last advance should complete
        result = progress.advance()
        assert result is False
        assert progress.status == OnboardingStatus.COMPLETED
        assert progress.completed_at is not None

    def test_skip(self) -> None:
        """Test skipping onboarding."""
        progress = OnboardingProgress()
        progress.start()
        progress.advance()

        progress.skip()

        assert progress.status == OnboardingStatus.SKIPPED
        assert progress.skipped_at is not None
        assert progress.skipped_from_step == 1

    def test_go_to_step(self) -> None:
        """Test going to specific step."""
        progress = OnboardingProgress()
        progress.start()

        result = progress.go_to_step(3)
        assert result is True
        assert progress.current_step == 3

    def test_go_to_invalid_step(self) -> None:
        """Test going to invalid step."""
        progress = OnboardingProgress()
        progress.start()

        result = progress.go_to_step(100)
        assert result is False

    def test_get_completion_percentage(self) -> None:
        """Test completion percentage."""
        progress = OnboardingProgress()
        assert progress.get_completion_percentage() == 0.0

        progress.start()
        progress.advance()  # 1 step done
        assert 0 < progress.get_completion_percentage() < 100

        progress.status = OnboardingStatus.COMPLETED
        assert progress.get_completion_percentage() == 100.0


class TestOnboardingManager:
    """Test OnboardingManager."""

    @pytest.fixture
    def manager(self) -> OnboardingManager:
        """Create fresh manager."""
        return OnboardingManager()

    def test_initial_state(self, manager: OnboardingManager) -> None:
        """Test initial state."""
        assert manager.should_show_onboarding() is True
        assert manager.is_completed() is False
        assert manager.is_skipped() is False

    def test_start(self, manager: OnboardingManager) -> None:
        """Test starting onboarding."""
        step = manager.start()

        assert step is not None
        assert step.id == OnboardingStep.WELCOME
        assert manager.progress.status == OnboardingStatus.IN_PROGRESS

    def test_advance(self, manager: OnboardingManager) -> None:
        """Test advancing steps."""
        manager.start()

        step = manager.advance()
        assert step is not None
        assert step.id == OnboardingStep.CREATE_FIRST_TASK

    def test_skip(self, manager: OnboardingManager) -> None:
        """Test skipping onboarding."""
        manager.start()
        manager.skip()

        assert manager.is_skipped() is True
        assert manager.should_show_onboarding() is False

    def test_reset(self, manager: OnboardingManager) -> None:
        """Test resetting onboarding."""
        manager.start()
        manager.skip()
        manager.reset()

        assert manager.should_show_onboarding() is True
        assert manager.progress.status == OnboardingStatus.NOT_STARTED

    def test_get_step(self, manager: OnboardingManager) -> None:
        """Test getting specific step."""
        step = manager.get_step(OnboardingStep.CREATE_FIRST_TASK)
        assert step is not None
        assert step.id == OnboardingStep.CREATE_FIRST_TASK

    def test_current_step(self, manager: OnboardingManager) -> None:
        """Test getting current step."""
        manager.start()
        step = manager.current_step
        assert step is not None
        assert step.id == OnboardingStep.WELCOME

    def test_current_step_when_completed(self, manager: OnboardingManager) -> None:
        """Test current step is None when completed."""
        manager.start()
        manager.skip()
        assert manager.current_step is None


class TestFormatting:
    """Test formatting functions."""

    def test_format_step_output(self) -> None:
        """Test step output formatting."""
        step = TutorialStep(
            id=OnboardingStep.WELCOME,
            title="Welcome",
            description="Welcome message",
            instructions=["Step 1", "Step 2"],
            tips=["Tip 1"],
        )

        output = format_step_output(step, 1, 6)

        assert "Step 1/6" in output
        assert "Welcome" in output
        assert "Welcome message" in output
        assert "Step 1" in output
        assert "Tip 1" in output

    def test_format_welcome_message(self) -> None:
        """Test welcome message formatting."""
        message = format_welcome_message()

        assert "Welcome to Mahavishnu" in message
        assert "[Y]es" in message
        assert "[S]kip" in message


class TestSingleton:
    """Test singleton pattern."""

    def test_get_onboarding_manager_singleton(self) -> None:
        """Test singleton returns same instance."""
        manager1 = get_onboarding_manager()
        manager2 = get_onboarding_manager()
        assert manager1 is manager2
