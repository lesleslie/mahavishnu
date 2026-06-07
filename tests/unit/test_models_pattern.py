"""Unit tests for mahavishnu/models/pattern.py.

Covers the Pydantic models used for pattern detection, analysis and
prediction. These are pure-data models, so the tests focus on:

- Enum values and string conversions
- Field defaults and validation bounds
- Subclass overrides of pattern_type
- to_dict() serialisation paths
- Construction edge cases (missing required fields, out-of-range values)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError
import pytest

from mahavishnu.models.pattern import (
    BlockerPattern,
    CompletionSequencePattern,
    DetectedPattern,
    PatternAnalysisResult,
    PatternBase,
    PatternFrequency,
    PatternMatch,
    PatternSeverity,
    PatternType,
    TaskDurationPattern,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Enum Tests
# =============================================================================


class TestPatternEnums:
    """Tests for the StrEnum types in pattern.py."""

    def test_pattern_type_values(self):
        assert PatternType.TASK_DURATION.value == "task_duration"
        assert PatternType.BLOCKER_RECURRING.value == "blocker_recurring"
        assert PatternType.COMPLETION_SEQUENCE.value == "completion_sequence"
        assert PatternType.REPOSITORY_WORKFLOW.value == "repository_workflow"
        assert PatternType.ASSIGNMENT_PATTERN.value == "assignment_pattern"
        assert PatternType.TAG_CORRELATION.value == "tag_correlation"

    def test_pattern_type_is_string(self):
        """StrEnum values compare equal to their string value."""
        assert PatternType.TASK_DURATION == "task_duration"
        assert str(PatternType.BLOCKER_RECURRING) == "blocker_recurring"

    def test_pattern_severity_values(self):
        assert PatternSeverity.LOW == "low"
        assert PatternSeverity.MEDIUM == "medium"
        assert PatternSeverity.HIGH == "high"
        assert PatternSeverity.CRITICAL == "critical"

    def test_pattern_frequency_values(self):
        assert PatternFrequency.RARE == "rare"
        assert PatternFrequency.OCCASIONAL == "occasional"
        assert PatternFrequency.COMMON == "common"
        assert PatternFrequency.FREQUENT == "frequent"
        assert PatternFrequency.VERY_FREQUENT == "very_frequent"

    @pytest.mark.parametrize(
        "enum_cls,member",
        [
            (PatternType, "TASK_DURATION"),
            (PatternSeverity, "HIGH"),
            (PatternFrequency, "COMMON"),
        ],
    )
    def test_enums_parametrised_membership(self, enum_cls, member):
        assert hasattr(enum_cls, member)


# =============================================================================
# PatternBase Tests
# =============================================================================


class TestPatternBaseModel:
    """Tests for the PatternBase root model."""

    def test_minimum_construction(self):
        base = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        assert base.pattern_type == PatternType.TAG_CORRELATION
        assert base.description == ""
        assert base.confidence == 0.5
        assert base.frequency == PatternFrequency.OCCASIONAL
        assert base.severity == PatternSeverity.MEDIUM
        assert base.metadata == {}

    def test_metadata_independence_between_instances(self):
        a = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        b = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        a.metadata["key"] = "value"
        assert b.metadata == {}

    @pytest.mark.parametrize("confidence", [-0.1, 1.01, 2.5, -1.0])
    def test_confidence_must_stay_within_bounds(self, confidence):
        with pytest.raises(ValidationError):
            PatternBase(
                pattern_type=PatternType.TAG_CORRELATION,
                confidence=confidence,
            )

    def test_confidence_accepts_boundary_values(self):
        low = PatternBase(pattern_type=PatternType.TAG_CORRELATION, confidence=0.0)
        high = PatternBase(pattern_type=PatternType.TAG_CORRELATION, confidence=1.0)
        assert low.confidence == 0.0
        assert high.confidence == 1.0


# =============================================================================
# TaskDurationPattern Tests
# =============================================================================


class TestTaskDurationPattern:
    """Tests for TaskDurationPattern subclass."""

    def _build(self, **overrides: Any) -> TaskDurationPattern:
        defaults = {
            "min_duration": 0.5,
            "max_duration": 10.0,
            "avg_duration": 4.2,
            "median_duration": 3.5,
            "std_deviation": 1.1,
        }
        defaults.update(overrides)
        return TaskDurationPattern(**defaults)

    def test_default_pattern_type_is_task_duration(self):
        pat = self._build()
        assert pat.pattern_type == PatternType.TASK_DURATION

    def test_required_duration_fields_must_be_provided(self):
        with pytest.raises(ValidationError):
            TaskDurationPattern()  # type: ignore[call-arg]

    def test_optional_fields_default_to_none_or_empty(self):
        pat = self._build()
        assert pat.repository is None
        assert pat.task_type is None
        assert pat.priority_range is None
        assert pat.sample_count == 0
        assert pat.sample_task_ids == []

    def test_priority_range_accepts_tuple(self):
        pat = self._build(priority_range=("low", "high"))
        assert pat.priority_range == ("low", "high")

    def test_sample_task_ids_can_be_populated(self):
        pat = self._build(sample_count=3, sample_task_ids=["a", "b", "c"])
        assert pat.sample_count == 3
        assert pat.sample_task_ids == ["a", "b", "c"]


# =============================================================================
# BlockerPattern Tests
# =============================================================================


class TestBlockerPattern:
    """Tests for BlockerPattern subclass."""

    def test_required_fields(self):
        pat = BlockerPattern(
            blocker_keyword="dependency",
            blocker_category="technical",
        )
        assert pat.pattern_type == PatternType.BLOCKER_RECURRING
        assert pat.blocker_keyword == "dependency"
        assert pat.blocker_category == "technical"
        assert pat.occurrence_count == 0
        assert pat.affected_task_ids == []
        assert pat.affected_repositories == []
        assert pat.resolution_suggestions == []
        assert pat.avg_resolution_time_hours is None

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            BlockerPattern(blocker_keyword="dep")  # type: ignore[call-arg]

    def test_full_construction_with_resolution_data(self):
        pat = BlockerPattern(
            blocker_keyword="circular",
            blocker_category="dependency",
            occurrence_count=4,
            affected_task_ids=["t1", "t2"],
            affected_repositories=["repo-a"],
            resolution_suggestions=["refactor"],
            avg_resolution_time_hours=2.5,
        )
        assert pat.occurrence_count == 4
        assert pat.avg_resolution_time_hours == 2.5
        assert pat.affected_task_ids == ["t1", "t2"]


# =============================================================================
# CompletionSequencePattern Tests
# =============================================================================


class TestCompletionSequencePattern:
    """Tests for CompletionSequencePattern subclass."""

    def test_required_fields(self):
        pat = CompletionSequencePattern(
            sequence=["plan", "code", "review"],
            completion_probability=0.85,
        )
        assert pat.pattern_type == PatternType.COMPLETION_SEQUENCE
        assert pat.sequence == ["plan", "code", "review"]
        assert pat.sequence_count == 0
        assert pat.completion_probability == 0.85
        assert pat.leads_to_completion is True
        assert pat.repository is None

    def test_missing_required_completion_probability(self):
        with pytest.raises(ValidationError):
            CompletionSequencePattern(sequence=["plan"])  # type: ignore[call-arg]

    @pytest.mark.parametrize("prob", [-0.01, 1.5])
    def test_completion_probability_out_of_range(self, prob):
        with pytest.raises(ValidationError):
            CompletionSequencePattern(sequence=["x"], completion_probability=prob)

    def test_completion_probability_boundary(self):
        zero = CompletionSequencePattern(sequence=["x"], completion_probability=0.0)
        one = CompletionSequencePattern(sequence=["x"], completion_probability=1.0)
        assert zero.completion_probability == 0.0
        assert one.completion_probability == 1.0


# =============================================================================
# DetectedPattern Tests
# =============================================================================


class TestDetectedPattern:
    """Tests for DetectedPattern model and serialisation."""

    def _make(self) -> DetectedPattern:
        base = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        return DetectedPattern(
            pattern_type=PatternType.TAG_CORRELATION,
            pattern_data=base,
            confidence_score=0.75,
        )

    def test_default_id_is_eight_chars(self):
        d = self._make()
        assert isinstance(d.id, str)
        assert len(d.id) == 8

    def test_detected_at_is_datetime(self):
        d = self._make()
        assert isinstance(d.detected_at, datetime)

    def test_to_dict_serialises_expected_keys(self):
        d = self._make()
        result = d.to_dict()
        assert set(result.keys()) >= {
            "id",
            "pattern_type",
            "pattern_data",
            "detected_at",
            "source_task_ids",
            "confidence_score",
        }
        # pattern_type should serialise as its string value
        assert result["pattern_type"] == "tag_correlation"
        # detected_at should serialise to ISO string
        assert isinstance(result["detected_at"], str)
        datetime.fromisoformat(result["detected_at"])

    def test_to_dict_preserves_pattern_data_dump(self):
        d = self._make()
        result = d.to_dict()
        assert isinstance(result["pattern_data"], dict)
        assert result["pattern_data"]["pattern_type"] == "tag_correlation"

    def test_confidence_score_validation(self):
        base = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        with pytest.raises(ValidationError):
            DetectedPattern(
                pattern_type=PatternType.TAG_CORRELATION,
                pattern_data=base,
                confidence_score=1.5,
            )

    def test_embedding_defaults_to_none(self):
        d = self._make()
        assert d.embedding is None

    def test_embedding_accepts_float_list(self):
        base = PatternBase(pattern_type=PatternType.TAG_CORRELATION)
        d = DetectedPattern(
            pattern_type=PatternType.TAG_CORRELATION,
            pattern_data=base,
            confidence_score=0.5,
            embedding=[0.1, 0.2, 0.3],
        )
        assert d.embedding == [0.1, 0.2, 0.3]

    def test_unique_ids_across_instances(self):
        a = self._make()
        b = self._make()
        # uuid-derived prefixes are highly unlikely to collide
        assert a.id != b.id


# =============================================================================
# PatternMatch Tests
# =============================================================================


class TestPatternMatch:
    """Tests for PatternMatch model."""

    def test_basic_construction(self):
        match = PatternMatch(
            pattern_id="pid-1",
            pattern_type=PatternType.BLOCKER_RECURRING,
            match_score=0.9,
        )
        assert match.pattern_id == "pid-1"
        assert match.pattern_type == PatternType.BLOCKER_RECURRING
        assert match.match_score == 0.9
        assert match.matched_keywords == []
        assert match.matched_features == {}
        assert match.predictions == {}

    @pytest.mark.parametrize("score", [-0.5, 1.5, 100])
    def test_match_score_validation(self, score):
        with pytest.raises(ValidationError):
            PatternMatch(
                pattern_id="pid",
                pattern_type=PatternType.TASK_DURATION,
                match_score=score,
            )

    def test_matched_at_is_datetime(self):
        match = PatternMatch(
            pattern_id="x",
            pattern_type=PatternType.TASK_DURATION,
            match_score=0.5,
        )
        assert isinstance(match.matched_at, datetime)


# =============================================================================
# PatternAnalysisResult Tests
# =============================================================================


class TestPatternAnalysisResult:
    """Tests for PatternAnalysisResult model and to_dict serialisation."""

    def test_default_construction(self):
        result = PatternAnalysisResult()
        assert result.task_count == 0
        assert result.duration_patterns == []
        assert result.blocker_patterns == []
        assert result.sequence_patterns == []
        assert result.avg_task_duration_hours == 0.0
        assert result.blocker_rate == 0.0
        assert result.completion_rate == 0.0
        assert isinstance(result.analyzed_at, datetime)

    def test_to_dict_structure(self):
        result = PatternAnalysisResult(task_count=5, completion_rate=0.4)
        d = result.to_dict()
        assert d["task_count"] == 5
        assert "duration_patterns" in d
        assert "blocker_patterns" in d
        assert "sequence_patterns" in d
        assert "statistics" in d
        assert d["statistics"]["completion_rate"] == 0.4
        # analyzed_at must be ISO string
        datetime.fromisoformat(d["analyzed_at"])

    def test_to_dict_includes_nested_pattern_dumps(self):
        duration = TaskDurationPattern(
            min_duration=1.0,
            max_duration=5.0,
            avg_duration=3.0,
            median_duration=3.0,
            std_deviation=0.5,
        )
        blocker = BlockerPattern(blocker_keyword="k", blocker_category="c")
        sequence = CompletionSequencePattern(sequence=["a", "b"], completion_probability=0.7)
        result = PatternAnalysisResult(
            task_count=10,
            duration_patterns=[duration],
            blocker_patterns=[blocker],
            sequence_patterns=[sequence],
        )
        d = result.to_dict()
        assert len(d["duration_patterns"]) == 1
        assert len(d["blocker_patterns"]) == 1
        assert len(d["sequence_patterns"]) == 1
        assert d["duration_patterns"][0]["min_duration"] == 1.0
        assert d["blocker_patterns"][0]["blocker_keyword"] == "k"
        assert d["sequence_patterns"][0]["completion_probability"] == 0.7

    def test_statistics_block_keys(self):
        result = PatternAnalysisResult()
        stats = result.to_dict()["statistics"]
        assert set(stats.keys()) == {
            "avg_task_duration_hours",
            "blocker_rate",
            "completion_rate",
        }
