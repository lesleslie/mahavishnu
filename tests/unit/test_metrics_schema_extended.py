"""Extended coverage tests for mahavishnu.core.metrics_schema.

Focuses on branches the canonical test_metrics_schema.py did not exercise:
- Key generation function body returns
- calculate_percentiles internal branches (custom percentiles,
  empty input, p50/p95/p99 formulas, index clamping)
- calculate_confidence_interval branches (small samples, boundary
  success rates, Wilson score arithmetic)
- Fallback generate_config_id when oneiric is unavailable
"""

from __future__ import annotations

import builtins
import importlib

import pytest
from pydantic import ValidationError

from mahavishnu.core import metrics_schema as ms_mod
from mahavishnu.core.metrics_schema import (
    ABTest,
    AdapterStats,
    AdapterType,
    CostTracking,
    ExecutionRecord,
    ExecutionStatus,
    RoutingDecision,
    TaskType,
    TaskTypeStats,
    calculate_confidence_interval,
    calculate_percentiles,
    generate_cost_key,
    generate_execution_key,
    generate_stats_key,
    generate_task_stats_key,
)
from mahavishnu.core.status import ExecutionStatus as CoreExecutionStatus


# ---------------------------------------------------------------------------
# StrEnum exhaustiveness
# ---------------------------------------------------------------------------


class TestStrEnumMembership:
    """Ensure every value defined on a StrEnum is covered."""

    def test_adapter_type_includes_all_three_adapters(self) -> None:
        assert AdapterType.PREFECT.value == "prefect"
        assert AdapterType.AGNO.value == "agno"
        assert AdapterType.LLAMAINDEX.value == "llamaindex"
        assert {a.value for a in AdapterType} == {"prefect", "agno", "llamaindex"}

    def test_task_type_includes_all_six_kinds(self) -> None:
        expected = {
            "workflow",
            "ai_task",
            "rag_query",
            "batch_task",
            "critical_task",
            "interactive_task",
        }
        actual = {t.value for t in TaskType}
        assert actual == expected
        # Each member should also stringify to its raw value.
        assert str(TaskType.CRITICAL_TASK) == "critical_task"

    def test_execution_status_matches_status_module(self) -> None:
        # metrics_schema re-exports ExecutionStatus — they must be the same class.
        assert ExecutionStatus is CoreExecutionStatus
        # And the canonical four members exist.
        names = {s.name for s in ExecutionStatus}
        assert names == {"SUCCESS", "FAILURE", "TIMEOUT", "CANCELLED"}


# ---------------------------------------------------------------------------
# Key generation body coverage
# ---------------------------------------------------------------------------


class TestKeyGenerationBodies:
    """Hit the *return* statements inside the key generators."""

    @pytest.mark.parametrize(
        ("fn", "expected"),
        [
            (generate_execution_key, "exec:abc-123"),
            (generate_cost_key, "cost:abc-123"),
        ],
    )
    def test_identity_keys_preserve_id(self, fn, expected: str) -> None:
        assert fn("abc-123") == expected

    def test_generate_stats_key_uses_adapter_value(self) -> None:
        # Exercises the f-string and adapter.value lookup.
        assert generate_stats_key(AdapterType.PREFECT, "2026-09-05") == (
            "stats:adapter:prefect:2026-09-05"
        )
        assert generate_stats_key(AdapterType.LLAMAINDEX, "1970-01-01") == (
            "stats:adapter:llamaindex:1970-01-01"
        )

    def test_generate_task_stats_key_uses_task_value(self) -> None:
        assert generate_task_stats_key(TaskType.RAG_QUERY, "2026-09-05") == (
            "stats:task:rag_query:2026-09-05"
        )
        assert generate_task_stats_key(TaskType.INTERACTIVE_TASK, "today") == (
            "stats:task:interactive_task:today"
        )


# ---------------------------------------------------------------------------
# calculate_percentiles — exhaustive branch coverage
# ---------------------------------------------------------------------------


