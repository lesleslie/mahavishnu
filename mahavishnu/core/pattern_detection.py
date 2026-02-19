"""Pattern Detection Engine for Mahavishnu.

Analyzes historical task data to detect patterns, predict blockers,
and estimate task durations using statistical analysis and similarity search.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from mahavishnu.models.pattern import (
    BlockerPattern,
    CompletionSequencePattern,
    DetectedPattern,
    PatternAnalysisResult,
    PatternFrequency,
    PatternSeverity,
    PatternType,
    TaskDurationPattern,
)

logger = logging.getLogger(__name__)


class PatternDetectionConfig(BaseModel):
    """Configuration for pattern detection."""

    # Minimum samples required for pattern detection
    min_samples: int = Field(default=5, ge=1)

    # Confidence thresholds
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    high_confidence: float = Field(default=0.85, ge=0.0, le=1.0)

    # Pattern detection windows
    lookback_days: int = Field(default=90, ge=7)

    # Duration buckets (hours)
    duration_buckets: list[int] = Field(
        default_factory=lambda: [1, 4, 8, 24, 72, 168]  # 1h, 4h, 1d, 3d, 1w
    )

    # Blocker keywords
    blocker_keywords: list[str] = Field(
        default_factory=lambda: [
            "blocked",
            "waiting",
            "dependency",
            "depends on",
            "need",
            "requires",
            "cannot proceed",
            "stuck",
            "on hold",
        ]
    )


class PatternDetector:
    """Detects patterns in historical task data."""

    def __init__(self, config: PatternDetectionConfig | None = None):
        """Initialize pattern detector.

        Args:
            config: Optional configuration
        """
        self.config = config or PatternDetectionConfig()
        self._patterns: dict[str, DetectedPattern] = {}

    def analyze_tasks(self, tasks: list[dict[str, Any]]) -> PatternAnalysisResult:
        """Analyze a set of tasks for patterns.

        Args:
            tasks: List of task dictionaries with historical data

        Returns:
            PatternAnalysisResult with detected patterns
        """
        if len(tasks) < self.config.min_samples:
            logger.warning(
                f"Insufficient samples for pattern detection: {len(tasks)} < {self.config.min_samples}"
            )
            return PatternAnalysisResult(task_count=len(tasks))

        result = PatternAnalysisResult(task_count=len(tasks))

        # Analyze duration patterns
        result.duration_patterns = self._detect_duration_patterns(tasks)

        # Analyze blocker patterns
        result.blocker_patterns = self._detect_blocker_patterns(tasks)

        # Analyze completion sequences
        result.sequence_patterns = self._detect_sequence_patterns(tasks)

        # Calculate statistics
        result.avg_task_duration_hours = self._calculate_avg_duration(tasks)
        result.blocker_rate = self._calculate_blocker_rate(tasks)
        result.completion_rate = self._calculate_completion_rate(tasks)

        return result

    def _detect_duration_patterns(
        self, tasks: list[dict[str, Any]]
    ) -> list[TaskDurationPattern]:
        """Detect duration patterns in tasks.

        Args:
            tasks: List of tasks with duration data

        Returns:
            List of detected duration patterns
        """
        patterns: list[TaskDurationPattern] = []

        # Group by repository
        by_repo: dict[str, list[float]] = defaultdict(list)
        by_type: dict[str, list[float]] = defaultdict(list)
        by_priority: dict[str, list[float]] = defaultdict(list)

        for task in tasks:
            if duration := self._get_task_duration_hours(task):
                if repo := task.get("repository"):
                    by_repo[repo].append(duration)
                if tags := task.get("tags"):
                    for tag in tags:
                        by_type[tag].append(duration)
                if priority := task.get("priority"):
                    by_priority[priority].append(duration)

        # Create repository patterns
        for repo, durations in by_repo.items():
            if len(durations) >= self.config.min_samples:
                pattern = self._create_duration_pattern(
                    durations=durations,
                    repository=repo,
                    sample_task_ids=[t["id"] for t in tasks if t.get("repository") == repo][:10],
                )
                patterns.append(pattern)

        # Create type patterns
        for task_type, durations in by_type.items():
            if len(durations) >= self.config.min_samples:
                pattern = self._create_duration_pattern(
                    durations=durations,
                    task_type=task_type,
                    sample_task_ids=[
                        t["id"]
                        for t in tasks
                        if task_type in t.get("tags", [])
                    ][:10],
                )
                patterns.append(pattern)

        return patterns

    def _detect_blocker_patterns(
        self, tasks: list[dict[str, Any]]
    ) -> list[BlockerPattern]:
        """Detect recurring blocker patterns.

        Args:
            tasks: List of tasks with blocker data

        Returns:
            List of detected blocker patterns
        """
        patterns: list[BlockerPattern] = []

        # Track blockers by keyword
        keyword_blockers: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for task in tasks:
            if task.get("status") == "blocked":
                text = f"{task.get('title', '')} {task.get('description', '')}".lower()

                for keyword in self.config.blocker_keywords:
                    if keyword in text:
                        keyword_blockers[keyword].append(task)

        # Create patterns for common blockers
        for keyword, blocked_tasks in keyword_blockers.items():
            if len(blocked_tasks) >= self.config.min_samples:
                # Calculate resolution time for resolved blockers
                resolution_times: list[float] = []
                for task in blocked_tasks:
                    if resolved_time := task.get("blocked_resolved_at"):
                        if blocked_time := task.get("blocked_at"):
                            delta = datetime.fromisoformat(resolved_time) - datetime.fromisoformat(
                                blocked_time
                            )
                            resolution_times.append(delta.total_seconds() / 3600)

                avg_resolution = (
                    sum(resolution_times) / len(resolution_times)
                    if resolution_times
                    else None
                )

                pattern = BlockerPattern(
                    blocker_keyword=keyword,
                    blocker_category=self._categorize_blocker(keyword),
                    occurrence_count=len(blocked_tasks),
                    affected_task_ids=[t["id"] for t in blocked_tasks[:20]],
                    affected_repositories=list(
                        {t.get("repository") for t in blocked_tasks if t.get("repository")}
                    ),
                    resolution_suggestions=self._get_resolution_suggestions(keyword),
                    avg_resolution_time_hours=avg_resolution,
                    confidence=min(1.0, len(blocked_tasks) / 20),
                    frequency=self._calculate_frequency(len(blocked_tasks), len(tasks)),
                    severity=self._determine_severity(keyword, len(blocked_tasks)),
                )
                patterns.append(pattern)

        return patterns

    def _detect_sequence_patterns(
        self, tasks: list[dict[str, Any]]
    ) -> list[CompletionSequencePattern]:
        """Detect task completion sequence patterns.

        Args:
            tasks: List of tasks with status history

        Returns:
            List of detected sequence patterns
        """
        patterns: list[CompletionSequencePattern] = []

        # Track status transitions
        transitions: dict[tuple[str, ...], int] = Counter()
        by_repo: dict[str, list[tuple[str, ...]]] = defaultdict(list)

        for task in tasks:
            if history := task.get("status_history"):
                sequence = tuple(h.get("status") for h in history if h.get("status"))
                if len(sequence) >= 2:
                    transitions[sequence] += 1
                    if repo := task.get("repository"):
                        by_repo[repo].append(sequence)

        # Create patterns for common sequences
        total_tasks = len(tasks)
        for sequence, count in transitions.most_common(10):
            if count >= self.config.min_samples:
                completion_prob = self._calculate_sequence_completion_prob(
                    sequence, tasks
                )

                pattern = CompletionSequencePattern(
                    sequence=list(sequence),
                    sequence_count=count,
                    repository=None,  # Global pattern
                    leads_to_completion=sequence[-1] == "completed",
                    completion_probability=completion_prob,
                    confidence=min(1.0, count / 10),
                    frequency=self._calculate_frequency(count, total_tasks),
                )
                patterns.append(pattern)

        # Create repository-specific patterns
        for repo, repo_sequences in by_repo.items():
            repo_transitions = Counter(repo_sequences)
            for sequence, count in repo_transitions.most_common(5):
                if count >= self.config.min_samples:
                    completion_prob = self._calculate_sequence_completion_prob(
                        sequence, tasks
                    )

                    pattern = CompletionSequencePattern(
                        sequence=list(sequence),
                        sequence_count=count,
                        repository=repo,
                        leads_to_completion=sequence[-1] == "completed",
                        completion_probability=completion_prob,
                        confidence=min(1.0, count / 8),
                        frequency=self._calculate_frequency(count, len(repo_sequences)),
                    )
                    patterns.append(pattern)

        return patterns

    def match_task_to_patterns(
        self, task: dict[str, Any], patterns: list[DetectedPattern]
    ) -> list[dict[str, Any]]:
        """Match a task to known patterns.

        Args:
            task: Task to match
            patterns: Known patterns

        Returns:
            List of pattern matches with predictions
        """
        from mahavishnu.models.pattern import PatternMatch

        matches: list[dict[str, Any]] = []

        for pattern in patterns:
            match_score = self._calculate_match_score(task, pattern)
            if match_score >= self.config.min_confidence:
                predictions = self._generate_predictions(task, pattern)

                matches.append(
                    {
                        "pattern_id": pattern.id,
                        "pattern_type": pattern.pattern_type.value,
                        "match_score": match_score,
                        "predictions": predictions,
                    }
                )

        return sorted(matches, key=lambda m: m["match_score"], reverse=True)

    def _calculate_match_score(
        self, task: dict[str, Any], pattern: DetectedPattern
    ) -> float:
        """Calculate how well a task matches a pattern.

        Args:
            task: Task to match
            pattern: Pattern to match against

        Returns:
            Match score (0-1)
        """
        base_score = 0.0

        if pattern.pattern_type == PatternType.TASK_DURATION:
            duration_data = pattern.pattern_data
            if isinstance(duration_data, TaskDurationPattern):
                # Check repository match (most important factor)
                if duration_data.repository and task.get("repository") == duration_data.repository:
                    base_score += 0.5
                # Check type match
                if duration_data.task_type and duration_data.task_type in task.get("tags", []):
                    base_score += 0.25
                # Check priority match
                if task.get("priority") in (duration_data.priority_range or []):
                    base_score += 0.15
                # Base confidence bonus
                base_score += duration_data.confidence * 0.1

        elif pattern.pattern_type == PatternType.BLOCKER_RECURRING:
            blocker_data = pattern.pattern_data
            if isinstance(blocker_data, BlockerPattern):
                # Check for blocker keyword
                text = f"{task.get('title', '')} {task.get('description', '')}".lower()
                if blocker_data.blocker_keyword in text:
                    base_score += 0.5
                # Check repository match
                if task.get("repository") in blocker_data.affected_repositories:
                    base_score += 0.3
                # Base confidence
                base_score += blocker_data.confidence * 0.2

        return min(1.0, base_score)

    def _generate_predictions(
        self, task: dict[str, Any], pattern: DetectedPattern
    ) -> dict[str, Any]:
        """Generate predictions based on pattern match.

        Args:
            task: Task being analyzed
            pattern: Matched pattern

        Returns:
            Dictionary of predictions
        """
        predictions: dict[str, Any] = {}

        if pattern.pattern_type == PatternType.TASK_DURATION:
            duration_data = pattern.pattern_data
            if isinstance(duration_data, TaskDurationPattern):
                predictions["estimated_duration_hours"] = duration_data.avg_duration
                predictions["duration_range"] = (
                    duration_data.min_duration,
                    duration_data.max_duration,
                )
                predictions["confidence"] = duration_data.confidence

        elif pattern.pattern_type == PatternType.BLOCKER_RECURRING:
            blocker_data = pattern.pattern_data
            if isinstance(blocker_data, BlockerPattern):
                predictions["blocker_probability"] = blocker_data.confidence
                predictions["potential_blocker"] = blocker_data.blocker_keyword
                predictions["resolution_suggestions"] = blocker_data.resolution_suggestions
                if blocker_data.avg_resolution_time_hours:
                    predictions["estimated_resolution_hours"] = (
                        blocker_data.avg_resolution_time_hours
                    )

        return predictions

    # Helper methods

    def _get_task_duration_hours(self, task: dict[str, Any]) -> float | None:
        """Get task duration in hours."""
        if created := task.get("created_at"):
            if completed := task.get("completed_at"):
                created_dt = datetime.fromisoformat(created) if isinstance(created, str) else created
                completed_dt = datetime.fromisoformat(completed) if isinstance(completed, str) else completed
                return (completed_dt - created_dt).total_seconds() / 3600
        return None

    def _create_duration_pattern(
        self,
        durations: list[float],
        repository: str | None = None,
        task_type: str | None = None,
        sample_task_ids: list[str] | None = None,
    ) -> TaskDurationPattern:
        """Create a duration pattern from duration samples."""
        sorted_durations = sorted(durations)
        n = len(sorted_durations)

        avg = sum(durations) / n
        variance = sum((d - avg) ** 2 for d in durations) / n
        std_dev = math.sqrt(variance)

        # Median
        mid = n // 2
        if n % 2 == 0:
            median = (sorted_durations[mid - 1] + sorted_durations[mid]) / 2
        else:
            median = sorted_durations[mid]

        return TaskDurationPattern(
            min_duration=min(durations),
            max_duration=max(durations),
            avg_duration=avg,
            median_duration=median,
            std_deviation=std_dev,
            repository=repository,
            task_type=task_type,
            sample_count=n,
            sample_task_ids=sample_task_ids or [],
            confidence=min(1.0, n / 20),
            frequency=self._calculate_frequency(n, 100),  # Relative frequency
        )

    def _categorize_blocker(self, keyword: str) -> str:
        """Categorize blocker by keyword."""
        categories = {
            "dependency": ["dependency", "depends on", "requires"],
            "resource": ["waiting", "need", "on hold"],
            "technical": ["stuck", "cannot proceed", "blocked"],
        }
        for category, keywords in categories.items():
            if keyword in keywords:
                return category
        return "unknown"

    def _get_resolution_suggestions(self, keyword: str) -> list[str]:
        """Get resolution suggestions for a blocker type."""
        suggestions = {
            "dependency": [
                "Check if dependency task is in progress",
                "Contact dependency task owner",
                "Consider parallel work on non-dependent parts",
            ],
            "waiting": [
                "Follow up with blocking party",
                "Set reminder to check status",
                "Document waiting reason",
            ],
            "stuck": [
                "Break down into smaller tasks",
                "Request code review or pair programming",
                "Research similar problems",
            ],
        }
        category = self._categorize_blocker(keyword)
        return suggestions.get(category, ["Investigate root cause", "Ask for help"])

    def _calculate_frequency(self, count: int, total: int) -> PatternFrequency:
        """Calculate pattern frequency from count and total."""
        if total == 0:
            return PatternFrequency.RARE

        percentage = (count / total) * 100

        if percentage < 5:
            return PatternFrequency.RARE
        elif percentage < 20:
            return PatternFrequency.OCCASIONAL
        elif percentage < 50:
            return PatternFrequency.COMMON
        elif percentage < 80:
            return PatternFrequency.FREQUENT
        else:
            return PatternFrequency.VERY_FREQUENT

    def _determine_severity(
        self, keyword: str, occurrence_count: int
    ) -> PatternSeverity:
        """Determine pattern severity."""
        # High severity for frequently occurring blockers
        if occurrence_count >= 10:
            return PatternSeverity.HIGH
        elif occurrence_count >= 5:
            return PatternSeverity.MEDIUM
        else:
            return PatternSeverity.LOW

    def _calculate_avg_duration(self, tasks: list[dict[str, Any]]) -> float:
        """Calculate average task duration in hours."""
        durations = [d for t in tasks if (d := self._get_task_duration_hours(t))]
        return sum(durations) / len(durations) if durations else 0.0

    def _calculate_blocker_rate(self, tasks: list[dict[str, Any]]) -> float:
        """Calculate rate of blocked tasks."""
        if not tasks:
            return 0.0
        blocked = sum(1 for t in tasks if t.get("status") == "blocked")
        return blocked / len(tasks)

    def _calculate_completion_rate(self, tasks: list[dict[str, Any]]) -> float:
        """Calculate task completion rate."""
        if not tasks:
            return 0.0
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        return completed / len(tasks)

    def _calculate_sequence_completion_prob(
        self, sequence: tuple[str, ...], tasks: list[dict[str, Any]]
    ) -> float:
        """Calculate probability that a sequence leads to completion."""
        if not sequence or sequence[-1] == "completed":
            return 1.0

        # Count tasks with this sequence that eventually completed
        matching = 0
        completed = 0

        for task in tasks:
            if history := task.get("status_history"):
                task_sequence = tuple(h.get("status") for h in history)
                if task_sequence[: len(sequence)] == sequence:
                    matching += 1
                    if task.get("status") == "completed":
                        completed += 1

        return completed / matching if matching > 0 else 0.0


def detect_patterns(tasks: list[dict[str, Any]]) -> PatternAnalysisResult:
    """Convenience function to detect patterns in tasks.

    Args:
        tasks: List of task dictionaries

    Returns:
        PatternAnalysisResult
    """
    detector = PatternDetector()
    return detector.analyze_tasks(tasks)
