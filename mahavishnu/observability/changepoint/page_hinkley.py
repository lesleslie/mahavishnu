"""Page-Hinkley sequential change-point test.

# Implements: REQ-004

The :class:`PageHinkleyDetector` is the online-quadratic variant of
CUSUM. The detector tracks the running mean of observations and a
cumulative deviation from the mean; the test fires when the
cumulative deviation first exceeds the threshold.

Mathematical reference:

* Page, E. S. (1954). Continuous inspection schemes. *Biometrika*
  41(1/2), 141-154.
* Hinkley, D. V. (1971). Inference about the change-point from
  cumulative sum tests. *Biometrika* 58(3), 509-523.

The Page-Hinkley test is the closest sequential test to the
classical CUSUM in asymptotic behavior, but the formulation in
terms of a running mean makes it more robust to gradual shifts
and slightly slower to respond to abrupt spikes. In the Phase 6
integration the operator can select CUSUM (default) or
Page-Hinkley via the ``detector`` config field; the Phase 7
benchmark report measures the difference.

The ``delta`` parameter is the minimum detectable shift
magnitude (not the post-change mean). Setting ``delta > 0``
discounts small fluctuations that are smaller than ``delta``
from the target mean; this reduces false-positive rate at the
cost of missed-shift sensitivity for very small shifts.
"""

from __future__ import annotations

from mahavishnu.core.errors import ChangePointError
from mahavishnu.observability.changepoint.cusum import (
    ChangePointResult,
    DirectionT,
    _is_finite,
)


class PageHinkleyDetector:
    """Two-sided Page-Hinkley change-point test.

    Args:
        target_mean: ``mu_0``, the in-control process mean.
        slack: the detection slack in standard deviation units.
            Controls the trade-off between false-positive rate and
            detection latency. Typical values: 0.1-0.5.
        threshold: the decision interval. Larger values reduce
            false positives at the cost of latency.
        delta: minimum detectable shift magnitude; cumulative
            deviation smaller than ``delta`` is floored to 0
            (Page-Hinkley's classical discount).

    Req: REQ-004
    """  # req: REQ-004

    __slots__ = (
        "_cumulative_deviation_high",
        "_cumulative_deviation_low",
        "_running_mean",
        "_samples_since_reset",
        "delta",
        "slack",
        "target_mean",
        "threshold",
    )

    def __init__(
        self,
        target_mean: float,
        slack: float,
        threshold: float,
        delta: float = 0.0,
    ) -> None:
        if not _is_finite(target_mean):
            raise ChangePointError(
                f"target_mean must be a finite float, got {target_mean!r}",
                details={"target_mean": target_mean},
            )
        if not _is_finite(slack) or slack < 0.0:
            raise ChangePointError(
                f"slack must be a non-negative finite float, got {slack!r}",
                details={"slack": slack},
            )
        if not _is_finite(threshold) or threshold <= 0.0:
            raise ChangePointError(
                f"threshold must be a positive finite float, got {threshold!r}",
                details={"threshold": threshold},
            )
        if not _is_finite(delta) or delta < 0.0:
            raise ChangePointError(
                f"delta must be a non-negative finite float, got {delta!r}",
                details={"delta": delta},
            )
        self.target_mean: float = target_mean
        self.slack: float = slack
        self.threshold: float = threshold
        self.delta: float = delta
        # S-6 (round-2 review): track high and low deviations
        # independently so the detector fires on downward shifts
        # too. The prior single-accumulator design only detected
        # upward shifts because negative deviations were floored
        # by ``-delta`` instead of accumulating symmetrically.
        self._cumulative_deviation_high: float = 0.0
        self._cumulative_deviation_low: float = 0.0
        self._running_mean: float = 0.0
        self._samples_since_reset: int = 0

    def update(self, observation: float) -> ChangePointResult:
        """Feed one observation; return the detection result.

        Two-sided Page-Hinkley: tracks the high-side and low-side
        cumulative deviations independently. The test fires when
        ``max(high, low)`` first exceeds ``threshold``. The
        ``direction`` attribute reports which side fired
        (``up`` / ``down`` / ``unknown``).
        """
        if not _is_finite(observation):
            raise ChangePointError(
                f"observation must be a finite float, got {observation!r}",
                details={"observation": observation},
            )

        # Update running mean incrementally (Welford-style would
        # be slightly more numerically stable, but the simple
        # running mean is correct for Page-Hinkley's design).
        n = self._samples_since_reset + 1
        self._running_mean = self._running_mean + (observation - self._running_mean) / n

        # High-side (upward) cumulative deviation: positive when
        # observation exceeds target by more than slack+delta.
        # Negative deviations contribute 0 to the high side.
        high_increment = (observation - self.target_mean) - self.slack - self.delta
        self._cumulative_deviation_high += max(0.0, high_increment)

        # Low-side (downward) cumulative deviation: positive when
        # observation is below target by more than slack+delta.
        # Positive deviations contribute 0 to the low side. The
        # mirror of the high side: subtract (target - slack - delta).
        low_increment = (self.target_mean - observation) - self.slack - self.delta
        self._cumulative_deviation_low += max(0.0, low_increment)

        self._samples_since_reset += 1

        score_high = self._cumulative_deviation_high
        score_low = self._cumulative_deviation_low
        # Combined score is the larger of the two tails (the
        # "peak" of the cumulative deviation).
        score = max(score_high, score_low)
        detected = score >= self.threshold

        # Direction is "up" if the high side fired, "down" if the
        # low side fired, "unknown" if neither has fired yet.
        if not detected:
            direction: DirectionT = "unknown"
        elif score_high >= score_low:
            direction = "up"
        else:
            direction = "down"

        return ChangePointResult(
            detected=detected,
            score_high=score_high,
            score_low=score_low,
            score=score,
            threshold=self.threshold,
            samples_since_reset=self._samples_since_reset,
            direction=direction,
        )

    def reset(self) -> None:
        """Reset the detector's accumulators and sample count."""
        self._cumulative_deviation_high = 0.0
        self._cumulative_deviation_low = 0.0
        self._running_mean = 0.0
        self._samples_since_reset = 0


# Runtime-checkable Protocol conformance: PageHinkleyDetector exposes
# the same `update`/`reset` shape as ChangePointDetector, so it
# satisfies the protocol implicitly. The integration layer in
# :class:`mahavishnu.core.observability.ObservabilityManager` does
# not need an explicit registration.
