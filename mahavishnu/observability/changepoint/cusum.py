"""CUSUM (Cumulative Sum) change-point detector.

# Implements: REQ-004

The :class:`CUSUMDetector` is the canonical Cumulative Sum detector
of Page (1954) / Brook & Evans (1972). It is a sequential test that
accumulates the deviation of observations from a target mean; when
the cumulative deviation exceeds a threshold the process mean is
declared to have shifted.

Mathematical reference:

* Page, E. S. (1954). Continuous inspection schemes. *Biometrika*
  41(1/2), 141-154.
* Brook, D. & Evans, D. A. (1972). An approach to the probability
  distribution of CUSUM run length. *Biometrika* 59(3), 539-549.
* Hawkins, D. M. (1993). *Cumulative Sum Control Charts: A Quality
  Control Tool*. Chapter 2 (design of CUSUM for known mean).

The two-sided variant tracks high-side and low-side accumulators
in parallel and reports whichever has the larger score. The
``slack`` parameter is the classical ``k`` (allowance / slack
parameter, in units of standard deviation of the target
distribution); ``threshold`` is the classical ``h`` (decision
interval).

A natural parameter pair for "ARL₀ ≥ 10,000 on a 0.5-σ shift" is
``slack=0.5, threshold=5.0`` (one-sided) or
``slack=0.25, threshold=8.0`` (two-sided, default in
``settings/mahavishnu.yaml``). The exact ARL₀ for these settings
is verified empirically in Phase 7's benchmark test
(``tests/integration/observability/test_changepoint_benchmark.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Protocol, runtime_checkable

from mahavishnu.core.errors import ChangePointError

# ClassVar-style runtime type aliases (PEP 613-compatible as a string).
DirectionT = Literal["up", "down", "unknown"]


def _is_finite(x: float) -> bool:
    """Return True iff ``x`` is a real, finite number (int or float, not bool, not NaN, not Inf).

    Round-4 general/safety (MEDIUM-1): accept ints. YAML operators
    naturally write ``target_mean: 0`` for zero-centered metrics; the
    prior ``isinstance(x, float)`` check rejected ``0`` (an int) with
    ChangePointError. Pandas/numpy numeric coercion means this matters
    whenever a config field is loaded as an int.
    """
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True, slots=True)
class ChangePointResult:
    """Result of a single ``update()`` call on a change-point detector.

    Attributes:
        detected: True iff the detector fired on this observation.
        score_high: cumulative high-side score (one-sided and two-sided).
        score_low: cumulative low-side score (one-sided and two-sided).
        score: ``max(score_high, score_low)`` for two-sided; the
            single accumulator value for one-sided. Reported
            alongside ``detected`` so operators can see the
            detection margin (how far past the threshold the score
            reached).
        threshold: the configured decision interval ``h``.
        samples_since_reset: number of observations since the last
            reset. Used for the OTel span attribute so operators
            can distinguish "shift detected at sample 1" from
            "shift detected at sample 2000".
        direction: "up" for upward mean shift, "down" for downward,
            "unknown" for the one-sided / not-yet-fired case.
    """

    detected: bool
    score_high: float
    score_low: float
    score: float
    threshold: float
    samples_since_reset: int
    direction: DirectionT


@runtime_checkable
class ChangePointDetector(Protocol):
    """Protocol for online change-point detectors.

    The protocol is :func:`runtime_checkable` so callers can write
    ``isinstance(detector, ChangePointDetector)`` for the integration
    contract in :class:`mahavishnu.core.observability.ObservabilityManager`.
    """

    def update(self, observation: float) -> ChangePointResult:
        """Feed one observation; return the detection result.

        Args:
            observation: a finite real number. NaN/Inf raises.

        Returns:
            A :class:`ChangePointResult`. The detector's internal
            state is updated; subsequent calls reflect cumulative
            evidence from the full stream.
        """
        ...

    def reset(self) -> None:
        """Reset the detector to its initial state.

        Called by the integration layer after a confirmed detection
        so the detector is ready for the next shift.
        """
        ...


class CUSUMDetector:
    """Two-sided or one-sided CUSUM change-point detector.

    Args:
        target_mean: ``mu_0``, the in-control process mean.
        slack: ``k``, the allowance parameter in standard
            deviation units. Typical values: 0.5σ for one-sided
            (detects 1-σ shifts with sub-100-sample latency),
            0.25σ for two-sided (detects 0.5-σ shifts; default
            in ``settings/mahavishnu.yaml``).
        threshold: ``h``, the decision interval. Larger
            ``threshold`` reduces false-positive rate at the
            cost of detection latency. The default ``8.0`` at
            ``slack=0.25`` (two-sided) yields ARL₀ ≈ 10,000 per
            the Brook & Evans 1972 tables.
        two_sided: if True, run high and low CUSUM in parallel and
            report whichever score is larger. Default True (the
            Phase 6 spec calls for two-sided detection).

    Req: REQ-004
    """  # req: REQ-004

    __slots__ = (
        "_samples_since_reset",
        "_score_high",
        "_score_low",
        "slack",
        "target_mean",
        "threshold",
        "two_sided",
    )

    def __init__(
        self,
        target_mean: float,
        slack: float,
        threshold: float,
        two_sided: bool = True,
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
        self.target_mean: float = target_mean
        self.slack: float = slack
        self.threshold: float = threshold
        self.two_sided: bool = two_sided
        self._score_high: float = 0.0
        self._score_low: float = 0.0
        self._samples_since_reset: int = 0

    def update(self, observation: float) -> ChangePointResult:
        """Feed one observation; return the detection result.

        Updates the high-side accumulator ``S_H`` and (in two-sided
        mode) the low-side accumulator ``S_L``:

        .. math::

            S_H \\leftarrow \\max(0, S_H + (x_t - \\mu_0 - k))
            S_L \\leftarrow \\max(0, S_L + (\\mu_0 - k - x_t))

        The score in two-sided mode is ``max(S_H, S_L)``; the
        direction is "up" if ``S_H >= S_L`` and "down" otherwise.
        Detection fires when the score first crosses ``threshold``.

        Args:
            observation: a finite real number. NaN/Inf raises
                :class:`ChangePointError`.
        """
        if not _is_finite(observation):
            raise ChangePointError(
                f"observation must be a finite float, got {observation!r}",
                details={"observation": observation},
            )
        # High side
        high_increment = observation - self.target_mean - self.slack
        new_high = self._score_high + high_increment
        self._score_high = max(0.0, new_high)

        # Low side (only in two-sided mode; mirror the slack so a
        # symmetric shift yields a symmetric score).
        if self.two_sided:
            low_increment = self.target_mean - self.slack - observation
            new_low = self._score_low + low_increment
            self._score_low = max(0.0, new_low)
        else:
            # In one-sided mode we still report the low side as
            # the mirror value (zero) so the result dataclass
            # is uniformly populated.
            self._score_low = 0.0

        self._samples_since_reset += 1
        score = max(self._score_high, self._score_low) if self.two_sided else self._score_high
        detected = score >= self.threshold
        if self.two_sided:
            direction: DirectionT = "up" if self._score_high >= self._score_low else "down"
        else:
            direction = "up" if detected else "unknown"

        return ChangePointResult(
            detected=detected,
            score_high=self._score_high,
            score_low=self._score_low,
            score=score,
            threshold=self.threshold,
            samples_since_reset=self._samples_since_reset,
            direction=direction,
        )

    def reset(self) -> None:
        """Reset the detector's internal accumulators and sample count.

        Called by the integration layer after a confirmed
        detection so the next shift starts from a clean baseline.
        """
        self._score_high = 0.0
        self._score_low = 0.0
        self._samples_since_reset = 0