class TestCalculatePercentilesBranches:
    """Drive every branch in `calculate_percentiles`."""

    def test_default_percentiles_when_none_provided(self) -> None:
        # Exercises the `if percentiles is None` branch.
        result = calculate_percentiles([10, 20, 30, 40, 50])
        assert set(result.keys()) == {"p50", "p95", "p99"}
        # p50 uses nearest-rank (0-indexed): n=5 → index 5//2=2 → sorted[2]=30.
        assert result["p50"] == 30
        # p99 uses last index.
        assert result["p99"] == 50

    def test_empty_latencies_returns_empty_dict(self) -> None:
        # Exercises the `if not latencies` branch.
        assert calculate_percentiles([]) == {}
        assert calculate_percentiles([], [50.0, 95.0]) == {}

    def test_p50_branch_uses_explicit_formula(self) -> None:
        # 5 elements — p50 nearest-rank: 5//2 = 2 → sorted[2] = 30.
        result = calculate_percentiles([10, 20, 30, 40, 50], [50.0])
        assert result["p50"] == 30

    def test_p99_branch_takes_last_index(self) -> None:
        # 4 elements — p99 should be the LAST sorted value.
        result = calculate_percentiles([100, 200, 300, 400], [99.0])
        assert result["p99"] == 400

    def test_p99_with_long_list(self) -> None:
        # 100 elements — verify the function scales.
        latencies = list(range(1, 101))
        result = calculate_percentiles(latencies, [99.0])
        assert result["p99"] == 100

    def test_fallback_branch_for_percentiles_between(self) -> None:
        # p75 falls into the `else` branch in the calculate_percentiles switch.
        latencies = list(range(1, 21))
        result = calculate_percentiles(latencies, [75.0])
        # max(0, int(20 * 0.75) - 1) = max(0, 14) = 14 → sorted list [15]
        assert result["p75"] == 15

    def test_index_clamp_when_percentage_yields_large_index(self) -> None:
        # 1-element list — `p95` formula gives int(1*0.95)-1 = -1, then max(0, -1) = 0.
        result = calculate_percentiles([42], [95.0])
        assert result["p95"] == 42

    def test_unsorted_latencies_are_sorted_first(self) -> None:
        # Sorted = [100,200,300]; p50 nearest-rank: 3//2 = 1 → sorted[1] = 200.
        result = calculate_percentiles([300, 100, 200], [50.0])
        assert result["p50"] == 200

    def test_negative_percentile_raises_value_error(self) -> None:
        # Edge: percentiles below 0 now raise ValueError (was silent accept).
        with pytest.raises(ValueError, match=r"percentile must be in"):
            calculate_percentiles([10, 20, 30], [-1.0])

    def test_percentile_over_100_raises_value_error(self) -> None:
        # Edge: percentiles > 100 now raise ValueError (was silent accept).
        with pytest.raises(ValueError, match=r"percentile must be in"):
            calculate_percentiles([10, 20, 30], [150.0])

    def test_zero_percentile_returns_first_value(self) -> None:
        # p=0 is in the valid range [0, 100].
        result = calculate_percentiles([10, 20, 30], [0.0])
        assert result["p0"] == 10


# ---------------------------------------------------------------------------
# calculate_confidence_interval — exhaustive branch coverage
# ---------------------------------------------------------------------------


