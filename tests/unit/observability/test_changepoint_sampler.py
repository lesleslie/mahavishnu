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
        from mahavishnu.core.config import ChangepointConfig

        cfg = ChangepointConfig()
        # Phase 6 default is OFF (False); the YAML in
        # settings/mahavishnu.yaml carries the Phase 8 promotion
        # (enabled: true). A fresh operator that omits the YAML
        # block gets the safe default.
        assert cfg.enabled is False
        assert cfg.target_metric == "pool_queue_depth"
        assert cfg.detector == "cusum"
        assert cfg.slack == 0.25
        assert cfg.threshold == 8.0
        assert cfg.reference_detector == "three_sigma"
        assert cfg.sampler_cadence_seconds == 60.0

    def test_can_be_overridden(self) -> None:
        from mahavishnu.core.config import ChangepointConfig

        cfg = ChangepointConfig(
            enabled=True,
            target_metric="workflow_duration_p99",
            detector="page_hinkley",
            slack=0.5,
            threshold=5.0,
            reference_detector="none",
            sampler_cadence_seconds=30.0,
        )
        assert cfg.enabled is True
        assert cfg.target_metric == "workflow_duration_p99"
        assert cfg.detector == "page_hinkley"
        assert cfg.reference_detector == "none"

    def test_extra_forbid_still_enforced(self) -> None:
        from pydantic import ValidationError

        from mahavishnu.core.config import ChangepointConfig

        with pytest.raises(ValidationError):
            ChangepointConfig(changepoint_unknown_field=True)  # type: ignore[call-arg]

    def test_top_level_on_mahavishnu_settings(self) -> None:
        """ChangepointConfig is a top-level sibling on MahavishnuSettings.

        Env-var contract: MAHAVISHNU_CHANGEPOINT__<FIELD>.
        """
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()
        # Top-level block: settings.changepoint is a ChangepointConfig,
        # NOT nested under pools. (Audit CRITICAL #5 / HIGH #7 fix.)
        assert hasattr(settings, "changepoint")
        assert settings.changepoint.__class__.__name__ == "ChangepointConfig"
        # YAML in this checkout promotes Phase 8 (enabled: true); a
        # fresh setup with the YAML line removed gets the False default.
        assert settings.changepoint.enabled is True
        assert settings.changepoint.target_metric == "pool_queue_depth"

    def test_target_mean_defaults_to_zero(self) -> None:
        """target_mean defaults to 0.0; valid only for normalized metrics.

        Raw-count metrics like pool_queue_depth require operators to
        set an explicit baseline. See docs/runbooks/mahavishnu-drift-detection.md.
        """
        from mahavishnu.core.config import ChangepointConfig

        cfg = ChangepointConfig()
        assert cfg.target_mean == 0.0
        assert cfg.target_mean_auto is False
        assert cfg.target_mean_auto_window == 60

    def test_target_mean_can_be_set_explicitly(self) -> None:
        """Operators set target_mean explicitly for raw-count metrics."""
        from mahavishnu.core.config import ChangepointConfig

        cfg = ChangepointConfig(target_mean=4.0)
        assert cfg.target_mean == 4.0

    def test_target_mean_auto_window_validated(self) -> None:
        """target_mean_auto_window must be in [10, 7200]."""
        from pydantic import ValidationError

        from mahavishnu.core.config import ChangepointConfig

        with pytest.raises(ValidationError):
            ChangepointConfig(target_mean_auto_window=5)  # too small

        # 7200 is the upper bound (matches sampler default max_samples).
        cfg = ChangepointConfig(target_mean_auto_window=7200)
        assert cfg.target_mean_auto_window == 7200

    def test_target_mean_passed_to_detector(self) -> None:
        """target_mean from config is forwarded to CUSUMDetector/PageHinkleyDetector.

        Without this, the detector accumulates on baseline traffic for
        raw-count metrics and fires within ~30 samples. (Math CRITICAL #4.)
        """
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(
            enabled=True,
            target_mean=4.0,  # explicit baseline for raw-count pool_queue_depth
            detector="cusum",
        )
        mgr.logger = None  # type: ignore[attr-defined]
        detector = mgr._get_or_create_changepoint_detector()
        assert detector.target_mean == 4.0

    def test_target_mean_auto_overrides_explicit(self) -> None:
        """target_mean_auto=True with a warm sampler uses the rolling baseline."""
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(
            enabled=True,
            target_mean=0.0,
            target_mean_auto=True,
            target_mean_auto_window=10,
            target_metric="test_metric",
        )
        mgr.logger = None  # type: ignore[attr-defined]
        # Feed 50 samples around value=7.0
        sampler = mgr._get_metric_sampler()
        for _ in range(50):
            sampler.observe("test_metric", 7.0)
        detector = mgr._get_or_create_changepoint_detector()
        # Rolling baseline ≈ 7.0 (not the explicit 0.0)
        assert detector.target_mean == pytest.approx(7.0, abs=0.01)


