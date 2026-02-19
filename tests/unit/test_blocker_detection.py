"""Tests for Blocker Detection Module.

Tests cover:
- Blocker keyword detection
- Blocker pattern analysis
- Metrics calculation
- Alert generation
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from mahavishnu.core.blocker_detection import (
    BlockerAlert,
    BlockerDetector,
    BlockerMetrics,
    analyze_blockers,
)
from mahavishnu.models.pattern import PatternFrequency, PatternSeverity


class TestBlockerAlert:
    """Test blocker alert model."""

    def test_create_alert(self) -> None:
        """Test creating a blocker alert."""
        alert = BlockerAlert(
            alert_id="alert-123",
            blocker_keyword="dependency",
            blocker_category="dependency",
            severity=PatternSeverity.HIGH,
            message="High-frequency blocker detected",
            affected_repositories=["repo-1", "repo-2"],
            suggested_actions=["Check dependency status"],
        )

        assert alert.alert_id == "alert-123"
        assert alert.blocker_keyword == "dependency"
        assert alert.severity == PatternSeverity.HIGH
        assert len(alert.affected_repositories) == 2

    def test_alert_to_dict(self) -> None:
        """Test alert serialization."""
        alert = BlockerAlert(
            alert_id="alert-123",
            blocker_keyword="stuck",
            blocker_category="technical",
            severity=PatternSeverity.MEDIUM,
            message="Recurring blocker",
        )

        d = alert.to_dict()

        assert d["alert_id"] == "alert-123"
        assert d["severity"] == "medium"
        assert "created_at" in d


class TestBlockerMetrics:
    """Test blocker metrics model."""

    def test_default_metrics(self) -> None:
        """Test default metrics values."""
        metrics = BlockerMetrics()

        assert metrics.total_blocked_tasks == 0
        assert metrics.unique_blocker_types == 0
        assert metrics.most_common_blocker is None

    def test_metrics_to_dict(self) -> None:
        """Test metrics serialization."""
        metrics = BlockerMetrics(
            total_blocked_tasks=10,
            unique_blocker_types=3,
            avg_resolution_time_hours=4.5,
            most_common_blocker="dependency",
            blocker_by_repository={"repo-1": 5, "repo-2": 5},
        )

        d = metrics.to_dict()

        assert d["total_blocked_tasks"] == 10
        assert d["most_common_blocker"] == "dependency"
        assert d["blocker_by_repository"]["repo-1"] == 5


class TestBlockerDetector:
    """Test blocker detector."""

    @pytest.fixture
    def detector(self) -> BlockerDetector:
        """Create blocker detector."""
        return BlockerDetector(min_occurrences=2, alert_threshold=5)

    @pytest.fixture
    def sample_tasks(self) -> list[dict]:
        """Create sample tasks with blockers."""
        tasks = []
        now = datetime.utcnow()

        # Create blocked tasks
        for i in range(8):
            blocked_at = now - timedelta(days=i, hours=3)

            task = {
                "id": f"task-{i}",
                "title": f"Task blocked by dependency issue {i}",
                "description": "Waiting for API to be ready" if i < 4 else "Cannot proceed due to error",
                "status": "blocked",
                "repository": "test-repo" if i < 5 else "other-repo",
                "tags": ["backend"] if i % 2 == 0 else ["frontend"],
                "blocked_at": blocked_at.isoformat(),
            }

            # Some tasks have resolution times
            if i < 3:
                task["blocked_resolved_at"] = (
                    blocked_at + timedelta(hours=4 + i)
                ).isoformat()

            tasks.append(task)

        # Add some non-blocked tasks
        for i in range(10):
            tasks.append({
                "id": f"completed-{i}",
                "title": f"Completed task {i}",
                "status": "completed",
                "repository": "test-repo",
            })

        return tasks

    def test_analyze_blockers_empty(self, detector: BlockerDetector) -> None:
        """Test analysis with no blocked tasks."""
        tasks = [{"id": "1", "status": "completed"}]
        patterns, metrics = detector.analyze_blockers(tasks)

        assert len(patterns) == 0
        assert metrics.total_blocked_tasks == 0

    def test_analyze_blockers_with_data(
        self, detector: BlockerDetector, sample_tasks: list[dict]
    ) -> None:
        """Test analysis with blocked tasks."""
        patterns, metrics = detector.analyze_blockers(sample_tasks)

        assert len(patterns) > 0
        assert metrics.total_blocked_tasks == 8
        assert metrics.most_common_blocker is not None

    def test_detect_keywords(self, detector: BlockerDetector) -> None:
        """Test keyword detection."""
        text = "This task is blocked by a dependency and waiting for review"
        keywords = detector._detect_keywords(text)

        assert "blocked" in keywords
        assert "dependency" in keywords
        assert "waiting" in keywords

    def test_categorize_keyword(self, detector: BlockerDetector) -> None:
        """Test keyword categorization."""
        assert detector._categorize_keyword("dependency") == "dependency"
        assert detector._categorize_keyword("waiting") == "resource"
        assert detector._categorize_keyword("stuck") == "technical"
        assert detector._categorize_keyword("unknown_keyword") == "unknown"

    def test_calculate_metrics(
        self, detector: BlockerDetector, sample_tasks: list[dict]
    ) -> None:
        """Test metrics calculation."""
        blocked_tasks = [t for t in sample_tasks if t.get("status") == "blocked"]
        patterns, _ = detector.analyze_blockers(sample_tasks)
        metrics = detector._calculate_metrics(blocked_tasks, patterns, sample_tasks)

        assert metrics.total_blocked_tasks == 8
        assert len(metrics.blocker_by_repository) > 0
        assert metrics.avg_resolution_time_hours > 0

    def test_get_suggestions(self, detector: BlockerDetector) -> None:
        """Test resolution suggestions."""
        suggestions = detector._get_suggestions("dependency")
        assert len(suggestions) > 0

        suggestions = detector._get_suggestions("stuck")
        assert len(suggestions) > 0

    def test_generate_alerts(
        self, detector: BlockerDetector, sample_tasks: list[dict]
    ) -> None:
        """Test alert generation."""
        detector.analyze_blockers(sample_tasks)
        alerts = detector.get_alerts()

        # Should generate alerts for blockers with >= 5 occurrences
        # Our sample has 8 blocked tasks with "dependency" or similar keywords
        assert len(alerts) > 0

    def test_get_alerts_with_clear(self, detector: BlockerDetector) -> None:
        """Test alert retrieval with clear."""
        # First analysis
        tasks = [
            {
                "id": f"task-{i}",
                "title": f"Blocked by dependency {i}",
                "status": "blocked",
                "blocked_at": datetime.utcnow().isoformat(),
            }
            for i in range(10)
        ]
        detector.analyze_blockers(tasks)

        alerts = detector.get_alerts(clear=True)
        assert len(alerts) > 0

        # Should be cleared now
        alerts_after = detector.get_alerts()
        assert len(alerts_after) == 0


class TestBlockerPatterns:
    """Test blocker pattern detection."""

    @pytest.fixture
    def detector(self) -> BlockerDetector:
        """Create blocker detector."""
        return BlockerDetector(min_occurrences=2)

    def test_pattern_properties(
        self, detector: BlockerDetector
    ) -> None:
        """Test blocker pattern properties."""
        tasks = [
            {
                "id": f"task-{i}",
                "title": f"Waiting for API dependency {i}",
                "status": "blocked",
                "repository": "test-repo",
                "blocked_at": datetime.utcnow().isoformat(),
            }
            for i in range(5)
        ]

        patterns, _ = detector.analyze_blockers(tasks)

        assert len(patterns) > 0
        pattern = patterns[0]

        assert pattern.occurrence_count >= 2
        assert pattern.blocker_keyword is not None
        assert pattern.blocker_category in [
            "dependency",
            "resource",
            "technical",
            "external",
            "knowledge",
            "unknown",
        ]

    def test_frequency_calculation(self, detector: BlockerDetector) -> None:
        """Test frequency calculation."""
        assert detector._calculate_frequency(1, 100) == PatternFrequency.RARE
        assert detector._calculate_frequency(15, 100) == PatternFrequency.OCCASIONAL
        assert detector._calculate_frequency(30, 100) == PatternFrequency.COMMON
        assert detector._calculate_frequency(60, 100) == PatternFrequency.FREQUENT

    def test_severity_determination(self, detector: BlockerDetector) -> None:
        """Test severity determination."""
        # High severity for high count
        assert detector._determine_severity("blocked", 15, None) == PatternSeverity.HIGH

        # High severity for long resolution
        assert detector._determine_severity("blocked", 3, 72.0) == PatternSeverity.HIGH

        # Medium severity
        assert detector._determine_severity("blocked", 7, None) == PatternSeverity.MEDIUM

        # Low severity
        assert detector._determine_severity("blocked", 2, None) == PatternSeverity.LOW


class TestTrendCalculation:
    """Test blocker trend calculation."""

    @pytest.fixture
    def detector(self) -> BlockerDetector:
        """Create blocker detector."""
        return BlockerDetector()

    def test_trend_calculation(self, detector: BlockerDetector) -> None:
        """Test trend is calculated correctly."""
        now = datetime.utcnow()
        tasks = []

        # Create tasks blocked on different days
        for i in range(7):
            blocked_at = now - timedelta(days=i)
            for j in range(i + 1):  # More recent = fewer blockers
                tasks.append({
                    "id": f"task-{i}-{j}",
                    "title": f"Blocked task",
                    "status": "blocked",
                    "blocked_at": blocked_at.isoformat(),
                })

        blocked_tasks = [t for t in tasks if t.get("status") == "blocked"]
        trend = detector._calculate_trend(blocked_tasks)

        assert len(trend) == 7
        assert "date" in trend[0]
        assert "blocked_count" in trend[0]

    def test_trend_empty(self, detector: BlockerDetector) -> None:
        """Test trend with no blocked tasks."""
        trend = detector._calculate_trend([])
        assert len(trend) == 7
        assert all(t["blocked_count"] == 0 for t in trend)


class TestConvenienceFunction:
    """Test convenience function."""

    def test_analyze_blockers_function(self) -> None:
        """Test analyze_blockers convenience function."""
        tasks = [
            {
                "id": f"task-{i}",
                "title": f"Blocked by dependency {i}",
                "status": "blocked",
                "blocked_at": datetime.utcnow().isoformat(),
            }
            for i in range(5)
        ]

        patterns, metrics = analyze_blockers(tasks)

        assert isinstance(metrics, BlockerMetrics)
        assert metrics.total_blocked_tasks == 5
