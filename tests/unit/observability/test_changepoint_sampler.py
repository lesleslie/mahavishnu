"""Tests for Phase 6: MetricSampler + ObservabilityManager change-point wiring (REQ-005, REQ-006, REQ-009)."""
from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from mahavishnu.observability.changepoint import AnomalyResult
from mahavishnu.observability.sampler import (
    DEFAULT_CADENCE_SECONDS,
    DEFAULT_MAX_SAMPLES,
    MetricSample,
    MetricSampler,
)


# ---------------------------------------------------------------------------
# MetricSample
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetricSample:
    def test_construct(self) -> None:
        s = MetricSample(
            metric="x", ts_monotonic=1.0, ts_wall=datetime(2026, 1, 1, tzinfo=UTC), value=42.0
        )
        assert s.metric == "x"
        assert s.ts_monotonic == 1.0
        assert s.value == 42.0

    def test_is_frozen(self) -> None:
        s = MetricSample(
            metric="x", ts_monotonic=1.0, ts_wall=datetime(2026, 1, 1, tzinfo=UTC), value=1.0
        )
        with pytest.raises((AttributeError, Exception)):
            s.value = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MetricSampler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetricSampler:
    def test_default_cadence(self) -> None:
        s = MetricSampler()
        assert s.cadence_seconds == DEFAULT_CADENCE_SECONDS == 60.0

    def test_default_max_samples(self) -> None:
        s = MetricSampler()
        assert s.max_samples == DEFAULT_MAX_SAMPLES == 7_200

    def test_invalid_cadence_rejected(self) -> None:
        with pytest.raises(ValueError):
            MetricSampler(cadence_seconds=0.0)
        with pytest.raises(ValueError):
            MetricSampler(cadence_seconds=-1.0)

    def test_invalid_max_samples_rejected(self) -> None:
        with pytest.raises(ValueError):
            MetricSampler(max_samples=0)

    def test_observe_returns_sample(self) -> None:
        s = MetricSampler()
        sample = s.observe("pool_queue_depth", 5.0)
        assert isinstance(sample, MetricSample)
        assert sample.metric == "pool_queue_depth"
        assert sample.value == 5.0

    def test_series_grows(self) -> None:
        s = MetricSampler()
        for i in range(10):
            s.observe("m", float(i))
        assert len(s.series("m")) == 10
        assert s.values("m") == [float(i) for i in range(10)]

    def test_nan_dropped_silently(self) -> None:
        s = MetricSampler()
        s.observe("m", float("nan"))
        s.observe("m", 1.0)
        s.observe("m", float("inf"))
        assert s.values("m") == [1.0]

    def test_negative_value_kept(self) -> None:
        """Negative metric values are valid (e.g. temperature, signed diffs)."""
        s = MetricSampler()
        s.observe("m", -1.0)
        s.observe("m", -2.0)
        assert s.values("m") == [-1.0, -2.0]

    def test_ring_buffer_trims_to_max(self) -> None:
        s = MetricSampler(max_samples=5)
        for i in range(10):
            s.observe("m", float(i))
        # Only the last 5 should remain
        assert s.values("m") == [5.0, 6.0, 7.0, 8.0, 9.0]

    def test_per_metric_separation(self) -> None:
        s = MetricSampler()
        s.observe("m1", 1.0)
        s.observe("m2", 2.0)
        s.observe("m1", 11.0)
        assert s.values("m1") == [1.0, 11.0]
        assert s.values("m2") == [2.0]

    def test_clear_specific_metric(self) -> None:
        s = MetricSampler()
        s.observe("m1", 1.0)
        s.observe("m2", 2.0)
        s.clear("m1")
        assert s.values("m1") == []
        assert s.values("m2") == [2.0]

    def test_clear_all(self) -> None:
        s = MetricSampler()
        s.observe("m1", 1.0)
        s.observe("m2", 2.0)
        s.clear()
        assert s.values("m1") == []
        assert s.values("m2") == []

    def test_tick_with_no_source_returns_empty(self) -> None:
        s = MetricSampler()
        assert s.tick() == {}

    def test_tick_with_source_observes_scalars(self) -> None:
        s = MetricSampler(source=lambda: {"a": 1.0, "b": 2.0})
        observed = s.tick()
        assert observed == {"a": 1.0, "b": 2.0}
        assert s.values("a") == [1.0]
        assert s.values("b") == [2.0]

    def test_tick_with_source_walks_subdicts(self) -> None:
        s = MetricSampler(source=lambda: {"workflows": {"wf1": 3.0, "wf2": 4.0}})
        observed = s.tick()
        assert "workflows.wf1" in observed
        assert "workflows.wf2" in observed
        assert s.values("workflows.wf1") == [3.0]


