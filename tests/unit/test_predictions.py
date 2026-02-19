"""Tests for Predictions Module.

Tests cover:
- Blocker prediction
- Duration estimation
- Confidence intervals
- Pattern matching
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from mahavishnu.core.predictions import (
    BlockerPrediction,
    BlockerPredictor,
    DurationEstimator,
    DurationPrediction,
    PredictionConfig,
    predict_blockers,
    estimate_duration,
)
from mahavishnu.models.pattern import (
    BlockerPattern,
    PatternSeverity,
    TaskDurationPattern,
)


class TestPredictionConfig:
    """Test prediction configuration."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = PredictionConfig()

        assert config.min_samples == 5
        assert config.confidence_level == 0.95
        assert config.repository_weight == 0.3

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = PredictionConfig(
            min_samples=10,
            confidence_level=0.99,
            repository_weight=0.5,
        )

        assert config.min_samples == 10
        assert config.confidence_level == 0.99
        assert config.repository_weight == 0.5


class TestBlockerPrediction:
    """Test blocker prediction model."""

    def test_create_prediction(self) -> None:
        """Test creating a blocker prediction."""
        prediction = BlockerPrediction(
            task_id="task-123",
            blocker_probability=0.7,
            confidence_interval=(0.5, 0.9),
            potential_blockers=["dependency", "external_api"],
            risk_factors=["High priority", "Contains 'integration'"],
            mitigation_suggestions=["Identify dependencies early"],
        )

        assert prediction.task_id == "task-123"
        assert prediction.blocker_probability == 0.7
        assert len(prediction.potential_blockers) == 2

    def test_prediction_to_dict(self) -> None:
        """Test prediction serialization."""
        prediction = BlockerPrediction(
            task_id="task-123",
            blocker_probability=0.5,
            confidence_interval=(0.3, 0.7),
        )

        d = prediction.to_dict()

        assert d["task_id"] == "task-123"
        assert d["blocker_probability"] == 0.5
        assert "predicted_at" in d


class TestDurationPrediction:
    """Test duration prediction model."""

    def test_create_prediction(self) -> None:
        """Test creating a duration prediction."""
        prediction = DurationPrediction(
            task_id="task-123",
            estimated_hours=4.5,
            confidence_interval=(2.0, 8.0),
            confidence=0.8,
            based_on_tasks=10,
        )

        assert prediction.task_id == "task-123"
        assert prediction.estimated_hours == 4.5
        assert prediction.confidence == 0.8

    def test_prediction_to_dict(self) -> None:
        """Test prediction serialization."""
        prediction = DurationPrediction(
            task_id="task-123",
            estimated_hours=6.0,
            confidence=0.7,
        )

        d = prediction.to_dict()

        assert d["estimated_hours"] == 6.0
        assert "confidence_interval" in d
        assert "factors" in d