# ---------------------------------------------------------------------------
# ObservabilityManager drift detection methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestObservabilityManagerDriftDetection:
    def _build_manager(self, **kwargs):  # type: ignore[no-untyped-def]
        """Build an ObservabilityManager with a minimal MahavishnuSettings stub."""
        from mahavishnu.core.observability import ObservabilityManager
        from mahavishnu.core.config import (
            ChangepointConfig,
            MahavishnuSettings,
        )

        changepoint_cfg = ChangepointConfig(**kwargs)
        # Build a settings-like object that exposes the top-level
        # .changepoint sibling (per C5 fix; not under pools).
        class _StubSettings:
            pass

        settings = _StubSettings()
        settings.changepoint = changepoint_cfg
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
        # Inject a config with changepoint.enabled=False
        from mahavishnu.core.config import ChangepointConfig

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=False)  # explicitly off
        mgr.logger = None  # type: ignore[attr-defined]
        result = mgr._evaluate_change_point("pool_queue_depth", 5.0)
        assert result.detected is False
        assert result.score == 0.0

    def test_changepoint_enabled_first_observation_below_threshold(self) -> None:
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True)  # explicit opt-in
        mgr.logger = None  # type: ignore[attr-defined]
        # First observation at value 5 against target 0 with
        # slack 0.25 threshold 8 → CUSUM accumulates
        # (5 - 0 - 0.25) = 4.75. Below threshold 8 → not detected.
        result = mgr._evaluate_change_point("pool_queue_depth", 5.0)
        assert result.detected is False
        assert result.samples_since_reset == 1
        # Default-off (Phase 6) returns a synthetic no-op result
        mgr_default = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub2:
            pass

        mgr_default.config = _Stub2()
        mgr_default.config.changepoint = ChangepointConfig()  # default-off
        mgr_default.logger = None  # type: ignore[attr-defined]
        r2 = mgr_default._evaluate_change_point("pool_queue_depth", 5.0)
        assert r2.detected is False
        # When disabled, samples_since_reset stays 0 (no detector
        # state updated) — distinct from the "ran but didn't fire"
        # path above.
        assert r2.samples_since_reset == 0

    def test_changepoint_fires_on_persistent_shift(self) -> None:
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True)  # explicit opt-in
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
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True)
        mgr.logger = None  # type: ignore[attr-defined]
        result = mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        # Not enough samples for a meaningful z-score
        assert result.detected is False
        assert result.window_mean != result.window_mean  # NaN check
        assert math.isnan(result.window_mean)

    def test_3sigma_with_constant_data_does_not_fire(self) -> None:
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True)
        mgr.logger = None  # type: ignore[attr-defined]
        for _ in range(10):
            mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        result = mgr._evaluate_3sigma("pool_queue_depth", 5.0)
        # Constant series → window_std = 0 → not detected
        assert result.detected is False
        assert result.window_std == 0.0

    def test_3sigma_with_spike_fires(self) -> None:
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True)
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
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(reference_detector="none")
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
        from mahavishnu.core.config import ChangepointConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(sampler_cadence_seconds=60.0)
        mgr.logger = None  # type: ignore[attr-defined]
        assert getattr(mgr, "_metric_sampler", None) is None
        s = mgr._get_metric_sampler()
        assert s is not None
        assert s.cadence_seconds == 60.0
        # Second call returns the same instance (cached)
        assert mgr._get_metric_sampler() is s
        # Cadence overrides via ChangepointConfig.sampler_cadence_seconds
        mgr2 = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub2:
            pass

        mgr2.config = _Stub2()
        mgr2.config.changepoint = ChangepointConfig(sampler_cadence_seconds=10.0)
        mgr2.logger = None  # type: ignore[attr-defined]
        assert mgr2._get_metric_sampler().cadence_seconds == 10.0