# ---------------------------------------------------------------------------
# Pydantic changepoint config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChangepointConfig:
    def test_defaults(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig()
        assert cfg.changepoint_enabled is False
        assert cfg.changepoint_target_metric == "pool_queue_depth"
        assert cfg.changepoint_detector == "cusum"
        assert cfg.changepoint_slack == 0.25
        assert cfg.changepoint_threshold == 8.0
        assert cfg.changepoint_reference_detector == "three_sigma"
        assert cfg.changepoint_sampler_cadence_seconds == 60.0

    def test_can_be_overridden(self) -> None:
        from mahavishnu.core.config import PoolConfig

        cfg = PoolConfig(
            changepoint_enabled=True,
            changepoint_target_metric="workflow_duration_p99",
            changepoint_detector="page_hinkley",
            changepoint_slack=0.5,
            changepoint_threshold=5.0,
            changepoint_reference_detector="none",
            changepoint_sampler_cadence_seconds=30.0,
        )
        assert cfg.changepoint_enabled is True
        assert cfg.changepoint_target_metric == "workflow_duration_p99"
        assert cfg.changepoint_detector == "page_hinkley"
        assert cfg.changepoint_reference_detector == "none"

    def test_extra_forbid_still_enforced(self) -> None:
        from pydantic import ValidationError

        from mahavishnu.core.config import PoolConfig

        with pytest.raises(ValidationError):
            PoolConfig(changepoint_unknown_field=True)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ObservabilityManager drift detection methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestObservabilityManagerDriftDetection:
    def _build_manager(self, **kwargs):  # type: ignore[no-untyped-def]
        """Build an ObservabilityManager with a minimal MahavishnuSettings stub."""
        from mahavishnu.core.observability import ObservabilityManager
        from mahavishnu.core.config import PoolConfig, MahavishnuSettings

        pools = PoolConfig(**kwargs)
        # Build a settings-like object that exposes .pools
        class _StubSettings:
            pass

        settings = _StubSettings()
        settings.pools = pools
        # ObservabilityConfig and other fields are not exercised in
        # these tests, so we leave them at default.
        try:
            return ObservabilityManager.__new__(ObservabilityManager).__init__(  # type: ignore[attr-defined]
                config=settings,  # type: ignore[arg-type]
            )
        except Exception:
            # __init__ may fail on OTel init in this minimal stub;
            # build directly without calling __init__.
            mgr = ObservabilityManager.__new__(ObservabilityManager)
            mgr.config = settings  # type: ignore[attr-defined]
            mgr.logger = None  # type: ignore[attr-defined]
            return mgr

    def test_changepoint_disabled_returns_noop_result(self) -> None:
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)
        # Inject a config with changepoint_enabled=False
        from mahavishnu.core.config import PoolConfig

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig()  # changepoint_enabled defaults False
        mgr.logger = None  # type: ignore[attr-defined]
        result = mgr._evaluate_change_point("pool_queue_depth", 5.0)
        assert result.detected is False
        assert result.score == 0.0

    def test_changepoint_enabled_with_no_data_returns_noop(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig(changepoint_enabled=True)
        mgr.logger = None  # type: ignore[attr-defined]
        # No data in sampler → target_mean defaults to 0.0
        result = mgr._evaluate_change_point("pool_queue_depth", 5.0)
        # First observation at value 5 against target 0 with
        # slack 0.25 threshold 8 → CUSUM accumulates
        # (5 - 0 - 0.25) = 4.75. Below threshold 8 → not detected.
        assert result.detected is False
        assert result.samples_since_reset == 1

    def test_changepoint_fires_on_persistent_shift(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig(changepoint_enabled=True)
        mgr.logger = None  # type: ignore[attr-defined]
        detected_at = None
        for i in range(200):
            result = mgr._evaluate_change_point("pool_queue_depth", 1.0)
            if result.detected:
                detected_at = result.samples_since_reset
                break
        assert detected_at is not None
        assert detected_at < 100  # Should detect a 1.0-σ shift well under 100 samples

    def test_3sigma_no_data_returns_noop(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig()
        mgr.logger = None  # type: ignore[attr-defined]
        result = mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        # Not enough samples for a meaningful z-score
        assert result.detected is False
        assert result.window_mean != result.window_mean  # NaN check
        assert math.isnan(result.window_mean)

    def test_3sigma_with_constant_data_does_not_fire(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig()
        mgr.logger = None  # type: ignore[attr-defined]
        for _ in range(10):
            mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        result = mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        # Constant series → window_std = 0 → not detected
        assert result.detected is False
        assert result.window_std == 0.0

    def test_3sigma_with_spike_fires(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig()
        mgr.logger = None  # type: ignore[attr-defined]
        # Feed 30 constant values to build a stable window
        for _ in range(30):
            mgr._evaluate_3sigma("pool_queue_depth", 10.0)
        # Inject a >3-σ spike
        result = mgr._evaluate_3sigma("pool_queue_depth", 100.0)
        # The spike is 90 units above mean 10 — when std is small,
        # z-score is well above 3.
        assert result.detected is True
        assert result.z_score > 3.0

    def test_3sigma_disabled_when_reference_none(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig(changepoint_reference_detector="none")
        mgr.logger = None  # type: ignore[attr-defined]
        result = mgr._evaluate_3sigma("pool_queue_depth", 100.0)
        # Reference disabled — no detection, no exception
        assert result.detected is False

    def test_drift_severity_classifier(self) -> None:
        from mahavishnu.core.observability import ObservabilityManager

        assert ObservabilityManager._classify_drift_severity(0, 8) == "minor"
        assert ObservabilityManager._classify_drift_severity(15, 8) == "minor"  # < 16
        assert ObservabilityManager._classify_drift_severity(16, 8) == "moderate"  # >= 2*8
        assert ObservabilityManager._classify_drift_severity(31, 8) == "moderate"
        assert ObservabilityManager._classify_drift_severity(32, 8) == "critical"  # >= 4*8
        assert ObservabilityManager._classify_drift_severity(100, 8) == "critical"

    def test_metric_sampler_lazy_init(self) -> None:
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig()
        mgr.logger = None  # type: ignore[attr-defined]
        assert getattr(mgr, "_metric_sampler", None) is None
        s = mgr._get_metric_sampler()
        assert s is not None
        assert s.cadence_seconds == 60.0
        # Second call returns the same instance (cached)
        assert mgr._get_metric_sampler() is s