class TestBlockerPredictor:
    """Test blocker predictor."""

    @pytest.fixture
    def predictor(self) -> BlockerPredictor:
        """Create blocker predictor."""
        return BlockerPredictor()

    @pytest.fixture
    def blocker_patterns(self) -> list[BlockerPattern]:
        """Create sample blocker patterns."""
        return [
            BlockerPattern(
                blocker_keyword="dependency",
                blocker_category="dependency",
                occurrence_count=10,
                affected_repositories=["test-repo", "other-repo"],
                confidence=0.8,
                severity=PatternSeverity.HIGH,
            ),
            BlockerPattern(
                blocker_keyword="api",
                blocker_category="external",
                occurrence_count=5,
                affected_repositories=["api-repo"],
                confidence=0.6,
            ),
        ]

    @pytest.fixture
    def historical_tasks(self) -> list[dict]:
        """Create sample historical tasks."""
        tasks = []
        for i in range(20):
            tasks.append({
                "id": f"hist-{i}",
                "repository": "test-repo" if i < 15 else "other-repo",
                "status": "completed" if i < 15 else "blocked",
            })
        return tasks

    def test_predict_blockers_basic(
        self,
        predictor: BlockerPredictor,
        blocker_patterns: list[BlockerPattern],
        historical_tasks: list[dict],
    ) -> None:
        """Test basic blocker prediction."""
        task = {
            "id": "new-task",
            "title": "Integration task with external API dependency",
            "repository": "test-repo",
            "priority": "high",
        }

        prediction = predictor.predict_blockers(
            task, blocker_patterns, historical_tasks
        )

        assert prediction.task_id == "new-task"
        assert prediction.blocker_probability >= 0.0
        assert prediction.blocker_probability <= 1.0
        assert len(prediction.confidence_interval) == 2

    def test_predict_blockers_with_risk_keywords(
        self,
        predictor: BlockerPredictor,
        blocker_patterns: list[BlockerPattern],
        historical_tasks: list[dict],
    ) -> None:
        """Test prediction with risk keywords."""
        task = {
            "id": "risky-task",
            "title": "Complex migration with third-party integration",
            "repository": "test-repo",
            "priority": "critical",
        }

        prediction = predictor.predict_blockers(
            task, blocker_patterns, historical_tasks
        )

        # Should have identified risk factors
        assert len(prediction.risk_factors) > 0
        # Critical priority should increase probability
        assert prediction.blocker_probability > 0.0

    def test_assess_risk_factors(self, predictor: BlockerPredictor) -> None:
        """Test risk factor assessment."""
        task = {
            "title": "Critical integration with external API",
            "priority": "critical",
        }

        risk_score, risk_factors = predictor._assess_risk_factors(task)

        assert risk_score > 0
        assert len(risk_factors) > 0

    def test_calculate_confidence_interval(
        self, predictor: BlockerPredictor
    ) -> None:
        """Test confidence interval calculation."""
        # High sample size = narrow interval
        interval_high = predictor._calculate_confidence_interval(0.5, 100)
        assert interval_high[1] - interval_high[0] < 0.2

        # Low sample size = wide interval
        interval_low = predictor._calculate_confidence_interval(0.5, 5)
        assert interval_low[1] - interval_low[0] > 0.2

    def test_identify_potential_blockers(
        self,
        predictor: BlockerPredictor,
        blocker_patterns: list[BlockerPattern],
    ) -> None:
        """Test identifying potential blockers."""
        task = {
            "id": "test",
            "title": "Task with dependency on external API",
            "repository": "test-repo",
        }

        potential = predictor._identify_potential_blockers(task, blocker_patterns)

        assert "dependency" in potential

    def test_generate_mitigation_suggestions(
        self, predictor: BlockerPredictor
    ) -> None:
        """Test generating mitigation suggestions."""
        suggestions = predictor._generate_mitigation_suggestions(
            ["dependency", "external_api"],
            ["High priority"],
        )

        assert len(suggestions) > 0
        assert any("dependency" in s.lower() for s in suggestions)


