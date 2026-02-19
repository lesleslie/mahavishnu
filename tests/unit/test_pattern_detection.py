"""Tests for Pattern Detection Module.

Tests cover:
- Pattern detection configuration
- Duration pattern detection
- Blocker pattern detection
- Sequence pattern detection
- Pattern matching and predictions
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from mahavishnu.core.pattern_detection import (
    PatternDetectionConfig,
    PatternDetector,
    detect_patterns,
)
from mahavishnu.models.pattern import (
    BlockerPattern,
    CompletionSequencePattern,
    DetectedPattern,
    PatternFrequency,
    PatternSeverity,
    PatternType,
    TaskDurationPattern,
)


class TestPatternDetectionConfig:
    """Test pattern detection configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = PatternDetectionConfig()

        assert config.min_samples == 5
        assert config.min_confidence == 0.6
        assert config.high_confidence == 0.85
        assert config.lookback_days == 90
        assert "blocked" in config.blocker_keywords

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = PatternDetectionConfig(
            min_samples=10,
            min_confidence=0.7,
            blocker_keywords=["custom_blocker"],
        )

        assert config.min_samples == 10
        assert config.min_confidence == 0.7
        assert config.blocker_keywords == ["custom_blocker"]


class TestPatternDetector:
    """Test pattern detector."""

    @pytest.fixture
    def detector(self) -> PatternDetector:
        """Create pattern detector with low min_samples for testing."""
        config = PatternDetectionConfig(min_samples=2)
        return PatternDetector(config)

    @pytest.fixture
    def sample_tasks(self) -> list[dict]:
        """Create sample tasks for testing."""
        base_time = datetime.utcnow()
        tasks = []

        for i in range(10):
            created = base_time - timedelta(days=10 - i, hours=2)
            completed = created + timedelta(hours=4 + i)

            task = {
                "id": f"task-{i}",
                "title": f"Test task {i}",
                "repository": "test-repo" if i < 5 else "other-repo",
                "status": "completed" if i < 8 else "blocked",
                "priority": "high" if i < 3 else "medium",
                "tags": ["bug"] if i % 2 == 0 else ["feature"],
                "created_at": created.isoformat(),
                "completed_at": completed.isoformat() if i < 8 else None,
            }

            if i >= 8:
                task["description"] = "blocked waiting for dependency"
                task["status_history"] = [
                    {"status": "pending", "timestamp": created.isoformat()},
                    {"status": "in_progress", "timestamp": (created + timedelta(hours=1)).isoformat()},
                    {"status": "blocked", "timestamp": (created + timedelta(hours=2)).isoformat()},
                ]
            else:
                task["status_history"] = [
                    {"status": "pending", "timestamp": created.isoformat()},
                    {"status": "in_progress", "timestamp": (created + timedelta(hours=1)).isoformat()},
                    {"status": "completed", "timestamp": completed.isoformat()},
                ]

            tasks.append(task)

        return tasks

    def test_analyze_tasks_insufficient_samples(self) -> None:
        """Test analysis with insufficient samples."""
        detector = PatternDetector()  # Default min_samples=5
        tasks = [{"id": "1", "status": "completed"}]

        result = detector.analyze_tasks(tasks)

        assert result.task_count == 1
        assert len(result.duration_patterns) == 0

    def test_analyze_tasks_with_samples(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test analysis with sufficient samples."""
        result = detector.analyze_tasks(sample_tasks)

        assert result.task_count == 10
        assert len(result.duration_patterns) > 0
        assert result.avg_task_duration_hours > 0
        assert result.completion_rate == 0.8  # 8/10 completed

    def test_detect_duration_patterns(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test duration pattern detection."""
        patterns = detector._detect_duration_patterns(sample_tasks)

        assert len(patterns) > 0

        # Check that patterns have required fields
        for pattern in patterns:
            assert isinstance(pattern, TaskDurationPattern)
            assert pattern.avg_duration > 0
            assert pattern.median_duration > 0
            assert pattern.sample_count >= 2

    def test_detect_duration_patterns_by_repository(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test duration patterns grouped by repository."""
        patterns = detector._detect_duration_patterns(sample_tasks)

        repo_patterns = [p for p in patterns if p.repository]
        assert len(repo_patterns) > 0

        repositories = {p.repository for p in repo_patterns}
        assert "test-repo" in repositories or "other-repo" in repositories

    def test_detect_blocker_patterns(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test blocker pattern detection."""
        patterns = detector._detect_blocker_patterns(sample_tasks)

        # Should detect "blocked" keyword in 2 blocked tasks
        assert len(patterns) > 0

        for pattern in patterns:
            assert isinstance(pattern, BlockerPattern)
            assert pattern.occurrence_count >= 2
            assert pattern.blocker_keyword in detector.config.blocker_keywords

    def test_detect_sequence_patterns(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test completion sequence pattern detection."""
        patterns = detector._detect_sequence_patterns(sample_tasks)

        assert len(patterns) > 0

        for pattern in patterns:
            assert isinstance(pattern, CompletionSequencePattern)
            assert len(pattern.sequence) >= 2
            assert pattern.sequence_count >= 2

    def test_calculate_statistics(
        self, detector: PatternDetector, sample_tasks: list[dict]
    ) -> None:
        """Test statistics calculation."""
        avg_duration = detector._calculate_avg_duration(sample_tasks)
        blocker_rate = detector._calculate_blocker_rate(sample_tasks)
        completion_rate = detector._calculate_completion_rate(sample_tasks)

        assert avg_duration > 0
        assert blocker_rate == 0.2  # 2/10 blocked
        assert completion_rate == 0.8  # 8/10 completed


class TestPatternMatching:
    """Test pattern matching functionality."""

    @pytest.fixture
    def detector(self) -> PatternDetector:
        """Create pattern detector with lower min_confidence for testing."""
        config = PatternDetectionConfig(min_samples=2, min_confidence=0.5)
        return PatternDetector(config)

    @pytest.fixture
    def sample_pattern(self) -> DetectedPattern:
        """Create sample detected pattern."""
        duration_pattern = TaskDurationPattern(
            min_duration=1.0,
            max_duration=10.0,
            avg_duration=5.0,
            median_duration=4.5,
            std_deviation=2.0,
            repository="test-repo",
            sample_count=10,
            confidence=0.8,
        )
        return DetectedPattern(
            pattern_type=PatternType.TASK_DURATION,
            pattern_data=duration_pattern,
            confidence_score=0.8,
        )

    def test_match_task_to_pattern(
        self, detector: PatternDetector, sample_pattern: DetectedPattern
    ) -> None:
        """Test task matching to pattern."""
        task = {
            "id": "new-task",
            "title": "New task",
            "repository": "test-repo",
            "tags": ["bug"],
            "priority": "high",
        }

        matches = detector.match_task_to_patterns(task, [sample_pattern])

        assert len(matches) > 0
        assert matches[0]["pattern_type"] == PatternType.TASK_DURATION.value
        assert matches[0]["match_score"] >= detector.config.min_confidence

    def test_match_task_no_match(
        self, detector: PatternDetector, sample_pattern: DetectedPattern
    ) -> None:
        """Test task that doesn't match pattern."""
        task = {
            "id": "new-task",
            "title": "New task",
            "repository": "different-repo",  # Different repo
            "tags": ["feature"],
            "priority": "low",
        }

        # Match score should be low since repository doesn't match
        match_score = detector._calculate_match_score(task, sample_pattern)
        assert match_score < detector.config.min_confidence  # Below min_confidence

    def test_generate_duration_predictions(
        self, detector: PatternDetector, sample_pattern: DetectedPattern
    ) -> None:
        """Test duration prediction generation."""
        task = {"id": "test", "repository": "test-repo"}

        predictions = detector._generate_predictions(task, sample_pattern)

        assert "estimated_duration_hours" in predictions
        assert predictions["estimated_duration_hours"] == 5.0
        assert "duration_range" in predictions
        assert predictions["confidence"] == 0.8

    def test_generate_blocker_predictions(self, detector: PatternDetector) -> None:
        """Test blocker prediction generation."""
        blocker_pattern = BlockerPattern(
            blocker_keyword="dependency",
            blocker_category="dependency",
            occurrence_count=10,
            avg_resolution_time_hours=4.0,
            resolution_suggestions=["Check dependency status"],
            confidence=0.7,
        )

        detected = DetectedPattern(
            pattern_type=PatternType.BLOCKER_RECURRING,
            pattern_data=blocker_pattern,
            confidence_score=0.7,
        )

        task = {"id": "test", "description": "blocked by dependency"}
        predictions = detector._generate_predictions(task, detected)

        assert "blocker_probability" in predictions
        assert predictions["potential_blocker"] == "dependency"
        assert len(predictions["resolution_suggestions"]) > 0


class TestHelperMethods:
    """Test helper methods."""

    @pytest.fixture
    def detector(self) -> PatternDetector:
        """Create pattern detector."""
        return PatternDetector()

    def test_categorize_blocker(self, detector: PatternDetector) -> None:
        """Test blocker categorization."""
        assert detector._categorize_blocker("dependency") == "dependency"
        assert detector._categorize_blocker("waiting") == "resource"
        assert detector._categorize_blocker("stuck") == "technical"
        assert detector._categorize_blocker("unknown_keyword") == "unknown"

    def test_get_resolution_suggestions(self, detector: PatternDetector) -> None:
        """Test resolution suggestion retrieval."""
        suggestions = detector._get_resolution_suggestions("dependency")
        assert len(suggestions) > 0
        assert any("dependency" in s.lower() for s in suggestions)

    def test_calculate_frequency(self, detector: PatternDetector) -> None:
        """Test frequency calculation."""
        assert detector._calculate_frequency(1, 100) == PatternFrequency.RARE
        assert detector._calculate_frequency(10, 100) == PatternFrequency.OCCASIONAL
        assert detector._calculate_frequency(30, 100) == PatternFrequency.COMMON
        assert detector._calculate_frequency(60, 100) == PatternFrequency.FREQUENT
        assert detector._calculate_frequency(90, 100) == PatternFrequency.VERY_FREQUENT

    def test_calculate_frequency_zero_total(self, detector: PatternDetector) -> None:
        """Test frequency calculation with zero total."""
        assert detector._calculate_frequency(1, 0) == PatternFrequency.RARE

    def test_determine_severity(self, detector: PatternDetector) -> None:
        """Test severity determination."""
        assert detector._determine_severity("blocked", 15) == PatternSeverity.HIGH
        assert detector._determine_severity("blocked", 7) == PatternSeverity.MEDIUM
        assert detector._determine_severity("blocked", 2) == PatternSeverity.LOW


class TestConvenienceFunction:
    """Test convenience function."""

    def test_detect_patterns_function(self) -> None:
        """Test detect_patterns convenience function."""
        tasks = [
            {
                "id": "1",
                "status": "completed",
                "created_at": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
                "repository": "test",
                "status_history": [
                    {"status": "pending"},
                    {"status": "completed"},
                ],
            }
        ]

        result = detect_patterns(tasks)

        assert result.task_count == 1
        assert isinstance(result, type(result))


class TestPatternModels:
    """Test pattern model classes."""

    def test_task_duration_pattern(self) -> None:
        """Test TaskDurationPattern model."""
        pattern = TaskDurationPattern(
            min_duration=1.0,
            max_duration=10.0,
            avg_duration=5.0,
            median_duration=4.5,
            std_deviation=2.0,
            sample_count=10,
        )

        assert pattern.pattern_type == PatternType.TASK_DURATION
        assert pattern.min_duration == 1.0
        assert pattern.max_duration == 10.0

    def test_blocker_pattern(self) -> None:
        """Test BlockerPattern model."""
        pattern = BlockerPattern(
            blocker_keyword="dependency",
            blocker_category="dependency",
            occurrence_count=5,
            affected_task_ids=["task-1", "task-2"],
        )

        assert pattern.pattern_type == PatternType.BLOCKER_RECURRING
        assert pattern.blocker_keyword == "dependency"
        assert len(pattern.affected_task_ids) == 2

    def test_completion_sequence_pattern(self) -> None:
        """Test CompletionSequencePattern model."""
        pattern = CompletionSequencePattern(
            sequence=["pending", "in_progress", "completed"],
            sequence_count=10,
            leads_to_completion=True,
            completion_probability=0.95,
        )

        assert pattern.pattern_type == PatternType.COMPLETION_SEQUENCE
        assert len(pattern.sequence) == 3
        assert pattern.completion_probability == 0.95

    def test_detected_pattern(self) -> None:
        """Test DetectedPattern model."""
        duration_pattern = TaskDurationPattern(
            min_duration=1.0,
            max_duration=10.0,
            avg_duration=5.0,
            median_duration=4.5,
            std_deviation=2.0,
        )

        detected = DetectedPattern(
            pattern_type=PatternType.TASK_DURATION,
            pattern_data=duration_pattern,
            confidence_score=0.8,
        )

        assert detected.id is not None
        assert detected.confidence_score == 0.8

        d = detected.to_dict()
        assert "id" in d
        assert "pattern_type" in d
        assert "confidence_score" in d

    def test_pattern_analysis_result(self) -> None:
        """Test PatternAnalysisResult model."""
        result = type("PatternAnalysisResult", (), {})()
        from mahavishnu.models.pattern import PatternAnalysisResult

        result = PatternAnalysisResult(
            task_count=10,
            avg_task_duration_hours=5.0,
            blocker_rate=0.2,
            completion_rate=0.8,
        )

        assert result.task_count == 10
        assert result.avg_task_duration_hours == 5.0

        d = result.to_dict()
        assert "task_count" in d
        assert "statistics" in d
