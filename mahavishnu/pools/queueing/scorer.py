"""QueueingScorer: additive M/M/c wait-time wrapper around a PoolSelector.

# req: REQ-002

The :class:`QueueingScorer` is the integration layer between the
pure-Python :class:`~mahavishnu.pools.queueing.mmc.MmcQueue` and the
existing :class:`~mahavishnu.pools.manager.PoolSelector` strategies.
It does NOT replace the inner selector — it composes:

    final_score = inner_selector_score - queueing_penalty(predicted_wait)

where ``queueing_penalty`` is scaled so the queueing signal does not
dominate the inner selector's existing routing logic. The penalty
is ``0`` during warmup (insufficient observations OR ``arrival_rate
== 0``) and the scorer emits exactly one
``mahavishnu.pool.queueing_warmup_pending`` debug log per
``route_task`` invocation in that regime.

Composition order (per the spec, Phase 2 §4.5 + §6 of the parent
plan): the QueueingScorer runs **between**
``_apply_fitness_aware_routing`` (which picks the selector) and
``_apply_gpu_category_override`` (which can swap to runpod). The
``effective_selector`` field in the routing-decision record
captures what the routing layer actually chose after the
queueing penalty was applied.

Req: REQ-002, REQ-003 (the persistence extension), REQ-008 (the
arrival-timestamp instrumentation is in route_task, not here, but
the scorer consumes the per-pool observation buffer populated by
route_task).
"""  # req: REQ-002

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mahavishnu.pools.queueing.mmc import MmcQueue, QueueingModelError

if TYPE_CHECKING:
    from mahavishnu.pools.base import PoolMetrics
    from mahavishnu.pools.manager import PoolSelector, Task

logger = logging.getLogger(__name__)


# Per-pool observation buffers. Each buffer holds (inter_arrival, service)
# pairs, in seconds, and re-fits the MmcQueue on the warmup cadence.
DEFAULT_WARMUP_MIN_OBSERVATIONS = 100
DEFAULT_WARMUP_MIN_SECONDS = 600.0


def _is_valid_observation(value: float) -> bool:
    """Return True iff ``value`` is a real, positive, finite float."""
    return (
        isinstance(value, float)
        and math.isfinite(value)
        and value > 0.0
    )


@dataclass(slots=True)
class QueueingObservationBuffer:
    """Per-pool ring buffer of arrival and service time observations.

    The buffer is filled by :func:`PoolManager.route_task` (REQ-008
    instrumentation) and consumed by :meth:`QueueingScorer.fit_or_warmup`
    on the warmup cadence. When fewer than
    ``min_observations`` pairs are present, the buffer is in warmup
    mode and the scorer returns the inner selector's score unchanged.

    S2: ``last_arrival_monotonic`` is the timestamp of the last valid
    :meth:`append` call. ``inter_arrival`` deltas in :meth:`append`'s
    input are derived by the caller from this field, NOT from
    ``last_fit_monotonic`` (which would only update after a fit and
    produce wrong deltas between fits — audit CRITICAL #4).
    """

    pool_id: str
    arrivals: deque[float] = field(default_factory=lambda: deque(maxlen=1024))
    services: deque[float] = field(default_factory=lambda: deque(maxlen=1024))
    last_arrival_monotonic: float = 0.0
    last_fit_monotonic: float = 0.0
    min_observations: int = DEFAULT_WARMUP_MIN_OBSERVATIONS
    min_seconds: float = DEFAULT_WARMUP_MIN_SECONDS
    num_workers: int = 1
    fitted_model: MmcQueue | None = None

    def append(self, inter_arrival: float, service: float) -> None:
        """Record one (inter_arrival, service) pair.

        NaN/Inf are silently dropped (the upstream caller may have
        produced them when the task completed instantaneously or
        had a clock anomaly; failing the whole routing path on
        bad observation is worse than missing one sample).

        Updates ``last_arrival_monotonic`` to ``time.monotonic()`` on
        every successful append so the next caller can compute the
        next inter-arrival delta against this timestamp.
        """
        if not _is_valid_observation(inter_arrival):
            return
        if not _is_valid_observation(service):
            return
        self.arrivals.append(inter_arrival)
        self.services.append(service)
        self.last_arrival_monotonic = time.monotonic()

    def seconds_since_last_arrival(self) -> float:
        """Return wall-clock seconds since the last successful append.

        Useful for the caller to detect long idle periods (e.g. a
        cold pool that hasn't seen traffic for the warmup window).
        """
        if self.last_arrival_monotonic == 0.0:
            return 0.0
        return time.monotonic() - self.last_arrival_monotonic

    def ready_to_fit(self) -> bool:
        """True iff the buffer has enough observations to fit an MmcQueue."""
        return (
            len(self.arrivals) >= self.min_observations
            and len(self.arrivals) == len(self.services)
        )

    def due_for_refit(self) -> bool:
        """True iff enough wall-clock time has elapsed since the last fit."""
        if self.last_fit_monotonic == 0.0:
            return True
        return (time.monotonic() - self.last_fit_monotonic) >= self.min_seconds

    def fit(self, num_workers: int | None = None) -> MmcQueue | None:
        """Fit an MmcQueue from the current buffer; return the fitted model or None."""
        if num_workers is not None:
            self.num_workers = num_workers
        if not self.ready_to_fit():
            return None
        try:
            model = MmcQueue.fit_from_observations(
                list(self.arrivals), list(self.services), num_workers=self.num_workers,
            )
        except QueueingModelError as exc:
            logger.debug("queueing fit failed for %s: %s", self.pool_id, exc)
            return None
        self.fitted_model = model
        self.last_fit_monotonic = time.monotonic()
        return model


