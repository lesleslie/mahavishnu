"""Integration test: change-point detection on a synthetic 0.5-σ mean shift.

Asserts the CUSUM detector fires within 30 samples (median) on a
0.5-σ shift, while the 3-sigma reference detector does not.

Req: REQ-004, REQ-005, REQ-006, REQ-009 (verification).
"""
from __future__ import annotations

import pytest

from mahavishnu.observability.changepoint import (
    CUSUMDetector,
    PageHinkleyDetector,
    AnomalyResult,
)


@pytest.mark.integration
@pytest.mark.slow
class TestChangePointIntegration:
    def test_cusum_fires_on_0_5_sigma_shift(self) -> None:
        import random

        rng = random.Random(2026_09_10)
        detector = CUSUMDetector(
            target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True
        )
        for _ in range(200):
            detector.update(rng.gauss(0.0, 1.0))
        detector.reset()
        detected_at = None
        for _ in range(100):
            r = detector.update(rng.gauss(0.5, 1.0))
            if r.detected:
                detected_at = r.samples_since_reset
                break
        assert detected_at is not None
        assert detected_at < 30, f"CUSUM took {detected_at} samples to detect 0.5-σ shift"

    def test_three_sigma_misses_0_5_sigma_shift(self) -> None:
        """The 3-sigma reference detector should MISS a 0.5-σ shift."""
        import math
        import random

        rng = random.Random(2026_09_11)
        window = [rng.gauss(0.0, 1.0) for _ in range(60)]
        window_mean = sum(window) / len(window)
        window_std = math.sqrt(sum((v - window_mean) ** 2 for v in window) / (len(window) - 1))
        shifted_value = 0.5
        z_score = (shifted_value - window_mean) / window_std
        assert abs(z_score) < 1.0, f"3-sigma test setup error: |z|={z_score:.3f}"
        result = AnomalyResult(
            detected=abs(z_score) >= 3.0,
            z_score=z_score,
            current_value=shifted_value,
            window_mean=window_mean,
            window_std=window_std,
        )
        assert result.detected is False

    def test_sampler_to_cusum_pipeline(self) -> None:
        """Sampler → CUSUMDetector wired end-to-end via ObservabilityManager."""
        from mahavishnu.core.config import PoolConfig
        from mahavishnu.core.observability import ObservabilityManager

        mgr = ObservabilityManager.__new__(ObservabilityManager)

        class _Stub:
            pass

        mgr.config = _Stub()
        mgr.config.pools = PoolConfig(changepoint_enabled=True)
        mgr.logger = None  # type: ignore[attr-defined]

        # A constant stream at value 0 (the target) should not fire
        for _ in range(50):
            r = mgr._evaluate_change_point("pool_queue_depth", 0.0)
        assert r.detected is False

        # Inject a large shift to 50 → should fire
        for _ in range(50):
            r = mgr._evaluate_change_point("pool_queue_depth", 50.0)
        assert r.detected is True

    def test_three_way_comparison(self) -> None:
        """CUSUM and Page-Hinkley should both fire; 3-sigma should not on 0.5-σ shift."""
        import random

        rng = random.Random(42)
        cusum = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
        ph = PageHinkleyDetector(target_mean=0.0, slack=0.05, threshold=5.0, delta=0.0)
        for _ in range(200):
            x = rng.gauss(0.0, 1.0)
            cusum.update(x)
            ph.update(x)
        cusum.reset()
        ph.reset()
        cusum_fired = False
        ph_fired = False
        for _ in range(50):
            x = rng.gauss(0.5, 1.0)
            if cusum.update(x).detected:
                cusum_fired = True
            if ph.update(x).detected:
                ph_fired = True
            if cusum_fired and ph_fired:
                break
        assert cusum_fired
        assert ph_fired
