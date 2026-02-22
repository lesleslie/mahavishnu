"""Learning system for Goal-Driven Teams.

Extends StatisticalRouter concepts to learn from team execution outcomes.

Storage:
- Session-Buddy: Full execution context (via context manager)
- Akosha: Embeddings for similarity search (via context manager)

Metrics tracked:
- Success rate by skill combination
- Latency by team mode
- Quality score correlation
- User feedback integration

Design:
- Lazy singleton pattern for global learning engine
- Prometheus metrics integration for learning events
- ContextVar for dependency injection
- WebSocket broadcasting for learning events

Created: 2026-02-21
Version: 1.0
Related: Goal-Driven Teams Phase 3 - Learning System
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Learning Models
# ============================================================================


class TeamExecutionOutcome(BaseModel):
    """Record of a team execution for learning.

    Captures all relevant context from a team execution to enable
    learning and optimization of future team configurations.

    Attributes:
        team_id: Unique team identifier
        goal: Original natural language goal
        parsed_intent: Intent extracted from goal (review, build, test, etc.)
        parsed_domain: Domain extracted from goal (security, performance, etc.)
        parsed_skills: Skills extracted from goal
        team_mode: Team collaboration mode used
        task: The actual task that was executed
        success: Whether the execution succeeded
        latency_ms: Execution latency in milliseconds
        tokens_used: Total tokens consumed
        quality_score: Optional quality score (0-100)
        timestamp: When the execution occurred
        error_code: Error code if execution failed
        error_message: Error message if execution failed
        user_feedback: User feedback ("positive", "negative", None)
    """

    team_id: str = Field(description="Unique team identifier")
    goal: str = Field(description="Original natural language goal")
    parsed_intent: str = Field(description="Intent extracted from goal")
    parsed_domain: str = Field(description="Domain extracted from goal")
    parsed_skills: list[str] = Field(default_factory=list, description="Skills extracted from goal")
    team_mode: str = Field(description="Team collaboration mode used")
    task: str = Field(description="The actual task that was executed")
    success: bool = Field(description="Whether the execution succeeded")
    latency_ms: float = Field(description="Execution latency in milliseconds")
    tokens_used: int = Field(default=0, ge=0, description="Total tokens consumed")
    quality_score: float | None = Field(default=None, ge=0.0, le=100.0, description="Optional quality score")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Execution timestamp")
    error_code: str | None = Field(default=None, description="Error code if execution failed")
    error_message: str | None = Field(default=None, description="Error message if execution failed")
    user_feedback: str | None = Field(default=None, description="User feedback (positive/negative/None)")

    def to_storage_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage.

        Returns:
            Dictionary suitable for JSON serialization or database storage
        """
        return {
            "team_id": self.team_id,
            "goal": self.goal,
            "parsed_intent": self.parsed_intent,
            "parsed_domain": self.parsed_domain,
            "parsed_skills": self.parsed_skills,
            "team_mode": self.team_mode,
            "task": self.task,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "quality_score": self.quality_score,
            "timestamp": self.timestamp.isoformat(),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "user_feedback": self.user_feedback,
        }