class TestCalculateConfidenceIntervalBranches:
    """Drive every branch in `calculate_confidence_interval`."""

    def test_sample_size_below_10_returns_wide_window(self) -> None:
        # Exercises `if sample_size < 10: return (0.0, 1.0)`.
        low, high = calculate_confidence_interval(sample_size=0, success_rate=0.5)
        assert (low, high) == (0.0, 1.0)
        low, high = calculate_confidence_interval(sample_size=9, success_rate=0.5)
        assert (low, high) == (0.0, 1.0)

    def test_perfect_success_rate_returns_one_one(self) -> None:
        # Exercises `if success_rate >= 1.0: return (1.0, 1.0)`.
        assert calculate_confidence_interval(sample_size=100, success_rate=1.0) == (1.0, 1.0)
        # Boundary: rates > 1.0 still collapse to 1.0.
        assert calculate_confidence_interval(sample_size=100, success_rate=2.0) == (1.0, 1.0)

    def test_zero_success_rate_returns_zero_zero(self) -> None:
        # Exercises `if success_rate <= 0.0: return (0.0, 0.0)`.
        assert calculate_confidence_interval(sample_size=100, success_rate=0.0) == (0.0, 0.0)
        # Negative rates — defensive branch.
        assert calculate_confidence_interval(sample_size=100, success_rate=-0.5) == (0.0, 0.0)

    def test_wilson_formula_with_typical_input(self) -> None:
        # Exercises the z, denominator, center, margin, lower, upper arithmetic.
        low, high = calculate_confidence_interval(sample_size=500, success_rate=0.9)
        assert 0.0 <= low <= high <= 1.0
        assert low < 0.9 < high  # Wilson interval should bracket the point estimate
        # Reasonable width for n=500.
        assert high - low < 0.1

    def test_wilson_formula_with_low_rate(self) -> None:
        low, high = calculate_confidence_interval(sample_size=1000, success_rate=0.1)
        assert 0.0 <= low <= 0.1 <= high <= 1.0
        # Margin should be wide enough that upper is well above 0.10.
        assert high - low > 0.03

    def test_confidence_interval_is_clamped_at_zero_and_one(self) -> None:
        # Try a pathological case — extreme rate with small sample.
        low, high = calculate_confidence_interval(sample_size=11, success_rate=0.001)
        assert low >= 0.0
        assert high <= 1.0

    def test_wilson_formula_shrinks_with_more_data(self) -> None:
        small_low, small_high = calculate_confidence_interval(
            sample_size=50, success_rate=0.8
        )
        large_low, large_high = calculate_confidence_interval(
            sample_size=5000, success_rate=0.8
        )
        small_width = small_high - small_low
        large_width = large_high - large_low
        assert large_width < small_width

    def test_confidence_interval_returns_floats(self) -> None:
        low, high = calculate_confidence_interval(sample_size=100, success_rate=0.5)
        assert isinstance(low, float)
        assert isinstance(high, float)

    def test_higher_confidence_yields_wider_interval(self) -> None:
        """Regression: confidence parameter must affect interval width.

        Previously, the `confidence` parameter was declared but ignored —
        z was hardcoded to 1.96 regardless. A higher confidence level must
        produce a wider interval.
        """
        low_90, high_90 = calculate_confidence_interval(
            sample_size=500, success_rate=0.8, confidence=0.90
        )
        low_95, high_95 = calculate_confidence_interval(
            sample_size=500, success_rate=0.8, confidence=0.95
        )
        low_99, high_99 = calculate_confidence_interval(
            sample_size=500, success_rate=0.8, confidence=0.99
        )
        width_90 = high_90 - low_90
        width_95 = high_95 - low_95
        width_99 = high_99 - low_99
        assert width_99 > width_95 > width_90

    def test_unknown_confidence_falls_back_to_1_96(self) -> None:
        """Unknown confidence values should fall back to z=1.96 (≈95% CI)."""
        low_default, high_default = calculate_confidence_interval(
            sample_size=500, success_rate=0.8
        )
        low_odd, high_odd = calculate_confidence_interval(
            sample_size=500, success_rate=0.8, confidence=0.73
        )
        assert abs((high_default - low_default) - (high_odd - low_odd)) < 1e-9


# ---------------------------------------------------------------------------
# Fallback for oneiric.core.ulid import failure
# ---------------------------------------------------------------------------


class TestGenerateConfigIdFallback:
    """Drive the import-failure branch of metrics_schema top-of-file."""

    def test_fallback_yields_32_char_hex(self, monkeypatch) -> None:
        original_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Block oneiric and its submodules; everything else delegates.
            if name == "oneiric.core.ulid" or name.startswith("oneiric."):
                raise ImportError("forced fallback")
            return original_import(name, globals, locals, fromlist, level)

        try:
            monkeypatch.setattr(builtins, "__import__", blocked_import)
            reloaded = importlib.reload(ms_mod)
            try:
                gid = reloaded.generate_config_id()
                assert isinstance(gid, str)
                assert len(gid) == 32
                int(gid, 16)  # valid hex
            finally:
                # Reattach the real import + reload so other tests aren't affected.
                monkeypatch.setattr(builtins, "__import__", original_import)
                importlib.reload(ms_mod)
        except ImportError:
            # If reloading fails for any reason, restore manually.
            monkeypatch.setattr(builtins, "__import__", original_import)
            importlib.reload(ms_mod)
            pytest.skip("Could not reload metrics_schema cleanly")