class TestDurationEstimator:
    """Test duration estimator."""

    @pytest.fixture
    def estimator(self) -> DurationEstimator:
        """Create duration estimator."""
        return DurationEstimator()

    @pytest.fixture
    def duration_patterns(self) -> list[TaskDurationPattern]:
        """Create sample duration patterns."""
        return [
            TaskDurationPattern(
                repository="test-repo",
                avg_duration=6.0,
                min_duration=2.0,
                max_duration=12.0,
                median_duration=5.0,
                std_deviation=2.0,
                sample_count=20,
                confidence=0.8,
            ),
            TaskDurationPattern(
                task_type="bug",
                avg_duration=4.0,
                min_duration=1.0,
                max_duration=8.0,
                median_duration=3.5,
                std_deviation=1.5,
                sample_count=15,
                confidence=0.7,
            ),
        ]

    @pytest.fixture
    def historical_tasks(self) -> list[dict]:
        """Create sample historical tasks."""
        tasks = []
        now = datetime.utcnow()

        for i in range(20):
            created = now - timedelta(days=10 - i, hours=4)
            completed = created + timedelta(hours=5 + (i % 5))

            tasks.append({
                "id": f"hist-{i}",
                "repository": "test-repo",
                "tags": ["bug"] if i % 2 == 0 else ["feature"],
                "priority": "high" if i < 10 else "medium",
                "status": "completed",
                "created_at": created.isoformat(),
                "completed_at": completed.isoformat(),
            })

        return tasks

    def test_estimate_duration_basic(
        self,
        estimator: DurationEstimator,
        duration_patterns: list[TaskDurationPattern],
        historical_tasks: list[dict],
    ) -> None:
        """Test basic duration estimation."""
        task = {
            "id": "new-task",
            "title": "Fix bug in test-repo",
            "repository": "test-repo",
            "tags": ["bug"],
            "priority": "high",
        }

        prediction = estimator.estimate_duration(
            task, duration_patterns, historical_tasks
        )

        assert prediction.task_id == "new-task"
        assert prediction.estimated_hours > 0
        assert len(prediction.confidence_interval) == 2

    def test_estimate_duration_no_patterns(
        self,
        estimator: DurationEstimator,
        historical_tasks: list[dict],
    ) -> None:
        """Test estimation with no matching patterns."""
        task = {
            "id": "new-task",
            "title": "New feature",
            "repository": "unknown-repo",
            "tags": ["new-feature"],
        }

        prediction = estimator.estimate_duration(task, [], historical_tasks)

        # Should provide a default estimate
        assert prediction.estimated_hours > 0
        assert prediction.confidence < 0.5  # Lower confidence

    def test_calculate_pattern_match(
        self, estimator: DurationEstimator,
        duration_patterns: list[TaskDurationPattern],
    ) -> None:
        """Test pattern matching calculation."""
        task = {
            "repository": "test-repo",
            "tags": ["bug"],
            "priority": "high",
        }

        # Match first pattern (repository)
        weight = estimator._calculate_pattern_match(task, duration_patterns[0])
        assert weight > 0

    def test_get_historical_durations(
        self,
        estimator: DurationEstimator,
        historical_tasks: list[dict],
    ) -> None:
        """Test retrieving historical durations."""
        task = {
            "repository": "test-repo",
            "tags": ["bug"],
            "priority": "high",
        }

        durations = estimator._get_historical_durations(task, historical_tasks)

        # Should find some matching tasks
        assert len(durations) > 0
        # All durations should be positive
        assert all(d > 0 for d in durations)

    def test_combine_estimates(self, estimator: DurationEstimator) -> None:
        """Test combining estimates."""
        weighted = [(6.0, 0.8), (4.0, 0.6)]
        historical = [5.0, 6.0, 4.5]

        estimate, confidence = estimator._combine_estimates(weighted, historical)

        assert estimate > 0
        assert confidence > 0
        # Estimate should be between min and max
        assert 4.0 <= estimate <= 6.5

    def test_calculate_duration_interval(
        self, estimator: DurationEstimator
    ) -> None:
        """Test duration confidence interval."""
        durations = [4.0, 5.0, 6.0, 5.5, 4.5]

        interval = estimator._calculate_duration_interval(5.0, durations)

        assert interval[0] < 5.0
        assert interval[1] > 5.0

    def test_identify_factors(
        self,
        estimator: DurationEstimator,
        duration_patterns: list[TaskDurationPattern],
    ) -> None:
        """Test factor identification."""
        task = {
            "id": "test",
            "repository": "test-repo",
            "tags": ["bug"],
            "priority": "high",
        }

        factors = estimator._identify_factors(task, duration_patterns)

        assert "repository" in factors
        assert "tags" in factors
        assert factors["repository"] == "test-repo"


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_predict_blockers_function(self) -> None:
        """Test predict_blockers convenience function."""
        task = {"id": "test", "title": "Task with dependency", "repository": "test"}
        patterns = [
            BlockerPattern(
                blocker_keyword="dependency",
                blocker_category="dependency",
                occurrence_count=5,
                affected_repositories=["test"],
            )
        ]
        historical = [{"id": "h1", "repository": "test", "status": "completed"}]

        prediction = predict_blockers(task, patterns, historical)

        assert isinstance(prediction, BlockerPrediction)
        assert prediction.task_id == "test"

    def test_estimate_duration_function(self) -> None:
        """Test estimate_duration convenience function."""
        task = {"id": "test", "repository": "test", "tags": ["bug"]}
        patterns = [
            TaskDurationPattern(
                repository="test",
                avg_duration=5.0,
                min_duration=2.0,
                max_duration=10.0,
                median_duration=4.0,
                std_deviation=1.5,
            )
        ]
        historical = []

        prediction = estimate_duration(task, patterns, historical)

        assert isinstance(prediction, DurationPrediction)
        assert prediction.task_id == "test"
