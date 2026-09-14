"""Per-pool queueing observation buffer feeding the M/M/c routing model.

# Implements: REQ-002, REQ-008

The :class:`QueueingObservationBuffer` is the per-pool ring buffer that
holds ``(inter_arrival, service)`` pairs and produces fitted
:class:`~mahavishnu.pools.queueing.mmc.MmcQueue` instances on the
configured warmup cadence. The fitted model is consumed by
:class:`~mahavishnu.pools.manager.PoolManager._apply_queueing_penalty`
to re-rank candidates by predicted wait time.

Round-4 general/safety (HIGH-1): the previous ``QueueingScorer``
additive-penalty wrapper was removed. The production re-ranking
implements full argmin-by-predicted-wait directly in
``_apply_queueing_penalty``; the additive-penalty pattern was not
wired into production and the class was orphaned.

Req: REQ-002, REQ-003 (the persistence extension), REQ-008 (the
arrival-timestamp instrumentation is in route_task, not here, but
the buffer is populated by route_task).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import math
import time

from mahavishnu.pools.queueing.mmc import MmcQueue, QueueingModelError

logger = logging.getLogger(__name__)


# Per-pool observation buffers. Each buffer holds (inter_arrival, service)
# pairs, in seconds, and re-fits the MmcQueue on the warmup cadence.
DEFAULT_WARMUP_MIN_OBSERVATIONS = 100
DEFAULT_WARMUP_MIN_SECONDS = 600.0


def _is_valid_observation(value: float) -> bool:
    """Return True iff ``value`` is a real, positive, finite float."""
    return isinstance(value, float) and math.isfinite(value) and value > 0.0


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

    C7: arrivals are recorded in :meth:`record_arrival` (called from
    :func:`PoolManager._record_arrival`). The (inter_arrival, service)
    pair is appended on task completion via :meth:`complete_observation`,
    using the actual observed service duration. The first arrival is
    recorded but cannot be paired with an inter-arrival delta yet, so
    it is paired on the SECOND arrival's completion (which sees both
    arrival timestamps).
    """

    pool_id: str
    arrivals: deque[float] = field(default_factory=lambda: deque(maxlen=1024))
    services: deque[float] = field(default_factory=lambda: deque(maxlen=1024))
    _pending_arrival_timestamps: deque[float] = field(
        default_factory=lambda: deque(maxlen=64),
        repr=False,
    )
    last_arrival_monotonic: float = 0.0
    last_fit_monotonic: float = 0.0
    min_observations: int = DEFAULT_WARMUP_MIN_OBSERVATIONS
    min_seconds: float = DEFAULT_WARMUP_MIN_SECONDS
    num_workers: int = 1
    fitted_model: MmcQueue | None = None

    def record_arrival(self) -> bool:
        """Mark an arrival timestamp. Returns True if a timestamp was queued.

        The (inter_arrival, service) pair is appended later via
        :meth:`complete_observation` when the task finishes. Arrival
        timestamps are stored in a deque so concurrent arrivals
        (one in flight, one queued) are paired with completions in
        FIFO order.
        """
        now = time.monotonic()
        if self.last_arrival_monotonic > 0.0:
            self._pending_arrival_timestamps.append(now)
            return True
        # First arrival — just stamp the timestamp; the inter-arrival
        # delta will be computable on the next arrival.
        self.last_arrival_monotonic = now
        return False

    def complete_observation(self, service: float) -> bool:
        """Pair the oldest pending arrival with the observed service duration.

        Returns True when a (inter_arrival, service) pair was appended;
        False when there are no arrivals to pair or the service value
        is invalid.

        Concurrency: pops the oldest pending timestamp. If a task
        completes out of arrival order, the inter-arrival delta is
        computed against the prior completed observation's arrival
        timestamp, not the prior arrival's raw timestamp. This is a
        small approximation in pathological cases but is correct for
        the dominant case of one-in-flight per pool.
        """
        if not _is_valid_observation(service):
            return False
        # No pending arrivals yet: the only arrival in flight is the
        # unmarked first arrival (whose timestamp is in
        # last_arrival_monotonic, but with no prior arrival to compute
        # the delta against). Skip this observation.
        if not self._pending_arrival_timestamps:
            # First observation: we have no inter-arrival. Mark that
            # arrival as completed so subsequent arrivals have a
            # baseline; no observation is appended.
            if self.last_arrival_monotonic > 0.0 and len(self.arrivals) == 0:
                # Bootstrap: record last_arrival_monotonic as the
                # arrival time of this (unpaired) observation; no
                # pair is appended because inter-arrival is undefined.
                # The NEXT arrival's delta will use this timestamp.
                return False
            # Otherwise (post-bootstrap) we're missing a queued arrival
            # timestamp — fall back to the same skip.
            return False
        arrival_ts = self._pending_arrival_timestamps.popleft()
        if self.last_arrival_monotonic == 0.0:
            # No prior arrival to compute delta against — skip.
            # This case is rare since record_arrival() sets
            # last_arrival_monotonic on the very first call.
            self.last_arrival_monotonic = arrival_ts
            return False
        inter_arrival = arrival_ts - self.last_arrival_monotonic
        if inter_arrival <= 0.0:
            # Clock skew or two arrivals in the same monotonic tick —
            # record arrival but skip the degenerate pair.
            self.last_arrival_monotonic = arrival_ts
            return False
        self.arrivals.append(inter_arrival)
        self.services.append(service)
        self.last_arrival_monotonic = arrival_ts
        return True

    def append(self, inter_arrival: float, service: float) -> None:
        """Direct append path. Use :meth:`complete_observation` for
        the standard route_task → execute_on_pool flow.

        NaN/Inf are silently dropped. Updates ``last_arrival_monotonic``
        to ``time.monotonic()`` on every successful append so the
        next caller can compute the next inter-arrival delta.
        """
        if not _is_valid_observation(inter_arrival):
            return
        if not _is_valid_observation(service):
            return
        self.arrivals.append(inter_arrival)
        self.services.append(service)
        self.last_arrival_monotonic = time.monotonic()

    def seconds_since_last_arrival(self) -> float:
        """Return wall-clock seconds since the last successful arrival.

        Useful for the caller to detect long idle periods (e.g. a
        cold pool that hasn't seen traffic for the warmup window).
        """
        if self.last_arrival_monotonic == 0.0:
            return 0.0
        return time.monotonic() - self.last_arrival_monotonic

    def ready_to_fit(self) -> bool:
        """True iff the buffer has enough observations to fit an MmcQueue."""
        return len(self.arrivals) >= self.min_observations and len(self.arrivals) == len(
            self.services
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
                list(self.arrivals),
                list(self.services),
                num_workers=self.num_workers,
            )
        except QueueingModelError as exc:
            logger.debug("queueing fit failed for %s: %s", self.pool_id, exc)
            return None
        self.fitted_model = model
        self.last_fit_monotonic = time.monotonic()
        return model


# Round-4 general/safety (HIGH-1): QueueingScorer class was removed.
# The actual production queueing re-ranking lives in
# PoolManager._apply_queueing_penalty. The orphan-abstraction trap
# (built-but-not-wired) is what the wire-up-contract.md policy was
# meant to prevent; carrying the class forward would have left
# operators reading the docstring thinking they could tune
# penalty_weight when in fact production ignores it.


__all__ = [
    "DEFAULT_WARMUP_MIN_OBSERVATIONS",
    "DEFAULT_WARMUP_MIN_SECONDS",
    "QueueingObservationBuffer",
]