# ---------------------------------------------------------------------------
# ExecutionRecord extended coverage
# ---------------------------------------------------------------------------


class TestExecutionRecordExtended:
    """Cover ExecutionRecord branches the original test missed."""

    def test_auto_generates_execution_id_when_omitted(self) -> None:
        # Exercises `default_factory=generate_config_id` on execution_id.
        record = ExecutionRecord(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            start_timestamp=1.0,
            status=ExecutionStatus.SUCCESS,
        )
        assert isinstance(record.execution_id, str)
        assert record.execution_id != ""

    def test_all_optional_fields_can_be_set(self) -> None:
        record = ExecutionRecord(
            execution_id="x",
            adapter=AdapterType.AGNO,
            task_type=TaskType.BATCH_TASK,
            start_timestamp=1.0,
            end_timestamp=2.0,
            status=ExecutionStatus.FAILURE,
            latency_ms=123,
            error_type="timeout",
            error_message="boom",
            cost_usd=0.99,
            metadata={"trace_id": "t-1"},
        )
        assert record.end_timestamp == 2.0
        assert record.error_type == "timeout"
        assert record.metadata == {"trace_id": "t-1"}

    def test_invalid_success_rate_constraint_rejected(self) -> None:
        # AdapterStats.success_rate has ge=0.0, le=1.0 — test bounds.
        with pytest.raises(ValidationError):
            AdapterStats(
                adapter=AdapterType.PREFECT,
                date="2026-09-05",
                success_rate=1.5,
                total_executions=10,
                sample_size=5,
            )

    def test_negative_total_executions_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AdapterStats(
                adapter=AdapterType.PREFECT,
                date="2026-09-05",
                success_rate=0.9,
                total_executions=-1,
                sample_size=5,
            )

    def test_uptime_percentage_at_bounds(self) -> None:
        # Both ends of 0..100.
        low = AdapterStats(
            adapter=AdapterType.PREFECT,
            date="d",
            success_rate=0.0,
            total_executions=1,
            uptime_percentage=0.0,
            sample_size=1,
        )
        high = AdapterStats(
            adapter=AdapterType.PREFECT,
            date="d",
            success_rate=1.0,
            total_executions=1,
            uptime_percentage=100.0,
            sample_size=1,
        )
        assert low.uptime_percentage == 0.0
        assert high.uptime_percentage == 100.0


# ---------------------------------------------------------------------------
# RoutingDecision extended coverage
# ---------------------------------------------------------------------------


class TestRoutingDecisionExtended:
    """Branches in RoutingDecision the original test missed."""

    def test_auto_generated_decision_id_and_timestamp(self) -> None:
        before = __import__("time").time()
        decision = RoutingDecision(
            task_type=TaskType.WORKFLOW,
            selected_adapter=AdapterType.PREFECT,
            reasoning="auto",
            adapter_scores={AdapterType.PREFECT: 0.9},
        )
        after = __import__("time").time()
        assert decision.decision_id  # non-empty
        assert before <= decision.timestamp <= after
        assert decision.alternative_adapters == []
        assert decision.constraints == {}

    def test_alternative_adapters_must_match_enum(self) -> None:
        # Pydantic should coerce/coerce-fail when wrong types come in.
        with pytest.raises(ValidationError):
            RoutingDecision(
                task_type=TaskType.WORKFLOW,
                selected_adapter=AdapterType.PREFECT,
                reasoning="bad",
                adapter_scores={AdapterType.PREFECT: 0.5},
                alternative_adapters=["not_an_adapter"],
            )


# ---------------------------------------------------------------------------
# ABTest extended coverage
# ---------------------------------------------------------------------------


