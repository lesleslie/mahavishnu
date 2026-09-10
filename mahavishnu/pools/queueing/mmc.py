"""M/M/c queueing model for Mahavishnu pool routing.

# Implements: REQ-001

The :class:`MmcQueue` class fits M/M/c parameters from observed
inter-arrival and service times and produces expected-wait-time
estimates using either the Kingman heavy-traffic approximation or
the exact M/M/c Erlang-C formula. Both formulas require ``rho < 1``;
:func:`safe_expected_wait_time` is the router-friendly variant that
returns :data:`math.inf` past a configurable utilization cap so a
router can use it as a "do not route here" guardrail.

Mathematical references:

* Gross, D. & Harris, C. M. *Fundamentals of Queueing Theory* (4th ed.).
* Harchol-Balter, M. *Performance Modeling and Design of Computer
  Systems*, Chapter 32 (M/M/c).
* Kingman, G. F. C. (1961). The single server queue in heavy traffic.
  *Proc. Cambridge Philos. Soc.* 57, 902-904.

Notes:

* M/M/c assumes Poisson arrivals (exponential inter-arrival times)
  and exponential service times. Real Mahavishnu traffic is closer
  to bursty/hyperexponential; the Kingman formula degrades
  gracefully under coefficient-of-variation deviation (the formula
  is a function of ``(CV_a^2 + CV_s^2)/2``), but the validation
  report in ``docs/audits/2026-09-10-queueing-validation.md``
  documents the per-shift-size error budget.
* For ``c = 1`` the Erlang-C formula reduces to the closed-form
  M/M/1 result ``W_q = rho / (mu * (1 - rho))``; the implementation
  uses the same general code path for any ``c >= 1``.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Literal

from mahavishnu.core.errors import QueueingModelError


# Default utilization cap used by :func:`safe_expected_wait_time` when
# the caller does not pass an explicit cap. Chosen so that a single
# pool saturating at 95% utilization still has bounded wait time;
# beyond this cap the router is told to back off via ``inf``.
DEFAULT_UTILIZATION_CAP = 0.95


def _is_finite(x: float) -> bool:
    """Return True iff ``x`` is a real, finite float (not NaN, not Inf)."""
    return isinstance(x, float) and math.isfinite(x)


def _erlang_c_probability(num_workers: int, rho: float) -> float:
    """Return ``P(wait)`` for M/M/c at utilization ``rho``.

    This is the Erlang-C formula:

    .. math::

        P(wait) = \\frac{(c \\rho)^c / (c! (1 - \\rho))}
                       {\\sum_{k=0}^{c-1} (c \\rho)^k / k! +
                        (c \\rho)^c / (c! (1 - \\rho))}

    The numerator and denominator use the same recurrence-friendly
    computation so we avoid catastrophic cancellation in
    ``(1 - rho)`` for ``rho`` close to 1.
    """
    c = num_workers
    c_rho = c * rho
    # Build the Poisson-like sum up to and including the c-1 term,
    # then add the c-th term (which is the same form the numerator
    # uses, divided by (1 - rho)).
    sum_k = 0.0
    term = 1.0  # (c*rho)^0 / 0!
    for k in range(c):
        sum_k += term
        term *= c_rho / (k + 1)
    # term at this point is (c*rho)^c / c!
    numerator = term / (1.0 - rho)
    denominator = sum_k + numerator
    return numerator / denominator


def _expected_wait_time_kingman(rho: float, service_rate: float) -> float:
    """Return ``W_q`` using the Kingman heavy-traffic approximation.

    For M/M/c with Poisson arrivals and exponential service, both
    coefficients of variation equal 1, so the Kingman formula
    simplifies to:

    .. math::

        W_q \\approx \\frac{\\rho}{1 - \\rho} \\cdot \\frac{1}{\\mu}

    The :class:`MmcQueue` router uses this as the default because
    the computation is O(1) and the bound is tight in heavy traffic
    (``rho`` close to 1). For small ``c`` and moderate ``rho`` the
    Erlang-C formula is preferred.
    """
    return (rho / (1.0 - rho)) * (1.0 / service_rate)


def _expected_wait_time_erlang_c(
    num_workers: int, rho: float, service_rate: float,
) -> float:
    """Return ``W_q`` using the exact M/M/c Erlang-C formula.

    .. math::

        W_q = \\frac{P(\\text{wait})}{c \\mu - \\lambda}
            = \\frac{P(\\text{wait})}{c \\mu (1 - \\rho)}
    """
    p_wait = _erlang_c_probability(num_workers, rho)
    return p_wait / (num_workers * service_rate * (1.0 - rho))


@dataclass(frozen=True, slots=True)
class MmcQueue:
    """Stateless M/M/c queueing model.

    Attributes:
        arrival_rate: ``lambda`` in tasks/sec; non-negative.
        service_rate: ``mu`` in tasks/sec per worker; strictly positive.
        num_workers: ``c``, the number of parallel servers; ``>= 1``.

    The class is intentionally frozen: callers that need a re-fit
    construct a new :class:`MmcQueue` via :meth:`fit_from_observations`
    rather than mutating the existing instance. This makes the
    router's hot path allocation-friendly (the scorer caches one
    model per pool and replaces it on a fit cadence).

    Req: REQ-001
    """  # req: REQ-001

    arrival_rate: float
    service_rate: float
    num_workers: int

    def __post_init__(self) -> None:
        if not _is_finite(self.arrival_rate) or self.arrival_rate < 0.0:
            raise QueueingModelError(
                f"arrival_rate must be a non-negative finite float, got {self.arrival_rate!r}",
                details={"arrival_rate": self.arrival_rate},
            )
        if not _is_finite(self.service_rate) or self.service_rate <= 0.0:
            raise QueueingModelError(
                f"service_rate must be a strictly positive finite float, got {self.service_rate!r}",
                details={"service_rate": self.service_rate},
            )
        if not isinstance(self.num_workers, int) or self.num_workers < 1:
            raise QueueingModelError(
                f"num_workers must be a positive int, got {self.num_workers!r}",
                details={"num_workers": self.num_workers},
            )

    @property
    def utilization(self) -> float:
        """Return ``rho = lambda / (c * mu)``.

        Raises:
            QueueingModelError: if ``rho >= 1`` (the model is unstable).

        The router uses :meth:`safe_expected_wait_time` instead when
        it cannot tolerate an exception at ``rho >= 1``.
        """
        rho = self.arrival_rate / (self.num_workers * self.service_rate)
        if rho >= 1.0:
            raise QueueingModelError(
                f"utilization rho={rho:.6f} >= 1; M/M/c is unstable; refuse to evaluate",
                details={
                    "arrival_rate": self.arrival_rate,
                    "service_rate": self.service_rate,
                    "num_workers": self.num_workers,
                    "rho": rho,
                },
            )
        return rho

    @classmethod
    def fit_from_observations(
        cls,
        arrivals: Sequence[float],
        services: Sequence[float],
        num_workers: int,
    ) -> "MmcQueue":
        """Fit an :class:`MmcQueue` from observed inter-arrival and service times.

        Args:
            arrivals: ``Sequence[float]`` of inter-arrival *gaps* in
                seconds. Each value is the time between consecutive
                arrivals; ``1 / mean(arrivals)`` is the arrival rate.
            services: ``Sequence[float]`` of service times in seconds;
                ``1 / mean(services)`` is the per-worker service rate.
                Must be the same length as ``arrivals`` (one service
                per arrival).
            num_workers: number of parallel workers in the observed
                system (``c``).

        Returns:
            A fitted :class:`MmcQueue` with the rates computed from the
            means. When the observed service times have zero variance
            (degenerate case) the fit is still valid; the M/M/c
            assumption is violated but the rate estimate is a useful
            lower bound.

        Raises:
            QueueingModelError: if either sequence is empty, if their
                lengths disagree, if any value is NaN/Inf, or if the
                derived rates do not satisfy the MmcQueue invariants
                (``arrival_rate >= 0``, ``service_rate > 0``).
        """
        if not arrivals or not services:
            raise QueueingModelError(
                "fit_from_observations requires non-empty arrivals and services",
                details={"arrivals_len": len(arrivals), "services_len": len(services)},
            )
        if len(arrivals) != len(services):
            raise QueueingModelError(
                f"arrivals and services must have equal length "
                f"(got {len(arrivals)} vs {len(services)})",
                details={"arrivals_len": len(arrivals), "services_len": len(services)},
            )
        for seq, name in ((arrivals, "arrivals"), (services, "services")):
            for idx, value in enumerate(seq):
                if not _is_finite(value) or value < 0.0:
                    raise QueueingModelError(
                        f"{name}[{idx}] must be a non-negative finite float, got {value!r}",
                        details={"index": idx, "value": value, "sequence": name},
                    )

        # statistics.mean raises StatisticsError on empty input. With
        # the empty-input guard above, mean is always defined, but
        # we still wrap in QueueingModelError to satisfy the contract
        # documented in the spec.
        import statistics

        try:
            mean_arrival = statistics.fmean(arrivals)
            mean_service = statistics.fmean(services)
        except statistics.StatisticsError as exc:
            raise QueueingModelError(
                f"fit_from_observations failed to compute means: {exc}",
                details={"arrivals_len": len(arrivals), "services_len": len(services)},
            ) from exc

        if mean_arrival <= 0.0:
            raise QueueingModelError(
                f"mean inter-arrival time must be > 0, got {mean_arrival!r}",
                details={"mean_arrival": mean_arrival},
            )
        if mean_service <= 0.0:
            raise QueueingModelError(
                f"mean service time must be > 0, got {mean_service!r}",
                details={"mean_service": mean_service},
            )

        arrival_rate = 1.0 / mean_arrival
        service_rate = 1.0 / mean_service
        # MmcQueue.__post_init__ validates the rate invariants.
        return cls(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)

    def expected_wait_time(
        self,
        approximation: Literal["kingman", "erlang_c"] = "kingman",
    ) -> float:
        """Return the expected wait-in-queue time ``W_q`` in seconds.

        Args:
            approximation: which formula to use. ``"kingman"`` is the
                default (O(1), tight in heavy traffic) and is the
                spec's mandated default for the router. ``"erlang_c"``
                is the exact M/M/c formula and is preferred for
                small ``c`` (single-worker pools) where Kingman
                over-estimates due to the M/M/1 vs M/M/c asymptotic
                difference.

        Returns:
            Expected wait time ``W_q`` in seconds. ``W_q`` is the
            time a task waits *before* service starts; total time
            in system is ``W_q + 1 / mu``.

        Raises:
            ValueError: if ``approximation`` is not in the allowed set.
            QueueingModelError: if the model is unstable (``rho >= 1``).
        """
        if approximation not in ("kingman", "erlang_c"):
            raise ValueError(
                f"approximation must be 'kingman' or 'erlang_c', got {approximation!r}"
            )
        rho = self.utilization  # raises QueueingModelError if unstable
        if approximation == "kingman":
            return _expected_wait_time_kingman(rho, self.service_rate)
        return _expected_wait_time_erlang_c(self.num_workers, rho, self.service_rate)

    def expected_queue_length(self) -> float:
        """Return the expected number of tasks in the queue ``L_q``.

        Computed by Little's law: ``L_q = lambda * W_q`` (with
        ``W_q`` from the Kingman approximation, the spec's default).
        """
        rho = self.utilization
        w_q = _expected_wait_time_kingman(rho, self.service_rate)
        return self.arrival_rate * w_q

    def expected_number_in_system(self) -> float:
        """Return the expected number of tasks in the system ``L``.

        ``L = lambda * W = lambda * (W_q + 1 / mu) = L_q + lambda / mu``.

        Identical to ``L_q + rho * c`` (the per-system busy-server
        count + queued tasks), which is a useful sanity check at
        small scale.
        """
        l_q = self.expected_queue_length()
        return l_q + (self.arrival_rate / self.service_rate)

    def safe_expected_wait_time(
        self,
        utilization_cap: float = DEFAULT_UTILIZATION_CAP,
        approximation: Literal["kingman", "erlang_c"] = "kingman",
    ) -> float:
        """Return ``W_q`` capped at ``utilization_cap``; ``inf`` past the cap.

        The router calls this method during normal operation: if
        the returned wait time is finite, it uses the value as a
        routing penalty; if ``inf``, it treats the pool as a
        "do not route here" candidate and falls back to the inner
        selector's score.

        Args:
            utilization_cap: maximum ``rho`` at which the model will
                return a finite wait time. Defaults to 0.95 — past
                this, the queue length is large enough that the
                wait-time penalty would dominate the inner selector's
                signal and any small mis-fit compounds. Callers can
                pass a stricter cap (e.g. 0.7) for safety-critical
                workloads.
            approximation: forwarded to :meth:`expected_wait_time`.

        Returns:
            Finite ``W_q`` when ``rho < utilization_cap``; ``math.inf``
            otherwise. The cap check is strictly less-than so a
            model at exactly the cap is treated as at-capacity.
        """
        rho = self.arrival_rate / (self.num_workers * self.service_rate)
        if not math.isfinite(rho) or rho >= utilization_cap:
            return math.inf
        return self.expected_wait_time(approximation=approximation)