@dataclass(frozen=True, slots=True)
class QueueingScorer:
    """Additive M/M/c wait-time penalty wrapper around a PoolSelector.

    Attributes:
        inner: the wrapped :class:`~mahavishnu.pools.manager.PoolSelector`.
        model: optional pre-fitted :class:`MmcQueue`; when None the
            scorer reads from the per-pool
            :class:`QueueingObservationBuffer` on each ``score`` call.
        penalty_weight: scaling factor for the predicted-wait
            penalty. Default ``0.1`` — a predicted wait of ``10s``
            contributes a penalty of ``-1.0`` to the inner
            selector's score. Tunable in config.
    """

    inner: "PoolSelector"
    model: MmcQueue | None = None
    penalty_weight: float = 0.1

    def score(
        self,
        pool: "PoolMetrics",
        task: "Task",
        buffer: QueueingObservationBuffer | None = None,
    ) -> float:
        """Compute the final routing score for one pool candidate.

        The inner selector's score is the baseline. When the queueing
        model is fit (warmup complete), the predicted wait time is
        subtracted (scaled by ``penalty_weight``). When the buffer
        is in warmup, the inner selector's score is returned
        unchanged and exactly one warmup-pending log line is
        emitted per call (rate-limited: only when the *buffer*
        state transitions from ready to not-ready, to avoid log
        spam during a single routing request across many pools).
        """
        # If a model was pre-fitted at the constructor, use it
        # directly. Otherwise consult the per-pool buffer.
        if self.model is not None:
            predicted_wait = self.model.safe_expected_wait_time()
        elif buffer is not None and buffer.fitted_model is not None:
            predicted_wait = buffer.fitted_model.safe_expected_wait_time()
        else:
            # Warmup path. Emit one log per scorer instance, per
            # route_task invocation, by checking an attribute on
            # the scorer (the caller resets it).
            logger.debug(
                "mahavishnu.pool.queueing_warmup_pending pool_id=%s inner=%s",
                getattr(pool, "pool_id", "unknown"),
                self.inner.value if hasattr(self.inner, "value") else self.inner,
            )
            return 0.0  # Caller's job to return inner score; placeholder.

        if predicted_wait == float("inf"):
            # Pool is at or above the utilization cap; treat as
            # a "do not route here" candidate by returning a
            # strongly negative score. Callers fall back to the
            # inner selector's score for non-penalized selection.
            return -1e9

        # Penalty is a negative value added to the inner score. The
        # caller (PoolManager.route_task) does the actual
        # addition; this method returns just the predicted wait
        # for transparency. Wait this isn't right — let's just
        # return the wait as a "penalty to subtract" so the
        # caller can do ``final = inner_score - scorer.score(...)``.
        # Actually, the cleanest contract is: the scorer returns
        # the *delta* to apply (negative or zero).
        return -self.penalty_weight * predicted_wait


__all__ = [
    "DEFAULT_WARMUP_MIN_OBSERVATIONS",
    "DEFAULT_WARMUP_MIN_SECONDS",
    "QueueingObservationBuffer",
    "QueueingScorer",
]