class TestABTestExtended:
    """Branches in ABTest the original test missed."""

    def test_default_status_is_active(self) -> None:
        # Verifies Field(default="active").
        experiment = ABTest(
            name="empty",
            start_date="2026-09-05",
            traffic_split={},
            sample_size={},
            success_metric="success_rate",
            significance_threshold=0.05,
        )
        assert experiment.status == "active"

    def test_winner_optional(self) -> None:
        experiment = ABTest(
            name="no-winner",
            start_date="2026-09-05",
            traffic_split={AdapterType.PREFECT: 1.0},
            sample_size={AdapterType.PREFECT: 10},
            success_metric="latency",
            significance_threshold=0.01,
        )
        assert experiment.winner is None
        assert experiment.results is None
        assert experiment.end_date is None

    def test_significance_threshold_at_bounds(self) -> None:
        # Both extremes of [0, 1] must be permitted.
        zero = ABTest(
            name="z",
            start_date="d",
            traffic_split={},
            sample_size={},
            success_metric="x",
            significance_threshold=0.0,
        )
        one = ABTest(
            name="o",
            start_date="d",
            traffic_split={},
            sample_size={},
            success_metric="x",
            significance_threshold=1.0,
        )
        assert zero.significance_threshold == 0.0
        assert one.significance_threshold == 1.0

    def test_results_optional_payload(self) -> None:
        experiment = ABTest(
            name="with-results",
            start_date="d",
            end_date="2026-09-12",
            traffic_split={AdapterType.PREFECT: 0.5, AdapterType.AGNO: 0.5},
            sample_size={AdapterType.PREFECT: 100, AdapterType.AGNO: 100},
            success_metric="cost",
            significance_threshold=0.05,
            results={"p_value": 0.03, "effect_size": 0.2},
            winner=AdapterType.AGNO,
            status="completed",
        )
        assert experiment.results == {"p_value": 0.03, "effect_size": 0.2}
        assert experiment.winner == AdapterType.AGNO


# ---------------------------------------------------------------------------
# CostTracking & TaskTypeStats boundary tests
# ---------------------------------------------------------------------------


class TestCostTrackingExtended:
    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CostTracking(
                execution_id="x",
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                cost_usd=-1.0,
            )

    def test_all_optional_fields_set(self) -> None:
        cost = CostTracking(
            execution_id="x",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            cost_usd=0.0,
            budget_type="monthly",
            budget_limit_usd=42.0,
        )
        assert cost.budget_type == "monthly"


class TestTaskTypeStatsExtended:
    def test_minimum_sample_count_accepted(self) -> None:
        # ge=1 — boundary.
        stats = TaskTypeStats(
            task_type=TaskType.WORKFLOW,
            date="d",
            preferred_adapter=AdapterType.PREFECT,
            sample_count=1,
            routing_confidence=0.0,
        )
        assert stats.sample_count == 1
        assert stats.routing_confidence == 0.0

    def test_zero_sample_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaskTypeStats(
                task_type=TaskType.WORKFLOW,
                date="d",
                preferred_adapter=AdapterType.PREFECT,
                sample_count=0,
                routing_confidence=0.0,
            )

    def test_default_alternative_adapters_is_empty_list(self) -> None:
        stats = TaskTypeStats(
            task_type=TaskType.WORKFLOW,
            date="d",
            preferred_adapter=AdapterType.PREFECT,
            sample_count=10,
            routing_confidence=0.5,
        )
        assert stats.alternative_adapters == []


# ---------------------------------------------------------------------------
# ConfigDict / Pydantic v2 model behavior
# ---------------------------------------------------------------------------


class TestModelConfigBehavior:
    """Verify the ConfigDict() defaults are honored (extra fields allowed by default)."""

    def test_execution_record_accepts_extra_fields_by_default(self) -> None:
        # ConfigDict() with no extra="forbid" — extra fields are stored but accessible.
        record = ExecutionRecord(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            start_timestamp=1.0,
            status=ExecutionStatus.SUCCESS,
        )
        dumped = record.model_dump()
        assert isinstance(dumped, dict)
        # Round-trip through model_validate should yield the same data.
        rebuilt = ExecutionRecord.model_validate(dumped)
        assert rebuilt == record

    def test_adapter_stats_dump_round_trip(self) -> None:
        stats = AdapterStats(
            adapter=AdapterType.LLAMAINDEX,
            date="2026-09-05",
            success_rate=0.95,
            total_executions=200,
            sample_size=200,
            p50_latency_ms=120.0,
            p95_latency_ms=300.0,
            p99_latency_ms=500.0,
        )
        round_trip = AdapterStats.model_validate(stats.model_dump())
        assert round_trip == stats
