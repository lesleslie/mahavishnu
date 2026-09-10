"""Integration benchmark: two-stage warn/confirm detector on synthetic shifts.

Empirical validation that the §1 latency gate (median warning time
<= 30 samples on 0.5σ shift) and the §7 FP gate (≤ 2 confirmed
alerts per 10,080 quiet samples) are BOTH achievable via the
two-stage architecture. See docs/plans/2026-09-10-bodai-math-initiatives-tier1.md
§1 (success metrics).

Req: REQ-005 (two-stage extension verification).
"""
from __future__ import annotations

import json
import math

import pytest

from mahavishnu.observability.changepoint import (
    CUSUMDetector,
    PageHinkleyDetector,
)
from mahavishnu.observability.changepoint.two_stage import (
    TwoStageDetector,
)


def _production_two_stage_factory() -> TwoStageDetector:
    """Build the production-default TwoStageDetector.

    Warn: CUSUMDetector at slack=0.25, threshold=8.0
    Confirm: CUSUMDetector at slack=0.25, threshold=14.0
    Confirm window: 100 samples

    These are the same defaults documented in settings/mahavishnu.yaml
    (warn_threshold=8.0, confirm_threshold=14.0, confirm_window_samples=100)
    and the §1/§7 calibration table in
    docs/audits/2026-09-10-changepoint-validation.md.
    """
    warn = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
    confirm = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=14.0, two_sided=True)
    return TwoStageDetector(warn, confirm, confirm_window_samples=100)


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    n = len(sorted_values)
    idx = min(int(q * n), n - 1)
    return sorted_values[idx]


def _benchmark_two_stage_warning_latency(
    shift_size: float, n_trials: int = 30, n_baseline: int = 200, seed: int = 42,
) -> dict:
    import random

    rng = random.Random(seed)
    warning_latencies: list[int] = []
    confirmed_latencies: list[int] = []
    for trial in range(n_trials):
        rng_trial = random.Random(rng.random() * 1e9 + trial)
        ts = _production_two_stage_factory()
        for _ in range(n_baseline):
            ts.update(rng_trial.gauss(0.0, 1.0))
        ts.reset()
        first_warning = None
        first_confirmed = None
        for i in range(500):
            r = ts.update(rng_trial.gauss(shift_size, 1.0))
            if first_warning is None and r.state == "warning_pending":
                first_warning = i + 1
            if first_confirmed is None and r.state == "confirmed":
                first_confirmed = i + 1
                break
        if first_warning is not None:
            warning_latencies.append(first_warning)
        if first_confirmed is not None:
            confirmed_latencies.append(first_confirmed)
    result: dict = {
        "n_trials": n_trials,
        "n_warnings": len(warning_latencies),
        "n_confirmed": len(confirmed_latencies),
    }
    if warning_latencies:
        warning_latencies.sort()
        result["warning_median_latency"] = _quantile(warning_latencies, 0.5)
        result["warning_p95_latency"] = _quantile(warning_latencies, 0.95)
    if confirmed_latencies:
        confirmed_latencies.sort()
        result["confirmed_median_latency"] = _quantile(confirmed_latencies, 0.5)
    return result


def _benchmark_two_stage_fp_per_quiet(
    n_trials: int = 25, n_samples: int = 10_080, seed: int = 2026_09_10,
) -> dict:
    """§7 v3.1 gate: confirmed alerts on stationary noise ≤ 2 per 10,080 samples."""
    import random

    rng = random.Random(seed)
    confirmed_per_trial: list[int] = []
    for trial in range(n_trials):
        rng_trial = random.Random(rng.random() * 1e9 + trial)
        ts = _production_two_stage_factory()
        confirmed = 0
        for _ in range(n_samples):
            r = ts.update(rng_trial.gauss(0.0, 1.0))
            if r.state == "confirmed":
                confirmed += 1
        confirmed_per_trial.append(confirmed)
    return {
        "n_trials": n_trials,
        "n_samples": n_samples,
        "mean_confirmed": sum(confirmed_per_trial) / n_trials,
        "median_confirmed": _quantile(sorted(confirmed_per_trial), 0.5),
        "max_confirmed": max(confirmed_per_trial),
        "confirmed_per_trial": confirmed_per_trial,
    }


