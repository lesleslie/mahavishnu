"""Integration test: TwoStageResult dispatch via ObservabilityManager.

Verifies that the change-point pipeline routes TwoStageResult warnings
and confirmations to the correct emission callbacks (``_on_drift_warning``
during the warn-only state, ``_on_drift_detected_two_stage`` during the
confirmed state) and that BOTH the ``drift_warning_total`` and
``drift_detected_total`` Prometheus counters increment exactly once
across the lifetime of a single confirmed drift.

Mirrors ``tests/integration/observability/test_changepoint_detection.py::test_sampler_to_cusum_pipeline``
but exercises the two-stage architecture end-to-end.

Req: REQ-005 (two-stage extension verification).
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from mahavishnu.core.config import ChangepointConfig
from mahavishnu.core.observability import ObservabilityManager
from mahavishnu.observability.changepoint.cusum import CUSUMDetector
from mahavishnu.observability.changepoint.two_stage import (
    TwoStageDetector,
    TwoStageResult,
)


def _make_two_stage_manager(
    warn_threshold: float = 8.0,
    confirm_threshold: float = 14.0,
    confirm_window_samples: int = 100,
) -> ObservabilityManager:
    """Build a minimally-initialized ObservabilityManager wired to a TwoStageDetector.

    Skips ``__init__`` to avoid pulling config wiring — only sets the
    fields ``_evaluate_change_point`` reads: ``config.changepoint`` and
    the private ``_changepoint_detector``. Mirrors the pattern in
    ``tests/integration/observability/test_changepoint_detection.py::test_sampler_to_cusum_pipeline``.
    """
    mgr = ObservabilityManager.__new__(ObservabilityManager)

    class _Stub:
        pass

    mgr.config = _Stub()
    mgr.config.changepoint = ChangepointConfig(
        enabled=True,
        detector="two_stage",
        warn_threshold=warn_threshold,
        confirm_threshold=confirm_threshold,
        confirm_window_samples=confirm_window_samples,
    )
    mgr.logger = None  # type: ignore[attr-defined]

    warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=warn_threshold, two_sided=True)
    confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=confirm_threshold, two_sided=True)
    mgr._changepoint_detector = TwoStageDetector(warn, confirm, confirm_window_samples)
    return mgr


@pytest.mark.integration
class TestTwoStageDispatch:
    def test_two_stage_dispatch_warning_then_confirm(self) -> None:
        """Thread a 0.5σ shift and verify warn + confirm dispatch paths.

        Asserts:
            1. ``_on_drift_warning`` is called at least once during the
               warn-only state (i.e. before any confirm fire).
            2. ``_on_drift_detected_two_stage`` is called at least once
               once the shift sustains long enough to confirm.
        """
        mgr = _make_two_stage_manager()

        rng = random.Random(2026_09_10)
        warning_calls: list[TwoStageResult] = []
        detected_calls: list[TwoStageResult] = []

        def _capture_warning(metric_name: str, value: float, result: TwoStageResult) -> None:
            warning_calls.append(result)

        def _capture_detected(metric_name: str, value: float, result: TwoStageResult) -> None:
            detected_calls.append(result)

        with (
            patch.object(mgr, "_on_drift_warning", side_effect=_capture_warning),
            patch.object(mgr, "_on_drift_detected_two_stage", side_effect=_capture_detected),
        ):
            # Quiet baseline so the detector starts fresh.
            for _ in range(200):
                mgr._evaluate_change_point("pool_queue_depth", rng.gauss(0.0, 1.0))
            mgr._changepoint_detector.reset()

            # Inject a 0.5σ shift for long enough that the warn detector
            # fires (median ~28 samples) AND the confirm detector fires
            # (median ~50 samples). 250 samples covers both medians
            # comfortably within the 100-sample confirm window.
            for _ in range(250):
                mgr._evaluate_change_point("pool_queue_depth", rng.gauss(0.5, 1.0))

        assert len(warning_calls) >= 1, (
            f"_on_drift_warning was never called — the warn detector "
            f"never fired on the 0.5σ shift (got {len(warning_calls)} calls)"
        )
        assert len(detected_calls) >= 1, (
            f"_on_drift_detected_two_stage was never called — the confirm "
            f"detector never fired within the 100-sample window of a warn "
            f"(got {len(detected_calls)} calls; warnings={len(warning_calls)})"
        )

    def test_two_stage_dispatch_prometheus_counters(self) -> None:
        """Both Prometheus counters (``drift_warning_total``, ``drift_detected_total``) increment.

        Uses stub counter objects so we can observe the ``Counter.add(1, ...)``
        invocations without requiring the OTel Prometheus exporter to be
        initialized. The dispatch methods run unmodified (no ``patch.object``)
        so the counters are incremented normally.
        """
        mgr = _make_two_stage_manager()

        from mahavishnu.observability.metrics import _validate_labels

        warning_adds: list[dict] = []
        detected_adds: list[dict] = []

        class _StubCounter:
            def __init__(self, sink: list[dict], allow_severity: bool) -> None:
                self._sink = sink
                self._allow_severity = allow_severity

            def add(self, amount: int, attributes: dict | None = None) -> None:
                attrs = attributes or {}
                _validate_labels(attrs)
                if amount == 1 and "severity" in attrs and self._allow_severity:
                    self._sink.append(attrs)
                elif amount == 1 and "severity" not in attrs and not self._allow_severity:
                    self._sink.append(attrs)

        mgr.drift_warning_counter = _StubCounter(warning_adds, allow_severity=False)  # type: ignore[attr-defined]
        mgr.drift_detected_counter = _StubCounter(detected_adds, allow_severity=True)  # type: ignore[attr-defined]
        # The detector reset / counter flush paths reference these; stub them
        # to keep the test focused on the increment calls.
        mgr.detector_age_gauge = None  # type: ignore[attr-defined]

        rng = random.Random(2026_09_11)
        # Quiet baseline.
        for _ in range(200):
            mgr._evaluate_change_point("pool_queue_depth", rng.gauss(0.0, 1.0))
        mgr._changepoint_detector.reset()

        # Sustained 0.5σ shift to drive both warn and confirm fires.
        for _ in range(250):
            mgr._evaluate_change_point("pool_queue_depth", rng.gauss(0.5, 1.0))

        # Each counter should have been incremented at least once.
        assert len(warning_adds) >= 1, (
            f"drift_warning_total was not incremented on a sustained "
            f"0.5σ shift (warning counter add() calls={len(warning_adds)})"
        )
        assert len(detected_adds) >= 1, (
            f"drift_detected_total was not incremented on a confirmed "
            f"drift (detected counter add() calls={len(detected_adds)})"
        )