# ---------------------------------------------------------------------------
# C4 + C6: drift counter, gauge, and span attributes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftCounterEmission:
    """C6: drift_detected_total counter + detector_age_samples gauge.

    The §7 stage-1 gate depends on the drift_detected_total counter.
    Without registration, the gate is unenforced even though the
    detector logic runs. See audit CRITICAL #1 / observability #1 / HIGH #10.
    """

    def _build_manager(self):  # type: ignore[no-untyped-def]
        from mahavishnu.core.observability import ObservabilityManager
        from mahavishnu.core.config import ChangepointConfig

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True, threshold=4.0)
        mgr.logger = None  # type: ignore[attr-defined]
        return mgr

    def test_observability_manager_has_drift_counter(self) -> None:
        """After construction, the manager must have a drift_detected_counter."""
        mgr = self._build_manager()
        # Call the real init to wire fallback instruments
        mgr._init_fallback_components()
        assert hasattr(mgr, "drift_detected_counter")
        assert mgr.drift_detected_counter is not None

    def test_observability_manager_has_detector_age_gauge(self) -> None:
        mgr = self._build_manager()
        mgr._init_fallback_components()
        assert hasattr(mgr, "detector_age_gauge")
        assert mgr.detector_age_gauge is not None

    def test_drift_counter_called_on_persistent_shift(self) -> None:
        """A persistent shift must invoke drift_detected_counter.add(1)."""
        from mahavishnu.core.observability import ObservabilityManager
        from mahavishnu.core.config import ChangepointConfig

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True, threshold=4.0)
        mgr.logger = None  # type: ignore[attr-defined]
        mgr._init_fallback_components()

        # Spy on the counter
        added = []

        class _Spy:
            def add(self, amount, attributes=None):
                added.append((amount, attributes))

        mgr.drift_detected_counter = _Spy()  # type: ignore[assignment]

        # Drive a persistent shift
        detected = False
        for _ in range(100):
            r = mgr._evaluate_change_point("pool_queue_depth", 1.0)
            if r.detected:
                detected = True
                break
        assert detected, "Detector should fire on a 1.0-sigma shift"
        assert len(added) >= 1, "drift_detected_counter.add was never called"
        # Verify the labels are correct
        amount, attrs = added[0]
        assert amount == 1
        assert attrs["metric_name"] == "pool_queue_depth"
        assert "cusum" in attrs["detector"].lower() or "page" in attrs["detector"].lower()
        assert attrs["severity"] in {"minor", "moderate", "critical"}

    def test_drift_span_attributes_complete(self) -> None:
        """C4: OTel span carries all 16 spec attributes."""
        from unittest.mock import patch

        from mahavishnu.core.observability import ObservabilityManager
        from mahavishnu.core.config import ChangepointConfig

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.changepoint = ChangepointConfig(enabled=True, threshold=4.0)
        mgr.logger = None  # type: ignore[attr-defined]
        mgr._init_fallback_components()

        # Capture span attributes via a spy tracer
        captured_attrs: list[dict] = []

        class _SpySpan:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def set_attribute(self, key, value):
                captured_attrs.append((key, value))

        class _SpyTracer:
            def start_as_current_span(self, name, attributes=None):
                captured_attrs.extend(list((attributes or {}).items()))
                return _SpySpan()

        mgr.tracer = _SpyTracer()  # type: ignore[assignment]

        # Patch OTEL_AVAILABLE so the OTel branch in _on_drift_detected
        # executes even in CI where the OTel SDK is not installed.
        with patch("mahavishnu.core.observability.OTEL_AVAILABLE", True):
            # Drive a drift
            for _ in range(200):
                r = mgr._evaluate_change_point("pool_queue_depth", 1.0)
                if r.detected:
                    break

        # Inspect captured attributes
        attr_keys = {k for k, _ in captured_attrs}
        # Spec §6 Phase 6 Integration Contract — 16 attributes
        required = {
            "metric_name",
            "detector",
            "score_high",
            "score_low",
            "score",
            "threshold",
            "samples_since_reset",
            "direction",
            "severity",
            "current_value",
            "baseline_mean",
            "baseline_std",
            "host",
            "instance_id",
            "trace_id",
            "runbook_url",
        }
        missing = required - attr_keys
        assert not missing, f"Missing OTel span attributes: {missing}"


# ---------------------------------------------------------------------------
# C6: ALLOWED_LABEL_KEYS includes the new drift labels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftLabelAllowlist:
    """C6: metric_name, detector, severity labels must be allowlisted.

    Without these entries, the counter emission in _on_drift_detected
    raises ValueError("Unknown metric label keys: ...") at runtime
    and the counter is silently dropped. See audit HIGH #24 / obs HIGH #1.
    """

    def test_metric_name_allowed(self) -> None:
        from mahavishnu.observability.metrics import _ALLOWED_LABEL_KEYS

        assert "metric_name" in _ALLOWED_LABEL_KEYS

    def test_detector_allowed(self) -> None:
        from mahavishnu.observability.metrics import _ALLOWED_LABEL_KEYS

        assert "detector" in _ALLOWED_LABEL_KEYS

    def test_severity_allowed(self) -> None:
        from mahavishnu.observability.metrics import _ALLOWED_LABEL_KEYS

        assert "severity" in _ALLOWED_LABEL_KEYS
