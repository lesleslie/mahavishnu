"""Predictions Module for Mahavishnu.

Provides predictive insights including:
- Blocker prediction based on historical patterns
- Task duration estimation
- Confidence intervals for predictions
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from mahavishnu.models.pattern import (
    BlockerPattern,
    TaskDurationPattern,
)

logger = logging.getLogger(__name__)


class BlockerPrediction(BaseModel):
    """Prediction for potential blockers."""

    task_id: str
    blocker_probability: float = Field(ge=0.0, le=1.0)
    confidence_interval: tuple[float, float] = Field(default=(0.0, 1.0))
    potential_blockers: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    mitigation_suggestions: list[str] = Field(default_factory=list)
    predicted_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "blocker_probability": self.blocker_probability,
            "confidence_interval": list(self.confidence_interval),
            "potential_blockers": self.potential_blockers,
            "risk_factors": self.risk_factors,
            "mitigation_suggestions": self.mitigation_suggestions,
            "predicted_at": self.predicted_at.isoformat(),
        }


class DurationPrediction(BaseModel):
    """Prediction for task duration."""

    task_id: str
    estimated_hours: float = Field(ge=0.0)
    confidence_interval: tuple[float, float] = Field(default=(0.0, float("inf")))
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    based_on_tasks: int = Field(default=0, ge=0)
    factors: dict[str, Any] = Field(default_factory=dict)
    predicted_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "estimated_hours": self.estimated_hours,
            "confidence_interval": list(self.confidence_interval),
            "confidence": self.confidence,
            "based_on_tasks": self.based_on_tasks,
            "factors": self.factors,
            "predicted_at": self.predicted_at.isoformat(),
        }


class PredictionConfig(BaseModel):
    """Configuration for predictions."""

    # Minimum samples for reliable prediction
    min_samples: int = Field(default=5, ge=1)

    # Confidence level for intervals (0.95 = 95%)
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.99)

    # Risk factor weights
    repository_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    tag_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    priority_weight: float = Field(default=0.2, ge=0.0, le=1.0)
    assignee_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.1, ge=0.0, le=1.0)


class BlockerPredictor:
    """Predicts potential blockers for tasks."""

    # Risk indicator keywords
    RISK_KEYWORDS: dict[str, float] = {
        "integration": 0.3,
        "external": 0.25,
        "api": 0.2,
        "third-party": 0.25,
        "migration": 0.2,
        "refactor": 0.15,
        "complex": 0.2,
        "urgent": 0.15,
        "critical": 0.2,
        "asap": 0.1,
    }

    def __init__(self, config: PredictionConfig | None = None):
        """Initialize blocker predictor.

        Args:
            config: Optional prediction configuration
        """
        self.config = config or PredictionConfig()

    def predict_blockers(
        self,
        task: dict[str, Any],
        blocker_patterns: list[BlockerPattern],
        historical_tasks: list[dict[str, Any]],
    ) -> BlockerPrediction:
        """Predict potential blockers for a task.

        Args:
            task: Task to predict blockers for
            blocker_patterns: Known blocker patterns
            historical_tasks: Historical task data

        Returns:
            BlockerPrediction with probability and suggestions
        """
        # Calculate base probability from patterns
        base_probability = self._calculate_pattern_probability(task, blocker_patterns)

        # Adjust based on risk factors
        risk_score, risk_factors = self._assess_risk_factors(task)

        # Combine probabilities
        blocker_probability = min(1.0, base_probability + risk_score * 0.3)

        # Calculate confidence interval
        sample_size = len([t for t in historical_tasks if t.get("repository") == task.get("repository")])
        confidence_interval = self._calculate_confidence_interval(
            blocker_probability, sample_size
        )

        # Identify potential blockers
        potential_blockers = self._identify_potential_blockers(
            task, blocker_patterns
        )

        # Generate mitigation suggestions
        mitigation_suggestions = self._generate_mitigation_suggestions(
            potential_blockers, risk_factors
        )

        return BlockerPrediction(
            task_id=task.get("id", "unknown"),
            blocker_probability=blocker_probability,
            confidence_interval=confidence_interval,
            potential_blockers=potential_blockers,
            risk_factors=risk_factors,
            mitigation_suggestions=mitigation_suggestions,
        )

    def _calculate_pattern_probability(
        self, task: dict[str, Any], patterns: list[BlockerPattern]
    ) -> float:
        """Calculate blocker probability from patterns."""
        if not patterns:
            return 0.0

        text = f"{task.get('title', '')} {task.get('description', '')}".lower()
        total_prob = 0.0

        for pattern in patterns:
            # Check if task matches pattern
            match_score = 0.0

            # Keyword match
            if pattern.blocker_keyword in text:
                match_score += 0.4

            # Repository match
            if task.get("repository") in pattern.affected_repositories:
                match_score += 0.3

            # Tag match
            task_tags = set(task.get("tags", []))
            pattern_tags = set()  # Would be populated from pattern metadata
            if task_tags & pattern_tags:
                match_score += 0.2

            # Weight by pattern confidence
            total_prob += match_score * pattern.confidence

        return min(1.0, total_prob)

    def _assess_risk_factors(
        self, task: dict[str, Any]
    ) -> tuple[float, list[str]]:
        """Assess risk factors in a task.

        Returns:
            Tuple of (risk_score, risk_factors)
        """
        text = f"{task.get('title', '')} {task.get('description', '')}".lower()
        risk_score = 0.0
        risk_factors: list[str] = []

        # Check for risk keywords
        for keyword, weight in self.RISK_KEYWORDS.items():
            if keyword in text:
                risk_score += weight
                risk_factors.append(f"Contains '{keyword}' keyword")

        # Check priority
        priority = task.get("priority", "").lower()
        if priority in ("critical", "urgent"):
            risk_score += 0.15
            risk_factors.append(f"High priority: {priority}")

        # Check for dependencies mentioned
        if "depend" in text or "block" in text:
            risk_score += 0.2
            risk_factors.append("Mentions dependencies or blocking")

        return min(1.0, risk_score), risk_factors

    def _calculate_confidence_interval(
        self, probability: float, sample_size: int
    ) -> tuple[float, float]:
        """Calculate confidence interval using Wilson score.

        Args:
            probability: Point estimate probability
            sample_size: Number of samples

        Returns:
            Tuple of (lower_bound, upper_bound)
        """
        if sample_size < self.config.min_samples:
            # Wide interval for small samples
            return (max(0.0, probability - 0.3), min(1.0, probability + 0.3))

        # Wilson score interval
        z = 1.96  # 95% confidence
        n = sample_size
        p = probability

        denominator = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denominator

        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)

        return (lower, upper)

    def _identify_potential_blockers(
        self, task: dict[str, Any], patterns: list[BlockerPattern]
    ) -> list[str]:
        """Identify specific potential blockers."""
        potential: list[str] = []
        text = f"{task.get('title', '')} {task.get('description', '')}".lower()

        for pattern in patterns:
            if pattern.blocker_keyword in text:
                potential.append(pattern.blocker_keyword)
            elif task.get("repository") in pattern.affected_repositories:
                if pattern.severity.value in ("high", "critical"):
                    potential.append(f"{pattern.blocker_keyword} (repo pattern)")

        return list(set(potential))[:5]  # Top 5 unique

    def _generate_mitigation_suggestions(
        self, potential_blockers: list[str], risk_factors: list[str]
    ) -> list[str]:
        """Generate suggestions to mitigate predicted blockers."""
        suggestions: list[str] = []

        for blocker in potential_blockers:
            if "dependency" in blocker:
                suggestions.extend([
                    "Identify and document all dependencies upfront",
                    "Create dependency tracking in task comments",
                    "Schedule dependency resolution meetings early",
                ])
            elif "external" in blocker or "api" in blocker:
                suggestions.extend([
                    "Implement fallback/error handling for external calls",
                    "Add circuit breakers for API dependencies",
                    "Document external service SLAs",
                ])
            elif "integration" in blocker:
                suggestions.extend([
                    "Plan integration testing early",
                    "Set up integration environment",
                    "Coordinate with integration teams in advance",
                ])

        # Add general suggestions for risk factors
        if any("high priority" in rf.lower() for rf in risk_factors):
            suggestions.append("Consider breaking into smaller subtasks")

        if not suggestions:
            suggestions.append("Monitor task progress closely")

        return list(set(suggestions))[:5]  # Top 5 unique


class DurationEstimator:
    """Estimates task duration based on historical data."""

    def __init__(self, config: PredictionConfig | None = None):
        """Initialize duration estimator.

        Args:
            config: Optional prediction configuration
        """
        self.config = config or PredictionConfig()

    def estimate_duration(
        self,
        task: dict[str, Any],
        duration_patterns: list[TaskDurationPattern],
        historical_tasks: list[dict[str, Any]],
    ) -> DurationPrediction:
        """Estimate task duration.

        Args:
            task: Task to estimate
            duration_patterns: Known duration patterns
            historical_tasks: Historical task data

        Returns:
            DurationPrediction with estimate and confidence
        """
        # Find matching patterns
        matching_durations: list[tuple[float, float]] = []  # (duration, weight)

        for pattern in duration_patterns:
            weight = self._calculate_pattern_match(task, pattern)
            if weight > 0:
                matching_durations.append((pattern.avg_duration, weight))

        # Also check direct historical matches
        historical_durations = self._get_historical_durations(
            task, historical_tasks
        )

        # Combine estimates
        if matching_durations or historical_durations:
            estimated_hours, confidence = self._combine_estimates(
                matching_durations, historical_durations
            )
        else:
            # Default estimate
            estimated_hours = 8.0  # 1 day default
            confidence = 0.3

        # Calculate confidence interval
        all_durations = [d for d, _ in matching_durations] + historical_durations
        confidence_interval = self._calculate_duration_interval(
            estimated_hours, all_durations
        )

        # Identify factors affecting estimate
        factors = self._identify_factors(task, duration_patterns)

        return DurationPrediction(
            task_id=task.get("id", "unknown"),
            estimated_hours=round(estimated_hours, 1),
            confidence_interval=(
                round(confidence_interval[0], 1),
                round(confidence_interval[1], 1),
            ),
            confidence=round(confidence, 2),
            based_on_tasks=len(all_durations),
            factors=factors,
        )

    def _calculate_pattern_match(
        self, task: dict[str, Any], pattern: TaskDurationPattern
    ) -> float:
        """Calculate how well a task matches a duration pattern."""
        weight = 0.0

        # Repository match (most important)
        if pattern.repository and task.get("repository") == pattern.repository:
            weight += self.config.repository_weight

        # Task type/tag match
        if pattern.task_type and pattern.task_type in task.get("tags", []):
            weight += self.config.tag_weight

        # Priority match
        task_priority = task.get("priority", "").lower()
        if pattern.priority_range:
            if task_priority in pattern.priority_range:
                weight += self.config.priority_weight

        return weight

    def _get_historical_durations(
        self, task: dict[str, Any], historical_tasks: list[dict[str, Any]]
    ) -> list[float]:
        """Get durations from similar historical tasks."""
        durations: list[float] = []

        for hist_task in historical_tasks:
            # Check similarity
            similarity = 0.0

            if hist_task.get("repository") == task.get("repository"):
                similarity += 0.4

            task_tags = set(task.get("tags", []))
            hist_tags = set(hist_task.get("tags", []))
            if task_tags & hist_tags:
                similarity += 0.3

            if hist_task.get("priority") == task.get("priority"):
                similarity += 0.2

            # Get duration if similar and completed
            if similarity >= 0.5 and hist_task.get("status") == "completed":
                duration = self._calculate_task_duration(hist_task)
                if duration:
                    durations.append(duration)

        return durations

    def _calculate_task_duration(self, task: dict[str, Any]) -> float | None:
        """Calculate duration of a completed task in hours."""
        created = task.get("created_at")
        completed = task.get("completed_at")

        if created and completed:
            try:
                created_dt = datetime.fromisoformat(created) if isinstance(created, str) else created
                completed_dt = datetime.fromisoformat(completed) if isinstance(completed, str) else completed
                return (completed_dt - created_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                pass
        return None

    def _combine_estimates(
        self,
        weighted_durations: list[tuple[float, float]],
        historical_durations: list[float],
    ) -> tuple[float, float]:
        """Combine estimates from patterns and history.

        Returns:
            Tuple of (estimated_hours, confidence)
        """
        all_estimates: list[tuple[float, float]] = []

        # Add weighted pattern estimates
        for duration, weight in weighted_durations:
            all_estimates.append((duration, weight))

        # Add historical estimates with equal weight
        for duration in historical_durations:
            all_estimates.append((duration, 0.5))

        if not all_estimates:
            return (8.0, 0.3)

        # Weighted average
        total_weight = sum(w for _, w in all_estimates)
        weighted_sum = sum(d * w for d, w in all_estimates)
        estimated_hours = weighted_sum / total_weight if total_weight > 0 else 8.0

        # Confidence based on sample size and consistency
        sample_size = len(all_estimates)
        durations = [d for d, _ in all_estimates]

        if len(durations) > 1:
            variance = sum((d - estimated_hours) ** 2 for d in durations) / len(durations)
            std_dev = math.sqrt(variance)
            coefficient_of_variation = std_dev / estimated_hours if estimated_hours > 0 else 1.0

            # Higher consistency = higher confidence
            consistency_score = max(0.0, 1.0 - coefficient_of_variation)
            sample_score = min(1.0, sample_size / 10)

            confidence = (consistency_score * 0.6 + sample_score * 0.4)
        else:
            confidence = 0.4

        return (estimated_hours, confidence)

    def _calculate_duration_interval(
        self, estimate: float, durations: list[float]
    ) -> tuple[float, float]:
        """Calculate confidence interval for duration estimate."""
        if len(durations) < self.config.min_samples:
            # Wide interval for small samples
            return (max(0.0, estimate * 0.5), estimate * 2.0)

        # Calculate standard deviation
        avg = sum(durations) / len(durations)
        variance = sum((d - avg) ** 2 for d in durations) / len(durations)
        std_dev = math.sqrt(variance)

        # 95% confidence interval
        margin = 1.96 * std_dev

        return (max(0.0, estimate - margin), estimate + margin)

    def _identify_factors(
        self, task: dict[str, Any], patterns: list[TaskDurationPattern]
    ) -> dict[str, Any]:
        """Identify factors affecting the duration estimate."""
        factors: dict[str, Any] = {
            "repository": task.get("repository"),
            "tags": task.get("tags", []),
            "priority": task.get("priority"),
        }

        # Add pattern matches
        matched_patterns = []
        for pattern in patterns:
            if self._calculate_pattern_match(task, pattern) > 0:
                matched_patterns.append({
                    "repository": pattern.repository,
                    "avg_duration": pattern.avg_duration,
                    "sample_count": pattern.sample_count,
                })

        if matched_patterns:
            factors["matched_patterns"] = matched_patterns[:3]

        return factors


def predict_blockers(
    task: dict[str, Any],
    blocker_patterns: list[BlockerPattern],
    historical_tasks: list[dict[str, Any]],
) -> BlockerPrediction:
    """Convenience function to predict blockers.

    Args:
        task: Task to analyze
        blocker_patterns: Known blocker patterns
        historical_tasks: Historical task data

    Returns:
        BlockerPrediction
    """
    predictor = BlockerPredictor()
    return predictor.predict_blockers(task, blocker_patterns, historical_tasks)


def estimate_duration(
    task: dict[str, Any],
    duration_patterns: list[TaskDurationPattern],
    historical_tasks: list[dict[str, Any]],
) -> DurationPrediction:
    """Convenience function to estimate duration.

    Args:
        task: Task to estimate
        duration_patterns: Known duration patterns
        historical_tasks: Historical task data

    Returns:
        DurationPrediction
    """
    estimator = DurationEstimator()
    return estimator.estimate_duration(task, duration_patterns, historical_tasks)