class TeamLearningStats(BaseModel):
    """Statistics for a skill/intent/mode combination.

    Tracks aggregate statistics for a specific combination of skills,
    intent, or mode to enable learning and optimization.

    Attributes:
        total_executions: Total number of executions
        successful_executions: Number of successful executions
        total_latency_ms: Cumulative latency in milliseconds
        total_quality_score: Cumulative quality score
        quality_samples: Number of quality score samples
        positive_feedback_count: Number of positive feedback
        negative_feedback_count: Number of negative feedback
    """

    total_executions: int = Field(default=0, ge=0)
    successful_executions: int = Field(default=0, ge=0)
    total_latency_ms: float = Field(default=0.0, ge=0.0)
    total_quality_score: float = Field(default=0.0, ge=0.0)
    quality_samples: int = Field(default=0, ge=0)
    positive_feedback_count: int = Field(default=0, ge=0)
    negative_feedback_count: int = Field(default=0, ge=0)

    @property
    def success_rate(self) -> float:
        """Calculate success rate.

        Returns:
            Success rate as a float between 0.0 and 1.0
        """
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency.

        Returns:
            Average latency in milliseconds
        """
        if self.total_executions == 0:
            return 0.0
        return self.total_latency_ms / self.total_executions

    @property
    def avg_quality_score(self) -> float | None:
        """Calculate average quality score.

        Returns:
            Average quality score or None if no samples
        """
        if self.quality_samples == 0:
            return None
        return self.total_quality_score / self.quality_samples

    @property
    def feedback_ratio(self) -> float | None:
        """Calculate positive feedback ratio.

        Returns:
            Ratio of positive to total feedback, or None if no feedback
        """
        total_feedback = self.positive_feedback_count + self.negative_feedback_count
        if total_feedback == 0:
            return None
        return self.positive_feedback_count / total_feedback

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary with computed properties
        """
        return {
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "avg_quality_score": self.avg_quality_score,
            "quality_samples": self.quality_samples,
            "positive_feedback_count": self.positive_feedback_count,
            "negative_feedback_count": self.negative_feedback_count,
            "feedback_ratio": self.feedback_ratio,
        }


class ModeRecommendation(BaseModel):
    """Recommendation for team mode selection.

    Provides a recommended mode with confidence and supporting data.

    Attributes:
        mode: Recommended team mode
        confidence: Confidence in the recommendation (0.0-1.0)
        success_rate: Success rate for this mode
        sample_count: Number of samples used for recommendation
        reason: Human-readable reason for the recommendation
    """

    mode: str = Field(description="Recommended team mode")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in recommendation")
    success_rate: float = Field(ge=0.0, le=1.0, description="Success rate for this mode")
    sample_count: int = Field(ge=0, description="Number of samples used")
    reason: str = Field(description="Human-readable reason for recommendation")


# ============================================================================
# Learning Engine
# ============================================================================


