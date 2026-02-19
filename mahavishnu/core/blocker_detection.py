"""Blocker Detection Module for Mahavishnu.

Analyzes blocked tasks to identify recurring blockers, calculate blocker
frequency metrics, and generate alerts for common blocking patterns.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from mahavishnu.models.pattern import (
    BlockerPattern,
    PatternFrequency,
    PatternSeverity,
)

logger = logging.getLogger(__name__)


class BlockerAlert(BaseModel):
    """Alert for a detected blocker pattern."""

    alert_id: str
    blocker_keyword: str
    blocker_category: str
    severity: PatternSeverity
    message: str
    affected_repositories: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "blocker_keyword": self.blocker_keyword,
            "blocker_category": self.blocker_category,
            "severity": self.severity.value,
            "message": self.message,
            "affected_repositories": self.affected_repositories,
            "suggested_actions": self.suggested_actions,
            "created_at": self.created_at.isoformat(),
        }


class BlockerMetrics(BaseModel):
    """Metrics for blocker analysis."""

    total_blocked_tasks: int = 0
    unique_blocker_types: int = 0
    avg_resolution_time_hours: float = 0.0
    most_common_blocker: str | None = None
    blocker_by_repository: dict[str, int] = Field(default_factory=dict)
    blocker_by_tag: dict[str, int] = Field(default_factory=dict)
    blocker_trend: list[dict[str, Any]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_blocked_tasks": self.total_blocked_tasks,
            "unique_blocker_types": self.unique_blocker_types,
            "avg_resolution_time_hours": self.avg_resolution_time_hours,
            "most_common_blocker": self.most_common_blocker,
            "blocker_by_repository": self.blocker_by_repository,
            "blocker_by_tag": self.blocker_by_tag,
            "blocker_trend": self.blocker_trend,
        }


class BlockerDetector:
    """Detects and analyzes recurring blockers in tasks."""

    # Standard blocker categories with their keywords
    BLOCKER_CATEGORIES: dict[str, list[str]] = {
        "dependency": [
            "dependency",
            "depends on",
            "waiting for",
            "blocked by",
            "requires",
            "prerequisite",
        ],
        "resource": [
            "waiting",
            "need access",
            "need permission",
            "need approval",
            "pending review",
            "awaiting",
        ],
        "technical": [
            "stuck",
            "cannot proceed",
            "blocked",
            "error",
            "bug",
            "issue",
            "problem",
        ],
        "external": [
            "external",
            "third party",
            "vendor",
            "api down",
            "service unavailable",
            "upstream",
        ],
        "knowledge": [
            "unclear",
            "confused",
            "need clarification",
            "documentation",
            "how to",
            "don't know",
        ],
    }

    def __init__(
        self,
        min_occurrences: int = 2,
        alert_threshold: int = 5,
    ):
        """Initialize blocker detector.

        Args:
            min_occurrences: Minimum occurrences to consider a pattern
            alert_threshold: Threshold to generate an alert
        """
        self.min_occurrences = min_occurrences
        self.alert_threshold = alert_threshold
        self._alerts: list[BlockerAlert] = []

    def analyze_blockers(
        self, tasks: list[dict[str, Any]]
    ) -> tuple[list[BlockerPattern], BlockerMetrics]:
        """Analyze tasks for blocker patterns.

        Args:
            tasks: List of tasks to analyze

        Returns:
            Tuple of (blocker patterns, metrics)
        """
        blocked_tasks = [t for t in tasks if t.get("status") == "blocked"]

        if not blocked_tasks:
            return [], BlockerMetrics()

        # Detect blocker patterns
        patterns = self._detect_blocker_patterns(blocked_tasks, tasks)

        # Calculate metrics
        metrics = self._calculate_metrics(blocked_tasks, patterns, tasks)

        # Generate alerts for high-frequency blockers
        self._generate_alerts(patterns)

        return patterns, metrics

    def _detect_blocker_patterns(
        self, blocked_tasks: list[dict[str, Any]], all_tasks: list[dict[str, Any]]
    ) -> list[BlockerPattern]:
        """Detect blocker patterns from blocked tasks."""
        patterns: list[BlockerPattern] = []

        # Track blockers by keyword
        keyword_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "tasks": [],
                "repositories": set(),
                "tags": set(),
                "resolution_times": [],
            }
        )

        for task in blocked_tasks:
            text = f"{task.get('title', '')} {task.get('description', '')}".lower()
            detected_keywords = self._detect_keywords(text)

            for keyword in detected_keywords:
                keyword_data[keyword]["tasks"].append(task)
                if repo := task.get("repository"):
                    keyword_data[keyword]["repositories"].add(repo)
                if tags := task.get("tags"):
                    keyword_data[keyword]["tags"].update(tags)

                # Track resolution time if resolved
                if blocked_at := task.get("blocked_at"):
                    if resolved_at := task.get("blocked_resolved_at"):
                        try:
                            blocked_dt = self._parse_datetime(blocked_at)
                            resolved_dt = self._parse_datetime(resolved_at)
                            hours = (resolved_dt - blocked_dt).total_seconds() / 3600
                            keyword_data[keyword]["resolution_times"].append(hours)
                        except (ValueError, TypeError):
                            pass

        # Create patterns for recurring blockers
        total_tasks = len(all_tasks)
        for keyword, data in keyword_data.items():
            if len(data["tasks"]) >= self.min_occurrences:
                avg_resolution = (
                    sum(data["resolution_times"]) / len(data["resolution_times"])
                    if data["resolution_times"]
                    else None
                )

                pattern = BlockerPattern(
                    blocker_keyword=keyword,
                    blocker_category=self._categorize_keyword(keyword),
                    occurrence_count=len(data["tasks"]),
                    affected_task_ids=[t["id"] for t in data["tasks"][:20]],
                    affected_repositories=list(data["repositories"]),
                    resolution_suggestions=self._get_suggestions(keyword),
                    avg_resolution_time_hours=avg_resolution,
                    confidence=min(1.0, len(data["tasks"]) / 10),
                    frequency=self._calculate_frequency(
                        len(data["tasks"]), total_tasks
                    ),
                    severity=self._determine_severity(
                        keyword, len(data["tasks"]), avg_resolution
                    ),
                    description=f"Recurring blocker: '{keyword}' detected in {len(data['tasks'])} tasks",
                )
                patterns.append(pattern)

        return sorted(patterns, key=lambda p: p.occurrence_count, reverse=True)

    def _detect_keywords(self, text: str) -> list[str]:
        """Detect blocker keywords in text."""
        detected = []
        text_lower = text.lower()

        for category, keywords in self.BLOCKER_CATEGORIES.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected.append(keyword)

        return detected

    def _categorize_keyword(self, keyword: str) -> str:
        """Categorize a blocker keyword."""
        for category, keywords in self.BLOCKER_CATEGORIES.items():
            if keyword in keywords:
                return category
        return "unknown"

    def _calculate_metrics(
        self,
        blocked_tasks: list[dict[str, Any]],
        patterns: list[BlockerPattern],
        all_tasks: list[dict[str, Any]],
    ) -> BlockerMetrics:
        """Calculate blocker metrics."""
        metrics = BlockerMetrics()

        metrics.total_blocked_tasks = len(blocked_tasks)
        metrics.unique_blocker_types = len(patterns)

        if patterns:
            metrics.most_common_blocker = patterns[0].blocker_keyword

        # Count by repository
        repo_counts: dict[str, int] = defaultdict(int)
        for task in blocked_tasks:
            if repo := task.get("repository"):
                repo_counts[repo] += 1
        metrics.blocker_by_repository = dict(repo_counts)

        # Count by tag
        tag_counts: dict[str, int] = defaultdict(int)
        for task in blocked_tasks:
            for tag in task.get("tags", []):
                tag_counts[tag] += 1
        metrics.blocker_by_tag = dict(tag_counts)

        # Calculate average resolution time
        resolution_times = []
        for task in blocked_tasks:
            if blocked_at := task.get("blocked_at"):
                if resolved_at := task.get("blocked_resolved_at"):
                    try:
                        blocked_dt = self._parse_datetime(blocked_at)
                        resolved_dt = self._parse_datetime(resolved_at)
                        hours = (resolved_dt - blocked_dt).total_seconds() / 3600
                        resolution_times.append(hours)
                    except (ValueError, TypeError):
                        pass

        metrics.avg_resolution_time_hours = (
            sum(resolution_times) / len(resolution_times) if resolution_times else 0.0
        )

        # Calculate blocker trend (last 7 days)
        metrics.blocker_trend = self._calculate_trend(blocked_tasks)

        return metrics

    def _calculate_trend(
        self, blocked_tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Calculate blocker trend over time."""
        trend: list[dict[str, Any]] = []
        now = datetime.utcnow()

        for i in range(7):
            day_start = now - timedelta(days=i + 1)
            day_end = now - timedelta(days=i)

            count = 0
            for task in blocked_tasks:
                if blocked_at := task.get("blocked_at"):
                    try:
                        blocked_dt = self._parse_datetime(blocked_at)
                        if day_start <= blocked_dt < day_end:
                            count += 1
                    except (ValueError, TypeError):
                        pass

            trend.append(
                {
                    "date": day_start.strftime("%Y-%m-%d"),
                    "blocked_count": count,
                }
            )

        return list(reversed(trend))

    def _get_suggestions(self, keyword: str) -> list[str]:
        """Get resolution suggestions for a blocker type."""
        suggestions = {
            "dependency": [
                "Check if the dependency task is actively being worked on",
                "Contact the owner of the blocking task",
                "Consider if work can proceed on non-dependent parts",
                "Evaluate if the dependency can be removed or deferred",
            ],
            "waiting": [
                "Follow up with the blocking party",
                "Set a reminder to check status daily",
                "Document the waiting reason in the task",
                "Consider escalation if waiting > 2 days",
            ],
            "stuck": [
                "Break the task into smaller subtasks",
                "Request a code review or pair programming session",
                "Research similar problems in documentation",
                "Ask for help in team chat or standup",
            ],
            "external": [
                "Check external service status page",
                "Implement fallback behavior if possible",
                "Document the external dependency",
                "Consider caching or queuing for reliability",
            ],
            "knowledge": [
                "Search existing documentation",
                "Ask a subject matter expert",
                "Create a spike task for research",
                "Update documentation once resolved",
            ],
        }

        category = self._categorize_keyword(keyword)
        return suggestions.get(category, ["Investigate root cause", "Ask for help"])

    def _calculate_frequency(
        self, count: int, total: int
    ) -> PatternFrequency:
        """Calculate pattern frequency."""
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
        self, keyword: str, count: int, avg_resolution: float | None
    ) -> PatternSeverity:
        """Determine blocker severity."""
        # High severity for frequently occurring or long-resolution blockers
        if count >= 10:
            return PatternSeverity.HIGH
        if avg_resolution and avg_resolution > 48:  # > 2 days
            return PatternSeverity.HIGH
        if count >= 5:
            return PatternSeverity.MEDIUM
        if avg_resolution and avg_resolution > 24:  # > 1 day
            return PatternSeverity.MEDIUM
        return PatternSeverity.LOW

    def _generate_alerts(self, patterns: list[BlockerPattern]) -> None:
        """Generate alerts for high-frequency blockers."""
        from uuid import uuid4

        for pattern in patterns:
            if pattern.occurrence_count >= self.alert_threshold:
                alert = BlockerAlert(
                    alert_id=str(uuid4())[:8],
                    blocker_keyword=pattern.blocker_keyword,
                    blocker_category=pattern.blocker_category,
                    severity=pattern.severity,
                    message=f"High-frequency blocker detected: '{pattern.blocker_keyword}' "
                    f"has blocked {pattern.occurrence_count} tasks",
                    affected_repositories=pattern.affected_repositories,
                    suggested_actions=pattern.resolution_suggestions,
                )
                self._alerts.append(alert)

    def get_alerts(self, clear: bool = False) -> list[BlockerAlert]:
        """Get pending alerts.

        Args:
            clear: Whether to clear alerts after retrieval

        Returns:
            List of pending alerts
        """
        alerts = list(self._alerts)
        if clear:
            self._alerts.clear()
        return alerts

    def _parse_datetime(self, dt_str: str | datetime) -> datetime:
        """Parse datetime from string or return datetime."""
        if isinstance(dt_str, datetime):
            return dt_str
        return datetime.fromisoformat(dt_str)


def analyze_blockers(
    tasks: list[dict[str, Any]]
) -> tuple[list[BlockerPattern], BlockerMetrics]:
    """Convenience function to analyze blockers.

    Args:
        tasks: List of tasks to analyze

    Returns:
        Tuple of (blocker patterns, metrics)
    """
    detector = BlockerDetector()
    return detector.analyze_blockers(tasks)