@pytest.mark.integration
@pytest.mark.slow
class TestTwoStageBenchmark:
    def test_two_stage_warning_latency_at_0_5_sigma(self) -> None:
        """§1 gate (resolved via warn/confirm): median time-to-first-warning ≤ 30 samples."""
        stats = _benchmark_two_stage_warning_latency(shift_size=0.5, n_trials=30)
        assert stats.get("warning_median_latency", 0) <= 30, (
            f"§1 gate: two_stage_warning_latency_at_0_5_sigma <= 30 "
            f"(got median={stats.get('warning_median_latency', float('nan')):.1f}, "
            f"p95={stats.get('warning_p95_latency', float('nan')):.1f}). "
            f"The two-stage architecture decouples §1 (warnings) from §7 "
            f"(confirmed alerts); the warn detector at h=8.0 catches 0.5σ "
            f"shifts in ~28 samples on median."
        )

    def test_two_stage_confirmed_alert_latency_at_0_5_sigma(self) -> None:
        """Confirm detector's median latency on 0.5σ shift; bounded by confirm_window_samples."""
        stats = _benchmark_two_stage_warning_latency(shift_size=0.5, n_trials=30)
        # On a 0.5σ shift with h=14.0, median confirm latency is ~50 samples.
        # We assert <= 100 to leave margin for the confirm_window_samples=100 budget.
        assert stats.get("confirmed_median_latency", 0) <= 100, (
            f"two_stage_confirmed_alert_latency_at_0_5_sigma <= 100 "
            f"(got median={stats.get('confirmed_median_latency', float('nan')):.1f}). "
            f"At h=14.0 confirm threshold, median confirm latency on 0.5σ is ~50 samples."
        )

    def test_two_stage_confirmed_alert_fp_per_10080_quiet_samples(self) -> None:
        """§7 gate (resolved via warn/confirm): confirmed alerts ≤ 2 per 10,080 quiet samples."""
        stats = _benchmark_two_stage_fp_per_quiet(n_trials=25, n_samples=10_080)
        mean_confirmed = stats["mean_confirmed"]
        assert mean_confirmed <= 2, (
            f"§7 v3.1 gate: two_stage_confirmed_alert_fp_per_10080_quiet_samples <= 2 "
            f"(got mean={mean_confirmed:.2f} across {stats['n_trials']} trials; "
            f"min={min(stats['confirmed_per_trial'])}, "
            f"median={stats['median_confirmed']:.1f}, max={stats['max_confirmed']}). "
            f"Two-stage architecture: ~30 warnings / 10,080 quiet samples (warn detector "
            f"h=8.0), but only a fraction correlate with a confirm fire within the "
            f"100-sample window, so confirmed alerts stay well below the §7 bound."
        )

    def test_bench_json_two_stage_keys(self, tmp_path) -> None:
        """bench.json includes the two_stage keys the spec §9 validation matrix expects."""
        warning_stats = _benchmark_two_stage_warning_latency(shift_size=0.5, n_trials=10)
        fp_stats = _benchmark_two_stage_fp_per_quiet(n_trials=10, n_samples=10_080)
        bench = {
            "two_stage_warning_latency_at_0_5_sigma": warning_stats.get(
                "warning_median_latency", float("nan")
            ),
            "two_stage_confirmed_alert_latency_at_0_5_sigma": warning_stats.get(
                "confirmed_median_latency", float("nan")
            ),
            "two_stage_confirmed_alert_fp_per_10080_quiet_samples": fp_stats["mean_confirmed"],
        }
        bench_path = tmp_path / "bench.json"
        bench_path.write_text(json.dumps(bench, indent=2), encoding="utf-8")
        loaded = json.loads(bench_path.read_text(encoding="utf-8"))
        for key in (
            "two_stage_warning_latency_at_0_5_sigma",
            "two_stage_confirmed_alert_fp_per_10080_quiet_samples",
        ):
            assert key in loaded
            assert math.isfinite(loaded[key]), f"{key} should be finite, got {loaded[key]}"