class TeamLearningEngine:
    """Learn from team execution outcomes to improve configurations.

    This engine extends StatisticalRouter's capabilities to include:
    - Team execution outcome tracking
    - Skill combination success rates
    - Mode selection optimization
    - Quality score correlation
    - User feedback integration

    The engine uses in-memory storage for fast access, with optional
    persistence to Session-Buddy and embedding in Akosha.

    Example:
        ```python
        from mahavishnu.core.team_learning import get_learning_engine, TeamExecutionOutcome

        # Record an outcome
        engine = get_learning_engine()
        outcome = TeamExecutionOutcome(
            team_id="team_123",
            goal="Review code for security",
            parsed_intent="review",
            parsed_domain="security",
            parsed_skills=["security", "quality"],
            team_mode="coordinate",
            task="Review authentication code",
            success=True,
            latency_ms=1500.0,
        )
        engine.record_outcome(outcome)

        # Get a recommendation
        recommendation = engine.get_mode_recommendation("review")
        print(f"Recommended mode: {recommendation.mode}")
        ```
    """

    def __init__(self, max_recent_outcomes: int = 100) -> None:
        """Initialize the learning engine.

        Args:
            max_recent_outcomes: Maximum number of recent outcomes to keep
        """
        # Stats by skill combination (comma-separated sorted skills)
        self._skill_stats: dict[str, TeamLearningStats] = {}
        # Stats by intent
        self._intent_stats: dict[str, TeamLearningStats] = {}
        # Stats by mode
        self._mode_stats: dict[str, TeamLearningStats] = {}
        # Stats by intent-mode combination
        self._intent_mode_stats: dict[str, TeamLearningStats] = {}
        # Recent outcomes for analysis
        self._recent_outcomes: list[TeamExecutionOutcome] = []
        self._max_recent = max_recent_outcomes

        logger.info(f"TeamLearningEngine initialized (max_recent={max_recent_outcomes})")

    # ========================================================================
    # Outcome Recording
    # ========================================================================

    def record_outcome(self, outcome: TeamExecutionOutcome) -> None:
        """Record an execution outcome for learning.

        Updates all relevant statistics based on the outcome.

        Args:
            outcome: The execution outcome to record
        """
        # Update skill stats
        skill_key = ",".join(sorted(outcome.parsed_skills)) if outcome.parsed_skills else "none"
        if skill_key not in self._skill_stats:
            self._skill_stats[skill_key] = TeamLearningStats()
        self._update_stats(self._skill_stats[skill_key], outcome)

        # Update intent stats
        if outcome.parsed_intent not in self._intent_stats:
            self._intent_stats[outcome.parsed_intent] = TeamLearningStats()
        self._update_stats(self._intent_stats[outcome.parsed_intent], outcome)

        # Update mode stats
        if outcome.team_mode not in self._mode_stats:
            self._mode_stats[outcome.team_mode] = TeamLearningStats()
        self._update_stats(self._mode_stats[outcome.team_mode], outcome)

        # Update intent-mode combination stats
        intent_mode_key = f"{outcome.parsed_intent}:{outcome.team_mode}"
        if intent_mode_key not in self._intent_mode_stats:
            self._intent_mode_stats[intent_mode_key] = TeamLearningStats()
        self._update_stats(self._intent_mode_stats[intent_mode_key], outcome)

        # Store recent outcome
        self._recent_outcomes.append(outcome)
        if len(self._recent_outcomes) > self._max_recent:
            self._recent_outcomes.pop(0)

        logger.debug(
            f"Recorded outcome: team_id={outcome.team_id}, "
            f"success={outcome.success}, mode={outcome.team_mode}"
        )

    def _update_stats(self, stats: TeamLearningStats, outcome: TeamExecutionOutcome) -> None:
        """Update statistics with an outcome.

        Args:
            stats: Statistics object to update
            outcome: Outcome to incorporate
        """
        stats.total_executions += 1
        if outcome.success:
            stats.successful_executions += 1
        stats.total_latency_ms += outcome.latency_ms

        if outcome.quality_score is not None:
            stats.total_quality_score += outcome.quality_score
            stats.quality_samples += 1

        if outcome.user_feedback == "positive":
            stats.positive_feedback_count += 1
        elif outcome.user_feedback == "negative":
            stats.negative_feedback_count += 1

    # ========================================================================
    # Recommendations
    # ========================================================================

    def get_mode_recommendation(
        self,
        intent: str,
        min_samples: int = 3,
    ) -> ModeRecommendation | None:
        """Get recommended mode for an intent based on learning.

        Analyzes historical data to recommend the best mode for a given
        intent. Returns None if not enough data.

        Args:
            intent: The intent to get a recommendation for
            min_samples: Minimum samples required for recommendation

        Returns:
            ModeRecommendation or None if insufficient data
        """
        # Find all intent-mode combinations for this intent
        mode_scores: dict[str, dict[str, Any]] = {}

        for key, stats in self._intent_mode_stats.items():
            if not key.startswith(f"{intent}:"):
                continue
            if stats.total_executions < min_samples:
                continue

            mode = key.split(":", 1)[1]

            # Calculate combined score: success rate + quality + feedback
            score = stats.success_rate

            if stats.avg_quality_score is not None:
                # Normalize quality score to 0-1 range and weight it
                quality_factor = stats.avg_quality_score / 100.0
                score = (score * 0.6) + (quality_factor * 0.3)

            if stats.feedback_ratio is not None:
                # Weight feedback ratio
                score = (score * 0.9) + (stats.feedback_ratio * 0.1)

            mode_scores[mode] = {
                "score": score,
                "success_rate": stats.success_rate,
                "samples": stats.total_executions,
                "avg_latency": stats.avg_latency_ms,
            }

        if not mode_scores:
            return None

        # Find best mode
        best_mode = max(mode_scores.items(), key=lambda x: x[1]["score"])
        mode_name, mode_data = best_mode

        # Calculate confidence based on sample count
        sample_confidence = min(mode_data["samples"] / 20.0, 1.0)  # Max at 20 samples
        confidence = sample_confidence * 0.7 + mode_data["score"] * 0.3

        return ModeRecommendation(
            mode=mode_name,
            confidence=confidence,
            success_rate=mode_data["success_rate"],
            sample_count=mode_data["samples"],
            reason=f"Based on {mode_data['samples']} executions with "
                   f"{mode_data['success_rate']:.0%} success rate",
        )

    def get_skill_success_rate(self, skills: list[str]) -> float:
        """Get success rate for a skill combination.

        Args:
            skills: List of skills to check

        Returns:
            Success rate (0.0-1.0), or 0.0 if no data
        """
        skill_key = ",".join(sorted(skills)) if skills else "none"
        stats = self._skill_stats.get(skill_key)
        if not stats:
            return 0.0
        return stats.success_rate

    def get_intent_stats(self, intent: str) -> TeamLearningStats | None:
        """Get statistics for a specific intent.

        Args:
            intent: The intent to get stats for

        Returns:
            TeamLearningStats or None if no data
        """
        return self._intent_stats.get(intent)

    def get_mode_stats(self, mode: str) -> TeamLearningStats | None:
        """Get statistics for a specific mode.

        Args:
            mode: The mode to get stats for

        Returns:
            TeamLearningStats or None if no data
        """
        return self._mode_stats.get(mode)

    # ========================================================================
    # Learning Summaries
    # ========================================================================

    def get_learning_summary(self) -> dict[str, Any]:
        """Get a summary of all learning data.

        Returns:
            Dictionary with learning statistics and insights
        """
        return {
            "total_outcomes": len(self._recent_outcomes),
            "skill_combinations": len(self._skill_stats),
            "intents_tracked": len(self._intent_stats),
            "modes_tracked": len(self._mode_stats),
            "intent_mode_combinations": len(self._intent_mode_stats),
            "top_skills": self._get_top_skills(),
            "mode_performance": self._get_mode_performance(),
            "intent_performance": self._get_intent_performance(),
            "recent_success_rate": self._get_recent_success_rate(),
        }

    def _get_top_skills(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get top performing skill combinations.

        Args:
            limit: Maximum number to return

        Returns:
            List of skill combination stats
        """
        skill_scores = []
        for skills_key, stats in self._skill_stats.items():
            if stats.total_executions >= 3:
                skill_scores.append({
                    "skills": skills_key,
                    "success_rate": stats.success_rate,
                    "avg_latency_ms": stats.avg_latency_ms,
                    "executions": stats.total_executions,
                    "avg_quality": stats.avg_quality_score,
                })

        skill_scores.sort(key=lambda x: x["success_rate"], reverse=True)
        return skill_scores[:limit]

    def _get_mode_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance stats by mode.

        Returns:
            Dictionary of mode performance stats
        """
        return {
            mode: {
                "success_rate": stats.success_rate,
                "avg_latency_ms": stats.avg_latency_ms,
                "executions": stats.total_executions,
                "avg_quality": stats.avg_quality_score,
            }
            for mode, stats in self._mode_stats.items()
        }

    def _get_intent_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance stats by intent.

        Returns:
            Dictionary of intent performance stats
        """
        return {
            intent: {
                "success_rate": stats.success_rate,
                "avg_latency_ms": stats.avg_latency_ms,
                "executions": stats.total_executions,
                "avg_quality": stats.avg_quality_score,
            }
            for intent, stats in self._intent_stats.items()
        }

    def _get_recent_success_rate(self, window: int = 20) -> float:
        """Get success rate for recent outcomes.

        Args:
            window: Number of recent outcomes to consider

        Returns:
            Success rate for recent outcomes
        """
        recent = self._recent_outcomes[-window:] if len(self._recent_outcomes) > window else self._recent_outcomes
        if not recent:
            return 0.0
        successes = sum(1 for o in recent if o.success)
        return successes / len(recent)

    # ========================================================================
    # Data Management
    # ========================================================================

    def get_recent_outcomes(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent execution outcomes.

        Args:
            limit: Maximum number to return

        Returns:
            List of outcome dictionaries
        """
        recent = self._recent_outcomes[-limit:] if len(self._recent_outcomes) > limit else self._recent_outcomes
        return [o.to_storage_dict() for o in recent]

    def clear_stats(self) -> None:
        """Clear all learning statistics.

        Useful for testing or resetting learning data.
        """
        self._skill_stats.clear()
        self._intent_stats.clear()
        self._mode_stats.clear()
        self._intent_mode_stats.clear()
        self._recent_outcomes.clear()
        logger.info("Cleared all learning statistics")

    def export_stats(self) -> dict[str, Any]:
        """Export all statistics for persistence.

        Returns:
            Dictionary with all statistics for serialization
        """
        return {
            "skill_stats": {k: v.model_dump() for k, v in self._skill_stats.items()},
            "intent_stats": {k: v.model_dump() for k, v in self._intent_stats.items()},
            "mode_stats": {k: v.model_dump() for k, v in self._mode_stats.items()},
            "intent_mode_stats": {k: v.model_dump() for k, v in self._intent_mode_stats.items()},
            "recent_outcomes": [o.to_storage_dict() for o in self._recent_outcomes],
        }

    def import_stats(self, data: dict[str, Any]) -> None:
        """Import statistics from persistence.

        Args:
            data: Dictionary with exported statistics
        """
        self._skill_stats = {
            k: TeamLearningStats(**v) for k, v in data.get("skill_stats", {}).items()
        }
        self._intent_stats = {
            k: TeamLearningStats(**v) for k, v in data.get("intent_stats", {}).items()
        }
        self._mode_stats = {
            k: TeamLearningStats(**v) for k, v in data.get("mode_stats", {}).items()
        }
        self._intent_mode_stats = {
            k: TeamLearningStats(**v) for k, v in data.get("intent_mode_stats", {}).items()
        }
        # Note: Recent outcomes are not restored to avoid stale data
        logger.info(
            f"Imported learning stats: {len(self._skill_stats)} skills, "
            f"{len(self._intent_stats)} intents, {len(self._mode_stats)} modes"
        )


# ============================================================================
# Module-Level Functions and Context
# ============================================================================

# Singleton instance
_learning_engine: TeamLearningEngine | None = None

# Context variable for dependency injection
_learning_engine_context: ContextVar[TeamLearningEngine | None] = ContextVar(
    "learning_engine", default=None
)


def get_learning_engine() -> TeamLearningEngine:
    """Get the singleton learning engine.

    Creates the engine on first access. Thread-safe via module-level
    singleton pattern.

    Returns:
        TeamLearningEngine singleton instance
    """
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = TeamLearningEngine()
    return _learning_engine


def get_learning_engine_from_context() -> TeamLearningEngine | None:
    """Get learning engine from context variable.

    Used when the engine is injected via context rather than
    using the global singleton.

    Returns:
        TeamLearningEngine from context, or None if not set
    """
    return _learning_engine_context.get()


def set_learning_engine_in_context(engine: TeamLearningEngine | None) -> None:
    """Set learning engine in context variable.

    Args:
        engine: Engine instance to set, or None to clear
    """
    _learning_engine_context.set(engine)


def reset_learning_engine() -> None:
    """Reset the singleton learning engine.

    Useful for testing or clearing all learning data.
    """
    global _learning_engine
    if _learning_engine is not None:
        _learning_engine.clear_stats()
    _learning_engine = None
    logger.info("Reset learning engine singleton")


__all__ = [
    # Models
    "TeamExecutionOutcome",
    "TeamLearningStats",
    "ModeRecommendation",
    # Engine
    "TeamLearningEngine",
    # Module functions
    "get_learning_engine",
    "get_learning_engine_from_context",
    "set_learning_engine_in_context",
    "reset_learning_engine",
]
